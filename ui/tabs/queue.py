# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""The Queue: task rows, one real ffmpeg / yt-dlp job at a time, pause (a real
OS suspend), stop, failures, the details popup and the overall progress bar.

A row is one widget with one paintEvent: draw the row, then clip to the
fill width and draw it again in `primary` — so the fill edge cuts a glyph
cleanly, both halves coming from the same renderer at the same coordinates.

Progress arrives in coarse jumps (ffmpeg reports ~2 Hz); the painted fill
eases toward the latest value every frame so it glides rather than steps."""
import math
import os
import subprocess
import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetricsF, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QScrollArea,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from core import downloader, ffmpeg_vars, formats, llamalog, power
from core.ffmpeg_build import compile_command, uses_hdr_tonemap
from core.ffmpeg_runner import FfmpegJob, partial_path
from core.utilities import extract_video_thumbnail
from core.ytdlp_runner import _STAGE_FOR_PART, _STAGE_FOR_POST, YtDlpJob
from ui import scale
from ui import theme as T
from ui.scale import px
from ui.tabs.media_tab import hms
from ui.widgets.controls import (
    Dropdown,
    _MARQUEE_GAP,
    _MARQUEE_HOLD,
    _MARQUEE_SPEED,
    IconButton,
    MarqueeGroup,
    ScaledLabel,
    button,
    button_width_for,
    draw_cross,
    ui_font,
)
from ui.widgets.dialogs import ask_yes_no, show_message
from ui.widgets.tooltip import tip
from ui.widgets.queue_controls import GAP, SearchBar, SearchToggle, SlideHost, SortDropdown, WhenDoneButton
from ui.workers import pil_to_qimage, run_async

_FINISHED = ("Done", "Failed")
_POLL_INTERVAL_MS = 100
_EASE = 0.18                 # per animation frame, toward the reported fraction
_THUMB_W, _THUMB_H = 60, 40
_ROW_H = 56
_ROW_CORNER = 8
_DETAIL_SCROLL_HEIGHT = 140
_SORTS = ["A to Z", "Z to A", "Recent", "Latest"]
_SORT_DEFAULT = _SORTS[0]
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
    ("duration_secs", "Duration", "time"),
    ("av_sync", "A/V Sync", "bool"),
    ("strip_video", "Strip Video", "bool"),
    ("gpu_enabled", "GPU Acceleration", "bool"),
    ("hdr_to_sdr", "HDR to SDR", "bool"),
    ("quality", "Quality", None),
    ("profile", "Profile", None),
    ("level", "Level", None),
    ("speed", "Speed", None),
    ("resolution", "Resolution", None),
    ("fps", "FPS", None),
    ("strip_audio", "Strip Audio", "bool"),
]
_VIDEO_DETAIL_KEYS = {"encoder", "gpu_enabled", "hdr_to_sdr", "quality", "profile", "level", "speed",
                      "resolution", "fps"}
_AUDIO_DETAIL_KEYS = set()


_INFO_FONT_PX = 11
_TITLE_CHARS = 25            # a title longer than this scrolls instead of being cut
_COL_GAP = 6
_TITLE_LEFT = 10 + _THUMB_W + 8
_STATUS_TEXTS = ("Queued", "Paused", "Done", "Failed", "Encoding...", "Muxing...", _PREPARING, "Finishing...",
                 *_STAGE_FOR_PART.values(), *_STAGE_FOR_POST.values())
_AUDIO_TEXTS = tuple(f"{codec} {ch}" for codec in ("Dolby TrueHD", "E-AC-3", "Vorbis")
                     for ch in ("1.0", "2.0", "5.1", "7.1", "9.1", "5.2", "7.2"))
_HDR_TEXTS = ("HDR10", "HLG", "SDR", "HDR", "—")
_CHANNEL_SHORT = {"Mono": "1.0", "Stereo": "2.0"}
_RES_TEXTS = ("2160p", "4320p", "1440p", "1080p60", "1080p", "720p", "480p", "—")
_NO_INFO = "—"
_columns = None              # measured once: {"time", "res", "audio", "status", "title"} reference px


def _measure_columns():
    """Each info column's width, from the widest thing it can hold (reference
    pixels), so nothing but a scrolling title is ever cut off."""
    global _columns
    if _columns is None:
        fm = QFontMetricsF(ui_font(_INFO_FONT_PX))

        def widest(texts):
            return math.ceil(max(fm.horizontalAdvance(t) for t in texts)) + 4
        _columns = {
            "time": widest(("00:00:00", "100:00:00")),
            "res": widest(_RES_TEXTS),
            "hdr": widest(_HDR_TEXTS),
            "audio": widest(_AUDIO_TEXTS),
            "status": widest(t.rstrip(".") for t in _STATUS_TEXTS),
            "title": math.ceil(fm.horizontalAdvance("n" * _TITLE_CHARS)) + 4,
        }
    return _columns


class QueueRow(QWidget):
    """One task, fully painted: thumbnail, title, length, resolution, HDR/SDR, audio
    codec + channels, status, ✕. A title past 25 characters (or too wide for its space)
    scrolls; every other segment has room for its longest value."""

    clicked = Signal(int)
    removeRequested = Signal(int)

    def __init__(self, task_id, description, status, info=None, group=None):
        super().__init__()
        self.task_id = task_id
        self.description = description          # the title
        self.info = info or {}                  # {"length": "01:00:00", "resolution": "1080p", "audio": "AAC"}
        self.status = status
        self.fraction = 0.0      # what's painted
        self.thumb = None        # QPixmap
        self._hover_x = False
        self._scrolling = False  # the title's marquee, driven by the queue's shared MarqueeGroup
        self._group = group
        if group is not None:
            group.register(self)
        scale.fixed(self, h=_ROW_H)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self._font = ui_font(_INFO_FONT_PX)
        T.theme.changed.connect(self.update)

    # -- title marquee (duck-typed as a MarqueeGroup member) -----------------
    def _title_width(self):
        return QFontMetricsF(self._font).horizontalAdvance(self.description)

    def _title_rect(self):
        """The title's box: from after the thumbnail up to the time column."""
        return QRectF(_TITLE_LEFT, 0, self._time_left() - _COL_GAP - _TITLE_LEFT, _ROW_H)

    def _overflows(self):
        return len(self.description) > _TITLE_CHARS or self._title_width() > self._title_rect().width()

    def _sweep_seconds(self):
        return (self._title_width() + _MARQUEE_GAP) / _MARQUEE_SPEED

    def _sync_scrolling(self):
        scrolling = self.isVisible() and self._overflows()
        if scrolling != self._scrolling:
            self._scrolling = scrolling
            if self._group is not None:
                self._group.invalidate()
                if scrolling:
                    self._group.reset()
                self._group.sync()

    def showEvent(self, e):
        self._sync_scrolling()

    def hideEvent(self, e):
        self._scrolling = False
        if self._group is not None:
            self._group.invalidate()
            self._group.sync()

    def resizeEvent(self, e):
        self._sync_scrolling()

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

    # -- column geometry, right to left from the ✕ ---------------------------
    def _x_rect(self):
        return QRectF(scale.ref_size(self)[0] - 38, (_ROW_H - 28) / 2, 28, 28)

    def _status_rect(self):
        w = _measure_columns()["status"]
        return QRectF(scale.ref_size(self)[0] - 38 - 6 - w, 0, w, _ROW_H)

    def _hdr_rect(self):
        w = _measure_columns()["hdr"]
        return QRectF(self._audio_rect().left() - _COL_GAP - w, 0, w, _ROW_H)

    def _audio_rect(self):
        w = _measure_columns()["audio"]
        return QRectF(self._status_rect().left() - _COL_GAP - w, 0, w, _ROW_H)

    def _res_rect(self):
        w = _measure_columns()["res"]
        return QRectF(self._hdr_rect().left() - _COL_GAP - w, 0, w, _ROW_H)

    def _time_left(self):
        return self._res_rect().left() - _COL_GAP - _measure_columns()["time"]

    def _time_rect(self):
        return QRectF(self._time_left(), 0, _measure_columns()["time"], _ROW_H)

    def mouseMoveEvent(self, e):
        over = self._x_rect().contains(scale.ref_pos(e.position()))
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
        if self._x_rect().contains(scale.ref_pos(e.position())):
            self.removeRequested.emit(self.task_id)
        else:
            self.clicked.emit(self.task_id)

    def paintEvent(self, _event):
        th = T.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        scale.begin(p)
        w = scale.ref_size(self)[0]
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
        title_rect = self._title_rect()
        cells = ((self._time_rect(), self.info.get("length") or _NO_INFO),
                 (self._res_rect(), self.info.get("resolution") or _NO_INFO),
                 (self._hdr_rect(), self.info.get("hdr") or _NO_INFO),
                 (self._audio_rect(), self.info.get("audio") or _NO_INFO))
        running = self.status not in ("Queued", "Done", "Failed")
        fm = QFontMetricsF(self._font)

        def draw_description(color):
            p.setFont(self._font)
            p.setPen(color)
            for rect, value in cells:
                p.drawText(rect, Qt.AlignVCenter | Qt.AlignHCenter, value)
            p.save()
            p.setClipRect(title_rect, Qt.IntersectClip)
            baseline = (_ROW_H + fm.ascent() - fm.descent()) / 2
            if self._scrolling and self._group is not None:
                span = self._title_width() + _MARQUEE_GAP
                travel = max(0.0, min(self._group.phase() - _MARQUEE_HOLD, span / _MARQUEE_SPEED)) * _MARQUEE_SPEED
                p.drawText(QPointF(title_rect.left() - travel, baseline), self.description)
                p.drawText(QPointF(title_rect.left() - travel + span, baseline), self.description)
            else:
                p.drawText(QPointF(title_rect.left(), baseline), self.description)
            p.restore()

        draw_description(text)
        # The fill covers thumbnail + title + info, stopping at the status
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
            k = max(_THUMB_W / pw, _THUMB_H / ph)
            target = QRectF(0, 0, pw * k, ph * k)
            target.moveCenter(thumb_rect.center())
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawPixmap(target, self.thumb, QRectF(self.thumb.rect()))
            p.restore()

        p.setFont(self._font)
        p.setPen(text)
        p.drawText(status_rect, Qt.AlignCenter, self.status.rstrip("."))
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
        scale.fixed(self, h=8)
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


class _DetailScroll(QScrollArea):
    """The details list: prefers `_DETAIL_SCROLL_HEIGHT` but gives way, so the
    panel can be squeezed (by the search row) and stretched back."""

    def sizeHint(self):
        return QSize(super().sizeHint().width(), px(_DETAIL_SCROLL_HEIGHT))

    def minimumSizeHint(self):
        return QSize(0, px(40))


class _DetailPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground)
        T.theme.changed.connect(self._restyle)
        scale.changed.connect(self._restyle)
        self._restyle()

    def _restyle(self):
        # Connected to `scale.changed`, which fires on every live-resize step
        # regardless of which tab is showing: skip the (fairly costly)
        # setStyleSheet call when the text it would set hasn't actually
        # changed, same guard `MainWindow._style` uses for the per-tab sheet.
        css = f"_DetailPanel {{ background: {T.theme.hex('panel')}; border-radius: {px(8)}px; }}"
        if css != getattr(self, "_last_css", None):
            self._last_css = css
            self.setStyleSheet(css)


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
        self._marquee = MarqueeGroup()      # every row's scrolling title loops in step
        self._sort = _SORT_DEFAULT          # one of _SORTS
        self._filter = ""

        root = QVBoxLayout(self)
        scale.margins(root, 20, 15, 20, 10)
        scale.spacing(root, 0)      # the gaps are spacers / carried by the sliding rows, so none pops in or out

        self.progress_bar = ProgressStrip()
        root.addWidget(self.progress_bar)
        scale.spacer(root, GAP)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        self.list_layout = QVBoxLayout(host)
        scale.margins(self.list_layout, 0, 0, 4, 0)
        scale.spacing(self.list_layout, 8)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(host)

        # The empty-state message lives in its own stack page, not inside
        # `list_layout` alongside real rows — a stretch on both sides of it
        # there would centre it nicely while the list is genuinely empty,
        # but that same stretch stays live once rows exist too (a plain
        # QLayout item, unaffected by any one widget's own `.hide()`),
        # pushing the whole populated list down/off-centre instead of
        # letting it anchor to the top and scroll normally. A `QStackedLayout`
        # sidesteps that: only one page is ever shown, chosen explicitly by
        # `_show_task_list`/`_show_empty_state` below, so the centring
        # stretches here can never leak into the row list's own layout.
        self.empty_label = ScaledLabel("No tasks queued yet.")
        self.empty_label.setProperty("role", "empty")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self._empty_page = QWidget()
        epl = QVBoxLayout(self._empty_page)
        epl.addStretch(1)
        epl.addWidget(self.empty_label, 0, Qt.AlignHCenter)
        epl.addStretch(1)

        list_area = self._list_area = QWidget()
        self._list_stack = QStackedLayout(list_area)
        self._list_stack.addWidget(self.scroll)
        self._list_stack.addWidget(self._empty_page)
        self._list_stack.setCurrentWidget(self._empty_page)
        root.addWidget(list_area, 1)

        # Details popup — hidden until a row is clicked; fixed height so a
        # long Encode field list scrolls instead of growing the box.
        self.detail_panel = _DetailPanel()
        dl = QVBoxLayout(self.detail_panel)
        scale.margins(dl, 10, 8, 6, 8)
        scale.spacing(dl, 4)
        header = QHBoxLayout()
        self.detail_title_label = ScaledLabel("")
        self.detail_title_label.setProperty("role", "detailTitle")
        header.addWidget(self.detail_title_label)
        header.addStretch(1)
        self.detail_goto_btn = button("Go to File", width=90, height=24)
        scale.bind_style(self.detail_goto_btn, lambda: f"min-height: {px(24)}px;")
        self.detail_goto_btn.clicked.connect(self._go_to_detail_file)
        header.addWidget(self.detail_goto_btn)
        close = IconButton("close", role="ghost", width=24, height=24)
        scale.bind_style(close, lambda: f"min-height: {px(24)}px; padding: 0;")
        close.clicked.connect(self._close_details)
        header.addWidget(close)
        dl.addLayout(header)
        self.detail_scroll = _DetailScroll()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        dl.addWidget(self.detail_scroll)
        # The host slides the panel up over the bottom of the list (and keeps it put while
        # another row is picked); it floats, placed in `_place_search`, not in the layout.
        self.detail_frame = SlideHost(self.detail_panel)
        self.detail_frame.setParent(self)

        # Floats over the list (placed in `_place_search`, not in the layout).
        self.search_bar = SearchBar()
        self.search_bar.setParent(self)
        self.search_bar.queryChanged.connect(self._set_filter)
        self.search_bar.heightChanged.connect(self._on_search_height)

        controls = QHBoxLayout()
        scale.spacing(controls, 8)
        self.clear_btn = button("Clear Completed", width=button_width_for(["Clear Completed"], padding=20))
        self.clear_btn.clicked.connect(self.clear_completed)
        self.clear_all_btn = button("Clear All", width=button_width_for(["Clear All"], padding=20))
        self.clear_all_btn.clicked.connect(self.clear_all)
        controls.addWidget(self.clear_btn)
        controls.addWidget(self.clear_all_btn)
        controls.addStretch(1)
        self.sort_menu = SortDropdown("Sort By:", _SORTS)
        self.sort_menu.set(_SORT_DEFAULT)
        self.sort_menu.picked.connect(self._set_sort)
        tip(self.sort_menu, "How the queue is ordered — and so the order it runs in. Recent puts the "
                            "newest-added task first, Latest the oldest-added.")
        controls.addWidget(self.sort_menu)
        self.search_toggle = SearchToggle()
        self.search_toggle.clicked.connect(self.search_bar.toggle_open)
        controls.addWidget(self.search_toggle)
        controls.addStretch(1)
        self.stop_btn = button("Stop Queue", role="danger", width=button_width_for(["Stop Queue"], padding=20))
        self.stop_btn.clicked.connect(self.stop_queue)
        self.start_all_btn = button("Start Queue", role="action", width=button_width_for(["Start Queue", "Pause Queue"], padding=20))
        self.start_all_btn.clicked.connect(self.toggle_queue)
        controls.addWidget(self.stop_btn)
        # Start Queue and its When Done button read as one control: almost no gap between them.
        start_group = QHBoxLayout()
        scale.spacing(start_group, 3)
        start_group.addWidget(self.start_all_btn)
        self.when_done_btn = WhenDoneButton(power.ACTIONS)
        self.when_done_btn.set(app.when_done)
        self.when_done_btn.picked.connect(self._on_when_done)
        self._retip_when_done()
        start_group.addWidget(self.when_done_btn)
        controls.addLayout(start_group)
        scale.spacer(root, GAP)
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
        self._list_stack.setCurrentWidget(self.scroll)
        task_id = self._next_id
        self._next_id += 1
        settings = settings or {}
        llamalog.get("queue").info("Task %s added (%s, %s): %s", task_id, source_tab, status, description)
        meta = self._row_meta(settings, source_tab)
        shown = {**meta, "length": hms(meta["length"]) if meta["length"] is not None else ""}
        widget = QueueRow(task_id, description, status, info=shown, group=self._marquee)
        widget.clicked.connect(self._show_details)
        widget.removeRequested.connect(self.remove_task)
        self.list_layout.insertWidget(self.list_layout.count() - 1, widget)
        self._rows[task_id] = {"widget": widget, "settings": settings, "source_tab": source_tab,
                               "error": None, "added": time.time(), "meta": meta}
        self._load_thumbnail(widget, settings.get("input_file"), settings.get("thumbnail_url"))
        self._apply_sort()
        if self._filter:
            self._apply_filter()
        self._update_overall_progress()
        return task_id

    # ------------------------------------------------------------------ #
    #  Row info: length, resolution, audio codec — as the settings will leave them
    # ------------------------------------------------------------------ #
    @staticmethod
    def _effective_length(total, start, duration):
        """Length of the output: the trim applied to the source's `total`
        seconds (`duration` 0 means to the end); None while `total` is unknown."""
        if not total:
            return None
        remaining = max(0.0, total - min(start or 0, total))
        return duration if duration and duration < remaining else remaining

    def _source_info(self, settings):
        """The probe of this task's input, when it is still the selected file
        (add_task always runs right after the tab gathered the settings)."""
        info = self.app.media_info
        if info and settings.get("input_file") and settings.get("input_file") == self.app.current_file_path:
            return info
        return {}

    def _row_meta(self, settings, source_tab):
        """`{"length": secs|None, "total": secs|None, "resolution", "hdr", "audio": text}` for the row
        and the details panel; text is "" where there is nothing to show."""
        if source_tab == _YTDLP:
            return self._download_meta(settings)
        info = self._source_info(settings)
        total = info.get("duration")
        length = self._effective_length(total, settings.get("start_secs"), settings.get("duration_secs"))
        resolution = ""
        if not settings.get("strip_video") and info.get("height"):
            resolution = f"{info['height']}p"
            target = formats.resolution_height_for(settings.get("resolution"))
            source_h = settings.get("source_height") or info["height"]
            if target and target < source_h:
                resolution = f"{target}p"
        hdr = ""
        if not settings.get("strip_video"):
            vtracks = settings.get("video_tracks") or []
            vprobed = info.get("video_streams") or []
            index = vtracks[0].get("index", 0) if vtracks and vtracks[0].get("source") == "primary" else 0
            if settings.get("hdr_to_sdr"):
                hdr = "SDR"
            elif index < len(vprobed) and vprobed[index].get("hdr_display"):
                hdr = vprobed[index]["hdr_display"]
            elif info.get("hdr") is not None:
                hdr = "HDR" if info["hdr"] else "SDR"
        audio = ""
        if not settings.get("strip_audio"):
            probed = info.get("audio_streams") or []
            codec, channels, stream = "", "", None
            if source_tab == "Encoding":
                streams = settings.get("audio_streams") or []
                entry = streams[0] if streams else {}
                codec = entry.get("codec") or ""
                codec = "" if codec == formats.SELECT else codec
                channels = entry.get("channels") or ""
                if entry.get("source") == "primary" and entry.get("index", 0) < len(probed):
                    stream = probed[entry["index"]]
            else:
                tracks = settings.get("audio_tracks") or []
                first = tracks[0] if tracks else None
                if first and first.get("source") == "primary" and first.get("index", 0) < len(probed):
                    stream = probed[first["index"]]
                elif not tracks:
                    stream = probed[0] if probed else None
                    codec = info.get("audio") or ""
            if stream:
                codec = codec or stream.get("codec") or ""
            if not channels or channels == formats.SELECT:
                channels = (stream or {}).get("channels_display") or ""
            channels = _CHANNEL_SHORT.get(channels, channels)
            audio = f"{codec} {channels}".strip() if codec else ""
        return {"length": length, "total": total, "resolution": resolution, "hdr": hdr, "audio": audio}

    def _download_meta(self, settings):
        cache = self.app.ytdlp_cache or {}
        total = None
        if cache.get("url") == settings.get("url"):
            total = (cache.get("info") or {}).get("duration")
        plan = settings.get("download") or {}
        total = total or ((plan.get("post") or {}).get("media_secs")) or None
        mode = settings.get("mode")
        quality = "" if mode == downloader.MODE_AUDIO else (settings.get("quality") or "")
        resolution = quality.replace(" HDR", "")
        hdr = "" if not quality or quality == downloader.BEST_QUALITY else ("HDR" if "HDR" in quality else "SDR")
        if resolution == downloader.BEST_QUALITY:
            resolution = "Best"
        if mode == downloader.MODE_VIDEO:
            audio = ""
        else:
            audio = settings.get("video_codec") if mode == downloader.MODE_AUDIO else settings.get("audio_codec")
        audio = "Auto" if audio == downloader.BEST_CODEC else (audio or "")
        return {"length": total, "total": total, "resolution": resolution, "hdr": hdr, "audio": audio}

    def _status(self, task_id):
        return self._rows[task_id]["widget"].status

    def _load_thumbnail(self, widget, input_file, thumbnail_url=None):
        """A row's preview frame, never decoded on the GUI thread: the app's
        already-decoded frame for the selected file, the Downloader's cached
        thumbnail for the same link, else one decoded / fetched on a worker."""
        def deliver(image):
            if image is not None and not image.isNull() and widget.task_id in self._rows:
                # Only as big as it can be drawn (the 60x40 slot at up to 4x), not the whole
                # frame: a 4K preview frame is 33MB.
                if image.width() > _THUMB_W * 4 and image.height() > _THUMB_H * 4:
                    image = image.scaled(_THUMB_W * 4, _THUMB_H * 4,
                                         Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
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
        """Switching away: a completed 100% bar resets so it doesn't linger,
        and the details popup (if open) closes — coming back to Queue always
        starts with it hidden rather than showing a stale task's details."""
        if self.progress_bar.value >= 1.0:
            self.progress_bar.set_value(0)
        self.detail_frame.hide()
        self._detail_task_id = None

    def remove_task(self, task_id):
        """Removing the active row kills its process first — a process must
        never outlive its row — and continues if the queue was running."""
        continue_with = None
        llamalog.get("queue").info("Task %s removed", task_id)
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
        if row:
            self._marquee.unregister(row["widget"])
        if not self._rows:
            self.empty_label.setText("No tasks queued yet.")
            self._list_stack.setCurrentWidget(self._empty_page)
        elif self._filter:
            self._apply_filter()
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
    #  Sorting and searching
    # ------------------------------------------------------------------ #
    def _set_sort(self, choice):
        self._sort = choice
        llamalog.get("queue").info("Queue sort: %s", choice)
        self._apply_sort()

    def _on_when_done(self, action):
        """The queue's own door to Settings' When Done: same value, kept in step both ways."""
        self.app.when_done = action
        settings = self.app.tabs.get("Settings")
        if settings is not None:
            settings.when_done_menu.set(action)
            settings.autosave()
        self._retip_when_done()

    def _retip_when_done(self):
        tip(self.when_done_btn, f"When Done: {self.app.when_done}\nWhat happens once the queue has finished")

    def on_enter(self):
        """Settings may have changed When Done while this tab was away."""
        self.when_done_btn.set(self.app.when_done)
        self._retip_when_done()

    def _apply_sort(self):
        """Puts the rows — and the order the queue will run them in — into the
        chosen order: by title (A to Z / Z to A) or by time added (Recent: newest
        first, Latest: oldest first). Stable, so equal titles keep their added order."""
        by_time = sorted(self._rows, key=lambda tid: (self._rows[tid]["added"], tid))
        if self._sort == "Recent":
            order = by_time[::-1]
        elif self._sort == "Latest":
            order = by_time
        else:
            order = sorted(by_time, key=lambda tid: self._rows[tid]["widget"].description.casefold(),
                           reverse=self._sort == "Z to A")
        self._rows = {tid: self._rows[tid] for tid in order}
        for i, tid in enumerate(order):
            self.list_layout.insertWidget(i, self._rows[tid]["widget"])
        if self._active is not None:
            position = {tid: i for i, tid in enumerate(order)}
            self._active["rest"].sort(key=lambda tid: position.get(tid, len(position)))

    def _place_search(self):
        """The floating overlays: the details panel over the list's bottom edge, and the search row
        (the list's width) just above the bottom buttons."""
        row = self.search_bar.sizeHint().height()
        area = self._list_area
        self.detail_frame.set_anchor(area.x(), area.y() + area.height(), area.width())
        self.detail_frame.raise_() if self.detail_frame.isVisible() else None
        self.search_bar.setGeometry(area.x(), self.clear_btn.y() - scale.px(GAP) - row, area.width(), row)
        self.search_bar.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_search()
        QTimer.singleShot(0, self._place_search)      # once the layout has settled

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._place_search)

    def _on_search_height(self, height):
        """The search row floats over the list; only an open details panel gives it room
        (its bottom edge moves up, its top edge stays put)."""
        self._place_search()
        self.detail_frame.set_inset(height)

    def _set_filter(self, text):
        self._filter = text.strip().casefold()
        self._apply_filter()

    def _apply_filter(self):
        """Hides the rows whose title lacks the search text; says so when none match."""
        shown = 0
        for tid, row in self._rows.items():
            match = self._filter in row["widget"].description.casefold()
            row["widget"].setVisible(match)
            shown += match
        if not self._rows:
            return
        self.empty_label.setText("No matching tasks." if self._filter and not shown else "No tasks queued yet.")
        self._list_stack.setCurrentWidget(self.scroll if shown else self._empty_page)

    # ------------------------------------------------------------------ #
    #  Details popup
    # ------------------------------------------------------------------ #
    def _close_details(self):
        self.detail_frame.slide_closed()
        self._detail_task_id = None

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
        scale.margins(grid, 0, 0, 8, 0)
        scale.grid_spacing(grid, 8, 2)
        scale.bind(grid, lambda: grid.setColumnMinimumWidth(0, px(112)))
        grid.setColumnStretch(1, 1)
        rows = []
        strip_video = bool(settings.get("strip_video"))
        strip_audio = bool(settings.get("strip_audio"))
        is_download = row["source_tab"] == _YTDLP
        meta = row.get("meta") or {}
        length = meta.get("length")
        # "from the start, to the end of the file" is no trim at all, so Start Time is left out.
        whole_file = not settings.get("start_secs") and (
            not settings.get("duration_secs") or (meta.get("total") and settings["duration_secs"] >= meta["total"]))
        for key, label, fmt in _DETAIL_FIELDS:
            if key not in settings:
                continue
            if key == "start_secs" and whole_file:
                continue
            if (strip_video and key in _VIDEO_DETAIL_KEYS) or (strip_audio and key in _AUDIO_DETAIL_KEYS):
                continue
            # "quality" means two unrelated things depending on who queued
            # the task: Encoding's CRF/qscale value vs. the Downloader's own
            # resolution pick (DownloaderTab's dropdown is itself labeled
            # "Resolution:" — see its own module docstring). Same settings
            # key, so this is the one place that has to tell them apart
            # rather than the field list itself, which has no per-task-kind
            # branching otherwise.
            if key == "quality" and is_download:
                label = "Resolution"
            value = settings[key]
            if key == "duration_secs":
                value = length      # always how long the output is, never the raw 00:00:00 "to the end"
                if value is None:
                    rows.append((label, "—", False))
                    continue
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
        # video_tracks/audio_tracks (Muxing only -- see MuxingTab._track_args)
        # each carry every *checked* track for that kind, so a Mux task shows
        # one row per included track rather than a single "Video Track: ..."
        # value the way the old single-track dropdown did.
        for kind, key, strip in (("Video", "video_tracks", strip_video), ("Audio", "audio_tracks", strip_audio)):
            if key not in settings or strip:
                continue
            tracks = settings.get(key) or []
            for i, entry in enumerate(tracks):
                where = ("Source" if entry.get("source") == "primary"
                         else os.path.basename((entry.get("file") or "").replace("\\", "/")))
                label = f"{kind} Track" if len(tracks) == 1 else f"{kind} Track {i + 1}"
                rows.append((label, f"Track {entry.get('index', 0) + 1}  ·  {where}", False))
        if row.get("error"):
            rows.append(("Error", row["error"], True))
        for r, (label, value, is_error) in enumerate(rows):
            key_label = ScaledLabel(f"{label}:")
            key_label.setProperty("role", "detailKey")
            key_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            value_label = ScaledLabel(value)
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            if is_error:
                value_label.setProperty("role", "error")
            grid.addWidget(key_label, r, 0)
            grid.addWidget(value_label, r, 1)
        grid.setRowStretch(len(rows), 1)
        self.detail_scroll.setWidget(body)
        self.detail_frame.slide_open()      # rises once; picking another row while open just swaps the contents

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
                if not active["job"].resume():
                    llamalog.get("queue").warning("Task %s: the job's process could not be resumed", active["task_id"])
                active["paused"] = False
                self.update_status(active["task_id"], self._running_label(active["task_id"], active))
            self._set_running(True)
            self._start_timers()
            return
        queued = [tid for tid in self._rows if self._status(tid) == "Queued"]
        if not queued:
            return
        llamalog.get("queue").info("Queue started: %d task(s) queued", len(queued))
        self._set_running(True)
        self._process_next(queued)

    def pause_queue(self):
        """Freeze the active job's process in place (a real OS suspend)."""
        llamalog.get("queue").info("Queue paused")
        self._stop_timers()
        if self._active is not None and not self._active["paused"]:
            if not self._active["job"].suspend():
                llamalog.get("queue").warning("Task %s: the job's process could not be suspended", self._active["task_id"])
            self._active["paused"] = True
            self.update_status(self._active["task_id"], "Paused")
        self._set_running(False)

    def stop_queue(self):
        """Kill the active job (running or paused), delete its partial output,
        revert it to Queued."""
        llamalog.get("queue").info("Queue stopped")
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
            llamalog.get("queue").info("All queued jobs finished")
            self.app.notify("All queued jobs finished.")
            QTimer.singleShot(0, self._run_when_done)
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
            args = compile_command(temp_path, loglevel=llamalog.ffmpeg_loglevel())
        except Exception as exc:
            llamalog.get("queue").exception("Couldn't build the ffmpeg command for task %s", task_id)
            self._fail_task(task_id, rest, f"Couldn't build the ffmpeg command: {exc}")
            return
        job = FfmpegJob(
            args, final_path, temp_path,
            duration_secs=ffmpeg_vars.DURATION_SECS,
            input_file=ffmpeg_vars.INPUT_FILE,
            start_secs=ffmpeg_vars.START_SECS,
            verify_hdr_tag=uses_hdr_tonemap(),
            priority=self.app.priority_level,
        )
        self._active = {"task_id": task_id, "job": job, "rest": rest,
                        "paused": False, "fraction": 0.0, "stage": None}
        job.start()
        self._start_timers()

    def _start_download(self, task_id, row, rest):
        settings = row["settings"]
        plan = settings.get("download")
        if not plan or not settings.get("url") or not settings.get("output_path"):
            llamalog.get("queue").warning("Task %s has no link, format or output path; not started", task_id)
            self._fail_task(task_id, rest, "This download is missing its link or format choice.")
            return
        job = YtDlpJob(settings["url"], plan, settings["output_path"],
                       priority=self.app.priority_level)
        self._active = {"task_id": task_id, "job": job, "rest": rest,
                        "paused": False, "fraction": 0.0, "stage": _PREPARING}
        job.start()
        self._start_timers()

    def apply_priority(self):
        """Settings' Priority Level changed: move the running job (if any) to
        it. Jobs started later read `app.priority_level` themselves."""
        if self._active is not None:
            self._active["job"].set_priority(self.app.priority_level)

    def _run_when_done(self):
        """Settings' "When Done" — held back while a failure notice is still
        up (its modal would otherwise stack under the countdown) and dropped if
        the user queued more work in the meantime."""
        if self._error_dialog_open or self._error_queue:
            QTimer.singleShot(500, self._run_when_done)
            return
        if self._active is None and not self.pending_task_count():
            self.app.perform_when_done()

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
        llamalog.get("queue").info("Task %s finished (Done)", task_id)
        self._active = None
        if task_id in self._rows:
            self.update_status(task_id, "Done")
        self._process_next(rest)

    def _fail_task(self, task_id, rest, reason):
        """Red row, the reason kept for the details popup, a notice queued,
        and the queue keeps moving."""
        llamalog.get("queue").info("Task %s failed", task_id)
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
