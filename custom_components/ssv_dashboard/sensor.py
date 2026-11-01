"""sensor.ssv_time — Home Assistant's own time for the panel clocks.

The panels show this time instead of the tablet's clock, so every panel agrees
with the server and with the HA time zone even if a tablet's clock is wrong.
"""
from __future__ import annotations

from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.components.sensor import SensorEntity
from homeassistant.util import dt as dt_util



async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([SSVTimeSensor(entry)])


class SSVTimeSensor(SensorEntity):
    _attr_has_entity_name = False
    _attr_name = "SSV time"
    _attr_icon = "mdi:clock-outline"
    _attr_should_poll = False
    _unrecorded_attributes = frozenset({"time_zone"})

    def __init__(self, entry: ConfigEntry) -> None:
        self._attr_unique_id = f"{entry.entry_id}_time"
        self.entity_id = "sensor.ssv_time"

    @property
    def native_value(self) -> str:
        return dt_util.now().replace(microsecond=0).isoformat()

    @property
    def extra_state_attributes(self) -> dict:
        return {"time_zone": str(dt_util.get_default_time_zone())}

    async def async_added_to_hass(self) -> None:
        @callback
        def _tick(_now: datetime) -> None:
            self.async_write_ha_state()

        self.async_on_remove(async_track_time_change(self.hass, _tick, second=0))
