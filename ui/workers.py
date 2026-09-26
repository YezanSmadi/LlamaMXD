# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Off-thread work with results delivered back on the GUI thread.

A signal emitted from a worker thread is delivered as a *queued* call on the
receiver's thread, so each background job (thumbnails, probes, HDR renders,
yt-dlp fetches, the Deno check) is just "run this, then call that" — no poll
loop, no pending count.

Worker functions must never touch a widget; everything they return crosses
back through `run_async`'s callback."""
import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from core import llamalog


class _Bridge(QObject):
    delivered = Signal(object, object)   # (callback, result)

    def __init__(self):
        super().__init__()
        self.delivered.connect(self._call)

    @staticmethod
    def _call(callback, result):
        callback(result)


_bridge = None


def init_workers():
    """Create the GUI-thread bridge (call once, after the QApplication)."""
    global _bridge
    _bridge = _Bridge()


def run_async(fn, on_done, *args):
    """Run `fn(*args)` on a daemon thread; `on_done(result)` runs on the GUI
    thread afterwards. An exception inside `fn` is delivered as `None`."""
    def work():
        try:
            result = fn(*args)
        except Exception:   # a worker must never take the app down
            llamalog.get("workers").exception("Background task %s failed", getattr(fn, "__qualname__", fn))
            result = None
        _bridge.delivered.emit(on_done, result)

    threading.Thread(target=work, daemon=True).start()


def emit_progress(on_value, value):
    """Deliver an intermediate value from a worker to the GUI thread."""
    _bridge.delivered.emit(on_value, value)


def pil_to_qimage(image):
    """A PIL image as a detached QImage (safe to build on a worker thread —
    unlike QPixmap, QImage isn't tied to the GUI thread)."""
    if image is None:
        return None
    if image.mode not in ("RGBA", "LA", "PA", "P") and "transparency" not in image.info:
        # No alpha: 3 bytes a pixel, not 4 (a set of ten 4K preview frames is 75MB less).
        rgb = image.convert("RGB")
        return QImage(rgb.tobytes(), rgb.width, rgb.height, rgb.width * 3, QImage.Format_RGB888).copy()
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    return QImage(data, rgba.width, rgba.height, rgba.width * 4, QImage.Format_RGBA8888).copy()
