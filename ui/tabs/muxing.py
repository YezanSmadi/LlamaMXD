# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Muxing: change a file's container and choose which streams go into it. Nothing is ever
re-encoded, so there are no codec controls, and the container filter runs backwards: the
source's codecs decide which containers it can be remuxed into (`formats.containers_for`).
Video and Audio each list every track (the source's and any added from other files) in an
editable, reorderable `TrackListBox` with undo / redo."""
import os
import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QSizePolicy, QVBoxLayout, QWidget

from core import formats
from core.utilities import probe_media
from ui import scale
from ui.scale import px
from ui.tabs.media_tab import STRIP_TIP, MediaTab, hms, hrow, set_line_text
from ui.widgets.controls import NO_OPTION, CheckBox, IconButton, button, button_width_for
from ui.widgets.dialogs import pick_external_streams, show_message
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

_VIDEO_BROWSE_FILTER = "Video Files (*.mp4 *.mkv *.avi *.mov *.webm *.mxf *.ts *.vob)"
# Built from the app's audio-extension list, so it can't drift from what counts as audio-only.
_AUDIO_BROWSE_FILTER = "Audio Files (%s)" % " ".join(
    "*" + ext for ext in sorted(formats.AUDIO_EXTENSIONS))


_HISTORY_LIMIT = 50


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
        self._tracks = {"video": [], "audio": []}
        # Undo / redo, per kind: stacks of {"entries": [...], "checked": {ids}}.
        self._history = {"video": {"undo": [], "redo": []}, "audio": {"undo": [], "redo": []}}
        # The ticks an undo / redo puts back, applied by the next `_sync_controls`.
        self._restore_checked = {}
        # Ticked ids as of the last `_sync_controls`: a click reports after the fact, and its
        # undo step is the state from before it.
        self._checked_baseline = {"video": set(), "audio": set()}
        # The file the rows describe; when it differs from the current file the boxes reset.
        self._tracks_file = None
        # The probe the source entries were seeded from; a new one re-seeds them.
        self._tracks_info = None

    # ------------------------------------------------------------------ #
    #  Panels
    # ------------------------------------------------------------------ #
    def _track_panel(self, kind):
        """The track box beside a column of Select / Deselect All, Add and Remove Stream(s),
        and Undo / Redo with Strip. The box takes Overview's exact height so this page is never
        taller than Overview (a taller page would shrink this tab's preview); the column's four
        rows only just fit, hence the compact icon rows and 4px gaps."""
        btn_width = button_width_for(["Add Stream(s)", "Remove Stream(s)"])
        select_spacing = 4      # the column's vertical gap, also between each icon pair
        select_width = (btn_width - select_spacing) // 2
        row, rl = hrow(spacing=10, align_bottom=True)
        box = TrackListBox()
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
        box.changed.connect(lambda: self._track_toggled(kind.lower()))
        box.reordered.connect(lambda ids: self._reorder_tracks(kind.lower(), ids))
        tip(box, _TRACK_TIP)
        rl.addWidget(box, 1)

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
        select_all_btn.clicked.connect(lambda: self._select_all(kind.lower()))
        tip(select_all_btn, _SELECT_ALL_TIP)
        select_all_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        tl.addWidget(select_all_btn)
        deselect_all_btn = IconButton("deselect-multiple", role="compact", width=select_width)
        deselect_all_btn.clicked.connect(lambda: self._deselect_all(kind.lower()))
        tip(deselect_all_btn, _DESELECT_ALL_TIP)
        deselect_all_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        tl.addWidget(deselect_all_btn)
        sl.addWidget(top)
        add_btn = button("Add Stream(s)", width=btn_width)
        add_btn.clicked.connect(lambda: self._add_stream(kind.lower()))
        sl.addWidget(add_btn)
        remove_btn = button("Remove Stream(s)", role="danger", width=btn_width)
        remove_btn.clicked.connect(lambda: self._remove_streams(kind.lower()))
        tip(remove_btn, _REMOVE_TIP)
        sl.addWidget(remove_btn)
        history, hl = hrow(spacing=select_spacing, align_bottom=False)
        hl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        undo_btn = IconButton("undo", role="compact", width=select_width, height=24)
        undo_btn.clicked.connect(lambda: self._undo(kind.lower()))
        tip(undo_btn, _UNDO_TIP)
        hl.addWidget(undo_btn)
        redo_btn = IconButton("redo", role="compact", width=select_width, height=24)
        redo_btn.clicked.connect(lambda: self._redo(kind.lower()))
        tip(redo_btn, _REDO_TIP)
        hl.addWidget(redo_btn)
        scale.spacer(hl, 8 - select_spacing)     # 8px from Redo to Strip, as Remove had
        check = CheckBox(f"Strip {kind}", color_key="stop")
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
            self.video_redo_btn = self._track_panel("Video")
        return page

    def build_audio(self):
        page, self.audio_box, self.audio_add_btn, self.audio_remove_btn, \
            self.strip_audio_check, self.audio_select_all_btn, \
            self.audio_deselect_all_btn, self.audio_undo_btn, \
            self.audio_redo_btn = self._track_panel("Audio")
        return page

    # ------------------------------------------------------------------ #
    #  Add / remove / reorder
    def _add_stream(self, kind):
        if kind == "video":
            title, types = "Select Video Source", _VIDEO_BROWSE_FILTER + ";;All Files (*.*)"
        else:
            title, types = "Select Audio Source", _AUDIO_BROWSE_FILTER
        path, _ = QFileDialog.getOpenFileName(self, title, self._output_directory(), types)
        if not path:
            return
        run_async(probe_media, lambda info: self._stream_probed(kind, path, info), path)

    def _stream_probed(self, kind, path, info):
        streams = (info or {}).get(f"{kind}_streams") or []
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
        added = [{"id": f"ext:{uuid.uuid4().hex[:8]}", "source": "external", "file": path,
                  "index": stream["index"], "stream": stream, "name": name} for stream in streams]
        self._edit_tracks(kind, self._tracks[kind] + added)

    def _remove_streams(self, kind):
        """Remove every checked row, the source's own tracks included (the file is untouched).
        The rows below move up and renumber; undo puts them back."""
        box = self.video_box if kind == "video" else self.audio_box
        checked = set(box.checked_ids())
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
        box = self.video_box if kind == "video" else self.audio_box
        return {"entries": list(self._tracks[kind]), "checked": set(box.checked_ids())}

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
        box = self.video_box if kind == "video" else self.audio_box
        if set(box.checked_ids()) != set(box.item_ids()):     # nothing to undo otherwise
            self._push_history(kind)
            for row_id in box.item_ids():
                box.set_checked(row_id, True)
        self._sync_controls()

    def _deselect_all(self, kind):
        """Uncheck every row; nothing leaves the box."""
        box = self.video_box if kind == "video" else self.audio_box
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
        for kind in ("video", "audio"):
            primary = [{"id": f"src:{stream['index']}", "source": "primary", "file": None,
                        "index": stream["index"], "stream": stream, "name": None}
                       for stream in info.get(f"{kind}_streams") or []]
            external = [entry for entry in self._tracks[kind] if entry["source"] == "external"]
            self._tracks[kind] = primary + external
            self._history[kind] = {"undo": [], "redo": []}

    def _items_for(self, kind):
        """The box's rows, numbered by position (so a removal renumbers)."""
        return [{"id": entry["id"], "label": _row_label(kind, entry, number)}
                for number, entry in enumerate(self._tracks[kind], start=1)]

    def _track_args(self, kind):
        """Every checked row as a `-map` entry, in the box's (= the output's) order."""
        box = self.video_box if kind == "video" else self.audio_box
        entries = {entry["id"]: entry for entry in self._tracks[kind]}
        args = []
        for row_id in box.checked_ids():
            entry = entries.get(row_id)
            if entry:
                args.append({"source": entry["source"], "file": entry["file"], "index": entry["index"]})
        return args

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
          5. the Overview rundown"""
        stripping_video = self.strip_video_check.isChecked()
        stripping_audio = self.strip_audio_check.isChecked()
        info = self.app.media_info
        video_absent = info.get("has_video") is False
        audio_absent = info.get("has_audio") is False

        current_path = self.app.current_file_path
        reset = current_path != self._tracks_file
        if info is not self._tracks_info:
            self._reseed_tracks(info)
            self._tracks_info = info
        for kind, box in (("video", self.video_box), ("audio", self.audio_box)):
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
        self._retarget_container(formats.containers_for(video_codec, audio_codec))

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

        self._refresh_summary()
        self._apply_import_gate()

    def _retarget_container(self, allowed):
        before = self.format_menu.value()
        self.format_menu.set_values(allowed)
        after = self.format_menu.value()
        self._update_format_tip()
        # Not from the no-file placeholder: that wasn't a real pick.
        if before != after and before != NO_OPTION:
            # Keep the save path's extension in step with the snap.
            stem, extension = os.path.splitext(self.save_entry.text().strip())
            if extension:
                set_line_text(self.save_entry, stem + after)
        if self._ready and before != after and before != NO_OPTION:
            self.app.notify(
                f"Container switched to {after} — {before} can't hold this file's streams "
                "without re-encoding.",
                go_to_queue=False,
            )

    def _refresh_summary(self):
        """The rundown, including the keyframe caveat copy-only trimming has."""
        info = self.app.media_info
        no_file = not self.app.current_file_path

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
        })
        return settings

    def _validate_specific(self, settings):
        """A box with rows but nothing checked blocks the job; an empty box doesn't."""
        info = self.app.media_info
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
