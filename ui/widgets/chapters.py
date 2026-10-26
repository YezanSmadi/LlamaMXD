# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""`ChapterEditor`: the Chapters sub-tab Muxing and Encoding share. The source's chapters in an
editable, tickable list: add or edit in one popup (`edit_dialogs`), remove the ticked ones, undo /
redo. A ticked chapter is included in the output — deselecting or removing them all is this page's
only "strip" signal, same as Muxing's track boxes; there is no separate Strip checkbox. A list left
exactly as the source had it (every chapter still ticked, nothing renamed) is left to ffmpeg; an
edited one is written by the job."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from ui import scale
from ui.scale import px
from ui.widgets.controls import IconButton, button, button_width_for
from ui.widgets.dialogs import show_message
from ui.widgets.edit_dialogs import add_edit_chapters
from ui.widgets.tooltip import tip
from ui.widgets.tracklist import TrackListBox

_HISTORY_LIMIT = 50

_LIST_TIP = "The output's chapters in time order. Tick which ones to keep and untick or remove all to drop chapters entirely."
_SELECT_ALL_TIP = "Ticks every chapter; includes all of them in the output."
_DESELECT_ALL_TIP = "Unticks every chapter without completely removing any of them."
_ADD_EDIT_TIP = "Opens a window to change a chapter's time or name or add a new chapter."
_REMOVE_TIP = "Removes every ticked chapter. Undo brings them back."
_UNDO_TIP = "Undoes the last add, edit, remove, or change of which chapters are ticked."
_REDO_TIP = "Redoes what Undo just took back."


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
        self._history = {"undo": [], "redo": []}   # {"chapters": [...], "checked": {ids}} snapshots
        self._restore_checked = None    # the ticks an undo / redo puts back, applied by the next refresh
        self._checked_baseline = set()  # ticked ids as of the last refresh: a tick reports after the fact
        self._just_loaded = False       # load() just rebuilt the list: the next refresh() must reset the box

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        scale.spacing(rl, 10)
        rl.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        outer.addWidget(row)

        self.box = TrackListBox(min_width=200, reorderable=False, empty_text="No chapters")
        self.box.changed.connect(self._on_ticked)
        tip(self.box, _LIST_TIP)
        rl.addWidget(self.box, 1)

        # Select / Deselect All, then Add/Edit Chapter(s), Remove Chapter(s), then Undo / Redo —
        # the same four-row shape as Muxing's track panels (see muxing.py's _track_panel).
        col = QWidget()
        cl = QVBoxLayout(col)
        cl.setContentsMargins(0, 0, 0, 0)
        select_spacing = 4      # the column's vertical gap, also between the two icon pairs
        scale.spacing(cl, select_spacing)
        width = button_width_for(["Add/Edit Chapter(s)", "Remove Chapter(s)"])
        select_width = (width - select_spacing) // 2
        top = QWidget()
        top_row = QHBoxLayout(top)
        top_row.setContentsMargins(0, 0, 0, 0)
        scale.spacing(top_row, select_spacing)
        top_row.setAlignment(Qt.AlignLeft)

        def icon_button(icon, tooltip, handler, **size):
            btn = IconButton(icon, role="compact", **size)
            btn.clicked.connect(handler)
            tip(btn, tooltip)
            return btn

        self.select_all_btn = icon_button("select-multiple", _SELECT_ALL_TIP, self._select_all, width=select_width)
        self.deselect_all_btn = icon_button("deselect-multiple", _DESELECT_ALL_TIP, self._deselect_all,
                                            width=select_width)
        for btn in (self.select_all_btn, self.deselect_all_btn):
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            top_row.addWidget(btn)
        cl.addWidget(top)
        self.add_edit_btn = button("Add/Edit Chapter(s)", width=width)
        self.add_edit_btn.clicked.connect(self._add_edit)
        tip(self.add_edit_btn, _ADD_EDIT_TIP)
        cl.addWidget(self.add_edit_btn)
        self.remove_btn = button("Remove Chapter(s)", role="danger", width=width)
        self.remove_btn.clicked.connect(self._remove)
        tip(self.remove_btn, _REMOVE_TIP)
        cl.addWidget(self.remove_btn)
        history = QWidget()
        hl = QHBoxLayout(history)
        hl.setContentsMargins(0, 0, 0, 0)
        scale.spacing(hl, select_spacing)
        hl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.undo_btn = icon_button("undo", _UNDO_TIP, lambda: self._travel("undo", "redo"),
                                    width=select_width, height=24)
        self.redo_btn = icon_button("redo", _REDO_TIP, lambda: self._travel("redo", "undo"),
                                    width=select_width, height=24)
        hl.addWidget(self.undo_btn)
        hl.addWidget(self.redo_btn)
        cl.addWidget(history)
        rl.addWidget(col, 0, Qt.AlignBottom)

        # The list takes Overview's height, so this page never grows past it (a taller page
        # would shrink the preview). Same row shape and budget as Muxing's track panels: a
        # dynamic top row, two 28px rows, one 24px row, three 4px gaps.
        def size_page():
            self.box.setFixedHeight(max(px(92), overview_height()))
            top.setFixedHeight(max(px(22), self.box.height() - 2 * px(28) - px(24) - 3 * px(4)))
        scale.bind_after(self.box, size_page)

    # ------------------------------------------------------------------ #
    #  State
    # ------------------------------------------------------------------ #
    def load(self, info):
        """A new probe result: its chapters become the list (every one ticked by default), and
        the history goes; the next `refresh()` resets the box (a same-numbered chapter from a
        different file must never be mistaken for a carried-over tick)."""
        if info is self._info:
            return
        self._info = info
        self._duration = info.get("duration")
        self._source = [{"id": f"src:{n}", "start": chapter["start"], "title": chapter["title"] or ""}
                        for n, chapter in enumerate(info.get("chapter_list") or [])]
        self._chapters = list(self._source)
        self._history = {"undo": [], "redo": []}
        self._just_loaded = True

    def refresh(self, has_file):
        """Rows, labels and enabled state from the list. Returns whether chapters are stripped
        (there are some, but none are ticked — the same signal Muxing's track boxes use)."""
        self.box.set_items([{"id": chapter["id"], "label": self._label(n, chapter)}
                            for n, chapter in enumerate(self._chapters, start=1)],
                           reset=self._just_loaded, checked=self._restore_checked)
        self._restore_checked = None
        self._just_loaded = False
        self._checked_baseline = set(self.box.checked_ids())
        live = has_file
        has_rows = live and bool(self._chapters)
        # Stripped once the source had chapters at all, whether every one was removed outright
        # or simply left unticked — a fact about the source (self._source), not the current list.
        stripped = bool(self._source) and not self._checked_baseline
        self.box.setEnabled(has_rows)
        # Always live once a file's loaded, even with zero chapters: it's also how you add the first.
        self.add_edit_btn.setEnabled(live)
        self.remove_btn.setEnabled(has_rows)
        self.select_all_btn.setEnabled(has_rows)
        self.deselect_all_btn.setEnabled(has_rows)
        self.undo_btn.setEnabled(live and bool(self._history["undo"]))
        self.redo_btn.setEnabled(live and bool(self._history["redo"]))
        return stripped

    @staticmethod
    def _label(number, chapter):
        return "  ·  ".join([f"Chapter {number}", _hms(chapter["start"]), chapter["title"] or "—"])

    def _included(self):
        """The ticked chapters, in time order."""
        ticked = set(self.box.checked_ids())
        return [chapter for chapter in self._chapters if chapter["id"] in ticked]

    def gather(self):
        """This page's settings keys (`chapters` None only while the ticked set is exactly the
        source's own, unedited: ffmpeg then copies them itself)."""
        included = self._included()
        key = lambda chapters: [(round(c["start"], 3), c["title"]) for c in chapters]
        edited = key(included) != key(self._source)
        return {
            "chapters": [{"start": c["start"], "title": c["title"]} for c in included] if edited else None,
            "strip_chapters": bool(self._source) and not included,
            "source_duration": self._duration,
            "source_has_chapters": bool(self._source),
        }

    def apply(self, settings):
        """A preset's strip preference: untick every chapter on the next refresh — this page's
        only "strip" signal now that there's no checkbox."""
        if settings.get("strip_chapters"):
            self._restore_checked = set()

    # ------------------------------------------------------------------ #
    #  Edits (each one undoable)
    # ------------------------------------------------------------------ #
    def _snapshot(self):
        return {"chapters": list(self._chapters), "checked": set(self.box.checked_ids())}

    def _push_history(self, snapshot=None):
        self._history["undo"].append(snapshot or self._snapshot())
        del self._history["undo"][:-_HISTORY_LIMIT]
        self._history["redo"].clear()

    def _edit(self, chapters):
        self._push_history()
        self._chapters = sorted(chapters, key=lambda chapter: chapter["start"])
        self.changed.emit()

    def _on_ticked(self):
        """A row's checkbox was clicked: an undo step holding the ticks from before the click."""
        self._push_history({"chapters": list(self._chapters), "checked": set(self._checked_baseline)})
        self.changed.emit()

    def _travel(self, take, keep):
        if not self._history[take]:
            return
        self._history[keep].append(self._snapshot())
        snapshot = self._history[take].pop()
        self._chapters = list(snapshot["chapters"])
        self._restore_checked = snapshot["checked"]
        self.changed.emit()

    def _select_all(self):
        if set(self.box.checked_ids()) != set(self.box.item_ids()):     # nothing to undo otherwise
            self._push_history()
            for row_id in self.box.item_ids():
                self.box.set_checked(row_id, True)
        self.changed.emit()

    def _deselect_all(self):
        if self.box.checked_ids():
            self._push_history()
            for row_id in self.box.item_ids():
                self.box.set_checked(row_id, False)
        self.changed.emit()

    def _add_edit(self):
        edited = add_edit_chapters(self._dialog_parent, self._chapters, self._duration)
        if edited is not None and edited != self._chapters:
            self._edit(edited)

    def _remove(self):
        ticked = {chapter["id"] for chapter in self._included()}
        if not ticked:
            show_message(self._dialog_parent, "Nothing to Remove",
                         "Tick the chapter(s) you want removed, then press Remove Chapter(s) again.")
            return
        self._edit([chapter for chapter in self._chapters if chapter["id"] not in ticked])
