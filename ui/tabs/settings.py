# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Settings: theme (with a live hover preview), appearance mode, default save
location, the output file-naming format, hardware acceleration, job priority
"When Done" and the startup tab — all persisted to settings.json.

A theme change is live **without a rebuild**: `ThemeManager.changed`
repaints everything in place, which is also why hovering the list can
preview a palette across the whole window."""
import html

from PySide6.QtCore import QRectF, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QLabel,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core import about, gpu, keybinds, llamalog, naming, power, priority, startup_tab, system_info, window_mode
from core.theme import DEFAULT_THEME_NAME, THEMES, default_output_dir, get_theme, save_settings
from ui import scale
from ui import theme as T
from ui.scale import fpx
from ui.tabs.media_tab import hrow, set_line_text
from ui.widgets.controls import (
    CheckBox,
    ClickableLabel,
    Dropdown,
    ScaledLabel,
    ScaledLineEdit,
    Switch,
    button,
    button_width_for,
    field_label,
    restyle,
)
from ui.keymap import canonical
from ui.widgets.dialogs import ask_yes_no, show_message
from ui.widgets.keyfield import KeyField, display_key
from ui.widgets.panels import VERSION, BorderedFrame, SubTabBar
from ui.widgets.tooltip import tip

SETTINGS_PAGES = ("Appearance", "Output", "Performance", "Shortcuts", "About")
# Left/right padding of every row on this tab — the same 10px MediaTab's root
# layout uses, so the tab bar and content line up with Muxing/Encoding's.
_SIDE_PAD = 10
# ... and the 5px above the tab bar (MediaTab's root top margin), so the bar sits
# at the same height on every tab.
_TOP_PAD = 5
# The About page's license notice, in reference pixels: as wide as the page's content column
# (664px less the 10px side pads).
_ABOUT_NOTICE_W = 644

_GPU_TIP = ("Uses your GPU's built-in encoder (NVENC/Quick Sync/AMF) when available — "
            "falls back to software automatically if this encoder isn't supported.")
_GPU_UNAVAILABLE_TIP = ("Hardware acceleration needs a dedicated GPU (NVIDIA, AMD or Intel Arc) — "
                        "integrated graphics aren't used. None was detected, so encodes run in software.")
_SEPARATE_SAVE_TIP = "Lets Downloader save to a different default folder than Muxing/Encoding."
_NAMING_TIP = ("How output files are named. Tokens in braces are replaced: {source} is the input file's "
               "name (the site, for a download), {title} its embedded title, {chapters} the chapter "
               "count. Anything you type around them is kept as-is, e.g. {source}-{title}.")
_NAMING_HELP = ("Filled in as soon as a file is picked: {source} {title} {chapters}\n"
                "Filled in when a job is queued: {date} {time} {creation-time} {quality} {bitrate}")
_PRIORITY_TIP = ("How much CPU priority encodes and downloads get over your other programs. Higher "
                 "finishes sooner but can make the PC feel less responsive; lower keeps it smooth "
                 "while you work. Applies right away, even to a job that's running.")
_WINDOW_MODE_TIP = ("Windowed: the usual title bar and frame, resize it freely. Borderless: no title bar "
                    "or frame (drag the sidebar to move it, its edges to resize). Fixed: the window as the "
                    "app is designed, at a fixed size.")
_FULLSCREEN_TIP = "Fills the whole screen. Alt+F4 closes the app; switch the mode back here to get a frame again."
_WHEN_DONE_TIP = ("What happens once the queue has finished its last job. Shutdown, Sleep, Hibernate "
                  "and Log Off give you 30 seconds to cancel first.")
_WHEN_DONE_RESET_TIP = ("Starts every launch on 'Do Nothing', so a Shutdown you picked for one long "
                        "encode can't catch you out next time.")
_STARTUP_TAB_TIP = "Which tab the app opens on each time it launches."
_LOG_DETAIL_TIP = ("Normal records what the app does and any problems. Detailed also records ffmpeg's and "
                   "yt-dlp's full output for each job and the app's debug-level messages, which helps "
                   "when reporting a bug. Applies to the log right away, and to jobs started afterwards.")
_OPEN_LOG_TIP = "Opens the folder holding LlamaMXD's log file and the saved output of jobs that ran."
_SHORTCUTS_HELP = ("Click a shortcut, then press the key you want it on (click anywhere else to leave it "
                   "as it is). Turn a shortcut off with its switch.")

# "Available space" on the Default Save Location's drive turns red at or
# below this, in binary GB (matching system_info.format_bytes's units).
_LOW_DISK_BYTES = 25 * 1024 ** 3


class _Swatch(QWidget):
    """A 26px rounded chip showing one colour of the previewed palette."""

    def __init__(self, key):
        super().__init__()
        self.key = key
        self.theme_name = None
        scale.fixed(self, 26, 26)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), fpx(4), fpx(4))
        p.fillPath(path, QColor(get_theme(self.theme_name)[self.key]))


class SettingsTab(QWidget):
    @staticmethod
    def _page():
        """An empty, top-left-anchored settings page: `(widget, layout)`."""
        page = QWidget()
        lay = QVBoxLayout(page)
        # Small top margin: the header row is as tall as the (three-line) system
        # info, well past the tab bar, so it already supplies most of the gap.
        scale.margins(lay, _SIDE_PAD, 6, _SIDE_PAD, 10)
        lay.setSpacing(0)
        lay.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        return page, lay

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self._committed = T.theme.name

        # Three sub-tabs (the same SubTabBar Muxing/Encoding use), each page a
        # short list so nothing is overwhelming. **Each page has its own scroll
        # area**, not one shared around the whole stack: a plain `QStackedWidget`
        # (or a shared `QScrollArea` wrapping it) sizes itself to its *tallest*
        # ever-shown page via its internal `QStackedLayout` — which forces its
        # own `setMinimumSize`/`sizeHint` on the container widget at the C++
        # layout-activation level, a layer overriding `sizeHint()`/
        # `minimumSizeHint()` in a Python subclass can't reach (confirmed: even
        # `widget.resize(widget.sizeHint())` right after switching pages snapped
        # straight back to the tallest page's height). Measured before this fix:
        # `self.pages.height()` was a constant 505 (Shortcuts' own height) on
        # *every* sub-page, so Appearance (244) scrolled inside a box it never
        # needed to. Giving each page its own `QScrollArea` sidesteps the whole
        # class of problem — each one only ever sizes itself off *its own*
        # single child, so switching sub-tabs genuinely changes whether a
        # scrollbar shows: Shortcuts (many keybind rows) still gets one, short
        # pages like About don't. Reset / Save stay pinned below, outside the
        # stack entirely.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # System info (read-only: CPU / GPU / RAM) — a fixed-width corner
        # label, not a row in the main column: a bare CPU name can run past
        # 30 characters, and letting it size to its own content could grow
        # wider than the tab frame on a smaller screen or a DPI change from
        # dragging the window to another monitor, spilling text past the
        # frame's rounded border. It sits in the tab bar's own full-width row
        # after a stretch, so it lands at the frame's real right edge.
        self._header_row, hl = hrow(spacing=0, align_bottom=False)
        scale.margins(hl, _SIDE_PAD, _TOP_PAD, _SIDE_PAD, 0)
        self.sub_tab_bar = SubTabBar(SETTINGS_PAGES)
        hl.addWidget(self.sub_tab_bar, 0, Qt.AlignTop)
        hl.addStretch(1)
        ram_text = f"{system_info.format_bytes(system_info.ram_total_bytes())} RAM"
        # One paragraph per line so `line-height` can open them up a little (a
        # plain newline-joined label has no spacing knob). Escaped: a device
        # name is arbitrary text.
        sys_lines = (system_info.cpu_name(), gpu.display_name(), ram_text)
        sys_info = ScaledLabel("".join(
            f'<p style="margin:0; line-height:125%;">{html.escape(line)}</p>' for line in sys_lines))
        sys_info.setTextFormat(Qt.RichText)
        sys_info.setProperty("role", "muted")
        # 12px like the option names (the `muted` role is 11px); a widget-level rule
        # so the role's theme-driven colour still applies.
        sys_info.setStyleSheet("font-size: 12px;")
        sys_info.setAlignment(Qt.AlignRight | Qt.AlignTop)
        sys_info.setWordWrap(True)
        scale.fixed(sys_info, w=230)
        hl.addWidget(sys_info, 0, Qt.AlignTop)
        outer.addWidget(self._header_row)

        self.pages = QStackedWidget()
        page_appearance, pa = self._page()
        page_output, po = self._page()
        page_performance, pp = self._page()
        page_shortcuts, pk = self._page()
        page_about, pab = self._page()
        for page in (page_appearance, page_output, page_performance, page_shortcuts, page_about):
            page_scroll = QScrollArea()
            page_scroll.setWidgetResizable(True)
            page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            page_scroll.setWidget(page)
            self.pages.addWidget(page_scroll)
        self.sub_tab_bar.changed.connect(self._on_subtab_changed)
        outer.addWidget(self.pages, 1)

        # ================= Appearance =================
        # -- Theme
        pa.addWidget(field_label("Theme:"), 0, Qt.AlignLeft)
        scale.spacer(pa, 4)
        row, rl = hrow(spacing=0, align_bottom=False)
        self.theme_menu = Dropdown(list(THEMES), width=150)
        self.theme_menu.set(self._committed)
        self.theme_menu.hovered.connect(self._preview_theme)
        self.theme_menu.picked.connect(self._on_theme_change)
        self.theme_menu.popupClosed.connect(lambda: QTimer.singleShot(0, self._end_preview))
        rl.addWidget(self.theme_menu)
        scale.spacer(rl, 12)
        self.primary_swatch, self.secondary_swatch = _Swatch("primary"), _Swatch("secondary")
        rl.addWidget(self.primary_swatch)
        scale.spacer(rl, 5)
        rl.addWidget(self.secondary_swatch)
        pa.addWidget(row, 0, Qt.AlignLeft)
        self._show_swatches(self._committed)
        scale.spacer(pa, 18)

        # -- Appearance mode
        pa.addWidget(field_label("Appearance Mode:"))
        scale.spacer(pa, 4)
        self.appearance_menu = Dropdown(["System", "Light", "Dark"], width=150)
        self.appearance_menu.set(T.theme.mode)
        self.appearance_menu.picked.connect(self._on_appearance_change)
        pa.addWidget(self.appearance_menu)
        scale.spacer(pa, 18)

        # -- Window mode (Borderless adds a Fullscreen box underneath)
        pa.addWidget(field_label("Window Mode:"))
        scale.spacer(pa, 4)
        self.window_mode_menu = Dropdown(window_mode.MODES, width=150)
        self.window_mode_menu.set(app.window_mode)
        self.window_mode_menu.picked.connect(self._on_window_mode_change)
        tip(self.window_mode_menu, _WINDOW_MODE_TIP)
        pa.addWidget(self.window_mode_menu)
        self.fullscreen_row = QWidget()
        fsl = QVBoxLayout(self.fullscreen_row)
        scale.margins(fsl, 0, 8, 0, 0)
        self.fullscreen_check = CheckBox("Fullscreen", checked=app.borderless_fullscreen)
        self.fullscreen_check.clicked.connect(self._on_fullscreen_toggle)
        tip(self.fullscreen_check, _FULLSCREEN_TIP)
        fsl.addWidget(self.fullscreen_check)
        # Parent first, then visibility: a still-parentless widget made visible is
        # its own top-level window, which flashed on screen at every Borderless launch.
        pa.addWidget(self.fullscreen_row, 0, Qt.AlignLeft)
        self.fullscreen_row.setVisible(app.window_mode == window_mode.BORDERLESS)
        scale.spacer(pa, 18)

        # ================= Output =================
        # -- Default save location
        po.addWidget(field_label("Default Save Location:"))
        scale.spacer(po, 4)
        loc, ll = hrow(spacing=8, align_bottom=False)
        self.save_location_entry = ScaledLineEdit()
        self.save_location_entry.setPlaceholderText("No default location set...")
        scale.fixed(self.save_location_entry, 300, 28)
        set_line_text(self.save_location_entry, app.default_save_location)
        self.save_location_entry.editingFinished.connect(self._sync_state_from_widgets)
        ll.addWidget(self.save_location_entry)
        browse = button("Browse", width=80)
        browse.clicked.connect(self._browse_save_location)
        ll.addWidget(browse)
        po.addWidget(loc, 0, Qt.AlignLeft)
        scale.spacer(po, 4)
        self.disk_label = ScaledLabel("")
        self.disk_label.setProperty("role", "muted")
        po.addWidget(self.disk_label)
        scale.spacer(po, 10)
        self._refresh_disk_usage()

        # -- Downloader's own save location, off by default
        self.downloader_separate_check = CheckBox(
            "Separate Save for Downloader", checked=bool(app.downloader_separate_save))
        self.downloader_separate_check.clicked.connect(self._on_downloader_separate_toggle)
        tip(self.downloader_separate_check, _SEPARATE_SAVE_TIP)
        po.addWidget(self.downloader_separate_check)
        scale.spacer(po, 8)
        self.downloader_loc_row, dll = hrow(spacing=8, align_bottom=False)
        self.downloader_location_entry = ScaledLineEdit()
        self.downloader_location_entry.setPlaceholderText("No separate location set...")
        scale.fixed(self.downloader_location_entry, 300, 28)
        set_line_text(self.downloader_location_entry,
                     app.downloader_save_location or app.default_save_location)
        self.downloader_location_entry.editingFinished.connect(self._sync_state_from_widgets)
        dll.addWidget(self.downloader_location_entry)
        downloader_browse = button("Browse", width=80)
        downloader_browse.clicked.connect(self._browse_downloader_location)
        dll.addWidget(downloader_browse)
        po.addWidget(self.downloader_loc_row, 0, Qt.AlignLeft)
        self.downloader_loc_row.setVisible(bool(app.downloader_separate_save))
        scale.spacer(po, 18)

        # -- Output file naming (the tabs autofill their Save field from this)
        po.addWidget(field_label("File Naming:"))
        scale.spacer(po, 4)
        self.naming_entry = ScaledLineEdit()
        self.naming_entry.setPlaceholderText(naming.DEFAULT_TEMPLATE)
        scale.fixed(self.naming_entry, 300, 28)
        set_line_text(self.naming_entry, app.naming_template)
        self.naming_entry.textEdited.connect(self._validate_naming_text)
        self.naming_entry.editingFinished.connect(self._commit_naming)
        tip(self.naming_entry, _NAMING_TIP)
        po.addWidget(self.naming_entry)
        scale.spacer(po, 4)
        self.naming_hint = ScaledLabel(_NAMING_HELP)
        self.naming_hint.setProperty("role", "hint")
        self.naming_hint.setWordWrap(True)
        scale.fixed(self.naming_hint, w=400)
        po.addWidget(self.naming_hint)
        scale.spacer(po, 18)

        # ================= Performance =================
        # -- Hardware acceleration (a global preference every Encode inherits)
        # With no dedicated GPU the switch is off and greyed out (`app.gpu_enabled`
        # is already False then), caption included, with the status line saying why.
        self._gpu_available = gpu.has_dedicated()
        self.gpu_label = field_label("Hardware Acceleration (GPU):")
        self.gpu_label.setEnabled(self._gpu_available)
        pp.addWidget(self.gpu_label)
        scale.spacer(pp, 4)
        self.gpu_switch = Switch(checked=bool(app.gpu_enabled))
        self.gpu_switch.setEnabled(self._gpu_available)
        self.gpu_switch.clicked.connect(self._on_gpu_toggle)
        tip(self.gpu_switch, _GPU_TIP if self._gpu_available else _GPU_UNAVAILABLE_TIP)
        pp.addWidget(self.gpu_switch)
        scale.spacer(pp, 4)
        self.gpu_status_label = ScaledLabel("")
        self.gpu_status_label.setProperty("role", "hint")
        self.gpu_status_label.setWordWrap(True)
        scale.fixed(self.gpu_status_label, w=360)
        pp.addWidget(self.gpu_status_label)
        scale.spacer(pp, 18)
        self._refresh_gpu_status()

        # -- Priority level (how hard encodes/downloads compete with other apps)
        pp.addWidget(field_label("Priority Level:"))
        scale.spacer(pp, 4)
        self.priority_menu = Dropdown(priority.LEVELS, width=Dropdown.width_for(priority.LEVELS))
        self.priority_menu.set(app.priority_level)
        self.priority_menu.picked.connect(self._on_priority_change)
        tip(self.priority_menu, _PRIORITY_TIP)
        pp.addWidget(self.priority_menu)
        scale.spacer(pp, 18)

        # -- When Done (what happens once the queue empties)
        pp.addWidget(field_label("When Done:"))
        scale.spacer(pp, 4)
        self.when_done_menu = Dropdown(power.ACTIONS, width=Dropdown.width_for(power.ACTIONS))
        self.when_done_menu.set(app.when_done)
        self.when_done_menu.picked.connect(self._on_when_done_change)
        tip(self.when_done_menu, _WHEN_DONE_TIP)
        pp.addWidget(self.when_done_menu)
        scale.spacer(pp, 8)
        self.when_done_reset_check = CheckBox(
            "Reset to 'Do Nothing' when the app is relaunched", checked=app.when_done_reset)
        self.when_done_reset_check.clicked.connect(self._on_when_done_reset_toggle)
        tip(self.when_done_reset_check, _WHEN_DONE_RESET_TIP)
        pp.addWidget(self.when_done_reset_check)
        scale.spacer(pp, 18)

        # -- Startup tab (which of the four main tabs the app opens on)
        pp.addWidget(field_label("Startup Tab:"))
        scale.spacer(pp, 4)
        self.startup_tab_menu = Dropdown(startup_tab.TABS, width=Dropdown.width_for(startup_tab.TABS))
        self.startup_tab_menu.set(app.startup_tab)
        self.startup_tab_menu.picked.connect(self._on_startup_tab_change)
        tip(self.startup_tab_menu, _STARTUP_TAB_TIP)
        pp.addWidget(self.startup_tab_menu)
        scale.spacer(pp, 18)

        # -- LlamaLog (the app's log: how much it records, and where it is)
        pp.addWidget(field_label("LlamaLog:"))
        scale.spacer(pp, 4)
        log_row, log_l = hrow(spacing=10, align_bottom=False)
        self.log_detail_menu = Dropdown(llamalog.LEVELS, width=Dropdown.width_for(llamalog.LEVELS))
        self.log_detail_menu.set(app.log_detail)
        self.log_detail_menu.picked.connect(self._on_log_detail_change)
        tip(self.log_detail_menu, _LOG_DETAIL_TIP)
        log_l.addWidget(self.log_detail_menu)
        self.open_log_btn = button("Open Log Folder", width=button_width_for(["Open Log Folder"]))
        self.open_log_btn.clicked.connect(self._open_log_folder)
        tip(self.open_log_btn, _OPEN_LOG_TIP)
        log_l.addWidget(self.open_log_btn)
        pp.addWidget(log_row, 0, Qt.AlignLeft)
        scale.spacer(pp, 18)

        # ================= Shortcuts =================
        self._build_shortcuts(pk)

        # ================= About =================
        self._build_about(pab)

        self._actions_row, actions_l = hrow(spacing=10, align_bottom=False)
        self.reset_btn = button("Reset to Default", role="danger",
                                width=button_width_for(["Reset to Default"]))
        self.reset_btn.clicked.connect(self._on_reset_defaults)
        actions_l.addWidget(self.reset_btn)
        self.save_btn = button("Save", role="action", width=150)
        self.save_btn.clicked.connect(self._on_save)
        actions_l.addWidget(self.save_btn)
        scale.margins(actions_l, _SIDE_PAD, 10, _SIDE_PAD, 16)
        outer.addWidget(self._actions_row, 0, Qt.AlignLeft)

    def style_scope(self):
        """Only what's actually on screen right now: the header row, whichever
        of the five sub-pages is showing, and the Reset/Save row — not the
        other four pages `self.pages` keeps alive underneath. See
        `MainWindow._style_tab` for why this is safe here specifically (this
        page stack is given a layout stretch rather than sized to its own
        content, so a hidden page's stale size hint has no visible effect,
        unlike Muxing/Encoding's own sub-tab stack)."""
        return (self._header_row, self.pages.currentWidget(), self._actions_row)

    def _on_subtab_changed(self, name):
        """Switch sub-pages, then catch the newly-shown one up to the live
        stylesheet/scale — it was skipped by the live-resize restyle while it
        was the hidden one (see `style_scope`/`MainWindow._style_tab`)."""
        self.pages.setCurrentIndex(SETTINGS_PAGES.index(name))
        self.app.style_now(self.pages.currentWidget())

    # ------------------------------------------------------------------ #
    #  Shortcuts
    # ------------------------------------------------------------------ #
    def _build_shortcuts(self, page):
        """The Shortcuts page: one row per action — its name, a field showing (and taking) its key,
        and a switch that turns it on or off."""
        hint = ScaledLabel(_SHORTCUTS_HELP)
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        scale.fixed(hint, w=480)
        page.addWidget(hint)
        scale.spacer(page, 10)
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        scale.grid_spacing(grid, 14, 8)
        keys = self.app.keymap
        self._key_labels, self._key_fields, self._key_switches = {}, {}, {}
        for row, action in enumerate(keybinds.ACTIONS):
            on = keys.enabled(action.id)
            name = field_label(action.name + ":")
            scale.fixed(name, w=190)
            tip(name, action.tip)
            field = KeyField(keys.key(action.id), width=170)
            field.captured.connect(lambda spec, a=action.id: self._on_key_captured(a, spec))
            tip(field, action.tip)
            switch = Switch(checked=on)
            switch.clicked.connect(lambda _=False, a=action.id: self._on_shortcut_toggled(a))
            tip(switch, "Turns this shortcut on or off.")
            name.setEnabled(on)
            field.setEnabled(on)
            grid.addWidget(name, row, 0, Qt.AlignVCenter)
            grid.addWidget(field, row, 1, Qt.AlignVCenter)
            grid.addWidget(switch, row, 2, Qt.AlignVCenter)
            self._key_labels[action.id], self._key_fields[action.id] = name, field
            self._key_switches[action.id] = switch
        page.addWidget(grid_host, 0, Qt.AlignLeft)
        scale.spacer(page, 12)
        self.reset_shortcuts_btn = button("Reset Shortcuts", width=button_width_for(["Reset Shortcuts"]))
        self.reset_shortcuts_btn.clicked.connect(self._on_reset_shortcuts)
        tip(self.reset_shortcuts_btn, "Puts every shortcut back on its default key, switched on.")
        page.addWidget(self.reset_shortcuts_btn, 0, Qt.AlignLeft)

    # ------------------------------------------------------------------ #
    #  About
    # ------------------------------------------------------------------ #
    def _about_link_row(self, page, label_text, url):
        """One row: a bold caption ("GitHub:") beside the address itself, shown as a plain
        hyperlink — underlined, in the theme's secondary colour, restyled live on a theme
        change — rather than a button, so the URL is genuinely visible, not just named in a
        tooltip."""
        row, row_l = hrow(spacing=6, align_bottom=False)
        row_l.addWidget(field_label(label_text), 0, Qt.AlignVCenter)
        link = ClickableLabel(url)
        link.setCursor(Qt.PointingHandCursor)

        def restyle_link():
            link.setStyleSheet(f"font-size: 12px; color: {T.theme.hex('secondary')}; text-decoration: underline;")

        restyle_link()
        T.theme.changed.connect(restyle_link)
        link.clicked.connect(lambda u=url: self._open_url(u))
        row_l.addWidget(link, 0, Qt.AlignVCenter)
        page.addWidget(row, 0, Qt.AlignLeft)

    def _build_about(self, page):
        """The About page: the version, links to the project (as plain hyperlinks, not buttons),
        the license notice (GNU's short one) with buttons to the full texts, and a trademark
        disclaimer trailing under all of it, uncaptioned, as fine print. Nothing here is a
        setting, so nothing is saved."""
        version_row, version_l = hrow(spacing=6, align_bottom=False)
        version_l.addWidget(field_label("Version:"), 0, Qt.AlignVCenter)
        version = ScaledLabel(f"LlamaMXD™ {VERSION}")
        version.setStyleSheet("font-size: 12px;")
        version_l.addWidget(version, 0, Qt.AlignVCenter)
        page.addWidget(version_row, 0, Qt.AlignLeft)
        scale.spacer(page, 6)

        self._about_link_row(page, "GitHub:", about.REPO_URL)
        scale.spacer(page, 4)
        self._about_link_row(page, "Issue Tracker:", about.ISSUES_URL)
        scale.spacer(page, 6)

        page.addWidget(field_label("License:"))
        scale.spacer(page, 4)
        # A little tighter than Muxing's TrackListBox's own (9, 7, 5, 7): this page's own scroll
        # area needs the notice box to fit inside 385 reference px with real margin, not just
        # barely — Qt's own scrollbar-visibility check turned out racy within a few px of that
        # edge (measured: identical content and viewport heights showed the scrollbar after one
        # resize round-trip and not after another), so "fits, just" isn't good enough here.
        notice_box = BorderedFrame(color_key="secondary")
        scale.fixed(notice_box, w=_ABOUT_NOTICE_W)
        notice_l = QVBoxLayout(notice_box)
        scale.margins(notice_l, 9, 5, 5, 5)
        # A stock QLabel, not ScaledLabel — see the identical note in MessageDialog
        # (ui/widgets/dialogs.py) for why: real text selection needs Qt's own text
        # control, which only agrees with what's on screen when Qt paints it itself.
        # This label just accepts whole-pixel font stepping during a drag in exchange
        # for a text control that's actually usable.
        #
        # `set_font_px` does NOT work here (CLAUDE.md already documents it as a no-op
        # on any label: the base `QWidget` stylesheet rule's font-size wins back over
        # a plain `.setFont()` call the moment Qt polishes the widget — confirmed with
        # a throwaway repro: right after `set_font_px` the font reads 12px, and after
        # the very next `ensurePolished()` it's back to the app-wide 13px). The fix
        # `sys_info` above already uses works because it sets the font through the
        # label's own *instance* stylesheet, which — unlike a bare `.setFont()` —
        # keeps priority over anything an ancestor's stylesheet reapplies later. Here
        # that override has to be re-applied on every scale change too (`sys_info`
        # doesn't need that, being a `ScaledLabel`, which reinterprets its own
        # unchanging "12px" as reference units instead).
        # Rich text only to turn the closing "https://www.gnu.org/licenses/." into a real
        # link — everything else about the wording and layout stays exactly `about.NOTICE`'s
        # own verbatim GPL text: escaped whole, then `\n` swapped for `<br>` one for one (so
        # a blank `\n\n` line becomes `<br><br>`, matching plain-text QLabel's own rendering
        # of it) before the one known substring — the escaped URL — is wrapped in an anchor.
        # `about.NOTICE` itself stays plain text in `core/about.py` (no Qt/HTML in `core/`).
        notice_url = "https://www.gnu.org/licenses/"

        def notice_html():
            escaped = html.escape(about.NOTICE).replace("\n", "<br>")
            link = (f'<a href="{notice_url}" style="color: {T.theme.hex("secondary")}; '
                    f'text-decoration: underline;">{notice_url}</a>')
            return escaped.replace(notice_url, link)

        notice = QLabel(notice_html())
        notice.setTextFormat(Qt.RichText)
        notice.setWordWrap(True)
        notice.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
                                       | Qt.LinksAccessibleByMouse | Qt.LinksAccessibleByKeyboard)
        notice.setCursor(Qt.IBeamCursor)
        notice.linkActivated.connect(self._open_url)
        # The anchor's colour is baked into the text (inline style, not a stylesheet rule --
        # rich text doesn't take link colour from CSS), so a theme change needs the text
        # rebuilt, not just restyled.
        T.theme.changed.connect(lambda: notice.setText(notice_html()))
        scale.bind_style(notice, lambda: f"font-size: {scale.font_px(12)}px;")
        scale.fixed(notice, w=_ABOUT_NOTICE_W - 14)
        notice_l.addWidget(notice)
        page.addWidget(notice_box, 0, Qt.AlignLeft)
        scale.spacer(page, 6)
        licenses, licenses_l = hrow(spacing=10, align_bottom=False)
        # Each sized to its own text, not to the wider of the two — "View License" doesn't need
        # to match "Third-party Licenses"' width.
        view_btn = button("View License", width=button_width_for(["View License"]))
        view_btn.clicked.connect(self._open_license)
        tip(view_btn, "Opens the full text of the GNU General Public License (LICENSE.txt).")
        licenses_l.addWidget(view_btn)
        third_party_btn = button("Third-party Licenses", width=button_width_for(["Third-party Licenses"]))
        third_party_btn.clicked.connect(self._open_licenses_folder)
        tip(third_party_btn, "Opens the folder with the license texts, and links to the source code, of the "
                             "programs, libraries and fonts LlamaMXD uses (ffmpeg, yt-dlp, Qt, ...).")
        licenses_l.addWidget(third_party_btn)
        page.addWidget(licenses, 0, Qt.AlignLeft)
        scale.spacer(page, 6)

        # No caption of its own, unlike the rows above -- a trailing disclaimer under the
        # license, not a fourth thing to label alongside GitHub/Issue Tracker/License. The
        # `hint` role (muted colour, smaller than the rest of this page's 12px) is what
        # already reads as fine print elsewhere (the naming-format hint, the GPU status line).
        # The logo's own copyright comes before the trademark claim -- two separate facts
        # (copyright protects the artwork, trademark protects the names) in one fine-print block.
        branding_notice = ScaledLabel(f"{about.TRADEMARK_NOTICE} {about.LOGO_COPYRIGHT_NOTICE}")
        branding_notice.setProperty("role", "hint")
        branding_notice.setWordWrap(True)
        scale.fixed(branding_notice, w=_ABOUT_NOTICE_W)
        page.addWidget(branding_notice)

        # This page has its own scroll area now, sized off nothing but this page's own content
        # (see the note on `self.pages` in `__init__`) — this stretch just keeps the content
        # hugging the top rather than being spread out once the scroll area stretches the page
        # to fill whatever room it's given.
        page.addStretch(1)

    def _open_local(self, path, title, message):
        """Open a file or folder with Windows' default handler; say so if it is missing or won't open."""
        if path is None or not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            llamalog.get("settings").warning("%s: %s", title, path or "not found")
            show_message(self.app, title, message)

    def _open_license(self):
        """Open the full license text (LICENSE.txt) in the default text editor."""
        self._open_local(about.license_path(), "Couldn't Open License",
                         "The license file (LICENSE.txt) wasn't found next to the app. The license is "
                         f"published at {about.REPO_URL}")

    def _open_licenses_folder(self):
        """Open the folder of third-party license texts in Explorer."""
        self._open_local(about.licenses_dir(), "Couldn't Open Folder",
                         "The licenses folder wasn't found next to the app. The same texts are in the "
                         f"project's licenses folder at {about.REPO_URL}")

    def _open_url(self, url):
        """Open a link in the user's default browser."""
        if not QDesktopServices.openUrl(QUrl(url)):
            llamalog.get("settings").warning("Couldn't open %s", url)
            show_message(self.app, "Couldn't Open Link", f"Your browser couldn't be opened. The address is:\n{url}")

    def _refresh_shortcut_rows(self):
        """Show the keymap's state in every row (after a reset)."""
        keys = self.app.keymap
        for action in keybinds.ACTIONS:
            on = keys.enabled(action.id)
            self._key_fields[action.id].set_key(keys.key(action.id))
            self._key_fields[action.id].setEnabled(on)
            self._key_labels[action.id].setEnabled(on)
            self._key_switches[action.id].setChecked(on)

    def _on_key_captured(self, action_id, spec):
        """The user pressed a key for `action_id`: take it unless another shortcut that could fire
        at the same time already has it."""
        keys = self.app.keymap
        spec = canonical(spec)
        if not spec:
            self.app.notify("That key can't be used as a shortcut.", go_to_queue=False)
            return
        other = keys.conflict(action_id, spec)
        if other is not None:
            show_message(self.app, "Shortcut Already Used",
                         f"{display_key(spec)} is already used by “{other.name}”. Pick a different "
                         "key, or turn that shortcut off first.")
            return
        keys.set_key(action_id, spec)
        self._key_fields[action_id].set_key(keys.key(action_id))
        llamalog.get("settings").info("Shortcut %s set to %s", action_id, keys.key(action_id))
        self.autosave()

    def _on_shortcut_toggled(self, action_id):
        """A row's switch. Turning one on is refused while its key has since been taken by
        another shortcut that is on."""
        keys = self.app.keymap
        switch = self._key_switches[action_id]
        on = switch.isChecked()
        if on:
            other = keys.conflict(action_id, keys.key(action_id))
            if other is not None:
                switch.setChecked(False)
                show_message(self.app, "Shortcut Already Used",
                             f"{display_key(keys.key(action_id))} is already used by “{other.name}”, "
                             "so this shortcut can't be turned on. Change one of them first.")
                return
        keys.set_enabled(action_id, on)
        self._key_fields[action_id].setEnabled(on)
        self._key_labels[action_id].setEnabled(on)
        llamalog.get("settings").info("Shortcut %s %s", action_id, "on" if on else "off")
        self.autosave()

    def _on_reset_shortcuts(self):
        self.app.keymap.reset()
        self._refresh_shortcut_rows()
        self.autosave()
        self.app.notify("Shortcuts reset to default.", go_to_queue=False)

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
            # The saved choice, not the (possibly forced-off) switch -- see
            # `MainWindow.gpu_preference`.
            "gpu_enabled": self.app.gpu_preference,
            "naming_template": self.app.naming_template,
            "priority_level": self.app.priority_level,
            "when_done": self.app.when_done,
            "when_done_reset": self.when_done_reset_check.isChecked(),
            "window_mode": self.app.window_mode,
            "borderless_fullscreen": self.app.borderless_fullscreen,
            "startup_tab": self.app.startup_tab,
            "log_detail": self.app.log_detail,
            "keybinds": self.app.keymap.to_dict(),
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
        if self._gpu_available:
            self.app.gpu_preference = self.app.gpu_enabled = self.gpu_switch.isChecked()
        self._commit_naming(save=False)
        self._refresh_disk_usage()

    def autosave(self):
        self._sync_state_from_widgets()
        save_settings(self._settings_snapshot())

    def on_leave(self):
        """Switching away flushes every setting to disk."""
        self.theme_menu.close()
        self.appearance_menu.close()
        self.window_mode_menu.close()
        self.priority_menu.close()
        self.when_done_menu.close()
        self.startup_tab_menu.close()
        self.log_detail_menu.close()
        # A format left half-typed and invalid isn't kept around: show the one
        # actually in use when the tab is next opened.
        if naming.template_error(self.naming_entry.text()):
            set_line_text(self.naming_entry, self.app.naming_template)
            self._validate_naming_text(self.app.naming_template)
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

    def _on_window_mode_change(self, mode):
        """Apply the window mode at once; the Fullscreen box only exists for
        Borderless (its own choice is remembered while another mode is on)."""
        self.fullscreen_row.setVisible(mode == window_mode.BORDERLESS)
        self.app.set_window_mode(mode, self.fullscreen_check.isChecked())
        self.autosave()

    def set_fullscreen(self, on):
        """The Fullscreen Window shortcut while in Borderless: the Fullscreen box follows it."""
        self.fullscreen_check.setChecked(bool(on))
        self._on_fullscreen_toggle()

    def _on_fullscreen_toggle(self, *_):
        self.app.set_window_mode(self.window_mode_menu.value(), self.fullscreen_check.isChecked())
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

    def _validate_naming_text(self, text):
        """Live feedback while typing the naming format: the token help, or
        what's wrong with it in STOP_RED. Nothing is applied until Enter /
        focus leaves (`_commit_naming`), and never while it's invalid."""
        error = naming.template_error(text)
        self.naming_hint.setText(error or _NAMING_HELP)
        self.naming_hint.setProperty("role", "error" if error else "hint")
        restyle(self.naming_hint)

    def _commit_naming(self, save=True):
        """Adopt the typed naming format if it's valid and changed — every
        tab's autofilled Save field re-derives from it at once."""
        text = self.naming_entry.text().strip()
        if naming.template_error(text) or text == self.app.naming_template:
            return
        self.app.set_naming_template(text)
        if save:
            self.autosave()

    def _on_priority_change(self, level):
        self.app.set_priority_level(level)
        self.autosave()

    def _on_when_done_change(self, action):
        self.app.when_done = action
        self.autosave()

    def _on_startup_tab_change(self, tab):
        """Only what the *next* launch opens on: the current session stays put."""
        self.app.startup_tab = tab
        self.autosave()

    def _on_log_detail_change(self, level):
        """Normal or Detailed: the log follows at once; ffmpeg and yt-dlp pick it up on the next job."""
        self.app.log_detail = level
        llamalog.set_detail(level)
        self.autosave()

    def _open_log_folder(self):
        error = llamalog.open_log_folder()
        if error:
            show_message(self.app, "LlamaLog", error)

    def _on_when_done_reset_toggle(self, *_):
        self.app.when_done_reset = self.when_done_reset_check.isChecked()
        self.autosave()

    def _on_gpu_toggle(self, *_):
        self.app.gpu_preference = self.app.gpu_enabled = self.gpu_switch.isChecked()
        llamalog.get("settings").info("Hardware acceleration %s", "on" if self.gpu_switch.isChecked() else "off")
        self._refresh_gpu_status()
        self.autosave()

    def _refresh_gpu_status(self):
        if self._gpu_available and not self.gpu_switch.isChecked():
            self.gpu_status_label.setText("Off — encodes run in software.")
        else:
            # Either what it would use, or (no dedicated GPU) why it's unavailable.
            self.gpu_status_label.setText(gpu.summary_label())

    def _on_save(self):
        self.autosave()
        self.app.notify("Settings saved.", go_to_queue=False)

    def _on_reset_defaults(self):
        if not ask_yes_no(
            self.app, "Reset to Default?",
            "This resets the theme, appearance mode, window mode, default save location, "
            "Downloader save location, file naming, hardware acceleration, "
            "priority level, When Done, Startup Tab, log detail and keyboard shortcuts back to their "
            "defaults. Continue?",
        ):
            return
        self._committed = DEFAULT_THEME_NAME
        self.theme_menu.set(DEFAULT_THEME_NAME)
        self._show_swatches(DEFAULT_THEME_NAME)
        T.theme.set_theme(DEFAULT_THEME_NAME)
        self.appearance_menu.set("System")
        T.theme.set_mode("System")
        self.window_mode_menu.set(window_mode.DEFAULT_MODE)
        self.fullscreen_check.setChecked(False)
        self.fullscreen_row.setVisible(False)
        self.app.set_window_mode(window_mode.DEFAULT_MODE, False)
        location = default_output_dir()
        set_line_text(self.save_location_entry, location)
        self.app.set_default_save_location(location)
        self.downloader_separate_check.setChecked(False)
        self.downloader_loc_row.setVisible(False)
        set_line_text(self.downloader_location_entry, "")
        self.app.downloader_save_location = ""
        self.app.set_downloader_separate_save(False)
        self.app.gpu_preference = True
        self.app.gpu_enabled = self._gpu_available
        self.gpu_switch.setChecked(self._gpu_available)
        self._refresh_gpu_status()
        set_line_text(self.naming_entry, naming.DEFAULT_TEMPLATE)
        self._validate_naming_text(naming.DEFAULT_TEMPLATE)
        self.app.set_naming_template(naming.DEFAULT_TEMPLATE)
        self.priority_menu.set(priority.DEFAULT_LEVEL)
        self.app.set_priority_level(priority.DEFAULT_LEVEL)
        self.when_done_menu.set(power.DO_NOTHING)
        self.app.when_done = power.DO_NOTHING
        self.when_done_reset_check.setChecked(True)
        self.app.when_done_reset = True
        self.startup_tab_menu.set(startup_tab.DEFAULT_TAB)
        self.app.startup_tab = startup_tab.DEFAULT_TAB
        self.log_detail_menu.set(llamalog.DEFAULT_LEVEL)
        self.app.log_detail = llamalog.DEFAULT_LEVEL
        llamalog.set_detail(llamalog.DEFAULT_LEVEL)
        self.app.keymap.reset()
        self._refresh_shortcut_rows()
        self._refresh_disk_usage()
        self.autosave()
        llamalog.get("settings").info("Settings reset to their defaults")
        self.app.notify("Settings reset to default.", go_to_queue=False)
