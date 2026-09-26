# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""`Dropdown`: the self-painted dropdown, and `NO_OPTION`, the placeholder it shows for nothing."""
import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFontMetricsF, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import QApplication, QComboBox, QStyledItemDelegate

from ui import scale
from ui import theme as T
from ui.scale import px
from ui.widgets.controls import anim
from ui.widgets.text import ui_font

NO_OPTION = "—"


# --------------------------------------------------------------------------- #
#  Dropdown
# --------------------------------------------------------------------------- #
class Dropdown(QComboBox):
    """A secondary-filled dropdown with a darker arrow section. Opens straight down (or up, when
    there's more room above), unrolling and fading in via a mask on the popup, and reports row
    hover through `hovered(str)`. `set(value)` shows a value outside the list as a display-only
    override (Passthru mirroring a source's real bitrate); read it with `value()`."""

    picked = Signal(str)
    hovered = Signal(str)
    popupClosed = Signal()

    _OPEN_MS = 150
    _GAP = 3
    _ARROW_W = 28.0
    open_one = None      # the dropdown whose list is showing, if any (the keyboard routes to it)

    def __init__(self, values=(), width=None, parent=None):
        super().__init__(parent)
        self._override = None
        self._hover = False
        self._open = False
        self._up = False
        self.addItems(list(values) or [NO_OPTION])
        scale.fixed(self, width or None, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMaxVisibleItems(14)
        self.setItemDelegate(QStyledItemDelegate(self))
        self.view().setMouseTracking(True)
        self.view().entered.connect(lambda idx: self.hovered.emit(idx.data()))
        self.activated.connect(self._on_activated)

        container = self.view().parentWidget()
        container.setWindowFlags(
            container.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
        )
        container.setAttribute(Qt.WA_TranslucentBackground)
        self._container = container
        self._unroll = anim(self, self._OPEN_MS, self._unroll_step)
        T.theme.changed.connect(self.update)

    @classmethod
    def width_for(cls, values, min_width=60):
        """The width (reference pixels) fitting the longest of `values`."""
        fm = QFontMetricsF(ui_font(13))
        widest = max((fm.horizontalAdvance(v) for v in values), default=0)
        return max(min_width, math.ceil(widest + 8 + 6 + cls._ARROW_W))

    # --- values -------------------------------------------------------------
    def value(self):
        return self._override if self._override is not None else self.currentText()

    def values(self):
        return [self.itemText(i) for i in range(self.count())]

    def set(self, value):
        """Select `value`; a value not in the list is shown as an override."""
        if value is None:
            return
        idx = self.findText(value)
        self.blockSignals(True)
        if idx >= 0:
            self._override = None
            self.setCurrentIndex(idx)
        else:
            self._override = value
        self.blockSignals(False)
        self.update()

    def set_values(self, values):
        """Replace the option list. A no-op when unchanged and no override is showing; keeps a
        still-legal pick, else snaps to the first. A display override is not a legal pick (a
        no-file `—` once survived an unchanged list). Never fires `picked`."""
        values = list(values) or [NO_OPTION]
        if values == self.values() and self._override is None:
            return
        current = self.value()
        self.blockSignals(True)
        self.clear()
        self.addItems(values)
        self.blockSignals(False)
        self._override = None
        self.set(current if current in values else values[0])

    def retarget(self, values, default=None):
        """`set_values`, then (with `default`) a pick no longer in `values` goes to `default` if
        offered, else the first. Returns the real pick that was replaced, for the caller's toast,
        or None (kept, or it was only the no-file `—`)."""
        before = self.value()
        self.set_values(values)
        if default is not None and before not in values:
            self.set(default if default in values else values[0])
        after = self.value()
        return before if before != after and before != NO_OPTION else None

    def close(self):
        if self._open:
            self.hidePopup()

    def _on_activated(self, index):
        self._override = None
        self.update()
        self.picked.emit(self.itemText(index))

    # --- popup ----------------------------------------------------------------
    def showPopup(self):
        idx = self.findText(self.value())
        if idx >= 0:
            self.blockSignals(True)
            self.setCurrentIndex(idx)
            self.blockSignals(False)
        # Invisible until placed: Qt shows the list at its own spot first.
        self._container.setWindowOpacity(0.0)
        super().showPopup()
        self._open = True
        Dropdown.open_one = self
        c = self._container
        gap = px(self._GAP)
        below = self.mapToGlobal(self.rect().bottomLeft())
        above_y = self.mapToGlobal(self.rect().topLeft()).y()
        area = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        room_below = area.bottom() + 1 - (below.y() + gap)
        room_above = above_y - gap - area.top()
        # Opens upward only when the list won't fit below and there's more room above.
        self._up = c.height() > room_below and room_above > room_below
        if self._up:
            y = max(area.top(), above_y - gap - c.height())
        else:
            y = below.y() + gap
        self._place_popup(c, below.x(), y)
        c.setWindowOpacity(0.25)
        self._set_unroll_mask(1)
        self._unroll.stop()
        self._unroll.start()

    def _place_popup(self, container, x, y):
        """Put the open list at `x`, `y` (screen px, top-left); a subclass may widen or shift it."""
        container.move(x, y)

    def hidePopup(self):
        self._unroll.stop()
        super().hidePopup()
        self._container.clearMask()
        # Qt also calls hidePopup on style changes: only a genuinely open popup counts.
        if self._open:
            self._open = False
            if Dropdown.open_one is self:
                Dropdown.open_one = None
            self.popupClosed.emit()

    def move_highlight(self, delta):
        """Keyboard: move the open list's highlight by `delta` (clamped); `hovered` fires, as
        for the mouse."""
        view = self.view()
        row = view.currentIndex().row()
        row = self.currentIndex() if row < 0 else row
        row = max(0, min(self.count() - 1, row + delta))
        index = self.model().index(row, 0)
        view.setCurrentIndex(index)
        view.scrollTo(index)
        self.hovered.emit(self.itemText(row))

    def pick_highlighted(self):
        """Keyboard: choose the open list's highlighted row, exactly as clicking it would."""
        row = self.view().currentIndex().row()
        self.hidePopup()
        if row >= 0:
            self.setCurrentIndex(row)
            self._on_activated(row)

    def _unroll_step(self, t):
        c = self._container
        c.setWindowOpacity(0.25 + 0.75 * t)
        if t >= 1.0:
            c.clearMask()
        else:
            self._set_unroll_mask(max(1, round(c.height() * t)))

    def _set_unroll_mask(self, shown):
        """Clip the popup to `shown` px, anchored to the edge nearest the button."""
        c = self._container
        top = c.height() - shown if self._up else 0
        c.setMask(QRegion(0, top, c.width(), shown))

    # --- painting -------------------------------------------------------------
    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def sizeHint(self):
        return QSize(self.width(), px(28))

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
        # Arrow section: one shade darker, and darker again on hover.
        p.save()
        p.setClipRect(QRectF(r.right() - self._ARROW_W, r.top(), self._ARROW_W, r.height()))
        hover = self._hover and enabled
        p.fillPath(body, th.color("secondary_pressed" if hover else "secondary_hover"))
        p.restore()

        text_color = th.color("secondary_text" if enabled else "secondary_disabled_text")
        p.setPen(text_color)
        p.setFont(ui_font(13))
        text_rect = r.adjusted(8, 0, -self._ARROW_W - 4, 0)
        value = self.value()
        elided = p.fontMetrics().elidedText(value, Qt.ElideRight, int(text_rect.width()))
        # The NO_OPTION placeholder is centred; real text is left-aligned.
        h_align = Qt.AlignHCenter if value == NO_OPTION else Qt.AlignLeft
        p.drawText(text_rect, Qt.AlignVCenter | h_align, elided)

        cx, cy = r.right() - self._ARROW_W / 2, r.center().y() + 1
        pen = QPen(text_color, 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawPolyline([QPointF(cx - 4, cy - 2), QPointF(cx, cy + 2), QPointF(cx + 4, cy - 2)])
