# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""The Queue tab end to end, offscreen: tasks added the way the tabs add them, run through
QueueTab's own job start (settings -> ffmpeg_vars -> compile -> FfmpegJob), paused and resumed,
and their outputs checked. Also a task that fails, and Stop mid-run."""
import os
import shutil
import time

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import check_jobs as J  # noqa: E402  (its fixtures and settings)
import harness  # noqa: E402
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
    ok &= _retry(cases, long_settings)
    ok &= _drag(cases, long_settings)
    return ok


def _mouse(row, kind, point):
    """A real left-button mouse event delivered to `row`, `point` in its own coordinates."""
    buttons = {QEvent.MouseButtonPress: Qt.LeftButton, QEvent.MouseMove: Qt.NoButton,
               QEvent.MouseButtonRelease: Qt.NoButton}[kind]
    held = Qt.NoButton if kind == QEvent.MouseButtonRelease else Qt.LeftButton
    button = Qt.NoButton if kind == QEvent.MouseMove else Qt.LeftButton
    local = QPointF(point)
    event = QMouseEvent(kind, local, QPointF(row.mapToGlobal(point)), button, held, Qt.NoModifier)
    QApplication.sendEvent(row, event)


def _clear_rows():
    for task_id in list(queue._rows):
        queue.remove_task(task_id)


def _drag(cases, long_settings):
    """A click on a Queued row opens its details (a nudge under the drag distance still is one); a
    press that moves picks it up at once, and dropping it elsewhere makes the order Custom.
    Dropped above the running job, it runs now and the running job waits, then resumes."""
    ok = True
    window.show_tab("Queue")
    settle(0.3)
    _clear_rows()
    queue._set_sort("Custom")
    enc = cases["enc_h264_trim.mp4"][1]
    a, _ = _task("d_a.mp4", "Encoding", enc)
    b, _ = _task("d_b.mp4", "Encoding", enc)
    c, _ = _task("d_c.mp4", "Encoding", enc)
    settle(0.3)
    row = lambda tid: queue._rows[tid]["widget"]
    mid = lambda tid: QPoint(100, row(tid).height() // 2)

    # A short click opens the details and carries nothing.
    problems = []
    _mouse(row(c), QEvent.MouseButtonPress, mid(c))
    _mouse(row(c), QEvent.MouseButtonRelease, mid(c))
    if queue._detail_task_id != c:
        problems.append("a short click did not open the details")
    if queue._row_drag is not None:
        problems.append("a short click picked the row up")
    ok &= report("a short click on a Queued row opens its details", problems)
    queue._close_details()

    # A nudge under the drag distance is still a click.
    problems = []
    nudge = mid(c) + QPoint(1, 1)
    _mouse(row(c), QEvent.MouseButtonPress, mid(c))
    _mouse(row(c), QEvent.MouseMove, nudge)
    _mouse(row(c), QEvent.MouseButtonRelease, nudge)
    if queue._detail_task_id != c or queue._row_drag is not None:
        problems.append("a small nudge was not treated as a click")
    ok &= report("a nudge under the drag distance still opens the details", problems)

    # The details are still open: carrying a row collapses them. Pressed and moved straight above the
    # first row, then released: no waiting.
    problems = []
    if queue._detail_task_id != c:
        problems.append("the details were not open going in")
    _mouse(row(c), QEvent.MouseButtonPress, mid(c))
    top = row(a).mapToGlobal(QPoint(100, 4))
    _mouse(row(c), QEvent.MouseMove, row(c).mapFromGlobal(top))
    if queue._row_drag is None:
        problems.append("moving did not pick the row up")
    else:
        if queue._detail_task_id is not None:
            problems.append("picking a row up left the details open")
        _mouse(row(c), QEvent.MouseButtonRelease, row(c).mapFromGlobal(top))
    settle(0.2)
    if list(queue._rows) != [c, a, b]:
        problems.append(f"order after the drop: {list(queue._rows)} (wanted {[c, a, b]})")
    if queue._sort != "Custom" or queue.sort_menu.value() != "Custom":
        problems.append(f"sort is {queue._sort} / {queue.sort_menu.value()}, not Custom")
    if queue._row_drag is not None or row(c).graphicsEffect() is not None:
        problems.append("the drag left its ghost or fade behind")
    if queue._detail_task_id is not None:
        problems.append("the drop opened the details")
    ok &= report("dragging a Queued row at once moves it; dropping it sets the order to Custom", problems)

    # Dropped above the running job: that job waits suspended, the dropped one runs, then it resumes.
    _clear_rows()
    problems = []
    long_id, long_out = _task("d_long.mp4", "Encoding", dict(long_settings, speed="slow"))
    short_id, _ = _task("d_short.mp4", "Encoding", enc)
    settle(0.3)
    queue.start_queue()
    settle(1.0)
    _mouse(row(short_id), QEvent.MouseButtonPress, mid(short_id))
    top = row(long_id).mapToGlobal(QPoint(100, 4))
    _mouse(row(short_id), QEvent.MouseMove, row(short_id).mapFromGlobal(top))
    if queue._row_drag is None:
        problems.append("moving did not pick the row up")
    else:
        _mouse(row(short_id), QEvent.MouseButtonRelease, row(short_id).mapFromGlobal(top))
    # Checked at once: the short job is over within a fraction of a second.
    if queue._active is None or queue._active["task_id"] != short_id:
        problems.append("the dropped job is not the running one")
    if queue._status(long_id) != "Paused" or len(queue._shelved) != 1:
        problems.append(f"the running job was not set aside: {queue._status(long_id)}")
    states = _wait([short_id, long_id])
    if states[short_id] != "Done" or states[long_id] != "Done" or not os.path.exists(long_out):
        problems.append(f"after the drop: {states}")
    if queue._shelved:
        problems.append("a job is still set aside")
    ok &= report("dropped above the running job: it runs now, the running job waits and resumes", problems)
    _clear_rows()
    return ok


def _retry(cases, long_settings):
    """Retry runs a Failed task ahead of a running job, which waits suspended and then finishes,
    whether the retry succeeds or fails again."""
    ok = True
    src = os.path.join(OUT, "retry_src.mp4")
    for outcome in ("succeeds", "fails again"):
        if os.path.exists(src):
            os.remove(src)
        retry_id, retry_out = _task("q_retry.mp4", "Encoding", dict(cases["enc_h264_trim.mp4"][1], input_file=src))
        queue._error_dialog_open = True        # the failure notices are modal; keep them from opening
        queue.start_queue()
        problems = []
        if _wait([retry_id])[retry_id] != "Failed":
            problems.append("the first run should have failed")
        if outcome == "succeeds":
            shutil.copy(fixture("sdr.mp4"), src)
        held_id, held_out = _task("q_held.mp4", "Encoding", dict(long_settings, speed="slow"))
        queue.start_queue()
        settle(1.0)
        queue.retry_task(retry_id)
        if outcome == "succeeds":
            if queue._active is None or queue._active["task_id"] != retry_id:
                problems.append("the retry is not the active job")
            if queue._status(held_id) != "Paused" or len(queue._shelved) != 1:
                problems.append(f"the running job was not set aside: {queue._status(held_id)}")
        states = _wait([retry_id, held_id])
        want = "Done" if outcome == "succeeds" else "Failed"
        if states[retry_id] != want:
            problems.append(f"retry {outcome}: status {states[retry_id]}")
        if states[held_id] != "Done" or not os.path.exists(held_out):
            problems.append(f"the held job did not finish: {states[held_id]}")
        if queue._shelved:
            problems.append("a job is still set aside")
        ok &= report(f"retry {outcome}: runs first, the running job resumes and finishes", problems)
        for tid in (retry_id, held_id):
            queue.remove_task(tid)
    return ok


if __name__ == "__main__":
    run()
    harness.finish()
