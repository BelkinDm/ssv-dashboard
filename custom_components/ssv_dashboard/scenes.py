"""User scenes — made by the people who live in the house, on the wall panels and phones.

Panel users are not administrators, so they cannot use Home Assistant's scene
editor. These services can be called by anyone signed in:
  ssv_dashboard.save_scene    create / update a user scene   (returns entity_id)
  ssv_dashboard.get_scene     read a user scene's states     (returns entities, timing, panels, home)
  ssv_dashboard.delete_scene  delete a user scene
  ssv_dashboard.run_scene     run any scene; a user scene runs with its own timing:
                              each device can start later ("delay", seconds) and go back after
                              "back" minutes to what it was before or to off ("back_to")
Where a scene is shown is set with labels, chosen in the editor with check boxes (the owner
never opens Home Assistant's settings): Panel <Name> for each panel, Home for the Home page of
the 10″ panels. No Panel <Name> label = the scene is on every panel.
Safety:
  * only entities labelled "scene_device" can be used, and only with values the
    device itself reports as valid (hvac modes, fan modes, min/max temperature,
    brightness, position ...);
  * only scenes whose id starts with "ssv_user_" (or the older "inex_user_")
    can be changed or deleted — scenes made by the installer are never touched;
  * a user changes or deletes only the scenes they made; administrators can
    change all of them;
  * scenes.yaml is written atomically, with a copy kept as scenes.yaml.ssv_bak.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import uuid

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er, label_registry as lr
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.util.file import write_utf8_file_atomic
from homeassistant.util.yaml import dump, load_yaml

from .const import (
    DEVICE_LABEL,
    DOMAIN,
    ID_PREFIX,
    LEGACY_PREFIXES,
    MAX_ENTITIES,
    MAX_SCENES,
    SCENE_LABELS,
    SCENES_FILE,
    STORE_KEY,
    STORE_VERSION,
)

_LOGGER = logging.getLogger(__name__)
_LOCK = asyncio.Lock()
SERVICES = ("save_scene", "get_scene", "delete_scene", "run_scene")
TIMING_SCHEMA = vol.Schema({
    vol.Optional("delay", default=0): vol.All(vol.Coerce(int), vol.Range(0, 24 * 3600)),
    vol.Optional("back", default=0): vol.All(vol.Coerce(int), vol.Range(0, 24 * 60)),
    vol.Optional("back_to", default="previous"): vol.In(("previous", "off")),
})

ALLOWED_DOMAINS = {"light", "switch", "climate", "cover", "fan", "input_boolean"}

SAVE_SCHEMA = vol.Schema({
    vol.Required("name"): vol.All(str, vol.Strip, vol.Length(min=1, max=40)),
    vol.Required("entities"): vol.All(dict, vol.Length(min=1, max=MAX_ENTITIES)),
    vol.Optional("icon"): vol.Any(None, vol.Match(r"^mdi:[a-z0-9-]{1,60}$")),
    vol.Optional("scene"): vol.Any(None, str),
    vol.Optional("timing"): vol.Any(None, {str: TIMING_SCHEMA}),
    vol.Optional("panels"): vol.Any(None, [vol.Match(r"^[a-z0-9][a-z0-9_]{0,40}$")]),
    vol.Optional("home"): vol.Any(None, bool),
})
RUN_SCHEMA = vol.Schema({vol.Required("entity_id"): vol.Match(r"^scene\.[a-z0-9_]+$")})
ONE_SCHEMA = vol.Schema({vol.Required("scene"): str})


def _num(v, lo, hi, what):
    try:
        x = float(v)
    except (TypeError, ValueError) as err:
        raise ServiceValidationError(f"{what}: not a number") from err
    if lo is not None and x < float(lo) - 1e-6 or hi is not None and x > float(hi) + 1e-6:
        raise ServiceValidationError(f"{what}: {x} is outside {lo}..{hi}")
    return x


def _pick(v, options, what):
    if v not in (options or []):
        raise ServiceValidationError(f"{what}: '{v}' is not one of {options}")
    return v


def _clean(hass: HomeAssistant, eid: str, want) -> dict:
    """Return a scene state for one entity, keeping only values the device supports."""
    st = hass.states.get(eid)
    if st is None:
        raise ServiceValidationError(f"{eid} does not exist")
    dom = eid.split(".")[0]
    if dom not in ALLOWED_DOMAINS:
        raise ServiceValidationError(f"{eid}: this kind of device cannot be in a scene")
    ent = er.async_get(hass).async_get(eid)
    if ent is None or DEVICE_LABEL not in (ent.labels or set()):
        raise ServiceValidationError(f"{eid} is not allowed in scenes (label '{DEVICE_LABEL}' missing)")
    if not isinstance(want, dict):
        raise ServiceValidationError(f"{eid}: settings must be an object")
    a = st.attributes
    out: dict = {}
    if dom in ("light", "switch", "fan", "input_boolean"):
        out["state"] = _pick(want.get("state"), ["on", "off"], f"{eid} state")
        if dom == "light" and out["state"] == "on":
            modes = a.get("supported_color_modes") or []
            if "brightness" in want and any(m != "onoff" for m in modes):
                out["brightness"] = int(round(_num(want["brightness"], 1, 255, f"{eid} brightness")))
            if "color_temp_kelvin" in want and "color_temp" in modes:
                out["color_temp_kelvin"] = int(round(_num(want["color_temp_kelvin"], a.get("min_color_temp_kelvin", 2000), a.get("max_color_temp_kelvin", 6500), f"{eid} colour temperature")))
        if dom == "fan" and out["state"] == "on" and "percentage" in want and want["percentage"] is not None:
            out["percentage"] = int(round(_num(want["percentage"], 0, 100, f"{eid} speed")))
    elif dom == "climate":
        out["state"] = _pick(want.get("state"), a.get("hvac_modes") or [], f"{eid} mode")
        if out["state"] != "off":
            if "temperature" in want:
                t = _num(want["temperature"], a.get("min_temp", 5), a.get("max_temp", 35), f"{eid} temperature")
                step = float(a.get("target_temp_step") or 0.5)
                out["temperature"] = round(round(t / step) * step, 2)
            for key, opts in (("fan_mode", "fan_modes"), ("swing_mode", "swing_modes"), ("preset_mode", "preset_modes")):
                if key in want and want[key] is not None:
                    out[key] = _pick(want[key], a.get(opts) or [], f"{eid} {key}")
    elif dom == "cover":
        if "current_position" in want:
            p = int(round(_num(want["current_position"], 0, 100, f"{eid} position")))
            out["current_position"] = p
            out["state"] = "closed" if p == 0 else "open"
        else:
            out["state"] = _pick(want.get("state"), ["open", "closed"], f"{eid} state")
    return out


def _read(path: str) -> list:
    if not os.path.exists(path):
        return []
    data = load_yaml(path)
    if data is None:
        return []
    if not isinstance(data, list):
        raise HomeAssistantError("scenes.yaml is not a list — not touching it")
    return data


def _write(path: str, data: list) -> None:
    if os.path.exists(path):
        shutil.copyfile(path, path + ".ssv_bak")
    write_utf8_file_atomic(path, dump(data) if data else "[]\n")


def _scene_id(hass: HomeAssistant, entity_id: str) -> str:
    ent = er.async_get(hass).async_get(entity_id)
    if ent is None or ent.platform != "homeassistant" or not str(ent.unique_id).startswith((ID_PREFIX, *LEGACY_PREFIXES)):
        raise ServiceValidationError(f"{entity_id} is not a user scene and cannot be changed here")
    return str(ent.unique_id)


def _panel_ids(hass: HomeAssistant) -> set[str]:
    st = hass.data.get(DOMAIN, {}).get("panels")
    return set(st.panels) if st else set()


def _place_labels(hass: HomeAssistant, labels: set[str], panels: list | None, home: bool | None) -> set[str]:
    """Labels of a scene after the "show on" check boxes: Panel <Name> per panel, Home for the 10″ Home page."""
    out = set(labels)
    if panels is not None:
        known = _panel_ids(hass)
        out -= {f"panel_{p}" for p in known}
        lreg = lr.async_get(hass)
        for p in panels:
            if p in known and lreg.async_get_label(f"panel_{p}"):
                out.add(f"panel_{p}")
    if home is not None:
        out.discard("home")
        if home:
            out.add("home")
    return out


def _snap(hass: HomeAssistant, eid: str) -> dict | None:
    """What a device is doing now, as a scene state (to go back to it later)."""
    st = hass.states.get(eid)
    if st is None or st.state in ("unavailable", "unknown"):
        return None
    a, dom = st.attributes, eid.split(".")[0]
    if dom == "climate":
        out = {"state": st.state}
        if st.state != "off":
            for k in ("temperature", "fan_mode", "swing_mode", "preset_mode"):
                if a.get(k) is not None:
                    out[k] = a[k]
        return out
    if dom == "cover":
        if a.get("current_position") is not None:
            return {"state": "closed" if a["current_position"] == 0 else "open", "current_position": a["current_position"]}
        return {"state": "closed" if st.state == "closed" else "open"}
    out = {"state": "on" if st.state == "on" else "off"}
    if dom == "light" and out["state"] == "on":
        if a.get("brightness") is not None:
            out["brightness"] = a["brightness"]
        if a.get("color_mode") == "color_temp" and a.get("color_temp_kelvin") is not None:
            out["color_temp_kelvin"] = a["color_temp_kelvin"]
    if dom == "fan" and out["state"] == "on" and a.get("percentage") is not None:
        out["percentage"] = a["percentage"]
    return out


def _off_state(eid: str) -> dict:
    dom = eid.split(".")[0]
    if dom == "climate":
        return {"state": "off"}
    if dom == "cover":
        return {"state": "closed", "current_position": 0}
    return {"state": "off"}


async def _reload_and_label(hass: HomeAssistant, sid: str | None, panels: list | None = None, home: bool | None = None) -> str | None:
    await hass.services.async_call("scene", "reload", blocking=True)
    if not sid:
        return None
    reg = er.async_get(hass)
    for _ in range(20):
        eid = reg.async_get_entity_id("scene", "homeassistant", sid)
        if eid:
            ent = reg.async_get(eid)
            labels = _place_labels(hass, set(ent.labels or set()) | set(SCENE_LABELS), panels, home)
            if labels != set(ent.labels or set()):
                reg.async_update_entity(eid, labels=labels)
            return eid
        await asyncio.sleep(0.25)
    return None



async def _can_edit(hass: HomeAssistant, call: ServiceCall, owners: dict, sid: str) -> None:
    """A user edits only their own scenes; admins edit all; legacy scenes without an owner are open."""
    uid = call.context.user_id
    if uid is None:
        return  # called by Home Assistant itself (automation, script)
    user = await hass.auth.async_get_user(uid)
    if user is not None and user.is_admin:
        return
    owner = owners.get(sid)
    if owner and owner != uid:
        raise ServiceValidationError("This scene was made by another user and can only be changed by them")


async def async_setup_scenes(hass: HomeAssistant) -> None:
    path = hass.config.path(SCENES_FILE)
    store: Store = Store(hass, STORE_VERSION, STORE_KEY)
    saved = await store.async_load() or {}
    owners: dict = saved.get("owners", {})
    timing: dict = saved.get("timing", {})   # scene id -> {entity_id: {delay, back, back_to}}
    runs: dict = {}                          # scene id -> [cancel callbacks] of a running scene

    def _persist() -> None:
        store.async_delay_save(lambda: {"owners": owners, "timing": timing}, 1)

    # 1.5: scenes made before (id inex_user_…) get the id ssv_user_…; the scene entity keeps its name and labels
    async with _LOCK:
        try:
            data = await hass.async_add_executor_job(_read, path)
        except HomeAssistantError:
            data = []
        reg = er.async_get(hass)
        moved = []
        for item in data:
            sid = str(item.get("id", "")) if isinstance(item, dict) else ""
            pre = next((p for p in LEGACY_PREFIXES if sid.startswith(p)), None)
            if not pre:
                continue
            new = ID_PREFIX + sid[len(pre):]
            eid = reg.async_get_entity_id("scene", "homeassistant", sid)
            if eid and not reg.async_get_entity_id("scene", "homeassistant", new):
                reg.async_update_entity(eid, new_unique_id=new)
            item["id"] = new
            for d in (owners, timing):
                if sid in d:
                    d[new] = d.pop(sid)
            moved.append(new)
        if moved:
            await hass.async_add_executor_job(_write, path, data)
            _persist()
            if hass.services.has_service("scene", "reload"):
                await hass.services.async_call("scene", "reload", blocking=True)
            _LOGGER.info("User scenes renamed to ssv_user_: %s", ", ".join(moved))


    async def save(call: ServiceCall) -> ServiceResponse:
        d = SAVE_SCHEMA(dict(call.data))
        ents = {eid: _clean(hass, eid, v) for eid, v in d["entities"].items()}
        tim = {eid: t for eid, t in (d.get("timing") or {}).items() if eid in ents and (t["delay"] or t["back"])}
        async with _LOCK:
            data = await hass.async_add_executor_job(_read, path)
            sid = _scene_id(hass, d["scene"]) if d.get("scene") else None
            if sid:
                await _can_edit(hass, call, owners, sid)
            user = [s for s in data if isinstance(s, dict) and str(s.get("id", "")).startswith((ID_PREFIX, *LEGACY_PREFIXES))]
            if not sid and len(user) >= MAX_SCENES:
                raise ServiceValidationError(f"Too many scenes (max {MAX_SCENES}) — delete one first")
            item = {"id": sid or ID_PREFIX + uuid.uuid4().hex[:10], "name": d["name"], "entities": ents}
            if d.get("icon"):
                item["icon"] = d["icon"]
            if sid:
                idx = next((i for i, s in enumerate(data) if isinstance(s, dict) and s.get("id") == sid), None)
                if idx is None:
                    raise ServiceValidationError("This scene is no longer stored")
                data[idx] = item
            else:
                data.append(item)
                if call.context.user_id:
                    owners[item["id"]] = call.context.user_id
                    _persist()
            if d.get("timing") is not None or sid:
                if tim:
                    timing[item["id"]] = tim
                else:
                    timing.pop(item["id"], None)
                _persist()
            await hass.async_add_executor_job(_write, path, data)
            eid = await _reload_and_label(hass, item["id"], d.get("panels"), d.get("home"))
        _LOGGER.info("User scene %s saved by %s", item["name"], call.context.user_id)
        return {"entity_id": eid, "id": item["id"]}

    async def get(call: ServiceCall) -> ServiceResponse:
        d = ONE_SCHEMA(dict(call.data))
        sid = _scene_id(hass, d["scene"])
        data = await hass.async_add_executor_job(_read, path)
        s = next((x for x in data if isinstance(x, dict) and x.get("id") == sid), None)
        if s is None:
            raise ServiceValidationError("This scene is no longer stored")
        ent = er.async_get(hass).async_get(d["scene"])
        labels = set(ent.labels or set()) if ent else set()
        panels = sorted(p for p in _panel_ids(hass) if f"panel_{p}" in labels)
        return {"name": s.get("name"), "icon": s.get("icon"), "entities": s.get("entities") or {},
                "timing": timing.get(sid, {}), "panels": panels, "home": "home" in labels}

    async def delete(call: ServiceCall) -> ServiceResponse:
        d = ONE_SCHEMA(dict(call.data))
        sid = _scene_id(hass, d["scene"])
        await _can_edit(hass, call, owners, sid)
        async with _LOCK:
            data = await hass.async_add_executor_job(_read, path)
            new = [s for s in data if not (isinstance(s, dict) and s.get("id") == sid)]
            if len(new) != len(data):
                await hass.async_add_executor_job(_write, path, new)
            await _reload_and_label(hass, None)
            reg = er.async_get(hass)
            eid = reg.async_get_entity_id("scene", "homeassistant", sid)
            if eid:
                reg.async_remove(eid)
            owners.pop(sid, None)
            timing.pop(sid, None)
            _persist()
        _LOGGER.info("User scene %s deleted by %s", d["scene"], call.context.user_id)
        return {"deleted": d["scene"]}

    async def _apply(eid: str, state: dict) -> None:
        try:
            await hass.services.async_call("scene", "apply", {"entities": {eid: state}}, blocking=True)
        except Exception as err:  # noqa: BLE001 — one device failing must not stop the others
            _LOGGER.warning("Scene step for %s failed: %s", eid, err)

    async def run(call: ServiceCall) -> ServiceResponse:
        """Run a scene. A user scene with timing: each device on its own clock; running it again restarts it."""
        d = RUN_SCHEMA(dict(call.data))
        ent = er.async_get(hass).async_get(d["entity_id"])
        sid = str(ent.unique_id) if ent and ent.platform == "homeassistant" else None
        tim = timing.get(sid) if sid else None
        if not tim:
            await hass.services.async_call("scene", "turn_on", {"entity_id": d["entity_id"]}, blocking=True, context=call.context)
            return {"timed": False}
        data = await hass.async_add_executor_job(_read, path)
        item = next((x for x in data if isinstance(x, dict) and x.get("id") == sid), None)
        if item is None:
            raise ServiceValidationError("This scene is no longer stored")
        for cancel in runs.pop(sid, []):
            cancel()
        handles: list = []
        runs[sid] = handles
        now: dict = {}

        def _later(seconds: float, job) -> None:
            @callback
            def _fire(_now) -> None:
                hass.async_create_task(job())
            handles.append(async_call_later(hass, seconds, _fire))

        for eid, want in (item.get("entities") or {}).items():
            t = tim.get(eid) or {}
            delay, back, back_to = int(t.get("delay", 0)), int(t.get("back", 0)), t.get("back_to", "previous")

            async def step(eid=eid, want=want, back=back, back_to=back_to) -> None:
                before = _snap(hass, eid)
                await _apply(eid, want)
                if back:
                    target = _off_state(eid) if back_to == "off" or before is None else before
                    _later(back * 60, lambda: _apply(eid, target))

            if delay:
                _later(delay, step)
            elif back:
                await step()
            else:
                now[eid] = want
        if now:
            await hass.services.async_call("scene", "apply", {"entities": now}, blocking=True, context=call.context)
        return {"timed": True}

    hass.services.async_register(DOMAIN, "run_scene", run, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "save_scene", save, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "get_scene", get, supports_response=SupportsResponse.ONLY)
    hass.services.async_register(DOMAIN, "delete_scene", delete, supports_response=SupportsResponse.OPTIONAL)


def async_unload_scenes(hass: HomeAssistant) -> None:
    for s in SERVICES:
        hass.services.async_remove(DOMAIN, s)
