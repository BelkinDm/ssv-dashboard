"""Tests for SSV Dashboard: setup, files, labels, scenes, timers, websocket."""
import os

from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er, label_registry as lr
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.ssv_dashboard.const import DOMAIN, LABELS


async def _setup(hass: HomeAssistant):
    with open(hass.config.path("configuration.yaml"), "w") as f:
        f.write("scene: !include scenes.yaml\n")
    with open(hass.config.path("scenes.yaml"), "w") as f:
        f.write("[]\n")
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "scene", {})
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={"timer_actions": True})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_labels_sensor_panel(hass, hass_client_no_auth):
    entry = await _setup(hass)
    reg = lr.async_get(hass)
    for lid in LABELS:
        assert reg.async_get_label(lid) is not None, lid
    st = hass.states.get("sensor.ssv_time")
    assert st is not None and "T" in st.state
    assert "ssv-setup" in hass.data["frontend_panels"]

    client = await hass_client_no_auth()
    r = await client.get("/ssv_dashboard/panel.html")
    assert r.status == 200
    body = await r.text()
    ver = hass.data[DOMAIN]["version"]
    assert f"const BUILD = '{ver}';" in body
    assert r.headers["Cache-Control"] == "no-cache"
    r2 = await client.get("/ssv_dashboard/panel.html", headers={"If-None-Match": r.headers["ETag"]})
    assert r2.status == 304
    for f in ("room.html", "phone.html"):
        assert (await client.get("/ssv_dashboard/" + f)).status == 200
    js = await (await client.get("/ssv_dashboard/setup.js")).text()
    assert ver in js and "__SSV_VERSION__" not in js
    assert (await client.get("/ssv_dashboard/..%2Fmanifest.json")).status in (400, 404)
    assert (await client.get("/ssv_dashboard/secret.txt")).status == 404

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert "ssv-setup" not in hass.data["frontend_panels"]
    assert not hass.services.has_service(DOMAIN, "save_scene")
    # reload works (view registered only once)
    assert await hass.config_entries.async_setup(entry.entry_id)


async def test_ws_info_and_labels(hass, hass_ws_client):
    await _setup(hass)
    reg = lr.async_get(hass)
    reg.async_delete("curtain")
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "ssv_dashboard/info"})
    r = await ws.receive_json()
    assert r["success"] and r["result"]["labels"]["curtain"] is False
    await ws.send_json({"id": 2, "type": "ssv_dashboard/create_labels"})
    r = await ws.receive_json()
    assert r["success"] and r["result"]["created"] == ["curtain"]


def _light(hass, name, labels):
    reg = er.async_get(hass)
    e = reg.async_get_or_create("light", "test", name, suggested_object_id=name)
    reg.async_update_entity(e.entity_id, labels=set(labels))
    hass.states.async_set(e.entity_id, "off", {"supported_color_modes": ["brightness"]})
    return e.entity_id


async def test_user_scenes(hass, hass_admin_user, hass_read_only_user):
    await _setup(hass)
    lamp = _light(hass, "lamp", ["scene_device"])
    pump = _light(hass, "pump", [])
    guest = Context(user_id=hass_read_only_user.id)

    # not labelled → refused
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "save_scene", {"name": "x", "entities": {pump: {"state": "on"}}},
                                       blocking=True, return_response=True, context=guest)
    # bad value → refused
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "save_scene", {"name": "x", "entities": {lamp: {"state": "on", "brightness": 999}}},
                                       blocking=True, return_response=True, context=guest)

    r = await hass.services.async_call(DOMAIN, "save_scene", {"name": "Movie", "entities": {lamp: {"state": "on", "brightness": 80}}},
                                       blocking=True, return_response=True, context=guest)
    eid = r["entity_id"]
    assert eid and eid.startswith("scene.") and r["id"].startswith("ssv_user_")
    ent = er.async_get(hass).async_get(eid)
    assert {"scene", "user_scene"} <= set(ent.labels)
    got = await hass.services.async_call(DOMAIN, "get_scene", {"scene": eid}, blocking=True, return_response=True)
    assert got["entities"][lamp] == {"state": "on", "brightness": 80}

    # another non-admin cannot delete it
    from homeassistant.auth.models import User  # noqa
    other = await hass.auth.async_create_user("other", group_ids=["system-users"])
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "delete_scene", {"scene": eid}, blocking=True, return_response=True,
                                       context=Context(user_id=other.id))
    # admin can
    await hass.services.async_call(DOMAIN, "delete_scene", {"scene": eid}, blocking=True, return_response=True,
                                   context=Context(user_id=hass_admin_user.id))
    await hass.async_block_till_done()
    assert er.async_get(hass).async_get(eid) is None
    assert open(hass.config.path("scenes.yaml")).read().strip() == "[]"
    assert os.path.exists(hass.config.path("scenes.yaml.ssv_bak"))


async def test_installer_scene_untouchable(hass):
    await _setup(hass)
    reg = er.async_get(hass)
    e = reg.async_get_or_create("scene", "homeassistant", "installer_1", suggested_object_id="welcome")
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "delete_scene", {"scene": e.entity_id}, blocking=True, return_response=True)


async def test_timers(hass):
    await _setup(hass)
    hvac = async_mock_service(hass, "climate", "set_hvac_mode")
    off = async_mock_service(hass, "homeassistant", "turn_off")
    wh_off = async_mock_service(hass, "water_heater", "turn_off")
    hass.states.async_set("climate.wall_bed1", "heat")
    hass.bus.async_fire("timer.finished", {"entity_id": "timer.inex_wall_wall_bed1"})
    await hass.async_block_till_done()
    assert hvac and hvac[0].data == {"entity_id": "climate.wall_bed1", "hvac_mode": "off"}

    reg = er.async_get(hass)
    def mk(domain, oid, labels, state="on"):
        e = reg.async_get_or_create(domain, "test", oid, suggested_object_id=oid)
        reg.async_update_entity(e.entity_id, labels=set(labels))
        hass.states.async_set(e.entity_id, state)
        return e.entity_id
    t = mk("timer", "hw", ["water", "hot_water"], "idle")
    sw = mk("switch", "boiler", ["water", "hot_water"])
    wh = mk("water_heater", "tank", ["water", "hot_water"])
    mk("switch", "pump", ["water", "recirculation"])
    hass.bus.async_fire("timer.finished", {"entity_id": t})
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in off] == [sw]
    assert [c.data["entity_id"] for c in wh_off] == [wh]


# ---------------------------------------------------------------- 1.1
async def test_panels_and_labels(hass, hass_ws_client, hass_read_only_user):
    await _setup(hass)
    ws = await hass_ws_client(hass)
    panel = {"id": "gym", "name": "Gym", "type": "wall", "purpose": "gym", "areas": ["gym"],
             "tabs": {"water": False}, "night": {"enabled": False}}
    await ws.send_json({"id": 1, "type": "ssv_dashboard/panels/save", "panel": panel})
    r = await ws.receive_json()
    assert r["success"], r
    assert r["result"]["label"] == "panel_gym"
    lab = lr.async_get(hass).async_get_label("panel_gym")
    assert lab is not None and lab.name == "Panel · Gym"

    await ws.send_json({"id": 2, "type": "ssv_dashboard/panel/get", "panel": "gym"})
    r = await ws.receive_json()
    assert r["result"]["areas"] == ["gym"] and r["result"]["tabs"] == {"water": False}
    assert r["result"]["runs"]["wall"] == 180

    # rename keeps the label id
    await ws.send_json({"id": 3, "type": "ssv_dashboard/panels/save", "panel": {**panel, "name": "Fitness"}})
    assert (await ws.receive_json())["success"]
    assert lr.async_get(hass).async_get_label("panel_gym").name == "Panel · Fitness"

    # bad id refused
    await ws.send_json({"id": 4, "type": "ssv_dashboard/panels/save", "panel": {**panel, "id": "Bad Id"}})
    assert not (await ws.receive_json())["success"]

    await ws.send_json({"id": 5, "type": "ssv_dashboard/panels/list"})
    r = await ws.receive_json()
    assert [p["id"] for p in r["result"]["panels"]] == ["gym"]

    await ws.send_json({"id": 6, "type": "ssv_dashboard/info"})
    r = await ws.receive_json()
    keys = {c["key"]: c["ok"] for c in r["result"]["checks"]}
    assert keys["scene_yaml"] is True and keys["scheduler"] is False


async def test_timers_follow_labels(hass, hass_ws_client):
    assert await async_setup_component(hass, "timer", {})
    await _setup(hass)
    reg = er.async_get(hass)
    e = reg.async_get_or_create("climate", "test", "wall1", suggested_object_id="bath_wall")
    reg.async_update_entity(e.entity_id, labels={"heated_wall"})
    sw = reg.async_get_or_create("switch", "test", "boiler", suggested_object_id="boiler")
    reg.async_update_entity(sw.entity_id, labels={"water", "hot_water"})
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "ssv_dashboard/runs/save", "runs": {"wall": 120, "per": {}}})
    assert (await ws.receive_json())["success"]
    await ws.send_json({"id": 2, "type": "ssv_dashboard/sync_timers"})
    r = await ws.receive_json()
    await hass.async_block_till_done()
    assert hass.states.get("timer.inex_wall_bath_wall") is not None, r
    assert hass.states.get("timer.inex_wall_bath_wall").attributes["duration"] == "2:00:00"
    t = reg.async_get("timer.inex_water_hot_water")
    assert t is not None and {"water", "hot_water"} <= set(t.labels)

    # label removed -> its timer goes; a hand-made timer stays
    reg.async_update_entity(e.entity_id, labels=set())
    await ws.send_json({"id": 3, "type": "ssv_dashboard/sync_timers"})
    await ws.receive_json()
    await hass.async_block_till_done()
    assert hass.states.get("timer.inex_wall_bath_wall") is None
    assert hass.states.get("timer.inex_water_hot_water") is not None
