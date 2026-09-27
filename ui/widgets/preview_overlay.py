# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""The expanded preview: a scrim over the main window hosting the tab's own carousel."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from ui.scale import px


class _ExpandedPreviewOverlay(QWidget):
    """A translucent scrim over the main window hosting the tab's own carousel, reparented in
    at a bigger size, so all its behaviour carries over. A child widget, not its own window: a
    separate window stole activation, and the Left/Right keybind is gated on the main window
    being active. Clicking the scrim shrinks back. One per MediaTab."""

    _SCRIM = QColor(0, 0, 0, 175)
    _MARGIN = 20

    def __init__(self, main_window):
        super().__init__(main_window)
        self._carousel = None
        self.hide()

    def paintEvent(self, _event):
        QPainter(self).fillRect(self.rect(), self._SCRIM)

    def resizeEvent(self, _event):
        self._layout_carousel()

    def _layout_carousel(self):
        if self._carousel is None:
            return
        m = px(self._MARGIN)
        avail = self.rect().adjusted(m, m, -m, -m)
        self._carousel.setGeometry(avail)

    def show_with(self, carousel):
        self._carousel = carousel
        carousel.setParent(self)
        self.setGeometry(self.parentWidget().rect())
        self._layout_carousel()
        self.show()
        # setParent() hides the widget, whatever the new parent's visibility.
        carousel.show()
        self.raise_()

    def release(self):
        """Give the carousel back; the caller re-parents it at once."""
        self._carousel = None
        self.hide()

    def mousePressEvent(self, e):
        """A click on the scrim (outside the carousel) shrinks back."""
        if e.button() == Qt.LeftButton and self._carousel is not None:
            self._carousel.force_collapse()
