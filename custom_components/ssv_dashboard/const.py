"""Constants for SSV Dashboard."""
from __future__ import annotations

DOMAIN = "ssv_dashboard"
NAME = "SSV Dashboard"

# Files served from custom_components/ssv_dashboard/www at /ssv_dashboard/<file>
STATIC_URL = "/ssv_dashboard"
STATIC_FILES = ("panel.html", "room.html", "phone.html", "setup.js", "loader.html", "start.html")
LOADER_DIR = "www/ssv"            # /config/www/ssv/loader.html, served by HA itself at /local/ssv/loader.html
LOADER_URL = "/local/ssv/loader.html"

# Admin sidebar page (installer tools)
SETUP_PANEL = "ssv-setup"

# ---------------------------------------------------------------- labels
# label_id: (name, icon). Ids are what the panels look for; names are what the
# installer sees in Settings → Labels, all in one style (see labels.py).
LABELS: dict[str, tuple[str, str]] = {
    "light": ("Light", "mdi:lightbulb"),
    "on_off_only": ("On Off Only", "mdi:toggle-switch"),
    "climate": ("Climate", "mdi:thermostat"),
    "ac": ("AC", "mdi:air-conditioner"),
    "ufh": ("UFH", "mdi:heating-coil"),
    "heated_wall": ("Heated Wall", "mdi:wall"),
    "t_h": ("Temperature Humidity", "mdi:thermometer-water"),
    "curtain": ("Curtain", "mdi:curtains"),
    "net": ("Net", "mdi:curtains"),
    "blackout": ("Blackout", "mdi:curtains-closed"),
    "roller": ("Roller", "mdi:roller-shade"),
    "shutter": ("Shutter", "mdi:window-shutter"),
    "left": ("Left", "mdi:arrow-left"),
    "right": ("Right", "mdi:arrow-right"),
    "both_side": ("Both Sides", "mdi:arrow-left-right"),
    "scene": ("Scene", "mdi:palette"),
    "scene_device": ("Scene Device", "mdi:palette-outline"),
    "user_scene": ("User Scene", "mdi:account-star"),
    "home": ("Home", "mdi:home"),
    "water": ("Water", "mdi:water"),
    "hot_water": ("Hot Water", "mdi:water-boiler"),
    "recirculation": ("Recirculation", "mdi:pump"),
    "valve": ("Valve", "mdi:valve"),
    "water_meter": ("Water Meter", "mdi:water-pump"),
    "schedule": ("Schedule", "mdi:calendar-clock"),
    "cctv": ("CCTV", "mdi:cctv"),
    "alarm": ("Alarm", "mdi:shield-home"),
    "critical": ("Critical", "mdi:alert"),
    "doorbell": ("Doorbell", "mdi:doorbell"),
    "no_panel": ("No Panel", "mdi:eye-off"),
}

# Label colours by group (Home Assistant's label colours), so Settings → Labels reads at a glance.
# Set when a label has no colour yet; a colour chosen by hand is kept.
LABEL_GROUP_COLOR: dict[str, tuple[str, tuple[str, ...]]] = {
    "lights":   ("yellow", ("light", "on_off_only")),
    "climate":  ("orange", ("climate", "ac", "ufh", "heated_wall", "t_h")),
    "curtains": ("purple", ("curtain", "net", "blackout", "roller", "shutter", "left", "right", "both_side")),
    "scenes":   ("green", ("scene", "scene_device", "user_scene")),
    "water":    ("blue", ("water", "hot_water", "recirculation", "valve", "water_meter")),
    "schedule": ("indigo", ("schedule",)),
    "security": ("red", ("cctv", "alarm", "critical", "doorbell")),
    "service":  ("brown", ("home", "no_panel")),
}
LABEL_COLOR: dict[str, str] = {lid: color for color, ids in LABEL_GROUP_COLOR.values() for lid in ids}
PANEL_LABEL_COLOR = "teal"      # Panel <Name>, Panel <Name> <Room>
ROOM_LABEL_COLOR = "grey"       # <Room> labels made for the areas of the panels

# What each label does — shown in the Labels list at the bottom of the SSV Dashboard page
LABEL_USE: dict[str, str] = {
    "light": "Lights shown on the panels (also a switch that drives a light)",
    "on_off_only": "Dimmable light shown as a plain On / Off switch",
    "climate": "Climate tab: room thermostats",
    "ac": "Air conditioners (with fan speed buttons on room panels)",
    "ufh": "Floor heating: a climate, or a relay / valve (On / Off; with a room sensor SSV makes a thermostat); can get Run buttons",
    "heated_wall": "Heated walls; can get Run buttons",
    "t_h": "Temperature / humidity sensors for the room header",
    "curtain": "Curtains",
    "net": "Curtain look: sheer",
    "blackout": "Curtain look: blackout",
    "roller": "Roller blinds",
    "shutter": "Shutters",
    "left": "Curtain opens to the left",
    "right": "Curtain opens to the right",
    "both_side": "Curtain opens to both sides",
    "scene": "Ready scenes (script.* shown as a scene)",
    "scene_device": "Devices people may use in their own user scenes",
    "user_scene": "Put by SSV on user scenes (made on the panels)",
    "home": "Light or tile picked for the Home page; on a scene — a scene button on Home of the 10″ panels",
    "water": "Water tab (together with a function label)",
    "hot_water": "Water function: hot water / boiler; can get Run buttons",
    "recirculation": "Water function: recirculation; can get Run buttons",
    "valve": "Water function: main valves",
    "water_meter": "Water function: meters",
    "schedule": "Devices offered on the Schedule tab",
    "cctv": "Cameras on the Cameras tab",
    "alarm": "Alarm panel on the Security tab",
    "critical": "Leak / smoke / gas sensors: alert on every panel",
    "doorbell": "Intercom device (and its camera)",
    "no_panel": "Never shown on any panel",
}

# ---------------------------------------------------------------- user scenes
SCENES_FILE = "scenes.yaml"
ID_PREFIX = "ssv_user_"
LEGACY_PREFIXES = ("inex_user_",)  # scenes made before 1.5 — renamed to ssv_user_ at start
DEVICE_LABEL = "scene_device"
SCENE_LABELS = ("scene", "user_scene")
MAX_SCENES = 40
MAX_ENTITIES = 40
STORE_KEY = f"{DOMAIN}.scenes"
STORE_VERSION = 1

# ---------------------------------------------------------------- timers
# Heated wall: timer.<prefix>wall_<climate object id>  → climate off when it ends
# Water:       timer with labels "water" + <function>  → that function off when it ends
TIMER_PREFIXES = ("ssv_", "inex_")   # inex_: timers from before 1.5 that are still running
# Run timers chosen on the SSV Dashboard page: key -> timer object id
#   climate.<x> labelled Heated Wall -> ssv_wall_<x>;  climate/switch.<x> labelled UFH -> ssv_ufh_<x>
#   fn:hot_water / fn:recirculation   -> ssv_water_<fn> (labelled Water + <fn>)
WATER_FUNCTIONS = ("hot_water", "recirculation")
WATER_CONTROL_DOMAINS = ("switch", "fan", "water_heater", "input_boolean")

CONF_TIMER_ACTIONS = "timer_actions"
CONF_NOTIFY = "notify_service"
