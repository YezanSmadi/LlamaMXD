# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""ffprobe / ffmpeg queries: the media probe, capability checks, and preview-frame decode."""
import io
import json
import os
import re
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
from PIL import Image

from core import formats, llamalog
from core.tools import tool_path

# Keeps ffprobe/ffmpeg from flashing a console window (Windows-only flag).
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Process-lifetime capability caches; None = not checked yet. libplacebo's answer is None when
# nothing is wrong, so it has its own sentinel.
_fps_mode_supported = None
_UNCHECKED = object()
_libplacebo_problem = _UNCHECKED
_libplacebo_lock = threading.Lock()
_av1_preset_range = None

LIBPLACEBO_MISSING = "missing"        # this ffmpeg build lacks the libplacebo filter
LIBPLACEBO_NO_VULKAN = "vulkan"       # it has it, but can't run it (no usable Vulkan)


# AV1's ffprobe `level` is a seq_level_idx (a table index): raw 5 is "3.1".
_AV1_LEVELS = [
    "2.0", "2.1", "2.2", "2.3", "3.0", "3.1", "3.2", "3.3",
    "4.0", "4.1", "4.2", "4.3", "5.0", "5.1", "5.2", "5.3",
    "6.0", "6.1", "6.2", "6.3", "7.0", "7.1", "7.2", "7.3",
]
# MPEG-2's ffprobe `level` is ffmpeg's named-level code (ffmpeg_vars._LEVEL_ARGS in reverse).
_MPEG2_LEVEL_NAMES = {10: "Low", 8: "Main", 6: "High-1440", 4: "High"}

# ffprobe's ProRes profile names -> this app's (editors say "422 HQ", not "HQ"). Lowercase keys.
_PRORES_PROFILE_NAMES = {
    "proxy": "Proxy", "lt": "LT", "standard": "422", "hq": "422 HQ",
    "4444": "4444", "4444xq": "4444 XQ",
}


def _parse_frame_rate(raw):
    """ffprobe's rational `r_frame_rate` ("24000/1001") as a float, or None ("0/0", missing)."""
    if not raw or "/" not in raw:
        return None
    num, _, den = raw.partition("/")
    try:
        num, den = float(num), float(den)
    except ValueError:
        return None
    return num / den if den else None


def _normalize_video_profile(codec_name, profile):
    """ffprobe's raw `profile` -> this app's display name where they differ: ProRes by table,
    DNxHR by dropping ffprobe's "DNXHR " prefix. Legacy DNxHD (no tier) is left unmatched."""
    if not profile:
        return profile
    if codec_name == "prores":
        return _PRORES_PROFILE_NAMES.get(profile.lower(), profile)
    if codec_name == "dnxhd" and profile.upper().startswith("DNXHR "):
        return profile[len("DNXHR "):].upper()
    return profile

# ffprobe `color_transfer` values that mean HDR: PQ (HDR10 / HDR10+ / DV base layer) and HLG.
_HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}

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


def _ffprobe_level(codec_name, level):
    """ffprobe's video `level` -> display string, or None (-99 / unmapped). The encoding differs
    per codec: H.264 is 10x ("40" -> 4.0), HEVC 30x ("120" -> 4.0), AV1 a table index, MPEG-2 a
    named level."""
    if not isinstance(level, int) or level <= 0:
        return None
    if codec_name == "hevc":
        level = level // 3
        return f"{level // 10}.{level % 10}"
    if codec_name == "av1":
        return _AV1_LEVELS[level] if 0 <= level < len(_AV1_LEVELS) else None
    if codec_name == "mpeg2video":
        return _MPEG2_LEVEL_NAMES.get(level)
    return f"{level // 10}.{level % 10}"


def _parse_luminance_ratio(value):
    """A `"num/den"` luminance in nits (`"10000000/10000"` -> 1000.0), or None."""
    if not value:
        return None
    try:
        num, _, den = str(value).partition("/")
        return float(num) / float(den) if den else float(num)
    except (ValueError, ZeroDivisionError):
        return None


def _probe_hdr_static_metadata(path):
    """The source's static HDR metadata — ST 2086 mastering luminance and MaxCLL/MaxFALL — as
    `{mastering_max_nits, mastering_min_nits, max_cll, max_fall}`, each None when absent.

    These live only on the decoded first frame's side data (never the stream's), and only an
    unrestricted `-show_frames` returns them. The interval must start at an explicit `0`: a bare
    `%+#1` returned no frames on a file with an edit list."""
    empty = {"mastering_max_nits": None, "mastering_min_nits": None,
             "max_cll": None, "max_fall": None}
    try:
        completed = subprocess.run(
            [tool_path("ffprobe"), "-v", "error", "-select_streams", "v:0",
             "-read_intervals", "0%+#1", "-show_frames", "-of", "json", path],
            capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW,
        )
        frames = json.loads(completed.stdout or "{}").get("frames", [])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        llamalog.get("probe").debug("HDR static metadata probe failed for %s: %s", path, exc)
        return empty
    if not frames:
        return empty

    result = dict(empty)
    for entry in frames[0].get("side_data_list", []):
        kind = entry.get("side_data_type")
        if kind == "Mastering display metadata":
            result["mastering_max_nits"] = _parse_luminance_ratio(entry.get("max_luminance"))
            result["mastering_min_nits"] = _parse_luminance_ratio(entry.get("min_luminance"))
        elif kind == "Content light level metadata":
            result["max_cll"] = entry.get("max_content")
            result["max_fall"] = entry.get("max_average")
    return result


_CHROMA_SUBSAMPLING = re.compile(r"(?:yuvj?|yuva)(4[1-4][0-4])")
_PIX_FMT_DEPTH = re.compile(r"(\d+)(?:le|be)$")
# Semi-planar / packed-YUV names that carry no "420"-style digits of their own.
_CHROMA_BY_PIX_FMT = {"nv12": "4:2:0", "nv21": "4:2:0", "p010le": "4:2:0", "p016le": "4:2:0",
                      "nv16": "4:2:2", "p210le": "4:2:2", "nv24": "4:4:4", "p410le": "4:4:4"}


def _describe_pix_format(pix_fmt, bits_per_raw_sample):
    """ffprobe's `pix_fmt` (`yuv420p10le`) -> "10-bit 4:2:0", or None when it
    says nothing useful. Bit depth prefers the stream's own
    `bits_per_raw_sample`; else it is read off the pixel-format name (a name
    with no depth suffix is 8-bit — only for the planar/YUV/gray families,
    since a packed RGB name's digits are total bits per pixel, not depth)."""
    if not pix_fmt:
        return None
    depth = None
    try:
        depth = int(bits_per_raw_sample)
    except (TypeError, ValueError):
        match = _PIX_FMT_DEPTH.search(pix_fmt)
        if match and int(match.group(1)) <= 16:
            depth = int(match.group(1))
        elif pix_fmt.startswith(("yuv", "nv", "gray", "gbrp")):
            depth = 8
    chroma = _CHROMA_BY_PIX_FMT.get(pix_fmt)
    if chroma is None:
        match = _CHROMA_SUBSAMPLING.match(pix_fmt)
        if match:
            chroma = ":".join(match.group(1))
        elif pix_fmt.startswith("gbrp"):
            chroma = "4:4:4"
    return " ".join(bit for bit in (f"{depth}-bit" if depth else None, chroma) if bit) or None


def fps_text(fps):
    """23.976023... -> "23.976", 30.0 -> "30", 29.97003 -> "29.97"."""
    return f"{fps:.3f}".rstrip("0").rstrip(".") if fps else None


def _bitrate_text(bits_per_second):
    """A stream's own bit rate as shown in a track row: "8.4 Mbps" / "640 kbps"."""
    if not bits_per_second or bits_per_second <= 0:
        return None
    if bits_per_second >= 1_000_000:
        return f"{bits_per_second / 1_000_000:.1f} Mbps"
    return f"{round(bits_per_second / 1000)} kbps"


def _describe_video_stream(index, stream):
    """One `video_streams` entry: the details a track row shows. `index` is the stream's
    position among video streams (`-map 0:v:<index>`); `hdr_display` is SDR for anything
    that isn't PQ/HLG."""
    name = stream.get("codec_name")
    width, height = stream.get("width"), stream.get("height")
    fps = _parse_frame_rate(stream.get("r_frame_rate"))
    try:
        bit_rate = int(stream.get("bit_rate"))
    except (TypeError, ValueError):
        bit_rate = None
    transfer = stream.get("color_transfer")
    hdr_display = {"smpte2084": "HDR10", "arib-std-b67": "HLG"}.get(transfer, "SDR")
    return {
        "index": index,
        "codec": formats.FFPROBE_VIDEO.get(name),
        # The raw ffprobe name, for a codec this app has no display name for.
        "codec_name": name.upper() if name else None,
        "resolution_display": f"{width}x{height}" if width and height else None,
        "profile": _normalize_video_profile(name, stream.get("profile")),
        "level": _ffprobe_level(name, stream.get("level")),
        "fps": fps,
        "fps_display": fps_text(fps),
        "bitrate": bit_rate,
        "bitrate_display": _bitrate_text(bit_rate),
        "color_format": _describe_pix_format(stream.get("pix_fmt"), stream.get("bits_per_raw_sample")),
        "hdr": transfer in _HDR_TRANSFERS,
        "hdr_display": hdr_display,
        "language": (stream.get("tags") or {}).get("language"),
    }


def _describe_audio_stream(index, stream):
    """One `audio_streams` entry: display codec / channels / rate / bitrate (the raw value when
    there is no matching option) and language. `index` is the position among audio streams
    (`-map 0:a:<index>`), not the absolute stream index."""
    name = stream.get("codec_name")
    channels = stream.get("channels")
    sample_rate = stream.get("sample_rate")
    bit_rate = stream.get("bit_rate")

    sample_rate_int = None
    if sample_rate is not None:
        try:
            sample_rate_int = int(sample_rate)
        except ValueError:
            pass
    bit_rate_int = None
    if bit_rate is not None:
        try:
            bit_rate_int = int(bit_rate)
        except ValueError:
            pass

    return {
        "index": index,
        "codec": formats.FFPROBE_AUDIO.get(name) or (name.upper() if name else None),
        "channels": channels,
        "channels_display": formats.channels_display_for(channels),
        "sample_rate": sample_rate_int,
        "sample_rate_display": (
            formats.sample_rate_display_for(sample_rate_int) if sample_rate_int else None
        ),
        "bitrate": bit_rate_int,
        "bitrate_display": formats.bitrate_display_for(bit_rate_int) if bit_rate_int else None,
        # Lossless has no bitrate worth showing (TrueHD reports none at all).
        "lossless": formats.probed_audio_is_lossless(name, stream.get("profile")),
        "language": (stream.get("tags") or {}).get("language"),
    }


def probe_media(path):
    """Best-effort ffprobe of `path`: container, first video/audio stream's codec and details,
    size, fps, HDR (+ its static metadata), duration, file size, every stream
    (`video_streams` / `audio_streams`), and the container's title / chapter count / bit rate /
    creation time (the naming tokens). Any field may be None.

    `has_video` / `has_audio` say whether a stream of that kind exists at all: False only when
    the probe ran and found none, None when it never completed ("unknown", never "absent").
    Never raises. Runs a subprocess, so keep it off the GUI thread."""
    unknown = {
        "container": None, "video": None, "audio": None,
        "video_profile": None, "video_level": None, "hdr": None,
        "width": None, "height": None, "duration": None, "file_size": None,
        "audio_channels": None, "audio_sample_rate": None, "audio_bitrate": None,
        "has_video": None, "has_audio": None, "fps": None,
        "video_streams": [], "audio_streams": [],
        "mastering_max_nits": None, "mastering_min_nits": None,
        "max_cll": None, "max_fall": None,
        "title": None, "chapters": None, "bit_rate": None, "creation_time": None,
    }
    if not path or not os.path.exists(path):
        return unknown

    file_size = None
    try:
        file_size = os.path.getsize(path)
    except OSError:
        pass

    try:
        completed = subprocess.run(
            [tool_path("ffprobe"), "-v", "error", "-show_entries",
             "stream=codec_type,codec_name,profile,level,channels,sample_rate,"
             "bit_rate,width,height,color_transfer,color_primaries,r_frame_rate,"
             "pix_fmt,bits_per_raw_sample:"
             "stream_tags=language:format=duration,start_time,bit_rate:"
             "format_tags=title,creation_time:chapter=id",
             "-of", "json", path],
            capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW,
        )
        payload = json.loads(completed.stdout or "{}")
        streams = payload.get("streams", [])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        llamalog.get("probe").warning("ffprobe failed for %s: %s", path, exc)
        info = dict(unknown)
        info["file_size"] = file_size
        return info

    info = dict(unknown)
    info["has_video"] = False
    info["has_audio"] = False
    info["file_size"] = file_size
    # As on disk, not limited to output containers: the tooltip shows import-only formats too.
    extension = os.path.splitext(path)[1].lower()
    if extension:
        info["container"] = extension

    container_info = payload.get("format") or {}
    duration = _to_float(container_info.get("duration"))
    if duration is not None:
        info["duration"] = _effective_duration(
            path, duration, _to_float(container_info.get("start_time")))
    try:
        info["bit_rate"] = int(container_info["bit_rate"])
    except (KeyError, TypeError, ValueError):
        pass
    # Tag names vary in case (Matroska TITLE, MP4 title).
    tags = {str(k).lower(): v for k, v in (container_info.get("tags") or {}).items()}
    info["title"] = (tags.get("title") or "").strip() or None
    info["creation_time"] = tags.get("creation_time") or None
    info["chapters"] = len(payload.get("chapters") or []) or None

    audio_index = 0
    video_index = 0
    # The singular video/audio fields describe the first stream of each kind; the lists hold all.
    for stream in streams:
        kind, name = stream.get("codec_type"), stream.get("codec_name")
        if kind == "video":
            info["has_video"] = True
            info["video_streams"].append(_describe_video_stream(video_index, stream))
            video_index += 1
            if info["video"] is None:
                info["video"] = formats.FFPROBE_VIDEO.get(name)
                info["video_profile"] = _normalize_video_profile(name, stream.get("profile"))
                info["video_level"] = _ffprobe_level(name, stream.get("level"))
                info["width"] = stream.get("width")
                info["height"] = stream.get("height")
                info["fps"] = _parse_frame_rate(stream.get("r_frame_rate"))
                info["hdr"] = stream.get("color_transfer") in _HDR_TRANSFERS
                # Static HDR metadata needs its own (frame-level) probe; only worth it for HDR.
                if info["hdr"]:
                    info.update(_probe_hdr_static_metadata(path))
        elif kind == "audio":
            info["has_audio"] = True
            info["audio_streams"].append(_describe_audio_stream(audio_index, stream))
            audio_index += 1
            if info["audio"] is None:
                info["audio"] = formats.FFPROBE_AUDIO.get(name)
                info["audio_channels"] = formats.channels_display_for(stream.get("channels"))
                sample_rate = stream.get("sample_rate")
                if sample_rate is not None:
                    try:
                        info["audio_sample_rate"] = formats.sample_rate_display_for(int(sample_rate))
                    except ValueError:
                        pass
                bit_rate = stream.get("bit_rate")
                if bit_rate is not None:
                    try:
                        info["audio_bitrate"] = formats.bitrate_display_for(int(bit_rate))
                    except ValueError:
                        pass
    return info


def _to_float(value):
    """`float(value)`, or None for a missing / "N/A" / unparseable one."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# A start time at or under this is ordinary (muxer padding, an edit list): trust the duration.
_START_TRUST_SECS = 1.0
# How close the last timestamp must be to a candidate end to match it (`_effective_duration`).
_END_MATCH_SECS = 1.0


def _tail_end_time(path, start, header):
    """Where the file's last packet ends (max `pts + duration`), or None. Reads only the last
    ~10s. The interval needs an explicit end: an open-ended `T%` came back empty, without an
    error, on about a third of runs."""
    seek = max(start, header - 10.0)
    interval = f"{seek:.3f}%{start + header + 1.0:.3f}"
    packets = []
    for _attempt in range(2):
        try:
            completed = subprocess.run(
                [tool_path("ffprobe"), "-v", "error", "-read_intervals", interval,
                 "-show_entries", "packet=pts_time,duration_time", "-of", "json", path],
                capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW,
            )
            packets = json.loads(completed.stdout or "{}").get("packets") or []
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            llamalog.get("probe").debug("Tail-end timestamp probe failed for %s: %s", path, exc)
            return None
        if packets:
            break
    end = None
    for packet in packets:
        pts = _to_float(packet.get("pts_time"))
        if pts is None:
            continue
        stop = pts + (_to_float(packet.get("duration_time")) or 0.0)
        end = stop if end is None else max(end, stop)
    return end


def _effective_duration(path, header, start):
    """The file's real length from the header `duration` and `start` time. A clip cut from a
    longer file can start minutes in with a header duration that is its END timestamp (35s
    starting at 5465s says 5501s). When the start is past ~1s, the last real timestamp decides:
    at `header` the header is an end time (length = header - start), at `start + header` it is
    honest. Anything unclear keeps the header."""
    if start is None or start <= _START_TRUST_SECS:
        return header
    end = _tail_end_time(path, start, header)
    if end is None:
        return header
    as_end_time = abs(end - header)
    as_length = abs(end - (start + header))
    if as_end_time <= _END_MATCH_SECS and as_end_time < as_length and header > start:
        return header - start
    return header


def probe_duration(path):
    """Best-effort corrected length of `path` in seconds (`_effective_duration`), or None.
    Runs a subprocess, so keep it off the GUI thread."""
    if not path or not os.path.exists(path):
        return None
    try:
        completed = subprocess.run(
            [tool_path("ffprobe"), "-v", "error", "-show_entries", "format=duration,start_time",
             "-of", "json", path],
            capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW,
        )
        container = json.loads(completed.stdout or "{}").get("format") or {}
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        llamalog.get("probe").debug("Duration probe failed for %s: %s", path, exc)
        return None
    duration = _to_float(container.get("duration"))
    if duration is None:
        return None
    return _effective_duration(path, duration, _to_float(container.get("start_time")))


def verify_hdr_sdr_tag(path):
    """After an HDR->SDR job: does the output's video now read as SDR? True, False (still an
    HDR transfer — an HDR picture under an SDR label), or None (the probe failed: unknown,
    never a failure)."""
    try:
        completed = subprocess.run(
            [tool_path("ffprobe"), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=color_transfer",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW,
        )
        transfer = completed.stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        llamalog.get("probe").warning("Couldn't verify the output's colour tags for %s: %s", path, exc)
        return None
    return transfer not in _HDR_TRANSFERS if transfer else None


def supports_fps_mode():
    """Whether ffmpeg knows `-fps_mode` (5.1+) rather than only the older `-vsync`. Cached per
    process; a failed check counts as False, since `-vsync` still works on a new build."""
    global _fps_mode_supported
    if _fps_mode_supported is None:
        try:
            completed = subprocess.run(
                [tool_path("ffmpeg"), "-hide_banner", "-h", "full"],
                capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW,
            )
            _fps_mode_supported = "-fps_mode" in (completed.stdout or "")
        except (OSError, subprocess.SubprocessError) as exc:
            llamalog.get("probe").warning("Couldn't check ffmpeg's -fps_mode support (%s); using -vsync", exc)
            _fps_mode_supported = False
        llamalog.get("probe").info("ffmpeg supports -fps_mode: %s", _fps_mode_supported)
    return _fps_mode_supported


def _libplacebo_listed():
    """Whether `ffmpeg -filters` lists `libplacebo` (i.e. it was compiled in)."""
    try:
        completed = subprocess.run(
            [tool_path("ffmpeg"), "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        llamalog.get("probe").warning("Couldn't list ffmpeg's filters: %s", exc)
        return False
    return "libplacebo" in (completed.stdout or "")


def _libplacebo_runs():
    """Whether the real tone-map filter runs here: one frame on an explicit Vulkan device, as a
    job launches it. Being listed by `-filters` doesn't prove a Vulkan driver is there. A crash,
    hang or missing ffmpeg counts as no."""
    try:
        completed = subprocess.run(
            [tool_path("ffmpeg"), "-hide_banner", "-loglevel", "error", *VULKAN_DEVICE_FLAGS,
             "-f", "lavfi", "-i", "color=c=black:s=128x72:r=1:d=1",
             "-vf", libplacebo_tonemap_vf(), "-frames:v", "1", "-f", "null", "-"],
            capture_output=True, text=True, timeout=30, creationflags=_NO_WINDOW,
        )
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
            completed = subprocess.run(
                [tool_path("ffmpeg"), "-hide_banner", "-h", "encoder=libsvtav1"],
                capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW,
            )
            match = re.search(r"-preset\s+<int>.*?\(from (-?\d+) to (-?\d+)\)", completed.stdout or "")
            if match:
                lo, hi = max(0, int(match.group(1))), int(match.group(2))
                if hi >= lo:
                    _av1_preset_range = (lo, hi)
        except (OSError, subprocess.SubprocessError) as exc:
            llamalog.get("probe").debug("Couldn't read SVT-AV1's preset range (%s); using 0-8", exc)
    return _av1_preset_range


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


def _has_previewable_video(path):
    """True when `path` has a real video stream, not just cover art (an audio file with a cover
    keeps its Wave Loop)."""
    try:
        completed = subprocess.run(
            [tool_path("ffprobe"), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_type:stream_disposition=attached_pic",
             "-of", "json", path],
            capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW,
        )
        streams = json.loads(completed.stdout or "{}").get("streams") or []
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        llamalog.get("probe").debug("Couldn't check %s for a real video stream: %s", path, exc)
        return False
    return bool(streams) and not (streams[0].get("disposition") or {}).get("attached_pic")


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
                capture_output=True, timeout=30, creationflags=_NO_WINDOW,
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
                    creationflags=_NO_WINDOW | _BELOW_NORMAL,
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