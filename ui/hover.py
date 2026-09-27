# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""`HoverSync`: keeps the cursor and the hover highlights right under a resting pointer.

Qt re-evaluates both only when the mouse moves, so a widget that moves, resizes or goes away under
a still pointer (a layout shift, an animation, a closing popup) leaves the old cursor and highlight
behind until the next move: a hand over nothing, an I-beam over no text field. While the app is
active this looks every `_POLL_MS`; when the pointer hasn't moved but what is under it has, or the
window's cursor isn't the one that widget wants, it sends the window a mouse move to the same spot,
which makes Qt redo both."""
import weakref

from PySide6.QtCore import QEvent, QPointF, Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication, QMouseEvent
from PySide6.QtWidgets import QApplication

_POLL_MS = 120
# The widget at a global point. Module-level so a test can swap it: the offscreen platform can't answer.
widget_at = QApplication.widgetAt


def wanted_cursor(widget):
    """The cursor shape Qt shows over `widget`: its own, else its nearest ancestor's, and an arrow
    over a disabled one."""
    if not widget.isEnabled():
        return Qt.ArrowCursor
    while widget is not None:
        if widget.testAttribute(Qt.WA_SetCursor):
            return widget.cursor().shape()
        widget = widget.parentWidget()
    return Qt.ArrowCursor


class HoverSync:
    """Poll while the app is active; see the module docstring. `tick()` is one look."""

    def __init__(self):
        self._pos = None
        self._under = None          # weakref to the widget under the pointer at the last look
        self._nudged = None         # (x, y, widget id) of the last nudge: once per resting spot
        app = QApplication.instance()
        # Owned by the app: a timer owned by a Python object was torn down after it and crashed at exit.
        self._timer = QTimer(app)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self.tick)
        app.applicationStateChanged.connect(self._on_state)
        self._on_state(app.applicationState())

    def _on_state(self, state):
        """Only look while the app is the active one: nothing to fix, and no wake-ups, in the background."""
        if state == Qt.ApplicationActive:
            self._timer.start()
        else:
            self._timer.stop()
            self._pos = None

    def tick(self):
        """Nudge the window under the pointer if it is showing what used to be there."""
        if (QGuiApplication.mouseButtons() != Qt.NoButton or QApplication.overrideCursor() is not None
                or QApplication.activePopupWidget() is not None):
            self._pos = None        # something has hold of the pointer (a drag, an open list): start over after
            return
        pos = QCursor.pos()
        widget = widget_at(pos)
        last = self._under() if self._under is not None else None
        moved = pos != self._pos
        self._pos = pos
        self._under = weakref.ref(widget) if widget is not None else None
        if moved or widget is None:
            self._nudged = None
            return          # Qt handles a moving pointer itself
        modal = QApplication.activeModalWidget()
        if modal is not None and widget.window() is not modal.window():
            return          # blocked by a dialog: it takes no mouse events
        handle = widget.window().windowHandle()
        spot = (pos.x(), pos.y(), id(widget))
        if handle is not None and spot != self._nudged and (
                widget is not last or handle.cursor().shape() != wanted_cursor(widget)):
            self._nudged = spot
            local = QPointF(handle.mapFromGlobal(pos))
            QApplication.sendEvent(handle, QMouseEvent(QEvent.MouseMove, local, local, QPointF(pos),
                                                       Qt.NoButton, Qt.NoButton, Qt.NoModifier))
