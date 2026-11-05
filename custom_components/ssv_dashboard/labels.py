"""Labels in one style.

Name: every word starts with a capital letter, words are separated by spaces, no "_",
"·", "&" or other signs; abbreviations stay in capitals (AC, UFH, CCTV, WC).
Id: made by Home Assistant from the name (heated_wall, panel_bedroom_3_wc) and never
typed by hand. A label is first created under a name that gives the wanted id, then
renamed — the id stays, so labels already on devices keep working.
"""
from __future__ import annotations

import logging
import re

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import label_registry as lr
from homeassistant.util import slugify

from .const import LABEL_COLOR, LABELS

_LOGGER = logging.getLogger(__name__)
ABBR = {"ac", "ufh", "cctv", "wc", "tv", "ups", "ev", "hvac", "led", "rgb", "spa", "bbq", "id"}


def nice(text: str) -> str:
    """'bedroom_3 wc' -> 'Bedroom 3 WC'; 'master-bathroom' -> 'Master Bathroom'."""
    words = [w for w in re.split(r"[\s_\-·&/]+", str(text or "")) if w]
    return " ".join(w.upper() if w.lower() in ABBR else (w[:1].upper() + w[1:]) for w in words)


@callback
def ensure_label(hass: HomeAssistant, label_id: str, name: str, icon: str | None = None, color: str | None = None) -> str | None:
    """Make sure label <label_id> exists and is called <name>. Returns the id, or None if impossible."""
    reg = lr.async_get(hass)
    entry = reg.async_get_label(label_id)
    if entry is None:
        seed = " ".join(label_id.split("_"))  # slugifies back to label_id
        if slugify(seed) != label_id:
            _LOGGER.warning("Label id %s cannot be made", label_id)
            return None
        clash = reg.async_get_label_by_name(seed)
        if clash is not None:
            _LOGGER.warning("Label %s not created: name %s is taken by %s", label_id, seed, clash.label_id)
            return None
        entry = reg.async_create(seed, icon=icon, color=color)
        if entry.label_id != label_id:  # someone else holds the id-like name
            _LOGGER.warning("Label %s got id %s", label_id, entry.label_id)
            return entry.label_id
    if entry.name != name:
        other = reg.async_get_label_by_name(name)
        if other is None or other.label_id == entry.label_id:
            reg.async_update(entry.label_id, name=name)
        else:
            _LOGGER.warning("Label %s keeps its name: %s is used by %s", label_id, name, other.label_id)
    if color and not entry.color:  # a colour chosen by hand stays
        reg.async_update(entry.label_id, color=color)
    return entry.label_id


@callback
def ensure_base_labels(hass: HomeAssistant) -> list[str]:
    """All labels the panels read, created and named in the one style. Returns ids created."""
    reg = lr.async_get(hass)
    made: list[str] = []
    for label_id, (name, icon) in LABELS.items():
        existed = reg.async_get_label(label_id) is not None
        if ensure_label(hass, label_id, name, icon, LABEL_COLOR.get(label_id)) and not existed:
            made.append(label_id)
    return made
