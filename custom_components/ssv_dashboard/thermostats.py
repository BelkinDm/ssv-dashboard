"""Floor heating on a relay (switch) — a valve or a contactor instead of a climate device.

The panels show such a relay as floor heating (label UFH): On / Off and Run buttons, no set point.
When the same room has a temperature sensor (label Temperature Humidity), the SSV Dashboard page
offers "Make thermostat": SSV creates Home Assistant's own Generic Thermostat (relay + sensor), so
the set point, the room temperature, schedules and Run timers work as with any floor heating, and the
thermostat keeps working without SSV. The new climate gets the relay's area and labels plus
Climate + UFH; the relay gets No Panel so the panel does not show it twice.

Defaults (change them later in the thermostat's options): 16–28 °C, hysteresis 0.3 °C,
at least 5 minutes between valve switchings (thermal actuators take minutes to open).
"""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er

from .const import DOMAIN
from .labels import ensure_label

_LOGGER = logging.getLogger(__name__)
GT = "generic_thermostat"
DEFAULTS = {
    "ac_mode": False,
    "cold_tolerance": 0.3,
    "hot_tolerance": 0.3,
    "min_cycle_duration": {"hours": 0, "minutes": 5, "seconds": 0},
    "min_temp": 16.0,
    "max_temp": 28.0,
}


def _area(hass: HomeAssistant, eid: str) -> str | None:
    e = er.async_get(hass).async_get(eid)
    if e is None:
        return None
    if e.area_id:
        return e.area_id
    d = e.device_id and dr.async_get(hass).async_get(e.device_id)
    return d.area_id if d else None


def _labels(hass: HomeAssistant, eid: str) -> set[str]:
    e = er.async_get(hass).async_get(eid)
    return set(e.labels or ()) if e else set()


def _thermostat_of(hass: HomeAssistant, relay: str) -> str | None:
    """The climate entity of a Generic Thermostat that drives this relay, if one exists."""
    reg = er.async_get(hass)
    for entry in hass.config_entries.async_entries(GT):
        if entry.options.get("heater") == relay:
            for ent in er.async_entries_for_config_entry(reg, entry.entry_id):
                if ent.domain == "climate":
                    return ent.entity_id
    return None


def candidates(hass: HomeAssistant) -> list[dict]:
    """Every floor-heating relay (switch with label UFH), its room, a room sensor and its thermostat."""
    reg = er.async_get(hass)
    areas = ar.async_get(hass)
    sensors: dict[str, list[str]] = {}
    for e in reg.entities.values():
        if e.domain != "sensor" or "t_h" not in (e.labels or ()):
            continue
        st = hass.states.get(e.entity_id)
        if st is None or st.attributes.get("device_class") != "temperature":
            continue
        a = _area(hass, e.entity_id)
        if a:
            sensors.setdefault(a, []).append(e.entity_id)
    out = []
    for e in reg.entities.values():
        if e.domain != "switch" or "ufh" not in (e.labels or ()) or e.disabled_by:
            continue
        a = _area(hass, e.entity_id)
        st = hass.states.get(e.entity_id)
        area = areas.async_get_area(a) if a else None
        out.append({
            "relay": e.entity_id,
            "name": (st and st.name) or e.entity_id,
            "area": a, "area_name": area.name if area else None,
            "sensors": sorted(sensors.get(a, [])),
            "thermostat": _thermostat_of(hass, e.entity_id),
        })
    return sorted(out, key=lambda x: ((x["area_name"] or "~").lower(), x["name"].lower()))


async def async_make_thermostat(hass: HomeAssistant, relay: str, sensor: str) -> str:
    """Create a Generic Thermostat for relay + sensor and label it like floor heating. Returns climate id."""
    reg = er.async_get(hass)
    if relay not in {c["relay"] for c in candidates(hass)}:
        raise vol.Invalid(f"{relay} is not a floor heating relay (switch with label UFH)")
    st = hass.states.get(sensor)
    if st is None or st.attributes.get("device_class") != "temperature":
        raise vol.Invalid(f"{sensor} is not a temperature sensor")
    existing = _thermostat_of(hass, relay)
    if existing:
        return existing
    area = _area(hass, relay)
    rst = hass.states.get(relay)
    name = (area and (a := ar.async_get(hass).async_get_area(area)) and f"{a.name} floor heating") or f"{rst.name if rst else relay} thermostat"
    flow = await hass.config_entries.flow.async_init(GT, context={"source": "user"})
    res = await hass.config_entries.flow.async_configure(flow["flow_id"], {"name": name, "heater": relay, "target_sensor": sensor, **DEFAULTS})
    if res.get("type") == "form" and res.get("step_id") == "presets":
        res = await hass.config_entries.flow.async_configure(res["flow_id"], {})
    if res.get("type") != "create_entry":
        raise vol.Invalid(f"Thermostat not created: {res.get('errors') or res.get('reason') or res.get('type')}")
    await hass.async_block_till_done()
    entry_id = res["result"].entry_id
    climate = next((e.entity_id for e in er.async_entries_for_config_entry(reg, entry_id) if e.domain == "climate"), None)
    if climate is None:
        raise vol.Invalid("Thermostat created but its climate entity was not found")
    ensure_label(hass, "no_panel", "No Panel")
    relay_labels = _labels(hass, relay)
    keep = {lid for lid in relay_labels if lid not in ("no_panel", "home")}
    reg.async_update_entity(climate, area_id=area, labels=keep | {"climate", "ufh"})
    reg.async_update_entity(relay, labels=relay_labels | {"no_panel"})
    _LOGGER.info("Thermostat %s made for %s with %s", climate, relay, sensor)
    return climate


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/thermostats/list"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_thermostats_list(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    connection.send_result(msg["id"], {"items": candidates(hass)})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/thermostats/make", vol.Required("relay"): str, vol.Required("sensor"): str})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_thermostats_make(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    try:
        climate = await async_make_thermostat(hass, msg["relay"], msg["sensor"])
    except (vol.Invalid, Exception) as err:  # noqa: BLE001 — shown to the installer
        connection.send_error(msg["id"], "thermostat_failed", str(err))
        return
    connection.send_result(msg["id"], {"climate": climate})


def async_register_ws(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_thermostats_list)
    websocket_api.async_register_command(hass, ws_thermostats_make)
