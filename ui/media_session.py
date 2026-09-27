# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""The selected input file and everything derived from it: the probe, the ten preview frames,
the tone-mapped HDR set and the shared scrub position, broadcast to the media tabs (Muxing,
Encoding). `select_file` is the only place the selected file changes."""
import os
import time

from PySide6.QtGui import QGuiApplication

from core import formats, llamalog
from core.capabilities import libplacebo_checked, libplacebo_problem
from core.previews import extract_preview_frames, hdr_seeks, hdr_tonemap_filter, hdr_tonemap_frame, preview_workers
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
        # HDR→SDR tone-mapped preview frames for one file: a list with None for frames not rendered yet.
        self.hdr_frames = None
        self.hdr_frames_path = None
        self._hdr = None                  # the render in progress: see _hdr_begin
        self._hdr_token = 0

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

    def _clear_state(self):
        """Undo the selection entirely, back to the pristine drop box. Bumping the token makes
        the in-flight decode for the old path a no-op when it lands. Shared by a rejected import
        and a deliberate Clear."""
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

    def _reject_file(self, path):
        """A probe found neither video nor audio: clear the selection and say why."""
        llamalog.get("app").warning("Rejected %s: no video or audio stream could be identified "
                                    "(unreadable, or a format this ffmpeg can't parse)", path)
        self._clear_state()
        show_message(
            self._window, "Couldn't Read This File",
            f"“{os.path.basename(path)}”'s video and audio couldn't be identified. "
            "It may be corrupted, or use a format this app's bundled ffmpeg can't "
            "fully parse.",
        )

    def clear_selection(self):
        """The Clear button: deliberately drop the selected file and everything derived from it,
        with no message (there's nothing wrong with the file). Unlike a rejected import, this is
        the only way a tab's own controls (Clear/Queue Task/Mux, all gated on having a file) need
        to grey out immediately rather than waiting on the next unrelated resync."""
        if not self.current_file_path:
            return
        llamalog.get("app").info("Selection cleared")
        self._clear_state()
        for tab in self.tabs:
            tab._sync_controls()

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
        """A carousel was scrubbed — mirror it onto the other tab's, and have the tone-mapped
        frames there ready too (an HDR file)."""
        if index == self._preview_index:
            return
        self._preview_index = index
        for tab in self.tabs:
            tab.carousel.sync_index(index)
        if self._hdr is not None:
            self._hdr_want(_around(index))

    # ------------------------------------------------------------------ #
    #  HDR→SDR preview renders
    # ------------------------------------------------------------------ #
    # One ffmpeg per tone-mapped frame, and a frame not ready takes ~1s to appear. So an HDR file's
    # frame on screen (and the next two) is rendered in the background one at a time, and the rest
    # only once HDR->SDR is on — the view first, several at once: the switch shows a tone-mapped
    # frame at once, without the whole set's CPU / GPU burst on every import.

    def _prerender_hdr(self, path):
        """An HDR file's raw previews are up: tone-map the frame on screen and the next two."""
        if path == self.current_file_path and path == self.info_path and self.info.get("hdr") is True:
            self._hdr_begin(path)
            self._hdr_want(_around(self._preview_index))

    def start_hdr_render(self, path):
        """HDR->SDR is on: render every frame not yet done, nearest the one on screen first,
        `preview_workers()` at a time."""
        if not path or path != self.current_file_path:
            return
        self._hdr_begin(path)
        self._hdr["workers"] = preview_workers()
        count = len(self._hdr["seeks"] or self._thumb_seeks) or 10
        order = sorted(range(count), key=lambda i: (abs(i - self._preview_index), i < self._preview_index))
        self._hdr_want(order)

    def hdr_idle(self):
        """HDR->SDR is off: back to one at a time, and only the frames around the view."""
        if self._hdr is not None:
            self._hdr["workers"] = 1
            self._hdr["queue"] = [i for i in self._hdr["queue"] if i in _around(self._preview_index)]

    def _hdr_begin(self, path):
        """Start the render for `path` (once): its filter and seeks are worked out on a worker."""
        if self._hdr is not None and self._hdr["path"] == path:
            return
        self._hdr_token += 1
        token = self._hdr_token
        seeks = list(self._thumb_seeks) if path == self.thumb_frames_path else []
        self._hdr = {"token": token, "path": path, "vf": None, "seeks": seeks, "queue": [], "busy": set(),
                     "workers": 1, "t0": time.monotonic()}
        llamalog.get("app").info("HDR preview render started for %s", os.path.basename(path))

        def prepare():
            return hdr_tonemap_filter(path), seeks or hdr_seeks(path)

        run_async(prepare, lambda result: self._hdr_prepared(token, *(result or (None, []))))

    def _hdr_prepared(self, token, vf, seeks):
        render = self._hdr
        if render is None or render["token"] != token:
            return
        if vf is None or not seeks:
            llamalog.get("app").warning("HDR preview unavailable for %s (libplacebo unavailable, or the frames "
                                        "couldn't be located)", os.path.basename(render["path"]))
            self._hdr = None
            return
        render["vf"], render["seeks"] = vf, seeks
        self.hdr_frames = [None] * len(seeks)
        self.hdr_frames_path = render["path"]
        self._hdr_pump()

    def _hdr_want(self, indices):
        """Put `indices` at the front of the queue (in that order), then start what fits."""
        render = self._hdr
        if render is None:
            return
        wanted = [i for i in indices if i not in render["busy"]]
        render["queue"] = wanted + [i for i in render["queue"] if i not in wanted]
        self._hdr_pump()

    def _hdr_pump(self):
        render = self._hdr
        if render is None or render["vf"] is None:
            return
        frames, max_size = self.hdr_frames, _preview_max_size()
        while render["queue"] and len(render["busy"]) < render["workers"]:
            i = render["queue"].pop(0)
            if i >= len(frames) or frames[i] is not None or i in render["busy"]:
                continue
            render["busy"].add(i)
            path, seek, vf, token = render["path"], render["seeks"][i], render["vf"], render["token"]
            # Bound now: the loop moves on before the worker runs.
            run_async(lambda path=path, seek=seek, vf=vf, i=i:
                      _qimage_or_none(hdr_tonemap_frame(path, seek, vf, max_size, label=str(i))),
                      lambda image, i=i: self._hdr_frame_done(token, i, image))

    def _hdr_frame_done(self, token, i, image):
        render = self._hdr
        if render is None or render["token"] != token:
            return   # the file changed meanwhile
        render["busy"].discard(i)
        if image is not None:
            self.hdr_frames[i] = image
            for tab in self.tabs:
                ready = getattr(tab, "on_hdr_frames_ready", None)
                if callable(ready):
                    ready(render["path"], i)
            if all(frame is not None for frame in self.hdr_frames):
                llamalog.get("app").info("HDR preview ready for %s: %d frames in %.1fs", os.path.basename(render["path"]),
                                         len(self.hdr_frames), time.monotonic() - render["t0"])
        self._hdr_pump()

    def _cancel_hdr_render(self):
        """Stop an HDR preview render (its file is no longer shown); a frame already rendering
        finishes and is dropped."""
        render = self._hdr
        if render is not None and (render["queue"] or render["busy"]):
            llamalog.get("app").info("HDR preview render cancelled (%s)", os.path.basename(render["path"]))
        self._hdr = None


def _around(index, count=3):
    """The frame at `index` and the next `count - 1` (a queue skips any past the last)."""
    return list(range(index, index + count))


def _qimage_or_none(image):
    """A PIL image as a QImage for the GUI thread, or None."""
    return pil_to_qimage(image) if image is not None else None
