"""Themed modal dialogs: blocking problems get one of these; things that just
happened get a toast (ui/widgets/toast.py) instead.

A QDialog's `exec()` spins a nested event loop, so timers keep firing
underneath it. Never open one from inside a recurring
tick — post it with `QTimer.singleShot(0, ...)` (see QueueTab._show_errors)."""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from ui.widgets.controls import CheckBox, button
from ui.widgets.panels import ASSETS

_DIALOG_WIDTH = 400


class MessageDialog(QDialog):
    """A bold title, a wrapped message, an optional single-line entry, and one
    or two buttons. The FIRST button is the affirmative one (primary); the
    rest are declines (secondary). Enter confirms; Escape and the title-bar
    close box both count as declining, so a dismissed confirmation can never
    destroy work. `.result_label` is the pressed button's label or None."""

    def __init__(self, parent, title, message, buttons=("OK",), entry=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        icon = os.path.join(ASSETS, "llama.ico")
        if os.path.exists(icon):
            self.setWindowIcon(QIcon(icon))
        self.setModal(True)
        self.setFixedWidth(_DIALOG_WIDTH)
        self.result_label = None
        self._buttons = buttons

        body = QVBoxLayout(self)
        body.setContentsMargins(20, 18, 20, 14)
        body.setSpacing(0)
        heading = QLabel(title)
        heading.setProperty("role", "dialogTitle")
        body.addWidget(heading)
        body.addSpacing(6)
        text = QLabel(message)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.addWidget(text)

        self.entry = None
        if entry is not None:
            body.addSpacing(10)
            self.entry = QLineEdit(entry)
            self.entry.setFixedHeight(28)
            body.addWidget(self.entry)
        self._build_extra(body)

        body.addSpacing(16)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        for index, label in enumerate(buttons):
            btn = button(label, role="primary" if index == 0 else None, width=90)
            btn.clicked.connect(lambda _=False, choice=label: self._dismiss(choice))
            row.addWidget(btn)
        body.addLayout(row)

    def _build_extra(self, body):
        """Hook for subclasses that need more than a message."""

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
            self._dismiss(self._buttons[0])
        elif e.key() == Qt.Key_Escape:
            self._dismiss(None)
        else:
            super().keyPressEvent(e)

    def _dismiss(self, choice):
        self.result_label = choice
        self.done(0)

    def show_modal(self):
        self.exec()
        return self.result_label


def show_message(parent, title, message):
    """Single-OK notice. Returns once the user acknowledges it."""
    return MessageDialog(parent, title, message, buttons=("OK",)).show_modal()


def ask_yes_no(parent, title, message):
    """Yes/No confirmation — True only on an explicit Yes."""
    return MessageDialog(parent, title, message, buttons=("Yes", "No")).show_modal() == "Yes"


def ask_text(parent, title, message, initial="", confirm="Save"):
    """One line of text (preset names). The stripped string, or None when
    cancelled, closed, or left blank."""
    dialog = MessageDialog(parent, title, message, buttons=(confirm, "Cancel"), entry=initial)
    if dialog.show_modal() != confirm:
        return None
    return (dialog.entry.text() or "").strip() or None


def confirm_output_path(parent, output_path, input_file, claimed=False):
    """The pre-queue checks on where a job will write. A folder or the input
    file itself is refused; a path that exists — or that another unfinished
    job will write (`claimed`) — asks first, and No means the job isn't
    queued. Asking at queue time is what lets the queue run without ever
    stopping to prompt."""
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


class AudioStreamPickerDialog(MessageDialog):
    """"Choose Stream(s)": one checkbox per probed audio stream, pre-checked to
    match what's included. OK returns the chosen index set — never empty ("no
    audio" is Strip Audio's job); Cancel/close returns None."""

    def __init__(self, parent, streams, included):
        self._streams = streams
        self._included = set(included)
        self._checks = {}
        super().__init__(
            parent, "Choose Audio Streams",
            "Pick which of this file's audio streams to include in the output. "
            "Each included stream keeps its own codec settings — select it from "
            "the Audio Track dropdown to edit them.",
            buttons=("OK", "Cancel"),
        )

    def _build_extra(self, body):
        body.addSpacing(10)
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        for stream in self._streams:
            index = stream["index"]
            check = CheckBox(self._describe(stream), checked=index in self._included)
            check.setFont(check.font())
            lay.addWidget(check)
            self._checks[index] = check
        if not self._streams:
            empty = QLabel("This file has no audio streams.")
            empty.setProperty("role", "empty")
            lay.addWidget(empty)
        body.addWidget(box)

    @staticmethod
    def _describe(stream):
        bits = [f"Track {stream['index'] + 1}"]
        for key in ("codec", "channels_display", "sample_rate_display", "language"):
            if stream.get(key):
                bits.append(str(stream[key]))
        return "  ·  ".join(bits)

    def _dismiss(self, choice):
        if choice == "OK":
            chosen = {i for i, check in self._checks.items() if check.isChecked()}
            if not chosen and self._checks:
                self._checks[min(self._checks)].setChecked(True)
                return
            self.chosen = chosen
        else:
            self.chosen = None
        super()._dismiss(choice)


def choose_audio_streams(parent, streams, included):
    """Opens the picker; the chosen index set, or None if cancelled."""
    dialog = AudioStreamPickerDialog(parent, streams, included)
    dialog.show_modal()
    return getattr(dialog, "chosen", None)


class ExternalStreamPickerDialog(MessageDialog):
    """Muxing's "Add Stream": shown only once a browsed-in file turns out to
    have more than one track of the requested kind (a single match is added
    straight away, no dialog needed). One checkbox per track, all unchecked
    to start — unlike `AudioStreamPickerDialog`, there's no "already
    included" set to pre-check, since every row here is brand new. OK/"Add"
    never returns an empty set; Cancel/close returns None."""

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
        body.addSpacing(10)
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
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
    """Opens the picker for a file just browsed in via "Add Stream"; the
    chosen index set, or None if cancelled. `describe(stream)` renders one
    row's label."""
    dialog = ExternalStreamPickerDialog(parent, kind, streams, describe)
    dialog.show_modal()
    return getattr(dialog, "chosen", None)
