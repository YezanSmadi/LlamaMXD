# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Runs one ffmpeg job off the GUI thread: start, pause / resume (a real OS suspend), stop,
progress and a readable failure reason. Everything reaches the GUI through `poll_events()`.

Launched with a plain `subprocess.Popen`, since ffmpeg-python's `run_async()` can't pass
CREATE_NO_WINDOW. The output goes to a temp file first (`partial_path`) and replaces the real
path only on a clean exit, so a stopped or failed job never deletes a file the user had."""

import collections
import os
import re
import subprocess
import threading
import time

from core import llamalog
from core import priority as process_priority
from core.probe import probe_duration, verify_hdr_sdr_tag
from core.process_job import ProcessJob, replace_output

# Trailing stderr lines kept for the failure message.
_STDERR_TAIL = 40
_REASON_LINES = 3
# With Detailed logging (`-loglevel level+info`) each line carries its level: `[error] ...`, or
# `[ctx @ 0x..] [fatal] ...`.
_ERROR_TAG = re.compile(r"\s?\[(?:error|fatal)\]")


def partial_path(final_path):
    """`<stem>.partial<ext>` beside the final file (the real extension last, for the muxer)."""
    root, ext = os.path.splitext(final_path)
    return f"{root}.partial{ext}"


class FfmpegJob(ProcessJob):
    """One ffmpeg process and the two threads that watch it. `args` is a complete argv writing
    to `temp_path` with `-progress pipe:1`. Progress is measured against `duration_secs` if
    trimmed, else the input's probed length minus `start_secs`, stretched upward if the encode
    runs past it (a container can undersell its length 10x).

    Events from `poll_events()`: ("progress", fraction), ("done",), ("failed", reason). A
    stopped job reports nothing further."""

    AREA = TOOL = "ffmpeg"

    def __init__(self, args, final_path, temp_path, *, duration_secs=0,
                 input_file="", start_secs=0, verify_hdr_tag=False,
                 priority=process_priority.DEFAULT_LEVEL, label=None):
        super().__init__(args, final_path, priority, label)
        self._t0 = None
        self.temp_path = temp_path
        self._duration_secs = duration_secs or 0
        self._input_file = input_file
        self._start_secs = start_secs or 0
        # Post-encode check that an HDR->SDR output really is tagged SDR.
        self._verify_hdr_tag = verify_hdr_tag

        self._stderr = collections.deque(maxlen=_STDERR_TAIL)
        self._errors = collections.deque(maxlen=_STDERR_TAIL)   # the level-tagged error lines only
        self._stderr_thread = None

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

        if not self._launch("ffmpeg wasn't found. Reinstall LlamaMXD, or install ffmpeg and add it to your PATH.",
                            stderr=subprocess.PIPE):
            return

        self._t0 = time.monotonic()
        llamalog.log_job_start(self.AREA, self.label, self.args)
        # stderr must be drained, or ffmpeg blocks when the pipe fills.
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()
        threading.Thread(target=self._watch, daemon=True).start()

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
                replace_output(self.temp_path, self.final_path)
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

    def _elapsed(self):
        return time.monotonic() - self._t0 if self._t0 else 0.0

    def _cleanup(self):
        self._discard_temp()

    def _discard_temp(self):
        """Delete the partial output, if any; never the real output path."""
        try:
            os.remove(self.temp_path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            llamalog.get("ffmpeg").warning("Couldn't delete the partial output %s: %s", self.temp_path, exc)
