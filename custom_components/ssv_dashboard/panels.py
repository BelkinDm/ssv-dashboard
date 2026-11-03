"""Panels: what each screen is, where it hangs and what it shows.

A panel is made on the SSV Dashboard page and stored here, not in the dashboard
address, so it can be changed later without touching the tablet:

  id        short name used in the address (?panel=gym) and in the label panel_<id>
  name      shown on the panel (Gym, Office, Kitchen ...)
  type      wall | room | tablet | phone — only the layout (5.5" comes later)
  attached  rooms that belong to the panel's room: [{"key": "wc", "name": "WC", "area": ...}]
            — each gets its own tab on a room panel and its own label panel_<id>_<key>
  purpose   residential | hotel_room | office | gym | common — default set of tabs
  areas     the rooms it controls (empty = whole house)
  room      the room shown big on Home
  tabs      {tab: false} switches a tab off
  night     {"enabled": bool, "from": 22, "to": 7}
  villa, place, dashboard

Every panel gets a label "Panel <Name>" (id panel_<id>), and every attached room
"Panel <Name> <Room>" (id panel_<id>_<key>); a room panel always gets "Panel <Name> WC".
Put it on an area to add the whole room, or on a device / entity to show just that
device there, wherever it is installed.
"""
from __future__ import annotations

import logging
import re

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import slugify

from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er, label_registry as lr

from .const import DOMAIN, LABEL_USE, LABELS
from .labels import ensure_label, nice
from .timers import async_apply_timers, async_candidates

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
    vol.Optional("attached", default=list): [vol.Schema({
        vol.Required("key"): vol.All(str, vol.Match(r"^[a-z0-9][a-z0-9_]{0,30}$")),
        vol.Required("name"): vol.All(str, vol.Strip, vol.Length(min=1, max=30)),
        vol.Optional("area"): vol.Any(None, str),
    })],
})
MINUTES = vol.All(int, vol.Range(5, 24 * 60))
TIMERS_SCHEMA = vol.Schema({str: vol.Schema({vol.Required("runs"): vol.All([MINUTES], vol.Length(min=1, max=4))})})


class PanelStore:
    """Panels and run times, kept in .storage/ssv_dashboard.panels."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store = Store(hass, STORE_VERSION, STORE_KEY)
        self.panels: dict[str, dict] = {}
        self.timers: dict[str, dict] = {}   # key -> {"runs": [minutes]} chosen on the page
        self.seen: list[str] = []            # candidates the installer has already been shown
        self.managed_timers: list[str] = []
        self.notified: str | None = None     # last version announced as an update
        self._listeners: list = []

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.panels = data.get("panels", {})
        self.timers = data.get("timers", {})
        if "timers" not in data and data.get("managed_timers"):
            # 1.1 made timers by itself: keep those as chosen, with the run time it used
            old = data.get("runs") or {}
            for obj in data["managed_timers"]:
                if obj.startswith("inex_wall_"):
                    eid = "climate." + obj[len("inex_wall_"):]
                    self.timers[eid] = {"runs": [int((old.get("per") or {}).get(eid) or old.get("wall") or 180)]}
                elif obj.startswith("inex_water_"):
                    self.timers["fn:" + obj[len("inex_water_"):]] = {"runs": [60, 90, 120] if obj.endswith("hot_water") else [10]}
        self.seen = data.get("seen", [])
        self.notified = data.get("notified")
        self.managed_timers = data.get("managed_timers", [])

    @callback
    def async_save(self) -> None:
        self._store.async_delay_save(
            lambda: {"panels": self.panels, "timers": self.timers, "seen": self.seen,
                     "managed_timers": self.managed_timers, "notified": self.notified}, 1)
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
        return {**p, "runs": {k: v["runs"] for k, v in self.timers.items()}}


def panel_label_specs(panel: dict) -> list[tuple[str, str, str, str]]:
    """(id, name, icon, what for) of every label a panel owns.

    Panel <Name> (panel_<id>), Panel <Name> <Room> (panel_<id>_<key>) for each attached room,
    and for a room panel always Panel <Name> WC (panel_<id>_wc)."""
    pid, name = panel["id"], nice(panel["name"])
    out = [(f"panel_{pid}", f"Panel {name}", "mdi:tablet-dashboard",
            f"Panel {name}: on an area — the whole room, on a device — just that device")]
    att = list(panel.get("attached") or [])
    if panel.get("type") == "room" and not any(a["key"] == "wc" for a in att):
        att.append({"key": "wc", "name": "WC"})
    for a in att:
        out.append((f"panel_{pid}_{a['key']}", f"Panel {name} {nice(a['name'])}", "mdi:door",
                    f"{nice(a['name'])} tab of panel {name}"))
    return out


def panel_areas(hass: HomeAssistant, panel: dict) -> list:
    """Areas a panel controls: its rooms, its home room and the areas of attached rooms (none listed = whole house)."""
    areg = ar.async_get(hass)
    ids = list(panel.get("areas") or [])
    if panel.get("room"):
        ids.append(panel["room"])
    ids += [a["area"] for a in panel.get("attached") or [] if a.get("area")]
    if not ids:
        return sorted(areg.async_list_areas(), key=lambda a: a.name.lower())
    out = []
    for i in dict.fromkeys(ids):
        a = areg.async_get_area(i)
        if a:
            out.append(a)
    return out


@callback
def ensure_room_labels(hass: HomeAssistant, panel: dict) -> list[str]:
    """Room labels (<room>) for the panel's areas: id = area id, name = area name — Bedroom 1 (bedroom_1)."""
    made = []
    for a in panel_areas(hass, panel):
        lid = ensure_label(hass, a.id, nice(a.name), "mdi:door")
        if lid:
            made.append(lid)
    return made


@callback
def ensure_panel_labels(hass: HomeAssistant, panel: dict) -> list[str]:
    """Make all labels of a panel (see panel_label_specs) and the room labels of its areas. Returns their ids."""
    made = [ensure_label(hass, lid, name, icon) for lid, name, icon, _ in panel_label_specs(panel)]
    made += ensure_room_labels(hass, panel)
    return list(dict.fromkeys(m for m in made if m))


@callback
def labels_overview(hass: HomeAssistant, store: "PanelStore") -> list[dict]:
    """Every label SSV Dashboard reads, with what it is for and where it is used now."""
    lreg = lr.async_get(hass)
    use: dict[str, dict[str, int]] = {}

    def bump(lid: str, kind: str) -> None:
        use.setdefault(lid, {"areas": 0, "devices": 0, "entities": 0})[kind] += 1

    for a in ar.async_get(hass).async_list_areas():
        for lid in a.labels or ():
            bump(lid, "areas")
    for d in dr.async_get(hass).devices.values():
        for lid in d.labels or ():
            bump(lid, "devices")
    for e in er.async_get(hass).entities.values():
        for lid in e.labels or ():
            bump(lid, "entities")

    rows: list[dict] = []

    def row(lid: str, name: str, icon: str, what: str, group: str) -> None:
        entry = lreg.async_get_label(lid)
        rows.append({"id": lid, "name": entry.name if entry else name, "icon": icon, "use": what, "group": group,
                     "exists": entry is not None, **use.get(lid, {"areas": 0, "devices": 0, "entities": 0})})

    for lid, (name, icon) in LABELS.items():
        row(lid, name, icon, LABEL_USE.get(lid, ""), "base")
    for p in sorted(store.panels.values(), key=lambda x: x["name"].lower()):
        for lid, name, icon, what in panel_label_specs(p):
            row(lid, name, icon, what, "panel")
    seen = {r["id"] for r in rows}
    for p in sorted(store.panels.values(), key=lambda x: x["name"].lower()):
        for a in panel_areas(hass, p):
            if a.id in seen:
                continue
            seen.add(a.id)
            row(a.id, nice(a.name), "mdi:door", f"Room {a.name}: puts a device in this room on the panels (<room> label)", "room")
    return rows


@callback
def restyle_panel_labels(hass: HomeAssistant, store: "PanelStore") -> None:
    """Bring labels of panels made before 1.2 ("Panel · Gym") to the one style."""
    for p in store.panels.values():
        ensure_panel_labels(hass, p)


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
    connection.send_result(msg["id"], {"panels": list(st.panels.values())})


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
    labels = ensure_panel_labels(hass, panel)
    st.panels[panel["id"]] = panel
    st.async_save()
    connection.send_result(msg["id"], {"panel": panel, "label": labels[0] if labels else None, "labels": labels})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/panels/delete", vol.Required("panel"): str})
@websocket_api.require_admin
@callback
def ws_panels_delete(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Forget a panel. Its label and dashboard stay — they may still be in use."""
    st = _store(hass)
    removed = st.panels.pop(msg["panel"], None)
    st.async_save()
    connection.send_result(msg["id"], {"deleted": bool(removed)})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/labels/list"})
@websocket_api.require_admin
@callback
def ws_labels_list(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """All labels of SSV Dashboard: the base set plus the ones made with each panel."""
    connection.send_result(msg["id"], {"labels": labels_overview(hass, _store(hass))})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/timers/list"})
@websocket_api.require_admin
@callback
def ws_timers_list(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """What can have a run timer: heated walls, floor heating, hot water, recirculation."""
    connection.send_result(msg["id"], {"items": async_candidates(hass, _store(hass))})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/timers/save", vol.Required("timers"): dict})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_timers_save(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Save the chosen timers and their buttons, then make / remove the timers."""
    try:
        chosen = TIMERS_SCHEMA(msg["timers"])
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    st = _store(hass)
    shown = [c["key"] for c in async_candidates(hass, st)]
    st.timers = {k: {"runs": sorted(set(v["runs"]))} for k, v in chosen.items()}
    st.seen = sorted(set(st.seen) | set(shown))
    try:
        changes = await async_apply_timers(hass, st)
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "timers_failed", str(err))
        return
    connection.send_result(msg["id"], {"changes": changes})


@callback
def async_register_ws(hass: HomeAssistant) -> None:
    for cmd in (ws_panel_get, ws_panels_list, ws_panels_save, ws_panels_delete, ws_labels_list, ws_timers_list, ws_timers_save):
        websocket_api.async_register_command(hass, cmd)
