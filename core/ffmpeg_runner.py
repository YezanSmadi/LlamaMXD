"""Runs one ffmpeg job off the GUI thread: start, real pause/resume, stop,
progress, and a readable failure reason — without ever touching a widget.

The command itself is built with ffmpeg-python (`core.ffmpeg_build`), but it
is *launched* here with one plain `subprocess.Popen`, because ffmpeg-python's
own `run_async()` can't pass `creationflags` — and CREATE_NO_WINDOW matters:
without it every job flashes a console window. ffmpeg runs at the OS's
normal process priority (profiled: event-loop lateness during a full-speed
x264 encode came back the same as idle, so there was nothing to protect the
UI from by throttling it — see _CREATION_FLAGS).

Threads here never touch a widget. Everything reaches the GUI thread
through `poll_events()`, which the Queue tab drains on its own timer tick.

**Pause is real.** `suspend()` freezes the whole ffmpeg process
(`NtSuspendProcess`) and `resume()` thaws it, so a paused job picks up from
the exact frame it stopped on — verified: 0 progress lines over a 3s
suspend, then carrying on from where it was. `stop()` works on a suspended
process too (kill exits it immediately).

**The output goes to a temp file first** (`partial_path`), and only replaces
the real output path once ffmpeg exits cleanly. So a stopped or failed job
only ever deletes a file it created itself — never a file the user already
had at that path.
"""

import collections
import os
import queue
import stat
import subprocess
import threading
import time

from core.utilities import probe_duration, verify_hdr_sdr_tag

# CREATE_NO_WINDOW only -- otherwise every job flashes a console window.
# Deliberately *not* BELOW_NORMAL_PRIORITY_CLASS any more: profiled event-loop
# lateness at normal priority came back the same as idle (see the module
# docstring), so throttling ffmpeg was buying nothing on this machine while
# slowing every encode down for no reason. getattr() so the module still
# imports on a non-Windows Python (the flag is Windows-only).
_CREATION_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# How many trailing stderr lines to keep for the failure message. The runner
# passes -loglevel error, so these are errors, not ffmpeg's usual chatter.
_STDERR_TAIL = 40
_REASON_LINES = 3

# os.replace onto the final path retries this many times, this far apart,
# before actually failing. See _replace_output for why this is needed at
# all -- verified against two real Windows causes, not a guess.
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
    """Freezes (or thaws) every thread of process `pid`. Returns whether the
    OS call succeeded. Windows has no SIGSTOP, so this goes through ntdll's
    NtSuspendProcess/NtResumeProcess — the same calls Task Manager's
    "suspend" uses, and no psutil dependency."""
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
    """`os.replace(temp_path, final_path)`, but tolerant of a transient
    Windows "Access is denied" (WinError 5) instead of failing the job
    outright on one. Confirmed against two real causes, not a guess:

    1. **The destination is marked read-only.** Common for a file that came
       from a download or another program. `os.replace` refuses it outright,
       every time -- so the read-only bit is cleared first, best-effort.
    2. **Something else briefly has the destination open** -- a media
       player, thumbnail/preview generation, an antivirus scan reacting to
       the just-closed temp file. This is usually gone within a second, so
       a short retry loop clears it without bothering the user over
       something that isn't really an error. If it's a genuine, lasting
       lock, the loop still gives up and reports it.

    Raises the last OSError if `final_path` never becomes replaceable."""
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
    """`<stem>.partial<ext>` beside the final file. The real extension stays
    last, so ffmpeg still picks the right muxer from the name."""
    root, ext = os.path.splitext(final_path)
    return f"{root}.partial{ext}"


class FfmpegJob:
    """One ffmpeg process plus the two threads that watch it.

    `args` is a complete argv (see `ffmpeg_build.compile_command`) that must
    write to `temp_path` and report with `-progress pipe:1`. The progress
    fraction's denominator starts as `duration_secs` when the job is trimmed
    to a length, else the input's own duration (probed in the worker thread)
    minus `start_secs`; if neither is known, no progress is reported and the
    job just finishes. That starting figure is only a guess where it comes
    from a probe: `_watch` stretches it upward on the fly if the actual
    encode runs past it (confirmed real-world cause: a source whose
    container-reported duration undersold its true playable length by over
    10x), so the bar re-calibrates instead of freezing at 100% early.

    Events, drained with `poll_events()`:
      ("progress", fraction)   0.0..1.0
      ("done",)                the finished file is at `final_path`
      ("failed", reason)       a short, user-readable explanation
    A job that was `stop()`ped reports nothing further."""

    def __init__(self, args, final_path, temp_path, *, duration_secs=0,
                 input_file="", start_secs=0, verify_hdr_tag=False):
        self.args = list(args)
        self.final_path = final_path
        self.temp_path = temp_path
        self._duration_secs = duration_secs or 0
        self._input_file = input_file
        self._start_secs = start_secs or 0
        # Set by QueueTab._process_next when this job's HDR_TO_SDR toggle is
        # actually driving the tonemap filter (core.ffmpeg_build.
        # uses_hdr_tonemap()) -- a post-encode safety net, see
        # core.utilities.verify_hdr_sdr_tag for why it exists on top of the
        # filter already being verified at development time.
        self._verify_hdr_tag = verify_hdr_tag

        self._proc = None
        self._events = queue.Queue()
        self._stderr = collections.deque(maxlen=_STDERR_TAIL)
        self._stderr_thread = None
        # _finished (the job reached an end of its own) and _stopped (stop()
        # was called) are both only flipped under this lock, so a job that
        # finishes at the very instant it's stopped settles on exactly one.
        self._lock = threading.Lock()
        self._finished = False
        self._stopped = False

    # ------------------------------------------------------------------ #
    #  Control (all called from the GUI thread)
    # ------------------------------------------------------------------ #
    def start(self):
        """Launches ffmpeg and its watcher threads. Never raises — a job
        that can't even start reports a ("failed", ...) event instead."""
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
                creationflags=_CREATION_FLAGS,
            )
        except FileNotFoundError:
            self._fail_early("ffmpeg wasn't found. Reinstall LlamaMXD, or install ffmpeg and add it to your PATH.")
            return
        except OSError as exc:
            self._fail_early(f"Couldn't start ffmpeg: {exc.strerror or exc}")
            return

        # stderr MUST be drained continuously, or ffmpeg blocks the moment
        # its pipe buffer fills and the job hangs forever.
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()
        threading.Thread(target=self._watch, daemon=True).start()

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
        """Kills ffmpeg (suspended or not), waits for it to exit, and deletes
        the partial output. Returns False when the job had already finished
        on its own, in which case there was nothing to stop."""
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
                pass
        self._discard_temp()
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
        """Keeps the tail of stderr for the failure message."""
        for line in self._proc.stderr:
            line = line.strip()
            if line:
                self._stderr.append(line)

    def _watch(self):
        """Reads -progress blocks off stdout, then settles the job once
        ffmpeg exits."""
        total = self._total_secs()
        for line in self._proc.stdout:
            key, _, value = line.strip().partition("=")
            # out_time_us, not out_time_ms: the latter is *also* microseconds
            # despite its name (ffmpeg quirk, checked on this build).
            if key == "out_time_us" and total:
                try:
                    seconds = int(value) / 1_000_000
                except ValueError:
                    continue   # "N/A" until the encoder emits its first packet
                # total is a probe of the *container's declared* duration,
                # which can be flatly wrong for some sources (confirmed: a
                # VFR file whose metadata read 3:30 while its actual playable
                # length was 45:54) -- out_time then races past total well
                # before ffmpeg is actually done, and clamping to 1.0 would
                # freeze the bar at "done" for however much real encoding is
                # still left. Stretching the estimate upward instead of
                # clamping means the fraction re-calibrates as reality proves
                # the original guess wrong, rather than lying at 100%.
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
                self._events.put((
                    "failed",
                    f"Couldn't save the finished file — it may be open in another "
                    f"program or read-only. ({exc.strerror or exc})",
                ))
                return
            if self._verify_hdr_tag and verify_hdr_sdr_tag(self.final_path) is False:
                # The file exists and plays -- this isn't corrupt, so it's
                # left in place rather than deleted (the user's actual
                # encoded work shouldn't vanish over a tag check) -- but it's
                # reported as Failed rather than Done, same reasoning as the
                # article that prompted this check: a file that's still HDR
                # data under an SDR label is worse than not tone-mapping at
                # all, since every consumer trusts the label and displays it
                # wrong with no warning. A None result (probe itself failed)
                # is "unknown", not "wrong" -- falls through to Done.
                self._events.put((
                    "failed",
                    "The file finished encoding, but its color tags still read "
                    "HDR (smpte2084/arib-std-b67) instead of SDR (bt709) -- the "
                    "BT.2390 tone-map may not have actually applied. The file "
                    f"was still saved to {self.final_path} for inspection.",
                ))
                return
            self._events.put(("progress", 1.0))
            self._events.put(("done",))
        else:
            self._discard_temp()
            self._events.put(("failed", self._reason(returncode)))

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #
    def _total_secs(self):
        """The *initial* progress denominator, or None when it can't be
        known. Only a starting guess -- `_watch` stretches it upward on the
        fly if a source's actual encoded length runs past it (see there)."""
        if self._duration_secs > 0:
            return float(self._duration_secs)
        total = probe_duration(self._input_file)
        if total is None:
            return None
        remaining = total - self._start_secs
        return remaining if remaining > 0 else None

    def _reason(self, returncode):
        """The last few stderr lines, or the exit code if ffmpeg said nothing."""
        lines = list(self._stderr)[-_REASON_LINES:]
        return "\n".join(lines) if lines else f"ffmpeg exited with code {returncode}."

    def _fail_early(self, reason):
        """Reports a job that never got as far as running ffmpeg."""
        with self._lock:
            self._finished = True
        self._events.put(("failed", reason))

    def _discard_temp(self):
        """Deletes the partial output, if there is one. Only ever the temp
        file — the real output path is never removed from here."""
        try:
            os.remove(self.temp_path)
        except OSError:
            pass
