"""Floor heating on a relay (switch) — a valve or a contactor instead of a climate device.

The panels show such a relay as floor heating (label UFH): On / Off and Run buttons, no set point.
When the same room has a temperature sensor (label Temperature Humidity), the SSV Dashboard page
offers "Make thermostat": SSV creates Home Assistant's own Generic Thermostat (relay + sensor), so
the set point, the room temperature, schedules and Run timers work as with any floor heating, and the
thermostat keeps working without SSV. The new climate gets the relay's area and labels plus
Climate + UFH; the relay gets No Panel so the panel does not show it twice.

Defaults (change them later in the thermostat's options): set point 16–35 °C, step 1 °C,
heats up to the set point and waits (Standby) until the room is 2 °C under it (cold tolerance 2,
hot tolerance 0), at least 5 minutes between valve switchings (thermal actuators take minutes).
When the floor is switched on or its set point is raised while the room is under the set point,
SSV opens the valve at once (Generic Thermostat alone would wait for the 2 °C). Thermostats SSV
made earlier get these values once (1.6.1 step, 1.6.4 range and hysteresis).
"""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er

from .const import DOMAIN
from .labels import ensure_label

_LOGGER = logging.getLogger(__name__)
GT = "generic_thermostat"
DEFAULTS = {
    "ac_mode": False,
    "cold_tolerance": 2.0,   # 1.6.4: back on when the room is 2 °C under the set point
    "hot_tolerance": 0.0,    # valve closes when the set point is reached
    "min_cycle_duration": {"hours": 0, "minutes": 5, "seconds": 0},
    "min_temp": 16.0,
    "max_temp": 35.0,
}
# set after the flow: older Home Assistant has no step field in the Generic Thermostat form,
# but every version reads target_temp_step from the entry options
STEP = {"target_temp_step": 1.0}   # a number: older versions do not accept the text "1"


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
    # 1.6.5: "UFH <room>": the panels drop the room, so scenes and schedules just say UFH
    name = (area and (a := ar.async_get(hass).async_get_area(area)) and f"UFH {a.name}") or f"UFH {rst.name if rst else relay}"
    flow = await hass.config_entries.flow.async_init(GT, context={"source": "user"})
    res = await hass.config_entries.flow.async_configure(flow["flow_id"], {"name": name, "heater": relay, "target_sensor": sensor, **DEFAULTS})
    if res.get("type") == "form" and res.get("step_id") == "presets":
        res = await hass.config_entries.flow.async_configure(res["flow_id"], {})
    if res.get("type") != "create_entry":
        raise vol.Invalid(f"Thermostat not created: {res.get('errors') or res.get('reason') or res.get('type')}")
    await hass.async_block_till_done()
    entry_id = res["result"].entry_id
    gt = hass.config_entries.async_get_entry(entry_id)
    if gt is not None and gt.options.get("target_temp_step") != STEP["target_temp_step"]:
        hass.config_entries.async_update_entry(gt, options={**gt.options, **STEP})
        await hass.config_entries.async_reload(entry_id)
        await hass.async_block_till_done()
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


THERMO_FLAG = "thermostat_step1_hyst3"   # 1.6.1, done once per install
RANGE_FLAG = "thermostat_164"            # 1.6.4: range 16–35 °C and hysteresis 2 / 0, once per install


async def async_migrate_thermostats(hass: HomeAssistant, store) -> int:
    """Once: thermostats SSV made on floor-heating relays get step 1 °C and hysteresis 3 °C."""
    if THERMO_FLAG in store.flags:
        return 0
    relays = {c["relay"] for c in candidates(hass)}
    want = {"cold_tolerance": DEFAULTS["cold_tolerance"], "hot_tolerance": DEFAULTS["hot_tolerance"], **STEP}
    n = 0
    for entry in hass.config_entries.async_entries(GT):
        if entry.options.get("heater") not in relays:
            continue
        if all(str(entry.options.get(k)) == str(v) for k, v in want.items()):
            continue
        hass.config_entries.async_update_entry(entry, options={**entry.options, **want})
        if entry.state is ConfigEntryState.LOADED:
            hass.config_entries.async_schedule_reload(entry.entry_id)
        n += 1
        _LOGGER.info("Thermostat %s: step 1 °C, hysteresis 3 °C", entry.title)
    store.flags.append(THERMO_FLAG)
    store.async_save()
    return n


async def async_migrate_thermostat_range(hass: HomeAssistant, store) -> int:
    """Once (1.6.4): thermostats SSV made on floor-heating relays get 16–35 °C and hysteresis 2 / 0."""
    if RANGE_FLAG in store.flags:
        return 0
    relays = {c["relay"] for c in candidates(hass)}
    want = {k: DEFAULTS[k] for k in ("min_temp", "max_temp", "cold_tolerance", "hot_tolerance")}
    n = 0
    for entry in hass.config_entries.async_entries(GT):
        if entry.options.get("heater") not in relays:
            continue
        if all(entry.options.get(k) == v for k, v in want.items()):
            continue
        hass.config_entries.async_update_entry(entry, options={**entry.options, **want})
        if entry.state is ConfigEntryState.LOADED:
            hass.config_entries.async_schedule_reload(entry.entry_id)
        n += 1
        _LOGGER.info("Thermostat %s: set point 16–35 °C, hysteresis 2 / 0", entry.title)
    store.flags.append(RANGE_FLAG)
    store.async_save()
    return n


NAME_FLAG = "thermostat_name_ufh"   # 1.6.5, done once per install


async def async_rename_thermostats(hass: HomeAssistant, store) -> int:
    """Once (1.6.5): thermostats SSV made as "<Room> floor heating" become "UFH <Room>".

    Only when the name is still SSV's own (no name typed by hand in Home Assistant)."""
    if NAME_FLAG in store.flags:
        return 0
    reg = er.async_get(hass)
    areas = ar.async_get(hass)
    n = 0
    for climate, relay in _ssv_thermostats(hass).items():
        ent = reg.async_get(climate)
        if ent is None or ent.name:
            continue
        area_id = ent.area_id or _area(hass, relay)
        a = area_id and areas.async_get_area(area_id)
        if not a:
            continue
        new = f"UFH {a.name}"
        st = hass.states.get(climate)
        if st is not None and st.name == new:
            continue
        reg.async_update_entity(climate, name=new)
        entry = ent.config_entry_id and hass.config_entries.async_get_entry(ent.config_entry_id)
        if entry is not None and entry.title.endswith("floor heating"):
            hass.config_entries.async_update_entry(entry, title=new)
        n += 1
        _LOGGER.info("Thermostat %s renamed to %s", climate, new)
    store.flags.append(NAME_FLAG)
    store.async_save()
    return n


def _ssv_thermostats(hass: HomeAssistant) -> dict[str, str]:
    """climate entity -> relay, for the Generic Thermostats SSV made on floor-heating relays."""
    relays = {c["relay"] for c in candidates(hass)}
    reg = er.async_get(hass)
    out = {}
    for entry in hass.config_entries.async_entries(GT):
        heater = entry.options.get("heater")
        if heater in relays:
            for ent in er.async_entries_for_config_entry(reg, entry.entry_id):
                if ent.domain == "climate":
                    out[ent.entity_id] = heater
    return out


@callback
def async_setup_start_heating(hass: HomeAssistant):
    """1.6.4: switched on, or set point raised, while the room is under the set point -> open the valve now.

    Generic Thermostat only switches on when the room is cold_tolerance (2 °C) under the set point; with
    the room at 22 °C and the set point 23 °C the floor would just wait. Once the valve is open, Generic
    Thermostat keeps it open up to the set point (hot tolerance 0) and then waits for the 2 °C again."""
    cache: dict = {"map": None}

    @callback
    def _registry_changed(_event) -> None:
        cache["map"] = None

    @callback
    def _state_changed(event) -> None:
        eid = event.data.get("entity_id", "")
        if not eid.startswith("climate."):
            return
        if cache["map"] is None:
            cache["map"] = _ssv_thermostats(hass)
        relay = cache["map"].get(eid)
        new, old = event.data.get("new_state"), event.data.get("old_state")
        if relay is None or new is None or new.state != "heat":
            return
        tgt, cur = new.attributes.get("temperature"), new.attributes.get("current_temperature")
        if tgt is None or cur is None:
            return
        started = old is None or old.state != "heat" or (old.attributes.get("temperature") or 0) < tgt
        rst = hass.states.get(relay)
        if started and cur < tgt and rst is not None and rst.state == "off":
            _LOGGER.debug("%s: %.1f < %.1f, opening %s", eid, cur, tgt, relay)
            hass.async_create_task(hass.services.async_call("homeassistant", "turn_on", {"entity_id": relay}))

    unsubs = [hass.bus.async_listen(EVENT_STATE_CHANGED, _state_changed),
              hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _registry_changed)]
    return lambda: [u() for u in unsubs]


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
