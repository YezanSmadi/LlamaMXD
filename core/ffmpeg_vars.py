# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""One queued job's settings flattened into module variables for building its ffmpeg command.

`load()` fills them as the job starts, so they describe the job as it was queued, not the form
now. Read them through the module (`from core import ffmpeg_vars as v`; `v.INPUT_FILE`):
`from ... import NAME` copies the value once. Most come raw, as the UI shows them
(`ENCODER = "H.264"`), and as an ffmpeg-ready `*_ARG` (`VIDEO_CODEC_ARG = "libx264"`). A key
from the other tab keeps its default, so a Mux job's `VIDEO_CODEC_ARG` is "copy"."""

import os

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
#  The variables (defaults = "no job loaded")
# ---------------------------------------------------------------------- #

# --- Job ---
SOURCE_TAB = ""             # "Encoding" or "Muxing" — who queued this job

# --- Input file ---
INPUT_FILE = ""             # full path
INPUT_DIR = ""              # folder it lives in
INPUT_NAME = ""             # "clip.mkv"
INPUT_STEM = ""             # "clip"
INPUT_EXT = ""              # ".mkv" (lowercased)

# --- Output ---
OUTPUT_PATH = ""            # full path, as typed/browsed/auto-filled
OUTPUT_DIR = ""
OUTPUT_NAME = ""            # "clip_encoded.mp4"
OUTPUT_STEM = ""            # "clip_encoded"
OUTPUT_EXT = ""             # extension actually on OUTPUT_PATH
OUTPUT_FORMAT = ""          # dropdown value, ".mp4"; a hand-typed path's extension can differ

# --- Trim ---
START_SECS = 0              # int seconds
DURATION_SECS = 0           # int seconds; 0 means "to the end of the file"
END_SECS = None             # START_SECS + DURATION_SECS, or None when to-end
START_TIME = "00:00:00"     # the same three as HH:MM:SS
DURATION_TIME = "00:00:00"
END_TIME = None

# Never use END_TIME / END_SECS as an output-side -to: after an input-side -ss the output
# timeline starts at 0, so `-ss 00:21:36 -i in -to 00:21:41` makes a 21m41s clip. Pass both -ss
# and -to to the input, or (the default) an output-side -t duration.

# --- Stream presence ---
AV_SYNC = False             # align A/V start + pass through common metadata
STRIP_VIDEO = False         # -> -vn   (check before using any video value)
STRIP_AUDIO = False         # -> -an   (never both — the UI makes that unreachable)

# --- Encoding / Video ---
ENCODER = formats.SELECT    # "H.264", ... or "Select"
VIDEO_CODEC_ARG = "copy"    # -c:v   "libx264", ... or "copy"
PROFILE = ""                # "High 10", ... ("" when the codec has none)
PROFILE_ARG = None          # -profile:v   "high10", ... or None
LEVEL = ""                  # "4.0", ... ("" when the codec has none)
LEVEL_ARG = None            # -level:v   "4.0", ... or None
PIX_FMT_ARG = None          # -pix_fmt   "yuv422p10le", ... or None (see _PIX_FMT_ARGS)
QUALITY_PRESET_ARG = None   # -quality   "film3+", ... or None (CineForm only; see _QUALITY_PRESET_ARGS)
QUALITY = None              # slider value (int); None on a Mux job
QUALITY_KIND = None         # "crf" (-crf) / "qscale" (-q:v) / None on Select (QUALITY still set)
SPEED = ""                  # "fast", "4", ... ("" when the codec has none)
SPEED_ARG = {}              # {"preset": "fast"} / {"cpu-used": "4", "deadline": "good"} / {}
GPU_ENABLED = False         # the Settings tab's global GPU switch
HW_ENCODER = None           # hardware encoder id ("h264_nvenc") for ENCODER, else None (core.gpu)
HDR_TO_SDR = False          # HDRtoSDR switch
MASTERING_MAX_NITS = None   # the source's ST 2086 mastering peak (nits), snapshotted at queue time
MAX_CLL = None              # the source's MaxCLL; with a mastering peak, turns peak_detect off
RESOLUTION = formats.SOURCE_RESOLUTION   # "Source", "1080p", ... (formats.RESOLUTIONS)
SOURCE_HEIGHT = None        # the source's height (px), snapshotted at queue time
SCALE_VF = None             # -vf "scale=-2:<height>" for a real downscale, else None
FPS = formats.SOURCE_FPS    # "Source", "30", ... (formats.FPS_VALUES)
SOURCE_FPS = None           # the source's fps, snapshotted at queue time
FPS_ARG = None              # -r value for a real rate change, else None

# --- Encoding / Audio ---
# One entry per included audio stream, in output order ([] when stripped): {"src_index" (its
# index in its own file), "source"/"file" (primary or an external file), "codec_arg" ("copy"
# for Passthru), "bitrate_arg", "channels_arg", "sample_rate_arg" (None = omit), "language"
# (re-encoded streams only)}. Per-stream flags address the position in this list, not
# src_index: ffmpeg numbers `:a:N` over the output's streams.
AUDIO_STREAMS = []

# --- Muxing ---
VIDEO_TRACK = "Auto"
VIDEO_TRACK_INDEX = None
VIDEO_TRACK_FILE = ""
AUDIO_TRACK = "Auto"
AUDIO_TRACK_INDEX = None
AUDIO_TRACK_FILE = ""


# ---------------------------------------------------------------------- #
#  Loading
# ---------------------------------------------------------------------- #
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
    """Every variable above, from one task's settings dict, as `{NAME: value}`."""
    s = settings or {}

    input_file = s.get("input_file") or ""
    output_path = s.get("output_path") or ""
    in_dir, in_name, in_stem, in_ext = _split_path(input_file)
    out_dir, out_name, out_stem, out_ext = _split_path(output_path)

    start = int(s.get("start_secs") or 0)
    duration = int(s.get("duration_secs") or 0)
    end = start + duration if duration else None

    encoder = s.get("encoder") or formats.SELECT
    profile = s.get("profile") or ""
    level = s.get("level") or ""
    quality_spec = formats.quality_for(encoder)
    speed = s.get("speed") or ""
    gpu_enabled = bool(s.get("gpu_enabled"))
    # Hardware encoders have their own -preset vocabulary: omit it and use their default.
    hw_encoder = gpu.hw_encoder_for(encoder) if gpu_enabled else None
    video_codec_arg = hw_encoder or formats.VIDEO_ENCODERS.get(encoder, "copy")
    speed_arg = {} if hw_encoder else _speed_kwargs(encoder, speed)

    resolution = s.get("resolution") or formats.SOURCE_RESOLUTION
    source_height = s.get("source_height")
    scale_vf = _scale_vf(resolution, source_height)

    fps = s.get("fps") or formats.SOURCE_FPS
    source_fps = s.get("source_fps")
    fps_arg = _fps_arg(fps, source_fps)

    audio_streams = [_audio_stream_args(entry) for entry in (s.get("audio_streams") or [])]

    video_tracks = s.get("video_tracks") or []
    audio_tracks = s.get("audio_tracks") or []

    return {
        "SOURCE_TAB": source_tab,

        "INPUT_FILE": input_file,
        "INPUT_DIR": in_dir,
        "INPUT_NAME": in_name,
        "INPUT_STEM": in_stem,
        "INPUT_EXT": in_ext,

        "OUTPUT_PATH": output_path,
        "OUTPUT_DIR": out_dir,
        "OUTPUT_NAME": out_name,
        "OUTPUT_STEM": out_stem,
        "OUTPUT_EXT": out_ext,
        "OUTPUT_FORMAT": s.get("output_format") or "",

        "START_SECS": start,
        "DURATION_SECS": duration,
        "END_SECS": end,
        "START_TIME": _hms(start),
        "DURATION_TIME": _hms(duration),
        "END_TIME": _hms(end) if end is not None else None,

        "AV_SYNC": bool(s.get("av_sync")),
        "STRIP_VIDEO": bool(s.get("strip_video")),
        "STRIP_AUDIO": bool(s.get("strip_audio")),

        "ENCODER": encoder,
        "VIDEO_CODEC_ARG": video_codec_arg,
        "PROFILE": profile,
        "PROFILE_ARG": _profile_arg(encoder, profile),
        "LEVEL": level,
        "LEVEL_ARG": _LEVEL_ARGS.get(encoder, {}).get(level, level) or None,
        "PIX_FMT_ARG": _PIX_FMT_ARGS.get(encoder, {}).get(profile),
        "QUALITY_PRESET_ARG": _QUALITY_PRESET_ARGS.get(encoder, {}).get(profile),
        "QUALITY": int(s["quality"]) if s.get("quality") is not None else None,
        "QUALITY_KIND": quality_spec["kind"] if quality_spec else None,
        "SPEED": speed,
        "SPEED_ARG": speed_arg,
        "GPU_ENABLED": gpu_enabled,
        "HW_ENCODER": hw_encoder,
        "HDR_TO_SDR": bool(s.get("hdr_to_sdr")),
        "MASTERING_MAX_NITS": s.get("mastering_max_nits"),
        "MAX_CLL": s.get("max_cll"),
        "RESOLUTION": resolution,
        "SOURCE_HEIGHT": source_height,
        "SCALE_VF": scale_vf,
        "FPS": fps,
        "SOURCE_FPS": source_fps,
        "FPS_ARG": fps_arg,

        "AUDIO_STREAMS": audio_streams,

        # Each entry: {"source", "file", "index"}; index is 0-based among that file's own
        # streams of the kind (`-map <input>:v:<index>`).
        "VIDEO_TRACKS": video_tracks,
        "AUDIO_TRACKS": audio_tracks,
    }


def load(settings, source_tab=""):
    """Point every module variable at one job's values (`load({})` resets them). Called on
    the GUI thread as each job starts; one job runs at a time."""
    globals().update(derive(settings, source_tab))
