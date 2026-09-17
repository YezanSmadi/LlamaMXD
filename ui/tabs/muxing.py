"""Muxing: change a file's container and/or choose which streams go into it.
**Nothing here ever re-encodes** — every stream is copied, which is what
separates this tab from Encoding rather than making it a weaker version.

Two consequences fall out of copy-only: there are no codec controls at all,
and the container filter runs **backwards** — the source's *existing* codecs
decide which containers it can be remuxed into (`formats.containers_for`).

Video and Audio each show a `TrackListBox`: every track the source (or a
file pulled in via "Add Stream(s)") has, one checkbox apiece, all mapped
into the output — not the single "Auto"/"Track N" pick this tab used to
offer."""
import os
import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QVBoxLayout, QWidget

from core import formats
from core.utilities import probe_media
from ui.tabs.media_tab import STRIP_TIP, MediaTab, hms, hrow, set_line_text
from ui.widgets.controls import CheckBox, button, button_width_for
from ui.widgets.dialogs import pick_external_streams, show_message
from ui.widgets.tooltip import tip
from ui.widgets.tracklist import TrackListBox
from ui.workers import run_async

_TRACK_TIP = ("Check as many streams as the output should carry — muxing never "
              "re-encodes them. \"Add Stream(s)\" pulls one in from another file.")
_REMOVE_TIP = ("Excludes every checked track from the output — one pulled in with "
               "\"Add Stream(s)\" is dropped outright, a source track is simply unchecked.")

_VIDEO_BROWSE_FILTER = "Video Files (*.mp4 *.mkv *.avi *.mov *.webm *.mxf *.ts *.vob)"
_AUDIO_BROWSE_FILTER = ("Audio / Video Files (*.mp3 *.aac *.ac3 *.flac *.opus *.wav *.m4a "
                         "*.mp4 *.mkv *.mov *.mxf *.ts *.vob)")


def _describe_stream(kind, stream):
    """One row's label: "Track N · codec · ... · language", the video/audio
    fields chosen per kind (mirrors AudioStreamPickerDialog's own format)."""
    bits = [f"Track {stream['index'] + 1}"]
    keys = (("codec", "resolution_display", "language") if kind == "video"
            else ("codec", "channels_display", "sample_rate_display", "language"))
    for key in keys:
        if stream.get(key):
            bits.append(str(stream[key]))
    return "  ·  ".join(bits)


class MuxingTab(MediaTab):
    TAB = "Muxing"
    ACTION_TEXT = "Mux"
    OUTPUT_SUFFIX = "_muxed"
    VERB_ING = "Muxing"
    DIRECT_LABEL = "Direct Mux"
    PRESET_NOTE = ("Name this preset. It stores the container and the strip flags — "
                   "not the trim, the track picks, or the file paths.")

    def _init_state(self):
        # Streams pulled in from another file via "Add Stream":
        # {row_id: {"file": path, "index": N, "label": str}}, per kind.
        self._video_external = {}
        self._audio_external = {}
        # The file the boxes' rows currently describe -- differs from
        # app.current_file_path exactly when the input just changed, which is
        # when stream indices stop meaning what they meant a moment ago and
        # the boxes need a hard reset rather than a same-id refresh.
        self._tracks_file = None

    # ------------------------------------------------------------------ #
    #  Panels
    # ------------------------------------------------------------------ #
    def _track_panel(self, kind):
        """The box fills the row, stopping only where the Add/Remove Stream(s)
        + Strip column begins, so the whole panel stays as short as
        Encoding's own Video/Audio panels: the tab-wide preview above is
        sized off whichever sub-tab page is tallest, so a taller Muxing
        panel would shrink the preview on this tab alone relative to
        Encoding's. "Add Stream(s)" sits above; "Remove Stream(s)" (which
        acts on every checked row, deleting the ones it can and unchecking
        the ones it can't — see `_remove_streams`) shares a line with Strip
        below it, matching width so the pair stacks flush."""
        btn_width = button_width_for(["Add Stream(s)", "Remove Stream(s)"])
        row, rl = hrow(spacing=10, align_bottom=True)
        box = TrackListBox()
        # Maximize the box rather than leaving it at TrackListBox's own
        # floor: the Overview page (already built and in `self.panels` by
        # the time build_video/build_audio run) is what actually sets this
        # tab's page-height ceiling, so growing the box up to that height
        # costs nothing -- the panel stack's sizeHint (and the preview
        # above it) stays exactly where Overview already put it. Fixed, not
        # just raising the floor -- the box's own height must never move
        # once a file's probed tracks (or several "Add Stream(s)" pulls)
        # populate it; see TrackListBox's own fixed-height comment.
        overview_height = self.panels.widget(0).sizeHint().height()
        box.setFixedHeight(max(box.height(), overview_height))
        box.changed.connect(self._on_control_change)
        tip(box, _TRACK_TIP)
        rl.addWidget(box, 1)

        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(6)
        add_btn = button("Add Stream(s)", width=btn_width)
        add_btn.clicked.connect(lambda: self._add_stream(kind.lower()))
        sl.addWidget(add_btn)
        bottom, bl = hrow(spacing=8, align_bottom=True)
        remove_btn = button("Remove Stream(s)", role="danger", width=btn_width)
        remove_btn.clicked.connect(lambda: self._remove_streams(kind.lower()))
        tip(remove_btn, _REMOVE_TIP)
        bl.addWidget(remove_btn)
        check = CheckBox(f"Strip {kind}", color_key="stop")
        check.clicked.connect(self._on_control_change)
        tip(check, STRIP_TIP)
        bl.addWidget(check)
        sl.addWidget(bottom)
        rl.addWidget(side, 0, Qt.AlignBottom)

        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        outer.addWidget(row)
        return page, box, add_btn, remove_btn, check

    def build_video(self):
        page, self.video_box, self.video_add_btn, self.video_remove_btn, \
            self.strip_video_check = self._track_panel("Video")
        return page

    def build_audio(self):
        page, self.audio_box, self.audio_add_btn, self.audio_remove_btn, \
            self.strip_audio_check = self._track_panel("Audio")
        return page

    # ------------------------------------------------------------------ #
    #  "Add Stream" — browse a file, probe it off the GUI thread, then
    #  (when it holds more than one matching track) let the user pick which
    # ------------------------------------------------------------------ #
    def _add_stream(self, kind):
        if kind == "video":
            title, types = "Select Video Source", _VIDEO_BROWSE_FILTER
        else:
            title, types = "Select Audio Source", _AUDIO_BROWSE_FILTER
        path, _ = QFileDialog.getOpenFileName(self, title, "", types + ";;All Files (*.*)")
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
        store = self._video_external if kind == "video" else self._audio_external
        name = os.path.basename(path.replace("\\", "/"))
        for stream in streams:
            row_id = f"ext:{uuid.uuid4().hex[:8]}"
            store[row_id] = {
                "file": path, "index": stream["index"],
                "label": f"External: {name}  —  {_describe_stream(kind, stream)}",
            }
        self._sync_controls()

    def _remove_streams(self, kind):
        """"Remove Stream(s)": every checked row stops being included in the
        output. A row "Add Stream(s)" pulled in is dropped outright; a
        source row — the file's own track — can't actually be deleted (the
        file still has it), so it's simply unchecked instead, exactly as if
        its own checkbox had been clicked off. Either way, checking a row
        and pressing this button means "get rid of this one"."""
        box = self.video_box if kind == "video" else self.audio_box
        store = self._video_external if kind == "video" else self._audio_external
        checked = box.checked_ids()
        if not checked:
            show_message(
                self.app, "Nothing to Remove",
                f"Check the {kind} track(s) you want removed, then press Remove Stream(s) again.",
            )
            return
        for row_id in checked:
            if row_id in store:
                store.pop(row_id, None)
            else:
                box.set_checked(row_id, False)
        self._sync_controls()

    # ------------------------------------------------------------------ #
    #  Track box contents
    # ------------------------------------------------------------------ #
    def _items_for(self, kind):
        streams = self.app.media_info.get(f"{kind}_streams") or []
        items = [{"id": f"src:{s['index']}", "label": _describe_stream(kind, s)} for s in streams]
        store = self._video_external if kind == "video" else self._audio_external
        items += [{"id": row_id, "label": data["label"]} for row_id, data in store.items()]
        return items

    def _track_args(self, kind):
        """Every checked row in `kind`'s box, translated into the shape
        `ffmpeg_vars`/`build_mux_command` map straight to a `-map`."""
        box = self.video_box if kind == "video" else self.audio_box
        store = self._video_external if kind == "video" else self._audio_external
        args = []
        for row_id in box.checked_ids():
            if row_id.startswith("src:"):
                args.append({"source": "primary", "file": None, "index": int(row_id.split(":", 1)[1])})
            else:
                entry = store.get(row_id)
                if entry:
                    args.append({"source": "external", "file": entry["file"], "index": entry["index"]})
        return args

    # ------------------------------------------------------------------ #
    #  The single constraint pass
    # ------------------------------------------------------------------ #
    def _sync_controls(self, *_):
        """**The only place derived UI state is decided.** Idempotent.
          1. stream presence — both stripped would write an empty file; a
             stream the source doesn't have reads the same as stripped
          2. the track boxes carry the source's own streams plus any browsed-
             in external ones — reset (indices renumbered from scratch)
             exactly when the input file itself just changed
          3. **the container inversion** — the source's own codecs decide
             which containers are reachable
          4. a stripped or absent stream disables its own panel
          5. the Overview rundown"""
        stripping_video = self.strip_video_check.isChecked()
        stripping_audio = self.strip_audio_check.isChecked()
        info = self.app.media_info
        video_absent = info.get("has_video") is False
        audio_absent = info.get("has_audio") is False

        self.strip_video_check.setEnabled(not (stripping_audio or video_absent))
        self.strip_audio_check.setEnabled(not (stripping_video or audio_absent))
        self.sub_tab_bar.set_marked("Video", stripping_video or video_absent)
        self.sub_tab_bar.set_marked("Audio", stripping_audio or audio_absent)
        self.carousel.set_strip_state(stripping_video, stripping_audio or audio_absent)

        current_path = self.app.current_file_path
        reset = current_path != self._tracks_file
        self.video_box.set_items(self._items_for("video"), reset=reset)
        self.audio_box.set_items(self._items_for("audio"), reset=reset)
        self._tracks_file = current_path

        video_codec = None if stripping_video else info.get("video")
        audio_codec = None if stripping_audio else info.get("audio")
        self._retarget_container(formats.containers_for(video_codec, audio_codec))

        video_live = not stripping_video and not video_absent
        audio_live = not stripping_audio and not audio_absent
        self.video_box.setEnabled(video_live)
        self.video_add_btn.setEnabled(video_live)
        self.video_remove_btn.setEnabled(video_live)
        self.audio_box.setEnabled(audio_live)
        self.audio_add_btn.setEnabled(audio_live)
        self.audio_remove_btn.setEnabled(audio_live)

        self._refresh_summary()

    def _retarget_container(self, allowed):
        before = self.format_menu.value()
        self.format_menu.set_values(allowed)
        after = self.format_menu.value()
        self._update_format_tip()
        if before != after:
            # Keep the save path's extension in step with a forced snap, so
            # a snapped .mkv never sits beside "_muxed.mp4".
            stem, extension = os.path.splitext(self.save_entry.text().strip())
            if extension:
                set_line_text(self.save_entry, stem + after)
        if self._ready and before != after:
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
            checked = box.checked_ids()
            if not checked:
                return "— no streams selected —", "stop"
            bits = ["copy"]
            actual = formats.short_name(info.get(kind))
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
        """Adopt the source's own container (while the user hasn't picked
        one), then re-run the cascade — which narrows the container list."""
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
        """Encoding never lets a present stream queue on an unresolved
        codec; Muxing's equivalent is a track box with rows but nothing
        checked — the box being *empty* (nothing probed, or the source
        genuinely lacks that stream) isn't an error, there's simply nothing
        to pick."""
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
        return True

    def _apply_settings(self, settings):
        """Presets only ever carry the recipe keys (output_format, av_sync,
        strip_video, strip_audio) — never track picks, which are per-file
        job state (see core/presets.py)."""
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
