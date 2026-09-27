# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Two-state and one-of-many controls: `CheckBox`, `Switch`, `SegmentedButton`."""
import math

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QWidget

from ui import scale
from ui import theme as T
from ui.scale import px
from ui.widgets.controls import anim
from ui.widgets.text import ui_font

# --------------------------------------------------------------------------- #
#  CheckBox
# --------------------------------------------------------------------------- #
class CheckBox(QAbstractButton):
    """A 24px rounded box, filled with a checkmark when on. `color_key` is "secondary" or
    "stop" (the Strip boxes). The fill fades; disabled greys the box too."""

    def __init__(self, text="", color_key="secondary", checked=False, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self._color_key = color_key
        self._t = 1.0 if checked else 0.0
        self._hover = False
        self._font = ui_font(12, bold=True, family="Arial")
        self._fade = anim(self, 120, self._fade_step)
        self.toggled.connect(self._on_toggled)
        T.theme.changed.connect(self.update)

    def _fade_step(self, v):
        self._t = v if self.isChecked() else 1.0 - v
        self.update()

    def _on_toggled(self, _on):
        if self.isVisible():
            self._fade.stop()
            self._fade.start()
        else:
            self._t = 1.0 if self.isChecked() else 0.0
            self.update()

    def sizeHint(self):
        w = 24
        if self.text():
            w += 8 + QFontMetricsF(self._font).horizontalAdvance(self.text())
        return QSize(px(math.ceil(w) + 1), px(24))

    def minimumSizeHint(self):
        return self.sizeHint()

    def set_hover(self, hover):
        """The hover shade driven from outside, by a row the checkbox sits in."""
        if hover != self._hover:
            self._hover = hover
            self.update()

    def enterEvent(self, e):
        self.set_hover(True)

    def leaveEvent(self, e):
        self.set_hover(False)

    def paintEvent(self, _event):
        th = T.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        scale.begin(p)
        box = QRectF(1.5, 1.5, 21, 21)
        enabled = self.isEnabled()
        if enabled:
            fill = th.color(f"{self._color_key}_hover" if self._hover else self._color_key)
            border = th.color("check_border")
            mark = th.color(f"{self._color_key}_text")
        else:
            fill = border = th.color("disabled")
            mark = th.color("frame")
        edge = T.lerp(border, fill, self._t)

        path = QPainterPath()
        path.addRoundedRect(box, 5, 5)
        if self._t > 0:
            p.fillPath(path, T.with_alpha(fill, self._t))
        p.setPen(QPen(edge, 3))
        p.drawPath(path)

        if self._t > 0.01:
            pen = QPen(T.with_alpha(mark, self._t), 2.4)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.drawPolyline([QPointF(7, 12.5), QPointF(10.5, 16), QPointF(17, 8.5)])

        if self.text():
            p.setFont(self._font)
            p.setPen(th.color("text") if enabled else th.color("label_disabled"))
            p.drawText(QRectF(32, 0, scale.ref_size(self)[0] - 32, 24), Qt.AlignVCenter, self.text())


# --------------------------------------------------------------------------- #
#  StripButton
# --------------------------------------------------------------------------- #
class StripButton(QAbstractButton):
    """The Strip Video/Audio/Subtitles toggle: off reads "Strip <kind>" filled in `stop` red,
    on reads "Return <kind>" filled in `secondary` — the fill and text colour cross-fade between
    the two rather than a checkbox ticking beside a fixed label. `clicked` fires only on a real
    click (`QAbstractButton`'s own signal); `setChecked` from code doesn't animate, so a preset
    or an undo can still set it silently, the same as the checkbox it replaces."""

    def __init__(self, kind, checked=False, parent=None):
        super().__init__(parent)
        self._kind = kind
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self._hover = False
        self._t = 1.0 if checked else 0.0
        self._font = ui_font(12, family="Arial")
        fm = QFontMetricsF(self._font)
        self.ref_width = math.ceil(max(fm.horizontalAdvance(f"Strip {kind}"),
                                       fm.horizontalAdvance(f"Return {kind}")) + 20)
        scale.fixed(self, self.ref_width, 24)
        self._fade = anim(self, 160, self._fade_step)
        self.toggled.connect(self._on_toggled)
        T.theme.changed.connect(self.update)

    def _fade_step(self, v):
        self._t = v if self.isChecked() else 1.0 - v
        self.update()

    def _on_toggled(self, _on):
        if self.isVisible():
            self._fade.stop()
            self._fade.start()
        else:
            self._t = 1.0 if self.isChecked() else 0.0
            self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _event):
        th = T.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        scale.begin(p)
        rect = scale.ref_rect(self)
        enabled = self.isEnabled()
        if enabled:
            shade = "_pressed" if self.isDown() else ("_hover" if self._hover else "")
            fill = T.lerp(th.color(f"stop{shade}"), th.color(f"secondary{shade}"), self._t)
            text_color = T.lerp(th.color("stop_text"), th.color("secondary_text"), self._t)
        else:
            fill = th.color("disabled")
            text_color = T.lerp(th.color("stop_disabled_text"), th.color("secondary_disabled_text"), self._t)
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        p.fillPath(path, fill)
        p.setFont(self._font)
        p.setPen(text_color)
        p.drawText(rect, Qt.AlignCenter, f"Return {self._kind}" if self.isChecked() else f"Strip {self._kind}")


# --------------------------------------------------------------------------- #
#  Switch
# --------------------------------------------------------------------------- #
class Switch(QAbstractButton):
    """A pill track whose knob slides between off and on. Disabled greys both."""

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        scale.fixed(self, 42, 24)
        self._pos = 1.0 if checked else 0.0
        self._from = self._to = self._pos
        self._slide = anim(self, 160, self._step, QEasingCurve.InOutCubic)
        self.toggled.connect(self._on_toggled)
        T.theme.changed.connect(self.update)

    def _on_toggled(self, on):
        self._from = self._pos
        self._to = 1.0 if on else 0.0
        if self.isVisible():
            self._slide.stop()
            self._slide.start()
        else:
            self._pos = self._to
            self.update()

    def _step(self, t):
        self._pos = self._from + (self._to - self._from) * t
        self.update()

    def paintEvent(self, _event):
        th = T.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        scale.begin(p)
        track = QRectF(3, 5, 36, 14)
        enabled = self.isEnabled()
        on_color = th.color("secondary") if enabled else th.color("disabled")
        off_color = th.color("track")
        p.setPen(Qt.NoPen)
        p.setBrush(T.lerp(off_color, on_color, self._pos))
        p.drawRoundedRect(track, 7, 7)
        knob_r = 8.0
        x = track.left() + knob_r - 1 + (track.width() - 2 * knob_r + 2) * self._pos
        p.setBrush(th.color("knob") if enabled else th.color("disabled"))
        if not enabled:
            p.setPen(QPen(th.color("frame"), 1.5))
        p.drawEllipse(QPointF(x, track.center().y()), knob_r, knob_r)


# --------------------------------------------------------------------------- #
#  SegmentedButton
# --------------------------------------------------------------------------- #
class SegmentedButton(QWidget):
    """A segmented selector whose selection pill slides. `changed` fires on a user click only;
    `set` is silent."""

    changed = Signal(str)

    def __init__(self, options, current=None, parent=None):
        super().__init__(parent)
        self._options = list(options)
        self._index = self._options.index(current) if current in self._options else 0
        self._pos = self._from = float(self._index)
        self._hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self._font = ui_font(13)
        fm = QFontMetricsF(self._font)
        self._widths = [fm.horizontalAdvance(o) + 16 for o in self._options]
        scale.fixed(self, math.ceil(sum(self._widths)) + 4, 28)
        self._slide = anim(self, 180, self._step)
        T.theme.changed.connect(self.update)

    def value(self):
        return self._options[self._index]

    def set(self, value):
        if value in self._options:
            self._slide.stop()
            self._index = self._options.index(value)
            self._pos = float(self._index)
            self.update()

    def _x_of(self, pos):
        """Left edge + width of a (possibly fractional) segment position."""
        i = min(int(pos), len(self._widths) - 1)
        frac = pos - i
        x = 2 + sum(self._widths[:i])
        w = self._widths[i]
        if frac and i + 1 < len(self._widths):
            x += w * frac
            w = w + (self._widths[i + 1] - w) * frac
        return x, w

    def _step(self, t):
        self._pos = self._from + (self._index - self._from) * t
        self.update()

    def _hit(self, x):
        edge = 2
        for i, w in enumerate(self._widths):
            if edge <= x < edge + w:
                return i
            edge += w
        return -1

    def mouseMoveEvent(self, e):
        h = self._hit(scale.ref_pos(e.position()).x())
        if h != self._hover:
            self._hover = h
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def mousePressEvent(self, e):
        self.select(self._hit(scale.ref_pos(e.position()).x()))

    def select(self, i):
        """Slide to segment `i` and report it (a user choice)."""
        if i >= 0 and i != self._index and self.isEnabled():
            self._from = self._pos
            self._index = i
            self._slide.stop()
            self._slide.start()
            self.changed.emit(self._options[i])

    def nav_stops(self):
        """The keyboard's stops: `(rect in real pixels, activate)` per segment."""
        f = scale.factor()
        edge, stops = 2, []
        for i, w in enumerate(self._widths):
            stops.append((QRectF(edge * f, 0, w * f, self.height()).toRect(), lambda i=i: self.select(i)))
            edge += w
        return stops

    def changeEvent(self, e):
        self.update()
        super().changeEvent(e)

    def paintEvent(self, _event):
        th = T.theme
        enabled = self.isEnabled()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        scale.begin(p)
        height = scale.ref_size(self)[1]
        p.setPen(Qt.NoPen)
        p.setBrush(th.color("segment"))
        p.drawRoundedRect(scale.ref_rect(self), 6, 6)
        if enabled and 0 <= self._hover != self._index:
            hx, hw = self._x_of(self._hover)
            p.setBrush(th.color("menu_hover"))
            p.drawRoundedRect(QRectF(hx, 2, hw, height - 4), 5, 5)
        x, w = self._x_of(self._pos)
        p.setBrush(th.color("secondary"))
        p.drawRoundedRect(QRectF(x, 2, w, height - 4), 5, 5)
        p.setFont(self._font)
        edge = 2
        for i, (opt, sw) in enumerate(zip(self._options, self._widths)):
            near = max(0.0, 1.0 - abs(self._pos - i))
            if enabled:
                p.setPen(T.lerp(th.color("text"), th.color("secondary_text"), near))
            else:
                p.setPen(T.lerp(th.color("label_disabled"), th.color("secondary_disabled_text"), near))
            p.drawText(QRectF(edge, 0, sw, height), Qt.AlignCenter, opt)
            edge += sw
