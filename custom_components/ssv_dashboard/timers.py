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
