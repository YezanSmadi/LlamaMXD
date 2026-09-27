# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""LlamaLog, the app's logging (no Qt here; `ui/qt_log.py` routes Qt's messages in).

A rotating `%LOCALAPPDATA%\\LlamaMXD\\logs\\llamamxd.log` (temp folder fallback; with neither,
no log, and logging never raises). Normal logs INFO and up, Detailed adds DEBUG. `setup()`
installs the exception hooks and faulthandler (`crash.log`, reported at the next start). URLs
lose their query, fragment and credentials on every line (`scrub`). Each job keeps its output in
a `JobOutput` ring buffer, written to `logs\\jobs\\` when it ends (`record_job`)."""
import collections
import datetime
import faulthandler
import logging
import logging.handlers
import os
import platform
import re
import subprocess
import sys
import tempfile
import threading
from urllib.parse import urlsplit, urlunsplit

from core import winproc

ROOT = "llamamxd"
NORMAL, DETAILED = "Normal", "Detailed"
LEVELS = (NORMAL, DETAILED)
DEFAULT_LEVEL = NORMAL
_LEVEL_FOR = {NORMAL: logging.INFO, DETAILED: logging.DEBUG}

_MAX_BYTES = 1_000_000
_BACKUPS = 5

# One job's ring buffer holds this many lines; a successful job keeps this many of them.
JOB_CAPACITY = 2000
JOB_SUCCESS_LINES = 100
# Job files kept on disk: failed and stopped ones (what you go looking for) outlast successful ones.
_KEEP_FAILED_JOBS = 50
_KEEP_DONE_JOBS = 20
_KEEP_CRASH_FILES = 5

_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)

_state = {"detail": DEFAULT_LEVEL, "dir": None, "dir_checked": False, "ready": False, "crash_file": None}
_setup_lock = threading.Lock()


# --------------------------------------------------------------------------- #
#  Where the files live
# --------------------------------------------------------------------------- #
def log_dir():
    """The folder the log files live in (made if needed), or None when no folder could be."""
    if _state["dir_checked"]:
        return _state["dir"]
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    for folder in (os.path.join(base, "LlamaMXD", "logs"),
                   os.path.join(tempfile.gettempdir(), "LlamaMXD-logs")):
        try:
            os.makedirs(folder, exist_ok=True)
            probe = os.path.join(folder, ".write-test")
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write("ok")
            os.remove(probe)
        except OSError:
            continue
        _state["dir"] = folder
        break
    _state["dir_checked"] = True
    return _state["dir"]


def jobs_dir():
    """`logs\\jobs` (not created until a job file is written), or None."""
    folder = log_dir()
    return os.path.join(folder, "jobs") if folder else None


def open_log_folder():
    """Opens the log folder in Explorer. Returns an error message, or "" on success."""
    folder = log_dir()
    if not folder:
        return "No writable log folder could be found."
    try:
        os.startfile(folder)
    except (OSError, AttributeError) as exc:
        return f"Couldn't open the log folder: {exc}"
    return ""


# --------------------------------------------------------------------------- #
#  Scrubbing
# --------------------------------------------------------------------------- #
def clean_url(url):
    """`url` without its query string, fragment or credentials — what a log may hold."""
    try:
        parts = urlsplit(url)
        host = parts.netloc.rpartition("@")[2]
        return urlunsplit((parts.scheme, host, parts.path, "", ""))
    except ValueError:
        return url.split("?", 1)[0].split("#", 1)[0]


# Query text of links seen so far: yt-dlp repeats a link's tail without its scheme, which no URL
# pattern catches, so it is removed wherever it turns up.
_hidden = collections.deque(maxlen=64)
_MIN_HIDDEN = 6


def _remember_hidden(url):
    try:
        parts = urlsplit(url)
    except ValueError:
        return
    for piece in (parts.query, parts.fragment):
        if len(piece) >= _MIN_HIDDEN and piece not in _hidden:
            _hidden.append(piece)


def scrub(text):
    """`text` with every http(s) link cut down by `clean_url`, and the query text of every link seen
    so far removed from anywhere else it appears."""
    def cut(match):
        _remember_hidden(match.group(0))
        return clean_url(match.group(0))

    text = _URL.sub(cut, text)
    for piece in list(_hidden):
        if piece in text:
            text = text.replace(piece, "…")
    return text


class _Formatter(logging.Formatter):
    """`time LEVEL area | [thread] message` (the thread only when it isn't the main one), scrubbed."""

    def __init__(self):
        super().__init__(datefmt="%Y-%m-%d %H:%M:%S")

    def format(self, record):
        area = record.name[len(ROOT) + 1:] or "app"
        thread = "" if record.threadName == "MainThread" else f"[{record.threadName}] "
        record.message = record.getMessage()
        stamp = f"{self.formatTime(record, self.datefmt)}.{int(record.msecs):03d}"
        text = f"{stamp} {record.levelname:<8} {area:<10} | {thread}{record.message}"
        if record.exc_info:
            text += "\n" + self.formatException(record.exc_info)
        return scrub(text)


# --------------------------------------------------------------------------- #
#  Setup
# --------------------------------------------------------------------------- #
def get(area):
    """The logger for one area of the app (`get("queue")`, `get("probe")`, ...)."""
    return logging.getLogger(f"{ROOT}.{area}")


def is_detailed():
    return _state["detail"] == DETAILED


def set_detail(name):
    """Switches between Normal (INFO) and Detailed (DEBUG) logging, live."""
    if name not in LEVELS:
        name = DEFAULT_LEVEL
    changed = name != _state["detail"]
    _state["detail"] = name
    logging.getLogger(ROOT).setLevel(_LEVEL_FOR[name])
    if changed and _state["ready"]:
        get("app").info("Log detail set to %s", name)


def ffmpeg_loglevel():
    """ffmpeg's `-loglevel`: errors only, or in Detailed `level+info` (every line tagged, so the
    failure message can still come from the error lines)."""
    return "level+info" if is_detailed() else "error"


def setup(detail_name=DEFAULT_LEVEL, version=""):
    """Starts logging (once): the rotating file, the crash hooks, faulthandler, and the session's
    first lines. Never raises. Returns the log file's path, or None when there is nowhere to write."""
    with _setup_lock:
        if _state["ready"]:
            return None
        root = logging.getLogger(ROOT)
        root.propagate = False
        logging.raiseExceptions = False        # a full disk must not throw into the app
        folder = log_dir()
        path = None
        if folder:
            try:
                path = os.path.join(folder, "llamamxd.log")
                handler = logging.handlers.RotatingFileHandler(
                    path, maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8", delay=True)
                handler.setFormatter(_Formatter())
                root.addHandler(handler)
            except OSError:
                path = None
        if path is None:
            root.addHandler(logging.NullHandler())
        set_detail(detail_name)
        _state["ready"] = True
        _install_hooks()
        previous_crash = _enable_faulthandler()
        _log_session_start(version, path)
        if previous_crash:
            get("app").warning("The previous session ended in a crash. Saved as %s:\n%s", *previous_crash)
        return path


def _log_session_start(version, path):
    """The first lines of a session — cheap facts only; `describe_environment_async` adds the rest."""
    lg = get("app")
    lg.info("=" * 72)
    lg.info("LlamaMXD %s starting (pid %d, log detail: %s)", version or "?", os.getpid(), _state["detail"])
    lg.info("Python %s | %s | log file: %s", sys.version.split()[0], platform.platform(), path or "none")
    versions = []
    try:
        from importlib import metadata
        for package in ("PySide6", "opencv-python", "numpy", "Pillow", "rlottie-python", "ffmpeg-python"):
            try:
                versions.append(f"{package} {metadata.version(package)}")
            except metadata.PackageNotFoundError:
                versions.append(f"{package} MISSING")
    except Exception:
        pass
    if versions:
        lg.info("Packages: %s", ", ".join(versions))


def describe_environment_async():
    """Logs the slower half of the session header — CPU, RAM, GPU and each bundled tool's path and
    version — from a thread (the version checks launch processes)."""
    def work():
        lg = get("app")
        try:
            from core import gpu, system_info, tools
            lg.info("Machine: %s | %s RAM | GPU: %s (%s)", system_info.cpu_name(),
                    system_info.format_bytes(system_info.ram_total_bytes()), gpu.display_name(),
                    gpu.summary_label())
            for name in ("ffmpeg", "ffprobe", "yt-dlp", "deno"):
                path = tools.find_tool(name)
                if not path:
                    lg.warning("Tool %s: NOT FOUND", name)
                    continue
                lg.info("Tool %s: %s (%s)", name, path, _first_line(path))
        except Exception:
            lg.exception("Couldn't describe the environment")

    threading.Thread(target=work, name="log-env", daemon=True).start()


def _first_line(exe):
    """The first line of `exe --version` (or `-version` for ffmpeg), or why there isn't one."""
    flag = "-version" if os.path.basename(exe).lower().startswith(("ffmpeg", "ffprobe")) else "--version"
    try:
        out = winproc.run([exe, flag], text=True, timeout=15).stdout or ""
        return out.strip().splitlines()[0][:120] if out.strip() else "no version output"
    except (OSError, subprocess.SubprocessError) as exc:
        return f"version check failed: {exc}"


# --------------------------------------------------------------------------- #
#  Crash capture
# --------------------------------------------------------------------------- #
def _call_default_excepthook(exc_type, exc, tb):
    if sys.stderr is not None:          # None under pythonw / a frozen windowed build
        try:
            sys.__excepthook__(exc_type, exc, tb)
        except Exception:
            pass


def _install_hooks():
    def on_exception(exc_type, exc, tb):
        if not issubclass(exc_type, KeyboardInterrupt):
            get("app").critical("Unhandled exception", exc_info=(exc_type, exc, tb))
        _call_default_excepthook(exc_type, exc, tb)

    def on_thread_exception(args):
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread else "?"
        get("app").critical("Unhandled exception in thread %s", name,
                            exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    def on_unraisable(unraisable):
        get("app").error("Unraisable exception in %r: %s", unraisable.object, unraisable.err_msg,
                         exc_info=(unraisable.exc_type, unraisable.exc_value, unraisable.exc_traceback))

    sys.excepthook = on_exception
    threading.excepthook = on_thread_exception
    sys.unraisablehook = on_unraisable


def _enable_faulthandler():
    """Native crashes (an access violation in a driver, OpenCV or libplacebo) bypass every Python
    hook; faulthandler writes their traceback to `crash.log`. Returns `(saved_path, text)` when
    the previous session left one, else None."""
    folder = log_dir()
    if not folder:
        return None
    path = os.path.join(folder, "crash.log")
    previous = None
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
            body = [line for line in lines if line.strip() and not line.startswith("--- session")]
            if body:
                stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                saved = os.path.join(folder, f"crash-{stamp}.log")
                os.replace(path, saved)
                previous = (saved, "\n".join(body[:40]))
                _prune(folder, "crash-*.log", _KEEP_CRASH_FILES)
        handle = open(path, "w", encoding="utf-8")
        handle.write(f"--- session started {datetime.datetime.now():%Y-%m-%d %H:%M:%S} pid {os.getpid()} ---\n")
        handle.flush()
        faulthandler.enable(file=handle, all_threads=True)
        _state["crash_file"] = handle      # must stay open for the life of the process
    except (OSError, ValueError, RuntimeError):
        pass
    return previous


def _prune(folder, pattern, keep):
    """Deletes all but the `keep` newest files matching `pattern` in `folder`."""
    import glob
    files = sorted(glob.glob(os.path.join(folder, pattern)), key=os.path.getmtime, reverse=True)
    for stale in files[keep:]:
        try:
            os.remove(stale)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
#  Jobs
# --------------------------------------------------------------------------- #
class JobOutput:
    """One job's output as a bounded ring buffer: the newest `capacity` lines, oldest dropped
    (and counted). Fed from the runner's reader thread, read when the job ends. Lines are
    scrubbed as they come in."""

    def __init__(self, capacity=JOB_CAPACITY):
        self._lines = collections.deque(maxlen=capacity)
        self._added = 0
        self._lock = threading.Lock()

    def add(self, line):
        line = scrub(str(line).rstrip("\r\n"))
        if not line.strip():
            return
        with self._lock:
            self._lines.append(line)
            self._added += 1

    def snapshot(self):
        """`(lines still held, how many older ones were dropped)`."""
        with self._lock:
            return list(self._lines), self._added - len(self._lines)


def duration_text(seconds):
    """`3.2s`, `1m 05s` or `1h 02m 03s`."""
    seconds = max(0.0, float(seconds or 0))
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(round(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m {secs:02d}s" if hours else f"{minutes}m {secs:02d}s"


def log_job_start(area, label, argv):
    """One INFO line: a job is starting, with its full command line."""
    get(area).info('Started %s job "%s": %s', area, label, subprocess.list2cmdline([str(a) for a in argv]))


def record_job(area, label, argv, outcome, output, *, returncode=None, reason="", seconds=0.0):
    """A job ended ("done", "failed" or "stopped"): a summary line in the main log and its
    output in `logs\\jobs\\` (a failed / stopped job's whole buffer, always a file; a successful
    one's last `JOB_SUCCESS_LINES`, none if it said nothing). Returns the file's path or None."""
    lines, dropped = output.snapshot()
    keep = lines if outcome != "done" else lines[-JOB_SUCCESS_LINES:]
    older = dropped + (len(lines) - len(keep))
    path = None
    if keep or outcome != "done":
        path = _write_job_file(area, label, argv, outcome, keep, older, returncode, reason, seconds)
    lg = get(area)
    text = f'{area} job "{label}" {outcome} after {duration_text(seconds)}'
    if returncode is not None:
        text += f" (exit code {returncode})"
    if reason:
        text += " | " + reason.strip().splitlines()[-1][:300]
    if path:
        text += f" | output: {path}"
    lg.log(logging.ERROR if outcome == "failed" else logging.INFO, "%s", text)
    return path


def _write_job_file(area, label, argv, outcome, lines, older, returncode, reason, seconds):
    folder = jobs_dir()
    if not folder:
        return None
    safe = re.sub(r"[^\w.-]+", "_", label)[:40].strip("_") or "job"
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(folder, f"{stamp}-{area}-{safe}-{outcome}.log")
    if not lines:
        shown = "no output"
    elif older:
        shown = f"the last {len(lines)} lines ({older} earlier {'line' if older == 1 else 'lines'} not kept)"
    else:
        shown = f"all {len(lines)} {'line' if len(lines) == 1 else 'lines'}"
    header = [
        f"LlamaMXD {area} job — {outcome}",
        f"Job:       {label}",
        f"Finished:  {datetime.datetime.now():%Y-%m-%d %H:%M:%S} (ran {duration_text(seconds)})",
        f"Exit code: {returncode if returncode is not None else 'n/a'}",
        f"Reason:    {reason.strip() or 'n/a'}",
        f"Command:   {subprocess.list2cmdline([str(a) for a in argv])}",
        f"Output:    {shown}",
        "-" * 72,
    ]
    try:
        os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(scrub("\n".join(header)) + "\n" + "\n".join(lines) + ("\n" if lines else ""))
    except OSError:
        return None
    _prune_jobs(folder)
    return path


def _prune_jobs(folder):
    _prune(folder, "*-failed.log", _KEEP_FAILED_JOBS)
    _prune(folder, "*-stopped.log", _KEEP_FAILED_JOBS)
    _prune(folder, "*-done.log", _KEEP_DONE_JOBS)
