# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""The main window and the app's hub: shared state, the file-selection
broadcast, background work (probe + preview frames, HDR renders, yt-dlp
fetches, the Deno check), tab routing, keybinds, toasts and the close prompt.

Every tab is built once and lives in a QStackedWidget. A tab switch is one
`setCurrentWidget` — Qt hides one page and shows another inside a single
native window and presents the result as one frame, so there's no re-mapping
of hundreds of child windows and nothing fills in piece by piece."""
import os
import threading
import time

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLayout,
    QLineEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from core import downloader, formats, gpu, llamalog, power, priority, window_mode, window_style
from core.theme import load_settings
from core.utilities import (
    extract_hdr_tonemapped_thumbnails,
    extract_video_thumbnails,
    libplacebo_problem,
    probe_media,
)
from ui import scale
from ui import theme as T
from ui.keymap import KeyMap
from ui.keynav import KeyNav
from ui.tabs.downloader import DownloaderTab
from ui.tabs.encoding import EncodingTab
from ui.tabs.media_tab import set_line_text
from ui.tabs.muxing import MuxingTab
from ui.tabs.queue import QueueTab
from ui.tabs.settings import SettingsTab
from ui.widgets.controls import Dropdown
from ui.widgets.dialogs import ask_yes_no, confirm_countdown, show_message
from ui.widgets.frameless import ResizeGrips, WindowControls
from ui.widgets.panels import ASSETS, Sidebar, TabIndicator
from ui.scale import px
from ui.widgets.toast import ToastManager
from ui.workers import emit_progress, pil_to_qimage, run_async

TAB_NAMES = ("Muxing", "Encoding", "Downloader", "Queue", "Settings")

_QWIDGETSIZE_MAX = 16777215   # Qt's "no maximum size"

_MEDIA_INFO_KEYS = ("container", "video", "audio", "video_profile", "video_level", "hdr",
                    "width", "height", "duration", "file_size", "has_video", "has_audio",
                    "title", "chapters", "bit_rate", "creation_time")


def _probe_summary(info):
    """One line describing a probe result, for the log."""
    parts = [info.get("container") or "?"]
    if info.get("video"):
        size = f"{info.get('width')}x{info.get('height')}" if info.get("width") else "?"
        parts.append(f"video {info['video']} {size}{' HDR' if info.get('hdr') else ''}")
    elif info.get("has_video") is False:
        parts.append("no video")
    if info.get("audio"):
        count = len(info.get("audio_streams") or [])
        parts.append(f"audio {info['audio']}" + (f" (+{count - 1} more)" if count > 1 else ""))
    elif info.get("has_audio") is False:
        parts.append("no audio")
    if info.get("duration"):
        parts.append(f"{info['duration']:.1f}s")
    if info.get("file_size"):
        parts.append(f"{info['file_size'] / 1024 ** 2:.1f} MB")
    return ", ".join(parts)


def _preview_max_size():
    """The largest a preview frame is ever drawn, in device pixels: the biggest screen (the
    expanded preview fills at most the window, the window at most its screen). Frames are
    stored no bigger — a 4K frame kept whole is 33MB, ten of them per set."""
    sizes = [(round(s.geometry().width() * s.devicePixelRatio()), round(s.geometry().height() * s.devicePixelRatio()))
             for s in QGuiApplication.screens()]
    return max(sizes, key=lambda size: size[0] * size[1]) if sizes else None


def _empty_media_info():
    """"Unknown" for every probe field — None never reads as absent."""
    info = dict.fromkeys(_MEDIA_INFO_KEYS)
    info["audio_streams"] = []
    return info


class _MainLayout(QHBoxLayout):
    """The window's own layout, opted out of height-for-width. Word-wrapped
    labels deep in a page (Settings has several) make a plain layout report
    it, and Qt then restores a maximised or fullscreen window at the height
    those labels want at the *outgoing* scale — 1388px tall on a 540px
    window — instead of the size it had."""

    def hasHeightForWidth(self):
        return False

    def heightForWidth(self, width):
        return -1

    def minimumHeightForWidth(self, width):
        return -1


class _TabFrame(QWidget):
    """The rounded panel the pages sit on. Painted rather than styled: a
    stylesheet rule on it would cascade over — and re-style — every page under
    it on each rescale, which is the one cost live resizing can't afford."""

    def __init__(self):
        super().__init__()
        T.theme.changed.connect(self.update)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), px(6), px(6))
        p.fillPath(path, T.theme.color("frame"))


def _is_typing(widget):
    """Is `widget` a place keys are typed into (so the shortcuts must leave the keys alone)?"""
    return isinstance(widget, QLineEdit) or type(widget).__name__ == "_TimeField"


class _Keybinds(QObject):
    """Global keybinds, filtered at the application level so they work
    wherever focus happens to be — unless focus is on something the key
    already means something for. Which key does what is the user's
    (`MainWindow.keymap`, Settings' Shortcuts page); this decides *when* each
    one may fire. Also clears a text field's focus the moment a click lands
    somewhere else: every clickable in this app is `Qt.NoFocus` (see
    Conventions), so Qt's own default — a click that lands on a widget which
    never takes focus simply leaves focus wherever it already was — otherwise
    left a line edit looking and behaving focused (cursor still blinking,
    still first in line for Ctrl+A/paste) long after the user had clicked off
    it onto a button or blank space."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.MouseButtonPress:
            focus = QApplication.focusWidget()
            if (_is_typing(focus) or getattr(focus, "captures_keys", False)) and obj is not focus:
                focus.clearFocus()
            self.window.keynav.dismiss()      # the mouse took over: no keyboard selection left behind
            return False
        if kind != QEvent.KeyPress:
            return False
        win = self.window
        # An open dropdown list owns the arrow keys and Enter, whatever else is going on.
        dropdown = Dropdown.open_one
        if dropdown is not None and isValid(dropdown) and dropdown._open:
            return win.keynav.dropdown_key(dropdown, event)
        if not win.isActiveWindow() or QApplication.activeModalWidget() is not None:
            return False
        focus = QApplication.focusWidget()
        if getattr(focus, "captures_keys", False):
            return False          # a Shortcuts field is listening for the next key, whatever it is
        keys = win.keymap
        repeat = event.isAutoRepeat()
        expanded = win.preview_expanded()
        typing = _is_typing(focus)

        # These two work from inside a text field too: F11 means nothing there, and Tab is how
        # you leave it. Always consumed, so Qt's own Tab (which hops into the next text field and
        # would leave the shortcuts standing aside) never runs; an expanded preview covers every
        # control, so Tab has nowhere to go then.
        if keys.matches("fullscreen", event):
            if not repeat:
                win.toggle_fullscreen()
            return True
        step = keys.step("focus_next", event)
        if step:
            if not repeat and not expanded:
                win.keynav.step(step)
            return True
        if typing:
            return False

        tab = win.tabs.get(win.current_tab)
        carousel = getattr(tab, "carousel", None)
        # (action, may repeat while held, handler -> True if it acted)
        table = (
            ("preview_prev", True, lambda: self._step_preview(carousel, -1)),
            ("preview_next", True, lambda: self._step_preview(carousel, 1)),
            ("collapse_preview", False, win.collapse_previews),
            ("expand_preview", False, lambda: carousel is not None and carousel.toggle_expand()),
            ("toggle_queue", False, lambda: self._toggle_queue(focus)),
            ("tab_prev", False, lambda: not expanded and win.cycle_tab(-1)),
            ("tab_next", False, lambda: not expanded and win.cycle_tab(1)),
            ("activate", False, lambda: not expanded and win.keynav.activate()),
        )
        for action, may_repeat, handler in table:
            if keys.matches(action, event):
                if repeat and not may_repeat:
                    return True
                if handler():
                    return True
        return False

    @staticmethod
    def _step_preview(carousel, delta):
        """Left / Right: step the current tab's preview (its tab has one, or this isn't ours)."""
        if carousel is None:
            return False
        carousel.step(delta)
        return True

    def _toggle_queue(self, focus):
        """Space on the Queue tab starts / pauses it — unless a button or dropdown has focus."""
        win = self.window
        if win.current_tab != "Queue" or isinstance(focus, (QAbstractButton, QComboBox)):
            return False
        win.tabs["Queue"].toggle_queue()
        return True


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        # {widget: (stylesheet text, scale)} — what each stylesheet target was last
        # given, and the scale its layouts were last invalidated for.
        self._styled = {}
        T.theme.changed.connect(self.update)
        self.setWindowTitle("LlamaMXD")
        icon = os.path.join(ASSETS, "llama.ico")
        if os.path.exists(icon):
            self.setWindowIcon(QIcon(icon))

        settings = load_settings()
        self.current_file_path = ""
        self.default_save_location = settings["default_save_location"]
        # `gpu_preference` is what the user chose (and what gets saved);
        # `gpu_enabled` is what jobs actually use -- forced off on a machine
        # with no dedicated GPU, without overwriting the saved choice (a GPU
        # added later picks the preference back up).
        self.gpu_preference = bool(settings["gpu_enabled"])
        self.gpu_enabled = self.gpu_preference and gpu.has_dedicated()
        # The Downloader's own save folder, used instead of the shared
        # default only while separate-save is on and a folder's been set.
        self.downloader_separate_save = bool(settings["downloader_separate_save"])
        self.downloader_save_location = settings["downloader_save_location"] or ""
        # Settings' output naming format (`core.naming`), the Queue's job
        # priority, and what to do when the queue empties. "When Done" starts
        # over at Do Nothing when its reset-on-launch flag is set, so a
        # Shutdown chosen last session can't surprise this one.
        self.naming_template = settings["naming_template"]
        self.priority_level = settings["priority_level"]
        self.when_done_reset = bool(settings["when_done_reset"])
        self.when_done = power.DO_NOTHING if self.when_done_reset else settings["when_done"]
        # Settings' window mode (`core.window_mode`) and, for Borderless, whether
        # it fills the screen.
        self.window_mode = settings["window_mode"]
        self.borderless_fullscreen = bool(settings["borderless_fullscreen"])
        # F11 in Windowed / Fixed: fullscreen for this session only (Borderless's is a setting).
        self._session_fullscreen = False
        # Settings' log detail (`core.llamalog`): Normal or Detailed.
        self.log_detail = settings["log_detail"]
        llamalog.set_detail(self.log_detail)
        # Settings' keyboard shortcuts (`core.keybinds`): which key does what, and which are on.
        self.keymap = KeyMap(settings["keybinds"])
        llamalog.get("settings").info(
            "Settings: theme=%s appearance=%s window=%s gpu=%s priority=%s when_done=%s startup_tab=%s "
            "naming=%r save=%s", settings["theme"], settings["appearance_mode"], self.window_mode,
            self.gpu_enabled, self.priority_level, self.when_done, settings["startup_tab"],
            self.naming_template, self.default_save_location)
        if self.default_save_location:
            try:
                os.makedirs(self.default_save_location, exist_ok=True)
            except OSError as exc:
                llamalog.get("settings").warning("Couldn't create the default save folder %s: %s",
                                                 self.default_save_location, exc)

        # Preview frames (QImages) for the selected file, decoded once off
        # the GUI thread and cached so tab switches never re-decode.
        self.thumb_frames = []
        self.thumb_frames_path = None
        self._thumb_token = 0
        self.media_info = _empty_media_info()
        self._media_info_path = None
        self._preview_index = 0
        # HDR→SDR tone-mapped preview frames, cached per file.
        self.hdr_frames = None
        self.hdr_frames_path = None
        self._hdr_inflight_path = None
        self._hdr_token = 0
        self._hdr_cancel_event = None
        self._hdr_cancelled_token = 0     # the render a file change interrupted: its late, empty result is dropped
        # Downloader: the last successful fetch, and a token so a superseded
        # fetch's late result is dropped.
        self.ytdlp_cache = None
        self._ytdlp_token = 0
        self.deno_missing = False
        self.media_tabs = []
        # Settings' "Startup Tab" (`core.startup_tab`): the tab the app opens on.
        self.startup_tab = settings["startup_tab"]
        self.current_tab = self.startup_tab

        # Starts at 35% of the screen's width at the reference aspect ratio,
        # centred. The window's size sets the UI scale (`ui.scale`) — adopted
        # before any widget is built, so every size in the app is already at
        # this scale when it's constructed. `_apply_window_mode` (last thing
        # in here) then fixes, frees or strips the window per Settings.
        scale.changed.connect(self._on_scale_changed)
        self._replace_pending = False
        screen = self.screen().geometry()
        width, height = scale.window_size(screen.width(), screen.height())
        scale.set_factor(scale.fit(width, height))
        self.resize(width, height)
        self.move(screen.x() + (screen.width() - width) // 2, screen.y() + (screen.height() - height) // 2)

        layout = _MainLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # The window's size limits are `_apply_window_mode`'s to set, not
        # whatever the layout's own minimum would impose at the current scale
        # (which would stop a shrinking window from ever lowering it).
        layout.setSizeConstraint(QLayout.SetNoConstraint)
        self.sidebar = Sidebar()
        self.sidebar.navigate.connect(self.show_tab)
        layout.addWidget(self.sidebar)

        frame_host = QVBoxLayout()
        scale.margins(frame_host, 10)
        self.tab_frame = _TabFrame()
        inner = QVBoxLayout(self.tab_frame)
        inner.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        inner.addWidget(self.stack)
        frame_host.addWidget(self.tab_frame)
        layout.addLayout(frame_host, 1)

        self.tabs = {}
        self.tabs["Queue"] = QueueTab(self)       # built first: the others read it
        self.tabs["Muxing"] = MuxingTab(self)
        self.tabs["Encoding"] = EncodingTab(self)
        self.tabs["Downloader"] = DownloaderTab(self)
        self.tabs["Settings"] = SettingsTab(self)
        for name in TAB_NAMES:
            self.stack.addWidget(self.tabs[name])
        self.stack.setCurrentWidget(self.tabs[self.current_tab])
        # Everything was just built under the application-level sheet, which is
        # current: record that so `_restyle` knows what still needs the new one.
        css = T.stylesheet()
        for target in (self.sidebar, *self.tabs.values()):
            self._styled[target] = (css, scale.factor())

        self.indicator = TabIndicator(self)
        self.toasts = ToastManager(self, lambda: self.tab_frame)
        self.keynav = KeyNav(self)
        self._grips = ResizeGrips(self)
        # Borderless has no OS title bar, so it gets its own close / maximise /
        # minimise, in the strip above the sidebar's title (`_apply_window_mode`
        # shows them only in that mode).
        self.window_controls = WindowControls(self.sidebar)
        self.window_controls.closeRequested.connect(self.close)
        self.window_controls.maximizeRequested.connect(self._toggle_maximized)
        self.window_controls.minimizeRequested.connect(self.showMinimized)
        self._apply_window_mode()

        self._keybinds = _Keybinds(self)
        QApplication.instance().installEventFilter(self._keybinds)
        T.theme.changed.connect(self._restyle)
        T.theme.changed.connect(self._sync_titlebar)

        run_async(downloader.deno_path, self._deliver_deno_check)
        # Warm the (cached) libplacebo/Vulkan probe: it is a real ffmpeg run, so
        # it belongs off the GUI thread and ahead of the first HDR file.
        run_async(libplacebo_problem, lambda _problem: None)

    # ------------------------------------------------------------------ #
    #  Tabs
    # ------------------------------------------------------------------ #
    def show_tab(self, name, animate=True):
        outgoing = self.tabs.get(self.current_tab)
        incoming = self.tabs[name]
        if outgoing is not None and outgoing is not incoming:
            self.keynav.dismiss()
            on_leave = getattr(outgoing, "on_leave", None)
            if callable(on_leave):
                on_leave()
        self.current_tab = name
        self.stack.setCurrentWidget(incoming)
        # Only once it's visible: a hidden widget restyled doesn't invalidate
        # its parent's layout, so its size hints stay cached at the old scale.
        if self._style_tab(incoming):
            scale.settle()      # sizes measured off this page's hints, now against its new sheet
        on_enter = getattr(incoming, "on_enter", None)
        if callable(on_enter):
            on_enter()
        self.indicator.set_active(name, self.sidebar.buttons, self.tab_frame.x(), animate=animate)
        self._restack()
        if not isinstance(QApplication.focusWidget(), QLineEdit):
            self.setFocus()
        self.toasts.relayout()

    def cycle_tab(self, step):
        """Go `step` tabs down (+1) or up (-1) the sidebar, wrapping round at the ends."""
        index = (TAB_NAMES.index(self.current_tab) + step) % len(TAB_NAMES)
        self.show_tab(TAB_NAMES[index])
        return True

    def preview_expanded(self):
        """Is a media tab's preview blown up over the window?"""
        return any(getattr(tab.carousel, "_expanded", False) for tab in self.media_tabs)

    def collapse_previews(self):
        """Shrink any expanded preview back. True if there was one."""
        expanded = [tab for tab in self.media_tabs if getattr(tab.carousel, "_expanded", False)]
        for tab in expanded:
            tab.carousel.force_collapse()
        return bool(expanded)

    def showEvent(self, e):
        super().showEvent(e)
        # Geometry is final once shown — no after(50) guesswork needed.
        QTimer.singleShot(0, lambda: self.show_tab(self.current_tab, animate=False))

    def notify(self, message, go_to_queue=True):
        """A toast at the tab frame's top-right; clicking it opens the Queue."""
        self.toasts.show(message, on_click=(lambda: self.show_tab("Queue")) if go_to_queue else None)

    # ------------------------------------------------------------------ #
    #  Styling: only what's on screen, the rest when it's shown
    # ------------------------------------------------------------------ #
    def paintEvent(self, _event):
        QPainter(self).fillRect(self.rect(), T.theme.color("window"))

    def _style(self, target):
        """Give `target` (the sidebar or a page) the current stylesheet if it
        doesn't have it yet, and re-measure its layouts if the scale moved;
        True when it did either. Applied on the widget itself, which overrides
        the application-level sheet the app started with and touches only that
        subtree. The sheet is compared by *text*: every length in it is a whole
        pixel, so between two nearby scales (a drag moves it a thousandth per
        pixel) it is often byte-identical, and then there is nothing to
        re-apply. The layouts are keyed on the *scale* as well, though: a text
        label's size hint follows the scale continuously (`ScaledLabel`), not
        the sheet's whole pixels, and a hidden page's `updateGeometry` calls
        reach nothing — so its layouts must be invalidated here, when it is
        next made current, or it would show hints from an older scale."""
        css = T.stylesheet()
        key = (css, scale.factor())
        prev = self._styled.get(target)
        if prev == key:
            return False
        if prev is None or prev[0] != css:
            target.setStyleSheet(css)
        self._styled[target] = key
        # A restyle doesn't refresh the cached size hints of widgets that are
        # hidden inside the page (Encoding's Video and Audio panels while
        # Overview shows), and the stack above takes the tallest page's hint —
        # so the preview would stay sized for the old scale until that panel
        # was next shown. Invalidate every layout in the subtree explicitly.
        for layout in target.findChildren(QLayout):
            layout.invalidate()
        if target.layout() is not None:
            target.layout().invalidate()
        return True

    def _restyle(self):
        """The theme or the scale changed. Re-applying the one application-wide
        sheet re-styles all ~500 widgets (~185ms — measured; the same sheet on
        the window itself is ~45ms, on one page ~13ms), far too slow to follow
        a window being dragged. So only the sidebar and the page on screen are
        restyled now; a page that isn't showing catches up in `show_tab`."""
        if not getattr(self, "tabs", None):
            # Nothing is built yet (the scale moved during construction): the
            # application-level sheet is all there is.
            QApplication.instance().setStyleSheet(T.stylesheet())
            return
        self._style(self.sidebar)
        self._style_tab(self.tabs[self.current_tab])

    def _style_tab(self, tab):
        """`_style`, scoped to what a tab says is actually on screen right now
        (`tab.style_scope()`) instead of the tab's whole widget tree.

        A plain `_style(tab)` would call `setStyleSheet` on the tab's own
        top-level widget, which — because Qt's stylesheet engine re-polishes
        an entire subtree on every `setStyleSheet` call, visible or not —
        re-styles every sub-tab page a tab keeps alive in its own internal
        `QStackedWidget` (Muxing/Encoding's Video/Audio panels, Settings'
        other four pages), even though only one is ever on screen. A tab can
        opt in by implementing `style_scope()` — returning just the widgets
        genuinely visible right now — and must then also call
        `MainWindow.style_now()` on a sub-page the moment it's switched to, so
        that page catches up instead of showing whatever it looked like the
        last time this ran (mirrors how `show_tab` already catches up a
        newly-shown top-level tab). Tabs that don't implement it (Downloader,
        Queue — no internal sub-tab stack, so there's nothing to skip) are
        restyled exactly as before.

        Not used for Muxing/Encoding's own sub-tab stack: their preview above
        it sizes off `panels.sizeHint()`, which — by design (`QStackedWidget`
        sizes to its *tallest ever-shown* page, so a sub-tab switch never
        resizes the preview) — depends on every page's size hint staying
        accurate at the *current* scale, hidden ones included. Skipping their
        restyle would let a hidden page's hint go stale and could size the
        preview against last scale's numbers — exactly the kind of drift the
        Muxing/Encoding preview-height invariant exists to prevent. Settings'
        own sub-pages carry no such risk: `self.pages` is given a layout
        stretch (fills whatever room it's left, never sized to its own
        content), so a stale hidden page's hint has no visible consequence."""
        scope_fn = getattr(tab, "style_scope", None)
        if scope_fn is None:
            return self._style(tab)
        return any([self._style(w) for w in scope_fn()])

    def style_now(self, widget):
        """Catch `widget` up to the live stylesheet/scale right away. For a
        sub-tab page a tab's own `style_scope()` leaves out of the live-resize
        restyle (see `_style_tab`) — called the moment that page is actually
        switched to, the same way `show_tab` catches up a newly-shown tab."""
        if self._style(widget):
            scale.settle()

    # ------------------------------------------------------------------ #
    #  Window mode + size
    # ------------------------------------------------------------------ #
    def set_window_mode(self, mode, fullscreen):
        """Settings' Window Mode (and, for Borderless, its Fullscreen box)."""
        if mode not in window_mode.MODES:
            return
        self._session_fullscreen = False      # an explicit choice here replaces F11's
        self.window_mode = mode
        self.borderless_fullscreen = bool(fullscreen)
        llamalog.get("settings").info("Window mode set to %s%s", mode, " (fullscreen)" if fullscreen else "")
        self._apply_window_mode()

    def _wants_fullscreen(self):
        return self._session_fullscreen or (self.window_mode == window_mode.BORDERLESS
                                            and self.borderless_fullscreen)

    def toggle_fullscreen(self):
        """The Fullscreen Window shortcut. In Borderless it is Settings' Fullscreen box (so it is
        remembered); in Windowed and Fixed it lasts until pressed again or the mode is changed."""
        if self.window_mode == window_mode.BORDERLESS:
            self.tabs["Settings"].set_fullscreen(not self.borderless_fullscreen)
            return
        self._session_fullscreen = not self._session_fullscreen
        llamalog.get("settings").info("Fullscreen %s (F11)", "on" if self._session_fullscreen else "off")
        self._apply_window_mode()

    def _apply_window_mode(self):
        """Bring the window's frame, size limits and state in line with the
        mode: Fixed is the reference-shaped window, not resizable; Windowed and
        Borderless are free to resize, never below the default size;
        Borderless drops the frame (moved by the sidebar, resized by
        `ResizeGrips`) and can fill the screen."""
        mode = self.window_mode
        frameless = mode == window_mode.BORDERLESS
        visible = self.isVisible()
        # Back to an ordinary window first — a fullscreen or maximised state
        # would fight the size limits set below.
        size = None
        if visible and (self.isFullScreen() or self.isMaximized()):
            size = self.normalGeometry().size()
            self.showNormal()
            # Let the restore finish: flipping the frame flag before it has
            # would re-show the window maximised and swallow the resizes below.
            QApplication.processEvents()
        screen = self.screen().geometry()
        fixed_size = scale.window_size(screen.width(), screen.height())
        if mode == window_mode.FIXED:
            size = QSize(*fixed_size)
        elif size is None:
            size = self.size()
        if bool(self.windowFlags() & Qt.FramelessWindowHint) != frameless:
            self.setWindowFlag(Qt.FramelessWindowHint, frameless)   # hides a visible window
            if visible:
                self.show()
                # Adding or dropping the frame leaves Windows with a client
                # area a title bar and borders smaller than Qt believes it is
                # (880x501 for 896x540) — and Qt, seeing no change, never
                # corrects it. Make it see one.
                self.setMinimumSize(0, 0)
                self.setMaximumSize(_QWIDGETSIZE_MAX, _QWIDGETSIZE_MAX)
                self.resize(size.width() + 1, size.height() + 1)
                self.resize(size)
        fullscreen = self._wants_fullscreen()
        if mode == window_mode.FIXED and not fullscreen:
            self.setFixedSize(size)
            self.move(screen.x() + (screen.width() - size.width()) // 2,
                      screen.y() + (screen.height() - size.height()) // 2)
        else:
            # (A Fixed window that F11 made fullscreen is free for as long as it is.)
            self.setMinimumSize(*fixed_size)
            self.setMaximumSize(_QWIDGETSIZE_MAX, _QWIDGETSIZE_MAX)
        if visible:
            # Qt leaves the maximize button as it was: a Fixed window must not
            # have one, a resizable one must.
            window_style.set_maximize_box(int(self.winId()), mode != window_mode.FIXED)
            self._sync_titlebar()
        if fullscreen and visible:
            self._prescale_for_screen(screen)
            self.showFullScreen()
        self._sync_window_chrome()
        self._schedule_replace()

    def _sync_titlebar(self):
        """Match the native title bar to the app's resolved Light / Dark. Qt only
        sets it when it creates a window that already has a frame, so a window
        that gained one later (Borderless -> Windowed / Fixed) has to be told."""
        if self.window_mode != window_mode.BORDERLESS and self.isVisible():
            window_style.set_dark_titlebar(int(self.winId()), T.theme.resolved_mode() == "Dark")

    def _sync_window_chrome(self):
        """Show the borderless controls and resize grips the window's current
        mode and state call for: the controls in Borderless only (fullscreen
        included — there is no OS button then either, though maximise is
        dimmed since fullscreen is a Settings choice), the grips only while the
        window is a resizable, un-maximised, non-fullscreen one."""
        frameless = self.window_mode == window_mode.BORDERLESS
        fullscreen = self._wants_fullscreen()
        self.window_controls.setVisible(frameless)
        self.window_controls.raise_()
        self.window_controls.set_maximize_enabled(not self._wants_fullscreen())
        self._grips.set_active(frameless and not fullscreen and not self.isMaximized())

    def _toggle_maximized(self):
        """The borderless maximise button: maximise, or restore if already so.
        Inert in borderless *fullscreen* (a Settings choice) — judged by the
        setting, not `isFullScreen()`: a maximised frameless window reports
        `Maximized|FullScreen`, and that would swallow the restore click."""
        if self._wants_fullscreen():
            return
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, event):
        """Maximising or restoring a borderless window hides or restores its resize grips."""
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and hasattr(self, "window_controls"):
            self._sync_window_chrome()

    def present(self):
        """Show the window the way its mode wants it shown."""
        if self._wants_fullscreen():
            self._prescale_for_screen(self.screen().geometry())
            self.showFullScreen()
        else:
            self.show()

    def _prescale_for_screen(self, screen):
        """Adopt the scale a fullscreen window will need before it is shown, so
        it opens laid out once rather than at the old scale first."""
        scale.set_factor(scale.fit(screen.width(), screen.height()))

    def resizeEvent(self, e):
        """The window's size is the UI scale: every size in the app is
        authored at the reference window and multiplied by this — rescaled on
        every resize event, so the whole window follows a drag live."""
        super().resizeEvent(e)
        self._grips.place()
        # The expanded preview covers the whole window, so follows its size.
        for tab in self.media_tabs:
            overlay = getattr(tab, "_expand_overlay", None)
            if overlay is not None and overlay.isVisible():
                overlay.setGeometry(self.rect())
        # Everything below must finish before this handler returns: Windows
        # paints synchronously between a resize and the next posted event, so
        # anything left for a queued LayoutRequest or a zero-delay timer is
        # drawn one frame late — the new window size with last step's layout,
        # and the tab pipe trailing behind its button. That was the jitter.
        # `_replace_pending` stands in for the timer `_schedule_replace` would
        # otherwise queue (the overlays are re-placed here, once).
        self._replace_pending = True
        try:
            if abs(scale.fit(self.width(), self.height()) - scale.factor()) > 1e-6:
                self._rescale_to_window()
            if hasattr(self, "indicator"):
                self._settle_layout()
                self._replace_overlays()
        finally:
            self._replace_pending = False

    def _rescale_to_window(self):
        scale.set_factor(scale.fit(self.width(), self.height()))

    def _settle_layout(self):
        """Run every layout the last resize / rescale invalidated now, rather
        than on its posted `LayoutRequest`. A layout that activates posts its
        parent's request only once it has changed size, so a single flush
        leaves a chain of them behind — one row of Muxing's Overview page was
        still 1-2px off at some scales — and a few passes reach the fixed
        point (measured: two settled every scale in a 60-step drag)."""
        for _ in range(3):
            QApplication.sendPostedEvents(None, QEvent.LayoutRequest)

    def mousePressEvent(self, e):
        """A borderless window has no title bar: a press on the sidebar or the
        margin around the tab frame (anything a child widget didn't take)
        drags it. The tab frame itself doesn't, so an empty spot in a page
        can't pick the window up by accident."""
        if (e.button() == Qt.LeftButton and self.window_mode == window_mode.BORDERLESS
                and not self.isFullScreen()
                and not self.tab_frame.geometry().contains(e.position().toPoint())):
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemMove()
                return
        super().mousePressEvent(e)

    def _on_scale_changed(self):
        """The scale moved: restyle what's on screen, let the sizes measured off
        other widgets re-measure, then re-place what sits at absolute positions
        (the tab pipe, the toasts) once the layout has caught up."""
        self._restyle()
        if hasattr(self, "indicator"):
            # Sizes measured off other widgets' hints must read *current* hints,
            # so the layouts the rescale invalidated run first.
            self._settle_layout()
        scale.settle()
        if getattr(self, "tabs", None):
            # Every MediaTab's `panels` (Muxing's *and* Encoding's), not just
            # the current top-level tab's: the bound setters that drive this
            # bug (`scale.bind`/`scale.bind_after` fixed sizes) run for every
            # widget in the app on every scale change regardless of which
            # tab is on screen (see `ui/scale.py`'s `set_factor`), so a tab
            # that's hidden *entirely* -- not just one of its own hidden
            # sub-pages -- goes just as stale. Confirmed: resizing while on
            # Muxing left Encoding's own drop box a full 23px short the
            # moment it was switched to, having never been the active tab
            # during that resize at all. Settings/Downloader/Queue have no
            # `panels` attribute, so this only ever touches the two tabs
            # that actually need it.
            for tab in self.tabs.values():
                panels = getattr(tab, "panels", None)
                if panels is not None:
                    self._bust_hidden_size_caches(panels)
        self._schedule_replace()

    def _bust_hidden_size_caches(self, panels):
        """`panels` is a `MediaTab`'s Overview/Video/Audio `QStackedWidget`.
        Root cause of the documented "Muxing's panel stack is left too tall
        after the window is dragged bigger and then smaller" bug: found by
        tracing exactly why `panels.sizeHint()` (which sizes itself to
        whichever sub-page is tallest, so switching sub-tabs never resizes
        the preview above it) kept reporting a stale, too-tall number for a
        *hidden* sub-page (Muxing's Video/Audio) even after every layout in
        it had been `invalidate()`-d and its widgets' real fixed heights
        (e.g. `_track_panel`'s `size_box()`, a `scale.bind_after` measured
        off Overview's own height) had already been recomputed correctly.

        `invalidate()` marks a *layout's own* aggregate hint dirty, but each
        widget it contains is held by a separate cached `QWidgetItem`, and
        that cache is only busted by calling `updateGeometry()` on the widget
        itself — which Qt's widgets already do internally whenever their own
        size changes. The catch: `QWidget::updateGeometry()` invalidates the
        widget's *own* cached item (as seen by its *direct* parent layout)
        unconditionally, but only *cascades further up* to invalidate the
        grandparent's cache when the widget `isHidden()` is false. Every
        widget inside a hidden sub-tab page *is* hidden, so a fixed-height
        change three layouts deep (a `TrackListBox` -> its row -> the page)
        busts the immediate parent's cache and stops there — the *next*
        layout up (and the one above that) never finds out its child's hint
        changed, so `sizeHint()` at the top keeps returning whatever was
        cached from the last time that page was genuinely shown. Confirmed
        by hand: calling `.invalidate()` (even directly, even repeatedly) on
        every layout in the chain did nothing; explicitly calling
        `.updateGeometry()` on each *widget* one level at a time is what
        actually cleared each cache in turn.

        The fix: after every scale change (`scale.settle()`, once every
        `bind_after` setter has run and any fixed sizes are at their final,
        correct values), call `updateGeometry()` on every widget under
        `panels` — including its hidden sub-pages — so each one's cache is
        individually busted regardless of the hidden-cascade cutoff, and the
        next `sizeHint()` query at any level recomputes for real instead of
        replaying a snapshot from whenever that page was last on screen.
        Scoped to just `panels` (not the whole tab — the carousel, header and
        save row are all genuinely visible already *when their own tab is the
        one on screen*, so Qt's normal resize path keeps them correct then)
        to keep this cheap enough for a live resize — `updateGeometry()`
        itself only marks a cache dirty, it doesn't force an immediate
        recompute. Not needed for Settings' own hidden sub-pages (its page
        stack is layout-stretched, not sized to content, so a stale hint
        there is invisible) or for Downloader/Queue (no such stack at all).

        **`_on_scale_changed` calls this for every `MediaTab`, not only the
        current one.** The bound setters that drive this bug run for every
        widget in the app on every scale change regardless of which top-level
        tab is on screen (`scale.set_factor` iterates the whole app's
        `_bound` registry) — so a tab that's *entirely* hidden behind another
        one goes just as stale as one of its own hidden sub-pages does, and
        the drop box comes out visibly shrunk the moment it's switched to.
        Confirmed: resizing while on Muxing left Encoding's own `drop_box` a
        real 23px short (226 instead of 249) the instant Encoding became the
        active tab, having never been on screen during that resize at all.

        Verified: a real 1.0x -> 2.6x -> 1.0x drag (and a repeated
        1.0x -> 1.7x -> 1.0x one right after), on either tab, while it was
        active or while the other one was, left both tabs' `panels.sizeHint()`
        and `drop_box` size exactly where they started and identical to each
        other, across a battery of scales (0.5x-3.0x), every sub-tab, and
        both a single resize jump and a stepped multi-frame drag."""
        for widget in panels.findChildren(QWidget):
            widget.updateGeometry()
        panels.updateGeometry()

    def _schedule_replace(self):
        """Queue one `_replace_overlays` for after the layout has caught up —
        however many resizes and rescales ask for it first."""
        if hasattr(self, "indicator") and not self._replace_pending:
            self._replace_pending = True
            QTimer.singleShot(0, self._run_scheduled_replace)

    def _run_scheduled_replace(self):
        self._replace_pending = False
        self._replace_overlays()

    def _replace_overlays(self):
        """Re-lay the tab pipe and toasts against the new geometry."""
        self.indicator.set_active(self.current_tab, self.sidebar.buttons, self.tab_frame.x(), animate=False)
        self._restack()
        self.toasts.relayout()

    def _restack(self):
        """Restore the window's stacking order, bottom to top: the tab pipe, an
        expanded preview, the keyboard selection's ring, the toasts, the resize grips. The tab pipe raises
        itself every time it is re-laid out (a tab switch, any resize), so
        without this it ended up on top of an expanded preview — a cable
        drawn across the picture."""
        for tab in self.media_tabs:
            overlay = getattr(tab, "_expand_overlay", None)
            if overlay is not None and overlay.isVisible():
                overlay.raise_()
        if self.keynav.ring.isVisible():
            self.keynav.ring.raise_()
        self.toasts.raise_all()
        self._grips.place()

    # ------------------------------------------------------------------ #
    #  Settings-driven defaults
    # ------------------------------------------------------------------ #
    def set_default_save_location(self, path):
        """A new default save location from Settings — while no file's been
        imported yet, Muxing/Encoding's save fields (still just the bare
        default directory — see `MediaTab._autofill_output_path`) follow it
        live, and so does the Downloader's own field unless it has its own
        separate location. Once a real file/fetch is in the field, only that
        flow's own autofill touches it again."""
        self.default_save_location = path
        if not self.current_file_path:
            for tab in self.media_tabs:
                set_line_text(tab.save_entry, path)
                tab._auto_output = path
        downloader_tab = self.tabs.get("Downloader")
        if downloader_tab is not None and not self.downloader_separate_save:
            downloader_tab.refresh_default_location()

    def downloader_default_location(self):
        """The folder the Downloader autofills into before a fetch — its own
        separate location when Settings has that on and one's been set, else
        the same default save location every other tab uses."""
        if self.downloader_separate_save and self.downloader_save_location:
            return self.downloader_save_location
        return self.default_save_location

    def set_naming_template(self, template):
        """A new output naming format from Settings: every tab whose Save
        field still holds an autofilled name re-derives it live."""
        if template == self.naming_template:
            return
        self.naming_template = template
        for tab in (*self.media_tabs, self.tabs.get("Downloader")):
            if tab is not None:
                tab.refresh_auto_output()

    def set_priority_level(self, level):
        """A new job priority from Settings — applied at once to a job that's
        already running, and to every job started after."""
        self.priority_level = level
        llamalog.get("settings").info("Priority level set to %s", level)
        queue_tab = self.tabs.get("Queue")
        if queue_tab is not None:
            queue_tab.apply_priority()

    def perform_when_done(self):
        """The queue just emptied: carry out Settings' "When Done" choice.
        The four that end or suspend the Windows session get a 30-second
        cancellable countdown first — nothing is worth a surprise shutdown."""
        action = self.when_done
        if action == power.DO_NOTHING:
            return
        llamalog.get("app").info("Queue finished: When Done is %r", action)
        if action == power.QUIT:
            self.close()
            return
        if action in power.SYSTEM_ACTIONS:
            what = {power.SHUTDOWN: "shut down", power.SLEEP: "go to sleep",
                    power.HIBERNATE: "hibernate", power.LOG_OFF: "log off"}[action]
            if not confirm_countdown(
                self, action, f"The queue has finished. Your PC will {what} in {{n}} seconds.\n\n"
                              "Cancel to stay as you are.", seconds=30, now_label=action,
            ):
                self.notify(f"{action} cancelled.", go_to_queue=False)
                return
        error = power.perform(action)
        if error:
            show_message(self, "When Done", error)

    def set_downloader_separate_save(self, enabled):
        self.downloader_separate_save = bool(enabled)
        downloader_tab = self.tabs.get("Downloader")
        if downloader_tab is not None:
            downloader_tab.refresh_default_location()

    def set_downloader_save_location(self, path):
        self.downloader_save_location = path
        downloader_tab = self.tabs.get("Downloader")
        if downloader_tab is not None and self.downloader_separate_save:
            downloader_tab.refresh_default_location()

    # ------------------------------------------------------------------ #
    #  File selection broadcast
    # ------------------------------------------------------------------ #
    def register_media_tab(self, tab):
        self.media_tabs.append(tab)

    def update_global_file(self, file_path):
        """The only place the selected file changes."""
        clean_path = (file_path or "").strip("{}").strip()
        if not clean_path:
            return
        if clean_path != self.current_file_path:
            self._preview_index = 0
            if clean_path != self._media_info_path:
                self.media_info = _empty_media_info()
            # A genuinely new file — drop the outgoing file's preview right
            # away instead of leaving it on screen until the new one's
            # frames finish decoding (_load_thumbnails, below, rebroadcasts
            # synchronously on a cache hit, so this never even flashes blank
            # for a file that's been seen before).
            for tab in self.media_tabs:
                tab.carousel.clear_preview()
            # The file being replaced owns any HDR→SDR preview still
            # rendering, and its own HDR→SDR switch — interrupt the one and
            # turn the other back off so the new file never inherits either.
            self._cancel_hdr_render()
            # Only one tone-mapped set is cached, and a new file's render replaces it: kept
            # until then, an SDR file after an HDR one held the old set (~300MB at 4K) for good.
            self.hdr_frames = None
            self.hdr_frames_path = None
            for tab in self.media_tabs:
                reset_hdr = getattr(tab, "reset_hdr_preview", None)
                if callable(reset_hdr):
                    reset_hdr()
        self.current_file_path = clean_path
        llamalog.get("app").info("File selected: %s", clean_path)
        for tab in self.media_tabs:
            tab.set_selected_file(clean_path)
            tab._autofill_output_path()
        self._load_thumbnails(clean_path)

    def _load_thumbnails(self, path):
        """Cache hit → broadcast now. Miss → probe then decode ten frames on a
        worker; the probe (~50ms) lands first so defaults settle early."""
        self._thumb_token += 1
        token = self._thumb_token
        self._thumb_t0 = time.monotonic()
        cached_info = path == self._media_info_path
        if cached_info:
            self._broadcast_media_info()
            # An audio file has no frames to wait for, and its Wave Loop is what reveals the
            # carousel — as `_deliver_media_info` does for a fresh probe. Without this a
            # re-selected audio file kept showing the loading spinner until the frame
            # decode (which OpenCV never finishes on an audio-only file) reported back.
            if self._is_audio_only(path):
                self._broadcast_audio_only(True)
        if path == self.thumb_frames_path and self.thumb_frames:
            self._broadcast_thumbnails(self.thumb_frames)
            self._prerender_hdr(path)
            if cached_info:
                return

        max_size = _preview_max_size()

        def work():
            if not cached_info:
                info = probe_media(path)
                emit_progress(lambda i: self._deliver_media_info(token, path, i), info)
            return [pil_to_qimage(f) for f in extract_video_thumbnails(path, count=10, max_size=max_size)]

        run_async(work, lambda frames: self._deliver_thumbnails(token, path, frames or []))

    def _deliver_media_info(self, token, path, info):
        if token != self._thumb_token or info is None:
            return
        # Neither a video nor an audio stream at all -- not a legitimate
        # audio-only file (that's has_audio True, has_video False) but a
        # probe that found literally nothing, the signature of ffmpeg's
        # demuxer failing to read this file (a corrupt file, or a container
        # variant this build's demuxer doesn't handle -- e.g. some vendors'
        # MXF headers). Rejected before it ever reaches a tab, rather than
        # broadcast as if it were a real, empty file.
        if info.get("has_video") in (None, False) and info.get("has_audio") in (None, False):
            self._reject_file(path)
            return
        self.media_info = info
        self._media_info_path = path
        llamalog.get("probe").info("Probed %s: %s", os.path.basename(path), _probe_summary(info))
        self._broadcast_media_info()
        if self._is_audio_only(path):
            self._broadcast_audio_only(True)

    def _reject_file(self, path):
        """Undo the selection entirely -- back to the dropbox's pristine,
        nothing-imported state, and this file's info never reaches Muxing/
        Encoding. Bumping the token also makes the in-flight thumbnail
        decode for this same path a no-op once it lands (`_deliver_thumbnails`
        checks it too)."""
        llamalog.get("app").warning("Rejected %s: no video or audio stream could be identified "
                                    "(unreadable, or a format this ffmpeg can't parse)", path)
        self._thumb_token += 1
        self.current_file_path = ""
        self.media_info = _empty_media_info()
        self._media_info_path = None
        self.thumb_frames = []
        self.thumb_frames_path = None
        self._preview_index = 0
        self._cancel_hdr_render()
        for tab in self.media_tabs:
            tab.clear_selected_file()
            reset_hdr = getattr(tab, "reset_hdr_preview", None)
            if callable(reset_hdr):
                reset_hdr()
        show_message(
            self, "Couldn't Read This File",
            f"“{os.path.basename(path)}”'s video and audio couldn't be identified. "
            "It may be corrupted, or use a format this app's bundled ffmpeg can't "
            "fully parse.",
        )

    def _is_audio_only(self, path):
        info = self.media_info
        if info.get("video"):
            return False
        if info.get("audio"):
            return True
        return os.path.splitext(path)[1].lower() in formats.AUDIO_EXTENSIONS

    def _broadcast_audio_only(self, flag):
        for tab in self.media_tabs:
            tab.carousel.set_audio_only(flag)

    def _broadcast_media_info(self):
        for tab in self.media_tabs:
            tab.on_media_info(self.media_info)
            tab.carousel.set_media_info(self.media_info)
            # The probe may carry a title / chapter count the naming format
            # uses, which weren't known when the file was first picked.
            tab.refresh_auto_output()

    def _deliver_thumbnails(self, token, path, frames):
        if token != self._thumb_token:
            return
        took = time.monotonic() - getattr(self, "_thumb_t0", time.monotonic())
        if not frames:
            if self._is_audio_only(path):
                llamalog.get("app").info("%s is audio-only: no preview frames (Wave Loop)", os.path.basename(path))
                self._broadcast_audio_only(True)
                return
            llamalog.get("app").warning("No preview frames could be decoded for %s after %.1fs "
                                        "(the file stays selected)", path, took)
            # A video that decoded to no frames (the preview decoder, OpenCV, can fail
            # on a file ffmpeg reads fine): the file stays selected and usable, the
            # drop box says so, and the user is told once.
            for tab in self.media_tabs:
                tab.show_no_preview()
            show_message(
                self, "No Preview",
                "No preview images could be generated.\n\n"
                "The file is still usable but the preview images could not be decoded properly.",
            )
            return
        self.thumb_frames = frames
        self.thumb_frames_path = path
        llamalog.get("app").info("Previews ready for %s: %d frames in %.1fs",
                                 os.path.basename(path), len(frames), took)
        self._broadcast_thumbnails(frames)
        self._prerender_hdr(path)

    def _broadcast_thumbnails(self, frames):
        for tab in self.media_tabs:
            tab.carousel.set_audio_only(False)
            tab.on_thumbnails(frames)
            tab.carousel.sync_index(self._preview_index)

    def sync_preview_index(self, index):
        """A carousel was scrubbed — mirror it onto the other tab's."""
        if index == self._preview_index:
            return
        self._preview_index = index
        for tab in self.media_tabs:
            tab.carousel.sync_index(index)

    # ------------------------------------------------------------------ #
    #  HDR→SDR preview renders
    # ------------------------------------------------------------------ #
    def _prerender_hdr(self, path):
        """An HDR file's tone-mapped previews start rendering as soon as its raw ones are up,
        in the background, so HDR→SDR shows them the moment it is switched on rather than
        after a ~15s wait. Only an HDR file (the probe has landed by now) pays for it; a
        switch pressed before it finishes just waits for the rest (`start_hdr_render` is a
        no-op while this path's render is in flight). It runs alongside a running queue job."""
        if path == self.current_file_path and path == self._media_info_path \
                and self.media_info.get("hdr") is True:
            self.start_hdr_render(path)

    def start_hdr_render(self, path):
        """One tone-mapped render per file, cached here; no-op when cached or
        already running for this path."""
        if not path or path == self.hdr_frames_path or path == self._hdr_inflight_path:
            return
        self._hdr_inflight_path = path
        self._hdr_t0 = time.monotonic()
        llamalog.get("app").info("HDR preview render started for %s", os.path.basename(path))
        self._hdr_token += 1
        token = self._hdr_token
        cancel_event = threading.Event()
        self._hdr_cancel_event = cancel_event

        max_size = _preview_max_size()

        def work():
            frames = extract_hdr_tonemapped_thumbnails(path, count=10, should_cancel=cancel_event.is_set,
                                                       max_size=max_size)
            return [pil_to_qimage(f) for f in frames]

        run_async(work, lambda frames: self._deliver_hdr(token, path, frames or []))

    def _cancel_hdr_render(self):
        """Interrupts an HDR→SDR preview render still in flight — its file is
        no longer the one being shown, so letting it finish would just be
        wasted ffmpeg/libplacebo work. A no-op when nothing's running."""
        if self._hdr_cancel_event is not None:
            self._hdr_cancel_event.set()
        if self._hdr_inflight_path:
            llamalog.get("app").info("HDR preview render cancelled (%s)", os.path.basename(self._hdr_inflight_path))
            self._hdr_cancelled_token = self._hdr_token
        self._hdr_inflight_path = None

    def _deliver_hdr(self, token, path, frames):
        if path == self._hdr_inflight_path:
            self._hdr_inflight_path = None
        if token != self._hdr_token or token == self._hdr_cancelled_token:
            # Superseded, or interrupted by a file change: its (empty) result must not be logged as a
            # failure, nor replace the cached frames of the file before it.
            return
        took = time.monotonic() - getattr(self, "_hdr_t0", time.monotonic())
        if frames:
            llamalog.get("app").info("HDR preview ready for %s: %d frames in %.1fs",
                                     os.path.basename(path), len(frames), took)
        else:
            llamalog.get("app").warning("HDR preview render for %s produced no frames (%.1fs; cancelled, "
                                        "libplacebo unavailable, or a decode failure)", os.path.basename(path), took)
        self.hdr_frames = frames or None
        self.hdr_frames_path = path if frames else None
        for tab in self.media_tabs:
            ready = getattr(tab, "on_hdr_frames_ready", None)
            if callable(ready):
                ready(path, self.hdr_frames)

    # ------------------------------------------------------------------ #
    #  Downloader
    # ------------------------------------------------------------------ #
    def _deliver_deno_check(self, deno):
        self.deno_missing = deno is None
        llamalog.get("downloader").info("Deno check: %s", deno or "not found (or older than 2.3.0)")
        self.tabs["Downloader"].set_deno_missing(self.deno_missing)

    def fetch_ytdlp_info(self, url):
        llamalog.get("downloader").info("Fetching link info: %s", url)
        self._ytdlp_token += 1
        token = self._ytdlp_token

        def work():
            info, error = downloader.fetch_info(url)
            thumb = pil_to_qimage(downloader.download_thumbnail(info.get("thumbnail"))) if info else None
            return info, error, thumb

        run_async(work, lambda result: self._deliver_ytdlp_info(token, url, result))

    def _deliver_ytdlp_info(self, token, url, result):
        if token != self._ytdlp_token:
            return
        info, error, thumb = result if result else (None, "The link couldn't be fetched.", None)
        if info is not None:
            llamalog.get("downloader").info("Fetched %s: %r, %s formats", url, info.get("title"),
                                            len(info.get("formats") or []))
        else:
            llamalog.get("downloader").warning("Couldn't fetch %s: %s", url, error)
        if info is not None:
            self.ytdlp_cache = {"url": url, "info": info, "thumb": thumb}
        self.tabs["Downloader"].on_ytdlp_info(url, info, error, thumb)

    # ------------------------------------------------------------------ #
    #  Closing
    # ------------------------------------------------------------------ #
    def closeEvent(self, event):
        """Confirm before discarding unfinished queue work (pausing — not
        stopping — for the prompt, so backing out resumes exactly where it
        was), then kill any active job: Windows doesn't take a child process
        down with its parent."""
        if getattr(self, "_closing", False):
            event.accept()
            return
        queue_tab = self.tabs["Queue"]
        pending = queue_tab.pending_task_count()
        if pending:
            was_running = queue_tab.is_running()
            if was_running:
                queue_tab.pause_queue()
            plural = "job" if pending == 1 else "jobs"
            confirmed = ask_yes_no(
                self, "Close LlamaMXD?",
                f"There {'is' if pending == 1 else 'are'} still {pending} unfinished {plural} in "
                f"the queue. Closing now would cancel {'it' if pending == 1 else 'them all'}.\n\n"
                "Are you sure you want to close?",
            )
            if not confirmed:
                llamalog.get("app").info("Close cancelled (%d unfinished job(s))", pending)
                if was_running:
                    queue_tab.start_queue()
                event.ignore()
                return
        llamalog.get("app").info("Closing LlamaMXD (%d unfinished job(s) discarded)", pending)
        # Flagged so the close Qt re-sends while quitting doesn't prompt twice.
        self._closing = True
        self.tabs["Settings"].autosave()
        queue_tab.shutdown()
        event.accept()
        QApplication.instance().quit()
