# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Win32 window styles Qt leaves stale when a live window's frame or size limits change (Window
Mode): the maximize button's enabled state, and DWM's dark title bar, which Qt sets only for a
window created with a frame."""
import os

_WS_MAXIMIZEBOX = 0x00010000

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    _user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    _dwm = ctypes.WinDLL("dwmapi")
    _dwm.DwmSetWindowAttribute.restype = ctypes.c_long
    _dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    _user32.SendMessageW.restype = ctypes.c_ssize_t
    _user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _GWL_STYLE = -16
    _WM_NCACTIVATE = 0x0086
    # SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
    _SWP_REFRESH = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020


def set_dark_titlebar(hwnd, dark):
    """Give a framed window a dark (or light) native title bar and redraw it. DWM's
    DWMWA_USE_IMMERSIVE_DARK_MODE is attribute 20 on Windows 10 2004+ / 11 and 19
    on the builds before it; a no-op off Windows."""
    if os.name != "nt":
        return
    hwnd = wintypes.HWND(hwnd)
    value = ctypes.c_int(1 if dark else 0)
    for attribute in (20, 19):
        if _dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
            break
    _user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, _SWP_REFRESH)
    # Windows 10 repaints the caption only when the frame's active state is bounced (not on
    # SWP_FRAMECHANGED or RedrawWindow); the real active state is put back.
    active = _user32.GetForegroundWindow() == hwnd.value
    _user32.SendMessageW(hwnd, _WM_NCACTIVATE, 0 if active else 1, 0)
    _user32.SendMessageW(hwnd, _WM_NCACTIVATE, 1 if active else 0, 0)


def set_maximize_box(hwnd, enabled):
    """Enable or disable a window's maximize button (a no-op off Windows)."""
    if os.name != "nt":
        return
    hwnd = wintypes.HWND(hwnd)
    style = _user32.GetWindowLongPtrW(hwnd, _GWL_STYLE)
    wanted = (style | _WS_MAXIMIZEBOX) if enabled else (style & ~_WS_MAXIMIZEBOX)
    if wanted != style:
        _user32.SetWindowLongPtrW(hwnd, _GWL_STYLE, wanted)
        _user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, _SWP_REFRESH)   # redraw the caption buttons
