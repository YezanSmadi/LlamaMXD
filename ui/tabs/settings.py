"""Settings: theme (with a live hover preview), appearance mode, default save
location, and hardware acceleration — all persisted to settings.json.

A theme change is live **without a rebuild**: `ThemeManager.changed`
repaints everything in place, which is also why hovering the list can
preview a palette across the whole window."""
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QFileDialog, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget

from core import gpu, system_info
from core.theme import DEFAULT_THEME_NAME, THEMES, default_output_dir, get_theme, save_settings
from ui import theme as T
from ui.tabs.media_tab import hrow, set_line_text
from ui.widgets.controls import CheckBox, Dropdown, Switch, button, button_width_for, field_label
from ui.widgets.dialogs import ask_yes_no
from ui.widgets.tooltip import tip

_GPU_TIP = ("Uses your GPU's built-in encoder (NVENC/Quick Sync/AMF) when available — "
            "falls back to software automatically if this encoder isn't supported.")
_SEPARATE_SAVE_TIP = "Lets Downloader save to a different default folder than Muxing/Encoding."

# "Available space" on the Default Save Location's drive turns red at or
# below this, in binary GB (matching system_info.format_bytes's units).
_LOW_DISK_BYTES = 25 * 1024 ** 3


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

        # A plain QVBoxLayout on a fixed-size window's tab (see MainWindow's
        # own fixed size) has nowhere to put content past the frame's own
        # height — it just gets clipped. Settings.own content is now tall
        # enough to hit that once the Downloader location row is showing
        # (confirmed: revealing it pushed later rows outside the frame), so
        # everything scrolls instead, same pattern as the Queue tab's list.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(30, 22, 30, 20)
        root.setSpacing(0)
        root.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        scroll.setWidget(content)

        # System info (read-only: CPU / GPU / RAM) — a fixed-width corner
        # label, not a row in the main column: a bare CPU name can run past
        # 30 characters, and letting it size to its own content (as a row
        # among the others below once did) could grow wider than the tab
        # frame on a smaller screen or a DPI change from dragging the window
        # to another monitor, spilling text past the frame's rounded border.
        # It sits in its own full-width row with a leading stretch, not a
        # bare `addWidget(..., Qt.AlignRight)` on `root` directly — `root`
        # itself is only as wide as its widest *stretching* item (see its
        # own `setAlignment(Qt.AlignLeft)` above), so a fixed-width label
        # right-aligned straight on it lands at the right edge of that
        # narrower column instead of the actual panel (confirmed: it sat
        # noticeably left of the frame's real right edge).
        title_row, title_rl = hrow(spacing=0, align_bottom=False)
        ram_text = f"{system_info.format_bytes(system_info.ram_total_bytes())} RAM"
        sys_text = "\n".join((system_info.cpu_name(), gpu.display_name(), ram_text))
        sys_info = QLabel(sys_text)
        sys_info.setProperty("role", "muted")
        sys_info.setAlignment(Qt.AlignRight | Qt.AlignTop)
        sys_info.setWordWrap(True)
        sys_info.setFixedWidth(230)
        title_rl.addStretch(1)
        title_rl.addWidget(sys_info, 0, Qt.AlignTop)
        root.addWidget(title_row)
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
        root.addSpacing(4)
        self.disk_label = QLabel("")
        self.disk_label.setProperty("role", "muted")
        root.addWidget(self.disk_label)
        root.addSpacing(10)
        self._refresh_disk_usage()

        # -- Downloader's own save location, off by default
        self.downloader_separate_check = CheckBox(
            "Separate Save for Downloader", checked=bool(app.downloader_separate_save))
        self.downloader_separate_check.clicked.connect(self._on_downloader_separate_toggle)
        tip(self.downloader_separate_check, _SEPARATE_SAVE_TIP)
        root.addWidget(self.downloader_separate_check)
        root.addSpacing(8)
        self.downloader_loc_row, dll = hrow(spacing=8, align_bottom=False)
        self.downloader_location_entry = QLineEdit()
        self.downloader_location_entry.setPlaceholderText("No separate location set...")
        self.downloader_location_entry.setFixedSize(300, 28)
        set_line_text(self.downloader_location_entry,
                     app.downloader_save_location or app.default_save_location)
        self.downloader_location_entry.editingFinished.connect(self._sync_state_from_widgets)
        dll.addWidget(self.downloader_location_entry)
        downloader_browse = button("Browse", width=80)
        downloader_browse.clicked.connect(self._browse_downloader_location)
        dll.addWidget(downloader_browse)
        root.addWidget(self.downloader_loc_row, 0, Qt.AlignLeft)
        self.downloader_loc_row.setVisible(bool(app.downloader_separate_save))
        root.addSpacing(18)

        # -- Hardware acceleration (a global preference every Encode inherits)
        root.addWidget(field_label("Hardware Acceleration (GPU):", "field11"))
        root.addSpacing(4)
        self.gpu_switch = Switch(checked=bool(app.gpu_enabled))
        self.gpu_switch.clicked.connect(self._on_gpu_toggle)
        tip(self.gpu_switch, _GPU_TIP)
        root.addWidget(self.gpu_switch)
        root.addSpacing(4)
        self.gpu_status_label = QLabel("")
        self.gpu_status_label.setProperty("role", "hint")
        self.gpu_status_label.setWordWrap(True)
        self.gpu_status_label.setFixedWidth(360)
        root.addWidget(self.gpu_status_label)
        root.addSpacing(18)
        self._refresh_gpu_status()

        actions, actions_l = hrow(spacing=10, align_bottom=False)
        self.reset_btn = button("Reset to Default", role="danger",
                                width=button_width_for(["Reset to Default"]))
        self.reset_btn.clicked.connect(self._on_reset_defaults)
        actions_l.addWidget(self.reset_btn)
        self.save_btn = button("Save", role="primary", width=150)
        self.save_btn.clicked.connect(self._on_save)
        actions_l.addWidget(self.save_btn)
        root.addWidget(actions, 0, Qt.AlignLeft)

    # ------------------------------------------------------------------ #
    #  Persistence
    # ------------------------------------------------------------------ #
    def _settings_snapshot(self):
        location = self.save_location_entry.text().strip()
        downloader_location = self.downloader_location_entry.text().strip()
        separate = self.downloader_separate_check.isChecked()
        return {
            "theme": self._committed,
            "appearance_mode": self.appearance_menu.value(),
            "default_save_location": location or self.app.default_save_location,
            "gpu_enabled": self.gpu_switch.isChecked(),
            "downloader_separate_save": separate,
            # While separate-save is off, the entry just displays the shared
            # default as a fallback (see __init__) — that display text is
            # never itself a real separate location, so it must not get
            # persisted as one on the next autosave.
            "downloader_save_location": (
                downloader_location if separate and downloader_location
                else self.app.downloader_save_location
            ),
        }

    def _sync_state_from_widgets(self):
        location = self.save_location_entry.text().strip()
        if location and location != self.app.default_save_location:
            self.app.set_default_save_location(location)
        downloader_location = self.downloader_location_entry.text().strip()
        if downloader_location and self.downloader_separate_check.isChecked() \
                and downloader_location != self.app.downloader_save_location:
            self.app.set_downloader_save_location(downloader_location)
        self.app.gpu_enabled = self.gpu_switch.isChecked()
        self._refresh_disk_usage()

    def autosave(self):
        self._sync_state_from_widgets()
        save_settings(self._settings_snapshot())

    def on_leave(self):
        """Switching away flushes every setting to disk."""
        self.theme_menu.close()
        self.appearance_menu.close()
        self.autosave()

    def on_enter(self):
        """Free disk space can change while the app sits on another tab —
        refresh it every time Settings is shown, not just at startup."""
        self._refresh_disk_usage()

    # ------------------------------------------------------------------ #
    #  Theme
    # ------------------------------------------------------------------ #
    def _show_swatches(self, name):
        for swatch in (self.primary_swatch, self.secondary_swatch):
            swatch.theme_name = name
            swatch.update()

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
            set_line_text(self.save_location_entry, folder)
            self.app.set_default_save_location(folder)
            self._refresh_disk_usage()
            self.autosave()

    def _on_downloader_separate_toggle(self, *_):
        enabled = self.downloader_separate_check.isChecked()
        self.downloader_loc_row.setVisible(enabled)
        self.app.set_downloader_separate_save(enabled)
        self.autosave()

    def _browse_downloader_location(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Downloader Save Location",
                                                  self.downloader_location_entry.text())
        if folder:
            set_line_text(self.downloader_location_entry, folder)
            self.app.set_downloader_save_location(folder)
            self.autosave()

    def _refresh_disk_usage(self):
        """Total/free space for the drive under the save-location entry —
        "" falls back to the app's own default, same as `_settings_snapshot`.
        Only the "___ free" half renders in STOP_RED when space is low at or
        below `_LOW_DISK_BYTES` — the total figure stays neutral either way."""
        location = self.save_location_entry.text().strip() or self.app.default_save_location
        total, free = system_info.disk_usage(location)
        if total is None:
            self.disk_label.setText("Disk space unavailable.")
            return
        free_text = f"{system_info.format_bytes(free)} free"
        if free <= _LOW_DISK_BYTES:
            free_text = f'<span style="color: {T.theme.hex("stop")};">{free_text}</span>'
        self.disk_label.setText(f"{system_info.format_bytes(total)} total, {free_text}")

    def _on_gpu_toggle(self, *_):
        self.app.gpu_enabled = self.gpu_switch.isChecked()
        self._refresh_gpu_status()
        self.autosave()

    def _refresh_gpu_status(self):
        checked = self.gpu_switch.isChecked()
        self.gpu_status_label.setText(gpu.summary_label() if checked else "Off — encodes run in software.")

    def _on_save(self):
        self.autosave()
        self.app.notify("Settings saved.", go_to_queue=False)

    def _on_reset_defaults(self):
        if not ask_yes_no(
            self.app, "Reset to Default?",
            "This resets the theme, appearance mode, default save location, "
            "Downloader save location and hardware acceleration back to their "
            "defaults. Continue?",
        ):
            return
        self._committed = DEFAULT_THEME_NAME
        self.theme_menu.set(DEFAULT_THEME_NAME)
        self._show_swatches(DEFAULT_THEME_NAME)
        T.theme.set_theme(DEFAULT_THEME_NAME)
        self.appearance_menu.set("System")
        T.theme.set_mode("System")
        location = default_output_dir()
        set_line_text(self.save_location_entry, location)
        self.app.set_default_save_location(location)
        self.downloader_separate_check.setChecked(False)
        self.downloader_loc_row.setVisible(False)
        set_line_text(self.downloader_location_entry, "")
        self.app.downloader_save_location = ""
        self.app.set_downloader_separate_save(False)
        self.app.gpu_enabled = True
        self.gpu_switch.setChecked(True)
        self._refresh_gpu_status()
        self._refresh_disk_usage()
        self.autosave()
        self.app.notify("Settings reset to default.", go_to_queue=False)
