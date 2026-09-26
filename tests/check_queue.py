# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""The Queue tab end to end, offscreen: tasks added the way the tabs add them, run through
QueueTab's own job start (settings -> ffmpeg_vars -> compile -> FfmpegJob), paused and resumed,
and their outputs checked. Also a task that fails, and Stop mid-run."""
import os
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import check_jobs as J  # noqa: E402  (its fixtures and settings)
from harness import WORK, fixture, report  # noqa: E402

from check_ui import settle, window  # noqa: E402  (isolated settings + the offscreen MainWindow)

queue = window.tabs["Queue"]
OUT = os.path.join(WORK, "queue")
os.makedirs(OUT, exist_ok=True)


def _task(name, tab, settings):
    path = os.path.join(OUT, name)
    if os.path.exists(path):
        os.remove(path)
    return queue.add_task(name, dict(settings, output_path=path), source_tab=tab), path


def _wait(task_ids, seconds=120):
    end = time.monotonic() + seconds
    while time.monotonic() < end and any(queue._status(t) not in ("Done", "Failed") for t in task_ids):
        settle(0.1)
    return {t: queue._status(t) for t in task_ids}


def run():
    cases = {name: (tab, settings) for tab, name, settings in J.cases()}
    problems = []

    # Two tasks queued, then the queue started: they run in order and both finish.
    mux_id, mux_out = _task("q_mux.mkv", *cases["mux_reordered.mkv"])
    enc_id, enc_out = _task("q_enc.mp4", *cases["enc_h264_trim.mp4"])
    queue.start_queue()
    states = _wait([mux_id, enc_id])
    for tid, out, want in ((mux_id, mux_out, "mux_reordered.mkv"), (enc_id, enc_out, "enc_h264_trim.mp4")):
        if states[tid] != "Done":
            problems.append(f"{want}: status {states[tid]}, error {queue._rows[tid].get('error')}")
        elif J._summary(out) != J._summary(os.path.join(J.OUT, want)):
            problems.append(f"{want}: queue output differs from the direct job's")
    ok = report("queued Mux + Encode run in order to Done, same outputs as direct jobs", problems)

    # Pause then resume a long job: it suspends, and still finishes.
    long_settings = dict(cases["enc_h264_trim.mp4"][1], input_file=fixture("long.mp4"), start_secs=0,
                         duration_secs=0, speed="medium", audio_streams=[], strip_audio=True)
    long_id, long_out = _task("q_long.mp4", "Encoding", long_settings)
    queue.start_queue()
    settle(1.0)
    queue.pause_queue()
    before = queue._active and queue._active.get("fraction", 0)
    settle(1.5)
    during = queue._active and queue._active.get("fraction", 0)
    queue.start_queue()
    state = _wait([long_id])[long_id]
    problems = []
    if before is None or during is None or during > before + 0.01:
        problems.append(f"progress moved while paused: {before} -> {during}")
    if state != "Done" or not os.path.exists(long_out):
        problems.append(f"after resume: status {state}")
    ok &= report("pause suspends a running job; resume finishes it", problems)

    # Stop mid-run: back to Queued, no files.
    stop_id, stop_out = _task("q_stop.mp4", "Encoding", dict(long_settings, speed="veryslow"))
    queue.start_queue()
    settle(1.0)
    queue.stop_queue()
    settle(0.5)
    problems = [p for p, bad in ((f"status {queue._status(stop_id)}", queue._status(stop_id) != "Queued"),
                                 ("output left behind", os.path.exists(stop_out)),
                                 ("partial left behind", os.path.exists(J.partial_path(stop_out)))) if bad]
    queue.remove_task(stop_id)
    ok &= report("Stop returns the task to Queued and leaves no files", problems)

    # A task that can't run turns Failed with a reason, and the queue moves on to the next.
    bad_id, _ = _task("q_bad.mp4", "Encoding", dict(cases["enc_h264_trim.mp4"][1],
                                                     input_file=os.path.join(WORK, "missing.mp4")))
    next_id, next_out = _task("q_next.mkv", *cases["mux_reordered.mkv"])
    queue._error_dialog_open = True            # the failure notice is modal; keep it from opening
    queue.start_queue()
    states = _wait([bad_id, next_id])
    problems = []
    if states[bad_id] != "Failed" or not queue._rows[bad_id].get("error"):
        problems.append(f"bad task: {states[bad_id]}, error {queue._rows[bad_id].get('error')!r}")
    if states[next_id] != "Done":
        problems.append(f"next task: {states[next_id]}")
    ok &= report("a failing task turns Failed with a reason and the queue continues", problems)
    return ok


if __name__ == "__main__":
    run()
