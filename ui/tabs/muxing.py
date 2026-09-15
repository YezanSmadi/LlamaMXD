"""Muxing: change a file's container and/or choose which streams go into it.
**Nothing here ever re-encodes** — every stream is copied, which is what
separates this tab from Encoding rather than making it a weaker version.

Two consequences fall out of copy-only: there are no codec controls at all,
and the container filter runs **backwards** — the source's *existing* codecs
decide which containers it can be remuxed into (`formats.containers_for`)."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog

from core import formats
from ui.tabs.media_tab import MediaTab, hms, hrow, set_line_text
from ui.widgets.controls import CheckBox, Dropdown, button, labeled, set_enabled

# No "None" entry — removing a stream is the Strip checkbox's job.
_STREAM_TRACKS = ["Auto", "Track 1", "Track 2", "Track 3"]
_EXTERNAL_PREFIX = "External: "


class MuxingTab(MediaTab):
    TAB = "Muxing"
    ACTION_TEXT = "Mux"
    OUTPUT_SUFFIX = "_muxed"
    VERB_ING = "Muxing"
    DIRECT_LABEL = "Direct Mux"
    PRESET_NOTE = ("Name this preset. It stores the container and the strip flags — "
                   "not the trim, the track picks, or the file paths.")

    # Extra input files pulled in per stream via the panels' Browse buttons.
    _video_ext_file = None
    _audio_ext_file = None

    # ------------------------------------------------------------------ #
    #  Panels
    # ------------------------------------------------------------------ #
    def _stream_panel(self, kind):
        page, left, right = self.stream_page()
        row, rl = hrow(spacing=8)
        menu = Dropdown(_STREAM_TRACKS, width=Dropdown.width_for(["Track 3 (Dolby TrueHD)"], 150))
        menu.picked.connect(self._on_control_change)
        box, label = labeled(f"{kind} Track:", menu)
        rl.addWidget(box)
        browse = button("Browse…", width=76)
        browse.clicked.connect(lambda: self._browse_external(kind.lower()))
        rl.addWidget(browse, 0, Qt.AlignBottom)
        left.addWidget(row)
        left.addSpacing(4)
        check = CheckBox(f"Strip {kind}", color_key="stop")
        check.clicked.connect(self._on_control_change)
        right.addStretch(1)
        right.addWidget(check, 0, Qt.AlignRight)
        right.addSpacing(4)
        return page, menu, label, browse, check

    def build_video(self):
        page, self.video_track_menu, self.video_track_label, self.video_browse_btn, \
            self.strip_video_check = self._stream_panel("Video")
        return page

    def build_audio(self):
        page, self.audio_track_menu, self.audio_track_label, self.audio_browse_btn, \
            self.strip_audio_check = self._stream_panel("Audio")
        return page

    # ------------------------------------------------------------------ #
    #  External stream inputs
    # ------------------------------------------------------------------ #
    def _browse_external(self, kind):
        """Pulls a stream in from a second file; it appears in that panel's
        track dropdown as `External: <name>`."""
        if kind == "video":
            title, types = "Select Video Source", "Video Files (*.mp4 *.mkv *.avi *.mov *.webm *.mxf)"
        else:
            title = "Select Audio Source"
            types = "Audio / Video Files (*.mp3 *.aac *.ac3 *.flac *.opus *.wav *.m4a *.mp4 *.mkv *.mov)"
        path, _ = QFileDialog.getOpenFileName(self, title, "", types + ";;All Files (*.*)")
        if not path:
            return
        label = _EXTERNAL_PREFIX + os.path.basename(path.replace("\\", "/"))
        if kind == "video":
            self._video_ext_file = path
            self._sync_controls()
            self.video_track_menu.set(label)
        else:
            self._audio_ext_file = path
            self._sync_controls()
            self.audio_track_menu.set(label)
        self._sync_controls()

    def _track_values(self, external_path):
        values = list(_STREAM_TRACKS)
        if external_path:
            values.append(_EXTERNAL_PREFIX + os.path.basename(external_path.replace("\\", "/")))
        return values

    def _audio_track_values(self, external_path):
        """Audio's list, each real track annotated with its probed codec."""
        streams = {s["index"]: s for s in (self.app.media_info.get("audio_streams") or [])}
        values = ["Auto"]
        for i in range(1, len(_STREAM_TRACKS)):
            label = f"Track {i}"
            stream = streams.get(i - 1)
            if stream and stream.get("codec"):
                label += f" ({stream['codec']})"
            values.append(label)
        if external_path:
            values.append(_EXTERNAL_PREFIX + os.path.basename(external_path.replace("\\", "/")))
        return values

    @staticmethod
    def _external_for(menu, path):
        return path if path and menu.value().startswith(_EXTERNAL_PREFIX) else ""

    # ------------------------------------------------------------------ #
    #  The single constraint pass
    # ------------------------------------------------------------------ #
    def _sync_controls(self, *_):
        """**The only place derived UI state is decided.** Idempotent.
          1. stream presence — both stripped would write an empty file; a
             stream the source doesn't have reads the same as stripped
          2. track lists carry any browsed-in external file
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

        self.video_track_menu.set_values(self._track_values(self._video_ext_file))
        self.audio_track_menu.set_values(self._audio_track_values(self._audio_ext_file))

        video_codec = None if stripping_video else info.get("video")
        audio_codec = None if stripping_audio else info.get("audio")
        self._retarget_container(formats.containers_for(video_codec, audio_codec))

        video_live = not stripping_video and not video_absent
        audio_live = not stripping_audio and not audio_absent
        set_enabled(self.video_track_menu, self.video_track_label, video_live)
        self.video_browse_btn.setEnabled(video_live)
        set_enabled(self.audio_track_menu, self.audio_track_label, audio_live)
        self.audio_browse_btn.setEnabled(audio_live)

        self._refresh_summary()

    def _retarget_container(self, allowed):
        before = self.format_menu.value()
        self.format_menu.set_values(allowed)
        after = self.format_menu.value()
        if before != after:
            # Keep the save path's extension in step with a forced snap (the
            # CTk version left e.g. "_muxed.mp4" beside a snapped .mkv).
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

        def stream(kind, check, menu):
            if check.isChecked():
                return "— removed —", "stop"
            if info.get(f"has_{kind}") is False:
                return f"— no {kind} stream —", "stop"
            bits = ["copy"]
            actual = formats.short_name(info.get(kind))
            if actual:
                bits.append(actual)
            bits.append(menu.value())
            return " · ".join(bits), None

        start = self.start_time_spinner.seconds()
        duration = self.duration_time_spinner.seconds()
        if not start and not duration:
            length = ("Whole File", None)
        elif not duration:
            length = (f"{hms(start)} → end · keyframe", None)
        else:
            length = (f"{hms(start)} → {hms(start + duration)} · keyframe", None)
        self.summary.set_values([
            stream("video", self.strip_video_check, self.video_track_menu),
            stream("audio", self.strip_audio_check, self.audio_track_menu),
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
            "video_track": self.video_track_menu.value(),
            "video_track_file": self._external_for(self.video_track_menu, self._video_ext_file),
            "strip_video": self.strip_video_check.isChecked(),
            "audio_track": self.audio_track_menu.value(),
            "audio_track_file": self._external_for(self.audio_track_menu, self._audio_ext_file),
            "strip_audio": self.strip_audio_check.isChecked(),
        })
        return settings

    def _apply_settings(self, settings):
        if not settings:
            return
        was_ready, self._ready = self._ready, False
        try:
            self._apply_common(settings)
            if settings.get("video_track_file"):
                self._video_ext_file = settings["video_track_file"]
            if settings.get("audio_track_file"):
                self._audio_ext_file = settings["audio_track_file"]
            if "output_format" in settings:
                self.format_menu.set(settings["output_format"])
                self._auto_format = None
            self._sync_controls()
            self._set_menu(self.video_track_menu, settings.get("video_track"))
            self._set_menu(self.audio_track_menu, settings.get("audio_track"))
        finally:
            self._ready = was_ready
        self._sync_controls()

    @staticmethod
    def _set_menu(menu, value):
        """Select `value`, or the entry sharing its leading "Track N" token
        (a saved dict from before the "(codec)" suffix still lands)."""
        if value is None:
            return
        values = menu.values()
        if value in values:
            menu.set(value)
            return
        prefix = value.split(" (")[0]
        for candidate in values:
            if candidate.split(" (")[0] == prefix:
                menu.set(candidate)
                return
