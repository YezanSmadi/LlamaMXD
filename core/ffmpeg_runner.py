# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Runs one ffmpeg job off the GUI thread: start, pause / resume (a real OS suspend), stop,
progress and a readable failure reason. Everything reaches the GUI through `poll_events()`.

Launched with a plain `subprocess.Popen`, since ffmpeg-python's `run_async()` can't pass
CREATE_NO_WINDOW. The output goes to a temp file first (`partial_path`) and replaces the real
path only on a clean exit, so a stopped or failed job never deletes a file the user had."""

import collections
import os
import queue
import re
import stat
import subprocess
import threading
import time

from core import llamalog
from core import priority as process_priority
from core.probe import probe_duration, verify_hdr_sdr_tag

# CREATE_NO_WINDOW; the priority class is ORed in at launch from Settings. Normal by default:
# throttling measured no benefit to the GUI and slowed every encode.
_CREATION_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Trailing stderr lines kept for the failure message.
_STDERR_TAIL = 40
_REASON_LINES = 3
# With Detailed logging (`-loglevel level+info`) each line carries its level: `[error] ...`, or
# `[ctx @ 0x..] [fatal] ...`.
_ERROR_TAG = re.compile(r"\s?\[(?:error|fatal)\]")

# How often, and how far apart, the final rename is retried (see _replace_output).
_REPLACE_ATTEMPTS = 10
_REPLACE_DELAY_SECS = 0.3

if os.name == "nt":
    import ctypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")
    _kernel32.OpenProcess.restype = ctypes.c_void_p
    _kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    _ntdll.NtSuspendProcess.argtypes = [ctypes.c_void_p]
    _ntdll.NtResumeProcess.argtypes = [ctypes.c_void_p]
    _PROCESS_SUSPEND_RESUME = 0x0800


def _set_suspended(pid, suspended):
    """Freeze or thaw every thread of process `pid` via ntdll's NtSuspendProcess /
    NtResumeProcess (Windows has no SIGSTOP). Returns whether it worked."""
    if os.name != "nt":
        import signal
        try:
            os.kill(pid, signal.SIGSTOP if suspended else signal.SIGCONT)
            return True
        except OSError:
            return False
    handle = _kernel32.OpenProcess(_PROCESS_SUSPEND_RESUME, False, pid)
    if not handle:
        return False
    try:
        call = _ntdll.NtSuspendProcess if suspended else _ntdll.NtResumeProcess
        return call(handle) == 0
    finally:
        _kernel32.CloseHandle(handle)


def _replace_output(temp_path, final_path):
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


def partial_path(final_path):
    """`<stem>.partial<ext>` beside the final file (the real extension last, for the muxer)."""
    root, ext = os.path.splitext(final_path)
    return f"{root}.partial{ext}"


class FfmpegJob:
    """One ffmpeg process and the two threads that watch it. `args` is a complete argv writing
    to `temp_path` with `-progress pipe:1`. Progress is measured against `duration_secs` if
    trimmed, else the input's probed length minus `start_secs`, stretched upward if the encode
    runs past it (a container can undersell its length 10x).

    Events from `poll_events()`: ("progress", fraction), ("done",), ("failed", reason). A
    stopped job reports nothing further."""

    def __init__(self, args, final_path, temp_path, *, duration_secs=0,
                 input_file="", start_secs=0, verify_hdr_tag=False,
                 priority=process_priority.DEFAULT_LEVEL, label=None):
        self.args = list(args)
        # The log's name for the job and its output ring buffer; `log_path` is the file it was
        # written to, once ended.
        self.label = label or os.path.basename(final_path)
        self.output = llamalog.JobOutput()
        self.log_path = None
        self._t0 = None
        self._recorded = False
        self._priority = priority
        self.final_path = final_path
        self.temp_path = temp_path
        self._duration_secs = duration_secs or 0
        self._input_file = input_file
        self._start_secs = start_secs or 0
        # Post-encode check that an HDR->SDR output really is tagged SDR.
        self._verify_hdr_tag = verify_hdr_tag

        self._proc = None
        self._events = queue.Queue()
        self._stderr = collections.deque(maxlen=_STDERR_TAIL)
        self._errors = collections.deque(maxlen=_STDERR_TAIL)   # the level-tagged error lines only
        self._stderr_thread = None
        # _finished and _stopped flip only under this lock, so a job finishing as it's stopped
        # settles on exactly one.
        self._lock = threading.Lock()
        self._finished = False
        self._stopped = False

    # ------------------------------------------------------------------ #
    #  Control (all called from the GUI thread)
    # ------------------------------------------------------------------ #
    def start(self):
        """Launch ffmpeg and its watchers. Never raises: a job that can't start reports
        ("failed", ...)."""
        folder = os.path.dirname(self.final_path)
        try:
            if folder:
                os.makedirs(folder, exist_ok=True)
        except OSError as exc:
            self._fail_early(f"Couldn't create the output folder: {exc.strerror or exc}")
            return

        try:
            self._proc = subprocess.Popen(
                self.args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=_CREATION_FLAGS | process_priority.creation_flag(self._priority),
            )
        except FileNotFoundError:
            self._fail_early("ffmpeg wasn't found. Reinstall LlamaMXD, or install ffmpeg and add it to your PATH.")
            return
        except OSError as exc:
            self._fail_early(f"Couldn't start ffmpeg: {exc.strerror or exc}")
            return

        self._t0 = time.monotonic()
        llamalog.log_job_start("ffmpeg", self.label, self.args)
        # stderr must be drained, or ffmpeg blocks when the pipe fills.
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()
        threading.Thread(target=self._watch, daemon=True).start()

    def set_priority(self, level):
        """Move the running process to a new priority level. Returns whether it worked."""
        self._priority = level
        if self._proc is None or self._proc.poll() is not None:
            return False
        return process_priority.set_process_priority(self._proc.pid, level)

    def suspend(self):
        """Freezes the process in place. Returns whether it worked."""
        if self._proc is None or self._proc.poll() is not None:
            return False
        return _set_suspended(self._proc.pid, True)

    def resume(self):
        """Thaws a suspended process. Returns whether it worked."""
        if self._proc is None or self._proc.poll() is not None:
            return False
        return _set_suspended(self._proc.pid, False)

    def stop(self):
        """Kill ffmpeg (suspended or not), wait for it, and delete the partial output. False if
        the job had already finished on its own."""
        with self._lock:
            if self._finished:
                return False
            self._stopped = True
        if self._proc is not None:
            if self._proc.poll() is None:
                self._proc.kill()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                llamalog.get("ffmpeg").warning('ffmpeg for "%s" was still running 10s after being killed', self.label)
        self._discard_temp()
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
    #  Worker threads — never touch a widget from here
    # ------------------------------------------------------------------ #
    def _drain_stderr(self):
        """Keep stderr's tail for the failure message, and all of it in the ring buffer."""
        for line in self._proc.stderr:
            line = line.strip()
            if line:
                self._stderr.append(line)
                self.output.add(line)
                if _ERROR_TAG.search(line):
                    self._errors.append(_ERROR_TAG.sub("", line, count=1))

    def _watch(self):
        """Read -progress off stdout, then settle the job once ffmpeg exits."""
        total = self._total_secs()
        for line in self._proc.stdout:
            key, _, value = line.strip().partition("=")
            # out_time_us: out_time_ms is also microseconds, despite its name.
            if key == "out_time_us" and total:
                try:
                    seconds = int(value) / 1_000_000
                except ValueError:
                    continue   # "N/A" until the encoder emits its first packet
                # The declared duration can be far too short (a VFR file said 3:30 of 45:54):
                # stretch it rather than freeze the bar at 100%.
                if seconds > total:
                    total = seconds * 1.05
                self._events.put(("progress", min(1.0, max(0.0, seconds / total))))

        returncode = self._proc.wait()
        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=2)

        with self._lock:
            if self._stopped:
                return   # stop() owns the cleanup and wants no events
            self._finished = True

        if returncode == 0:
            try:
                _replace_output(self.temp_path, self.final_path)
            except OSError as exc:
                self._discard_temp()
                reason = (f"Couldn't save the finished file — it may be open in another "
                          f"program or read-only. ({exc.strerror or exc})")
                self._record("failed", returncode, reason)
                self._events.put(("failed", reason))
                return
            if self._verify_hdr_tag and verify_hdr_sdr_tag(self.final_path) is False:
                # Kept, not deleted (the file plays), but Failed: HDR data under an SDR label
                # is worse than no tone-map. A None check result is unknown and passes.
                reason = ("The file finished encoding, but its color tags still read "
                          "HDR (smpte2084/arib-std-b67) instead of SDR (bt709) -- the "
                          "BT.2390 tone-map may not have actually applied. The file "
                          f"was still saved to {self.final_path} for inspection.")
                self._record("failed", returncode, reason)
                self._events.put(("failed", reason))
                return
            self._record("done", returncode)
            self._events.put(("progress", 1.0))
            self._events.put(("done",))
        else:
            self._discard_temp()
            reason = self._reason(returncode)
            self._record("failed", returncode, reason)
            self._events.put(("failed", reason))

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #
    def _total_secs(self):
        """The starting progress denominator, or None (`_watch` may stretch it)."""
        if self._duration_secs > 0:
            return float(self._duration_secs)
        total = probe_duration(self._input_file)
        if total is None:
            return None
        remaining = total - self._start_secs
        return remaining if remaining > 0 else None

    def _reason(self, returncode):
        """The last error lines of stderr, or the exit code. With Detailed logging the tagged
        errors are used, since the tail is `[info]` lines."""
        lines = list(self._errors or self._stderr)[-_REASON_LINES:]
        return "\n".join(lines) if lines else f"ffmpeg exited with code {returncode}."

    def _record(self, outcome, returncode=None, reason=""):
        """Write the job's end to the log, once: a summary line and its output file."""
        with self._lock:
            if self._recorded:
                return
            self._recorded = True
        seconds = time.monotonic() - self._t0 if self._t0 else 0.0
        self.log_path = llamalog.record_job("ffmpeg", self.label, self.args, outcome, self.output,
                                            returncode=returncode, reason=reason, seconds=seconds)

    def _fail_early(self, reason):
        """Report a job that never got as far as running ffmpeg."""
        with self._lock:
            self._finished = True
        self._record("failed", reason=reason)
        self._events.put(("failed", reason))

    def _discard_temp(self):
        """Delete the partial output, if any; never the real output path."""
        try:
            os.remove(self.temp_path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            llamalog.get("ffmpeg").warning("Couldn't delete the partial output %s: %s", self.temp_path, exc)
