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
    assert lab is not None and lab.name == "Panel Gym"

    await ws.send_json({"id": 2, "type": "ssv_dashboard/panel/get", "panel": "gym"})
    r = await ws.receive_json()
    assert r["result"]["areas"] == ["gym"] and r["result"]["tabs"] == {"water": False}
    assert r["result"]["runs"] == {}

    # rename keeps the label id
    await ws.send_json({"id": 3, "type": "ssv_dashboard/panels/save", "panel": {**panel, "name": "Fitness"}})
    assert (await ws.receive_json())["success"]
    assert lr.async_get(hass).async_get_label("panel_gym").name == "Panel Fitness"

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


async def test_timers_made_on_save(hass, hass_ws_client):
    assert await async_setup_component(hass, "timer", {})
    await _setup(hass)
    reg = er.async_get(hass)
    wall = reg.async_get_or_create("climate", "test", "wall1", suggested_object_id="bath_wall")
    reg.async_update_entity(wall.entity_id, labels={"heated_wall"})
    ufh = reg.async_get_or_create("climate", "test", "ufh1", suggested_object_id="bed_floor")
    reg.async_update_entity(ufh.entity_id, labels={"ufh"})
    sw = reg.async_get_or_create("switch", "test", "boiler", suggested_object_id="boiler")
    reg.async_update_entity(sw.entity_id, labels={"water", "hot_water"})
    await hass.async_block_till_done()
    # nothing is made until Save
    assert hass.states.get("timer.ssv_wall_bath_wall") is None
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "ssv_dashboard/timers/list"})
    items = {c["key"]: c for c in (await ws.receive_json())["result"]["items"]}
    assert set(items) == {"climate.bath_wall", "climate.bed_floor", "fn:hot_water"}
    assert all(c["new"] and not c["chosen"] for c in items.values())
    assert items["climate.bed_floor"]["kind"] == "ufh"

    await ws.send_json({"id": 2, "type": "ssv_dashboard/timers/save", "timers": {
        "climate.bath_wall": {"runs": [60, 120]}, "climate.bed_floor": {"runs": [30]}, "fn:hot_water": {"runs": [60, 90]}}})
    r = await ws.receive_json()
    assert r["success"], r
    await hass.async_block_till_done()
    assert hass.states.get("timer.ssv_wall_bath_wall").attributes["duration"] == "2:00:00"
    assert hass.states.get("timer.ssv_ufh_bed_floor") is not None
    t = reg.async_get("timer.ssv_water_hot_water")
    assert t is not None and {"water", "hot_water"} <= set(t.labels)

    # the panels get the buttons
    await ws.send_json({"id": 3, "type": "ssv_dashboard/panels/save", "panel": {"id": "bed", "name": "Bedroom 3", "type": "room", "areas": ["bedroom_3"]}})
    assert (await ws.receive_json())["success"]
    await ws.send_json({"id": 4, "type": "ssv_dashboard/panel/get", "panel": "bed"})
    runs = (await ws.receive_json())["result"]["runs"]
    assert runs["climate.bath_wall"] == [60, 120] and runs["fn:hot_water"] == [60, 90]

    # untick + Save removes our timer; seen candidates are no longer "new"
    await ws.send_json({"id": 5, "type": "ssv_dashboard/timers/save", "timers": {"fn:hot_water": {"runs": [60]}}})
    assert (await ws.receive_json())["success"]
    await hass.async_block_till_done()
    assert hass.states.get("timer.ssv_wall_bath_wall") is None
    assert hass.states.get("timer.ssv_water_hot_water") is not None
    await ws.send_json({"id": 6, "type": "ssv_dashboard/timers/list"})
    items = {c["key"]: c for c in (await ws.receive_json())["result"]["items"]}
    assert not items["climate.bath_wall"]["new"] and not items["climate.bath_wall"]["chosen"]


async def test_ufh_timer_turns_off(hass):
    await _setup(hass)
    hvac = async_mock_service(hass, "climate", "set_hvac_mode")
    hass.states.async_set("climate.bed_floor", "heat")
    hass.bus.async_fire("timer.finished", {"entity_id": "timer.ssv_ufh_bed_floor"})
    await hass.async_block_till_done()
    assert hvac and hvac[0].data == {"entity_id": "climate.bed_floor", "hvac_mode": "off"}


async def test_label_style_and_attached_rooms(hass, hass_ws_client):
    reg = lr.async_get(hass)
    old = reg.async_create("T H")  # made by 1.0 / by hand
    assert old.label_id == "t_h"
    await _setup(hass)
    assert reg.async_get_label("t_h").name == "Temperature Humidity"
    assert reg.async_get_label("ac").name == "AC"
    for lab in reg.async_list_labels():
        assert "_" not in lab.name and "·" not in lab.name, lab.name
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "ssv_dashboard/panels/save", "panel": {
        "id": "bedroom_3", "name": "bedroom 3", "type": "room", "areas": ["bedroom_3"],
        "attached": [{"key": "wc", "name": "wc"}, {"key": "shower", "name": "Shower", "area": "shower_3"}]}})
    r = await ws.receive_json()
    assert r["success"], r
    assert r["result"]["labels"] == ["panel_bedroom_3", "panel_bedroom_3_wc", "panel_bedroom_3_shower"]
    assert reg.async_get_label("panel_bedroom_3").name == "Panel Bedroom 3"
    assert reg.async_get_label("panel_bedroom_3_wc").name == "Panel Bedroom 3 WC"


async def test_update_notice(hass, hass_ws_client):
    from homeassistant.components import persistent_notification as pn
    await _setup(hass)
    ereg = er.async_get(hass)
    e = ereg.async_get_or_create("update", "hacs", "123", suggested_object_id="ssv_dashboard_update")
    hass.states.async_set(e.entity_id, "on", {"installed_version": "1.1.0", "latest_version": "1.2.0"})
    await hass.async_block_till_done()
    notes = pn._async_get_or_create_notifications(hass) if hasattr(pn, "_async_get_or_create_notifications") else hass.data.get(pn.DOMAIN, {})
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "ssv_dashboard/info"})
    info = (await ws.receive_json())["result"]["update"]
    assert info == {"entity_id": e.entity_id, "available": True, "installed": "1.1.0", "latest": "1.2.0"}
    assert any("ssv_dashboard_update" in str(k) for k in notes), notes


async def test_room_panel_wc_and_labels_list(hass, hass_ws_client):
    """A room panel always gets Panel <Name> WC; the Labels list shows base and panel labels."""
    await _setup(hass)
    reg = lr.async_get(hass)
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "ssv_dashboard/panels/save", "panel": {
        "id": "master", "name": "Master Bedroom", "type": "room", "areas": ["master"],
        "attached": [{"key": "balcony", "name": "Balcony"}]}})
    r = await ws.receive_json()
    assert r["success"], r
    assert r["result"]["labels"] == ["panel_master", "panel_master_balcony", "panel_master_wc"]
    assert reg.async_get_label("panel_master_wc").name == "Panel Master Bedroom WC"
    ent = er.async_get(hass).async_get_or_create("light", "demo", "wc1", suggested_object_id="master_wc")
    er.async_get(hass).async_update_entity(ent.entity_id, labels={"light", "panel_master_wc"})
    await ws.send_json({"id": 2, "type": "ssv_dashboard/labels/list"})
    r = await ws.receive_json()
    assert r["success"], r
    rows = {x["id"]: x for x in r["result"]["labels"]}
    assert rows["heated_wall"]["name"] == "Heated Wall" and rows["heated_wall"]["group"] == "base" and rows["heated_wall"]["use"]
    assert rows["panel_master_wc"]["group"] == "panel" and rows["panel_master_wc"]["entities"] == 1
    assert rows["panel_master"]["name"] == "Panel Master Bedroom"
    assert rows["light"]["entities"] >= 1


async def test_room_labels_made_with_panel(hass, hass_ws_client):
    """Saving a panel makes the room labels of its areas (id = area id) and lists them."""
    from homeassistant.helpers import area_registry as ar
    await _setup(hass)
    area = ar.async_get(hass).async_create("Bedroom 1")
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "ssv_dashboard/panels/save", "panel": {
        "id": "bedroom_1", "name": "Bedroom 1", "type": "room", "areas": [area.id]}})
    r = await ws.receive_json()
    assert r["success"], r
    assert area.id in r["result"]["labels"]
    assert lr.async_get(hass).async_get_label(area.id).name == "Bedroom 1"
    await ws.send_json({"id": 2, "type": "ssv_dashboard/labels/list"})
    rows = {x["id"]: x for x in (await ws.receive_json())["result"]["labels"]}
    assert rows[area.id]["group"] == "room"


async def test_scene_timing_panels_home_and_run(hass, hass_ws_client, hass_read_only_user):
    """1.3: each device on its own timer, panels and Home chosen by check boxes, run_scene."""
    from datetime import timedelta
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed
    await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/panels/save", "panel": {"id": "living", "name": "Living", "type": "wall"}})
    assert (await client.receive_json())["success"]
    lamp = _light(hass, "lamp", ["scene_device"])
    fan = _light(hass, "fanlight", ["scene_device"])
    applied = async_mock_service(hass, "scene", "apply")
    guest = Context(user_id=hass_read_only_user.id)
    r = await hass.services.async_call(DOMAIN, "save_scene", {
        "name": "Bath", "entities": {lamp: {"state": "on", "brightness": 120}, fan: {"state": "on"}},
        "timing": {lamp: {"delay": 0, "back": 5, "back_to": "off"}, fan: {"delay": 60}},
        "panels": ["living", "nope"], "home": True}, blocking=True, return_response=True, context=guest)
    eid = r["entity_id"]
    labels = set(er.async_get(hass).async_get(eid).labels)
    assert {"scene", "user_scene", "home", "panel_living"} <= labels and "panel_nope" not in labels
    got = await hass.services.async_call(DOMAIN, "get_scene", {"scene": eid}, blocking=True, return_response=True)
    assert got["panels"] == ["living"] and got["home"] is True
    assert got["timing"][lamp]["back"] == 5 and got["timing"][fan]["delay"] == 60

    # names of the panels: any signed-in user (the scene editor on a panel)
    await client.send_json({"id": 2, "type": f"{DOMAIN}/panels/names"})
    assert (await client.receive_json())["result"]["panels"] == [{"id": "living", "name": "Living", "type": "wall"}]

    await hass.services.async_call(DOMAIN, "run_scene", {"entity_id": eid}, blocking=True, return_response=True)
    await hass.async_block_till_done()
    assert [list(c.data["entities"]) for c in applied] == [[lamp]]           # lamp now, fan waits a minute
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61)); await hass.async_block_till_done()
    assert list(applied[-1].data["entities"]) == [fan]
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6)); await hass.async_block_till_done()
    assert applied[-1].data["entities"] == {lamp: {"state": "off"}}          # lamp goes back to off after 5 min

    # untick Home and the panel → labels removed again
    await hass.services.async_call(DOMAIN, "save_scene", {"scene": eid, "name": "Bath", "entities": {lamp: {"state": "on"}},
        "timing": {}, "panels": [], "home": False}, blocking=True, return_response=True, context=guest)
    labels = set(er.async_get(hass).async_get(eid).labels)
    assert "home" not in labels and "panel_living" not in labels
    got = await hass.services.async_call(DOMAIN, "get_scene", {"scene": eid}, blocking=True, return_response=True)
    assert got["timing"] == {}


async def test_ping_loader_and_start_file(hass, hass_client_no_auth, hass_ws_client):
    """1.3: ping.png for the tablet start file, the loader in /config/www/ssv, start.html template."""
    await _setup(hass)
    client = await hass_client_no_auth()
    r = await client.get("/ssv_dashboard/ping.png")
    assert r.status == 200 and r.headers["Content-Type"].startswith("image/png") and r.headers["Access-Control-Allow-Origin"] == "*"
    r = await client.get("/ssv_dashboard/start.html")
    body = await r.text()
    assert r.status == 200 and "__HA__" in body and "ping.png" in body
    assert os.path.exists(hass.config.path("www/ssv/loader.html"))
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": f"{DOMAIN}/info"})
    res = (await ws.receive_json())["result"]
    assert "loader" in res and "internal_url" in res


async def test_label_colours(hass, hass_ws_client):
    """1.3.1: labels get a colour by group; a colour chosen by hand stays."""
    reg = lr.async_get(hass)
    reg.async_create("cctv", color="pink")          # made by hand before SSV
    await _setup(hass)
    assert reg.async_get_label("light").color == "yellow"
    assert reg.async_get_label("ac").color == "orange"
    assert reg.async_get_label("curtain").color == "purple"
    assert reg.async_get_label("scene").color == "green"
    assert reg.async_get_label("water").color == "blue"
    assert reg.async_get_label("home").color == "brown"
    assert reg.async_get_label("cctv").color == "pink"
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/panels/save", "panel": {"id": "gym", "name": "Gym", "type": "wall"}})
    assert (await client.receive_json())["success"]
    assert reg.async_get_label("panel_gym").color == "teal"
    await client.send_json({"id": 2, "type": f"{DOMAIN}/labels/list"})
    rows = {r["id"]: r for r in (await client.receive_json())["result"]["labels"]}
    assert rows["light"]["color"] == "yellow" and rows["panel_gym"]["color"] == "teal"


async def test_relay_floor_heating_thermostat(hass, hass_ws_client):
    """1.4: floor heating on a relay; Make thermostat = HA Generic Thermostat (relay + room sensor)."""
    from homeassistant.helpers import area_registry as ar
    await _setup(hass)
    area = ar.async_get(hass).async_create("Bedroom 2")
    reg = er.async_get(hass)
    relay = reg.async_get_or_create("switch", "test", "ufh_valve", suggested_object_id="bedroom_2_ufh")
    reg.async_update_entity(relay.entity_id, labels={"ufh", "bedroom_2"}, area_id=area.id)
    hass.states.async_set(relay.entity_id, "off")
    sen = reg.async_get_or_create("sensor", "test", "t2", suggested_object_id="bedroom_2_temperature")
    reg.async_update_entity(sen.entity_id, labels={"t_h"}, area_id=area.id)
    hass.states.async_set(sen.entity_id, "20.5", {"device_class": "temperature", "unit_of_measurement": "°C"})
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/thermostats/list"})
    items = (await client.receive_json())["result"]["items"]
    assert items == [{"relay": relay.entity_id, "name": items[0]["name"], "area": area.id, "area_name": "Bedroom 2",
                      "sensors": [sen.entity_id], "thermostat": None}]
    await client.send_json({"id": 2, "type": f"{DOMAIN}/thermostats/make", "relay": relay.entity_id, "sensor": sen.entity_id})
    res = await client.receive_json()
    assert res["success"], res
    climate = res["result"]["climate"]
    await hass.async_block_till_done()
    ce = reg.async_get(climate)
    assert {"climate", "ufh", "bedroom_2"} <= set(ce.labels) and ce.area_id == area.id
    assert "no_panel" in reg.async_get(relay.entity_id).labels
    st = hass.states.get(climate)
    assert st is not None and st.attributes["min_temp"] == 16 and st.attributes["max_temp"] == 28
    # second time: the same thermostat, not a new one
    await client.send_json({"id": 3, "type": f"{DOMAIN}/thermostats/make", "relay": relay.entity_id, "sensor": sen.entity_id})
    assert (await client.receive_json())["result"]["climate"] == climate
    await client.send_json({"id": 4, "type": f"{DOMAIN}/thermostats/list"})
    assert (await client.receive_json())["result"]["items"][0]["thermostat"] == climate


async def test_no_inex_objects_after_start(hass):
    """1.5: timers inex_… are replaced by ssv_… (same duration and labels), user scenes inex_user_… get ssv_user_…."""
    assert await async_setup_component(hass, "timer", {})
    from custom_components.ssv_dashboard.timers import _timer_collection
    coll = _timer_collection(hass)
    await coll.async_create_item({"name": "inex_water_hot_water", "duration": "01:30:00", "restore": True})
    await hass.async_block_till_done()
    reg = er.async_get(hass)
    reg.async_update_entity("timer.inex_water_hot_water", labels={"water", "hot_water"})
    with open(hass.config.path("scenes.yaml"), "w") as f:
        f.write("- id: inex_user_abc\n  name: Evening\n  entities:\n    light.lamp:\n      state: 'on'\n")
    old = reg.async_get_or_create("scene", "homeassistant", "inex_user_abc", suggested_object_id="evening")
    reg.async_update_entity(old.entity_id, labels={"scene", "user_scene", "home"})
    # _setup writes an empty scenes.yaml — do the same steps here without it
    with open(hass.config.path("configuration.yaml"), "w") as f:
        f.write("scene: !include scenes.yaml\n")
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "scene", {})
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={"timer_actions": True})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("timer.inex_water_hot_water") is None
    new = hass.states.get("timer.ssv_water_hot_water")
    assert new is not None and new.attributes["duration"] == "1:30:00"
    assert {"water", "hot_water"} <= set(reg.async_get("timer.ssv_water_hot_water").labels)
    assert "inex" not in open(hass.config.path("scenes.yaml")).read()
    ent = reg.async_get(old.entity_id)
    assert ent.unique_id == "ssv_user_abc" and "home" in ent.labels
