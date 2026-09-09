import os
import customtkinter as ctk
from tkinter import filedialog

from components.animated_switch import AnimatedSwitch
from components.dialogs import ask_text, ask_yes_no, show_message
from components.drop_box import DropBox
from components.dropdown import ThemedDropdown
from components.sub_tab_bar import SubTabBar
from components.summary_panel import SummaryPanel
from components.thumbnail_carousel import ThumbnailCarousel
from components.time_spinner import TimeSpinner
from core import formats, presets
from core.theme import get_active_theme, readable_text_on, STOP_RED, STOP_RED_HOVER

# One consistent "disabled" label colour, so a control that's dimmed by two
# different rules never compounds into a darker grey than one dimmed by one.
_DISABLED_LABEL = "gray50"

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
        self._show_subtab("Overview")

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

        self.label = ctk.CTkLabel(
            master=self.header_row, text="", font=ctk.CTkFont(size=11), anchor="w"
        )
        self.label.pack(side="left", fill="x", expand=True, padx=(10, 0))
        self.label.bind("<Double-Button-1>", lambda e: self.select_input_file())

        self.carousel = ThumbnailCarousel(
            master=self.top_container,
            on_reselect=self.select_input_file,
            on_populated=self._reveal_preview,
            on_index=self.app.sync_preview_index,   # keep both tabs on the same frame
        )

        self.drop_box = DropBox(
            master=self.top_container, on_file_selected=self.app.update_global_file, height=380
        )
        self.drop_box.pack(fill="both", expand=True)

        self.app.register_tab_ui(self.label, self.carousel, on_thumbnail=self.carousel.set_frames)

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
            self.globals_row, "Output Format:", formats.containers(), 88,
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
        self.start_frame.pack(side="left")
        self.start_label = ctk.CTkLabel(master=self.start_frame, text="Start Time:", font=("Arial", 12, "bold"))
        self.start_label.pack(anchor="w", pady=(0, 1))
        self.start_time_spinner = TimeSpinner(master=self.start_frame, initial_seconds=0)
        self.start_time_spinner.pack(anchor="w")

        self.duration_frame = ctk.CTkFrame(master=self.trim_row, fg_color="transparent")
        self.duration_frame.pack(side="left", padx=(14, 0))
        self.duration_label = ctk.CTkLabel(master=self.duration_frame, text="Clip Duration:", font=("Arial", 12, "bold"))
        self.duration_label.pack(anchor="w", pady=(0, 1))
        self.duration_time_spinner = TimeSpinner(master=self.duration_frame, initial_seconds=0)
        self.duration_time_spinner.pack(anchor="w")

        # -- Right: the rundown --
        self.summary = SummaryPanel(master=right, labels=["Container", "Video", "Audio", "Trim"])
        self.summary.pack(fill="x", anchor="s")

        return left, right

    def _build_video_panel(self, left_parent, right_parent):
        """Video: the Encoder / Profile / Level codec row on the left, Strip
        Video + the HDR switch + the quality slider on the right.

        Profile and Level are *derived* from Encoder — '4.0' means different
        things to H.264 and H.265, and VP8 has no profiles at all — so their
        option lists are filled by `_sync_controls`, not hardcoded here."""
        left = ctk.CTkFrame(master=left_parent, fg_color="transparent")
        right = ctk.CTkFrame(master=right_parent, fg_color="transparent")

        self.codec_options_frame = ctk.CTkFrame(master=left, fg_color="transparent")
        self.codec_options_frame.pack(anchor="w")

        self.encoder_label, self.encoder_menu = self._panel_dropdown(
            self.codec_options_frame, "Encoder:", [formats.SOURCE], 138,
            command=self._on_control_change,
        )
        self.profile_label, self.profile_menu = self._panel_dropdown(
            self.codec_options_frame, "Profile:", [_NO_OPTION], 108, padx=(10, 0),
            command=self._on_control_change,
        )
        self.level_label, self.level_menu = self._panel_dropdown(
            self.codec_options_frame, "Level:", [_NO_OPTION], 92, padx=(10, 0),
            command=self._on_control_change,
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

        # HDR to SDR — an AnimatedSwitch (slides instead of snapping). Built
        # with text="" and width=42 so a separate label sits to its LEFT:
        # CTkSwitch's internal grid always reserves its (here-empty) text
        # column, so without the narrow width anchor="e" would leave phantom
        # label space instead of landing the toggle flush right.
        self.hdr_row = ctk.CTkFrame(master=right, fg_color="transparent")
        self.hdr_row.pack(anchor="e", pady=2)

        self.hdr_label = ctk.CTkLabel(master=self.hdr_row, text="HDRtoSDR")
        self.hdr_label.pack(side="left", padx=(0, 8))
        self.hdr_label.bind("<Button-1>", lambda e: self._toggle_hdr())

        self.hdr_switch = AnimatedSwitch(
            master=self.hdr_row, text="", width=42, command=self._on_control_change
        )
        self.hdr_switch.pack(side="left")

        # Quality slider. Its range, default, end labels and even its *kind*
        # (CRF vs qscale) come from the encoder — see formats.quality_for and
        # _apply_quality. Always built reversed (from_=worst, to=best) so the
        # slider reads low-quality-left / high-quality-right whichever scale
        # is in play.
        self.crf_frame = ctk.CTkFrame(master=right, fg_color="transparent")
        self.crf_frame.pack(fill="x", pady=(6, 0))

        self.crf_label = ctk.CTkLabel(master=self.crf_frame, text="Quality", font=("Arial", 12, "bold"))
        self.crf_label.pack(anchor="center", pady=(0, 1))

        self.crf_slider_row = ctk.CTkFrame(master=self.crf_frame, fg_color="transparent")
        self.crf_slider_row.pack(anchor="center")

        self.crf_low_label = ctk.CTkLabel(
            master=self.crf_slider_row, text="Low", text_color="gray60", font=("Arial", 11)
        )
        self.crf_low_label.pack(side="left", padx=(0, 4))

        self.crf_slider = ctk.CTkSlider(
            master=self.crf_slider_row, from_=51, to=0, number_of_steps=51,
            width=180, command=self._on_quality_change,
        )
        self.crf_slider.pack(side="left")

        self.crf_high_label = ctk.CTkLabel(
            master=self.crf_slider_row, text="Placebo", text_color="gray60", font=("Arial", 12)
        )
        self.crf_high_label.pack(side="left", padx=(4, 0))

        return left, right

    def _build_audio_panel(self, left_parent, right_parent):
        """Audio: Codec / Bitrate / Channels / Sample Rate on one row
        (mirroring the Video codec row), Strip Audio on the right."""
        left = ctk.CTkFrame(master=left_parent, fg_color="transparent")
        right = ctk.CTkFrame(master=right_parent, fg_color="transparent")

        self.audio_options_frame = ctk.CTkFrame(master=left, fg_color="transparent")
        self.audio_options_frame.pack(anchor="w")

        self.audio_codec_label, self.audio_codec_menu = self._panel_dropdown(
            self.audio_options_frame, "Audio Codec:", [formats.SOURCE], 108,
            command=self._on_control_change,
        )
        self.audio_bitrate_label, self.audio_bitrate_menu = self._panel_dropdown(
            self.audio_options_frame, "Bitrate:", [_NO_OPTION], 78, padx=(10, 0),
            command=self._on_control_change,
        )
        self.audio_channels_label, self.audio_channels_menu = self._panel_dropdown(
            self.audio_options_frame, "Channels:", formats.AUDIO_CHANNELS, 92,
            default=formats.SOURCE, padx=(10, 0), command=self._on_control_change,
        )
        self.audio_samplerate_label, self.audio_samplerate_menu = self._panel_dropdown(
            self.audio_options_frame, "Sample Rate:", formats.AUDIO_SAMPLE_RATES, 106,
            default=formats.SOURCE, padx=(10, 0), command=self._on_control_change,
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

    def _pin_options_height(self):
        """Locks `options_row` to the tallest sub-tab's natural height.

        The three panels legitimately differ (Overview stacks two rows, Video
        stacks Strip/HDR/quality, Audio is a single row), so without this the
        DropBox / preview above would resize every time the sub-tab changed.
        Measured once here rather than hardcoded, so the number can't drift
        out of step with the widgets."""
        tallest = 0
        for left, right in (
            (self.overview_left, self.overview_right),
            (self.video_left, self.video_right),
            (self.audio_left, self.audio_right),
        ):
            left.pack(anchor="w")
            right.pack(fill="x")
            self.options_row.update_idletasks()
            tallest = max(tallest, left.winfo_reqheight(), right.winfo_reqheight())
            left.pack_forget()
            right.pack_forget()

        self.options_row.configure(height=max(tallest, 96))
        self.options_row.pack_propagate(False)

    def _show_subtab(self, name):
        """Swaps the visible sub-tab: packs one panel's left row into
        `left_col` and its right stack into `right_col`, forgetting the
        others'. `options_row` is height-pinned, so the shorter panels simply
        get slack below the preview rather than resizing it."""
        self._active_subtab = name
        for frame in (self.overview_left, self.video_left, self.audio_left):
            frame.pack_forget()
        for frame in (self.overview_right, self.video_right, self.audio_right):
            frame.pack_forget()

        pairs = {
            "Overview": (self.overview_left, self.overview_right),
            "Video": (self.video_left, self.video_right),
            "Audio": (self.audio_left, self.audio_right),
        }
        left, right = pairs.get(name, pairs["Overview"])
        left.pack(anchor="w")
        right.pack(fill="x")

    # ------------------------------------------------------------------ #
    #  The single constraint pass
    # ------------------------------------------------------------------ #
    def _on_control_change(self, *_):
        """Every control's `command` lands here, which just re-runs the one
        constraint pass. No control ever reaches into another directly."""
        self._sync_controls()

    def _toggle_hdr(self):
        """Clicking the HDRtoSDR label toggles the switch (and re-syncs)."""
        if self.hdr_switch.cget("state") != "disabled":
            self.hdr_switch.toggle()
            self._sync_controls()

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
          1. stream presence — both streams stripped would write an empty file
          2. container -> legal video/audio codec lists
          3. video codec -> profile / level / rate-control kind and range
          4. audio codec -> whether a bitrate is ours to set
          5. everything a removed or copied stream makes meaningless
          6. the Overview rundown, which is the only cross-panel view
        """
        container = self.format_menu.get()
        stripping_video = bool(self.strip_video_check.get())
        stripping_audio = bool(self.strip_audio_check.get())

        # 1. Stream presence. Ticking one Strip locks the other, so the
        # empty-output combination simply can't be reached; the tab-button
        # marker is what makes that visible from the panel you're not on.
        self.strip_video_check.configure(state="disabled" if stripping_audio else "normal")
        self.strip_audio_check.configure(state="disabled" if stripping_video else "normal")
        self.sub_tab_bar.set_marked("Video", stripping_video)
        self.sub_tab_bar.set_marked("Audio", stripping_audio)

        # 2. Container -> codecs.
        self._retarget(self.encoder_menu, formats.video_codecs_for(container), "Encoder")
        self._retarget(self.audio_codec_menu, formats.audio_codecs_for(container), "Audio codec")
        encoder = self.encoder_menu.get()
        audio_codec = self.audio_codec_menu.get()

        # 3. Video codec -> profile / level / quality.
        profiles = formats.profiles_for(encoder)
        levels = formats.levels_for(encoder)
        self._retarget(self.profile_menu, profiles)
        self._retarget(self.level_menu, levels)
        self._quality_spec = formats.quality_for(encoder)
        self._apply_quality()

        # 4. Audio codec -> bitrate (lossless and copied streams have none).
        bitrates = formats.audio_bitrates_for(audio_codec)
        self._retarget(self.audio_bitrate_menu, bitrates)

        # 5. Enabled states. A stripped stream disables its whole panel; a
        # copied one disables everything that would require re-encoding.
        copying_video = encoder == formats.SOURCE
        copying_audio = audio_codec == formats.SOURCE
        video_live = not stripping_video
        audio_live = not stripping_audio

        self._set_enabled(self.encoder_menu, self.encoder_label, video_live)
        self._set_enabled(self.profile_menu, self.profile_label, video_live and bool(profiles))
        self._set_enabled(self.level_menu, self.level_label, video_live and bool(levels))
        self._set_enabled(self.hdr_switch, self.hdr_label, video_live and not copying_video)
        quality_live = video_live and self._quality_spec is not None
        self._set_enabled(self.crf_slider, self.crf_label, quality_live)
        for label in (self.crf_low_label, self.crf_high_label):
            label.configure(text_color=_DISABLED_LABEL if not quality_live else "gray60")

        self._set_enabled(self.audio_codec_menu, self.audio_codec_label, audio_live)
        self._set_enabled(self.audio_bitrate_menu, self.audio_bitrate_label,
                          audio_live and bool(bitrates))
        self._set_enabled(self.audio_channels_menu, self.audio_channels_label,
                          audio_live and not copying_audio)
        self._set_enabled(self.audio_samplerate_menu, self.audio_samplerate_label,
                          audio_live and not copying_audio)

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

    def _apply_quality(self):
        """Re-ranges the quality slider for the current encoder.

        CRF is not universal — the MPEG-era encoders take a qscale on a
        completely different scale (1-31 vs 0-51/0-63), so the slider's
        bounds and its label both come from `formats.quality_for`. The
        current value is kept when it still falls inside the new range, and
        reset to the codec's own default when it doesn't."""
        spec = self._quality_spec
        if spec is None:
            self.crf_label.configure(text="Quality")
            return

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
        spec = self._quality_spec
        if spec is None:
            self.crf_label.configure(text="Quality")
            return
        self.crf_label.configure(text=f"{spec['label']}: {int(round(self.crf_slider.get()))}")

    def _on_quality_change(self, _value=None):
        """Slider callback — the value feeds nothing else, so this refreshes
        the readout and the rundown rather than running a whole sync pass."""
        self._update_quality_label()
        self._refresh_summary()

    def _refresh_summary(self):
        """Rebuilds the Overview rundown — the one view where the container,
        both streams and the trim are visible at the same time."""
        container = self.format_menu.get()
        info = self.app.media_info
        source_container = info.get("container")

        # Text here is kept terse on purpose — the rundown shares its row
        # with the controls, so it has maybe 260px to say everything in.
        container_text = container
        if source_container and source_container != container:
            container_text = f"{container} ← {source_container}"

        # Video
        if self.strip_video_check.get():
            video = ("— removed —", STOP_RED)
        elif self.encoder_menu.get() == formats.SOURCE:
            actual = formats.short_name(info.get("video"))
            video = ("copy" + (f" · {actual}" if actual else ""), None)
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

        # Audio
        if self.strip_audio_check.get():
            audio = ("— removed —", STOP_RED)
        elif self.audio_codec_menu.get() == formats.SOURCE:
            actual = formats.short_name(info.get("audio"))
            audio = ("copy" + (f" · {actual}" if actual else ""), None)
        else:
            bits = [self.audio_codec_menu.get()]
            if formats.audio_bitrates_for(self.audio_codec_menu.get()):
                bits.append(self.audio_bitrate_menu.get())
            for menu in (self.audio_channels_menu, self.audio_samplerate_menu):
                if menu.get() != formats.SOURCE:
                    bits.append(menu.get().replace(" Hz", ""))
            audio = (" · ".join(bits), None)

        # Trim
        start = self.start_time_spinner.get_total_seconds()
        duration = self.duration_time_spinner.get_total_seconds()
        if not start and not duration:
            trim = ("whole file", None)
        elif not duration:
            trim = (f"{_hms(start)} → end", None)
        else:
            trim = (f"{_hms(start)} → {_hms(start + duration)}", None)

        self.summary.set_values([(container_text, None), video, audio, trim])

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
            filetypes=[("Video Files", "*.mp4 *.mkv *.avi *.mov *.webm"), ("All Files", "*.*")],
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

    def on_media_info(self, info):
        """A probe of the selected file landed (see LlamaGUI._decode_worker).

        Adopts the source's own container as the output default, which is
        what makes the untouched form a true passthrough — but only while the
        user hasn't picked a container themselves (`_auto_format`), so a new
        file drop never overrides a deliberate choice."""
        container = info.get("container")
        if container and self._auto_format is not None and container in formats.containers():
            self.format_menu.set(container)
            self._auto_format = container
            self._autofill_output_path()
        self._sync_controls()

    def _autofill_output_path(self):
        """Suggests '<default folder>/<input basename>_encoded<format>' in the
        output field — but only while the user hasn't set their own path
        (`self._auto_output` holds the last value we filled; None once the
        user picks via Browse)."""
        current = self.save_entry.get().strip()
        if current and current != self._auto_output:
            return
        input_file = self.app.current_file_path
        if not input_file:
            return
        base = os.path.splitext(os.path.basename(input_file.replace("\\", "/")))[0]
        suggested = os.path.normpath(
            os.path.join(self.app.default_save_location or "", f"{base}_encoded{self.format_menu.get()}")
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
        preference, not a control of ours."""
        return {
            "input_file": self.app.current_file_path,
            "output_path": self.save_entry.get(),
            "output_format": self.format_menu.get(),
            "start_secs": self.start_time_spinner.get_total_seconds(),
            "duration_secs": self.duration_time_spinner.get_total_seconds(),
            "encoder": self.encoder_menu.get(),
            "profile": self._menu_value(self.profile_menu),
            "level": self._menu_value(self.level_menu),
            "quality": int(round(self.crf_slider.get())),
            "gpu_enabled": bool(self.app.gpu_enabled),
            "hdr_to_sdr": bool(self.hdr_switch.get()),
            "strip_video": bool(self.strip_video_check.get()),
            "audio_codec": self.audio_codec_menu.get(),
            "audio_bitrate": self._menu_value(self.audio_bitrate_menu),
            "audio_channels": self.audio_channels_menu.get(),
            "audio_sample_rate": self.audio_samplerate_menu.get(),
            "strip_audio": bool(self.strip_audio_check.get()),
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
            self._set_menu(self.encoder_menu, settings.get("encoder"))
            self._set_menu(self.audio_codec_menu, settings.get("audio_codec"))
            self._sync_controls()

            # Tier 3 — the leaves.
            self._set_menu(self.profile_menu, settings.get("profile"))
            self._set_menu(self.level_menu, settings.get("level"))
            self._set_menu(self.audio_bitrate_menu, settings.get("audio_bitrate"))
            self._set_menu(self.audio_channels_menu, settings.get("audio_channels"))
            self._set_menu(self.audio_samplerate_menu, settings.get("audio_sample_rate"))
            if "hdr_to_sdr" in settings:
                self._set_check(self.hdr_switch, settings["hdr_to_sdr"])
            if settings.get("quality") is not None:
                self.crf_slider.set(settings["quality"])
        finally:
            self._ready = was_ready
        self._sync_controls()

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
        container/codec pairings unrepresentable in the first place."""
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
        return True

    # ------------------------------------------------------------------ #
    #  Queue hand-off
    # ------------------------------------------------------------------ #
    def encode_now(self):
        settings = self._gather_settings()
        if not self._validate_settings(settings):
            return

        filename = settings["input_file"].split("/")[-1]
        description = f"{filename}  ·  Direct Encode"

        queue_tab = self.app.tabs.get("Queue")
        if queue_tab:
            task_id = queue_tab.add_task(description, settings=settings, status="Queued", source_tab="Encoding")
            queue_tab.start_task(task_id)
            self.app.notify("Encoding job has begun.")
        else:
            print(f"Queue tab unavailable — would have encoded now: {settings}")

    def add_to_queue(self):
        settings = self._gather_settings()
        if not self._validate_settings(settings):
            return

        filename = settings["input_file"].split("/")[-1]
        description = f"{filename}  ·  {settings['duration_secs']}s from {settings['start_secs']}s"

        queue_tab = self.app.tabs.get("Queue")
        if queue_tab:
            queue_tab.add_task(description, settings=settings, status="Queued", source_tab="Encoding")
            self.app.notify("Encoding job added to queue.")
        else:
            print(f"Queue tab unavailable — would have queued: {settings}")
