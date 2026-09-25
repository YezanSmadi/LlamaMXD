# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Encoding: the superset tab — Overview (container, trim, presets, rundown),
Video (encoder / profile / level / preset, quality, HDR→SDR, Strip Video) and
Audio (multi-stream: track, codec, passthru, bitrate, channels, sample rate,
Strip Audio).

Every derived control state is decided by one function, `_sync_controls`.
Encoding never falls back to a silent stream copy: `Select` auto-resolves to
the source's own codec once probed, and `_validate_specific` blocks a
present-or-unknown stream left on `Select`."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSlider, QVBoxLayout, QWidget

from core import formats
from core.utilities import av1_preset_range, libplacebo_problem_text, supports_libplacebo
from ui import scale
from ui.tabs.media_tab import STRIP_TIP, MediaTab, hms, hrow
from ui.widgets.controls import (
    NO_OPTION,
    CheckBox,
    ClickableLabel,
    Dropdown,
    ScaledLabel,
    Switch,
    button,
    field_label,
    labeled,
    set_enabled,
)
from ui.widgets.dialogs import choose_audio_streams, show_message
from ui.widgets.tooltip import tip
from ui.tips import (
    AUDIO_CODEC_TIPS,
    SELECT_AUDIO_CODEC_TIP,
    SELECT_VIDEO_CODEC_TIP,
    VIDEO_CODEC_TIPS,
)

# The quality slider's range when the encoder has no spec of its own
# (`Select`) — it stays usable rather than freezing on a stale range.
_FALLBACK_QUALITY = {
    "kind": "crf", "label": "Quality (CRF)", "lo": 0, "hi": 51,
    "default": 22, "low": "Low", "high": "Placebo",
}

_SPEED_TIP = ("Trades encode speed for compression efficiency — slower settles on a "
              "smaller file at the same quality.")
_PROFILE_LEVEL_TIP = ("Constrains playback compatibility (older devices/decoders may "
                       "only support certain profiles/levels).")
_HDR_TIP = ("Tone-maps HDR (PQ/BT.2020) down to standard SDR (BT.709) using BT.2390 — "
            "the only curve this app uses, for accurate color.")
_PASSTHRU_TIP = ("Copies this stream byte-for-byte instead of re-encoding it — Bitrate/"
                  "Channels/Sample Rate below just show the source's real values.")
_CHOOSE_STREAMS_TIP = ("Pick which audio tracks the output includes and in what order (drag to reorder), "
                       "and add tracks from other files.")
_CRF_TIP = "Lower = higher quality, larger file. This encoder doesn't target a bitrate — it targets a visual quality level."
_QSCALE_TIP = "Lower = higher quality, larger file. This is a fixed qscale, not a CRF — this codec has no bitrate-target rate control."
_RESOLUTION_TIP = ("Downscales the video, keeping its aspect ratio — the width is computed "
                    "from the source's own ratio, never stretched or cropped. Never upscales: "
                    "only rungs at or below the source's own height are offered.")
_FPS_TIP = ("Retimes the video to a lower frame rate, duplicating or dropping frames as "
            "needed. Never speeds up: only rates at or below the source's own are offered.")


class EncodingTab(MediaTab):
    TAB = "Encoding"
    ACTION_TEXT = "Encode"
    OUTPUT_SUFFIX = "_encoded"
    VERB_ING = "Encoding"
    DIRECT_LABEL = "Direct Encode"
    PRESET_NOTE = ("Name this preset. It stores the container and every codec / "
                   "quality setting — not the trim, and not the file paths.")

    def _init_state(self):
        self._quality_spec = None
        # The auto-picked Encoder (None once the user picks one themselves).
        self._auto_encoder = formats.SELECT
        # Multi-stream audio. `_audio_list` is every audio stream on offer, in the
        # order the Choose Stream(s) popup shows them (which is the output's order):
        # the source file's own (seeded from the probe) then any added from other
        # files, each `{"id": "src:0" | "ext:ab12cd34", "source": "primary" |
        # "external", "file": path | None, "index": N (0-based among that file's own
        # audio streams — what `-map` addresses), "stream": the probe's description
        # of it, "name": the other file's name | None}` — the same shape Muxing's
        # track lists use. `_audio_included` is the ids that go into the output, the
        # active one is what the four shared controls are editing, and every
        # stream's own settings are kept by id (so switching tracks never loses an
        # edit). `_audio_track_ids` maps the Audio Track dropdown's labels back.
        self._audio_list = []
        self._audio_included = set()
        self._active_audio_id = None
        self._audio_stream_settings = {}
        self._audio_track_ids = {}
        self._audio_streams_source = None
        # HDR→SDR preview: which file this tab is showing and its raw frames
        # (the tone-mapped cache lives on the app).
        self._preview_path = None
        self._raw_frames = []

    # ------------------------------------------------------------------ #
    #  Panels
    # ------------------------------------------------------------------ #
    def build_video(self):
        """Encoder / Profile / Level / Encoder Preset / Resolution on one row
        (Resolution's own column stacking FPS directly beneath it), with the
        quality slider spanning the row beneath; the right column holds
        HDR→SDR (top) then Strip Video (bottom), right-aligned."""
        page, left, right = self.stream_page()
        scale.spacing(left, 0)   # replaces stream_page()'s own 6
        # This page has no width to spare: the dropdown row needs 527 reference
        # pixels and the HDR column 112, in a 656px page. It was laid out to fit
        # with 6px over when text was measured hinted; unhinted text (which is
        # what is actually painted) measures ~1-3% wider — the dropdowns 6px
        # more in all, the HDR label 3px — which left it 3px short, so Qt
        # squeezed the Profile box under its own dropdown and cut its arrow off
        # (at every scale, since the shortfall scales too). The gutter between
        # the columns (replacing stream_page()'s 20) and the HDR label/switch
        # gap (below) give the 9px back.
        scale.spacing(page.layout(), 14)
        row, rl = hrow(spacing=8)
        # Each dropdown is sized to the longest entry it could ever show,
        # across every encoder — not just whatever's legal right now — so
        # picking a longer value never clips or resizes the box.
        encoder_universe = [formats.SELECT] + list(formats.VIDEO_ENCODERS)
        profile_universe = [NO_OPTION] + [
            p for enc in formats.VIDEO_ENCODERS for p in formats.profiles_for(enc)
        ]
        level_universe = [NO_OPTION] + [
            lvl for enc in formats.VIDEO_ENCODERS for lvl in formats.levels_for(enc)
        ]
        speed_universe = [NO_OPTION] + [
            s for enc in formats.VIDEO_ENCODERS for s in formats.speed_values_for(enc)
        ]
        encoder_width = Dropdown.width_for(encoder_universe)
        self.encoder_menu = Dropdown([formats.SELECT], width=encoder_width)
        self.encoder_menu.picked.connect(self._on_encoder_change)
        # MPEG-4's "Advanced Simple" is far longer than every other codec's
        # widest profile ("Professional") — sizing for it would make every
        # encoder's Profile box noticeably wider than Encoder/Level/Encoder
        # Preset just to cover one rare legacy value, which elides instead.
        profile_width = Dropdown.width_for([p for p in profile_universe if p != "Advanced Simple"])
        self.profile_menu = Dropdown([NO_OPTION], width=profile_width)
        level_width = Dropdown.width_for(level_universe)
        self.level_menu = Dropdown([NO_OPTION], width=level_width)
        speed_width = Dropdown.width_for(speed_universe)
        self.speed_menu = Dropdown([NO_OPTION], width=speed_width)
        self.resolution_menu = Dropdown([formats.SOURCE_RESOLUTION],
                                        width=Dropdown.width_for(formats.RESOLUTIONS))
        fps_width = Dropdown.width_for(formats.FPS_VALUES)
        self.fps_menu = Dropdown([formats.SOURCE_FPS], width=fps_width)
        for menu in (self.profile_menu, self.level_menu, self.speed_menu,
                     self.resolution_menu, self.fps_menu):
            menu.picked.connect(self._on_control_change)
        box, self.encoder_label = labeled("Encoder:", self.encoder_menu)
        rl.addWidget(box)
        tip(self.profile_menu, _PROFILE_LEVEL_TIP)
        box, self.profile_label = labeled("Profile:", self.profile_menu)
        rl.addWidget(box)
        tip(self.level_menu, _PROFILE_LEVEL_TIP)
        box, self.level_label = labeled("Level:", self.level_menu)
        rl.addWidget(box)
        # Internally still "speed" — only the on-screen label changed.
        tip(self.speed_menu, _SPEED_TIP)
        box, self.speed_label = labeled("Encoder Preset:", self.speed_menu)
        rl.addWidget(box)
        tip(self.resolution_menu, _RESOLUTION_TIP)
        box, self.resolution_label = labeled("Resolution:", self.resolution_menu)
        rl.addWidget(box)
        left.addWidget(row)

        self.crf_label = field_label("Quality")
        self.crf_label.setAlignment(Qt.AlignCenter)
        tip(self.fps_menu, _FPS_TIP)
        # "FPS:" sits on its own caption row beside "Quality (CRF): NN"
        # (below) rather than stacked directly on top of the FPS dropdown
        # in a `labeled()` box — keeping the dropdown itself a direct,
        # un-wrapped sibling of `slider_row` in `quality_row` (below) is
        # what keeps their vertical alignment identical to before this
        # caption existed at all, rather than fighting to re-centre the
        # slider against a taller box.
        self.fps_label = field_label("FPS:")
        scale.fixed(self.fps_label, w=fps_width)
        caption_row, cpl = hrow(spacing=8, align_bottom=False)
        cpl.addWidget(self.crf_label)
        cpl.addWidget(self.fps_label)
        left.addWidget(caption_row)
        slider_row, sr = hrow(spacing=4, align_bottom=False)
        self.crf_low_label = ScaledLabel("Low")
        self.crf_low_label.setProperty("role", "muted")
        self.crf_high_label = ScaledLabel("Placebo")
        self.crf_high_label.setProperty("role", "muted")
        self.crf_high_label.setStyleSheet("font-size: 12px;")
        # Inverted so worst quality sits left and best right, whichever scale
        # (CRF or qscale — both count *down* toward better) is active.
        self.crf_slider = QSlider(Qt.Horizontal)
        self.crf_slider.setInvertedAppearance(True)
        self.crf_slider.setFocusPolicy(Qt.NoFocus)
        self.crf_slider.setCursor(Qt.PointingHandCursor)
        self.crf_slider.setRange(_FALLBACK_QUALITY["lo"], _FALLBACK_QUALITY["hi"])
        self.crf_slider.setValue(_FALLBACK_QUALITY["default"])
        self.crf_slider.valueChanged.connect(self._on_quality_change)
        sr.addWidget(self.crf_low_label)
        sr.addWidget(self.crf_slider, 1)
        sr.addWidget(self.crf_high_label)
        # Fixed to exactly span Encoder..Encoder Preset (not Resolution's own
        # column to the right) — width alone, since its own row would
        # otherwise stretch it to fill the full available width by default —
        # so "Placebo" ends flush with Encoder Preset's own right edge
        # rather than trailing off under a column the slider has nothing to
        # do with. `crf_label` gets the identical width for the same reason,
        # so "Quality (CRF): 22" centres over the slider itself rather than
        # the wider Encoder..Resolution span `left`'s own column spans.
        quality_width = encoder_width + profile_width + level_width + speed_width + 8 * 3
        scale.fixed(slider_row, w=quality_width)
        scale.fixed(self.crf_label, w=quality_width)
        # FPS sits beside the slider, in the space its fixed width leaves
        # under Resolution's own column — same 8px gap the row above uses
        # before Resolution, and (Resolution's and FPS's value lists both
        # happening to size to the same width) it lands exactly under
        # Resolution's dropdown. Added as a direct, un-wrapped sibling of
        # `slider_row` — not inside a `labeled()` box with its own caption
        # — so the two vertically align exactly the way they did before FPS
        # had a caption at all (the caption itself lives in `caption_row`
        # above, not here).
        quality_row, ql = hrow(spacing=8, align_bottom=True)
        ql.addWidget(slider_row)
        ql.addWidget(self.fps_menu)
        left.addWidget(quality_row)

        hdr_row, hl = hrow(spacing=5, align_bottom=False)
        self.hdr_label = ClickableLabel("HDRtoSDR")
        self.hdr_label.setCursor(Qt.PointingHandCursor)
        self.hdr_label.clicked.connect(self._toggle_hdr)
        self.hdr_switch = Switch()
        self.hdr_switch.clicked.connect(self._on_hdr_toggle)
        tip(self.hdr_label, _HDR_TIP)
        tip(self.hdr_switch, _HDR_TIP)
        hl.addWidget(self.hdr_label)
        hl.addWidget(self.hdr_switch)
        self.strip_video_check = CheckBox("Strip Video", color_key="stop")
        self.strip_video_check.clicked.connect(self._on_control_change)
        tip(self.strip_video_check, STRIP_TIP)
        scale.spacer(right, 26)   # aligns HDR with the dropdown row's top
        right.addWidget(hdr_row, 0, Qt.AlignRight)
        right.addStretch(1)
        right.addWidget(self.strip_video_check, 0, Qt.AlignRight | Qt.AlignBottom)
        return page

    def build_audio(self):
        """Audio Track + Choose Stream(s) + Passthru on one row; then Codec /
        Bitrate / Channels / Sample Rate for whichever stream Track shows;
        Strip Audio alone on the right. Each dropdown is sized to its longest
        possible entry."""
        page, left, right = self.stream_page()
        row1, r1 = hrow(spacing=8)
        track_universe = [f"Track 9 ({c})" for c in
                          list(formats.AUDIO_ENCODERS) + list(formats.PASSTHRU_ONLY_CODECS)]
        self.audio_track_menu = Dropdown([NO_OPTION], width=Dropdown.width_for(track_universe))
        self.audio_track_menu.picked.connect(self._on_audio_track_change)
        box, self.audio_track_label = labeled("Audio Track:", self.audio_track_menu)
        r1.addWidget(box)
        self.choose_streams_btn = button("Choose Stream(s)", width=130)
        self.choose_streams_btn.clicked.connect(self._open_stream_picker)
        tip(self.choose_streams_btn, _CHOOSE_STREAMS_TIP)
        r1.addWidget(self.choose_streams_btn, 0, Qt.AlignBottom)

        # Passthru: its own caption above the checkbox, both centred, next
        # to the stream picker it most directly relates to. On by default —
        # a probed stream defaults to a plain copy, not a re-encode.
        passthru = QWidget()
        pl = QVBoxLayout(passthru)
        scale.margins(pl, 0, 0, 0, 2)
        scale.spacing(pl, 1)
        self.passthru_label = field_label("Passthru")
        self.passthru_check = CheckBox(checked=True)
        tip(self.passthru_label, _PASSTHRU_TIP)
        tip(self.passthru_check, _PASSTHRU_TIP)
        pl.addWidget(self.passthru_label, 0, Qt.AlignHCenter)
        pl.addWidget(self.passthru_check, 0, Qt.AlignHCenter)
        r1.addWidget(passthru, 0, Qt.AlignBottom)
        left.addWidget(row1)

        row2, r2 = hrow(spacing=10)
        codec_universe = list(formats.AUDIO_ENCODERS) + list(formats.PASSTHRU_ONLY_CODECS) + [formats.SELECT]
        self.audio_codec_menu = Dropdown([formats.SELECT], width=Dropdown.width_for(codec_universe))
        box, self.audio_codec_label = labeled("Audio Codec:", self.audio_codec_menu)
        r2.addWidget(box)

        bitrate_universe = [formats.SELECT, formats.LOSSLESS] + formats.AUDIO_BITRATES
        self.audio_bitrate_menu = Dropdown([NO_OPTION], width=Dropdown.width_for(bitrate_universe))
        box, self.audio_bitrate_label = labeled("Bitrate:", self.audio_bitrate_menu)
        r2.addWidget(box)
        self.audio_channels_menu = Dropdown(formats.AUDIO_CHANNELS,
                                            width=Dropdown.width_for(formats.AUDIO_CHANNELS))
        self.audio_channels_menu.set(formats.SELECT)
        box, self.audio_channels_label = labeled("Channels:", self.audio_channels_menu)
        r2.addWidget(box)
        self.audio_samplerate_menu = Dropdown(formats.AUDIO_SAMPLE_RATES,
                                              width=Dropdown.width_for(formats.AUDIO_SAMPLE_RATES))
        self.audio_samplerate_menu.set(formats.SELECT)
        box, self.audio_samplerate_label = labeled("Sample Rate:", self.audio_samplerate_menu)
        r2.addWidget(box)
        for control in (self.audio_codec_menu, self.audio_bitrate_menu,
                        self.audio_channels_menu, self.audio_samplerate_menu):
            control.picked.connect(self._on_control_change)
        self.passthru_check.clicked.connect(self._on_control_change)
        left.addWidget(row2)
        scale.spacer(left, 2)

        self.strip_audio_check = CheckBox("Strip Audio", color_key="stop")
        self.strip_audio_check.clicked.connect(self._on_control_change)
        tip(self.strip_audio_check, STRIP_TIP)
        right.addStretch(1)
        right.addWidget(self.strip_audio_check, 0, Qt.AlignRight)
        scale.spacer(right, 4)
        return page

    # ------------------------------------------------------------------ #
    #  Change handlers
    # ------------------------------------------------------------------ #
    def _on_encoder_change(self, *_):
        """The user picked an Encoder — stop auto-adopting the source's."""
        self._auto_encoder = None
        self._sync_controls()

    def _toggle_hdr(self):
        if self.hdr_switch.isEnabled():
            self.hdr_switch.toggle()
            self._on_hdr_toggle()

    def _on_quality_change(self, _value=None):
        self._update_quality_label()
        if self._ready:
            self._refresh_summary()

    # ------------------------------------------------------------------ #
    #  HDR→SDR preview
    # ------------------------------------------------------------------ #
    def _on_hdr_toggle(self, *_):
        self._sync_controls()
        self._apply_preview_frames()
        if self.hdr_switch.isChecked() and self.app.hdr_frames_path != self._preview_path:
            self.app.start_hdr_render(self._preview_path)

    def reset_hdr_preview(self):
        """A new file is coming in (`MainWindow.update_global_file`): HDR→SDR
        starts back off, so the app never renders a tone-mapped preview
        nobody's asked for on the file replacing this one — the app
        separately interrupts any render already in flight for the outgoing
        file. Skips the raw/tone-mapped frame swap `_on_hdr_toggle` would do:
        the carousel's about to be cleared for the new file anyway, so
        re-showing the outgoing file's raw frames here would just flash."""
        if not self.hdr_switch.isChecked():
            return
        self.hdr_switch.setChecked(False)
        self._sync_controls()

    def on_thumbnails(self, frames):
        """Wraps the app's raw frame broadcast so HDR→SDR can show a
        tone-mapped set in its place."""
        self._preview_path = self.app.current_file_path
        self._raw_frames = frames
        self._apply_preview_frames()
        if self.hdr_switch.isChecked() and self.app.hdr_frames_path != self._preview_path:
            self.app.start_hdr_render(self._preview_path)

    def on_hdr_frames_ready(self, path, _frames):
        """The render finished. With the switch off there is nothing to change — the render
        starts on import, so it usually lands while the raw previews are being scrubbed, and
        re-applying them would reset the carousel under the user's cursor."""
        if path == self._preview_path and self.hdr_switch.isChecked():
            self._apply_preview_frames()

    def _apply_preview_frames(self):
        """The cached tone-mapped set when it's on, ready and for this file;
        the raw set otherwise — keeping the scrub position across the swap."""
        show_hdr = (
            self.hdr_switch.isChecked()
            and self.app.hdr_frames is not None
            and self.app.hdr_frames_path == self._preview_path
        )
        frames = self.app.hdr_frames if show_hdr else self._raw_frames
        if not frames:
            return
        index = self.carousel.current_index()
        self.carousel.set_frames(frames)
        self.carousel.sync_index(index)

    # ------------------------------------------------------------------ #
    #  The single constraint pass
    # ------------------------------------------------------------------ #
    def _sync_controls(self, *_):
        """**The only place derived UI state is decided.** Idempotent.
          1. stream presence (strip / absent) — red tabs, locked strips
          2. container → legal video/audio codec lists
          3. video codec → profile / level / speed / quality kind and range;
             source height → the Resolution ladder (never offers an upscale)
          4. audio codec → whether a bitrate is ours to set (Passthru mirrors
             the source instead)
          5. enabled state for everything a removed, absent or unresolved
             stream makes meaningless (HDR→SDR forced off when unavailable)
          6. the Overview rundown"""
        container = self.format_menu.value()
        self._update_format_tip()
        stripping_video = self.strip_video_check.isChecked()
        stripping_audio = self.strip_audio_check.isChecked()
        info = self.app.media_info
        video_absent = info.get("has_video") is False
        audio_absent = info.get("has_audio") is False

        # 1.
        self.strip_video_check.setEnabled(not (stripping_audio or video_absent))
        self.strip_audio_check.setEnabled(not (stripping_video or audio_absent))
        self.sub_tab_bar.set_marked("Video", stripping_video or video_absent)
        self.sub_tab_bar.set_marked("Audio", stripping_audio or audio_absent)
        self.carousel.set_strip_state(stripping_video, stripping_audio or audio_absent)

        # 2. A probe-only passthru codec (DTS / TrueHD) is never snapped away.
        self._retarget(self.encoder_menu, formats.video_codecs_for(container), "Encoder")
        encoder = self.encoder_menu.value()
        tip(self.encoder_menu, VIDEO_CODEC_TIPS.get(encoder, SELECT_VIDEO_CODEC_TIP))
        audio_codec = self.audio_codec_menu.value()
        passthru_only = formats.is_passthru_only(audio_codec)
        if not passthru_only:
            audio_codec = self._retarget(
                self.audio_codec_menu, formats.audio_codecs_for(container), "Audio codec")
        tip(self.audio_codec_menu, AUDIO_CODEC_TIPS.get(audio_codec, SELECT_AUDIO_CODEC_TIP))

        # 3.
        profiles = formats.profiles_for(encoder)
        levels = formats.levels_for(encoder)
        speeds = self._speed_values(encoder)
        self._retarget(self.profile_menu, profiles)
        self._retarget(self.level_menu, levels)
        self._apply_speed(encoder)
        self._quality_spec = formats.quality_for(encoder)
        self._apply_quality()
        self._retarget_resolution(info.get("height"))
        self._retarget_fps(info.get("fps"))

        # 3b. The Audio Track list mirrors the included streams.
        track_values = self._audio_track_values()
        self.audio_track_menu.set_values(track_values)
        if self._active_audio_id is not None:
            label = next((l for l, i in self._audio_track_ids.items() if i == self._active_audio_id), None)
            if label is not None:
                self.audio_track_menu.set(label)

        # 4.
        if passthru_only:
            self.passthru_check.setChecked(True)
        passthru = self.passthru_check.isChecked()
        bitrates = [] if passthru else formats.audio_bitrates_for(audio_codec)
        if not passthru:
            # A lossless codec has no bitrate to set — it says so, rather than
            # the "—" of "nothing to pick yet" (the control stays disabled).
            lossless = [formats.LOSSLESS] if formats.is_lossless_audio(audio_codec) else []
            self._retarget(self.audio_bitrate_menu, bitrates or lossless)
        else:
            self._apply_passthru_values()

        # 5.
        audio_unresolved = audio_codec == formats.SELECT
        if audio_unresolved and not passthru:
            self.audio_channels_menu.set(formats.SELECT)
            self.audio_samplerate_menu.set(formats.SELECT)
        video_live = not stripping_video and not video_absent
        audio_live = not stripping_audio and not audio_absent

        set_enabled(self.encoder_menu, self.encoder_label, video_live)
        set_enabled(self.resolution_menu, self.resolution_label, video_live)
        set_enabled(self.fps_menu, self.fps_label, video_live)
        set_enabled(self.profile_menu, self.profile_label, video_live and bool(profiles))
        set_enabled(self.level_menu, self.level_label, video_live and bool(levels))
        set_enabled(self.speed_menu, self.speed_label, video_live and bool(speeds))
        # BT.2390 via libplacebo is the only tone-mapping this app uses, and
        # only for a source actually detected as HDR. Forced *off* (not just
        # greyed) once unavailable, so nothing silently keeps tone-mapping.
        hdr_source = video_live and info.get("hdr") is True
        hdr_enabled = hdr_source and supports_libplacebo()
        if not hdr_enabled and self.hdr_switch.isChecked():
            self.hdr_switch.setChecked(False)
            self._apply_preview_frames()
        set_enabled(self.hdr_switch, self.hdr_label, hdr_enabled)
        # A greyed switch on an HDR file is exactly when "why" matters: say
        # what's missing (ffmpeg build vs. Vulkan), not just the generic blurb.
        hdr_tip = f"{_HDR_TIP}\n\nUnavailable: {libplacebo_problem_text()}" if hdr_source and not hdr_enabled else _HDR_TIP
        tip(self.hdr_label, hdr_tip)
        tip(self.hdr_switch, hdr_tip)
        # Quality stays live on an unresolved Select; a codec with no rate
        # control at all (ProRes / DNxHR / CineForm / FFV1) disables it.
        quality_live = video_live and (encoder == formats.SELECT or self._quality_spec is not None)
        for widget in (self.crf_slider, self.crf_label, self.crf_low_label, self.crf_high_label):
            widget.setEnabled(quality_live)

        set_enabled(self.audio_track_menu, self.audio_track_label,
                    audio_live and bool(self._audio_included))
        self.choose_streams_btn.setEnabled(audio_live)
        set_enabled(self.passthru_check, self.passthru_label, audio_live and not passthru_only)
        set_enabled(self.audio_codec_menu, self.audio_codec_label, audio_live and not passthru_only)
        set_enabled(self.audio_bitrate_menu, self.audio_bitrate_label,
                    audio_live and not passthru and bool(bitrates))
        set_enabled(self.audio_channels_menu, self.audio_channels_label,
                    audio_live and not passthru and not audio_unresolved)
        set_enabled(self.audio_samplerate_menu, self.audio_samplerate_label,
                    audio_live and not passthru and not audio_unresolved)

        # 6.
        self._refresh_summary()
        self._apply_import_gate(extra=(
            (self.encoder_menu, self.encoder_label), (self.profile_menu, self.profile_label),
            (self.level_menu, self.level_label), (self.speed_menu, self.speed_label),
            (self.resolution_menu, self.resolution_label), (self.fps_menu, self.fps_label),
            (self.audio_track_menu, self.audio_track_label),
            (self.audio_codec_menu, self.audio_codec_label),
            (self.audio_bitrate_menu, self.audio_bitrate_label),
            (self.audio_channels_menu, self.audio_channels_label),
            (self.audio_samplerate_menu, self.audio_samplerate_label),
        ))
        # The non-dropdown controls, same no-file rule. Every one's enabled
        # state was already recomputed fresh above, so — like `extra`'s
        # dropdowns — only the no-file side needs forcing here.
        if not self.app.current_file_path:
            for widget in (self.crf_slider, self.crf_label, self.crf_low_label, self.crf_high_label,
                           self.strip_video_check, self.strip_audio_check,
                           self.choose_streams_btn, self.passthru_check, self.passthru_label):
                widget.setEnabled(False)

    def _retarget(self, menu, values, what=None):
        """Point a derived dropdown at a fresh list, toasting a forced snap —
        silently swapping a codec out from under the user feels haunted."""
        before = menu.value()
        menu.set_values(values or [NO_OPTION])
        after = menu.value()
        if what and self._ready and before != after and before != NO_OPTION:
            self.app.notify(
                f"{what} switched to {after} — {self.format_menu.value()} can't carry {before}.",
                go_to_queue=False,
            )
        return after

    def _retarget_resolution(self, source_height):
        """Caps the Resolution list to the current file's own height —
        separate from `_retarget` since the reason a pick stops fitting is
        the source's height, not the container, so the toast needs its own
        wording."""
        before = self.resolution_menu.value()
        self.resolution_menu.set_values(formats.resolutions_for(source_height))
        after = self.resolution_menu.value()
        # before == NO_OPTION means the dropdown was just showing the
        # no-file-imported placeholder (_apply_import_gate) a moment ago,
        # not a real prior pick — recovering from that isn't a snap worth
        # toasting about, same guard `_retarget` already has.
        if self._ready and before != after and before != NO_OPTION:
            self.app.notify(
                f"Resolution reset to {after} — this file is only {source_height}p tall.",
                go_to_queue=False,
            )

    def _retarget_fps(self, source_fps):
        """Caps the FPS list to the current file's own frame rate — separate
        from `_retarget` since the reason a pick stops fitting is the
        source's rate, not the container, so the toast needs its own
        wording."""
        before = self.fps_menu.value()
        self.fps_menu.set_values(formats.fps_values_for(source_fps))
        after = self.fps_menu.value()
        if self._ready and before != after and before != NO_OPTION:
            rate = f"{source_fps:.2f}" if source_fps else "?"
            self.app.notify(
                f"FPS reset to {after} — this file is only {rate}fps.",
                go_to_queue=False,
            )

    def _speed_values(self, encoder):
        """AV1's preset range comes from the installed ffmpeg."""
        av1_range = av1_preset_range() if encoder == "AV1" else None
        return formats.speed_values_for(encoder, av1_range)

    def _apply_speed(self, encoder):
        """A Speed retarget snaps to the encoder's own recommended default,
        not the list's first (most extreme) entry."""
        values = self._speed_values(encoder) or [NO_OPTION]
        before = self.speed_menu.value()
        self.speed_menu.set_values(values)
        if before not in values:
            default = formats.speed_default_for(encoder)
            if default:
                self.speed_menu.set(default)

    def _apply_quality(self):
        """Re-range the slider for the current encoder, keeping the value
        when it still fits, else the codec's default."""
        spec = self._quality_spec or _FALLBACK_QUALITY
        value = self.crf_slider.value()
        low, high = spec["lo"], spec["hi"]
        self.crf_slider.blockSignals(True)
        if (self.crf_slider.minimum(), self.crf_slider.maximum()) != (low, high):
            self.crf_slider.setRange(low, high)
            if not low <= value <= high:
                value = spec["default"]
        self.crf_slider.setValue(value)
        self.crf_slider.blockSignals(False)
        self.crf_low_label.setText(spec["low"])
        self.crf_high_label.setText(spec["high"])
        tip(self.crf_slider, _CRF_TIP if spec["kind"] == "crf" else _QSCALE_TIP)
        self._update_quality_label()

    def _update_quality_label(self):
        spec = self._quality_spec or _FALLBACK_QUALITY
        self.crf_label.setText(f"{spec['label']}: {self.crf_slider.value()}")

    # ------------------------------------------------------------------ #
    #  Multi-stream audio
    # ------------------------------------------------------------------ #
    def _included_audio(self):
        """The included audio entries, in list (= output) order."""
        return [entry for entry in self._audio_list if entry["id"] in self._audio_included]

    def _audio_track_values(self):
        """The Audio Track dropdown's labels — the included streams, numbered by their place in
        the Choose Stream(s) list — and, as a side effect, the label -> id map behind them."""
        self._audio_track_ids = {}
        labels = []
        for number, entry in enumerate(self._audio_list, start=1):
            if entry["id"] not in self._audio_included:
                continue
            label = f"Track {number}"
            if entry["stream"].get("codec"):
                label += f" ({entry['stream']['codec']})"
            self._audio_track_ids[label] = entry["id"]
            labels.append(label)
        return labels or [NO_OPTION]

    def _save_active_audio_stream(self):
        """Bank what the four shared controls show into the active track."""
        if self._active_audio_id is None:
            return
        self._audio_stream_settings[self._active_audio_id] = {
            "codec": self.audio_codec_menu.value(),
            "bitrate": self._menu_value(self.audio_bitrate_menu),
            "channels": self.audio_channels_menu.value(),
            "sample_rate": self.audio_samplerate_menu.value(),
            "passthru": self.passthru_check.isChecked(),
        }

    def _active_stream_info(self):
        for entry in self._audio_list:
            if entry["id"] == self._active_audio_id:
                return entry["stream"]
        return None

    def _apply_passthru_values(self):
        """Passthru: Bitrate / Channels / Sample Rate mirror the source's own
        real values (rarely one of the offered options — set as overrides). A
        lossless source — FLAC, or a probed TrueHD / DTS-HD MA — says so in Bitrate
        instead of a number (or, for TrueHD, which reports none, a bare `Select`)."""
        stream = self._active_stream_info() or {}
        if stream.get("lossless") or formats.is_lossless_audio(stream.get("codec")):
            self.audio_bitrate_menu.set(formats.LOSSLESS)
        else:
            self.audio_bitrate_menu.set(stream.get("bitrate_display") or formats.SELECT)
        self.audio_channels_menu.set(stream.get("channels_display") or formats.SELECT)
        self.audio_samplerate_menu.set(stream.get("sample_rate_display") or formats.SELECT)

    def _load_active_audio_stream(self):
        """Write the active track's stored settings into the shared controls
        (muted — this is the form being written into, not a user change)."""
        settings = (self._audio_stream_settings.get(self._active_audio_id, {})
                    if self._active_audio_id is not None else {})
        was_ready, self._ready = self._ready, False
        try:
            codec = settings.get("codec", formats.SELECT)
            if formats.is_passthru_only(codec):
                self.audio_codec_menu.set(codec)
            else:
                self.audio_codec_menu.set(codec if codec in self.audio_codec_menu.values() else formats.SELECT)
            self.passthru_check.setChecked(bool(settings.get("passthru", False)))
            self._sync_controls()
            if not settings.get("passthru"):
                for menu, key in ((self.audio_bitrate_menu, "bitrate"),
                                  (self.audio_channels_menu, "channels"),
                                  (self.audio_samplerate_menu, "sample_rate")):
                    value = settings.get(key, formats.SELECT)
                    if value in menu.values():
                        menu.set(value)
        finally:
            self._ready = was_ready

    def _on_audio_track_change(self, _value=None):
        self._save_active_audio_stream()
        self._active_audio_id = self._audio_track_ids.get(self.audio_track_menu.value())
        self._load_active_audio_stream()
        self._sync_controls()

    def _open_stream_picker(self):
        """Choose Stream(s): the popup edits a copy of the list (ticks, order, tracks added
        from other files or removed); OK swaps the result in, Cancel changes nothing."""
        result = choose_audio_streams(self.app, self._audio_list, self._audio_included,
                                     self._output_directory())
        if result is None:
            return
        entries, chosen = result
        self._save_active_audio_stream()
        present = {entry["id"] for entry in entries}
        for entry in entries:
            self._audio_stream_settings.setdefault(entry["id"], self._default_audio_settings(entry["stream"]))
        self._audio_stream_settings = {i: v for i, v in self._audio_stream_settings.items() if i in present}
        self._audio_list = entries
        self._audio_included = chosen & present
        self._reactivate_audio_stream()
        self._load_active_audio_stream()
        self._sync_controls()

    def _reactivate_audio_stream(self):
        """Keeps the active track one that is still included (else the first included)."""
        if self._active_audio_id not in self._audio_included:
            included = self._included_audio()
            self._active_audio_id = included[0]["id"] if included else None

    def _default_audio_settings(self, stream):
        """A stream's starting settings: its own probed codec/params where this app offers
        them (DTS / TrueHD are named and forced to Passthru), as a plain copy."""
        codec = stream.get("codec")
        legal_codecs = formats.audio_codecs_for(self.format_menu.value())
        return {
            "codec": codec if (formats.is_passthru_only(codec) or codec in legal_codecs) else formats.SELECT,
            "bitrate": stream.get("bitrate_display") or formats.SELECT,
            "channels": stream.get("channels_display") or formats.SELECT,
            "sample_rate": stream.get("sample_rate_display") or formats.SELECT,
            "passthru": True,
        }

    def _auto_select_audio_streams(self, info):
        """(Re)initialise the source's own audio once per file: every stream
        defaults to its own probed codec/params where this app offers them,
        DTS / TrueHD are named and forced to Passthru, and — Passthru
        defaulting on — every stream starts as a plain copy until the user
        picks a re-encode. Every stream is included. Streams added
        from other files stay (with their settings and whether they were
        included), as Muxing's do. Guarded per path so a re-delivery of the
        same probe never discards the user's edits."""
        if self.app.current_file_path == self._audio_streams_source:
            return
        self._audio_streams_source = self.app.current_file_path
        primary = [{"id": f"src:{stream['index']}", "source": "primary", "file": None,
                    "index": stream["index"], "stream": stream, "name": None}
                   for stream in info.get("audio_streams") or []]
        external = [entry for entry in self._audio_list if entry["source"] == "external"]
        external_ids = {entry["id"] for entry in external}
        kept_settings = {i: v for i, v in self._audio_stream_settings.items() if i in external_ids}
        kept_included = self._audio_included & external_ids
        self._audio_list = primary + external
        self._audio_stream_settings = {entry["id"]: self._default_audio_settings(entry["stream"])
                                       for entry in primary}
        self._audio_stream_settings.update(kept_settings)
        self._audio_included = {entry["id"] for entry in primary} | kept_included
        self._active_audio_id = None
        self._reactivate_audio_stream()
        self._load_active_audio_stream()

    # ------------------------------------------------------------------ #
    #  Rundown
    # ------------------------------------------------------------------ #
    def _refresh_summary(self):
        info = self.app.media_info
        no_file = not self.app.current_file_path

        if no_file:
            video = ("— no streams selected —", "stop")
        elif self.strip_video_check.isChecked():
            video = ("— removed —", "stop")
        elif info.get("has_video") is False:
            video = ("— no video stream —", "stop")
        elif self.encoder_menu.value() == formats.SELECT:
            video = ("— pick an encoder —", "stop")
        else:
            encoder = self.encoder_menu.value()
            bits = [formats.short_name(encoder)]
            if formats.profiles_for(encoder):
                bits.append(self.profile_menu.value())
            if formats.levels_for(encoder):
                bits.append("L" + self.level_menu.value())
            if self._quality_spec:
                kind = "CRF" if self._quality_spec["kind"] == "crf" else "Q"
                bits.append(f"{kind}{self.crf_slider.value()}")
            if self.resolution_menu.value() != formats.SOURCE_RESOLUTION:
                bits.append(self.resolution_menu.value())
            if self.fps_menu.value() != formats.SOURCE_FPS:
                bits.append(f"{self.fps_menu.value()}fps")
            if self.hdr_switch.isChecked():
                bits.append("SDR")
            video = (" · ".join(bits), None)

        if self.strip_audio_check.isChecked():
            audio = ("— removed —", "stop")
        elif info.get("has_audio") is False:
            audio = ("— no audio stream —", "stop")
        elif not self._audio_included:
            audio = ("— no streams selected —", "stop")
        else:
            self._save_active_audio_stream()
            first = self._included_audio()[0]
            primary = self._audio_stream_settings.get(first["id"], {})
            if primary.get("codec", formats.SELECT) == formats.SELECT:
                audio = ("— pick a codec —", "stop")
            else:
                bits = [primary["codec"]]
                if primary.get("passthru"):
                    bits.append("copy")
                stream = first["stream"]
                lossless = formats.is_lossless_audio(primary["codec"]) or (
                    bool(primary.get("passthru")) and bool(stream.get("lossless")))
                for key in ("bitrate", "channels", "sample_rate"):
                    if key == "bitrate" and lossless:
                        continue      # the codec already says lossless; a number would only mislead
                    value = primary.get(key, formats.SELECT)
                    if value not in (formats.SELECT, NO_OPTION, ""):
                        bits.append(value)
                extra = len(self._audio_included) - 1
                if extra:
                    bits.append(f"+ {extra} more")
                audio = (" · ".join(bits), None)

        start = self.start_time_spinner.seconds()
        duration = self.duration_time_spinner.seconds()
        if no_file:
            length = ("— no file imported —", "stop")
        elif not start and not duration:
            length = ("Whole File", None)
        elif not duration:
            length = (f"{hms(start)} → end", None)
        else:
            length = (f"{hms(start)} → {hms(start + duration)}", None)
        self.summary.set_values([video, audio, length])

    # ------------------------------------------------------------------ #
    #  Media info
    # ------------------------------------------------------------------ #
    def on_media_info(self, info):
        """Adopt the source's container (while unpicked), then auto-resolve
        Encoder and the per-stream audio from the same probe."""
        container = info.get("container")
        if container and self._auto_format is not None and container in formats.containers():
            self.format_menu.set(container)
            self._auto_format = container
            self._autofill_output_path()
        self._sync_controls()
        self._auto_select_codecs(info)
        self._auto_select_audio_streams(info)
        self._sync_controls()

    def _auto_select_codecs(self, info):
        """Encoder (+ best-effort Profile / Level) from the probe, only while
        the user hasn't picked one; anything unidentified stays on Select."""
        if self._auto_encoder is None:
            return
        video = info.get("video")
        if video and video in self.encoder_menu.values():
            self.encoder_menu.set(video)
            self._auto_encoder = video
            self._sync_controls()
            profile = info.get("video_profile")
            if profile and profile in formats.profiles_for(video):
                self.profile_menu.set(profile)
            level = info.get("video_level")
            if level and level in formats.levels_for(video):
                self.level_menu.set(level)

    # ------------------------------------------------------------------ #
    #  Settings in / out
    # ------------------------------------------------------------------ #
    def _gather_settings(self):
        self._save_active_audio_stream()
        settings = self._gather_common()
        settings.update({
            "encoder": self.encoder_menu.value(),
            "profile": self._menu_value(self.profile_menu),
            "level": self._menu_value(self.level_menu),
            "speed": self._menu_value(self.speed_menu),
            "quality": self.crf_slider.value(),
            "resolution": self.resolution_menu.value(),
            "fps": self.fps_menu.value(),
            # A fact about the input at queue time, not a user choice — same
            # convention as mastering_max_nits/max_cll below — so a job
            # queued now still scales/retimes against the source it was
            # actually queued against even if the user swaps files before
            # it runs.
            "source_height": self.app.media_info.get("height"),
            "source_fps": self.app.media_info.get("fps"),
            "gpu_enabled": bool(self.app.gpu_enabled),
            "hdr_to_sdr": self.hdr_switch.isChecked(),
            # Facts about the input at queue time — together they decide the
            # tonemap's peak_detect (see core.utilities.libplacebo_tonemap_vf).
            "mastering_max_nits": self.app.media_info.get("mastering_max_nits"),
            "max_cll": self.app.media_info.get("max_cll"),
            "strip_video": self.strip_video_check.isChecked(),
            "strip_audio": self.strip_audio_check.isChecked(),
            # In list order — the output's stream order. `source` / `file` say which
            # input a track is read from (a stream added from another file has its own).
            "audio_streams": [
                dict(self._audio_stream_settings.get(entry["id"], {}), id=entry["id"],
                     index=entry["index"], source=entry["source"], file=entry["file"],
                     language=entry["stream"].get("language"))
                for entry in self._included_audio()
            ],
        })
        return settings

    def _apply_settings(self, settings):
        """Write a settings dict in dependency order — container, codecs,
        then the leaves — syncing between tiers so every list is legal before
        the next tier's value lands in it. Snap toasts muted throughout."""
        if not settings:
            return
        was_ready, self._ready = self._ready, False
        try:
            self._apply_common(settings)
            if "output_format" in settings:
                self.format_menu.set(settings["output_format"])
                self._auto_format = None
            self._sync_controls()

            encoder = settings.get("encoder")
            if encoder is not None and encoder in self.encoder_menu.values():
                self.encoder_menu.set(encoder)
                self._auto_encoder = None
            self._sync_controls()

            for menu, key in ((self.profile_menu, "profile"), (self.level_menu, "level"),
                              (self.speed_menu, "speed")):
                if settings.get(key) is not None and settings[key] in menu.values():
                    menu.set(settings[key])
            if settings.get("resolution") and settings["resolution"] in self.resolution_menu.values():
                self.resolution_menu.set(settings["resolution"])
            if settings.get("fps") and settings["fps"] in self.fps_menu.values():
                self.fps_menu.set(settings["fps"])
            if "audio_streams" in settings:
                known = {entry["id"] for entry in self._audio_list}
                included, stream_settings = set(), {}
                for entry in settings["audio_streams"] or []:
                    row_id = entry.get("id") or (f"src:{entry['index']}" if entry.get("index") is not None else None)
                    if row_id not in known:
                        continue
                    included.add(row_id)
                    stream_settings[row_id] = {
                        "codec": entry.get("codec", formats.SELECT),
                        "bitrate": entry.get("bitrate", formats.SELECT),
                        "channels": entry.get("channels", formats.SELECT),
                        "sample_rate": entry.get("sample_rate", formats.SELECT),
                        "passthru": bool(entry.get("passthru")),
                    }
                self._audio_stream_settings.update(stream_settings)
                self._audio_included = included
                self._active_audio_id = None
                self._reactivate_audio_stream()
                self._load_active_audio_stream()
            if "hdr_to_sdr" in settings:
                self.hdr_switch.setChecked(bool(settings["hdr_to_sdr"]))
            if settings.get("quality") is not None:
                self.crf_slider.setValue(int(settings["quality"]))
        finally:
            self._ready = was_ready
        self._sync_controls()
        self._apply_preview_frames()
        if self.hdr_switch.isChecked() and self.app.hdr_frames_path != self._preview_path:
            self.app.start_hdr_render(self._preview_path)

    def _validate_specific(self, settings):
        info = self.app.media_info
        if (not settings["strip_video"] and info.get("has_video") is not False
                and settings["encoder"] == formats.SELECT):
            show_message(
                self.app, "Pick a Video Encoder",
                "This file's video codec couldn't be auto-detected. Choose an "
                "Encoder on the Video sub-tab before queueing or encoding.",
            )
            return False
        if not settings["strip_audio"] and info.get("has_audio") is not False:
            streams = settings["audio_streams"]
            unresolved = any(e.get("codec", formats.SELECT) == formats.SELECT for e in streams)
            if not streams or unresolved:
                show_message(
                    self.app, "Pick an Audio Codec",
                    "Every included audio stream needs a codec before queueing or "
                    "encoding — choose one on the Audio sub-tab (or use Choose "
                    "Stream(s) to include at least one), or turn on Strip Audio.",
                )
                return False
        if settings["hdr_to_sdr"] and not settings["strip_video"] and not supports_libplacebo():
            show_message(
                self.app, "HDR to SDR Unavailable",
                f"{libplacebo_problem_text()} Or turn HDR to SDR off before continuing.",
            )
            return False
        return True
