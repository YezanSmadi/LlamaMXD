# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""ffprobe queries: `probe_media` (everything the tabs read about a file), its real length, and
the HDR colour-tag check on a finished output. Every failure returns "unknown", never raises."""
import os
import re
import subprocess

from core import formats, llamalog
from core.tools import ffprobe_json, run_tool

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
        frames = ffprobe_json("-select_streams", "v:0", "-read_intervals", "0%+#1", "-show_frames",
                              path).get("frames", [])
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


def _describe_subtitle_stream(index, stream):
    """One `subtitle_streams` entry: codec (display and raw), picture or text, size (a picture
    format's canvas), language, title and the Default / Forced flags. `index` is the position
    among subtitle streams (`-map 0:s:<index>`, the `subtitles` filter's `si`)."""
    name = stream.get("codec_name")
    tags = stream.get("tags") or {}
    disposition = stream.get("disposition") or {}
    return {
        "index": index,
        "codec": formats.FFPROBE_SUBTITLE.get(name) or (name.upper() if name else None),
        "codec_name": name,
        "image": name in formats.IMAGE_SUBTITLES,
        "width": stream.get("width") or None,
        "height": stream.get("height") or None,
        "language": tags.get("language"),
        "title": tags.get("title"),
        "default": bool(disposition.get("default")),
        "forced": bool(disposition.get("forced")),
    }


def _chapter_list(chapters):
    """ffprobe's chapters as `[{"start", "end", "title"}]` in seconds, sorted by start."""
    out = []
    for chapter in chapters or []:
        start, end = _to_float(chapter.get("start_time")), _to_float(chapter.get("end_time"))
        if start is None:
            continue
        title = ((chapter.get("tags") or {}).get("title") or "").strip() or None
        out.append({"start": start, "end": end, "title": title})
    return sorted(out, key=lambda chapter: chapter["start"])


def probe_media(path):
    """Best-effort ffprobe of `path`: container, first video/audio stream's codec and details,
    size, fps, HDR (+ its static metadata), duration, file size, every stream
    (`video_streams` / `audio_streams` / `subtitle_streams`), the chapters (`chapter_list`), the
    container's start time, and its title / chapter count / bit rate / creation time (the naming
    tokens). Any field may be None.

    `has_video` / `has_audio` say whether a stream of that kind exists at all: False only when
    the probe ran and found none, None when it never completed ("unknown", never "absent").
    `previewable` is `_has_previewable_video`'s answer, from the same probe.
    Never raises. Runs a subprocess, so keep it off the GUI thread."""
    unknown = {
        "container": None, "video": None, "audio": None,
        "video_profile": None, "video_level": None, "hdr": None,
        "width": None, "height": None, "duration": None, "file_size": None,
        "audio_channels": None, "audio_sample_rate": None, "audio_bitrate": None,
        "has_video": None, "has_audio": None, "previewable": None, "fps": None,
        "video_streams": [], "audio_streams": [], "subtitle_streams": [], "chapter_list": [],
        "mastering_max_nits": None, "mastering_min_nits": None,
        "max_cll": None, "max_fall": None,
        "title": None, "chapters": None, "bit_rate": None, "creation_time": None,
        "start_time": None,
    }
    if not path or not os.path.exists(path):
        return unknown

    file_size = None
    try:
        file_size = os.path.getsize(path)
    except OSError:
        pass

    try:
        payload = ffprobe_json(
            "-show_entries",
            "stream=codec_type,codec_name,profile,level,channels,sample_rate,"
            "bit_rate,width,height,color_transfer,color_primaries,r_frame_rate,"
            "pix_fmt,bits_per_raw_sample:"
            "stream_disposition=attached_pic,default,forced:stream_tags=language,title:"
            "format=duration,start_time,bit_rate:format_tags=title,creation_time:"
            "chapter=id,start_time,end_time:chapter_tags=title",
            path)
        streams = payload.get("streams", [])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        llamalog.get("probe").warning("ffprobe failed for %s: %s", path, exc)
        info = dict(unknown)
        info["file_size"] = file_size
        return info

    info = dict(unknown)
    info["has_video"] = False
    info["has_audio"] = False
    info["previewable"] = False
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
    info["chapter_list"] = _chapter_list(payload.get("chapters"))
    info["start_time"] = _to_float(container_info.get("start_time"))

    audio_index = 0
    video_index = 0
    subtitle_index = 0
    # The singular video/audio fields describe the first stream of each kind; the lists hold all.
    for stream in streams:
        kind, name = stream.get("codec_type"), stream.get("codec_name")
        if kind == "video":
            if not info["has_video"]:
                info["previewable"] = not (stream.get("disposition") or {}).get("attached_pic")
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
        elif kind == "subtitle":
            info["subtitle_streams"].append(_describe_subtitle_stream(subtitle_index, stream))
            subtitle_index += 1
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
            packets = ffprobe_json("-read_intervals", interval, "-show_entries", "packet=pts_time,duration_time",
                                   path).get("packets") or []
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
        container = ffprobe_json("-show_entries", "format=duration,start_time", path).get("format") or {}
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
        transfer = run_tool("ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=color_transfer", "-of", "default=noprint_wrappers=1:nokey=1",
                            path).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        llamalog.get("probe").warning("Couldn't verify the output's colour tags for %s: %s", path, exc)
        return None
    return transfer not in _HDR_TRANSFERS if transfer else None


def _has_previewable_video(path):
    """True when `path` has a real video stream, not just cover art (an audio file with a cover
    keeps its Wave Loop)."""
    try:
        streams = ffprobe_json("-select_streams", "v:0", "-show_entries",
                               "stream=codec_type:stream_disposition=attached_pic", path).get("streams") or []
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        llamalog.get("probe").debug("Couldn't check %s for a real video stream: %s", path, exc)
        return False
    return bool(streams) and not (streams[0].get("disposition") or {}).get("attached_pic")
