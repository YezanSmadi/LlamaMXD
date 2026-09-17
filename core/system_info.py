"""CPU / RAM / disk facts for the Settings tab's system info block. No UI
code, no extra dependency (psutil isn't in requirements.txt) -- everything
here goes through the registry or ctypes' Win32 calls directly. Every
lookup is best-effort: a failure returns a placeholder rather than raising,
same posture as core.utilities' ffmpeg capability probes.
"""
import ctypes
import os
import platform
import re
import shutil
import winreg

_cpu_name = None
_ram_total_bytes = None


def _query_cpu_name():
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        )
        name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
        return re.sub(r"\s+", " ", name).strip()
    except OSError:
        return None


def cpu_name():
    """The CPU's marketing name (e.g. "AMD Ryzen 7 5800X"), from the
    registry -- platform.processor() only returns the raw architecture
    string ("AMD64 Family 25 Model 33...") on Windows, not a human name.
    Cached; the CPU can't change while the process is running."""
    global _cpu_name
    if _cpu_name is None:
        _cpu_name = _query_cpu_name() or platform.processor() or "Unknown CPU"
    return _cpu_name


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


def _query_ram_total():
    try:
        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return None
        return int(stat.ullTotalPhys)
    except OSError:
        return None


def ram_total_bytes():
    """Installed physical RAM in bytes, via GlobalMemoryStatusEx. Cached;
    None if the call itself failed (never 0 -- see format_bytes)."""
    global _ram_total_bytes
    if _ram_total_bytes is None:
        _ram_total_bytes = _query_ram_total()
    return _ram_total_bytes


def format_bytes(n):
    """"512.3 GB" -- binary (1024-based) units, matching how Windows itself
    reports disk and RAM sizes. "Unknown" for a lookup that failed (None),
    never a bare "0 B" that reads as a real, if odd, measurement."""
    if n is None:
        return "Unknown"
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def disk_usage(path):
    """(total_bytes, free_bytes) for the drive holding `path` -- a file, a
    folder, or a not-yet-created path (falls back to its parent directory).
    (None, None) if that still doesn't resolve to a reachable drive (an
    empty setting, a disconnected network share)."""
    directory = path if os.path.isdir(path) else os.path.dirname(path)
    directory = directory or "."
    try:
        usage = shutil.disk_usage(directory)
        return usage.total, usage.free
    except OSError:
        return None, None
