"""Transient notifications that drop in at the current tab frame's top-right.

A toast is a child widget painted with real alpha and antialiased corners,
so it moves and minimizes with the window. At most `_MAX_VISIBLE` hold a slot
at once: every toast runs its own animation, and an uncapped stack under
button-mashing is wasted work — a new arrival retires the oldest into a fast
fade."""
from PySide6.QtCore import QEasingCurve, QPoint, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from ui import theme as T
from ui.widgets.controls import ui_font

_TOAST_WIDTH = 260
_TOAST_HEIGHT = 44
_INSET = 12
_STACK_GAP = 6
_MAX_VISIBLE = 3
_CORNER = 10
_PAD = 14
_SLIDE_MS = 200
_HOLD_MS = 2200
_FADE_MS = 700
_RETIRE_MS = 200


class Toast(QWidget):
    def __init__(self, manager, message, on_click=None):
        super().__init__(manager.window)
        self.manager = manager
        self.message = message
        self._on_click = on_click
        self._opacity = 1.0
        self._dismissed = False
        self.retiring = False
        self._rest = QPoint()
        self.setFixedSize(_TOAST_WIDTH, _TOAST_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._slide = QVariantAnimation(self)
        self._slide.setDuration(_SLIDE_MS)
        self._slide.setEasingCurve(QEasingCurve.OutCubic)
        self._slide.valueChanged.connect(lambda y: self.move(self._rest.x(), round(y)))

        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.timeout.connect(lambda: self._fade_out(_FADE_MS))

        self._fade = QVariantAnimation(self)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.valueChanged.connect(self._set_opacity)
        self._fade.finished.connect(self.dismiss)

    def start(self, rest):
        self._rest = rest
        self._slide.setStartValue(float(rest.y() - _TOAST_HEIGHT - _INSET))
        self._slide.setEndValue(float(rest.y()))
        self.move(rest.x(), rest.y() - _TOAST_HEIGHT - _INSET)
        self.show()
        self.raise_()
        self._slide.start()
        self._hold.start(_SLIDE_MS + _HOLD_MS)

    def reposition(self, rest):
        """Snap to a new slot (the stack closing up, or the window resizing)."""
        self._rest = rest
        if self._slide.state() != QVariantAnimation.Running:
            self.move(rest)
        else:
            self._slide.setEndValue(float(rest.y()))

    def retire(self):
        """Skip the hold and fade out fast — a newer toast pushed this one out."""
        if self._dismissed or self.retiring:
            return
        self.retiring = True
        self._hold.stop()
        self._fade_out(_RETIRE_MS)

    def _fade_out(self, duration):
        self._fade.stop()
        self._fade.setDuration(duration)
        self._fade.setStartValue(self._opacity)
        self._fade.start()

    def _set_opacity(self, value):
        self._opacity = value
        self.update()

    def mousePressEvent(self, e):
        callback = self._on_click
        self.dismiss()
        if callback:
            callback()

    def dismiss(self):
        if self._dismissed:
            return
        self._dismissed = True
        self._slide.stop()
        self._fade.stop()
        self._hold.stop()
        self.manager.forget(self)
        self.hide()
        self.deleteLater()

    def paintEvent(self, _event):
        th = T.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self._opacity)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), _CORNER, _CORNER)
        p.fillPath(path, th.color("primary"))
        p.setPen(th.color("primary_text"))
        p.setFont(ui_font(13))
        p.drawText(QRectF(_PAD, 0, _TOAST_WIDTH - 2 * _PAD, _TOAST_HEIGHT),
                   Qt.AlignVCenter | Qt.AlignLeft | Qt.TextWordWrap, self.message)


class ToastManager:
    """Owns the live toasts for the main window and keeps them stacked."""

    def __init__(self, window, frame_getter):
        self.window = window
        self._frame = frame_getter    # -> the tab frame widget toasts hang off
        self._toasts = []

    def show(self, message, on_click=None):
        active = [t for t in self._toasts if not t.retiring]
        while len(active) >= _MAX_VISIBLE:
            active.pop(0).retire()
        toast = Toast(self, message, on_click)
        self._toasts.append(toast)
        toast.start(self._slot(len(active)))
        return toast

    def _slot(self, index):
        frame = self._frame()
        top_right = frame.mapTo(self.window, frame.rect().topRight())
        return QPoint(top_right.x() - _TOAST_WIDTH - _INSET + 1,
                      top_right.y() + _INSET + index * (_TOAST_HEIGHT + _STACK_GAP))

    def forget(self, toast):
        if toast in self._toasts:
            self._toasts.remove(toast)
        self.relayout()

    def relayout(self):
        index = 0
        for toast in self._toasts:
            if toast.retiring:
                continue
            toast.reposition(self._slot(index))
            index += 1

    def clear(self):
        for toast in list(self._toasts):
            toast.dismiss()
