"""Tell the installer when a new SSV Dashboard is out.

HACS keeps an update entity for every repository it installed. When the one for
SSV Dashboard turns on, this shows a notification in Home Assistant (once per
version) and, if a notify service is set in the integration's options, pushes the
same text there (for example notify.mobile_app_<phone>). The SSV Dashboard page
shows a banner with an "Update now" button.
"""
from __future__ import annotations

import logging

from homeassistant.components import persistent_notification
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

_LOGGER = logging.getLogger(__name__)
NOTIFICATION_ID = "ssv_dashboard_update"


@callback
def find_update_entity(hass: HomeAssistant) -> str | None:
    """update.* made by HACS for this repository."""
    for ent in er.async_get(hass).entities.values():
        if ent.domain != "update" or ent.platform != "hacs":
            continue
        text = " ".join(str(x or "") for x in (ent.entity_id, ent.original_name, ent.name)).lower()
        if "ssv_dashboard" in text or "ssv dashboard" in text or "ssv-dashboard" in text:
            return ent.entity_id
    return None


@callback
def update_info(hass: HomeAssistant) -> dict:
    eid = find_update_entity(hass)
    st = hass.states.get(eid) if eid else None
    return {
        "entity_id": eid,
        "available": bool(st and st.state == "on"),
        "installed": st.attributes.get("installed_version") if st else None,
        "latest": st.attributes.get("latest_version") if st else None,
    }


@callback
def async_watch_updates(hass: HomeAssistant, store, notify_service: str | None):
    """Watch the HACS update entity. Returns the unsubscribe callback."""
    state: dict = {"unsub": None, "eid": None}

    async def _announce() -> None:
        info = update_info(hass)
        if not info["available"] or not info["latest"] or store.notified == info["latest"]:
            return
        store.notified = info["latest"]
        store.async_save()
        msg = (f"SSV Dashboard {info['latest']} is available (installed {info['installed']}). "
               "Open SSV Dashboard in the sidebar and press Update now, or Settings → Updates.")
        persistent_notification.async_create(hass, msg, title="SSV Dashboard update", notification_id=NOTIFICATION_ID)
        if notify_service and "." in notify_service:
            dom, svc = notify_service.split(".", 1)
            if hass.services.has_service(dom, svc):
                await hass.services.async_call(dom, svc, {"title": "SSV Dashboard update", "message": msg})
            else:
                _LOGGER.warning("Notify service %s not found", notify_service)

    @callback
    def _changed(_event: Event | None = None) -> None:
        hass.async_create_task(_announce())

    @callback
    def _attach(_event: Event | None = None) -> None:
        eid = find_update_entity(hass)
        if eid == state["eid"]:
            return
        if state["unsub"]:
            state["unsub"]()
        state["eid"] = eid
        state["unsub"] = async_track_state_change_event(hass, [eid], _changed) if eid else None
        if eid:
            _changed()

    _attach()
    unsub_reg = hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _attach)

    def _stop() -> None:
        unsub_reg()
        if state["unsub"]:
            state["unsub"]()

    return _stop
