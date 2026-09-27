# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Runs one yt-dlp download off the GUI thread with FfmpegJob's contract (`start` / `suspend` /
`resume` / `stop` / `poll_events`), plus ("stage", text) events the Queue shows as the status.

The whole process tree (yt-dlp's bootloader, its Python child and its own ffmpeg) lives in a
kill-on-close Windows Job Object, so stop and pause reach every member; the first process is
created suspended and resumed only once inside the job. yt-dlp works in a private hidden folder
beside the output, and the finished file is moved in only on success.

Progress is time-based: elapsed / (elapsed + estimated remaining), where remaining is bytes
left over the recent speed plus the merge / conversion (estimated from the last measured one,
then from its output growing on disk). Never moves backward; paused time doesn't count."""

import collections
import json
import os
import shutil
import subprocess
import threading
import time
import uuid

from core import downloader, llamalog
from core import priority as process_priority
from core.process_job import ProcessJob, replace_output, set_suspended

# Created suspended so it can join the job before it runs.
_CREATE_SUSPENDED = 0x00000004

_OUTPUT_TAIL = 60
# How often poll_events re-applies the priority level to the process tree.
_PRIORITY_SYNC_SECS = 1.0
_WORK_DIR_PREFIX = ".llamamxd-download-"
# The most reported until the file is in place (the last sliver is the move).
_MAX_LIVE_FRACTION = 0.99
_SPEED_SMOOTHING = 0.3
# Download speed is bytes received over this window, not yt-dlp's instantaneous figure: one
# burst after a stall jumped the bar from 15% to 78%, where never-backward then held it.
_SPEED_WINDOW_SECS = 20.0
_MIN_WINDOW_SECS = 2.0
# Each poll moves the bar this share of the way to its target, so a spike only nudges it.
_EASE = 0.12
# Rates measured from the last post-processing step this session, for the next pre-merge
# estimate; middle-of-the-road defaults until then.
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
    """A fresh private folder beside `final_path` (same drive, so the final move is a rename)."""
    folder = os.path.dirname(os.path.abspath(final_path))
    return os.path.join(folder, _WORK_DIR_PREFIX + uuid.uuid4().hex[:8])


class YtDlpJob(ProcessJob):
    """One yt-dlp download plus the thread that watches it. `plan` is
    `core.downloader.resolve()`'s dict, as carried in the task's settings."""

    AREA, TOOL = "ytdlp", "yt-dlp"
    CONTAIN = False        # its tree lives in its own kill-on-close job (_make_job)
    CREATION_FLAGS = ProcessJob.CREATION_FLAGS | (_CREATE_SUSPENDED if os.name == "nt" else 0)

    def __init__(self, url, plan, final_path, priority=process_priority.DEFAULT_LEVEL, label=None):
        self.url = url
        final_path = os.path.abspath(final_path)
        work_dir = work_dir_for(final_path)
        super().__init__(downloader.build_download_args(plan, url, work_dir, verbose=llamalog.is_detailed()),
                         final_path, priority, label)
        self.work_dir = work_dir
        self._last_priority_sync = 0.0
        self.plan = plan
        self._job_handle = None
        self._tail = collections.deque(maxlen=_OUTPUT_TAIL)

        # Progress state: written by the reader thread, read by poll_events, under _lock.
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
        """Launch yt-dlp inside its job object. Never raises: a job that can't start reports
        ("failed", ...)."""
        try:
            os.makedirs(self.work_dir, exist_ok=True)
            if os.name == "nt":
                _k32.SetFileAttributesW(self.work_dir, _FILE_ATTRIBUTE_HIDDEN)
        except OSError as exc:
            self._fail_early(f"Couldn't create a working folder beside the output: {exc.strerror or exc}")
            return

        # One pipe: progress comes on stdout but post-processing and errors on stderr, and
        # merged they keep their order.
        if not self._launch("yt-dlp wasn't found. Reinstall LlamaMXD.", stderr=subprocess.STDOUT,
                            env=downloader.subprocess_env()):
            return

        self._job_handle = self._make_job(self._proc)
        if os.name == "nt":
            set_suspended(self._proc.pid, False)   # created suspended — let it run
        self._started_at = time.monotonic()
        llamalog.log_job_start(self.AREA, self.label, self.args)
        self._events.put(("stage", "Preparing..."))
        threading.Thread(target=self._watch, daemon=True).start()

    def _sync_priority(self):
        """Put every process in the tree at the chosen level. A child inherits only Low / Below
        Normal, so yt-dlp's later ffmpeg would run at Normal under a High parent; poll_events
        re-runs this about once a second. (A job-object limit refuses High for a normal user.)"""
        self._last_priority_sync = time.monotonic()
        return super()._sync_priority()

    def _on_suspended(self, suspended):
        """Paused time doesn't count toward the progress estimate."""
        with self._lock:
            if suspended and self._paused_since is None:
                self._paused_since = time.monotonic()
            elif not suspended and self._paused_since is not None:
                self._paused_total += time.monotonic() - self._paused_since
                self._paused_since = None

    def poll_events(self):
        """Every event since the last call, oldest first, plus a fresh progress estimate."""
        events = super().poll_events()
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
        """Seconds of downloading left: 0 once every part is in, None with no speed yet."""
        left = sum(max(0, p["size"] - p["done"]) for p in self._parts if not p["finished"])
        if left <= 0 or all(p["finished"] for p in self._parts):
            return 0.0
        speed = self._window_speed()
        if speed <= 0:
            return None
        return left / speed

    def _window_speed(self):
        """Bytes/second over the recent window, or yt-dlp's own speed until it has enough
        history. Call with _lock held."""
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
                # Everything but the per-update download progress goes in the job's kept output.
                if line.startswith("LLAMA_DL "):
                    self._on_download(line)
                elif line.startswith("LLAMA_PP "):
                    self.output.add(line)
                    self._on_postprocess(line)
                elif line.startswith("LLAMA_FORMATS ") or line.startswith("LLAMA_FORMAT "):
                    self.output.add(line)
                    self._on_formats(line)
                elif line.startswith("LLAMA_FILE "):
                    self.output.add(line)
                    self._final_file = line[len("LLAMA_FILE "):].strip()
                else:
                    self.output.add(line)
                    self._tail.append(line)
            except (ValueError, KeyError, TypeError):
                self.output.add(line)
                self._tail.append(line)
        returncode = self._proc.wait()
        self._settle(returncode)

    def _on_formats(self, line):
        """What yt-dlp really picked: normally the pinned IDs, but if the fallback selector
        kicked in the byte budget is rebuilt from what was chosen. `LLAMA_FORMATS <json>` for a
        merge (`[]` for a single format) and `LLAMA_FORMAT <id> <size>` for a single format."""
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
                replace_output(self._final_file, self.final_path)
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
        self._record(outcome[0], returncode, outcome[1] if len(outcome) > 1 else "")
        if outcome[0] == "done":
            self._events.put(("progress", 1.0))
        self._events.put(outcome)

    # ------------------------------------------------------------------ #
    #  Process tree / cleanup
    # ------------------------------------------------------------------ #
    @staticmethod
    def _make_job(proc):
        """A kill-on-close job object holding `proc`, or None if Windows refuses."""
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

    def _pids(self):
        """Every process id in the job, or just yt-dlp's without one."""
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

    def _kill(self):
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
        """Delete the work folder, retrying briefly (a killed ffmpeg can hold its output)."""
        for _ in range(20):
            shutil.rmtree(self.work_dir, ignore_errors=True)
            if not os.path.exists(self.work_dir):
                return
            time.sleep(0.15)

    def _cleanup(self):
        self._close_job()
        self._discard_work_dir()

    def _elapsed(self):
        return self._active_elapsed()

    def _fail_early(self, reason):
        self._discard_work_dir()
        super()._fail_early(reason)


def _folder_bytes(folder):
    """Total size of the files directly in `folder` (0 if gone). `os.stat(path)`, not
    `entry.stat()`: on Windows the latter is stale for a file still open, so a growing output
    read as 0 bytes."""
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
