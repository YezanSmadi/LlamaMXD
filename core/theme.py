import json
import os

import customtkinter as ctk

# Repo root, derived from this file's own location rather than a bare
# relative path — settings.json always lands next to main.py regardless of
# the app's own "must be launched from the repo root" constraint elsewhere.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SETTINGS_PATH = os.path.join(_REPO_ROOT, "settings.json")
_GENERATED_THEME_DIR = os.path.join(_REPO_ROOT, "_generated_themes")

# CTk's own bundled "blue" theme reuses these exact three color pairs
# across every widget's accent-colored properties — CTkButton/CTkCheckBox/
# CTkRadioButton's fg_color, CTkSwitch/CTkProgressBar's progress_color,
# CTkSlider's button_color, CTkOptionMenu's fg_color, CTkSegmentedButton's
# selected_color (and each of those widgets' hover-color counterpart, plus
# a third, even-darker shade CTkOptionMenu alone uses for its own button's
# hover state). Confirmed by dumping customtkinter's blue.json in full.
_CTK_ACCENT = ["#3B8ED0", "#1F6AA5"]
_CTK_ACCENT_HOVER = ["#36719F", "#144870"]
_CTK_ACCENT_PRESSED = ["#27577D", "#203A4F"]
# The flat near-white pair CTk uses for label text that sits *on* an accent
# fill — CTkButton, CTkOptionMenu, and CTkSegmentedButton's `text_color`
# (confirmed by dumping blue.json: it appears in exactly those three spots,
# every other `text_color` is the adaptive `["gray10", "#DCE4EE"]` pair for
# text on the window background, which must stay untouched). Since those
# three fills all become `secondary`, this pair becomes readable_text_on
# (secondary) — otherwise a light secondary (e.g. Shire's #DAE2ED) leaves
# near-white text on a near-white button, i.e. invisible.
_CTK_ACCENT_TEXT = ["#DCE4EE", "#DCE4EE"]
# The same three widgets' `text_color_disabled` (CTk never dims a disabled
# widget's fill, only its text — see disabled_text_on's docstring), so a
# disabled dropdown/segmented-button/button is still filled with the full
# accent color. CTkCheckBox/CTkSwitch/CTkRadioButton use a *different* stock
# pair (["gray60", "gray45"]) for this, left untouched — their disabled text
# sits on the plain window background, not an accent fill, so CTk's own
# adaptive grey is fine there.
_CTK_ACCENT_TEXT_DISABLED = ["gray74", "gray60"]

DEFAULT_THEME_NAME = "Lemon"

# Each theme is a primary (brand accent — sidebar, DropBox border, the
# yellow/pink/purple "do it now" buttons, the queue's active-tab indicator,
# queued rows, and the progress fill) and a secondary (the "Queue Task" /
# "Clear Completed" action buttons, previously just CTk's own default blue
# button color). Colors are flat hex strings, not (light, dark) tuples —
# deliberately, so switching appearance mode never changes them. "Lemon"'s
# secondary is CTk's own stock button blue, flattened to a single shade
# (CTk itself varies light/dark for it) so all three themes behave the same
# way. Hover shades are auto-derived (see _darken) except Lemon's primary
# hover, kept as the exact historical value already used throughout the app.
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
    """A "greyed out" text color for CTk's disabled state that still stays
    legible on `hex_color` — needed because CTk's disabled state only dims a
    widget's *text*, never its fill (`CTkButton`/`CTkOptionMenu`/
    `CTkSegmentedButton` all keep painting their full accent color when
    disabled; see CLAUDE.md). CTk's own stock disabled grey (gray74 light /
    gray60 dark) reads fine against a very dark or very light accent, but on
    a mid-brightness one — Lemon's `#3B8ED0` secondary, Vaporwave's
    `#ED72D4` — it sits close enough in brightness to nearly vanish
    (confirmed: WCAG contrast ~1.1-1.2, verified against every theme).

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
    is enough to fix the original near-invisible gray74/gray60 (~1.1:1 on
    Lemon/Vaporwave) while keeping a genuine mid-grey, disabled-looking
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
    (no settings.json yet); the folder itself is created lazily by
    LlamaGUI.__init__, not here."""
    return os.path.join(os.path.expanduser("~"), "Videos", "LlamaMXD Export")


def load_settings():
    """Reads persisted app settings (theme, appearance mode, default save
    location, GPU acceleration), filling in defaults for anything missing or
    if the file doesn't exist yet (e.g. first run). Appearance mode defaults
    to "System"; default save location defaults to default_output_dir()."""
    settings = {
        "theme": DEFAULT_THEME_NAME,
        "appearance_mode": "System",
        "default_save_location": default_output_dir(),
        "gpu_enabled": True,
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


def get_active_theme():
    """Convenience accessor: the color palette for whatever theme is
    currently persisted — this is what every explicitly-colored widget
    (sidebar, DropBox border, the primary/secondary action buttons, the
    queue's fill) reads at construction time."""
    return get_theme(load_settings().get("theme"))


def _substitute_ctk_accents(node, secondary, secondary_hover, secondary_pressed, secondary_text,
                             secondary_disabled_text):
    """Recursively walks a CTk theme JSON structure, replacing every
    occurrence of CTk's own hardcoded accent-blue value pairs with the
    given theme's secondary colors (flattened to a single shade repeated
    for both the light and dark slots, so appearance mode never changes
    them), CTk's on-accent label color with `secondary_text` (the adaptive
    black/white for that secondary), and CTk's on-accent *disabled* label
    color with `secondary_disabled_text` (see disabled_text_on) — everything
    else (backgrounds, borders, neutral greys, corner radii, and the separate
    text-on-window-background color) is left exactly as CTk's own bundled
    theme defines it, since only the accent color role is part of "the
    theme" here."""
    if isinstance(node, dict):
        return {
            key: _substitute_ctk_accents(value, secondary, secondary_hover, secondary_pressed,
                                          secondary_text, secondary_disabled_text)
            for key, value in node.items()
        }
    if isinstance(node, list):
        if node == _CTK_ACCENT:
            return [secondary, secondary]
        if node == _CTK_ACCENT_HOVER:
            return [secondary_hover, secondary_hover]
        if node == _CTK_ACCENT_PRESSED:
            return [secondary_pressed, secondary_pressed]
        if node == _CTK_ACCENT_TEXT:
            return [secondary_text, secondary_text]
        if node == _CTK_ACCENT_TEXT_DISABLED:
            return [secondary_disabled_text, secondary_disabled_text]
        return node
    return node


def _ctk_theme_path(theme_name):
    """Generates (or reuses a cached) CTk theme JSON file for `theme_name`
    — CTk's own bundled "blue" theme with every accent-blue value replaced
    by that theme's secondary color — so default-styled widgets (sidebar
    nav buttons, checkboxes, switches, sliders, dropdowns) match the same
    two-color combo as the widgets this app colors explicitly, instead of
    always showing CTk's stock blue regardless of theme. Returns a file
    path suitable for ctk.set_default_color_theme()."""
    palette = get_theme(theme_name)
    os.makedirs(_GENERATED_THEME_DIR, exist_ok=True)
    generated_path = os.path.join(_GENERATED_THEME_DIR, f"{theme_name.lower()}.json")

    base_path = os.path.join(os.path.dirname(ctk.__file__), "assets", "themes", "blue.json")
    with open(base_path, "r") as f:
        base_theme = json.load(f)

    secondary_pressed = _darken(palette["secondary_hover"])
    generated_theme = _substitute_ctk_accents(
        base_theme, palette["secondary"], palette["secondary_hover"],
        secondary_pressed, palette["secondary_text"], palette["secondary_disabled_text"],
    )

    with open(generated_path, "w") as f:
        json.dump(generated_theme, f, indent=2)
    return generated_path


def apply_ctk_theme(theme_name):
    """Loads the generated custom CTk theme for `theme_name` as the
    process's default color theme. Must be called before constructing any
    widgets that should pick it up — CTk never retroactively recolors
    already-built widgets, which is why a live theme switch (see
    LlamaGUI.apply_theme) has to rebuild the affected widget tree after
    calling this, not just call it on its own."""
    ctk.set_default_color_theme(_ctk_theme_path(theme_name))
