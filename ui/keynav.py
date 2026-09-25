# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Keyboard navigation of the current tab: the "Select Next Option" / "Press Selected Option"
shortcuts, and the arrow / Enter keys inside an open dropdown.

Every clickable in the app is `Qt.NoFocus` (so a focused button can't swallow the Space keybind,
and there are no focus rings), so this doesn't use Qt's focus chain. It keeps its own "selected
option" and draws a ring around it (`_Ring`, an overlay on the window); text fields are the one
exception — they take real focus, since typing needs it. The order is reading order (rows top to
bottom, left to right within a row), recomputed on every press, so it always matches what is on
screen."""
from PySide6.QtCore import QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QApplication, QLineEdit, QScrollArea, QWidget
from shiboken6 import isValid

from ui import theme as T
from ui.scale import fpx, px
from ui.widgets.controls import Dropdown, SegmentedButton, _TimeField
from ui.widgets.panels import SubTabBar
from ui.widgets.tracklist import _TrackRow

_TEXT_STOPS = (QLineEdit, _TimeField)
_NATIVE_LIST_KEYS = (Qt.Key_Up, Qt.Key_Down, Qt.Key_Return, Qt.Key_Enter)


class _Stop:
    """One place the selection can rest: `target` (the widget the ring goes around), `rect` (in
    the target's coordinates), `act` (what Enter does, None for a text field) and `index`
    (which of the widget's own stops this is — a segmented button or tab bar has several)."""

    def __init__(self, widget, index, rect, act, target=None):
        self.widget, self.index, self.rect, self.act = widget, index, rect, act
        self.target = target or widget
        center = self.target.mapToGlobal(rect.center())
        self.cx, self.cy = center.x(), center.y()

    def same_as(self, other):
        return other is not None and self.widget is other.widget and self.index == other.index

    def is_text(self):
        return isinstance(self.widget, _TEXT_STOPS)


class _Ring(QWidget):
    """The selection ring: an outline drawn over whatever is selected, transparent to the mouse."""

    def __init__(self, window):
        super().__init__(window)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()
        T.theme.changed.connect(self.update)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        width = fpx(2)
        pen = QPen(T.theme.color("text"), width)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(width / 2, width / 2, -width / 2, -width / 2),
                          fpx(8), fpx(8))


class KeyNav:
    """The selected option on the current tab, and how to move it and press it."""

    def __init__(self, window):
        self.window = window
        self.ring = _Ring(window)
        self._stop = None
        # The target can move (scrolling, a relayout, a resize) or go away (a tab switch, a
        # rebuilt list), so the ring follows it by polling — cheap, and only while shown.
        self._timer = QTimer(window)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._sync)

    # ------------------------------------------------------------------ #
    #  Finding the stops
    # ------------------------------------------------------------------ #
    def _collect(self):
        """Every stop on the tab that is showing, in reading order."""
        tab = self.window.tabs[self.window.current_tab]
        stops = []
        for w in tab.findChildren(QWidget):
            if not (w.isVisible() and w.isEnabled()) or w.width() < 4 or w.height() < 4:
                continue
            if isinstance(w, (SubTabBar, SegmentedButton)):
                stops += [_Stop(w, i, rect, act) for i, (rect, act) in enumerate(w.nav_stops())]
            elif isinstance(w, Dropdown):
                stops.append(_Stop(w, 0, w.rect(), w.showPopup))
            elif isinstance(w, _TEXT_STOPS):
                stops.append(_Stop(w, 0, w.rect(), None))
            elif isinstance(w, QAbstractButton):
                if w.property("role") == "stepper":
                    continue        # a time field's ▲ / ▼ (mouse only): you type into the field instead
                row = w.parent()
                if isinstance(row, _TrackRow):
                    # A track row's own checkbox is transparent to the mouse; the row is what
                    # a click lands on, so it is what gets the ring.
                    stops.append(_Stop(w, 0, row.rect(), w.click, target=row))
                else:
                    stops.append(_Stop(w, 0, w.rect(), w.click))
        return self._reading_order(stops)

    @staticmethod
    def _reading_order(stops):
        """Rows top to bottom, then left to right inside a row: two stops are on one row when
        their centres are within a control's height of each other."""
        rows = []
        for stop in sorted(stops, key=lambda s: s.cy):
            if rows and abs(stop.cy - rows[-1][0]) <= px(10):
                rows[-1][1].append(stop)
            else:
                rows.append((stop.cy, [stop]))
        return [stop for _, row in rows for stop in sorted(row, key=lambda s: s.cx)]

    def _current_index(self, stops):
        """Where the selection is in `stops`: the ring's stop, else a text field that has focus
        (clicked into, or reached by a previous press), else None."""
        focus = QApplication.focusWidget()
        for i, stop in enumerate(stops):
            if stop.same_as(self._stop) or (self._stop is None and stop.widget is focus):
                return i
        return None

    # ------------------------------------------------------------------ #
    #  Moving and pressing
    # ------------------------------------------------------------------ #
    def step(self, direction):
        """Select the next (+1) or previous (-1) option — the first / last when none is selected
        yet, wrapping at the ends. True if there was anything to select."""
        stops = self._collect()
        if not stops:
            return False
        current = self._current_index(stops)
        if current is None:
            index = 0 if direction > 0 else len(stops) - 1
        else:
            index = (current + direction) % len(stops)
        self._select(stops[index])
        return True

    def activate(self):
        """Press the selected option. False (so the key falls through to Qt) when none is
        selected or it is a text field."""
        stop = self._stop
        if stop is None or stop.is_text() or not self._alive():
            return False
        stop.act()
        return True

    def dismiss(self):
        """Drop the selection (a click, a tab switch): the ring goes and nothing is selected."""
        self._stop = None
        self._timer.stop()
        self.ring.hide()

    def _select(self, stop):
        previous = QApplication.focusWidget()
        if isinstance(previous, _TEXT_STOPS) and previous is not stop.widget:
            previous.clearFocus()
        self._stop = stop
        self._scroll_into_view(stop)
        if stop.is_text():
            stop.widget.setFocus(Qt.TabFocusReason)     # real focus: typing needs it, and it draws its own
            self.ring.hide()
        else:
            self._place()
            self.ring.show()
            self.ring.raise_()
        self._timer.start()

    def _scroll_into_view(self, stop):
        area = stop.target.parentWidget()
        while area is not None and not isinstance(area, QScrollArea):
            area = area.parentWidget()
        if area is not None:
            area.ensureWidgetVisible(stop.target, 0, px(24))

    def _alive(self):
        stop = self._stop
        return (stop is not None and isValid(stop.widget) and isValid(stop.target)
                and stop.widget.isVisible() and stop.widget.isEnabled())

    def _place(self):
        stop = self._stop
        grow = px(3)
        origin = stop.target.mapTo(self.window, stop.rect.topLeft())
        self.ring.setGeometry(QRect(origin, stop.rect.size()).adjusted(-grow, -grow, grow, grow))

    def _sync(self):
        if not self._alive():
            self.dismiss()
        elif not self._stop.is_text():
            self._place()

    # ------------------------------------------------------------------ #
    #  An open dropdown
    # ------------------------------------------------------------------ #
    def dropdown_key(self, dropdown, event):
        """A key press while `dropdown`'s list is open. Its own shortcuts move through the list
        and pick from it; Qt's built-in handling of the same keys is swallowed, so switching a
        shortcut off (or moving it) really does turn it off. True if the press is consumed."""
        keys = self.window.keymap
        if keys.matches("dropdown_prev", event):
            dropdown.move_highlight(-1)
        elif keys.matches("dropdown_next", event):
            dropdown.move_highlight(1)
        elif keys.matches("activate", event):
            dropdown.pick_highlighted()
        else:
            return event.key() in _NATIVE_LIST_KEYS
        return True
