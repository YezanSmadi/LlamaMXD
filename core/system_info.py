# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""CPU / RAM / disk facts for Settings' system info, via the registry and Win32 calls (no
psutil). Best-effort: a failure gives a placeholder, never an exception."""
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
    """The CPU's marketing name from the registry (`platform.processor()` gives only the
    architecture string on Windows). Cached."""
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
    """"512.3 GB" in binary units, as Windows shows sizes; "Unknown" for None, never "0 B"."""
    if n is None:
        return "Unknown"
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def disk_usage(path):
    """(total_bytes, free_bytes) of the drive holding `path` (a missing path uses its parent),
    or (None, None) when it doesn't reach a drive."""
    directory = path if os.path.isdir(path) else os.path.dirname(path)
    directory = directory or "."
    try:
        usage = shutil.disk_usage(directory)
        return usage.total, usage.free
    except OSError:
        return None, None
