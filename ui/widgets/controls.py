# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Small themed building blocks: the caption and button helpers, `IconButton`, `anim`, `draw_cross`.
The controls themselves live beside this module: `text` (scaled label / button / line edit),
`dropdown`, `toggles` (checkbox, switch, segmented button), `timespinner`, `marquee`.

User-action signals (`Dropdown.picked`, `CheckBox.clicked`, `Switch.clicked`,
`SegmentedButton.changed`) fire only on user changes, never when code sets a value, so a tab
can write a settings dict into the form without tripping its own handlers."""
import math

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from ui import scale
from ui import theme as T
from ui.widgets.svg import svg_renderer
from ui.widgets.text import ScaledButton, ScaledLabel, ui_font


def field_label(text, role="field"):
    """The bold Arial caption that sits above a control."""
    label = ScaledLabel(text)
    label.setProperty("role", role)
    return label


def labeled(label_text, widget, role="field", spacing=1, align=Qt.AlignLeft):
    """`label` stacked above `widget`. Returns `(box, label)` — the label so a
    tab can dim it in step with its control."""
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    scale.spacing(lay, spacing)
    label = field_label(label_text, role)
    lay.addWidget(label, 0, align)
    lay.addWidget(widget, 0, align)
    return box, label


def button_width_for(texts, padding=26, min_width=60):
    """The width (reference pixels) fitting the widest of `texts` in a themed button."""
    fm = QFontMetricsF(ui_font(13))
    widest = max((fm.horizontalAdvance(t) for t in texts), default=0)
    return max(min_width, math.ceil(widest + padding))


def button(text, role=None, width=None, height=None):
    """A stylesheet push button (secondary unless `role`). NoFocus, like every clickable: a
    focused button would swallow the Space keybind."""
    btn = ScaledButton(text)
    if role:
        btn.setProperty("role", role)
    scale.fixed(btn, width or None, height or None)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFocusPolicy(Qt.NoFocus)
    return btn


def restyle(widget):
    """Re-apply the stylesheet after a dynamic property change (e.g. `role`)."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def set_enabled(widget, label, enabled):
    """Enable/disable a control and dim its caption to match."""
    widget.setEnabled(bool(enabled))
    if label is not None:
        label.setEnabled(bool(enabled))


def anim(owner, duration, on_value, curve=QEasingCurve.OutCubic):
    """A reusable 0→1 QVariantAnimation calling `on_value(t)` each frame."""
    a = QVariantAnimation(owner)
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.setDuration(duration)
    a.setEasingCurve(curve)
    a.valueChanged.connect(on_value)
    return a


def draw_cross(p, rect, color, width=1.6):
    """A ✕ as two strokes (no font glyph). `rect` and `width` are design-space pixels."""
    c = rect.center()
    r = min(rect.width(), rect.height()) * 0.2
    pen = QPen(color, width)
    pen.setCapStyle(Qt.RoundCap)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(pen)
    p.drawLine(QPointF(c.x() - r, c.y() - r), QPointF(c.x() + r, c.y() + r))
    p.drawLine(QPointF(c.x() - r, c.y() + r), QPointF(c.x() + r, c.y() - r))
    p.restore()


_SVG_ICON_KINDS = {"select-multiple": "select-multiple.svg", "deselect-multiple": "deselect-multiple.svg",
                   "undo": "undo.svg", "redo": "redo.svg"}


# An icon's box as a share of the button's shorter side, where the default (72% compact, 56%
# otherwise) doesn't suit the art: undo/redo's arrow fills only ~16x8 of its 24-unit viewBox.
_ICON_FRACTION = {"undo": 1.0, "redo": 1.0}


class IconButton(QPushButton):
    """A stylesheet button with a painted glyph: "close" (✕), "up" (▲), "down" (▼), or an SVG
    asset ("select-multiple", "deselect-multiple", "undo", "redo") recoloured to its text colour.
    `role="compact"` is the shorter variant."""

    def __init__(self, kind, role=None, width=None, height=None):
        super().__init__("")
        self._kind = kind
        if role:
            self.setProperty("role", role)
        scale.fixed(self, width or None, height or None)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        scale.begin(p)
        rect = scale.ref_rect(self)
        if self.property("role") == "ghost":
            color = T.theme.color("text")
        else:
            color = T.theme.color("secondary_text" if self.isEnabled() else "secondary_disabled_text")
        if self._kind == "close":
            draw_cross(p, rect, color)
            return
        if self._kind in _SVG_ICON_KINDS:
            # A square box off the shorter side: `render(rect)` stretches to the rect.
            fraction = _ICON_FRACTION.get(self._kind, 0.72 if self.property("role") == "compact" else 0.56)
            side = min(rect.width(), rect.height()) * fraction
            icon_rect = QRectF(0, 0, side, side)
            icon_rect.moveCenter(rect.center())
            svg_renderer(_SVG_ICON_KINDS[self._kind], color.name(), "ink").render(p, icon_rect)
            return
        c = rect.center()
        half_w, half_h = 3.5, 2.2
        sign = -1 if self._kind == "up" else 1
        path = QPainterPath()
        path.moveTo(c.x() - half_w, c.y() - sign * half_h)
        path.lineTo(c.x() + half_w, c.y() - sign * half_h)
        path.lineTo(c.x(), c.y() + sign * half_h)
        path.closeSubpath()
        p.fillPath(path, color)
