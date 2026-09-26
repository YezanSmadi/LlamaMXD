# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""The borderless window's chrome: `ResizeGrips` (eight invisible strips that start the OS's
native resize) and `WindowControls` (close / maximise / minimise). The grips are real pixels,
like OS chrome; the controls belong to the sidebar and scale with it."""
import os
import re

from PySide6.QtCore import QByteArray, QRectF, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget

from ui import scale
from ui import theme as T
from ui.scale import px

_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets")
_FILL = re.compile(r'fill="(?!none")[^"]*"')   # every painted fill; the `fill="none"` on a group stays
_renderers = {}


def _tinted_svg(name, color):
    """A cached `QSvgRenderer` for `assets/<name>` with every painted fill set to `color` (the
    three icons ship in different colours). Stays vector, smooth at any scale."""
    key = (name, color)
    if key not in _renderers:
        with open(os.path.join(_ASSETS, name), "r", encoding="utf-8") as fh:
            data = _FILL.sub(f'fill="{color}"', fh.read())
        _renderers[key] = QSvgRenderer(QByteArray(data.encode("utf-8")))
    return _renderers[key]


class WindowControls(QWidget):
    """Close, maximise and minimise as bare icons in the sidebar's text colour; the icon under
    the pointer turns STOP_RED (close) or secondary. Placed by geometry in the strip above the
    sidebar title, so it can't move the layout. Borderless mode only."""

    closeRequested = Signal()
    maximizeRequested = Signal()
    minimizeRequested = Signal()

    _ICONS = ("close-window.svg", "maximize-window.svg", "minimize-window.svg")
    LEFT = 6         # reference px from the sidebar's left edge
    SLOT_W = 24      # each icon's click area
    HEIGHT = 24      # the sidebar's top margin
    # Drawn sizes: the close X fills 60% of its box and the square 83%, so Close is drawn larger.
    ICON_SIZES = (20, 16, 16)

    def __init__(self, parent):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self._hover = -1
        self._pressed = -1
        self._maximize_enabled = True
        scale.bind(self, lambda: self.setGeometry(px(self.LEFT), 0, px(self.SLOT_W * len(self._ICONS)), px(self.HEIGHT)),
                   "geometry")
        T.theme.changed.connect(self.update)

    def set_maximize_enabled(self, enabled):
        """Maximise is dimmed and inert while fullscreen (a Settings choice)."""
        self._maximize_enabled = bool(enabled)
        self.update()

    def _slot_at(self, pos):
        x = scale.ref_pos(pos).x()
        i = int(x // self.SLOT_W)
        return i if 0 <= i < len(self._ICONS) else -1

    # Each icon's ink within its 24-unit box (left, right, top, bottom), for the straight-edged
    # ones; None for the close X.
    _INK = (None, (2, 22, 2, 22), (2.5, 21.5, 10.5, 13.5))

    def _icon_rect(self, i, cx, cy, size):
        """The icon's rect in real pixels, snapped so a straight-edged icon's strokes land on
        whole device pixels: the maximise square's 1.33px lines straddled two pixels and looked
        faint at the default size."""
        ink = self._INK[i]
        if ink is None:
            return QRectF(cx - size / 2, cy - size / 2, size, size)
        d = self.devicePixelRatioF()
        left, right, top, _bottom = ink
        k = size / 24.0
        k = max(1, round((right - left) * k * d)) / d / (right - left)
        size = 24 * k
        x = round((cx - size / 2 + left * k) * d) / d - left * k
        y = round((cy - size / 2 + top * k) * d) / d - top * k
        return QRectF(x, y, size, size)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = scale.factor()          # painted in real pixels, not design space: the snapping is to the pixel grid
        normal = T.theme.hex("primary_text")
        for i, name in enumerate(self._ICONS):
            inert = i == 1 and not self._maximize_enabled
            if self._hover == i and not inert:
                color = T.theme.hex("stop" if i == 0 else "secondary")
            else:
                color = normal
            p.setOpacity(0.4 if inert else 1.0)
            rect = self._icon_rect(i, (i + 0.5) * self.SLOT_W * f, self.HEIGHT * f / 2, self.ICON_SIZES[i] * f)
            _tinted_svg(name, color).render(p, rect)

    def mouseMoveEvent(self, event):
        slot = self._slot_at(event.position())
        if slot != self._hover:
            self._hover = slot
            self.update()

    def leaveEvent(self, _event):
        self._hover = -1
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressed = self._slot_at(event.position())

    def mouseReleaseEvent(self, event):
        slot, self._pressed = self._pressed, -1
        if event.button() != Qt.LeftButton or slot < 0 or slot != self._slot_at(event.position()):
            return
        if slot == 0:
            self.closeRequested.emit()
        elif slot == 1 and self._maximize_enabled:
            self.maximizeRequested.emit()
        elif slot == 2:
            self.minimizeRequested.emit()


_EDGE = 5      # thickness of an edge strip
_CORNER = 10   # side of a corner square

_L, _R, _T, _B = Qt.LeftEdge, Qt.RightEdge, Qt.TopEdge, Qt.BottomEdge
_CURSORS = {
    _L: Qt.SizeHorCursor, _R: Qt.SizeHorCursor, _T: Qt.SizeVerCursor, _B: Qt.SizeVerCursor,
    _L | _T: Qt.SizeFDiagCursor, _R | _B: Qt.SizeFDiagCursor,
    _R | _T: Qt.SizeBDiagCursor, _L | _B: Qt.SizeBDiagCursor,
}


class _Grip(QWidget):
    """One invisible strip; a left press starts a native resize from its edge."""

    def __init__(self, window, edges):
        super().__init__(window)
        self._edges = edges
        self.setCursor(_CURSORS[edges])

    def mousePressEvent(self, e):
        handle = self.window().windowHandle()
        if e.button() == Qt.LeftButton and handle is not None:
            handle.startSystemResize(self._edges)


class ResizeGrips:
    """The eight grips of one window. `place()` after every resize; `set_active`
    shows them (borderless, not fullscreen) or hides them."""

    def __init__(self, window):
        self._window = window
        self._grips = [_Grip(window, edges) for edges in _CURSORS]
        self.set_active(False)

    def set_active(self, active):
        for grip in self._grips:
            grip.setVisible(bool(active))
        if active:
            self.place()

    def place(self):
        """Lay the strips along the window's outline, above everything else."""
        w, h = self._window.width(), self._window.height()
        for grip in self._grips:
            e = grip._edges
            left, right = bool(e & _L), bool(e & _R)
            top, bottom = bool(e & _T), bool(e & _B)
            corner = (left or right) and (top or bottom)
            size_x = _CORNER if corner else (_EDGE if (left or right) else w - 2 * _CORNER)
            size_y = _CORNER if corner else (_EDGE if (top or bottom) else h - 2 * _CORNER)
            x = 0 if left else (w - size_x if right else _CORNER)
            y = 0 if top else (h - size_y if bottom else _CORNER)
            grip.setGeometry(x, y, size_x, size_y)
            grip.raise_()
