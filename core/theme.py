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
}


def _darken(hex_color, factor=0.87):
    """Returns a slightly-darker shade of hex_color for hover states —
    the same ~0.87 factor already implicit in the brand yellow's existing
    hover (#FDCA3C -> #e0b234)."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = (max(0, min(255, int(channel * factor))) for channel in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def get_theme(name=None):
    """Returns the full color palette for a theme name — primary/
    primary_hover/secondary/secondary_hover — falling back to the default
    theme for an unknown or missing name."""
    colors = THEMES.get(name, THEMES[DEFAULT_THEME_NAME])
    return {
        "primary": colors["primary"],
        "primary_hover": colors.get("primary_hover") or _darken(colors["primary"]),
        "secondary": colors["secondary"],
        "secondary_hover": colors.get("secondary_hover") or _darken(colors["secondary"]),
    }


def load_settings():
    """Reads persisted app settings (theme, appearance mode, default save
    location), filling in defaults for anything missing or if the file
    doesn't exist yet (e.g. first run)."""
    settings = {"theme": DEFAULT_THEME_NAME, "appearance_mode": "System", "default_save_location": ""}
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


def _substitute_ctk_accents(node, secondary, secondary_hover, secondary_pressed):
    """Recursively walks a CTk theme JSON structure, replacing every
    occurrence of CTk's own hardcoded accent-blue value pairs with the
    given theme's secondary colors (flattened to a single shade repeated
    for both the light and dark slots, so appearance mode never changes
    them) — everything else (backgrounds, borders, neutral greys, corner
    radii) is left exactly as CTk's own bundled theme defines it, since
    only the accent color role is part of "the theme" here."""
    if isinstance(node, dict):
        return {
            key: _substitute_ctk_accents(value, secondary, secondary_hover, secondary_pressed)
            for key, value in node.items()
        }
    if isinstance(node, list):
        if node == _CTK_ACCENT:
            return [secondary, secondary]
        if node == _CTK_ACCENT_HOVER:
            return [secondary_hover, secondary_hover]
        if node == _CTK_ACCENT_PRESSED:
            return [secondary_pressed, secondary_pressed]
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
        base_theme, palette["secondary"], palette["secondary_hover"], secondary_pressed
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
