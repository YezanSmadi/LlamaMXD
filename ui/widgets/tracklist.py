"""`TrackListBox` — Muxing's inline, checkable track picker: a scrollable,
secondary-bordered box (see `BorderedFrame`) where each row is one stream the
output can carry, checked to include it. It's the same "one checkbox per
probed stream" idea as `AudioStreamPickerDialog` (`ui/widgets/dialogs.py`),
just inline in the panel instead of behind a "Choose Stream(s)" button — and
rows aren't limited to the source file's own streams: MuxingTab appends rows
here for streams pulled in from another file via "Add Stream(s)", removed
again in bulk via "Remove Stream(s)" (whichever of *those* rows are checked
at the time — see MuxingTab._remove_streams) rather than a per-row control."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from ui.widgets.controls import CheckBox, MarqueeGroup, MarqueeLabel
from ui.widgets.panels import BorderedFrame


class _TrackRow(QWidget):
    """One row: a text-less `CheckBox` plus a `MarqueeLabel` in place of the
    checkbox's own caption, so a long label scrolls instead of clipping while
    the box itself stays put. A click anywhere on the row (label included)
    toggles the checkbox, matching what clicking a captioned `CheckBox`
    did before."""

    def __init__(self, label, checked, group):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        rl = QHBoxLayout(self)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(7)
        self.check = CheckBox("", checked=checked)
        rl.addWidget(self.check)
        # Same face as CheckBox's own caption (Arial 12 bold) so the swap
        # is invisible for text that already fit.
        self.label = MarqueeLabel(label, pixel_size=12, bold=True, family="Arial", group=group)
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents)
        rl.addWidget(self.label, 1)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.isEnabled() and self.rect().contains(e.position().toPoint()):
            self.check.click()

    def enterEvent(self, e):
        self.check.set_hover(True)

    def leaveEvent(self, e):
        self.check.set_hover(False)


class TrackListBox(BorderedFrame):
    """`set_items([{"id", "label"}, ...])` rebuilds the row list. Empty shows
    a centered "No tracks available" in place of the list.

    Matching by `id`, an already-present row keeps its checked state and just
    refreshes its label — a click on one checkbox never disturbs the others.
    `reset=True` (a new input file — its stream indices no longer mean what
    they meant before) instead tears down every row first, so a same-named id
    from the *previous* file can't be mistaken for a carried-over pick.
    A brand new id (first appearance, whether from a reset or a fresh "Add
    Stream(s)" pull) defaults to checked only when it lands in the very first
    row — every other stream starts unchecked, same as Encoding's own
    multi-track audio picker defaulting to just the first stream."""

    changed = Signal()          # a row's checkbox was toggled by the user

    def __init__(self, parent=None):
        super().__init__(parent, color_key="secondary")
        # Height is fixed, not just a minimum: a QScrollArea's own sizeHint
        # follows its scrolled widget's when `widgetResizable` is True, so
        # with only a *minimum* height here, five or six rows would have
        # quietly grown the box (and the whole panel, and the whole tab's
        # preview area — see the "same height as Encoding" paragraph in
        # CLAUDE.md) taller than an empty or lightly-populated one. Fixed
        # forces every extra row into the scroll area's own internal
        # scrollbar instead. Width stays a minimum/floor — MuxingTab's
        # `_track_panel` stretches the box wider via its row's own layout,
        # which a fixed width would block.
        self.setMinimumWidth(340)
        self.setFixedHeight(92)
        self._rows = {}  # id -> (row_widget, CheckBox)
        # One shared loop for every row's label: a long label holds at its
        # start once its own sweep ends, and they all restart together only
        # after the longest has too — same as the Overview rundown.
        self._marquee_group = MarqueeGroup()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(9, 7, 5, 7)

        # Centered dead-center in the box, not the scroll list's first row —
        # a "No tracks" message sitting at the top-left like a row would look
        # like a label, not an empty state. Hidden (and out of the layout's
        # space calculation) the moment there's a real row to show instead.
        self.empty_label = QLabel("No tracks available")
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
        self._list_layout.setContentsMargins(0, 0, 6, 0)
        self._list_layout.setSpacing(4)
        self._list_layout.addStretch(1)
        self.scroll.setWidget(host)

    def set_items(self, items, reset=False):
        ids = [it["id"] for it in items]
        stale = list(self._rows) if reset else [rid for rid in self._rows if rid not in ids]
        for rid in stale:
            self._remove_row(rid)
        for i, item in enumerate(items):
            if item["id"] in self._rows:
                row, _check = self._rows[item["id"]]
                row.label.setText(item["label"])
            else:
                self._add_row(item, checked=(i == 0))
        self.empty_label.setVisible(not items)
        self.scroll.setVisible(bool(items))

    def _add_row(self, item, checked):
        row = _TrackRow(item["label"], checked, self._marquee_group)
        row.check.clicked.connect(lambda _=False: self.changed.emit())
        self._list_layout.insertWidget(self._list_layout.count() - 1, row)
        self._rows[item["id"]] = (row, row.check)

    def _remove_row(self, rid):
        row, _check = self._rows.pop(rid)
        self._marquee_group.unregister(row.label)
        row.setParent(None)
        row.deleteLater()

    def checked_ids(self):
        """Every checked row's id, in the order rows were added."""
        return [rid for rid, (_row, check) in self._rows.items() if check.isChecked()]

    def set_checked(self, row_id, checked):
        """Programmatically (un)checks one row — e.g. "Remove Stream(s)"
        excluding a source row it can't actually delete. Doesn't emit
        `changed` (this app's controls only fire on a genuine user click),
        so the caller is responsible for its own follow-up resync."""
        entry = self._rows.get(row_id)
        if entry:
            entry[1].setChecked(checked)

    def item_count(self):
        return len(self._rows)

    def item_ids(self):
        """Every row's id, in the order rows were added — checked or not,
        unlike `checked_ids()`. What "Select All"/"Deselect All" iterate."""
        return list(self._rows)
