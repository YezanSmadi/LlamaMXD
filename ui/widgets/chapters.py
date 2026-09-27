# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""`ChapterEditor`: the Chapters sub-tab Muxing and Encoding share. The source's chapters in an
editable list: add one at a time, rename or remove the ticked ones, undo / redo, or strip them
all. A list left as the source had it is left to ffmpeg; an edited one is written by the job."""
import uuid

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ui import scale
from ui.scale import px
from ui.widgets.controls import IconButton, button, button_width_for, labeled, set_enabled
from ui.widgets.dialogs import ask_text, show_message
from ui.widgets.timespinner import TimeSpinner
from ui.widgets.toggles import CheckBox
from ui.widgets.tooltip import tip
from ui.widgets.tracklist import TrackListBox

_HISTORY_LIMIT = 50

_LIST_TIP = "The output's chapters, in time order. Tick chapters to rename or remove them."
_ADD_TIP = "Adds a chapter starting at the time set under Add At, and asks for its name."
_RENAME_TIP = "Renames each ticked chapter, one at a time."
_REMOVE_TIP = "Removes every ticked chapter. Undo brings them back."
_UNDO_TIP = "Undoes the last Add, Rename or Remove."
_REDO_TIP = "Redoes what Undo just took back."
_STRIP_TIP = "Leaves every chapter out of the output."


def _hms(seconds):
    seconds = int(seconds or 0)
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


class ChapterEditor(QWidget):
    """The Chapters page. `load(info)` seeds it from a new probe; `refresh(has_file)` is its
    part of the tab's constraint pass; `gather()` / `apply()` are its settings. `changed` fires on
    every user edit. `overview_height` gives the height the list takes (Overview's)."""

    changed = Signal()

    def __init__(self, dialog_parent, overview_height, parent=None):
        super().__init__(parent)
        self._dialog_parent = dialog_parent
        self._chapters = []        # [{"id", "start", "title"}], by start; entries are never mutated
        self._source = []          # the source's own, for "was this edited"
        self._duration = None
        self._info = None
        self._history = {"undo": [], "redo": []}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        scale.spacing(rl, 10)
        rl.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        outer.addWidget(row)

        self.box = TrackListBox(min_width=200, reorderable=False, new_checked=False, empty_text="No chapters")
        self.box.changed.connect(self.changed)
        tip(self.box, _LIST_TIP)
        rl.addWidget(self.box, 1)

        # Add At + Add Chapter.
        add_col = QWidget()
        al = QVBoxLayout(add_col)
        al.setContentsMargins(0, 0, 0, 0)
        scale.spacing(al, 4)
        self.at_spinner = TimeSpinner()
        at_box, self.at_label = labeled("Add At:", self.at_spinner)
        al.addWidget(at_box)
        self.add_btn = button("Add Chapter", width=button_width_for(["Add Chapter"]))
        self.add_btn.clicked.connect(self._add)
        tip(self.add_btn, _ADD_TIP)
        al.addWidget(self.add_btn)
        rl.addWidget(add_col, 0, Qt.AlignBottom)

        # Rename / Remove, then Undo / Redo with Strip.
        edit_col = QWidget()
        el = QVBoxLayout(edit_col)
        el.setContentsMargins(0, 0, 0, 0)
        scale.spacing(el, 4)
        width = button_width_for(["Rename", "Remove Chapter(s)"])
        self.rename_btn = button("Rename", width=width)
        self.rename_btn.clicked.connect(self._rename)
        tip(self.rename_btn, _RENAME_TIP)
        el.addWidget(self.rename_btn)
        self.remove_btn = button("Remove Chapter(s)", role="danger", width=width)
        self.remove_btn.clicked.connect(self._remove)
        tip(self.remove_btn, _REMOVE_TIP)
        el.addWidget(self.remove_btn)
        history = QWidget()
        hl = QHBoxLayout(history)
        hl.setContentsMargins(0, 0, 0, 0)
        scale.spacing(hl, 4)
        hl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        half = (width - 4) // 2
        self.undo_btn = IconButton("undo", role="compact", width=half, height=24)
        self.undo_btn.clicked.connect(lambda: self._travel("undo", "redo"))
        tip(self.undo_btn, _UNDO_TIP)
        hl.addWidget(self.undo_btn)
        self.redo_btn = IconButton("redo", role="compact", width=half, height=24)
        self.redo_btn.clicked.connect(lambda: self._travel("redo", "undo"))
        tip(self.redo_btn, _REDO_TIP)
        hl.addWidget(self.redo_btn)
        scale.spacer(hl, 4)
        self.strip_check = CheckBox("Strip Chapters", color_key="stop")
        self.strip_check.clicked.connect(self.changed)
        tip(self.strip_check, _STRIP_TIP)
        hl.addWidget(self.strip_check)
        el.addWidget(history)
        rl.addWidget(edit_col, 0, Qt.AlignBottom)

        # The list takes Overview's height, so this page never grows past it (a taller page
        # would shrink the preview).
        scale.bind_after(self.box, lambda: self.box.setFixedHeight(max(px(92), overview_height())))

    # ------------------------------------------------------------------ #
    #  State
    # ------------------------------------------------------------------ #
    def load(self, info):
        """A new probe result: its chapters become the list, and the history goes."""
        if info is self._info:
            return
        self._info = info
        self._duration = info.get("duration")
        self._source = [{"id": f"src:{n}", "start": chapter["start"], "title": chapter["title"] or ""}
                        for n, chapter in enumerate(info.get("chapter_list") or [])]
        self._chapters = list(self._source)
        self._history = {"undo": [], "redo": []}

    def refresh(self, has_file):
        """Rows, labels and enabled state from the list. Returns whether chapters are stripped."""
        self.box.set_items([{"id": chapter["id"], "label": self._label(n, chapter)}
                            for n, chapter in enumerate(self._chapters, start=1)])
        stripped = self.strip_check.isChecked()
        live = has_file and not stripped
        has_rows = live and bool(self._chapters)
        self.box.setEnabled(has_rows)
        set_enabled(self.at_spinner, self.at_label, live)
        self.add_btn.setEnabled(live)
        self.rename_btn.setEnabled(has_rows)
        self.remove_btn.setEnabled(has_rows)
        self.undo_btn.setEnabled(live and bool(self._history["undo"]))
        self.redo_btn.setEnabled(live and bool(self._history["redo"]))
        self.strip_check.setEnabled(has_file)
        return stripped

    @staticmethod
    def _label(number, chapter):
        return "  ·  ".join([f"Chapter {number}", _hms(chapter["start"]), chapter["title"] or "—"])

    def edited(self):
        """Whether the list differs from the source's."""
        key = lambda chapters: [(round(c["start"], 3), c["title"]) for c in chapters]
        return key(self._chapters) != key(self._source)

    def gather(self):
        """This page's settings keys (`chapters` None when unedited: ffmpeg copies the source's)."""
        return {
            "chapters": [{"start": c["start"], "title": c["title"]} for c in self._chapters] if self.edited() else None,
            "strip_chapters": self.strip_check.isChecked(),
            "source_duration": self._duration,
            "source_has_chapters": bool(self._source),
        }

    def apply(self, settings):
        """Only the strip flag is a recipe key."""
        if "strip_chapters" in settings:
            self.strip_check.setChecked(bool(settings["strip_chapters"]))

    # ------------------------------------------------------------------ #
    #  Edits (each one undoable)
    # ------------------------------------------------------------------ #
    def _edit(self, chapters):
        self._history["undo"].append(list(self._chapters))
        del self._history["undo"][:-_HISTORY_LIMIT]
        self._history["redo"].clear()
        self._chapters = sorted(chapters, key=lambda chapter: chapter["start"])
        self.changed.emit()

    def _travel(self, take, keep):
        if not self._history[take]:
            return
        self._history[keep].append(list(self._chapters))
        self._chapters = self._history[take].pop()
        self.changed.emit()

    def _ticked(self):
        ticked = set(self.box.checked_ids())
        return [chapter for chapter in self._chapters if chapter["id"] in ticked]

    def _add(self):
        at = self.at_spinner.seconds()
        if self._duration and at >= self._duration:
            show_message(self._dialog_parent, "Past the End",
                         f"This file is only {_hms(self._duration)} long. Set Add At to a time inside it.")
            return
        if any(int(chapter["start"]) == at for chapter in self._chapters):
            show_message(self._dialog_parent, "Chapter Already There",
                         f"A chapter already starts at {_hms(at)}. Pick another time, or rename that one.")
            return
        number = 1 + sum(1 for chapter in self._chapters if chapter["start"] < at)
        title = ask_text(self._dialog_parent, "Add Chapter", f"Name the chapter starting at {_hms(at)}.",
                         initial=f"Chapter {number}", confirm="Add")
        if title is None:
            return
        self._edit(self._chapters + [{"id": f"new:{uuid.uuid4().hex[:8]}", "start": float(at), "title": title}])

    def _rename(self):
        ticked = self._ticked()
        if not ticked:
            show_message(self._dialog_parent, "Nothing to Rename",
                         "Tick the chapter(s) you want to rename, then press Rename again.")
            return
        names = {}
        for chapter in ticked:
            title = ask_text(self._dialog_parent, "Rename Chapter",
                             f"A new name for the chapter at {_hms(chapter['start'])}.", initial=chapter["title"])
            if title is None:
                return      # cancelled: nothing changes
            names[chapter["id"]] = title
        self._edit([dict(chapter, title=names[chapter["id"]]) if chapter["id"] in names else chapter
                    for chapter in self._chapters])

    def _remove(self):
        ticked = {chapter["id"] for chapter in self._ticked()}
        if not ticked:
            show_message(self._dialog_parent, "Nothing to Remove",
                         "Tick the chapter(s) you want removed, then press Remove Chapter(s) again.")
            return
        self._edit([chapter for chapter in self._chapters if chapter["id"] not in ticked])
