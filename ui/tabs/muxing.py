# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Muxing: change a file's container and choose which streams go into it. Nothing is ever
re-encoded, so there are no codec controls, and the container filter runs backwards: the
source's codecs decide which containers it can be remuxed into (`formats.containers_for`), and
a ticked picture subtitle track (PGS, VobSub) narrows them to Matroska. Video, Audio and Subtitles
each list every track (the source's and any added from other files) in an editable, reorderable
`TrackListBox` with undo / redo; Subtitles adds/edits a track's language and Default / Forced in
one popup. There is no Strip checkbox anywhere in this tab: a kind with nothing ticked — whether
the source never had one, every track was removed, or the user simply deselected them all — is
this app's one "no ___ in the output" signal (`strip_video` / `strip_audio` / `strip_subtitles`
are still real settings keys, just derived from that instead of a widget)."""
import os
import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from core import formats
from ui import scale
from ui.scale import px
from ui.tabs.media_tab import MediaTab, hms, hrow, set_line_text
from ui.widgets.controls import button, button_width_for, IconButton
from ui.widgets.dialogs import show_message
from ui.widgets.edit_dialogs import edit_streams, edit_subtitles
from ui.widgets.tooltip import tip
from ui.widgets.tracklist import TrackListBox
from ui.widgets.tracklist import row_label as _row_label

_TRACK_TIP = ("Check as many streams as the output should carry. Muxing never "
              "re-encodes them. \"Add/Edit %s\" pulls one in from another file or sets which "
              "track is the default. Drag a track up or down to reorder it.")
_ADD_EDIT_TIP = ("Adds a %s track from another file, or sets which track is the Default. "
                 "Opens a window with a dropdown of the tracks.")
_REMOVE_TIP = ("Removes every checked track from the list, including ones from the source file. "
               "Any tracks below move up to fill the gap. Undo brings them back.")
_UNDO_TIP = "Undoes the last add, remove, edit, reorder, or change of which tracks are checked."
_REDO_TIP = "Redoes what Undo just took back."
_SELECT_ALL_TIP = "Checks every track in the box; includes all of them in the output."
_DESELECT_ALL_TIP = "Unchecks every track in the box without completely removing any of them."
_ADD_EDIT_SUBS_TIP = ("Adds a subtitle track from another file or changes an existing one's "
                      "language and Default / Forced flags. Opens a window with a dropdown of the tracks.")
_SUBS_TRACK_TIP = ("Check as many subtitle tracks as the output should carry. "
                   "\"Add/Edit Subs\" adds one from another file. Drag a track up or down to reorder it.")
_SUBS_REMOVE_TIP = ("Removes every checked subtitle track from the list, including ones from the source file. "
                    "Any tracks below move up to fill the gap. Undo brings them back.")
_KINDS = ("video", "audio", "subtitle")

_HISTORY_LIMIT = 50


def _offered(kind, stream):
    """Whether a probed stream becomes a row: every video / audio one; subtitles in a format
    this app can carry (not teletext or closed captions)."""
    return kind != "subtitle" or stream.get("codec_name") in formats.FFPROBE_SUBTITLE


def _entry(kind, stream, source, file=None, name=None, start_time=None):
    """A track-list entry for `stream`. Its Default flag starts as the stream's and is edited on the
    entry (a subtitle's language and Forced flag too); `start_time` is its file's own (see
    ffmpeg_build)."""
    entry = {"id": f"src:{stream['index']}" if source == "primary" else f"ext:{uuid.uuid4().hex[:8]}",
             "source": source, "file": file, "index": stream["index"], "stream": stream, "name": name,
             "default": bool(stream.get("default"))}
    if kind == "subtitle":
        entry.update(language=formats.language_code(stream.get("language")),
                     forced=bool(stream.get("forced")), start_time=start_time if source == "external" else None)
    return entry


class MuxingTab(MediaTab):
    TAB = "Muxing"
    ACTION_TEXT = "Mux"
    OUTPUT_SUFFIX = "_muxed"
    VERB_ING = "Muxing"
    DIRECT_LABEL = "Direct Mux"
    PRESET_NOTE = ("Name this preset. It stores the container and every codec / "
                   "quality setting. Does not include the trim nor the file paths.")

    def _init_state(self):
        # Each box's tracks in order, per kind: the source's streams (from the probe), then any
        # added. This list, not the probe, is what the box shows. Entries are never mutated, so
        # a snapshot is a copy. Entry: {"id": "src:0" | "ext:ab12cd34", "source": "primary" |
        # "external", "file", "index" (0-based among that file's streams of the kind),
        # "stream" (the probe's description), "name" (an external file's name)}.
        # Every entry holds its (editable, in Add/Edit) "default"; a subtitle also its "language" and "forced".
        self._tracks = {kind: [] for kind in _KINDS}
        # Undo / redo, per kind: stacks of {"entries": [...], "checked": {ids}}.
        self._history = {kind: {"undo": [], "redo": []} for kind in _KINDS}
        # The ticks an undo / redo puts back, applied by the next `_sync_controls`.
        self._restore_checked = {}
        # Checked ids as of the last `_sync_controls`: a click reports after the fact, and its
        # undo step is the state from before it.
        self._checked_baseline = {kind: set() for kind in _KINDS}
        self._boxes = {}
        # The file the rows describe; when it differs from the current file the boxes reset.
        self._tracks_file = None
        # The probe the source entries were seeded from; a new one re-seeds them.
        self._tracks_info = None

    # ------------------------------------------------------------------ #
    #  Panels
    # ------------------------------------------------------------------ #
    def _track_panel(self, kind, min_width=340):
        """The track box beside its column of buttons: Select / Deselect All, Add/Edit, Remove, then
        Undo / Redo. The box takes Overview's exact
        height so this page is never taller than Overview (a taller page would shrink this tab's
        preview), which the column's four rows only just fit, hence the compact icon rows and
        4px gaps."""
        subs = kind == "subtitle"
        add_text = {"video": "Add/Edit Video", "audio": "Add/Edit Audio", "subtitle": "Add/Edit Subs"}[kind]
        remove_text = "Remove Subs" if subs else "Remove Stream(s)"
        # One width on every page, so the buttons don't change size between sub-tabs.
        btn_width = button_width_for(["Add/Edit Video", "Add/Edit Audio", "Remove Stream(s)", "Add/Edit Subs",
                                      "Remove Subs"])
        select_spacing = 4      # the column's vertical gap, also between each icon pair
        select_width = (btn_width - select_spacing) // 2
        row, rl = hrow(spacing=10, align_bottom=True)
        box = TrackListBox(min_width=min_width)
        self._boxes[kind] = box
        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        # 4px gaps leave room for the rounding of five px() lengths: with 6 the column came out
        # taller than the box at 1.25x.
        scale.spacing(sl, select_spacing)
        # The box is fixed at Overview's height, so it never grows as tracks arrive; the top row
        # takes what the column has left (a fixed row height, since the button's stylesheet
        # min-height overrides setFixedHeight). Both are measured off real widgets, so
        # re-measured after a rescale.
        top = None

        def size_box():
            overview_height = self.panels.widget(0).sizeHint().height()
            box.setFixedHeight(max(px(92), overview_height))
            if top is not None:
                top.setFixedHeight(max(px(22), box.height() - 2 * px(28) - px(24) - 3 * px(4)))
        box.changed.connect(lambda: self._track_toggled(kind))
        box.reordered.connect(lambda ids: self._reorder_tracks(kind, ids))
        tip(box, _SUBS_TRACK_TIP if subs else _TRACK_TIP % kind.capitalize())
        rl.addWidget(box, 1)

        top, tl = hrow(spacing=select_spacing, align_bottom=False)
        size_box()
        # Left-aligned, or the pair drifts apart across the column's width.
        tl.setAlignment(Qt.AlignLeft)

        def icon_button(icon, tooltip, handler, **size):
            btn = IconButton(icon, role="compact", **size)
            btn.clicked.connect(handler)
            tip(btn, tooltip)
            return btn

        select_all_btn = icon_button("select-multiple", _SELECT_ALL_TIP, lambda: self._select_all(kind),
                                     width=select_width)
        deselect_all_btn = icon_button("deselect-multiple", _DESELECT_ALL_TIP, lambda: self._deselect_all(kind),
                                       width=select_width)
        for btn in (select_all_btn, deselect_all_btn):
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            tl.addWidget(btn)
        sl.addWidget(top)
        add_btn = button(add_text, width=btn_width)
        add_btn.clicked.connect((lambda: self._add_edit_subtitles()) if subs else (lambda: self._add_edit_streams(kind)))
        tip(add_btn, _ADD_EDIT_SUBS_TIP if subs else _ADD_EDIT_TIP % kind)
        sl.addWidget(add_btn)
        remove_btn = button(remove_text, role="danger", width=btn_width)
        remove_btn.clicked.connect(lambda: self._remove_streams(kind))
        tip(remove_btn, _SUBS_REMOVE_TIP if subs else _REMOVE_TIP)
        sl.addWidget(remove_btn)
        history, hl = hrow(spacing=select_spacing, align_bottom=False)
        hl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        undo_btn = icon_button("undo", _UNDO_TIP, lambda: self._undo(kind), width=select_width, height=24)
        redo_btn = icon_button("redo", _REDO_TIP, lambda: self._redo(kind), width=select_width, height=24)
        hl.addWidget(undo_btn)
        hl.addWidget(redo_btn)
        sl.addWidget(history)
        rl.addWidget(side, 0, Qt.AlignBottom)
        scale.bind_after(box, size_box)

        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        outer.addWidget(row)
        return page, box, add_btn, remove_btn, select_all_btn, deselect_all_btn, undo_btn, redo_btn

    def build_video(self):
        page, self.video_box, self.video_add_btn, self.video_remove_btn, \
            self.video_select_all_btn, self.video_deselect_all_btn, \
            self.video_undo_btn, self.video_redo_btn = self._track_panel("video")
        return page

    def build_audio(self):
        page, self.audio_box, self.audio_add_btn, self.audio_remove_btn, \
            self.audio_select_all_btn, self.audio_deselect_all_btn, \
            self.audio_undo_btn, self.audio_redo_btn = self._track_panel("audio")
        return page

    def build_subtitles(self):
        page, self.subtitle_box, self.subtitle_add_edit_btn, self.subtitle_remove_btn, \
            self.subtitle_select_all_btn, self.subtitle_deselect_all_btn, \
            self.subtitle_undo_btn, self.subtitle_redo_btn = self._track_panel("subtitle")
        return page

    # ------------------------------------------------------------------ #
    #  Add/Edit Subs: adds a track from another file, or edits an existing one's language/flags
    # ------------------------------------------------------------------ #
    def _add_edit_subtitles(self):
        """Open Add/Edit Subs. OK's edits (including any tracks it added) are one undo step."""
        entries = self._tracks["subtitle"]
        edited = edit_subtitles(self.app, entries, self._output_directory())
        if edited is not None and edited != entries:
            self._edit_tracks("subtitle", edited)

    # ------------------------------------------------------------------ #
    #  Add/Edit Video and Audio: adds a track from another file, or sets which one is the default
    # ------------------------------------------------------------------ #
    def _add_edit_streams(self, kind):
        """Open Add/Edit Video or Audio. OK's edits (including any tracks it added) are one undo step."""
        entries = self._tracks[kind]
        edited = edit_streams(self.app, kind, entries, self._output_directory())
        if edited is not None and edited != entries:
            self._edit_tracks(kind, edited)

    # ------------------------------------------------------------------ #
    #  Remove / reorder
    # ------------------------------------------------------------------ #
    def _remove_streams(self, kind):
        """Remove every checked row, the source's own tracks included (the file is untouched).
        The rows below move up and renumber; undo puts them back."""
        checked = set(self._boxes[kind].checked_ids())
        if not checked:
            remove_name = "Remove Subs" if kind == "subtitle" else "Remove Stream(s)"
            show_message(
                self.app, "Nothing to Remove",
                f"Check the {kind} track(s) you want removed, then press {remove_name} again.",
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
        """Every checked row as a `-map` entry with its Default flag, in the box's (= the output's)
        order; a subtitle also carries its codec, language, Forced flag and its file's start."""
        entries = {entry["id"]: entry for entry in self._tracks[kind]}
        args = []
        for row_id in self._boxes[kind].checked_ids():
            entry = entries.get(row_id)
            if not entry:
                continue
            arg = {"source": entry["source"], "file": entry["file"], "index": entry["index"],
                   "default": bool(entry.get("default"))}
            if kind == "subtitle":
                arg.update(codec_name=entry["stream"].get("codec_name"), language=entry.get("language"),
                           forced=bool(entry.get("forced")), start_time=entry.get("start_time"))
            args.append(arg)
        return args

    def _ticked_subtitle_codecs(self):
        """The raw codecs of the subtitle tracks going into the output."""
        return [track["codec_name"] for track in self._track_args("subtitle")]

    # ------------------------------------------------------------------ #
    #  The single constraint pass
    # ------------------------------------------------------------------ #
    def _sync_controls(self, *_):
        """The only place derived UI state is decided. Idempotent.
          1. the track boxes from `self._tracks` (reset when the file changes)
          2. nothing checked = nothing of that kind in the output: this tab's one "strip" signal,
             marks the sub-tab red and greys the preview (an emptied panel keeps Add and Undo /
             Redo live — they're the ways back)
          3. the container inversion: the source's codecs decide the containers
          4. subtitles: a ticked picture track narrows the containers to Matroska
          5. chapters (the shared page)
          6. the Overview rundown"""
        info = self.app.media.info
        current_path = self.app.media.current_file_path
        reset = current_path != self._tracks_file
        if info is not self._tracks_info:
            self._reseed_tracks(info)
            self._tracks_info = info
        for kind, box in self._boxes.items():
            box.set_items(self._items_for(kind), reset=reset, checked=self._restore_checked.pop(kind, None))
            self._checked_baseline[kind] = set(box.checked_ids())
        self._tracks_file = current_path

        # Nothing checked of a kind the source has, or that was added from another file, means no
        # ___ in the output — however that came to be. A source without the kind starts there, and
        # stops being stripped once a track of it is added and ticked.
        def stripped(kind):
            known = info.get(f"has_{kind}") is not None or bool(self._tracks[kind])
            return known and not self._boxes[kind].checked_ids()

        video_stripped = stripped("video")
        audio_stripped = stripped("audio")
        subtitle_stripped = bool(self._tracks["subtitle"]) and not self.subtitle_box.checked_ids()
        self.sub_tab_bar.set_marked("Video", video_stripped)
        self.sub_tab_bar.set_marked("Audio", audio_stripped)
        self.sub_tab_bar.set_marked("Subtitles", subtitle_stripped)
        self.carousel.set_strip_state(video_stripped, audio_stripped)

        def codec_of(kind):
            """The source's codec of this kind; for a source without one, the first ticked track's."""
            if stripped(kind):
                return None
            if info.get(f"has_{kind}") is not False:
                return info.get(kind)
            first = next((entry for entry in self._tracks[kind]
                          if entry["id"] in set(self._boxes[kind].checked_ids())), None)
            return first["stream"].get("codec") if first else None

        video_codec = codec_of("video")
        audio_codec = codec_of("audio")
        subtitle_ok = formats.containers_for_subtitles(self._ticked_subtitle_codecs())
        self._retarget_container([c for c in formats.containers_for(video_codec, audio_codec) if c in subtitle_ok]
                                 or subtitle_ok)

        add_btns = {"video": self.video_add_btn, "audio": self.audio_add_btn,
                   "subtitle": self.subtitle_add_edit_btn}
        has_file = bool(current_path)
        # Add/Edit and Undo/Redo are live for every kind once a file is selected — a source without
        # audio (or video) is exactly when a track from another file is wanted. "has rows":
        # something to select, check or remove.
        for kind in ("video", "audio", "subtitle"):
            open_ = has_file
            has_rows = open_ and bool(self._tracks[kind])
            history = self._history[kind]
            self._boxes[kind].setEnabled(has_rows)
            add_btns[kind].setEnabled(open_)
            getattr(self, f"{kind}_remove_btn").setEnabled(has_rows)
            getattr(self, f"{kind}_select_all_btn").setEnabled(has_rows)
            getattr(self, f"{kind}_deselect_all_btn").setEnabled(has_rows)
            getattr(self, f"{kind}_undo_btn").setEnabled(open_ and bool(history["undo"]))
            getattr(self, f"{kind}_redo_btn").setEnabled(open_ and bool(history["redo"]))

        self._sync_chapters()
        self._refresh_summary()
        self._apply_import_gate()

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

        def stream(kind, box):
            if no_file:
                return "— no streams selected —", "stop"
            if info.get(f"has_{kind}") is False and not self._tracks[kind]:
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
            stream("video", self.video_box),
            stream("audio", self.audio_box),
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
    def _gather_strip_subtitles(self):
        """Computed in `_gather_settings` itself, from the track box — there's no checkbox here."""
        return {}

    def _apply_strip_flags(self, settings):
        """A preset's strip preference: uncheck every track of that kind on the next sync — this
        tab's only "strip" signal now that there's no checkbox (see `_sync_controls`)."""
        for kind, key in (("video", "strip_video"), ("audio", "strip_audio"), ("subtitle", "strip_subtitles")):
            if settings.get(key):
                self._restore_checked[kind] = set()

    def _gather_settings(self):
        settings = self._gather_common()
        video_tracks = self._track_args("video")
        audio_tracks = self._track_args("audio")
        subtitle_tracks = self._track_args("subtitle")
        settings.update({
            "video_tracks": video_tracks,
            "strip_video": not video_tracks,
            "audio_tracks": audio_tracks,
            "strip_audio": not audio_tracks,
            "subtitle_tracks": subtitle_tracks,
            "strip_subtitles": not subtitle_tracks,
        })
        return settings

    def _validate_specific(self, settings):
        """Nothing checked is a valid, deliberate "no ___" choice; the only real block is
        winding up with nothing to mux at all."""
        if not (settings["video_tracks"] or settings["audio_tracks"]):
            show_message(
                self.app, "Nothing to Mux",
                "Every video and audio track has been removed or deselected. Keep at least one "
                "track (Undo brings a removed one back).",
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
