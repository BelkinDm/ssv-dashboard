"""Run-for-a-while buttons: turn things off when their timer ends.

The panels start a timer when someone presses "Run 3h" on a heated wall or
"Run 1h" on hot water. When that timer finishes, this turns the device off —
so no automations have to be written by hand on each site.

  timer.inex_wall_<id> / timer.ssv_wall_<id>  → climate.<id> set to off
  timer labelled "water" + "hot_water"        → everything labelled water + hot_water off
  timer labelled "water" + "recirculation"    → everything labelled water + recirculation off
"""
from __future__ import annotations

import logging

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import TIMER_PREFIXES, WATER_CONTROL_DOMAINS, WATER_FUNCTIONS

_LOGGER = logging.getLogger(__name__)


def _labels(reg: er.EntityRegistry, entity_id: str) -> set[str]:
    ent = reg.async_get(entity_id)
    return set(ent.labels) if ent else set()


@callback
def async_setup_timers(hass: HomeAssistant):
    """Listen for timer.finished. Returns the unsubscribe callback."""

    @callback
    def _finished(event: Event) -> None:
        tid = event.data.get("entity_id") or ""
        if not tid.startswith("timer."):
            return
        obj = tid.split(".", 1)[1]
        for pre in TIMER_PREFIXES:
            if obj.startswith(pre + "wall_"):
                climate = "climate." + obj[len(pre) + 5:]
                if hass.states.get(climate) is not None:
                    _LOGGER.info("%s finished: turning %s off", tid, climate)
                    hass.async_create_task(hass.services.async_call(
                        "climate", "set_hvac_mode", {"entity_id": climate, "hvac_mode": "off"}, context=event.context))
                return
        reg = er.async_get(hass)
        lab = _labels(reg, tid)
        if "water" not in lab:
            return
        for fn in WATER_FUNCTIONS:
            if fn not in lab:
                continue
            targets = [
                s.entity_id for s in hass.states.async_all(WATER_CONTROL_DOMAINS)
                if {"water", fn} <= _labels(reg, s.entity_id)
            ]
            _LOGGER.info("%s finished: turning %s off", tid, targets)
            for eid in targets:
                dom = eid.split(".")[0]
                svc = ("water_heater", "turn_off") if dom == "water_heater" else ("homeassistant", "turn_off")
                hass.async_create_task(hass.services.async_call(svc[0], svc[1], {"entity_id": eid}, context=event.context))

    return hass.bus.async_listen("timer.finished", _finished)


# ---------------------------------------------------------------- 1.1: timers made by themselves
# Every climate labelled Heated Wall gets timer.inex_wall_<object id>; every water function
# (devices labelled Water + Hot Water / Recirculation) gets one timer labelled the same.
# Timers made here are remembered; when the label goes, the timer goes. Timers made by
# hand are never touched.

def _timer_collection(hass: HomeAssistant):
    """The timer helpers' storage collection (the same one the UI uses), or None."""
    import inspect

    handler = (hass.data.get("websocket_api") or {}).get("timer/create")
    if not handler:
        return None
    fn = inspect.unwrap(handler[0])
    owner = getattr(fn, "__self__", None)
    return getattr(owner, "storage_collection", None)


def _fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}:00"


async def async_sync_timers(hass: HomeAssistant, store) -> list[str]:
    """Create missing run timers and remove ones whose device lost its label. Returns changes."""
    coll = _timer_collection(hass)
    if coll is None:
        _LOGGER.debug("timer helpers not loaded yet")
        return []
    reg = er.async_get(hass)
    changes: list[str] = []
    want: dict[str, dict] = {}
    for ent in list(reg.entities.values()):
        if ent.domain == "climate" and "heated_wall" in (ent.labels or set()):
            obj = ent.entity_id.split(".", 1)[1]
            want[f"inex_wall_{obj}"] = {"duration": _fmt(store.runs.get("per", {}).get(ent.entity_id) or store.runs.get("wall", 180)), "labels": set()}
    for fn in WATER_FUNCTIONS:
        devs = [e for e in reg.entities.values() if {"water", fn} <= set(e.labels or set()) and e.domain in WATER_CONTROL_DOMAINS]
        timers = [e for e in reg.entities.values() if e.domain == "timer" and {"water", fn} <= set(e.labels or set())]
        if devs and (not timers or any(t.entity_id == f"timer.inex_water_{fn}" for t in timers)):
            want[f"inex_water_{fn}"] = {"duration": "01:00:00", "labels": {"water", fn}}

    have = {item["id"]: item for item in coll.async_items()}
    for tid, spec in want.items():
        if tid in have or hass.states.get(f"timer.{tid}") is not None:
            continue
        try:
            await coll.async_create_item({"name": tid, "duration": spec["duration"], "restore": True})
        except Exception as err:  # noqa: BLE001 — a name clash must not stop the others
            _LOGGER.warning("Run timer %s not created: %s", tid, err)
            continue
        if tid not in store.managed_timers:
            store.managed_timers.append(tid)
        changes.append(f"+timer.{tid}")
        if spec["labels"]:
            eid = reg.async_get_entity_id("timer", "timer", tid)
            if eid:
                reg.async_update_entity(eid, labels=spec["labels"])
    for tid in list(store.managed_timers):
        if tid in want:
            continue
        if tid in have:
            try:
                await coll.async_delete_item(tid)
                changes.append(f"-timer.{tid}")
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Run timer %s not removed: %s", tid, err)
                continue
        store.managed_timers.remove(tid)
    if changes:
        store.async_save()
        _LOGGER.info("Run timers: %s", ", ".join(changes))
    return changes


@callback
def async_track_timer_labels(hass: HomeAssistant, store):
    """Re-sync after labels change (debounced). Returns the unsubscribe callback."""
    from homeassistant.helpers.event import async_call_later

    pending: dict = {"cancel": None}

    @callback
    def _later(_now=None) -> None:
        pending["cancel"] = None
        hass.async_create_task(async_sync_timers(hass, store))

    @callback
    def _changed(event: Event) -> None:
        if event.data.get("action") == "update" and "labels" not in (event.data.get("changes") or {}):
            return
        if pending["cancel"]:
            pending["cancel"]()
        pending["cancel"] = async_call_later(hass, 5, _later)

    unsub = hass.bus.async_listen("entity_registry_updated", _changed)

    def _stop() -> None:
        unsub()
        if pending["cancel"]:
            pending["cancel"]()

    return _stop
