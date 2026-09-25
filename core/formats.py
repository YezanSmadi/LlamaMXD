# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Container <-> codec compatibility, and the option cascade hanging off it.

The Encoding/Muxing option tree has exactly one root: the **output
container**. It decides which video and audio codecs are legal; the chosen
video codec then decides which profiles and levels exist, and what kind of
quality control applies (CRF vs qscale) over what range. Nothing ever flows
the other way -- a codec never re-filters the container list. That
one-directional rule is what makes illegal combinations *unrepresentable*
rather than something a validation dialog has to catch later.

The one inversion is Muxing, which never re-encodes: there the *source's*
existing codecs decide which containers it can be remuxed into, so
`containers_for()` runs the filter backwards.

`SELECT` is the one placeholder in every codec/channel/rate/bitrate list --
"nothing picked yet". It's the default until a file is probed, at which
point EncodingTab auto-resolves each control (Encoder, Audio Codec, Profile,
Level, Audio Channels, Audio Sample Rate, Audio Bitrate) to whatever the
source already has -- never a silent stream copy, that's Muxing's job.
`Encoder`/`Audio Codec` left on `SELECT` blocks the job in
`_validate_settings` (there's no valid command without a real codec);
Channels/Sample Rate/Bitrate don't need that -- omitting `-ac`/`-ar`/`-b:a`
is always a valid, sensible "follow the source" outcome, so those simply
stay unresolved rather than blocking anything. Always legal in every
container as far as the UI can tell -- only a probe of the actual input
(`core.utilities.probe_media`) can say otherwise, which is what feeds
`containers_for`.

Pure data + lookups; no UI code in here.
"""

# The one "nothing picked/resolved yet" placeholder, shared by every derived
# list in this module (video/audio codec, audio channels, sample rate,
# bitrate). EncodingTab auto-resolves it from `core.utilities.probe_media`
# the moment a file's probed; see the module docstring for which controls
# additionally block the job while still on it.
SELECT = "Select"

# Display name -> ffmpeg encoder id. The ids aren't called yet (there's no
# real pipeline), but this is the natural place for the mapping to live so
# the eventual subprocess builder has one lookup rather than a scattered
# pile of if/elif.
VIDEO_ENCODERS = {
    "H.264": "libx264",
    "H.265": "libx265",
    "MPEG-4": "mpeg4",
    "MPEG-2": "mpeg2video",
    "VP8": "libvpx",
    "VP9": "libvpx-vp9",
    "AV1": "libsvtav1",
    "ProRes": "prores_ks",
    "DNxHR": "dnxhd",   # ffmpeg's dnxhd encoder covers both classic DNxHD and DNxHR
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

# Codecs `probe_media` can identify but this app will never offer through a
# dropdown -- DTS and Dolby TrueHD have no re-encode path here (freely
# transcoding surround/Atmos codecs is out of scope), so a track holding one
# always passes through untouched instead. EncodingTab auto-forces Passthru
# and greys every audio control the moment one of these is probed (see
# EncodingTab._auto_select_audio_streams / _sync_controls) rather than
# leaving it unresolved on SELECT the way a codec this app just doesn't
# recognize would.
PASSTHRU_ONLY_CODECS = {"DTS", "Dolby TrueHD"}


def is_passthru_only(codec):
    """Whether `codec` is a probe-only, always-passthrough codec (DTS /
    Dolby TrueHD) -- never selectable via a dropdown, never re-encoded."""
    return codec in PASSTHRU_ONLY_CODECS


# What each container can actually carry. WebM is the reason this table has
# to exist at all: it shares *no* video codec with mp4/mov, so before this
# existed, picking .webm left every entry in the encoder list illegal.
_CONTAINERS = {
    ".mp4": {
        "video": ["H.264", "H.265", "MPEG-4", "MPEG-2", "AV1"],
        "audio": ["AAC", "AC3", "E-AC-3", "MP3", "ALAC"],
    },
    ".mkv": {
        # Matroska is the permissive catch-all -- every real encoder this app has.
        "video": list(VIDEO_ENCODERS),
        "audio": list(AUDIO_ENCODERS),
    },
    ".mov": {
        # QuickTime is the native/canonical delivery container for all three
        # professional intermediates (ProRes, DNxHR, CineForm) as well as
        # this app's existing consumer codecs.
        "video": ["H.264", "H.265", "MPEG-4", "ProRes", "DNxHR", "CineForm"],
        "audio": ["AAC", "AC3", "E-AC-3", "ALAC", "PCM"],
    },
    ".webm": {
        "video": ["VP8", "VP9", "AV1"],
        "audio": ["Opus", "Vorbis"],
    },
}

# Per-encoder detail options. `profiles`/`levels` are empty where the codec
# has no such concept (VP8 profiles, VP9/MPEG-4 levels) -- the UI disables
# the dropdown rather than offering meaningless values borrowed from H.264.
# `quality` names the *kind* of rate control, because CRF is not universal:
# the MPEG-era encoders take a qscale on a completely different scale.
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
    # The three mezzanine/archival intermediates -- none of them take a CRF
    # or qscale: ProRes/DNxHR's "quality" IS the profile choice (each is a
    # fixed target bitrate/quality tier), and FFV1 is lossless, so there's
    # nothing left to rate-control. `quality: None` here means the same
    # thing it does for SELECT -- see EncodingTab._sync_controls, which
    # additionally has to distinguish "nothing picked yet" (slider stays
    # live) from "this codec genuinely has no such knob" (slider disables).
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
    # CineForm's "profile" is really a quality-preset ladder (ffmpeg's cfhd
    # encoder takes it as -quality, not -profile:v -- see
    # ffmpeg_vars._QUALITY_PRESET_ARGS/_NO_PROFILE_FLAG), so it's modeled the
    # same way ProRes/DNxHR's profile-as-quality already is: no separate CRF/
    # qscale slider, the profile choice IS the quality choice. Ascending
    # worst -> best, matching GoPro's own naming and this app's ProRes/DNxHR
    # convention.
    "CineForm": {
        "profiles": ["Low", "Low+", "Medium", "Medium+", "High", "High+",
                     "Film 1", "Film 1+", "Film 1.5", "Film 2", "Film 2+",
                     "Film 3", "Film 3+"],
        "levels": [],
        "quality": None,
    },
    # Nothing picked yet: there is nothing to configure.
    SELECT: {"profiles": [], "levels": [], "quality": None},
}

# x264/x265's preset ladder -- stable across ffmpeg's history (unlike a
# numeric scale such as SVT-AV1's, whose ceiling varies a lot by build; see
# AV1 below), and every encoding tool's users already know this vocabulary,
# so it's shown as-is rather than abstracted into a generic slider.
_X264_PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast",
                 "medium", "slow", "slower", "veryslow", "placebo"]

# Per-encoder speed control. `kind` says what the raw value means:
# "preset" -> a named -preset value passed straight through; "cpu-used" ->
# libvpx's numeric -cpu-used, paired with a fixed -deadline good (see
# ffmpeg_vars._speed_kwargs). Absent entirely for MPEG-2/MPEG-4 (no speed
# knob) and SELECT (nothing picked yet) -- same convention as the profiles/
# levels lists above; the UI disables the control rather than offering
# meaningless values.
_SPEED_SPECS = {
    "H.264": {"kind": "preset", "values": _X264_PRESETS, "default": "fast"},
    "H.265": {"kind": "preset", "values": _X264_PRESETS, "default": "fast"},
    # cpu-used's *practical* range (0 = best/slowest, higher = faster) --
    # not this build's reported raw min/max (libvpx accepts far wider, but
    # values past this are rarely used/documented).
    "VP8": {"kind": "cpu-used", "values": [str(n) for n in range(6)], "default": "4"},
    "VP9": {"kind": "cpu-used", "values": [str(n) for n in range(9)], "default": "4"},
    # SVT-AV1's preset ceiling varies a lot by ffmpeg build -- confirmed
    # firsthand (0-8 on one install, -2 to 13 after updating ffmpeg on the
    # same machine). This static list is only the fallback for when a live
    # probe isn't available; speed_values_for's `av1_range` param (fed by
    # core.utilities.av1_preset_range(), a UI-layer concern -- this module
    # stays subprocess-free) overrides it with the installed build's own
    # reported range.
    "AV1": {"kind": "preset", "values": [str(n) for n in range(9)], "default": "8"},
}


def speed_values_for(encoder, av1_range=None):
    """Speed-control values for `encoder`, slow-to-fast -- empty when the
    codec has no speed knob (MPEG-2/MPEG-4) or nothing's picked yet.

    `av1_range`, an optional `(lo, hi)`, overrides AV1's static fallback
    list with the installed ffmpeg's own reported preset range (see
    `core.utilities.av1_preset_range` for why this can't be a fixed list) --
    ignored for every other encoder."""
    if encoder == "AV1" and av1_range:
        lo, hi = av1_range
        return [str(n) for n in range(lo, hi + 1)]
    spec = _SPEED_SPECS.get(encoder)
    return list(spec["values"]) if spec else []


def speed_kind_for(encoder):
    """"preset" or "cpu-used" (see _SPEED_SPECS), or None when the codec has
    no speed knob at all."""
    spec = _SPEED_SPECS.get(encoder)
    return spec["kind"] if spec else None


def speed_default_for(encoder):
    """The encoder's own recommended default speed value, or None."""
    spec = _SPEED_SPECS.get(encoder)
    return spec["default"] if spec else None


# Encoding / Video sub-tab's optional downscale. Unlike the Downloader's own
# Quality dropdown (core/downloader.py), which just picks among streams
# YouTube already encoded at each size, a local input has exactly one
# resolution -- picking one of these actually re-encodes at a smaller size
# via ffmpeg's scale filter (see ffmpeg_vars._scale_vf) rather than choosing
# among files that already exist at that size. "Source" (no scaling at all)
# is a genuine, permanent choice here, not a placeholder -- unlike SELECT, it
# never auto-resolves to something else and never blocks a job.
SOURCE_RESOLUTION = "Source"
RESOLUTIONS = [SOURCE_RESOLUTION, "2160p", "1440p", "1080p", "720p", "480p", "360p"]

# Target *height* in pixels for each rung -- ffmpeg's scale filter computes
# the matching width itself from the source's own aspect ratio, which is what
# actually keeps it intact rather than this module trying to precompute both
# dimensions.
_RESOLUTION_HEIGHTS = {
    "2160p": 2160, "1440p": 1440, "1080p": 1080, "720p": 720, "480p": 480, "360p": 360,
}


def resolutions_for(source_height):
    """Resolution ladder for a probed source height, capped so a pick can
    never *upscale* -- 'Source' plus every standard rung at or below the
    source's own height. An unknown height (no probe yet, or one that
    couldn't read it) offers the full ladder rather than guessing a cap."""
    if not source_height:
        return list(RESOLUTIONS)
    return [SOURCE_RESOLUTION] + [
        r for r in RESOLUTIONS[1:] if _RESOLUTION_HEIGHTS[r] <= source_height
    ]


def resolution_height_for(resolution):
    """Target pixel height for a Resolution pick, or None for 'Source' /
    anything unrecognized -- the "no scaling" case."""
    return _RESOLUTION_HEIGHTS.get(resolution)


# Encoding / Video sub-tab's optional frame-rate change, alongside
# Resolution -- "Source" (no change) plus a fixed ladder of common rates:
# the broadcast and cinema standards, the three NTSC ones among them
# (23.976 / 29.97 / 59.94), then 12 and 8 for deliberately choppy output.
SOURCE_FPS = "Source"
FPS_VALUES = [SOURCE_FPS, "120", "60", "59.94", "50", "48", "30", "29.97", "25", "24", "23.976", "12", "8"]

# The NTSC rates are 24000/1001 etc., not 23.976 -- typing the rounded decimal
# into ffmpeg's -r would retime a true NTSC source a hair off, drifting audio
# sync over a long file -- so their `-r` value is the exact rational. Every
# other rung is its own value.
_FPS_ARGS = {"59.94": "60000/1001", "29.97": "30000/1001", "23.976": "24000/1001"}


def fps_values_for(source_fps):
    """FPS ladder for a probed source frame rate, capped so a pick can never
    *upsample* -- 'Source' plus every standard rate at or below the source's
    own. A small tolerance (0.1) keeps a true 29.97/23.976 source from
    excluding the round 30/24 sitting just above it. An unknown rate (no
    probe yet) offers the full ladder rather than guessing a cap."""
    if not source_fps:
        return list(FPS_VALUES)
    return [SOURCE_FPS] + [f for f in FPS_VALUES[1:] if fps_number_for(f) <= source_fps + 0.1]


def fps_arg_for(fps):
    """ffmpeg -r value for an FPS pick, or None for 'Source' -- the "no
    change" case. The NTSC rates come back as their exact rational
    ("24000/1001"), which -r accepts."""
    if not fps or fps == SOURCE_FPS:
        return None
    return _FPS_ARGS.get(fps, fps)


def fps_number_for(fps):
    """An FPS pick as a plain float (23.976023...), for comparing against a
    probed rate; None for 'Source'. (`float("24000/1001")` doesn't parse, so
    callers that used to `float()` the -r value need this.)"""
    arg = fps_arg_for(fps)
    if arg is None:
        return None
    if "/" in arg:
        numerator, denominator = arg.split("/")
        return int(numerator) / int(denominator)
    return float(arg)


# Canonical bitrate ladder in kbps -- 1024/1536 rather than round 1000/1500
# are deliberate: both are exact multiples of 1024, so `_format_bitrate`'s
# kbps->Mbps conversion below lands on a clean "1 Mbps"/"1.5 Mbps" rather
# than a display like "1.024 Mbps".
_AUDIO_BITRATE_KBPS = [96, 128, 192, 256, 320, 384, 448, 512, 640, 768, 1024, 1536]


def _format_bitrate(kbps):
    """kbps -> display text: "<n> kbps" below 1 Mbps (1024 kbps), else
    "<n> Mbps" -- every AUDIO_BITRATES entry at or above that threshold is an
    exact multiple of 1024, so the division is always a clean value."""
    if kbps >= 1024:
        mbps = kbps / 1024
        return f"{mbps:g} Mbps"
    return f"{kbps} kbps"


# The dropdown's own values are these display strings directly (same
# "value is the display text" convention every other derived dropdown in
# this app follows, e.g. Audio Channels' "Stereo", Sample Rate's "48000 Hz")
# -- ffmpeg_vars.bitrate_arg_for is what turns one back into an ffmpeg-ready
# "<n>k" argument at the point it's actually needed.
AUDIO_BITRATES = [_format_bitrate(kbps) for kbps in _AUDIO_BITRATE_KBPS]

# display text -> the kbps it came from, for bitrate_arg_for's reverse lookup.
_BITRATE_KBPS_BY_DISPLAY = dict(zip(AUDIO_BITRATES, _AUDIO_BITRATE_KBPS))

AUDIO_CHANNELS = [SELECT, "Mono", "Stereo", "5.1", "5.2", "7.1", "7.2", "9.1"]
AUDIO_SAMPLE_RATES = [SELECT, "44100 Hz", "48000 Hz", "96000 Hz"]

# Codecs that are lossless (PCM is uncompressed, which is lossless too): they
# have no bitrate to set, so the Bitrate dropdown says "Lossless" for them
# rather than the "—" it shows when there is simply nothing to pick yet.
LOSSLESS = "Lossless"
LOSSLESS_AUDIO = {"FLAC", "ALAC", "PCM"}

# Codecs whose rate isn't ours to set (lossless, or nothing picked yet) --
# offering a bitrate dropdown alongside them would be a dead control.
_FIXED_RATE_AUDIO = {SELECT} | LOSSLESS_AUDIO


def is_lossless_audio(codec):
    """Whether `codec` is one of the lossless audio codecs (no bitrate to set)."""
    return codec in LOSSLESS_AUDIO


def probed_audio_is_lossless(codec_name, profile=None):
    """Whether a *probed* audio stream is lossless, from ffprobe's own
    `codec_name` / `profile`. Wider than `is_lossless_audio`: that answers for
    the codecs this app can encode to, while a source can also hold Dolby
    TrueHD / MLP (always lossless) or DTS. DTS is the one that needs the
    profile -- the core stream and DTS-HD High Resolution are lossy, and only
    DTS-HD Master Audio ("DTS-HD MA") is lossless. Any PCM variant counts."""
    name = (codec_name or "").lower()
    if name in ("flac", "alac", "truehd", "mlp") or name.startswith("pcm_"):
        return True
    if name == "dts":
        return "MA" in (profile or "").upper().split()   # "DTS-HD MA [+ DTS:X]", not "DTS-HD HRA"
    return False

# Reverse of ffmpeg_vars._CHANNEL_COUNTS -- a probed channel count this app
# has a named option for. Anything else (5.1.2, ...) has no match, so
# auto-fill leaves Audio Channels on SELECT rather than guessing.
_CHANNEL_NAMES = {1: "Mono", 2: "Stereo", 6: "5.1", 7: "5.2", 8: "7.1", 9: "7.2", 10: "9.1"}


def channels_display_for(count):
    """Display name for a probed channel count (`2` -> "Stereo"), or None
    when this app has no option for it -- used by EncodingTab's auto-fill,
    same spirit as FFPROBE_VIDEO/FFPROBE_AUDIO's codec-name mapping."""
    return _CHANNEL_NAMES.get(count)


def sample_rate_display_for(hz):
    """Display name for a probed sample rate in Hz (`48000` -> "48000 Hz"),
    or None when it isn't one of this app's offered rates."""
    display = f"{hz} Hz"
    return display if display in AUDIO_SAMPLE_RATES else None


def bitrate_display_for(bps):
    """Display name for a probed bit rate in bits/sec, snapped to the
    *closest* entry in AUDIO_BITRATES (`231000` -> "256 kbps") -- unlike a
    codec name or a sample rate, a real source's bitrate essentially never
    lands exactly on one of those round numbers, so this rounds rather than
    requiring an exact match. None only when `bps` itself is unusable."""
    if not bps or bps <= 0:
        return None
    kbps = bps / 1000
    closest = min(_AUDIO_BITRATE_KBPS, key=lambda k: abs(k - kbps))
    return _format_bitrate(closest)


def bitrate_arg_for(display):
    """The ffmpeg-ready `-b:a` value ("96k") for a bitrate dropdown's display
    text ("96 kbps"/"1 Mbps") -- the inverse of AUDIO_BITRATES' own kbps ->
    display formatting. None for SELECT or anything else unrecognized."""
    kbps = _BITRATE_KBPS_BY_DISPLAY.get(display)
    return f"{kbps}k" if kbps is not None else None



# ffprobe codec_name -> our display name, for probe_media's output. Only the
# codecs this app can name are mapped; anything else stays None (unknown),
# which every consumer treats as "constrains nothing".
FFPROBE_VIDEO = {
    "h264": "H.264", "hevc": "H.265", "mpeg4": "MPEG-4",
    "mpeg2video": "MPEG-2", "vp8": "VP8", "vp9": "VP9", "av1": "AV1",
    "prores": "ProRes",
    "dnxhd": "DNxHR",   # ffprobe reports "dnxhd" for classic DNxHD too -- the
                        # `profile` field ("DNxHR HQX" vs. plain "DNxHD") is
                        # what actually distinguishes them (see
                        # core.utilities._normalize_video_profile).
    "cfhd": "CineForm",
    "ffv1": "FFV1",
}
FFPROBE_AUDIO = {
    "aac": "AAC", "ac3": "AC3", "eac3": "E-AC-3", "mp3": "MP3", "flac": "FLAC",
    "opus": "Opus", "vorbis": "Vorbis", "alac": "ALAC",
    "pcm_s16le": "PCM", "pcm_s24le": "PCM", "pcm_f32le": "PCM",
    # Passthru-only -- see PASSTHRU_ONLY_CODECS/is_passthru_only above.
    "dts": "DTS", "truehd": "Dolby TrueHD",
}


# Input file extensions the app treats as audio-only when a probe can't be
# run (no ffmpeg) or comes back blank. Only used to decide the preview shows
# the Wave Loop visualiser instead of video thumbnails — nothing downstream
# keys off it.
AUDIO_EXTENSIONS = {
    ".mp3", ".m4a", ".aac", ".flac", ".wav", ".opus", ".ogg", ".oga",
    ".wma", ".aiff", ".aif", ".alac", ".ac3", ".mka", ".weba",
}


def containers():
    """Every output container the app offers, in menu order."""
    return list(_CONTAINERS)


def video_codecs_for(container):
    """Legal video codecs for `container`, SELECT first. An unknown
    container falls back to the permissive Matroska set."""
    spec = _CONTAINERS.get(container, _CONTAINERS[".mkv"])
    return [SELECT] + list(spec["video"])


def audio_codecs_for(container):
    """Legal audio codecs for `container`, SELECT first."""
    spec = _CONTAINERS.get(container, _CONTAINERS[".mkv"])
    return [SELECT] + list(spec["audio"])


def profiles_for(encoder):
    """Profile names for `encoder` -- empty when the codec has no profiles
    to pick (VP8), or when nothing's been picked yet."""
    return list(_ENCODER_SPECS.get(encoder, _ENCODER_SPECS[SELECT])["profiles"])


def levels_for(encoder):
    """Level names for `encoder` -- empty where the codec has no levels
    (VP8/VP9/MPEG-4). Deliberately *not* shared between codecs: '4.0' means
    different things to H.264 and H.265."""
    return list(_ENCODER_SPECS.get(encoder, _ENCODER_SPECS[SELECT])["levels"])


def quality_for(encoder):
    """The rate-control spec for `encoder` (kind/label/range/default/end
    labels), or None when there's nothing to control (nothing picked yet)."""
    spec = _ENCODER_SPECS.get(encoder, _ENCODER_SPECS[SELECT])["quality"]
    return dict(spec) if spec else None


def audio_bitrates_for(codec):
    """Bitrate choices for `codec`, SELECT first -- empty (no SELECT either)
    for lossless/copy codecs, where a bitrate dropdown would be a dead
    control regardless of what's picked."""
    return [] if codec in _FIXED_RATE_AUDIO else [SELECT] + list(AUDIO_BITRATES)


def containers_for(video_codec, audio_codec):
    """**The Muxing inversion.** Given the codecs a source file actually
    holds, which containers can it be remuxed into without re-encoding?
    A `None` codec means "unknown, or no such stream" and constrains
    nothing, so an unprobed file still offers every container."""
    out = []
    for name, spec in _CONTAINERS.items():
        if video_codec and video_codec not in spec["video"]:
            continue
        if audio_codec and audio_codec not in spec["audio"]:
            continue
        out.append(name)
    return out or list(_CONTAINERS)


def short_name(codec):
    """Display name without a parenthetical library suffix, if it has one
    (no current codec does — "H.264 (x264)"/"H.265 (x265)" were shortened to
    plain "H.264"/"H.265" — but the Overview rundown has very little width
    to spend, so this stays as a defensive no-op rather than being removed
    in case a future codec name grows one)."""
    return (codec or "").split(" (")[0]


def coerce(value, allowed, fallback=None):
    """Snap `value` into `allowed`; returns `(value, changed)`. Used by the
    tabs' `_sync_controls` when a container switch invalidates a codec that
    was already picked -- they toast the swap rather than silently changing
    a choice out from under the user."""
    if not allowed:
        return fallback, False
    if value in allowed:
        return value, False
    return (fallback if fallback in allowed else allowed[0]), True
