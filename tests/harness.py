# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Shared test plumbing: a sandbox (the log goes to a temp folder, settings.json is never
written), fixture clips made by the bundled ffmpeg, and golden-file comparison."""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")
WORK = os.path.join(tempfile.gettempdir(), "llamamxd-tests")
FIXTURES = os.path.join(WORK, "fixtures")
UPDATE = "--update" in sys.argv

os.environ["LOCALAPPDATA"] = os.path.join(WORK, "appdata")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.makedirs(FIXTURES, exist_ok=True)
os.makedirs(GOLDEN, exist_ok=True)

from core import llamalog  # noqa: E402
from core.tools import find_tool, tool_path  # noqa: E402

llamalog.setup(version="tests")


# --------------------------------------------------------------------------- #
#  Fixture clips
# --------------------------------------------------------------------------- #
_SRC = ["-f", "lavfi", "-i", "testsrc2=s=640x360:r=24:d=4"]
_TONE = ["-f", "lavfi", "-i", "sine=f=440:d=4:sample_rate=48000"]
_TONE2 = ["-f", "lavfi", "-i", "sine=f=660:d=4:sample_rate=44100"]
_HDR_X265 = ("colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:log-level=error:"
             "master-display=G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1):"
             "max-cll=1000,400")
_CLIPS = {
    # H.264 + stereo AAC, a title tag.
    "sdr.mp4": [*_SRC, *_TONE, "-map", "0", "-map", "1", "-c:v", "libx264", "-preset", "ultrafast",
                "-c:a", "aac", "-ac", "2", "-metadata", "title=Fixture Clip", "-shortest"],
    # H.264 + two audio tracks with languages (AAC stereo eng, Opus mono jpn).
    "multi.mkv": [*_SRC, *_TONE, *_TONE2, "-map", "0", "-map", "1", "-map", "2", "-c:v", "libx264",
                  "-preset", "ultrafast", "-c:a:0", "aac", "-ac:a:0", "2", "-c:a:1", "libopus",
                  "-ac:a:1", "1", "-metadata:s:a:0", "language=eng", "-metadata:s:a:1", "language=jpn",
                  "-shortest"],
    # 10-bit HEVC tagged HDR10 with mastering display + MaxCLL.
    "hdr.mkv": [*_SRC, "-map", "0", "-pix_fmt", "yuv420p10le", "-c:v", "libx265", "-preset", "ultrafast",
                "-x265-params", _HDR_X265, "-color_primaries", "bt2020", "-color_trc", "smpte2084",
                "-colorspace", "bt2020nc"],
    # 30s at 720p: long enough to stop an encode part-way.
    "long.mp4": ["-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=30", "-map", "0", "-c:v", "libx264",
                 "-preset", "ultrafast"],
    # Audio only.
    "audio.m4a": [*_TONE, "-map", "0", "-c:a", "aac"],
    # VP9 + Opus in WebM.
    "vp9.webm": [*_SRC, *_TONE, "-map", "0", "-map", "1", "-c:v", "libvpx-vp9", "-deadline", "realtime",
                 "-cpu-used", "8", "-c:a", "libopus", "-shortest"],
}


def fixture(name):
    """The path of fixture clip `name`, generated on first use."""
    path = os.path.join(FIXTURES, name)
    if not os.path.exists(path):
        made = path + ".raw.mkv" if name in _RETAG else path
        _ffmpeg(*_CLIPS[name], made)
        if name in _RETAG:
            # x265 keeps the colour tags in the bitstream only: a copy with them set on the
            # stream (and the VUI rewritten) is what ffprobe reads as HDR10.
            _ffmpeg("-i", made, "-c", "copy", *_RETAG[name], path)
            os.remove(made)
    return path


def _ffmpeg(*args):
    subprocess.run([tool_path("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", *args], check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


_RETAG = {"hdr.mkv": ["-bsf:v", "hevc_metadata=colour_primaries=9:transfer_characteristics=16:matrix_coefficients=9",
                      "-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc"]}


# --------------------------------------------------------------------------- #
#  Normalising and golden files
# --------------------------------------------------------------------------- #
def normalize(value):
    """`value` with machine-specific paths replaced by placeholders, so a golden file holds
    the same text on any machine: the bundled tools, the fixture and work folders."""
    tools = [(name, find_tool(name)) for name in ("ffmpeg", "ffprobe", "yt-dlp", "deno")]
    swaps = [(found, f"<{name}>") for name, found in tools if found]         # whole paths first,
    swaps += [(os.path.dirname(found), "<tools>") for _name, found in tools if found]   # then folders
    swaps += [(FIXTURES, "<fixtures>"), (WORK, "<work>"), (ROOT, "<repo>")]
    if isinstance(value, str):
        for old, new in swaps:
            value = value.replace(old, new).replace(old.replace("\\", "/"), new)
        return value
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if isinstance(value, tuple):
        return [normalize(v) for v in value]
    if isinstance(value, dict):
        return {str(k): normalize(v) for k, v in value.items()}
    return value


def _diff(old, new, path="", out=None):
    out = [] if out is None else out
    if type(old) is not type(new):
        out.append(f"{path}: {old!r} -> {new!r}")
    elif isinstance(old, dict):
        for key in sorted(set(old) | set(new)):
            if key not in new:
                out.append(f"{path}/{key}: removed")
            elif key not in old:
                out.append(f"{path}/{key}: added {new[key]!r}")
            else:
                _diff(old[key], new[key], f"{path}/{key}", out)
    elif isinstance(old, list):
        if len(old) != len(new):
            out.append(f"{path}: length {len(old)} -> {len(new)}")
        for i, (a, b) in enumerate(zip(old, new)):
            _diff(a, b, f"{path}[{i}]", out)
    elif old != new:
        out.append(f"{path}: {old!r} -> {new!r}")
    return out


def check_golden(name, data):
    """Compare `data` with golden/<name>.json; record it instead with --update or when there is
    no golden yet. Returns a list of differences (empty = pass)."""
    path = os.path.join(GOLDEN, f"{name}.json")
    data = json.loads(json.dumps(normalize(data)))
    if UPDATE or not os.path.exists(path):
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False, sort_keys=True)
            fh.write("\n")
        return []
    with open(path, encoding="utf-8") as fh:
        return _diff(json.load(fh), data)


def report(title, problems, limit=25):
    """Print a check's result; returns whether it passed."""
    if not problems:
        print(f"  PASS  {title}")
        return True
    print(f"  FAIL  {title} ({len(problems)} difference(s))")
    for line in problems[:limit]:
        print(f"          {line}")
    if len(problems) > limit:
        print(f"          ... {len(problems) - limit} more")
    return False
