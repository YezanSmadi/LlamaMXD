# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""The job runners' lifecycle, offline. YtDlpJob runs a stand-in yt-dlp (`fake_ytdlp.py`) through
its real Windows job object: a download with a merge, pause / resume, priority, Stop (the tree
killed, a child process included), yt-dlp failing, finishing without a file, a missing
executable and an output folder that can't be made. FfmpegJob: the paths check_jobs doesn't
reach (missing executable, bad folder, controls on a finished job). Events, files left behind
and the job logs are recorded (golden)."""
import ctypes
import glob
import os
import shutil
import sys
import time

from harness import WORK, check_golden, fixture, report

from core import downloader
from core.ffmpeg_runner import FfmpegJob, partial_path
from core.tools import tool_path

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(WORK, "runners")
downloader.base_args = lambda: [sys.executable, os.path.join(HERE, "fake_ytdlp.py")]
from core.ytdlp_runner import YtDlpJob  # noqa: E402

_PLAN = {"format": "137+140", "ext": "mp4", "args": ["--merge-output-format", "mp4"],
         "parts": [{"id": "137", "kind": "video", "size": 800_000}, {"id": "140", "kind": "audio", "size": 200_000}],
         "post": {"kind": "merge", "expected_bytes": 1_000_000, "media_secs": 10}}


def _alive(pid):
    """Is process `pid` still running? (os.kill would terminate it on Windows.)"""
    k32 = ctypes.WinDLL("kernel32")
    k32.OpenProcess.restype = ctypes.c_void_p
    handle = k32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    code = ctypes.c_ulong()
    k32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))
    k32.CloseHandle(ctypes.c_void_p(handle))
    return code.value == 259   # STILL_ACTIVE


def _drain(job, until=("done", "failed"), limit=30):
    events, end = [], time.monotonic() + limit
    while time.monotonic() < end:
        events += job.poll_events()
        if any(e[0] in until for e in events):
            break
        time.sleep(0.05)
    return events


def _describe(job, events, folder):
    """Events without the timing-dependent progress values, plus what was left on disk."""
    progress = [e[1] for e in events if e[0] == "progress"]
    return {
        "events": [list(e) for e in events if e[0] != "progress"],
        "had_progress": bool(progress),
        "progress_monotonic": progress == sorted(progress),
        "last_progress": progress[-1] if progress else None,
        "final_exists": os.path.exists(job.final_path),
        "final_size": os.path.getsize(job.final_path) if os.path.exists(job.final_path) else None,
        "left_in_folder": sorted(os.path.basename(p) for p in glob.glob(os.path.join(folder, "*"))
                                 if os.path.abspath(p) != os.path.abspath(job.final_path)),
        "log": os.path.basename(job.log_path).split("-", 2)[-1] if job.log_path else None,
    }


def _fresh(name):
    folder = os.path.join(OUT, name)
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    return folder


def _ytdlp(name, mode, *, args0=None, final=None):
    folder = _fresh(name)
    os.environ["FAKE_YTDLP_MODE"] = mode
    job = YtDlpJob("https://www.youtube.com/watch?v=fixture", _PLAN, final or os.path.join(folder, "out.mp4"),
                   label=name)
    if args0:
        job.args[0] = args0
    return job, folder


def run():
    out = {}
    blocker = os.path.join(OUT, "a-file")
    os.makedirs(OUT, exist_ok=True)
    open(blocker, "w").close()

    for name, mode in (("ytdlp ok", "ok"), ("ytdlp fail", "fail"), ("ytdlp nofile", "nofile")):
        job, folder = _ytdlp(name, mode)
        job.start()
        out[name] = _describe(job, _drain(job), folder)
    job, folder = _ytdlp("ytdlp missing exe", "ok", args0=os.path.join(OUT, "nope", "yt-dlp.exe"))
    job.start()
    out["ytdlp missing exe"] = _describe(job, _drain(job), folder)
    job, folder = _ytdlp("ytdlp bad folder", "ok", final=os.path.join(blocker, "out.mp4"))
    job.start()
    out["ytdlp bad folder"] = _describe(job, _drain(job), folder)

    # Pause / resume / priority / stop on a run that never ends.
    job, folder = _ytdlp("ytdlp stop", "slow")
    job.start()
    end = time.monotonic() + 10
    while time.monotonic() < end and not (os.path.exists(os.path.join(job.work_dir, "child.pid"))
                                          and job._parts[0]["done"] > 0):
        job.poll_events()
        time.sleep(0.05)
    time.sleep(0.3)
    child = int(open(os.path.join(job.work_dir, "child.pid")).read())
    stats = {"priority_below_normal": job.set_priority("Below Normal"), "suspend": job.suspend()}
    time.sleep(0.3)
    frozen_at = job._parts[0]["done"]
    time.sleep(1.0)
    stats["frozen_while_paused"] = job._parts[0]["done"] == frozen_at
    stats["no_progress_while_paused"] = not any(e[0] == "progress" for e in job.poll_events())
    stats["resume"] = job.resume()
    time.sleep(0.8)
    stats["moving_after_resume"] = job._parts[0]["done"] > frozen_at
    stats["child_alive_before_stop"] = _alive(child)
    job.poll_events()
    stats["stop"] = job.stop()
    time.sleep(0.3)
    stats["child_alive_after_stop"] = _alive(child)
    stats["work_dir_left"] = os.path.exists(job.work_dir)
    stats["events_after_stop"] = [e for e in job.poll_events() if e[0] != "progress"]
    stats["suspend_after_stop"] = job.suspend()
    out["ytdlp stop"] = {**stats, **_describe(job, [], folder)}

    # FfmpegJob: the early failures, and the controls once a job has ended.
    folder = _fresh("ffmpeg missing exe")
    final = os.path.join(folder, "out.mp4")
    job = FfmpegJob([os.path.join(OUT, "nope", "ffmpeg.exe"), "-i", "x", partial_path(final)], final,
                    partial_path(final), duration_secs=1, label="ffmpeg missing exe")
    job.start()
    out["ffmpeg missing exe"] = _describe(job, _drain(job), folder)
    folder = _fresh("ffmpeg bad folder")
    open(os.path.join(folder, "a-file"), "w").close()
    final = os.path.join(folder, "a-file", "out.mp4")
    job = FfmpegJob([tool_path("ffmpeg"), "-i", "x", partial_path(final)], final, partial_path(final),
                    duration_secs=1, label="ffmpeg bad folder")
    job.start()
    out["ffmpeg bad folder"] = _describe(job, _drain(job), folder)

    folder = _fresh("ffmpeg ended")
    final = os.path.join(folder, "out.mp4")
    job = FfmpegJob([tool_path("ffmpeg"), "-nostdin", "-loglevel", "error", "-progress", "pipe:1", "-i",
                     fixture("sdr.mp4"), "-c", "copy", "-y", partial_path(final)], final, partial_path(final),
                    input_file=fixture("sdr.mp4"), label="ffmpeg ended")
    stats = {"suspend_before_start": job.suspend(), "priority_before_start": job.set_priority("Normal")}
    job.start()
    events = _drain(job)
    time.sleep(0.2)
    stats.update(suspend_after_end=job.suspend(), resume_after_end=job.resume(),
                 priority_after_end=job.set_priority("Normal"), stop_after_end=job.stop())
    out["ffmpeg ended"] = {**stats, **_describe(job, events, folder)}
    return report(f"job runners: lifecycle, pause, stop, failures ({len(out)} cases)", check_golden("runners", out))


if __name__ == "__main__":
    run()
