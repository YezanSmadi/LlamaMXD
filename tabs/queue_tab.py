import os
import queue
import subprocess
import threading
import tkinter

import customtkinter as ctk

from components.dialogs import ask_yes_no, show_message
from core import downloader, ffmpeg_vars, formats
from core.ffmpeg_build import compile_command, uses_hdr_tonemap
from core.ffmpeg_runner import FfmpegJob, partial_path
from core.ytdlp_runner import YtDlpJob
from core.utilities import extract_video_thumbnail
from core.theme import get_active_theme, readable_text_on, STOP_RED, STOP_RED_HOVER

# The Stop Queue button's red is a permanent, theme-independent exception
# (see CLAUDE.md, and STOP_RED in core/theme.py — shared with the Encoding
# tab's Strip Video checkbox). Its label still picks a legible color against
# that fixed red the same adaptive way every themed color does.
_STOP_RED = STOP_RED
_STOP_RED_HOVER = STOP_RED_HOVER
_STOP_TEXT = readable_text_on(_STOP_RED)

# Read once at import time, and reassigned by refresh_theme() on a live
# theme switch (see LlamaGUI.apply_theme) — every row construction and
# style lookup reads this module-level name at call time, not a value
# captured once, so a reassignment here is picked up everywhere.
_THEME = get_active_theme()

# Row styling by state: not-yet-started tasks read as solid brand primary;
# once a task starts, the row goes grey and progress_canvas (a primary-
# colored overlay placed on top) grows left-to-right to show its individual
# progress: Done just drops back to flat grey with the fill hidden. Text on
# the primary (queued) state — the row label and the "X" — uses the theme's
# adaptive primary_text (black or white, whichever is legible on that primary).
_QUEUED_STYLE = {"bg": _THEME["primary"], "text": _THEME["primary_text"], "remove_text": _THEME["primary_text"], "remove_hover": _THEME["primary_hover"]}
_GREY_STYLE = {"bg": ("gray85", "gray20"), "text": None, "remove_text": None, "remove_hover": ("gray75", "gray30")}
# A job ffmpeg couldn't finish: the destructive red, which (like Stop Queue's)
# never changes with the theme; its text is picked for contrast against it.
_FAILED_STYLE = {"bg": _STOP_RED, "text": _STOP_TEXT, "remove_text": _STOP_TEXT, "remove_hover": _STOP_RED_HOVER}
# The statuses a row can end on — neither has anything left to run or lose.
_FINISHED = ("Done", "Failed")
_THUMB_SIZE = (60, 40)
_ROW_CORNER = 8  # row frame corner_radius; the running fill echoes it on its left
# How often the Tk thread drains the running job's events. ffmpeg itself only
# reports progress about every 0.5s, so this is plenty smooth and costs next
# to nothing.
_POLL_INTERVAL_MS = 100
_DETAIL_SCROLL_HEIGHT = 140  # fixed so Encode/Mux popups match height; Encode's extra fields scroll

# (settings key, display label, value kind) — kind is None for plain text,
# "time" to format as HH:MM:SS, "bool" to format as Yes/No. Fields not present
# in a given task's settings (e.g. GPU/CRF for a Mux task) are skipped.
_DETAIL_FIELDS = [
    # Downloader tasks: what was downloaded, and how.
    ("title", "Title", None),
    ("url", "Link", None),
    ("input_file", "Input File", None),
    ("output_path", "Output Path", None),
    ("encoder", "Encoder", None),
    ("output_format", "Format", None),
    ("mode", "Mode", None),
    ("video_codec", "Video Codec", None),
    ("audio_codec", "Audio Codec", None),
    ("start_secs", "Start Time", "time"),
    ("duration_secs", "Clip Duration", "time"),
    ("av_sync", "A/V Sync", "bool"),
    # Video-stream fields — Encode tasks carry `profile`/`level`/`quality`;
    # Mux tasks carry `video_track`/`video_track_file` instead (it never
    # re-encodes). Each is skipped when simply absent from the settings dict.
    ("strip_video", "Strip Video", "bool"),
    ("gpu_enabled", "GPU Acceleration", "bool"),
    ("hdr_to_sdr", "HDR to SDR", "bool"),
    ("quality", "Quality", None),
    ("profile", "Profile", None),
    ("level", "Level", None),
    ("speed", "Speed", None),
    ("video_track", "Video Track", None),
    ("video_track_file", "Video From", None),
    # Audio-stream fields — `audio_track`/`audio_track_file` are Mux only
    # (Encoding's audio is described by the `audio_streams` list instead;
    # see the multi-stream rendering in _show_details). `strip_audio` is
    # shared by both tabs.
    ("audio_track", "Audio Track", None),
    ("audio_track_file", "Audio From", None),
    ("strip_audio", "Strip Audio", "bool"),
]

# Which _DETAIL_FIELDS rows belong to which stream — used by _show_details to
# hide a stream's codec/track detail once it's been stripped (or, for a
# Mux task, was never carried at all). The strip_video/strip_audio rows
# themselves are never hidden by this — "Strip Video: Yes" is exactly the
# fact worth showing once its codec details are gone.
_VIDEO_DETAIL_KEYS = {
    "encoder", "gpu_enabled", "hdr_to_sdr", "quality", "profile", "level",
    "speed", "video_track", "video_track_file",
}
_AUDIO_DETAIL_KEYS = {"audio_track", "audio_track_file"}

# Source tab name for a download task (the Downloader tab). Download jobs
# are YtDlpJobs, which share FfmpegJob's control/event contract plus a
# ("stage", text) event.
_YTDLP = "Downloader"
# A download row's status before yt-dlp reports its first stage.
_PREPARING = "Preparing..."


def _format_seconds(total_seconds):
    total_seconds = int(total_seconds or 0)
    hrs, rem = divmod(total_seconds, 3600)
    mins, secs = divmod(rem, 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"


_SCROLLBAR_GUTTER = 18  # px held at the list's right edge for the auto-hiding bar


def _autohide_scrollbar_in_gutter(scroll_frame):
    """Show a CTkScrollableFrame's vertical scrollbar only while its content
    overflows — with the row area never changing width.

    CTk grids the scrollbar into its own column and touches nothing else, so
    the bar turning on steals ~18px from the rows; worse, the canvas re-fits
    only on its next `<Configure>`, so the bar spends a beat drawn *over* the
    rows before they reflow narrower (exactly the flicker the queue showed).
    Two parts fix it: (1) give that column a permanent `minsize` so the
    gutter is always there whether the bar sits in it or not — the caller
    trims its own right padding to match, so the gutter comes out of the
    window margin, not the rows; (2) route the canvas's `yscrollcommand`
    through a relay that `grid()`/`grid_remove()`s the bar as the content
    crosses the overflow line, still forwarding every update to the real
    `CTkScrollbar.set` so scrolling itself is untouched. Reaches for
    `_parent_frame` / `_scrollbar` / `_parent_canvas` — CTk exposes no hook."""
    bar = scroll_frame._scrollbar
    canvas = scroll_frame._parent_canvas
    scroll_frame._parent_frame.grid_columnconfigure(1, minsize=_SCROLLBAR_GUTTER)

    def relay(start, end):
        bar.set(start, end)
        overflowing = not (float(start) <= 0.0 and float(end) >= 1.0)
        if overflowing == relay.shown:
            return
        relay.shown = overflowing
        (bar.grid if overflowing else bar.grid_remove)()

    relay.shown = True  # CTk grids the bar in by default
    canvas.configure(yscrollcommand=relay)


class QueueTab(ctk.CTkFrame):
    """Displays queued encoding/muxing tasks and lets the user manage them."""

    def __init__(self, master, app):
        super().__init__(master=master)
        self.app = app
        self._next_id = 0
        self._rows = {}  # task_id -> row frame
        self._is_running = False
        # The one job with an ffmpeg process right now, running or suspended:
        # {"task_id", "job", "rest", "paused", "fraction", "drawn"} — or None.
        # One at a time by design; "Encode now" while a job is active runs it
        # next rather than alongside (see start_task).
        self._active = None
        self._poll_job = None  # the one in-flight after() id for _poll
        # Failure notices waiting to be shown one at a time (_show_errors).
        self._error_queue = []
        self._error_dialog_open = False
        # Which task the details popup currently shows — None while it's
        # hidden. Set by _show_details, read by _go_to_detail_file (the
        # button's own command carries no argument, since the popup can be
        # re-shown for a different row without being torn down and rebuilt).
        self._detail_task_id = None
        # Row thumbnails decoded off the Tk thread (see _load_thumbnail).
        self._thumb_results = queue.Queue()
        self._thumb_pending = 0

        # on_leave() (called by LlamaGUI.show_tab) resets a fully-completed
        # overall progress bar — but ONLY when actually switching to a
        # different tab, not on a Queue->Queue re-click or a window minimize.

        # Overall queue progress — how many of the current tasks are Done.
        # corner_radius=0: CTkProgressBar's rounded end-caps are drawn as full
        # circles regardless of fill amount, so at value=0 two overlapping
        # caps still paint a visible dot of progress_color — flat corners
        # avoid that "color before anything happened" artifact.
        self.progress_bar = ctk.CTkProgressBar(master=self, progress_color=_THEME["primary"], corner_radius=0)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", padx=20, pady=(15, 10))

        # Scrollable list of queued tasks
        self.list_frame = ctk.CTkScrollableFrame(master=self, fg_color="transparent")
        # Right pad trimmed from 20 to 3: _autohide_scrollbar_in_gutter reserves
        # a fixed ~18px column at the list's right edge for the scrollbar, and
        # that gutter should come out of the window margin, not the row width —
        # so the rows stay put whether or not the bar is showing.
        self.list_frame.pack(fill="both", expand=True, padx=(20, 3), pady=(0, 10))
        _autohide_scrollbar_in_gutter(self.list_frame)

        # Empty-state placeholder
        self.empty_label = ctk.CTkLabel(
            master=self.list_frame, text="No tasks queued yet.", text_color="gray60"
        )
        self.empty_label.pack(pady=20)

        # Job details popup — hidden until a row is clicked. Fixed overall
        # height (header + a fixed-height scroll area) so an Encode task's
        # longer field list scrolls instead of growing the box taller than a
        # Mux task's. Packed with before=self.controls_frame at show-time so
        # it always slides in directly above the bottom controls.
        self.detail_frame = ctk.CTkFrame(master=self, fg_color=("gray85", "gray20"), corner_radius=8)

        self.detail_header_row = ctk.CTkFrame(master=self.detail_frame, fg_color="transparent")
        self.detail_header_row.pack(fill="x", padx=10, pady=(8, 4))

        self.detail_title_label = ctk.CTkLabel(
            master=self.detail_header_row, text="", font=ctk.CTkFont(size=13, weight="bold")
        )
        self.detail_title_label.pack(side="left")

        self.detail_close_btn = ctk.CTkButton(
            master=self.detail_header_row, text="✕", width=24, height=24,
            fg_color="transparent", hover_color=("gray75", "gray30"),
            command=self.detail_frame.pack_forget,
        )
        self.detail_close_btn.pack(side="right")

        # Only meaningful once the output file actually exists — greyed out
        # otherwise (see _show_details, which enables/disables it per task
        # rather than hiding it, matching this app's usual convention for a
        # control that doesn't currently apply).
        self.detail_goto_btn = ctk.CTkButton(
            master=self.detail_header_row, text="Go to File", width=90, height=24,
            fg_color=_THEME["secondary"], hover_color=_THEME["secondary_hover"],
            text_color=_THEME["secondary_text"],
            command=self._go_to_detail_file,
        )
        self.detail_goto_btn.pack(side="right", padx=(0, 6))

        self.detail_scroll = ctk.CTkScrollableFrame(
            master=self.detail_frame, fg_color="transparent", height=_DETAIL_SCROLL_HEIGHT
        )
        # fill="x" only (no expand) — keeps this at its configured height
        # regardless of content, so Encode's longer field list scrolls
        # inside it instead of stretching the whole popup taller.
        self.detail_scroll.pack(fill="x", padx=6, pady=(0, 8))

        # Bottom controls
        self.controls_frame = ctk.CTkFrame(master=self, fg_color="transparent")
        self.controls_frame.pack(fill="x", padx=20, pady=(0, 10))

        self.clear_btn = ctk.CTkButton(
            master=self.controls_frame,
            text="Clear Completed",
            fg_color=_THEME["secondary"],
            hover_color=_THEME["secondary_hover"],
            text_color=_THEME["secondary_text"],
            command=self.clear_completed,
        )
        self.clear_btn.pack(side="left")

        self.clear_all_btn = ctk.CTkButton(
            master=self.controls_frame,
            text="Clear All",
            width=90,
            fg_color=_THEME["secondary"],
            hover_color=_THEME["secondary_hover"],
            text_color=_THEME["secondary_text"],
            command=self.clear_all,
        )
        self.clear_all_btn.pack(side="left", padx=(8, 0))

        # Packed side="right" in this order (start first, stop second) so
        # Stop lands immediately to Start/Pause's left.
        self.start_all_btn = ctk.CTkButton(
            master=self.controls_frame,
            text="Start Queue",
            fg_color=_THEME["primary"],
            text_color=_THEME["primary_text"],
            hover_color=_THEME["primary_hover"],
            command=self.start_queue,
        )
        self.start_all_btn.pack(side="right")

        self.stop_btn = ctk.CTkButton(
            master=self.controls_frame,
            text="Stop Queue",
            text_color=_STOP_TEXT,
            fg_color=_STOP_RED,
            hover_color=_STOP_RED_HOVER,
            command=self.stop_queue,
        )
        self.stop_btn.pack(side="right", padx=(0, 8))

    def add_task(self, description, settings=None, status="Queued", source_tab="Encoding"):
        """Adds a new task row to the queue. `settings` is an arbitrary dict of
        encoding/muxing parameters that can later be sent back to the tab that
        queued it (`source_tab`, e.g. "Encoding" or "Muxing"). Returns the
        task's internal id."""
        # Unconditionally — winfo_ismapped() is False while the tab has
        # never been shown, which used to leave the placeholder packed above
        # the first real rows until the tab was opened.
        self.empty_label.pack_forget()

        task_id = self._next_id
        self._next_id += 1
        settings = settings or {}

        row = ctk.CTkFrame(master=self.list_frame, corner_radius=_ROW_CORNER)
        row.pack(fill="x", pady=4)

        # Construction order below IS the stacking order — in Tk, a
        # later-constructed sibling sits higher, so this ordering alone (no
        # explicit lift()/lower() anywhere) gives every widget the z-position
        # it needs:
        #   description_label < base_canvas < progress_canvas < thumb_label
        # i.e. both canvases paint over the label (replacing its text with
        # their own while running), the fill paints over the grey base, and
        # the thumbnail stays on top of all of it so the fill can never cover
        # it no matter how far it grows. Confirmed by isolating this exact
        # construction order and comparing rendered pixels. Packing happens
        # afterward, in the actual left-to-right visual order — pack() call
        # order controls layout position independently of construction order
        # controlling stacking.
        description_label = ctk.CTkLabel(master=row, text=description, anchor="w", justify="left")

        # While a row is running its description is rendered by TWO stacked
        # raw tkinter.Canvases, not by description_label — see
        # _paint_row_canvas for the full why. Short version: the moving fill
        # edge has to cut a glyph in half, so the text either side of it must
        # come from the *same* renderer at the *same* coordinates, or the two
        # halves don't line up. `base_canvas` spans the whole description
        # region in the row's grey; `progress_canvas` is the same drawing
        # clipped to `fill_width` in the theme's primary. Both draw their text
        # via create_text at identical local coords with the same font, so the
        # halves are pixel-identical by construction. Both sit unplaced
        # (invisible) until the row actually starts running.
        #
        # A raw Canvas is what makes the clip possible at all: it genuinely
        # crops whatever it draws to its configured width/height, unlike
        # CTkLabel, which silently ignores a width smaller than its natural
        # text size (confirmed empirically — see CLAUDE.md).
        char_font = description_label.cget("font")
        backdrop = self._row_backdrop_bg(row)
        base_canvas = tkinter.Canvas(
            master=row, bg=backdrop, highlightthickness=0, bd=0
        )
        base_text_item = base_canvas.create_text(
            0, 0, anchor="w", text=description, fill=self._grey_row_text(), font=char_font
        )
        progress_canvas = tkinter.Canvas(
            master=row, bg=backdrop, highlightthickness=0, bd=0
        )
        progress_text_item = progress_canvas.create_text(
            0, 0, anchor="w", text=description, fill=_THEME["primary_text"], font=char_font
        )

        thumb_label = ctk.CTkLabel(master=row, text="", width=_THUMB_SIZE[0], height=_THUMB_SIZE[1])

        thumb_label.pack(side="left", padx=(10, 8), pady=8)
        self._load_thumbnail(thumb_label, settings.get("input_file"), settings.get("thumbnail_url"))

        status_label = ctk.CTkLabel(master=row, text=status, width=80)
        remove_btn = ctk.CTkButton(
            master=row, text="✕", width=28, height=28,
            fg_color="transparent",
            command=lambda: self.remove_task(task_id),
        )
        # The fixed-width right-hand pieces are packed BEFORE the expanding
        # description (pack order is independent of the construction order
        # above). pack() carves the cavity in call order, so a description
        # packed first — any long file name — requested more than the row had
        # left and squeezed status_label and remove_btn out entirely
        # (unmapped, x=0). That also zeroed the progress fill, whose width is
        # capped at status_label's left edge. Packed last, the description
        # just gets whatever room remains and clips.
        remove_btn.pack(side="right", padx=10)
        status_label.pack(side="right", padx=(0, 10))
        description_label.pack(side="left", fill="x", expand=True, padx=(0, 10), pady=8)

        # Single click shows job details — bound on every part of the row
        # except remove_btn. The two progress canvases are in the list because
        # while a job runs they sit on top of description_label and would
        # otherwise swallow every click that lands on the description text,
        # leaving only the thumbnail and status-label ends of the row live.
        for widget in (row, thumb_label, description_label, status_label,
                       base_canvas, progress_canvas):
            widget.bind("<Button-1>", lambda e, tid=task_id: self._show_details(tid))

        self._rows[task_id] = {
            "frame": row,
            "description_label": description_label,
            "base_canvas": base_canvas,
            "base_text_item": base_text_item,
            "progress_canvas": progress_canvas,
            "progress_text_item": progress_text_item,
            "status_label": status_label,
            "remove_btn": remove_btn,
            "settings": settings,
            "source_tab": source_tab,
        }
        self._apply_row_style(task_id)
        self._update_overall_progress()
        return task_id

    @staticmethod
    def _flatten_color(color):
        """Picks the light or dark half of a CTk (light, dark) color pair for
        the current appearance mode — a raw tkinter.Canvas can only take a
        single Tk color, never a pair. Passes a plain string through."""
        if isinstance(color, (list, tuple)):
            return color[0] if ctk.get_appearance_mode() == "Light" else color[1]
        return color

    def _grey_row_text(self):
        """The label color a running (grey) row's text uses, flattened to a
        single Tk color — base_canvas has to reproduce description_label's
        appearance exactly, so it reads the same CTk default the label does."""
        return self._flatten_color(ctk.ThemeManager.theme["CTkLabel"]["text_color"])

    def _row_backdrop_bg(self, row_frame):
        """The color visible *behind* a task row — i.e. what shows through the
        row's own rounded-corner cutouts. CTk already resolves this for every
        frame as its `bg_color` (the color it paints outside the rounded
        rectangle it draws in `fg_color`), so we just ask the row for it.

        This is what progress_canvas uses as its Tk `bg`, and it matters: the
        canvas is a hard rectangle covering the row's left end, and the only
        pixels of it left unpainted by the fill are the two corner nooks
        outside the fill's rounded left corners. Painting those the *row's*
        grey (as this used to) filled the row's own corner cutouts with a
        solid block, so a running row read as a square grey box with a
        rounded fill floating inside it. Painting them the backdrop instead
        leaves the row looking rounded on all four corners, fill or no fill."""
        return self._flatten_color(row_frame.cget("bg_color"))

    def _load_thumbnail(self, thumb_label, input_file, thumbnail_url=None):
        """Gives a row a small preview frame of its input file, if any —
        without decoding video on the Tk thread, which used to hitch the UI
        every time a job was queued.

        The queued file is almost always the one currently selected, whose
        frames the app has already decoded off-thread, so its first frame is
        simply reused. Otherwise (e.g. queued before those frames landed) one
        frame is decoded on a worker thread and delivered via
        _drain_thumbnails — same worker/queue/poll pattern as the app's own
        thumbnail loading.

        A download task has no file yet — it shows the video's online
        thumbnail instead: the one the Downloader tab's fetch already
        downloaded when it's the same link, else fetched on a worker."""
        if not input_file and thumbnail_url:
            cache = getattr(self.app, "ytdlp_cache", None)
            if cache and cache.get("thumb") is not None \
                    and cache["info"].get("thumbnail") == thumbnail_url:
                self._set_thumbnail(thumb_label, cache["thumb"])
                return

            def fetch():
                self._thumb_results.put((thumb_label, downloader.download_thumbnail(thumbnail_url)))

            self._thumb_pending += 1
            threading.Thread(target=fetch, daemon=True).start()
            if self._thumb_pending == 1:
                self.after(80, self._drain_thumbnails)
            return
        if not input_file:
            return
        cached = getattr(self.app, "_thumb_frames", None)
        if cached and getattr(self.app, "_thumb_frames_path", None) == input_file:
            self._set_thumbnail(thumb_label, cached[0])
            return

        def decode():
            self._thumb_results.put((thumb_label, extract_video_thumbnail(input_file)))

        self._thumb_pending += 1
        threading.Thread(target=decode, daemon=True).start()
        if self._thumb_pending == 1:
            self.after(80, self._drain_thumbnails)

    def _drain_thumbnails(self):
        """Main-thread poll for row thumbnails decoded off-thread; re-arms
        while any are still outstanding. A row removed mid-decode is skipped."""
        while True:
            try:
                thumb_label, pil_image = self._thumb_results.get_nowait()
            except queue.Empty:
                break
            self._thumb_pending = max(0, self._thumb_pending - 1)
            if pil_image is not None and thumb_label.winfo_exists():
                self._set_thumbnail(thumb_label, pil_image)
        if self._thumb_pending > 0:
            self.after(80, self._drain_thumbnails)

    @staticmethod
    def _set_thumbnail(thumb_label, pil_image):
        """Shows `pil_image` in a row's thumbnail slot."""
        ctk_img = ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=_THUMB_SIZE)
        thumb_label.configure(image=ctk_img, text="")

    def _apply_row_style(self, task_id):
        """Colors a row by its current status: solid yellow while queued
        (not yet started), grey with a growing yellow fill while running or
        paused, flat grey once Done, solid red once Failed."""
        row = self._rows.get(task_id)
        if not row:
            return

        status = row["status_label"].cget("text")
        # Both canvases only ever exist to draw a running row; hiding them
        # hands the description back to description_label's own rendering.
        if status == "Queued":
            style = _QUEUED_STYLE
            row["base_canvas"].place_forget()
            row["progress_canvas"].place_forget()
        elif status == "Failed":
            style = _FAILED_STYLE
            row["base_canvas"].place_forget()
            row["progress_canvas"].place_forget()
        else:
            style = _GREY_STYLE
            if status == "Done":
                row["base_canvas"].place_forget()
                row["progress_canvas"].place_forget()
            # else: mid-run or Paused — _paint_fraction owns both canvases' geometry

        text_color = style["text"] or ctk.ThemeManager.theme["CTkLabel"]["text_color"]
        remove_text_color = style["remove_text"] or ctk.ThemeManager.theme["CTkButton"]["text_color"]

        row["frame"].configure(fg_color=style["bg"])
        row["description_label"].configure(text_color=text_color)
        row["status_label"].configure(text_color=text_color)
        row["remove_btn"].configure(text_color=remove_text_color, hover_color=style["remove_hover"])

    def refresh_theme(self):
        """Re-applies the (freshly re-read) active theme's colors to this
        tab's own already-built widgets, in place — used by LlamaGUI.
        apply_theme() for a live theme switch. Unlike Muxing/Encoding/
        Settings, this tab is never destroyed and rebuilt on a theme
        change, specifically so self._rows (the task list), self._is_
        running, and any in-flight animation survive completely untouched;
        only colors change here."""
        global _THEME
        _THEME = get_active_theme()
        _QUEUED_STYLE["bg"] = _THEME["primary"]
        _QUEUED_STYLE["remove_hover"] = _THEME["primary_hover"]
        # Adaptive label color (black/white) for the new primary — picked up
        # per row by _apply_row_style below, which reads these keys every call.
        _QUEUED_STYLE["text"] = _THEME["primary_text"]
        _QUEUED_STYLE["remove_text"] = _THEME["primary_text"]

        self.progress_bar.configure(progress_color=_THEME["primary"])
        for button in (self.clear_btn, self.clear_all_btn, self.detail_goto_btn):
            button.configure(
                fg_color=_THEME["secondary"], hover_color=_THEME["secondary_hover"],
                text_color=_THEME["secondary_text"],
            )
        self.start_all_btn.configure(
            fg_color=_THEME["primary"], hover_color=_THEME["primary_hover"],
            text_color=_THEME["primary_text"],
        )

        for task_id, row in self._rows.items():
            backdrop = self._row_backdrop_bg(row["frame"])
            row["base_canvas"].configure(bg=backdrop)
            row["base_canvas"].itemconfigure(row["base_text_item"], fill=self._grey_row_text())
            row["progress_canvas"].configure(bg=backdrop)
            row["progress_canvas"].itemconfigure(row["progress_text_item"], fill=_THEME["primary_text"])
            self._apply_row_style(task_id)

    def _add_detail_row(self, label, value):
        """One `label: value` row in the details popup — shared by the
        _DETAIL_FIELDS loop and the multi-stream audio rows below it, so
        both render identically."""
        field_row = ctk.CTkFrame(master=self.detail_scroll, fg_color="transparent")
        field_row.pack(fill="x", pady=1)
        ctk.CTkLabel(
            master=field_row, text=f"{label}:", font=("Arial", 11, "bold"), width=120, anchor="w"
        ).pack(side="left")
        ctk.CTkLabel(master=field_row, text=str(value) or "—", anchor="w", justify="left").pack(
            side="left", fill="x", expand=True
        )

    def _show_details(self, task_id):
        """Populates and reveals the job-details popup for a clicked row."""
        row = self._rows.get(task_id)
        if not row:
            return

        self._detail_task_id = task_id
        kind = {"Encoding": "Encode", _YTDLP: "Download"}.get(row["source_tab"], "Mux")
        self.detail_title_label.configure(text=f"{kind} Details")

        settings = row["settings"]
        output_path = settings.get("output_path")
        self.detail_goto_btn.configure(
            state="normal" if output_path and os.path.exists(output_path) else "disabled"
        )

        for child in self.detail_scroll.winfo_children():
            child.destroy()
        # A stripped stream's own codec/track details are noise once it's not
        # actually in the output — "Strip Video: Yes" already says everything
        # that matters, so those rows (not that one) are skipped here.
        strip_video = bool(settings.get("strip_video"))
        strip_audio = bool(settings.get("strip_audio"))
        for key, label, kind_fmt in _DETAIL_FIELDS:
            if key not in settings:
                continue
            if strip_video and key in _VIDEO_DETAIL_KEYS:
                continue
            if strip_audio and key in _AUDIO_DETAIL_KEYS:
                continue
            value = settings[key]
            if kind_fmt == "time":
                value = _format_seconds(value)
            elif kind_fmt == "bool":
                value = "Yes" if value else "No"
            self._add_detail_row(label, value)

        # Encoding's multi-stream audio — one row per included stream, since
        # there's no longer a single flat audio_codec/bitrate/channels/
        # sample_rate to list generically alongside _DETAIL_FIELDS above.
        # Absent on a Mux task (it has its own audio_track/audio_track_file,
        # already covered above) and skipped entirely once Strip Audio makes
        # the whole thing moot, same as every other audio row.
        if not strip_audio:
            streams = settings.get("audio_streams")
            if streams:
                for i, entry in enumerate(streams):
                    bits = [entry.get("codec") or "—"]
                    if entry.get("passthru"):
                        bits.append("copy")
                    for key in ("bitrate", "channels", "sample_rate"):
                        value = entry.get(key)
                        if value and value != formats.SELECT:
                            bits.append(value)
                    label = "Audio Stream" if len(streams) == 1 else f"Audio Stream {i + 1}"
                    self._add_detail_row(label, " · ".join(bits))

        # A failed job's reason — not a settings key, so it's added by hand.
        if row.get("error"):
            field_row = ctk.CTkFrame(master=self.detail_scroll, fg_color="transparent")
            field_row.pack(fill="x", pady=1)
            ctk.CTkLabel(
                master=field_row, text="Error:", font=("Arial", 11, "bold"), width=120, anchor="nw"
            ).pack(side="left", anchor="n")
            ctk.CTkLabel(
                master=field_row, text=row["error"], text_color=_STOP_RED,
                anchor="w", justify="left", wraplength=420,
            ).pack(side="left", fill="x", expand=True)

        self.detail_frame.pack(fill="x", padx=20, pady=(0, 10), before=self.controls_frame)

    def _go_to_detail_file(self):
        """Opens Explorer with the currently-shown task's output file
        selected. The button is only enabled once `_show_details` has
        confirmed the file exists, but re-checks here too — the popup can
        sit open for a while, and the file could be moved or deleted out
        from under it in the meantime."""
        row = self._rows.get(self._detail_task_id)
        if not row:
            return
        path = os.path.abspath(row["settings"].get("output_path") or "")
        if not path or not os.path.exists(path):
            self.detail_goto_btn.configure(state="disabled")
            show_message(
                self.app, "File Not Found",
                "This file no longer exists at its saved location — it may "
                "have been moved, renamed, or deleted since the job finished.",
            )
            return
        # A single command-line *string*, not an argv list -- Explorer's own
        # "/select,<path>" syntax needs the path wrapped in literal quote
        # characters it parses itself, and subprocess's list-to-command-line
        # conversion (list2cmdline) would quote the whole "/select,..." token
        # as one unit whenever the path contains a space, breaking Explorer's
        # own parsing of where the flag ends and the path begins. Passing a
        # plain string on Windows bypasses that conversion entirely and is
        # used exactly as written.
        subprocess.Popen(f'explorer /select,"{path}"')

    def update_status(self, task_id, status):
        """Updates the status text of an existing task row and its styling."""
        row = self._rows.get(task_id)
        if row:
            row["status_label"].configure(text=status)
            self._apply_row_style(task_id)
            self._update_overall_progress()

    def _update_overall_progress(self):
        """Sets the top progress bar to (finished tasks + the active task's
        own live fraction) / total -- called on every status change *and*
        every `_poll` tick, so it moves continuously with whatever's actually
        running rather than only jumping at Queued/Done/Failed transitions.
        (It used to just count finished/total, which sat still for the
        entire length of whichever job was currently encoding.)"""
        total = len(self._rows)
        if total == 0:
            self.progress_bar.set(0)
            return
        # Failed counts as finished: nothing more will happen to it.
        done = sum(1 for row in self._rows.values() if row["status_label"].cget("text") in _FINISHED)
        active_fraction = self._active["fraction"] if self._active is not None else 0.0
        self.progress_bar.set((done + active_fraction) / total)

    def is_running(self):
        """Whether the queue is actively processing right now."""
        return self._is_running

    def pending_task_count(self):
        """How many tasks would be lost if the app closed right now — i.e.
        everything not yet finished, whether it's mid-run, paused, or still
        Queued behind it. (A Failed job has nothing left to lose.) Read by
        LlamaGUI.on_close to decide whether to confirm."""
        return sum(
            1 for row in self._rows.values() if row["status_label"].cget("text") not in _FINISHED
        )

    def claims_output(self, path):
        """Whether an unfinished job (queued, running, or paused) will write
        `path`. The tabs' overwrite prompt checks this as well as the disk,
        since two queued jobs aimed at one path both pass a disk check."""
        target = os.path.normcase(os.path.abspath(path))
        for row in self._rows.values():
            if row["status_label"].cget("text") in _FINISHED:
                continue
            other = row["settings"].get("output_path")
            if other and os.path.normcase(os.path.abspath(other)) == target:
                return True
        return False

    def on_leave(self):
        """Called by LlamaGUI.show_tab when switching to a *different* tab
        (not on a Queue->Queue re-click, not on minimize). Resets the
        overall progress bar only if it was sitting at a completed 100%, so
        a finished batch doesn't linger as a stale full bar."""
        if self.progress_bar.get() >= 1.0:
            self.progress_bar.set(0)

    def remove_task(self, task_id):
        """Removes a row. Removing the active job's row kills its ffmpeg
        first — a process must never outlive its row — and, if the queue was
        running, moves straight on to the next job."""
        continue_with = None
        if self._active is not None:
            if self._active["task_id"] == task_id:
                continue_with = self._active["rest"] if self._is_running else None
                self._halt_active()
                if continue_with is None:
                    self._set_running(False)
            elif task_id in self._active["rest"]:
                self._active["rest"].remove(task_id)

        row = self._rows.pop(task_id, None)
        if row:
            row["frame"].destroy()
        if not self._rows:
            self.empty_label.pack(pady=20)
        self._update_overall_progress()

        if continue_with is not None:
            self._process_next(continue_with)

    def clear_completed(self):
        """Removes every finished row — Done and Failed alike."""
        for task_id, row in list(self._rows.items()):
            if row["status_label"].cget("text") in _FINISHED:
                self.remove_task(task_id)

    def clear_all(self):
        """Empties the queue outright. Confirms first if anything unfinished
        would be thrown away (same reasoning as the close prompt — queued work
        shouldn't vanish on a stray click), then halts processing — killing
        any active ffmpeg — before removing rows, so no poll tick can fire
        against a dead row."""
        pending = self.pending_task_count()
        if pending:
            plural = "job" if pending == 1 else "jobs"
            if not ask_yes_no(
                self.app,
                "Clear the whole queue?",
                f"{pending} unfinished {plural} would be cancelled and removed.\n\n"
                "Clear the queue anyway?",
            ):
                return
        self.stop_queue()
        for task_id in list(self._rows):
            self.remove_task(task_id)

    def _set_running(self, is_running):
        self._is_running = is_running
        if is_running:
            self.start_all_btn.configure(text="Pause Queue", command=self.pause_queue)
        else:
            self.start_all_btn.configure(text="Start Queue", command=self.start_queue)

    def toggle_queue(self):
        """Pause if running, start / resume if not — the Space-bar shortcut
        (`LlamaGUI._toggle_queue`), mirroring the `start_all_btn` toggle."""
        if self._is_running:
            self.pause_queue()
        else:
            self.start_queue()

    def start_queue(self):
        """Starts processing Queued tasks in order — or, when a job is
        paused, thaws its ffmpeg so it carries on from the exact frame it
        froze on."""
        if self._active is not None:
            active = self._active
            if active["paused"]:
                active["job"].resume()
                active["paused"] = False
                self.update_status(active["task_id"], self._running_label(active["task_id"], active))
            self._set_running(True)
            self._schedule_poll()
            return

        queued_ids = [
            tid for tid, row in self._rows.items()
            if row["status_label"].cget("text") == "Queued"
        ]
        if not queued_ids:
            return
        self._set_running(True)
        self._process_next(queued_ids)

    def pause_queue(self):
        """Freezes the active job's ffmpeg in place — a real OS-level suspend
        (core.ffmpeg_runner), not just a stopped poll, so nothing encodes
        while paused — and keeps it, so Start Queue resumes it from exactly
        where it stopped."""
        self._cancel_poll()
        if self._active is not None and not self._active["paused"]:
            self._active["job"].suspend()
            self._active["paused"] = True
            self.update_status(self._active["task_id"], "Paused")
        self._set_running(False)

    def stop_queue(self):
        """Halts processing: kills the active job's ffmpeg (running or
        paused), deletes its partial output, and reverts it to Queued."""
        if self._active is not None:
            task_id = self._active["task_id"]
            self._halt_active()
            if task_id in self._rows:
                self.update_status(task_id, "Queued")
        self._set_running(False)

    def shutdown(self):
        """Called by LlamaGUI.on_close just before the window goes: kills any
        active ffmpeg and deletes its partial output. Windows doesn't take a
        child process down with its parent, so without this an encode would
        carry on after the app is gone — or, if paused, sit frozen forever
        holding its file open."""
        self._halt_active()

    def start_task(self, task_id):
        """The tabs' "do it now" path (Encode / Mux). Starts `task_id` right
        away when no job is active; otherwise it jumps the line and runs as
        soon as the active job finishes — one ffmpeg at a time. Returns
        "started", "next", or "paused" (next, but the queue is paused) so
        the tab can word its toast."""
        if self._active is not None:
            self._active["rest"].insert(0, task_id)
            return "next" if self._is_running else "paused"
        self._set_running(True)
        self._process_next([task_id])
        return "started"

    def _running_label(self, task_id, active=None):
        """A row's in-progress status text: "Encoding..." / "Muxing...", or
        for a download, the last stage its job reported ("Downloading
        video...", "Merging...")."""
        source = self._rows[task_id]["source_tab"]
        if source == _YTDLP:
            return (active or {}).get("stage") or _PREPARING
        return "Encoding..." if source == "Encoding" else "Muxing..."

    def _process_next(self, remaining_ids):
        """Launches the next Queued job in `remaining_ids` as a real ffmpeg
        process and returns immediately. Only the argv is built here on the
        Tk thread; the encode runs in core.ffmpeg_runner's worker threads,
        and _poll picks up what they report."""
        if not remaining_ids:
            self._active = None
            self._set_running(False)
            # Every path that reaches here (queue exhausted, or the active
            # job's row was removed and nothing was left behind it) follows
            # at least one job actually running — start_queue/start_task
            # both refuse to call _process_next at all on an empty list —
            # so this is always a genuine "the batch is over" moment.
            self.app.notify("All queued jobs finished.")
            return
        task_id, rest = remaining_ids[0], list(remaining_ids[1:])
        row = self._rows.get(task_id)
        # Skip anything removed, or already finished, since it was lined up.
        if not row or row["status_label"].cget("text") != "Queued":
            self._process_next(rest)
            return

        self.update_status(task_id, self._running_label(task_id))
        if row["source_tab"] == _YTDLP:
            self._start_download(task_id, row, rest)
            return
        # This job's values become the core.ffmpeg_vars globals and its argv
        # is compiled from them — both here on the Tk thread, so the worker
        # threads only ever see a plain list, never the shared module state.
        ffmpeg_vars.load(row["settings"], row["source_tab"])
        final_path = os.path.abspath(ffmpeg_vars.OUTPUT_PATH)
        temp_path = partial_path(final_path)
        try:
            args = compile_command(temp_path)
        except Exception as exc:   # a settings combination the builder can't express
            self._fail_task(task_id, rest, f"Couldn't build the ffmpeg command: {exc}")
            return
        print("ffmpeg:", subprocess.list2cmdline(args))

        job = FfmpegJob(
            args, final_path, temp_path,
            duration_secs=ffmpeg_vars.DURATION_SECS,
            input_file=ffmpeg_vars.INPUT_FILE,
            start_secs=ffmpeg_vars.START_SECS,
            # Only jobs whose compiled command actually ran the BT.2390
            # tonemap chain get the post-encode color-tag check -- an
            # ordinary encode (or one with no HDR source at all) has nothing
            # here to verify. Read right after ffmpeg_vars.load() above, so
            # this reflects the job that's actually about to run.
            verify_hdr_tag=uses_hdr_tonemap(),
        )
        self._active = {
            "task_id": task_id, "job": job, "rest": rest,
            "paused": False, "fraction": 0.0, "drawn": None,
        }
        job.start()
        self._paint_fraction(self._active)
        self._schedule_poll()

    def _start_download(self, task_id, row, rest):
        """_process_next for a Downloader task: a YtDlpJob built from the plan the
        tab resolved at queue time. Its argv is built here on the Tk thread,
        same as an ffmpeg job's."""
        settings = row["settings"]
        plan = settings.get("download")
        if not plan or not settings.get("url") or not settings.get("output_path"):
            self._fail_task(task_id, rest, "This download is missing its link or format choice.")
            return
        job = YtDlpJob(settings["url"], plan, settings["output_path"])
        print("yt-dlp:", subprocess.list2cmdline(job.args))
        self._active = {
            "task_id": task_id, "job": job, "rest": rest,
            "paused": False, "fraction": 0.0, "drawn": None, "stage": _PREPARING,
        }
        job.start()
        self._paint_fraction(self._active)
        self._schedule_poll()

    def _schedule_poll(self):
        """(Re)arms the one _poll tick."""
        self._cancel_poll()
        self._poll_job = self.after(_POLL_INTERVAL_MS, self._poll)

    def _cancel_poll(self):
        """Cancels a pending _poll tick, if any. Every path that halts
        processing goes through here, so no stray tick fires later."""
        if self._poll_job is not None:
            self.after_cancel(self._poll_job)
            self._poll_job = None

    def _poll(self):
        """Tk-thread tick: drains the active job's events, paints its latest
        progress, and settles it when it ends. Re-arms itself while the job
        is still going; pause_queue and stop_queue cancel it.

        The worker always queues a final ("progress", 1.0) right before
        ("done",) (see FfmpegJob._watch), so a finishing job's terminal
        event usually lands in the *same* batch as the progress event that
        brings the fill to 100%. The previous version returned the instant
        it saw "done"/"failed" without ever painting that last progress
        event — so the fill would jump from wherever it last happened to be
        (often well short of full) straight to the flat "Done" grey,
        looking like it never finished filling. Painting first, unconditionally,
        fixes that; `update_idletasks()` then forces that paint to actually
        reach the screen before the status flip — without it, Tk can
        coalesce the two into one redraw and the full bar is never visibly
        rendered even though it was technically drawn (confirmed by
        recording the exact sequence of drawn widths against a real job)."""
        self._poll_job = None
        active = self._active
        if active is None:
            return
        terminal = None
        for event in active["job"].poll_events():
            if event[0] == "progress":
                active["fraction"] = event[1]
            elif event[0] == "stage":
                # A download moved to its next part ("Downloading audio...",
                # "Merging...") — the row's status follows; the bar doesn't
                # restart.
                active["stage"] = event[1]
                if not active["paused"]:
                    self.update_status(active["task_id"], event[1])
            else:
                terminal = event   # "done" or "failed" — nothing follows it
                break
        self._paint_fraction(active)
        self._update_overall_progress()
        if terminal is None:
            self._schedule_poll()
            return
        self.update_idletasks()
        if terminal[0] == "done":
            self._finish_task(active["task_id"], active["rest"])
        else:
            self._fail_task(active["task_id"], active["rest"], terminal[1])

    def _halt_active(self):
        """Kills the active job's ffmpeg (running or suspended), deletes its
        partial output, and forgets it. The row's status is the caller's."""
        self._cancel_poll()
        if self._active is not None:
            self._active["job"].stop()
            self._active = None

    def _paint_row_canvas(self, canvas, text_item, w, h, color, backdrop, text_xy):
        """Draws one of a running row's two stacked canvases: a `w`x`h` block
        of `color` with its two LEFT corners rounded (radius _ROW_CORNER,
        echoing the row) and a square right edge, with `text_item` raised on
        top at `text_xy`.

        The right edge stays square because on the fill canvas it's mid-row
        and moving — a rounded end there would read as a floating blob. The
        shape is a body rectangle plus a left edge-strip and two
        quarter-circle pieslices rather than one smooth-spline polygon; the
        spline version bowed the straight edges into visible curves. The only
        pixels of the canvas the shape leaves unpainted are the two ~8px
        corner nooks outside the arcs, which is why `backdrop` (not the row's
        grey) is the canvas bg — see _row_backdrop_bg."""
        r = min(_ROW_CORNER, w, h // 2)  # don't let the corners exceed the shape
        canvas.configure(width=w, height=h, bg=backdrop)
        canvas.delete("shape")
        canvas.create_rectangle(r, 0, w, h, fill=color, outline=color, tags="shape")
        canvas.create_rectangle(0, r, r, h - r, fill=color, outline=color, tags="shape")
        canvas.create_arc(
            0, 0, 2 * r, 2 * r, start=90, extent=90, style="pieslice",
            fill=color, outline=color, tags="shape",
        )
        canvas.create_arc(
            0, h - 2 * r, 2 * r, h, start=180, extent=90, style="pieslice",
            fill=color, outline=color, tags="shape",
        )
        canvas.tag_raise(text_item)
        canvas.coords(text_item, *text_xy)
        canvas.place(x=0, y=0)

    def _paint_progress(self, row, fill_width, max_fill_width, row_height):
        """Repaints a running row's description area as two stacked canvases:
        `base_canvas` (the row's grey, spanning the whole description region)
        with `progress_canvas` (the theme's primary, clipped to `fill_width`)
        on top. Both draw their own copy of the description text at the same
        local coordinates in the same font, so the fill edge can cut a glyph
        in half and the two halves still line up exactly.

        That stacking is the whole point. This used to be one canvas drawn
        over `description_label`, letting the fill edge fall between a
        *canvas*-rendered glyph half and a *CTkLabel*-rendered one — and
        those two renderers don't agree: measured against each other, the
        canvas copy landed exactly 1px right and 1px down of the label's,
        so every glyph the edge crossed visibly sheared. Covering the label
        entirely with base_canvas means the seam is now only ever between
        two canvases, which can't disagree. (The label still owns the row's
        layout, and still renders the text itself while the row is Queued or
        Done, when both canvases are hidden.)"""
        label = row["description_label"]
        # Canvases are placed at row-local (0,0), so label coords are already
        # canvas coords — no translation needed, and both canvases get the
        # identical value.
        text_xy = (label.winfo_x(), label.winfo_y() + label.winfo_height() / 2)
        backdrop = self._row_backdrop_bg(row["frame"])

        self._paint_row_canvas(
            row["base_canvas"], row["base_text_item"], max_fill_width, row_height,
            self._flatten_color(_GREY_STYLE["bg"]), backdrop, text_xy,
        )
        # Stay hidden until the fill is at least as wide as the corner radius,
        # so it never flashes a partial square corner on the way in.
        if fill_width < _ROW_CORNER:
            row["progress_canvas"].place_forget()
            return
        self._paint_row_canvas(
            row["progress_canvas"], row["progress_text_item"], fill_width, row_height,
            _THEME["primary"], backdrop, text_xy,
        )

    def _paint_fraction(self, active):
        """Paints the active row's fill at its latest reported fraction —
        only when the drawn result would actually change, since progress
        often repeats and the tab's geometry only settles once it has been
        shown (a changed width/height forces a repaint on its own)."""
        row = self._rows.get(active["task_id"])
        if not row:
            return
        row_height = row["frame"].winfo_height()
        # Capped at status_label's own left edge, not the full row width.
        # status_label and remove_btn are fg_color="transparent", which is
        # a frozen, one-time snapshot of the row's pre-style color, not real
        # per-pixel transparency (see the CLAUDE.md gotcha). If the fill
        # grew underneath either of them, that frozen background would
        # occlude it, showing as a solid grey box cut into an otherwise
        # continuous fill. The fill only ever represents progress on the
        # thumbnail/description portion of the row, so it's simplest to
        # just never let it reach that far, rather than chase dynamic
        # recoloring on every other widget in the row.
        max_fill_width = row["status_label"].winfo_x()
        fill_width = round(active["fraction"] * max_fill_width)
        drawn = (fill_width, max_fill_width, row_height)
        if drawn != active["drawn"]:
            active["drawn"] = drawn
            self._paint_progress(row, fill_width, max_fill_width, row_height)

    def _finish_task(self, task_id, rest):
        """The active job exited cleanly and its file is in place."""
        self._active = None
        if task_id in self._rows:
            self.update_status(task_id, "Done")
        self._process_next(rest)

    def _fail_task(self, task_id, rest, reason):
        """The active job failed: turn its row red, keep the queue moving,
        and tell the user why. The notice is queued rather than shown here —
        see _show_errors."""
        self._active = None
        row = self._rows.get(task_id)
        if row:
            row["error"] = reason
            self.update_status(task_id, "Failed")
            name = os.path.basename((row["settings"].get("input_file") or "").replace("\\", "/")) \
                or row["settings"].get("title") or "This download"
            verb = {"Encoding": "encoded", _YTDLP: "downloaded"}.get(row["source_tab"], "muxed")
            self._error_queue.append(f"“{name}” couldn't be {verb}.\n\n{reason}")
            self.after(0, self._show_errors)
        self._process_next(rest)

    def _show_errors(self):
        """Shows queued failure notices one at a time.

        `show_message` blocks in a *nested* event loop (`wait_window`), and
        after() callbacks — the job poll included — keep firing inside it. So
        a notice is never opened from inside _poll (that would re-enter the
        poll and could stack dialogs); it's posted here via after(0) instead.
        A failure that lands while a notice is already up hits the
        `_error_dialog_open` guard, and the loop below picks it up once the
        current one is dismissed. The queue keeps running behind the dialog."""
        if self._error_dialog_open:
            return
        self._error_dialog_open = True
        try:
            while self._error_queue:
                show_message(self.app, "Job Failed", self._error_queue.pop(0))
        finally:
            self._error_dialog_open = False
