# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
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

# Windows-only flag that keeps ffprobe from flashing a console window over
# the GUI. Absent on other platforms, hence the getattr default.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Lazy, process-lifetime caches for supports_fps_mode()/libplacebo_problem()/
# av1_preset_range() -- None means "not checked yet"; a real value once it
# has been (True/False for the first, an (lo, hi) tuple for the third).
# libplacebo's answer is None itself when nothing is wrong, so it has its own
# "not checked yet" sentinel.
_fps_mode_supported = None
_UNCHECKED = object()
_libplacebo_problem = _UNCHECKED
_libplacebo_lock = threading.Lock()
_av1_preset_range = None

LIBPLACEBO_MISSING = "missing"        # this ffmpeg build lacks the libplacebo filter
LIBPLACEBO_NO_VULKAN = "vulkan"       # it has it, but can't run it (no usable Vulkan)


# AV1's raw ffprobe `level` is a seq_level_idx table index (0-based), not an
# arithmetic encoding -- confirmed empirically: a naturally-encoded 720p30
# clip reported raw level 5, which is index 5 here ("3.1"), matching the
# resolution/bitrate that level is meant for. Indices 24-31 are reserved/
# unused in the AV1 spec, so there's nothing past 7.3 to add.
_AV1_LEVELS = [
    "2.0", "2.1", "2.2", "2.3", "3.0", "3.1", "3.2", "3.3",
    "4.0", "4.1", "4.2", "4.3", "5.0", "5.1", "5.2", "5.3",
    "6.0", "6.1", "6.2", "6.3", "7.0", "7.1", "7.2", "7.3",
]
# MPEG-2's raw ffprobe `level` is the same numeric code ffmpeg's own
# `-level:v` option takes for it (mirrors ffmpeg_vars._LEVEL_ARGS["MPEG-2"]
# in reverse) -- named levels, not a major.minor number.
_MPEG2_LEVEL_NAMES = {10: "Low", 8: "Main", 6: "High-1440", 4: "High"}

# ffprobe's own `profile` strings for ProRes don't match this app's display
# names (formats._ENCODER_SPECS["ProRes"]["profiles"]) -- ffmpeg's libavcodec
# names them "Proxy"/"LT"/"Standard"/"HQ"/"4444"/"4444XQ", while this app
# calls the middle four tiers "Proxy"/"LT"/"422"/"422 HQ"/"4444"/"4444 XQ"
# (matching how editors/colorists actually talk about ProRes). Matched
# case-insensitively since ffprobe's casing isn't itself guaranteed.
_PRORES_PROFILE_NAMES = {
    "proxy": "Proxy", "lt": "LT", "standard": "422", "hq": "422 HQ",
    "4444": "4444", "4444xq": "4444 XQ",
}


def _parse_frame_rate(raw):
    """ffprobe's `r_frame_rate` is a rational string ("24000/1001", "30/1"),
    not a decimal -- converted here so `info["fps"]` is a plain float
    (29.97, not "30000/1001"), or None for anything missing/unparseable
    (a "0/0" placeholder ffprobe emits for some still-image/data streams)."""
    if not raw or "/" not in raw:
        return None
    num, _, den = raw.partition("/")
    try:
        num, den = float(num), float(den)
    except ValueError:
        return None
    return num / den if den else None


def _normalize_video_profile(codec_name, profile):
    """ffprobe's raw `profile` string -> this app's display name, for the
    codecs whose naming doesn't already match (see _PRORES_PROFILE_NAMES).
    Left unchanged for every other codec -- H.264/HEVC/etc.'s ffprobe profile
    strings ("High", "Main 10", ...) already are this app's own display
    names, which is why auto-fill worked for them with no translation at all.

    DNxHR's raw profile is reported as "DNXHR HQX"/"DNXHR LQ"/etc. (confirmed
    against a real encode -- all-caps "DNXHR", not the mixed-case "DNxHR"
    this app displays it as) -- stripping that prefix case-insensitively
    recovers this app's own "LQ"/"HQX" names. Classic legacy DNxHD reports
    the bare "DNxHD" (no tier), which has no equivalent in
    formats.profiles_for("DNxHR") and is deliberately left unmatched rather
    than guessed at -- EncodingTab's auto-fill already treats "not in the
    list" as "leave unresolved", same as any other codec."""
    if not profile:
        return profile
    if codec_name == "prores":
        return _PRORES_PROFILE_NAMES.get(profile.lower(), profile)
    if codec_name == "dnxhd" and profile.upper().startswith("DNXHR "):
        return profile[len("DNXHR "):].upper()
    return profile

# ffprobe's color_transfer values that mean "this is HDR", not SDR --
# smpte2084 is PQ (HDR10/HDR10+/Dolby Vision's base layer), arib-std-b67 is
# HLG. Anything else (bt709, smpte170m, absent, ...) is treated as SDR --
# there's no third "maybe" state once a video stream has actually been
# identified, only "no video stream / probe never ran" (None) beforehand.
_HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}

# HDR->SDR: libplacebo's BT.2390 EETF curve, deliberately the *only* option
# this app will ever use -- BT.2390 is the industry-standard broadcast
# tone-mapping operator; the classic zscale+tonemap filter's own algorithm
# list tops out at "hable" (none/linear/gamma/clip/reinhard/hable/mobius,
# confirmed via `ffmpeg -h filter=tonemap` -- no BT.2390 among them), a
# noticeably less accurate stand-in this app should never silently
# substitute. Verified end-to-end against a real HDR10 (PQ/BT.2020) source:
# correctly BT.709-tagged SDR output, not just a visually-plausible one with
# the container tags left unset/wrong.
#
# **Confirmed the `bt.2390` value is genuinely taking effect, not silently
# falling back to `auto` or being ignored** -- three independent checks
# against this app's own ffmpeg build: (1) `ffmpeg -h full filter=libplacebo`
# lists `bt.2390` as a real named enum value (index 4) for the `tonemapping`
# option, not a typo'd string; (2) `-loglevel debug` on a real encode logs
# `Setting 'tonemapping' to value 'bt.2390'` during graph construction, and
# libplacebo compiles an actual curve-specific `tone_map()` GLSL shader, not
# a stub; (3) decisive: feeding the same real HDR10 frame (sun.mkv) through
# `tonemapping=bt.2390` vs `clip` (no tonemapping at all) vs `reinhard` vs
# `hable` produced measurably different output every time (93% of pixels
# changed vs `clip`, 100% vs `hable`, with `reinhard` -- the curve closest in
# shape to BT.2390 -- showing the smallest but still nonzero difference,
# exactly the ordering curve theory predicts). If our value were being
# silently dropped, all four would have rendered pixel-identical.
# `post_encode_hdr_tag_check` (`core/ffmpeg_runner.py`) re-verifies this on
# every real HDR->SDR job's actual output, not just at development time.
#
# Needs a build compiled with libplacebo *and* a working Vulkan device at
# runtime -- gated by supports_libplacebo() everywhere this is used.
# **Being listed as compiled in is not enough on its own** -- confirmed on
# this app's own dev machine (after updating ffmpeg specifically to get
# libplacebo) that the filter's own *implicit* Vulkan device selection
# segfaults outright, zero stderr, on a real hybrid dual-vendor GPU (NVIDIA
# discrete + AMD integrated) with several overlay/capture Vulkan layers
# installed (Steam, OBS, Epic, Rockstar -- all common software). Explicitly
# creating the device up front (`-init_hw_device vulkan=vk`) and binding the
# filter to it (`-filter_hw_device vk`) avoids the crash entirely -- verified
# on that same machine, with no need to name a specific device index (an
# index would be the wrong GPU on some other machine's enumeration order).
#
# Lives here (not core/ffmpeg_build.py, which uses it for the real encode)
# so extract_hdr_tonemapped_thumbnails below can share the exact same filter
# string without a circular import -- ffmpeg_build already imports
# supports_libplacebo/supports_fps_mode from this module, so the dependency
# only runs one way.
VULKAN_DEVICE_FLAGS = ["-init_hw_device", "vulkan=vk", "-filter_hw_device", "vk"]


def libplacebo_tonemap_vf(peak_detect=True):
    """The BT.2390 tonemap filter string -- a function of `peak_detect`, not
    a fixed constant, since which way that should go depends on the
    *source*'s HDR metadata. Callers should pass `peak_detect=False` only
    when the source has BOTH a mastering peak (`probe_media`'s
    `mastering_max_nits`) AND a genuine, nonzero MaxCLL (`max_cll`) --
    `True`, libplacebo's own default, otherwise. A mastering peak alone is
    not enough; see the second finding below for why that distinction is
    load-bearing, not pedantic.

    **Why this exists at all -- confirmed directly, not a guess, in both
    directions.** libplacebo's `peak_detect` (on by default) dynamically
    estimates each frame's true peak brightness by analysing actual pixel
    values, smoothed over a ~100-frame window (`smoothing_period`'s
    default) -- meant to compensate for a source with *no* static metadata
    to go on.

    1. **A source with a real, measured MaxCLL benefits from turning
       peak_detect off.** `Spider-Man 3 Sheriff.mp4` (mastering peak 4000
       nits, MaxCLL 4471, MaxFALL 1007 -- a genuine per-content brightness
       measurement) run through the *exact* real encode pipeline
       (`build_encode_command`, full file): `peak_detect=true` (the
       default) left 16% of pixels red-channel-saturated in one
       skin-highlight region and 27% near-white in another;
       `peak_detect=false` on the identical full encode cut that to 2% and
       0.6% -- an 87%/98% reduction. Mechanism, also confirmed rather than
       assumed: the smoothed per-frame estimate anchors to the *recent
       local average*, so a frame that's brighter than its neighbours gets
       mapped against a knee tuned for the dimmer average and clips harder
       than if the file's own declared mastering peak had simply been
       trusted outright -- confirmed by checking that *more* temporal
       continuity (a full continuous decode vs. an isolated single frame)
       made the clipping *worse*, not better, which rules out "it just
       needs more frames to converge."

    2. **A source with a mastering peak but NO real MaxCLL measurement gets
       actively worse with peak_detect off -- this is why MaxCLL is
       required, not just the mastering peak.** `Beauty and the Beast (Be
       Our Guest HDR).mp4` carries a mastering peak (4000 nits) but MaxCLL/
       MaxFALL of 0/0 -- present in the SEI but unset, not a real
       measurement (same convention `ThumbnailCarousel._mastering_text`
       already treats as absent). A mastering peak alone only says "this
       was graded on a display capable of up to 4000 nits" -- it says
       nothing about how bright the actual content gets, unlike MaxCLL.
       Forcing peak_detect off on this file (an earlier, too-broad version
       of this condition that keyed on the mastering peak alone) made a
       real frame measurably *dimmer and lower-contrast*, not better: mean
       82.0 -> 78.6, p95 174 -> 153. Trusting a mastering peak with no
       content-level backing overstates how much dynamic range the actual
       scene needs compressed, over-flattening it -- exactly the opposite
       problem from case 1, and confirmed on this exact file rather than
       assumed from the general principle.

    When a source has no static metadata at all, `peak_detect` is still
    exactly the right fallback -- there's nothing else to trust -- so this
    only ever turns it off when there's real, specific evidence to prefer
    that, never as a blanket "metadata exists" shortcut."""
    return (
        "libplacebo="
        f"apply_dolbyvision=true:"  # explicit, not relied-on-as-default (it
                                    # already defaults to true on this app's
                                    # own ffmpeg build -- confirmed via
                                    # `ffmpeg -h filter=libplacebo` -- but a
                                    # default can change under us across
                                    # ffmpeg versions; Profile 5/8.x DV
                                    # sources embed their own dynamic RPU
                                    # metadata, which libplacebo applies on
                                    # top of the BT.2390 base-layer tonemap
                                    # when this is on).
        f"peak_detect={'true' if peak_detect else 'false'}:"
        "tonemapping=bt.2390:"     # ITU-R BT.2390 EETF -- NOT bt.2446a, reinhard,
                                    # hable, mobius, spline, or any other entry in
                                    # `ffmpeg -h filter=libplacebo`'s tonemapping
                                    # enum. This is the one curve this app will
                                    # ever use (see the block comment above) --
                                    # if this ever needs to change, change it
                                    # here, the one place both the real encode
                                    # (ffmpeg_build.build_encode_command) and the
                                    # HDR preview (extract_hdr_tonemapped_
                                    # thumbnails below) read it from.
        "colorspace=bt709:"
        "color_primaries=bt709:"
        "color_trc=bt709:"
        "format=yuv420p"
    )


def _ffprobe_level(codec_name, level):
    """ffprobe's video `level` -> this app's display string, or None when
    it can't be identified (no level reported -- ffprobe uses -99 for that
    -- or a codec/value this app doesn't have a mapping for).

    **Not one universal formula** -- confirmed empirically per codec:
    - H.264 (and anything else not special-cased below): `level` is ten
      times the display value (`40` -> "4.0").
    - HEVC's `level` is *thirty* times the display value (level_idc = level
      * 30 per the HEVC spec) -- confirmed: a source ffprobe reported as
      raw `120` is really "4.0", not "12.0" (dividing by 30 first recovers
      the same major*10+minor encoding H.264 uses, `//10`/`%10` from there).
    - AV1's `level` is a seq_level_idx table lookup (_AV1_LEVELS), not an
      arithmetic encoding at all.
    - MPEG-2's `level` is a named-level code (_MPEG2_LEVEL_NAMES), not a
      major.minor number.
    Getting this wrong doesn't crash anything -- EncodingTab only acts on a
    result that's actually in `formats.levels_for(video)` -- but it does
    mean Level silently never auto-fills for that codec, which is exactly
    the bug this was written to fix (HEVC sources always missed instead of
    landing on a nonsense value like "12.0")."""
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
    """ffprobe reports mastering-display luminance as a `"num/den"` ratio
    string in candela/m^2 (nits) -- `"10000000/10000"` -> `1000.0`,
    `"1/10000"` -> `0.0001` (confirmed against a real x265-muxed HDR10 SEI
    payload). Returns None on anything that doesn't parse rather than
    raising -- this only ever refines a tonemap preview/tooltip, never
    blocks anything."""
    if not value:
        return None
    try:
        num, _, den = str(value).partition("/")
        return float(num) / float(den) if den else float(num)
    except (ValueError, ZeroDivisionError):
        return None


def _probe_hdr_static_metadata(path):
    """Best-effort extraction of the source's *static* HDR metadata --
    SMPTE ST 2086 mastering-display luminance and MaxCLL/MaxFALL (SMPTE ST
    2094's simpler sibling, "Content light level") -- as
    `{"mastering_max_nits": 1000.0, "mastering_min_nits": 0.0001,
      "max_cll": 1000, "max_fall": 400}`, any key None if that particular
    piece wasn't present or didn't parse.

    This is genuinely a separate probe from `probe_media`'s main one:
    confirmed directly (against a real x265-encoded HDR10 file, with and
    without `-x265-params master-display=...:max-cll=...`, remuxed into both
    MP4 and MKV) that neither ever shows up in ffprobe's *stream*-level
    `side_data_list` -- only on the decoded *frame*'s own side data, which
    `-show_entries` can't selectively filter to (it silently drops
    side_data_list's nested fields down to empty objects; only a full,
    unrestricted `-show_frames` returns the real values). So this reads just
    the first frame (`-read_intervals "0%+#1"`, a fast keyframe-only decode)
    rather than folding into the main probe's lighter `-show_entries` query.
    The leading `"0"` is load-bearing, not decorative -- confirmed directly
    against a real-world file (a 46-minute HDR10 MP4 with an edit list /
    VFR timing): the commonly-quoted idiom `"%+#1"` (no explicit start)
    silently returned zero frames on it, while the interval's own duration
    was clearly fine (`"0%+1"`, a 1-second window, returned 21 frames)  --
    apparently `%` alone doesn't reliably resolve to "the stream's actual
    start" when the container carries a nonzero/edit-list-adjusted first
    presentation timestamp. An anchored `"0%..."` start works on both that
    file and a from-scratch synthetic one, so it's the only form used here.

    This data matters for real: confirmed empirically that ffmpeg's
    `libplacebo` tonemap filter (`libplacebo_tonemap_vf` below) reads the
    metadata *values* automatically off the frame's own side data with no
    filter option needed -- feeding otherwise-identical HDR content through
    the exact same filter string with and without this metadata produced
    visibly different SDR output (mean channel delta ~30/255, ~80% of
    pixels changed) since libplacebo falls back to blind per-frame dynamic
    peak-detection (`peak_detect`) when it's absent. What this app *does*
    act on explicitly is this probe's result: `libplacebo_tonemap_vf`'s
    `peak_detect` argument follows `mastering_max_nits is not None AND
    max_cll` (both required -- a mastering peak alone isn't enough,
    confirmed the two ways documented on that function: real MaxCLL means
    trusting the metadata measurably reduces clipping, while a mastering
    peak with no real MaxCLL measurement makes it measurably worse if
    trusted the same way).
    This probe result is also surfaced straight to the user
    (`ThumbnailCarousel._info_text`), since it's now literally the thing
    that decides how the tonemap runs, not just a trivia display.

    Every failure path (no ffmpeg, unreadable file, no video stream, a slow
    decode) returns all-None rather than raising, same contract as
    `probe_media`."""
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
    """One entry of `probe_media`'s `video_streams` list -- the video-side
    counterpart of `_describe_audio_stream`, for Muxing's track box and its
    "Add Stream" picker (see CLAUDE.md's Muxing/Video panel). `index` is the
    stream's position among video streams only, matching `-map 0:v:<index>`.

    Carries everything a row shows to tell two video tracks apart: profile,
    level (`_ffprobe_level`, codec-aware), frame rate, bit depth + chroma,
    HDR kind and the stream's own bit rate (absent from most Matroska
    files, which only tag it per container). `hdr_display` is "SDR" for
    anything that isn't PQ/HLG — the same call `probe_media`'s own `hdr`
    makes, so a source with no transfer tag counts as SDR here too."""
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
    """One entry of `probe_media`'s `audio_streams` list: the raw values a
    per-stream settings UI needs (a display codec/channels/rate/bitrate,
    falling back to the raw ffprobe value when this app has no matching
    option for it, plus a best-effort language tag) alongside `index` — the
    stream's position *among audio streams only* (0-based), which is what
    `-map 0:a:<index>` / `-c:a:<index>` actually address, not its absolute
    ffprobe stream index."""
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
    """Best-effort ffprobe of `path`, as
    `{"container": ".mp4", "video": "H.264", "audio": "AAC",
      "video_profile": "High", "video_level": "4.0", "hdr": False,
      "width": 1920, "height": 1080, "duration": 83.4, "file_size": 12345,
      "audio_channels": "Stereo", "audio_sample_rate": "48000 Hz",
      "audio_bitrate": "192k", "has_video": True, "has_audio": True,
      "fps": 29.97, "video_streams": [{...}, ...], "audio_streams": [{...}, ...],
      "mastering_max_nits": None,
      "mastering_min_nits": None, "max_cll": None, "max_fall": None,
      "title": "...", "chapters": 12, "bit_rate": 8500000,
      "creation_time": "2024-03-05T10:20:30.000000Z"}`.

    `title` / `chapters` (a count) / `bit_rate` (the container's overall
    bits per second) / `creation_time` come from the container itself and
    back the output-name tokens `{title}` `{chapters}` `{bitrate}`
    `{creation-time}` (`core.naming`); each is None when the file has none.

    The last four are only ever populated for HDR content (see
    `_probe_hdr_static_metadata`) -- ST 2086 mastering-display luminance and
    MaxCLL/MaxFALL, when the source actually carries them. Confirmed to
    matter for real: `libplacebo_tonemap_vf`'s BT.2390 tonemap reads the
    metadata's *values* off the frame automatically (no filter option
    needed), and `mastering_max_nits is not None AND max_cll` together (a
    mastering peak alone is deliberately not enough -- see that function's
    docstring for a real source where trusting the peak alone made results
    *worse*) decide whether that function turns `peak_detect` off.
    Surfaced to the user via the info tooltip too, since it's no longer
    just trivia.

    This is what makes `Select` mean something concrete: EncodingTab
    auto-resolves Encoder/Audio Codec/Profile/Level/Channels/Sample Rate/
    Bitrate from this, so an untouched form re-encodes at (close to) the
    source's own parameters rather than staying an unresolved placeholder.
    It also lets the tabs default the output container to the input's own,
    and — on Muxing, which never re-encodes — work out which containers the
    file can legally be remuxed into (`formats.containers_for`).

    `has_video`/`has_audio` answer a different question than `video`/`audio`:
    whether a stream of that kind exists *at all*, independent of whether its
    codec was one this app recognizes. `False` only when the probe genuinely
    ran and found no such stream; `True` when one was found (named or not);
    `None` when the probe itself never completed (no ffmpeg, unreadable
    file) — "unknown", which must never be treated as "absent". `hdr` follows
    the same three-state shape: `None` until a video stream has actually been
    identified, then `True`/`False` from its color_transfer tag (see
    `_HDR_TRANSFERS`) — never a guess.

    `video`/`audio`/`video_profile`/etc. describe only the *first* stream of
    each kind (most of the app models exactly one video and one audio
    stream). `video_streams`/`audio_streams` are the exception: every stream
    of that kind, in order, each described by `_describe_video_stream`/
    `_describe_audio_stream` — what Muxing's track box (and its "Add Stream"
    picker) and Encoding's multi-track audio picker offer, and what
    `channels_display_for` / `sample_rate_display_for` / `bitrate_display_for`
    can't resolve to one of this app's own options is simply left as the raw
    ffprobe value instead of
    None, since a per-stream settings UI still wants *something* to show even
    for a channel layout or rate this app has no named option for.

    Entirely optional. Any missing key comes back None (or an empty list for
    `audio_streams`), and every failure path (no ffmpeg on PATH, unreadable
    file, odd JSON, a slow probe) returns that same "unknown" shape rather
    than raising, because nothing here is required for the UI to function —
    it only ever *improves* defaults.

    Runs a subprocess, so callers must keep it off the GUI thread (MainWindow
    runs it on the same worker as the thumbnail decode)."""
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

    # File size needs no subprocess at all -- best-effort and independent of
    # whether ffprobe itself succeeds below.
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
    # The extension as read off disk, not filtered to this app's own output
    # containers -- an import-only format (.vob, .ts, .mxf, ...) still shows
    # correctly in the info tooltip. Callers that auto-adopt an *output*
    # container (MuxingTab/EncodingTab.on_media_info) separately re-check it
    # against `formats.containers()`, so a source extension this app doesn't
    # offer as an export target is never mistakenly auto-selected there.
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
    # Container tag names are case-insensitive in practice (Matroska writes
    # TITLE, MP4 title), so match them that way.
    tags = {str(k).lower(): v for k, v in (container_info.get("tags") or {}).items()}
    info["title"] = (tags.get("title") or "").strip() or None
    info["creation_time"] = tags.get("creation_time") or None
    info["chapters"] = len(payload.get("chapters") or []) or None

    audio_index = 0
    video_index = 0
    # First stream of each kind wins for the singular video/audio_* fields —
    # the app models exactly one video and one audio stream there — but
    # video_streams/audio_streams collect every one, for Muxing's track box
    # and Encoding's multi-track audio picker.
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
                # Static HDR metadata (ST 2086 mastering luminance, MaxCLL/
                # MaxFALL) is a separate probe -- see
                # _probe_hdr_static_metadata for why it can't be folded into
                # this same query. Only worth running for actual HDR content.
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


# A start time at or under this is ordinary (muxer padding, an edit list): the
# container's duration is trusted without a second look.
_START_TRUST_SECS = 1.0
# How close the file's real last timestamp must be to one of the two candidate
# ends (see `_effective_duration`) to count as matching it.
_END_MATCH_SECS = 1.0


def _tail_end_time(path, start, header):
    """Where the file's last packet ends (largest `pts + duration` over every
    stream), or None if it can't be told. Seeks to the last ~10s and reads on to
    the end -- roughly one GOP of packets, never the whole file -- so it costs
    tens of milliseconds even on a feature-length file.

    The interval is given an explicit end (past both candidate ends, so the file's
    own end still stops it): an open-ended `T%` came back empty, with no error, on
    about a third of runs of the same command on the same file (8 of 30, then 8 of
    30 again), where a closed one succeeded 30 of 30. One retry covers what's left."""
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
    """The file's real length, given the container's own `header` duration and
    `start` time.

    Some files (a clip cut out of a longer one with its original timestamps kept)
    start far into the timeline -- `start` is minutes in -- and carry a header
    duration that is the END timestamp rather than the length: a 35s clip starting
    at 5465s says 5501s. ffmpeg itself is unaffected (it rebases every output to 0
    and writes the real length back), but everything the app derives from the number
    is wrong: the tooltip, the `{bitrate}` token, the queue's progress denominator,
    the preview sample positions. A file starting at ~0 is trusted as is. Otherwise
    the last real timestamp decides between the two readings -- it sits at `header`
    when the header is an end time (length = header - start) and at `start + header`
    when the header is honest -- and anything that can't be told keeps the header,
    so this is never worse than trusting it."""
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
    """Best-effort length of `path` in seconds (a float), or None.

    Same contract as `probe_media`: every failure path (no ffprobe, an
    unreadable file, a container that reports no duration) returns None
    rather than raising, and it gives the same corrected length
    (`_effective_duration`). The queue's job runner uses it as the progress
    denominator for an untrimmed job, and the preview fallback to place its
    frames. Runs a subprocess, so keep it off the GUI thread (`FfmpegJob` calls
    it from its worker)."""
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
    """Best-effort post-encode check: does `path`'s video stream actually
    read as SDR now? Used as a safety net right after an HDR->SDR tonemap
    job finishes (`core.ffmpeg_runner.FfmpegJob`, gated by
    `core.ffmpeg_build.uses_hdr_tonemap()`).

    This exists on top of, not instead of, the verification already done at
    development time (see `libplacebo_tonemap_vf`'s block comment -- three
    independent checks confirming `tonemapping=bt.2390` genuinely runs).
    That confirms the *filter* works; it says nothing about whether *this
    specific job's actual output* came out tagged correctly -- a future
    ffmpeg/libplacebo regression, or an unusual muxer that doesn't propagate
    the requested `color_primaries`/`color_trc`/`colorspace` the way mp4/mkv
    do, would still slip through undetected without re-checking the real
    file. The failure mode this guards against is exactly what motivated
    it: shipping a file that's still HDR data under an SDR label, which
    every consumer (a player, an NLE) then displays wrong with no warning --
    worse than not tone-mapping at all.

    Returns True (confirmed SDR), False (still reads an HDR transfer
    characteristic -- something went wrong), or None (the probe itself
    failed -- "unknown", and must never be treated as a failure, same
    three-state convention as every other probe result in this module)."""
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
    """Whether the installed ffmpeg understands `-fps_mode` (added in ffmpeg
    5.1, mid-2022) rather than only the older, deprecated `-vsync`. Checked
    once per process (`ffmpeg -h full`'s own option listing) and cached --
    `core.ffmpeg_build` calls this every job, and a subprocess per job would
    be wasteful for an answer that can't change mid-run. Any failure (no
    ffmpeg on PATH, a timeout) is cached as False, the safe fallback: a job
    that then uses `-vsync cfr` still runs, where guessing True and being
    wrong would fail every job outright."""
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
    """Whether the real tonemap filter actually runs on this machine: one
    black frame through `libplacebo_tonemap_vf()` on an explicitly created
    Vulkan device, exactly the way a real HDR->SDR job launches it. Being
    listed by `-filters` proves nothing about that -- it says the filter was
    compiled in, not that a Vulkan driver is there to run it on. A crash
    (the dev machine's implicit-device segfault gave a nonzero exit and no
    stderr), a hang and a missing ffmpeg all count as "doesn't run"."""
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
    """Why HDR->SDR isn't available, or None when it is: `LIBPLACEBO_MISSING`
    (this ffmpeg build doesn't have the `libplacebo` filter) or
    `LIBPLACEBO_NO_VULKAN` (it does, but the filter can't run on this machine
    -- no usable Vulkan driver/device). libplacebo is what gets a real BT.2390
    curve (`tonemapping=bt.2390`) rather than the classic `zscale`+`tonemap`
    chain's fixed algorithm list (none/linear/gamma/clip/reinhard/hable/
    mobius, no BT.2390 among them), and it needs a build compiled with it in
    *and* a working Vulkan setup at runtime. Checked once per process and
    cached, same reasoning as `supports_fps_mode` -- the Vulkan probe is a
    real ffmpeg run (about a second, shader compile included), so
    `MainWindow` warms it on a worker at startup. Behind a lock: a caller
    that arrives mid-probe waits for that answer rather than starting a
    second one."""
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
    """`libplacebo_problem()` as one sentence for a dialog, error or tooltip
    ('' when there's no problem)."""
    problem = libplacebo_problem()
    if problem == LIBPLACEBO_MISSING:
        return ("This ffmpeg install doesn't have libplacebo (needed for accurate BT.2390 "
                "tone-mapping) compiled in. Update ffmpeg.")
    if problem == LIBPLACEBO_NO_VULKAN:
        return ("ffmpeg has libplacebo, but it couldn't run on this machine — HDR to SDR "
                "needs a working Vulkan driver. Update your graphics driver.")
    return ""


def supports_libplacebo():
    """Whether HDR->SDR tone-mapping can run at all (`libplacebo_problem()` is
    None). A failure the probe can't foresee still surfaces as a normal Failed
    job with ffmpeg's own reason -- same safety net as any other capability
    guess."""
    return libplacebo_problem() is None


def av1_preset_range():
    """`(lo, hi)` for SVT-AV1's `-preset` -- confirmed firsthand to swing
    wildly by ffmpeg build: a 2020 build capped at (0, 8), a 2025 build on
    this same machine after updating ffmpeg reports (-2, 13). Hardcoding
    either would eventually be wrong again, so this parses the *installed*
    build's own reported range (`ffmpeg -h encoder=libsvtav1`) once per
    process and caches it, same pattern as the other capability checks here.
    Negative presets (SVT-AV1's "auto" modes) are excluded from the low end
    -- this app offers a plain speed dial, not that special-case. Falls back
    to `(0, 8)` -- this app's own historically-verified floor -- if ffmpeg
    is missing, the encoder isn't compiled in, or the output doesn't parse,
    so the Speed dropdown never ends up empty."""
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
    """Frame indices for `count` evenly-spaced *interior* samples of a
    `total`-frame video — the fractions 1/(count+1) … count/(count+1),
    deliberately avoiding frame 0 and the last frame so a black/blank first
    frame and an end-credits/fade-out last frame don't get picked. Deduped
    so a very short clip doesn't ask for the same index several times.

    Shared with `extract_hdr_tonemapped_thumbnails`'s ffmpeg-side sampling
    (via `_probe_frame_geometry`) so the tonemapped set lands on the exact
    same instants as `extract_video_thumbnails`'s own cv2 set and the two
    stay index-for-index aligned when a caller swaps between them."""
    return sorted({
        min(total - 1, max(0, round(total * (i + 1) / (count + 1))))
        for i in range(count)
    })


def _probe_frame_geometry(video_path):
    """`(total_frame_count, fps)` via cv2, or `(0, 0.0)` if either is
    unusable. Used to turn a frame-index sample point
    (`_interior_sample_frames`) into the timestamp ffmpeg's own `-ss` seek
    needs, in `extract_hdr_tonemapped_thumbnails`.

    cv2's frame count comes from the container's duration, so a file whose header
    is an end timestamp (`_effective_duration`) reports far more frames than it
    has, and every sample would land past its end. When cv2's implied length is
    over 1.5x the real one the count is rebuilt from the real length; a smaller
    disagreement (variable frame rate) is left alone so the tone-mapped set stays
    index-for-index aligned with cv2's own."""
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


# The widest a fallback preview frame is made (ffmpeg scales anything larger
# down): a 4K frame as a raw image is ~25MB, and the carousel never shows it
# bigger than the window.
_PREVIEW_MAX_WIDTH = 1920
# Fallback frames give up after this many misses in a row with none found yet --
# a file ffmpeg can't decode either shouldn't cost ten failed launches.
_PREVIEW_MAX_MISSES = 3


def _has_previewable_video(path):
    """True when `path` has a real video stream -- not just cover art, which is
    one frame stuck on an audio file and must not turn it into a "video" with ten
    identical previews (an audio file keeps its Wave Loop)."""
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
    """`count` interior frames taken with ffmpeg instead of OpenCV -- the fallback
    for a file OpenCV can't seek (it works from the container's frame count, which
    is wrong for a file whose header duration is an end timestamp: every interior
    seek lands before the first real frame). Positions are the same fractions of
    the file's real length (`probe_duration`, corrected), as input-side `-ss`
    seeks, which count from the file's own start whatever its timestamps say.
    Runs one short ffmpeg process per frame, so keep it off the GUI thread."""
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
                 # rgb24 explicitly: a 10-bit source otherwise comes out as a 16-bit
                 # PPM, which Pillow needs ~1.4s a frame to read (0.01s as 8-bit).
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
    """Grabs `count` frames spread evenly across the video's *interior* as
    PIL Images, each shrunk to fit inside `max_size` (w, h) if given: OpenCV first, and ffmpeg
    (`_extract_thumbnails_ffmpeg`) only if OpenCV produced nothing at all.

    Returns a list 1..count long — shorter if the clip is too short to yield
    that many distinct frames or some seeks fail. Returns an empty list if
    nothing decodes at all (not a video, unreadable, missing codec)."""
    return (_extract_thumbnails_cv2(video_path, count, max_size)
            or _extract_thumbnails_ffmpeg(video_path, count, max_size))


def _extract_thumbnails_cv2(video_path, count, max_size=None):
    """The OpenCV half of `extract_video_thumbnails`.

    Sample positions are the fractions 1/(count+1) … count/(count+1) of the
    frame count — deliberately interior, so a black/blank first frame and an
    end-credits or fade-out last frame don't get picked. Falls back to a
    single first-frame read when the container reports no usable frame count
    (some webm / streamed sources)."""
    cap = cv2.VideoCapture(video_path)
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        # No reliable frame count — just take the first frame we can read.
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
                # A frame count that doesn't match the file (see
                # `_extract_thumbnails_ffmpeg`) fails every seek, each one slowly:
                # stop and let the ffmpeg fallback have it.
                misses += 1
                if not frames and misses >= _PREVIEW_MAX_MISSES:
                    break
        return frames
    finally:
        cap.release()


def extract_video_thumbnail(video_path):
    """Back-compat single-frame helper — the first interior sample, or None."""
    frames = extract_video_thumbnails(video_path, count=1)
    return frames[0] if frames else None


# The HDR preview's ffmpeg processes run at below-normal priority: the render is
# speculative background work (it starts on import, before anyone asks for it), and
# may overlap a running queue job — which keeps whatever priority Settings gives it,
# so it wins any contention for the CPU.
_BELOW_NORMAL = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
# A frame that has to share the machine with an encode can take far longer than the
# ~1.5s it takes alone, and a frame that times out is a hole in a set that has to stay
# index-for-index aligned with the raw one.
_HDR_FRAME_TIMEOUT = 90


def hdr_preview_workers():
    """How many tone-mapped preview frames render at once. Measured on a real 4K HDR10
    file (10 frames; a single ffmpeg at a time took 18.6s at 8 logical CPUs, 20.1s at 4):
    a third worker still helped at 8 CPUs (11.7s -> 10.0s) but hardly at 4 (13.9s ->
    13.2s), and two beat one everywhere down to a single CPU (54s -> 42s), since each
    process spends much of its time waiting on the GPU rather than the CPU. So 3 with 8
    or more logical CPUs, else 2 — never 1."""
    return 3 if (os.cpu_count() or 1) >= 8 else 2


def _hdr_decoder_threads():
    """ffmpeg's decoder threads per preview process: its default is one per logical CPU,
    and with several processes at once that is a lot of decoder threads doing nothing.
    Capped at 4 (or the CPU count if lower) the render used the same total CPU time as
    one process at a time (40 vs 43 CPU-seconds) and about half the memory per process."""
    return max(1, min(4, os.cpu_count() or 1))


def extract_hdr_tonemapped_thumbnails(video_path, count=10, should_cancel=None, max_size=None):
    """Like `extract_video_thumbnails`, but each frame is decoded and
    tone-mapped by ffmpeg's own libplacebo BT.2390 chain
    (`libplacebo_tonemap_vf` — the exact filter `build_encode_command` uses
    for a real HDR-to-SDR job) instead of cv2's plain decode.

    This exists because cv2's decode of a real HDR (PQ/BT.2020) source has
    no color management at all — it just clips/rescales the wide-range
    pixel values into 8-bit RGB, which isn't a preview of the tone-mapped
    export, it's a wrong, washed-out picture of the *untouched* HDR data
    (the video genuinely does carry HDR information; cv2 just throws it
    away on the way to a `numpy` array). A preview that actually reflects
    the export has to go through the same decode-then-tonemap pipeline the
    real job runs — which means a real ffmpeg + libplacebo process per
    frame, not a cv2 seek.

    Targets the identical frame numbers `extract_video_thumbnails` samples
    (`_interior_sample_frames`, converted to a timestamp via the source's
    own fps from `_probe_frame_geometry`) so the two frame sets stay
    index-for-index aligned when a caller swaps between them — scrubbing to
    position 3 shows the same instant in either set.

    Runs one short-lived ffmpeg process *per frame* (an input-side `-ss`
    seek is an approximate, fast keyframe seek — the same reason cv2's own
    `CAP_PROP_POS_FRAMES` seek is cheap — followed by a single-frame decode
    and tonemap) rather than one process decoding the whole file: a real
    HDR source is often feature-length, and `select`-ing 10 frames out of a
    full linear decode would mean sitting through the entire file just to
    reach the last one. Ten short seeks, even with libplacebo's own Vulkan
    device-init cost paid ten times over, measured well under the cost of
    one full-file decode on a real multi-GB HDR10 source.

    Returns a list of PIL Images, empty on any failure (no ffmpeg/
    libplacebo, no readable frame count/fps, a decode error) rather than
    raising — this only ever replaces a preview, never blocks the app.
    Callers must check `supports_libplacebo()` themselves before treating an
    empty result as "no HDR to show" vs. "libplacebo isn't available".
    Runs subprocesses, so keep this off the GUI thread.

    `should_cancel`, an optional zero-arg callable, is checked before every
    frame's ffmpeg process starts — a new file replacing the one this render
    was for (see `MainWindow._cancel_hdr_render`) makes the rest of the run
    pointless. Cancelling returns `[]`, same as any other failure, rather
    than a partial set: a caller that expects `count`-many index-aligned
    frames (`extract_video_thumbnails`'s own set) would otherwise get a
    shorter list quietly out of step with it."""
    if not supports_libplacebo():
        return []
    total, fps = _probe_frame_geometry(video_path)
    if total <= 0 or fps <= 0:
        return []
    targets = _interior_sample_frames(total, count)
    fps_flags = ["-fps_mode", "passthrough"] if supports_fps_mode() else ["-vsync", "0"]
    # One metadata probe for the whole file, not per frame -- see
    # libplacebo_tonemap_vf for why peak_detect follows it.
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