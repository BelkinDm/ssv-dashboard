"""Panels: what each screen is, where it hangs and what it shows.

A panel is made on the SSV Dashboard page and stored here, not in the dashboard
address, so it can be changed later without touching the tablet:

  id        short name used in the address (?panel=gym) and in the label panel_<id>
  name      shown on the panel (Gym, Office, Kitchen ...)
  type      wall | room | tablet | phone — only the layout
  purpose   residential | hotel_room | office | gym | common — default set of tabs
  areas     the rooms it controls (empty = whole house)
  room      the room shown big on Home
  tabs      {tab: false} switches a tab off
  night     {"enabled": bool, "from": 22, "to": 7}
  villa, place, dashboard

Every panel gets a label "Panel · <name>" (id panel_<id>): put it on an area to
add the whole room, or on a device / entity to show just that device on the panel
wherever it is installed.
"""
from __future__ import annotations

import logging
import re

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import label_registry as lr
from homeassistant.helpers.storage import Store
from homeassistant.util import slugify

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
STORE_KEY = f"{DOMAIN}.panels"
STORE_VERSION = 1
TYPES = ("wall", "room", "tablet", "phone")
PURPOSES = ("residential", "hotel_room", "office", "gym", "common", "custom")
TABS = ("rooms", "lights", "climate", "heating", "curtains", "water", "cameras", "intercom", "security", "schedule")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,40}$")

PANEL_SCHEMA = vol.Schema({
    vol.Required("id"): vol.All(str, vol.Match(ID_RE)),
    vol.Required("name"): vol.All(str, vol.Strip, vol.Length(min=1, max=40)),
    vol.Required("type"): vol.In(TYPES),
    vol.Optional("purpose", default="residential"): vol.In(PURPOSES),
    vol.Optional("areas", default=list): [str],
    vol.Optional("room"): vol.Any(None, str),
    vol.Optional("tabs", default=dict): {vol.In(TABS): bool},
    vol.Optional("night", default=dict): {
        vol.Optional("enabled"): bool,
        vol.Optional("from"): vol.All(int, vol.Range(0, 23)),
        vol.Optional("to"): vol.All(int, vol.Range(0, 23)),
    },
    vol.Optional("villa"): vol.Any(None, vol.All(str, vol.Length(max=60))),
    vol.Optional("place"): vol.Any(None, vol.All(str, vol.Length(max=60))),
    vol.Optional("dashboard"): vol.Any(None, str),
})
RUNS_SCHEMA = vol.Schema({
    vol.Optional("wall", default=180): vol.All(int, vol.Range(5, 24 * 60)),
    vol.Optional("per", default=dict): {str: vol.All(int, vol.Range(5, 24 * 60))},
})


class PanelStore:
    """Panels and run times, kept in .storage/ssv_dashboard.panels."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store = Store(hass, STORE_VERSION, STORE_KEY)
        self.panels: dict[str, dict] = {}
        self.runs: dict = {"wall": 180, "per": {}}
        self.managed_timers: list[str] = []
        self._listeners: list = []

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.panels = data.get("panels", {})
        self.runs = RUNS_SCHEMA(data.get("runs", {}))
        self.managed_timers = data.get("managed_timers", [])

    @callback
    def async_save(self) -> None:
        self._store.async_delay_save(
            lambda: {"panels": self.panels, "runs": self.runs, "managed_timers": self.managed_timers}, 1)
        for cb in list(self._listeners):
            cb()

    @callback
    def async_listen(self, cb):
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    def public(self, panel_id: str) -> dict | None:
        p = self.panels.get(panel_id)
        if p is None:
            return None
        return {**p, "runs": self.runs}


@callback
def ensure_panel_label(hass: HomeAssistant, panel: dict) -> str:
    """Label "Panel · <name>" with id panel_<id>; created once, renamed with the panel."""
    reg = lr.async_get(hass)
    want = f"panel_{panel['id']}"
    name = f"Panel · {panel['name']}"
    entry = reg.async_get_label(want)
    if entry is None:
        if slugify(name) != want or reg.async_get_label_by_name(name):
            # names that do not slugify to the id: create under the id-like name, then rename
            entry = reg.async_create(want, icon="mdi:tablet-dashboard")
        else:
            entry = reg.async_create(name, icon="mdi:tablet-dashboard")
    if entry.name != name and not reg.async_get_label_by_name(name):
        reg.async_update(entry.label_id, name=name)
    return entry.label_id


def _store(hass: HomeAssistant) -> PanelStore:
    return hass.data[DOMAIN]["panels"]


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/panel/get", vol.Required("panel"): str})
@callback
def ws_panel_get(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Settings for one panel — any signed-in user (the panels are not administrators)."""
    st = hass.data.get(DOMAIN, {}).get("panels")
    connection.send_result(msg["id"], st.public(slugify(msg["panel"])) if st else None)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/panels/list"})
@websocket_api.require_admin
@callback
def ws_panels_list(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    st = _store(hass)
    connection.send_result(msg["id"], {"panels": list(st.panels.values()), "runs": st.runs})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/panels/save", vol.Required("panel"): dict})
@websocket_api.require_admin
@callback
def ws_panels_save(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    try:
        panel = PANEL_SCHEMA(msg["panel"])
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    st = _store(hass)
    old = st.panels.get(panel["id"], {})
    panel = {**old, **panel}
    label = ensure_panel_label(hass, panel)
    st.panels[panel["id"]] = panel
    st.async_save()
    connection.send_result(msg["id"], {"panel": panel, "label": label})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/panels/delete", vol.Required("panel"): str})
@websocket_api.require_admin
@callback
def ws_panels_delete(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Forget a panel. Its label and dashboard stay — they may still be in use."""
    st = _store(hass)
    removed = st.panels.pop(msg["panel"], None)
    st.async_save()
    connection.send_result(msg["id"], {"deleted": bool(removed)})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/runs/save", vol.Required("runs"): dict})
@websocket_api.require_admin
@callback
def ws_runs_save(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    try:
        runs = RUNS_SCHEMA(msg["runs"])
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    st = _store(hass)
    st.runs = runs
    st.async_save()
    connection.send_result(msg["id"], runs)


@callback
def async_register_ws(hass: HomeAssistant) -> None:
    for cmd in (ws_panel_get, ws_panels_list, ws_panels_save, ws_panels_delete, ws_runs_save):
        websocket_api.async_register_command(hass, cmd)
