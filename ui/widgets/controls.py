"""Small themed controls, each painting itself from `ui.theme.theme`.

Every widget paints in one QPainter pass into Qt's backing store and Qt
presents the whole window at once, so a disabled control can simply *look*
disabled and nothing fills in piece by piece. Animations run on
`QVariantAnimation`, driven off one timer and repainted in step.

**User-action signals fire only on user changes**: `Dropdown.picked`,
`CheckBox.clicked`, `Switch.clicked`, `SegmentedButton.changed` never fire
when code sets a value. That's what lets the tabs write a settings dict into
the form without tripping their own handlers."""
import math
import time

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from ui import theme as T

NO_OPTION = "—"


def ui_font(px, bold=False, family=None):
    """A pixel-sized font — Roboto unless `family` is given."""
    f = QFont()
    f.setFamilies([family] if family else ["Roboto", "Segoe UI"])
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def field_label(text, role="field"):
    """The bold Arial caption that sits above a control."""
    label = QLabel(text)
    label.setProperty("role", role)
    return label


def labeled(label_text, widget, role="field", spacing=1, align=Qt.AlignLeft):
    """`label` stacked above `widget`. Returns `(box, label)` — the label so a
    tab can dim it in step with its control."""
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    label = field_label(label_text, role)
    lay.addWidget(label, 0, align)
    lay.addWidget(widget, 0, align)
    return box, label


def button_width_for(texts, padding=26, min_width=60):
    """The width that fits the widest of `texts` inside a themed button (the
    QPushButton stylesheet's own 10px-per-side padding, plus a little slack)
    — so a button never clips text a fixed guess didn't leave room for."""
    fm = QFontMetricsF(ui_font(13))
    widest = max((fm.horizontalAdvance(t) for t in texts), default=0)
    return max(min_width, math.ceil(widest + padding))


def button(text, role=None, width=None, height=None):
    """A stylesheet-driven push button (secondary unless `role` says otherwise).
    NoFocus, like every clickable here: no focus rings, and a focused button
    would swallow the global Space keybind."""
    btn = QPushButton(text)
    if role:
        btn.setProperty("role", role)
    if width:
        btn.setFixedWidth(width)
    if height:
        btn.setFixedHeight(height)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFocusPolicy(Qt.NoFocus)
    return btn


def restyle(widget):
    """Re-applies the stylesheet after a dynamic property change (e.g. a
    button's `role`)."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def set_enabled(widget, label, enabled):
    """Enables/disables a control and dims its caption to match, so a dead
    option never looks live."""
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
    """A ✕ drawn as two strokes — never at the mercy of a font's glyphs."""
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


class IconButton(QPushButton):
    """A stylesheet-backed button whose glyph is painted: "close" (✕),
    "up" (▲) or "down" (▼)."""

    def __init__(self, kind, role=None, width=None, height=None):
        super().__init__("")
        self._kind = kind
        if role:
            self.setProperty("role", role)
        if width:
            self.setFixedWidth(width)
        if height:
            self.setFixedHeight(height)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        if self.property("role") == "ghost":
            color = T.theme.color("text")
        else:
            color = T.theme.color("secondary_text" if self.isEnabled() else "secondary_disabled_text")
        if self._kind == "close":
            draw_cross(p, rect, color)
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


class ClickableLabel(QLabel):
    """A label that reports clicks (the HDRtoSDR caption toggles its switch)."""

    clicked = Signal()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.isEnabled():
            self.clicked.emit()


# --------------------------------------------------------------------------- #
#  Dropdown
# --------------------------------------------------------------------------- #
class Dropdown(QComboBox):
    """A secondary-filled dropdown with a darker arrow section. Opens
    straight down below the button, unrolls
    + fades in, and reports row hover through `hovered(str)` for live
    previews.

    `set(value)` does **not** require the value to be in the list — a value that isn't is shown as a display-only
    override (Passthru uses this to mirror a source's real bitrate/channels,
    which are rarely one of the offered options). `value()` reads it back.

    The unroll animates a *mask* on the popup window rather than its geometry,
    so nothing is resized or re-laid-out per frame — just clipped."""

    picked = Signal(str)
    hovered = Signal(str)
    popupClosed = Signal()

    _OPEN_MS = 150
    _GAP = 3
    _ARROW_W = 28.0

    def __init__(self, values=(), width=None, parent=None):
        super().__init__(parent)
        self._override = None
        self._hover = False
        self._open = False
        self.addItems(list(values) or [NO_OPTION])
        if width:
            self.setFixedWidth(width)
        self.setFixedHeight(28)
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
        """The width that fits the longest of `values`, so a dropdown never
        resizes when a longer option is picked."""
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
        """Replace the option list. No-op when unchanged; keeps the current
        pick when it's still legal, else snaps to the first entry. Never fires
        `picked` — the caller owns any value change it causes."""
        values = list(values) or [NO_OPTION]
        if values == self.values():
            return
        current = self.value()
        self.blockSignals(True)
        self.clear()
        self.addItems(values)
        self.blockSignals(False)
        self._override = None
        self.set(current if current in values else values[0])

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
        super().showPopup()
        self._open = True
        c = self._container
        anchor = self.mapToGlobal(self.rect().bottomLeft())
        c.move(anchor.x(), anchor.y() + self._GAP)
        c.setWindowOpacity(0.25)
        c.setMask(QRegion(0, 0, c.width(), 1))
        self._unroll.stop()
        self._unroll.start()

    def hidePopup(self):
        self._unroll.stop()
        super().hidePopup()
        self._container.clearMask()
        # Qt also calls hidePopup on style changes (e.g. a live theme switch),
        # so only a popup that was genuinely open counts as closing.
        if self._open:
            self._open = False
            self.popupClosed.emit()

    def _unroll_step(self, t):
        c = self._container
        c.setWindowOpacity(0.25 + 0.75 * t)
        if t >= 1.0:
            c.clearMask()
        else:
            c.setMask(QRegion(0, 0, c.width(), max(1, round(c.height() * t))))

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
        return QSize(self.width(), 28)

    def paintEvent(self, _event):
        th = T.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
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
        elided = p.fontMetrics().elidedText(self.value(), Qt.ElideRight, int(text_rect.width()))
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, elided)

        cx, cy = r.right() - self._ARROW_W / 2, r.center().y() + 1
        pen = QPen(text_color, 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawPolyline([QPointF(cx - 4, cy - 2), QPointF(cx, cy + 2), QPointF(cx + 4, cy - 2)])


# --------------------------------------------------------------------------- #
#  CheckBox
# --------------------------------------------------------------------------- #
class CheckBox(QAbstractButton):
    """A 24px rounded box, 3px border, filled + checkmark when on.
    `color_key` picks the fill ("secondary", or "stop" for the destructive
    Strip checkboxes). The fill fades rather than snapping, and disabled
    greys the *box* too, not just the label."""

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
        return QSize(math.ceil(w) + 1, 24)

    def minimumSizeHint(self):
        return self.sizeHint()

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
            p.drawText(QRectF(32, 0, self.width() - 32, 24), Qt.AlignVCenter, self.text())


# --------------------------------------------------------------------------- #
#  Switch
# --------------------------------------------------------------------------- #
class Switch(QAbstractButton):
    """The AnimatedSwitch: a pill track whose knob slides between off/on.
    Disabled greys the knob and track."""

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(42, 24)
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
    """A segmented selector whose selection pill *slides* between segments.
    `changed` fires on a user click only; `set` is silent."""

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
        self.setFixedSize(math.ceil(sum(self._widths)) + 4, 28)
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
        h = self._hit(e.position().x())
        if h != self._hover:
            self._hover = h
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def mousePressEvent(self, e):
        i = self._hit(e.position().x())
        if i >= 0 and i != self._index and self.isEnabled():
            self._from = self._pos
            self._index = i
            self._slide.stop()
            self._slide.start()
            self.changed.emit(self._options[i])

    def changeEvent(self, e):
        self.update()
        super().changeEvent(e)

    def paintEvent(self, _event):
        th = T.theme
        enabled = self.isEnabled()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(th.color("segment"))
        p.drawRoundedRect(QRectF(self.rect()), 6, 6)
        if enabled and 0 <= self._hover != self._index:
            hx, hw = self._x_of(self._hover)
            p.setBrush(th.color("menu_hover"))
            p.drawRoundedRect(QRectF(hx, 2, hw, self.height() - 4), 5, 5)
        x, w = self._x_of(self._pos)
        p.setBrush(th.color("secondary"))
        p.drawRoundedRect(QRectF(x, 2, w, self.height() - 4), 5, 5)
        p.setFont(self._font)
        edge = 2
        for i, (opt, sw) in enumerate(zip(self._options, self._widths)):
            near = max(0.0, 1.0 - abs(self._pos - i))
            if enabled:
                p.setPen(T.lerp(th.color("text"), th.color("secondary_text"), near))
            else:
                p.setPen(T.lerp(th.color("label_disabled"), th.color("secondary_disabled_text"), near))
            p.drawText(QRectF(edge, 0, sw, self.height()), Qt.AlignCenter, opt)
            edge += sw


# --------------------------------------------------------------------------- #
#  TimeSpinner
# --------------------------------------------------------------------------- #
class _TimeField(QWidget):
    """The HH:MM:SS field itself, fully self-painted. Internal state is a
    6-digit list and `cursor_pos` indexes straight into it — the single source
    of truth for the block cursor. Typing
    overwrites the digit under the cursor and advances; Backspace steps back
    then clears (typing in reverse); Delete clears in place. Minutes/seconds
    clamp to 59."""

    edited = Signal()

    _SEGMENT_POSITIONS = (0, 1, 3, 4, 6, 7)

    def __init__(self, parent=None, mute_when_zero=False):
        super().__init__(parent)
        self.digits = list("000000")
        self.cursor_pos = 5
        self._mute_when_zero = mute_when_zero
        self.setFixedSize(100, 30)
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
        x = (self.width() - total) / 2
        rects = []
        for ch in text:
            w = fm.horizontalAdvance(ch)
            rects.append(QRectF(x, 0, w, self.height()))
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
        x = e.position().x()
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
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        p.fillPath(path, th.color("entry"))
        p.setPen(QPen(th.color("entry_border"), 2))
        p.drawPath(path)

        enabled = self.isEnabled()
        # Muted like a placeholder while every digit's still 0 — a duration
        # that's never been touched (or was clicked back down to it) reads
        # as "not set" rather than "00:00:00, the number zero". Only applies
        # to fields opted into it (Clip Duration, not Start Time).
        muted = self._mute_when_zero and all(d == "0" for d in self.digits)
        rects = self._char_rects()
        p.setFont(self._font)
        fm = QFontMetricsF(self._font)
        block = self._SEGMENT_POSITIONS[self.cursor_pos] if (self.hasFocus() and enabled) else -1
        for i, ch in enumerate(self.text()):
            r = rects[i]
            if i == block:
                hl = QRectF(r.left(), (self.height() - fm.height()) / 2, r.width(), fm.height())
                p.fillRect(hl, th.color("secondary"))
                p.setPen(th.color("secondary_text"))
            elif not enabled:
                p.setPen(th.color("label_disabled"))
            else:
                p.setPen(th.color("label_disabled") if muted else th.color("text"))
            p.drawText(r, Qt.AlignCenter, ch)


class TimeSpinner(QWidget):
    """HH:MM:SS field + a stacked ▲/▼ stepper to its right with an
    accelerating auto-repeat (400ms → 30ms, ×0.85 per tick). `valueChanged`
    fires on **every** change — typing, stepping, `set_seconds` — so a live
    readout like the Overview rundown can follow as the user types."""

    valueChanged = Signal(int)

    def __init__(self, seconds=0, parent=None, mute_when_zero=False):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)
        self.field = _TimeField(mute_when_zero=mute_when_zero)
        self.field.edited.connect(lambda: self.valueChanged.emit(self.seconds()))
        lay.addWidget(self.field)

        stepper = QVBoxLayout()
        stepper.setSpacing(2)
        stepper.setContentsMargins(0, 1, 0, 1)
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


# --------------------------------------------------------------------------- #
#  MarqueeLabel
# --------------------------------------------------------------------------- #
_MARQUEE_SPEED = 40.0   # px / second
_MARQUEE_GAP = 48
_MARQUEE_HOLD = 1.5     # seconds still at the start of each loop


class MarqueeGroup:
    """Synchronizes several `MarqueeLabel`s sharing one loop (e.g.
    `SummaryPanel`'s Video/Audio/Length rows): without this, each label
    wraps back to its own start the moment *its own* text finishes
    sweeping, so three labels of different lengths drift in and out of
    phase with each other. A grouped label instead holds at its resting
    position once its own sweep finishes, and every member restarts
    together only once the slowest one has too."""

    def __init__(self):
        self.t0 = time.perf_counter()
        self._members = []

    def register(self, label):
        self._members.append(label)

    def reset(self):
        self.t0 = time.perf_counter()

    def period(self):
        """The shared cycle length: `_MARQUEE_HOLD` plus the longest sweep
        among members that actually need to scroll right now."""
        sweeps = [m._sweep_seconds() for m in self._members if m._overflows()]
        return _MARQUEE_HOLD + (max(sweeps) if sweeps else 0.0)


class MarqueeLabel(QWidget):
    """Single-line text that scrolls smoothly (sub-pixel, time-based) when it
    doesn't fit, and sits still when it does. The timer only runs while the
    widget is actually shown — a page hidden in a QStackedWidget gets a real
    hideEvent, so there's nothing to gate by hand.

    Pass `group` (a `MarqueeGroup`) to keep several labels' loops in step —
    see `MarqueeGroup`. Standalone labels (the default) just loop on their
    own, as before."""

    doubleClicked = Signal()

    def __init__(self, text="", pixel_size=11, color_key="text", bold=False, family=None,
                 parent=None, group=None):
        super().__init__(parent)
        self._text = text or ""
        self._color_key = color_key
        self._font = ui_font(pixel_size, bold=bold, family=family)
        self.setMinimumWidth(10)
        self.setFixedHeight(math.ceil(QFontMetricsF(self._font).height()) + 4)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self.update)
        self._t0 = time.perf_counter()
        self._group = group
        if group is not None:
            group.register(self)
        T.theme.changed.connect(self.update)

    def setText(self, text):
        text = text or ""
        if text == self._text:
            return
        self._text = text
        if self._group is not None:
            self._group.reset()
        else:
            self._t0 = time.perf_counter()
        self._sync_timer()
        self.update()

    def text(self):
        return self._text

    def set_color_key(self, key):
        if key != self._color_key:
            self._color_key = key
            self.update()

    def _overflows(self):
        return QFontMetricsF(self._font).horizontalAdvance(self._text) > self.width()

    def _sweep_seconds(self):
        """How long this label's own text takes to scroll through once —
        excludes the resting hold at the start."""
        fm = QFontMetricsF(self._font)
        span = fm.horizontalAdvance(self._text) + _MARQUEE_GAP
        return span / _MARQUEE_SPEED

    def _sync_timer(self):
        if self.isVisible() and self._overflows():
            if not self._timer.isActive():
                if self._group is None:
                    self._t0 = time.perf_counter()
                self._timer.start(16)
        else:
            self._timer.stop()

    def showEvent(self, e):
        self._sync_timer()

    def hideEvent(self, e):
        self._timer.stop()

    def resizeEvent(self, e):
        self._sync_timer()

    def mouseDoubleClickEvent(self, e):
        self.doubleClicked.emit()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setFont(self._font)
        p.setPen(T.theme.color(self._color_key) if self.isEnabled() else T.theme.color("label_disabled"))
        fm = QFontMetricsF(self._font)
        tw = fm.horizontalAdvance(self._text)
        rect = QRectF(self.rect())
        if tw <= rect.width():
            p.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, self._text)
            return
        span = tw + _MARQUEE_GAP
        sweep = span / _MARQUEE_SPEED
        if self._group is not None:
            t0, period = self._group.t0, self._group.period()
        else:
            t0, period = self._t0, sweep + _MARQUEE_HOLD
        cycle_t = (time.perf_counter() - t0) % period
        # Holds at the resting position both before the sweep starts (everyone
        # waits out `_MARQUEE_HOLD` together) and after this label's own sweep
        # finishes (waiting for a slower groupmate) — travel pinned at `sweep`
        # looks identical to 0 since the second drawn copy lands exactly at x=0.
        travel = max(0.0, min(cycle_t - _MARQUEE_HOLD, sweep)) * _MARQUEE_SPEED
        baseline = (rect.height() + fm.ascent() - fm.descent()) / 2
        p.drawText(QPointF(-travel, baseline), self._text)
        p.drawText(QPointF(-travel + span, baseline), self._text)
