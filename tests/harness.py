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
_KEYS_SRC = ["-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=60", "-map", "0"]
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
    # Timestamps starting 60s in: the MKV header's duration is the end time, the TS's is honest
    # (probe._effective_duration must tell them apart).
    "late.mkv": ["-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=6", "-f", "lavfi", "-i", "sine=d=6",
                 "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-output_ts_offset", "60"],
    "late.ts": ["-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=6", "-c:v", "libx264", "-preset", "ultrafast",
                "-output_ts_offset", "60"],
    # Audio only.
    "audio.m4a": [*_TONE, "-map", "0", "-c:a", "aac"],
    # VP9 + Opus in WebM.
    "vp9.webm": [*_SRC, *_TONE, "-map", "0", "-map", "1", "-c:v", "libvpx-vp9", "-deadline", "realtime",
                 "-cpu-used", "8", "-c:a", "libopus", "-shortest"],
    # Audio with cover art: a video stream, but nothing to preview.
    "cover.m4a": [*_TONE, "-f", "lavfi", "-i", "color=c=red:s=64x64:d=1", "-map", "0", "-map", "1",
                  "-c:a", "aac", "-c:v", "mjpeg", "-frames:v", "1", "-disposition:v:0", "attached_pic"],
    # 60s with a keyframe every second: previews come from keyframes.
    "keys.mp4": [*_KEYS_SRC, "-c:v", "libx264", "-preset", "ultrafast", "-x264-params", "keyint=30:scenecut=0"],
    # Keyframes every 5s except at 40s and 45s: the 43.6s sample lands on the 38.2s sample's
    # keyframe (35s), so that one is redone at its exact frame.
    "sparse.mp4": [*_KEYS_SRC, "-c:v", "libx264", "-preset", "ultrafast", "-x264-params", "keyint=1800:scenecut=0",
                   "-force_key_frames", "0,5,10,15,20,25,30,35,50,55"],
}


def finish():
    """End a check that built a MainWindow once its results are printed, skipping teardown: Qt's
    native teardown crashes at exit now and then (see CLAUDE.md), and os._exit still runs the
    DLLs' own unload code, where it can crash too. TerminateProcess runs none of it."""
    sys.stdout.flush()
    sys.stderr.flush()
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    kernel32.TerminateProcess(kernel32.GetCurrentProcess(), 0)


# Subtitles and chapters. Cues: 1-3s "Hello one", 5-8s "Hello two"; the ASS line 2-6s.
_SRT = "1\n00:00:01,000 --> 00:00:03,000\nHello one\n\n2\n00:00:05,000 --> 00:00:08,000\nHello two\n"
_ASS = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 640\nPlayResY: 360\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,28,&H0000FFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1\n"
        "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:02.00,0:00:06.00,Default,,0,0,0,,Styled line\n")
_CHAPTERS = (";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=4000\ntitle=Intro\n"
             "[CHAPTER]\nTIMEBASE=1/1000\nSTART=4000\nEND=10000\ntitle=Main\n")


def _sup(width=1920, height=1080, shown=((1.0, 4.0), (6.0, 8.0))):
    """A Blu-ray PGS (.sup): a white 400x60 bar at the bottom centre of a `width` x `height`
    canvas, on screen for each `(start, end)` of `shown`. ffmpeg can't make one (it only
    converts pictures to pictures), so it is written here."""
    import struct

    def segment(kind, payload, pts):
        ticks = int(pts * 90000)
        return b"PG" + struct.pack(">IIBH", ticks, ticks, kind, len(payload)) + payload

    ow, oh = 400, 60
    x, y = (width - ow) // 2, height - oh - 60
    # One run of colour 1 per line (00 11LLLLLL LLLLLLLL CC), then end of line (00 00).
    rle = bytes([0, 0b11000000 | (ow >> 8), ow & 0xFF, 1, 0, 0]) * oh
    out = b""
    number = 0
    for start, end in shown:
        pcs = struct.pack(">HHBHBBBB", width, height, 0x10, number, 0x80, 0, 0, 1) + struct.pack(">HBBHH", 0, 0, 0, x, y)
        wds = struct.pack(">BBHHHH", 1, 0, x, y, ow, oh)
        pds = struct.pack(">BB", 0, 0) + bytes([1, 235, 128, 128, 255])
        ods = (struct.pack(">HBB", 0, 0, 0xC0) + (len(rle) + 4).to_bytes(3, "big") + struct.pack(">HH", ow, oh) + rle)
        out += (segment(0x16, pcs, start) + segment(0x17, wds, start) + segment(0x14, pds, start)
                + segment(0x15, ods, start) + segment(0x80, b"", start))
        clear = struct.pack(">HHBHBBBB", width, height, 0x10, number + 1, 0x00, 0, 0, 0)
        out += segment(0x16, clear, end) + segment(0x17, wds, end) + segment(0x80, b"", end)
        number += 2
    return out


# Titles with 台 and я, whose UTF-8 bytes include 0x8f, which the Windows code page (cp1252) can't decode.
UNICODE_TITLES = {"container": "台配国语 Я", "chapters": ["第 01 章", "Глава 2 я"], "audio": "国语 台配", "subtitle": "简体 я"}
_UNICODE_CHAPTERS = (";FFMETADATA1\ntitle=%s\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=4000\ntitle=%s\n"
                     "[CHAPTER]\nTIMEBASE=1/1000\nSTART=4000\nEND=10000\ntitle=%s\n"
                     % (UNICODE_TITLES["container"], *UNICODE_TITLES["chapters"]))

_WRITTEN = {"subs.srt": _SRT.encode(), "subs.ass": _ASS.encode(), "chapters.txt": _CHAPTERS.encode(),
            "unicode-chapters.txt": _UNICODE_CHAPTERS.encode("utf-8"), "bar.sup": None}


def _made_clips():
    """Clips built from the written fixtures (their paths aren't known until then)."""
    return {
        # H.264 (a keyframe every second) + AAC, an eng SRT (Default) and a spa ASS (Forced), two
        # chapters.
        "subs.mkv": ["-f", "lavfi", "-i", "testsrc2=s=640x360:r=24:d=10", "-f", "lavfi", "-i", "sine=d=10",
                     "-i", fixture("subs.srt"), "-i", fixture("subs.ass"), "-i", fixture("chapters.txt"),
                     "-map", "0", "-map", "1", "-map", "2", "-map", "3", "-map_chapters", "4",
                     "-c:v", "libx264", "-preset", "ultrafast", "-g", "24", "-c:a", "aac", "-c:s", "copy",
                     "-metadata:s:s:0", "language=eng", "-metadata:s:s:1", "language=spa",
                     "-disposition:s:0", "default", "-disposition:s:1", "forced"],
        # 720p video + the 1080p PGS bar, which shows 1-4s and 6-8s (itsoffset: ffmpeg moves a
        # .sup's first picture to 0 otherwise).
        "pgs.mkv": ["-f", "lavfi", "-i", "testsrc2=s=1280x720:r=24:d=10", "-itsoffset", "1", "-i", fixture("bar.sup"),
                    "-map", "0", "-map", "1", "-c:v", "libx264", "-preset", "ultrafast", "-g", "24", "-c:s", "copy"],
        # Container, chapter, audio and subtitle titles that aren't ASCII (UNICODE_TITLES).
        "unicode.mkv": ["-f", "lavfi", "-i", "testsrc2=s=320x180:r=24:d=10", "-f", "lavfi", "-i", "sine=d=10",
                        "-i", fixture("subs.srt"), "-i", fixture("unicode-chapters.txt"),
                        "-map", "0", "-map", "1", "-map", "2", "-map_chapters", "3", "-map_metadata", "3",
                        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-c:s", "copy",
                        "-metadata:s:a:0", "title=" + UNICODE_TITLES["audio"],
                        "-metadata:s:s:0", "title=" + UNICODE_TITLES["subtitle"]],
    }


def fixture(name):
    """The path of fixture clip `name`, generated on first use."""
    path = os.path.join(FIXTURES, name)
    if name in _WRITTEN and not os.path.exists(path):
        with open(path, "wb") as fh:
            fh.write(_WRITTEN[name] if _WRITTEN[name] is not None else _sup())
        return path
    if name in ("subs.mkv", "pgs.mkv", "unicode.mkv") and not os.path.exists(path):
        _ffmpeg(*_made_clips()[name], path)
        return path
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
