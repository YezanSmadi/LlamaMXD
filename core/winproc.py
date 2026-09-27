# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Windows process control for the tools the app runs (ffmpeg, ffprobe, yt-dlp, deno, WMI): one
kill-on-close job object holds every one of them, so none outlives the app — a close, a crash or
End Task takes them down (Windows doesn't take a child down with its parent). Processes the user
asked for (a browser, Explorer, Notepad) are never put in it. Also: suspend / resume. No imports
from the rest of the app."""
import os
import subprocess
import threading

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
BELOW_NORMAL = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
_CREATE_SUSPENDED = 0x00000004

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")
    _k32.OpenProcess.restype = ctypes.c_void_p
    _k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    _k32.CloseHandle.argtypes = [ctypes.c_void_p]
    _k32.CreateJobObjectW.restype = ctypes.c_void_p
    _k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _k32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    _ntdll.NtSuspendProcess.argtypes = [ctypes.c_void_p]
    _ntdll.NtResumeProcess.argtypes = [ctypes.c_void_p]
    _PROCESS_SUSPEND_RESUME = 0x0800

    class _BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimits), ("IoInfo", ctypes.c_ulonglong * 6),
            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _JOB_EXTENDED_LIMITS = 9
    _KILL_ON_JOB_CLOSE = 0x2000

_job = None
_job_lock = threading.Lock()


def set_suspended(pid, suspended):
    """Freeze or thaw every thread of process `pid` via ntdll's NtSuspendProcess /
    NtResumeProcess (Windows has no SIGSTOP). Returns whether it worked."""
    if os.name != "nt":
        import signal
        try:
            os.kill(pid, signal.SIGSTOP if suspended else signal.SIGCONT)
            return True
        except OSError:
            return False
    handle = _k32.OpenProcess(_PROCESS_SUSPEND_RESUME, False, pid)
    if not handle:
        return False
    try:
        call = _ntdll.NtSuspendProcess if suspended else _ntdll.NtResumeProcess
        return call(handle) == 0
    finally:
        _k32.CloseHandle(handle)


def _tools_job():
    """The kill-on-close job every tool joins, made on first use. Its handle is never closed: the
    app exiting (however it exits) closes it, and Windows ends every process still in it."""
    global _job
    if os.name != "nt":
        return None
    with _job_lock:
        if _job is None:
            handle = _k32.CreateJobObjectW(None, None)
            if handle:
                info = _ExtendedLimits()
                info.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
                if _k32.SetInformationJobObject(handle, _JOB_EXTENDED_LIMITS, ctypes.byref(info), ctypes.sizeof(info)):
                    _job = handle
                else:
                    _k32.CloseHandle(handle)
        return _job


def contain(proc):
    """Put `proc` (a Popen) in the tools job, so it can't outlive the app. Returns whether it
    worked. Its children join too if it is still suspended."""
    job = _tools_job()
    return bool(job) and bool(_k32.AssignProcessToJobObject(job, ctypes.c_void_p(int(proc._handle))))


def run(args, *, timeout, text=False, env=None, below_normal=False):
    """`subprocess.run(args, capture_output=True)` for a tool: no console window, started
    suspended, put in the tools job, then let go — so neither it nor anything it starts can outlive
    the app. Killed on a timeout or any error; raises like `subprocess.run`."""
    flags = NO_WINDOW | (BELOW_NORMAL if below_normal else 0) | (_CREATE_SUSPENDED if os.name == "nt" else 0)
    proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=text, env=env, creationflags=flags)
    try:
        if os.name == "nt":
            contain(proc)
            set_suspended(proc.pid, False)
        stdout, stderr = proc.communicate(timeout=timeout)
    except BaseException:
        proc.kill()
        proc.communicate()
        raise
    return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
