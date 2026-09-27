# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Process priority for the encode/download jobs the Queue runs (Settings'
"Priority Level"). Windows priority classes, by the same names Task Manager
uses; `REALTIME` is deliberately not offered — it can starve the mouse and
keyboard drivers, which a video encoder has no business doing. Below Normal and
Low also lower the process's disk I/O and memory priority, so a big remux or
merge doesn't bog down the rest of the machine either."""
import os

LEVELS = ["High", "Above Normal", "Normal", "Below Normal", "Low"]
DEFAULT_LEVEL = "Normal"

# name -> Windows priority class flag (the value CreateProcess and
# SetPriorityClass both take).
_CLASSES = {
    "High": 0x00000080,
    "Above Normal": 0x00008000,
    "Normal": 0x00000020,
    "Below Normal": 0x00004000,
    "Low": 0x00000040,       # IDLE_PRIORITY_CLASS — Task Manager's "Low"
}

# name -> (I/O priority, memory priority). I/O: 0 very low, 1 low, 2 normal (high needs a
# privilege); memory: 1-5, 5 normal. Normal and above keep the defaults.
_IO_MEMORY = {
    "Below Normal": (1, 4),
    "Low": (0, 2),
}
_NORMAL_IO_MEMORY = (2, 5)

if os.name == "nt":
    import ctypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.OpenProcess.restype = ctypes.c_void_p
    _k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    _k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    _k32.CloseHandle.argtypes = [ctypes.c_void_p]
    _k32.SetProcessInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    _ntdll = ctypes.WinDLL("ntdll")
    _ntdll.NtSetInformationProcess.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
    _PROCESS_SET_INFORMATION = 0x0200
    _PROCESS_IO_PRIORITY = 33          # NtSetInformationProcess class (no documented API sets it)
    _PROCESS_MEMORY_PRIORITY = 0       # SetProcessInformation class


def class_for(level):
    """The Windows priority class for `level` (Normal for anything unknown)."""
    return _CLASSES.get(level, _CLASSES[DEFAULT_LEVEL])


def creation_flag(level):
    """`Popen(creationflags=...)` bit that starts a process at `level`."""
    return class_for(level) if os.name == "nt" else 0


def io_memory_for(level):
    """`(I/O priority, memory priority)` for `level`."""
    return _IO_MEMORY.get(level, _NORMAL_IO_MEMORY)


def set_process_priority(pid, level):
    """Moves running process `pid` to `level`: CPU, disk I/O and memory priority. Returns whether
    the CPU class took (the other two are best-effort)."""
    if os.name != "nt":
        return False
    handle = _k32.OpenProcess(_PROCESS_SET_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        io, memory = io_memory_for(level)
        io_value, memory_value = ctypes.c_ulong(io), ctypes.c_ulong(memory)
        _ntdll.NtSetInformationProcess(handle, _PROCESS_IO_PRIORITY, ctypes.byref(io_value), 4)
        _k32.SetProcessInformation(handle, _PROCESS_MEMORY_PRIORITY, ctypes.byref(memory_value), 4)
        return bool(_k32.SetPriorityClass(handle, class_for(level)))
    finally:
        _k32.CloseHandle(handle)

