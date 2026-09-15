"""Live theme state for the Qt UI.

The brand palettes still come from `core.theme` (THEMES / get_theme /
readable_text_on), so both front ends read the same colours. What's new is
that a theme or appearance switch is *live without a rebuild*: `ThemeManager.
changed` fires, the app re-applies one stylesheet, and every custom-painted
widget calls `update()`. Nothing is destroyed, so no form state has to be
snapshotted and restored the way the CTk version's `apply_theme` needed.

Neutral colours (window, frame, entry, …) mirror CustomTkinter's own
`blue.json` values for each appearance mode, so the translation is 1:1."""
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication

from core.theme import (
    DEFAULT_THEME_NAME,
    STOP_RED,
    STOP_RED_HOVER,
    THEMES,
    get_theme,
    load_settings,
    readable_text_on,
)

# CustomTkinter's neutral greys, per appearance mode (gray14 = #242424, etc.).
_NEUTRALS = {
    "Dark": {
        "window": "#242424",        # gray14
        "frame": "#2b2b2b",         # gray17
        "entry": "#343638",
        "entry_border": "#565b5e",
        "text": "#dce4ee",
        "muted": "#999999",         # gray60
        "label_disabled": "#7f7f7f",  # gray50
        "placeholder": "#9e9e9e",   # gray62
        "track": "#4a4d50",
        "track_fill": "#aab0b5",
        "knob": "#d5d9de",
        "check_border": "#949a9f",
        "menu_bg": "#333333",       # gray20
        "menu_hover": "#474747",    # gray28
        "menu_border": "#4d4d4d",   # gray30
        "menu_text": "#e5e5e5",     # gray90
        "segment": "#4a4a4a",       # gray29
        "row": "#333333",           # gray20 — a running / done queue row
        "row_hover": "#4d4d4d",     # gray30
        "panel": "#333333",         # the queue's details popup
        "disabled": "#666666",      # gray40 — a disabled control's own fill
        "tooltip_bg": "#202020",
        "warn_bg": "#4a3a0e",
        "warn_text": "#f6d77e",
    },
    "Light": {
        "window": "#ebebeb",        # gray92
        "frame": "#dbdbdb",         # gray86
        "entry": "#f9f9fa",
        "entry_border": "#979da2",
        "text": "#1a1a1a",          # gray10
        "muted": "#666666",
        "label_disabled": "#7f7f7f",
        "placeholder": "#858585",   # gray52
        "track": "#939ba2",
        "track_fill": "#666666",
        "knob": "#5c5c5c",
        "check_border": "#3e454a",
        "menu_bg": "#e5e5e5",
        "menu_hover": "#bfbfbf",
        "menu_border": "#b3b3b3",
        "menu_text": "#1a1a1a",
        "segment": "#979da2",
        "row": "#d9d9d9",           # gray85
        "row_hover": "#bfbfbf",
        "panel": "#d9d9d9",
        "disabled": "#a6a6a6",
        "tooltip_bg": "#202020",
        "warn_bg": "#fff1c2",
        "warn_text": "#5c4300",
    },
}

APPEARANCE_MODES = ["System", "Light", "Dark"]


class ThemeManager(QObject):
    """Holds the active palette and announces changes. One instance per app
    (`ui.theme.theme`), created after the QApplication exists."""

    changed = Signal()

    _rebuilding = False

    def __init__(self):
        super().__init__()
        settings = load_settings()
        name = settings.get("theme", DEFAULT_THEME_NAME)
        self.name = name if name in THEMES else DEFAULT_THEME_NAME
        mode = settings.get("appearance_mode", "System")
        self.mode = mode if mode in APPEARANCE_MODES else "System"
        self._colors = {}
        self._rebuild()
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_system_scheme)

    # --- public -----------------------------------------------------------
    def set_theme(self, name):
        """Swap the brand palette live."""
        if name in THEMES and name != self.name:
            self.name = name
            self._rebuild()
            self.changed.emit()

    def set_mode(self, mode):
        """Swap System/Light/Dark live."""
        if mode in APPEARANCE_MODES and mode != self.mode:
            self.mode = mode
            self._rebuild()
            self.changed.emit()

    def resolved_mode(self):
        """"Light" or "Dark" — System resolved against the OS setting."""
        if self.mode != "System":
            return self.mode
        scheme = QGuiApplication.styleHints().colorScheme()
        return "Light" if scheme == Qt.ColorScheme.Light else "Dark"

    def hex(self, key):
        """A palette entry as "#rrggbb"."""
        return self._colors[key]

    def color(self, key):
        """A palette entry as a QColor."""
        return QColor(self._colors[key])

    # --- internals --------------------------------------------------------
    def _on_system_scheme(self, _scheme):
        if self.mode == "System" and not self._rebuilding:
            self._rebuild()
            self.changed.emit()

    def _rebuild(self):
        self._rebuilding = True
        try:
            self._rebuild_colors()
        finally:
            self._rebuilding = False

    def _rebuild_colors(self):
        # The native title bar follows the colour scheme (Qt 6.8+), which is
        # what CTk's DWM tweak did. "System" must hand the scheme back to the
        # OS *before* resolving it, or an earlier explicit Light/Dark would
        # read back as the system's own.
        hints = QGuiApplication.styleHints()
        if self.mode == "System":
            hints.unsetColorScheme()
        else:
            hints.setColorScheme(
                Qt.ColorScheme.Light if self.mode == "Light" else Qt.ColorScheme.Dark
            )
        brand = get_theme(self.name)
        colors = dict(_NEUTRALS[self.resolved_mode()])
        colors.update(brand)
        colors["stop"] = STOP_RED
        colors["stop_hover"] = STOP_RED_HOVER
        colors["stop_text"] = readable_text_on(STOP_RED)
        colors["stop_pressed"] = _shade(STOP_RED_HOVER, 0.87)
        colors["secondary_pressed"] = _shade(brand["secondary_hover"], 0.87)
        colors["primary_pressed"] = _shade(brand["primary_hover"], 0.87)
        self._colors = colors


def _shade(hex_color, factor):
    """Multiply a colour's channels by `factor` (<1 darkens)."""
    h = hex_color.lstrip("#")
    r, g, b = (max(0, min(255, int(int(h[i:i + 2], 16) * factor))) for i in (0, 2, 4))
    return f"#{r:02x}{g:02x}{b:02x}"


def lerp(a, b, t):
    """Straight RGB(A) interpolation between two QColors."""
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
        round(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


def with_alpha(color, alpha):
    """`color` (QColor) at opacity `alpha` (0..1)."""
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


theme = None  # set by init_theme()


def init_theme():
    """Create the process-wide ThemeManager (needs a QApplication)."""
    global theme
    theme = ThemeManager()
    return theme


def stylesheet():
    """The one app-wide stylesheet, generated from the active palette. Only
    stock Qt widgets (buttons, entries, sliders, labels, scroll areas, combo
    popups) are styled here — everything with custom geometry paints itself
    straight from `theme`."""
    c = theme.hex
    return f"""
    QWidget {{
        color: {c('text')};
        font-family: "Roboto", "Segoe UI";
        font-size: 13px;
    }}
    #Root, QDialog {{ background: {c('window')}; }}
    #TabFrame {{ background: {c('frame')}; border-radius: 6px; }}
    QStackedWidget, QStackedWidget > QWidget {{ background: transparent; }}

    QLabel {{ background: transparent; }}
    QLabel:disabled {{ color: {c('label_disabled')}; }}
    QLabel[role="field"] {{ font-family: Arial; font-size: 12px; font-weight: bold; min-height: 26px; }}
    QLabel[role="field11"] {{ font-family: Arial; font-size: 11px; font-weight: bold; min-height: 26px; }}
    QLabel[role="muted"] {{ color: {c('muted')}; font-family: Arial; font-size: 11px; }}
    QLabel[role="muted"]:disabled {{ color: {c('label_disabled')}; }}
    QLabel[role="meta"] {{ color: {c('label_disabled')}; font-family: Arial; font-size: 12px; }}
    QLabel[role="hint"] {{ color: {c('muted')}; font-family: Arial; font-size: 10px; }}
    QLabel[role="title"] {{ font-size: 28px; font-weight: bold; }}
    QLabel[role="dialogTitle"] {{ font-size: 15px; font-weight: bold; }}
    QLabel[role="detailTitle"] {{ font-size: 13px; font-weight: bold; }}
    QLabel[role="detailKey"] {{ font-family: Arial; font-size: 11px; font-weight: bold; }}
    QLabel[role="error"] {{ color: {c('stop')}; }}
    QLabel[role="sidebarTitle"] {{ color: {c('primary_text')}; font-size: 20px; font-weight: bold; }}
    QLabel[role="sidebarFooter"] {{ color: {c('primary_text')}; font-size: 10px; }}
    QLabel[role="empty"] {{ color: {c('muted')}; }}
    QLabel[role="warn"] {{
        background: {c('warn_bg')}; color: {c('warn_text')};
        font-family: Arial; font-size: 12px; border-radius: 6px; padding: 5px 10px;
    }}

    QPushButton {{
        background: {c('secondary')};
        color: {c('secondary_text')};
        border: none;
        border-radius: 6px;
        min-height: 28px;
        padding: 0 10px;
    }}
    QPushButton:hover {{ background: {c('secondary_hover')}; }}
    QPushButton:pressed {{ background: {c('secondary_pressed')}; }}
    QPushButton:disabled {{ color: {c('secondary_disabled_text')}; }}
    QPushButton[role="primary"] {{ background: {c('primary')}; color: {c('primary_text')}; }}
    QPushButton[role="primary"]:hover {{ background: {c('primary_hover')}; }}
    QPushButton[role="primary"]:pressed {{ background: {c('primary_pressed')}; }}
    QPushButton[role="primary"]:disabled {{ color: {c('primary_disabled_text')}; }}
    QPushButton[role="danger"] {{ background: {c('stop')}; color: {c('stop_text')}; }}
    QPushButton[role="danger"]:hover {{ background: {c('stop_hover')}; }}
    QPushButton[role="danger"]:pressed {{ background: {c('stop_pressed')}; }}
    QPushButton[role="ghost"] {{ background: transparent; color: {c('text')}; }}
    QPushButton[role="ghost"]:hover {{ background: {c('row_hover')}; }}
    QPushButton[role="stepper"] {{
        min-height: 13px; max-height: 13px; min-width: 30px; max-width: 30px;
        padding: 0; border-radius: 3px; font-size: 8px;
    }}

    QLineEdit {{
        background: {c('entry')};
        border: 2px solid {c('entry_border')};
        border-radius: 6px;
        padding: 0 6px;
        min-height: 24px;
        selection-background-color: {c('secondary')};
        selection-color: {c('secondary_text')};
    }}
    QLineEdit:focus {{ border-color: {c('secondary')}; }}
    QLineEdit:disabled {{ color: {c('label_disabled')}; }}

    QSlider {{ min-height: 18px; }}
    QSlider::groove:horizontal {{ height: 4px; background: {c('track')}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {c('track_fill')}; border-radius: 2px; }}
    QSlider::add-page:horizontal {{ background: {c('track')}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        background: {c('secondary')}; width: 16px; height: 16px;
        margin: -6px 0; border-radius: 8px;
    }}
    QSlider::handle:horizontal:hover {{ background: {c('secondary_hover')}; }}
    QSlider::handle:horizontal:disabled {{ background: {c('disabled')}; }}
    QSlider::sub-page:horizontal:disabled {{ background: {c('disabled')}; }}

    QComboBox {{ combobox-popup: 0; }}
    QComboBoxPrivateContainer {{ background: transparent; border: none; }}
    QComboBox QAbstractItemView {{
        background: {c('menu_bg')};
        color: {c('menu_text')};
        border: 1px solid {c('menu_border')};
        border-radius: 6px;
        padding: 3px;
        outline: 0;
    }}
    QComboBox QAbstractItemView::item {{
        min-height: 28px; padding-left: 8px; border-radius: 4px;
    }}
    QComboBox QAbstractItemView::item:hover,
    QComboBox QAbstractItemView::item:selected {{
        background: {c('menu_hover')}; color: {c('menu_text')};
    }}

    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 12px; margin: 4px 2px; }}
    QScrollBar::handle:vertical {{ background: {c('segment')}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {c('muted')}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QMenu {{ background: {c('menu_bg')}; color: {c('menu_text')}; border: 1px solid {c('menu_border')}; }}
    """
