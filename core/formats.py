# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Container <-> codec compatibility and the option cascade hanging off it. Pure data.

The option tree has one root, the output container: it decides the legal video and audio
codecs, and the video codec decides the profiles, levels and kind of quality control. Nothing
flows back, which makes an illegal combination unrepresentable. Muxing, which never
re-encodes, is the one inversion: `containers_for()` takes the source's codecs instead."""

# The one "nothing picked yet" placeholder in every derived list. Encoding resolves it from the
# probe; Encoder / Audio Codec left on it block the job, while Channels / Sample Rate / Bitrate
# just omit their flag ("follow the source").
SELECT = "Select"

# Display name -> ffmpeg encoder id.
VIDEO_ENCODERS = {
    "H.264": "libx264",
    "H.265": "libx265",
    "MPEG-4": "mpeg4",
    "MPEG-2": "mpeg2video",
    "VP8": "libvpx",
    "VP9": "libvpx-vp9",
    "AV1": "libsvtav1",
    "ProRes": "prores_ks",
    "DNxHR": "dnxhd",   # one encoder for classic DNxHD and DNxHR
    "FFV1": "ffv1",
    "CineForm": "cfhd",
}

AUDIO_ENCODERS = {
    "AAC": "aac",
    "AC3": "ac3",
    "E-AC-3": "eac3",
    "MP3": "libmp3lame",
    "FLAC": "flac",
    "Opus": "libopus",
    "Vorbis": "libvorbis",
    "ALAC": "alac",
    "PCM": "pcm_s16le",
}

# Probe-only codecs never offered in a dropdown: a track holding one always passes through.
PASSTHRU_ONLY_CODECS = {"DTS", "Dolby TrueHD"}


def is_passthru_only(codec):
    """Whether `codec` is probe-only and always passed through (DTS / Dolby TrueHD)."""
    return codec in PASSTHRU_ONLY_CODECS


# What each container can carry (WebM shares no video codec with mp4/mov).
_CONTAINERS = {
    ".mp4": {
        "video": ["H.264", "H.265", "MPEG-4", "MPEG-2", "AV1"],
        "audio": ["AAC", "AC3", "E-AC-3", "MP3", "ALAC"],
    },
    ".mkv": {
        "video": list(VIDEO_ENCODERS),
        "audio": list(AUDIO_ENCODERS),
    },
    ".mov": {
        # The native container for the three intermediates as well as the consumer codecs.
        "video": ["H.264", "H.265", "MPEG-4", "ProRes", "DNxHR", "CineForm"],
        "audio": ["AAC", "AC3", "E-AC-3", "ALAC", "PCM"],
    },
    ".webm": {
        "video": ["VP8", "VP9", "AV1"],
        "audio": ["Opus", "Vorbis"],
    },
}

# Per-encoder details. Empty `profiles` / `levels` mean the codec has none (the UI disables
# the dropdown). `quality` names the kind of rate control: MPEG-era encoders take a qscale.
_ENCODER_SPECS = {
    "H.264": {
        "profiles": ["High", "Main", "Baseline", "High 10"],
        "levels": ["3.0", "3.1", "4.0", "4.1", "4.2", "5.0", "5.1", "5.2"],
        "quality": {"kind": "crf", "label": "Quality (CRF)", "lo": 0, "hi": 51,
                    "default": 22, "low": "Low", "high": "Placebo"},
    },
    "H.265": {
        "profiles": ["Main", "Main 10", "Main 12"],
        "levels": ["3.1", "4.0", "4.1", "5.0", "5.1", "5.2", "6.0"],
        "quality": {"kind": "crf", "label": "Quality (CRF)", "lo": 0, "hi": 51,
                    "default": 28, "low": "Low", "high": "Placebo"},
    },
    "MPEG-4": {
        "profiles": ["Simple", "Advanced Simple"],
        "levels": [],
        "quality": {"kind": "qscale", "label": "Quality (qscale)", "lo": 1, "hi": 31,
                    "default": 5, "low": "Low", "high": "High"},
    },
    "MPEG-2": {
        "profiles": ["Simple", "Main", "High"],
        "levels": ["Low", "Main", "High-1440", "High"],
        "quality": {"kind": "qscale", "label": "Quality (qscale)", "lo": 1, "hi": 31,
                    "default": 5, "low": "Low", "high": "High"},
    },
    "VP8": {
        "profiles": [],
        "levels": [],
        "quality": {"kind": "crf", "label": "Quality (CRF)", "lo": 0, "hi": 63,
                    "default": 30, "low": "Low", "high": "Placebo"},
    },
    "VP9": {
        "profiles": ["0", "1", "2", "3"],
        "levels": [],
        "quality": {"kind": "crf", "label": "Quality (CRF)", "lo": 0, "hi": 63,
                    "default": 31, "low": "Low", "high": "Placebo"},
    },
    "AV1": {
        "profiles": ["Main", "High", "Professional"],
        "levels": ["4.0", "5.0", "5.1", "6.0"],
        "quality": {"kind": "crf", "label": "Quality (CRF)", "lo": 0, "hi": 63,
                    "default": 35, "low": "Low", "high": "Placebo"},
    },
    # The intermediates take no CRF / qscale: ProRes / DNxHR's quality is the profile tier,
    # FFV1 is lossless. `quality: None`, like SELECT, but the slider disables here rather
    # than staying live.
    "ProRes": {
        "profiles": ["Proxy", "LT", "422", "422 HQ", "4444", "4444 XQ"],
        "levels": [],
        "quality": None,
    },
    "DNxHR": {
        "profiles": ["LQ", "SQ", "HQ", "HQX", "444"],
        "levels": [],
        "quality": None,
    },
    "FFV1": {
        "profiles": [],
        "levels": [],
        "quality": None,
    },
    # CineForm's "profiles" are cfhd's -quality ladder (see ffmpeg_vars), worst -> best.
    "CineForm": {
        "profiles": ["Low", "Low+", "Medium", "Medium+", "High", "High+",
                     "Film 1", "Film 1+", "Film 1.5", "Film 2", "Film 2+",
                     "Film 3", "Film 3+"],
        "levels": [],
        "quality": None,
    },
    SELECT: {"profiles": [], "levels": [], "quality": None},
}

# x264/x265's named presets, stable across ffmpeg versions.
_X264_PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast",
                 "medium", "slow", "slower", "veryslow", "placebo"]

# Speed control per encoder: "preset" is a named -preset; "cpu-used" is libvpx's number, with
# a fixed -deadline good. Absent for MPEG-2/MPEG-4 and SELECT (the control disables).
_SPEED_SPECS = {
    "H.264": {"kind": "preset", "values": _X264_PRESETS, "default": "fast"},
    "H.265": {"kind": "preset", "values": _X264_PRESETS, "default": "fast"},
    # cpu-used's practical range (0 = slowest/best).
    "VP8": {"kind": "cpu-used", "values": [str(n) for n in range(6)], "default": "4"},
    "VP9": {"kind": "cpu-used", "values": [str(n) for n in range(9)], "default": "4"},
    # Only a fallback: SVT-AV1's range varies by build, and `speed_values_for`'s `av1_range`
    # (from core.utilities.av1_preset_range) replaces it.
    "AV1": {"kind": "preset", "values": [str(n) for n in range(9)], "default": "8"},
}


def speed_values_for(encoder, av1_range=None):
    """Speed values for `encoder`, slow to fast; empty when there is no speed knob. For AV1,
    `av1_range` `(lo, hi)` (the installed build's) replaces the static list."""
    if encoder == "AV1" and av1_range:
        lo, hi = av1_range
        return [str(n) for n in range(lo, hi + 1)]
    spec = _SPEED_SPECS.get(encoder)
    return list(spec["values"]) if spec else []


def speed_kind_for(encoder):
    """"preset" or "cpu-used" (see _SPEED_SPECS), or None when there is no speed knob."""
    spec = _SPEED_SPECS.get(encoder)
    return spec["kind"] if spec else None


def speed_default_for(encoder):
    """The encoder's own recommended default speed value, or None."""
    spec = _SPEED_SPECS.get(encoder)
    return spec["default"] if spec else None


# Encoding's optional downscale (a real re-encode through ffmpeg's scale filter). "Source" is
# a genuine choice, not a placeholder: it never blocks a job.
SOURCE_RESOLUTION = "Source"
RESOLUTIONS = [SOURCE_RESOLUTION, "2160p", "1440p", "1080p", "720p", "480p", "360p"]

# Target height for each rung; ffmpeg works out the width from the aspect ratio.
_RESOLUTION_HEIGHTS = {
    "2160p": 2160, "1440p": 1440, "1080p": 1080, "720p": 720, "480p": 480, "360p": 360,
}


def resolutions_for(source_height):
    """'Source' plus every rung at or below `source_height` (never an upscale); the full
    ladder when the height is unknown."""
    if not source_height:
        return list(RESOLUTIONS)
    return [SOURCE_RESOLUTION] + [
        r for r in RESOLUTIONS[1:] if _RESOLUTION_HEIGHTS[r] <= source_height
    ]


def resolution_height_for(resolution):
    """Target height for a Resolution pick, or None for 'Source' / unknown (no scaling)."""
    return _RESOLUTION_HEIGHTS.get(resolution)


# Encoding's optional frame-rate change: "Source" plus common rates, then 12 and 8 for
# deliberately choppy output.
SOURCE_FPS = "Source"
FPS_VALUES = [SOURCE_FPS, "120", "60", "59.94", "50", "48", "30", "29.97", "25", "24", "23.976", "12", "8"]

# The NTSC rates' -r values are the exact rationals: the rounded decimal would drift audio sync
# over a long file.
_FPS_ARGS = {"59.94": "60000/1001", "29.97": "30000/1001", "23.976": "24000/1001"}


def fps_values_for(source_fps):
    """'Source' plus every rate at or below `source_fps` (never a speed-up); 0.1 of tolerance
    keeps a 29.97 / 23.976 source's round 30 / 24. The full ladder when the rate is unknown."""
    if not source_fps:
        return list(FPS_VALUES)
    return [SOURCE_FPS] + [f for f in FPS_VALUES[1:] if fps_number_for(f) <= source_fps + 0.1]


def fps_arg_for(fps):
    """ffmpeg -r value for an FPS pick (NTSC as "24000/1001"), or None for 'Source'."""
    if not fps or fps == SOURCE_FPS:
        return None
    return _FPS_ARGS.get(fps, fps)


def fps_number_for(fps):
    """An FPS pick as a float, for comparing with a probed rate (`float("24000/1001")` doesn't
    parse); None for 'Source'."""
    arg = fps_arg_for(fps)
    if arg is None:
        return None
    if "/" in arg:
        numerator, denominator = arg.split("/")
        return int(numerator) / int(denominator)
    return float(arg)


# Bitrate ladder in kbps; 1024 / 1536 so they display as a clean "1 Mbps" / "1.5 Mbps".
_AUDIO_BITRATE_KBPS = [96, 128, 192, 256, 320, 384, 448, 512, 640, 768, 1024, 1536]


def _format_bitrate(kbps):
    """kbps -> "<n> kbps", or "<n> Mbps" from 1024 up."""
    if kbps >= 1024:
        mbps = kbps / 1024
        return f"{mbps:g} Mbps"
    return f"{kbps} kbps"


# The dropdown's values are these display strings; `bitrate_arg_for` turns one into "<n>k".
AUDIO_BITRATES = [_format_bitrate(kbps) for kbps in _AUDIO_BITRATE_KBPS]

_BITRATE_KBPS_BY_DISPLAY = dict(zip(AUDIO_BITRATES, _AUDIO_BITRATE_KBPS))

AUDIO_CHANNELS = [SELECT, "Mono", "Stereo", "5.1", "5.2", "7.1", "7.2", "9.1"]
AUDIO_SAMPLE_RATES = [SELECT, "44100 Hz", "48000 Hz", "96000 Hz"]

# Lossless codecs (PCM included) have no bitrate: the Bitrate dropdown says "Lossless".
LOSSLESS = "Lossless"
LOSSLESS_AUDIO = {"FLAC", "ALAC", "PCM"}

# Codecs whose rate isn't ours to set (lossless, or nothing picked).
_FIXED_RATE_AUDIO = {SELECT} | LOSSLESS_AUDIO


def is_lossless_audio(codec):
    """Whether `codec` is one of the lossless audio codecs (no bitrate to set)."""
    return codec in LOSSLESS_AUDIO


def probed_audio_is_lossless(codec_name, profile=None):
    """Whether a probed audio stream is lossless, from ffprobe's `codec_name` / `profile`: any
    PCM, TrueHD / MLP, and DTS-HD MA (the DTS core and DTS-HD HRA are lossy)."""
    name = (codec_name or "").lower()
    if name in ("flac", "alac", "truehd", "mlp") or name.startswith("pcm_"):
        return True
    if name == "dts":
        return "MA" in (profile or "").upper().split()   # "DTS-HD MA [+ DTS:X]", not "DTS-HD HRA"
    return False

# Probed channel count -> option name (the reverse of ffmpeg_vars._CHANNEL_COUNTS). No match
# (5.1.2, ...) leaves Channels on SELECT.
_CHANNEL_NAMES = {1: "Mono", 2: "Stereo", 6: "5.1", 7: "5.2", 8: "7.1", 9: "7.2", 10: "9.1"}


def channels_display_for(count):
    """Display name for a probed channel count (2 -> "Stereo"), or None."""
    return _CHANNEL_NAMES.get(count)


def sample_rate_display_for(hz):
    """Display name for a probed sample rate (48000 -> "48000 Hz") if offered, else None."""
    display = f"{hz} Hz"
    return display if display in AUDIO_SAMPLE_RATES else None


def bitrate_display_for(bps):
    """A probed bit rate snapped to the closest AUDIO_BITRATES entry (231000 -> "256 kbps"):
    a real source's never lands on a round number. None only for an unusable `bps`."""
    if not bps or bps <= 0:
        return None
    kbps = bps / 1000
    closest = min(_AUDIO_BITRATE_KBPS, key=lambda k: abs(k - kbps))
    return _format_bitrate(closest)


def bitrate_arg_for(display):
    """`-b:a` value ("96k") for a bitrate display text ("96 kbps"), or None."""
    kbps = _BITRATE_KBPS_BY_DISPLAY.get(display)
    return f"{kbps}k" if kbps is not None else None


# ffprobe codec_name -> display name. Unmapped codecs stay None ("constrains nothing").
FFPROBE_VIDEO = {
    "h264": "H.264", "hevc": "H.265", "mpeg4": "MPEG-4",
    "mpeg2video": "MPEG-2", "vp8": "VP8", "vp9": "VP9", "av1": "AV1",
    "prores": "ProRes",
    "dnxhd": "DNxHR",   # classic DNxHD too; the profile tells them apart
    "cfhd": "CineForm",
    "ffv1": "FFV1",
}
FFPROBE_AUDIO = {
    "aac": "AAC", "ac3": "AC3", "eac3": "E-AC-3", "mp3": "MP3", "flac": "FLAC",
    "opus": "Opus", "vorbis": "Vorbis", "alac": "ALAC",
    "pcm_s16le": "PCM", "pcm_s24le": "PCM", "pcm_f32le": "PCM",
    "dts": "DTS", "truehd": "Dolby TrueHD",
}


# Extensions treated as audio-only when there is no probe (picks the Wave Loop, nothing else).
AUDIO_EXTENSIONS = {
    ".mp3", ".m4a", ".aac", ".flac", ".wav", ".opus", ".ogg", ".oga",
    ".wma", ".aiff", ".aif", ".alac", ".ac3", ".mka", ".weba",
}


def containers():
    """Every output container the app offers, in menu order."""
    return list(_CONTAINERS)


def video_codecs_for(container):
    """Legal video codecs for `container`, SELECT first (unknown container: Matroska's)."""
    spec = _CONTAINERS.get(container, _CONTAINERS[".mkv"])
    return [SELECT] + list(spec["video"])


def audio_codecs_for(container):
    """Legal audio codecs for `container`, SELECT first."""
    spec = _CONTAINERS.get(container, _CONTAINERS[".mkv"])
    return [SELECT] + list(spec["audio"])


def profiles_for(encoder):
    """Profile names for `encoder`; empty when it has none or nothing is picked."""
    return list(_ENCODER_SPECS.get(encoder, _ENCODER_SPECS[SELECT])["profiles"])


def levels_for(encoder):
    """Level names for `encoder`; empty where it has none. Never shared between codecs."""
    return list(_ENCODER_SPECS.get(encoder, _ENCODER_SPECS[SELECT])["levels"])


def quality_for(encoder):
    """The rate-control spec for `encoder` (kind, label, range, default, end labels), or
    None."""
    spec = _ENCODER_SPECS.get(encoder, _ENCODER_SPECS[SELECT])["quality"]
    return dict(spec) if spec else None


def audio_bitrates_for(codec):
    """Bitrate choices for `codec`, SELECT first; empty for lossless codecs and SELECT."""
    return [] if codec in _FIXED_RATE_AUDIO else [SELECT] + list(AUDIO_BITRATES)


def containers_for(video_codec, audio_codec):
    """The Muxing inversion: the containers a source with these codecs can be remuxed into.
    A None codec (unknown / absent) constrains nothing."""
    out = []
    for name, spec in _CONTAINERS.items():
        if video_codec and video_codec not in spec["video"]:
            continue
        if audio_codec and audio_codec not in spec["audio"]:
            continue
        out.append(name)
    return out or list(_CONTAINERS)


def short_name(codec):
    """The codec name without a parenthetical suffix (no current codec has one)."""
    return (codec or "").split(" (")[0]


def coerce(value, allowed, fallback=None):
    """Snap `value` into `allowed`; returns `(value, changed)`."""
    if not allowed:
        return fallback, False
    if value in allowed:
        return value, False
    return (fallback if fallback in allowed else allowed[0]), True
