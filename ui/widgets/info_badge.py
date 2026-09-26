# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""The preview's info badge (painted from info.svg) and the tooltip it opens."""
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter

from ui import scale
from ui import theme as T
from ui.scale import px
from ui.widgets.svg import svg_renderer
from ui.widgets.text import ScaledLabel


def _paint_info_badge(painter, rect):
    """The info badge from `assets/info.svg`, a disc with the "i" cut out as a hole: a circle in
    the glyph colour first, then the SVG recoloured to the disc colour on top, so the glyph shows
    through the hole. Dark disc / white glyph in dark mode, the reverse in light. The backdrop
    circle is 80% size so its edge can't peek out past the disc's."""
    light = T.theme.resolved_mode() == "Light"
    disc_color = "#FFFFFF" if light else "#2B2B2B"
    glyph_color = "#2B2B2B" if light else "#FFFFFF"
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(glyph_color))
    inset = rect.width() * 0.1
    painter.drawEllipse(rect.adjusted(inset, inset, -inset, -inset))
    svg_renderer("info.svg", disc_color).render(painter, rect)
    painter.restore()


def _paint_info_badge_faded(painter, rect, alpha, dpr=1.0):
    """`_paint_info_badge` faded as one flattened image: fading the two layers separately lets
    the glyph colour bleed through the whole disc."""
    w, h = max(1, round(rect.width() * dpr)), max(1, round(rect.height() * dpr))
    buf = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    buf.fill(Qt.transparent)
    buf.setDevicePixelRatio(dpr)
    bp = QPainter(buf)
    _paint_info_badge(bp, QRectF(0, 0, rect.width(), rect.height()))
    bp.end()
    painter.save()
    painter.setOpacity(alpha)
    painter.drawImage(rect.topLeft(), buf)
    painter.restore()


class _InfoTooltip(ScaledLabel):
    """The info badge's tooltip: dark body, bordered in `subtab_active`. A real window that
    takes the mouse, so the pointer can move onto it and keep it up (`entered` / `left`); the
    carousel decides when to hide it."""

    entered = Signal()
    left = Signal()

    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setTextFormat(Qt.PlainText)
        self._restyle()
        T.theme.changed.connect(self._restyle)
        scale.changed.connect(self._restyle)

    def enterEvent(self, e):
        self.entered.emit()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.left.emit()
        super().leaveEvent(e)

    def _restyle(self):
        # Runs on every live-resize step: skip setStyleSheet when the text is unchanged.
        css = (
            f"QLabel {{ background: {T.theme.hex('tooltip_bg')}; color: white;"
            f" border: {px(1)}px solid {T.theme.hex('subtab_active')}; padding: {px(8)}px {px(10)}px;"
            f" font-family: Arial; font-size: 13px; }}"
        )
        if css != getattr(self, "_last_css", None):
            self._last_css = css
            self.setStyleSheet(css)
