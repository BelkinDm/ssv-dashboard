"""User scenes — made by guests on the wall panels and phones.

Panel users are not administrators, so they cannot use Home Assistant's scene
editor. These services can be called by anyone signed in:
  ssv_dashboard.save_scene    create / update a user scene   (returns entity_id)
  ssv_dashboard.get_scene     read a user scene's states     (returns entities)
  ssv_dashboard.delete_scene  delete a user scene
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

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
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
SERVICES = ("save_scene", "get_scene", "delete_scene")

ALLOWED_DOMAINS = {"light", "switch", "climate", "cover", "fan", "input_boolean"}

SAVE_SCHEMA = vol.Schema({
    vol.Required("name"): vol.All(str, vol.Strip, vol.Length(min=1, max=40)),
    vol.Required("entities"): vol.All(dict, vol.Length(min=1, max=MAX_ENTITIES)),
    vol.Optional("icon"): vol.Any(None, vol.Match(r"^mdi:[a-z0-9-]{1,60}$")),
    vol.Optional("scene"): vol.Any(None, str),
})
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
        if dom == "fan" and out["state"] == "on" and "percentage" in want:
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


async def _reload_and_label(hass: HomeAssistant, sid: str | None) -> str | None:
    await hass.services.async_call("scene", "reload", blocking=True)
    if not sid:
        return None
    reg = er.async_get(hass)
    for _ in range(20):
        eid = reg.async_get_entity_id("scene", "homeassistant", sid)
        if eid:
            ent = reg.async_get(eid)
            labels = set(ent.labels or set()) | set(SCENE_LABELS)
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
    owners: dict = (await store.async_load() or {}).get("owners", {})

    def _persist() -> None:
        store.async_delay_save(lambda: {"owners": owners}, 1)

    async def save(call: ServiceCall) -> ServiceResponse:
        d = SAVE_SCHEMA(dict(call.data))
        ents = {eid: _clean(hass, eid, v) for eid, v in d["entities"].items()}
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
            await hass.async_add_executor_job(_write, path, data)
            eid = await _reload_and_label(hass, item["id"])
        _LOGGER.info("User scene %s saved by %s", item["name"], call.context.user_id)
        return {"entity_id": eid, "id": item["id"]}

    async def get(call: ServiceCall) -> ServiceResponse:
        d = ONE_SCHEMA(dict(call.data))
        sid = _scene_id(hass, d["scene"])
        data = await hass.async_add_executor_job(_read, path)
        s = next((x for x in data if isinstance(x, dict) and x.get("id") == sid), None)
        if s is None:
            raise ServiceValidationError("This scene is no longer stored")
        return {"name": s.get("name"), "icon": s.get("icon"), "entities": s.get("entities") or {}}

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
            if owners.pop(sid, None):
                _persist()
        _LOGGER.info("User scene %s deleted by %s", d["scene"], call.context.user_id)
        return {"deleted": d["scene"]}

    hass.services.async_register(DOMAIN, "save_scene", save, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "get_scene", get, supports_response=SupportsResponse.ONLY)
    hass.services.async_register(DOMAIN, "delete_scene", delete, supports_response=SupportsResponse.OPTIONAL)


def async_unload_scenes(hass: HomeAssistant) -> None:
    for s in SERVICES:
        hass.services.async_remove(DOMAIN, s)
