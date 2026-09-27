# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""`MarqueeLabel`: single-line text that scrolls when it doesn't fit, and `MarqueeGroup`, which keeps
several in step."""
import math
import time

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetricsF, QPainter
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from ui import scale
from ui import theme as T
from ui.widgets.text import ui_font

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
