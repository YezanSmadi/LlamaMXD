"""Win32 window styles Qt doesn't keep in step when a live window's frame or
size limits change (Settings' Window Mode does exactly that).

Measured against the real native window: after Fixed -> Windowed the maximize
button stayed disabled, and after Borderless -> Fixed it stayed enabled on a
window whose size limits were pinned — so a click just moved the window to the
top-left corner at the same size. Likewise the dark title bar: Qt sets DWM's
dark-frame flag when it creates a native window that already has a frame, so a
window launched Borderless and then given a frame by Settings came up with the
flag off and a white title bar over a dark app, and stayed that way."""
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
    # Neither SWP_FRAMECHANGED nor RedrawWindow makes Windows 10 repaint the
    # caption with the new flag (measured on the real title bar: still white);
    # bouncing the frame's active state does. The window's real state is put
    # back, so one in the background doesn't suddenly look focused.
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
