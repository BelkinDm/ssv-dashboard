"""SSV Dashboard — wall panels, room panels, phone and tablet dashboards for Home Assistant.

What this integration does:
  * serves the panel pages at /ssv_dashboard/panel.html, room.html, phone.html;
  * creates the labels the panels read (Light, Curtain, Scene Device, ...);
  * offers user-scene services so guests can make their own scenes safely;
  * makes the run timers chosen on the SSV Dashboard page and turns heated walls,
    floor heating, hot water and recirculation off when their timer ends;
  * provides sensor.ssv_time so every panel clock follows Home Assistant;
  * keeps panels (name, screen, purpose, rooms, attached rooms, tabs) with a label each;
  * tells the installer when a new SSV Dashboard is out;
  * adds an admin-only "SSV Dashboard" page: panels and their dashboards, start page,
    run timers, and a check of the integrations each tab needs (with HACS install).
"""
from __future__ import annotations

import logging
import re

import voluptuous as vol

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import label_registry as lr
from homeassistant.loader import async_get_integration

from .const import CONF_NOTIFY, CONF_TIMER_ACTIONS, DOMAIN, LABELS, NAME, SETUP_PANEL, STATIC_URL
from .http import async_register_files
from .labels import ensure_base_labels
from .panels import PanelStore, async_register_ws as async_register_panel_ws, restyle_panel_labels
from .scenes import async_setup_scenes, async_unload_scenes
from .timers import async_setup_timers
from .updates import async_watch_updates, update_info

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
    websocket_api.async_register_command(hass, ws_update_install)
    async_register_panel_ws(hass)
    return True


@callback
def _ensure_labels(hass: HomeAssistant) -> list[str]:
    made = ensure_base_labels(hass)
    if made:
        _LOGGER.info("Created labels: %s", ", ".join(made))
    return made


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data[DOMAIN]
    _ensure_labels(hass)
    store = PanelStore(hass)
    await store.async_load()
    data["panels"] = store
    restyle_panel_labels(hass, store)
    await async_setup_scenes(hass)
    unsubs = []
    if entry.options.get(CONF_TIMER_ACTIONS, True):
        unsubs.append(async_setup_timers(hass))
    unsubs.append(async_watch_updates(hass, store, entry.options.get(CONF_NOTIFY)))
    data["unsubs"] = unsubs
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=SETUP_PANEL,
        webcomponent_name="ssv-setup-" + re.sub(r"[^a-z0-9]+", "-", data["version"].lower()),  # new name per version: an open browser loads the new page after an update
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
    for unsub in data.pop("unsubs", []):
        try:
            unsub()
        except ValueError:  # a once-listener that already fired
            pass
    async_unload_scenes(hass)
    frontend.async_remove_panel(hass, SETUP_PANEL)
    return ok


_SCENE_INCLUDE = re.compile(r"^scene:\s*!include\s+scenes\.yaml\s*$", re.M)


def _scene_include(path: str) -> bool:
    try:
        with open(path, encoding="utf-8") as f:
            return bool(_SCENE_INCLUDE.search(f.read()))
    except OSError:
        return False


async def _checks(hass: HomeAssistant) -> list[dict]:
    """What each tab needs, and whether it is there."""
    comps = hass.config.components
    has_dom = lambda d: any(True for _ in hass.states.async_entity_ids(d))  # noqa: E731
    scene_ok = await hass.async_add_executor_job(_scene_include, hass.config.path("configuration.yaml"))
    return [
        {"key": "hacs", "name": "HACS", "for": "Installing and updating SSV Dashboard", "ok": "hacs" in comps, "need": "required"},
        {"key": "scene_yaml", "name": "scene: !include scenes.yaml", "for": "Scenes made by guests", "ok": scene_ok, "need": "required"},
        {"key": "timer", "name": "Timer", "for": "Run buttons", "ok": "timer" in comps, "need": "required"},
        {"key": "recorder", "name": "Recorder", "for": "Water: today and 7 days", "ok": "recorder" in comps, "need": "required"},
        {"key": "weather", "name": "Weather (Met.no or other)", "for": "Weather in the header", "ok": has_dom("weather"), "need": "recommended"},
        {"key": "scheduler", "name": "Scheduler component", "for": "Schedule tab", "ok": "scheduler" in comps, "need": "tab", "hacs": "nielsfaber/scheduler-component", "domain": "scheduler"},
        {"key": "camera", "name": "Cameras (ONVIF, Generic Camera, Hikvision...)", "for": "Cameras tab", "ok": has_dom("camera"), "need": "tab"},
        {"key": "go2rtc", "name": "go2rtc", "for": "Intercom live video", "ok": "go2rtc" in comps, "need": "tab", "domain": "go2rtc"},
        {"key": "webrtc", "name": "WebRTC Camera (AlexxIT)", "for": "Intercom live video", "ok": "webrtc" in comps, "need": "tab", "hacs": "AlexxIT/WebRTC", "domain": "webrtc"},
        {"key": "alarm", "name": "Alarm / locks", "for": "Security tab", "ok": has_dom("alarm_control_panel") or has_dom("lock"), "need": "tab"},
        {"key": "mobile_app", "name": "Mobile App", "for": "Guests signing in on phones", "ok": "mobile_app" in comps, "need": "recommended"},
        {"key": "fully_kiosk", "name": "Fully Kiosk Browser", "for": "Tablet screen control", "ok": "fully_kiosk" in comps, "need": "recommended", "domain": "fully_kiosk"},
    ]


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/info"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_info(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Version, labels and integration checks for the setup page."""
    reg = lr.async_get(hass)
    connection.send_result(msg["id"], {
        "version": hass.data.get(DOMAIN, {}).get("version"),
        "labels": {lid: bool(reg.async_get_label(lid)) for lid in LABELS},
        "location_name": hass.config.location_name,
        "checks": await _checks(hass),
        "update": update_info(hass),
    })


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/update/install"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_update_install(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Install the new version through HACS' update entity (a restart is needed afterwards)."""
    info = update_info(hass)
    if not info["entity_id"] or not info["available"]:
        connection.send_error(msg["id"], "no_update", "No update available")
        return
    await hass.services.async_call("update", "install", {"entity_id": info["entity_id"]}, blocking=True)
    connection.send_result(msg["id"], {"installed": info["latest"]})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/create_labels"})
@websocket_api.require_admin
@callback
def ws_create_labels(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Create any missing labels again (e.g. after one was deleted by hand)."""
    connection.send_result(msg["id"], {"created": _ensure_labels(hass)})
