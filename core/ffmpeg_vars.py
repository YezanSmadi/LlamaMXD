"""Every Muxing / Encoding input, flattened into module-level variables for
building ffmpeg commands.

Populated by `load()`, which the Queue tab calls right before a job runs
(`QueueTab._process_next`). So these always describe **the job being run** —
the settings snapshot taken when it was queued (`_gather_settings`) — never
whatever the form happens to say right now. By the time a queued job starts,
the user may have changed the form or picked a different file entirely.

Read them through the module, not with `from ... import NAME`:

    from core import ffmpeg_vars as v
    cmd = ["ffmpeg", "-ss", v.START_TIME, "-i", v.INPUT_FILE, ...]

`from core.ffmpeg_vars import INPUT_FILE` copies the value once at import
time and never sees a later `load()`.

Most values come in two flavours: the raw one exactly as the UI shows it
(`ENCODER = "H.264"`), and an `*_ARG` one already translated into what ffmpeg
takes (`VIDEO_CODEC_ARG = "libx264"`). `Select` (formats.SELECT — the one
"nothing picked/resolved yet" placeholder) falls back to `"copy"` for
`*_CODEC_ARG` only as a defensive no-op — EncodingTab auto-resolves Encoder/
Audio Codec from the probed source the moment a file loads, and won't let a
job queue while a present stream's codec is still `Select`, so this fallback
should be unreachable in practice. Left on `Select`, Channels/Sample Rate/
Bitrate instead translate to `None` for their per-stream knob — i.e. "don't
pass that flag at all" — which is a genuinely fine outcome for those three
(unlike a codec, there's always a sensible "just follow the source" default
to fall back on), so nothing blocks a job over it.

A key that belongs to the other tab (no `ENCODER` on a Mux job, no
`VIDEO_TRACKS` on an Encode job) keeps its default below. Conveniently that
means a Mux job's `VIDEO_CODEC_ARG` comes out as `"copy"`, which is exactly
right: Muxing never re-encodes (and never touches `AUDIO_STREAMS` at all --
it maps its own `VIDEO_TRACKS`/`AUDIO_TRACKS` lists straight through
`build_mux_command`, always `-c copy`). Branch on `SOURCE_TAB` for anything
else that differs.

`AUDIO_STREAMS` is the one list-shaped variable here, not a scalar: an
Encoding job can include more than one *output* audio stream (EncodingTab's
Audio Track dropdown + Choose Stream(s) picker), each with its own codec/
bitrate/channels/sample-rate, so there's no single `AUDIO_CODEC_ARG` to
speak of any more -- see `_audio_stream_args` and `core.ffmpeg_build.
build_encode_command`.

Pure data; no UI code in here.
"""

import os

from core import formats, gpu

# ---------------------------------------------------------------------- #
#  Translation tables: UI display value -> what ffmpeg takes
# ---------------------------------------------------------------------- #

# -profile:v values. libx264 / libx265 take the profile *name* as a private
# string option. The rest go through libavcodec's generic `profile` option,
# so they get its AV_PROFILE_* number, which every build accepts. VP9's
# profiles are already numbers ("0"-"3") and pass through unchanged.
_PROFILE_ARGS = {
    "H.264": {"High": "high", "Main": "main", "Baseline": "baseline", "High 10": "high10"},
    "H.265": {"Main": "main", "Main 10": "main10", "Main 12": "main12"},
    "MPEG-4": {"Simple": "0", "Advanced Simple": "15"},
    "MPEG-2": {"High": "1", "Main": "4", "Simple": "5"},
    "AV1": {"Main": "0", "High": "1", "Professional": "2"},
    # prores_ks's -profile:v takes these exact named strings.
    "ProRes": {"Proxy": "proxy", "LT": "lt", "422": "standard", "422 HQ": "hq",
               "4444": "4444", "4444 XQ": "4444xq"},
    # dnxhd's -profile:v takes these exact named strings (it's the same
    # encoder for classic DNxHD and the modern DNxHR tiers).
    "DNxHR": {"LQ": "dnxhr_lq", "SQ": "dnxhr_sq", "HQ": "dnxhr_hq",
              "HQX": "dnxhr_hqx", "444": "dnxhr_444"},
}

# cfhd has no -profile:v option at all -- its "quality" ladder (see
# _QUALITY_PRESET_ARGS below) is a completely different flag. Reusing the
# Profile dropdown slot for it (same trick as ProRes/DNxHR's profile-as-
# quality) means _profile_arg must never fall through to a literal
# -profile:v value the way an encoder absent from _PROFILE_ARGS normally
# would (see _profile_arg) -- there's nothing for that flag to mean here.
_NO_PROFILE_FLAG = {"CineForm"}


def _profile_arg(encoder, profile):
    """-profile:v value for the current Profile dropdown pick, or None.
    Falls through to the raw display value when there's no explicit mapping
    (VP9's profiles are already the numeric strings -profile:v wants) --
    except for `_NO_PROFILE_FLAG` encoders, whose Profile slot maps to a
    different flag entirely and must never touch -profile:v."""
    if encoder in _NO_PROFILE_FLAG:
        return None
    return _PROFILE_ARGS.get(encoder, {}).get(profile, profile) or None


# -pix_fmt overrides for profile-locked intermediates. Unlike H.264/HEVC/etc.
# (which happily follow whatever pixel format the source decodes to), ffmpeg's
# dnxhd encoder actively *refuses to run* without an explicit, profile-legal
# -pix_fmt -- a typical yuv420p consumer source is illegal for every DNxHR
# tier -- and prores_ks/cfhd silently lock in whatever pix_fmt they default
# to rather than the one actually intended. Empty for every other encoder;
# they've always worked without this.
_PIX_FMT_ARGS = {
    "ProRes": {
        "Proxy": "yuv422p10le", "LT": "yuv422p10le", "422": "yuv422p10le",
        "422 HQ": "yuv422p10le", "4444": "yuv444p10le", "4444 XQ": "yuv444p10le",
    },
    "DNxHR": {
        "LQ": "yuv422p", "SQ": "yuv422p", "HQ": "yuv422p",
        "HQX": "yuv422p10le", "444": "yuv444p10le",
    },
    # cfhd only supports yuv422p10le/gbrp12le/gbrap12le (confirmed via
    # `ffmpeg -h encoder=cfhd`) -- every quality tier encodes the same way
    # pixel-format-wise, so every profile maps to the same value.
    "CineForm": {p: "yuv422p10le" for p in formats.profiles_for("CineForm")},
}

# cfhd's own quality dial -- a named preset ladder (-quality), not a
# continuous CRF/qscale range, so it rides the Profile dropdown slot instead
# of the quality slider (see formats._ENCODER_SPECS["CineForm"] and
# _NO_PROFILE_FLAG above). Values are cfhd's own AVOption names (confirmed
# via `ffmpeg -h encoder=cfhd`); ffmpeg's own default is "film3+" (best).
_QUALITY_PRESET_ARGS = {
    "CineForm": {
        "Low": "low", "Low+": "low+", "Medium": "medium", "Medium+": "medium+",
        "High": "high", "High+": "high+", "Film 1": "film1", "Film 1+": "film1+",
        "Film 1.5": "film1.5", "Film 2": "film2", "Film 2+": "film2+",
        "Film 3": "film3", "Film 3+": "film3+",
    },
}

# -level:v values. Everything passes through as displayed ("4.0") except
# MPEG-2, whose levels are names in the UI but level_idc numbers to ffmpeg.
# (libx265 takes its level via `-x265-params level-idc=<LEVEL_ARG>`.)
_LEVEL_ARGS = {
    "MPEG-2": {"Low": "10", "Main": "8", "High-1440": "6", "High": "4"},
}

# -ac values.
_CHANNEL_COUNTS = {"Mono": 1, "Stereo": 2, "5.1": 6, "5.2": 7, "7.1": 8, "7.2": 9, "9.1": 10}

# ---------------------------------------------------------------------- #
#  The variables (defaults = "no job loaded")
# ---------------------------------------------------------------------- #

# --- Job ---
SOURCE_TAB = ""             # "Encoding" or "Muxing" — who queued this job

# --- Input file (the one global selection; DropBox / Browse) ---
INPUT_FILE = ""             # full path                  -> your %name%
INPUT_DIR = ""              # folder it lives in
INPUT_NAME = ""             # "clip.mkv"
INPUT_STEM = ""             # "clip"                     -> your !name:~0,-4!
INPUT_EXT = ""              # ".mkv" (lowercased) — any length, unlike ~0,-4

# --- Output (the "Save file as..." entry + Output Format dropdown) ---
OUTPUT_PATH = ""            # full path, as typed/browsed/auto-filled
OUTPUT_DIR = ""
OUTPUT_NAME = ""            # "clip_encoded.mp4"
OUTPUT_STEM = ""            # "clip_encoded"
OUTPUT_EXT = ""             # extension actually on OUTPUT_PATH
OUTPUT_FORMAT = ""          # dropdown value, ".mp4". Normally == OUTPUT_EXT (the
                            # tab swaps the path's extension on change), but a
                            # hand-typed path can disagree — pass -f if so.

# --- Trim (Overview: Start Time / Clip Duration spinners) ---
START_SECS = 0              # int seconds
DURATION_SECS = 0           # int seconds; 0 means "to the end of the file"
END_SECS = None             # START_SECS + DURATION_SECS, or None when to-end
START_TIME = "00:00:00"     # the same three as HH:MM:SS
DURATION_TIME = "00:00:00"
END_TIME = None

# WARNING — verified against real ffmpeg output (frame-counted, not just
# read from docs): -ss as an INPUT option (before -i) rebases the output's
# timeline to start at 0. If -to is then given as an OUTPUT option (after
# -i, which is where it'd naturally land alongside -c:v/-crf/etc.), it's
# measured against that REBASED timeline, not the source -- so it behaves
# like a literal duration equal to the -to value itself, not (to - start).
# `-ss 00:21:36 -i in.mp4 -to 00:21:41 ...` does NOT give a 5-second clip;
# it gives a clip 21 minutes 41 seconds long, starting at 21:36.
#
# Two ways to actually use END_TIME/END_SECS safely:
#   1. Pass START_TIME/END_TIME to ffmpeg.input() TOGETHER (both -ss and
#      -to as input options) -- confirmed correct: `-ss 5 -to 10 -i src`
#      produced exactly a 5s clip.
#   2. Don't use END_TIME/END_SECS at all -- pass DURATION_TIME/DURATION_SECS
#      to the OUTPUT side (-t) instead. A duration is relative by
#      definition, so -ss placement can't corrupt it. This is the one to
#      reach for by default; see core/ffmpeg_vars.py's own module docstring
#      example and the Encoding-tab wiring for the pattern.

# --- Stream presence (Overview A/V Sync; Video/Audio Strip checkboxes) ---
AV_SYNC = False             # align A/V start + pass through common metadata
STRIP_VIDEO = False         # -> -vn   (check before using any video value)
STRIP_AUDIO = False         # -> -an   (never both — the UI makes that unreachable)

# --- Encoding / Video sub-tab ---
ENCODER = formats.SELECT    # "H.264", ... or "Select"
VIDEO_CODEC_ARG = "copy"    # -c:v   "libx264", ... or "copy"
PROFILE = ""                # "High 10", ... ("" when the codec has none)
PROFILE_ARG = None          # -profile:v   "high10", ... or None
LEVEL = ""                  # "4.0", ... ("" when the codec has none)
LEVEL_ARG = None            # -level:v   "4.0", ... or None
PIX_FMT_ARG = None          # -pix_fmt   "yuv422p10le", ... or None (see _PIX_FMT_ARGS)
QUALITY_PRESET_ARG = None   # -quality   "film3+", ... or None (CineForm only; see _QUALITY_PRESET_ARGS)
QUALITY = None              # slider value (int); None on a Mux job
QUALITY_KIND = None         # "crf" (-crf) / "qscale" (-q:v) / None on Select.
                            # QUALITY still holds the slider even when this is
                            # None — the slider stays live on Select.
SPEED = ""                  # "fast", "4", ... ("" when the codec has none)
SPEED_ARG = {}              # kwargs to merge in: {"preset": "fast"} or
                            # {"cpu-used": "4", "deadline": "good"}, or {}
GPU_ENABLED = False         # the Settings tab's global GPU switch
HW_ENCODER = None           # resolved hardware encoder id ("h264_nvenc", ...)
                            # when GPU_ENABLED found one for ENCODER on this
                            # machine's GPU, else None -- see core/gpu.py.
                            # VIDEO_CODEC_ARG already reflects it; this is
                            # what build_encode_command reads to know which
                            # rate-control flags to use instead of -crf/-q:v.
HDR_TO_SDR = False          # HDRtoSDR switch
MASTERING_MAX_NITS = None   # the source's probed ST 2086 mastering peak (nits),
                            # or None if it wasn't tagged -- core.utilities.
                            # probe_media's mastering_max_nits, snapshotted at
                            # queue time (EncodingTab._gather_settings).
MAX_CLL = None              # the source's probed MaxCLL (nits), or None/0 if
                            # unset -- probe_media's max_cll. Read alongside
                            # MASTERING_MAX_NITS to decide libplacebo_tonemap_
                            # vf's peak_detect argument in ffmpeg_build.py --
                            # BOTH are required, not just a mastering peak on
                            # its own; see that function's docstring for why
                            # (confirmed a mastering peak with no real MaxCLL
                            # measurement is the wrong signal to trust).
RESOLUTION = formats.SOURCE_RESOLUTION   # "Source", "1080p", ... (formats.RESOLUTIONS)
SOURCE_HEIGHT = None        # the probed source's own height (px), snapshotted
                            # at queue time (EncodingTab._gather_settings) -- a
                            # fact about the input, not a user choice, same
                            # convention as MASTERING_MAX_NITS/MAX_CLL above.
SCALE_VF = None             # -vf "scale=-2:<height>" when RESOLUTION picks a
                            # real downscale, else None -- see _scale_vf.
FPS = formats.SOURCE_FPS    # "Source", "30", ... (formats.FPS_VALUES)
SOURCE_FPS = None           # the probed source's own fps (float), snapshotted
                            # at queue time -- same convention as SOURCE_HEIGHT.
FPS_ARG = None              # -r value when FPS picks a real rate, else None
                            # -- see _fps_arg.

# --- Encoding / Audio sub-tab ---
# One entry per *included* source audio stream (EncodingTab's Audio Track
# dropdown + Choose Stream(s) picker), in output order -- [] when
# STRIP_AUDIO or the source has no audio at all. Each entry:
#   {"src_index": 0,            -- which source stream (-map 0:a:<src_index>)
#    "codec_arg": "aac",        -- -c:a:<output position>, or "copy"
#    "bitrate_arg": "192k",     -- -b:a:<output position>, or None (omit)
#    "channels_arg": 2,         -- -ac:<output position>, or None (omit)
#    "sample_rate_arg": 48000,  -- -ar:<output position>, or None (omit)
#    "language": "eng"}         -- probed language tag, or None; only set for
#                               -- a re-encoded (non-copy) stream -- see
#                               -- build_encode_command's stale-metadata wipe
# "output position" is this entry's index *within this list* (0, 1, 2, ...),
# not `src_index` -- ffmpeg numbers `:a:N` on the *output* file's audio
# streams, which only matches the source's numbering when every source
# stream up to that point was included. A Passthru track (the "Passthru"
# checkbox, forced on for DTS/Dolby TrueHD -- formats.is_passthru_only) always
# comes out "copy"/None/None/None regardless of what its display-value
# fields say -- see _audio_stream_args.
AUDIO_STREAMS = []

# --- Muxing / Video + Audio sub-tabs (track pickers + Browse…) ---
VIDEO_TRACK = "Auto"        # "Auto" / "Track 1".."Track 3" / "External: <name>"
VIDEO_TRACK_INDEX = None    # 0-based ffmpeg index: "Track 1" -> 0 (-map 0:v:0).
                            # None for Auto and for External.
VIDEO_TRACK_FILE = ""       # second input's path when an External track is
                            # picked (-i it too, then -map 1:v)
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
    """`(dir, name, stem, ext)` for a path, tolerating either slash style
    (Browse returns forward slashes, the auto-filled output path backslashes)."""
    path = path.replace("\\", "/")
    directory, name = os.path.split(path)
    stem, ext = os.path.splitext(name)
    return directory, name, stem, ext.lower()


def _audio_stream_args(entry):
    """One `settings["audio_streams"]` entry (display values, same shape the
    Audio sub-tab's four controls show) -> its ffmpeg-ready dict — the same
    per-scalar translations `derive()` used to apply once, globally, to a
    single audio track.

    Passthru (the "Passthru" checkbox -- forced for DTS/Dolby TrueHD via
    `formats.is_passthru_only`, or a deliberate pick for any other codec)
    means this stream is a straight `-c:a copy`: bitrate/channels/sample
    rate stop being ours to set (EncodingTab only ever shows the *source's*
    real values there while it's on, purely for display -- see
    EncodingTab._apply_passthru_values), so they're omitted here rather than
    passed alongside a copy, which ffmpeg would just ignore anyway."""
    codec = entry.get("codec") or formats.SELECT
    passthru = bool(entry.get("passthru")) or formats.is_passthru_only(codec)
    bitrate = entry.get("bitrate") or formats.SELECT
    channels = entry.get("channels") or formats.SELECT
    sample_rate = entry.get("sample_rate") or formats.SELECT
    return {
        "src_index": int(entry.get("index") or 0),
        "codec_arg": "copy" if passthru else formats.AUDIO_ENCODERS.get(codec, "copy"),
        "bitrate_arg": None if passthru else formats.bitrate_arg_for(bitrate),
        "channels_arg": None if passthru else _CHANNEL_COUNTS.get(channels),
        "sample_rate_arg": (
            None if passthru or sample_rate == formats.SELECT else int(sample_rate.split()[0])
        ),
        # The probed language tag, carried through so build_encode_command
        # can re-apply it after wiping a re-encoded stream's stale per-track
        # statistics (BPS/DURATION/... describing the *source's* codec and
        # length, not this job's) -- see its own comment for why passthru
        # never needs this at all (nothing about a copied stream's tags goes
        # stale).
        "language": None if passthru else entry.get("language"),
    }


def _scale_vf(resolution, source_height):
    """-vf value for a Resolution pick -- `-2` for the width lets ffmpeg's
    scale filter compute it from the source's own aspect ratio (rounded to
    the nearest even number, which every chroma subsampling this app's
    codecs use needs), which is what actually keeps the aspect ratio intact.
    This is the one piece of "what yt-dlp does" that doesn't carry over
    directly: yt-dlp's own Quality dropdown (core/downloader.py) just picks
    among streams already encoded at that size, never resizes anything
    itself -- a local input has exactly one resolution, so getting a smaller
    one here means a real re-encode through this filter.

    None for 'Source', or when there's no real downscale to do -- an
    unprobed height, or a resolution at/above the source's own height.
    EncodingTab's Resolution dropdown is already capped to the source's own
    height (formats.resolutions_for), but a saved preset applied to a
    smaller or differently-probed file could still name a rung no longer <=
    that file's real height, so this re-checks rather than trusting the
    caller."""
    target = formats.resolution_height_for(resolution)
    if not target or not source_height or target >= source_height:
        return None
    return f"scale=-2:{target}"


def _fps_arg(fps, source_fps):
    """-r value for an FPS pick -- None for 'Source', or when the picked
    rate is no longer <= the source's own (a saved preset applied to a
    different/faster file). EncodingTab's FPS dropdown is already capped
    (formats.fps_values_for), but this re-checks rather than trusting the
    caller, same reasoning as _scale_vf."""
    target = formats.fps_arg_for(fps)
    if not target:
        return None
    if source_fps and float(target) > source_fps + 0.1:
        return None
    return target


def _speed_kwargs(encoder, value):
    """SPEED's ffmpeg-ready kwargs -- a named -preset for x264/x265/AV1, or
    -cpu-used (+ a fixed -deadline good) for the libvpx codecs (see
    formats.speed_kind_for). {} when the codec has no speed knob or nothing's
    picked."""
    kind = formats.speed_kind_for(encoder)
    if not value or kind is None:
        return {}
    if kind == "preset":
        return {"preset": value}
    return {"cpu-used": value, "deadline": "good"}


def derive(settings, source_tab=""):
    """Every variable above, computed from one task's settings dict, as a
    plain `{NAME: value}` dict. Pure — use it directly instead of the module
    globals if a worker thread should hold its own copy of a job."""
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
    # Hardware encoder ids don't understand libx264/libx265/SVT-AV1's own
    # -preset ladder (nvenc/qsv/amf each have their own, incompatible preset
    # vocabulary) -- rather than trying to translate one onto the other,
    # a hardware-encoded job just omits -preset and rides that encoder's own
    # default, same reasoning as PIX_FMT_ARG being None for a codec it
    # doesn't apply to.
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

        # Each entry: {"source": "primary"/"external", "file": path|None,
        # "index": N} -- N is 0-based among that *file's own* streams of this
        # kind, matching what `-map <input>:v:<index>` / `:a:<index>` takes.
        "VIDEO_TRACKS": video_tracks,
        "AUDIO_TRACKS": audio_tracks,
    }


def load(settings, source_tab=""):
    """Points every module variable at one job's values. `load({})` resets
    them all to the "no job loaded" defaults.

    Called on the GUI thread as each job starts. The queue runs one job at a
    time, so a single set of globals is enough; if jobs ever run
    concurrently, give each worker its own `derive()` dict instead."""
    globals().update(derive(settings, source_tab))
