# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Downloader: a link's video (or just its audio), through the queue. A link is pasted, typed or
dropped on the preview box; Fetch runs `yt-dlp -J` off the GUI thread, and the result drives
every dropdown. One constraint pass (`_sync_controls`): Mode -> Video Codec -> Resolution ->
(Audio Codec) -> Format, each offering only what the video delivers without re-encoding.
"Resolution" is internally `quality_menu` / "quality". Queueing hands `resolve()`'s plan to the
queue as `download`."""
import os
import re

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication, QFileDialog, QVBoxLayout, QWidget

from core import downloader, naming
from ui import scale
from ui.scale import fpx, px
from ui.tabs.media_tab import hrow, set_line_text
from ui.widgets.controls import button, field_label, labeled, set_enabled
from ui.widgets.dropdown import Dropdown, NO_OPTION
from ui.widgets.marquee import MarqueeLabel
from ui.widgets.text import ScaledLabel, ScaledLineEdit
from ui.widgets.toggles import SegmentedButton
from ui.widgets.dialogs import confirm_output_path, show_message
from ui.widgets.panels import BorderedFrame
from ui.widgets.tooltip import tip
from ui.tips import (
    AUDIO_CODEC_TIPS,
    AUDIO_FORMAT_TIPS,
    BEST_AUDIO_CODEC_TIP,
    BEST_VIDEO_CODEC_TIP,
    CONTAINER_TIPS,
    VIDEO_CODEC_TIPS,
)

_TAB = "Downloader"
_MODE_TIP = "Video Only / Audio Only strip the other track entirely; Video + Audio keeps both."


def _codec_tip(value, table, best_tip):
    """A codec dropdown's tip: the codec's blurb, the "Best Available" blurb, or nothing."""
    if value == downloader.BEST_CODEC:
        return best_tip
    return table.get(value, "")
_KNOWN_EXTS = set(downloader.VIDEO_CONTAINERS) | set(downloader.AUDIO_CONVERSIONS) | {
    ".webm", ".m4a", ".mp4", ".mkv", ".ogg", ".mp3", ".aac", ".flv", ".3gp", ".mov"}
_URL_RE = re.compile(r"^https?://\S+$")
_PLACEHOLDER = "Paste a link above then press Fetch."


def _human_size(num_bytes):
    if not num_bytes:
        return ""
    mb = num_bytes / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    return f"{mb:.1f} MB" if mb < 10 else f"{mb:.0f} MB"


def _hms(total_seconds):
    total_seconds = int(total_seconds or 0)
    hours, rest = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def _dropped_link(mime):
    """The one http(s) link a drag carries, or None."""
    text = ""
    if mime.hasText():
        text = mime.text()
    elif mime.hasUrls() and len(mime.urls()) == 1 and not mime.urls()[0].isLocalFile():
        text = mime.urls()[0].toString()
    text = (text or "").strip()
    return text if _URL_RE.match(text) else None


class _Thumbnail(QWidget):
    """The fetched thumbnail, fitted and centred with rounded corners."""

    def __init__(self):
        super().__init__()
        self.pixmap = None

    def set_image(self, image):
        self.pixmap = QPixmap.fromImage(image) if image is not None and not image.isNull() else None
        self.update()

    def paintEvent(self, _event):
        if self.pixmap is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        pw, ph = self.pixmap.width(), self.pixmap.height()
        k = min(self.width() / pw, self.height() / ph)
        target = QRectF(0, 0, pw * k, ph * k)
        target.moveCenter(QRectF(self.rect()).center())
        clip = QPainterPath()
        clip.addRoundedRect(target, fpx(6), fpx(6))
        p.setClipPath(clip)
        p.drawPixmap(target, self.pixmap, QRectF(self.pixmap.rect()))


class _LinkDropFrame(BorderedFrame):
    """The preview box — accepts a dragged link, and nothing else."""

    def __init__(self, on_link):
        super().__init__(color_key="secondary")     # matches Muxing/Encoding's DropBox
        self._on_link = on_link
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if _dropped_link(e.mimeData()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        link = _dropped_link(e.mimeData())
        if link:
            self._on_link(link)


class DownloaderTab(QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self._ready = False
        self._url = None
        self._info = None
        # The path the last autofill wrote (None once the user Browses).
        self._auto_output = None
        self._fmts = []
        self._thumb = None
        self._plan = None
        self._last_mode = None

        root = QVBoxLayout(self)
        scale.margins(root, 10, 5, 10, 4)
        root.setSpacing(0)
        self._deno_missing = False

        # Deno warning — only while the startup check says it's missing.
        self.deno_banner = ScaledLabel(
            "⚠  Deno wasn't found — YouTube downloads may be limited or fail. Reinstall LlamaMXD.")
        self.deno_banner.setProperty("role", "warn")
        self.deno_banner.hide()
        root.addWidget(self.deno_banner)
        self._banner_gap = root.count()
        root.addSpacing(0)
        scale.bind(self, self._apply_banner_gap)

        url_row, ul = hrow(spacing=5, align_bottom=False)
        self.url_entry = ScaledLineEdit()
        self.url_entry.setPlaceholderText("Paste a video link here...")
        scale.fixed(self.url_entry, h=28)
        self.url_entry.returnPressed.connect(self.fetch)
        ul.addWidget(self.url_entry, 1)
        self.paste_btn = button("Paste", role="queue", width=70)
        self.paste_btn.clicked.connect(self.paste_and_fetch)
        ul.addWidget(self.paste_btn)
        self.fetch_btn = button("Fetch", role="action", width=80)
        self.fetch_btn.clicked.connect(self.fetch)
        ul.addWidget(self.fetch_btn)
        root.addWidget(url_row)
        scale.spacer(root, 6)

        # Preview: the bordered placeholder, then thumbnail + title + meta.
        self.preview_frame = _LinkDropFrame(self._on_link_drop)
        pl = QVBoxLayout(self.preview_frame)
        scale.margins(pl, 12, 8, 12, 8)
        scale.spacing(pl, 4)
        self.placeholder_label = ScaledLabel(_PLACEHOLDER)
        # An instance-level rule, as on DropBox's prompt: a plain setFont loses to the next
        # polish while the tab is hidden.
        self.placeholder_label.setStyleSheet("font-size: 14px;")
        self.placeholder_label.setAlignment(Qt.AlignCenter)
        pl.addWidget(self.placeholder_label, 1)
        self.thumb_view = _Thumbnail()
        self.thumb_view.hide()
        pl.addWidget(self.thumb_view, 1)
        self.title_label = MarqueeLabel("", pixel_size=13, bold=True)
        self.title_label.hide()
        pl.addWidget(self.title_label)
        self.meta_label = ScaledLabel("")
        self.meta_label.setProperty("role", "meta")
        self.meta_label.hide()
        pl.addWidget(self.meta_label)
        root.addWidget(self.preview_frame, 1)
        scale.spacer(root, 10)

        self.mode_label = field_label("Mode:")
        self.mode_switch = SegmentedButton(downloader.MODES, current=downloader.MODE_AV)
        self.mode_switch.changed.connect(self._on_control_change)
        tip(self.mode_switch, _MODE_TIP)
        mode_box = QWidget()
        ml = QVBoxLayout(mode_box)
        ml.setContentsMargins(0, 0, 0, 0)
        scale.spacing(ml, 1)
        ml.addWidget(self.mode_label)
        ml.addWidget(self.mode_switch, 0, Qt.AlignLeft)
        root.addWidget(mode_box)
        scale.spacer(root, 4)

        options, ol = hrow(spacing=10)
        self.codec_menu = Dropdown([downloader.BEST_CODEC], width=132)
        box, self.codec_label = labeled("Video Codec:", self.codec_menu)
        ol.addWidget(box)
        # Video + Audio only — shown before Resolution (see _show_audio_picker).
        self.audio_menu = Dropdown([downloader.BEST_CODEC], width=132)
        self.audio_box, self.audio_label = labeled("Audio Codec:", self.audio_menu)
        self.audio_box.hide()
        ol.addWidget(self.audio_box)
        self.quality_menu = Dropdown([downloader.BEST_QUALITY], width=120)
        box, self.quality_label = labeled("Resolution:", self.quality_menu)
        ol.addWidget(box)
        self.format_menu = Dropdown([".mp4"], width=96)
        box, self.format_label = labeled("Video Format:", self.format_menu)
        ol.addWidget(box)
        for menu in (self.codec_menu, self.audio_menu, self.quality_menu, self.format_menu):
            menu.picked.connect(self._on_control_change)
        self.size_label = ScaledLabel("")
        self.size_label.setProperty("role", "meta")
        ol.addWidget(self.size_label, 0, Qt.AlignBottom)
        root.addWidget(options)
        scale.spacer(root, 11)   # as above Muxing / Encoding's save field

        save, sl = hrow(spacing=6, align_bottom=False)
        self.save_entry = ScaledLineEdit()
        self.save_entry.setPlaceholderText("Save file as...")
        scale.fixed(self.save_entry, h=28)
        set_line_text(self.save_entry, app.downloader_default_location())
        sl.addWidget(self.save_entry, 1)
        self.browse_save_btn = button("Browse", width=80)
        self.browse_save_btn.clicked.connect(self.select_save_location)
        sl.addWidget(self.browse_save_btn)
        root.addWidget(save)
        scale.spacer(root, 10)

        actions, al = hrow(spacing=8, align_bottom=False)
        self.queue_btn = button("Queue Job", role="queue")
        self.queue_btn.clicked.connect(self.add_to_queue)
        self.download_btn = button("Download", role="action")
        self.download_btn.clicked.connect(self.download_now)
        al.addWidget(self.queue_btn, 1)
        al.addWidget(self.download_btn, 1)
        root.addWidget(actions)

        self.set_deno_missing(app.deno_missing)
        self._sync_controls()
        self._ready = True

    def set_deno_missing(self, missing):
        self._deno_missing = bool(missing)
        self.deno_banner.setVisible(self._deno_missing)
        self._apply_banner_gap()

    def _apply_banner_gap(self):
        """The gap under the Deno banner: 6 reference px while it's showing."""
        layout = self.layout()
        item = layout.itemAt(self._banner_gap)
        if item is not None and item.spacerItem() is not None:
            item.spacerItem().changeSize(0, px(6) if self._deno_missing else 0)
            layout.invalidate()

    # ------------------------------------------------------------------ #
    #  Fetch
    # ------------------------------------------------------------------ #
    def paste_and_fetch(self):
        text = (QApplication.clipboard().text() or "").strip()
        if text:
            self.url_entry.setText(text)
            self.fetch()

    def _on_link_drop(self, link):
        self.url_entry.setText(link)
        self.fetch()

    def fetch(self):
        url = self.url_entry.text().strip()
        if not url:
            show_message(self.app, "No Link", "Paste a video link first, then press Fetch.")
            return
        self.fetch_btn.setText("Fetching...")
        self.fetch_btn.setEnabled(False)
        if not self._info:
            self.placeholder_label.setText("Fetching video info...")
        self.app.fetch_ytdlp_info(url)

    def on_ytdlp_info(self, url, info, error, thumb):
        """A fetch landed (on the GUI thread)."""
        self.fetch_btn.setText("Fetch")
        self.fetch_btn.setEnabled(True)
        if error:
            if not self._info:
                self.placeholder_label.setText(_PLACEHOLDER)
            show_message(self.app, "Couldn't Fetch Link", error)
            return
        self._apply_info(url, info, thumb)
        self._autofill_output_path()

    def _apply_info(self, url, info, thumb):
        """Adopt a fetched video: every pick resets to its best default."""
        self._url, self._info, self._thumb = url, info, thumb
        self._fmts = downloader.parse_formats(info)
        was_ready, self._ready = self._ready, False
        try:
            modes = downloader.modes_for(self._fmts)
            self.mode_switch.set(modes[0] if modes else downloader.MODE_AV)
            self.codec_menu.set(downloader.BEST_CODEC)
            self.quality_menu.set(downloader.BEST_QUALITY)
            self.format_menu.set(".mp4")
            self.audio_menu.set(downloader.BEST_CODEC)
            self._last_mode = None
            self._sync_controls()
        finally:
            self._ready = was_ready
        self.placeholder_label.hide()
        self.thumb_view.set_image(thumb)
        self.thumb_view.show()
        self.title_label.setText(info.get("title") or "Untitled")
        self.title_label.show()
        bits = [b for b in (info.get("uploader") or info.get("channel"),
                            _hms(info.get("duration")) if info.get("duration") else "") if b]
        self.meta_label.setText("  ·  ".join(bits))
        self.meta_label.show()

    # ------------------------------------------------------------------ #
    #  The single constraint pass
    # ------------------------------------------------------------------ #
    def _on_control_change(self, *_):
        self._sync_controls()

    def _sync_controls(self, *_):
        """Nothing fetched: everything disabled. Otherwise Mode -> Video Codec -> Resolution ->
        (Video + Audio: Audio Codec) -> Format, or for Audio Only Format -> Resolution. The plan
        drives the size estimate and the extension. A snap toasts unless a Mode switch caused
        it."""
        has_info = bool(self._fmts)
        for widget, label in ((self.mode_switch, self.mode_label), (self.codec_menu, self.codec_label),
                              (self.quality_menu, self.quality_label), (self.format_menu, self.format_label),
                              (self.audio_menu, self.audio_label)):
            set_enabled(widget, label, has_info)
        self.queue_btn.setEnabled(has_info)
        self.download_btn.setEnabled(has_info)
        if not has_info:
            for menu in (self.codec_menu, self.audio_menu, self.quality_menu, self.format_menu):
                menu.set(NO_OPTION)
            self._plan = None
            self.size_label.setText("")
            return

        fmts = self._fmts
        modes = downloader.modes_for(fmts)
        if self.mode_switch.value() not in modes and modes:
            self.mode_switch.set(modes[0])
        mode = self.mode_switch.value()
        mode_changed = self._last_mode is not None and mode != self._last_mode
        announce = self._ready and not mode_changed
        self._last_mode = mode
        self._show_audio_picker(mode)

        codecs = downloader.codecs_for(fmts, mode)
        self._retarget(self.codec_menu, codecs, downloader.BEST_CODEC, "Video Codec" if announce else None)
        codec = self.codec_menu.value()
        codec_table = AUDIO_CODEC_TIPS if mode == downloader.MODE_AUDIO else VIDEO_CODEC_TIPS
        codec_best_tip = BEST_AUDIO_CODEC_TIP if mode == downloader.MODE_AUDIO else BEST_VIDEO_CODEC_TIP
        tip(self.codec_menu, _codec_tip(codec, codec_table, codec_best_tip))

        audio_codec = downloader.BEST_CODEC
        if mode == downloader.MODE_AUDIO:
            allowed = downloader.formats_for(fmts, mode, codec, None)
            self._retarget(self.format_menu, allowed, downloader.default_format(mode, allowed),
                           "Audio Format" if announce else None)
            qualities = downloader.qualities_for(fmts, mode, codec, self.format_menu.value())
            self._retarget(self.quality_menu, qualities, qualities[0] if qualities else None,
                           "Bitrate" if announce else None)
        else:
            qualities = downloader.qualities_for(fmts, mode, codec)
            self._retarget(self.quality_menu, qualities, downloader.BEST_QUALITY,
                           "Resolution" if announce else None)
            quality = self.quality_menu.value()
            if mode == downloader.MODE_AV:
                audio_codecs = downloader.audio_codecs_for(fmts, mode, codec, quality)
                self._retarget(self.audio_menu, audio_codecs, downloader.BEST_CODEC,
                               "Audio Codec" if announce else None)
                set_enabled(self.audio_menu, self.audio_label, bool(audio_codecs))
                tip(self.audio_menu, _codec_tip(self.audio_menu.value(), AUDIO_CODEC_TIPS, BEST_AUDIO_CODEC_TIP))
                audio_codec = self._menu_value(self.audio_menu) or downloader.BEST_CODEC
            allowed = downloader.formats_for(fmts, mode, codec, quality, audio_codec)
            self._retarget(self.format_menu, allowed, downloader.default_format(mode, allowed),
                           "Video Format" if announce else None)
        set_enabled(self.quality_menu, self.quality_label, bool(qualities))
        set_enabled(self.format_menu, self.format_label, bool(allowed))
        format_table = AUDIO_FORMAT_TIPS if mode == downloader.MODE_AUDIO else CONTAINER_TIPS
        tip(self.format_menu, format_table.get(self.format_menu.value(), ""))

        self._plan = downloader.resolve(
            fmts, mode, codec, self._menu_value(self.quality_menu), self._menu_value(self.format_menu),
            (self._info or {}).get("duration") or 0, audio_codec=audio_codec,
        )
        if self._plan:
            size = sum(p["size"] for p in self._plan["parts"])
            if self._plan["post"] and self._plan["post"]["kind"] == "convert":
                size = self._plan["post"]["expected_bytes"]
            text = _human_size(size)
            self.size_label.setText(f"≈ {text}" if text else "")
            self._apply_output_extension(self._plan["ext"])
        else:
            self.size_label.setText("")

    def _show_audio_picker(self, mode):
        self.audio_box.setVisible(mode == downloader.MODE_AV)
        audio_only = mode == downloader.MODE_AUDIO
        self.format_label.setText("Audio Format:" if audio_only else "Video Format:")
        self.quality_label.setText("Bitrate:" if audio_only else "Resolution:")

    def _retarget(self, menu, values, default, what=None):
        lost = menu.retarget(values or [NO_OPTION], default if values else None)
        if what and lost and values:
            self.app.notify(f"{what} switched to {menu.value()} — {lost} isn't available for this pick.",
                            go_to_queue=False)

    @staticmethod
    def _menu_value(menu):
        value = menu.value()
        return None if value == NO_OPTION else value

    # ------------------------------------------------------------------ #
    #  Output path
    # ------------------------------------------------------------------ #
    def _current_directory(self):
        current = self.save_entry.text().strip().replace("\\", "/")
        _root, ext = os.path.splitext(current)
        directory = os.path.dirname(current) if ext.lower() in _KNOWN_EXTS else current
        return directory or self.app.downloader_default_location() or ""

    def has_fetched(self):
        return bool(self._info)

    def refresh_default_location(self):
        """Adopt Settings' default folder while nothing is fetched; afterwards only Browse or
        the fetch's autofill touch the field."""
        if not self._info:
            set_line_text(self.save_entry, self.app.downloader_default_location())

    def _name_info(self):
        """The fetched info with a file-name-safe title (`safe_stem`'s look-alikes)."""
        info = dict(self._info or {})
        info["title"] = downloader.safe_stem(info["title"]) if info.get("title") else ""
        return info

    def _default_stem(self):
        """The file name from the naming format: `{source}` is the site, `{title}` the video's;
        queue-time tokens stay literal until queueing."""
        info = self._name_info()
        return naming.render_live(self.app.naming_template, naming.download_live_values(info),
                                  fallback=info["title"] or "download")

    def _autofill_output_path(self):
        if not self._info:
            return
        ext = self._plan["ext"] if self._plan else ".mp4"
        suggested = os.path.normpath(os.path.join(self._current_directory(), self._default_stem() + ext))
        set_line_text(self.save_entry, suggested)
        self._auto_output = suggested

    def refresh_auto_output(self):
        """Re-derive the suggested name, only while the field holds the autofill."""
        if not self._info or not self._auto_output:
            return
        typed = os.path.splitext(self.save_entry.text().strip())[0]
        if typed == os.path.splitext(self._auto_output)[0]:
            self._autofill_output_path()

    def _resolve_output_tokens(self, settings):
        """Fill the queue-time tokens from this download's settings."""
        path = settings.get("output_path") or ""
        if "{" in os.path.basename(path):
            values = naming.download_queue_values(self._name_info(), settings)
            settings["output_path"] = naming.resolve_path(path, values)

    def _apply_output_extension(self, ext):
        current = self.save_entry.text().strip()
        root, old = os.path.splitext(current)
        if old and old.lower() in _KNOWN_EXTS and old.lower() != ext.lower():
            set_line_text(self.save_entry, root + ext)

    def select_save_location(self):
        ext = self._plan["ext"] if self._plan else ".mp4"
        stem = self._default_stem() if self._info else "download"
        path, _ = QFileDialog.getSaveFileName(
            self, "Select Output File", os.path.join(self._current_directory(), stem + ext),
            f"{ext.lstrip('.').upper()} File (*{ext});;All Files (*.*)",
        )
        if path:
            set_line_text(self.save_entry, os.path.normpath(path))
            self._auto_output = None
            self._sync_controls()

    # ------------------------------------------------------------------ #
    #  Settings / validation / queue
    # ------------------------------------------------------------------ #
    def _gather_settings(self):
        info = self._info or {}
        settings = {
            "url": self._url or self.url_entry.text().strip(),
            "title": info.get("title") or "",
            "thumbnail_url": info.get("thumbnail") or "",
            "output_path": self.save_entry.text().strip(),
            "output_format": self._menu_value(self.format_menu) or "",
            "mode": self.mode_switch.value(),
            "video_codec": self.codec_menu.value(),
            "quality": self._menu_value(self.quality_menu) or "",
            "download": self._plan,
        }
        if self.mode_switch.value() == downloader.MODE_AV:
            settings["audio_codec"] = self._menu_value(self.audio_menu) or downloader.BEST_CODEC
        return settings

    def _validate_settings(self, settings):
        if not self._info or not settings["download"]:
            show_message(self.app, "Nothing Fetched", "Paste a video link and press Fetch before downloading.")
            return False
        if self.url_entry.text().strip() != self._url:
            show_message(self.app, "Link Changed",
                         "The link was edited after it was fetched. Press Fetch again so the "
                         "download matches what's in the box.")
            return False
        if not settings["output_path"]:
            show_message(self.app, "No Save Location",
                         "Choose where the download should be saved. Use Browse, or set a "
                         "default save location on the Settings tab.")
            return False
        queue_tab = self.app.tabs.get("Queue")
        claimed = bool(queue_tab and queue_tab.claims_output(settings["output_path"]))
        return confirm_output_path(self.app, settings["output_path"], None, claimed)

    @staticmethod
    def _describe(settings):
        """The queue row's title: the output file's own name (its other columns come from the
        settings)."""
        return os.path.basename(settings["output_path"].replace("\\", "/")) or "Download"

    def download_now(self):
        settings = self._gather_settings()
        self._resolve_output_tokens(settings)
        if not self._validate_settings(settings):
            return
        queue_tab = self.app.tabs["Queue"]
        task_id = queue_tab.add_task(self._describe(settings), settings=settings,
                                     status="Queued", source_tab=_TAB)
        outcome = queue_tab.start_task(task_id)
        self.app.notify({
            "started": "Download has begun.",
            "next": "Download will run next.",
            "paused": "Download will run next — the queue is paused.",
        }[outcome])

    def add_to_queue(self):
        settings = self._gather_settings()
        self._resolve_output_tokens(settings)
        if not self._validate_settings(settings):
            return
        self.app.tabs["Queue"].add_task(self._describe(settings), settings=settings,
                                        status="Queued", source_tab=_TAB)
        self.app.notify("Download added to queue.")
