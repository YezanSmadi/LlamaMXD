"""Settings: theme (with a live hover preview), appearance mode, default save
location, and hardware acceleration — all persisted to settings.json.

A theme change is live **without a rebuild**. The CTk version had to destroy
and reconstruct the sidebar and three tabs (snapshotting each form first)
because CTk never recolours a built widget; here `ThemeManager.changed`
repaints everything in place, which is also why hovering the list can
preview a palette across the whole window."""
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QFileDialog, QLabel, QLineEdit, QVBoxLayout, QWidget

from core.theme import THEMES, get_theme, save_settings
from ui import theme as T
from ui.tabs.media_tab import hrow, set_line_text
from ui.widgets.controls import Dropdown, Switch, button, field_label


class _Swatch(QWidget):
    """A 26px rounded chip showing one colour of the previewed palette."""

    def __init__(self, key):
        super().__init__()
        self.key = key
        self.theme_name = None
        self.setFixedSize(26, 26)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 4, 4)
        p.fillPath(path, QColor(get_theme(self.theme_name)[self.key]))


class SettingsTab(QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self._committed = T.theme.name

        root = QVBoxLayout(self)
        root.setContentsMargins(30, 22, 30, 20)
        root.setSpacing(0)
        root.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        title = QLabel("Settings")
        title.setProperty("role", "title")
        root.addWidget(title)
        root.addSpacing(22)

        # -- Theme
        root.addWidget(field_label("Theme:", "field11"))
        root.addSpacing(4)
        row, rl = hrow(spacing=0, align_bottom=False)
        self.theme_menu = Dropdown(list(THEMES), width=150)
        self.theme_menu.set(self._committed)
        self.theme_menu.hovered.connect(self._preview_theme)
        self.theme_menu.picked.connect(self._on_theme_change)
        self.theme_menu.popupClosed.connect(lambda: QTimer.singleShot(0, self._end_preview))
        rl.addWidget(self.theme_menu)
        rl.addSpacing(12)
        self.primary_swatch, self.secondary_swatch = _Swatch("primary"), _Swatch("secondary")
        rl.addWidget(self.primary_swatch)
        rl.addSpacing(5)
        rl.addWidget(self.secondary_swatch)
        rl.addSpacing(8)
        self.theme_name_label = QLabel("")
        self.theme_name_label.setStyleSheet("font-family: Arial; font-size: 11px;")
        rl.addWidget(self.theme_name_label)
        root.addWidget(row, 0, Qt.AlignLeft)
        root.addSpacing(8)
        note = QLabel("Applies instantly — no restart. Saves automatically when you leave.")
        note.setProperty("role", "hint")
        root.addWidget(note)
        root.addSpacing(24)
        self._show_swatches(self._committed)

        # -- Appearance mode
        root.addWidget(field_label("Appearance Mode:", "field11"))
        root.addSpacing(4)
        self.appearance_menu = Dropdown(["System", "Light", "Dark"], width=150)
        self.appearance_menu.set(T.theme.mode)
        self.appearance_menu.picked.connect(self._on_appearance_change)
        root.addWidget(self.appearance_menu)
        root.addSpacing(18)

        # -- Default save location
        root.addWidget(field_label("Default Save Location:", "field11"))
        root.addSpacing(4)
        loc, ll = hrow(spacing=8, align_bottom=False)
        self.save_location_entry = QLineEdit()
        self.save_location_entry.setPlaceholderText("No default location set...")
        self.save_location_entry.setFixedSize(300, 28)
        set_line_text(self.save_location_entry, app.default_save_location)
        self.save_location_entry.editingFinished.connect(self._sync_state_from_widgets)
        ll.addWidget(self.save_location_entry)
        browse = button("Browse", width=80)
        browse.clicked.connect(self._browse_save_location)
        ll.addWidget(browse)
        root.addWidget(loc, 0, Qt.AlignLeft)
        root.addSpacing(18)

        # -- Hardware acceleration (a global preference every Encode inherits)
        root.addWidget(field_label("Hardware Acceleration (GPU):", "field11"))
        root.addSpacing(4)
        self.gpu_switch = Switch(checked=bool(app.gpu_enabled))
        self.gpu_switch.clicked.connect(self._on_gpu_toggle)
        root.addWidget(self.gpu_switch)
        root.addSpacing(22)

        self.save_btn = button("Save", role="primary", width=150)
        self.save_btn.clicked.connect(self._on_save)
        root.addWidget(self.save_btn)

    # ------------------------------------------------------------------ #
    #  Persistence
    # ------------------------------------------------------------------ #
    def _settings_snapshot(self):
        location = self.save_location_entry.text().strip()
        return {
            "theme": self._committed,
            "appearance_mode": self.appearance_menu.value(),
            "default_save_location": location or self.app.default_save_location,
            "gpu_enabled": self.gpu_switch.isChecked(),
        }

    def _sync_state_from_widgets(self):
        location = self.save_location_entry.text().strip()
        if location:
            self.app.default_save_location = location
        self.app.gpu_enabled = self.gpu_switch.isChecked()

    def autosave(self):
        self._sync_state_from_widgets()
        save_settings(self._settings_snapshot())

    def on_leave(self):
        """Switching away flushes every setting to disk."""
        self.theme_menu.close()
        self.appearance_menu.close()
        self.autosave()

    # ------------------------------------------------------------------ #
    #  Theme
    # ------------------------------------------------------------------ #
    def _show_swatches(self, name):
        for swatch in (self.primary_swatch, self.secondary_swatch):
            swatch.theme_name = name
            swatch.update()
        self.theme_name_label.setText(name)

    def _preview_theme(self, name):
        """Hovering a row previews that palette across the whole app."""
        self._show_swatches(name)
        T.theme.set_theme(name)

    def _end_preview(self):
        """The list closed: drop back to whatever is committed."""
        self.theme_menu.set(self._committed)
        self._show_swatches(self._committed)
        T.theme.set_theme(self._committed)

    def _on_theme_change(self, name):
        self._committed = name
        self._show_swatches(name)
        T.theme.set_theme(name)
        self.autosave()

    # ------------------------------------------------------------------ #
    #  Appearance / location / GPU
    # ------------------------------------------------------------------ #
    def _on_appearance_change(self, mode):
        T.theme.set_mode(mode)
        self.autosave()

    def _browse_save_location(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Default Save Location",
                                                  self.save_location_entry.text())
        if folder:
            self.app.default_save_location = folder
            set_line_text(self.save_location_entry, folder)
            self.autosave()

    def _on_gpu_toggle(self, *_):
        self.app.gpu_enabled = self.gpu_switch.isChecked()
        self.autosave()

    def _on_save(self):
        self.autosave()
        self.app.notify("Settings saved.", go_to_queue=False)
