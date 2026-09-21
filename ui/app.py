"""The main window and the app's hub: shared state, the file-selection
broadcast, background work (probe + preview frames, HDR renders, yt-dlp
fetches, the Deno check), tab routing, keybinds, toasts and the close prompt.

Every tab is built once and lives in a QStackedWidget. A tab switch is one
`setCurrentWidget` — Qt hides one page and shows another inside a single
native window and presents the result as one frame, so there's no re-mapping
of hundreds of child windows and nothing fills in piece by piece."""
import os
import threading

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPainter, QPainterPath
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

from core import downloader, formats, gpu, power, priority, window_mode, window_style
from core.theme import load_settings
from core.utilities import (
    extract_hdr_tonemapped_thumbnails,
    extract_video_thumbnails,
    libplacebo_problem,
    probe_media,
)
from ui import scale
from ui import theme as T
from ui.tabs.downloader import DownloaderTab
from ui.tabs.encoding import EncodingTab
from ui.tabs.media_tab import set_line_text
from ui.tabs.muxing import MuxingTab
from ui.tabs.queue import QueueTab
from ui.tabs.settings import SettingsTab
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


class _Keybinds(QObject):
    """Global keybinds, filtered at the application level so they work
    wherever focus happens to be — unless focus is on something the key
    already means something for. Also clears a text field's focus the moment
    a click lands somewhere else: every clickable in this app is `Qt.NoFocus`
    (see Conventions), so Qt's own default — a click that lands on a widget
    which never takes focus simply leaves focus wherever it already was —
    otherwise left a line edit looking and behaving focused (cursor still
    blinking, still first in line for Ctrl+A/paste) long after the user had
    clicked off it onto a button or blank space."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress:
            focus = QApplication.focusWidget()
            typing = isinstance(focus, QLineEdit) or type(focus).__name__ == "_TimeField"
            if typing and obj is not focus:
                focus.clearFocus()
            return False
        if event.type() != QEvent.KeyPress or not self.window.isActiveWindow():
            return False
        if QApplication.activeModalWidget() is not None:
            return False
        key = event.key()
        focus = QApplication.focusWidget()
        typing = isinstance(focus, QLineEdit) or type(focus).__name__ == "_TimeField"
        if key in (Qt.Key_Left, Qt.Key_Right) and not typing:
            carousel = getattr(self.window.tabs.get(self.window.current_tab), "carousel", None)
            if carousel is not None:
                carousel.step(-1 if key == Qt.Key_Left else 1)
                return True
        if key == Qt.Key_Escape and not typing:
            for tab in self.window.media_tabs:
                if getattr(tab.carousel, "_expanded", False):
                    tab.carousel.force_collapse()
                    return True
        if key == Qt.Key_Space and self.window.current_tab == "Queue" and not event.isAutoRepeat():
            if typing or isinstance(focus, (QAbstractButton, QComboBox)):
                return False
            self.window.tabs["Queue"].toggle_queue()
            return True
        return False


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
        if self.default_save_location:
            try:
                os.makedirs(self.default_save_location, exist_ok=True)
            except OSError:
                pass

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
            on_leave = getattr(outgoing, "on_leave", None)
            if callable(on_leave):
                on_leave()
        self.current_tab = name
        self.stack.setCurrentWidget(incoming)
        # Only once it's visible: a hidden widget restyled doesn't invalidate
        # its parent's layout, so its size hints stay cached at the old scale.
        if self._style(incoming):
            scale.settle()      # sizes measured off this page's hints, now against its new sheet
        on_enter = getattr(incoming, "on_enter", None)
        if callable(on_enter):
            on_enter()
        self.indicator.set_active(name, self.sidebar.buttons, self.tab_frame.x(), animate=animate)
        self._restack()
        if not isinstance(QApplication.focusWidget(), QLineEdit):
            self.setFocus()
        self.toasts.relayout()

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
        self._style(self.tabs[self.current_tab])

    # ------------------------------------------------------------------ #
    #  Window mode + size
    # ------------------------------------------------------------------ #
    def set_window_mode(self, mode, fullscreen):
        """Settings' Window Mode (and, for Borderless, its Fullscreen box)."""
        if mode not in window_mode.MODES:
            return
        self.window_mode = mode
        self.borderless_fullscreen = bool(fullscreen)
        self._apply_window_mode()

    def _wants_fullscreen(self):
        return self.window_mode == window_mode.BORDERLESS and self.borderless_fullscreen

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
        if mode == window_mode.FIXED:
            self.setFixedSize(size)
            self.move(screen.x() + (screen.width() - size.width()) // 2,
                      screen.y() + (screen.height() - size.height()) // 2)
        else:
            self.setMinimumSize(*fixed_size)
            self.setMaximumSize(_QWIDGETSIZE_MAX, _QWIDGETSIZE_MAX)
        if visible:
            # Qt leaves the maximize button as it was: a Fixed window must not
            # have one, a resizable one must.
            window_style.set_maximize_box(int(self.winId()), mode != window_mode.FIXED)
            self._sync_titlebar()
        fullscreen = self._wants_fullscreen()
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
        self._schedule_replace()

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
        expanded preview, the toasts, the resize grips. The tab pipe raises
        itself every time it is re-laid out (a tab switch, any resize), so
        without this it ended up on top of an expanded preview — a cable
        drawn across the picture."""
        for tab in self.media_tabs:
            overlay = getattr(tab, "_expand_overlay", None)
            if overlay is not None and overlay.isVisible():
                overlay.raise_()
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
            for tab in self.media_tabs:
                reset_hdr = getattr(tab, "reset_hdr_preview", None)
                if callable(reset_hdr):
                    reset_hdr()
        self.current_file_path = clean_path
        for tab in self.media_tabs:
            tab.set_selected_file(clean_path)
            tab._autofill_output_path()
        self._load_thumbnails(clean_path)

    def _load_thumbnails(self, path):
        """Cache hit → broadcast now. Miss → probe then decode ten frames on a
        worker; the probe (~50ms) lands first so defaults settle early."""
        self._thumb_token += 1
        token = self._thumb_token
        cached_info = path == self._media_info_path
        if cached_info:
            self._broadcast_media_info()
        if path == self.thumb_frames_path and self.thumb_frames:
            self._broadcast_thumbnails(self.thumb_frames)
            if cached_info:
                return

        def work():
            if not cached_info:
                info = probe_media(path)
                emit_progress(lambda i: self._deliver_media_info(token, path, i), info)
            return [pil_to_qimage(f) for f in extract_video_thumbnails(path, count=10)]

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
        self._broadcast_media_info()
        if self._is_audio_only(path):
            self._broadcast_audio_only(True)

    def _reject_file(self, path):
        """Undo the selection entirely -- back to the dropbox's pristine,
        nothing-imported state, and this file's info never reaches Muxing/
        Encoding. Bumping the token also makes the in-flight thumbnail
        decode for this same path a no-op once it lands (`_deliver_thumbnails`
        checks it too)."""
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
        if not frames:
            if self._is_audio_only(path):
                self._broadcast_audio_only(True)
                return
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
        self._broadcast_thumbnails(frames)

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
    def start_hdr_render(self, path):
        """One tone-mapped render per file, cached here; no-op when cached or
        already running for this path."""
        if not path or path == self.hdr_frames_path or path == self._hdr_inflight_path:
            return
        self._hdr_inflight_path = path
        self._hdr_token += 1
        token = self._hdr_token
        cancel_event = threading.Event()
        self._hdr_cancel_event = cancel_event

        def work():
            frames = extract_hdr_tonemapped_thumbnails(path, count=10, should_cancel=cancel_event.is_set)
            return [pil_to_qimage(f) for f in frames]

        run_async(work, lambda frames: self._deliver_hdr(token, path, frames or []))

    def _cancel_hdr_render(self):
        """Interrupts an HDR→SDR preview render still in flight — its file is
        no longer the one being shown, so letting it finish would just be
        wasted ffmpeg/libplacebo work. A no-op when nothing's running."""
        if self._hdr_cancel_event is not None:
            self._hdr_cancel_event.set()
        self._hdr_inflight_path = None

    def _deliver_hdr(self, token, path, frames):
        if path == self._hdr_inflight_path:
            self._hdr_inflight_path = None
        if token != self._hdr_token:
            return
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
        self.tabs["Downloader"].set_deno_missing(self.deno_missing)

    def fetch_ytdlp_info(self, url):
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
                if was_running:
                    queue_tab.start_queue()
                event.ignore()
                return
        # Flagged so the close Qt re-sends while quitting doesn't prompt twice.
        self._closing = True
        self.tabs["Settings"].autosave()
        queue_tab.shutdown()
        event.accept()
        QApplication.instance().quit()
