# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Themed modal dialogs: blocking problems get one of these; things that just
happened get a toast (ui/widgets/toast.py) instead.

A QDialog's `exec()` spins a nested event loop, so timers keep firing
underneath it. Never open one from inside a recurring
tick — post it with `QTimer.singleShot(0, ...)` (see QueueTab._show_errors)."""
import os
import uuid

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core import formats
from core.utilities import probe_media
from ui import scale
from ui import theme as T
from ui.widgets.controls import CheckBox, ScaledLabel, ScaledLineEdit, button, button_width_for
from ui.widgets.panels import ASSETS
from ui.widgets.tracklist import TrackListBox, describe_stream, row_label
from ui.workers import run_async

_DIALOG_WIDTH = 400
_BORDER = 2     # the outline's width, reference px
_RADIUS = 8     # the panel's corner radius, reference px


class MessageDialog(QDialog):
    """A bold title, a wrapped message, an optional single-line entry, and one
    or two buttons. The FIRST button is the affirmative one (primary); the
    rest are declines (secondary). Enter confirms; Escape (and Alt+F4) count
    as declining, so a dismissed confirmation can never destroy work.
    `.result_label` is the pressed button's label or None.

    **Borderless**: no OS title bar or frame, like the app's own Borderless
    window mode. It paints its own rounded panel (the window colour, outlined
    in the theme's primary) over a translucent window, and — with no title bar
    to grab — a press on any part of it that a child didn't take drags it
    (`startSystemMove`).

    A subclass with a body of its own and nothing to say above it sets
    `SHOW_HEADER = False`: no bold title and no message are built (the window
    title is still set, for the taskbar)."""

    SHOW_HEADER = True
    WIDTH = _DIALOG_WIDTH        # reference px; a dialog with a lot on its button row is wider

    def __init__(self, parent, title, message, buttons=("OK",), entry=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Styled here, not left to the window's own sheets: a window restyles
        # only what's on screen when the scale or theme changes (see
        # `MainWindow._restyle`), and a dialog built later must not inherit a
        # stale application-level sheet. Its `QDialog` background is cleared:
        # `paintEvent` draws the rounded panel, and a square sheet fill would
        # show at the corners.
        self.setStyleSheet(T.stylesheet() + "QDialog { background: transparent; }")
        self.setWindowTitle(title)
        icon = os.path.join(ASSETS, "llama.ico")
        if os.path.exists(icon):
            self.setWindowIcon(QIcon(icon))
        self.setModal(True)
        scale.fixed(self, w=self.WIDTH)
        self.result_label = None
        self._buttons = buttons

        body = QVBoxLayout(self)
        scale.margins(body, 20, 18, 20, 14)
        body.setSpacing(0)
        self.message_label = None
        if self.SHOW_HEADER:
            heading = ScaledLabel(title)
            heading.setProperty("role", "dialogTitle")
            body.addWidget(heading)
            scale.spacer(body, 6)
            # A stock QLabel, not ScaledLabel: real, selectable text (drag to select, Ctrl+A,
            # Ctrl+C, a right-click Copy menu) needs Qt's own text control, which only ever
            # sees what Qt itself painted — a ScaledLabel's custom-scaled painter draws
            # somewhere else, so its hit-testing would be wrong at any scale but 1.0. Safe
            # here specifically because a dialog rebuilds its whole stylesheet fresh on every
            # open (`T.stylesheet()` above), already baked to the current scale, and a modal
            # dialog can't be live-resized after that — the one case a plain QLabel doesn't
            # need ScaledLabel's continuous-rescale machinery at all. The title stays a
            # ScaledLabel: its role's stylesheet size is a *reference* px value only ScaledLabel
            # reinterprets, so a native QLabel would render it unscaled (correct only at 1.0x).
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
            row.addWidget(btn)
        body.addLayout(row)

    def _build_extra(self, body):
        """Hook for subclasses that need more than a message."""

    def _build_leading_buttons(self, row):
        """Hook: widgets for the *left* end of the button row (the standard buttons sit
        at the right, after a stretch)."""

    def paintEvent(self, _event):
        """The rounded, outlined panel a frameless window doesn't get for free."""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        border = scale.fpx(_BORDER)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(border / 2, border / 2, -border / 2, -border / 2),
                            scale.fpx(_RADIUS), scale.fpx(_RADIUS))
        p.fillPath(path, T.theme.color("window"))
        p.setPen(QPen(T.theme.color("primary"), border))
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


class CountdownDialog(MessageDialog):
    """A confirmation that goes ahead by itself: `message` (with `{n}` standing
    for the seconds left) counts down once a second and the dialog answers
    "Now" at zero. The first button ("Now") acts immediately, Cancel — and
    Escape — call it off."""

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
    """True when the countdown ran out or "Now" was pressed, False when it was
    cancelled."""
    return CountdownDialog(parent, title, message, seconds, now_label).show_modal() == now_label


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


# Audio-only, built off the app's own audio-extension list (same as Muxing's Add Stream(s));
# "All Files" so an audio track inside a video file can be picked too.
_AUDIO_BROWSE_FILTER = "Audio Files (%s);;All Files (*.*)" % " ".join(
    "*" + ext for ext in sorted(formats.AUDIO_EXTENSIONS))
_PICKER_LIST_HEIGHT = 150     # reference px: room for about five rows before it scrolls


class AudioStreamPickerDialog(MessageDialog):
    """Encoding's "Choose Stream(s)": nothing in it but the tracks — a
    `TrackListBox` (one checkbox per audio stream, ticked = included in the
    output, drag a row to reorder), then **one row of buttons** — Add Stream(s),
    Remove Stream(s), OK, Cancel, left to right (the first two at the left edge, the
    standard two at the right). No title, no explanation.

    It edits a *copy* of the list, so Cancel discards everything — ticks, added
    and removed tracks, the order. Rows are the same shape of entry Muxing's
    boxes use, `{"id", "source", "file", "index", "stream", "name"}`, so both
    label them with `tracklist.row_label`. Add Stream(s) browses another file,
    probes it off the GUI thread and appends its audio stream(s) (a file with
    several asks which, via `ExternalStreamPickerDialog`) ticked, as in Muxing;
    Remove Stream(s) takes every ticked row out of the list, the source file's
    own included. The track numbers follow the order, which is the output's.

    OK gives `chosen` (the ticked ids) and `result_entries` (the list as it now
    is); with rows but none ticked, the first is ticked instead of closing — "no
    audio" is Strip Audio's job. Cancel/Escape gives None."""

    SHOW_HEADER = False
    WIDTH = 500      # one row holds Add, Remove, OK and Cancel; 400 was two buttons short

    def __init__(self, parent, entries, included, start_dir=""):
        self._entries = list(entries)
        self._initial_checked = set(included)
        self._start_dir = start_dir  # where Add Stream(s)'s file dialog opens (the tab's output folder)
        self._finished = False       # an Add Stream(s) probe landing after OK/Cancel is dropped
        self.chosen = None
        self.result_entries = None
        super().__init__(parent, "Choose Audio Streams", "", buttons=("OK", "Cancel"))

    def _build_extra(self, body):
        self.box = TrackListBox()
        scale.fixed(self.box, h=_PICKER_LIST_HEIGHT)
        self.box.reordered.connect(self._on_reordered)
        body.addWidget(self.box)
        self._refresh(self._initial_checked)

    def _build_leading_buttons(self, row):
        """Add Stream(s) then Remove Stream(s), on the left of the one bottom row
        (OK and Cancel follow at the right)."""
        add_btn = button("Add Stream(s)", width=button_width_for(["Add Stream(s)"]))
        add_btn.clicked.connect(self._add_stream)
        row.addWidget(add_btn)
        remove_btn = button("Remove Stream(s)", role="danger", width=button_width_for(["Remove Stream(s)"]))
        remove_btn.clicked.connect(self._remove_streams)
        row.addWidget(remove_btn)

    def _refresh(self, checked=None):
        """Shows `self._entries` in the box, numbered by position; `checked` (default:
        whatever is ticked now) says which rows are ticked."""
        if checked is None:
            checked = set(self.box.checked_ids())
        items = [{"id": entry["id"], "label": row_label("audio", entry, number)}
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
        path, _ = QFileDialog.getOpenFileName(self, "Select Audio Source", self._start_dir, _AUDIO_BROWSE_FILTER)
        if path:
            run_async(probe_media, lambda info: self._stream_probed(path, info), path)

    def _stream_probed(self, path, info):
        """The browsed-in file's probe landed: append its audio stream(s)."""
        if self._finished:
            return
        streams = (info or {}).get("audio_streams") or []
        if not streams:
            show_message(self, "No Matching Streams",
                         f"\u201c{os.path.basename(path)}\u201d has no audio streams to add.")
            return
        if len(streams) > 1:
            picked = pick_external_streams(self, "audio", streams, lambda s: describe_stream("audio", s))
            if picked is None:
                return
            streams = [s for s in streams if s["index"] in picked]
        name = os.path.basename(path.replace("\\", "/"))
        added = [{"id": f"ext:{uuid.uuid4().hex[:8]}", "source": "external", "file": path,
                  "index": stream["index"], "stream": stream, "name": name}
                 for stream in streams]
        self._entries += added
        self._refresh(set(self.box.checked_ids()) | {entry["id"] for entry in added})
        # The new rows are at the bottom: bring them into view once the list has laid out.
        bar = self.box.scroll.verticalScrollBar()
        QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))

    def _dismiss(self, choice):
        if choice == "OK":
            chosen = set(self.box.checked_ids())
            if not chosen and self.box.item_ids():
                self.box.set_checked(self.box.item_ids()[0], True)
                return
            self.chosen = chosen
            self.result_entries = list(self._entries)
        self._finished = True
        super()._dismiss(choice)


def choose_audio_streams(parent, entries, included, start_dir=""):
    """Opens the picker on `entries` (ticked = `included`, a set of ids), its Add
    Stream(s) browsing from `start_dir`; `(entries, chosen ids)` as edited, or None
    if cancelled."""
    dialog = AudioStreamPickerDialog(parent, entries, included, start_dir)
    dialog.show_modal()
    if dialog.chosen is None:
        return None
    return dialog.result_entries, dialog.chosen


class ExternalStreamPickerDialog(MessageDialog):
    """Muxing's "Add Stream": shown only once a browsed-in file turns out to
    have more than one track of the requested kind (a single match is added
    straight away, no dialog needed). One checkbox per track, all unchecked
    to start — unlike `AudioStreamPickerDialog`, there's no "already
    included" set to pre-check, since every row here is brand new. OK/"Add"
    never returns an empty set; Cancel/Escape returns None."""

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
    """Opens the picker for a file just browsed in via "Add Stream"; the
    chosen index set, or None if cancelled. `describe(stream)` renders one
    row's label."""
    dialog = ExternalStreamPickerDialog(parent, kind, streams, describe)
    dialog.show_modal()
    return getattr(dialog, "chosen", None)
