# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Themed modal dialogs (blocking problems get one; things that just happened get a toast).
`exec()` spins a nested event loop and timers keep firing under it: never open one from a
recurring tick; post it with `QTimer.singleShot(0, ...)`."""
import os
import uuid

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core import formats
from core.probe import probe_media
from ui import scale
from ui import theme as T
from ui.widgets.controls import button, button_width_for
from ui.widgets.text import ScaledLabel, ScaledLineEdit
from ui.widgets.toggles import CheckBox
from ui.widgets.panels import ASSETS
from ui.widgets.tracklist import TrackListBox, describe_stream, row_label
from ui.workers import run_async

_DIALOG_WIDTH = 400
_BORDER = 2     # the outline's width, reference px
_RADIUS = 8     # the panel's corner radius, reference px


class MessageDialog(QDialog):
    """A bold title, a wrapped message, an optional entry, and buttons. The first button is
    the affirmative one; Enter confirms, Escape and Alt+F4 decline. `.result_label` is the
    pressed button's label or None. Borderless: it paints its own rounded panel and a press on
    it drags the window. A subclass sets `SHOW_HEADER = False` to skip the title and message."""

    SHOW_HEADER = True
    WIDTH = _DIALOG_WIDTH        # reference px; a dialog with a lot on its button row is wider
    SIDE_MARGIN = 20             # reference px; a dialog whose own content is tight can narrow this

    def __init__(self, parent, title, message, buttons=("OK",), entry=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Styled here: a dialog built after a rescale must not inherit the stale app-level
        # sheet. Its background is cleared, since paintEvent draws the rounded panel.
        self.setStyleSheet(T.stylesheet() + "QDialog { background: transparent; }")
        self.setWindowTitle(title)
        icon = os.path.join(ASSETS, "llama.ico")
        if os.path.exists(icon):
            self.setWindowIcon(QIcon(icon))
        self.setModal(True)
        scale.fixed(self, w=self.WIDTH)
        self.result_label = None
        self._buttons = buttons
        self._button_widgets = {}

        body = QVBoxLayout(self)
        scale.margins(body, self.SIDE_MARGIN, 18, self.SIDE_MARGIN, 14)
        body.setSpacing(0)
        self.message_label = None
        if self.SHOW_HEADER:
            heading = ScaledLabel(title)
            heading.setProperty("role", "dialogTitle")
            body.addWidget(heading)
            scale.spacer(body, 6)
            # A stock QLabel so the text is selectable (Qt's text control only matches what Qt
            # paints). Fine here: a modal dialog is styled once at the current scale and not
            # resized. The title stays a ScaledLabel, whose role size is in reference px.
            text = QLabel(message)
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
            text.setCursor(Qt.IBeamCursor)
            body.addWidget(text)
            self.message_label = text

        self.entry = None
        if entry is not None:
            scale.spacer(body, 10)
            self.entry = ScaledLineEdit(entry)
            scale.fixed(self.entry, h=28)
            body.addWidget(self.entry)
        self._build_extra(body)

        scale.spacer(body, 16)
        row = QHBoxLayout()
        scale.spacing(row, 8)
        self._build_leading_buttons(row)
        row.addStretch(1)
        for index, label in enumerate(buttons):
            btn = button(label, role="action" if index == 0 else "queue", width=90)
            btn.clicked.connect(lambda _=False, choice=label: self._dismiss(choice))
            self._button_widgets[label] = btn
            row.addWidget(btn)
        body.addLayout(row)

    def _build_extra(self, body):
        """Hook for subclasses that need more than a message."""

    def set_button_enabled(self, label, enabled):
        """Grey out (or restore) the button labelled `label`; Enter then does nothing either."""
        self._button_widgets[label].setEnabled(bool(enabled))

    def _build_leading_buttons(self, row):
        """Hook: widgets for the left end of the button row (the standard buttons are right)."""

    def paintEvent(self, _event):
        """The rounded, outlined panel a frameless window doesn't get for free."""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        border = scale.fpx(_BORDER)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(border / 2, border / 2, -border / 2, -border / 2),
                            scale.fpx(_RADIUS), scale.fpx(_RADIUS))
        p.fillPath(path, T.theme.color("window"))
        p.setPen(QPen(T.theme.color("theme_accent"), border))
        p.drawPath(path)

    def mousePressEvent(self, e):
        """No title bar to drag by: a press on the panel itself moves the window."""
        handle = self.windowHandle()
        if e.button() == Qt.LeftButton and handle is not None:
            handle.startSystemMove()
        else:
            super().mousePressEvent(e)

    def showEvent(self, e):
        super().showEvent(e)
        parent = self.parentWidget()
        if parent is not None:
            self.adjustSize()
            geo = parent.frameGeometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + (geo.height() - self.height()) // 3
            self.move(max(0, x), max(0, y))
        if self.entry is not None:
            self.entry.setFocus()
            self.entry.selectAll()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self._button_widgets[self._buttons[0]].isEnabled():
                self._dismiss(self._buttons[0])
        elif e.key() == Qt.Key_Escape:
            self._dismiss(None)
        else:
            super().keyPressEvent(e)

    def _dismiss(self, choice):
        self.result_label = choice
        self.done(0)

    def show_modal(self):
        """Run the dialog; its button's label. The dialog is deleted once control returns to the
        event loop (the window owns it, so it would otherwise live as long as the window) —
        after the caller has read whatever it needs from it."""
        self.exec()
        self.deleteLater()
        return self.result_label


def show_message(parent, title, message):
    """Single-OK notice. Returns once the user acknowledges it."""
    return MessageDialog(parent, title, message, buttons=("OK",)).show_modal()


def ask_yes_no(parent, title, message):
    """Yes/No confirmation — True only on an explicit Yes."""
    return MessageDialog(parent, title, message, buttons=("Yes", "No")).show_modal() == "Yes"


def ask_text(parent, title, message, initial="", confirm="Save"):
    """One line of text; the stripped string, or None if cancelled or blank."""
    dialog = MessageDialog(parent, title, message, buttons=(confirm, "Cancel"), entry=initial)
    if dialog.show_modal() != confirm:
        return None
    return (dialog.entry.text() or "").strip() or None


class _RememberDialog(MessageDialog):
    """Yes/No plus a "Don't ask again" checkbox, under the message."""

    def __init__(self, parent, title, message, checkbox_text):
        self._checkbox_text = checkbox_text
        self.dont_ask = None
        super().__init__(parent, title, message, buttons=("Yes", "No"))

    def _build_extra(self, body):
        scale.spacer(body, 10)
        self.remember_check = CheckBox(self._checkbox_text)
        body.addWidget(self.remember_check)

    def _dismiss(self, choice):
        self.dont_ask = self.remember_check.isChecked()
        super()._dismiss(choice)


def ask_yes_no_remember(parent, title, message, checkbox_text="Don't ask again"):
    """Yes/No with a "Don't ask again" checkbox: `(confirmed, dont_ask)` — `confirmed` True only
    on an explicit Yes, `dont_ask` whatever the checkbox read when the dialog closed."""
    dialog = _RememberDialog(parent, title, message, checkbox_text)
    confirmed = dialog.show_modal() == "Yes"
    return confirmed, bool(dialog.dont_ask)


class CountdownDialog(MessageDialog):
    """A confirmation that goes ahead by itself: `message` (`{n}` = seconds left) counts
    down and answers "Now" at zero. "Now" acts at once; Cancel or Escape calls it off."""

    def __init__(self, parent, title, message, seconds, now_label="Now"):
        super().__init__(parent, title, message.format(n=seconds), buttons=(now_label, "Cancel"))
        self._template, self._remaining, self._now_label = message, seconds, now_label
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self):
        self._remaining -= 1
        if self._remaining <= 0:
            self._timer.stop()
            self._dismiss(self._now_label)
            return
        self.message_label.setText(self._template.format(n=self._remaining))

    def _dismiss(self, choice):
        self._timer.stop()
        super()._dismiss(choice)


def confirm_countdown(parent, title, message, seconds=30, now_label="Now"):
    """True when the countdown ran out or "Now" was pressed; False if cancelled."""
    return CountdownDialog(parent, title, message, seconds, now_label).show_modal() == now_label


def confirm_output_path(parent, output_path, input_file, claimed=False):
    """Pre-queue checks on where a job writes: a folder or the input itself is refused; an
    existing path, or one another unfinished job claims, asks first (No = not queued)."""
    if os.path.isdir(output_path):
        show_message(
            parent, "Choose a File Name",
            "The save location is a folder. Add a file name to it, or use "
            "Browse to pick where the file should be saved.",
        )
        return False

    target = os.path.normcase(os.path.abspath(output_path))
    if input_file and target == os.path.normcase(os.path.abspath(input_file)):
        show_message(
            parent, "Same File",
            "The output can't overwrite the input file it's made from. "
            "Choose a different name or folder.",
        )
        return False

    if claimed or os.path.exists(output_path):
        folder, name = os.path.split(os.path.abspath(output_path))
        where = (
            f"Another job in the queue is already set to save “{name}” in {folder}."
            if claimed and not os.path.exists(output_path)
            else f"A file named “{name}” already exists in {folder}."
        )
        return ask_yes_no(
            parent, "File Already Exists",
            f"{where}\n\nDo you want to overwrite it? Choosing No won't queue this job.",
        )
    return True


# Each kind's files, plus "All Files" so a track inside a video can be picked.
BROWSE_FILTERS = {
    "audio": "Audio Files (%s);;All Files (*.*)" % " ".join("*" + ext for ext in sorted(formats.AUDIO_EXTENSIONS)),
    "subtitle": "Subtitle Files (%s);;All Files (*.*)" % " ".join("*" + ext for ext in formats.SUBTITLE_EXTENSIONS),
}
_PICKER_LIST_HEIGHT = 150     # reference px: about five rows before it scrolls


class StreamPickerDialog(MessageDialog):
    """Encoding's "Choose Stream(s)" (audio or subtitle): a `TrackListBox` of streams (ticked =
    included, drag to reorder) and one button row: Add Stream(s), Remove Stream(s), OK, Cancel.
    It edits a copy, so Cancel discards everything. Add browses a file, probes it off the GUI
    thread and appends its stream(s) ticked; Remove takes out every ticked row. OK gives
    `chosen` and `result_entries` — `chosen` may be empty, for either kind: the caller (Strip
    Video/Audio/Subtitles) treats that the same as stripping the stream; Cancel gives None."""

    SHOW_HEADER = False
    WIDTH = 476           # one row holds Add, Remove, OK and Cancel — tight, see SIDE_MARGIN
    SIDE_MARGIN = 12      # narrower than the default 20: only the button row needs the width

    def __init__(self, parent, kind, entries, included, start_dir=""):
        self._kind = kind
        self._entries = list(entries)
        self._initial_checked = set(included)
        self._start_dir = start_dir  # where Add Stream(s)'s file dialog opens (the tab's output folder)
        self._finished = False       # an Add Stream(s) probe landing after OK/Cancel is dropped
        self.chosen = None
        self.result_entries = None
        super().__init__(parent, f"Choose {kind.capitalize()} Streams", "", buttons=("OK", "Cancel"))

    def _build_extra(self, body):
        self.box = TrackListBox()
        scale.fixed(self.box, h=_PICKER_LIST_HEIGHT)
        self.box.reordered.connect(self._on_reordered)
        body.addWidget(self.box)
        self._refresh(self._initial_checked)

    def _build_leading_buttons(self, row):
        """Add Stream(s) and Remove Stream(s), at the left of the button row."""
        add_btn = button("Add Stream(s)", width=button_width_for(["Add Stream(s)"]))
        add_btn.clicked.connect(self._add_stream)
        row.addWidget(add_btn)
        remove_btn = button("Remove Stream(s)", role="danger", width=button_width_for(["Remove Stream(s)"]))
        remove_btn.clicked.connect(self._remove_streams)
        row.addWidget(remove_btn)

    def _refresh(self, checked=None):
        """Show `self._entries` numbered by position; `checked` (default: the current ticks)
        says which rows are ticked."""
        if checked is None:
            checked = set(self.box.checked_ids())
        items = [{"id": entry["id"], "label": row_label(self._kind, entry, number)}
                 for number, entry in enumerate(self._entries, start=1)]
        self.box.set_items(items, checked=checked)

    def _on_reordered(self, ids):
        by_id = {entry["id"]: entry for entry in self._entries}
        self._entries = [by_id[row_id] for row_id in ids if row_id in by_id]
        self._refresh()

    def _remove_streams(self):
        ticked = set(self.box.checked_ids())
        if not ticked:
            show_message(self, "Nothing to Remove",
                         "Check the track(s) you want removed, then press Remove Stream(s) again.")
            return
        self._entries = [entry for entry in self._entries if entry["id"] not in ticked]
        self._refresh(set(self.box.checked_ids()) - ticked)

    def _add_stream(self):
        path, _ = QFileDialog.getOpenFileName(self, f"Select {self._kind.capitalize()} Source", self._start_dir,
                                              BROWSE_FILTERS[self._kind])
        if path:
            run_async(probe_media, lambda info: self._stream_probed(path, info), path)

    def _stream_probed(self, path, info):
        """The browsed-in file's probe landed: append its stream(s) of the kind."""
        if self._finished:
            return
        streams = [stream for stream in (info or {}).get(f"{self._kind}_streams") or []
                   if self._kind != "subtitle" or stream.get("codec_name") in formats.FFPROBE_SUBTITLE]
        if not streams:
            show_message(self, "No Matching Streams",
                         f"\u201c{os.path.basename(path)}\u201d has no {self._kind} streams to add.")
            return
        if len(streams) > 1:
            picked = pick_external_streams(self, self._kind, streams, lambda s: describe_stream(self._kind, s))
            if picked is None:
                return
            streams = [s for s in streams if s["index"] in picked]
        name = os.path.basename(path.replace("\\", "/"))
        added = [{"id": f"ext:{uuid.uuid4().hex[:8]}", "source": "external", "file": path,
                  "index": stream["index"], "stream": stream, "name": name,
                  "start_time": (info or {}).get("start_time")}
                 for stream in streams]
        self._entries += added
        self._refresh(set(self.box.checked_ids()) | {entry["id"] for entry in added})
        # The new rows are at the bottom: scroll to them once laid out.
        bar = self.box.scroll.verticalScrollBar()
        QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))

    def _dismiss(self, choice):
        if choice == "OK":
            # Nothing ticked is a real, confirmable choice here — Strip Video/Audio/Subtitles
            # picks it up as one (`EncodingTab._open_stream_picker`/`_open_sub_picker`), not a
            # dead end the dialog has to steer the user away from.
            self.chosen = set(self.box.checked_ids())
            self.result_entries = list(self._entries)
        self._finished = True
        super()._dismiss(choice)


def choose_streams(parent, kind, entries, included, start_dir=""):
    """Open the `kind` ("audio" / "subtitle") picker on `entries` (`included` ticked), Add
    Stream(s) browsing from `start_dir`; `(entries, chosen ids)`, or None if cancelled."""
    dialog = StreamPickerDialog(parent, kind, entries, included, start_dir)
    dialog.show_modal()
    if dialog.chosen is None:
        return None
    return dialog.result_entries, dialog.chosen


class ExternalStreamPickerDialog(MessageDialog):
    """Muxing's "Add Stream(s)" when the browsed file has several tracks of the kind: one
    unchecked box per track. OK never returns an empty set; Cancel / Escape returns None."""

    def __init__(self, parent, kind, streams, describe):
        self._streams = streams
        self._describe = describe
        self._checks = {}
        super().__init__(
            parent, f"Choose {kind.capitalize()} Streams",
            f"This file has more than one {kind} track. Pick which to add — "
            "each becomes its own row in the track box.",
            buttons=("Add", "Cancel"),
        )

    def _build_extra(self, body):
        scale.spacer(body, 10)
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        scale.spacing(lay, 6)
        for stream in self._streams:
            index = stream["index"]
            check = CheckBox(self._describe(stream), checked=(index == 0))
            lay.addWidget(check)
            self._checks[index] = check
        body.addWidget(box)

    def _dismiss(self, choice):
        if choice == "Add":
            chosen = {i for i, check in self._checks.items() if check.isChecked()}
            if not chosen and self._checks:
                self._checks[min(self._checks)].setChecked(True)
                return
            self.chosen = chosen
        else:
            self.chosen = None
        super()._dismiss(choice)


def pick_external_streams(parent, kind, streams, describe):
    """Open the picker for a browsed-in file; the chosen index set, or None if cancelled.
    `describe(stream)` renders a row's label."""
    dialog = ExternalStreamPickerDialog(parent, kind, streams, describe)
    dialog.show_modal()
    return getattr(dialog, "chosen", None)
