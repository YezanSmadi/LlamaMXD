"""Runs one YT-DLP download off the GUI thread, with the same contract as
`core.ffmpeg_runner.FfmpegJob` so the Queue tab drives both identically:
`start()` / `suspend()` / `resume()` / `stop()` / `poll_events()`, emitting
("progress", fraction), then ("done",) or ("failed", reason) — plus one extra
event, ("stage", text), which the Queue shows as the row's status
("Downloading video..." -> "Downloading audio..." -> "Merging...").

**The whole process tree lives in a Windows Job Object.** yt-dlp.exe is a
PyInstaller bundle (a bootloader process plus the real Python child) and it
starts its *own* ffmpeg to merge/convert — killing or suspending just the
process `Popen` returned would leave the rest running. Every process started
under the job joins it automatically, so `stop()` terminates the whole tree
and `suspend()` freezes every member. The first process is created
suspended and only resumed once it's inside the job, so nothing can escape
in between. `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` is a last line of defence:
if the app dies outright, Windows closes the handle and takes the tree down.

**Nothing is written to the user's folder until the download succeeds.**
yt-dlp works entirely inside a private hidden folder beside the output
(`.llamamxd-download-XXXXXXXX`), and the finished file is moved onto
`final_path` with the same retrying replace as ffmpeg jobs. Stop or failure
just deletes that folder.

**Progress is time-based, not a fixed split.** One bar covers the video
download, the audio download and the merge, and each gets exactly as much of
it as it takes:

    fraction = elapsed / (elapsed + estimated time remaining)

Remaining download time is bytes left across every part / yt-dlp's live
speed; the merge (or conversion) before it starts is estimated from the last
one this session measured, and once it's running, from how fast its output
is actually growing on disk. The fraction never moves backward — a slower
estimate holds the bar still rather than dropping it — and it's computed in
`poll_events()` on the GUI thread (a cheap folder stat), so it keeps moving
through a merge that prints nothing at all. Paused time doesn't count.

The reader thread follows the same rule as FfmpegJob's: it never touches a
widget; everything reaches the GUI thread through `poll_events()`.
"""

import collections
import json
import os
import queue
import shutil
import subprocess
import threading
import time
import uuid

from core import downloader
from core import priority as process_priority
from core.ffmpeg_runner import _replace_output, _set_suspended

# CREATE_SUSPENDED so the first process can be put in the job before it runs
# a single instruction; CREATE_NO_WINDOW so no console flashes.
_CREATE_SUSPENDED = 0x00000004
_CREATION_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) | (
    _CREATE_SUSPENDED if os.name == "nt" else 0
)

_OUTPUT_TAIL = 60
# How often poll_events re-applies the priority level to the process tree.
_PRIORITY_SYNC_SECS = 1.0
_WORK_DIR_PREFIX = ".llamamxd-download-"
# Never report more than this until the file is actually in place — the last
# sliver is the move into the user's folder.
_MAX_LIVE_FRACTION = 0.99
_SPEED_SMOOTHING = 0.3
# Download speed for the estimate is bytes actually received over this many
# seconds of (unpaused) time, not yt-dlp's instantaneous figure: one burst
# after a stall once read as a near-finished download and jumped the bar from
# 15% to 78%, where the never-backward rule then held it for two minutes
# (confirmed on a real 1080p job). yt-dlp's own smoothed speed only stands in
# until the window has _MIN_WINDOW_SECS of history.
_SPEED_WINDOW_SECS = 20.0
_MIN_WINDOW_SECS = 2.0
# Each poll moves the bar this share of the way to its new target, so what
# spikes the estimate for a moment only nudges the bar (~1s time constant at
# the Queue's 100ms poll).
_EASE = 0.12
# Measured rates from the last finished post-processing step this session,
# so the next job's pre-merge estimate is grounded in this machine's disk.
# Defaults are deliberately middle-of-the-road; a single job replaces them.
_learned = {"copy_bytes_per_sec": 150 * 1024 * 1024, "convert_realtime": 80.0}
_MIN_MEASURE_SECS = 0.5

_STAGE_FOR_PART = {"video": "Downloading video...", "audio": "Downloading audio...",
                   "both": "Downloading..."}
_STAGE_FOR_POST = {"Merger": "Merging...", "VideoRemuxer": "Remuxing...",
                   "ExtractAudio": "Converting audio..."}
_IGNORED_POST = {"MoveFiles"}

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.SetFileAttributesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]

    class _IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _JOB_EXTENDED_LIMITS = 9
    _JOB_PROCESS_ID_LIST = 3
    _KILL_ON_JOB_CLOSE = 0x2000
    _FILE_ATTRIBUTE_HIDDEN = 0x2


def work_dir_for(final_path):
    """A fresh private folder beside `final_path` for one download. Beside it
    (not in %TEMP%) so moving the finished file in is a same-drive rename."""
    folder = os.path.dirname(os.path.abspath(final_path))
    return os.path.join(folder, _WORK_DIR_PREFIX + uuid.uuid4().hex[:8])


class YtDlpJob:
    """One yt-dlp download plus the thread that watches it. `plan` is
    `core.downloader.resolve()`'s dict, as carried in the task's settings."""

    def __init__(self, url, plan, final_path, priority=process_priority.DEFAULT_LEVEL):
        self.url = url
        self._priority = priority
        self._last_priority_sync = 0.0
        self.plan = plan
        self.final_path = os.path.abspath(final_path)
        self.work_dir = work_dir_for(self.final_path)
        self.args = downloader.build_download_args(plan, url, self.work_dir)

        self._proc = None
        self._job_handle = None
        self._events = queue.Queue()
        self._tail = collections.deque(maxlen=_OUTPUT_TAIL)
        self._lock = threading.Lock()
        self._finished = False
        self._stopped = False

        # Progress state — written by the reader thread, read by poll_events,
        # always under _lock.
        self._parts = [dict(part, done=0, finished=False) for part in plan.get("parts") or []]
        self._post = dict(plan["post"]) if plan.get("post") else None
        self._post_running = None      # postprocessor name while one is running
        self._post_started_active = 0.0
        self._post_baseline = 0
        self._post_done = False
        self._speed = 0.0
        self._samples = collections.deque()   # (active seconds, total bytes received)
        self._final_file = None
        self._last_fraction = 0.0

        self._started_at = None
        self._paused_total = 0.0
        self._paused_since = None

    # ------------------------------------------------------------------ #
    #  Control (all called from the GUI thread)
    # ------------------------------------------------------------------ #
    def start(self):
        """Launches yt-dlp inside its job object. Never raises — a job that
        can't even start reports ("failed", ...) instead."""
        try:
            os.makedirs(self.work_dir, exist_ok=True)
            if os.name == "nt":
                _k32.SetFileAttributesW(self.work_dir, _FILE_ATTRIBUTE_HIDDEN)
        except OSError as exc:
            self._fail_early(f"Couldn't create a working folder beside the output: {exc.strerror or exc}")
            return

        try:
            self._proc = subprocess.Popen(
                self.args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                # One pipe: yt-dlp writes download progress to stdout but
                # post-processing events and errors to stderr (confirmed), and
                # merging them keeps their order and needs only one reader.
                stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=_CREATION_FLAGS | process_priority.creation_flag(self._priority),
                env=downloader.subprocess_env(),
            )
        except FileNotFoundError:
            self._fail_early("yt-dlp wasn't found. Reinstall LlamaMXD.")
            return
        except OSError as exc:
            self._fail_early(f"Couldn't start yt-dlp: {exc.strerror or exc}")
            return

        self._job_handle = self._make_job(self._proc)
        if os.name == "nt":
            _set_suspended(self._proc.pid, False)   # created suspended — let it run
        self._started_at = time.monotonic()
        self._events.put(("stage", "Preparing..."))
        threading.Thread(target=self._watch, daemon=True).start()

    def set_priority(self, level):
        """Moves the whole tree to a new priority level (Settings' "Priority
        Level" changed mid-download). Returns whether it worked."""
        self._priority = level
        return self._sync_priority()

    def _sync_priority(self):
        """Puts every process in the tree at the chosen level. A child only
        inherits its parent's class when that class is Low or Below Normal, so
        yt-dlp's own ffmpeg (started later, for a merge) would otherwise run
        at Normal under a High parent -- `poll_events` re-runs this about once
        a second to catch it. (The job object's own priority-limit isn't used
        instead: Windows refuses High there without a privilege a normal user
        doesn't hold.)"""
        self._last_priority_sync = time.monotonic()
        if self._proc is None or self._proc.poll() is not None:
            return False
        return all([process_priority.set_process_priority(pid, self._priority)
                    for pid in self._tree_pids()])

    def suspend(self):
        """Freezes every process in the tree. Returns whether it worked."""
        if self._proc is None or self._proc.poll() is not None:
            return False
        ok = all([_set_suspended(pid, True) for pid in self._tree_pids()])
        with self._lock:
            if self._paused_since is None:
                self._paused_since = time.monotonic()
        return ok

    def resume(self):
        """Thaws every process in the tree. Returns whether it worked."""
        if self._proc is None or self._proc.poll() is not None:
            return False
        ok = all([_set_suspended(pid, False) for pid in self._tree_pids()])
        with self._lock:
            if self._paused_since is not None:
                self._paused_total += time.monotonic() - self._paused_since
                self._paused_since = None
        return ok

    def stop(self):
        """Kills the whole tree (suspended or not) and deletes the working
        folder. Returns False when the job had already finished on its own."""
        with self._lock:
            if self._finished:
                return False
            self._stopped = True
        self._kill_tree()
        if self._proc is not None:
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        self._close_job()
        self._discard_work_dir()
        return True

    def poll_events(self):
        """Every event queued since the last call, oldest first, with a fresh
        progress estimate appended while the job is still going."""
        events = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break
        if not any(e[0] in ("done", "failed") for e in events):
            if (self._priority != process_priority.DEFAULT_LEVEL
                    and time.monotonic() - self._last_priority_sync >= _PRIORITY_SYNC_SECS):
                self._sync_priority()
            fraction = self._estimate()
            if fraction is not None:
                events.append(("progress", fraction))
        return events

    # ------------------------------------------------------------------ #
    #  Progress estimate (GUI thread, via poll_events)
    # ------------------------------------------------------------------ #
    def _active_elapsed(self, now=None):
        """Seconds since start, minus time spent paused."""
        now = now or time.monotonic()
        if self._started_at is None:
            return 0.0
        paused = self._paused_total
        if self._paused_since is not None:
            paused += now - self._paused_since
        return max(0.0, now - self._started_at - paused)

    def _estimate(self):
        """The bar's fraction right now, or None when nothing's changed."""
        with self._lock:
            if self._started_at is None or self._paused_since is not None:
                return None
            elapsed = self._active_elapsed()
            remaining = self._remaining_download()
            if remaining is None:
                return None
            post_remaining = self._remaining_post(elapsed)
            if post_remaining is None:
                return None
            remaining += post_remaining
            target = elapsed / (elapsed + remaining) if elapsed + remaining > 0 else 0.0
            target = min(_MAX_LIVE_FRACTION, target)
            if target <= self._last_fraction:
                return None
            fraction = self._last_fraction + (target - self._last_fraction) * _EASE
            if fraction - self._last_fraction < 0.0005:
                return None
            self._last_fraction = fraction
            return fraction

    def _remaining_download(self):
        """Seconds of downloading left, 0 once every part is in, or None
        while there's no speed to judge by yet."""
        left = sum(max(0, p["size"] - p["done"]) for p in self._parts if not p["finished"])
        if left <= 0 or all(p["finished"] for p in self._parts):
            return 0.0
        speed = self._window_speed()
        if speed <= 0:
            return None
        return left / speed

    def _window_speed(self):
        """Bytes/second received over the recent window (see
        _SPEED_WINDOW_SECS), or yt-dlp's own smoothed speed until the window
        has enough history. Call with _lock held."""
        if len(self._samples) >= 2:
            (t0, b0), (t1, b1) = self._samples[0], self._samples[-1]
            if t1 - t0 >= _MIN_WINDOW_SECS:
                return max(0.0, (b1 - b0) / (t1 - t0))
        return self._speed

    def _remaining_post(self, elapsed):
        """Seconds of merging/converting left (0 when there's none to do)."""
        post = self._post
        if post is None or self._post_done:
            return 0.0
        expected = max(1, post.get("expected_bytes") or 0)
        if self._post_running is None:
            return self._post_duration_guess(post, expected)
        in_post = max(0.0, elapsed - self._post_started_active)
        written = max(0, _folder_bytes(self.work_dir) - self._post_baseline)
        if written > expected:
            expected = int(written * 1.05)
        if in_post >= _MIN_MEASURE_SECS and written > 0:
            return (expected - written) / (written / in_post)
        return max(0.2, self._post_duration_guess(post, expected) - in_post)

    @staticmethod
    def _post_duration_guess(post, expected):
        """Seconds a not-yet-measured merge/remux/conversion should take."""
        if post["kind"] == "convert" and post.get("media_secs"):
            return post["media_secs"] / max(1.0, _learned["convert_realtime"])
        return expected / max(1.0, _learned["copy_bytes_per_sec"])

    # ------------------------------------------------------------------ #
    #  Reader thread — never touch a widget from here
    # ------------------------------------------------------------------ #
    def _watch(self):
        """Parses yt-dlp's marker lines until it exits, then settles the job."""
        for raw in self._proc.stdout:
            line = raw.rstrip("\r\n")
            if not line:
                continue
            try:
                if line.startswith("LLAMA_DL "):
                    self._on_download(line)
                elif line.startswith("LLAMA_PP "):
                    self._on_postprocess(line)
                elif line.startswith("LLAMA_FORMATS ") or line.startswith("LLAMA_FORMAT "):
                    self._on_formats(line)
                elif line.startswith("LLAMA_FILE "):
                    self._final_file = line[len("LLAMA_FILE "):].strip()
                else:
                    self._tail.append(line)
            except (ValueError, KeyError, TypeError):
                self._tail.append(line)
        returncode = self._proc.wait()
        self._settle(returncode)

    def _on_formats(self, line):
        """What yt-dlp really picked. Normally the plan's own pinned IDs —
        but if YouTube rotated one and the fallback selector kicked in, the
        byte budget is rebuilt from the formats actually chosen.

        Two prints feed this: `LLAMA_FORMATS <json list>` for a merge (it's
        `[]` for a single format — confirmed), and `LLAMA_FORMAT <id> <size>`
        for a single format (a merge shows its combined "299+140" id there,
        which is skipped)."""
        tag, payload = line.split(" ", 1)
        if tag == "LLAMA_FORMATS":
            if not payload.strip().startswith("["):
                return
            chosen = [(str(c.get("format_id")), c.get("filesize") or c.get("filesize_approx") or 0)
                      for c in json.loads(payload)]
        else:
            format_id, _, size = payload.strip().partition(" ")
            if not format_id or "+" in format_id or format_id == "NA":
                return
            chosen = [(format_id, int(size) if size.isdigit() else 0)]
        if not chosen:
            return
        with self._lock:
            if [fid for fid, _ in chosen] == [p["id"] for p in self._parts]:
                for part, (_, size) in zip(self._parts, chosen):
                    part["size"] = int(size) or part["size"]
                return
            kinds = ["video", "audio"] if len(chosen) == 2 else [
                self._parts[0]["kind"] if self._parts else "both"]
            self._parts = [
                {"id": fid, "kind": kind, "done": 0, "finished": False, "size": int(size)}
                for (fid, size), kind in zip(chosen, kinds)
            ]

    def _on_download(self, line):
        """One per-stream progress update."""
        _, format_id, payload = line.split(" ", 2)
        data = json.loads(payload)
        stage = None
        with self._lock:
            part = next((p for p in self._parts if p["id"] == format_id), None)
            if part is None:
                part = next((p for p in self._parts if not p["finished"]), None)
            if part is None:
                return
            if part["done"] == 0 and not part["finished"]:
                stage = _STAGE_FOR_PART.get(part["kind"], "Downloading...")
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            if total:
                part["size"] = int(total)
            part["done"] = int(data.get("downloaded_bytes") or part["done"])
            speed = data.get("speed")
            if speed:
                self._speed = speed if self._speed <= 0 else (
                    _SPEED_SMOOTHING * speed + (1 - _SPEED_SMOOTHING) * self._speed)
            if data.get("status") == "finished":
                part["finished"] = True
                part["done"] = part["size"] = max(part["size"], part["done"])
            now = self._active_elapsed()
            self._samples.append((now, sum(p["done"] for p in self._parts)))
            while len(self._samples) > 2 and now - self._samples[0][0] > _SPEED_WINDOW_SECS:
                self._samples.popleft()
        if stage:
            self._events.put(("stage", stage))

    def _on_postprocess(self, line):
        """A postprocessor started or finished."""
        data = json.loads(line.split(" ", 1)[1])
        name, status = data.get("postprocessor"), data.get("status")
        if name in _IGNORED_POST:
            return
        now = time.monotonic()
        stage = None
        with self._lock:
            for part in self._parts:   # downloads are over once post-processing starts
                part["finished"] = True
                part["done"] = part["size"] = max(part["size"], part["done"])
            if status == "started":
                if self._post is None:
                    total = sum(p["size"] for p in self._parts)
                    self._post = {"kind": "copy", "expected_bytes": total, "media_secs": 0}
                self._post_done = False
                self._post_running = name
                self._post_started_active = self._active_elapsed(now)
                self._post_baseline = _folder_bytes(self.work_dir)
                stage = _STAGE_FOR_POST.get(name, "Finishing...")
            elif status == "finished" and self._post_running == name:
                took = self._active_elapsed(now) - self._post_started_active
                if took > _MIN_MEASURE_SECS and self._post:
                    if self._post["kind"] == "convert" and self._post.get("media_secs"):
                        _learned["convert_realtime"] = self._post["media_secs"] / took
                    elif self._post.get("expected_bytes"):
                        _learned["copy_bytes_per_sec"] = self._post["expected_bytes"] / took
                self._post_running = None
                self._post_done = True
        if stage:
            self._events.put(("stage", stage))

    def _settle(self, returncode):
        """yt-dlp exited: move the file into place and report, unless stopped."""
        with self._lock:
            if self._stopped:
                return
        outcome = None
        if returncode == 0 and self._final_file and os.path.isfile(self._final_file):
            self._events.put(("stage", "Finishing..."))
            try:
                folder = os.path.dirname(self.final_path)
                if folder:
                    os.makedirs(folder, exist_ok=True)
                _replace_output(self._final_file, self.final_path)
                outcome = ("done",)
            except OSError as exc:
                outcome = ("failed", _replace_failure(exc))
        elif returncode == 0:
            outcome = ("failed", "yt-dlp finished but didn't produce a file.")
        else:
            reason = downloader.error_reason(list(self._tail))
            outcome = ("failed", reason or f"yt-dlp exited with code {returncode}.")

        with self._lock:
            if self._stopped:
                return
            self._finished = True
        self._close_job()
        self._discard_work_dir()
        if outcome[0] == "done":
            self._events.put(("progress", 1.0))
        self._events.put(outcome)

    # ------------------------------------------------------------------ #
    #  Process tree / cleanup
    # ------------------------------------------------------------------ #
    @staticmethod
    def _make_job(proc):
        """A kill-on-close job object holding `proc`, or None if Windows
        refuses (the tree then falls back to single-process control)."""
        if os.name != "nt":
            return None
        handle = _k32.CreateJobObjectW(None, None)
        if not handle:
            return None
        info = _ExtendedLimits()
        info.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
        if not _k32.SetInformationJobObject(handle, _JOB_EXTENDED_LIMITS,
                                            ctypes.byref(info), ctypes.sizeof(info)) \
                or not _k32.AssignProcessToJobObject(handle, int(proc._handle)):
            _k32.CloseHandle(handle)
            return None
        return handle

    def _tree_pids(self):
        """Every process id in the job — yt-dlp, its bootloader child, and
        any ffmpeg it started — or just yt-dlp's own without a job."""
        if self._job_handle is None:
            return [self._proc.pid]
        # JOBOBJECT_BASIC_PROCESS_ID_LIST: two DWORD counts, then ULONG_PTR ids.
        capacity = 64
        raw = (ctypes.c_ubyte * (8 + ctypes.sizeof(ctypes.c_size_t) * capacity))()
        if not _k32.QueryInformationJobObject(self._job_handle, _JOB_PROCESS_ID_LIST,
                                              raw, ctypes.sizeof(raw), None):
            return [self._proc.pid]
        count = int.from_bytes(bytes(raw[4:8]), "little")
        size = ctypes.sizeof(ctypes.c_size_t)
        return [int.from_bytes(bytes(raw[8 + i * size:8 + (i + 1) * size]), "little")
                for i in range(min(count, capacity))]

    def _kill_tree(self):
        """Terminates everything in the job (or just yt-dlp without one)."""
        if self._job_handle is not None:
            _k32.TerminateJobObject(self._job_handle, 1)
        elif self._proc is not None and self._proc.poll() is None:
            self._proc.kill()

    def _close_job(self):
        """Releases the job handle. Kill-on-close takes down anything left."""
        with self._lock:
            handle, self._job_handle = self._job_handle, None
        if handle is not None:
            _k32.CloseHandle(handle)

    def _discard_work_dir(self):
        """Deletes the private working folder, retrying briefly — a just-
        killed ffmpeg can hold its output open for a moment."""
        for _ in range(20):
            shutil.rmtree(self.work_dir, ignore_errors=True)
            if not os.path.exists(self.work_dir):
                return
            time.sleep(0.15)

    def _fail_early(self, reason):
        """Reports a job that never got as far as running yt-dlp."""
        with self._lock:
            self._finished = True
        self._discard_work_dir()
        self._events.put(("failed", reason))


def _folder_bytes(folder):
    """Total size of the files directly inside `folder` (0 if it's gone).

    `os.stat(path)`, not `entry.stat()`: on Windows the latter is the
    directory listing's cached size, which isn't updated for a file another
    process still has open — a growing .part or merge output read as 0 bytes
    the whole time it was being written (confirmed)."""
    total = 0
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                try:
                    if entry.is_file():
                        total += os.stat(entry.path).st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _replace_failure(exc):
    """A readable reason for a finished download that couldn't be moved in."""
    if getattr(exc, "winerror", None) == 5 or isinstance(exc, PermissionError):
        return ("The download finished, but the file couldn't be saved over the existing one — "
                "it may be open in another program or marked read-only.")
    return f"The download finished, but the file couldn't be saved: {exc.strerror or exc}"
