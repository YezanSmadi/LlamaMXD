# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Preview frames: ten from the file's interior (OpenCV, else ffmpeg), and the same ten
tone-mapped through the encode's own libplacebo filter for an HDR source."""
import io
import os
import re
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


# The OpenCV pass gives up after this many misses in a row with none found.
_PREVIEW_MAX_MISSES = 3

# Keyframe grabs decode one frame each, which a thread per core only slows and bloats.
_KEYFRAME_THREADS = 1

# Past this many samples sharing a keyframe, one forward OpenCV decode beats exact seeks.
_MAX_EXACT_REDOS = 2

# Keyframes are rarely closer than this (seconds): samples spaced tighter would share them, so
# such a short clip goes straight to the OpenCV pass.
_MIN_KEYFRAME_GAP = 2.0


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


_PTS = re.compile(rb"pts_time:\s*(-?[\d.]+)")
_START = re.compile(rb"start: (-?[\d.]+)")


def _grab_frame(video_path, seconds, max_size, exact=False, threads=1):
    """`(PIL image, its time from the file's start)` for the keyframe at or before `seconds`, or
    with `exact` the frame at `seconds` itself; `(None, None)` on a miss."""
    try:
        completed = subprocess.run(
            [tool_path("ffmpeg"), "-hide_banner", "-nostdin", "-threads", str(threads),
             *([] if exact else ["-noaccurate_seek"]), "-ss", f"{seconds:.3f}", "-i", video_path,
             "-map", "0:v:0", "-frames:v", "1", "-copyts",
             # rgb24: a 10-bit source otherwise gives a 16-bit PPM, ~100x slower for Pillow.
             "-vf", "showinfo,format=rgb24", "-f", "image2pipe", "-c:v", "ppm", "-"],
            capture_output=True, timeout=30, creationflags=NO_WINDOW,
        )
        pts, start = _PTS.search(completed.stderr), _START.search(completed.stderr)
        with Image.open(io.BytesIO(completed.stdout)) as image:
            frame = _fit_pil(image, max_size)
    except (OSError, subprocess.SubprocessError) as exc:
        llamalog.get("probe").debug("Preview frame at %.3fs of %s failed: %s", seconds, video_path, exc)
        return None, None
    # -copyts keeps the file's own timestamps; -ss counts from its start.
    at = float(pts.group(1)) - (float(start.group(1)) if start else 0.0) if pts else seconds
    return frame, max(0.0, at)


def _extract_keyframes(video_path, count, max_size=None, duration=None):
    """`(frames, seeks)`: the keyframe at or before each interior fraction of the real length (one
    frame decoded, not the run from the keyframe to an exact frame). A sample landing on the
    previous one's keyframe is redone exactly; past `_MAX_EXACT_REDOS` of those it returns
    nothing and the caller's OpenCV pass, which decodes forward once, does the set."""
    duration = duration or probe_duration(video_path)
    if not duration or duration / (count + 1) < _MIN_KEYFRAME_GAP:
        return [], []
    targets = [duration * (i + 1) / (count + 1) for i in range(count)]
    with ThreadPoolExecutor(max_workers=preview_workers()) as pool:
        futures = [pool.submit(_grab_frame, video_path, t, max_size, threads=_KEYFRAME_THREADS) for t in targets]
        got, repeats = [], []
        for i, future in enumerate(futures):
            frame, at = future.result()
            if frame is None or (got and got[-1][1] is not None and at <= got[-1][1]):
                repeats.append(i)
                if len(repeats) > _MAX_EXACT_REDOS:
                    for rest in futures:
                        rest.cancel()
                    return [], []
            got.append((frame, at))
        threads = _decoder_threads()
        exact = pool.map(lambda i: _grab_frame(video_path, targets[i], max_size, exact=True, threads=threads),
                         repeats)
        for i, result in zip(repeats, exact):
            got[i] = (result[0], None)
    kept = [(frame, (t, at is None)) for (frame, at), t in zip(got, targets) if frame is not None]
    return [frame for frame, _ in kept], [seek for _, seek in kept]


def _extract_exact(video_path, count, max_size=None, duration=None):
    """`(frames, seeks)` at the exact frames, one ffmpeg each: the last resort, for a file OpenCV
    can't seek (a header whose frame count comes from an end timestamp)."""
    duration = duration or probe_duration(video_path)
    if not duration:
        return [], []
    targets = [duration * (i + 1) / (count + 1) for i in range(count)]
    threads = _decoder_threads()
    with ThreadPoolExecutor(max_workers=preview_workers()) as pool:
        got = list(pool.map(lambda t: _grab_frame(video_path, t, max_size, exact=True, threads=threads), targets))
    kept = [(frame, (t, True)) for (frame, _), t in zip(got, targets) if frame is not None]
    return [frame for frame, _ in kept], [seek for _, seek in kept]


def extract_preview_frames(video_path, count=10, max_size=None, info=None):
    """`(frames, seeks)`: `count` frames from the video's interior as PIL images, shrunk to fit
    `max_size` (w, h) if given, and how each was reached, `(seconds from the file's start,
    exact)`, for the HDR set to repeat. Keyframes via ffmpeg, then OpenCV, then exact ffmpeg
    grabs, each only if the one before found nothing; empty for a file with no picture to show
    (audio, cover art). `info`, the file's `probe_media`, saves probing it again."""
    info = info or {}
    previewable = info.get("previewable")
    if not (previewable if previewable is not None else _has_previewable_video(video_path)):
        return [], []
    duration = info.get("duration")
    for extract in (_extract_keyframes, _extract_thumbnails_cv2, _extract_exact):
        frames, seeks = extract(video_path, count, max_size, duration)
        if frames:
            return frames, seeks
    return [], []


def extract_video_thumbnails(video_path, count=10, max_size=None):
    """The frames of `extract_preview_frames`, without their seeks."""
    return extract_preview_frames(video_path, count, max_size)[0]


def _extract_thumbnails_cv2(video_path, count, max_size=None, duration=None):
    """The OpenCV fallback of `extract_preview_frames`, at exact frame indices. With no usable
    frame count (some webm / streamed sources) it reads the first frame instead."""
    cap = cv2.VideoCapture(video_path)
    try:
        total, fps = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), cap.get(cv2.CAP_PROP_FPS)

        if total <= 0:
            success, frame = cap.read()
            if not success or frame is None:
                return [], []
            return [Image.fromarray(cv2.cvtColor(_shrink(frame, max_size), cv2.COLOR_BGR2RGB))], [(0.0, True)]

        frames, seeks, misses = [], [], 0
        for target in _interior_sample_frames(total, count):
            cap.set(cv2.CAP_PROP_POS_FRAMES, target)
            success, frame = cap.read()
            if success and frame is not None:
                frames.append(Image.fromarray(cv2.cvtColor(_shrink(frame, max_size), cv2.COLOR_BGR2RGB)))
                seeks.append((target / fps if fps > 0 else 0.0, True))
            else:
                # A wrong frame count fails every seek, slowly: give up early.
                misses += 1
                if not frames and misses >= _PREVIEW_MAX_MISSES:
                    break
        return frames, seeks
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


def preview_workers():
    """How many preview ffmpegs run at once: 3 with 8+ logical CPUs, else 2. A tone-mapped frame
    waits on the GPU much of the time, so 2 beat 1 even on a single CPU."""
    return 3 if (os.cpu_count() or 1) >= 8 else 2


def _decoder_threads():
    """Decoder threads per preview process, capped at 4: ffmpeg's default of one per CPU
    wastes threads and memory with several processes running."""
    return max(1, min(4, os.cpu_count() or 1))


def extract_hdr_tonemapped_thumbnails(video_path, count=10, should_cancel=None, max_size=None, seeks=None):
    """Like `extract_preview_frames`, but each frame goes through the encode's own libplacebo
    tone-map (a plain decode of an HDR source is a washed-out picture of the raw data). One short
    ffmpeg per frame, several in parallel, repeating the raw set's `seeks` so the two align.

    Returns [] on any failure or when `should_cancel()` turns true (never a partial set, which
    would fall out of step with the raw one). Callers check `supports_libplacebo()` themselves
    to tell "no HDR" from "unavailable". Keep off the GUI thread."""
    if not supports_libplacebo():
        return []
    if not seeks:
        total, fps = _probe_frame_geometry(video_path)
        if total <= 0 or fps <= 0:
            return []
        seeks = [(target / fps, True) for target in _interior_sample_frames(total, count)]
    fps_flags = ["-fps_mode", "passthrough"] if supports_fps_mode() else ["-vsync", "0"]
    # One metadata probe for the file; see libplacebo_tonemap_vf for why peak_detect follows it.
    static_metadata = _probe_hdr_static_metadata(video_path)
    has_reliable_metadata = (
        static_metadata["mastering_max_nits"] is not None and bool(static_metadata["max_cll"])
    )
    vf = libplacebo_tonemap_vf(peak_detect=not has_reliable_metadata)

    threads = _decoder_threads()

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
                     # Formatted as _grab_frame does, so a keyframe seek lands on the same frame.
                     *([] if seeks[i][1] else ["-noaccurate_seek"]), "-ss", f"{seeks[i][0]:.3f}",
                     "-i", video_path,
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

        with ThreadPoolExecutor(max_workers=preview_workers()) as pool:
            rendered = list(pool.map(render, range(len(seeks))))
    if should_cancel is not None and should_cancel():
        return []
    return [frame for frame in rendered if frame is not None]
