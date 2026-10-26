# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""The Add/Edit popups: a video or audio track's Default flag and a subtitle track's language and
flags (each plus adding another track), and a chapter's time and name (plus adding a new one). Each works on a copy of what it is given and only
OK/the dialog's own Add hands a result back, so Cancel leaves everything as it was. Both show an
em-dash and grey their fields while the list is empty — the popup is still how you add the first
one."""
import os
import uuid

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget

from core import formats
from core.probe import probe_media
from ui import scale
from ui import theme as T
from ui.tips import (DEFAULT_TIP, FORCED_TIP, LANGUAGE_TIP, STREAM_DEFAULT_TIP, STREAM_TRACK_TIP,
                     SUBTITLE_TRACK_TIP)
from ui.widgets.controls import button, button_width_for, field_label, labeled, set_enabled
from ui.widgets.dialogs import BROWSE_FILTERS, MessageDialog, pick_external_streams, show_message
from ui.widgets.dropdown import NO_OPTION, Dropdown
from ui.widgets.text import ScaledLabel, ScaledLineEdit
from ui.widgets.timespinner import TimeSpinner
from ui.widgets.toggles import CheckBox
from ui.widgets.tooltip import tip
from ui.widgets.tracklist import describe_stream
from ui.workers import run_async

_CONTENT_WIDTH = 360      # reference px: the dialog's width less its margins
_NAME_CHARS = 18          # how much of a chapter's name its dropdown entry shows


def _hms(seconds):
    seconds = int(seconds or 0)
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _row(spacing=8, packed=True):
    """A plain horizontal row widget + its layout: `packed` keeps the controls at their own width
    at the left, otherwise a child added with a stretch fills the rest."""
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    scale.spacing(layout, spacing)
    if packed:
        layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
    return widget, layout


def _problem_label():
    """The line under a dialog's fields that says why the action is greyed out (kept a line tall
    so the dialog doesn't jump when it appears)."""
    label = ScaledLabel(" ")
    label.setProperty("role", "error")
    return label


class _Divider(QWidget):
    """A thin rule in the theme's accent colour (the same one a popup's own border uses),
    separating a popup's edit section (an existing entry's fields) from its add-another section
    below."""

    def __init__(self, parent=None):
        super().__init__(parent)
        scale.fixed(self, h=2)
        T.theme.changed.connect(self.update)

    def paintEvent(self, _event):
        p = QPainter(self)
        scale.begin(p)
        w, h = scale.ref_size(self)
        p.setPen(QPen(T.theme.color("theme_accent"), 2))
        p.drawLine(0, h / 2, w, h / 2)


def _named_entry(text, on_edited):
    """A labelled name field taking the row's whole width; `on_edited` hears the user's typing."""
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    scale.spacing(layout, 1)
    entry = ScaledLineEdit(text)
    scale.fixed(entry, h=30)        # as tall as the time field beside it
    entry.textEdited.connect(on_edited)
    layout.setAlignment(Qt.AlignTop)
    layout.addWidget(field_label("Name:"), 0, Qt.AlignLeft)
    layout.addWidget(entry)
    return box, entry


# --------------------------------------------------------------------------- #
#  Add/Edit Subtitles
# --------------------------------------------------------------------------- #
class EditSubtitlesDialog(MessageDialog):
    """Muxing's Add/Edit Subs: a Track dropdown (— while there are none), that track's Language,
    Default and Forced, and a leading Add button that browses another file and appends its
    stream(s), selecting the newest one. Edits a copy of the entries (Default clears every other
    track's, as only one can be the default); `result_entries` is that copy after OK, None after
    Cancel."""

    def __init__(self, parent, entries, start_dir=""):
        self._entries = [dict(entry) for entry in entries]
        self._start_dir = start_dir       # where Add's file dialog opens (the tab's output folder)
        self._finished = False            # an Add probe landing after OK/Cancel is dropped
        self._current = self._entries[0]["id"] if self._entries else None
        self._track_ids = {}              # the Track dropdown's label -> entry id
        self.result_entries = None
        super().__init__(parent, "Add/Edit Subtitles", "Choose a track to edit, or add another.",
                         buttons=("OK", "Cancel"))
        self._load()

    def _build_leading_buttons(self, row):
        self.add_btn = button("Browse", width=button_width_for(["Browse"]))
        self.add_btn.clicked.connect(self._add_stream)
        row.addWidget(self.add_btn)

    def _build_extra(self, body):
        scale.spacer(body, 12)
        top, tl = _row()
        self.track_menu = Dropdown([NO_OPTION], width=Dropdown.width_for(["Track 99 (SRT)"]))
        self.track_menu.picked.connect(self._on_track_pick)
        tip(self.track_menu, SUBTITLE_TRACK_TIP)
        box, self.track_label = labeled("Track:", self.track_menu)
        tl.addWidget(box)
        self.language_menu = Dropdown([NO_OPTION], width=Dropdown.width_for(
            list(formats.SUBTITLE_LANGUAGES.values())))
        self.language_menu.picked.connect(self._on_language_pick)
        tip(self.language_menu, LANGUAGE_TIP)
        box, self.language_label = labeled("Language:", self.language_menu)
        tl.addWidget(box)
        body.addWidget(top)
        scale.spacer(body, 10)
        flags, fl = _row(12)
        self.default_check = CheckBox("Default")
        self.default_check.clicked.connect(lambda: self._set_flag("default", self.default_check))
        tip(self.default_check, DEFAULT_TIP)
        fl.addWidget(self.default_check)
        self.forced_check = CheckBox("Forced")
        self.forced_check.clicked.connect(lambda: self._set_flag("forced", self.forced_check))
        tip(self.forced_check, FORCED_TIP)
        fl.addWidget(self.forced_check)
        body.addWidget(flags)

    def _entry(self):
        return next((entry for entry in self._entries if entry["id"] == self._current), None)

    def _refresh_track_menu(self):
        self._track_ids = {f"Track {n} ({entry['stream'].get('codec') or '?'})": entry["id"]
                           for n, entry in enumerate(self._entries, start=1)}
        self.track_menu.set_values(list(self._track_ids) or [NO_OPTION])
        label = next((label for label, entry_id in self._track_ids.items() if entry_id == self._current), NO_OPTION)
        self.track_menu.set(label)

    def _load(self):
        """Show the chosen track's values, or grey everything out with none to show."""
        self._refresh_track_menu()
        entry = self._entry()
        editable = entry is not None
        if editable:
            languages = list(formats.SUBTITLE_LANGUAGES.values())
            name = formats.language_name(entry.get("language"))
            if name not in languages:
                languages.append(name)
            self.language_menu.set_values(languages)
            self.language_menu.set(name)
        else:
            self.language_menu.set_values([NO_OPTION])
        self.default_check.setChecked(bool(entry and entry.get("default")))
        self.forced_check.setChecked(bool(entry and entry.get("forced")))
        set_enabled(self.track_menu, self.track_label, editable)
        set_enabled(self.language_menu, self.language_label, editable)
        self.default_check.setEnabled(editable)
        self.forced_check.setEnabled(editable)

    def _on_track_pick(self, label):
        self._current = self._track_ids.get(label, self._current)
        self._load()

    def _on_language_pick(self, name):
        entry = self._entry()
        if entry is not None:
            entry["language"] = next((code for code, full in formats.SUBTITLE_LANGUAGES.items() if full == name), name)

    def _set_flag(self, flag, check):
        entry = self._entry()
        if entry is None:
            return
        entry[flag] = check.isChecked()
        if flag == "default" and entry[flag]:
            for other in self._entries:
                if other is not entry:
                    other["default"] = False

    def _add_stream(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Subtitle Source", self._start_dir,
                                              BROWSE_FILTERS["subtitle"])
        if path:
            run_async(probe_media, lambda info: self._stream_probed(path, info), path)

    def _stream_probed(self, path, info):
        """The browsed-in file's probe landed: append its stream(s) and select the newest."""
        if self._finished:
            return
        streams = [s for s in (info or {}).get("subtitle_streams") or [] if s.get("codec_name") in formats.FFPROBE_SUBTITLE]
        if not streams:
            show_message(self, "No Matching Streams", f"“{os.path.basename(path)}” has no subtitle streams to add.")
            return
        if len(streams) > 1:
            chosen = pick_external_streams(self, "subtitle", streams, lambda s: describe_stream("subtitle", s))
            if chosen is None:
                return
            streams = [s for s in streams if s["index"] in chosen]
        name = os.path.basename(path.replace("\\", "/"))
        added = [{"id": f"ext:{uuid.uuid4().hex[:8]}", "source": "external", "file": path, "index": stream["index"],
                 "stream": stream, "name": name, "language": formats.language_code(stream.get("language")),
                 "default": bool(stream.get("default")), "forced": bool(stream.get("forced")),
                 "start_time": (info or {}).get("start_time")}
                for stream in streams]
        self._entries += added
        self._current = added[0]["id"]
        self._load()

    def _dismiss(self, choice):
        if choice == "OK":
            self.result_entries = self._entries
        self._finished = True
        super()._dismiss(choice)


def edit_subtitles(parent, entries, start_dir=""):
    """Open Add/Edit Subs on the subtitle `entries`, Add browsing from `start_dir`; the edited
    copy of the list, or None if cancelled."""
    dialog = EditSubtitlesDialog(parent, entries, start_dir)
    dialog.show_modal()
    return dialog.result_entries


# --------------------------------------------------------------------------- #
#  Add/Edit Video / Audio
# --------------------------------------------------------------------------- #
class EditStreamsDialog(MessageDialog):
    """Muxing's Add/Edit Video and Add/Edit Audio: a Track dropdown (— while there are none), that
    track's Default flag, and a leading Browse button that adds the stream(s) of another file,
    selecting the newest. Edits a copy of the entries (Default clears every other track's: one
    default per kind); `result_entries` is that copy after OK, None after Cancel."""

    def __init__(self, parent, kind, entries, start_dir=""):
        self._kind = kind
        self._entries = [dict(entry) for entry in entries]
        self._start_dir = start_dir       # where Browse's file dialog opens (the tab's output folder)
        self._finished = False            # a Browse probe landing after OK/Cancel is dropped
        self._current = self._entries[0]["id"] if self._entries else None
        self._track_ids = {}              # the Track dropdown's label -> entry id
        self.result_entries = None
        super().__init__(parent, f"Add/Edit {kind.capitalize()}", "Choose a track to edit, or add another.",
                         buttons=("OK", "Cancel"))
        self._load()

    def _build_leading_buttons(self, row):
        self.add_btn = button("Browse", width=button_width_for(["Browse"]))
        self.add_btn.clicked.connect(self._add_stream)
        row.addWidget(self.add_btn)

    def _build_extra(self, body):
        scale.spacer(body, 12)
        top, tl = _row()
        self.track_menu = Dropdown([NO_OPTION], width=Dropdown.width_for(["Track 99 (Dolby TrueHD)"]))
        self.track_menu.picked.connect(self._on_track_pick)
        tip(self.track_menu, STREAM_TRACK_TIP)
        box, self.track_label = labeled("Track:", self.track_menu)
        tl.addWidget(box)
        self.default_check = CheckBox("Default")
        self.default_check.clicked.connect(self._set_default)
        tip(self.default_check, STREAM_DEFAULT_TIP)
        # Level with the dropdown, not its caption: the box's bottom edge, lifted to the dropdown's centre.
        holder = QWidget()
        hl = QVBoxLayout(holder)
        scale.margins(hl, 0, 0, 0, 2)
        hl.addWidget(self.default_check)
        tl.addWidget(holder, 0, Qt.AlignBottom)
        body.addWidget(top)

    def _entry(self):
        return next((entry for entry in self._entries if entry["id"] == self._current), None)

    def _refresh_track_menu(self):
        self._track_ids = {
            f"Track {n} ({entry['stream'].get('codec') or entry['stream'].get('codec_name') or '?'})": entry["id"]
            for n, entry in enumerate(self._entries, start=1)}
        self.track_menu.set_values(list(self._track_ids) or [NO_OPTION])
        label = next((label for label, entry_id in self._track_ids.items() if entry_id == self._current), NO_OPTION)
        self.track_menu.set(label)

    def _load(self):
        """Show the chosen track's flag, or grey everything out with none to show."""
        self._refresh_track_menu()
        entry = self._entry()
        self.default_check.setChecked(bool(entry and entry.get("default")))
        set_enabled(self.track_menu, self.track_label, entry is not None)
        self.default_check.setEnabled(entry is not None)

    def _on_track_pick(self, label):
        self._current = self._track_ids.get(label, self._current)
        self._load()

    def _set_default(self):
        entry = self._entry()
        if entry is None:
            return
        entry["default"] = self.default_check.isChecked()
        if entry["default"]:
            for other in self._entries:
                if other is not entry:
                    other["default"] = False

    def _add_stream(self):
        path, _ = QFileDialog.getOpenFileName(self, f"Select {self._kind.capitalize()} Source", self._start_dir,
                                              BROWSE_FILTERS[self._kind])
        if path:
            run_async(probe_media, lambda info: self._stream_probed(path, info), path)

    def _stream_probed(self, path, info):
        """The browsed-in file's probe landed: append its stream(s) and select the newest."""
        if self._finished:
            return
        kind = self._kind
        streams = (info or {}).get(f"{kind}_streams") or []
        if not streams:
            show_message(self, "No Matching Streams", f"\u201c{os.path.basename(path)}\u201d has no {kind} streams to add.")
            return
        if len(streams) > 1:
            chosen = pick_external_streams(self, kind, streams, lambda s: describe_stream(kind, s))
            if chosen is None:
                return
            streams = [s for s in streams if s["index"] in chosen]
        name = os.path.basename(path.replace("\\", "/"))
        added = [{"id": f"ext:{uuid.uuid4().hex[:8]}", "source": "external", "file": path, "index": stream["index"],
                  "stream": stream, "name": name, "default": bool(stream.get("default"))}
                 for stream in streams]
        self._entries += added
        self._current = added[0]["id"]
        self._load()

    def _dismiss(self, choice):
        if choice == "OK":
            self.result_entries = self._entries
        self._finished = True
        super()._dismiss(choice)


def edit_streams(parent, kind, entries, start_dir=""):
    """Open Add/Edit Video or Audio on the `kind` `entries`, Browse starting at `start_dir`; the
    edited copy of the list, or None if cancelled."""
    dialog = EditStreamsDialog(parent, kind, entries, start_dir)
    dialog.show_modal()
    return dialog.result_entries


# --------------------------------------------------------------------------- #
#  Add/Edit Chapters
# --------------------------------------------------------------------------- #
class AddEditChaptersDialog(MessageDialog):
    """Add/Edit Chapters: a dropdown of every chapter (— while there are none), then the chosen
    one's Time and Name; a separate Add At + Name + Add appends a new one and selects it (its name
    follows Add At, like a new chapter's name always has, until one is typed). Edits a copy of
    every chapter; OK's `result_chapters` is that copy (added ones included), None after Cancel. A
    time left alone on an existing chapter keeps its exact start, since the spinner only shows
    whole seconds."""

    def __init__(self, parent, chapters, duration):
        self._chapters = {c["id"]: dict(c) for c in chapters}
        self._order = [c["id"] for c in chapters]      # display / time order
        self._duration = duration
        self._current = self._order[0] if self._order else None
        self._labels = {}
        self._new_typed = False       # the new chapter's name follows Add At until one is typed
        self.result_chapters = None
        super().__init__(parent, "Add/Edit Chapter(s)", "Choose a chapter to edit, or add a new one.",
                         buttons=("OK", "Cancel"))
        self._load()

    def _build_extra(self, body):
        scale.spacer(body, 12)
        self.chapter_menu = Dropdown([NO_OPTION], width=_CONTENT_WIDTH)
        self.chapter_menu.picked.connect(self._on_chapter_pick)
        box, self.chapter_label = labeled("Chapter:", self.chapter_menu)
        body.addWidget(box)
        scale.spacer(body, 10)
        top, tl = _row(10, packed=False)
        self.time_spinner = TimeSpinner()
        self.time_spinner.valueChanged.connect(self._on_time)
        box, self.time_label = labeled("Time:", self.time_spinner)
        tl.addWidget(box)
        name_box, self.name_entry = _named_entry("", self._on_name)
        tl.addWidget(name_box, 1)
        body.addWidget(top)
        scale.spacer(body, 8)
        self.edit_problem = _problem_label()
        body.addWidget(self.edit_problem)
        scale.spacer(body, 10)
        body.addWidget(_Divider())
        scale.spacer(body, 10)
        add_row, al = _row(10, packed=False)
        self.at_spinner = TimeSpinner(self._first_free_second())
        self.at_spinner.valueChanged.connect(self._on_add_time)
        box, _label = labeled("Add At:", self.at_spinner)
        al.addWidget(box)
        new_name_box, self.new_name_entry = _named_entry(self._next_name(self.at_spinner.seconds()), self._on_new_typed)
        al.addWidget(new_name_box, 1)
        self.add_btn = button("Add", width=button_width_for(["Add"]))
        self.add_btn.clicked.connect(self._add)
        al.addWidget(self.add_btn, 0, Qt.AlignBottom)
        body.addWidget(add_row)
        scale.spacer(body, 4)
        self.add_problem = _problem_label()
        body.addWidget(self.add_problem)
        self._check_add()

    def _first_free_second(self):
        taken = {int(c["start"]) for c in self._chapters.values()}
        at = 0
        while at in taken and (not self._duration or at + 1 < self._duration):
            at += 1
        return at

    def _next_name(self, seconds):
        """"Chapter N" for a chapter starting at `seconds`, N being its place among the current
        (possibly already-added-to) list."""
        return f"Chapter {1 + sum(1 for c in self._chapters.values() if c['start'] < seconds)}"

    def _on_new_typed(self, _text):
        self._new_typed = True

    def _on_add_time(self, seconds):
        if not self._new_typed:
            self.new_name_entry.setText(self._next_name(seconds))
        self._check_add()

    def _make_labels(self):
        self._labels = {}
        for n, chapter_id in enumerate(self._order, start=1):
            chapter = self._chapters[chapter_id]
            name = chapter["title"] or "—"
            name = name if len(name) <= _NAME_CHARS else name[:_NAME_CHARS - 1] + "…"
            self._labels[f"Chapter {n}  ·  {_hms(chapter['start'])}  ·  {name}"] = chapter_id
        return self._labels

    def _refresh_menu(self):
        """Re-word the dropdown after an edit and keep the same chapter showing."""
        labels = self._make_labels()
        self.chapter_menu.set_values(list(labels) or [NO_OPTION])
        self.chapter_menu.set(next((label for label, chapter_id in labels.items() if chapter_id == self._current),
                                   NO_OPTION))

    def _load(self):
        """Show the chosen chapter's time and name, or grey everything with none to show."""
        chapter = self._chapters.get(self._current)
        editable = chapter is not None
        if editable:
            self.time_spinner.blockSignals(True)
            self.time_spinner.set_seconds(int(chapter["start"]))
            self.time_spinner.blockSignals(False)
            self.name_entry.setText(chapter["title"])
        else:
            self.name_entry.setText("")
        set_enabled(self.time_spinner, self.time_label, editable)
        self.name_entry.setEnabled(editable)
        self._refresh_menu()
        self._check_edit()

    def _on_chapter_pick(self, label):
        self._current = self._labels.get(label, self._current)
        self._load()

    def _edit_problem(self):
        chapter = self._chapters.get(self._current)
        if chapter is None:
            return None
        seconds = self.time_spinner.seconds()
        if self._duration and seconds >= self._duration:
            return f"This file is only {_hms(self._duration)} long. Pick a time inside it."
        if any(cid != self._current and int(c["start"]) == seconds for cid, c in self._chapters.items()):
            return f"A chapter already starts at {_hms(seconds)}. Pick another time."
        return None

    def _check_edit(self):
        problem = self._edit_problem()
        self.edit_problem.setText(problem or " ")
        self.set_button_enabled("OK", problem is None)

    def _on_time(self, seconds):
        chapter = self._chapters.get(self._current)
        if chapter is not None and self._edit_problem() is None and seconds != int(chapter["start"]):
            chapter["start"] = float(seconds)
            self._refresh_menu()
        self._check_edit()

    def _on_name(self, text):
        if self._current is not None:
            self._chapters[self._current]["title"] = text.strip()
            self._refresh_menu()

    def _add_problem(self):
        seconds = self.at_spinner.seconds()
        if self._duration and seconds >= self._duration:
            return f"This file is only {_hms(self._duration)} long. Pick a time inside it."
        if any(int(c["start"]) == seconds for c in self._chapters.values()):
            return f"A chapter already starts at {_hms(seconds)}. Pick another time."
        return None

    def _check_add(self):
        problem = self._add_problem()
        self.add_problem.setText(problem or " ")
        self.add_btn.setEnabled(problem is None)

    def _add(self):
        if self._add_problem() is not None:
            return
        seconds = self.at_spinner.seconds()
        title = self.new_name_entry.text().strip() or self._next_name(seconds)
        new_id = f"new:{uuid.uuid4().hex[:8]}"
        self._chapters[new_id] = {"id": new_id, "start": float(seconds), "title": title}
        self._order = sorted(self._chapters, key=lambda cid: self._chapters[cid]["start"])
        self._current = new_id
        self._load()
        # Ready for another: the next free second after everything added so far, with a fresh
        # name following it until the user types one of their own again.
        self._new_typed = False
        at = self._first_free_second()
        self.new_name_entry.setText(self._next_name(at))
        self.at_spinner.blockSignals(True)
        self.at_spinner.set_seconds(at)
        self.at_spinner.blockSignals(False)
        self._check_add()

    def _dismiss(self, choice):
        if choice == "OK":
            if self._edit_problem() is not None:
                return
            self.result_chapters = [self._chapters[cid] for cid in self._order]
        super()._dismiss(choice)


def add_edit_chapters(parent, chapters, duration):
    """Open Add/Edit Chapters on `chapters` (`{"id", "start", "title"}`), a file `duration`
    seconds long (or None); the edited copy of every chapter (added ones included), or None if
    cancelled."""
    dialog = AddEditChaptersDialog(parent, chapters, duration)
    dialog.show_modal()
    return dialog.result_chapters
