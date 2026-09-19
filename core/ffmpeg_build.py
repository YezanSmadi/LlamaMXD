"""Builds an ffmpeg-python Stream from the currently-loaded job in
`core.ffmpeg_vars`. Two separate builders, one per source tab, rather than
one function trying to cover both -- see CLAUDE.md's Muxing/Encoding split
("Muxing never re-encodes... that split is what stops the two tabs from
collapsing into one fuzzy thing"). The same split applies here: a Mux job's
arguments (track picks, external files, always `-c copy`) and an Encode
job's arguments (codec/profile/level/quality, HDR, per-stream re-encode
options) don't share enough shape to be worth merging.

Call `build_command()` after `ffmpeg_vars.load(settings, source_tab)` --
this reads the module's current values, it doesn't take a settings dict
itself. This is a plain Stream builder; nothing here runs anything. The
queue runs jobs through `core.ffmpeg_runner`, using `compile_command()`
for the full argv.
"""

import ffmpeg

from core import ffmpeg_vars as v
from core import gpu
from core.tools import tool_path
from core.utilities import (
    VULKAN_DEVICE_FLAGS, libplacebo_tonemap_vf, supports_fps_mode, supports_libplacebo,
)

# Global flags every queued job runs with. They go right after "ffmpeg"
# (via compile()'s `cmd`), not at the end where ffmpeg-python puts
# global_args(), so ffmpeg can never read them as trailing per-file options.
#   -nostdin            ffmpeg otherwise watches stdin for keypresses
#   -loglevel error     stderr carries only errors -> the failure message
#   -nostats            no carriage-return stats line on stderr
#   -progress pipe:1    machine-readable key=value progress on stdout
_RUNNER_FLAGS = ["-hide_banner", "-nostdin", "-loglevel", "error", "-nostats", "-progress", "pipe:1"]

# HDR->SDR: libplacebo's BT.2390 EETF curve -- see libplacebo_tonemap_vf /
# VULKAN_DEVICE_FLAGS in core/utilities.py (moved there so
# extract_hdr_tonemapped_thumbnails' preview pass can share the identical
# filter string with this real-encode path without a circular import).
# Gated by supports_libplacebo() in both build_encode_command (raises rather
# than falling back to a less-accurate curve when it's missing -- see there)
# and EncodingTab._validate_settings (blocks the job before it's even
# queued, with a message telling the user to update ffmpeg).


def _trim_kwargs():
    """-ss as an input kwarg, -t as an output kwarg -- shared by both
    builders so neither can reintroduce the -ss/-to bug documented on
    END_TIME/END_SECS in core/ffmpeg_vars.py. Omitted entirely when unset,
    rather than passed as "00:00:00", so an untrimmed job's compiled
    command doesn't carry a no-op -ss/-t."""
    input_kwargs = {"ss": v.START_TIME} if v.START_SECS else {}
    output_kwargs = {"t": v.DURATION_TIME} if v.DURATION_SECS else {}
    return input_kwargs, output_kwargs


def uses_hdr_tonemap():
    """Whether the *currently-loaded* job's compiled command needs the
    libplacebo tonemap chain -- shared by build_encode_command (which
    raises rather than using it if libplacebo isn't actually available; see
    there), compile_command (whether to prepend the Vulkan device-init
    flags that chain needs -- VULKAN_DEVICE_FLAGS), and QueueTab._process_next
    (whether to ask FfmpegJob to verify the finished output's color tags
    actually landed as SDR -- see core.ffmpeg_runner's verify_hdr_tag kwarg
    and core.utilities.verify_hdr_sdr_tag). Mirrors build_encode_command's
    own HDR_TO_SDR gate exactly (not stripped, not a Mux job -- Muxing has
    no HDR toggle at all). By the time compile_command reads this,
    build_command() has already run and would have raised if HDR_TO_SDR
    were set without libplacebo actually being there, so supports_libplacebo()
    here is really just re-confirming a precondition that's already true,
    not making a fresh decision. No longer module-private (the leading `_`
    dropped) now that it has a caller outside this module."""
    return (
        v.SOURCE_TAB != "Muxing" and v.HDR_TO_SDR and not v.STRIP_VIDEO
        and supports_libplacebo()
    )


def _faststart_kwargs():
    """+faststart is a private option of the mov/mp4/ismv muxer -- it moves
    the moov atom to the front so playback (mainly progressive-download/web
    streaming) can start before the whole file arrives; it does nothing for
    local random-access playback or editor import, and is a purely lossless
    metadata rewrite either way. Confirmed on this app's own ffmpeg that a
    non-mov muxer (.mkv) silently ignores it rather than erroring -- but
    that's this build's leniency, not a documented guarantee, so it's only
    ever passed when the output is actually mp4/mov."""
    return {"movflags": "+faststart"} if v.OUTPUT_EXT in (".mp4", ".mov") else {}


def _mux_input(entry, primary, input_kwargs, external_cache):
    """The ffmpeg-python input a track entry reads from -- the primary input,
    or an external file's own input (one per distinct path, cached, so
    pulling several tracks from the same browsed-in file doesn't re-declare
    it as a separate ffmpeg input each time). An external file gets the
    *same* trim as the primary -- an external track is assumed to line up
    with the primary input's own timeline."""
    if entry.get("source") == "external" and entry.get("file"):
        path = entry["file"]
        if path not in external_cache:
            external_cache[path] = ffmpeg.input(path, **input_kwargs)
        return external_cache[path]
    return primary


def build_mux_command(output_path=None):
    """Muxing job -> Stream. Every stream is `-c copy` -- the only
    per-job variables are *which* tracks get mapped and from which file(s)
    (the primary input, or ones pulled in via a panel's "Add Stream").
    `VIDEO_TRACKS`/`AUDIO_TRACKS` (see ffmpeg_vars.derive) each carry every
    *checked* track for that kind -- zero, one or several -- so this needs
    one `-map` per entry, the same multi-map pattern build_encode_command
    uses for its own multi-stream audio. Writes to `output_path` when given,
    else the job's own OUTPUT_PATH."""
    input_kwargs, output_kwargs = _trim_kwargs()
    primary = ffmpeg.input(v.INPUT_FILE, **input_kwargs)
    external_cache = {}

    streams = []
    if not v.STRIP_VIDEO:
        for entry in v.VIDEO_TRACKS:
            src = _mux_input(entry, primary, input_kwargs, external_cache)
            streams.append(src[f"v:{entry['index']}"])

    if not v.STRIP_AUDIO:
        for entry in v.AUDIO_TRACKS:
            src = _mux_input(entry, primary, input_kwargs, external_cache)
            streams.append(src[f"a:{entry['index']}"])

    output_kwargs["c"] = "copy"
    # Global, NOT audio-scoped (`-strict:a`) -- see build_encode_command's
    # comment for why: this has to satisfy the *muxer's* own compliance
    # gate, which `-strict:a` doesn't reach.
    output_kwargs["strict"] = "-2"
    output_kwargs.update(_faststart_kwargs())
    # AV_SYNC has no mapping here: Muxing is always -c copy, and -fps_mode
    # (see build_encode_command) has nothing to act on without a real video
    # encode -- there's no equivalent for a copied stream.

    return ffmpeg.output(*streams, output_path or v.OUTPUT_PATH, **output_kwargs).overwrite_output()


def build_encode_command(output_path=None):
    """Encoding job -> Stream. Re-encodes whichever stream isn't stripped --
    EncodingTab never lets a job queue with a present stream still on
    `Select` (formats.VIDEO_ENCODERS/AUDIO_ENCODERS have no "Select" entry;
    ffmpeg_vars.derive() falling back to "copy" for that case is a defensive
    no-op that should be unreachable, not a real code path any more). Writes
    to `output_path` when given, else the job's own OUTPUT_PATH.

    Unlike video (always at most one stream), audio needs explicit `-map`s
    the moment more than one output stream is possible -- a bare `ffmpeg.
    output(stream, ...)` with no `-map` at all only ever gets ffmpeg's own
    "one best video + one best audio" default. So `streams` collects every
    output component (the video stream, if kept, then one entry per included
    audio stream from `AUDIO_STREAMS`) and they're all passed as positional
    args to `ffmpeg.output()` together -- the same multi-`-map` pattern
    `build_mux_command` already uses for its own external-track case."""
    input_kwargs, output_kwargs = _trim_kwargs()
    stream = ffmpeg.input(v.INPUT_FILE, **input_kwargs)
    streams = []

    if v.STRIP_VIDEO:
        output_kwargs["vn"] = None
    else:
        streams.append(stream["v"])
        output_kwargs["c:v"] = v.VIDEO_CODEC_ARG
        # Encoding always genuinely re-encodes the video stream when it's
        # kept (see the module docstring for build_mux_command/
        # build_encode_command's split -- Muxing is the only copy path) --
        # confirmed directly that ffmpeg's default per-stream metadata
        # mapping otherwise carries the *source's* stale statistics tags
        # (title, BPS/DURATION/NUMBER_OF_FRAMES-<lang> -- mkvmerge/lavf's own
        # per-track stats) onto the new stream untouched: re-encoding a
        # trimmed 2-minute HEVC clip out of an 87-minute source kept the
        # source's title text ("...@ 7561 kbps") and its BPS-eng tag
        # (7562021, the *source's* real bitrate) verbatim, so every player/
        # tool reading those tags (MediaInfo's own "Bit rate" field among
        # them) reported the same wrong, unchanged number regardless of the
        # new encode's actual resolution or bitrate. A video track's
        # language tag is never used for playback/track-selection the way an
        # audio one is, so wiping it along with the rest costs nothing real.
        output_kwargs["map_metadata:s:v:0"] = "-1"
        if v.HW_ENCODER:
            # Hardware Acceleration (Settings) resolved to a real GPU
            # encoder for this codec -- see core/gpu.py. None of NVENC/QSV/
            # AMF take -crf/-q:v; rate_control_kwargs picks whichever flag
            # that encoder family actually uses instead.
            output_kwargs.update(gpu.rate_control_kwargs(v.HW_ENCODER, v.QUALITY))
        elif v.QUALITY_KIND == "crf":
            output_kwargs["crf"] = v.QUALITY
        elif v.QUALITY_KIND == "qscale":
            output_kwargs["q:v"] = v.QUALITY
        if v.PROFILE_ARG:
            output_kwargs["profile:v"] = v.PROFILE_ARG
        if v.LEVEL_ARG:
            output_kwargs["level:v"] = v.LEVEL_ARG
        if v.PIX_FMT_ARG:
            output_kwargs["pix_fmt"] = v.PIX_FMT_ARG
        if v.QUALITY_PRESET_ARG:
            output_kwargs["quality"] = v.QUALITY_PRESET_ARG
        if v.FPS_ARG:
            output_kwargs["r"] = v.FPS_ARG
        output_kwargs.update(v.SPEED_ARG)
        if v.AV_SYNC:
            # -fps_mode is the current, non-deprecated way to say "hold a
            # constant rate" (duplicate/drop frames as needed) -- but it
            # only exists from ffmpeg 5.1 (mid-2022) onward. An older
            # install (confirmed: this app's own dev machine runs a 2020
            # build) doesn't recognize it at all and would fail every job
            # outright, so supports_fps_mode() checks once and falls back to
            # the older -vsync for exactly the same "cfr" behaviour.
            output_kwargs["fps_mode" if supports_fps_mode() else "vsync"] = "cfr"
        video_filters = []
        if v.HDR_TO_SDR:
            if not supports_libplacebo():
                # No less-accurate substitute (e.g. the classic zscale+
                # tonemap=hable chain) gets used here -- BT.2390 or nothing.
                # EncodingTab._validate_settings should have already caught
                # this before the job was even queued; reaching here means
                # ffmpeg changed out from under a queued job (e.g. an
                # in-flight preset from before an ffmpeg downgrade), so it
                # surfaces through the same "couldn't build the command"
                # Failed-task path QueueTab._process_next already has for a
                # settings combination the builder can't express.
                raise ValueError(
                    "HDR to SDR needs libplacebo for accurate BT.2390 "
                    "tone-mapping, and this ffmpeg install doesn't have it "
                    "compiled in. Update ffmpeg, or turn HDR to SDR off."
                )
            # Explicit output tags -- verified libplacebo's target colorspace
            # doesn't reliably propagate to the output stream's own tags on
            # its own, so a player/editor has no guarantee the result is
            # really BT.709 without these.
            output_kwargs["color_primaries"] = "bt709"
            output_kwargs["color_trc"] = "bt709"
            output_kwargs["colorspace"] = "bt709"
            # peak_detect off only when there's a mastering peak *and* a
            # real, nonzero MaxCLL -- a mastering peak alone isn't enough
            # (confirmed both ways on real commercial sources: Spider-Man 3
            # Sheriff.mp4 has a genuine measured MaxCLL and disabling
            # peak_detect there cut highlight clipping 87-98%; Beauty and
            # the Beast's HDR source has a mastering peak but MaxCLL/MaxFALL
            # both 0 -- unset, not a real measurement -- and disabling
            # peak_detect there made the output measurably *dimmer and
            # lower-contrast*, the opposite of an improvement). See
            # libplacebo_tonemap_vf's docstring for both sets of numbers.
            has_reliable_metadata = v.MASTERING_MAX_NITS is not None and bool(v.MAX_CLL)
            video_filters.append(libplacebo_tonemap_vf(peak_detect=not has_reliable_metadata))
        if v.SCALE_VF:
            # After the tonemap, if any -- libplacebo's own filter string
            # already ends back on a plain software yuv420p frame (see
            # libplacebo_tonemap_vf), so a second, ordinary scale filter
            # chains onto it in the same -vf with nothing else needed in
            # between. Independent of HDR_TO_SDR otherwise: a Resolution
            # pick downscales an SDR source exactly the same way.
            video_filters.append(v.SCALE_VF)
        if video_filters:
            output_kwargs["vf"] = ",".join(video_filters)

    if v.STRIP_AUDIO or not v.AUDIO_STREAMS:
        output_kwargs["an"] = None
    else:
        # `i` here is the stream's position in the *output* file (0, 1, 2,
        # ...), which is what ffmpeg's per-stream option suffixes (`:a:0`,
        # `:a:1`, ...) address -- not `src_index` (the stream's position in
        # the *source*), which only matches when every source stream up to
        # that point was included.
        for i, cfg in enumerate(v.AUDIO_STREAMS):
            streams.append(stream[f"a:{cfg['src_index']}"])
            output_kwargs[f"c:a:{i}"] = cfg["codec_arg"]
            if cfg["bitrate_arg"]:
                output_kwargs[f"b:a:{i}"] = cfg["bitrate_arg"]
            # -ac / -ar need the explicit "a:" type qualifier, unlike -c:a: /
            # -b:a: which already carry it -- confirmed directly: a bare
            # "-ac:0"/"-ar:0" specifier counts across *every* output stream
            # (video included), not just audio ones, so with a kept video
            # stream at output position 0, "-ac:0"/"-ar:0" silently landed on
            # the video stream (a no-op) and every audio stream's value
            # shifted onto the next one's slot instead of its own.
            if cfg["channels_arg"]:
                output_kwargs[f"ac:a:{i}"] = cfg["channels_arg"]
            if cfg["sample_rate_arg"]:
                output_kwargs[f"ar:a:{i}"] = cfg["sample_rate_arg"]
            if cfg["codec_arg"] != "copy":
                # Same stale-statistics problem as the video stream above,
                # for a genuinely re-encoded audio track -- a copied
                # (Passthru) stream's tags stay accurate (nothing about it
                # actually changed) so this only ever runs for a real
                # transcode. Unlike video, a wrong language tag here is a
                # real, player-visible regression (audio track selection
                # reads it), so it's wiped and then explicitly reapplied
                # from the probe rather than just dropped.
                output_kwargs[f"map_metadata:s:a:{i}"] = "-1"
                if cfg["language"]:
                    output_kwargs[f"metadata:s:a:{i}"] = f"language={cfg['language']}"

    # **Global, NOT audio-scoped.** This exists for non-standard audio/
    # container pairings (TrueHD/E-AC3 with Atmos side data, etc.) -- it used
    # to be scoped to `-strict:a` on the theory that the video codec context
    # had no business being loosened by an audio-only concern, which sounds
    # right but is wrong in practice: confirmed directly (a real TrueHD-in-MP4
    # source, `Spider-Man 3 Sheriff.mp4`) that `-strict:a -2` alone still
    # crashes the job outright --
    #   `[mp4] truehd in MP4 support is experimental, add '-strict -2' ...`
    #   `[out#0/mp4] Could not write header (incorrect codec parameters ?):
    #    Experimental feature`
    #   `[[some internal task]] Terminating thread with return code
    #    -733130664 (Experimental feature)`
    #   `Nothing was written into output file, because at least one of its
    #    streams received no packets.`
    # -- reproduced 100% (5/5), and confirmed independent of everything else
    # in the command (no HDR filter, no Vulkan device, plain `-c:v libx264`):
    # it's the **muxer's** own compliance gate objecting to an experimental
    # codec-in-container pairing, not the audio codec context's -- `-strict:a`
    # sets the latter, not the former, so it never actually reaches the check
    # that's failing. A bare, unscoped `-strict -2` does. (The log's
    # "Terminating thread" line names an internal scheduler task, not the
    # `-vf` video filter -- it still appears verbatim with no `-vf` on the
    # command line at all, which is what proved this had nothing to do with
    # tone-mapping.)
    output_kwargs["strict"] = "-2"
    output_kwargs.update(_faststart_kwargs())

    return ffmpeg.output(*streams, output_path or v.OUTPUT_PATH, **output_kwargs).overwrite_output()


def build_command(output_path=None):
    """Dispatches on which tab queued the currently-loaded job
    (`ffmpeg_vars.SOURCE_TAB`, set by `ffmpeg_vars.load()`)."""
    if v.SOURCE_TAB == "Muxing":
        return build_mux_command(output_path)
    return build_encode_command(output_path)


def compile_command(output_path=None):
    """The complete argv for the currently-loaded job, with the runner's
    global flags (`_RUNNER_FLAGS`) — what `core.ffmpeg_runner.FfmpegJob`
    launches. The queue passes the job's temp path as `output_path`.

    Must call `build_command()` (not `uses_hdr_tonemap()`) first: SOURCE_TAB/
    HDR_TO_SDR/STRIP_VIDEO are only meaningful once a job's actually loaded,
    same as everything else read off `ffmpeg_vars`, and the check is cheap
    either way. `VULKAN_DEVICE_FLAGS` must land in the `cmd` prefix, not
    ffmpeg-python's `.global_args()` — that appends *after* the compiled
    output spec, and ffmpeg refuses `-filter_hw_device` there ("Invalid
    filter device") since `-init_hw_device` hasn't run yet at that point in
    its own left-to-right option parsing (confirmed directly)."""
    graph = build_command(output_path)
    prefix = list(_RUNNER_FLAGS)
    if uses_hdr_tonemap():
        prefix += VULKAN_DEVICE_FLAGS
    return ffmpeg.compile(graph, cmd=[tool_path("ffmpeg"), *prefix])
