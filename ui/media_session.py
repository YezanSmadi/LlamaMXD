# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""The selected input file and everything derived from it: the probe, the ten preview frames,
the tone-mapped HDR set and the shared scrub position, broadcast to the media tabs (Muxing,
Encoding). `select_file` is the only place the selected file changes."""
import os
import threading
import time

from PySide6.QtGui import QGuiApplication

from core import formats, llamalog
from core.capabilities import libplacebo_checked, libplacebo_problem
from core.previews import extract_hdr_tonemapped_thumbnails, extract_preview_frames
from core.probe import probe_media
from ui.widgets.dialogs import show_message
from ui.workers import emit_progress, pil_to_qimage, run_async

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
    """The largest a preview frame is ever drawn, in device pixels: the biggest screen. Frames
    are stored no bigger (a 4K frame kept whole is 33MB)."""
    sizes = [(round(s.geometry().width() * s.devicePixelRatio()), round(s.geometry().height() * s.devicePixelRatio()))
             for s in QGuiApplication.screens()]
    return max(sizes, key=lambda size: size[0] * size[1]) if sizes else None


def _empty_media_info():
    """"Unknown" for every probe field — None never reads as absent."""
    info = dict.fromkeys(_MEDIA_INFO_KEYS)
    info["audio_streams"] = []
    return info


class MediaSession:
    """Owns the selected file's state; `window` parents its dialogs."""

    def __init__(self, window):
        self._window = window
        self.tabs = []                    # the media tabs, registered by MediaTab.__init__
        self.current_file_path = ""
        # Preview frames (QImages) for the selected file, decoded once off the GUI thread.
        self.thumb_frames = []
        self.thumb_frames_path = None
        self._thumb_seeks = []            # how each frame was reached: the HDR set repeats them
        self._thumb_token = 0
        self._thumb_t0 = time.monotonic()
        self.info = _empty_media_info()
        self.info_path = None             # the file `info` was probed from
        self._preview_index = 0
        # HDR→SDR tone-mapped preview frames, cached for one file.
        self.hdr_frames = None
        self.hdr_frames_path = None
        self._hdr_inflight_path = None
        self._hdr_token = 0
        self._hdr_t0 = time.monotonic()
        self._hdr_cancel_event = None
        self._hdr_cancelled_token = 0     # the render a file change interrupted: its late, empty result is dropped

    def register_tab(self, tab):
        self.tabs.append(tab)

    def select_file(self, file_path):
        """The only place the selected file changes."""
        clean_path = (file_path or "").strip("{}").strip()
        if not clean_path:
            return
        if clean_path != self.current_file_path:
            self._preview_index = 0
            if clean_path != self.info_path:
                self.info = _empty_media_info()
            # A new file: drop the outgoing preview now rather than when the new frames land.
            for tab in self.tabs:
                tab.carousel.clear_preview()
            # Interrupt the old file's HDR render and turn its HDR->SDR switch off.
            self._cancel_hdr_render()
            # Only the current file's frames are kept (a reselect of it reuses them): don't hold
            # the old raw and tone-mapped sets meanwhile, or at all if the new file has none.
            self.thumb_frames = []
            self.thumb_frames_path = None
            self._thumb_seeks = []
            self.hdr_frames = None
            self.hdr_frames_path = None
            self._reset_hdr_previews()
        self.current_file_path = clean_path
        llamalog.get("app").info("File selected: %s", clean_path)
        for tab in self.tabs:
            tab.set_selected_file(clean_path)
            tab._autofill_output_path()
        self._load_thumbnails(clean_path)

    def _reset_hdr_previews(self):
        for tab in self.tabs:
            reset_hdr = getattr(tab, "reset_hdr_preview", None)
            if callable(reset_hdr):
                reset_hdr()

    def _load_thumbnails(self, path):
        """Cache hit: broadcast now. Miss: probe, then decode ten frames, on a worker; the probe
        lands first so defaults settle early."""
        self._thumb_token += 1
        token = self._thumb_token
        self._thumb_t0 = time.monotonic()
        cached_info = path == self.info_path
        if cached_info:
            self._broadcast_media_info()
            self._check_hdr_support()
            # An audio file's Wave Loop comes from the probe, not from the (empty) frame decode.
            if self._is_audio_only(path):
                self._broadcast_audio_only(True)
        if path == self.thumb_frames_path and self.thumb_frames:
            self._broadcast_thumbnails(self.thumb_frames)
            self._prerender_hdr(path)
            if cached_info:
                return

        max_size = _preview_max_size()
        known = self.info if cached_info else None

        def work():
            info = known
            if info is None:
                info = probe_media(path)
                emit_progress(lambda i: self._deliver_media_info(token, path, i), info)
            frames, seeks = extract_preview_frames(path, count=10, max_size=max_size, info=info)
            return [pil_to_qimage(f) for f in frames], seeks

        run_async(work, lambda result: self._deliver_thumbnails(token, path, *(result or ([], []))))

    def _deliver_media_info(self, token, path, info):
        if token != self._thumb_token or info is None:
            return
        # No video and no audio at all is ffmpeg's demuxer failing (corrupt, or an unsupported
        # variant like some MXF), not an audio-only file: reject it before it reaches a tab.
        if info.get("has_video") in (None, False) and info.get("has_audio") in (None, False):
            self._reject_file(path)
            return
        self.info = info
        self.info_path = path
        llamalog.get("probe").info("Probed %s: %s", os.path.basename(path), _probe_summary(info))
        self._broadcast_media_info()
        if self._is_audio_only(path):
            self._broadcast_audio_only(True)
        self._check_hdr_support()

    def _check_hdr_support(self):
        """An HDR file: find out, once and off the GUI thread, whether this PC can tone-map it
        (a Vulkan probe that wakes the GPU, so not at launch), then let the tabs re-sync."""
        if self.info.get("hdr") is True and not libplacebo_checked():
            run_async(libplacebo_problem, lambda _problem: [tab._sync_controls() for tab in self.tabs])

    def _reject_file(self, path):
        """Undo the selection entirely, back to the pristine drop box. Bumping the token makes
        the in-flight decode for this path a no-op when it lands."""
        llamalog.get("app").warning("Rejected %s: no video or audio stream could be identified "
                                    "(unreadable, or a format this ffmpeg can't parse)", path)
        self._thumb_token += 1
        self.current_file_path = ""
        self.info = _empty_media_info()
        self.info_path = None
        self.thumb_frames = []
        self.thumb_frames_path = None
        self._thumb_seeks = []
        self._preview_index = 0
        self._cancel_hdr_render()
        for tab in self.tabs:
            tab.clear_selected_file()
        self._reset_hdr_previews()
        show_message(
            self._window, "Couldn't Read This File",
            f"“{os.path.basename(path)}”'s video and audio couldn't be identified. "
            "It may be corrupted, or use a format this app's bundled ffmpeg can't "
            "fully parse.",
        )

    def _is_audio_only(self, path):
        info = self.info
        if info.get("video"):
            return False
        if info.get("audio"):
            return True
        return os.path.splitext(path)[1].lower() in formats.AUDIO_EXTENSIONS

    def _broadcast_audio_only(self, flag):
        for tab in self.tabs:
            tab.carousel.set_audio_only(flag)

    def _broadcast_media_info(self):
        for tab in self.tabs:
            tab.on_media_info(self.info)
            tab.carousel.set_media_info(self.info)
            # The probe may carry a title / chapter count the naming format uses.
            tab.refresh_auto_output()

    def _deliver_thumbnails(self, token, path, frames, seeks=()):
        if token != self._thumb_token:
            return
        took = time.monotonic() - self._thumb_t0
        if not frames:
            if self._is_audio_only(path):
                llamalog.get("app").info("%s is audio-only: no preview frames (Wave Loop)", os.path.basename(path))
                self._broadcast_audio_only(True)
                return
            llamalog.get("app").warning("No preview frames could be decoded for %s after %.1fs "
                                        "(the file stays selected)", path, took)
            # A video that decoded to no frames stays selected and usable; the drop box says so.
            for tab in self.tabs:
                tab.show_no_preview()
            show_message(
                self._window, "No Preview",
                "No preview images could be generated.\n\n"
                "The file is still usable but the preview images could not be decoded properly.",
            )
            return
        self.thumb_frames = frames
        self.thumb_frames_path = path
        self._thumb_seeks = list(seeks)
        llamalog.get("app").info("Previews ready for %s: %d frames in %.1fs",
                                 os.path.basename(path), len(frames), took)
        self._broadcast_thumbnails(frames)
        self._prerender_hdr(path)

    def _broadcast_thumbnails(self, frames):
        for tab in self.tabs:
            tab.carousel.set_audio_only(False)
            tab.on_thumbnails(frames)
            tab.carousel.sync_index(self._preview_index)

    def sync_preview_index(self, index):
        """A carousel was scrubbed — mirror it onto the other tab's."""
        if index == self._preview_index:
            return
        self._preview_index = index
        for tab in self.tabs:
            tab.carousel.sync_index(index)

    # ------------------------------------------------------------------ #
    #  HDR→SDR preview renders
    # ------------------------------------------------------------------ #
    def _prerender_hdr(self, path):
        """Start an HDR file's tone-mapped previews once its raw ones are up, in the background,
        so HDR->SDR is instant when switched on. A switch pressed earlier waits for this run."""
        if path == self.current_file_path and path == self.info_path and self.info.get("hdr") is True:
            self.start_hdr_render(path)

    def start_hdr_render(self, path):
        """One tone-mapped render per file; a no-op when cached or already running for it."""
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
        seeks = self._thumb_seeks if path == self.thumb_frames_path else None

        def work():
            frames = extract_hdr_tonemapped_thumbnails(path, count=10, should_cancel=cancel_event.is_set,
                                                       max_size=max_size, seeks=seeks)
            return [pil_to_qimage(f) for f in frames]

        run_async(work, lambda frames: self._deliver_hdr(token, path, frames or []))

    def _cancel_hdr_render(self):
        """Interrupt an HDR preview render still in flight (its file is no longer shown)."""
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
            # Superseded or interrupted: not a failure, and it must not replace the cached frames.
            return
        took = time.monotonic() - self._hdr_t0
        if frames:
            llamalog.get("app").info("HDR preview ready for %s: %d frames in %.1fs",
                                     os.path.basename(path), len(frames), took)
        else:
            llamalog.get("app").warning("HDR preview render for %s produced no frames (%.1fs; cancelled, "
                                        "libplacebo unavailable, or a decode failure)", os.path.basename(path), took)
        self.hdr_frames = frames or None
        self.hdr_frames_path = path if frames else None
        for tab in self.tabs:
            ready = getattr(tab, "on_hdr_frames_ready", None)
            if callable(ready):
                ready(path, self.hdr_frames)
