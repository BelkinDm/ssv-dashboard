"""Constants for SSV Dashboard."""
from __future__ import annotations

DOMAIN = "ssv_dashboard"
NAME = "SSV Dashboard"

# Files served from custom_components/ssv_dashboard/www at /ssv_dashboard/<file>
STATIC_URL = "/ssv_dashboard"
STATIC_FILES = ("panel.html", "room.html", "phone.html", "setup.js")

# Admin sidebar page (installer tools)
SETUP_PANEL = "ssv-setup"

# ---------------------------------------------------------------- labels
# label_id: (name, icon). Ids are what the panels look for; names are what the
# installer sees in Settings → Labels. Home Assistant derives the id from the
# name, so every name below slugifies to its id.
LABELS: dict[str, tuple[str, str]] = {
    "light": ("Light", "mdi:lightbulb"),
    "on_off_only": ("On Off Only", "mdi:toggle-switch"),
    "climate": ("Climate", "mdi:thermostat"),
    "ac": ("AC", "mdi:air-conditioner"),
    "ufh": ("UFH", "mdi:heating-coil"),
    "heated_wall": ("Heated Wall", "mdi:wall"),
    "t_h": ("T H", "mdi:thermometer-water"),
    "curtain": ("Curtain", "mdi:curtains"),
    "net": ("Net", "mdi:curtains"),
    "blackout": ("Blackout", "mdi:curtains-closed"),
    "roller": ("Roller", "mdi:roller-shade"),
    "shutter": ("Shutter", "mdi:window-shutter"),
    "left": ("Left", "mdi:arrow-left"),
    "right": ("Right", "mdi:arrow-right"),
    "both_side": ("Both Side", "mdi:arrow-left-right"),
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

# ---------------------------------------------------------------- user scenes
SCENES_FILE = "scenes.yaml"
ID_PREFIX = "ssv_user_"
LEGACY_PREFIXES = ("inex_user_",)  # scenes made with the old inex_scenes integration
DEVICE_LABEL = "scene_device"
SCENE_LABELS = ("scene", "user_scene")
MAX_SCENES = 40
MAX_ENTITIES = 40
STORE_KEY = f"{DOMAIN}.scenes"
STORE_VERSION = 1

# ---------------------------------------------------------------- timers
# Heated wall: timer.<prefix>wall_<climate object id>  → climate off when it ends
# Water:       timer with labels "water" + <function>  → that function off when it ends
TIMER_PREFIXES = ("inex_", "ssv_")
WATER_FUNCTIONS = ("hot_water", "recirculation")
WATER_CONTROL_DOMAINS = ("switch", "fan", "water_heater", "input_boolean")

CONF_TIMER_ACTIONS = "timer_actions"
