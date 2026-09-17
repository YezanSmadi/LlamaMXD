"""A themed hover tooltip for option controls, attached with `tip(widget, text)`.

Mirrors `carousel._InfoTooltip`'s look (dark body, primary border) but is
shared and driven by real QWidget Enter/Leave events rather than a manual
`mouseMoveEvent` hit-test, since every caller here is an actual widget
(Dropdown, CheckBox, Switch, SegmentedButton, QSlider, ...). Installed as an
event filter, so it never touches a control's own hover/paint logic."""
from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, Qt, QTimer, QVariantAnimation
from PySide6.QtWidgets import QLabel

from ui import theme as T

_DELAY_MS = 400
_MAX_WIDTH = 280
_FADE_MS = 120


class _Tooltip(QLabel):
    """The popup itself — one shared instance for the whole app. Fades in
    (soft but quick) on every show; hides instantly, no fade out."""

    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setTextFormat(Qt.PlainText)
        self.setWordWrap(True)
        self.setMaximumWidth(_MAX_WIDTH)
        self._fade = QVariantAnimation(self)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setDuration(_FADE_MS)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.valueChanged.connect(self.setWindowOpacity)
        self._restyle()
        T.theme.changed.connect(self._restyle)

    def _restyle(self):
        self.setStyleSheet(
            f"QLabel {{ background: {T.theme.hex('tooltip_bg')}; color: white;"
            f" border: 1px solid {T.theme.hex('primary')}; border-radius: 4px;"
            f" padding: 6px 9px; font-family: Arial; font-size: 12px; }}"
        )

    def fade_in(self):
        self.setWindowOpacity(0.0)
        self._fade.stop()
        self._fade.start()


class _TooltipManager(QObject):
    """Installed as an event filter on every registered widget: shows the
    shared popup after a hover delay, hides it on leave / click / disable."""

    def __init__(self):
        super().__init__()
        self._popup = None
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._show)
        self._pending = None

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
            self._timer.start(_DELAY_MS)
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

    def _show(self):
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
        popup.adjustSize()
        anchor = widget.mapToGlobal(QPoint(0, widget.height() + 6))
        screen = widget.screen()
        if screen is not None:
            avail = screen.availableGeometry()
            anchor.setX(max(avail.left(), min(anchor.x(), avail.right() - popup.width())))
            if anchor.y() + popup.height() > avail.bottom():
                anchor.setY(widget.mapToGlobal(QPoint(0, 0)).y() - popup.height() - 6)
        popup.move(anchor)
        popup.show()
        popup.fade_in()

    def _hide(self):
        if self._popup is not None:
            self._popup._fade.stop()
            self._popup.hide()


_manager = None


def tip(widget, text):
    """Attach (or update) a hover tooltip on `widget` — shown after a short
    delay, below the widget, in the app's own themed popup rather than the
    OS's plain tooltip box."""
    global _manager
    if _manager is None:
        _manager = _TooltipManager()
    _manager.register(widget, text)
