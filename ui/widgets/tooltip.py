# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""A themed hover tooltip, attached with `tip(widget, text)`: one shared popup driven by an
event filter, so it never touches a control's own hover or paint logic."""
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
    """The one shared popup. Fades in on show; hides at once."""

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
        # Runs on every live-resize step: skip setStyleSheet when the text is unchanged.
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
    """Shows the popup once the cursor has hovered over a registered widget and stopped for
    `_DELAY_MS`; hides it on leave, click or disable. Stillness is sampled from `QCursor.pos()`
    (a container never gets mouse moves over its children). `hold(True)` suspends every tip,
    for a drag that starts on a child (the widget never sees that press)."""

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
            # A disabled control keeps its tip but must not look clickable: a plain arrow until
            # it re-enables.
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
        """Suspend (True) or resume (False) the tips. Resuming re-arms the hover delay if the
        cursor is still on the last widget, so the tip returns after a pause."""
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
        # Still shown on a disabled widget: that is when "why" matters most.
        if widget is None or not widget.isVisible():
            return
        text = widget.property("_tooltip_text")
        if not text:
            return
        popup = self._popup_widget()
        popup.setText(text)
        # Width first (clamped), then the height at that width: `adjustSize` measured at the
        # unclamped width and cut long tips short.
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
    """Hide every tip and keep them hidden until `hold_tips(False)` (a drag)."""
    global _manager
    if _manager is None:
        _manager = _TooltipManager()
    _manager.hold(held)


def tip(widget, text):
    """Attach (or update) a hover tip on `widget`, in the app's themed popup."""
    global _manager
    if _manager is None:
        _manager = _TooltipManager()
    _manager.register(widget, text)
