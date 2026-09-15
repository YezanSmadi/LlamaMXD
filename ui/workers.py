"""Off-thread work with results delivered back on the GUI thread.

The CTk app needed a `queue.Queue` plus a self-re-arming `after()` poller for
every kind of background job (thumbnails, probes, HDR renders, yt-dlp fetches,
the Deno check), because Tkinter isn't thread-safe. In Qt a signal emitted from
a worker thread is delivered as a *queued* call on the receiver's thread, so
each job is just "run this, then call that" — no poll loop, no pending count.

Worker functions must never touch a widget; everything they return crosses
back through `run_async`'s callback."""
import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage


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
        except Exception as exc:   # a worker must never take the app down
            print(f"background task failed: {exc!r}")
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
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    return QImage(data, rgba.width, rgba.height, rgba.width * 4, QImage.Format_RGBA8888).copy()
