"""The Queue: task rows, one real ffmpeg / yt-dlp job at a time, pause (a real
OS suspend), stop, failures, the details popup and the overall progress bar.

A row is one widget with one paintEvent: draw the row, then clip to the
fill width and draw it again in `primary` — so the fill edge cuts a glyph
cleanly, both halves coming from the same renderer at the same coordinates.

Progress arrives in coarse jumps (ffmpeg reports ~2 Hz); the painted fill
eases toward the latest value every frame so it glides rather than steps."""
import os
import subprocess

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core import downloader, ffmpeg_vars, formats
from core.ffmpeg_build import compile_command, uses_hdr_tonemap
from core.ffmpeg_runner import FfmpegJob, partial_path
from core.utilities import extract_video_thumbnail
from core.ytdlp_runner import YtDlpJob
from ui import theme as T
from ui.tabs.media_tab import hms
from ui.widgets.controls import IconButton, button, draw_cross, ui_font
from ui.widgets.dialogs import ask_yes_no, show_message
from ui.workers import pil_to_qimage, run_async

_FINISHED = ("Done", "Failed")
_POLL_INTERVAL_MS = 100
_EASE = 0.18                 # per animation frame, toward the reported fraction
_THUMB_W, _THUMB_H = 60, 40
_ROW_H = 56
_ROW_CORNER = 8
_DETAIL_SCROLL_HEIGHT = 140
_YTDLP = "Downloader"
_PREPARING = "Preparing..."

# (settings key, label, kind) — kind None / "time" / "bool". A key absent from
# a task's settings is skipped, which is how each task kind shows only its own.
_DETAIL_FIELDS = [
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
    ("strip_video", "Strip Video", "bool"),
    ("gpu_enabled", "GPU Acceleration", "bool"),
    ("hdr_to_sdr", "HDR to SDR", "bool"),
    ("quality", "Quality", None),
    ("profile", "Profile", None),
    ("level", "Level", None),
    ("speed", "Speed", None),
    ("video_track", "Video Track", None),
    ("video_track_file", "Video From", None),
    ("audio_track", "Audio Track", None),
    ("audio_track_file", "Audio From", None),
    ("strip_audio", "Strip Audio", "bool"),
]
_VIDEO_DETAIL_KEYS = {"encoder", "gpu_enabled", "hdr_to_sdr", "quality", "profile", "level",
                      "speed", "video_track", "video_track_file"}
_AUDIO_DETAIL_KEYS = {"audio_track", "audio_track_file"}


class QueueRow(QWidget):
    """One task, fully painted: thumbnail, description, status, ✕."""

    clicked = Signal(int)
    removeRequested = Signal(int)

    def __init__(self, task_id, description, status):
        super().__init__()
        self.task_id = task_id
        self.description = description
        self.status = status
        self.fraction = 0.0      # what's painted
        self.thumb = None        # QPixmap
        self._hover_x = False
        self.setFixedHeight(_ROW_H)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self._font = ui_font(13)
        T.theme.changed.connect(self.update)

    def set_status(self, status):
        if status != self.status:
            self.status = status
            if status == "Queued":
                self.fraction = 0.0
            self.update()

    def set_fraction(self, fraction):
        fraction = max(0.0, min(1.0, fraction))
        if abs(fraction - self.fraction) > 0.0005:
            self.fraction = fraction
            self.update()

    def _x_rect(self):
        return QRectF(self.width() - 38, (_ROW_H - 28) / 2, 28, 28)

    def _status_rect(self):
        return QRectF(self.width() - 38 - 10 - 80, 0, 80, _ROW_H)

    def mouseMoveEvent(self, e):
        over = self._x_rect().contains(e.position())
        if over != self._hover_x:
            self._hover_x = over
            self.update()

    def leaveEvent(self, e):
        if self._hover_x:
            self._hover_x = False
            self.update()

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self._x_rect().contains(e.position()):
            self.removeRequested.emit(self.task_id)
        else:
            self.clicked.emit(self.task_id)

    def paintEvent(self, _event):
        th = T.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        row = QPainterPath()
        row.addRoundedRect(QRectF(0, 0, w, _ROW_H), _ROW_CORNER, _ROW_CORNER)

        if self.status == "Queued":
            base, text, x_hover = th.color("primary"), th.color("primary_text"), th.color("primary_hover")
        elif self.status == "Failed":
            base, text, x_hover = th.color("stop"), th.color("stop_text"), th.color("stop_hover")
        else:
            base, text, x_hover = th.color("row"), th.color("text"), th.color("row_hover")
        p.fillPath(row, base)

        status_rect = self._status_rect()
        desc_rect = QRectF(10 + _THUMB_W + 8, 0, status_rect.left() - 10 - (10 + _THUMB_W + 8), _ROW_H)
        running = self.status not in ("Queued", "Done", "Failed")

        def draw_description(color):
            p.setFont(self._font)
            p.setPen(color)
            elided = p.fontMetrics().elidedText(self.description, Qt.ElideRight, int(desc_rect.width()))
            p.drawText(desc_rect, Qt.AlignVCenter | Qt.AlignLeft, elided)

        draw_description(text)
        # The fill covers thumbnail + description, stopping at the status
        # column; square right edge (mid-row and moving), rounded left.
        fill_w = status_rect.left() * self.fraction if running else 0.0
        if fill_w >= 1:
            p.save()
            p.setClipRect(QRectF(0, 0, fill_w, _ROW_H))
            p.fillPath(row, th.color("primary"))
            draw_description(th.color("primary_text"))
            p.restore()

        thumb_rect = QRectF(10, (_ROW_H - _THUMB_H) / 2, _THUMB_W, _THUMB_H)
        if self.thumb is not None:
            clip = QPainterPath()
            clip.addRoundedRect(thumb_rect, 4, 4)
            p.save()
            p.setClipPath(clip)
            pw, ph = self.thumb.deviceIndependentSize().width(), self.thumb.deviceIndependentSize().height()
            scale = max(_THUMB_W / pw, _THUMB_H / ph)
            target = QRectF(0, 0, pw * scale, ph * scale)
            target.moveCenter(thumb_rect.center())
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawPixmap(target, self.thumb, QRectF(self.thumb.rect()))
            p.restore()

        p.setFont(self._font)
        p.setPen(text)
        p.drawText(status_rect, Qt.AlignCenter, self.status)
        xr = self._x_rect()
        if self._hover_x:
            hover = QPainterPath()
            hover.addRoundedRect(xr, 6, 6)
            p.fillPath(hover, x_hover)
        draw_cross(p, xr, text)


class ProgressStrip(QWidget):
    """The flat overall progress bar."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(8)
        self.value = 0.0
        T.theme.changed.connect(self.update)

    def set_value(self, value):
        value = max(0.0, min(1.0, value))
        if abs(value - self.value) > 0.0005:
            self.value = value
            self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), T.theme.color("track"))
        p.fillRect(QRectF(0, 0, self.width() * self.value, self.height()), T.theme.color("primary"))


class _DetailPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground)
        T.theme.changed.connect(self._restyle)
        self._restyle()

    def _restyle(self):
        self.setStyleSheet(f"_DetailPanel {{ background: {T.theme.hex('panel')}; border-radius: 8px; }}")


class QueueTab(QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self._next_id = 0
        self._rows = {}          # task_id -> {"widget", "settings", "source_tab", "error"}
        self._is_running = False
        # The one job with a process, running or suspended:
        # {"task_id", "job", "rest", "paused", "fraction", "stage"} — or None.
        self._active = None
        self._error_queue = []
        self._error_dialog_open = False
        self._detail_task_id = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 15, 20, 10)
        root.setSpacing(10)

        self.progress_bar = ProgressStrip()
        root.addWidget(self.progress_bar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        self.list_layout = QVBoxLayout(host)
        self.list_layout.setContentsMargins(0, 0, 4, 0)
        self.list_layout.setSpacing(8)
        self.empty_label = QLabel("No tasks queued yet.")
        self.empty_label.setProperty("role", "empty")
        self.empty_label.setAlignment(Qt.AlignHCenter)
        self.list_layout.addSpacing(10)
        self.list_layout.addWidget(self.empty_label)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(host)
        root.addWidget(self.scroll, 1)

        # Details popup — hidden until a row is clicked; fixed height so a
        # long Encode field list scrolls instead of growing the box.
        self.detail_frame = _DetailPanel()
        dl = QVBoxLayout(self.detail_frame)
        dl.setContentsMargins(10, 8, 6, 8)
        dl.setSpacing(4)
        header = QHBoxLayout()
        self.detail_title_label = QLabel("")
        self.detail_title_label.setProperty("role", "detailTitle")
        header.addWidget(self.detail_title_label)
        header.addStretch(1)
        self.detail_goto_btn = button("Go to File", width=90, height=24)
        self.detail_goto_btn.setStyleSheet("min-height: 24px;")
        self.detail_goto_btn.clicked.connect(self._go_to_detail_file)
        header.addWidget(self.detail_goto_btn)
        close = IconButton("close", role="ghost", width=24, height=24)
        close.setStyleSheet("min-height: 24px; padding: 0;")
        close.clicked.connect(self.detail_frame.hide)
        header.addWidget(close)
        dl.addLayout(header)
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFixedHeight(_DETAIL_SCROLL_HEIGHT)
        self.detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        dl.addWidget(self.detail_scroll)
        self.detail_frame.hide()
        root.addWidget(self.detail_frame)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.clear_btn = button("Clear Completed", width=140)
        self.clear_btn.clicked.connect(self.clear_completed)
        self.clear_all_btn = button("Clear All", width=90)
        self.clear_all_btn.clicked.connect(self.clear_all)
        controls.addWidget(self.clear_btn)
        controls.addWidget(self.clear_all_btn)
        controls.addStretch(1)
        self.stop_btn = button("Stop Queue", role="danger", width=140)
        self.stop_btn.clicked.connect(self.stop_queue)
        self.start_all_btn = button("Start Queue", role="primary", width=140)
        self.start_all_btn.clicked.connect(self.toggle_queue)
        controls.addWidget(self.stop_btn)
        controls.addWidget(self.start_all_btn)
        root.addLayout(controls)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll)
        self._frame_timer = QTimer(self)
        self._frame_timer.setTimerType(Qt.PreciseTimer)
        self._frame_timer.setInterval(16)
        self._frame_timer.timeout.connect(self._animate_fill)

    # ------------------------------------------------------------------ #
    #  Rows
    # ------------------------------------------------------------------ #
    def add_task(self, description, settings=None, status="Queued", source_tab="Encoding"):
        """Adds a task row; returns its id."""
        self.empty_label.hide()
        task_id = self._next_id
        self._next_id += 1
        settings = settings or {}
        widget = QueueRow(task_id, description, status)
        widget.clicked.connect(self._show_details)
        widget.removeRequested.connect(self.remove_task)
        self.list_layout.insertWidget(self.list_layout.count() - 1, widget)
        self._rows[task_id] = {"widget": widget, "settings": settings,
                               "source_tab": source_tab, "error": None}
        self._load_thumbnail(widget, settings.get("input_file"), settings.get("thumbnail_url"))
        self._update_overall_progress()
        return task_id

    def _status(self, task_id):
        return self._rows[task_id]["widget"].status

    def _load_thumbnail(self, widget, input_file, thumbnail_url=None):
        """A row's preview frame, never decoded on the GUI thread: the app's
        already-decoded frame for the selected file, the Downloader's cached
        thumbnail for the same link, else one decoded / fetched on a worker."""
        def deliver(image):
            if image is not None and not image.isNull() and widget.task_id in self._rows:
                widget.thumb = QPixmap.fromImage(image)
                widget.update()

        if not input_file and thumbnail_url:
            cache = self.app.ytdlp_cache
            if cache and cache.get("thumb") is not None and cache["info"].get("thumbnail") == thumbnail_url:
                deliver(cache["thumb"])
                return
            run_async(lambda: pil_to_qimage(downloader.download_thumbnail(thumbnail_url)), deliver)
            return
        if not input_file:
            return
        if self.app.thumb_frames and self.app.thumb_frames_path == input_file:
            deliver(self.app.thumb_frames[0])
            return
        run_async(lambda: pil_to_qimage(extract_video_thumbnail(input_file)), deliver)

    def update_status(self, task_id, status):
        row = self._rows.get(task_id)
        if row:
            row["widget"].set_status(status)
            self._update_overall_progress()

    def _update_overall_progress(self):
        """(finished + the active job's live fraction) / total."""
        total = len(self._rows)
        if not total:
            self.progress_bar.set_value(0)
            return
        done = sum(1 for tid in self._rows if self._status(tid) in _FINISHED)
        active = self._active["fraction"] if self._active is not None else 0.0
        self.progress_bar.set_value((done + active) / total)

    def is_running(self):
        return self._is_running

    def pending_task_count(self):
        """Everything that would be lost on quit — running, paused or queued."""
        return sum(1 for tid in self._rows if self._status(tid) not in _FINISHED)

    def claims_output(self, path):
        """Whether an unfinished job will write `path`."""
        target = os.path.normcase(os.path.abspath(path))
        for tid, row in self._rows.items():
            if self._status(tid) in _FINISHED:
                continue
            other = row["settings"].get("output_path")
            if other and os.path.normcase(os.path.abspath(other)) == target:
                return True
        return False

    def on_leave(self):
        """Switching away: a completed 100% bar resets so it doesn't linger."""
        if self.progress_bar.value >= 1.0:
            self.progress_bar.set_value(0)

    def remove_task(self, task_id):
        """Removing the active row kills its process first — a process must
        never outlive its row — and continues if the queue was running."""
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
            row["widget"].hide()
            row["widget"].deleteLater()
        if task_id == self._detail_task_id:
            self.detail_frame.hide()
        if not self._rows:
            self.empty_label.show()
        self._update_overall_progress()
        if continue_with is not None:
            self._process_next(continue_with)

    def clear_completed(self):
        for task_id in [tid for tid in self._rows if self._status(tid) in _FINISHED]:
            self.remove_task(task_id)

    def clear_all(self):
        pending = self.pending_task_count()
        if pending:
            plural = "job" if pending == 1 else "jobs"
            if not ask_yes_no(self.app, "Clear the whole queue?",
                              f"{pending} unfinished {plural} would be cancelled and removed.\n\n"
                              "Clear the queue anyway?"):
                return
        self.stop_queue()
        for task_id in list(self._rows):
            self.remove_task(task_id)

    # ------------------------------------------------------------------ #
    #  Details popup
    # ------------------------------------------------------------------ #
    def _show_details(self, task_id):
        row = self._rows.get(task_id)
        if not row:
            return
        self._detail_task_id = task_id
        kind = {"Encoding": "Encode", _YTDLP: "Download"}.get(row["source_tab"], "Mux")
        self.detail_title_label.setText(f"{kind} Details")
        settings = row["settings"]
        output_path = settings.get("output_path")
        self.detail_goto_btn.setEnabled(bool(output_path and os.path.exists(output_path)))

        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 8, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        grid.setColumnMinimumWidth(0, 112)
        grid.setColumnStretch(1, 1)
        rows = []
        strip_video = bool(settings.get("strip_video"))
        strip_audio = bool(settings.get("strip_audio"))
        for key, label, fmt in _DETAIL_FIELDS:
            if key not in settings:
                continue
            if (strip_video and key in _VIDEO_DETAIL_KEYS) or (strip_audio and key in _AUDIO_DETAIL_KEYS):
                continue
            value = settings[key]
            if fmt == "time":
                value = hms(value)
            elif fmt == "bool":
                value = "Yes" if value else "No"
            rows.append((label, str(value) if value not in (None, "") else "—", False))
        if not strip_audio:
            streams = settings.get("audio_streams") or []
            for i, entry in enumerate(streams):
                bits = [entry.get("codec") or "—"]
                if entry.get("passthru"):
                    bits.append("copy")
                for k in ("bitrate", "channels", "sample_rate"):
                    if entry.get(k) and entry[k] != formats.SELECT:
                        bits.append(entry[k])
                rows.append(("Audio Stream" if len(streams) == 1 else f"Audio Stream {i + 1}",
                             " · ".join(bits), False))
        if row.get("error"):
            rows.append(("Error", row["error"], True))
        for r, (label, value, is_error) in enumerate(rows):
            key_label = QLabel(f"{label}:")
            key_label.setProperty("role", "detailKey")
            key_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            value_label = QLabel(value)
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            if is_error:
                value_label.setProperty("role", "error")
            grid.addWidget(key_label, r, 0)
            grid.addWidget(value_label, r, 1)
        grid.setRowStretch(len(rows), 1)
        self.detail_scroll.setWidget(body)
        self.detail_frame.show()

    def _go_to_detail_file(self):
        row = self._rows.get(self._detail_task_id)
        if not row:
            return
        path = os.path.abspath(row["settings"].get("output_path") or "")
        if not path or not os.path.exists(path):
            self.detail_goto_btn.setEnabled(False)
            show_message(self.app, "File Not Found",
                         "This file no longer exists at its saved location — it may have "
                         "been moved, renamed, or deleted since the job finished.")
            return
        # One command-line string: Explorer parses its own "/select,<path>".
        subprocess.Popen(f'explorer /select,"{path}"')

    # ------------------------------------------------------------------ #
    #  Start / pause / stop
    # ------------------------------------------------------------------ #
    def _set_running(self, running):
        self._is_running = running
        self.start_all_btn.setText("Pause Queue" if running else "Start Queue")

    def toggle_queue(self):
        if self._is_running:
            self.pause_queue()
        else:
            self.start_queue()

    def start_queue(self):
        """Start processing Queued tasks — or thaw a paused job in place."""
        if self._active is not None:
            active = self._active
            if active["paused"]:
                active["job"].resume()
                active["paused"] = False
                self.update_status(active["task_id"], self._running_label(active["task_id"], active))
            self._set_running(True)
            self._start_timers()
            return
        queued = [tid for tid in self._rows if self._status(tid) == "Queued"]
        if not queued:
            return
        self._set_running(True)
        self._process_next(queued)

    def pause_queue(self):
        """Freeze the active job's process in place (a real OS suspend)."""
        self._stop_timers()
        if self._active is not None and not self._active["paused"]:
            self._active["job"].suspend()
            self._active["paused"] = True
            self.update_status(self._active["task_id"], "Paused")
        self._set_running(False)

    def stop_queue(self):
        """Kill the active job (running or paused), delete its partial output,
        revert it to Queued."""
        if self._active is not None:
            task_id = self._active["task_id"]
            self._halt_active()
            if task_id in self._rows:
                self.update_status(task_id, "Queued")
        self._set_running(False)

    def shutdown(self):
        """App closing: Windows doesn't take a child process down with its
        parent, so kill the active job now."""
        self._halt_active()

    def start_task(self, task_id):
        """The do-it-now path: start at once, or run next. Returns "started",
        "next" or "paused"."""
        if self._active is not None:
            self._active["rest"].insert(0, task_id)
            return "next" if self._is_running else "paused"
        self._set_running(True)
        self._process_next([task_id])
        return "started"

    def _running_label(self, task_id, active=None):
        source = self._rows[task_id]["source_tab"]
        if source == _YTDLP:
            return (active or {}).get("stage") or _PREPARING
        return "Encoding..." if source == "Encoding" else "Muxing..."

    def _process_next(self, remaining):
        """Launch the next Queued job in `remaining` and return immediately."""
        if not remaining:
            self._active = None
            self._set_running(False)
            self._stop_timers()
            self.app.notify("All queued jobs finished.")
            return
        task_id, rest = remaining[0], list(remaining[1:])
        row = self._rows.get(task_id)
        if not row or self._status(task_id) != "Queued":
            self._process_next(rest)
            return

        self.update_status(task_id, self._running_label(task_id))
        if row["source_tab"] == _YTDLP:
            self._start_download(task_id, row, rest)
            return
        # The job's values become the ffmpeg_vars globals and its argv is
        # compiled from them here on the GUI thread — workers only ever see a
        # plain list, never the shared module state.
        ffmpeg_vars.load(row["settings"], row["source_tab"])
        final_path = os.path.abspath(ffmpeg_vars.OUTPUT_PATH)
        temp_path = partial_path(final_path)
        try:
            args = compile_command(temp_path)
        except Exception as exc:
            self._fail_task(task_id, rest, f"Couldn't build the ffmpeg command: {exc}")
            return
        print("ffmpeg:", subprocess.list2cmdline(args))
        job = FfmpegJob(
            args, final_path, temp_path,
            duration_secs=ffmpeg_vars.DURATION_SECS,
            input_file=ffmpeg_vars.INPUT_FILE,
            start_secs=ffmpeg_vars.START_SECS,
            verify_hdr_tag=uses_hdr_tonemap(),
        )
        self._active = {"task_id": task_id, "job": job, "rest": rest,
                        "paused": False, "fraction": 0.0, "stage": None}
        job.start()
        self._start_timers()

    def _start_download(self, task_id, row, rest):
        settings = row["settings"]
        plan = settings.get("download")
        if not plan or not settings.get("url") or not settings.get("output_path"):
            self._fail_task(task_id, rest, "This download is missing its link or format choice.")
            return
        job = YtDlpJob(settings["url"], plan, settings["output_path"])
        print("yt-dlp:", subprocess.list2cmdline(job.args))
        self._active = {"task_id": task_id, "job": job, "rest": rest,
                        "paused": False, "fraction": 0.0, "stage": _PREPARING}
        job.start()
        self._start_timers()

    def _start_timers(self):
        self._poll_timer.start()
        self._frame_timer.start()

    def _stop_timers(self):
        self._poll_timer.stop()
        self._frame_timer.stop()

    def _poll(self):
        """Drain the active job's events; settle it when it ends. The final
        ("progress", 1.0) usually lands in the same batch as "done", so the
        fraction is applied — and the fill snapped full — before the status
        flips, and the full bar is actually seen."""
        active = self._active
        if active is None:
            self._stop_timers()
            return
        terminal = None
        for event in active["job"].poll_events():
            if event[0] == "progress":
                active["fraction"] = event[1]
            elif event[0] == "stage":
                active["stage"] = event[1]
                if not active["paused"]:
                    self.update_status(active["task_id"], event[1])
            else:
                terminal = event
                break
        self._update_overall_progress()
        if terminal is None:
            return
        row = self._rows.get(active["task_id"])
        if row:
            row["widget"].set_fraction(1.0)
            row["widget"].repaint()
        self._stop_timers()
        if terminal[0] == "done":
            self._finish_task(active["task_id"], active["rest"])
        else:
            self._fail_task(active["task_id"], active["rest"], terminal[1])

    def _animate_fill(self):
        active = self._active
        if active is None:
            return
        row = self._rows.get(active["task_id"])
        if row:
            widget = row["widget"]
            widget.set_fraction(widget.fraction + (active["fraction"] - widget.fraction) * _EASE)

    def _halt_active(self):
        self._stop_timers()
        if self._active is not None:
            self._active["job"].stop()
            self._active = None

    def _finish_task(self, task_id, rest):
        self._active = None
        if task_id in self._rows:
            self.update_status(task_id, "Done")
        self._process_next(rest)

    def _fail_task(self, task_id, rest, reason):
        """Red row, the reason kept for the details popup, a notice queued,
        and the queue keeps moving."""
        self._active = None
        row = self._rows.get(task_id)
        if row:
            row["error"] = reason
            self.update_status(task_id, "Failed")
            name = os.path.basename((row["settings"].get("input_file") or "").replace("\\", "/")) \
                or row["settings"].get("title") or "This download"
            verb = {"Encoding": "encoded", _YTDLP: "downloaded"}.get(row["source_tab"], "muxed")
            self._error_queue.append(f"“{name}” couldn't be {verb}.\n\n{reason}")
            QTimer.singleShot(0, self._show_errors)
        self._process_next(rest)

    def _show_errors(self):
        """Failure notices one at a time — never from inside the poll, since a
        modal spins a nested loop and the poll keeps firing under it."""
        if self._error_dialog_open:
            return
        self._error_dialog_open = True
        try:
            while self._error_queue:
                show_message(self.app, "Job Failed", self._error_queue.pop(0))
        finally:
            self._error_dialog_open = False
