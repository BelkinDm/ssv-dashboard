"""Run timers: the "Run 1h / 2h / 3h" buttons on the panels.

1.2: timers are made on purpose. The SSV Dashboard page lists what can have a run
timer — heated walls, floor heating, hot water, recirculation — the installer ticks
them, sets the buttons (minutes) and presses Save; only then the timers are made and
the buttons appear on the panels. Untick + Save removes the timer again. Timers made
by hand are never touched.

  climate.<x> labelled Heated Wall      -> timer.ssv_wall_<x>
  climate / switch.<x> labelled UFH     -> timer.ssv_ufh_<x>
  devices labelled Water + Hot Water    -> timer.ssv_water_hot_water (labelled Water + Hot Water)
  devices labelled Water + Recirculation-> timer.ssv_water_recirculation

1.5: everything SSV makes is called ssv_…; timers left from the INEX Panel days (timer.inex_…)
are replaced by ssv_ ones once, at start (async_migrate_timers).

When a timer finishes, its device is turned off — no automations needed.
"""
from __future__ import annotations

import inspect
import logging

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import TIMER_PREFIXES, WATER_CONTROL_DOMAINS, WATER_FUNCTIONS

_LOGGER = logging.getLogger(__name__)
DEFAULT_RUNS = {"wall": [180], "ufh": [60, 120, 180], "hot_water": [60, 90, 120], "recirculation": [10]}


def _labels(reg: er.EntityRegistry, entity_id: str) -> set[str]:
    ent = reg.async_get(entity_id)
    return set(ent.labels) if ent else set()


def _off(hass: HomeAssistant, eid: str, context) -> None:
    dom = eid.split(".")[0]
    if dom == "climate":
        call = ("climate", "set_hvac_mode", {"entity_id": eid, "hvac_mode": "off"})
    elif dom == "water_heater":
        call = ("water_heater", "turn_off", {"entity_id": eid})
    else:
        call = ("homeassistant", "turn_off", {"entity_id": eid})
    hass.async_create_task(hass.services.async_call(*call, context=context))


@callback
def async_setup_timers(hass: HomeAssistant):
    """Listen for timer.finished and switch the device off. Returns the unsubscribe callback."""

    @callback
    def _finished(event: Event) -> None:
        tid = event.data.get("entity_id") or ""
        if not tid.startswith("timer."):
            return
        obj = tid.split(".", 1)[1]
        for pre in TIMER_PREFIXES:
            for kind in ("wall", "ufh"):
                if obj.startswith(f"{pre}{kind}_"):
                    rest = obj[len(pre) + len(kind) + 1:]
                    for dom in ("climate", "switch"):
                        if hass.states.get(f"{dom}.{rest}") is not None:
                            _LOGGER.info("%s finished: turning %s.%s off", tid, dom, rest)
                            _off(hass, f"{dom}.{rest}", event.context)
                            return
                    return
        reg = er.async_get(hass)
        lab = _labels(reg, tid)
        if "water" not in lab:
            return
        for fn in WATER_FUNCTIONS:
            if fn not in lab:
                continue
            targets = [s.entity_id for s in hass.states.async_all(WATER_CONTROL_DOMAINS)
                       if {"water", fn} <= _labels(reg, s.entity_id)]
            _LOGGER.info("%s finished: turning %s off", tid, targets)
            for eid in targets:
                _off(hass, eid, event.context)

    return hass.bus.async_listen("timer.finished", _finished)


# ---------------------------------------------------------------- what can have a run timer
@callback
def async_candidates(hass: HomeAssistant, store) -> list[dict]:
    """Everything that can get a run timer, with what is chosen for it now."""
    reg = er.async_get(hass)
    out: list[dict] = []

    def name_of(eid: str) -> str:
        st = hass.states.get(eid)
        return (st and st.attributes.get("friendly_name")) or eid

    for ent in sorted(reg.entities.values(), key=lambda e: e.entity_id):
        labels = set(ent.labels or set())
        if ent.domain == "climate" and "heated_wall" in labels:
            kind, tid = "wall", f"ssv_wall_{ent.entity_id.split('.', 1)[1]}"
        elif ent.domain in ("climate", "switch") and "ufh" in labels and "no_panel" not in labels:
            kind, tid = "ufh", f"ssv_ufh_{ent.entity_id.split('.', 1)[1]}"
        else:
            continue
        out.append({"key": ent.entity_id, "kind": kind, "name": name_of(ent.entity_id), "timer": f"timer.{tid}"})
    for fn in WATER_FUNCTIONS:
        devs = [e.entity_id for e in reg.entities.values()
                if {"water", fn} <= set(e.labels or set()) and e.domain in WATER_CONTROL_DOMAINS]
        if devs:
            out.append({"key": f"fn:{fn}", "kind": fn, "name": {"hot_water": "Hot Water", "recirculation": "Recirculation"}[fn],
                        "devices": devs, "timer": f"timer.ssv_water_{fn}"})
    for c in out:
        chosen = store.timers.get(c["key"])
        c["chosen"] = chosen is not None
        c["new"] = c["key"] not in store.seen
        c["runs"] = (chosen or {}).get("runs") or DEFAULT_RUNS[c["kind"]]
        c["exists"] = hass.states.get(c["timer"]) is not None
    return out


def _timer_collection(hass: HomeAssistant):
    """The timer helpers' storage collection (the same one the HA UI uses), or None."""
    handler = (hass.data.get("websocket_api") or {}).get("timer/create")
    if not handler:
        return None
    owner = getattr(inspect.unwrap(handler[0]), "__self__", None)
    return getattr(owner, "storage_collection", None)


def _fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}:00"


def _secs(value) -> int:
    try:
        h, m, s = (int(float(x)) for x in str(value).split(":"))
        return h * 3600 + m * 60 + s
    except (TypeError, ValueError):
        return -1


async def async_migrate_timers(hass: HomeAssistant, store) -> list[str]:
    """Replace timer helpers named inex_… (made by INEX Panel / SSV before 1.5) with ssv_… ones.

    Only timers in the UI timer list are touched (YAML timers cannot be changed). The new timer gets the
    same duration and labels; a timer that is running at that moment is left until the next start."""
    coll = _timer_collection(hass)
    if coll is None:
        return []
    reg = er.async_get(hass)
    have = {item["id"]: item for item in coll.async_items()}
    done: list[str] = []
    for old_id, item in list(have.items()):
        if not str(old_id).startswith("inex_"):
            continue
        new_id = "ssv_" + old_id[len("inex_"):]
        old_eid = reg.async_get_entity_id("timer", "timer", old_id)
        st = hass.states.get(old_eid) if old_eid else None
        if st is not None and st.state != "idle":
            continue  # running now — next start
        labels = set((reg.async_get(old_eid).labels if old_eid and reg.async_get(old_eid) else ()) or ())
        if new_id not in have:
            await coll.async_create_item({"name": new_id, "duration": item.get("duration") or "01:00:00", "restore": bool(item.get("restore", True))})
            new_eid = reg.async_get_entity_id("timer", "timer", new_id)
            if new_eid and labels:
                reg.async_update_entity(new_eid, labels=labels)
        await coll.async_delete_item(old_id)
        if old_id in store.managed_timers:
            store.managed_timers.remove(old_id)
            if new_id not in store.managed_timers:
                store.managed_timers.append(new_id)
        done.append(f"timer.{old_id} → timer.{new_id}")
    if done:
        store.async_save()
        _LOGGER.info("Timers renamed: %s", ", ".join(done))
    return done


async def async_apply_timers(hass: HomeAssistant, store) -> list[str]:
    """Make the timers chosen on the page and remove ours that are no longer chosen."""
    coll = _timer_collection(hass)
    if coll is None:
        raise RuntimeError("Timer helpers are not loaded — add 'timer:' or default_config")
    reg = er.async_get(hass)
    cands = {c["key"]: c for c in async_candidates(hass, store)}
    want: dict[str, dict] = {}
    for key, cfg in store.timers.items():
        c = cands.get(key)
        if not c:
            continue
        obj = c["timer"].split(".", 1)[1]
        labels = {"water", c["kind"]} if key.startswith("fn:") else set()
        want[obj] = {"duration": _fmt(max(cfg.get("runs") or DEFAULT_RUNS[c["kind"]])), "labels": labels}

    changes: list[str] = []
    have = {item["id"]: item for item in coll.async_items()}
    for obj, spec in want.items():
        if obj in have:
            if obj in store.managed_timers and _secs(have[obj].get("duration")) != _secs(spec["duration"]):
                await coll.async_update_item(obj, {"name": obj, "duration": spec["duration"], "restore": True})
            continue
        if hass.states.get(f"timer.{obj}") is not None:
            continue  # made by hand (YAML) — use it as it is
        await coll.async_create_item({"name": obj, "duration": spec["duration"], "restore": True})
        if obj not in store.managed_timers:
            store.managed_timers.append(obj)
        changes.append(f"+timer.{obj}")
        if spec["labels"]:
            eid = reg.async_get_entity_id("timer", "timer", obj)
            if eid:
                reg.async_update_entity(eid, labels=spec["labels"])
    for obj in list(store.managed_timers):
        if obj in want:
            continue
        if obj in have:
            await coll.async_delete_item(obj)
            changes.append(f"-timer.{obj}")
        store.managed_timers.remove(obj)
    store.async_save()
    if changes:
        _LOGGER.info("Run timers: %s", ", ".join(changes))
    return changes
