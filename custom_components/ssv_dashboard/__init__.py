"""SSV Dashboard — wall panels, room panels, phone and tablet dashboards for Home Assistant.

What this integration does:
  * serves the panel pages at /ssv_dashboard/panel.html, room.html, phone.html;
  * creates the labels the panels read (Light, Curtain, Scene Device, ...);
  * offers user-scene services so guests can make their own scenes safely;
  * turns heated walls / hot water / recirculation off when their run timer ends;
  * provides sensor.ssv_time so every panel clock follows Home Assistant;
  * adds an admin-only "SSV Dashboard" page that creates the dashboards,
    the start page and the run timers in a few clicks.
"""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import label_registry as lr
from homeassistant.loader import async_get_integration

from .const import CONF_TIMER_ACTIONS, DOMAIN, LABELS, NAME, SETUP_PANEL, STATIC_URL
from .http import async_register_files
from .scenes import async_setup_scenes, async_unload_scenes
from .timers import async_setup_timers

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Things that can be registered only once per Home Assistant run."""
    integration = await async_get_integration(hass, DOMAIN)
    version = str(integration.version)
    hass.data[DOMAIN] = {"version": version}
    await async_register_files(hass, version)
    websocket_api.async_register_command(hass, ws_info)
    websocket_api.async_register_command(hass, ws_create_labels)
    return True


@callback
def _ensure_labels(hass: HomeAssistant) -> list[str]:
    reg = lr.async_get(hass)
    made: list[str] = []
    for label_id, (name, icon) in LABELS.items():
        if reg.async_get_label(label_id) or reg.async_get_label_by_name(name):
            continue
        try:
            entry = reg.async_create(name, icon=icon)
        except ValueError as err:  # name taken in another spelling
            _LOGGER.warning("Label %s not created: %s", name, err)
            continue
        if entry.label_id != label_id:
            _LOGGER.warning("Label %s got id %s (panels look for %s)", name, entry.label_id, label_id)
        made.append(entry.label_id)
    if made:
        _LOGGER.info("Created labels: %s", ", ".join(made))
    return made


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data[DOMAIN]
    _ensure_labels(hass)
    await async_setup_scenes(hass)
    data["unsub_timers"] = (
        async_setup_timers(hass) if entry.options.get(CONF_TIMER_ACTIONS, True) else None
    )
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=SETUP_PANEL,
        webcomponent_name="ssv-setup",
        sidebar_title=NAME,
        sidebar_icon="mdi:tablet-dashboard",
        module_url=f"{STATIC_URL}/setup.js?v={data['version']}",
        require_admin=True,
        config={"version": data["version"]},
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    data = hass.data[DOMAIN]
    if data.get("unsub_timers"):
        data.pop("unsub_timers")()
    async_unload_scenes(hass)
    frontend.async_remove_panel(hass, SETUP_PANEL)
    return ok


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/info"})
@websocket_api.require_admin
@callback
def ws_info(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Version and label status for the setup page."""
    reg = lr.async_get(hass)
    connection.send_result(msg["id"], {
        "version": hass.data.get(DOMAIN, {}).get("version"),
        "labels": {lid: bool(reg.async_get_label(lid)) for lid in LABELS},
        "location_name": hass.config.location_name,
    })


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/create_labels"})
@websocket_api.require_admin
@callback
def ws_create_labels(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Create any missing labels again (e.g. after one was deleted by hand)."""
    connection.send_result(msg["id"], {"created": _ensure_labels(hass)})
