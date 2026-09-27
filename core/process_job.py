# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""What FfmpegJob and YtDlpJob share: launching the process, pause / resume (a real OS suspend),
priority, Stop, the event queue the GUI drains with `poll_events()`, and the job's log record.

A job ends exactly once: `_finished` (it settled on its own) and `_stopped` (Stop won) flip only
under `_lock`. Subclasses say which processes are theirs (`_pids`), how to kill them (`_kill`),
what to clean up (`_cleanup`) and how long they have run (`_elapsed`)."""
import os
import queue
import stat
import subprocess
import threading
import time

from core import llamalog, winproc
from core import priority as process_priority
from core.winproc import set_suspended  # noqa: F401  (also imported from here by ytdlp_runner)

# How often, and how far apart, the final rename is retried (see replace_output).
_REPLACE_ATTEMPTS = 10
_REPLACE_DELAY_SECS = 0.3

def replace_output(temp_path, final_path):
    """`os.replace` that survives Windows "Access is denied": the read-only bit is cleared
    first, and a destination briefly held open (a player, thumbnailer, antivirus) is retried
    for a few seconds. Raises the last OSError if it never becomes replaceable."""
    if os.path.exists(final_path):
        try:
            os.chmod(final_path, stat.S_IWRITE)
        except OSError:
            pass   # best-effort -- a failed chmod still gets a real attempt below

    last_exc = None
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(temp_path, final_path)
            return
        except OSError as exc:
            last_exc = exc
            if attempt < _REPLACE_ATTEMPTS - 1:
                time.sleep(_REPLACE_DELAY_SECS)
    raise last_exc


class ProcessJob:
    """One external process run as a queue job. Events from `poll_events()`: ("progress",
    fraction), ("done",), ("failed", reason), and whatever a subclass adds. A stopped job
    reports nothing further."""

    AREA = ""              # its log area: "ffmpeg" / "ytdlp"
    CONTAIN = True         # into the tools job (winproc), so it can't outlive the app
    TOOL = ""              # its name in messages: "ffmpeg" / "yt-dlp"
    CREATION_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def __init__(self, args, final_path, priority=process_priority.DEFAULT_LEVEL, label=None):
        self.args = list(args)
        self.final_path = final_path
        # The log's name for the job and its output ring buffer; `log_path` is the file it was
        # written to, once ended.
        self.label = label or os.path.basename(final_path)
        self.output = llamalog.JobOutput()
        self.log_path = None
        self._recorded = False
        self._priority = priority
        self._proc = None
        self._events = queue.Queue()
        self._lock = threading.Lock()
        self._finished = False
        self._stopped = False

    # ------------------------------------------------------------------ #
    #  Control (all called from the GUI thread)
    # ------------------------------------------------------------------ #
    def _launch(self, not_found, **popen_kwargs):
        """Start the process on `self.args`. On failure the job reports ("failed", ...) and this
        returns False."""
        try:
            self._proc = subprocess.Popen(
                self.args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=self.CREATION_FLAGS | process_priority.creation_flag(self._priority),
                **popen_kwargs,
            )
        except FileNotFoundError:
            self._fail_early(not_found)
            return False
        except OSError as exc:
            self._fail_early(f"Couldn't start {self.TOOL}: {exc.strerror or exc}")
            return False
        if self.CONTAIN:
            winproc.contain(self._proc)
        if self._priority != process_priority.DEFAULT_LEVEL:
            # The creation flag sets only the CPU class; this adds disk I/O and memory priority.
            self._sync_priority()
        return True

    def _running(self):
        return self._proc is not None and self._proc.poll() is None

    def set_priority(self, level):
        """Move the running process(es) to a new priority level. Returns whether it worked."""
        self._priority = level
        return self._sync_priority()

    def _sync_priority(self):
        if not self._running():
            return False
        return all([process_priority.set_process_priority(pid, self._priority) for pid in self._pids()])

    def suspend(self):
        """Freezes the process(es) in place. Returns whether it worked."""
        return self._set_suspended(True)

    def resume(self):
        """Thaws suspended process(es). Returns whether it worked."""
        return self._set_suspended(False)

    def _set_suspended(self, suspended):
        if not self._running():
            return False
        ok = all([set_suspended(pid, suspended) for pid in self._pids()])
        self._on_suspended(suspended)
        return ok

    def stop(self):
        """Kill the process(es) (suspended or not), wait, and clean up. False if the job had
        already finished on its own."""
        with self._lock:
            if self._finished:
                return False
            self._stopped = True
        self._kill()
        if self._proc is not None:
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                llamalog.get(self.AREA).warning('%s for "%s" was still running 10s after being killed',
                                                self.TOOL, self.label)
        self._cleanup()
        self._record("stopped", self._proc.returncode if self._proc is not None else None)
        return True

    def poll_events(self):
        """Every event queued since the last call, oldest first. Non-blocking."""
        events = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                return events

    # ------------------------------------------------------------------ #
    #  Subclass hooks
    # ------------------------------------------------------------------ #
    def _pids(self):
        """The processes pause, resume and priority act on."""
        return [self._proc.pid]

    def _on_suspended(self, suspended):
        """Called after a pause / resume of a running job."""

    def _kill(self):
        if self._running():
            self._proc.kill()

    def _cleanup(self):
        """Delete what a job that didn't finish leaves behind."""

    def _elapsed(self):
        """Seconds the job has run, for its log line."""
        return 0.0

    # ------------------------------------------------------------------ #
    #  Endings
    # ------------------------------------------------------------------ #
    def _record(self, outcome, returncode=None, reason=""):
        """Write the job's end to the log, once: a summary line and its output file."""
        with self._lock:
            if self._recorded:
                return
            self._recorded = True
        self.log_path = llamalog.record_job(self.AREA, self.label, self.args, outcome, self.output,
                                            returncode=returncode, reason=reason, seconds=self._elapsed())

    def _fail_early(self, reason):
        """Report a job that never got as far as running."""
        with self._lock:
            self._finished = True
        self._record("failed", reason=reason)
        self._events.put(("failed", reason))
