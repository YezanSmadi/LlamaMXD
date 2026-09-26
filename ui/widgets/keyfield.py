# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""KeyField: a box showing a shortcut's key; click it, press a key, and that becomes the shortcut."""
from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ui import keymap, scale
from ui import theme as T
from ui.widgets.text import ui_font

PROMPT = "Press a key…"


def display_key(spec):
    """A portable key string as the user knows it: "Ctrl+Alt+1" reads "Ctrl + Alt + 1", and
    "Return" is the Enter key. The plus key itself ("Ctrl++") is kept whole."""
    keys = spec.split("+")
    if spec.endswith("+"):                       # "+" or "Ctrl++": the last key is a plus sign
        keys = keys[:-2] + ["+"]
    return " + ".join("Enter" if key == "Return" else key for key in keys)


class KeyField(QWidget):
    """Shows the current key. A click starts listening (real focus, so the app-wide shortcuts stand
    aside — `captures_keys`); the next key pressed is reported through `captured` and listening
    stops. Every key is takeable, Esc and Tab included, so leaving without a change is a click
    elsewhere. A bare modifier is ignored (Ctrl+F is a Ctrl press first, then F)."""

    captured = Signal(str)
    captures_keys = True

    def __init__(self, key="", width=120, parent=None):
        super().__init__(parent)
        self._key = key
        scale.fixed(self, width, 28)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setCursor(Qt.PointingHandCursor)
        self._font = ui_font(13)
        T.theme.changed.connect(self.update)

    def key(self):
        return self._key

    def set_key(self, spec):
        self._key = spec
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.isEnabled():
            self.setFocus(Qt.MouseFocusReason)
            self.update()

    def event(self, e):
        """Takes every key press while listening — Tab and Esc included, which Qt would
        otherwise use to move focus — and a ShortcutOverride so no other shortcut claims it."""
        if e.type() in (QEvent.ShortcutOverride, QEvent.KeyPress) and self.hasFocus():
            if e.type() == QEvent.KeyPress and not e.isAutoRepeat():
                spec = keymap.event_spec(e)
                if spec:
                    self.clearFocus()
                    self.captured.emit(spec)
            e.accept()
            return True
        return super().event(e)

    def focusInEvent(self, e):
        self.update()

    def focusOutEvent(self, e):
        self.update()

    def changeEvent(self, e):
        self.update()
        super().changeEvent(e)

    def paintEvent(self, _event):
        th = T.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        scale.begin(p)
        rect = scale.ref_rect(self).adjusted(1, 1, -1, -1)
        listening = self.hasFocus() and self.isEnabled()
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        p.fillPath(path, th.color("entry"))
        p.setPen(QPen(th.color("secondary" if listening else "entry_border"), 2))
        p.drawPath(path)
        p.setFont(self._font)
        if listening:
            p.setPen(th.color("label_disabled"))
            text = PROMPT
        else:
            p.setPen(th.color("text" if self.isEnabled() else "label_disabled"))
            text = display_key(self._key) or "—"
        text = p.fontMetrics().elidedText(text, Qt.ElideRight, int(rect.width() - 12))
        p.drawText(QRectF(rect), Qt.AlignCenter, text)
