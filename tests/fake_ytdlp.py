# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""A stand-in for yt-dlp.exe, for check_runners: speaks the marker lines YtDlpJob parses
(`--print` / `--progress-template` output) and writes into the `-P` work folder, with no
network. FAKE_YTDLP_MODE picks the run: ok (two streams, a merge), slow (runs until killed,
with a child process standing in for yt-dlp's own ffmpeg), fail (an ERROR line, exit 1), nofile
(exit 0 without a file)."""
import json
import os
import subprocess
import sys
import time

mode = os.environ.get("FAKE_YTDLP_MODE", "ok")
work = sys.argv[sys.argv.index("-P") + 1]


def say(line):
    print(line, flush=True)


def dl(fid, done, total, status="downloading"):
    say(f"LLAMA_DL {fid} " + json.dumps({"status": status, "downloaded_bytes": done, "total_bytes": total,
                                          "total_bytes_estimate": None, "speed": 4_000_000}))


say("[youtube] fixture: Downloading webpage")
if mode == "fail":
    say("ERROR: [youtube] fixture: Video unavailable. This video is private")
    sys.exit(1)
if mode == "nofile":
    sys.exit(0)

say("LLAMA_FORMATS " + json.dumps([{"format_id": "137", "filesize": 800_000, "filesize_approx": None},
                                   {"format_id": "140", "filesize": 200_000, "filesize_approx": None}]))
if mode == "slow":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    with open(os.path.join(work, "child.pid"), "w") as f:
        f.write(str(child.pid))
    n = 0
    while True:
        n += 1
        dl("137", min(n * 1000, 799_000), 800_000)
        time.sleep(0.02)

for fid, total in (("137", 800_000), ("140", 200_000)):
    for step in range(1, 6):
        dl(fid, total * step // 5, total, "finished" if step == 5 else "downloading")
        time.sleep(0.03)
say("[Merger] Merging formats into \"download.mp4\"")
say("LLAMA_PP " + json.dumps({"status": "started", "postprocessor": "Merger"}))
out = os.path.join(work, "download.mp4")
with open(out, "wb") as f:
    for _ in range(4):
        f.write(b"\0" * 250_000)
        time.sleep(0.03)
say("LLAMA_PP " + json.dumps({"status": "finished", "postprocessor": "Merger"}))
say("LLAMA_PP " + json.dumps({"status": "started", "postprocessor": "MoveFiles"}))
say("LLAMA_PP " + json.dumps({"status": "finished", "postprocessor": "MoveFiles"}))
say(f"LLAMA_FILE {out}")
