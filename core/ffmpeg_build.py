# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi

"""Builds the ffmpeg-python Stream for a job (`core.ffmpeg_vars.JobVars`): one builder per tab
(Muxing is always `-c copy`), plus `compile_command()` for the full argv. Runs nothing."""

import ffmpeg

from core import gpu
from core.tools import tool_path
from core.capabilities import (
    VULKAN_DEVICE_FLAGS, libplacebo_problem_text, libplacebo_tonemap_vf, supports_fps_mode,
    supports_libplacebo,
)

# Global flags for every job, placed right after "ffmpeg" (compile()'s `cmd`) so they can't be
# read as trailing per-file options: -nostdin, -loglevel (error; `level+info` for Detailed
# logging), -nostats, and machine-readable -progress on stdout.
def _runner_flags(loglevel="error"):
    return ["-hide_banner", "-nostdin", "-loglevel", loglevel, "-nostats", "-progress", "pipe:1"]


def _trim_kwargs(job):
    """-ss as an input kwarg and -t as an output kwarg (never an output-side -to), each only
    when set."""
    input_kwargs = {"ss": job.start_time} if job.start_secs else {}
    output_kwargs = {"t": job.duration_time} if job.duration_secs else {}
    return input_kwargs, output_kwargs


def uses_hdr_tonemap(job):
    """Whether `job` runs the libplacebo tone-map (HDR_TO_SDR on a kept video stream of
    an Encode job): decides the Vulkan device flags and the post-encode colour-tag check."""
    return (
        job.source_tab != "Muxing" and job.hdr_to_sdr and not job.strip_video
        and supports_libplacebo()
    )


def _faststart_kwargs(job):
    """+faststart (moov atom first, for progressive playback), only for mp4/mov: other muxers
    ignore it by leniency, not by contract."""
    return {"movflags": "+faststart"} if job.output_ext in (".mp4", ".mov") else {}


def _mux_input(entry, primary, input_kwargs, external_cache):
    """The input a track entry reads from: the primary, or an external file's own (one per
    path, cached), trimmed like the primary."""
    if entry.get("source") == "external" and entry.get("file"):
        path = entry["file"]
        if path not in external_cache:
            external_cache[path] = ffmpeg.input(path, **input_kwargs)
        return external_cache[path]
    return primary


def _input_positions(streams):
    """`{input node: its -i position}` for the inputs `streams` read from. ffmpeg-python numbers
    inputs in graph order and drops unmapped ones, so the primary isn't necessarily 0; a
    `-map_metadata` naming an input needs the real number."""
    from ffmpeg._run import get_stream_spec_nodes
    from ffmpeg.dag import topo_sort
    nodes, _ = topo_sort(get_stream_spec_nodes(ffmpeg.output(*streams, "-")))
    inputs = [node for node in nodes if isinstance(node, ffmpeg.nodes.InputNode)]
    return {node: position for position, node in enumerate(inputs)}


def build_mux_command(job, output_path=None):
    """Muxing job -> Stream: one `-map` per checked track (the primary or an added file), all
    `-c copy`. Writes to `output_path` if given, else the job's own."""
    input_kwargs, output_kwargs = _trim_kwargs(job)
    primary = ffmpeg.input(job.input_file, **input_kwargs)
    external_cache = {}

    streams = []
    if not job.strip_video:
        for entry in job.video_tracks:
            src = _mux_input(entry, primary, input_kwargs, external_cache)
            streams.append(src[f"v:{entry['index']}"])

    if not job.strip_audio:
        for entry in job.audio_tracks:
            src = _mux_input(entry, primary, input_kwargs, external_cache)
            streams.append(src[f"a:{entry['index']}"])

    output_kwargs["c"] = "copy"
    # Global, not `-strict:a`: see build_encode_command.
    output_kwargs["strict"] = "-2"
    output_kwargs.update(_faststart_kwargs(job))
    # No A/V Sync here: -fps_mode needs a real video encode.

    return ffmpeg.output(*streams, output_path or job.output_path, **output_kwargs).overwrite_output()


def build_encode_command(job, output_path=None):
    """Encoding job -> Stream: re-encodes every stream that isn't stripped, with one `-map` per
    output stream (without explicit maps ffmpeg takes one best video and one best audio).
    Writes to `output_path` if given, else the job's own."""
    input_kwargs, output_kwargs = _trim_kwargs(job)
    stream = ffmpeg.input(job.input_file, **input_kwargs)
    external_cache = {}       # one input per external audio file
    streams = []

    if job.strip_video:
        output_kwargs["vn"] = None
    else:
        streams.append(stream["v"])
        output_kwargs["c:v"] = job.video_codec_arg
        # ffmpeg otherwise copies the source's per-track statistics tags (BPS, DURATION,
        # title, ...) onto the re-encoded stream, so tools report the source's bitrate.
        # Side effect: any `-map_metadata` of a type turns off the default copy for every
        # stream, so copied audio tracks get their tags mapped back below.
        output_kwargs["map_metadata:s:v:0"] = "-1"
        if job.hw_encoder:
            # A GPU encoder takes its own rate-control flags, not -crf / -q:v.
            output_kwargs.update(gpu.rate_control_kwargs(job.hw_encoder, job.quality))
        elif job.quality_kind == "crf":
            output_kwargs["crf"] = job.quality
        elif job.quality_kind == "qscale":
            output_kwargs["q:v"] = job.quality
        if job.profile_arg:
            output_kwargs["profile:v"] = job.profile_arg
        if job.level_arg:
            output_kwargs["level:v"] = job.level_arg
        if job.pix_fmt_arg:
            output_kwargs["pix_fmt"] = job.pix_fmt_arg
        if job.quality_preset_arg:
            output_kwargs["quality"] = job.quality_preset_arg
        if job.fps_arg:
            output_kwargs["r"] = job.fps_arg
        output_kwargs.update(job.speed_arg)
        if job.av_sync:
            # -fps_mode needs ffmpeg 5.1+; older builds get -vsync, same behaviour.
            output_kwargs["fps_mode" if supports_fps_mode() else "vsync"] = "cfr"
        video_filters = []
        if job.hdr_to_sdr:
            if not supports_libplacebo():
                # BT.2390 or nothing, never a lesser curve. Normally caught at queue time; this
                # surfaces as a Failed task.
                raise ValueError(f"{libplacebo_problem_text()} Or turn HDR to SDR off.")
            # Explicit tags: libplacebo's target colorspace doesn't reliably reach the output.
            output_kwargs["color_primaries"] = "bt709"
            output_kwargs["color_trc"] = "bt709"
            output_kwargs["colorspace"] = "bt709"
            # peak_detect off only with a mastering peak and a real MaxCLL (see
            # libplacebo_tonemap_vf).
            has_reliable_metadata = job.mastering_max_nits is not None and bool(job.max_cll)
            video_filters.append(libplacebo_tonemap_vf(peak_detect=not has_reliable_metadata))
        if job.scale_vf:
            # After the tone-map, which already ends on a software yuv420p frame.
            video_filters.append(job.scale_vf)
        if video_filters:
            output_kwargs["vf"] = ",".join(video_filters)

    copied = []      # (output position, input stream, cfg) of each copied audio track
    if job.strip_audio or not job.audio_streams:
        output_kwargs["an"] = None
    else:
        # `i` is the position in the output (what `:a:N` addresses), not `src_index`.
        for i, cfg in enumerate(job.audio_streams):
            # A stream from another file is mapped from its own input, trimmed like the primary.
            source = _mux_input(cfg, stream, input_kwargs, external_cache)
            streams.append(source[f"a:{cfg['src_index']}"])
            if cfg["codec_arg"] == "copy":
                copied.append((i, source, cfg))
                # The input seek lands on the keyframe before the trim start; a copied track kept
                # the packets from there, so the muxer shifted the re-encoded streams ~1s later.
                if job.start_secs:
                    output_kwargs[f"copypriorss:a:{i}"] = 0
            output_kwargs[f"c:a:{i}"] = cfg["codec_arg"]
            if cfg["bitrate_arg"]:
                output_kwargs[f"b:a:{i}"] = cfg["bitrate_arg"]
            # -ac / -ar need the explicit "a:": a bare "-ac:0" counts every output stream, so
            # with video at position 0 each audio value landed one stream off.
            if cfg["channels_arg"]:
                output_kwargs[f"ac:a:{i}"] = cfg["channels_arg"]
            if cfg["sample_rate_arg"]:
                output_kwargs[f"ar:a:{i}"] = cfg["sample_rate_arg"]
            if cfg["codec_arg"] != "copy":
                # Stale statistics wiped as for video; the language is re-applied, since audio
                # track selection reads it.
                output_kwargs[f"map_metadata:s:a:{i}"] = "-1"
                if cfg["language"]:
                    output_kwargs[f"metadata:s:a:{i}"] = f"language={cfg['language']}"

    if copied:
        # A copied track keeps its own tags, mapped from the input it is actually read from.
        positions = _input_positions(streams)
        for i, source, cfg in copied:
            output_kwargs[f"map_metadata:s:a:{i}"] = f"{positions[source.node]}:s:a:{cfg['src_index']}"

    # Global, not `-strict:a`: an experimental codec-in-container pairing (TrueHD in MP4) is
    # refused by the muxer's own compliance check, which `-strict:a` doesn't reach.
    output_kwargs["strict"] = "-2"
    output_kwargs.update(_faststart_kwargs(job))

    return ffmpeg.output(*streams, output_path or job.output_path, **output_kwargs).overwrite_output()


def build_command(job, output_path=None):
    """Dispatch on which tab queued `job`."""
    if job.source_tab == "Muxing":
        return build_mux_command(job, output_path)
    return build_encode_command(job, output_path)


def compile_command(job, output_path=None, loglevel="error"):
    """The complete argv for `job`, with the runner's flags: what `FfmpegJob` launches. The Vulkan flags go in the `cmd` prefix, not
    `.global_args()`: after the output spec ffmpeg rejects `-filter_hw_device`."""
    graph = build_command(job, output_path)
    prefix = _runner_flags(loglevel)
    if uses_hdr_tonemap(job):
        prefix += VULKAN_DEVICE_FLAGS
    return ffmpeg.compile(graph, cmd=[tool_path("ffmpeg"), *prefix])
