# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""The Queue tab's own controls: the sort dropdown, When Done button, search toggle and bar,
and the host that slides the details panel up."""
import math

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget

from ui import scale
from ui import theme as T
from ui.widgets.controls import Dropdown, ScaledLineEdit, _icon_svg, draw_cross, ui_font
from ui.widgets.tooltip import tip

GAP = 10                    # reference px between stacked rows (the tab's old layout spacing)
_SLIDE_MS = 320
_SEARCH_MS = 240


def _paint_icon(p, name, color, rect, fraction):
    """Draw `assets/<name>` tinted `color`, centred in `rect` at `fraction` of its shorter side,
    keeping the art's aspect ratio."""
    renderer = _icon_svg(name, color.name())
    if name == "search.svg":
        # The artwork sits in the top 72 of a 72x156 canvas; crop to it so it fills its circle.
        renderer.setViewBox(QRectF(0, 0, 72, 72))
    view = renderer.viewBoxF()
    box = min(rect.width(), rect.height()) * fraction
    k = box / max(view.width(), view.height())
    target = QRectF(0, 0, view.width() * k, view.height() * k)
    target.moveCenter(rect.center())
    renderer.render(p, target)


class SortDropdown(Dropdown):
    """A dropdown whose face reads `<title> | <value> v` -- the title lives inside
    the button, set off by a divider; the open list shows only the options."""

    def __init__(self, title, values):
        super().__init__(values, width=self.width_for_titled(title, values))
        self._title = title

    @classmethod
    def width_for_titled(cls, title, values):
        fm = QFontMetricsF(ui_font(13))
        widest = max(fm.horizontalAdvance(v) for v in values)
        return math.ceil(10 + fm.horizontalAdvance(title) + 8 + 1 + 8 + widest + 6 + cls._ARROW_W)

    def paintEvent(self, _event):
        th = T.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        scale.begin(p)
        r = scale.ref_rect(self)
        enabled = self.isEnabled()
        body = QPainterPath()
        body.addRoundedRect(r, 6, 6)
        p.fillPath(body, th.color("secondary"))
        p.save()
        p.setClipRect(QRectF(r.right() - self._ARROW_W, r.top(), self._ARROW_W, r.height()))
        p.fillPath(body, th.color("secondary_pressed" if self._hover and enabled else "secondary_hover"))
        p.restore()

        color = th.color("secondary_text" if enabled else "secondary_disabled_text")
        p.setPen(color)
        p.setFont(ui_font(13))
        fm = p.fontMetrics()
        title_w = fm.horizontalAdvance(self._title)
        p.drawText(QRectF(10, 0, title_w + 2, r.height()), Qt.AlignVCenter | Qt.AlignLeft, self._title)
        divider = 10 + title_w + 8
        line = QColor(color)
        line.setAlpha(150)
        p.setPen(QPen(line, 1.4))
        p.drawLine(QPointF(divider, 6), QPointF(divider, r.height() - 6))
        p.setPen(color)
        text_rect = QRectF(divider + 8, 0, r.right() - self._ARROW_W - 4 - (divider + 8), r.height())
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft,
                   fm.elidedText(self.value(), Qt.ElideRight, int(text_rect.width())))
        cx, cy = r.right() - self._ARROW_W / 2, r.center().y() + 1
        pen = QPen(color, 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawPolyline([QPointF(cx - 4, cy - 2), QPointF(cx, cy + 2), QPointF(cx + 4, cy - 2)])


class WhenDoneButton(Dropdown):
    """A small square button, filled like Start Queue, with a down triangle: a `Dropdown` of the
    When Done options whose list is wider than the button, opens to its left, and highlights the
    current choice."""

    def __init__(self, values, size=28, list_width=130):
        super().__init__(values, width=size)
        scale.fixed(self, size, size)
        self._list_width = list_width

    def _place_popup(self, container, x, y):
        width = scale.px(self._list_width)
        container.setFixedWidth(width)
        right = self.mapToGlobal(self.rect().topRight()).x() + 1
        container.move(right - width, y)

    def paintEvent(self, _event):
        th = T.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        scale.begin(p)
        r = scale.ref_rect(self)
        key = "action_btn_pressed" if self._open else "action_btn_hover" if self._hover else "action_btn"
        body = QPainterPath()
        body.addRoundedRect(r, 6, 6)
        p.fillPath(body, th.color(key))
        c = r.center()
        tri = QPainterPath()
        tri.moveTo(c.x() - 4.5, c.y() - 2.5)
        tri.lineTo(c.x() + 4.5, c.y() - 2.5)
        tri.lineTo(c.x(), c.y() + 3)
        tri.closeSubpath()
        p.fillPath(tri, th.color("action_btn_text" if self.isEnabled() else "action_btn_disabled_text"))


class SearchToggle(QPushButton):
    """The round search button — filled in the theme's secondary colour, always
    visible; it opens and closes the search bar."""

    def __init__(self, diameter=30):
        super().__init__("")
        self._d = diameter
        scale.fixed(self, diameter, diameter)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self._hover = False
        T.theme.changed.connect(self.update)
        tip(self, "Search the queue")

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        scale.begin(p)
        rect = scale.ref_rect(self)
        th = T.theme
        fill = th.color("secondary_pressed" if self.isDown() else "secondary_hover" if self._hover else "secondary")
        path = QPainterPath()
        path.addEllipse(rect)
        p.fillPath(path, fill)
        _paint_icon(p, "search.svg", th.color("secondary_text"), rect, 0.56)


class _ClearButton(QPushButton):
    """A bare ✕ in the theme's secondary colour, sitting inside the search box."""

    def __init__(self):
        super().__init__("")
        scale.fixed(self, 22, 22)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self._hover = False
        T.theme.changed.connect(self.update)
        tip(self, "Clear the search")

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        scale.begin(p)
        rect = scale.ref_rect(self).adjusted(4, 4, -4, -4)
        draw_cross(p, rect, T.theme.color("secondary_hover" if self._hover else "secondary"), width=2.0)


class SearchBar(QWidget):
    """The search row above the bottom buttons, floating over the list (placed by the tab), so
    a long queue runs on beneath it. The box grows and shrinks horizontally from the middle;
    closed, the row is hidden and takes no room. The ✕ inside only clears the text.
    `queryChanged(text)` reports every edit ("" on close); `heightChanged(px)` the row's height."""

    queryChanged = Signal(str)
    heightChanged = Signal(int)

    ROW_H = 30

    def __init__(self):
        super().__init__()
        self.field = ScaledLineEdit(self)
        self.field.setPlaceholderText("Search the queue")
        scale.bind_style(self.field, lambda: f"padding-right: {scale.px(34)}px;")
        self.clear_btn = _ClearButton()
        self.clear_btn.setParent(self)
        self.clear_btn.hide()
        self._open = False
        self._t = 0.0
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(_SEARCH_MS)
        self._anim.setEasingCurve(QEasingCurve.Linear)
        self._anim.valueChanged.connect(self._on_t)
        self._anim.finished.connect(self._on_done)
        self.clear_btn.clicked.connect(self.field.clear)
        self.field.textChanged.connect(lambda text: self.clear_btn.setVisible(bool(text)))
        self.field.textChanged.connect(self.queryChanged)
        self.hide()

    def is_open(self):
        return self._open

    def _row_px(self):
        return scale.px(self.ROW_H)

    def _gap_px(self):
        return scale.px(GAP)

    def taken_height(self):
        """The room the row claims from an open details panel: just the row, so the panel touches it."""
        return self._row_px()

    def sizeHint(self):
        return QSize(0, self._row_px())

    def minimumSizeHint(self):
        return self.sizeHint()

    def resizeEvent(self, e):
        self._place()

    def _place(self):
        """The box, centred, as wide as the motion has got; the ✕ inside its right end."""
        eased = QEasingCurve(QEasingCurve.OutCubic).valueForProgress(self._t)
        w = round(self.width() * eased)
        h = self._row_px()
        self.field.setGeometry((self.width() - w) // 2, self.height() - h, w, h)
        cw = self.clear_btn.width()
        self.clear_btn.move(self.field.x() + w - cw - scale.px(6), self.field.y() + (h - self.clear_btn.height()) // 2)
        self.clear_btn.raise_()

    def _on_t(self, value):
        self._t = float(value)
        self._place()

    def _on_done(self):
        if self._open:
            self.field.setFocus()
        else:
            self.hide()
            self.heightChanged.emit(0)

    def toggle_open(self):
        self.close_bar() if self._open else self.open_bar()

    def open_bar(self):
        if self._open:
            return
        self._open = True
        self.show()
        self.heightChanged.emit(self.taken_height())
        self.field.setFocus()       # so the box has its focus (secondary) border from the first frame
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def close_bar(self):
        if not self._open:
            return
        self._open = False
        self.field.clearFocus()
        self.field.clear()
        self.queryChanged.emit("")
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(0.0)
        self._anim.start()


class SlideHost(QWidget):
    """Holds a panel that slides up over the bottom of the list, floating (placed by the tab),
    so the list keeps its full height beneath it. The panel rises glued to the host's bottom.
    The search row's `inset` shortens the open panel from the bottom; its top edge stays put."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        panel.setParent(self)
        self._open = False                  # the logical state (a slide may still be running)
        self._h = None                      # slide height in px while animating; None = settled
        self._inset = 0
        self._anchor = (0, 0, 0)            # x, bottom edge y, width — in the parent's coordinates
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(_SLIDE_MS)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._anim.valueChanged.connect(self._on_height)
        self._anim.finished.connect(self._on_done)
        super().hide()

    def is_open(self):
        return self._open

    def _full(self):
        return self.panel.sizeHint().height()

    def _slide_height(self):
        if self._h is None:
            return self._full() if self._open else 0
        return min(self._full(), self._h)

    def set_anchor(self, x, bottom, width):
        """Where the panel's bottom edge sits when fully risen (the list's bottom)."""
        self._anchor = (x, bottom, width)
        self._reposition()

    def set_inset(self, pixels):
        if pixels != self._inset:
            self._inset = pixels
            self._reposition()

    def _reposition(self):
        x, bottom, width = self._anchor
        h = self._slide_height()
        self.setGeometry(x, bottom - h, width, h)
        full = self._full()
        self.panel.setGeometry(0, h - full, width, max(self.panel.minimumSizeHint().height(), full - self._inset))

    def _on_height(self, value):
        self._h = int(value)
        self._reposition()

    def _on_done(self):
        self._h = None
        if not self._open:
            super().hide()
        self._reposition()

    def _run(self, start, end):
        self._anim.stop()
        self._anim.setStartValue(float(start))
        self._anim.setEndValue(float(end))
        self._anim.start()

    def slide_open(self):
        """Rises into view from nothing — a no-op if it is already open."""
        if self._open:
            return
        self._open = True
        self._h = self._slide_height() if self._anim.state() == QVariantAnimation.Running else 0
        self._reposition()
        self.show()
        self.raise_()
        self._run(self._h, self._full())

    def slide_closed(self):
        if not self._open:
            return
        start = self._slide_height()
        self._open = False
        self._h = start
        self._run(start, 0)

    def hide(self):
        """Immediate (no slide): a tab switch or a removed row."""
        self._anim.stop()
        self._open = False
        self._h = None
        super().hide()
