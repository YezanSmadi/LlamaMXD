import os
import customtkinter as ctk
from tkinter import filedialog

from components.animated_switch import AnimatedSwitch
from components.audio_stream_dialog import choose_audio_streams
from components.dialogs import ask_text, ask_yes_no, confirm_output_path, show_message
from components.drop_box import DropBox
from components.dropdown import ThemedDropdown
from components.marquee_label import MarqueeLabel
from components.sub_tab_bar import SubTabBar
from components.summary_panel import SummaryPanel
from components.thumbnail_carousel import ThumbnailCarousel
from components.time_spinner import TimeSpinner
from core import formats, presets
from core.theme import get_active_theme, readable_text_on, STOP_RED, STOP_RED_HOVER
from core.utilities import av1_preset_range, supports_libplacebo

# One consistent "disabled" label colour, so a control that's dimmed by two
# different rules never compounds into a darker grey than one dimmed by one.
_DISABLED_LABEL = "gray50"
# The quality slider's knob + fill when it's disabled — a bare
# state="disabled" leaves a CTk slider looking active, so the colours are
# swapped explicitly too.
_DISABLED_SLIDER = "gray40"
# Strip Video/Strip Audio's own fill/border/checkmark when the OTHER strip
# (or an absent stream) disables them — same reasoning as _DISABLED_SLIDER:
# state="disabled" alone doesn't touch a CTkCheckBox's own colours (only its
# text label dims), so the destructive STOP_RED would otherwise stay fully
# bright regardless of state.
_DISABLED_CHECK = "gray40"
# The HDR->SDR switch's own knob + track when it's disabled — same gotcha
# again: CTkSwitch only dims its own text label (here empty) on disabled,
# leaving the knob and track at their normal theme colours otherwise.
_DISABLED_SWITCH = "gray40"

# Range/labels for the quality slider when the encoder has no spec of its own
# (i.e. `Select`, nothing chosen yet) — the slider stays usable rather than
# freezing on a stale range from whatever codec was picked before.
_FALLBACK_QUALITY = {
    "kind": "crf", "label": "Quality (CRF)", "lo": 0, "hi": 51,
    "default": 22, "low": "Low", "high": "Placebo",
}

# What a derived dropdown shows when the current codec has no such option at
# all (VP8 profiles, VP9 levels). Paired with state="disabled".
_NO_OPTION = "—"

_TAB = "Encoding"


def _hms(total_seconds):
    """Seconds as HH:MM:SS, for the Overview rundown's trim line."""
    total_seconds = int(total_seconds or 0)
    hours, rest = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class EncodingTab(ctk.CTkFrame):
    """Re-encoding: the superset tab. Three sub-tabs — Overview (container,
    global trim, presets, and the export rundown), Video, and Audio.

    Every derived control state in here is computed by one function,
    `_sync_controls`; see its docstring for why there are no pairwise
    handlers."""

    def __init__(self, master, app):
        super().__init__(master=master)
        self.app = app
        theme = get_active_theme()
        self._label_color = ctk.ThemeManager.theme["CTkLabel"]["text_color"]
        # Suppresses the "codec switched" toasts while a settings dict is
        # being written into the form (theme rebuild, preset load) — those
        # snaps aren't the user changing anything.
        self._ready = False
        self._quality_spec = None
        # Mirrors _auto_output: holds the container we defaulted for the
        # user, and goes None the moment they pick one themselves, so a new
        # file drop never overrides a deliberate choice.
        self._auto_format = formats.containers()[0]
        # Same pattern for the auto-picked Encoder (see on_media_info/
        # _auto_select_codecs): holds the value we picked from the probe,
        # goes None the instant the user picks one themselves via
        # _on_encoder_change. (Profile/Level have no flag of their own --
        # they ride along with Encoder's, since they're meaningless without
        # it.)
        self._auto_encoder = formats.SELECT

        # --- Multi-stream audio (Audio sub-tab's Track dropdown + "Choose
        # Stream(s)" picker) ---
        # `probe_media`'s `audio_streams` list for the current file, verbatim
        # (see core.utilities.probe_media / _describe_audio_stream).
        self._audio_streams = []
        # Which stream indices are actually included in the output. The four
        # shared Audio Codec/Bitrate/Channels/Sample Rate controls always
        # edit exactly one stream at a time -- whichever `_active_audio_
        # index` names -- not "the" audio settings the way they did before
        # multi-stream support existed.
        self._included_audio_indices = set()
        self._active_audio_index = None
        # index -> {"codec", "bitrate", "channels", "sample_rate"} (display
        # values, same shape the four controls show) for every probed
        # stream, included or not -- so switching the Track dropdown back and
        # forth never loses an edit. Initialized once per file by
        # `_auto_select_audio_streams`; `_audio_streams_source` is what tells
        # that apart from the probe's *second* message for the same file
        # (the frame decode's on_media_info call arrives after the same
        # info again) re-stomping whatever the user has since changed.
        self._audio_stream_settings = {}
        self._audio_streams_source = None

        # --- HDR->SDR preview (Video sub-tab's hdr_switch) ---
        # The tone-mapped frame cache itself lives on self.app, not here —
        # see LlamaGUI's own __init__ comment on hdr_frames/hdr_frames_path
        # for why. This tab only tracks which file it's currently showing
        # and the app's last raw-frame broadcast for it — see
        # _on_thumbnails/_apply_preview_frames/_start_hdr_render below.
        self._preview_path = None
        self._raw_frames = []

        # --- Bottom Section: Fixed Controls ---
        # Packed FIRST with side="bottom" to anchor at the window edge; the
        # top_container (preview / drop box) built afterward absorbs the rest.
        self.controls_frame = ctk.CTkFrame(master=self, fg_color="transparent")
        self.controls_frame.pack(side="bottom", fill="x", padx=10, pady=(0, 4))

        # 1. Options row — one two-column block. Each sub-tab owns *both*
        # columns: a dropdown row on the left, a checkbox/slider stack on the
        # right. Both bottom-align (anchor="s") against the save row beneath,
        # so the block hugs it and leaves the DropBox above as much room as
        # possible.
        self.options_row = ctk.CTkFrame(master=self.controls_frame, fg_color="transparent")
        self.options_row.pack(fill="x", pady=(2, 4))

        self.left_col = ctk.CTkFrame(master=self.options_row, fg_color="transparent")
        self.left_col.pack(side="left", anchor="s", padx=(0, 20))

        self.right_col = ctk.CTkFrame(master=self.options_row, fg_color="transparent")
        self.right_col.pack(side="left", anchor="s", fill="x", expand=True)

        self.overview_left, self.overview_right = self._build_overview_panel(self.left_col, self.right_col)
        self.video_left, self.video_right = self._build_video_panel(self.left_col, self.right_col)
        self.audio_left, self.audio_right = self._build_audio_panel(self.left_col, self.right_col)

        self._pin_options_height()
        self._active_subtab = "Overview"
        self._subtabs_warmed = False
        self._show_subtab("Overview")
        self.bind("<Map>", self._prewarm_subtabs, add="+")

        # 2. Save Location Section
        self.save_frame = ctk.CTkFrame(master=self.controls_frame, fg_color="transparent")
        self.save_frame.pack(fill="x", pady=4)

        self.save_entry = ctk.CTkEntry(master=self.save_frame, placeholder_text="Save file as...")
        self.save_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

        # Pre-fill with the default save folder and keep refining it to
        # "<folder>/<input name>_encoded<format>" as files are picked, until
        # the user overrides it themselves (tracked via self._auto_output).
        self._auto_output = ""
        if self.app.default_save_location:
            self.save_entry.insert(0, self.app.default_save_location)
            self._auto_output = self.app.default_save_location

        self.browse_save_btn = ctk.CTkButton(
            master=self.save_frame, text="Browse", width=80, command=self.select_save_location
        )
        self.browse_save_btn.pack(side="right")

        # 3. Action Buttons Row: Queue Task (secondary) + Encode (primary)
        self.action_frame = ctk.CTkFrame(master=self.controls_frame, fg_color="transparent")
        self.action_frame.pack(fill="x", pady=(5, 0))
        self.action_frame.grid_columnconfigure(0, weight=1, uniform="action")
        self.action_frame.grid_columnconfigure(1, weight=1, uniform="action")

        self.queue_btn = ctk.CTkButton(
            master=self.action_frame,
            text="Queue Task",
            fg_color=theme["secondary"],
            hover_color=theme["secondary_hover"],
            text_color=theme["secondary_text"],
            command=self.add_to_queue,
        )
        self.queue_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.encode_btn = ctk.CTkButton(
            master=self.action_frame,
            text="Encode",
            fg_color=theme["primary"],
            text_color=theme["primary_text"],
            hover_color=theme["primary_hover"],
            command=self.encode_now,
        )
        self.encode_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        # --- Top Flexible Section: sub-tab switch + Selected File header,
        # then the DropBox / preview carousel. ---
        self.top_container = ctk.CTkFrame(master=self, fg_color="transparent")
        self.top_container.pack(side="top", fill="both", expand=True, padx=10, pady=(5, 5))

        self.header_row = ctk.CTkFrame(master=self.top_container, fg_color="transparent")
        self.header_row.pack(fill="x", pady=(0, 4))

        self.sub_tab_bar = SubTabBar(
            master=self.header_row,
            options=["Overview", "Video", "Audio"],
            command=self._show_subtab,
        )
        self.sub_tab_bar.pack(side="left")

        # A marquee: the "Selected File:" line is usually a long path that
        # doesn't fit beside the sub-tab switch, so it scrolls rather than
        # being silently cut off.
        self.label = MarqueeLabel(
            master=self.header_row, text="", font=ctk.CTkFont(size=11), anchor="w"
        )
        self.label.pack(side="left", fill="x", expand=True, padx=(10, 0))
        self.label.bind("<Double-Button-1>", lambda e: self.select_input_file())

        self.carousel = ThumbnailCarousel(
            master=self.top_container,
            on_reselect=self.select_input_file,
            on_populated=self._reveal_preview,
            on_index=self.app.sync_preview_index,   # keep both tabs on the same frame
            on_file_selected=self.app.update_global_file,
        )

        self.drop_box = DropBox(
            master=self.top_container, on_file_selected=self.app.update_global_file, height=380
        )
        self.drop_box.pack(fill="both", expand=True)

        self.app.register_tab_ui(self.label, self.carousel, on_thumbnail=self._on_thumbnails)

        self._sync_controls()
        self._ready = True

    # ------------------------------------------------------------------ #
    #  Sub-tab panels
    # ------------------------------------------------------------------ #
    def _build_overview_panel(self, left_parent, right_parent):
        """Overview: the globals (output container + the one global trim) and
        preset management on the left, the export rundown on the right.

        Output Format lives here rather than on the Video panel because it's
        the root of the whole option tree — it filters *both* codec lists, so
        the panel that owns it has to be reachable from either side."""
        left = ctk.CTkFrame(master=left_parent, fg_color="transparent")
        right = ctk.CTkFrame(master=right_parent, fg_color="transparent")

        # -- Row 1: container + preset recipes. Format and Preset share this
        # row (rather than Format sitting beside the trim spinners) purely to
        # keep `left` narrow: the rundown on the right needs real width, and
        # the spinners are the widest things here. --
        theme = get_active_theme()
        self.globals_row = ctk.CTkFrame(master=left, fg_color="transparent")
        self.globals_row.pack(anchor="w")

        self.format_label, self.format_menu = self._panel_dropdown(
            self.globals_row, "Output Format:", formats.containers(), 92,
            default=formats.containers()[0], command=self._on_format_change,
        )

        self.preset_label, self.preset_menu = self._panel_dropdown(
            self.globals_row, "Preset:", presets.menu_values(_TAB), 132,
            default=presets.NONE_LABEL, padx=(14, 0), command=self._on_preset_selected,
        )

        self.preset_save_btn = ctk.CTkButton(
            master=self.globals_row, text="Save", width=54, height=28,
            fg_color=theme["secondary"], hover_color=theme["secondary_hover"],
            text_color=theme["secondary_text"], command=self._on_preset_save,
        )
        self.preset_save_btn.pack(side="left", anchor="s", padx=(8, 0))

        self.preset_delete_btn = ctk.CTkButton(
            master=self.globals_row, text="Delete", width=54, height=28,
            fg_color=theme["secondary"], hover_color=theme["secondary_hover"],
            text_color=theme["secondary_text"], command=self._on_preset_delete,
        )
        self.preset_delete_btn.pack(side="left", anchor="s", padx=(6, 0))

        # -- Row 2: the one global trim --
        # There is no "Retain Video Length" checkbox any more: a duration of
        # 00:00:00 already means "to the end of the file", so the checkbox was
        # a second way to say the same thing — and an ambiguous one whenever
        # it disagreed with the spinner values.
        self.trim_row = ctk.CTkFrame(master=left, fg_color="transparent")
        self.trim_row.pack(anchor="w", pady=(6, 0))

        self.start_frame = ctk.CTkFrame(master=self.trim_row, fg_color="transparent")
        self.start_frame.pack(side="left", anchor="s")
        self.start_label = ctk.CTkLabel(master=self.start_frame, text="Start Time:", font=("Arial", 12, "bold"))
        self.start_label.pack(anchor="w", pady=(0, 1))
        self.start_time_spinner = TimeSpinner(
            master=self.start_frame, initial_seconds=0, command=self._on_trim_change
        )
        self.start_time_spinner.pack(anchor="w")

        self.duration_frame = ctk.CTkFrame(master=self.trim_row, fg_color="transparent")
        self.duration_frame.pack(side="left", anchor="s", padx=(14, 0))
        self.duration_label = ctk.CTkLabel(master=self.duration_frame, text="Clip Duration:", font=("Arial", 12, "bold"))
        self.duration_label.pack(anchor="w", pady=(0, 1))
        self.duration_time_spinner = TimeSpinner(
            master=self.duration_frame, initial_seconds=0, command=self._on_trim_change
        )
        self.duration_time_spinner.pack(anchor="w")

        # A/V Sync — align the audio and video start and pass through the
        # streams' common metadata. Sits to the right of the trim spinners.
        self.av_sync_check = ctk.CTkCheckBox(
            master=self.trim_row, text="A/V Sync", font=("Arial", 12, "bold"),
            command=self._on_control_change,
        )
        self.av_sync_check.select()   # on by default (-fps_mode cfr; see ffmpeg_build)
        self.av_sync_check.pack(side="left", anchor="s", padx=(16, 0), pady=(0, 4))

        # -- Right: the rundown --
        self.summary = SummaryPanel(master=right, labels=["Video", "Audio", "Length"])
        self.summary.pack(fill="x", anchor="s")

        return left, right

    def _build_video_panel(self, left_parent, right_parent):
        """Video: on the left, the Encoder / Profile / Level / Encoder Preset
        codec row with the quality slider directly underneath it; on the
        right, the HDR switch on top and Strip Video below it (the sole,
        bottom-most item in the right column — matching where Strip Audio
        sits alone in the Audio panel).

        Profile, Level and Encoder Preset are *derived* from Encoder — '4.0'
        means different things to H.264 and H.265, and VP8 has no profiles
        at all — so their option lists are filled by `_sync_controls`, not
        hardcoded here."""
        left = ctk.CTkFrame(master=left_parent, fg_color="transparent")
        right = ctk.CTkFrame(master=right_parent, fg_color="transparent")

        self.codec_options_frame = ctk.CTkFrame(master=left, fg_color="transparent")
        self.codec_options_frame.pack(anchor="w")

        # Widths are tight on purpose — this row has four dropdowns to fit in
        # one fixed-width window, which is also why display names dropped
        # their library suffix ("H.264 (x264)" -> "H.264": see formats.py).
        self.encoder_label, self.encoder_menu = self._panel_dropdown(
            self.codec_options_frame, "Encoder:", [formats.SELECT], 80,
            command=self._on_encoder_change,
        )
        self.profile_label, self.profile_menu = self._panel_dropdown(
            self.codec_options_frame, "Profile:", [_NO_OPTION], 96, padx=(8, 0),
            command=self._on_control_change,
        )
        self.level_label, self.level_menu = self._panel_dropdown(
            self.codec_options_frame, "Level:", [_NO_OPTION], 80, padx=(8, 0),
            command=self._on_control_change,
        )
        # Internally still "speed" (settings key `speed`, ffmpeg_vars.SPEED,
        # formats.speed_values_for/etc.) -- only the on-screen label changed,
        # same as "Quality (CRF)" not matching its own `crf_slider`/`quality`
        # internals. Shows the encoder's own native speed vocabulary (x264/
        # x265's named preset ladder, libvpx's numeric cpu-used, SVT-AV1's
        # numeric preset scale) rather than an abstracted slider, same
        # reasoning as Profile/Level not sharing values between codecs.
        self.speed_label, self.speed_menu = self._panel_dropdown(
            self.codec_options_frame, "Encoder Preset:", [_NO_OPTION], 90, padx=(8, 0),
            command=self._on_control_change,
        )

        # HDR to SDR — an AnimatedSwitch (slides instead of snapping), pinned
        # to the TOP of the right column (aligned with the Encoder/Profile/
        # Level/Encoder Preset row — see _pin_options_height's "Video"
        # special case). Built with text="" and width=42 so a separate label
        # sits to its LEFT: CTkSwitch's internal grid always reserves its
        # (here-empty) text column, so without the narrow width anchor="e"
        # would leave phantom label space instead of landing the toggle
        # flush right.
        self.hdr_row = ctk.CTkFrame(master=right, fg_color="transparent")
        self.hdr_row.pack(anchor="e", pady=(0, 4))

        self.hdr_label = ctk.CTkLabel(master=self.hdr_row, text="HDRtoSDR")
        self.hdr_label.pack(side="left", padx=(0, 8))
        self.hdr_label.bind("<Button-1>", lambda e: self._toggle_hdr())

        self.hdr_switch = AnimatedSwitch(
            master=self.hdr_row, text="", width=42, command=self._on_hdr_toggle
        )
        self.hdr_switch.pack(side="left")

        # A flexible spacer separates HDR->SDR (pinned to the top) from
        # Strip Video (pinned to the bottom) -- by request, so the two read
        # as genuinely distinct controls rather than stacked together near
        # the top. This mirrors where Strip Audio sits alone, flush at the
        # bottom of its own right column, in the Audio panel.
        ctk.CTkFrame(master=right, fg_color="transparent", height=0).pack(
            fill="both", expand=True
        )

        # Strip Video — the destructive red (STOP_RED, the Stop Queue button's
        # colour; a permanent theme-independent exception). Removing a stream
        # is the one rule that spans sub-tabs, so _sync_controls also marks
        # the tab button (see SubTabBar.set_marked) and locks Strip Audio.
        self.strip_video_check = ctk.CTkCheckBox(
            master=right,
            text="Strip Video",
            fg_color=STOP_RED,
            hover_color=STOP_RED_HOVER,
            checkmark_color=readable_text_on(STOP_RED),
            command=self._on_control_change,
        )
        self.strip_video_check.pack(anchor="e", pady=(0, 4))

        # Quality slider — now directly underneath the Encoder/Profile/Level/
        # Encoder Preset row, in the LEFT column (it used to sit in the right
        # column instead). Its range, default, end labels and even its
        # *kind* (CRF vs qscale) come from the encoder — see
        # formats.quality_for and _apply_quality. Always built reversed
        # (from_=worst, to=best) so the slider reads low-quality-left /
        # high-quality-right whichever scale is in play.
        #
        # The row spans the full width of `left` (`fill="x"`, no anchor)
        # rather than being centered as a fixed-width unit, so "Low"'s own
        # left edge lands flush with the Encoder dropdown's left edge and
        # "Placebo"'s own right edge flush with Encoder Preset's right edge
        # (`codec_options_frame`, directly above, is `left`'s widest child
        # and so sets its width) -- the slider itself, packed between the two
        # labels with `fill="x", expand=True`, is simply whatever's left of
        # that span, which is why it reads longer than before.
        self.crf_frame = ctk.CTkFrame(master=left, fg_color="transparent")
        self.crf_frame.pack(fill="x", pady=(10, 0))

        self.crf_label = ctk.CTkLabel(master=self.crf_frame, text="Quality", font=("Arial", 12, "bold"))
        self.crf_label.pack(anchor="center", pady=(0, 1))

        self.crf_slider_row = ctk.CTkFrame(master=self.crf_frame, fg_color="transparent")
        self.crf_slider_row.pack(fill="x")

        self.crf_low_label = ctk.CTkLabel(
            master=self.crf_slider_row, text="Low", text_color="gray60", font=("Arial", 11)
        )
        self.crf_low_label.pack(side="left", padx=(0, 4))

        self.crf_high_label = ctk.CTkLabel(
            master=self.crf_slider_row, text="Placebo", text_color="gray60", font=("Arial", 12)
        )
        self.crf_high_label.pack(side="right", padx=(4, 0))

        self.crf_slider = ctk.CTkSlider(
            master=self.crf_slider_row, from_=51, to=0, number_of_steps=51,
            command=self._on_quality_change,
        )
        # A CTkSlider with no explicit initial value defaults to its own
        # (from_+to)/2 midpoint (here 25.5, rounding to 26) -- not any
        # encoder's real default. Confirmed this was never actually
        # overridden in practice: `_apply_quality`'s "keep the current value
        # if it still fits the new range" rule (deliberate, so a manual pick
        # survives a compatible codec switch) means the very first call ever
        # sees 26 already sitting inside every codec's range this app has,
        # so it never resets it. Seeding a real default here fixes the
        # symptom at its source rather than leaving _apply_quality to paper
        # over an uninitialized widget value that happens to look plausible.
        self.crf_slider.set(_FALLBACK_QUALITY["default"])
        self.crf_slider.pack(side="left", fill="x", expand=True)

        return left, right

    def _build_audio_panel(self, left_parent, right_parent):
        """Audio: Audio Track + Choose Stream(s) on one row, then Audio
        Codec / Passthru / Bitrate / Channels / Sample Rate together on the
        next — Strip Audio alone on the right, same as every other panel's
        one destructive checkbox.

        Every dropdown here is sized by `_measure_dropdown_width` to the
        exact pixel width its own longest *possible* entry needs — not just
        what happens to be showing — so nothing is wider than it has to be
        and nothing (dynamic_resizing is already off; see ThemedDropdown)
        can resize later when a codec/track swap lengthens the shown text.
        That precision is what keeps this layout affordable: an eyeballed
        Audio Codec width (150px, guessed for "Dolby TrueHD") pushed this
        same six-control arrangement to 566px in an earlier version, which is
        why it used to be split across three rows instead. Measuring
        precisely instead shows Audio Codec only needs 118px and Bitrate/
        Channels/Sample Rate 75/76/92px, fitting it all on one row. (Sub-tab
        panels no longer share one footprint — see `_pin_options_height` —
        so Audio's own width today only affects Audio's own right column
        when Audio is the active sub-tab; it no longer costs the Overview
        rundown anything, but the one-row layout is still worth keeping for
        its own sake.)"""
        left = ctk.CTkFrame(master=left_parent, fg_color="transparent")
        right = ctk.CTkFrame(master=right_parent, fg_color="transparent")

        # Row 1: which stream, and which of the source's streams are
        # actually included.
        self.audio_row1 = ctk.CTkFrame(master=left, fg_color="transparent")
        self.audio_row1.pack(anchor="w", pady=(0, 6))

        self.audio_track_label, self.audio_track_menu = self._panel_dropdown(
            self.audio_row1, "Audio Track:", [_NO_OPTION],
            self._measure_dropdown_width(self._audio_track_universe()),
            command=self._on_audio_track_change,
        )
        self.choose_streams_btn = ctk.CTkButton(
            master=self.audio_row1, text="Choose Stream(s)", width=130, height=28,
            command=self._open_stream_picker,
        )
        self.choose_streams_btn.pack(side="left", anchor="s", padx=(8, 0))

        # Row 2: the active track's codec and its own encode parameters.
        self.audio_row2 = ctk.CTkFrame(master=left, fg_color="transparent")
        self.audio_row2.pack(anchor="w")

        codec_universe = list(formats.AUDIO_ENCODERS) + list(formats.PASSTHRU_ONLY_CODECS) + [formats.SELECT]
        self.audio_codec_label, self.audio_codec_menu = self._panel_dropdown(
            self.audio_row2, "Audio Codec:", [formats.SELECT],
            self._measure_dropdown_width(codec_universe),
            command=self._on_control_change,
        )
        # Passthru — bitstream passthrough: the stream is copied verbatim
        # (-c:a copy), so Bitrate/Channels/Sample Rate stop being ours to
        # set and instead mirror the source's own real values (see
        # _apply_passthru_values). Forced on and disabled for a probe-
        # detected DTS/Dolby TrueHD track (formats.is_passthru_only) —
        # this app has no re-encode path for either — but togglable for
        # any other codec.
        #
        # Its own bold label sits above the checkbox, in its own frame —
        # matching every dropdown on this row (_panel_dropdown's label-
        # above-control pattern) instead of CTkCheckBox's own inline text to
        # the checkbox's right, which used to read inconsistently next to
        # them. Still needs an explicit narrow `width` even with `text=""`:
        # confirmed CTkCheckBox's own default `width=100` doesn't shrink to
        # fit an empty label the way a smaller widget would — the checkbox
        # mark itself only needs ~24px (its own `_checkbox_width`), so
        # without this the same ~76px of dead trailing space the old inline-
        # text version had would just reappear under a different cause.
        self.passthru_frame = ctk.CTkFrame(master=self.audio_row2, fg_color="transparent")
        self.passthru_frame.pack(side="left", anchor="s", padx=(10, 0))

        # No colon (unlike the dropdown labels beside it) and centered,
        # along with the checkbox below it, rather than both left-anchored —
        # the checkbox mark (~24px) is much narrower than the label text, so
        # left-anchoring both left it sitting under the label's leading edge
        # rather than under the word itself.
        self.passthru_label = ctk.CTkLabel(
            master=self.passthru_frame, text="Passthru", font=("Arial", 12, "bold")
        )
        self.passthru_label.pack(anchor="center", pady=(0, 1))

        self.passthru_check = ctk.CTkCheckBox(
            master=self.passthru_frame, text="", width=24, command=self._on_control_change,
        )
        self.passthru_check.pack(anchor="center", pady=(0, 4))

        bitrate_universe = [formats.SELECT] + formats.AUDIO_BITRATES
        self.audio_bitrate_label, self.audio_bitrate_menu = self._panel_dropdown(
            self.audio_row2, "Bitrate:", [_NO_OPTION],
            self._measure_dropdown_width(bitrate_universe),
            padx=(10, 0), command=self._on_control_change,
        )
        self.audio_channels_label, self.audio_channels_menu = self._panel_dropdown(
            self.audio_row2, "Channels:", formats.AUDIO_CHANNELS,
            self._measure_dropdown_width(formats.AUDIO_CHANNELS),
            default=formats.SELECT, padx=(10, 0), command=self._on_control_change,
        )
        self.audio_samplerate_label, self.audio_samplerate_menu = self._panel_dropdown(
            self.audio_row2, "Sample Rate:", formats.AUDIO_SAMPLE_RATES,
            self._measure_dropdown_width(formats.AUDIO_SAMPLE_RATES),
            default=formats.SELECT, padx=(10, 0), command=self._on_control_change,
        )

        self.strip_audio_check = ctk.CTkCheckBox(
            master=right,
            text="Strip Audio",
            fg_color=STOP_RED,
            hover_color=STOP_RED_HOVER,
            checkmark_color=readable_text_on(STOP_RED),
            command=self._on_control_change,
        )
        self.strip_audio_check.pack(anchor="e", pady=(0, 4))

        return left, right

    @staticmethod
    def _audio_track_universe():
        """Every label shape the Audio Track dropdown could ever show, for
        sizing it to its true worst case — "Track N (<codec>)" for the
        longest codec name this app recognizes (`formats.AUDIO_ENCODERS`
        plus the probe-only Passthru codecs — see `_audio_track_values`,
        which builds the real label the same way once a codec is known)."""
        codecs = list(formats.AUDIO_ENCODERS) + list(formats.PASSTHRU_ONLY_CODECS)
        return [f"Track 9 ({codec})" for codec in codecs] + [_NO_OPTION]

    def _measure_dropdown_width(self, values, min_width=60):
        """The exact pixel width CTk gives a dynamically-resizing dropdown
        showing the widest of `values` — used to fix a non-resizing
        ThemedDropdown's width to precisely its longest possible entry,
        rather than an eyeballed guess. Built and torn down off-screen
        (never shown), so this only ever costs a moment at panel-build
        time, not per frame."""
        values = list(values) or [formats.SELECT]
        probe = ctk.CTkOptionMenu(master=self, values=values, dynamic_resizing=True, width=1)
        widest = min_width
        for value in values:
            probe.set(value)
            probe.update_idletasks()
            widest = max(widest, probe.winfo_reqwidth())
        probe.destroy()
        return widest

    def _panel_dropdown(self, parent, label_text, values, width,
                        default=None, padx=(0, 0), command=None):
        """Bold label above a ThemedDropdown in its own frame, packed left
        into `parent`. Returns `(label, menu)` — the menu for its value, the
        label so `_sync_controls` can dim it in step with the control."""
        frame = ctk.CTkFrame(master=parent, fg_color="transparent")
        frame.pack(side="left", anchor="s", padx=padx)

        label = ctk.CTkLabel(master=frame, text=label_text, font=("Arial", 12, "bold"))
        label.pack(anchor="w", pady=(0, 1))

        menu = ThemedDropdown(master=frame, values=values, width=width, command=command)
        if default is not None:
            menu.set(default)
        menu.pack(anchor="w")
        return label, menu

    def _subtab_pairs(self):
        """`{name: (left_frame, right_frame)}` for the three sub-tab panels."""
        return {
            "Overview": (self.overview_left, self.overview_right),
            "Video": (self.video_left, self.video_right),
            "Audio": (self.audio_left, self.audio_right),
        }

    def _pin_options_height(self):
        """Measures each sub-tab panel's own natural footprint, floats its
        content to the bottom of that footprint, and pre-places all six with
        `.place()` so a switch is still cheap (no widget rebuild, no
        progressive dropdown redraw).

        **Width stays independent per sub-tab** (an earlier version shared
        one width across all three, which meant Overview's rundown got
        squeezed to whatever room was left over after Video's much wider
        Encoder/Profile/Level/Encoder Preset row or Audio's five-dropdown
        row, even though neither has anything to do with what Overview needs
        to show — confirmed directly: the same file's Trim line rendered in
        full under Muxing, whose own Video/Audio panels are narrower, but was
        cut off under Encoding at the same window width). `_show_subtab`
        resizes `left_col` to the target panel's own measured width before
        lifting it.

        **Height, unlike width, IS shared across all three** — every panel's
        `left`/`right` is built at Overview's own measured height, not its
        own. `controls_frame` sits below the DropBox/preview carousel and is
        packed `side="bottom"` — its actual height is exactly however much
        vertical room the DropBox above does *not* get, since the window
        itself is fixed-size. Letting each sub-tab's controls row size itself
        independently (as an earlier version did, matching width's own
        per-tab treatment) meant the DropBox visibly resized on every sub-tab
        switch: confirmed by measurement, Overview's own footprint (128px) is
        the tallest of the three (Video 124px, Audio 120px), so pinning every
        sub-tab to Overview's height costs nothing in clipping.

        Building the *shorter* panels' own `left`/`right` at their own
        smaller natural height, and only stretching the shared `left_col`/
        `right_col` containers at switch time (an earlier version of this
        method did exactly that), doesn't actually work: `left`/`right` are
        real child windows, and Tk clips a child to its parent's rectangle,
        not the other way around — a still-shorter, merely-lifted sibling
        leaves whatever's directly behind it (a *taller* inactive sibling,
        e.g. Overview's own trim row) visible in the leftover strip below it
        once the now-taller `left_col`/`right_col` stops clipping that far
        down. Confirmed by screenshot: Muxing's Video panel (96px) showed
        Overview's trim spinners peeking through its bottom 32px once
        `left_col` grew to Overview's 128px. Building every panel at the
        shared height from the start avoids the problem entirely — each
        panel's own spacer-before-content simply grows to fill the extra
        room instead of leaving it uncovered."""
        self._subtab_footprints = {}
        natural = {}
        for name, (left, right) in self._subtab_pairs().items():
            left.pack(anchor="w")
            right.pack(fill="x")
            self.options_row.update_idletasks()
            natural[name] = (left.winfo_reqwidth(), left.winfo_reqheight(), right.winfo_reqheight())
            left.pack_forget()
            right.pack_forget()

        _, overview_left_req, overview_right_req = natural["Overview"]
        shared_height = max(overview_left_req, overview_right_req, 96)

        for name, (left, right) in self._subtab_pairs().items():
            left_width, left_req_height, _ = natural[name]
            self._subtab_footprints[name] = (left_width, shared_height)

            left.configure(width=left_width, height=shared_height)
            right.configure(height=shared_height)
            left.pack_propagate(False)
            left_kids = left.pack_slaves()
            if left_kids:   # a spacer at the top floats the content to the bottom
                ctk.CTkFrame(left, fg_color="transparent", height=0).pack(
                    side="top", fill="both", expand=True, before=left_kids[0]
                )

            right.pack_propagate(False)
            right_kids = right.pack_slaves()
            if right_kids:
                if name == "Video":
                    # Align the HDR switch (right column's own top row) with
                    # the Encoder/Profile/Level/Encoder Preset row (left
                    # column's top row) -- both get the SAME gap above their
                    # content (left's own natural gap to the panel's shared
                    # height), rather than each column independently floating
                    # its own, differently-sized content to the bottom.
                    gap = shared_height - left_req_height
                    ctk.CTkFrame(right, fg_color="transparent", height=gap).pack(
                        side="top", before=right_kids[0]
                    )
                else:
                    ctk.CTkFrame(right, fg_color="transparent", height=0).pack(
                        side="top", fill="both", expand=True, before=right_kids[0]
                    )
            left.place(x=0, y=0)
            right.place(x=0, y=0, relwidth=1.0)

        self.options_row.pack_propagate(False)

    def _show_subtab(self, name):
        """Resizes `left_col`/`right_col`/`options_row` to the target
        panel's own measured *width* (`_subtab_footprints`, from
        `_pin_options_height`) and raises it, but always at the **Overview**
        panel's height rather than the target's own — see `_pin_options_
        height`'s docstring on why the controls row's height has to be one
        constant across all three sub-tabs regardless of each one's own
        natural content height. `right_col`'s width isn't set directly — it
        follows `left_col`'s (via its own `fill="x", expand=True` pack)
        automatically, and the placed `right` panel's `relwidth=1.0` tracks
        `right_col`'s width live, so Overview's rundown genuinely widens
        when Video/Audio's wider left column isn't the one occupying
        `left_col` any more."""
        self._active_subtab = name
        left, right = self._subtab_pairs().get(name, self._subtab_pairs()["Overview"])
        left_width, _ = self._subtab_footprints.get(
            name, (self.left_col.winfo_reqwidth(), 96)
        )
        height = self._subtab_footprints["Overview"][1]
        self.options_row.configure(height=height)
        self.left_col.configure(width=left_width, height=height)
        self.right_col.configure(height=height)
        left.lift()
        right.lift()

    def _prewarm_subtabs(self, event=None):
        """Once the tab is first mapped, cycle every panel onto the screen
        briefly (chained through `after` so CTk's deferred `_draw`s land
        between steps) and settle back on the active one. After this every
        real switch is an instant `lift()` — without it, a panel that has only
        ever been stacked behind another is unpainted, so its first reveal
        fills in over several frames (the switch flicker)."""
        if self._subtabs_warmed:
            return
        self._subtabs_warmed = True
        active = self._active_subtab
        names = [n for n in self._subtab_pairs() if n != active]

        def step(i):
            if i < len(names):
                self._show_subtab(names[i])
                self.after(40, lambda: step(i + 1))
            else:
                self._show_subtab(active)

        step(0)

    # ------------------------------------------------------------------ #
    #  The single constraint pass
    # ------------------------------------------------------------------ #
    def _on_control_change(self, *_):
        """Every control's `command` lands here, which just re-runs the one
        constraint pass. No control ever reaches into another directly."""
        self._sync_controls()

    def _on_encoder_change(self, *_):
        """The user picked an Encoder themselves — stop auto-adopting the
        source's (mirrors `_on_format_change`/`_auto_format`), then re-sync."""
        self._auto_encoder = None
        self._sync_controls()

    def _toggle_hdr(self):
        """Clicking the HDRtoSDR label toggles the switch (and re-syncs)."""
        if self.hdr_switch.cget("state") != "disabled":
            self.hdr_switch.toggle()
            self._sync_controls()

    # ------------------------------------------------------------------ #
    #  HDR->SDR preview (tone-mapped thumbnails)
    # ------------------------------------------------------------------ #
    # The actual cache/render/queue machinery lives on `self.app`
    # (LlamaGUI.start_hdr_render/hdr_frames/hdr_frames_path), not here —
    # see that block's own comment. A live theme rebuild destroys and
    # reconstructs this whole tab, and a tab-local cache would be destroyed
    # right along with it, forcing a re-render (and a several-second wait)
    # every time the user so much as changes theme. The app survives that
    # rebuild untouched, so the cache does too; everything below just reads
    # it and repaints.
    def _on_hdr_toggle(self):
        """HDR->SDR flipped (hdr_switch's own command — see also
        _toggle_hdr, which reaches the same command through .toggle()):
        re-runs the usual constraint pass, then swaps the carousel to match
        — the cached tone-mapped set if it's already there, the raw set if
        switching off, or a background render kicked off now if switching on
        for a file that hasn't been rendered yet."""
        self._on_control_change()
        self._apply_preview_frames()
        if self.hdr_switch.get() and self.app.hdr_frames_path != self._preview_path:
            self._start_hdr_render()

    def _on_thumbnails(self, frames):
        """`register_tab_ui`'s `on_thumbnail` target — wraps the app's raw
        preview-frame broadcast instead of handing it straight to the
        carousel, so HDR->SDR can show a tone-mapped set in its place.
        Re-kicks the background render if the switch is already on and
        nothing's cached on the app yet for the current file — covers both
        a fresh HDR file arriving while HDR->SDR was left on from a
        previous one, and a preset/theme-rebuild restore that checks the
        switch without going through `_on_hdr_toggle` (`_set_check` doesn't
        fire `command` — see `_apply_settings`'s own tail call for the
        other half of that case)."""
        self._preview_path = self.app.current_file_path
        self._raw_frames = frames
        self._apply_preview_frames()
        if self.hdr_switch.get() and self.app.hdr_frames_path != self._preview_path:
            self._start_hdr_render()

    def on_hdr_frames_ready(self, path, frames):
        """The app finished (or failed) a background HDR render
        (`LlamaGUI._poll_hdr_queue`'s broadcast) — repaint only if it's for
        the file currently showing here; a result for a file the user has
        since moved on from is simply cached on the app for later, not
        applied now."""
        if path == self._preview_path:
            self._apply_preview_frames()

    def _apply_preview_frames(self):
        """Shows whichever frame set HDR->SDR currently calls for — the
        app's cached tone-mapped set once it's ready and matches the
        current file and the switch is on, the raw set otherwise —
        preserving the current scrub position across the swap
        (`set_frames` always resets to frame 0)."""
        show_hdr = (
            bool(self.hdr_switch.get())
            and self.app.hdr_frames is not None
            and self.app.hdr_frames_path == self._preview_path
        )
        frames = self.app.hdr_frames if show_hdr else self._raw_frames
        index = self.carousel.current_index()
        self.carousel.set_frames(frames)
        self.carousel.sync_index(index)

    def _start_hdr_render(self):
        """Asks the app to render (or re-use its cache of) the current
        file's tone-mapped set — see `LlamaGUI.start_hdr_render`."""
        self.app.start_hdr_render(self._preview_path)

    def _sync_controls(self, *_):
        """**The only place derived UI state is decided.**

        Idempotent: reads the whole form and rewrites every dependent
        widget's option list, selection and enabled-state from scratch. This
        replaced a pile of pairwise handlers (`_on_strip_video_toggle`,
        `_on_format_change`, `toggle_time_spinners`) that could each clobber
        the others' work and needed early-return guards to stop them
        fighting — with one recompute, call order stops mattering and the
        whole ruleset is readable in one place.

        The rules, in dependency order:
          1. stream presence — both streams stripped would write an empty
             file; a stream the source doesn't have at all reads the same as
             stripped (red tab, greyed panel) without touching the checkbox
          2. container -> legal video/audio codec lists
          3. video codec -> profile / level / rate-control kind and range
          4. audio codec -> whether a bitrate is ours to set
          5. everything a removed, absent, or unresolved stream makes
             meaningless
          6. the Overview rundown, which is the only cross-panel view
        """
        container = self.format_menu.get()
        stripping_video = bool(self.strip_video_check.get())
        stripping_audio = bool(self.strip_audio_check.get())
        info = self.app.media_info
        # has_video/has_audio is False only once a probe has genuinely run
        # and found no such stream — None ("unknown", no probe yet/failed)
        # must never read as absent.
        video_absent = info.get("has_video") is False
        audio_absent = info.get("has_audio") is False

        # 1. Stream presence. Ticking one Strip locks the other, so the
        # empty-output combination simply can't be reached; the tab-button
        # marker is what makes that visible from the panel you're not on. A
        # stream the source simply doesn't have gets the same red mark, and
        # its Strip checkbox is disabled (nothing to strip) but never forced
        # checked or unchecked.
        self._set_strip_enabled(self.strip_video_check, not (stripping_audio or video_absent))
        self._set_strip_enabled(self.strip_audio_check, not (stripping_video or audio_absent))
        self.sub_tab_bar.set_marked("Video", stripping_video or video_absent)
        self.sub_tab_bar.set_marked("Audio", stripping_audio or audio_absent)
        # The preview reflects it too: waveform for a stripped video, mute
        # badge for stripped audio. A source that never had an audio stream
        # gets the same mute badge as a deliberate strip — there's nothing to
        # hear either way, and the checkbox above is already disabled for it.
        self.carousel.set_strip_state(stripping_video, stripping_audio or audio_absent)

        # 2. Container -> codecs. Audio Codec is skipped here while it's
        # showing a probe-only Passthru codec (DTS/Dolby TrueHD —
        # formats.is_passthru_only): that label was never one of the
        # container's own legal choices to begin with and must never be
        # snapped away from — it's copied verbatim regardless of what the
        # container would otherwise allow.
        self._retarget(self.encoder_menu, formats.video_codecs_for(container), "Encoder")
        encoder = self.encoder_menu.get()
        audio_codec = self.audio_codec_menu.get()
        passthru_only = formats.is_passthru_only(audio_codec)
        if not passthru_only:
            audio_codec = self._retarget(
                self.audio_codec_menu, formats.audio_codecs_for(container), "Audio codec"
            )

        # 3. Video codec -> profile / level / speed / quality.
        profiles = formats.profiles_for(encoder)
        levels = formats.levels_for(encoder)
        speeds = self._speed_values(encoder)
        self._retarget(self.profile_menu, profiles)
        self._retarget(self.level_menu, levels)
        self._apply_speed(encoder)
        self._quality_spec = formats.quality_for(encoder)
        self._apply_quality()

        # 3b. Audio Track dropdown mirrors whichever streams are currently
        # included (the "Choose Stream(s)" picker is what changes that set);
        # this just keeps the option list and selection in sync with it.
        track_values = self._audio_track_values()
        self.audio_track_menu.set_values(track_values)
        if self._active_audio_index is not None:
            prefix = f"Track {self._active_audio_index + 1}"
            match = next((v for v in track_values if v.split(" (")[0] == prefix), prefix)
            self.audio_track_menu.set(match)

        # 4. Passthru — forced for a probe-only codec (DTS/Dolby TrueHD), or
        # a deliberate pick for any other. Either way it's a stream copy, so
        # Bitrate/Channels/Sample Rate stop being user choices: they're
        # overwritten with the active stream's own real probed values
        # (`_apply_passthru_values`) rather than left showing a stale pick
        # that no longer applies. Audio codec -> bitrate list is skipped
        # while Passthru's on (nothing to encode at any bitrate).
        if passthru_only:
            self._set_check(self.passthru_check, True)
        passthru = bool(self.passthru_check.get())
        bitrates = [] if passthru else formats.audio_bitrates_for(audio_codec)
        if not passthru:
            self._retarget(self.audio_bitrate_menu, bitrates)
        else:
            self._apply_passthru_values()

        # 5. Enabled states. A stripped or absent stream disables its whole
        # panel. Audio Channels/Sample Rate are also disabled — and reset
        # back to `Select` rather than left showing a stale pick — while
        # Audio Codec is still unresolved (`Select`) or Passthru is on,
        # since neither leaves anything meaningful to set; on the video side
        # HDR->SDR and the quality slider stay live even before a codec's
        # chosen — deliberately, so the user can dial them in and let the
        # encoder follow once it's picked.
        audio_unresolved = audio_codec == formats.SELECT
        if audio_unresolved and not passthru:
            self.audio_channels_menu.set(formats.SELECT)
            self.audio_samplerate_menu.set(formats.SELECT)
        video_live = not stripping_video and not video_absent
        audio_live = not stripping_audio and not audio_absent

        self._set_enabled(self.encoder_menu, self.encoder_label, video_live)
        self._set_enabled(self.profile_menu, self.profile_label, video_live and bool(profiles))
        self._set_enabled(self.level_menu, self.level_label, video_live and bool(levels))
        self._set_enabled(self.speed_menu, self.speed_label, video_live and bool(speeds))
        # Disabled when libplacebo isn't available -- BT.2390 is the only
        # tone-mapping curve this app will use (see ffmpeg_build.py), never a
        # silent lower-accuracy substitute, so the control simply can't be
        # turned on rather than doing something less accurate than what it
        # promises.
        #
        # Also disabled while the source isn't actually detected as HDR
        # (info["hdr"] -- probe_media's color_transfer check) -- toggling it
        # on for an already-SDR source would just run BT.2390 tone-mapping on
        # content that never needed it. `is True` rather than a bare
        # truthiness check on purpose: `None` (no probe yet / no video stream
        # identified) must read the same as "not HDR", not as "unknown, so
        # allow it".
        #
        # Unlike every other disabled-but-not-forced-off control in this
        # method, HDR->SDR is also forced *off* the moment it's disabled —
        # not just greyed — since a switch left on from before (a file swap,
        # a preset saved against a different source or ffmpeg install) with
        # nothing backing it any more would otherwise silently keep tone-
        # mapping "on" behind a control the user can no longer even see the
        # state of clearly. `_set_check` doesn't fire `command`, so this
        # re-syncs the preview itself via `_apply_preview_frames`.
        hdr_detected = info.get("hdr") is True
        hdr_enabled = video_live and supports_libplacebo() and hdr_detected
        if not hdr_enabled and self.hdr_switch.get():
            self._set_check(self.hdr_switch, False)
            self._apply_preview_frames()
        self._set_hdr_enabled(hdr_enabled)
        # Quality stays live on an unresolved Select (so it can be dialed in
        # ahead of a codec pick — see rule 5's docstring above), but a real
        # codec with no rate-control concept at all (ProRes/DNxHR's quality
        # is entirely the profile choice; FFV1 is lossless) has to actually
        # disable it — nothing dials it in, unlike Select.
        self._set_quality_enabled(
            video_live and (encoder == formats.SELECT or self._quality_spec is not None)
        )

        self._set_enabled(self.audio_track_menu, self.audio_track_label,
                          audio_live and bool(self._included_audio_indices))
        self.choose_streams_btn.configure(state="normal" if audio_live else "disabled")
        # Audio Codec itself only greys for a forced passthru-only codec
        # (nothing to pick — it's not a real dropdown choice); a *manual*
        # Passthru pick on an ordinary codec leaves the codec dropdown live,
        # per its own design — only Bitrate/Channels/Sample Rate stop being
        # meaningful once the stream is a copy.
        self._set_enabled(self.passthru_check, self.passthru_label, audio_live and not passthru_only)
        self._set_enabled(self.audio_codec_menu, self.audio_codec_label, audio_live and not passthru_only)
        self._set_enabled(self.audio_bitrate_menu, self.audio_bitrate_label,
                          audio_live and not passthru and bool(bitrates))
        self._set_enabled(self.audio_channels_menu, self.audio_channels_label,
                          audio_live and not passthru and not audio_unresolved)
        self._set_enabled(self.audio_samplerate_menu, self.audio_samplerate_label,
                          audio_live and not passthru and not audio_unresolved)

        # 6. The rundown.
        self._refresh_summary()

    def _retarget(self, menu, values, what=None):
        """Points a derived dropdown at a freshly-computed option list.

        When the current selection isn't in the new list the dropdown snaps
        to the first legal value — and if `what` is given, says so in a
        toast. Silently swapping a codec out from under the user is exactly
        the kind of thing that makes an options screen feel haunted."""
        before = menu.get()
        menu.set_values(values or [_NO_OPTION])
        after = menu.get()
        if what and self._ready and before != after and before != _NO_OPTION:
            self.app.notify(
                f"{what} switched to {after} — {self.format_menu.get()} can't carry {before}.",
                go_to_queue=False,
            )
        return after

    def _set_enabled(self, widget, label, enabled):
        """Enables/disables a control and dims its label to match, so a dead
        option never looks live."""
        widget.configure(state="normal" if enabled else "disabled")
        if label is not None:
            label.configure(text_color=self._label_color if enabled else _DISABLED_LABEL)

    @staticmethod
    def _set_strip_enabled(checkbox, enabled):
        """Strip Video/Strip Audio's disabled look — `state="disabled"`
        alone leaves the checkbox's own fg_color/border_color (the
        destructive STOP_RED) fully bright, since CTkCheckBox only dims its
        text label on disabled (confirmed against CTkCheckBox._draw, which
        reads those colours unconditionally of state) — the same gotcha
        `_set_quality_enabled` already works around for the quality slider."""
        if enabled:
            checkbox.configure(
                state="normal", fg_color=STOP_RED, hover_color=STOP_RED_HOVER,
                border_color=ctk.ThemeManager.theme["CTkCheckBox"]["border_color"],
                checkmark_color=readable_text_on(STOP_RED),
            )
        else:
            checkbox.configure(
                state="disabled", fg_color=_DISABLED_CHECK, hover_color=_DISABLED_CHECK,
                border_color=_DISABLED_CHECK, checkmark_color=_DISABLED_CHECK,
            )

    def _set_hdr_enabled(self, enabled):
        """Enables/disables the HDR->SDR switch, dimming its label AND the
        switch's own knob/track — `state="disabled"` alone leaves both at
        their normal colours (CTkSwitch, like CTkCheckBox, only dims its own
        text label on disabled — here empty, so nothing would visibly change
        at all — see `_set_strip_enabled` for the identical gotcha)."""
        if enabled:
            theme = ctk.ThemeManager.theme["CTkSwitch"]
            self.hdr_switch.configure(
                state="normal", progress_color=theme["progress_color"],
                button_color=theme["button_color"], button_hover_color=theme["button_hover_color"],
            )
        else:
            self.hdr_switch.configure(
                state="disabled", progress_color=_DISABLED_SWITCH,
                button_color=_DISABLED_SWITCH, button_hover_color=_DISABLED_SWITCH,
            )
        self.hdr_label.configure(text_color=self._label_color if enabled else _DISABLED_LABEL)

    def _speed_values(self, encoder):
        """Speed dropdown values for `encoder` -- AV1's come from a live
        probe of the installed ffmpeg (`core.utilities.av1_preset_range`),
        since SVT-AV1's preset ceiling varies a lot by build (confirmed
        firsthand: 0-8 on one install, -2 to 13 after updating ffmpeg on the
        same machine) rather than formats.py's static fallback list."""
        av1_range = av1_preset_range() if encoder == "AV1" else None
        return formats.speed_values_for(encoder, av1_range)

    def _apply_speed(self, encoder):
        """Re-targets the Speed dropdown for `encoder`. Unlike Profile/Level
        (handled generically by `_retarget`, which snaps an outgoing value to
        the new list's *first* entry), an encoder switch snaps Speed to that
        encoder's own recommended default (`formats.speed_default_for`)
        instead — the first entry in a slow-to-fast list is its most
        extreme/least-representative choice (e.g. "ultrafast"), not a
        sensible one to land on silently."""
        values = self._speed_values(encoder) or [_NO_OPTION]
        before = self.speed_menu.get()
        self.speed_menu.set_values(values)
        if before not in values:
            default = formats.speed_default_for(encoder)
            if default:
                self.speed_menu.set(default)

    def _set_quality_enabled(self, enabled):
        """Enables/disables the *whole* quality slider — knob, fill and all
        three labels. `state="disabled"` alone leaves a CTk slider looking
        live, so the knob and progress colours are swapped explicitly."""
        if enabled:
            defaults = ctk.ThemeManager.theme["CTkSlider"]
            self.crf_slider.configure(
                state="normal",
                button_color=defaults["button_color"],
                button_hover_color=defaults["button_hover_color"],
                progress_color=defaults["progress_color"],
            )
        else:
            self.crf_slider.configure(
                state="disabled",
                button_color=_DISABLED_SLIDER,
                button_hover_color=_DISABLED_SLIDER,
                progress_color=_DISABLED_SLIDER,
            )
        self.crf_label.configure(
            text_color=self._label_color if enabled else _DISABLED_LABEL
        )
        for label in (self.crf_low_label, self.crf_high_label):
            label.configure(text_color="gray60" if enabled else _DISABLED_LABEL)

    def _apply_quality(self):
        """Re-ranges the quality slider for the current encoder.

        CRF is not universal — the MPEG-era encoders take a qscale on a
        completely different scale (1-31 vs 0-51/0-63), so the slider's
        bounds and its label both come from `formats.quality_for`. `Select`
        has no spec of its own, so it falls back to a plain 0-51 CRF range
        rather than freezing on the previous codec's. The current value is
        kept when it still falls inside the new range, and reset to the
        codec's own default when it doesn't."""
        spec = self._quality_spec or _FALLBACK_QUALITY

        low, high = spec["lo"], spec["hi"]
        value = self.crf_slider.get()
        if not (low <= value <= high):
            value = spec["default"]
        # from_ = worst, to = best: keeps low-quality on the left whichever
        # scale is active (both CRF and qscale count *down* toward better).
        self.crf_slider.configure(from_=high, to=low, number_of_steps=high - low)
        self.crf_slider.set(value)
        self.crf_low_label.configure(text=spec["low"])
        self.crf_high_label.configure(text=spec["high"])
        self._update_quality_label()

    def _update_quality_label(self):
        """Writes the live quality readout into the slider's title."""
        spec = self._quality_spec or _FALLBACK_QUALITY
        self.crf_label.configure(text=f"{spec['label']}: {int(round(self.crf_slider.get()))}")

    def _on_quality_change(self, _value=None):
        """Slider callback — the value feeds nothing else, so this refreshes
        the readout and the rundown rather than running a whole sync pass."""
        self._update_quality_label()
        self._refresh_summary()

    # ------------------------------------------------------------------ #
    #  Multi-stream audio (Track dropdown + Choose Stream(s))
    # ------------------------------------------------------------------ #
    def _audio_track_values(self):
        """The Audio Track dropdown's option list: one entry per *included*
        stream, in source order, each annotated with its probed codec name
        ("Track 1 (AAC)") when known — Auto/unresolved streams stay
        unlabeled. Only included streams are offered — the picker is what
        changes that set; the dropdown is just for editing one of them at a
        time."""
        if not self._included_audio_indices:
            return [_NO_OPTION]
        codecs = {s["index"]: s.get("codec") for s in self._audio_streams}
        labels = []
        for i in sorted(self._included_audio_indices):
            label = f"Track {i + 1}"
            codec = codecs.get(i)
            if codec:
                label += f" ({codec})"
            labels.append(label)
        return labels

    @staticmethod
    def _index_from_track_label(label):
        """"Track 3" -> 2 (0-based, matching probe_media's stream indices);
        None for the `_NO_OPTION` placeholder or anything unparseable."""
        try:
            return int(label.split()[1]) - 1
        except (IndexError, ValueError):
            return None

    def _save_active_audio_stream(self):
        """Snapshots whatever the four shared controls currently show into
        `_audio_stream_settings` for the track that's still active — called
        right before switching tracks (or gathering settings), so an edit
        the user just made is never silently dropped."""
        if self._active_audio_index is None:
            return
        self._audio_stream_settings[self._active_audio_index] = {
            "codec": self.audio_codec_menu.get(),
            "bitrate": self._menu_value(self.audio_bitrate_menu),
            "channels": self.audio_channels_menu.get(),
            "sample_rate": self.audio_samplerate_menu.get(),
            "passthru": bool(self.passthru_check.get()),
        }

    def _active_stream_info(self):
        """The probed `audio_streams` descriptor (`core.utilities.
        probe_media`'s per-stream dict) for the currently active track, or
        None (no file probed yet, or no such stream)."""
        for stream in self._audio_streams:
            if stream.get("index") == self._active_audio_index:
                return stream
        return None

    def _apply_passthru_values(self):
        """Passthru is on: Bitrate/Channels/Sample Rate stop being user
        choices and instead mirror the active stream's own real values
        (straight off the probe), since the audio is being copied verbatim
        rather than re-encoded. Set directly — ThemedDropdown.set() doesn't
        check list membership — since the controls are about to be disabled
        anyway; the source's true values frequently aren't one of this
        app's own offered options (e.g. DTS's actual bitrate)."""
        stream = self._active_stream_info() or {}
        self.audio_bitrate_menu.set(stream.get("bitrate_display") or formats.SELECT)
        self.audio_channels_menu.set(stream.get("channels_display") or formats.SELECT)
        self.audio_samplerate_menu.set(stream.get("sample_rate_display") or formats.SELECT)

    def _load_active_audio_stream(self):
        """Writes `_active_audio_index`'s stored settings into the four
        shared controls. Muted (`_ready` off) for the duration, same as
        `_apply_settings` — this is the form being written *into*, not the
        user changing anything, so a codec that's since become illegal for
        the current container shouldn't pop a "switched to..." toast."""
        settings = (
            self._audio_stream_settings.get(self._active_audio_index, {})
            if self._active_audio_index is not None else {}
        )
        was_ready, self._ready = self._ready, False
        try:
            codec = settings.get("codec", formats.SELECT)
            if formats.is_passthru_only(codec):
                # Never one of the codec menu's own options — see
                # formats.PASSTHRU_ONLY_CODECS — so it's set unconditionally
                # rather than through the usual membership check below.
                self.audio_codec_menu.set(codec)
            else:
                self.audio_codec_menu.set(
                    codec if codec in self.audio_codec_menu.cget("values") else formats.SELECT
                )
            self._set_check(self.passthru_check, settings.get("passthru", False))
            self._sync_controls()   # settles the bitrate list for this codec
            if not settings.get("passthru"):
                for menu, key in (
                    (self.audio_bitrate_menu, "bitrate"),
                    (self.audio_channels_menu, "channels"),
                    (self.audio_samplerate_menu, "sample_rate"),
                ):
                    value = settings.get(key, formats.SELECT)
                    if value in menu.cget("values"):
                        menu.set(value)
        finally:
            self._ready = was_ready

    def _on_audio_track_change(self, _value=None):
        """The user switched which stream the four Audio controls are
        editing: bank the outgoing track's edits, load the incoming one's."""
        self._save_active_audio_stream()
        self._active_audio_index = self._index_from_track_label(self.audio_track_menu.get())
        self._load_active_audio_stream()
        self._sync_controls()

    def _open_stream_picker(self):
        """Opens the "Choose Stream(s)" dialog and applies the result — the
        set of stream indices that end up in the output. If the previously
        active track got unchecked, falls back to the first still-included
        one (or None, if the user somehow leaves nothing checked and Strip
        Audio isn't on — _validate_settings catches that at queue time)."""
        if not self._audio_streams:
            show_message(
                self.app, "No Audio Streams",
                "This file has no audio streams to choose from.",
            )
            return
        chosen = choose_audio_streams(self.app, self._audio_streams, self._included_audio_indices)
        if chosen is None:
            return
        self._save_active_audio_stream()
        self._included_audio_indices = chosen
        if self._active_audio_index not in chosen:
            self._active_audio_index = min(chosen) if chosen else None
        self._load_active_audio_stream()
        self._sync_controls()

    def _auto_select_audio_streams(self, info):
        """(Re-)initializes the per-stream audio state the first time this
        file's probe result lands — every probed stream defaults to
        `Select` unless its own codec/channels/rate/bitrate matches one of
        this app's options (mirrors `_auto_select_codecs`' reasoning, just
        per stream instead of once globally). Included defaults to just the
        first stream, matching this app's pre-multi-stream behaviour for a
        file nobody's touched the picker on yet.

        Guarded on `_audio_streams_source` (the file path this was last run
        for): the probe's "info" message and the later "frames" message can
        both trigger a `_broadcast_media_info` re-delivery for the very same
        file (a cache hit on tab switch, a live theme rebuild), and re-
        running this on that second call would silently discard whatever the
        user has since picked or edited."""
        if self.app.current_file_path == self._audio_streams_source:
            return
        self._audio_streams_source = self.app.current_file_path
        streams = info.get("audio_streams") or []
        self._audio_streams = streams
        legal_codecs = formats.audio_codecs_for(self.format_menu.get())
        self._audio_stream_settings = {}
        for stream in streams:
            codec = stream.get("codec")
            # DTS / Dolby TrueHD have no re-encode path here at all — a
            # track holding one is never left on Select the way an
            # unrecognized codec would be; it's named directly (even though
            # neither is ever a legal dropdown choice) and forced to
            # Passthru.
            passthru_only = formats.is_passthru_only(codec)
            self._audio_stream_settings[stream["index"]] = {
                "codec": codec if (passthru_only or codec in legal_codecs) else formats.SELECT,
                "bitrate": stream.get("bitrate_display") or formats.SELECT,
                "channels": stream.get("channels_display") or formats.SELECT,
                "sample_rate": stream.get("sample_rate_display") or formats.SELECT,
                "passthru": passthru_only,
            }
        self._included_audio_indices = {0} if streams else set()
        self._active_audio_index = 0 if streams else None
        self._load_active_audio_stream()

    def _on_trim_change(self, *_):
        """A trim spinner's value changed — refresh just the rundown so the
        trim line updates as the user types, without a whole constraint pass.
        Guarded on `_ready` so it's inert while the form is still building or
        a settings dict is being written in (a full sync follows that)."""
        if getattr(self, "_ready", False):
            self._refresh_summary()

    def _refresh_summary(self):
        """Rebuilds the Overview rundown — the one view where both streams and
        the trim are visible at the same time. (The container isn't listed:
        the Output Format dropdown right beside it already says it.)"""
        info = self.app.media_info

        # Text here is kept terse on purpose — the rundown shares its row
        # with the controls, so it has maybe 260px to say everything in.

        # Video
        if self.strip_video_check.get():
            video = ("— removed —", STOP_RED)
        elif info.get("has_video") is False:
            video = ("— no video stream —", STOP_RED)
        elif self.encoder_menu.get() == formats.SELECT:
            video = ("— pick an encoder —", STOP_RED)
        else:
            encoder = self.encoder_menu.get()
            bits = [formats.short_name(encoder)]
            if formats.profiles_for(encoder):
                bits.append(self.profile_menu.get())
            if formats.levels_for(encoder):
                bits.append("L" + self.level_menu.get())
            if self._quality_spec:
                kind = "CRF" if self._quality_spec["kind"] == "crf" else "Q"
                bits.append(f"{kind}{int(round(self.crf_slider.get()))}")
            if self.hdr_switch.get():
                bits.append("SDR")
            video = (" · ".join(bits), None)

        # Audio — describes whichever stream sorts first among the included
        # ones, with a "+N more" tail once more than one is included. Reads
        # straight off the committed per-stream settings (not the four live
        # controls, which only reflect whichever track happens to be active
        # right now) so switching tracks doesn't make the rundown flicker
        # between different streams' summaries.
        if self.strip_audio_check.get():
            audio = ("— removed —", STOP_RED)
        elif info.get("has_audio") is False:
            audio = ("— no audio stream —", STOP_RED)
        elif not self._included_audio_indices:
            audio = ("— no streams selected —", STOP_RED)
        else:
            self._save_active_audio_stream()
            primary = self._audio_stream_settings.get(min(self._included_audio_indices), {})
            if primary.get("codec", formats.SELECT) == formats.SELECT:
                audio = ("— pick a codec —", STOP_RED)
            else:
                bits = [primary["codec"]]
                if primary.get("passthru"):
                    bits.append("copy")
                for key in ("bitrate", "channels", "sample_rate"):
                    value = primary.get(key, formats.SELECT)
                    if value not in (formats.SELECT, _NO_OPTION, ""):
                        bits.append(value.replace(" Hz", ""))
                extra = len(self._included_audio_indices) - 1
                if extra:
                    bits.append(f"+{extra} more")
                audio = (" · ".join(bits), None)

        # Length
        start = self.start_time_spinner.get_total_seconds()
        duration = self.duration_time_spinner.get_total_seconds()
        if not start and not duration:
            length = ("Whole File", None)
        elif not duration:
            length = (f"{_hms(start)} → end", None)
        else:
            length = (f"{_hms(start)} → {_hms(start + duration)}", None)

        self.summary.set_values([video, audio, length])


    # ------------------------------------------------------------------ #
    #  Presets
    # ------------------------------------------------------------------ #
    def _refresh_preset_menu(self, select=None):
        """Re-reads the saved preset names into the dropdown."""
        self.preset_menu.set_values(presets.menu_values(_TAB))
        if select is not None:
            self.preset_menu.set(select)

    def _on_preset_selected(self, name):
        """Applies a saved recipe. Presets carry codec/quality settings only
        — never the trim or the paths — so loading one can't quietly re-trim
        a clip or repoint its output."""
        if name == presets.NONE_LABEL:
            return
        stored = presets.get(_TAB, name)
        if stored is None:
            self._refresh_preset_menu(select=presets.NONE_LABEL)
            return
        self._apply_settings(stored)
        self.app.notify(f"Preset '{name}' applied.", go_to_queue=False)

    def _on_preset_save(self):
        """Names and saves the current codec/quality settings as a recipe."""
        current = self.preset_menu.get()
        initial = "" if current == presets.NONE_LABEL else current
        name = ask_text(
            self.app, "Save Preset",
            "Name this preset. It stores the container and every codec / "
            "quality setting — not the trim, and not the file paths.",
            initial=initial,
        )
        if name is None:
            return
        if name == presets.NONE_LABEL:
            show_message(self.app, "Reserved Name", "That name is reserved. Pick another.")
            return
        if presets.exists(_TAB, name) and not ask_yes_no(
            self.app, "Overwrite Preset?", f"'{name}' already exists. Replace it?"
        ):
            return
        presets.save(_TAB, name, self._gather_settings())
        self._refresh_preset_menu(select=name)
        self.app.notify(f"Preset '{name}' saved.", go_to_queue=False)

    def _on_preset_delete(self):
        """Deletes the selected recipe, after confirming."""
        name = self.preset_menu.get()
        if name == presets.NONE_LABEL:
            show_message(self.app, "No Preset Selected", "Pick a preset to delete first.")
            return
        if not ask_yes_no(self.app, "Delete Preset?", f"Delete the preset '{name}'?"):
            return
        presets.delete(_TAB, name)
        self._refresh_preset_menu(select=presets.NONE_LABEL)
        self.app.notify(f"Preset '{name}' deleted.", go_to_queue=False)

    # ------------------------------------------------------------------ #
    #  File selection / output path
    # ------------------------------------------------------------------ #
    def select_input_file(self):
        """Allows user to pick a video file via file dialog."""
        file_path = filedialog.askopenfilename(
            title="Select Video File",
            filetypes=[("Video Files", "*.mp4 *.mkv *.avi *.mov *.webm *.mxf"), ("All Files", "*.*")],
        )
        if file_path:
            self.app.update_global_file(file_path)

    def _reveal_preview(self):
        """First thumbnail set has arrived: swap the DropBox out for the
        preview carousel. (The header row with the sub-tab switch + filename
        label is always packed, so it isn't touched here.)"""
        self.drop_box.pack_forget()
        if not self.carousel.winfo_ismapped():
            self.carousel.pack(pady=(2, 2), fill="both", expand=True)

    def refresh_appearance(self):
        """Called by `app.refresh_previews_appearance` right after a live
        Appearance Mode switch — this tab is never rebuilt for that (unlike
        a theme change), so anything that pinned a colour at construction
        needs an explicit nudge to pick up the new mode."""
        self.carousel.refresh_appearance()
        self.sub_tab_bar.refresh_appearance()

    def on_media_info(self, info):
        """A probe of the selected file landed (see LlamaGUI._decode_worker).

        Adopts the source's own container as the output default — but only
        while the user hasn't picked one themselves (`_auto_format`), so a
        new file drop never overrides a deliberate choice. Then, now that the
        container's settled (it filters the codec lists), auto-resolves
        Encoder/Audio Codec from the same probe so an untouched `Select`
        becomes a genuine re-encode at the source's own parameters rather
        than staying unresolved."""
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
        """Auto-picks Encoder (and best-effort Profile/Level) from the probe,
        so an untouched `Select` resolves to the source's own video codec
        instead of staying a placeholder. Mirrors `_auto_format`: only
        touches Encoder while `_auto_encoder` is still set (the user hasn't
        picked one themselves), and a value the probe couldn't identify or
        that isn't legal for the current container simply leaves it on
        `Select` — never a guess (see `_validate_settings`, which blocks a
        job left that way while the video stream is actually present).

        Audio's equivalent is `_auto_select_audio_streams` — per-stream, and
        run unconditionally per file rather than gated on a single flag,
        since there's one such flag *per stream* now, not one global one."""
        if self._auto_encoder is not None:
            video = info.get("video")
            if video and video in self.encoder_menu.cget("values"):
                self.encoder_menu.set(video)
                self._auto_encoder = video
                profile = info.get("video_profile")
                if profile and profile in formats.profiles_for(video):
                    self.profile_menu.set(profile)
                level = info.get("video_level")
                if level and level in formats.levels_for(video):
                    self.level_menu.set(level)

    def _autofill_output_path(self):
        """Refreshes the output field's FILENAME for the newly-selected
        input file, every time — '<directory>/<input basename>_encoded
        <format>'. The directory is whatever's currently in the field
        (the default save location the first time, or wherever the user
        last Browsed to since), never reset back to the default just
        because a new file came in.

        This used to also gate on `self._auto_output` (skipping the
        refresh entirely once the user had Browsed a custom path even
        once) — meaning the FILENAME froze on whatever file was selected
        at that moment, silently mismatching every file imported
        afterward. A directory the user picked is worth remembering
        across a file swap; a stale filename from the previous input
        never is, so the filename is unconditionally re-derived from the
        current input while the directory alone persists."""
        input_file = self.app.current_file_path
        if not input_file:
            return
        base = os.path.splitext(os.path.basename(input_file.replace("\\", "/")))[0]
        # The field may currently hold either a full file path (an earlier
        # auto-fill, or a manual Browse pick) or a bare directory (fresh off
        # __init__, before any file has ever been picked, it's just
        # `default_save_location` with no filename at all) -- os.path.
        # dirname() on the latter would strip its last real folder segment
        # instead of leaving it alone, so the two cases need telling apart
        # by whether there's a file extension to split off.
        current = self.save_entry.get().strip().replace("\\", "/")
        if current and os.path.splitext(current)[1]:
            directory = os.path.dirname(current)
        else:
            directory = current
        directory = directory or self.app.default_save_location or ""
        suggested = os.path.normpath(
            os.path.join(directory, f"{base}_encoded{self.format_menu.get()}")
        )
        self.save_entry.delete(0, "end")
        self.save_entry.insert(0, suggested)
        self._auto_output = suggested

    def _on_format_change(self, _value=None):
        """The user picked a container themselves: stop auto-adopting the
        source's, swap the output path's extension, and re-run the cascade
        (the container is the root of the whole option tree)."""
        self._auto_format = None
        current = self.save_entry.get().strip()
        root, extension = os.path.splitext(current)
        if extension:
            updated = root + self.format_menu.get()
            self.save_entry.delete(0, "end")
            self.save_entry.insert(0, updated)
            if self._auto_output is not None:
                self._auto_output = updated
        self._sync_controls()

    def select_save_location(self):
        """Lets the user pick a full output FILE path (not just a folder)."""
        input_file = self.app.current_file_path
        fmt = self.format_menu.get()  # e.g. ".mkv" — already dotted

        if input_file:
            input_name = input_file.split("/")[-1]
            base_name = input_name.rsplit(".", 1)[0] if "." in input_name else input_name
            initial_dir = "/".join(input_file.replace("\\", "/").split("/")[:-1])
            default_name = f"{base_name}_encoded{fmt}"
        else:
            initial_dir = self.app.default_save_location
            default_name = f"output{fmt}"

        existing = self.save_entry.get().strip()
        if existing:
            existing_dir = "/".join(existing.replace("\\", "/").split("/")[:-1])
            if existing_dir:
                initial_dir = existing_dir

        file_path = filedialog.asksaveasfilename(
            title="Select Output File",
            initialdir=initial_dir,
            initialfile=default_name,
            defaultextension=fmt,
            filetypes=[("MP4 Video", "*.mp4"), ("MKV Video", "*.mkv"), ("All Files", "*.*")],
        )
        if file_path:
            self.save_entry.delete(0, "end")
            self.save_entry.insert(0, file_path)
            self._auto_output = None  # user chose their own — stop auto-filling

    # ------------------------------------------------------------------ #
    #  Settings in / out
    # ------------------------------------------------------------------ #
    def _gather_settings(self):
        """Collects the current Encoding state into a plain dict. Every field
        is read regardless of which sub-tab is showing — all three panels
        stay built and alive. `gpu_enabled` is the global Settings-tab
        preference, not a control of ours.

        `audio_streams` is built from `_audio_stream_settings` for every
        *included* index (see `_save_active_audio_stream` — called first so
        the currently-active track's live widget values are folded in), in
        source order; each entry keeps its own `index` so `ffmpeg_vars` knows
        which source stream (`-map 0:a:<index>`) it describes."""
        self._save_active_audio_stream()
        audio_streams = [
            dict(self._audio_stream_settings.get(i, {}), index=i)
            for i in sorted(self._included_audio_indices)
        ]
        return {
            "input_file": self.app.current_file_path,
            "output_path": self.save_entry.get(),
            "output_format": self.format_menu.get(),
            "start_secs": self.start_time_spinner.get_total_seconds(),
            "duration_secs": self.duration_time_spinner.get_total_seconds(),
            "av_sync": bool(self.av_sync_check.get()),
            "encoder": self.encoder_menu.get(),
            "profile": self._menu_value(self.profile_menu),
            "level": self._menu_value(self.level_menu),
            "speed": self._menu_value(self.speed_menu),
            "quality": int(round(self.crf_slider.get())),
            "gpu_enabled": bool(self.app.gpu_enabled),
            "hdr_to_sdr": bool(self.hdr_switch.get()),
            # The source's probed ST 2086 mastering peak and MaxCLL, if it
            # has them — not a user choice, but a fact about the input file
            # at queue time (same spirit as input_file itself). Both
            # together decide whether the tonemap's peak_detect runs — see
            # core.utilities.libplacebo_tonemap_vf and ffmpeg_build.
            # build_encode_command for why a mastering peak alone isn't
            # enough (confirmed: a file with a declared peak but no real
            # MaxCLL measurement tonemaps *worse*, not better, with
            # peak_detect forced off).
            "mastering_max_nits": self.app.media_info.get("mastering_max_nits"),
            "max_cll": self.app.media_info.get("max_cll"),
            "strip_video": bool(self.strip_video_check.get()),
            "strip_audio": bool(self.strip_audio_check.get()),
            "audio_streams": audio_streams,
        }

    def _apply_settings(self, settings):
        """Writes a settings dict into the form **in dependency order** —
        container, then codecs, then codec-detail options — running a sync
        pass between each tier so every list is legal before the next tier's
        value is written into it. A key that's absent leaves its control
        alone, which is how a preset (recipe keys only) can share this path
        with a full restore.

        Snap-toasts are muted for the duration: a value landing in a list
        that hasn't been rebuilt yet isn't the user changing anything."""
        if not settings:
            return
        was_ready, self._ready = self._ready, False
        try:
            if settings.get("input_file"):
                self.app.update_global_file(settings["input_file"])

            if "output_path" in settings:
                self.save_entry.delete(0, "end")
                self.save_entry.insert(0, settings["output_path"])
                self._auto_output = self.save_entry.get().strip()

            if "start_secs" in settings:
                self.start_time_spinner.set(settings["start_secs"])
            if "duration_secs" in settings:
                self.duration_time_spinner.set(settings["duration_secs"])
            if "av_sync" in settings:
                self._set_check(self.av_sync_check, settings["av_sync"])

            # Strip flags first: they gate whole panels, so settling them
            # before the cascade means the enabled-state pass runs once.
            if "strip_video" in settings:
                self._set_check(self.strip_video_check, settings["strip_video"])
            if "strip_audio" in settings:
                self._set_check(self.strip_audio_check, settings["strip_audio"])

            # Tier 1 — the container decides which codecs exist at all.
            if "output_format" in settings:
                self.format_menu.set(settings["output_format"])
                self._auto_format = None
            self._sync_controls()

            # Tier 2 — codecs decide which profiles/levels/bitrates exist.
            # Restoring an explicit, still-legal value freezes auto-tracking
            # (same as output_format/_auto_format above); a stale value from
            # a pre-"Select" preset (e.g. the old "Source") is dropped by
            # _set_menu's own guard and leaves auto-pick free to still fire.
            encoder = settings.get("encoder")
            if encoder is not None and encoder in self.encoder_menu.cget("values"):
                self.encoder_menu.set(encoder)
                self._auto_encoder = None
            self._sync_controls()

            # Tier 3 — the leaves, plus multi-stream audio. `audio_streams`
            # is a *full-state* key (this is also how the live theme rebuild
            # restores an in-progress form — see load_settings) rather than a
            # preset one — presets don't carry track picks, same precedent as
            # Muxing's — so a preset load leaves whatever the file's own
            # probe already set up alone; this block only runs when the key
            # is actually present.
            self._set_menu(self.profile_menu, settings.get("profile"))
            self._set_menu(self.level_menu, settings.get("level"))
            self._set_menu(self.speed_menu, settings.get("speed"))
            if "audio_streams" in settings:
                included = set()
                stream_settings = {}
                for entry in settings["audio_streams"] or []:
                    index = entry.get("index")
                    if index is None:
                        continue
                    included.add(index)
                    stream_settings[index] = {
                        "codec": entry.get("codec", formats.SELECT),
                        "bitrate": entry.get("bitrate", formats.SELECT),
                        "channels": entry.get("channels", formats.SELECT),
                        "sample_rate": entry.get("sample_rate", formats.SELECT),
                        "passthru": bool(entry.get("passthru")),
                    }
                self._audio_stream_settings.update(stream_settings)
                self._included_audio_indices = included
                self._active_audio_index = min(included) if included else None
                self._load_active_audio_stream()
            if "hdr_to_sdr" in settings:
                self._set_check(self.hdr_switch, settings["hdr_to_sdr"])
            if settings.get("quality") is not None:
                self.crf_slider.set(settings["quality"])
        finally:
            self._ready = was_ready
        self._sync_controls()
        # _set_check above doesn't fire hdr_switch's own command (select()/
        # deselect() never do), so a preset/theme-rebuild restore that
        # leaves it checked would otherwise never trigger the tone-mapped
        # preview on its own — this covers that half of _on_thumbnails'
        # docstring. Usually a no-op after a theme rebuild specifically:
        # the app's hdr_frames/hdr_frames_path cache survived the rebuild,
        # so _apply_preview_frames finds it already there.
        self._apply_preview_frames()
        if self.hdr_switch.get() and self.app.hdr_frames_path != self._preview_path:
            self._start_hdr_render()

    def load_settings(self, settings):
        """Restores a full settings dict into the UI (used by the live theme
        rebuild, which snapshots each tab before destroying it)."""
        self._apply_settings(settings)

    @staticmethod
    def _menu_value(menu):
        """A derived dropdown's value, with the `—` placeholder reported as
        an empty string — so a settings dict says "this codec has no profile"
        rather than carrying a dash around as if it were a real choice."""
        value = menu.get()
        return "" if value == _NO_OPTION else value

    @staticmethod
    def _set_menu(menu, value):
        """Selects `value` only if it's actually one of the menu's current
        options — a stale value from an older settings dict is dropped rather
        than displayed as a selection the list doesn't contain."""
        if value is not None and value in menu.cget("values"):
            menu.set(value)

    @staticmethod
    def _set_check(widget, on):
        """select()/deselect() from a truthy value, for checkboxes and the
        HDR switch alike."""
        widget.select() if on else widget.deselect()

    def _validate_settings(self, settings):
        """Checks the minimum required fields before queueing/encoding,
        raising a modal dialog on the first thing missing. Combination
        validity isn't checked here — `_sync_controls` makes illegal
        container/codec pairings unrepresentable in the first place.

        The Encoder/Audio Codec checks are last: a present-or-unknown stream
        left on `Select` (never auto-resolved, and the user didn't pick one)
        blocks the job rather than guessing — but a stream the source
        genuinely doesn't have (`has_video`/`has_audio` is False) is exempt,
        since there's nothing to encode either way."""
        if not settings["input_file"]:
            show_message(
                self.app, "No File Selected",
                "Add a video file before queueing or encoding — drag one onto "
                "the drop box, or double-click it to browse.",
            )
            return False
        if not settings["output_path"]:
            show_message(
                self.app, "No Save Location",
                "Choose where the encoded file should be saved before "
                "continuing. Use Browse, or set a default save location on the "
                "Settings tab.",
            )
            return False
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
            unresolved = any(
                entry.get("codec", formats.SELECT) == formats.SELECT for entry in streams
            )
            if not streams or unresolved:
                show_message(
                    self.app, "Pick an Audio Codec",
                    "Every included audio stream needs a codec before "
                    "queueing or encoding — choose one on the Audio sub-tab "
                    "(or use Choose Stream(s) to include at least one), or "
                    "turn on Strip Audio.",
                )
                return False
        if (settings["hdr_to_sdr"] and not settings["strip_video"]
                and not supports_libplacebo()):
            # The switch is normally disabled before this is ever reachable
            # (see _sync_controls) -- this only catches a value left on from
            # before (e.g. a preset saved on a different ffmpeg install).
            # BT.2390 via libplacebo is the only tone-mapping curve this app
            # will use; there's no less-accurate fallback to quietly run
            # instead (see ffmpeg_build.py).
            show_message(
                self.app, "HDR to SDR Unavailable",
                "This ffmpeg install doesn't have libplacebo (needed for "
                "accurate BT.2390 tone-mapping) compiled in. Update ffmpeg, "
                "or turn HDR to SDR off before continuing.",
            )
            return False
        queue_tab = self.app.tabs.get("Queue")
        claimed = bool(queue_tab and queue_tab.claims_output(settings["output_path"]))
        return confirm_output_path(
            self.app, settings["output_path"], settings["input_file"], claimed
        )

    # ------------------------------------------------------------------ #
    #  Queue hand-off
    # ------------------------------------------------------------------ #
    def encode_now(self):
        settings = self._gather_settings()
        if not self._validate_settings(settings):
            return

        filename = os.path.basename(settings["input_file"].replace("\\", "/"))
        description = f"{filename}  ·  Direct Encode"

        queue_tab = self.app.tabs.get("Queue")
        if queue_tab:
            task_id = queue_tab.add_task(description, settings=settings, status="Queued", source_tab="Encoding")
            outcome = queue_tab.start_task(task_id)
            message = {
                "started": "Encoding job has begun.",
                "next": "Encoding job will run next.",
                "paused": "Encoding job will run next — the queue is paused.",
            }[outcome]
            self.app.notify(message)
        else:
            print(f"Queue tab unavailable — would have encoded now: {settings}")

    def add_to_queue(self):
        settings = self._gather_settings()
        if not self._validate_settings(settings):
            return

        filename = os.path.basename(settings["input_file"].replace("\\", "/"))
        description = f"{filename}  ·  {settings['duration_secs']}s from {settings['start_secs']}s"

        queue_tab = self.app.tabs.get("Queue")
        if queue_tab:
            queue_tab.add_task(description, settings=settings, status="Queued", source_tab="Encoding")
            self.app.notify("Encoding job added to queue.")
        else:
            print(f"Queue tab unavailable — would have queued: {settings}")
