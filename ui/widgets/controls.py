# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
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
    """A cached, recolored `QSvgRenderer` for `assets/<name>` — every literal
    black stroke swapped for `color` (a hex string) before parsing, the same
    "recolor by string replace" trick `carousel._svg_renderer` uses for
    `fill="currentColor"`. Covers both forms a stroke-drawn icon actually
    ships in: an inline `stroke="#000000"` attribute (select-multiple.svg)
    and a `stroke: #000;` CSS property inside a `<style>` block
    (deselect-multiple.svg) — `QSvgRenderer` honors both, so the same
    recolor has to reach whichever one a given asset uses."""
    key = (name, color)
    if key not in _SVG_CACHE:
        with open(os.path.join(_ASSETS, name), "r", encoding="utf-8") as fh:
            data = fh.read()
        data = _BLACK_STROKE_RE.sub(
            lambda m: (f'stroke="{color}"' if m.group(1) else f'stroke{m.group(2)}{color}{m.group(3)}'), data)
        data = data.replace('fill="currentColor"', f'fill="{color}"')
        _SVG_CACHE[key] = QSvgRenderer(QByteArray(data.encode("utf-8")))
    return _SVG_CACHE[key]


def ui_font(size, bold=False, family=None):
    """A font at `size` *reference* pixels — Roboto unless `family` is given.
    For custom painters (which paint in design space, so the painter scales
    the glyphs) and for measuring text in reference pixels; a real widget's
    font goes through `set_font_px`."""
    f = QFont()
    f.setFamilies([family] if family else ["Roboto", "Segoe UI"])
    f.setPixelSize(size)
    f.setBold(bold)
    # Unhinted, so glyph advances are linear in the size: hinted ones snap per
    # size (a 40-character line measures 227 / 236 / 262px at 12 / 13 / 14px,
    # not 224 / 242 / 261), which made scaled text stutter and made a measured
    # width disagree with the painted one.
    f.setHintingPreference(QFont.PreferNoHinting)
    return f


def _unhinted(widget):
    """Make `widget`'s font unhinted whatever the app font is: hinted glyphs are
    placed on whole pixels, so text painted through a scaled painter comes out
    with uneven letter and word gaps (0.4px spread against 0.07px unhinted),
    and its measured width stops matching its painted width."""
    f = QFont(widget.font())
    f.setHintingPreference(QFont.PreferNoHinting)
    widget.setFont(f)


def set_font_px(widget, size, bold=False, family=None):
    """Give a real (stylesheet-laid-out) widget a font at `size` reference
    pixels, re-applied whenever the scale changes."""
    scale.bind(widget, lambda: widget.setFont(ui_font(scale.font_px(size), bold, family)))


class ScaledLabel(QLabel):
    """A label whose text is painted through the scale-transformed painter
    (`scale.begin`) instead of Qt's own text path.

    Qt snaps a widget font to a whole pixel size — whatever the family,
    engine or hinting — so a stylesheet-sized label hops between 12, 13, 14px
    as the window is dragged, and a sentence's width jumps by 10-35px at each
    hop (measured: a word's position wanders 5-6px rms, 14-19px worst, against
    0.3px rms for text drawn through a scaled painter, which every custom
    widget here already does). This label's font is therefore the *reference*
    font — the stylesheet gives it reference pixels, not `font_px` — and Qt's
    own metrics are at reference size; paint and size hints multiply by the
    scale. The stylesheet's box (padding, border, background) is real pixels
    and is left exactly as Qt lays it out, which is why hints are converted as
    "text part x scale + chrome" rather than scaled whole."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _unhinted(self)
        # A scale change moves the hint without touching the label's own state.
        scale.bind(self, self.updateGeometry, "hint")

    def _chrome(self):
        """(width, height) the stylesheet's padding + border add around the text."""
        self.ensurePolished()
        r, c = self.rect(), self.contentsRect()
        return r.width() - c.width(), r.height() - c.height()

    def _unwrapped_hint(self):
        """The real-pixel size hint of an unwrapped label: the text measured with
        the reference font (what the painter draws with) times the scale, plus
        the stylesheet's box, which is already real pixels. It is measured here
        rather than taken from Qt because Qt folds the real-pixel `min-height`
        and `min-width` (a fixed-width label's *fixed width*) into its hint —
        scaling that whole doubled them (a 26px caption box came out 104px at
        2x, a fixed 872px label reported 1744) — and every consumer of the hint
        then sat at the wrong size, invisibly at 1.0. The minimum height is
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
        """The text's height in reference pixels when wrapped at `ref_width`
        (unwrapped labels: one line per newline), from the same font the
        painter draws with."""
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
        """(ideal, narrowest) text widths, in reference pixels, of a
        word-wrapped label. Qt picks a wrapped label's ideal width by aspect
        ratio, but does it with reference-size text and real-pixel padding
        mixed together, so its answer drifts with the scale (a 132px-wide
        tooltip at 1x came out 220 at 1.9x — proportionally it is 250) — and
        its minimum hint is the tall, narrowest wrapping, which a top-level
        window enforces as a floor on its height. Both are computed here from
        the reference font alone, so they scale exactly."""
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
        """Wrapped text's height at a real `width`: Qt wraps at the reference
        width the real one corresponds to, and the result scales back up."""
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
    """A stylesheet-backed push button whose text is painted through the
    scale-transformed painter, for the same reason as `ScaledLabel`: Qt snaps a
    widget font to a whole pixel size, so button captions hopped between sizes
    during a resize. The stylesheet still draws the box (fill, radius, hover,
    pressed) and supplies the text colour per state; only the text moves."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _unhinted(self)
        scale.bind(self, self.updateGeometry, "hint")

    def sizeHint(self):
        # Measured from the text, not taken from Qt: Qt folds the real-pixel
        # `min-height` (and a fixed width) into its hint, so scaling that whole
        # scaled them twice (see `ScaledLabel._unwrapped_hint`). The stylesheet's
        # padding is real pixels — the width of the box around the contents
        # rect the text is painted into — and only the text scales.
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
    """A line edit whose text, selection and caret are painted through the
    scale-transformed painter, for the same reason as `ScaledLabel`: Qt snaps a
    widget font to a whole pixel size, so an entry's text hopped between sizes
    while the window was dragged. `QLineEdit` paints itself through a painter it
    opens internally, so nothing can be routed through it — this takes over the
    two things that touch the font and leaves the rest to Qt: **painting** (the
    stylesheet still draws the box, the focus border and the disabled state;
    text, placeholder, selection and caret are drawn here from the reference
    font) and **mouse-to-character mapping** (press, drag, double-click), which
    has to use the same metrics as the painting or a click lands on the wrong
    letter. Keys, undo, the clipboard, the selection model and every signal are
    Qt's own."""

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
        """Qt's size hint folds the stylesheet's real-pixel `min-height` in, so
        it can't be scaled whole (see `ScaledLabel._unwrapped_hint`): the text part
        scales, the box around it doesn't, and the minimum is applied last."""
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
    """The width (reference pixels) that fits the widest of `texts` inside a themed button (the
    QPushButton stylesheet's own 10px-per-side padding, plus a little slack)
    — so a button never clips text a fixed guess didn't leave room for."""
    fm = QFontMetricsF(ui_font(13))
    widest = max((fm.horizontalAdvance(t) for t in texts), default=0)
    return max(min_width, math.ceil(widest + padding))


def button(text, role=None, width=None, height=None):
    """A stylesheet-driven push button (secondary unless `role` says otherwise).
    NoFocus, like every clickable here: no focus rings, and a focused button
    would swallow the global Space keybind."""
    btn = ScaledButton(text)
    if role:
        btn.setProperty("role", role)
    scale.fixed(btn, width or None, height or None)
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
    """A ✕ drawn as two strokes — never at the mercy of a font's glyphs.
    `rect` and `width` are in the caller's (design-space) pixels."""
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


# How much of the button's shorter side an icon's square box takes, where the default
# (72% compact / 56% otherwise) doesn't suit the artwork: undo/redo's arrow only fills
# ~16x8 of its 24-unit viewBox, so it needs a box larger than the button to read.
_ICON_FRACTION = {"undo": 1.0, "redo": 1.0}


class IconButton(QPushButton):
    """A stylesheet-backed button whose glyph is painted: "close" (✕),
    "up" (▲), "down" (▼), or an svg asset ("select-multiple" /
    "deselect-multiple" / "undo" / "redo", recolored to match the button's own
    text color via `_icon_svg` rather than shipped pre-tinted). `role="compact"`
    is a shorter button (the stylesheet's own 28px minimum would otherwise
    override any fixed height) whose glyph fills more of it."""

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
            # Square and centered, sized off the shorter side only — the
            # button itself is usually a wide rectangle, and `render(rect)`
            # stretches a square-viewBox svg to fill whatever rect it's
            # given rather than preserving its aspect ratio, so a plain
            # inset on all four sides of a wide `rect` squashed the icon.
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
    """A secondary-filled dropdown with a darker arrow section. Opens
    straight down below the button (or straight up, when the list wouldn't fit
    below and there's more room above), unrolls + fades in, and reports row hover through `hovered(str)` for live
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
        """The width (reference pixels) that fits the longest of `values`, so
        a dropdown never resizes when a longer option is picked."""
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
        """Replace the option list. No-op when unchanged *and* nothing is being
        shown that isn't in it; keeps the current pick when it's still legal,
        else snaps to the first entry. Never fires `picked` — the caller owns
        any value change it causes.

        A display override (`set` with a value outside the list — the `—` a
        tab shows before a file is imported, or a Passthru mirror) is not a
        legal pick, so an unchanged list no longer leaves it in place: it used
        to, and Resolution kept showing `—` after a 2160p+ source was imported
        (its list only changes for shorter ones), as FPS did for 120fps+."""
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
        # Drops down unless the list would run off the screen (a tall list near the
        # bottom, most obviously in fullscreen) — then it opens upward if that has
        # more room, and rolls out from the button's edge either way.
        self._up = c.height() > room_below and room_above > room_below
        if self._up:
            y = max(area.top(), above_y - gap - c.height())
        else:
            y = below.y() + gap
        c.move(below.x(), y)
        c.setWindowOpacity(0.25)
        self._set_unroll_mask(1)
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
            if Dropdown.open_one is self:
                Dropdown.open_one = None
            self.popupClosed.emit()

    def move_highlight(self, delta):
        """Keyboard: move the open list's highlighted row by `delta` (clamped at the ends), as
        hovering it would — `hovered` fires, so Settings' theme preview follows the arrow keys."""
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
        # The NO_OPTION placeholder ("—") reads as a centred "nothing here"
        # mark rather than left-aligned like it's the start of real text.
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
        return QSize(px(math.ceil(w) + 1), px(24))

    def minimumSizeHint(self):
        return self.sizeHint()

    def set_hover(self, hover):
        """Drives the hover shade from outside — a caption-less checkbox whose
        row (e.g. `TrackListBox`'s) is what the pointer is really over."""
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
    """The AnimatedSwitch: a pill track whose knob slides between off/on.
    Disabled greys the knob and track."""

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
        """Slide to segment `i` and report it (a user choice, from a click or the keyboard)."""
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
        # Muted like a placeholder while every digit's still 0 — a time
        # that's never been touched (or was clicked back down to it) reads
        # as "not set" rather than "00:00:00, the number zero". Only applies
        # to fields opted into it (both trim fields: Start Time and Clip Duration).
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
    """HH:MM:SS field + a stacked ▲/▼ stepper to its right with an
    accelerating auto-repeat (400ms → 30ms, ×0.85 per tick). `valueChanged`
    fires on **every** change — typing, stepping, `set_seconds` — so a live
    readout like the Overview rundown can follow as the user types."""

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
    """One shared loop and clock for several `MarqueeLabel`s (e.g.
    `SummaryPanel`'s Video/Audio/Length rows, a track box's rows). Without it
    each label wrapped back to its own start the moment *its own* text
    finished sweeping, so labels of different lengths drifted in and out of
    phase; in the group a label instead holds at its resting position once its
    own sweep finishes, and every member restarts together only once the
    slowest one has too.

    **The group also owns the one timer, and reads the clock once per tick**
    (`now`) — every label paints from that snapshot, and the labels are all
    `update()`d in the same tick so Qt repaints them in one pass. Each label
    used to run its own 16ms timer and read `time.perf_counter()` at its own
    paint, so two rows that started together were painted a tick or a few
    milliseconds apart and visibly crept relative to each other (0.04px per
    ms at the marquee's speed, up to 0.7px for a late tick)."""

    def __init__(self):
        self.t0 = self.now = time.perf_counter()
        self._members = []
        self._period = None      # cached `period()`; dropped when a member changes
        self._timer = None       # built on first use (needs a QApplication)

    def register(self, label):
        self._members.append(label)
        self._period = None

    def unregister(self, label):
        """Drops a label that's about to be destroyed (a removed track row),
        so `period()` never touches a deleted widget."""
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
        """The shared cycle length: `_MARQUEE_HOLD` plus the longest sweep
        among members that are actually scrolling right now (cached — it is
        read by every member on every frame)."""
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
    """Single-line text that scrolls smoothly (sub-pixel, time-based) when it
    doesn't fit, and sits still when it does. It only animates while actually
    shown — a page hidden in a QStackedWidget gets a real hideEvent, so
    there's nothing to gate by hand.

    Pass `group` (a `MarqueeGroup`) to keep several labels' loops in step —
    see `MarqueeGroup`. Standalone labels (the default) get a group of their
    own, so there is one code path: a group of one loops exactly as a lone
    label always did."""

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
        """How long this label's own text takes to scroll through once —
        excludes the resting hold at the start."""
        fm = QFontMetricsF(self._font)
        span = fm.horizontalAdvance(self._text) + _MARQUEE_GAP
        return span / _MARQUEE_SPEED

    def _set_scrolling(self, scrolling):
        self._group.invalidate()
        if scrolling and not self._scrolling:
            # A label that starts scrolling *now* (imported after its group
            # was already looping, or just shown) restarts the shared loop
            # instead of landing at some arbitrary phase of it — which could
            # be past its own sweep, leaving it parked until the next wrap.
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
        # The group's per-tick snapshot, not the clock: every label painted in
        # this frame must show the same instant (see MarqueeGroup).
        cycle_t = self._group.phase()
        # Holds at the resting position both before the sweep starts (everyone
        # waits out `_MARQUEE_HOLD` together) and after this label's own sweep
        # finishes (waiting for a slower groupmate) — travel pinned at `sweep`
        # looks identical to 0 since the second drawn copy lands exactly at x=0.
        travel = max(0.0, min(cycle_t - _MARQUEE_HOLD, sweep)) * _MARQUEE_SPEED
        baseline = (rect.height() + fm.ascent() - fm.descent()) / 2
        p.drawText(QPointF(-travel, baseline), self._text)
        p.drawText(QPointF(-travel + span, baseline), self._text)
