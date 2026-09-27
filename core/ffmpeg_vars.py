# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""One queued job's settings translated into what its ffmpeg command needs: `derive()` returns
a frozen `JobVars`, built when the job starts from the settings it was queued with (never the form
as it is now). Values are ffmpeg-ready (`video_codec_arg = "libx264"`); a key from the other tab
keeps its default, so a Mux job's `video_codec_arg` is "copy"."""

import os
from dataclasses import dataclass, field

from core import formats, gpu

# ---------------------------------------------------------------------- #
#  Translation tables: UI display value -> what ffmpeg takes
# ---------------------------------------------------------------------- #

# -profile:v values. libx264/libx265 take the profile name; the rest take libavcodec's
# AV_PROFILE_* number. VP9's profiles are already numbers and pass through.
_PROFILE_ARGS = {
    "H.264": {"High": "high", "Main": "main", "Baseline": "baseline", "High 10": "high10"},
    "H.265": {"Main": "main", "Main 10": "main10", "Main 12": "main12"},
    "MPEG-4": {"Simple": "0", "Advanced Simple": "15"},
    "MPEG-2": {"High": "1", "Main": "4", "Simple": "5"},
    "AV1": {"Main": "0", "High": "1", "Professional": "2"},
    # prores_ks's -profile:v takes these exact named strings.
    "ProRes": {"Proxy": "proxy", "LT": "lt", "422": "standard", "422 HQ": "hq",
               "4444": "4444", "4444 XQ": "4444xq"},
    # The same dnxhd encoder covers classic DNxHD and the DNxHR tiers.
    "DNxHR": {"LQ": "dnxhr_lq", "SQ": "dnxhr_sq", "HQ": "dnxhr_hq",
              "HQX": "dnxhr_hqx", "444": "dnxhr_444"},
}

# cfhd has no -profile:v: its Profile slot is its -quality ladder (_QUALITY_PRESET_ARGS).
_NO_PROFILE_FLAG = {"CineForm"}


def _profile_arg(encoder, profile):
    """-profile:v value for the Profile pick, or None. Falls through to the display value
    (VP9's are already numeric), except for `_NO_PROFILE_FLAG` encoders."""
    if encoder in _NO_PROFILE_FLAG:
        return None
    return _PROFILE_ARGS.get(encoder, {}).get(profile, profile) or None


# -pix_fmt for the intermediates: dnxhd refuses to run without a profile-legal one, and
# prores_ks / cfhd otherwise lock in their own default.
_PIX_FMT_ARGS = {
    "ProRes": {
        "Proxy": "yuv422p10le", "LT": "yuv422p10le", "422": "yuv422p10le",
        "422 HQ": "yuv422p10le", "4444": "yuv444p10le", "4444 XQ": "yuv444p10le",
    },
    "DNxHR": {
        "LQ": "yuv422p", "SQ": "yuv422p", "HQ": "yuv422p",
        "HQX": "yuv422p10le", "444": "yuv444p10le",
    },
    # cfhd's only 10-bit 4:2:2 format; every tier uses it.
    "CineForm": {p: "yuv422p10le" for p in formats.profiles_for("CineForm")},
}

# cfhd's -quality ladder, carried by the Profile dropdown (ffmpeg's default is "film3+").
_QUALITY_PRESET_ARGS = {
    "CineForm": {
        "Low": "low", "Low+": "low+", "Medium": "medium", "Medium+": "medium+",
        "High": "high", "High+": "high+", "Film 1": "film1", "Film 1+": "film1+",
        "Film 1.5": "film1.5", "Film 2": "film2", "Film 2+": "film2+",
        "Film 3": "film3", "Film 3+": "film3+",
    },
}

# -level:v values: as displayed ("4.0"), except MPEG-2's named levels. (libx265 takes its
# level through -x265-params.)
_LEVEL_ARGS = {
    "MPEG-2": {"Low": "10", "Main": "8", "High-1440": "6", "High": "4"},
}

_CHANNEL_COUNTS = {"Mono": 1, "Stereo": 2, "5.1": 6, "5.2": 7, "7.1": 8, "7.2": 9, "9.1": 10}

# ---------------------------------------------------------------------- #
#  The job
# ---------------------------------------------------------------------- #
@dataclass(frozen=True)
class JobVars:
    """One job's ffmpeg-ready values (the defaults describe "no job")."""
    source_tab: str = ""            # "Encoding" or "Muxing"
    input_file: str = ""
    output_path: str = ""
    output_ext: str = ""            # the extension actually on output_path, lowercased
    # Trim. Never use an end time as an output-side -to: after an input-side -ss the output starts
    # at 0, so `-ss 00:21:36 -i in -to 00:21:41` makes a 21m41s clip. -ss in, -t out.
    start_secs: int = 0
    duration_secs: int = 0          # 0 = to the end of the file
    start_time: str = "00:00:00"
    duration_time: str = "00:00:00"
    av_sync: bool = False
    strip_video: bool = False
    strip_audio: bool = False
    # Encoding / video
    video_codec_arg: str = "copy"   # -c:v (a hardware encoder id when the GPU path applies)
    profile_arg: str = None         # -profile:v
    level_arg: str = None           # -level:v
    pix_fmt_arg: str = None         # -pix_fmt (the intermediates only)
    quality_preset_arg: str = None  # -quality (CineForm only)
    quality: int = None             # the slider value
    quality_kind: str = None        # "crf" / "qscale" / None
    speed_arg: dict = field(default_factory=dict)   # {"preset": ...} / {"cpu-used": ..., "deadline": "good"}
    hw_encoder: str = None          # e.g. "h264_nvenc": decides the rate-control flags
    hdr_to_sdr: bool = False
    mastering_max_nits: float = None    # the source's, snapshotted at queue time
    max_cll: int = None
    scale_vf: str = None            # -vf "scale=-2:<height>" for a real downscale
    fps_arg: str = None             # -r for a real rate change
    # One entry per included audio stream, in output order: {"src_index" (its index in its own
    # file), "source"/"file", "codec_arg" ("copy" for Passthru), "bitrate_arg", "channels_arg",
    # "sample_rate_arg" (None = omit), "language" (re-encoded streams only)}. Per-stream flags
    # address the position in this list: ffmpeg numbers `:a:N` over the output's streams.
    audio_streams: list = field(default_factory=list)
    # Muxing: {"source", "file", "index"} per checked track; index is 0-based among that file's own
    # streams of the kind (`-map <input>:v:<index>`).
    video_tracks: list = field(default_factory=list)
    audio_tracks: list = field(default_factory=list)
    # Subtitles (both tabs), in output order: {"source", "file", "index" (among that file's
    # subtitle streams), "codec_arg" ("copy" or a conversion), "text_muxer" (a copy's own muxer
    # and extension, for a trimmed external text track), "language", "disposition", "start_time"
    # (an external file's own start, which ffmpeg would otherwise rebase to 0)}.
    subtitle_tracks: list = field(default_factory=list)
    strip_subtitles: bool = False
    # Encoding: the one track painted into the picture, {"source", "file", "index", "image",
    # "width", "height" (a picture format's canvas), "start_time"}, or None.
    burn_subtitle: dict = None
    source_width: int = None
    source_height: int = None
    source_start: float = 0.0       # the source's own first timestamp (a burned text track's timeline)
    # None: the source's chapters are left to ffmpeg (it shifts them with the trim). Else the
    # chapters to write, already trimmed: [{"start", "end", "title"}] in output seconds.
    chapters: list = None
    strip_chapters: bool = False
    source_has_chapters: bool = False


def _hms(total_seconds):
    """Seconds as HH:MM:SS."""
    hours, rest = divmod(int(total_seconds), 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _split_path(path):
    """`(dir, name, stem, ext)` for a path with either slash style."""
    path = path.replace("\\", "/")
    directory, name = os.path.split(path)
    stem, ext = os.path.splitext(name)
    return directory, name, stem, ext.lower()


def _audio_stream_args(entry):
    """One `audio_streams` entry (display values) -> its ffmpeg-ready dict. A Passthru stream
    (forced for DTS / TrueHD) is a plain copy, so bitrate / channels / rate are omitted."""
    codec = entry.get("codec") or formats.SELECT
    passthru = bool(entry.get("passthru")) or formats.is_passthru_only(codec)
    bitrate = entry.get("bitrate") or formats.SELECT
    channels = entry.get("channels") or formats.SELECT
    sample_rate = entry.get("sample_rate") or formats.SELECT
    return {
        "src_index": int(entry.get("index") or 0),
        "source": entry.get("source") or "primary",
        "file": entry.get("file"),
        "codec_arg": "copy" if passthru else formats.AUDIO_ENCODERS.get(codec, "copy"),
        "bitrate_arg": None if passthru else formats.bitrate_arg_for(bitrate),
        "channels_arg": None if passthru else _CHANNEL_COUNTS.get(channels),
        "sample_rate_arg": (
            None if passthru or sample_rate == formats.SELECT else int(sample_rate.split()[0])
        ),
        # Re-applied after a re-encoded stream's stale tags are wiped (a copy keeps its own).
        "language": None if passthru else entry.get("language"),
    }


def _disposition(entry):
    """`-disposition` for a subtitle entry: "default", "forced", both, or "0" (neither)."""
    flags = [flag for flag in ("default", "forced") if entry.get(flag)]
    return "+".join(flags) or "0"


def _subtitle_track_args(entry, container):
    """One settings-dict subtitle entry -> its ffmpeg-ready dict, or None when `container`
    can't carry it (the UI narrows the format so this doesn't happen)."""
    codec_name = entry.get("codec_name")
    codec_arg = formats.subtitle_codec_arg(container, codec_name)
    if codec_arg is None:
        return None
    return {
        "source": entry.get("source") or "primary",
        "file": entry.get("file"),
        "index": int(entry.get("index") or 0),
        "codec_arg": codec_arg,
        "text_muxer": formats.SUBTITLE_TEXT_MUXERS.get(codec_name),
        "language": formats.language_code(entry.get("language")),
        "disposition": _disposition(entry),
        "start_time": entry.get("start_time") or None,
    }


def _burn_args(entry):
    """The burn-in entry as the builder wants it, or None."""
    if not entry:
        return None
    return {
        "source": entry.get("source") or "primary",
        "file": entry.get("file"),
        "index": int(entry.get("index") or 0),
        "image": bool(entry.get("image")),
        "width": entry.get("width"),
        "height": entry.get("height"),
        "start_time": entry.get("start_time") or None,
    }


def _trimmed_chapters(chapters, duration, start, length):
    """The chapters to write, moved onto the output's timeline: each ends where the next starts
    (the last at `duration`), the trim's start is subtracted, and whatever falls outside
    [0, length] (length 0: to the end) is cut off or dropped. None stays None."""
    if chapters is None:
        return None
    ordered = sorted(chapters, key=lambda chapter: float(chapter.get("start") or 0))
    out = []
    for n, chapter in enumerate(ordered):
        begin = float(chapter.get("start") or 0)
        end = float(ordered[n + 1]["start"]) if n + 1 < len(ordered) else float(duration or begin)
        begin, end = begin - start, end - start
        if length:
            end = min(end, length)
        begin = max(begin, 0.0)
        if end - begin < 0.001:
            continue
        out.append({"start": round(begin, 3), "end": round(end, 3), "title": chapter.get("title") or ""})
    return out


def _scale_vf(resolution, source_height):
    """-vf value for a Resolution pick (`-2`: the width follows the aspect ratio, rounded
    even), or None for Source or no real downscale. Re-checks against the source height, since
    a preset applied to another file can name a rung above it."""
    target = formats.resolution_height_for(resolution)
    if not target or not source_height or target >= source_height:
        return None
    return f"scale=-2:{target}"


def _fps_arg(fps, source_fps):
    """-r value for an FPS pick, or None for Source or a rate above the source's (re-checked,
    like `_scale_vf`)."""
    target = formats.fps_arg_for(fps)
    if not target:
        return None
    if source_fps and formats.fps_number_for(fps) > source_fps + 0.1:
        return None
    return target


def _speed_kwargs(encoder, value):
    """SPEED as ffmpeg kwargs: a named -preset (x264/x265/AV1) or -cpu-used plus -deadline
    good (libvpx); {} when there is no speed knob."""
    kind = formats.speed_kind_for(encoder)
    if not value or kind is None:
        return {}
    if kind == "preset":
        return {"preset": value}
    return {"cpu-used": value, "deadline": "good"}


def derive(settings, source_tab=""):
    """The `JobVars` for one task's settings dict."""
    s = settings or {}
    output_path = s.get("output_path") or ""
    start = int(s.get("start_secs") or 0)
    duration = int(s.get("duration_secs") or 0)

    encoder = s.get("encoder") or formats.SELECT
    profile = s.get("profile") or ""
    level = s.get("level") or ""
    quality_spec = formats.quality_for(encoder)
    # Hardware encoders have their own -preset vocabulary: omit it and use their default.
    hw_encoder = gpu.hw_encoder_for(encoder) if s.get("gpu_enabled") else None

    return JobVars(
        source_tab=source_tab,
        input_file=s.get("input_file") or "",
        output_path=output_path,
        output_ext=_split_path(output_path)[3],
        start_secs=start,
        duration_secs=duration,
        start_time=_hms(start),
        duration_time=_hms(duration),
        av_sync=bool(s.get("av_sync")),
        strip_video=bool(s.get("strip_video")),
        strip_audio=bool(s.get("strip_audio")),
        video_codec_arg=hw_encoder or formats.VIDEO_ENCODERS.get(encoder, "copy"),
        profile_arg=_profile_arg(encoder, profile),
        level_arg=_LEVEL_ARGS.get(encoder, {}).get(level, level) or None,
        pix_fmt_arg=_PIX_FMT_ARGS.get(encoder, {}).get(profile),
        quality_preset_arg=_QUALITY_PRESET_ARGS.get(encoder, {}).get(profile),
        quality=int(s["quality"]) if s.get("quality") is not None else None,
        quality_kind=quality_spec["kind"] if quality_spec else None,
        speed_arg={} if hw_encoder else _speed_kwargs(encoder, s.get("speed") or ""),
        hw_encoder=hw_encoder,
        hdr_to_sdr=bool(s.get("hdr_to_sdr")),
        mastering_max_nits=s.get("mastering_max_nits"),
        max_cll=s.get("max_cll"),
        scale_vf=_scale_vf(s.get("resolution") or formats.SOURCE_RESOLUTION, s.get("source_height")),
        fps_arg=_fps_arg(s.get("fps") or formats.SOURCE_FPS, s.get("source_fps")),
        audio_streams=[_audio_stream_args(entry) for entry in (s.get("audio_streams") or [])],
        video_tracks=s.get("video_tracks") or [],
        audio_tracks=s.get("audio_tracks") or [],
        subtitle_tracks=[track for track in (
            _subtitle_track_args(entry, _split_path(output_path)[3]) for entry in (s.get("subtitle_tracks") or [])
        ) if track],
        strip_subtitles=bool(s.get("strip_subtitles")),
        burn_subtitle=None if s.get("strip_video") else _burn_args(s.get("burn_subtitle")),
        source_width=s.get("source_width"),
        source_height=s.get("source_height"),
        source_start=float(s.get("source_start") or 0.0),
        chapters=_trimmed_chapters(s.get("chapters"), s.get("source_duration"), start, duration),
        strip_chapters=bool(s.get("strip_chapters")),
        source_has_chapters=bool(s.get("source_has_chapters")),
    )
