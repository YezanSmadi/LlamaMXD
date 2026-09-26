# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi

"""The Downloader's logic, no UI: fetch a URL's info with the bundled yt-dlp.exe, turn its
formats into the tab's Codec / Resolution / Format options, resolve a pick to the exact streams
(plus a fallback selector in case a site rotates an ID before the job runs), and build the argv."""

import json
import os
import re
import subprocess
import threading

from core import formats, llamalog
from core.tools import find_tool, tool_dir, tool_path

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

MODE_AV = "Video + Audio"
MODE_VIDEO = "Video Only"
MODE_AUDIO = "Audio Only"
MODES = [MODE_AV, MODE_VIDEO, MODE_AUDIO]

BEST_CODEC = "Best Available"
BEST_QUALITY = "Best"
ORIGINAL = "Original"

# Containers a video download can be merged / remuxed into. No '.mov': it adds nothing over
# '.mp4' for a web download and invites codec mismatches.
VIDEO_CONTAINERS = [".mp4", ".mkv", ".webm"]
AUDIO_CONVERSIONS = [".mp3", ".m4a", ".opus", ".flac", ".wav"]   # audio-only outputs
_LOSSLESS = {".flac", ".wav"}
BEST_VBR = "Best (VBR)"
LOSSY_BITRATES = [BEST_VBR, "320 kbps", "256 kbps", "192 kbps", "128 kbps", "96 kbps"]

# yt-dlp refuses older Deno for its JS challenge support; treated as missing.
_DENO_MIN_VERSION = (2, 3, 0)
_FETCH_TIMEOUT_SECS = 90

# vcodec/acodec prefix -> codec display name (formats.py's names, for containers_for).
_VIDEO_FAMILIES = [
    (("avc1", "avc3", "h264"), "H.264"),
    (("hev1", "hvc1", "h265", "hevc"), "H.265"),
    (("vp09", "vp9"), "VP9"),
    (("vp08", "vp8"), "VP8"),
    (("av01", "av1"), "AV1"),
]
_AUDIO_FAMILIES = [
    (("mp4a", "aac"), "AAC"),
    (("opus",), "Opus"),
    (("vorbis",), "Vorbis"),
    (("mp3", "mp4a.40.34", "mp4a.6b"), "MP3"),
    (("ac-3", "ac3"), "AC3"),
    (("ec-3", "eac3"), "E-AC-3"),
    (("flac",), "FLAC"),
]
# The inverse, for the fallback selector: family -> yt-dlp `vcodec^=` prefix.
_VIDEO_PREFIX = {"H.264": "avc1", "H.265": "hvc1", "VP9": "vp09", "VP8": "vp8", "AV1": "av01"}
_AUDIO_PREFIX = {"AAC": "mp4a", "Opus": "opus", "Vorbis": "vorbis", "MP3": "mp3"}

# Characters Windows forbids in a file name -> yt-dlp's look-alikes, so the name reads like the
# title.
_FILENAME_SWAPS = str.maketrans({
    "<": "＜", ">": "＞", ":": "：", '"': "＂", "/": "⧸", "\\": "⧹",
    "|": "｜", "?": "？", "*": "＊",
})
_MAX_STEM = 120


# ---------------------------------------------------------------------- #
#  Tools
# ---------------------------------------------------------------------- #
_deno_checked = False
_deno_path = None
# The startup check runs on a worker while the GUI may be building an argv: without the lock a
# second caller could see "checked, nothing found" mid-check.
_deno_lock = threading.Lock()


def deno_path():
    """Absolute path to a usable Deno (bundled, else PATH), or None if missing or too old.
    Checked once per process (a subprocess), first off the GUI thread."""
    global _deno_checked, _deno_path
    with _deno_lock:
        if not _deno_checked:
            path = find_tool("deno")
            if path:
                try:
                    completed = subprocess.run(
                        [path, "--version"], capture_output=True, text=True,
                        timeout=15, creationflags=_NO_WINDOW,
                    )
                    match = re.search(r"deno (\d+)\.(\d+)\.(\d+)", completed.stdout or "")
                    if match and tuple(int(g) for g in match.groups()) >= _DENO_MIN_VERSION:
                        _deno_path = path
                except (OSError, subprocess.SubprocessError) as exc:
                    llamalog.get("downloader").debug("deno --version failed: %s", exc)
            _deno_checked = True
    return _deno_path


def base_args():
    """The start of every yt-dlp argv: the bundled binary, `--ignore-config` (a user's own
    config would leak into every job), absolute `--js-runtimes` / `--ffmpeg-location` (a
    relative runtime path is silently ignored, and without a location Windows picks the
    ffmpeg), and `--no-playlist`."""
    args = [tool_path("yt-dlp"), "--ignore-config", "--no-playlist"]
    deno = deno_path()
    if deno:
        args += ["--js-runtimes", f"deno:{deno}"]
    ffmpeg_dir = tool_dir("ffmpeg")
    if ffmpeg_dir:
        args += ["--ffmpeg-location", ffmpeg_dir]
    return args


def subprocess_env():
    # UTF-8 output, so titles in any script survive the pipe.
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


# ---------------------------------------------------------------------- #
#  Fetch
# ---------------------------------------------------------------------- #
def fetch_info(url):
    """`(info, error)` for `url`: yt-dlp's `-J` JSON, or None and a short readable reason.
    Blocking (seconds on YouTube), so off the GUI thread."""
    url = (url or "").strip()
    if not url:
        return None, "Paste a video link first."
    argv = base_args() + ["--flat-playlist", "-J", url]
    try:
        completed = subprocess.run(
            argv, capture_output=True, timeout=_FETCH_TIMEOUT_SECS,
            creationflags=_NO_WINDOW, env=subprocess_env(),
        )
    except FileNotFoundError:
        return None, "yt-dlp wasn't found. Reinstall LlamaMXD."
    except subprocess.TimeoutExpired:
        return None, "The site took too long to respond. Check the link and try again."
    except OSError as exc:
        return None, f"Couldn't start yt-dlp: {exc.strerror or exc}"

    stdout = completed.stdout.decode("utf-8", errors="replace")
    stderr = completed.stderr.decode("utf-8", errors="replace")
    if completed.returncode != 0 or not stdout.strip():
        return None, error_reason(stderr.splitlines()) or "yt-dlp couldn't read that link."
    try:
        info = json.loads(stdout)
    except ValueError:
        return None, "yt-dlp returned something unreadable for that link."
    if info.get("_type") in ("playlist", "multi_video"):
        return None, "That link is a playlist. Playlists aren't supported yet — paste a single video's link."
    if not info.get("formats"):
        return None, "No downloadable formats were found at that link."
    return info, None


def error_reason(lines):
    """yt-dlp's last `ERROR:` line without its `ERROR: [extractor] id:` prefix."""
    for line in reversed(lines):
        line = line.strip()
        if line.startswith("ERROR:"):
            text = line[len("ERROR:"):].strip()
            text = re.sub(r"^\[[^\]]+\]\s*(?:[\w-]+:\s*)?", "", text)
            return text
    return ""


def download_thumbnail(url):
    """A PIL image of the thumbnail at `url`, or None, with black letterbox bars trimmed (an
    old video's thumbnail is often 16:9 boxed in 4:3). Blocking: worker thread only."""
    if not url:
        return None
    import io
    import urllib.request

    from PIL import Image
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=15) as response:
            data = response.read()
        with Image.open(io.BytesIO(data)) as img:
            img = img.convert("RGB")
        box = img.convert("L").point(lambda v: 255 if v > 18 else 0).getbbox()
        if box and (box[3] - box[1]) < img.height * 0.95 and (box[2] - box[0]) > img.width * 0.5:
            img = img.crop((0, box[1], img.width, box[3]))
        return img
    except Exception as exc:
        llamalog.get("downloader").warning("Couldn't fetch the thumbnail %s: %s", url, exc)
        return None


def safe_stem(title):
    """A Windows-safe file name stem from a video title."""
    stem = (title or "download").translate(_FILENAME_SWAPS)
    stem = re.sub(r"[\x00-\x1f]", "", stem).strip().rstrip(". ")
    return (stem[:_MAX_STEM].rstrip(". ") or "download")


# ---------------------------------------------------------------------- #
#  Format model
# ---------------------------------------------------------------------- #
def _family(codec, table):
    """Codec display name for a yt-dlp vcodec/acodec string: '?' if unrecognized, None when
    there is no such stream."""
    if codec == "none":
        return None
    if not codec:
        return "?"
    lowered = codec.lower()
    for prefixes, name in table:
        if lowered.startswith(prefixes):
            return name
    return "?"


def parse_formats(info):
    """yt-dlp's `formats` as a compact list, worst to best, without storyboards and DRC
    (quieter duplicate) audio."""
    duration = info.get("duration") or 0
    out = []
    for f in info.get("formats") or []:
        fid = str(f.get("format_id") or "")
        if not fid or f.get("ext") == "mhtml" or f.get("vcodec") == "images" or "-drc" in fid:
            continue
        vcodec, acodec = f.get("vcodec"), f.get("acodec")
        has_video = vcodec != "none" and (vcodec is not None or f.get("height") or f.get("width"))
        has_audio = acodec != "none"
        if not has_video and not has_audio:
            continue
        tbr = f.get("tbr") or 0
        size = f.get("filesize") or f.get("filesize_approx")
        if not size and tbr and duration:
            size = int(tbr * 1000 / 8 * duration)
        out.append({
            "id": fid,
            "ext": "." + (f.get("ext") or "bin"),
            "video": _family(vcodec, _VIDEO_FAMILIES) if has_video else None,
            "audio": _family(acodec, _AUDIO_FAMILIES) if has_audio else None,
            "height": f.get("height") or 0,
            "fps": f.get("fps") or 0,
            "hdr": (f.get("dynamic_range") or "SDR") != "SDR",
            "abr": f.get("abr") or (tbr if not has_video else 0) or 0,
            "size": int(size or 0),
        })
    return out


def _quality_label(fmt):
    """Label for a video format (e.g. 1080p60)."""
    label = f"{fmt['height']}p" if fmt["height"] else "Unknown"
    fps = round(fmt["fps"] or 0)
    if fps > 30:
        label += str(fps)
    if fmt["hdr"]:
        label += " HDR"
    return label


def _bitrate_label(fmt):
    """Label for an audio format (e.g. 129 kbps)."""
    return f"{round(fmt['abr'])} kbps" if fmt["abr"] else "Unknown bitrate"


def modes_for(fmts):
    """The modes this video can be downloaded in."""
    modes = []
    if any(f["video"] for f in fmts):
        modes.append(MODE_AV)
    if any(f["video"] and not f["audio"] for f in fmts):
        modes.append(MODE_VIDEO)
    if any(f["audio"] for f in fmts):
        modes.append(MODE_AUDIO)
    return modes


def _video_pool(fmts, mode):
    """Formats that can supply the picture in a video mode."""
    if mode == MODE_VIDEO:
        return [f for f in fmts if f["video"] and not f["audio"]]
    return [f for f in fmts if f["video"]]


def _audio_pool(fmts):
    """Audio-only formats."""
    solo = [f for f in fmts if f["audio"] and not f["video"]]
    return solo or [f for f in fmts if f["audio"]]


def codecs_for(fmts, mode):
    """Codec dropdown: Best Available, then every recognized codec the mode can use."""
    if mode == MODE_AUDIO:
        found = {f["audio"] for f in _audio_pool(fmts)}
        order = [name for _, name in _AUDIO_FAMILIES]
    else:
        found = {f["video"] for f in _video_pool(fmts, mode)}
        order = [name for _, name in _VIDEO_FAMILIES]
    return [BEST_CODEC] + [name for name in order if name in found]


def _matches_codec(fmt, codec, key):
    """Whether `fmt` fits the Codec dropdown's pick."""
    return codec == BEST_CODEC or fmt[key] == codec


def qualities_for(fmts, mode, codec, audio_format=None):
    """Resolution dropdown. Video modes: Best, then each resolution / frame rate / HDR the codec
    has, best first. Audio Only: the source bitrates for Original, a target bitrate for a lossy
    conversion, nothing for a lossless one."""
    if mode == MODE_AUDIO:
        if audio_format in _LOSSLESS:
            return []
        if audio_format and audio_format != ORIGINAL:
            return list(LOSSY_BITRATES)
        # Streams with no reported bitrate (YouTube's HLS audio) are reachable only via Best.
        pool = [f for f in _audio_pool(fmts)
                if not f["video"] and f["abr"] and _matches_codec(f, codec, "audio")]
        labels = []
        for f in sorted(pool, key=lambda f: f["abr"], reverse=True):
            label = _bitrate_label(f)
            if label not in labels:
                labels.append(label)
        return [BEST_QUALITY] + labels

    pool = [f for f in _video_pool(fmts, mode) if _matches_codec(f, codec, "video")]
    ranked = sorted(pool, key=lambda f: (f["height"], round(f["fps"] or 0), f["hdr"]), reverse=True)
    labels = []
    for f in ranked:
        label = _quality_label(f)
        if label not in labels:
            labels.append(label)
    return [BEST_QUALITY] + labels


def formats_for(fmts, mode, codec, quality, audio_codec=BEST_CODEC):
    """Format dropdown: containers the pick fits without re-encoding (video modes), or Original
    plus the conversions (Audio Only). `audio_codec` (Video + Audio) narrows it to containers
    that also carry that audio codec, so Video Format adapts to the audio pick."""
    if mode == MODE_AUDIO:
        has_solo = any(f["audio"] and not f["video"] for f in fmts)
        return ([ORIGINAL] if has_solo else []) + list(AUDIO_CONVERSIONS)
    return [c for c in VIDEO_CONTAINERS
            if resolve(fmts, mode, codec, quality, c, audio_codec=audio_codec) is not None]


def audio_codecs_for(fmts, mode, codec, quality):
    """Video + Audio's Audio dropdown: Best Available, then every codec a separate audio stream
    can supply for this video pick. Not filtered by the Video Format; that adapts to this."""
    if mode != MODE_AV:
        return []
    plan = resolve(fmts, mode, codec, quality, ".mkv")
    if plan is None or len(plan["parts"]) != 2:
        return []
    order = [name for _, name in _AUDIO_FAMILIES]
    found = {f["audio"] for f in _audio_pool(fmts) if f["audio"] in order}
    return [BEST_CODEC] + [name for name in order if name in found]


def default_format(mode, allowed):
    """The format a fresh fetch or mode switch lands on: '.mp4' when it fits, else the first
    legal container; Original for audio."""
    if mode == MODE_AUDIO:
        return ORIGINAL if ORIGINAL in allowed else (allowed[0] if allowed else "")
    return ".mp4" if ".mp4" in allowed else (allowed[0] if allowed else "")


def _fits(container, video, audio):
    """Whether `container` carries this codec pair without re-encoding ('?' only in .mkv)."""
    if video == "?" or audio == "?":
        return container == ".mkv"
    return container in formats.containers_for(video, audio)


# ---------------------------------------------------------------------- #
#  Resolution + argv
# ---------------------------------------------------------------------- #
def resolve(fmts, mode, codec, quality, container, duration=0, audio_codec=BEST_CODEC):
    """The exact download for one dropdown combination, or None. A JSON-safe dict: `format`
    (the -f selector: pinned IDs, then a fallback), `ext`, `args` (merge / remux / extract
    flags), `parts` ([{"id", "kind", "size"}] in download order) and `post` (None, or
    {"kind": "merge"|"remux"|"convert", "expected_bytes", "media_secs"}). `audio_codec`
    (Video + Audio) narrows the separate audio stream to one codec."""
    if mode == MODE_AUDIO:
        return _resolve_audio(fmts, codec, quality, container, duration)

    candidates = [
        f for f in _video_pool(fmts, mode)
        if _matches_codec(f, codec, "video")
        and (quality == BEST_QUALITY or _quality_label(f) == quality)
        and (f["video"] == "?" or _fits(container, f["video"], None))
    ]
    fmt_ext = container.lstrip(".")
    for video in reversed(candidates):
        if mode == MODE_VIDEO:
            if not _fits(container, video["video"], None):
                continue
            return {
                "format": f"{video['id']}/{_fallback_video(codec, quality, only=True)}",
                "ext": container,
                "args": ["--remux-video", fmt_ext],
                "parts": [{"id": video["id"], "kind": "video", "size": video["size"]}],
                "post": _post("remux", video["size"], duration) if video["ext"] != container else None,
            }
        if video["audio"]:
            if not _fits(container, video["video"], video["audio"]):
                continue
            return {
                "format": f"{video['id']}/{_fallback_video(codec, quality)}",
                "ext": container,
                "args": ["--remux-video", fmt_ext],
                "parts": [{"id": video["id"], "kind": "both", "size": video["size"]}],
                "post": _post("remux", video["size"], duration) if video["ext"] != container else None,
            }
        audio = _best_audio_for(fmts, container, video["video"], audio_codec)
        if audio is None:
            continue
        total = video["size"] + audio["size"]
        return {
            "format": (
                f"{video['id']}+{audio['id']}/"
                f"{_fallback_video(codec, quality, only=True)}+{_fallback_audio(container, audio_codec)}"
            ),
            "ext": container,
            "args": ["--merge-output-format", fmt_ext],
            "parts": [
                {"id": video["id"], "kind": "video", "size": video["size"]},
                {"id": audio["id"], "kind": "audio", "size": audio["size"]},
            ],
            "post": _post("merge", total, duration),
        }
    return None


def _best_audio_for(fmts, container, video_family, audio_codec=BEST_CODEC):
    """The best audio-only stream the container can carry beside this video, optionally of one
    codec."""
    pool = [f for f in fmts if f["audio"] and not f["video"] and f["audio"] != "?"
            and _matches_codec(f, audio_codec, "audio")]
    for audio in reversed(pool):
        if _fits(container, video_family, audio["audio"]):
            return audio
    return None


def _resolve_audio(fmts, codec, quality, container, duration):
    """Audio Only: the source stream as is (Original) or converted."""
    pool = [f for f in _audio_pool(fmts) if _matches_codec(f, codec, "audio")]
    if not pool:
        return None
    if container == ORIGINAL:
        solo = [f for f in pool if not f["video"]]
        if quality not in (None, "", BEST_QUALITY):
            solo = [f for f in solo if _bitrate_label(f) == quality]
        if not solo:
            return None
        source = solo[-1]
        return {
            "format": f"{source['id']}/ba[ext={source['ext'].lstrip('.')}]",
            "ext": source["ext"],
            "args": [],
            "parts": [{"id": source["id"], "kind": "audio", "size": source["size"]}],
            "post": None,
        }
    if container not in AUDIO_CONVERSIONS:
        return None
    source = pool[-1]
    args = ["-x", "--audio-format", container.lstrip(".")]
    if container not in _LOSSLESS:
        if quality in (None, "", BEST_VBR, BEST_QUALITY):
            args += ["--audio-quality", "0"]
        else:
            args += ["--audio-quality", quality.split()[0] + "K"]
    return {
        "format": f"{source['id']}/ba/b",
        "ext": container,
        "args": args,
        "parts": [{"id": source["id"], "kind": "audio" if not source["video"] else "both",
                   "size": source["size"]}],
        "post": _post("convert", _converted_size(container, quality, source, duration), duration),
    }


def _converted_size(container, quality, source, duration):
    """Rough size of an audio conversion, for the Queue's progress estimate."""
    if container == ".wav":
        return int(duration * 48000 * 2 * 2)
    if container == ".flac":
        return int(duration * 48000 * 2 * 2 * 0.6)
    if quality and quality[0].isdigit():
        kbps = int(quality.split()[0])
    else:
        kbps = max(128, int(source["abr"] or 0)) if container == ".mp3" else int(source["abr"] or 160)
    return int(duration * kbps * 1000 / 8)


def _post(kind, expected_bytes, duration):
    """A `post` entry for `resolve`."""
    return {"kind": kind, "expected_bytes": int(expected_bytes or 0), "media_secs": float(duration or 0)}


def _fallback_video(codec, quality, only=False):
    """A selector for the same codec / height, used only if a pinned ID has vanished."""
    base = "bv" if only else "b"
    filters = ""
    if codec in _VIDEO_PREFIX:
        filters += f"[vcodec^={_VIDEO_PREFIX[codec]}]"
    match = re.match(r"(\d+)p", quality or "")
    if match:
        filters += f"[height={match.group(1)}]"
    return base + filters


def _fallback_audio(container, audio_codec=BEST_CODEC):
    """Fallback audio selector limited to what the container holds (and the picked codec)."""
    if audio_codec in _AUDIO_PREFIX:
        return f"ba[acodec^={_AUDIO_PREFIX[audio_codec]}]"
    allowed = [name for name in _AUDIO_PREFIX if container in formats.containers_for(None, name)]
    if container == ".mkv" or not allowed:
        return "ba"
    # Parenthesised: `/` binds looser than `+`, so `bv+ba[x]/ba[y]` means "(bv+ba[x]) or ba[y]".
    return "(" + "/".join(f"ba[acodec^={_AUDIO_PREFIX[name]}]" for name in allowed) + ")"


def build_download_args(plan, url, work_dir, verbose=False):
    """The full yt-dlp argv for one queued download (`plan` from `resolve`), writing into the
    job's private `work_dir`. The `--print` marker lines are what YtDlpJob parses: the picked
    formats and sizes, per-stream progress, post-processing and the final path. `--print`
    implies quiet + simulate, hence `--no-simulate --progress`."""
    return base_args() + [
        *(["-v"] if verbose else []),   # Detailed logging: yt-dlp's debug lines join the output
        "-f", plan["format"],
        *plan["args"],
        "-P", work_dir,
        "-o", "download.%(ext)s",
        "--newline", "--no-simulate", "--progress", "--no-mtime",
        "--print", "video:LLAMA_FORMATS %(requested_formats.:.{format_id,filesize,filesize_approx})j",
        # A single format prints `[]` above, so it comes through here (a merge's "299+140" id is
        # ignored).
        "--print", "video:LLAMA_FORMAT %(format_id)s %(filesize,filesize_approx|0)s",
        "--print", "after_move:LLAMA_FILE %(filepath)s",
        "--progress-template",
        "download:LLAMA_DL %(info.format_id)s "
        "%(progress.{status,downloaded_bytes,total_bytes,total_bytes_estimate,speed})j",
        "--progress-template", "postprocess:LLAMA_PP %(progress.{status,postprocessor})j",
        url,
    ]
