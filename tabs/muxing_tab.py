import os
import customtkinter as ctk
from tkinter import filedialog

from components.dialogs import ask_text, ask_yes_no, show_message
from components.drop_box import DropBox
from components.dropdown import ThemedDropdown
from components.sub_tab_bar import SubTabBar
from components.summary_panel import SummaryPanel
from components.thumbnail_carousel import ThumbnailCarousel
from components.time_spinner import TimeSpinner
from core import formats, presets
from core.theme import get_active_theme, readable_text_on, STOP_RED, STOP_RED_HOVER

_DISABLED_LABEL = "gray50"

# Track choices offered for each stream. There's no "None" entry — removing a
# stream is the Strip checkbox's job, and having two controls that both mean
# "no video" is exactly the kind of duplicate state this tab is built to avoid.
_STREAM_TRACKS = ["Auto", "Track 1", "Track 2", "Track 3"]

# Prefix for a track pulled in from a second file via the panel's Browse
# button; the full path is kept alongside in _video_ext_file/_audio_ext_file.
_EXTERNAL_PREFIX = "External: "

_TAB = "Muxing"


def _hms(total_seconds):
    """Seconds as HH:MM:SS, for the Overview rundown's trim line."""
    total_seconds = int(total_seconds or 0)
    hours, rest = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class MuxingTab(ctk.CTkFrame):
    """Remuxing: change a file's container and/or choose which streams go
    into it. **Nothing here ever re-encodes** — every stream is copied, which
    is what separates this tab from Encoding rather than making it a weaker
    version of it.

    Two consequences fall out of copy-only:
      * There are no codec controls at all. "Copy video, re-encode audio"
        isn't a Muxing job; it's an Encoding job with the video codec left on
        `Source`.
      * The container filter runs **backwards** compared to Encoding. Rather
        than the container deciding which codecs are legal, the source's
        *existing* codecs decide which containers it can be remuxed into
        (`formats.containers_for`) — an H.264 file can't become a .webm
        without re-encoding, so .webm isn't offered.

    Trim is keyframe-limited here for the same reason: a copied stream can
    only be cut on a keyframe. The Overview rundown says so rather than
    letting it be a silent surprise."""

    def __init__(self, master, app):
        super().__init__(master=master)
        self.app = app
        theme = get_active_theme()
        self._label_color = ctk.ThemeManager.theme["CTkLabel"]["text_color"]
        self._ready = False
        self._auto_format = formats.containers()[0]
        # Extra input files pulled in per stream via the panels' Browse
        # buttons — one per stream, kept as a path alongside the display name
        # that appears in the track dropdown.
        self._video_ext_file = None
        self._audio_ext_file = None

        # --- Bottom Section: Fixed Controls ---
        self.controls_frame = ctk.CTkFrame(master=self, fg_color="transparent")
        self.controls_frame.pack(side="bottom", fill="x", padx=10, pady=(0, 4))

        # Options row — one two-column block; each sub-tab owns both columns.
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

        # Save Location Section
        self.save_frame = ctk.CTkFrame(master=self.controls_frame, fg_color="transparent")
        self.save_frame.pack(fill="x", pady=4)

        self.save_entry = ctk.CTkEntry(master=self.save_frame, placeholder_text="Save file as...")
        self.save_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self._auto_output = ""
        if self.app.default_save_location:
            self.save_entry.insert(0, self.app.default_save_location)
            self._auto_output = self.app.default_save_location

        self.browse_save_btn = ctk.CTkButton(
            master=self.save_frame, text="Browse", width=80, command=self.select_save_location
        )
        self.browse_save_btn.pack(side="right")

        # Action Buttons Row: Queue Task (secondary) + Mux (primary)
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

        self.mux_btn = ctk.CTkButton(
            master=self.action_frame,
            text="Mux",
            fg_color=theme["primary"],
            text_color=theme["primary_text"],
            hover_color=theme["primary_hover"],
            command=self.mux_now,
        )
        self.mux_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        # --- Top Flexible Section ---
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
            on_index=self.app.sync_preview_index,
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
        """Overview: output container + the one global trim, preset
        management, and the export rundown."""
        left = ctk.CTkFrame(master=left_parent, fg_color="transparent")
        right = ctk.CTkFrame(master=right_parent, fg_color="transparent")

        # Row 1: container + presets. They share a row (rather than Format
        # sitting beside the spinners) to keep `left` narrow — the rundown on
        # the right needs real width and the spinners are the widest things
        # on this panel.
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

        # Row 2: the one global trim.
        self.trim_row = ctk.CTkFrame(master=left, fg_color="transparent")
        self.trim_row.pack(anchor="w", pady=(6, 0))

        self.start_frame = ctk.CTkFrame(master=self.trim_row, fg_color="transparent")
        self.start_frame.pack(side="left", anchor="s")
        self.start_label = ctk.CTkLabel(master=self.start_frame, text="Start Time:", font=("Arial", 11, "bold"))
        self.start_label.pack(anchor="w", pady=(0, 1))
        self.start_time_spinner = TimeSpinner(master=self.start_frame, initial_seconds=0)
        self.start_time_spinner.pack(anchor="w")

        self.duration_frame = ctk.CTkFrame(master=self.trim_row, fg_color="transparent")
        self.duration_frame.pack(side="left", anchor="s", padx=(14, 0))
        self.duration_label = ctk.CTkLabel(master=self.duration_frame, text="Clip Duration:", font=("Arial", 11, "bold"))
        self.duration_label.pack(anchor="w", pady=(0, 1))
        self.duration_time_spinner = TimeSpinner(master=self.duration_frame, initial_seconds=0)
        self.duration_time_spinner.pack(anchor="w")

        self.summary = SummaryPanel(master=right, labels=["Container", "Video", "Audio", "Trim"])
        self.summary.pack(fill="x", anchor="s")

        return left, right

    def _build_video_panel(self, left_parent, right_parent):
        """Video: which source video track to carry over (or one browsed in
        from another file), and Strip Video."""
        left = ctk.CTkFrame(master=left_parent, fg_color="transparent")
        right = ctk.CTkFrame(master=right_parent, fg_color="transparent")

        self.video_row = ctk.CTkFrame(master=left, fg_color="transparent")
        self.video_row.pack(anchor="w")

        self.video_track_label, self.video_track_menu = self._panel_dropdown(
            self.video_row, "Video Track:", _STREAM_TRACKS, 150,
            default="Auto", command=self._on_control_change,
        )

        self.video_browse_btn = ctk.CTkButton(
            master=self.video_row, text="Browse…", width=76, height=28,
            command=lambda: self._browse_external("video"),
        )
        self.video_browse_btn.pack(side="left", anchor="s", padx=(8, 0))

        self.strip_video_check = ctk.CTkCheckBox(
            master=right,
            text="Strip Video",
            fg_color=STOP_RED,
            hover_color=STOP_RED_HOVER,
            checkmark_color=readable_text_on(STOP_RED),
            command=self._on_control_change,
        )
        self.strip_video_check.pack(anchor="e", pady=(0, 4))

        return left, right

    def _build_audio_panel(self, left_parent, right_parent):
        """Audio: which source audio track to carry over (or one browsed in
        from another file), and Strip Audio."""
        left = ctk.CTkFrame(master=left_parent, fg_color="transparent")
        right = ctk.CTkFrame(master=right_parent, fg_color="transparent")

        self.audio_row = ctk.CTkFrame(master=left, fg_color="transparent")
        self.audio_row.pack(anchor="w")

        self.audio_track_label, self.audio_track_menu = self._panel_dropdown(
            self.audio_row, "Audio Track:", _STREAM_TRACKS, 150,
            default="Auto", command=self._on_control_change,
        )

        self.audio_browse_btn = ctk.CTkButton(
            master=self.audio_row, text="Browse…", width=76, height=28,
            command=lambda: self._browse_external("audio"),
        )
        self.audio_browse_btn.pack(side="left", anchor="s", padx=(8, 0))

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
        into `parent`. Returns `(label, menu)`."""
        frame = ctk.CTkFrame(master=parent, fg_color="transparent")
        frame.pack(side="left", anchor="s", padx=padx)

        label = ctk.CTkLabel(master=frame, text=label_text, font=("Arial", 11, "bold"))
        label.pack(anchor="w", pady=(0, 1))

        menu = ThemedDropdown(master=frame, values=values, width=width, command=command)
        if default is not None:
            menu.set(default)
        menu.pack(anchor="w")
        return label, menu

    def _pin_options_height(self):
        """Locks `options_row` to the tallest sub-tab's natural height so the
        DropBox / preview above doesn't resize on a sub-tab switch. Measured
        rather than hardcoded so it can't drift out of step."""
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
        """Swaps the visible sub-tab. `options_row` is height-pinned, so the
        shorter panels get slack below the preview rather than resizing it."""
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
    #  External stream inputs
    # ------------------------------------------------------------------ #
    def _browse_external(self, kind):
        """Pulls a stream in from a second file. The chosen path is stored
        (`_video_ext_file` / `_audio_ext_file`) and appears in that panel's
        track dropdown as `External: <name>`, which `_sync_controls` keeps in
        the option list and `_gather_settings` reports alongside the track."""
        if kind == "video":
            title, types = "Select Video Source", [("Video Files", "*.mp4 *.mkv *.avi *.mov *.webm")]
        else:
            title, types = "Select Audio Source", [
                ("Audio / Video Files", "*.mp3 *.aac *.ac3 *.flac *.opus *.wav *.m4a *.mp4 *.mkv *.mov")
            ]
        path = filedialog.askopenfilename(title=title, filetypes=types + [("All Files", "*.*")])
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
        """The track list for one stream: the source file's own tracks, plus
        an `External:` entry once one has been browsed in."""
        values = list(_STREAM_TRACKS)
        if external_path:
            values.append(_EXTERNAL_PREFIX + os.path.basename(external_path.replace("\\", "/")))
        return values

    def _external_for(self, menu, path):
        """The external path backing `menu`'s current selection, or "" when
        an ordinary track of the primary input is selected."""
        return path if path and menu.get().startswith(_EXTERNAL_PREFIX) else ""

    # ------------------------------------------------------------------ #
    #  The single constraint pass
    # ------------------------------------------------------------------ #
    def _on_control_change(self, *_):
        """Every control's `command` lands here — one recompute, no pairwise
        handlers."""
        self._sync_controls()

    def _sync_controls(self, *_):
        """**The only place derived UI state is decided.** Idempotent: reads
        the whole form and rewrites every dependent widget from scratch, so
        call order never matters and no two rules can fight.

        The rules here:
          1. stream presence — both stripped would write an empty file
          2. track lists carry whatever external file has been browsed in
          3. **the container inversion** — since nothing is re-encoded, the
             source's own codecs decide which containers are reachable
          4. a stripped stream disables its own panel's controls
          5. the Overview rundown
        """
        stripping_video = bool(self.strip_video_check.get())
        stripping_audio = bool(self.strip_audio_check.get())

        # 1. Stream presence.
        self.strip_video_check.configure(state="disabled" if stripping_audio else "normal")
        self.strip_audio_check.configure(state="disabled" if stripping_video else "normal")
        self.sub_tab_bar.set_marked("Video", stripping_video)
        self.sub_tab_bar.set_marked("Audio", stripping_audio)

        # 2. Track lists (+ any browsed-in external entry).
        self.video_track_menu.set_values(self._track_values(self._video_ext_file))
        self.audio_track_menu.set_values(self._track_values(self._audio_ext_file))

        # 3. Container inversion. A stripped stream constrains nothing, and
        # neither does an unprobed one — so an unknown file still offers
        # every container rather than being narrowed on a guess.
        info = self.app.media_info
        video_codec = None if stripping_video else info.get("video")
        audio_codec = None if stripping_audio else info.get("audio")
        allowed = formats.containers_for(video_codec, audio_codec)
        self._retarget_container(allowed)

        # 4. Enabled states.
        video_live = not stripping_video
        audio_live = not stripping_audio
        self._set_enabled(self.video_track_menu, self.video_track_label, video_live)
        self.video_browse_btn.configure(state="normal" if video_live else "disabled")
        self._set_enabled(self.audio_track_menu, self.audio_track_label, audio_live)
        self.audio_browse_btn.configure(state="normal" if audio_live else "disabled")

        # 5. The rundown.
        self._refresh_summary()

    def _retarget_container(self, allowed):
        """Narrows the container list to what this source can be remuxed
        into, announcing a forced switch rather than silently changing the
        user's pick."""
        before = self.format_menu.get()
        self.format_menu.set_values(allowed)
        after = self.format_menu.get()
        if self._ready and before != after:
            self.app.notify(
                f"Container switched to {after} — {before} can't hold this file's streams "
                "without re-encoding.",
                go_to_queue=False,
            )

    def _set_enabled(self, widget, label, enabled):
        """Enables/disables a control and dims its label to match."""
        widget.configure(state="normal" if enabled else "disabled")
        if label is not None:
            label.configure(text_color=self._label_color if enabled else _DISABLED_LABEL)

    def _refresh_summary(self):
        """Rebuilds the Overview rundown, including the keyframe caveat that
        copy-only trimming carries."""
        container = self.format_menu.get()
        info = self.app.media_info
        source_container = info.get("container")

        container_text = container
        if source_container and source_container != container:
            container_text = f"{container} ← {source_container}"

        if self.strip_video_check.get():
            video = ("— removed —", STOP_RED)
        else:
            bits = ["copy"]
            actual = formats.short_name(info.get("video"))
            if actual:
                bits.append(actual)
            bits.append(self.video_track_menu.get())
            video = (" · ".join(bits), None)

        if self.strip_audio_check.get():
            audio = ("— removed —", STOP_RED)
        else:
            bits = ["copy"]
            actual = formats.short_name(info.get("audio"))
            if actual:
                bits.append(actual)
            bits.append(self.audio_track_menu.get())
            audio = (" · ".join(bits), None)

        # The keyframe caveat is stated here rather than left as a surprise:
        # a copied stream can only be cut on a keyframe, and this tab never
        # re-encodes, so there's no "precise cut" escape hatch to offer.
        start = self.start_time_spinner.get_total_seconds()
        duration = self.duration_time_spinner.get_total_seconds()
        if not start and not duration:
            trim = ("whole file", None)
        elif not duration:
            trim = (f"{_hms(start)} → end · keyframe", None)
        else:
            trim = (f"{_hms(start)} → {_hms(start + duration)} · keyframe", None)

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
        """Applies a saved recipe — container and strip flags only. Track
        picks and the trim are per-file, so they're never carried."""
        if name == presets.NONE_LABEL:
            return
        stored = presets.get(_TAB, name)
        if stored is None:
            self._refresh_preset_menu(select=presets.NONE_LABEL)
            return
        self._apply_settings(stored)
        self.app.notify(f"Preset '{name}' applied.", go_to_queue=False)

    def _on_preset_save(self):
        """Names and saves the current recipe settings."""
        current = self.preset_menu.get()
        initial = "" if current == presets.NONE_LABEL else current
        name = ask_text(
            self.app, "Save Preset",
            "Name this preset. It stores the container and the strip flags — "
            "not the trim, the track picks, or the file paths.",
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
        preview carousel."""
        self.drop_box.pack_forget()
        if not self.carousel.winfo_ismapped():
            self.carousel.pack(pady=(2, 2), fill="both", expand=True)

    def on_media_info(self, info):
        """A probe of the selected file landed. Adopts the source's own
        container as the output default (while the user hasn't picked one),
        then re-runs the cascade — which is also what narrows the container
        list to what this file can actually be remuxed into."""
        container = info.get("container")
        if container and self._auto_format is not None and container in formats.containers():
            self.format_menu.set(container)
            self._auto_format = container
            self._autofill_output_path()
        self._sync_controls()

    def _autofill_output_path(self):
        """Suggests '<default folder>/<input basename>_muxed<format>' in the
        output field, while the user hasn't set their own path."""
        current = self.save_entry.get().strip()
        if current and current != self._auto_output:
            return
        input_file = self.app.current_file_path
        if not input_file:
            return
        base = os.path.splitext(os.path.basename(input_file.replace("\\", "/")))[0]
        suggested = os.path.normpath(
            os.path.join(self.app.default_save_location or "", f"{base}_muxed{self.format_menu.get()}")
        )
        self.save_entry.delete(0, "end")
        self.save_entry.insert(0, suggested)
        self._auto_output = suggested

    def _on_format_change(self, _value=None):
        """The user picked a container themselves: stop auto-adopting the
        source's, swap the output path's extension, and re-sync."""
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
        fmt = self.format_menu.get()

        if input_file:
            input_name = input_file.split("/")[-1]
            base_name = input_name.rsplit(".", 1)[0] if "." in input_name else input_name
            initial_dir = "/".join(input_file.replace("\\", "/").split("/")[:-1])
            default_name = f"{base_name}_muxed{fmt}"
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
            self._auto_output = None

    # ------------------------------------------------------------------ #
    #  Settings in / out
    # ------------------------------------------------------------------ #
    def _gather_settings(self):
        """Collects the current Muxing state into a plain dict. There are no
        codec keys at all — this tab never re-encodes."""
        return {
            "input_file": self.app.current_file_path,
            "output_path": self.save_entry.get(),
            "output_format": self.format_menu.get(),
            "start_secs": self.start_time_spinner.get_total_seconds(),
            "duration_secs": self.duration_time_spinner.get_total_seconds(),
            "video_track": self.video_track_menu.get(),
            "video_track_file": self._external_for(self.video_track_menu, self._video_ext_file),
            "strip_video": bool(self.strip_video_check.get()),
            "audio_track": self.audio_track_menu.get(),
            "audio_track_file": self._external_for(self.audio_track_menu, self._audio_ext_file),
            "strip_audio": bool(self.strip_audio_check.get()),
        }

    def _apply_settings(self, settings):
        """Writes a settings dict into the form. A key that's absent leaves
        its control alone, which is how a preset (recipe keys only) shares
        this path with a full restore. Snap-toasts are muted throughout."""
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

            if "strip_video" in settings:
                self._set_check(self.strip_video_check, settings["strip_video"])
            if "strip_audio" in settings:
                self._set_check(self.strip_audio_check, settings["strip_audio"])

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

    def load_settings(self, settings):
        """Restores a full settings dict into the UI (used by the live theme
        rebuild)."""
        self._apply_settings(settings)

    @staticmethod
    def _set_menu(menu, value):
        """Selects `value` only if it's one of the menu's current options."""
        if value is not None and value in menu.cget("values"):
            menu.set(value)

    @staticmethod
    def _set_check(widget, on):
        """select()/deselect() from a truthy value."""
        widget.select() if on else widget.deselect()

    def _validate_settings(self, settings):
        """Checks the minimum required fields before queueing/muxing."""
        if not settings["input_file"]:
            show_message(
                self.app, "No File Selected",
                "Add a video file before queueing or muxing — drag one onto "
                "the drop box, or double-click it to browse.",
            )
            return False
        if not settings["output_path"]:
            show_message(
                self.app, "No Save Location",
                "Choose where the muxed file should be saved before "
                "continuing. Use Browse, or set a default save location on the "
                "Settings tab.",
            )
            return False
        return True

    # ------------------------------------------------------------------ #
    #  Queue hand-off
    # ------------------------------------------------------------------ #
    def mux_now(self):
        settings = self._gather_settings()
        if not self._validate_settings(settings):
            return

        filename = settings["input_file"].split("/")[-1]
        description = f"{filename}  ·  Direct Mux"

        queue_tab = self.app.tabs.get("Queue")
        if queue_tab:
            task_id = queue_tab.add_task(description, settings=settings, status="Queued", source_tab="Muxing")
            queue_tab.start_task(task_id)
            self.app.notify("Muxing job has begun.")
        else:
            print(f"Queue tab unavailable — would have muxed now: {settings}")

    def add_to_queue(self):
        settings = self._gather_settings()
        if not self._validate_settings(settings):
            return

        filename = settings["input_file"].split("/")[-1]
        description = f"{filename}  ·  {settings['duration_secs']}s from {settings['start_secs']}s"

        queue_tab = self.app.tabs.get("Queue")
        if queue_tab:
            queue_tab.add_task(description, settings=settings, status="Queued", source_tab="Muxing")
            self.app.notify("Muxing job added to queue.")
        else:
            print(f"Queue tab unavailable — would have queued: {settings}")
