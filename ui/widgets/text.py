# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Text painted through the scaled painter, so it scales continuously: `ScaledLabel`,
`ScaledButton`, `ScaledLineEdit`, `ClickableLabel`, and the reference-pixel fonts they use."""
import math
import re

from PySide6 import QtGui
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAbstractTextDocumentLayout,
    QFont,
    QFontMetricsF,
    QIcon,
    QPainter,
    QPalette,
    QTextDocument,
    QTextOption,
)
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyle,
    QStyleOptionButton,
    QStyleOptionFrame,
    QStylePainter,
)

from ui import scale
from ui import theme as T


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


class ClickableLabel(ScaledLabel):
    """A label that reports clicks (the HDRtoSDR caption toggles its switch)."""

    clicked = Signal()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.isEnabled():
            self.clicked.emit()
