# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""What the bundled ffmpeg can do: `-fps_mode`, libplacebo on a working Vulkan device, SVT-AV1's
preset range. Each answer is a real ffmpeg query, cached for the process."""
import re
import subprocess
import threading

from core import llamalog
from core.tools import run_tool

# Process-lifetime capability caches; None = not checked yet. libplacebo's answer is None when
# nothing is wrong, so it has its own sentinel.
_fps_mode_supported = None
_UNCHECKED = object()
_libplacebo_problem = _UNCHECKED
_libplacebo_lock = threading.Lock()
_av1_preset_range = None
LIBPLACEBO_MISSING = "missing"        # this ffmpeg build lacks the libplacebo filter
LIBPLACEBO_NO_VULKAN = "vulkan"       # it has it, but can't run it (no usable Vulkan)


# HDR->SDR is libplacebo's BT.2390 curve only, never a zscale+tonemap fallback. The filter needs an
# explicit Vulkan device: its implicit device selection segfaults on some hybrid-GPU machines.
# Defined here rather than in ffmpeg_build so the HDR preview frames share the exact encode filter.
VULKAN_DEVICE_FLAGS = ["-init_hw_device", "vulkan=vk", "-filter_hw_device", "vk"]


def libplacebo_tonemap_vf(peak_detect=True):
    """The BT.2390 tone-map filter. Pass `peak_detect=False` only when the source has both a
    mastering peak and a nonzero MaxCLL: trusting real MaxCLL cuts highlight clipping, while
    trusting a mastering peak alone makes the picture dimmer and flatter."""
    return (
        "libplacebo="
        f"apply_dolbyvision=true:"  # explicit, in case a later ffmpeg changes the default
        f"peak_detect={'true' if peak_detect else 'false'}:"
        "tonemapping=bt.2390:"
        "colorspace=bt709:"
        "color_primaries=bt709:"
        "color_trc=bt709:"
        "format=yuv420p"
    )


def supports_fps_mode():
    """Whether ffmpeg knows `-fps_mode` (5.1+) rather than only the older `-vsync`. Cached per
    process; a failed check counts as False, since `-vsync` still works on a new build."""
    global _fps_mode_supported
    if _fps_mode_supported is None:
        try:
            completed = run_tool("ffmpeg", "-hide_banner", "-h", "full")
            _fps_mode_supported = "-fps_mode" in (completed.stdout or "")
        except (OSError, subprocess.SubprocessError) as exc:
            llamalog.get("probe").warning("Couldn't check ffmpeg's -fps_mode support (%s); using -vsync", exc)
            _fps_mode_supported = False
        llamalog.get("probe").info("ffmpeg supports -fps_mode: %s", _fps_mode_supported)
    return _fps_mode_supported


def _libplacebo_listed():
    """Whether `ffmpeg -filters` lists `libplacebo` (i.e. it was compiled in)."""
    try:
        completed = run_tool("ffmpeg", "-hide_banner", "-filters")
    except (OSError, subprocess.SubprocessError) as exc:
        llamalog.get("probe").warning("Couldn't list ffmpeg's filters: %s", exc)
        return False
    return "libplacebo" in (completed.stdout or "")


def _libplacebo_runs():
    """Whether the real tone-map filter runs here: one frame on an explicit Vulkan device, as a
    job launches it. Being listed by `-filters` doesn't prove a Vulkan driver is there. A crash,
    hang or missing ffmpeg counts as no."""
    try:
        completed = run_tool("ffmpeg", "-hide_banner", "-loglevel", "error", *VULKAN_DEVICE_FLAGS,
                             "-f", "lavfi", "-i", "color=c=black:s=128x72:r=1:d=1",
                             "-vf", libplacebo_tonemap_vf(), "-frames:v", "1", "-f", "null", "-", timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        llamalog.get("probe").warning("libplacebo probe couldn't run: %s", exc)
        return False
    if completed.returncode != 0:
        lines = (completed.stderr or "").strip().splitlines()
        llamalog.get("probe").warning("libplacebo probe failed (exit %s): %s", completed.returncode,
                                      lines[-1] if lines else "no output")
    return completed.returncode == 0


def libplacebo_problem():
    """Why HDR->SDR is unavailable — `LIBPLACEBO_MISSING` (not compiled in) or
    `LIBPLACEBO_NO_VULKAN` (can't run here) — or None. Cached per process behind a lock; the
    Vulkan probe takes about a second, so `MainWindow` warms it on a worker at startup."""
    global _libplacebo_problem
    with _libplacebo_lock:
        if _libplacebo_problem is _UNCHECKED:
            if not _libplacebo_listed():
                _libplacebo_problem = LIBPLACEBO_MISSING
            elif not _libplacebo_runs():
                _libplacebo_problem = LIBPLACEBO_NO_VULKAN
            else:
                _libplacebo_problem = None
            llamalog.get("probe").info("libplacebo / Vulkan check: %s", _libplacebo_problem or "ok")
        return _libplacebo_problem


def libplacebo_problem_text():
    """`libplacebo_problem()` as one sentence for a dialog, error or tooltip ('' if none)."""
    problem = libplacebo_problem()
    if problem == LIBPLACEBO_MISSING:
        return ("This ffmpeg install doesn't have libplacebo (needed for accurate BT.2390 "
                "tone-mapping) compiled in. Update ffmpeg.")
    if problem == LIBPLACEBO_NO_VULKAN:
        return ("ffmpeg has libplacebo, but it couldn't run on this machine — HDR to SDR "
                "needs a working Vulkan driver. Update your graphics driver.")
    return ""


def supports_libplacebo():
    """Whether HDR->SDR tone-mapping can run (`libplacebo_problem()` is None)."""
    return libplacebo_problem() is None


def av1_preset_range():
    """`(lo, hi)` of SVT-AV1's `-preset` as this ffmpeg build reports it (it varies: 0-8 on an
    old build, -2 to 13 on a new one), negative "auto" presets excluded. Cached; (0, 8) when it
    can't be read."""
    global _av1_preset_range
    if _av1_preset_range is None:
        _av1_preset_range = (0, 8)
        try:
            completed = run_tool("ffmpeg", "-hide_banner", "-h", "encoder=libsvtav1")
            match = re.search(r"-preset\s+<int>.*?\(from (-?\d+) to (-?\d+)\)", completed.stdout or "")
            if match:
                lo, hi = max(0, int(match.group(1))), int(match.group(2))
                if hi >= lo:
                    _av1_preset_range = (lo, hi)
        except (OSError, subprocess.SubprocessError) as exc:
            llamalog.get("probe").debug("Couldn't read SVT-AV1's preset range (%s); using 0-8", exc)
    return _av1_preset_range
