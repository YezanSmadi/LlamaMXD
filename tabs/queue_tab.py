import tkinter

import customtkinter as ctk

from core.utilities import extract_video_thumbnail
from core.theme import get_active_theme

# Read once at import time, and reassigned by refresh_theme() on a live
# theme switch (see LlamaGUI.apply_theme) — every row construction and
# style lookup reads this module-level name at call time, not a value
# captured once, so a reassignment here is picked up everywhere.
_THEME = get_active_theme()

# Row styling by state: not-yet-started tasks read as solid brand primary;
# once a task starts, the row goes grey and progress_canvas (a primary-
# colored overlay placed on top) grows left-to-right to show its individual
# progress: Done just drops back to flat grey with the fill hidden. The
# remove button's "X" is darkened on the primary (queued) state for contrast.
_QUEUED_STYLE = {"bg": _THEME["primary"], "text": "black", "remove_text": "black", "remove_hover": _THEME["primary_hover"]}
_GREY_STYLE = {"bg": ("gray85", "gray20"), "text": None, "remove_text": None, "remove_hover": ("gray75", "gray30")}
_THUMB_SIZE = (60, 40)
_PROGRESS_STEPS = 15
_PROGRESS_INTERVAL_MS = 100  # 15 * 100ms = 1500ms total — same overall duration as before
_DETAIL_SCROLL_HEIGHT = 140  # fixed so Encode/Mux popups match height; Encode's extra fields scroll

# (settings key, display label, value kind) — kind is None for plain text,
# "time" to format as HH:MM:SS, "bool" to format as Yes/No. Fields not present
# in a given task's settings (e.g. GPU/CRF for a Mux task) are skipped.
_DETAIL_FIELDS = [
    ("input_file", "Input File", None),
    ("output_path", "Output Path", None),
    ("start_secs", "Start Time", "time"),
    ("duration_secs", "Clip Duration", "time"),
    ("retain_length", "Retain Length", "bool"),
    ("gpu_enabled", "GPU Acceleration", "bool"),
    ("hdr_to_sdr", "HDR to SDR", "bool"),
    ("crf", "Quality (CRF)", None),
    ("profile", "Profile", None),
    ("level", "Level", None),
]


def _format_seconds(total_seconds):
    total_seconds = int(total_seconds or 0)
    hrs, rem = divmod(total_seconds, 3600)
    mins, secs = divmod(rem, 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"


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

        # Reset the overall progress bar once a fully-completed queue is
        # navigated away from, so returning later (or starting a new batch)
        # doesn't show a stale "100% done" from a batch already dealt with.
        self.bind("<Unmap>", lambda e: self._on_hide())

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
        self.list_frame.pack(fill="both", expand=True, padx=20, pady=(0, 10))

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
            text_color="white",
            command=self.clear_completed,
        )
        self.clear_btn.pack(side="left")

        # Packed side="right" in this order (start first, stop second) so
        # Stop lands immediately to Start/Pause's left.
        self.start_all_btn = ctk.CTkButton(
            master=self.controls_frame,
            text="Start Queue",
            fg_color=_THEME["primary"],
            text_color="black",
            hover_color=_THEME["primary_hover"],
            command=self.start_queue,
        )
        self.start_all_btn.pack(side="right")

        self.stop_btn = ctk.CTkButton(
            master=self.controls_frame,
            text="Stop Queue",
            text_color="black",
            fg_color="#E5484D",
            hover_color="#C93C40",
            command=self.stop_queue,
        )
        self.stop_btn.pack(side="right", padx=(0, 8))

    def add_task(self, description, settings=None, status="Queued", source_tab="Encoding"):
        """Adds a new task row to the queue. `settings` is an arbitrary dict of
        encoding/muxing parameters that can later be sent back to the tab that
        queued it (`source_tab`, e.g. "Encoding" or "Muxing"). Returns the
        task's internal id."""
        if self.empty_label.winfo_ismapped():
            self.empty_label.pack_forget()

        task_id = self._next_id
        self._next_id += 1
        settings = settings or {}

        row = ctk.CTkFrame(master=self.list_frame, corner_radius=8)
        row.pack(fill="x", pady=4)

        # description_label is constructed (but not yet packed) before
        # progress_canvas, and thumb_label after it — construction order is
        # what determines default stacking order in Tk (later = higher), so
        # this ordering alone (no explicit lift()/lower() needed) gives
        # progress_canvas exactly the z-position it needs: above
        # description_label, so its own paint can replace what's under it,
        # but below thumb_label, so the thumbnail is never covered
        # regardless of how far the fill has grown. Confirmed by isolating
        # this exact construction order and comparing rendered pixels.
        # Packing happens afterward, in the actual left-to-right visual
        # order — pack() call order controls layout position independently
        # of construction order controlling stacking.
        description_label = ctk.CTkLabel(master=row, text=description, anchor="w", justify="left")

        # One raw tkinter.Canvas does the job that used to take two widgets
        # (a plain CTkFrame fill plus a separately-clipped text canvas).
        # Its own bg IS the theme's primary fill color, and the description
        # is drawn on top of that in black — so growing/shrinking this single
        # canvas's pixel width simultaneously grows the visible yellow fill
        # AND clips the black text at exactly the same edge, since they're
        # the same number by construction: there's no second, independently
        # -rounded width calculation left to ever disagree with it (unlike
        # the old two-widget version, which needed reading one widget's
        # resolved geometry back into the other to avoid an intermittent
        # 1px seam — see CLAUDE.md). A raw Canvas genuinely clips whatever
        # it draws to its own configured width/height, unlike CTkLabel,
        # which silently ignores a width smaller than its natural text size
        # and always renders the full, unclipped string (confirmed
        # empirically) — so this couldn't be done with CTkLabel alone.
        # Left unplaced (invisible) until the row starts running.
        char_font = description_label.cget("font")
        progress_canvas = tkinter.Canvas(
            master=row, bg=_THEME["primary"], highlightthickness=0, bd=0
        )
        progress_text_item = progress_canvas.create_text(
            0, 0, anchor="w", text=description, fill="black", font=char_font
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

        # Single click shows job details (bound on everything but remove_btn).
        for widget in (row, thumb_label, description_label, status_label):
            widget.bind("<Button-1>", lambda e, tid=task_id: self._show_details(tid))

        self._rows[task_id] = {
            "frame": row,
            "description_label": description_label,
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
        if status == "Queued":
            style = _QUEUED_STYLE
            row["progress_canvas"].place_forget()
        else:
            style = _GREY_STYLE
            if status == "Done":
                row["progress_canvas"].place_forget()
            # else: mid-run — _animate_progress owns progress_canvas's geometry

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

        self.progress_bar.configure(progress_color=_THEME["primary"])
        self.clear_btn.configure(fg_color=_THEME["secondary"], hover_color=_THEME["secondary_hover"])
        self.start_all_btn.configure(fg_color=_THEME["primary"], hover_color=_THEME["primary_hover"])

        for task_id, row in self._rows.items():
            row["progress_canvas"].configure(bg=_THEME["primary"])
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

    def _on_hide(self):
        """Resets a fully-completed overall progress bar when this tab is switched away from."""
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

    def _update_progress_canvas(self, row, fill_width, row_height):
        """Resizes progress_canvas to `fill_width` pixels wide (its own bg
        is the theme's primary fill color) and repositions its text item to
        description_label's current spot. `fill_width` is the one and only
        number driving both the visible fill width and the text clip edge —
        there's no second, independently-computed width for it to ever
        disagree with (that used to be two separate widgets — see
        CLAUDE.md's "Pixel-accurate progress-text clip" section for why
        that needed extra care to keep in sync). Hides the canvas entirely
        once `fill_width` is 0 or less."""
        canvas = row["progress_canvas"]
        if fill_width <= 0:
            canvas.place_forget()
            return

        label = row["description_label"]
        label_x = label.winfo_x()
        label_y = label.winfo_y()
        label_height = label.winfo_height()

        canvas.configure(width=fill_width, height=row_height)
        canvas.coords(row["progress_text_item"], label_x, label_y + label_height / 2)
        canvas.place(x=0, y=0)

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
        self._update_progress_canvas(row, fill_width, row_height)

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
