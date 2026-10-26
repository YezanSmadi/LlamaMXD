# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Brand palettes, contrast helpers and settings.json read/write, with no UI toolkit
(`ui/theme.py` builds the live palette and stylesheet on top)."""
import json
import os

from core import keybinds, llamalog, naming, power, priority, startup_tab, userdata, window_mode

# settings.json: beside main.py from source, the user's data folder once installed.
_SETTINGS_PATH = userdata.user_file("settings.json")

DEFAULT_THEME_NAME = "Lemon"

# Each theme is a primary (the brand accent: sidebar, action buttons, tab pipe, queued rows,
# progress) and a secondary (every other control). Flat hex strings, so appearance mode never
# changes them. Hovers are derived (`_darken`) except Lemon's historical primary hover.
THEMES = {
    "Lemon": {"primary": "#FDCA3C", "primary_hover": "#e0b234", "secondary": "#3B8ED0"},
    "Cupid": {"primary": "#FA6E99", "secondary": "#780219"},
    "Lilac": {"primary": "#a58fd7", "secondary": "#3e6d04"},
    "Ranger": {"primary":"#F98524", "secondary": "#104E4B" },
    "Noir": {"primary": "#131317", "secondary": "#5A5B63"}, 
    "Luck": {"primary": "#ADBCDE", "secondary": "#0E5914"},
    "Vaporwave": {"primary": "#3B41B8", "secondary": "#ED72D4"},
    "Dreamsicle": {"primary": "#f9be90", "secondary": "#f97c9c"},
    "Funk": {"primary": "#3dbcc1", "secondary": "#4b3383", "sidebar_text": "white",
             "sidebar_footer_text": "white"},
    # The sidebar title/logo/footer and the selected sub-tab take the green; black's derived hover
    # is black again, so it names a visible one.
    "Terminal": {"primary": "#000000", "primary_hover": "#1c1c1c", "secondary": "#44fe2c",
                 "sidebar_text": "secondary", "sidebar_footer_text": "secondary",
                 "swap_subtabs": True, "swap_action_buttons": True},
}


# The destructive / halting red (Stop Queue, Strip, failed rows); never changes with the theme.
STOP_RED = "#E5484D"
STOP_RED_HOVER = "#C93C40"


def _darken(hex_color, factor=0.87):
    """A slightly darker shade of `hex_color` for hover (~0.87, as in Lemon's own hover)."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = (max(0, min(255, int(channel * factor))) for channel in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def _relative_luminance(hex_color):
    """WCAG 2.x relative luminance of an "#rrggbb" color, in [0, 1]."""
    hex_color = hex_color.lstrip("#")
    channels = (int(hex_color[i:i + 2], 16) / 255 for i in (0, 2, 4))
    linear = [
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def readable_text_on(hex_color):
    """"black" or "white", whichever has the higher WCAG contrast against `hex_color`."""
    lum = _relative_luminance(hex_color)
    contrast_black = (lum + 0.05) / 0.05
    contrast_white = 1.05 / (lum + 0.05)
    return "black" if contrast_black >= contrast_white else "white"


def _gray_hex_for_luminance(lum):
    """The neutral grey hex with relative luminance `lum` (the WCAG formula inverted)."""
    lum = max(0.0, min(1.0, lum))
    channel = lum * 12.92 if lum <= 0.0031308 else 1.055 * (lum ** (1 / 2.4)) - 0.055
    value = max(0, min(255, round(channel * 255)))
    return f"#{value:02x}{value:02x}{value:02x}"


def disabled_text_on(hex_color, target_ratio=3.0):
    """A disabled-text grey for a control that keeps its accent fill: solved to hit
    `target_ratio` against `hex_color`, on the side `readable_text_on` would pick. 3.0 is WCAG's
    UI-component minimum; 4.5 read as enabled text, and a fixed grey vanished on mid-brightness
    accents (~1.1:1)."""
    lum = _relative_luminance(hex_color)
    contrast_black = (lum + 0.05) / 0.05
    contrast_white = 1.05 / (lum + 0.05)
    if contrast_black >= contrast_white:
        target_lum = (lum + 0.05) / target_ratio - 0.05
    else:
        target_lum = target_ratio * (lum + 0.05) - 0.05
    return _gray_hex_for_luminance(target_lum)


def get_theme(name=None):
    """The full palette for a theme (the default for an unknown name): the stored colours plus
    derived `*_text` colours. `sidebar_text` (the sidebar title and logo) and `sidebar_footer_text`
    (its copyright / version line) are `primary_text` unless the theme names one, as a colour or
    "primary"/"secondary". `subtab_active` /
    `subtab_inactive` (+ `_hover`, `_text`) are primary / secondary, swapped for a theme with
    `swap_subtabs`."""
    colors = THEMES.get(name, THEMES[DEFAULT_THEME_NAME])
    primary_text = readable_text_on(colors["primary"])
    palette = {
        "primary": colors["primary"],
        "primary_hover": colors.get("primary_hover") or _darken(colors["primary"]),
        "primary_text": primary_text,
        "primary_disabled_text": disabled_text_on(colors["primary"]),
        "secondary": colors["secondary"],
        "secondary_hover": colors.get("secondary_hover") or _darken(colors["secondary"]),
        "secondary_text": readable_text_on(colors["secondary"]),
        "secondary_disabled_text": disabled_text_on(colors["secondary"]),
    }
    sidebar_text = colors.get("sidebar_text") or primary_text
    palette["sidebar_text"] = palette[sidebar_text] if sidebar_text in ("primary", "secondary") else sidebar_text
    footer_text = colors.get("sidebar_footer_text") or primary_text
    palette["sidebar_footer_text"] = palette[footer_text] if footer_text in ("primary", "secondary") else footer_text
    active, inactive = ("secondary", "primary") if colors.get("swap_subtabs") else ("primary", "secondary")
    for role, source in (("subtab_active", active), ("subtab_inactive", inactive)):
        for suffix in ("", "_hover", "_text"):
            palette[role + suffix] = palette[source + suffix]
    return palette


def default_output_dir():
    """The out-of-the-box export folder, `~/Videos/LlamaMXD Export` (MainWindow creates it)."""
    return os.path.join(os.path.expanduser("~"), "Videos", "LlamaMXD Export")


def load_settings():
    """Read settings.json, with defaults for anything missing (or no file yet); a stored value
    that is no longer valid (a hand-edited file) falls back to its default."""
    settings = {
        "theme": DEFAULT_THEME_NAME,
        "appearance_mode": "System",
        "default_save_location": default_output_dir(),
        "gpu_enabled": True,
        "downloader_separate_save": False,
        "downloader_save_location": "",
        "naming_template": naming.DEFAULT_TEMPLATE,
        "when_done": power.DO_NOTHING,
        "when_done_reset": True,
        "priority_level": priority.DEFAULT_LEVEL,
        "window_mode": window_mode.DEFAULT_MODE,
        "borderless_fullscreen": False,
        "startup_tab": startup_tab.DEFAULT_TAB,
        "log_detail": llamalog.DEFAULT_LEVEL,
        "keybinds": keybinds.defaults(),
        "confirm_clear_selection": True,
    }
    if not os.path.exists(_SETTINGS_PATH):
        return settings
    try:
        with open(_SETTINGS_PATH, "r") as f:
            settings.update(json.load(f))
    except (json.JSONDecodeError, OSError) as exc:
        llamalog.get("settings").warning("settings.json couldn't be read (%s); using the defaults", exc)
    if naming.template_error(settings["naming_template"]):
        settings["naming_template"] = naming.DEFAULT_TEMPLATE
    if settings["when_done"] not in power.ACTIONS:
        settings["when_done"] = power.DO_NOTHING
    if settings["priority_level"] not in priority.LEVELS:
        settings["priority_level"] = priority.DEFAULT_LEVEL
    if settings["window_mode"] not in window_mode.MODES:
        settings["window_mode"] = window_mode.DEFAULT_MODE
    if settings["startup_tab"] not in startup_tab.TABS:
        settings["startup_tab"] = startup_tab.DEFAULT_TAB
    if settings["log_detail"] not in llamalog.LEVELS:
        settings["log_detail"] = llamalog.DEFAULT_LEVEL
    settings["borderless_fullscreen"] = settings["borderless_fullscreen"] is True
    settings["keybinds"] = keybinds.normalize(settings["keybinds"])
    return settings


def save_settings(settings):
    """Persists app settings to disk as JSON."""
    with open(_SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)
