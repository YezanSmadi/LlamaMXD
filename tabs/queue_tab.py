import tkinter

import customtkinter as ctk

from components.dialogs import ask_yes_no
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
_THUMB_SIZE = (60, 40)
_ROW_CORNER = 8  # row frame corner_radius; the running fill echoes it on its left
_PROGRESS_STEPS = 15
_PROGRESS_INTERVAL_MS = 100  # 15 * 100ms = 1500ms total — same overall duration as before
_DETAIL_SCROLL_HEIGHT = 140  # fixed so Encode/Mux popups match height; Encode's extra fields scroll

# (settings key, display label, value kind) — kind is None for plain text,
# "time" to format as HH:MM:SS, "bool" to format as Yes/No. Fields not present
# in a given task's settings (e.g. GPU/CRF for a Mux task) are skipped.
_DETAIL_FIELDS = [
    ("input_file", "Input File", None),
    ("output_path", "Output Path", None),
    ("encoder", "Encoder", None),
    ("output_format", "Format", None),
    ("start_secs", "Start Time", "time"),
    ("duration_secs", "Clip Duration", "time"),
    # Video-stream fields — Encode tasks carry `profile`/`level`/`quality`;
    # Mux tasks carry `video_track`/`video_track_file` instead (it never
    # re-encodes). Each is skipped when simply absent from the settings dict.
    ("strip_video", "Strip Video", "bool"),
    ("gpu_enabled", "GPU Acceleration", "bool"),
    ("hdr_to_sdr", "HDR to SDR", "bool"),
    ("quality", "Quality", None),
    ("profile", "Profile", None),
    ("level", "Level", None),
    ("video_track", "Video Track", None),
    ("video_track_file", "Video From", None),
    # Audio-stream fields — `audio_codec`/`audio_bitrate`/`strip_audio` are
    # shared by both tabs; `audio_channels`/`audio_sample_rate` are Encode
    # only, `audio_track` is Mux only.
    ("audio_track", "Audio Track", None),
    ("audio_track_file", "Audio From", None),
    ("audio_codec", "Audio Codec", None),
    ("audio_bitrate", "Audio Bitrate", None),
    ("audio_channels", "Audio Channels", None),
    ("audio_sample_rate", "Audio Sample Rate", None),
    ("strip_audio", "Strip Audio", "bool"),
]


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
        self._paused_state = None  # (task_id, step, rest) captured for Pause/Resume
        self._animation_job = None

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
        self._load_thumbnail(thumb_label, settings.get("input_file"))

        description_label.pack(side="left", fill="x", expand=True, padx=(0, 10), pady=8)

        status_label = ctk.CTkLabel(master=row, text=status, width=80)
        status_label.pack(side="left", padx=(0, 10))

        remove_btn = ctk.CTkButton(
            master=row, text="✕", width=28, height=28,
            fg_color="transparent",
            command=lambda: self.remove_task(task_id),
        )
        remove_btn.pack(side="right", padx=10)

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

    def _load_thumbnail(self, thumb_label, input_file):
        """Extracts a small preview frame from the task's input file, if any."""
        if not input_file:
            return
        pil_image = extract_video_thumbnail(input_file)
        if pil_image is None:
            return
        ctk_img = ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=_THUMB_SIZE)
        thumb_label.configure(image=ctk_img, text="")

    def _apply_row_style(self, task_id):
        """Colors a row by its current status: solid yellow while queued
        (not yet started), grey with a growing yellow fill while running,
        flat grey once Done."""
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
        else:
            style = _GREY_STYLE
            if status == "Done":
                row["base_canvas"].place_forget()
                row["progress_canvas"].place_forget()
            # else: mid-run — _animate_progress owns both canvases' geometry

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
        for button in (self.clear_btn, self.clear_all_btn):
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

    def _show_details(self, task_id):
        """Populates and reveals the job-details popup for a clicked row."""
        row = self._rows.get(task_id)
        if not row:
            return

        kind = "Encode" if row["source_tab"] == "Encoding" else "Mux"
        self.detail_title_label.configure(text=f"{kind} Details")

        for child in self.detail_scroll.winfo_children():
            child.destroy()

        settings = row["settings"]
        for key, label, kind_fmt in _DETAIL_FIELDS:
            if key not in settings:
                continue
            value = settings[key]
            if kind_fmt == "time":
                value = _format_seconds(value)
            elif kind_fmt == "bool":
                value = "Yes" if value else "No"

            field_row = ctk.CTkFrame(master=self.detail_scroll, fg_color="transparent")
            field_row.pack(fill="x", pady=1)
            ctk.CTkLabel(
                master=field_row, text=f"{label}:", font=("Arial", 11, "bold"), width=120, anchor="w"
            ).pack(side="left")
            ctk.CTkLabel(master=field_row, text=str(value) or "—", anchor="w", justify="left").pack(
                side="left", fill="x", expand=True
            )

        self.detail_frame.pack(fill="x", padx=20, pady=(0, 10), before=self.controls_frame)

    def update_status(self, task_id, status):
        """Updates the status text of an existing task row and its styling."""
        row = self._rows.get(task_id)
        if row:
            row["status_label"].configure(text=status)
            self._apply_row_style(task_id)
            self._update_overall_progress()

    def _update_overall_progress(self):
        """Sets the top progress bar to the fraction of current tasks that are Done."""
        total = len(self._rows)
        if total == 0:
            self.progress_bar.set(0)
            return
        done = sum(1 for row in self._rows.values() if row["status_label"].cget("text") == "Done")
        self.progress_bar.set(done / total)

    def is_running(self):
        """Whether the queue is actively processing right now."""
        return self._is_running

    def pending_task_count(self):
        """How many tasks would be lost if the app closed right now — i.e.
        everything not yet Done, whether it's mid-run or still Queued behind
        it. Read by LlamaGUI.on_close to decide whether to confirm."""
        return sum(1 for row in self._rows.values() if row["status_label"].cget("text") != "Done")

    def on_leave(self):
        """Called by LlamaGUI.show_tab when switching to a *different* tab
        (not on a Queue->Queue re-click, not on minimize). Resets the
        overall progress bar only if it was sitting at a completed 100%, so
        a finished batch doesn't linger as a stale full bar."""
        if self.progress_bar.get() >= 1.0:
            self.progress_bar.set(0)

    def remove_task(self, task_id):
        row = self._rows.pop(task_id, None)
        if row:
            row["frame"].destroy()
        if not self._rows:
            self.empty_label.pack(pady=20)
        self._update_overall_progress()

    def clear_completed(self):
        for task_id, row in list(self._rows.items()):
            if row["status_label"].cget("text") == "Done":
                self.remove_task(task_id)

    def clear_all(self):
        """Empties the queue outright. Confirms first if anything unfinished
        would be thrown away (same reasoning as the close prompt — queued work
        shouldn't vanish on a stray click), then halts processing before
        removing rows so no animation tick can fire against a dead row."""
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

    def start_queue(self):
        """Starts processing queued tasks in order, or resumes exactly where
        a paused job left off if one is pending."""
        if self._paused_state is not None:
            task_id, step, rest = self._paused_state
            self._paused_state = None
            self._set_running(True)
            self._animate_progress(task_id, step, rest)
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
        """Halts processing without discarding the current job's progress —
        Start Queue (now labeled Resume via the same button) picks up
        exactly where this left off."""
        if self._animation_job is not None:
            self.after_cancel(self._animation_job)
            self._animation_job = None
        self._set_running(False)

    def stop_queue(self):
        """Halts processing and discards the in-flight job's progress,
        reverting it back to Queued."""
        if self._animation_job is not None:
            self.after_cancel(self._animation_job)
            self._animation_job = None
        if self._paused_state is not None:
            task_id, _step, _rest = self._paused_state
            self._paused_state = None
            if task_id in self._rows:
                self.update_status(task_id, "Queued")
        self._set_running(False)

    def start_task(self, task_id):
        """Immediately processes a single task by id (e.g. from a direct
        'Encode Now'/'Mux' action), independent of the rest of the queue."""
        self._set_running(True)
        self._process_next([task_id])

    def _process_next(self, remaining_ids):
        if not remaining_ids:
            self._set_running(False)
            return
        task_id, rest = remaining_ids[0], remaining_ids[1:]
        row = self._rows.get(task_id)
        if not row:
            self._process_next(rest)
            return

        in_progress_label = "Encoding..." if row["source_tab"] == "Encoding" else "Muxing..."
        self.update_status(task_id, in_progress_label)
        print(f"Processing task {task_id} with settings: {row['settings']}")

        self._animate_progress(task_id, 0, rest)

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

    def _animate_progress(self, task_id, step, rest):
        """Simulated per-job progress — replace with real ffmpeg progress
        reporting once that pipeline exists. Grows the row's yellow fill
        left-to-right over _PROGRESS_STEPS ticks, then finishes the task."""
        row = self._rows.get(task_id)
        if not row:
            self._process_next(rest)
            return

        self._paused_state = (task_id, step, rest)  # always know how to resume from here

        fraction = step / _PROGRESS_STEPS
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
        fill_width = round(fraction * max_fill_width)
        self._paint_progress(row, fill_width, max_fill_width, row_height)

        if step >= _PROGRESS_STEPS:
            self._paused_state = None
            self._finish_task(task_id, rest)
        else:
            self._animation_job = self.after(
                _PROGRESS_INTERVAL_MS, lambda: self._animate_progress(task_id, step + 1, rest)
            )

    def _finish_task(self, task_id, rest):
        if task_id in self._rows:
            self.update_status(task_id, "Done")
        self._process_next(rest)
