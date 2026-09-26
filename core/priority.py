# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Process priority for the encode/download jobs the Queue runs (Settings'
"Priority Level"). Windows priority classes, by the same names Task Manager
uses; `REALTIME` is deliberately not offered — it can starve the mouse and
keyboard drivers, which a video encoder has no business doing."""
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

if os.name == "nt":
    import ctypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.OpenProcess.restype = ctypes.c_void_p
    _k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    _k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    _k32.CloseHandle.argtypes = [ctypes.c_void_p]
    _PROCESS_SET_INFORMATION = 0x0200


def class_for(level):
    """The Windows priority class for `level` (Normal for anything unknown)."""
    return _CLASSES.get(level, _CLASSES[DEFAULT_LEVEL])


def creation_flag(level):
    """`Popen(creationflags=...)` bit that starts a process at `level`."""
    return class_for(level) if os.name == "nt" else 0


def set_process_priority(pid, level):
    """Moves running process `pid` to `level`. Returns whether it worked."""
    if os.name != "nt":
        return False
    handle = _k32.OpenProcess(_PROCESS_SET_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        return bool(_k32.SetPriorityClass(handle, class_for(level)))
    finally:
        _k32.CloseHandle(handle)

