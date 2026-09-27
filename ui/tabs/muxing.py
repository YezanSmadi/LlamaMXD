# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Muxing: change a file's container and choose which streams go into it. Nothing is ever
re-encoded, so there are no codec controls, and the container filter runs backwards: the
source's codecs decide which containers it can be remuxed into (`formats.containers_for`), and
a ticked picture subtitle track (PGS, VobSub) narrows them to Matroska. Video, Audio and Subtitles
each list every track (the source's and any added from other files) in an editable, reorderable
`TrackListBox` with undo / redo; Subtitles also edits a track's language and Default / Forced."""
import os
import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QSizePolicy, QVBoxLayout, QWidget

from core import formats
from core.probe import probe_media
from ui import scale
from ui.scale import px
from ui.tabs.media_tab import STRIP_TIP, MediaTab, hms, hrow, set_line_text
from ui.widgets.controls import button, button_width_for, labeled, set_enabled, IconButton
from ui.widgets.dropdown import Dropdown, NO_OPTION
from ui.widgets.toggles import CheckBox
from ui.widgets.dialogs import BROWSE_FILTERS, pick_external_streams, show_message
from ui.widgets.tooltip import tip
from ui.widgets.tracklist import TrackListBox
from ui.widgets.tracklist import describe_stream as _describe_stream
from ui.widgets.tracklist import row_label as _row_label
from ui.workers import run_async

_TRACK_TIP = ("Check as many streams as the output should carry — muxing never "
              "re-encodes them. \"Add Stream(s)\" pulls one in from another file. "
              "Drag a track up or down to reorder it.")
_REMOVE_TIP = ("Removes every checked track from the list, the source file's own included — "
               "the tracks below move up to fill the gap. Undo brings them back.")
_UNDO_TIP = "Undoes the last Add / Remove Stream(s), reorder, or change of which tracks are selected."
_REDO_TIP = "Redoes what Undo just took back."
_SELECT_ALL_TIP = "Checks every track in the box — include all of them in the output."
_DESELECT_ALL_TIP = "Unchecks every track in the box, without removing any of them."
SUBTITLE_TRACK_TIP = "The subtitle track the Language, Default and Forced settings beside it edit."
LANGUAGE_TIP = "The track's language tag, which players use to pick a subtitle track."
DEFAULT_TIP = "Players show this track unless told otherwise. Only one track can be the default."
FORCED_TIP = "Marks the track as forced: only foreign-language dialogue and signs, shown even with subtitles off."
_KINDS = ("video", "audio", "subtitle")
_LABELS = {"video": "Video", "audio": "Audio", "subtitle": "Subtitles"}

_VIDEO_BROWSE_FILTER = "Video Files (*.mp4 *.mkv *.avi *.mov *.webm *.mxf *.ts *.vob)"
# Built from the app's audio-extension list, so it can't drift from what counts as audio-only.
_AUDIO_BROWSE_FILTER = "Audio Files (%s)" % " ".join(
    "*" + ext for ext in sorted(formats.AUDIO_EXTENSIONS))


_HISTORY_LIMIT = 50


def _offered(kind, stream):
    """Whether a probed stream becomes a row: every video / audio one; subtitles in a format
    this app can carry (not teletext or closed captions)."""
    return kind != "subtitle" or stream.get("codec_name") in formats.FFPROBE_SUBTITLE


def _entry(kind, stream, source, file=None, name=None, start_time=None):
    """A track-list entry for `stream`. A subtitle's language and flags start as the stream's
    and are edited on the entry; `start_time` is its file's own (see ffmpeg_build)."""
    entry = {"id": f"src:{stream['index']}" if source == "primary" else f"ext:{uuid.uuid4().hex[:8]}",
             "source": source, "file": file, "index": stream["index"], "stream": stream, "name": name}
    if kind == "subtitle":
        entry.update(language=formats.language_code(stream.get("language")), default=bool(stream.get("default")),
                     forced=bool(stream.get("forced")), start_time=start_time if source == "external" else None)
    return entry


class MuxingTab(MediaTab):
    TAB = "Muxing"
    ACTION_TEXT = "Mux"
    OUTPUT_SUFFIX = "_muxed"
    VERB_ING = "Muxing"
    DIRECT_LABEL = "Direct Mux"
    PRESET_NOTE = ("Name this preset. It stores the container and the strip flags — "
                   "not the trim, the track picks, or the file paths.")

    def _init_state(self):
        # Each box's tracks in order, per kind: the source's streams (from the probe), then any
        # added. This list, not the probe, is what the box shows. Entries are never mutated, so
        # a snapshot is a copy. Entry: {"id": "src:0" | "ext:ab12cd34", "source": "primary" |
        # "external", "file", "index" (0-based among that file's streams of the kind),
        # "stream" (the probe's description), "name" (an external file's name)}.
        # A subtitle entry also holds its (editable) "language", "default" and "forced".
        self._tracks = {kind: [] for kind in _KINDS}
        # Undo / redo, per kind: stacks of {"entries": [...], "checked": {ids}}.
        self._history = {kind: {"undo": [], "redo": []} for kind in _KINDS}
        # The ticks an undo / redo puts back, applied by the next `_sync_controls`.
        self._restore_checked = {}
        # Ticked ids as of the last `_sync_controls`: a click reports after the fact, and its
        # undo step is the state from before it.
        self._checked_baseline = {kind: set() for kind in _KINDS}
        self._boxes = {}
        # The subtitle row the editor shows; label -> id for its Track dropdown.
        self._active_subtitle = None
        self._subtitle_track_ids = {}
        # The file the rows describe; when it differs from the current file the boxes reset.
        self._tracks_file = None
        # The probe the source entries were seeded from; a new one re-seeds them.
        self._tracks_info = None

    # ------------------------------------------------------------------ #
    #  Panels
    # ------------------------------------------------------------------ #
    def _track_panel(self, kind, editor=None, min_width=340):
        """The track box beside a column of Select / Deselect All, Add and Remove Stream(s),
        and Undo / Redo with Strip (`editor`, if given, sits between them). The box takes
        Overview's exact height so this page is never taller than Overview (a taller page would
        shrink this tab's preview); the column's four rows only just fit, hence the compact icon
        rows and 4px gaps."""
        btn_width = button_width_for(["Add Stream(s)", "Remove Stream(s)"])
        select_spacing = 4      # the column's vertical gap, also between each icon pair
        select_width = (btn_width - select_spacing) // 2
        row, rl = hrow(spacing=10, align_bottom=True)
        box = TrackListBox(min_width=min_width)
        self._boxes[kind] = box
        # The box is fixed at Overview's height, so it never grows as tracks arrive; Select /
        # Deselect All take what the column has left (a fixed row height, since the button's
        # stylesheet min-height overrides setFixedHeight). Both are measured off real widgets,
        # so re-measured after a rescale.
        top = None

        def size_box():
            overview_height = self.panels.widget(0).sizeHint().height()
            box.setFixedHeight(max(px(92), overview_height))
            if top is not None:
                top.setFixedHeight(max(px(22), box.height() - 2 * px(28) - px(24) - 3 * px(4)))
        box.changed.connect(lambda: self._track_toggled(kind))
        box.reordered.connect(lambda ids: self._reorder_tracks(kind, ids))
        tip(box, _TRACK_TIP)
        rl.addWidget(box, 1)
        if editor is not None:
            rl.addWidget(editor, 0, Qt.AlignBottom)

        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        # 4px gaps leave room for the rounding of five px() lengths: with 6 the column came out
        # taller than the box at 1.25x.
        scale.spacing(sl, 4)
        top, tl = hrow(spacing=select_spacing, align_bottom=False)
        size_box()
        # Left-aligned, or the pair drifts apart across the column's width.
        tl.setAlignment(Qt.AlignLeft)
        select_all_btn = IconButton("select-multiple", role="compact", width=select_width)
        select_all_btn.clicked.connect(lambda: self._select_all(kind))
        tip(select_all_btn, _SELECT_ALL_TIP)
        select_all_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        tl.addWidget(select_all_btn)
        deselect_all_btn = IconButton("deselect-multiple", role="compact", width=select_width)
        deselect_all_btn.clicked.connect(lambda: self._deselect_all(kind))
        tip(deselect_all_btn, _DESELECT_ALL_TIP)
        deselect_all_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        tl.addWidget(deselect_all_btn)
        sl.addWidget(top)
        add_btn = button("Add Stream(s)", width=btn_width)
        add_btn.clicked.connect(lambda: self._add_stream(kind))
        sl.addWidget(add_btn)
        remove_btn = button("Remove Stream(s)", role="danger", width=btn_width)
        remove_btn.clicked.connect(lambda: self._remove_streams(kind))
        tip(remove_btn, _REMOVE_TIP)
        sl.addWidget(remove_btn)
        history, hl = hrow(spacing=select_spacing, align_bottom=False)
        hl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        undo_btn = IconButton("undo", role="compact", width=select_width, height=24)
        undo_btn.clicked.connect(lambda: self._undo(kind))
        tip(undo_btn, _UNDO_TIP)
        hl.addWidget(undo_btn)
        redo_btn = IconButton("redo", role="compact", width=select_width, height=24)
        redo_btn.clicked.connect(lambda: self._redo(kind))
        tip(redo_btn, _REDO_TIP)
        hl.addWidget(redo_btn)
        scale.spacer(hl, 8 - select_spacing)     # 8px from Redo to Strip, as Remove had
        check = CheckBox(f"Strip {_LABELS[kind]}", color_key="stop")
        check.clicked.connect(self._on_control_change)
        tip(check, STRIP_TIP)
        hl.addWidget(check)
        sl.addWidget(history)
        rl.addWidget(side, 0, Qt.AlignBottom)
        scale.bind_after(box, size_box)

        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        outer.addWidget(row)
        return (page, box, add_btn, remove_btn, check, select_all_btn, deselect_all_btn,
                undo_btn, redo_btn)

    def build_video(self):
        page, self.video_box, self.video_add_btn, self.video_remove_btn, \
            self.strip_video_check, self.video_select_all_btn, \
            self.video_deselect_all_btn, self.video_undo_btn, \
            self.video_redo_btn = self._track_panel("video")
        return page

    def build_audio(self):
        page, self.audio_box, self.audio_add_btn, self.audio_remove_btn, \
            self.strip_audio_check, self.audio_select_all_btn, \
            self.audio_deselect_all_btn, self.audio_undo_btn, \
            self.audio_redo_btn = self._track_panel("audio")
        return page

    def build_subtitles(self):
        """The subtitle track box with the chosen track's Language and Default / Forced beside
        it (a narrower box: the editor needs the width)."""
        editor = QWidget()
        el = QVBoxLayout(editor)
        el.setContentsMargins(0, 0, 0, 0)
        scale.spacing(el, 6)
        top, tl = hrow(spacing=8)
        self.subtitle_track_menu = Dropdown([NO_OPTION], width=Dropdown.width_for(["Track 99"]))
        self.subtitle_track_menu.picked.connect(self._on_subtitle_track_pick)
        tip(self.subtitle_track_menu, SUBTITLE_TRACK_TIP)
        box, self.subtitle_track_label = labeled("Track:", self.subtitle_track_menu)
        tl.addWidget(box)
        self.subtitle_language_menu = Dropdown([NO_OPTION], width=Dropdown.width_for(
            list(formats.SUBTITLE_LANGUAGES.values())))
        self.subtitle_language_menu.picked.connect(self._on_subtitle_language_pick)
        tip(self.subtitle_language_menu, LANGUAGE_TIP)
        box, self.subtitle_language_label = labeled("Language:", self.subtitle_language_menu)
        tl.addWidget(box)
        el.addWidget(top)
        flags, fl = hrow(spacing=12, align_bottom=False)
        self.subtitle_default_check = CheckBox("Default")
        self.subtitle_default_check.clicked.connect(lambda: self._set_subtitle_flag("default"))
        tip(self.subtitle_default_check, DEFAULT_TIP)
        fl.addWidget(self.subtitle_default_check)
        self.subtitle_forced_check = CheckBox("Forced")
        self.subtitle_forced_check.clicked.connect(lambda: self._set_subtitle_flag("forced"))
        tip(self.subtitle_forced_check, FORCED_TIP)
        fl.addWidget(self.subtitle_forced_check)
        el.addWidget(flags)
        page, self.subtitle_box, self.subtitle_add_btn, self.subtitle_remove_btn, \
            self.strip_subtitles_check, self.subtitle_select_all_btn, \
            self.subtitle_deselect_all_btn, self.subtitle_undo_btn, \
            self.subtitle_redo_btn = self._track_panel("subtitle", editor=editor, min_width=150)
        return page

    # ------------------------------------------------------------------ #
    #  Subtitle editor: language and flags of the track the Track dropdown shows
    # ------------------------------------------------------------------ #
    def _on_subtitle_track_pick(self, label):
        self._active_subtitle = self._subtitle_track_ids.get(label)
        self._sync_controls()

    def _active_subtitle_entry(self):
        return next((e for e in self._tracks["subtitle"] if e["id"] == self._active_subtitle), None)

    def _on_subtitle_language_pick(self, name):
        entry = self._active_subtitle_entry()
        code = next((c for c, n in formats.SUBTITLE_LANGUAGES.items() if n == name), name)
        if entry is not None and code != formats.language_code(entry.get("language")):
            self._edit_tracks("subtitle", [dict(e, language=code) if e is entry else e
                                           for e in self._tracks["subtitle"]])

    def _set_subtitle_flag(self, flag):
        """Default or Forced clicked: one undo step. Only one track can be the default."""
        entry = self._active_subtitle_entry()
        if entry is None:
            return
        on = (self.subtitle_default_check if flag == "default" else self.subtitle_forced_check).isChecked()
        entries = []
        for e in self._tracks["subtitle"]:
            if e is entry:
                e = dict(e, **{flag: on})
            elif flag == "default" and on and e.get("default"):
                e = dict(e, default=False)
            entries.append(e)
        self._edit_tracks("subtitle", entries)

    def _sync_subtitle_editor(self, live):
        """The Track dropdown lists every row; the rest shows (and edits) the chosen one."""
        entries = self._tracks["subtitle"]
        self._subtitle_track_ids = {f"Track {n}": e["id"] for n, e in enumerate(entries, start=1)}
        if self._active_subtitle not in self._subtitle_track_ids.values():
            self._active_subtitle = entries[0]["id"] if entries else None
        self.subtitle_track_menu.set_values(list(self._subtitle_track_ids) or [NO_OPTION])
        entry = self._active_subtitle_entry()
        languages = list(formats.SUBTITLE_LANGUAGES.values())
        if entry is not None:
            label = next(l for l, i in self._subtitle_track_ids.items() if i == entry["id"])
            self.subtitle_track_menu.set(label)
            name = formats.language_name(entry.get("language"))
            if name not in languages:
                languages.append(name)
            self.subtitle_language_menu.set_values(languages)
            self.subtitle_language_menu.set(name)
        else:
            self.subtitle_language_menu.set_values([NO_OPTION])
        self.subtitle_default_check.setChecked(bool(entry and entry.get("default")))
        self.subtitle_forced_check.setChecked(bool(entry and entry.get("forced")))
        editable = live and entry is not None
        set_enabled(self.subtitle_track_menu, self.subtitle_track_label, editable)
        set_enabled(self.subtitle_language_menu, self.subtitle_language_label, editable)
        self.subtitle_default_check.setEnabled(editable)
        self.subtitle_forced_check.setEnabled(editable)

    # ------------------------------------------------------------------ #
    #  Add / remove / reorder
    def _add_stream(self, kind):
        if kind == "video":
            title, types = "Select Video Source", _VIDEO_BROWSE_FILTER + ";;All Files (*.*)"
        elif kind == "subtitle":
            title, types = "Select Subtitle Source", BROWSE_FILTERS["subtitle"]
        else:
            title, types = "Select Audio Source", _AUDIO_BROWSE_FILTER
        path, _ = QFileDialog.getOpenFileName(self, title, self._output_directory(), types)
        if not path:
            return
        run_async(probe_media, lambda info: self._stream_probed(kind, path, info), path)

    def _stream_probed(self, kind, path, info):
        streams = [s for s in (info or {}).get(f"{kind}_streams") or [] if _offered(kind, s)]
        if not streams:
            show_message(
                self.app, "No Matching Streams",
                f"“{os.path.basename(path)}” has no {kind} streams to add.",
            )
            return
        if len(streams) > 1:
            chosen = pick_external_streams(self.app, kind, streams, lambda s: _describe_stream(kind, s))
            if chosen is None:
                return
            streams = [s for s in streams if s["index"] in chosen]
        name = os.path.basename(path.replace("\\", "/"))
        added = [_entry(kind, stream, "external", path, name, (info or {}).get("start_time"))
                 for stream in streams]
        self._edit_tracks(kind, self._tracks[kind] + added)

    def _remove_streams(self, kind):
        """Remove every checked row, the source's own tracks included (the file is untouched).
        The rows below move up and renumber; undo puts them back."""
        checked = set(self._boxes[kind].checked_ids())
        if not checked:
            show_message(
                self.app, "Nothing to Remove",
                f"Check the {kind} track(s) you want removed, then press Remove Stream(s) again.",
            )
            return
        self._edit_tracks(kind, [entry for entry in self._tracks[kind] if entry["id"] not in checked])

    def _reorder_tracks(self, kind, ids):
        """A drag ended with `ids` in their new order: the list follows, as one undo step."""
        by_id = {entry["id"]: entry for entry in self._tracks[kind]}
        entries = [by_id[row_id] for row_id in ids if row_id in by_id]
        if len(entries) == len(by_id) and entries != self._tracks[kind]:
            self._edit_tracks(kind, entries)

    # ------------------------------------------------------------------ #
    #  Undo / redo: list edits and ticks, per kind
    # ------------------------------------------------------------------ #
    def _snapshot(self, kind):
        """The box as it is now: its list and which rows are checked."""
        return {"entries": list(self._tracks[kind]), "checked": set(self._boxes[kind].checked_ids())}

    def _push_history(self, kind, snapshot=None):
        """Keep `snapshot` (default: the box now) as the next undo step; clears redo."""
        history = self._history[kind]
        history["undo"].append(snapshot or self._snapshot(kind))
        del history["undo"][:-_HISTORY_LIMIT]
        history["redo"].clear()

    def _edit_tracks(self, kind, entries):
        """Every change to a box's list: the outgoing list is kept for undo, then the tab
        resyncs."""
        self._push_history(kind)
        self._tracks[kind] = entries
        self._sync_controls()

    def _track_toggled(self, kind):
        """A row's checkbox was clicked: an undo step holding the ticks from before the click."""
        self._push_history(kind, {"entries": list(self._tracks[kind]),
                                  "checked": set(self._checked_baseline[kind])})
        self._on_control_change()

    def _undo(self, kind):
        self._travel(kind, "undo", "redo")

    def _redo(self, kind):
        self._travel(kind, "redo", "undo")

    def _travel(self, kind, take, keep):
        """Swap the box (list and ticks) with the top of `take`, keeping the current one on
        `keep`."""
        history = self._history[kind]
        if not history[take]:
            return
        history[keep].append(self._snapshot(kind))
        snapshot = history[take].pop()
        self._tracks[kind] = list(snapshot["entries"])
        self._restore_checked[kind] = snapshot["checked"]
        self._sync_controls()

    def _select_all(self, kind):
        """Check every row."""
        box = self._boxes[kind]
        if set(box.checked_ids()) != set(box.item_ids()):     # nothing to undo otherwise
            self._push_history(kind)
            for row_id in box.item_ids():
                box.set_checked(row_id, True)
        self._sync_controls()

    def _deselect_all(self, kind):
        """Uncheck every row; nothing leaves the box."""
        box = self._boxes[kind]
        if box.checked_ids():
            self._push_history(kind)
            for row_id in box.item_ids():
                box.set_checked(row_id, False)
        self._sync_controls()

    # ------------------------------------------------------------------ #
    #  Track box contents
    # ------------------------------------------------------------------ #
    def _reseed_tracks(self, info):
        """A new probe: the source's streams become the first rows, added tracks follow, and
        the undo history goes (it describes the old file)."""
        for kind in _KINDS:
            primary = [_entry(kind, stream, "primary") for stream in info.get(f"{kind}_streams") or []
                       if _offered(kind, stream)]
            external = [entry for entry in self._tracks[kind] if entry["source"] == "external"]
            self._tracks[kind] = primary + external
            self._history[kind] = {"undo": [], "redo": []}

    def _items_for(self, kind):
        """The box's rows, numbered by position (so a removal renumbers)."""
        return [{"id": entry["id"], "label": _row_label(kind, entry, number)}
                for number, entry in enumerate(self._tracks[kind], start=1)]

    def _track_args(self, kind):
        """Every checked row as a `-map` entry, in the box's (= the output's) order; a subtitle
        also carries its codec, language, flags and its file's start."""
        entries = {entry["id"]: entry for entry in self._tracks[kind]}
        args = []
        for row_id in self._boxes[kind].checked_ids():
            entry = entries.get(row_id)
            if not entry:
                continue
            arg = {"source": entry["source"], "file": entry["file"], "index": entry["index"]}
            if kind == "subtitle":
                arg.update(codec_name=entry["stream"].get("codec_name"), language=entry.get("language"),
                           default=bool(entry.get("default")), forced=bool(entry.get("forced")),
                           start_time=entry.get("start_time"))
            args.append(arg)
        return args

    def _ticked_subtitle_codecs(self):
        """The raw codecs of the subtitle tracks going into the output."""
        if self.strip_subtitles_check.isChecked():
            return []
        return [track["codec_name"] for track in self._track_args("subtitle")]

    # ------------------------------------------------------------------ #
    #  The single constraint pass
    # ------------------------------------------------------------------ #
    def _sync_controls(self, *_):
        """The only place derived UI state is decided. Idempotent.
          1. stream presence (both stripped would write an empty file)
          2. the track boxes from `self._tracks` (reset when the file changes)
          3. the container inversion: the source's codecs decide the containers
          4. a stripped, absent or emptied stream greys its panel and marks its sub-tab red
             (an emptied one keeps Add Stream(s) and Undo / Redo, the ways back)
          5. subtitles: a ticked picture track narrows the containers to Matroska; the editor
          6. chapters (the shared page)
          7. the Overview rundown"""
        stripping_video = self.strip_video_check.isChecked()
        stripping_audio = self.strip_audio_check.isChecked()
        info = self.app.media.info
        video_absent = info.get("has_video") is False
        audio_absent = info.get("has_audio") is False

        current_path = self.app.media.current_file_path
        reset = current_path != self._tracks_file
        if info is not self._tracks_info:
            self._reseed_tracks(info)
            self._tracks_info = info
        for kind, box in self._boxes.items():
            box.set_items(self._items_for(kind), reset=reset, checked=self._restore_checked.pop(kind, None))
            self._checked_baseline[kind] = set(box.checked_ids())
        self._tracks_file = current_path

        # Every track of a kind removed reads as stripped, once the probe says the source has
        # that kind (before it, the lists are simply empty).
        video_emptied = info.get("has_video") is True and not self._tracks["video"]
        audio_emptied = info.get("has_audio") is True and not self._tracks["audio"]

        # With one kind stripped or emptied, the other can't be.
        self.strip_video_check.setEnabled(not (stripping_audio or audio_emptied or video_absent))
        self.strip_audio_check.setEnabled(not (stripping_video or video_emptied or audio_absent))
        self.sub_tab_bar.set_marked("Video", stripping_video or video_absent or video_emptied)
        self.sub_tab_bar.set_marked("Audio", stripping_audio or audio_absent or audio_emptied)
        self.carousel.set_strip_state(stripping_video or video_emptied,
                                      stripping_audio or audio_absent or audio_emptied)

        video_codec = None if stripping_video else info.get("video")
        audio_codec = None if stripping_audio else info.get("audio")
        subtitle_ok = formats.containers_for_subtitles(self._ticked_subtitle_codecs())
        self._retarget_container([c for c in formats.containers_for(video_codec, audio_codec) if c in subtitle_ok]
                                 or subtitle_ok)

        for kind, stripping, absent in (("video", stripping_video, video_absent),
                                        ("audio", stripping_audio, audio_absent)):
            # "open": not stripped or absent (an emptied panel stays open, to add or undo).
            # "has rows": something to select, check or remove.
            open_ = not stripping and not absent
            has_rows = open_ and bool(self._tracks[kind])
            history = self._history[kind]
            getattr(self, f"{kind}_box").setEnabled(has_rows)
            getattr(self, f"{kind}_add_btn").setEnabled(open_)
            getattr(self, f"{kind}_remove_btn").setEnabled(has_rows)
            getattr(self, f"{kind}_select_all_btn").setEnabled(has_rows)
            getattr(self, f"{kind}_deselect_all_btn").setEnabled(has_rows)
            getattr(self, f"{kind}_undo_btn").setEnabled(open_ and bool(history["undo"]))
            getattr(self, f"{kind}_redo_btn").setEnabled(open_ and bool(history["redo"]))

        has_file = bool(current_path)
        stripping_subtitles = self.strip_subtitles_check.isChecked()
        subtitles_open = has_file and not stripping_subtitles
        has_subtitles = subtitles_open and bool(self._tracks["subtitle"])
        history = self._history["subtitle"]
        self.subtitle_box.setEnabled(has_subtitles)
        self.subtitle_add_btn.setEnabled(subtitles_open)
        for widget in (self.subtitle_remove_btn, self.subtitle_select_all_btn, self.subtitle_deselect_all_btn):
            widget.setEnabled(has_subtitles)
        self.subtitle_undo_btn.setEnabled(subtitles_open and bool(history["undo"]))
        self.subtitle_redo_btn.setEnabled(subtitles_open and bool(history["redo"]))
        self.strip_subtitles_check.setEnabled(has_file and bool(self._tracks["subtitle"]))
        self.sub_tab_bar.set_marked("Subtitles", stripping_subtitles)
        self._sync_subtitle_editor(has_subtitles)
        self._sync_chapters()

        self._refresh_summary()
        self._apply_import_gate(extra=((self.subtitle_track_menu, self.subtitle_track_label),
                                       (self.subtitle_language_menu, self.subtitle_language_label)))

    def _retarget_container(self, allowed):
        lost = self.format_menu.retarget(allowed)
        after = self.format_menu.value()
        self._update_format_tip()
        if lost:
            # Keep the save path's extension in step with the snap.
            stem, extension = os.path.splitext(self.save_entry.text().strip())
            if extension:
                set_line_text(self.save_entry, stem + after)
            if self._ready:
                # A subtitle track the lost container can't carry is the likelier reason to name.
                blocking = next((formats.FFPROBE_SUBTITLE.get(codec) for codec in self._ticked_subtitle_codecs()
                                 if not formats.subtitle_codec_arg(lost, codec)), None)
                reason = f"{blocking} subtitles" if blocking else "this file's streams without re-encoding"
                self.app.notify(f"Container switched to {after} — {lost} can't hold {reason}.", go_to_queue=False)

    def _refresh_summary(self):
        """The rundown, including the keyframe caveat copy-only trimming has."""
        info = self.app.media.info
        no_file = not self.app.media.current_file_path

        def stream(kind, check, box):
            if no_file:
                return "— no streams selected —", "stop"
            if check.isChecked():
                return "— removed —", "stop"
            if info.get(f"has_{kind}") is False:
                return f"— no {kind} stream —", "stop"
            if info.get(f"has_{kind}") is True and not self._tracks[kind]:
                return "— removed —", "stop"
            checked = box.checked_ids()
            if not checked:
                return "— no streams selected —", "stop"
            bits = ["copy"]
            # The first checked track's codec (the source's first may be removed or unticked).
            first = next(entry for entry in self._tracks[kind] if entry["id"] == checked[0])
            actual = formats.short_name(first["stream"].get("codec") or first["stream"].get("codec_name"))
            if actual:
                bits.append(actual)
            count = len(checked)
            bits.append("1 track" if count == 1 else f"{count} tracks")
            return " · ".join(bits), None

        start = self.start_time_spinner.seconds()
        duration = self.duration_time_spinner.seconds()
        if no_file:
            length = ("— no file imported —", "stop")
        elif not start and not duration:
            length = ("Whole File", None)
        elif not duration:
            length = (f"{hms(start)} → end · keyframe", None)
        else:
            length = (f"{hms(start)} → {hms(start + duration)} · keyframe", None)
        self.summary.set_values([
            stream("video", self.strip_video_check, self.video_box),
            stream("audio", self.strip_audio_check, self.audio_box),
            length,
        ])

    # ------------------------------------------------------------------ #
    #  Media info
    # ------------------------------------------------------------------ #
    def on_media_info(self, info):
        """Adopt the source's container (while unpicked), then re-run the cascade."""
        container = info.get("container")
        if container and self._auto_format is not None and container in formats.containers():
            self.format_menu.set(container)
            self._auto_format = container
            self._autofill_output_path()
        self._sync_controls()

    # ------------------------------------------------------------------ #
    #  Settings in / out
    # ------------------------------------------------------------------ #
    def _gather_settings(self):
        settings = self._gather_common()
        settings.update({
            "video_tracks": self._track_args("video"),
            "strip_video": self.strip_video_check.isChecked(),
            "audio_tracks": self._track_args("audio"),
            "strip_audio": self.strip_audio_check.isChecked(),
            "subtitle_tracks": self._track_args("subtitle"),
        })
        return settings

    def _validate_specific(self, settings):
        """A box with rows but nothing checked blocks the job; an empty box doesn't."""
        info = self.app.media.info
        if (not settings["strip_video"] and info.get("has_video") is not False
                and self.video_box.item_count() and not settings["video_tracks"]):
            show_message(
                self.app, "No Video Track Selected",
                "Check at least one Video track to include, or turn on Strip Video.",
            )
            return False
        if (not settings["strip_audio"] and info.get("has_audio") is not False
                and self.audio_box.item_count() and not settings["audio_tracks"]):
            show_message(
                self.app, "No Audio Track Selected",
                "Check at least one Audio track to include, or turn on Strip Audio.",
            )
            return False
        # Tracks can be removed outright, so check there is something to map at all.
        if not ((not settings["strip_video"] and settings["video_tracks"])
                or (not settings["strip_audio"] and settings["audio_tracks"])):
            show_message(
                self.app, "Nothing to Mux",
                "Every track has been removed or stripped. Keep at least one track "
                "(Undo brings a removed one back).",
            )
            return False
        return True

    def _apply_settings(self, settings):
        """Presets carry only recipe keys, never track picks (see core/presets.py)."""
        if not settings:
            return
        was_ready, self._ready = self._ready, False
        try:
            self._apply_common(settings)
            if "output_format" in settings:
                self.format_menu.set(settings["output_format"])
                self._auto_format = None
            self._sync_controls()
        finally:
            self._ready = was_ready
        self._sync_controls()
