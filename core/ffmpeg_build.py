# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi

"""Builds the ffmpeg-python Stream for a job (`core.ffmpeg_vars.JobVars`): one builder per tab
(Muxing is always `-c copy`), plus `compile_command()` for the full argv and
`prepare_commands()` for the steps that must run first. Runs nothing."""

import base64
import os

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


# --------------------------------------------------------------------------- #
#  Subtitles
# --------------------------------------------------------------------------- #
def _prepares(job, track):
    """Whether an external text track goes through a prep step: trimmed and converted. ffmpeg
    only drops the cues before a trim's start from a copied stream; converted from a trimmed
    input of its own, the cues came out shifted by the one in progress at the cut."""
    return (track["source"] == "external" and bool(track["file"]) and bool(job.start_secs)
            and track["codec_arg"] != "copy" and track["text_muxer"] is not None)


def _prepared_path(output_path, position, extension):
    """The prep step's output for subtitle track `position`, beside the job's own output."""
    root, _ext = os.path.splitext(output_path)
    return f"{root}.sub{position}{extension}"


def prepare_commands(job, output_path):
    """`[(argv, path)]`: the steps to run before `compile_command`'s argv (same `output_path`),
    each writing `path`, which the job deletes when it ends. A trimmed external text track is
    first cut by a copy into its own format; the main command then converts that file."""
    if job.strip_subtitles:
        return []
    out = []
    for position, track in enumerate(job.subtitle_tracks):
        if not _prepares(job, track):
            continue
        muxer, extension = track["text_muxer"]
        path = _prepared_path(output_path, position, extension)
        argv = [tool_path("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                "-ss", job.start_time]
        if track["start_time"]:
            argv += ["-itsoffset", str(track["start_time"])]
        argv += ["-i", track["file"]]
        if job.duration_secs:
            argv += ["-t", job.duration_time]
        argv += ["-map", f"0:s:{track['index']}", "-c", "copy", "-copypriorss", "0", "-f", muxer, path]
        out.append((argv, path))
    return out


def _subtitle_input(job, track, position, primary, input_kwargs, cache, output_path):
    """`(input, index)` a subtitle track reads from: the primary; a prepared file; or an external
    file of its own, trimmed like the primary and moved back to its own start (ffmpeg rebases
    every input to 0, which moved a .sup's first picture to the start)."""
    if track["source"] != "external" or not track["file"]:
        return primary, track["index"]
    if _prepares(job, track):
        path, kwargs, index = _prepared_path(output_path, position, track["text_muxer"][1]), {}, 0
    else:
        path, kwargs, index = track["file"], dict(input_kwargs), track["index"]
        if track["start_time"]:
            kwargs["itsoffset"] = track["start_time"]
    key = ("subtitle", path, tuple(sorted(kwargs.items())))
    if key not in cache:
        cache[key] = ffmpeg.input(path, **kwargs)
    return cache[key], index


def _map_subtitles(job, primary, input_kwargs, output_path, streams, output_kwargs, cache):
    """Append every subtitle track's `-map` and its codec, language and Default / Forced flags.
    Returns `[(output position, input, index)]` for their tags."""
    mapped = []
    if job.strip_subtitles:
        return mapped
    for i, track in enumerate(job.subtitle_tracks):
        source, index = _subtitle_input(job, track, i, primary, input_kwargs, cache, output_path)
        streams.append(source[f"s:{index}"])
        mapped.append((i, source, index))
        output_kwargs[f"c:s:{i}"] = track["codec_arg"]
        output_kwargs[f"metadata:s:s:{i}"] = f"language={track['language']}"
        output_kwargs[f"disposition:s:{i}"] = track["disposition"]
        # A copied track from a trimmed input of its own keeps the cue in progress at the cut
        # (and ffmpeg then shifts the whole file) unless the packets before it are dropped.
        if track["source"] == "external" and job.start_secs and track["codec_arg"] == "copy":
            output_kwargs[f"copypriorss:s:{i}"] = 0
    return mapped


def _filter_path(path):
    """A file path as a filtergraph option value: the option level escapes \\ ' :, and the
    graph level quotes it (which also covers [ ] , ;), an apostrophe as '\\''."""
    value = path.replace("\\", "/")
    for char in "\\':":
        value = value.replace(char, "\\" + char)
    return "'" + value.replace("'", "'\\''") + "'"


def _text_burn_vf(job, burn):
    """The `subtitles` filter for a burned text track. It reads the file itself, on the file's
    own timeline, so a trimmed picture is moved back there for it and returned after."""
    path = burn["file"] if burn["source"] == "external" and burn["file"] else job.input_file
    offset = job.start_secs + (0 if burn["source"] == "external" else (job.source_start or 0))
    parts = [f"subtitles={_filter_path(path)}:si={burn['index']}"]
    if offset:
        parts = [f"setpts=PTS+{offset:g}/TB", *parts, "setpts=PTS-STARTPTS"]
    return ",".join(parts)


def _vf_node(stream, vf):
    """`stream` through a `-vf` style chain ("name=k=v:k=v,name=a:b") as ffmpeg-python filters,
    for a graph that needs `-filter_complex` (an overlay)."""
    for part in vf.split(","):
        name, _, options = part.partition("=")
        args, kwargs = [], {}
        for option in options.split(":") if options else []:
            key, sep, value = option.partition("=")
            if sep:
                kwargs[key] = value
            else:
                args.append(option)
        stream = stream.filter(name, *args, **kwargs)
    return stream


def _image_burn(job, burn, video, primary, input_kwargs, cache):
    """`video` with a picture subtitle track painted over it, the pictures scaled from their own
    canvas to the video's size."""
    if burn["source"] == "external" and burn["file"]:
        kwargs = dict(input_kwargs)
        if burn["start_time"]:
            kwargs["itsoffset"] = burn["start_time"]
        key = ("burn", burn["file"], tuple(sorted(kwargs.items())))
        if key not in cache:
            cache[key] = ffmpeg.input(burn["file"], **kwargs)
        source = cache[key]
    else:
        source = primary
    pictures = source[f"s:{burn['index']}"]
    size = (job.source_width, job.source_height)
    if all(size) and (burn["width"], burn["height"]) != size:
        pictures = pictures.filter("scale", *size)
    return ffmpeg.overlay(video, pictures, eof_action="pass")


# --------------------------------------------------------------------------- #
#  Chapters
# --------------------------------------------------------------------------- #
def _chapter_kwargs(job, streams, primary):
    """`-map_chapters`: -1 to strip; the ffmetadata input `compile_command` adds last for edited
    chapters; else the source's own when other files are inputs too (ffmpeg would take the first
    input that has any)."""
    positions = _input_positions(streams)
    if job.strip_chapters or job.chapters == []:
        return {"map_chapters": -1}
    if job.chapters:
        return {"map_chapters": len(positions)}
    if len(positions) > 1:
        own = positions.get(primary.node)
        return {"map_chapters": own if job.source_has_chapters and own is not None else -1}
    return {}


def _ffmetadata(chapters):
    """An FFMETADATA1 document holding `chapters` (seconds -> milliseconds)."""
    def escape(text):
        for char in "\\=;#\n":
            text = text.replace(char, "\\" + char)
        return text
    lines = [";FFMETADATA1"]
    for chapter in chapters:
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={round(chapter['start'] * 1000)}",
                  f"END={round(chapter['end'] * 1000)}", f"title={escape(chapter['title'])}"]
    return "\n".join(lines) + "\n"


def _default_flag(output_kwargs, letter, position, entry):
    """Set or clear the Default flag of output stream `letter:position` when the entry says which.
    `+` / `-` change only that flag: a bare `-disposition` would also wipe the others (cover art's
    attached_pic, ...)."""
    if "default" in entry:
        output_kwargs[f"disposition:{letter}:{position}"] = "+default" if entry["default"] else "-default"


def build_mux_command(job, output_path=None):
    """Muxing job -> Stream: one `-map` per checked track (the primary or an added file), all
    `-c copy`. Writes to `output_path` if given, else the job's own."""
    input_kwargs, output_kwargs = _trim_kwargs(job)
    primary = ffmpeg.input(job.input_file, **input_kwargs)
    external_cache = {}

    streams = []
    if not job.strip_video:
        for i, entry in enumerate(job.video_tracks):
            src = _mux_input(entry, primary, input_kwargs, external_cache)
            streams.append(src[f"v:{entry['index']}"])
            _default_flag(output_kwargs, "v", i, entry)

    if not job.strip_audio:
        for i, entry in enumerate(job.audio_tracks):
            src = _mux_input(entry, primary, input_kwargs, external_cache)
            streams.append(src[f"a:{entry['index']}"])
            _default_flag(output_kwargs, "a", i, entry)

    # Tags travel with a copy by default: a `-map_metadata` here would switch that off for
    # every stream.
    _map_subtitles(job, primary, input_kwargs, output_path or job.output_path, streams, output_kwargs,
                   external_cache)
    output_kwargs.update(_chapter_kwargs(job, streams, primary))
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
        burn = job.burn_subtitle
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
        if burn and burn["image"]:
            # Pictures overlay the (tone-mapped) frame, so the chain becomes a graph.
            video = stream["v"]
            if video_filters:
                video = _vf_node(video, ",".join(video_filters))
            video = _image_burn(job, burn, video, stream, input_kwargs, external_cache)
            if job.scale_vf:
                video = _vf_node(video, job.scale_vf)
            streams[-1] = video
            video_filters = []
        else:
            if burn:
                # After the tone-map: text drawn onto the HDR picture would be tone-mapped too.
                video_filters.append(_text_burn_vf(job, burn))
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

    subtitles = _map_subtitles(job, stream, input_kwargs, output_path or job.output_path, streams,
                               output_kwargs, external_cache)
    if copied or subtitles:
        # A copied track keeps its own tags, mapped from the input it is actually read from.
        positions = _input_positions(streams)
        for i, source, cfg in copied:
            output_kwargs[f"map_metadata:s:a:{i}"] = f"{positions[source.node]}:s:a:{cfg['src_index']}"
        for i, source, index in subtitles:
            output_kwargs[f"map_metadata:s:s:{i}"] = f"{positions[source.node]}:s:s:{index}"
    output_kwargs.update(_chapter_kwargs(job, streams, stream))

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
    args = ffmpeg.compile(graph, cmd=[tool_path("ffmpeg"), *prefix])
    if job.chapters and not job.strip_chapters:
        # Edited chapters come in as an FFMETADATA input after the others (a data: URI, so
        # there's no file to write or clean up); `-map_chapters` already names its position.
        document = base64.b64encode(_ffmetadata(job.chapters).encode("utf-8")).decode("ascii")
        last = max(i for i, arg in enumerate(args) if arg == "-i")
        args[last + 2:last + 2] = ["-f", "ffmetadata", "-i", f"data:text/plain;base64,{document}"]
    return args
