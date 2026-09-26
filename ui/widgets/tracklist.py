# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""`TrackListBox`: the checkable, reorderable track list used by Muxing's panels and Encoding's
Choose Stream(s) popup. Each row is one stream, ticked to include it. Which rows exist and in
what order is the caller's; the box shows the list it is given and reports ticks (`changed`)
and drag reorders (`reordered`)."""
from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPixmap, QRegion
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget,
)

from ui import scale
from ui import theme as T
from ui.scale import px
from ui.widgets.marquee import MarqueeGroup, MarqueeLabel
from ui.widgets.text import ScaledLabel
from ui.widgets.toggles import CheckBox
from ui.widgets.panels import BorderedFrame
from ui.widgets.tooltip import hold_tips

_AUTOSCROLL_EDGE = 22       # px from the viewport's top/bottom where a drag starts scrolling it
_AUTOSCROLL_STEP = 7        # px scrolled per 16ms tick at the very edge
_DRAGGED_OPACITY = 0.28     # the row's own slot, left in the list as a placeholder


# Row text, for both users' entries: {"id", "source", "file", "index", "stream", "name"}.
def stream_details(kind, stream, compact=False):
    """One stream's details in row order. Video: codec, profile, level, size, fps, HDR kind,
    bit depth + chroma, bit rate, language. Audio: codec, channels, rate, language. `compact`
    (the narrow "Add Stream(s)" picker): fewer video fields, HDR only when it is."""
    if kind == "video" and compact:
        bits = [stream.get("codec") or stream.get("codec_name"), stream.get("profile"),
                stream.get("resolution_display"),
                stream.get("hdr_display") if stream.get("hdr") else None, stream.get("language")]
    elif kind == "video":
        level, fps = stream.get("level"), stream.get("fps_display")
        bits = [stream.get("codec") or stream.get("codec_name"), stream.get("profile"),
                f"L{level}" if level else None, stream.get("resolution_display"),
                f"{fps} fps" if fps else None, stream.get("hdr_display"),
                stream.get("color_format"), stream.get("bitrate_display"), stream.get("language")]
    else:
        bits = [stream.get("codec"), stream.get("channels_display"),
                stream.get("sample_rate_display"), stream.get("language")]
    return [str(bit) for bit in bits if bit]


def describe_stream(kind, stream):
    """A stream as the "Add Stream(s)" picker lists it: its number in its own file, then its
    details."""
    return "  ·  ".join([f"Track {stream['index'] + 1}", *stream_details(kind, stream, compact=True)])


def row_label(kind, entry, number):
    """A row's text. `number` is the row's place in the list (removing a track renumbers the
    rest); a track from another file says so."""
    bits = [f"Track {number}"]
    if entry["source"] == "external":
        bits.append(f"External: {entry['name']}")
    bits += stream_details(kind, entry["stream"])
    return "  ·  ".join(bits)


class _DragGhost(QWidget):
    """What follows the cursor during a drag: a snapshot of the row on a rounded slab in the
    window colour (the box itself is transparent). The snapshot is taken onto a transparent
    pixmap and clipped round: `QWidget.grab()` filled a sharp-cornered opaque band."""

    def __init__(self, row, parent):
        super().__init__(parent)
        self._pixmap = self.snapshot(row)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        T.theme.changed.connect(self.update)

    @staticmethod
    def snapshot(row):
        """`row` and its children drawn onto a transparent pixmap."""
        ratio = row.devicePixelRatioF()
        pixmap = QPixmap(round(row.width() * ratio), round(row.height() * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.transparent)
        row.render(pixmap, QPoint(), QRegion(), QWidget.DrawChildren)
        return pixmap

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        shape = QPainterPath()
        shape.addRoundedRect(QRectF(self.rect()), px(6), px(6))
        p.fillPath(shape, T.theme.color("window"))
        p.setClipPath(shape)
        p.drawPixmap(0, 0, self._pixmap)


class _TrackRow(QWidget):
    """One row: a text-less `CheckBox` and a `MarqueeLabel` (long text scrolls). A click
    anywhere on the row toggles the box; a press that moves past the drag distance picks the
    row up instead (`TrackListBox._begin_drag`) and toggles nothing."""

    def __init__(self, label, checked, group, box):
        super().__init__()
        self._box = box
        self._press = None          # global position of a left press not yet released
        self._dragging = False
        self.setCursor(Qt.PointingHandCursor)
        rl = QHBoxLayout(self)
        rl.setContentsMargins(0, 0, 0, 0)
        scale.spacing(rl, 7)
        self.check = CheckBox("", checked=checked)
        # The row does the clicking, so a drag can start on the checkbox too.
        self.check.setAttribute(Qt.WA_TransparentForMouseEvents)
        rl.addWidget(self.check)
        # CheckBox's own caption face (Arial 12 bold).
        self.label = MarqueeLabel(label, pixel_size=12, bold=True, family="Arial", group=group)
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents)
        rl.addWidget(self.label, 1)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        if self._press is None or not (e.buttons() & Qt.LeftButton):
            return
        here = e.globalPosition().toPoint()
        if not self._dragging:
            if (here - self._press).manhattanLength() < QApplication.startDragDistance():
                return
            if not self._box._begin_drag(self, here):
                self._press = None      # nothing to reorder against
                return
            self._dragging = True
        self._box._drag_to(here)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        dragged, self._dragging, self._press = self._dragging, False, None
        if dragged:
            self._box._end_drag()
        elif self.isEnabled() and self.rect().contains(e.position().toPoint()):
            self.check.click()

    def enterEvent(self, e):
        self.check.set_hover(True)

    def leaveEvent(self, e):
        self.check.set_hover(False)


class TrackListBox(BorderedFrame):
    """`set_items([{"id", "label"}, ...])` updates the rows; empty shows "No tracks available".
    Rows are matched by id (an existing row keeps its tick, so one click never disturbs
    another) and put in the order of `items`. `reset=True` (a new input file) rebuilds every
    row, so an old file's id can't pass for a pick. A new row starts ticked, unless `checked`
    (a set of ids) is given, which then sets every row (an undo putting ticks back)."""

    changed = Signal()          # a row's checkbox was toggled by the user
    reordered = Signal(list)    # a drag ended with the rows in a new order: every id, top to bottom

    def __init__(self, parent=None):
        super().__init__(parent, color_key="secondary")
        # Fixed height, not a minimum: the scroll area's hint follows its rows, so extra rows
        # would grow the box (and shrink the preview). Width is a floor; the row stretches it.
        scale.bounds(self, min_w=340)
        scale.fixed(self, h=92)
        self._rows = {}  # id -> (row_widget, CheckBox)
        self._drag = None   # while a row is being dragged: see _begin_drag
        self._autoscroll = QTimer(self)
        self._autoscroll.setInterval(16)
        self._autoscroll.timeout.connect(self._autoscroll_tick)
        # One shared loop, so every row's label sweeps and restarts in step.
        self._marquee_group = MarqueeGroup()

        outer = QVBoxLayout(self)
        scale.margins(outer, 9, 7, 5, 7)

        # Centred in the box, not placed like the list's first row; hidden when there are rows.
        self.empty_label = ScaledLabel("No tracks available")
        self.empty_label.setProperty("role", "empty")
        self.empty_label.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.empty_label, 1, Qt.AlignCenter)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.hide()
        outer.addWidget(self.scroll)

        host = QWidget()
        host.setAutoFillBackground(False)
        self._list_layout = QVBoxLayout(host)
        scale.margins(self._list_layout, 0, 0, 6, 0)
        scale.spacing(self._list_layout, 4)
        self._list_layout.addStretch(1)
        self.scroll.setWidget(host)

    def set_items(self, items, reset=False, checked=None):
        ids = [it["id"] for it in items]
        stale = list(self._rows) if reset else [rid for rid in self._rows if rid not in ids]
        for rid in stale:
            self._remove_row(rid)
        for i, item in enumerate(items):
            rid = item["id"]
            if rid in self._rows:
                row, check = self._rows[rid]
                row.label.setText(item["label"])
                if checked is not None:
                    check.setChecked(rid in checked)
            else:
                row = self._add_row(item, checked=(rid in checked) if checked is not None else True)
            # Move a row only when it isn't already in place.
            at = self._list_layout.itemAt(i)
            if at is None or at.widget() is not row:
                self._list_layout.removeWidget(row)
                self._list_layout.insertWidget(i, row)
        self._rows = {rid: self._rows[rid] for rid in ids}
        self.empty_label.setVisible(not items)
        self.scroll.setVisible(bool(items))

    def _add_row(self, item, checked):
        row = _TrackRow(item["label"], checked, self._marquee_group, self)
        row.check.clicked.connect(lambda _=False: self.changed.emit())
        self._rows[item["id"]] = (row, row.check)
        return row

    def _remove_row(self, rid):
        row, _check = self._rows.pop(rid)
        if self._drag is not None and self._drag["row"] is row:
            self._finish_drag()
        self._marquee_group.unregister(row.label)
        row.setParent(None)
        row.deleteLater()

    # ------------------------------------------------------------------ #
    #  Drag to reorder
    # ------------------------------------------------------------------ #
    # The dragged row stays in the layout as a dimmed placeholder, moved as the cursor passes
    # its neighbours; a `_DragGhost` follows the cursor. Only the drop reports anything.

    def _begin_drag(self, row, global_pos):
        """Picks `row` up. False (drag refused) with fewer than two rows."""
        if len(self._rows) < 2 or self._drag is not None:
            return False
        viewport = self.scroll.viewport()
        top_left = row.mapTo(viewport, QPoint(0, 0))
        ghost = _DragGhost(row, viewport)
        ghost.setGeometry(top_left.x(), top_left.y(), row.width(), row.height())
        ghost.show()
        ghost.raise_()
        effect = QGraphicsOpacityEffect(row)
        effect.setOpacity(_DRAGGED_OPACITY)
        row.setGraphicsEffect(effect)
        # Where inside the row the cursor took hold, so the ghost doesn't jump.
        grab_dy = viewport.mapFromGlobal(global_pos).y() - top_left.y()
        self._drag = {"row": row, "ghost": ghost, "grab_dy": grab_dy, "pos": global_pos}
        QApplication.setOverrideCursor(Qt.ClosedHandCursor)
        hold_tips(True)     # the box's own tip would otherwise appear mid-drag
        self._autoscroll.start()
        return True

    def _drag_to(self, global_pos):
        self._drag["pos"] = global_pos
        self._follow_cursor()

    def _follow_cursor(self):
        """Move the ghost to the cursor (inside the viewport) and the placeholder to the slot
        under the ghost's centre."""
        drag = self._drag
        viewport = self.scroll.viewport()
        ghost, row = drag["ghost"], drag["row"]
        y = viewport.mapFromGlobal(drag["pos"]).y() - drag["grab_dy"]
        y = max(0, min(y, viewport.height() - ghost.height()))
        ghost.move(ghost.x(), y)
        host = self.scroll.widget()
        centre = host.mapFrom(viewport, QPoint(0, y + ghost.height() // 2)).y()
        layout = self._list_layout
        step = row.height() + layout.spacing()
        target = int((centre - layout.contentsMargins().top()) // step)
        target = max(0, min(target, len(self._rows) - 1))
        if layout.indexOf(row) != target:
            layout.removeWidget(row)
            layout.insertWidget(target, row)
            layout.activate()

    def _autoscroll_tick(self):
        """Scrolls the list while the cursor is held near its top or bottom edge."""
        if self._drag is None:
            self._autoscroll.stop()
            return
        viewport = self.scroll.viewport()
        y = viewport.mapFromGlobal(self._drag["pos"]).y()
        depth = 0
        if y < _AUTOSCROLL_EDGE:
            depth = -(_AUTOSCROLL_EDGE - y)
        elif y > viewport.height() - _AUTOSCROLL_EDGE:
            depth = y - (viewport.height() - _AUTOSCROLL_EDGE)
        bar = self.scroll.verticalScrollBar()
        if depth and bar.maximum() > bar.minimum():
            sign = 1 if depth > 0 else -1
            amount = max(1, round(_AUTOSCROLL_STEP * min(abs(depth), _AUTOSCROLL_EDGE) / _AUTOSCROLL_EDGE))
            bar.setValue(bar.value() + sign * amount)
            self._follow_cursor()

    def _finish_drag(self):
        """Puts everything a drag borrowed back."""
        drag, self._drag = self._drag, None
        self._autoscroll.stop()
        drag["ghost"].hide()
        drag["ghost"].deleteLater()
        drag["row"].setGraphicsEffect(None)
        QApplication.restoreOverrideCursor()
        hold_tips(False)

    def _end_drag(self):
        """The drop: reports the new order if the rows ended up somewhere else."""
        self._follow_cursor()
        self._finish_drag()
        by_widget = {row: rid for rid, (row, _check) in self._rows.items()}
        order = [by_widget[self._list_layout.itemAt(i).widget()]
                 for i in range(self._list_layout.count() - 1)]
        if order != list(self._rows):
            self._rows = {rid: self._rows[rid] for rid in order}
            self.reordered.emit(order)

    def checked_ids(self):
        """Every checked row's id, top to bottom."""
        return [rid for rid, (_row, check) in self._rows.items() if check.isChecked()]

    def set_checked(self, row_id, checked):
        """(Un)check one row programmatically, without emitting `changed`."""
        entry = self._rows.get(row_id)
        if entry:
            entry[1].setChecked(checked)

    def item_count(self):
        return len(self._rows)

    def item_ids(self):
        """Every row's id, top to bottom, checked or not."""
        return list(self._rows)
