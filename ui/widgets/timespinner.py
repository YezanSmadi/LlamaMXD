# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""`TimeSpinner`: the self-painted HH:MM:SS field with a stepper."""
from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ui import scale
from ui import theme as T
from ui.widgets.controls import IconButton
from ui.widgets.text import ui_font

# --------------------------------------------------------------------------- #
#  TimeSpinner
# --------------------------------------------------------------------------- #
class _TimeField(QWidget):
    """The self-painted HH:MM:SS field. State is a 6-digit list indexed by `cursor_pos`: typing
    overwrites and advances, Backspace steps back then clears, Delete clears in place. Minutes
    and seconds clamp to 59."""

    edited = Signal()

    _SEGMENT_POSITIONS = (0, 1, 3, 4, 6, 7)

    def __init__(self, parent=None, mute_when_zero=False):
        super().__init__(parent)
        self.digits = list("000000")
        self.cursor_pos = 5
        self._mute_when_zero = mute_when_zero
        scale.fixed(self, 100, 30)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setCursor(Qt.IBeamCursor)
        self._font = ui_font(13)
        T.theme.changed.connect(self.update)

    def text(self):
        d = self.digits
        return f"{d[0]}{d[1]}:{d[2]}{d[3]}:{d[4]}{d[5]}"

    def _clamp(self):
        if int("".join(self.digits[2:4])) > 59:
            self.digits[2:4] = ["5", "9"]
        if int("".join(self.digits[4:6])) > 59:
            self.digits[4:6] = ["5", "9"]

    def _char_rects(self):
        fm = QFontMetricsF(self._font)
        text = self.text()
        total = fm.horizontalAdvance(text)
        width, height = scale.ref_size(self)
        x = (width - total) / 2
        rects = []
        for ch in text:
            w = fm.horizontalAdvance(ch)
            rects.append(QRectF(x, 0, w, height))
            x += w
        return rects

    def keyPressEvent(self, e):
        key = e.key()
        if key in (Qt.Key_Tab, Qt.Key_Backtab):
            return super().keyPressEvent(e)
        text = e.text()
        if text and text.isdigit():
            self.digits[self.cursor_pos] = text
            self._clamp()
            self.cursor_pos = min(5, self.cursor_pos + 1)
            self.edited.emit()
        elif key == Qt.Key_Backspace:
            if self.cursor_pos > 0:
                self.cursor_pos -= 1
            self.digits[self.cursor_pos] = "0"
            self.edited.emit()
        elif key == Qt.Key_Delete:
            self.digits[self.cursor_pos] = "0"
            self.edited.emit()
        elif key == Qt.Key_Left:
            self.cursor_pos = max(0, self.cursor_pos - 1)
        elif key == Qt.Key_Right:
            self.cursor_pos = min(5, self.cursor_pos + 1)
        elif key == Qt.Key_Home:
            self.cursor_pos = 0
        elif key == Qt.Key_End:
            self.cursor_pos = 5
        self.update()
        e.accept()   # every other key is swallowed

    def mousePressEvent(self, e):
        self.setFocus(Qt.MouseFocusReason)
        rects = self._char_rects()
        x = scale.ref_pos(e.position()).x()
        distances = [abs(rects[pos].center().x() - x) for pos in self._SEGMENT_POSITIONS]
        self.cursor_pos = distances.index(min(distances))
        self.update()

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
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        p.fillPath(path, th.color("entry"))
        p.setPen(QPen(th.color("entry_border"), 2))
        p.drawPath(path)

        enabled = self.isEnabled()
        # Muted while every digit is 0 (fields that opt in): an untouched time reads as unset.
        muted = self._mute_when_zero and all(d == "0" for d in self.digits)
        rects = self._char_rects()
        p.setFont(self._font)
        fm = QFontMetricsF(self._font)
        block = self._SEGMENT_POSITIONS[self.cursor_pos] if (self.hasFocus() and enabled) else -1
        for i, ch in enumerate(self.text()):
            r = rects[i]
            if i == block:
                hl = QRectF(r.left(), (scale.ref_size(self)[1] - fm.height()) / 2, r.width(), fm.height())
                p.fillRect(hl, th.color("secondary"))
                p.setPen(th.color("secondary_text"))
            elif not enabled:
                p.setPen(th.color("label_disabled"))
            else:
                p.setPen(th.color("label_disabled") if muted else th.color("text"))
            p.drawText(r, Qt.AlignCenter, ch)


class TimeSpinner(QWidget):
    """HH:MM:SS field plus a ▲/▼ stepper with an accelerating auto-repeat (400ms -> 30ms).
    `valueChanged` fires on every change, typing and `set_seconds` included."""

    valueChanged = Signal(int)

    def __init__(self, seconds=0, parent=None, mute_when_zero=False):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        scale.spacing(lay, 5)
        self.field = _TimeField(mute_when_zero=mute_when_zero)
        self.field.edited.connect(lambda: self.valueChanged.emit(self.seconds()))
        lay.addWidget(self.field)

        stepper = QVBoxLayout()
        scale.spacing(stepper, 2)
        scale.margins(stepper, 0, 1, 0, 1)
        self.btn_plus = IconButton("up", role="stepper")
        self.btn_minus = IconButton("down", role="stepper")
        stepper.addWidget(self.btn_plus)
        stepper.addWidget(self.btn_minus)
        lay.addLayout(stepper)

        self._repeat = QTimer(self)
        self._repeat.setSingleShot(True)
        self._repeat.setTimerType(Qt.PreciseTimer)
        self._repeat.timeout.connect(self._tick)
        self._delta = 0
        self._delay = 400
        self._held = None
        for btn, delta in ((self.btn_plus, 1), (self.btn_minus, -1)):
            btn.pressed.connect(lambda d=delta, b=btn: self._press(d, b))
            btn.released.connect(self._repeat.stop)
        self.set_seconds(seconds)

    def seconds(self):
        d = self.field.digits
        return int(d[0] + d[1]) * 3600 + int(d[2] + d[3]) * 60 + int(d[4] + d[5])

    def set_seconds(self, total):
        total = max(0, int(total or 0))
        hrs = min(99, total // 3600)
        mins = (total % 3600) // 60
        secs = total % 60
        self.field.digits = list(f"{hrs:02d}{mins:02d}{secs:02d}")
        self.field.update()
        self.valueChanged.emit(self.seconds())

    def _press(self, delta, btn):
        self._delta, self._held = delta, btn
        self._delay = 400
        self.set_seconds(self.seconds() + delta)
        self._schedule()

    def _schedule(self):
        self._delay = max(30, int(self._delay * 0.85))
        self._repeat.start(self._delay)

    def _tick(self):
        if self._held is None or not self._held.isDown():
            return   # dragged off the button — stop repeating
        self.set_seconds(self.seconds() + self._delta)
        self._schedule()
