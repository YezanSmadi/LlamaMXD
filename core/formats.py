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

`SOURCE` is a first-class value in every codec list, meaning "whatever the
input already has" (i.e. stream-copy). It's the default everywhere, so an
untouched form is a straight passthrough. It's always legal in every
container as far as the UI can tell -- only a probe of the actual input
(`core.utilities.probe_media`) can say otherwise, which is what feeds
`containers_for`.

Pure data + lookups; no Tk in here.
"""

SOURCE = "Source"

# Display name -> ffmpeg encoder id. The ids aren't called yet (there's no
# real pipeline), but this is the natural place for the mapping to live so
# the eventual subprocess builder has one lookup rather than a scattered
# pile of if/elif.
VIDEO_ENCODERS = {
    "H.264 (x264)": "libx264",
    "H.265 (x265)": "libx265",
    "MPEG-4": "mpeg4",
    "MPEG-2": "mpeg2video",
    "VP8": "libvpx",
    "VP9": "libvpx-vp9",
    "AV1": "libsvtav1",
}

AUDIO_ENCODERS = {
    "AAC": "aac",
    "AC3": "ac3",
    "MP3": "libmp3lame",
    "FLAC": "flac",
    "Opus": "libopus",
    "Vorbis": "libvorbis",
    "ALAC": "alac",
    "PCM": "pcm_s16le",
}

# What each container can actually carry. WebM is the reason this table has
# to exist at all: it shares *no* video codec with mp4/mov, so before this
# existed, picking .webm left every entry in the encoder list illegal.
_CONTAINERS = {
    ".mp4": {
        "video": ["H.264 (x264)", "H.265 (x265)", "MPEG-4", "MPEG-2", "AV1"],
        "audio": ["AAC", "AC3", "MP3", "ALAC"],
    },
    ".mkv": {
        "video": list(VIDEO_ENCODERS),
        "audio": list(AUDIO_ENCODERS),
    },
    ".mov": {
        "video": ["H.264 (x264)", "H.265 (x265)", "MPEG-4"],
        "audio": ["AAC", "AC3", "ALAC", "PCM"],
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
    "H.264 (x264)": {
        "profiles": ["High", "Main", "Baseline", "High 10"],
        "levels": ["3.0", "3.1", "4.0", "4.1", "4.2", "5.0", "5.1", "5.2"],
        "quality": {"kind": "crf", "label": "Quality (CRF)", "lo": 0, "hi": 51,
                    "default": 23, "low": "Low", "high": "Placebo"},
    },
    "H.265 (x265)": {
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
    # Copying the source stream through: there is nothing to configure.
    SOURCE: {"profiles": [], "levels": [], "quality": None},
}

AUDIO_BITRATES = ["96k", "128k", "192k", "256k", "320k"]
AUDIO_CHANNELS = [SOURCE, "Mono", "Stereo", "5.1"]
AUDIO_SAMPLE_RATES = [SOURCE, "44100 Hz", "48000 Hz", "96000 Hz"]

# Codecs whose rate isn't ours to set (lossless, or a straight copy) --
# offering a bitrate dropdown alongside them would be a dead control.
_FIXED_RATE_AUDIO = {SOURCE, "FLAC", "ALAC", "PCM"}

# ffprobe codec_name -> our display name, for probe_media's output. Only the
# codecs this app can name are mapped; anything else stays None (unknown),
# which every consumer treats as "constrains nothing".
FFPROBE_VIDEO = {
    "h264": "H.264 (x264)", "hevc": "H.265 (x265)", "mpeg4": "MPEG-4",
    "mpeg2video": "MPEG-2", "vp8": "VP8", "vp9": "VP9", "av1": "AV1",
}
FFPROBE_AUDIO = {
    "aac": "AAC", "ac3": "AC3", "eac3": "AC3", "mp3": "MP3", "flac": "FLAC",
    "opus": "Opus", "vorbis": "Vorbis", "alac": "ALAC",
    "pcm_s16le": "PCM", "pcm_s24le": "PCM", "pcm_f32le": "PCM",
}


def containers():
    """Every output container the app offers, in menu order."""
    return list(_CONTAINERS)


def video_codecs_for(container):
    """Legal video codecs for `container`, SOURCE first. An unknown
    container falls back to the permissive Matroska set."""
    spec = _CONTAINERS.get(container, _CONTAINERS[".mkv"])
    return [SOURCE] + list(spec["video"])


def audio_codecs_for(container):
    """Legal audio codecs for `container`, SOURCE first."""
    spec = _CONTAINERS.get(container, _CONTAINERS[".mkv"])
    return [SOURCE] + list(spec["audio"])


def profiles_for(encoder):
    """Profile names for `encoder` -- empty when the codec has no profiles
    to pick (VP8), or when the stream is being copied."""
    return list(_ENCODER_SPECS.get(encoder, _ENCODER_SPECS[SOURCE])["profiles"])


def levels_for(encoder):
    """Level names for `encoder` -- empty where the codec has no levels
    (VP8/VP9/MPEG-4). Deliberately *not* shared between codecs: '4.0' means
    different things to H.264 and H.265."""
    return list(_ENCODER_SPECS.get(encoder, _ENCODER_SPECS[SOURCE])["levels"])


def quality_for(encoder):
    """The rate-control spec for `encoder` (kind/label/range/default/end
    labels), or None when there's nothing to control (stream copy)."""
    spec = _ENCODER_SPECS.get(encoder, _ENCODER_SPECS[SOURCE])["quality"]
    return dict(spec) if spec else None


def audio_bitrates_for(codec):
    """Bitrate choices for `codec` -- empty for lossless/copy codecs."""
    return [] if codec in _FIXED_RATE_AUDIO else list(AUDIO_BITRATES)


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
    """Display name without its library suffix — "H.264 (x264)" -> "H.264".
    The Overview rundown has very little width to spend, and the encoder
    library is noise once you're only summarising."""
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
