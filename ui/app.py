"""The main window and the app's hub: shared state, the file-selection
broadcast, background work (probe + preview frames, HDR renders, yt-dlp
fetches, the Deno check), tab routing, keybinds, toasts and the close prompt.

Every tab is built once and lives in a QStackedWidget. A tab switch is one
`setCurrentWidget` — Qt hides one page and shows another inside a single
native window and presents the result as one frame, so there's no re-mapping
of hundreds of child windows and nothing fills in piece by piece."""
import os
import threading

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core import downloader, formats
from core.theme import load_settings
from core.utilities import extract_hdr_tonemapped_thumbnails, extract_video_thumbnails, probe_media
from ui import theme as T
from ui.tabs.downloader import DownloaderTab
from ui.tabs.encoding import EncodingTab
from ui.tabs.media_tab import set_line_text
from ui.tabs.muxing import MuxingTab
from ui.tabs.queue import QueueTab
from ui.tabs.settings import SettingsTab
from ui.widgets.dialogs import ask_yes_no, show_message
from ui.widgets.panels import ASSETS, Sidebar, TabIndicator
from ui.widgets.toast import ToastManager
from ui.workers import emit_progress, pil_to_qimage, run_async

TAB_NAMES = ("Muxing", "Encoding", "Downloader", "Queue", "Settings")

_MEDIA_INFO_KEYS = ("container", "video", "audio", "video_profile", "video_level", "hdr",
                    "width", "height", "duration", "file_size", "has_video", "has_audio")


def _empty_media_info():
    """"Unknown" for every probe field — None never reads as absent."""
    info = dict.fromkeys(_MEDIA_INFO_KEYS)
    info["audio_streams"] = []
    return info


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
        self.setObjectName("Root")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setWindowTitle("LlamaMXD")
        icon = os.path.join(ASSETS, "llama.ico")
        if os.path.exists(icon):
            self.setWindowIcon(QIcon(icon))

        settings = load_settings()
        self.current_file_path = ""
        self.default_save_location = settings["default_save_location"]
        self.gpu_enabled = bool(settings["gpu_enabled"])
        # The Downloader's own save folder, used instead of the shared
        # default only while separate-save is on and a folder's been set.
        self.downloader_separate_save = bool(settings["downloader_separate_save"])
        self.downloader_save_location = settings["downloader_save_location"] or ""
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
        self.current_tab = "Muxing"

        # 35% x 37.5% of the screen, fixed-size and centred.
        screen = self.screen().geometry()
        width, height = round(screen.width() * 0.35), round(screen.height() * 0.375)
        self.setFixedSize(width, height)
        self.move(screen.x() + (screen.width() - width) // 2, screen.y() + (screen.height() - height) // 2)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.sidebar = Sidebar()
        self.sidebar.navigate.connect(self.show_tab)
        layout.addWidget(self.sidebar)

        frame_host = QVBoxLayout()
        frame_host.setContentsMargins(10, 10, 10, 10)
        self.tab_frame = QWidget()
        self.tab_frame.setObjectName("TabFrame")
        self.tab_frame.setAttribute(Qt.WA_StyledBackground)
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

        self.indicator = TabIndicator(self)
        self.toasts = ToastManager(self, lambda: self.tab_frame)

        self._keybinds = _Keybinds(self)
        QApplication.instance().installEventFilter(self._keybinds)
        T.theme.changed.connect(self._restyle)

        run_async(downloader.deno_path, self._deliver_deno_check)

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
        on_enter = getattr(incoming, "on_enter", None)
        if callable(on_enter):
            on_enter()
        self.indicator.align_to(self.sidebar.buttons[name], self.tab_frame.x(), animate=animate)
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

    def _restyle(self):
        QApplication.instance().setStyleSheet(T.stylesheet())

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

    def _deliver_thumbnails(self, token, path, frames):
        if token != self._thumb_token:
            return
        if not frames:
            if self._is_audio_only(path):
                self._broadcast_audio_only(True)
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
