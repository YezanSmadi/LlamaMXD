# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Preview frames: ten from the file's interior (OpenCV, else ffmpeg), and the same ten
tone-mapped through the encode's own libplacebo filter for an HDR source."""
import io
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
from PIL import Image

from core import llamalog
from core.capabilities import VULKAN_DEVICE_FLAGS, libplacebo_tonemap_vf, supports_fps_mode, supports_libplacebo
from core.probe import _has_previewable_video, _probe_hdr_static_metadata, probe_duration
from core.tools import NO_WINDOW, tool_path

def _interior_sample_frames(total, count):
    """Frame indices for `count` samples at the fractions 1/(count+1) … count/(count+1), which
    skip a black first frame and a credits last frame. Shared by the raw and tone-mapped sets
    so they stay index-for-index aligned."""
    return sorted({
        min(total - 1, max(0, round(total * (i + 1) / (count + 1))))
        for i in range(count)
    })


def _probe_frame_geometry(video_path):
    """`(frame_count, fps)` via cv2, or `(0, 0.0)`. When cv2's implied length is over 1.5x the
    real one (a header that is an end timestamp) the count is rebuilt from the real length; a
    smaller gap (variable frame rate) is kept so the sets stay aligned with cv2's."""
    cap = cv2.VideoCapture(video_path)
    try:
        total, fps = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), cap.get(cv2.CAP_PROP_FPS)
    finally:
        cap.release()
    if total > 0 and fps > 0:
        real = probe_duration(video_path)
        if real and total / fps > 1.5 * real:
            total = max(1, int(real * fps))
    return total, fps


# The widest an ffmpeg-fallback preview frame is decoded.
_PREVIEW_MAX_WIDTH = 1920


# The fallback gives up after this many misses in a row with none found.
_PREVIEW_MAX_MISSES = 3


def _shrink(rgb, max_size):
    """`rgb` (an image array) area-scaled to fit inside `max_size` (w, h), aspect kept; as is
    when it already fits or `max_size` is None."""
    if max_size:
        h, w = rgb.shape[:2]
        k = min(max_size[0] / w, max_size[1] / h)
        if k < 1:
            rgb = cv2.resize(rgb, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA)
    return rgb


def _fit_pil(image, max_size):
    """A PIL image as RGB, shrunk like `_shrink`."""
    return Image.fromarray(_shrink(np.asarray(image.convert("RGB")), max_size))


def _extract_thumbnails_ffmpeg(video_path, count, max_size=None):
    """`count` interior frames via one ffmpeg per frame: the fallback for a file OpenCV can't
    seek (its frame count comes from a header that can be an end timestamp). Positions are
    fractions of the real length, as input-side `-ss` seeks."""
    duration = probe_duration(video_path)
    if not duration or duration <= 0 or not _has_previewable_video(video_path):
        return []
    frames, misses = [], 0
    for i in range(count):
        try:
            completed = subprocess.run(
                [tool_path("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
                 "-ss", f"{duration * (i + 1) / (count + 1):.3f}", "-i", video_path,
                 "-map", "0:v:0", "-frames:v", "1",
                 # rgb24: a 10-bit source otherwise gives a 16-bit PPM, ~100x slower for Pillow.
                 "-vf", f"scale='min({_PREVIEW_MAX_WIDTH},iw)':-2,format=rgb24",
                 "-f", "image2pipe", "-c:v", "ppm", "-"],
                capture_output=True, timeout=30, creationflags=NO_WINDOW,
            )
            with Image.open(io.BytesIO(completed.stdout)) as image:
                frames.append(_fit_pil(image, max_size))
        except (OSError, subprocess.SubprocessError) as exc:
            llamalog.get("probe").debug("ffmpeg preview frame %d of %s failed: %s", i, video_path, exc)
            misses += 1
            if not frames and misses >= _PREVIEW_MAX_MISSES:
                break
    return frames


def extract_video_thumbnails(video_path, count=10, max_size=None):
    """`count` frames from the video's interior as PIL images, each shrunk to fit `max_size`
    (w, h) if given: OpenCV first, ffmpeg only if OpenCV got nothing. Can be shorter than
    `count`, or empty if nothing decodes."""
    return (_extract_thumbnails_cv2(video_path, count, max_size)
            or _extract_thumbnails_ffmpeg(video_path, count, max_size))


def _extract_thumbnails_cv2(video_path, count, max_size=None):
    """The OpenCV half of `extract_video_thumbnails`. With no usable frame count (some webm /
    streamed sources) it reads the first frame instead."""
    cap = cv2.VideoCapture(video_path)
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        if total <= 0:
            success, frame = cap.read()
            if not success or frame is None:
                return []
            return [Image.fromarray(cv2.cvtColor(_shrink(frame, max_size), cv2.COLOR_BGR2RGB))]

        targets = _interior_sample_frames(total, count)

        frames, misses = [], 0
        for target in targets:
            cap.set(cv2.CAP_PROP_POS_FRAMES, target)
            success, frame = cap.read()
            if success and frame is not None:
                frames.append(Image.fromarray(cv2.cvtColor(_shrink(frame, max_size), cv2.COLOR_BGR2RGB)))
            else:
                # A wrong frame count fails every seek, slowly: leave it to the ffmpeg fallback.
                misses += 1
                if not frames and misses >= _PREVIEW_MAX_MISSES:
                    break
        return frames
    finally:
        cap.release()


def extract_video_thumbnail(video_path):
    """The first interior sample of `video_path`, or None."""
    frames = extract_video_thumbnails(video_path, count=1)
    return frames[0] if frames else None


# The HDR preview is speculative background work that may overlap a queue job, so it yields.
_BELOW_NORMAL = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)


# Generous: a frame sharing the machine with an encode takes far longer than ~1.5s, and a
# timed-out frame is a hole in a set that must stay aligned with the raw one.
_HDR_FRAME_TIMEOUT = 90


def hdr_preview_workers():
    """How many tone-mapped frames render at once: 3 with 8+ logical CPUs, else 2. Each
    process waits on the GPU much of the time, so 2 beat 1 even on a single CPU."""
    return 3 if (os.cpu_count() or 1) >= 8 else 2


def _hdr_decoder_threads():
    """Decoder threads per preview process, capped at 4: ffmpeg's default of one per CPU
    wastes threads and memory with several processes running."""
    return max(1, min(4, os.cpu_count() or 1))


def extract_hdr_tonemapped_thumbnails(video_path, count=10, should_cancel=None, max_size=None):
    """Like `extract_video_thumbnails`, but each frame goes through the encode's own libplacebo
    tone-map (cv2's decode of an HDR source is a washed-out picture of the raw data). One short
    ffmpeg per frame, at the same frame indices as the raw set, several in parallel.

    Returns [] on any failure or when `should_cancel()` turns true (never a partial set, which
    would fall out of step with the raw one). Callers check `supports_libplacebo()` themselves
    to tell "no HDR" from "unavailable". Keep off the GUI thread."""
    if not supports_libplacebo():
        return []
    total, fps = _probe_frame_geometry(video_path)
    if total <= 0 or fps <= 0:
        return []
    targets = _interior_sample_frames(total, count)
    fps_flags = ["-fps_mode", "passthrough"] if supports_fps_mode() else ["-vsync", "0"]
    # One metadata probe for the file; see libplacebo_tonemap_vf for why peak_detect follows it.
    static_metadata = _probe_hdr_static_metadata(video_path)
    has_reliable_metadata = (
        static_metadata["mastering_max_nits"] is not None and bool(static_metadata["max_cll"])
    )
    vf = libplacebo_tonemap_vf(peak_detect=not has_reliable_metadata)

    threads = _hdr_decoder_threads()

    with tempfile.TemporaryDirectory(prefix="llamamxd_hdr_") as tmp_dir:
        def render(i):
            """Frame `i` as a PIL image, or None on a miss or a cancel."""
            if should_cancel is not None and should_cancel():
                return None
            out_path = os.path.join(tmp_dir, f"frame_{i:03d}.png")
            try:
                completed = subprocess.run(
                    [tool_path("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                     *VULKAN_DEVICE_FLAGS,
                     "-threads", str(threads),
                     "-ss", f"{targets[i] / fps:.3f}", "-i", video_path,
                     "-vf", vf,
                     *fps_flags, "-frames:v", "1", out_path],
                    capture_output=True, timeout=_HDR_FRAME_TIMEOUT,
                    creationflags=NO_WINDOW | _BELOW_NORMAL,
                )
                if completed.returncode != 0:
                    tail = (completed.stderr or b"").decode("utf-8", "replace").strip().splitlines()
                    llamalog.get("probe").warning("HDR preview frame %d of %s: ffmpeg exited %s: %s", i, video_path,
                                                  completed.returncode, tail[-1] if tail else "no output")
                with Image.open(out_path) as img:
                    return _fit_pil(img, max_size)
            except (OSError, subprocess.SubprocessError) as exc:
                llamalog.get("probe").warning("HDR preview frame %d of %s failed: %s", i, video_path, exc)
                return None

        with ThreadPoolExecutor(max_workers=hdr_preview_workers()) as pool:
            rendered = list(pool.map(render, range(len(targets))))
    if should_cancel is not None and should_cancel():
        return []
    return [frame for frame in rendered if frame is not None]
