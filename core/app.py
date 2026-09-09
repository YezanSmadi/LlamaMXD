import os
import queue
import sys
import threading
import tkinter as tk
import customtkinter as ctk
from tkinterdnd2 import TkinterDnD
from PIL import Image

from core import formats
from core.utilities import extract_video_thumbnails, probe_media
from core.theme import get_active_theme, load_settings, apply_ctk_theme
from components.dialogs import ask_yes_no
from components.sidebar import Sidebar
from components.toast import ToastManager
from tabs.muxing_tab import MuxingTab
from tabs.encoding_tab import EncodingTab
from tabs.queue_tab import QueueTab
from tabs.ytdlp_tab import YtDlpTab
from tabs.settings_tab import SettingsTab

class LlamaGUI(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self):
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)

        # Window Setup
        width, height = self.winfo_screenwidth(), self.winfo_screenheight()
        # 0.375 = a quarter shorter than the 0.5 this briefly was. 0.5 fixed
        # an earlier bug where the window was too short for its content and
        # the packer silently compressed the DropBox below its configured
        # size — but it also made the window look too square. The DropBox's
        # expand+fill still lets it shrink gracefully at this shorter height;
        # it just won't grow as tall as it did at 0.5.
        scaled_w, scaled_h = int(width * 0.35), int(height * 0.375)
        x_center = (width - scaled_w) // 2
        y_center = (height - scaled_h) // 2
        self.geometry(f"{scaled_w}x{scaled_h}+{x_center}+{y_center}")
        self.title("LlamaMXD")
        self.iconbitmap("llama.ico")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Grid Config
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # Shared State & Registry
        _settings = load_settings()
        self.current_file_path = ""
        self.default_save_location = _settings["default_save_location"]
        # Hardware-acceleration is a global preference now (moved off the
        # Encoding tab into Settings) — every queued Encode task reads it.
        self.gpu_enabled = bool(_settings["gpu_enabled"])
        self.tab_ui_registry = []
        # Preview thumbnails for the currently-selected file. Decoded once
        # (on a background thread — see _load_thumbnails) and cached here so
        # tab switches and live theme rebuilds never re-decode. _thumb_token
        # rises on every request so a slow decode of a file the user has
        # since replaced can be dropped on arrival.
        self._thumb_frames = []
        self._thumb_frames_path = None
        self._thumb_token = 0
        # What the selected file actually *is* — container + codecs, from a
        # best-effort ffprobe on the same worker as the thumbnails. This is
        # what gives `Source` a concrete meaning: tabs use it to default the
        # output container, to name a copied stream in the Overview rundown,
        # and (Muxing) to work out which containers the file can be remuxed
        # into. Every field may stay None; nothing here is load-bearing.
        self.media_info = {"container": None, "video": None, "audio": None}
        self._media_info_path = None
        # Which preview frame the carousels are scrubbed to — shared across
        # tabs (Muxing/Encoding both mirror it) and preserved across a live
        # theme rebuild. Reset to 0 only when the input file actually changes.
        self._preview_index = 0
        # Decode threads hand their results back through this queue rather than
        # touching a widget or calling after() directly — Tkinter is not
        # thread-safe. _drain_thumbnails polls it on the main thread.
        self._thumb_queue = queue.Queue()
        self._thumb_pending = 0
        self._tab_indicator_job = None
        self._current_tab_name = "Muxing"
        # In-window drop-down notifications ("job added to queue" etc). Built
        # before the tabs since anything constructed below may want to post one.
        self.toasts = ToastManager(self)

        # Make sure the export folder actually exists so the first save
        # dialog opens somewhere real. Best-effort — a hand-picked path that
        # can't be created (bad drive, permissions) just falls back to the
        # dialog's own default.
        if self.default_save_location:
            try:
                os.makedirs(self.default_save_location, exist_ok=True)
            except OSError:
                pass

        # Loads (generating on first use) a CTk theme JSON where every
        # default-styled widget's accent color — checkboxes, switches,
        # sliders, dropdowns, the sidebar's nav buttons — has been swapped
        # to the active theme's secondary color. Must happen before any
        # widget below is constructed; see core/theme.py's apply_ctk_theme.
        apply_ctk_theme(load_settings()["theme"])

        # UI Components
        self.sidebar = Sidebar(master=self, app=self)
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        # Active-tab indicator: a primary-color strip that runs from the
        # active sidebar button, across the sidebar/content gutter, to the
        # tab frame's left edge — a visible connector between the button and
        # its content. Placed + raised (not gridded) by _update_tab_indicator
        # on every tab switch; it stops exactly at the frame edge so it never
        # covers content. The tab_indicator_line is a secondary-color band
        # crossing it through the vertical middle, stacked just above it.
        # corner_radius=0 on both, for two reasons: the pipes should read as
        # flat rectangles, and a rounded CTkFrame paints its *master's* color
        # in the corner nooks outside the rounded shape — the master here is
        # the root window (dark), while the pipes sit over the sidebar
        # (primary), so those nooks rendered as dark notches that looked like
        # a drop shadow. Flat corners have no nooks at all.
        # bg_color is pinned to primary on both, not left at its default
        # (a frozen snapshot of the root window's dark color). CTk floors a
        # drawn shape's width/height to the nearest even number, so an odd
        # dimension leaves a 1px strip of the widget's raw canvas showing at
        # its edge — which rendered as a dark line under the pipe. Matching
        # bg_color to what surrounds the pipe makes any such strip invisible.
        # (_update_tab_indicator also keeps the band's height even.)
        self.tab_indicator = ctk.CTkFrame(
            master=self, fg_color=get_active_theme()["primary"],
            bg_color=get_active_theme()["primary"], corner_radius=0,
        )
        self.tab_indicator_line = ctk.CTkFrame(
            master=self, fg_color=get_active_theme()["secondary"],
            bg_color=get_active_theme()["primary"], corner_radius=0,
        )

        # Tabs
        self.tabs = {
            "Muxing": MuxingTab(master=self, app=self),
            "Encoding": EncodingTab(master=self, app=self),
            "Queue": QueueTab(master=self, app=self),
            "YT-DLP": YtDlpTab(master=self, app=self),
            "Settings": SettingsTab(master=self, app=self),
        }
        self.show_tab("Muxing")

        # --- Keybinds. Bound on the root once (it outlives the theme rebuild);
        # the first of a growing set. Left/Right flip the visible tab's preview
        # carousel, unless a text field has focus (the TimeSpinner / save-path
        # entries own the arrow keys for cursor movement).
        self.bind("<Left>", lambda _e: self._nudge_preview(-1))
        self.bind("<Right>", lambda _e: self._nudge_preview(1))
        # Space starts / pauses the queue while the Queue tab is showing.
        self.bind("<space>", lambda _e: self._toggle_queue())

    def _nudge_preview(self, delta):
        """Steps the current tab's `ThumbnailCarousel` by `delta` frames — the
        Left/Right arrow-key binding. Ignored while an entry field is focused,
        and on tabs that have no carousel."""
        if isinstance(self.focus_get(), tk.Entry):
            return
        carousel = getattr(self.tabs.get(self._current_tab_name), "carousel", None)
        if carousel is not None:
            carousel.step(delta)

    def _toggle_queue(self):
        """Space-bar: Start / Pause the queue, but only on the Queue tab and
        only when the keypress isn't meant for a focused control (a text
        field, or a button / checkbox that Space already activates)."""
        if self._current_tab_name != "Queue":
            return
        focus = self.focus_get()
        if isinstance(focus, (tk.Entry, tk.Text)):
            return
        widget = focus
        while widget is not None:
            if isinstance(widget, (ctk.CTkButton, ctk.CTkCheckBox, ctk.CTkSwitch,
                                   ctk.CTkSegmentedButton, ctk.CTkOptionMenu)):
                return
            widget = getattr(widget, "master", None)
        self.tabs["Queue"].toggle_queue()

    def register_tab_ui(self, label_widget, img_widget, on_thumbnail=None):
        """Registers a tab's UI controls for batch cross-tab updates.
        `on_thumbnail` receives the full list of preview frames (PIL Images);
        the default handler just renders the first at a fixed size."""
        if on_thumbnail is None:
            def on_thumbnail(frames, _img_widget=img_widget):
                if not frames:
                    return
                pil_img = frames[0]
                ctk_img = ctk.CTkImage(
                    light_image=pil_img, dark_image=pil_img, size=(350, 200)
                )
                _img_widget.configure(image=ctk_img, text="")

        self.tab_ui_registry.append(
            {"label": label_widget, "img": img_widget, "on_thumbnail": on_thumbnail}
        )

    def update_global_file(self, file_path):
        """Central method triggered by drop box imports. Updates the shared
        path and every tab's text/output field synchronously, then resolves
        the preview thumbnails (cached, or decoded off-thread)."""
        clean_path = file_path.strip("{}").strip()
        if not clean_path:
            return

        # A genuinely new file starts the carousels back at frame 0; the same
        # path again (e.g. re-broadcast during a theme rebuild) keeps the
        # scrub position the user was on.
        if clean_path != self.current_file_path:
            self._preview_index = 0
            # Drop stale probe results the moment the file changes, so a tab
            # can never render the previous input's codecs against the new
            # one while the fresh probe is still in flight.
            if clean_path != self._media_info_path:
                self.media_info = {"container": None, "video": None, "audio": None}
        self.current_file_path = clean_path

        for ui in self.tab_ui_registry:
            if ui["label"]:
                # One line — the label sits inline to the right of the
                # Video/Audio sub-tab switch in each tab's header row.
                ui["label"].configure(text=f"Selected File:  {self.current_file_path}")

        for tab in self.tabs.values():
            if hasattr(tab, "drop_box"):
                tab.drop_box.hide_drop_text()
            # Let tabs that keep an output field refresh their suggested
            # path for the new input (independent of thumbnail success).
            autofill = getattr(tab, "_autofill_output_path", None)
            if callable(autofill):
                autofill()

        self._load_thumbnails(clean_path)

    def _load_thumbnails(self, path):
        """Broadcasts this file's preview frames to every registered tab.

        Cache hit (same path already decoded) → broadcast immediately, so a
        tab switch or a live theme rebuild costs nothing. Miss → decode ten
        interior frames on a daemon thread (ten frame-seeks would visibly
        stall the Tk loop) and broadcast when they land, unless the user has
        picked a different file in the meantime (stale _thumb_token)."""
        self._thumb_token += 1
        token = self._thumb_token

        cached_info = path == self._media_info_path
        if cached_info:
            self._broadcast_media_info()
        if path == self._thumb_frames_path and self._thumb_frames:
            self._broadcast_thumbnails(self._thumb_frames)
            if cached_info:
                return   # nothing left to fetch for this file

        self._thumb_pending += 1
        threading.Thread(
            target=self._decode_worker, args=(token, path, cached_info), daemon=True
        ).start()
        if self._thumb_pending == 1:
            self.after(80, self._drain_thumbnails)

    def _decode_worker(self, token, path, skip_probe=False):
        """Off-thread media probe + frame decode. Must not touch a widget or
        call after() — results go back via the queue only.

        Sends two tagged messages: the ffprobe result first (it's ~50ms, and
        the tabs want the container/codecs to settle their defaults as early
        as possible) and the ten decoded frames after (several seeks, much
        slower). `"frames"` is always last, so it's the one that clears the
        pending count."""
        if not skip_probe:
            self._thumb_queue.put(("info", token, path, probe_media(path)))
        frames = extract_video_thumbnails(path, count=10)
        self._thumb_queue.put(("frames", token, path, frames))

    def _drain_thumbnails(self):
        """Main-thread poll: delivers any finished worker results, then
        re-arms itself while decode threads are still outstanding."""
        while True:
            try:
                kind, token, path, payload = self._thumb_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "info":
                self._deliver_media_info(token, path, payload)
                continue
            # "frames" is the worker's last message — clear its pending slot.
            self._thumb_pending = max(0, self._thumb_pending - 1)
            self._deliver_thumbnails(token, path, payload)
        if self._thumb_pending > 0:
            self.after(80, self._drain_thumbnails)

    def _deliver_media_info(self, token, path, info):
        """Caches and broadcasts a probe result, dropping it if the user has
        already picked a different file (stale token) — same guard as the
        thumbnails, for the same reason."""
        if token != self._thumb_token or not self.winfo_exists():
            return
        self.media_info = info
        self._media_info_path = path
        self._broadcast_media_info()
        # Probe usually lands well before the (failing) frame decode for an
        # audio-only file — reveal the visualiser now rather than waiting.
        if self._is_audio_only(path):
            self._broadcast_audio_only(True)

    def _is_audio_only(self, path):
        """True when the imported file carries audio but no video — the
        probe's answer, or the file extension when there was no probe."""
        info = self.media_info
        if info.get("video"):
            return False
        if info.get("audio"):
            return True
        return os.path.splitext(path)[1].lower() in formats.AUDIO_EXTENSIONS

    def _broadcast_audio_only(self, flag):
        """Tells every registered carousel whether the current input is
        audio-only, so it shows the Wave Loop visualiser instead of frames."""
        for ui in self.tab_ui_registry:
            setter = getattr(ui["img"], "set_audio_only", None)
            if callable(setter):
                setter(flag)

    def _broadcast_media_info(self):
        """Hands the probe result to every tab exposing `on_media_info`
        (Muxing and Encoding), so they can settle their `Source` defaults and
        refresh the Overview rundown."""
        for tab in self.tabs.values():
            handler = getattr(tab, "on_media_info", None)
            if callable(handler):
                handler(self.media_info)

    def _deliver_thumbnails(self, token, path, frames):
        """Drops stale (user moved on) results; caches and broadcasts real
        frames; an empty result means either an undecodable file or an
        audio-only import — the latter gets the Wave Loop visualiser."""
        if token != self._thumb_token or not self.winfo_exists():
            return
        if not frames:
            if self._is_audio_only(path):
                self._broadcast_audio_only(True)
            return
        self._thumb_frames = frames
        self._thumb_frames_path = path
        self._broadcast_thumbnails(frames)

    def _broadcast_thumbnails(self, frames):
        """Hands the frame list to every registered tab's thumbnail handler,
        then re-points each carousel at the shared scrub index (0 for a fresh
        file; whatever the user was on if this is a theme-rebuild re-broadcast
        — set_frames resets each new carousel to 0)."""
        for ui in self.tab_ui_registry:
            setter = getattr(ui["img"], "set_audio_only", None)
            if callable(setter):
                setter(False)   # real frames arrived — this input has video
            ui["on_thumbnail"](frames)
            sync = getattr(ui["img"], "sync_index", None)
            if callable(sync):
                sync(self._preview_index)

    def sync_preview_index(self, index):
        """A carousel was scrubbed to `index`; mirror it onto every other
        carousel so the selected preview frame is shared across tabs. Called
        by the carousels via their `on_index` callback; `sync_index` on the
        receiving carousels does not fire `on_index` back, so this can't loop."""
        if index == self._preview_index:
            return
        self._preview_index = index
        for ui in self.tab_ui_registry:
            sync = getattr(ui["img"], "sync_index", None)
            if callable(sync):
                sync(index)

    def show_tab(self, name):
        # Give the tab being left a chance to flush state (Settings uses this
        # to auto-persist). Runs before the switch so the outgoing tab's
        # widgets are still fully alive.
        outgoing = self.tabs.get(self._current_tab_name)
        if outgoing is not None and outgoing is not self.tabs.get(name):
            on_leave = getattr(outgoing, "on_leave", None)
            if callable(on_leave):
                on_leave()

        self._current_tab_name = name
        for tab in self.tabs.values():
            tab.grid_forget()
        self.tabs[name].grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        # Pull keyboard focus back to the window. A CTk nav button keeps focus
        # after a click and swallows <space>/<Return>, so without this the
        # global keybinds (Space → queue start/pause) only started working
        # once the user clicked somewhere non-focusable inside the tab.
        if not isinstance(self.focus_get(), tk.Entry):
            self.focus_set()
        # Deferred: the very first call happens during __init__, before
        # mainloop() has run even once — at that point the sidebar buttons
        # haven't actually been mapped onscreen yet, so winfo_height() on
        # them still reports a stale placeholder (1px), even after
        # update_idletasks() and even via after_idle (still too early — the
        # window hasn't received its first <Configure>/map pass yet). A short
        # real delay gives mainloop time to actually map the window first.
        # Cancel any not-yet-fired update so switching tabs quickly can't
        # leave a stale, out-of-order callback overwriting a newer one.
        if self._tab_indicator_job is not None:
            self.after_cancel(self._tab_indicator_job)
        self._tab_indicator_job = self.after(50, lambda: self._update_tab_indicator(name))

    def _update_tab_indicator(self, name):
        """Aligns the accent strip's vertical span with the active sidebar button."""
        button = self.sidebar.buttons.get(name)
        if not button:
            return

        # Only force a layout pass when the button genuinely hasn't been laid
        # out yet (winfo_* still reporting the 1px placeholder). update_
        # idletasks() synchronously re-lays-out and redraws the whole window,
        # which profiling put at ~47ms — 28% of the cost of a tab switch, paid
        # on every switch for a geometry answer that the 50ms defer in
        # show_tab has already made valid. The guard keeps the safety net for
        # the one call that needs it (the first, during __init__) without
        # charging every later switch for it.
        if button.winfo_height() <= 1 or self.sidebar.winfo_width() <= 1:
            self.update_idletasks()

        sidebar_width = self.sidebar.winfo_width()
        button_x = button.winfo_x()
        button_y = button.winfo_y()
        button_w = button.winfo_width()
        button_h = button.winfo_height()

        # A flat connector from the active button to the tab frame's left edge
        # (sidebar_width + 10 = the padx in show_tab). It starts exactly at
        # the button's right edge rather than overlapping into it — the pipes
        # are square-cornered, so any overlap would square off the button's
        # own rounded corner. At mid-height (where the line band crosses) the
        # button's rounded edge reaches its full bounding width, so the two
        # still meet flush. Raised so the run over the sidebar shows; stops
        # exactly at the frame edge, never on content. CTk widgets take
        # width/height via configure(), not place().
        strip_left = button_x + button_w
        strip_right = sidebar_width + 10
        strip_w = max(1, strip_right - strip_left)
        self.tab_indicator.configure(width=strip_w, height=button_h)
        self.tab_indicator.place(x=strip_left, y=button_y)
        self.tab_indicator.lift()

        # Secondary-color band crossing the strip through its vertical middle,
        # same horizontal span, raised just above it. Height must stay EVEN:
        # CTk floors a drawn shape to the nearest even number of pixels, so an
        # odd height paints one row short and exposes a strip of the widget's
        # own canvas along the bottom edge (this was a visible dark line under
        # the pipe at height 9 — see the bg_color note where these are built).
        line_h = 12
        line_y = button_y + button_h // 2 - line_h // 2
        self.tab_indicator_line.configure(width=strip_w, height=line_h)
        self.tab_indicator_line.place(x=strip_left, y=line_y)
        self.tab_indicator_line.lift()

    def apply_theme(self, theme_name):
        """Live-applies a theme with no restart required. CTk never
        retroactively recolors an already-built widget — set_default_
        color_theme only affects widgets constructed *after* the call — so
        the only way to make every default-styled control (checkboxes,
        switches, sliders, dropdowns, the sidebar's nav buttons) genuinely
        change color live is to reload the theme and then rebuild the
        widgets that read it.

        Muxing/Encoding/YT-DLP/Settings are destroyed and rebuilt from
        scratch; Muxing/Encoding's field values are snapshotted first and
        restored via load_settings() so the user doesn't lose an in-progress
        form. The Queue tab is deliberately *not* rebuilt — destroying it
        would discard its task list — it instead gets its own in-place
        QueueTab.refresh_theme() call, recoloring its already-built widgets
        without touching self._rows or any in-flight animation."""
        apply_ctk_theme(theme_name)

        # Live toasts are placed against tab frames that are about to be
        # destroyed, and carry the old palette — drop them rather than leave
        # them floating over the rebuilt UI.
        self.toasts.clear()

        muxing_settings = self.tabs["Muxing"]._gather_settings()
        encoding_settings = self.tabs["Encoding"]._gather_settings()
        active_tab_name = self._current_tab_name

        self.sidebar.destroy()
        self.tab_indicator.destroy()
        self.tab_indicator_line.destroy()
        for name in ("Muxing", "Encoding", "YT-DLP", "Settings"):
            self.tabs[name].destroy()
        self.tab_ui_registry = []  # entries above pointed at widgets just destroyed

        self.sidebar = Sidebar(master=self, app=self)
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        # corner_radius=0 on both, for two reasons: the pipes should read as
        # flat rectangles, and a rounded CTkFrame paints its *master's* color
        # in the corner nooks outside the rounded shape — the master here is
        # the root window (dark), while the pipes sit over the sidebar
        # (primary), so those nooks rendered as dark notches that looked like
        # a drop shadow. Flat corners have no nooks at all.
        # bg_color is pinned to primary on both, not left at its default
        # (a frozen snapshot of the root window's dark color). CTk floors a
        # drawn shape's width/height to the nearest even number, so an odd
        # dimension leaves a 1px strip of the widget's raw canvas showing at
        # its edge — which rendered as a dark line under the pipe. Matching
        # bg_color to what surrounds the pipe makes any such strip invisible.
        # (_update_tab_indicator also keeps the band's height even.)
        self.tab_indicator = ctk.CTkFrame(
            master=self, fg_color=get_active_theme()["primary"],
            bg_color=get_active_theme()["primary"], corner_radius=0,
        )
        self.tab_indicator_line = ctk.CTkFrame(
            master=self, fg_color=get_active_theme()["secondary"],
            bg_color=get_active_theme()["primary"], corner_radius=0,
        )

        self.tabs["Muxing"] = MuxingTab(master=self, app=self)
        self.tabs["Encoding"] = EncodingTab(master=self, app=self)
        self.tabs["YT-DLP"] = YtDlpTab(master=self, app=self)
        self.tabs["Settings"] = SettingsTab(master=self, app=self)

        self.tabs["Muxing"].load_settings(muxing_settings)
        self.tabs["Encoding"].load_settings(encoding_settings)
        self.tabs["Queue"].refresh_theme()

        self.show_tab(active_tab_name)

    def notify(self, message, go_to_queue=True):
        """Drops a notification toast in at the current tab's top-left corner.
        By default clicking it jumps to the Queue tab, since every notification
        so far is about a job that landed there."""
        on_click = (lambda: self.show_tab("Queue")) if go_to_queue else None
        self.toasts.show(message, on_click=on_click)

    def on_close(self):
        """Confirms before discarding unfinished queue work, then hard-exits.

        Processing is paused for the duration of the prompt and resumed if the
        user backs out — otherwise a job would keep animating (and could even
        finish) behind a modal dialog asking whether to cancel it. Pausing
        rather than stopping is what makes that reversible: pause_queue keeps
        the in-flight task's progress in `_paused_state`, so start_queue picks
        it up from the exact step it left off at."""
        queue_tab = self.tabs.get("Queue")
        pending = queue_tab.pending_task_count() if queue_tab else 0
        if pending:
            was_running = queue_tab.is_running()
            if was_running:
                queue_tab.pause_queue()

            plural = "job" if pending == 1 else "jobs"
            confirmed = ask_yes_no(
                self,
                "Close LlamaMXD?",
                f"There {'is' if pending == 1 else 'are'} still {pending} unfinished "
                f"{plural} in the queue. Closing now would cancel "
                f"{'it' if pending == 1 else 'them all'}.\n\n"
                "Are you sure you want to close?",
            )
            if not confirmed:
                if was_running:
                    queue_tab.start_queue()
                return
        self.destroy()
        sys.exit(0)