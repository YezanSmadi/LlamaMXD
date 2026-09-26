# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Small themed controls, each painting itself from `ui.theme.theme`.

User-action signals (`Dropdown.picked`, `CheckBox.clicked`, `Switch.clicked`,
`SegmentedButton.changed`) fire only on user changes, never when code sets a value, so a tab
can write a settings dict into the form without tripping its own handlers."""
import math
import os
import re
import time

from PySide6 import QtGui
from shiboken6 import isValid
from PySide6.QtCore import (
    QByteArray,
    QEasingCurve,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QAbstractTextDocumentLayout,
    QFont,
    QFontMetricsF,
    QIcon,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QRegion,
    QTextDocument,
    QTextOption,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionButton,
    QStyleOptionFrame,
    QStylePainter,
    QVBoxLayout,
    QWidget,
)

from ui import scale
from ui import theme as T
from ui.scale import px

NO_OPTION = "—"

_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets")
_SVG_CACHE = {}
_BLACK_STROKE_RE = re.compile(r'stroke(=")#000(?:000)?"|stroke(:\s*)#000(?:000)?(;?)')


def _icon_svg(name, color):
    """A cached `QSvgRenderer` for `assets/<name>` with its black strokes (attribute or CSS
    form) and `currentColor` fills recoloured to `color`."""
    key = (name, color)
    if key not in _SVG_CACHE:
        with open(os.path.join(_ASSETS, name), "r", encoding="utf-8") as fh:
            data = fh.read()
        data = _BLACK_STROKE_RE.sub(
            lambda m: (f'stroke="{color}"' if m.group(1) else f'stroke{m.group(2)}{color}{m.group(3)}'), data)
        data = data.replace('fill="currentColor"', f'fill="{color}"')
        # The search / sort icons are drawn in Illustrator's #231f20 rather than pure black.
        data = data.replace("#231f20", color)
        _SVG_CACHE[key] = QSvgRenderer(QByteArray(data.encode("utf-8")))
    return _SVG_CACHE[key]


def ui_font(size, bold=False, family=None):
    """A font at `size` reference pixels (Roboto unless `family`), for custom painters and for
    measuring text in reference pixels. A real widget's font goes through `set_font_px`."""
    f = QFont()
    f.setFamilies([family] if family else ["Roboto", "Segoe UI"])
    f.setPixelSize(size)
    f.setBold(bold)
    # Unhinted: hinted advances snap per size, so scaled text stuttered and a measured width
    # disagreed with the painted one.
    f.setHintingPreference(QFont.PreferNoHinting)
    return f


def _unhinted(widget):
    """Make `widget`'s font unhinted: hinted glyphs sit on whole pixels, which makes uneven
    gaps once painted through a scaled painter."""
    f = QFont(widget.font())
    f.setHintingPreference(QFont.PreferNoHinting)
    widget.setFont(f)


def set_font_px(widget, size, bold=False, family=None):
    """A font at `size` reference pixels for a real widget, re-applied on every scale change."""
    scale.bind(widget, lambda: widget.setFont(ui_font(scale.font_px(size), bold, family)))


class ScaledLabel(QLabel):
    """A label whose text is painted through the scaled painter (`scale.begin`). Qt snaps a
    widget font to whole pixel sizes, so stylesheet-sized text hopped between sizes during a
    drag. Its font is the reference font; paint and size hints multiply by the scale, while the
    stylesheet's box (padding, border) stays in real pixels."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _unhinted(self)
        scale.bind(self, self.updateGeometry, "hint")

    def _chrome(self):
        """(width, height) the stylesheet's padding + border add around the text."""
        self.ensurePolished()
        r, c = self.rect(), self.contentsRect()
        return r.width() - c.width(), r.height() - c.height()

    def _unwrapped_hint(self):
        """The real-pixel hint of an unwrapped label: the reference-font text times the scale,
        plus the stylesheet's box. Measured here because Qt folds the real-pixel `min-height`
        and `min-width` into its hint, which scaling would then double. The minimum height is
        applied afterwards."""
        cw, ch = self._chrome()
        f = scale.factor()
        fm = QFontMetricsF(self.font())
        if self._is_rich():
            doc = QTextDocument()
            doc.setDefaultFont(self.font())
            doc.setHtml(self.text())
            text_w, text_h = doc.idealWidth(), doc.size().height()
        else:
            lines = self.text().split("\n")
            text_w = max((fm.horizontalAdvance(line) for line in lines), default=0.0)
            text_h = fm.height() + fm.lineSpacing() * (len(lines) - 1)
        return QSize(math.ceil(text_w * f + cw), max(math.ceil(text_h * f + ch), self.minimumHeight()))

    def _ref_text_height(self, ref_width):
        """The text's height in reference pixels wrapped at `ref_width` (unwrapped: one line
        per newline), with the painter's font."""
        text = self.text()
        if self._is_rich():
            doc = QTextDocument()
            doc.setDefaultFont(self.font())
            doc.setHtml(text)
            if self.wordWrap():
                doc.setTextWidth(ref_width)
            return doc.size().height()
        fm = QFontMetricsF(self.font())
        if not self.wordWrap():
            return fm.height() + fm.lineSpacing() * text.count("\n")
        return fm.boundingRect(QRectF(0, 0, ref_width, 1e6), int(Qt.TextWordWrap), text).height()

    def _wrap_widths(self):
        """(ideal, narrowest) reference-pixel widths of a word-wrapped label, from the reference
        font alone: Qt's own mixes reference text with real padding, so it drifts with the
        scale, and its narrow minimum floors a top-level window's height."""
        fm = QFontMetricsF(self.font())
        if self._is_rich():
            doc = QTextDocument()
            doc.setHtml(self.text())
            text = doc.toPlainText()
        else:
            text = self.text()
        lines = text.split("\n")
        widest = max((fm.horizontalAdvance(line) for line in lines), default=0.0)
        narrow = max((fm.horizontalAdvance(word) for word in text.split()), default=0.0)
        area = sum(fm.horizontalAdvance(line) for line in lines) * fm.height()
        return min(widest, max(narrow, math.sqrt(area * 4))), narrow    # about 4:1 wide

    def sizeHint(self):
        if not self.wordWrap():
            return self._unwrapped_hint()
        cw, ch = self._chrome()
        f = scale.factor()
        ideal, _ = self._wrap_widths()
        return QSize(math.ceil(ideal * f + cw),
                     max(math.ceil(self._ref_text_height(ideal) * f + ch), self.minimumHeight()))

    def minimumSizeHint(self):
        if not self.wordWrap():
            return self._unwrapped_hint()
        cw, ch = self._chrome()
        f = scale.factor()
        _, narrow = self._wrap_widths()
        one_line = QFontMetricsF(self.font()).height()
        return QSize(math.ceil(narrow * f + cw), max(math.ceil(one_line * f + ch), self.minimumHeight()))

    def heightForWidth(self, width):
        """Wrapped text's height at a real `width` (wrapped at the matching reference width)."""
        cw, ch = self._chrome()
        f = scale.factor()
        return max(math.ceil(self._ref_text_height((width - cw) / f) * f + ch), self.minimumHeight())

    def _is_rich(self):
        fmt = self.textFormat()
        return fmt == Qt.RichText or (fmt == Qt.AutoText and QtGui.Qt.mightBeRichText(self.text()))

    def paintEvent(self, event):
        text = self.text()
        if not text or not self.pixmap().isNull() or self.movie() is not None:
            return super().paintEvent(event)   # nothing to re-route: a picture, or an empty label
        QFrame.paintEvent(self, event)         # the stylesheet's background / border only
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing)
        f = scale.factor()
        cr = self.contentsRect()
        rect = QRectF(cr.x() / f, cr.y() / f, cr.width() / f, cr.height() / f)
        scale.begin(p)
        p.setFont(self.font())
        p.setPen(self.palette().color(self.foregroundRole()))
        align = self.alignment()
        if not self._is_rich():
            p.drawText(rect, int(align) | (int(Qt.TextWordWrap) if self.wordWrap() else 0), text)
            return
        doc = QTextDocument()
        doc.setDefaultFont(self.font())
        option = QTextOption(align & Qt.AlignHorizontal_Mask)
        option.setWrapMode(QTextOption.WordWrap if self.wordWrap() else QTextOption.NoWrap)
        doc.setDefaultTextOption(option)
        doc.setHtml(text)
        doc.setTextWidth(rect.width())
        top = rect.top() + (rect.height() - doc.size().height()) * (
            1.0 if align & Qt.AlignBottom else 0.5 if align & Qt.AlignVCenter else 0.0)
        p.translate(rect.left(), top)
        ctx = QAbstractTextDocumentLayout.PaintContext()
        ctx.palette.setColor(QPalette.Text, self.palette().color(self.foregroundRole()))
        doc.documentLayout().draw(p, ctx)


class ScaledButton(QPushButton):
    """A push button whose caption is painted through the scaled painter (see `ScaledLabel`).
    The stylesheet still draws the box and gives the text colour per state."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _unhinted(self)
        scale.bind(self, self.updateGeometry, "hint")

    def sizeHint(self):
        # Measured from the text: Qt's hint folds in the real-pixel min-height and would scale
        # twice. The padding is real pixels; only the text scales.
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        contents = self.style().subElementRect(QStyle.SE_PushButtonContents, opt, self)
        fm = QFontMetricsF(self.font())
        f = scale.factor()
        return QSize(math.ceil(fm.horizontalAdvance(self.text()) * f) + self.width() - contents.width(),
                     max(self.minimumHeight(), math.ceil(fm.height() * f)))

    def paintEvent(self, event):
        p = QStylePainter(self)
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        text = opt.text
        opt.text = ""
        opt.icon = QIcon()
        p.drawControl(QStyle.CE_PushButton, opt)        # the box, without its caption
        if not text:
            return
        f = scale.factor()
        cr = self.style().subElementRect(QStyle.SE_PushButtonContents, opt, self)
        p.setRenderHint(QPainter.TextAntialiasing)
        scale.begin(p)
        p.setFont(self.font())
        p.setPen(self.palette().color(self.foregroundRole()))
        p.drawText(QRectF(cr.x() / f, cr.y() / f, cr.width() / f, cr.height() / f), int(Qt.AlignCenter), text)


class ScaledLineEdit(QLineEdit):
    """A line edit whose text, selection and caret are painted through the scaled painter (see
    `ScaledLabel`). QLineEdit paints through its own painter, so this takes over painting and
    mouse-to-character mapping (which must use the same metrics); keys, undo, clipboard,
    selection and signals stay Qt's."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _unhinted(self)
        self._scroll = 0.0        # reference pixels the text is scrolled left by
        self._anchor = 0          # where a press began, for drag-selecting
        self._blink_on = True
        self._blink = QTimer(self)
        self._blink.setInterval(530)
        self._blink.timeout.connect(self._toggle_blink)
        for signal in (self.cursorPositionChanged, self.textChanged, self.selectionChanged):
            signal.connect(self._activity)
        T.theme.changed.connect(self.update)
        scale.bind(self, self.updateGeometry, "hint")

    # -- geometry ----------------------------------------------------------
    def _contents(self):
        """The text area (border and padding excluded), real pixels."""
        self.ensurePolished()
        opt = QStyleOptionFrame()
        self.initStyleOption(opt)
        return self.style().subElementRect(QStyle.SE_LineEditContents, opt, self)

    def _content_ref(self):
        c, f = self._contents(), scale.factor()
        return QRectF(c.x() / f, c.y() / f, c.width() / f, c.height() / f)

    def _to_real(self, ref_w, ref_h):
        """A real size from reference text size: the text part scales, the stylesheet's box
        doesn't, and the minimum is applied last."""
        c = self._contents()
        f = scale.factor()
        return QSize(math.ceil(ref_w * f) + self.width() - c.width(),
                     max(math.ceil(ref_h * f) + self.height() - c.height(), self.minimumHeight()))

    def sizeHint(self):
        fm = QFontMetricsF(self.font())
        return self._to_real(fm.horizontalAdvance("x") * 17, fm.height())

    def minimumSizeHint(self):
        fm = QFontMetricsF(self.font())
        return self._to_real(fm.horizontalAdvance("x") * 4, fm.height())

    # -- painting ----------------------------------------------------------
    def _fit_scroll(self, fm, width, text):
        """Keep the caret in view, scrolling only as far as it needs."""
        total = fm.horizontalAdvance(text)
        if total <= width:
            self._scroll = 0.0
            return
        cx = fm.horizontalAdvance(text[:self.cursorPosition()])
        if cx - self._scroll > width:
            self._scroll = cx - width
        if cx - self._scroll < 0:
            self._scroll = cx
        self._scroll = max(0.0, min(self._scroll, total - width + 1))

    def paintEvent(self, event):
        p = QPainter(self)
        opt = QStyleOptionFrame()
        self.initStyleOption(opt)
        self.style().drawPrimitive(QStyle.PE_PanelLineEdit, opt, p, self)   # the stylesheet's box only
        f = scale.factor()
        area = self._content_ref()
        text = self.displayText()
        font = self.font()
        fm = QFontMetricsF(font)
        p.setRenderHint(QPainter.TextAntialiasing)
        scale.begin(p)
        p.setClipRect(area)
        p.setFont(font)
        pal = self.palette()
        self._fit_scroll(fm, area.width(), text)
        left = area.left() - self._scroll
        top = area.top() + (area.height() - fm.height()) / 2
        base = QPointF(left, top + fm.ascent())
        if not text:
            hint = self.placeholderText()
            if hint:
                p.setPen(pal.color(QPalette.PlaceholderText))
                p.drawText(base, hint)
        else:
            sel_from = self.selectionStart() if self.hasSelectedText() else -1
            if sel_from >= 0:
                sel_to = sel_from + len(self.selectedText())
                x1, x2 = fm.horizontalAdvance(text[:sel_from]), fm.horizontalAdvance(text[:sel_to])
                band = QRectF(left + x1, top, x2 - x1, fm.height())
                p.fillRect(band, pal.color(QPalette.Highlight))
            p.setPen(pal.color(QPalette.Text))
            p.drawText(base, text)
            if sel_from >= 0:
                p.save()
                p.setClipRect(band, Qt.IntersectClip)
                p.setPen(pal.color(QPalette.HighlightedText))
                p.drawText(base, text)
                p.restore()
        if self.hasFocus() and self._blink_on and not self.isReadOnly():
            caret_w = max(1, round(f)) / f                       # one or two real pixels
            cx = round((left + fm.horizontalAdvance(text[:self.cursorPosition()])) * f) / f
            p.fillRect(QRectF(cx, top, caret_w, fm.height()), pal.color(QPalette.Text))

    # -- caret blink -------------------------------------------------------
    def _toggle_blink(self):
        self._blink_on = not self._blink_on
        self.update()

    def _activity(self, *_):
        """Typing, moving or selecting shows the caret again and restarts its blink."""
        self._blink_on = True
        if self.hasFocus():
            self._blink.start()
        self.update()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._blink_on = True
        self._blink.start()
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._blink.stop()
        self.update()

    # -- mouse -------------------------------------------------------------
    def _pos_at(self, x):
        """The character boundary nearest to real-pixel `x`, by the same metrics the text is painted with."""
        text = self.displayText()
        fm = QFontMetricsF(self.font())
        target = x / scale.factor() - self._content_ref().left() + self._scroll
        last = 0.0
        for i in range(1, len(text) + 1):
            adv = fm.horizontalAdvance(text[:i])
            if adv >= target:
                return i if adv - target < target - last else i - 1
            last = adv
        return len(text)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        self.setFocus(Qt.MouseFocusReason)
        pos = self._pos_at(event.position().x())
        if event.modifiers() & Qt.ShiftModifier:
            self.setSelection(self._anchor, pos - self._anchor)
        else:
            self._anchor = pos
            self.setCursorPosition(pos)
        event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            pos = self._pos_at(event.position().x())
            self.setSelection(self._anchor, pos - self._anchor)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mouseDoubleClickEvent(event)
        pos = self._pos_at(event.position().x())
        for m in re.finditer(r"\w+", self.displayText()):
            if m.start() <= pos <= m.end():
                self._anchor = m.start()
                self.setSelection(m.start(), m.end() - m.start())
                return
        self._anchor = 0
        self.selectAll()


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
            _icon_svg(_SVG_ICON_KINDS[self._kind], color.name()).render(p, icon_rect)
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


class ClickableLabel(ScaledLabel):
    """A label that reports clicks (the HDRtoSDR caption toggles its switch)."""

    clicked = Signal()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.isEnabled():
            self.clicked.emit()


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


# --------------------------------------------------------------------------- #
#  MarqueeLabel
# --------------------------------------------------------------------------- #
_MARQUEE_SPEED = 40.0   # px / second
_MARQUEE_GAP = 48
_MARQUEE_HOLD = 1.5     # seconds still at the start of each loop


class MarqueeGroup:
    """One shared loop, clock and timer for several `MarqueeLabel`s. A label holds at rest once
    its own sweep finishes and all restart together after the slowest, so rows of different
    lengths stay in step. The clock is read once per tick and every member paints from it, so
    rows can't creep apart."""

    def __init__(self):
        self.t0 = self.now = time.perf_counter()
        self._members = []
        self._period = None      # cached `period()`; dropped when a member changes
        self._timer = None       # built on first use (needs a QApplication)

    def register(self, label):
        self._members.append(label)
        self._period = None

    def unregister(self, label):
        """Drop a label about to be destroyed, so `period()` never touches it."""
        if label in self._members:
            self._members.remove(label)
            self._period = None
            self.reset()
            self.sync()

    def reset(self):
        """Restart the shared loop from its resting hold."""
        self.t0 = self.now = time.perf_counter()

    def invalidate(self):
        """A member's text, width or scrolling state changed."""
        self._period = None

    def period(self):
        """The shared cycle: `_MARQUEE_HOLD` plus the longest sweep among scrolling members
        (cached; read by every member every frame)."""
        if self._period is None:
            sweeps = [m._sweep_seconds() for m in self._members if m._scrolling]
            self._period = _MARQUEE_HOLD + (max(sweeps) if sweeps else 0.0)
        return self._period

    def phase(self):
        """Seconds into the current cycle, as of the last tick."""
        return (self.now - self.t0) % self.period()

    def sync(self):
        """Runs the timer exactly while some member is scrolling."""
        if any(m._scrolling for m in self._members):
            if self._timer is None:
                self._timer = QTimer(QApplication.instance())
                self._timer.setTimerType(Qt.PreciseTimer)
                self._timer.timeout.connect(self._tick)
            if not self._timer.isActive():
                self.now = time.perf_counter()
                self._timer.start(16)
        elif self._timer is not None:
            self._timer.stop()

    def _tick(self):
        self.now = time.perf_counter()
        live = False
        for label in list(self._members):
            if not isValid(label):        # deleted underneath us (a destroyed row)
                self._members.remove(label)
                self._period = None
            elif label._scrolling:
                live = True
                label.update()
        if not live:
            self._timer.stop()


class MarqueeLabel(QWidget):
    """Single-line text that scrolls smoothly when it doesn't fit and sits still when it does,
    only while shown. `group` keeps several labels in step; a standalone label gets its own."""

    doubleClicked = Signal()

    def __init__(self, text="", pixel_size=11, color_key="text", bold=False, family=None,
                 parent=None, group=None):
        super().__init__(parent)
        self._text = text or ""
        self._color_key = color_key
        self._font = ui_font(pixel_size, bold=bold, family=family)
        scale.bounds(self, min_w=10)
        scale.fixed(self, h=math.ceil(QFontMetricsF(self._font).height()) + 4)
        self._scrolling = False
        self._group = group if group is not None else MarqueeGroup()
        self._group.register(self)
        T.theme.changed.connect(self.update)

    def setText(self, text):
        text = text or ""
        if text == self._text:
            return
        self._text = text
        self._group.reset()
        self._sync_scrolling()
        self.update()

    def text(self):
        return self._text

    def set_color_key(self, key):
        if key != self._color_key:
            self._color_key = key
            self.update()

    def _overflows(self):
        return QFontMetricsF(self._font).horizontalAdvance(self._text) > scale.ref_size(self)[0]

    def _sweep_seconds(self):
        """How long this label's text takes to scroll through once, excluding the hold."""
        fm = QFontMetricsF(self._font)
        span = fm.horizontalAdvance(self._text) + _MARQUEE_GAP
        return span / _MARQUEE_SPEED

    def _set_scrolling(self, scrolling):
        self._group.invalidate()
        if scrolling and not self._scrolling:
            # Starting to scroll now restarts the shared loop, rather than joining it mid-cycle.
            self._group.reset()
        self._scrolling = scrolling
        self._group.sync()

    def _sync_scrolling(self):
        self._set_scrolling(self.isVisible() and self._overflows())

    def showEvent(self, e):
        self._sync_scrolling()

    def hideEvent(self, e):
        self._set_scrolling(False)

    def resizeEvent(self, e):
        self._sync_scrolling()

    def mouseDoubleClickEvent(self, e):
        self.doubleClicked.emit()

    def paintEvent(self, _event):
        p = QPainter(self)
        scale.begin(p)
        p.setFont(self._font)
        p.setPen(T.theme.color(self._color_key) if self.isEnabled() else T.theme.color("label_disabled"))
        fm = QFontMetricsF(self._font)
        tw = fm.horizontalAdvance(self._text)
        rect = scale.ref_rect(self)
        if tw <= rect.width():
            p.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, self._text)
            return
        span = tw + _MARQUEE_GAP
        sweep = span / _MARQUEE_SPEED
        # The group's per-tick snapshot, so every label shows the same instant.
        cycle_t = self._group.phase()
        # Holds at rest before the sweep and after it ends (waiting for a slower groupmate);
        # travel pinned at `sweep` looks identical to 0.
        travel = max(0.0, min(cycle_t - _MARQUEE_HOLD, sweep)) * _MARQUEE_SPEED
        baseline = (rect.height() + fm.ascent() - fm.descent()) / 2
        p.drawText(QPointF(-travel, baseline), self._text)
        p.drawText(QPointF(-travel + span, baseline), self._text)
