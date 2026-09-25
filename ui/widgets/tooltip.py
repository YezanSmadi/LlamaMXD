# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""A themed hover tooltip for option controls, attached with `tip(widget, text)`.

Mirrors `carousel._InfoTooltip`'s look (dark body, primary border) but is
shared and driven by real QWidget Enter/Leave events rather than a manual
`mouseMoveEvent` hit-test, since every caller here is an actual widget
(Dropdown, CheckBox, Switch, SegmentedButton, QSlider, ...). Installed as an
event filter, so it never touches a control's own hover/paint logic."""
import time

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QCursor

from ui import scale
from ui import theme as T
from ui.scale import px
from ui.widgets.controls import ScaledLabel

TIP_DELAY_MS = 400       # how long the cursor must sit still over a widget before its tip shows
_DELAY_MS = TIP_DELAY_MS
_POLL_MS = 30            # how often the cursor is sampled while a tip is pending
_STILL_TOLERANCE = 1     # px (Manhattan) of drift that still counts as "not moving"
_MAX_WIDTH = 280
_FADE_MS = 120


class _Tooltip(ScaledLabel):
    """The popup itself — one shared instance for the whole app. Fades in
    (soft but quick) on every show; hides instantly, no fade out."""

    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setTextFormat(Qt.PlainText)
        self.setWordWrap(True)
        scale.bounds(self, max_w=_MAX_WIDTH)
        self._fade = QVariantAnimation(self)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setDuration(_FADE_MS)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.valueChanged.connect(self.setWindowOpacity)
        self._restyle()
        T.theme.changed.connect(self._restyle)
        scale.changed.connect(self._restyle)

    def _restyle(self):
        # Connected to `scale.changed` (this manager's tooltip is one shared,
        # always-alive widget), which fires on every live-resize step
        # regardless of which tab is showing: skip the setStyleSheet call
        # when the text it would set hasn't actually changed.
        css = (
            f"QLabel {{ background: {T.theme.hex('tooltip_bg')}; color: white;"
            f" border: {px(1)}px solid {T.theme.hex('primary')}; border-radius: {px(4)}px;"
            f" padding: {px(6)}px {px(9)}px; font-family: Arial; font-size: 12px; }}"
        )
        if css != getattr(self, "_last_css", None):
            self._last_css = css
            self.setStyleSheet(css)

    def fade_in(self):
        self.setWindowOpacity(0.0)
        self._fade.stop()
        self._fade.start()


class _TooltipManager(QObject):
    """Installed as an event filter on every registered widget: shows the
    shared popup once the cursor has hovered over a widget *and stopped* for
    `_DELAY_MS`, hides it on leave / click / disable.

    "Stopped" is judged by sampling `QCursor.pos()` every `_POLL_MS` rather than
    by watching mouse-move events: a registered widget only receives those with
    mouse tracking on, and one that is a container (the track box) never sees
    moves over its children at all. Any move of more than `_STILL_TOLERANCE`
    pixels restarts the wait; once the tip is up, moving within the widget does
    not hide it (leaving, clicking or disabling still does).

    `hold(True)` suspends every tooltip (hiding the one showing) until
    `hold(False)`: a drag that starts on a *child* of a registered widget never
    sends that widget a press, so the press-hides rule below doesn't cover it."""

    def __init__(self):
        super().__init__()
        self._held = False
        self._popup = None
        self._timer = QTimer()      # the sampling loop: runs only while a tip is pending
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._tick)
        self._pending = None
        self._anchor = None         # where the cursor last came to rest
        self._still_since = 0.0     # when it got there (time.monotonic)

    def _popup_widget(self):
        if self._popup is None:
            self._popup = _Tooltip()
        return self._popup

    def register(self, widget, text):
        if not widget.property("_has_tooltip"):
            widget.setProperty("_has_tooltip", True)
            widget.installEventFilter(self)
            self._sync_cursor(widget)
        widget.setProperty("_tooltip_text", text)

    def eventFilter(self, obj, event):
        et = event.type()
        if et == QEvent.Enter:
            self._pending = obj
            if not self._held:
                self._arm()
        elif et in (QEvent.Leave, QEvent.MouseButtonPress, QEvent.Hide):
            self._timer.stop()
            self._pending = None
            self._hide()
        elif et == QEvent.EnabledChange:
            # Tooltips still work greyed out (below), but a disabled control
            # must never still look clickable -- swap the pointing-hand
            # cursor for a plain arrow while it's disabled, restoring
            # whatever cursor it actually had the moment it re-enables.
            self._sync_cursor(obj)
        return False

    def _arm(self):
        """Starts waiting for the cursor to keep still, from where it is now."""
        self._anchor = QCursor.pos()
        self._still_since = time.monotonic()
        self._timer.start()

    def _tick(self):
        """One sample: a move restarts the wait, enough stillness shows the tip."""
        pos, now = QCursor.pos(), time.monotonic()
        if (pos - self._anchor).manhattanLength() > _STILL_TOLERANCE:
            self._anchor, self._still_since = pos, now
        elif now - self._still_since >= _DELAY_MS / 1000:
            self._timer.stop()
            self._show()

    def _sync_cursor(self, widget):
        if not widget.isEnabled():
            if widget.cursor().shape() != Qt.ArrowCursor:
                widget.setProperty("_tooltip_saved_cursor", widget.cursor())
                widget.setCursor(Qt.ArrowCursor)
        else:
            saved = widget.property("_tooltip_saved_cursor")
            if saved is not None:
                widget.setCursor(saved)
                widget.setProperty("_tooltip_saved_cursor", None)

    def hold(self, held):
        """Suspends (True) or resumes (False) the tooltips. Suspending hides the
        popup and cancels the pending one; resuming re-arms the usual hover delay
        if the cursor is still over the widget last hovered, so the tip comes back
        after a pause rather than the instant a drag ends."""
        self._held = bool(held)
        if held:
            self._timer.stop()
            self._hide()
            return
        widget = self._pending
        if widget is not None and widget.isVisible() and widget.rect().contains(widget.mapFromGlobal(QCursor.pos())):
            self._arm()

    def _show(self):
        if self._held:
            return
        widget = self._pending
        # Deliberately still shown for a disabled (greyed) widget -- knowing
        # why something is unavailable is exactly when a tip helps most.
        if widget is None or not widget.isVisible():
            return
        text = widget.property("_tooltip_text")
        if not text:
            return
        popup = self._popup_widget()
        popup.setText(text)
        # Width first (clamped to the maximum), then the height *at that width*:
        # `adjustSize` works the height out at the unclamped hint width, so a
        # long tip came out too short for the width it was then squeezed to.
        width = min(popup.sizeHint().width(), popup.maximumWidth())
        popup.resize(width, popup.heightForWidth(width))
        gap = px(6)
        anchor = widget.mapToGlobal(QPoint(0, widget.height() + gap))
        screen = widget.screen()
        if screen is not None:
            avail = screen.availableGeometry()
            anchor.setX(max(avail.left(), min(anchor.x(), avail.right() - popup.width())))
            if anchor.y() + popup.height() > avail.bottom():
                anchor.setY(widget.mapToGlobal(QPoint(0, 0)).y() - popup.height() - gap)
        popup.move(anchor)
        popup.show()
        popup.fade_in()

    def _hide(self):
        if self._popup is not None:
            self._popup._fade.stop()
            self._popup.hide()


_manager = None


def hold_tips(held):
    """Hides every tooltip and keeps them hidden until `hold_tips(False)` —
    for the length of a drag."""
    global _manager
    if _manager is None:
        _manager = _TooltipManager()
    _manager.hold(held)


def tip(widget, text):
    """Attach (or update) a hover tooltip on `widget` — shown after a short
    delay, below the widget, in the app's own themed popup rather than the
    OS's plain tooltip box."""
    global _manager
    if _manager is None:
        _manager = _TooltipManager()
    _manager.register(widget, text)
