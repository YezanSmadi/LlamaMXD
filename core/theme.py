"""Brand palettes, contrast helpers, and the settings.json read/write.

UI-toolkit-free: `ui/theme.py` builds the live PySide6 palette and stylesheet
on top of what's here."""
import json
import os

# Repo root, derived from this file's own location — settings.json always
# lands next to main.py whatever directory the app was launched from.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SETTINGS_PATH = os.path.join(_REPO_ROOT, "settings.json")

DEFAULT_THEME_NAME = "Lemon"

# Each theme is a primary (brand accent — sidebar, drop box border, the "do
# it now" buttons, the active-tab pipe, queued rows, and the progress fill)
# and a secondary (every other button, dropdown, checkbox, switch, slider).
# Colors are flat hex strings, not (light, dark) pairs — deliberately, so
# switching appearance mode never changes a theme's colours. Hover shades are
# auto-derived (see _darken) except Lemon's primary hover, kept as its exact
# historical value.
THEMES = {
    "Lemon": {"primary": "#FDCA3C", "primary_hover": "#e0b234", "secondary": "#3B8ED0"},
    "Cupid": {"primary": "#FA6E99", "secondary": "#780219"},
    "Lilac": {"primary": "#a58fd7", "secondary": "#3e6d04"},
    "Ranger": {"primary":"#F98524", "secondary": "#104E4B" },
    "Noir": {"primary": "#131317", "secondary": "#5A5B63"},
    "Luck": {"primary": "#ADBCDE", "secondary": "#0E5914"},
    "Vaporwave": {"primary": "#3B41B8", "secondary": "#ED72D4"}
}


# The "destructive / halting" red — the Stop Queue button's fill, and the
# Strip Video checkbox on the Encoding tab. A permanent, theme-independent
# exception to the primary/secondary scheme (see CLAUDE.md): it never changes
# with the theme, so anything that needs "this is destructive" red reads it
# from here rather than the active palette.
STOP_RED = "#E5484D"
STOP_RED_HOVER = "#C93C40"


def _darken(hex_color, factor=0.87):
    """Returns a slightly-darker shade of hex_color for hover states —
    the same ~0.87 factor already implicit in the brand yellow's existing
    hover (#FDCA3C -> #e0b234)."""
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
    """Returns "black" or "white" — whichever has the higher WCAG contrast
    ratio against hex_color. This is what lets every theme's primary/
    secondary color carry legible text without a hand-picked per-theme text
    color: pale primaries (Lemon's yellow, Cupid's pink) get black text,
    and a near-black primary like Noir's #131317 gets white instead."""
    lum = _relative_luminance(hex_color)
    contrast_black = (lum + 0.05) / 0.05
    contrast_white = 1.05 / (lum + 0.05)
    return "black" if contrast_black >= contrast_white else "white"


def _gray_hex_for_luminance(lum):
    """Inverse of the WCAG relative-luminance formula for a neutral grey
    (equal R=G=B), rounded to the nearest hex channel value."""
    lum = max(0.0, min(1.0, lum))
    channel = lum * 12.92 if lum <= 0.0031308 else 1.055 * (lum ** (1 / 2.4)) - 0.055
    value = max(0, min(255, round(channel * 255)))
    return f"#{value:02x}{value:02x}{value:02x}"


def disabled_text_on(hex_color, target_ratio=3.0):
    """A "greyed out" text color that still stays legible on `hex_color` —
    the label of a disabled button or dropdown, which keeps its accent fill.
    A fixed grey reads fine against a very dark or very light accent, but on
    a mid-brightness one — Lemon's `#3B8ED0` secondary, Vaporwave's
    `#ED72D4` — it sits close enough in brightness to nearly vanish
    (confirmed: WCAG contrast ~1.1-1.2 for a stock gray74/gray60).

    Rather than a single fixed grey, this solves for the grey brightness that
    hits `target_ratio` against this *specific* color, on whichever side
    (darker or lighter) already has more contrast headroom (the same side
    `readable_text_on` would pick) — so it's still a genuine desaturated
    grey, and only pushes as far toward black/white as this background
    actually needs to stay readable, rather than every theme sharing one
    compromise value that only fits some of them.

    `target_ratio` defaults to 3.0 — WCAG's own minimum for non-text/UI-
    component contrast (SC 1.4.11), deliberately looser than the 4.5 used
    for real body text. 4.5 was tried first and read as too dark/light —
    on Lemon's blue in particular the disabled dropdown text came out close
    enough to solid black to look like ordinary enabled text rather than a
    greyed-out control, i.e. readable but no longer visibly *disabled*. 3.0
    is enough to fix a near-invisible fixed grey (~1.1:1 on Lemon/
    Vaporwave) while keeping a genuine mid-grey, disabled-looking
    result rather than one that reads as full-contrast text."""
    lum = _relative_luminance(hex_color)
    contrast_black = (lum + 0.05) / 0.05
    contrast_white = 1.05 / (lum + 0.05)
    if contrast_black >= contrast_white:
        target_lum = (lum + 0.05) / target_ratio - 0.05
    else:
        target_lum = target_ratio * (lum + 0.05) - 0.05
    return _gray_hex_for_luminance(target_lum)


def get_theme(name=None):
    """Returns the full color palette for a theme name — primary/
    primary_hover/primary_text/secondary/secondary_hover/secondary_text —
    falling back to the default theme for an unknown or missing name. The
    *_text entries are derived (see readable_text_on), not stored in THEMES,
    so adding a palette never needs a matching text color hand-picked."""
    colors = THEMES.get(name, THEMES[DEFAULT_THEME_NAME])
    return {
        "primary": colors["primary"],
        "primary_hover": colors.get("primary_hover") or _darken(colors["primary"]),
        "primary_text": readable_text_on(colors["primary"]),
        "primary_disabled_text": disabled_text_on(colors["primary"]),
        "secondary": colors["secondary"],
        "secondary_hover": colors.get("secondary_hover") or _darken(colors["secondary"]),
        "secondary_text": readable_text_on(colors["secondary"]),
        "secondary_disabled_text": disabled_text_on(colors["secondary"]),
    }


def default_output_dir():
    """The out-of-the-box export folder — `<user home>/Videos/LlamaMXD
    Export`. Used as `default_save_location`'s fallback on a fresh install
    (no settings.json yet); the folder itself is created by MainWindow,
    not here."""
    return os.path.join(os.path.expanduser("~"), "Videos", "LlamaMXD Export")


def load_settings():
    """Reads persisted app settings (theme, appearance mode, default save
    location, GPU acceleration, the Downloader's own separate save location),
    filling in defaults for anything missing or if the file doesn't exist yet
    (e.g. first run). Appearance mode defaults to "System"; default save
    location defaults to default_output_dir(); the Downloader's separate
    save location is off by default and empty until set."""
    settings = {
        "theme": DEFAULT_THEME_NAME,
        "appearance_mode": "System",
        "default_save_location": default_output_dir(),
        "gpu_enabled": True,
        "downloader_separate_save": False,
        "downloader_save_location": "",
    }
    if not os.path.exists(_SETTINGS_PATH):
        return settings
    try:
        with open(_SETTINGS_PATH, "r") as f:
            settings.update(json.load(f))
    except (json.JSONDecodeError, OSError):
        pass
    return settings


def save_settings(settings):
    """Persists app settings to disk as JSON."""
    with open(_SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)
