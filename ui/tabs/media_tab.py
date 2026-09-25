# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""The shared Muxing/Encoding frame.

The header, preview area, sub-tab panels, save row, action buttons, presets,
output-path logic and queue hand-off live here once; each tab supplies its
own panels and its own `_sync_controls` (the two rulesets genuinely differ —
Encoding cascades container → codec, Muxing inverts it).

The three sub-tab panels sit in a `QStackedWidget`, which sizes itself to the
tallest page — so the preview above never changes height on a switch."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QStackedLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core import formats, naming, presets
from ui import scale
from ui.widgets.carousel import ThumbnailCarousel, _ExpandedPreviewOverlay
from ui.widgets.controls import (
    NO_OPTION,
    CheckBox,
    Dropdown,
    MarqueeLabel,
    ScaledLineEdit,
    TimeSpinner,
    button,
    button_width_for,
    labeled,
    set_enabled,
)
from ui.widgets.dialogs import ask_text, ask_yes_no, confirm_output_path, show_message
from ui.widgets.panels import MEDIA_FILTER, DropBox, SubTabBar, SummaryPanel
from ui.widgets.tooltip import tip
from ui.tips import CONTAINER_TIPS

SUBTABS = ("Overview", "Video", "Audio")

AV_SYNC_TIP = ("Holds a constant frame rate and keeps timestamps aligned — turn off only "
               "if you need the source's exact original timing.")
STRIP_TIP = "Removes this stream entirely from the output — the other panel's stream is unaffected."
PRESET_TIP = "Presets remember the container and codec/quality choices — never the trim, file paths, or track picks."


def hrow(spacing=0, align_bottom=True):
    """A plain horizontal row widget + its layout."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    scale.spacing(lay, spacing)
    if align_bottom:
        lay.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
    return w, lay


def hms(total_seconds):
    """Seconds as HH:MM:SS."""
    total_seconds = int(total_seconds or 0)
    hours, rest = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def set_line_text(entry, text):
    """Replace a line edit's text and show its start (paths are long)."""
    entry.setText(text or "")
    entry.setCursorPosition(0)


class MediaTab(QWidget):
    """Base for Muxing and Encoding. Subclasses set the class constants and
    implement `build_video`, `build_audio`, `_sync_controls`,
    `_refresh_summary`, `_gather_settings`, `_apply_settings` and
    `_validate_specific`."""

    TAB = ""
    ACTION_TEXT = ""
    OUTPUT_SUFFIX = ""
    VERB_ING = ""        # "Muxing" / "Encoding" — toast wording
    DIRECT_LABEL = ""    # "Direct Mux" / "Direct Encode"
    PRESET_NOTE = ""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self._ready = False
        self._init_state()
        # The container we defaulted for the user — None the moment they pick
        # one, so a new file drop never overrides a deliberate choice.
        self._auto_format = formats.containers()[0]
        self._auto_output = app.default_save_location or ""

        root = QVBoxLayout(self)
        scale.margins(root, 10, 5, 10, 4)
        root.setSpacing(0)

        # --- Header: sub-tab switch + the selected file.
        header, hl = hrow(spacing=10, align_bottom=False)
        self.sub_tab_bar = SubTabBar(SUBTABS)
        hl.addWidget(self.sub_tab_bar, 0, Qt.AlignBottom)
        self.file_label = MarqueeLabel("", pixel_size=11)
        self.file_label.doubleClicked.connect(self.select_input_file)
        hl.addWidget(self.file_label, 1, Qt.AlignVCenter)
        root.addWidget(header)
        scale.spacer(root, 15)

        # --- Preview: the DropBox until the first frames land, then the
        # carousel in its place.
        preview = QWidget()
        self._preview_stack = QStackedLayout(preview)
        self.drop_box = DropBox(start_dir=self._output_directory)
        self.drop_box.fileSelected.connect(app.update_global_file)
        self.carousel = ThumbnailCarousel(host=self)
        self.carousel.reselect.connect(self.select_input_file)
        self.carousel.populated.connect(self._reveal_preview)
        self.carousel.indexChanged.connect(app.sync_preview_index)
        self.carousel.fileDropped.connect(app.update_global_file)
        self.carousel.expandToggled.connect(self._on_expand_toggled)
        self._expand_overlay = None
        self._preview_stack.addWidget(self.drop_box)
        self._preview_stack.addWidget(self.carousel)
        root.addWidget(preview, 1)
        scale.spacer(root, 18)

        # --- Sub-tab panels.
        self.panels = QStackedWidget()
        self.panels.addWidget(self._build_overview())
        self.panels.addWidget(self.build_video())
        self.panels.addWidget(self.build_audio())
        self.sub_tab_bar.changed.connect(lambda n: self.panels.setCurrentIndex(SUBTABS.index(n)))
        root.addWidget(self.panels)
        scale.spacer(root, 11)

        # --- Save row.
        save, sl = hrow(spacing=6, align_bottom=False)
        self.save_entry = ScaledLineEdit()
        self.save_entry.setPlaceholderText("Save file as...")
        scale.fixed(self.save_entry, h=28)
        set_line_text(self.save_entry, app.default_save_location)
        sl.addWidget(self.save_entry, 1)
        self.browse_save_btn = button("Browse", width=80)
        self.browse_save_btn.clicked.connect(self.select_save_location)
        sl.addWidget(self.browse_save_btn)
        root.addWidget(save)
        scale.spacer(root, 10)

        # --- Queue Task (secondary) + the do-it-now button (primary) — by role, so a
        # theme can swap the two (Terminal does).
        actions, al = hrow(spacing=8, align_bottom=False)
        self.queue_btn = button("Queue Task", role="queue")
        self.queue_btn.clicked.connect(self.add_to_queue)
        self.go_btn = button(self.ACTION_TEXT, role="action")
        self.go_btn.clicked.connect(self.run_now)
        al.addWidget(self.queue_btn, 1)
        al.addWidget(self.go_btn, 1)
        root.addWidget(actions)

        app.register_media_tab(self)
        self._sync_controls()
        self._ready = True

    def _init_state(self):
        """Per-instance state a subclass needs before its panels are built."""

    # ------------------------------------------------------------------ #
    #  Overview panel (shared)
    # ------------------------------------------------------------------ #
    def _build_overview(self):
        """Output Format + presets on one row, the one global trim + A/V Sync
        below, the export rundown on the right."""
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        scale.spacing(outer, 20)

        left = QVBoxLayout()
        scale.spacing(left, 6)
        left.addStretch(1)
        row1, r1 = hrow(spacing=8)
        self.format_menu = Dropdown(formats.containers(), width=92)
        self.format_menu.picked.connect(self._on_format_change)
        self._update_format_tip()
        box, self.format_label = labeled("Output Format:", self.format_menu)
        r1.addWidget(box)
        scale.spacer(r1, 6)
        self.preset_menu = Dropdown(presets.menu_values(self.TAB), width=132)
        self.preset_menu.set(presets.NONE_LABEL)
        self.preset_menu.picked.connect(self._on_preset_selected)
        box, self.preset_label = labeled("Preset:", self.preset_menu)
        r1.addWidget(box)
        preset_btn_width = button_width_for(["Save", "Delete"])
        self.preset_save_btn = button("Save", width=preset_btn_width)
        self.preset_save_btn.clicked.connect(self._on_preset_save)
        self.preset_delete_btn = button("Delete", width=preset_btn_width)
        self.preset_delete_btn.clicked.connect(self._on_preset_delete)
        tip(self.preset_save_btn, PRESET_TIP)
        tip(self.preset_delete_btn, PRESET_TIP)
        r1.addWidget(self.preset_save_btn, 0, Qt.AlignBottom)
        r1.addWidget(self.preset_delete_btn, 0, Qt.AlignBottom)
        left.addWidget(row1)

        # There is no "Retain Video Length" checkbox: Duration 00:00:00
        # already means "to the end of the file" — greyed out like a
        # placeholder while it's still 0, for exactly that reason, and back
        # to normal the moment it's incremented off it. Start Time is the same:
        # 00:00:00 there means "from the beginning", so it reads as not set until
        # the user spins it.
        row2, r2 = hrow(spacing=14)
        self.start_time_spinner = TimeSpinner(mute_when_zero=True)
        self.duration_time_spinner = TimeSpinner(mute_when_zero=True)
        for spinner in (self.start_time_spinner, self.duration_time_spinner):
            spinner.valueChanged.connect(self._on_trim_change)
        box, self.start_label = labeled("Start Time:", self.start_time_spinner)
        r2.addWidget(box)
        box, self.duration_label = labeled("Clip Duration:", self.duration_time_spinner)
        r2.addWidget(box)
        scale.spacer(r2, 2)
        self.av_sync_check = CheckBox("A/V Sync", checked=True)
        self.av_sync_check.clicked.connect(self._on_control_change)
        tip(self.av_sync_check, AV_SYNC_TIP)
        r2.addWidget(self.av_sync_check, 0, Qt.AlignBottom)
        left.addWidget(row2)
        outer.addLayout(left)

        right = QVBoxLayout()
        right.addStretch(1)
        self.summary = SummaryPanel(["Video", "Audio", "Length"])
        right.addWidget(self.summary)
        scale.spacer(right, 4)
        outer.addLayout(right, 1)
        return page

    @staticmethod
    def stream_page():
        """An empty sub-tab page: `(page, left_layout, right_layout)`, the
        left bottom-anchored."""
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        scale.spacing(outer, 20)
        left = QVBoxLayout()
        scale.spacing(left, 6)
        left.addStretch(1)
        outer.addLayout(left)
        outer.addStretch(1)
        right = QVBoxLayout()
        outer.addLayout(right)
        return page, left, right

    # ------------------------------------------------------------------ #
    #  Change handlers
    # ------------------------------------------------------------------ #
    def _on_control_change(self, *_):
        """Every control lands here — one recompute, no pairwise handlers."""
        self._sync_controls()

    def _on_trim_change(self, *_):
        """A trim spinner changed — refresh just the rundown."""
        if self._ready:
            self._refresh_summary()

    def _update_format_tip(self):
        """The container dropdown's hover tip — called on every value change,
        wherever it comes from (a user pick, `_apply_settings`, or a
        subclass's `_sync_controls` auto-adopting the source's own)."""
        tip(self.format_menu, CONTAINER_TIPS.get(self.format_menu.value(), ""))

    def _on_format_change(self, _value=None):
        """The user picked a container: stop auto-adopting the source's,
        swap the output path's extension, and re-sync."""
        self._update_format_tip()
        self._auto_format = None
        current = self.save_entry.text().strip()
        stem, extension = os.path.splitext(current)
        if extension:
            updated = stem + self.format_menu.value()
            set_line_text(self.save_entry, updated)
            if self._auto_output is not None:
                self._auto_output = updated
        self._sync_controls()

    # ------------------------------------------------------------------ #
    #  Import gate
    # ------------------------------------------------------------------ #
    def _apply_import_gate(self, extra=()):
        """With no file imported, every Overview/Video/Audio dropdown reads
        '—' and disables — Output Format and Preset here, plus whatever
        tab-specific dropdowns `extra` names (`(menu, label)` pairs) —
        rather than showing a default or stale value nothing has actually
        confirmed yet. Call this last, at the end of `_sync_controls`. Start
        Time, Clip Duration, A/V Sync, the preset Save/Delete buttons and the
        Queue Task / Mux / Encode action buttons disable with them (their
        values are left alone).

        Output Format and Preset get their enabled state set *both ways*,
        unconditionally — unlike every `extra` dropdown, nothing else in
        either tab ever calls `set_enabled` on them, so once this method
        had disabled them there was nothing to turn them back on again: a
        file import left them stuck disabled forever (confirmed: Output
        Format/Preset stayed greyed with a real file imported and a real
        container value already showing). `extra` dropdowns don't need
        that — each one's own enabled state is already recomputed fresh,
        every pass, by the rest of `_sync_controls` regardless of file
        presence, so with a file imported this leaves them, and their
        values, exactly as that earlier logic already derived them."""
        has_file = bool(self.app.current_file_path)
        set_enabled(self.format_menu, self.format_label, has_file)
        set_enabled(self.preset_menu, self.preset_label, has_file)
        # The rest of the Overview page too — a trim, A/V Sync, or a preset
        # Save/Delete means nothing without a file to apply it to. Set both
        # ways for the same reason as Output Format/Preset above: nothing
        # else ever re-enables them.
        set_enabled(self.start_time_spinner, self.start_label, has_file)
        set_enabled(self.duration_time_spinner, self.duration_label, has_file)
        self.av_sync_check.setEnabled(has_file)
        self.preset_save_btn.setEnabled(has_file)
        self.preset_delete_btn.setEnabled(has_file)
        # Queue Task / Mux / Encode have nothing to run without a file — greyed like
        # the Downloader's until a fetch succeeds (same both-ways rule as above).
        self.queue_btn.setEnabled(has_file)
        self.go_btn.setEnabled(has_file)
        if has_file:
            # The `—` the no-file pass left in Preset is a placeholder, not a pick: its
            # option list never changes after an import, so nothing else clears it
            # (an enabled Preset dropdown was reading `—`). No preset applied = None.
            if self.preset_menu.value() == NO_OPTION:
                self.preset_menu.set(presets.NONE_LABEL)
            return
        self.format_menu.set(NO_OPTION)
        self.preset_menu.set(NO_OPTION)
        for menu, label in extra:
            menu.set(NO_OPTION)
            set_enabled(menu, label, False)

    # ------------------------------------------------------------------ #
    #  File selection / output path
    # ------------------------------------------------------------------ #
    def select_input_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Video File", self._output_directory(), MEDIA_FILTER)
        if path:
            self.app.update_global_file(path)

    def set_selected_file(self, path):
        """A file was picked: the drop box turns into the loading spinner over the
        preview area, until the frames (or the audio-only Wave Loop) arrive and
        reveal the carousel. Picking a replacement while a preview is showing goes
        back to the spinner too, rather than leaving the carousel blank meanwhile."""
        self.file_label.setText(f"Selected File:  {path}")
        self.drop_box.collapse()
        self.carousel.force_collapse()
        self.carousel.clear_preview()
        self.carousel.forget_populated()
        self._preview_stack.setCurrentWidget(self.drop_box)

    def clear_selected_file(self):
        """Undo `set_selected_file` and the save-path autofill it triggers —
        called when a just-picked file turns out to be unreadable
        (`app._reject_file`), so the tab looks exactly as it did before that
        file was ever picked rather than stranded mid-import."""
        self.file_label.setText("")
        self.drop_box.reset()
        self.carousel.force_collapse()
        self.carousel.clear_preview()
        self.carousel.forget_populated()
        self._preview_stack.setCurrentWidget(self.drop_box)
        set_line_text(self.save_entry, self.app.default_save_location)
        self._auto_output = self.app.default_save_location or ""

    def show_no_preview(self):
        """The file stays selected but has no preview frames: put the drop box (now
        reading "No Preview Available") back over the carousel. The carousel forgets
        it was populated, so the next file that does have frames reveals it again."""
        self.carousel.force_collapse()
        self.carousel.clear_preview()
        self.carousel.forget_populated()
        self.drop_box.show_no_preview()
        self._preview_stack.setCurrentWidget(self.drop_box)

    def _reveal_preview(self):
        self._preview_stack.setCurrentWidget(self.carousel)

    def _on_expand_toggled(self, expanded):
        """The carousel's own expand/shrink icon: reparent the same carousel
        instance into (or back out of) a dimming overlay filling the main
        window. Every one of the carousel's own behaviors — chevrons, dots,
        badges, drag/drop, the icon itself, arrow-key stepping — keeps
        working unchanged since nothing here is a copy of it, just a
        different temporary parent."""
        if expanded:
            self._preview_stack.removeWidget(self.carousel)
            if self._expand_overlay is None:
                self._expand_overlay = _ExpandedPreviewOverlay(self.app)
            self._expand_overlay.show_with(self.carousel)
        else:
            self._expand_overlay.release()
            self._preview_stack.insertWidget(1, self.carousel)
            self._preview_stack.setCurrentWidget(self.carousel)
            # Same reparent-hides-the-widget gotcha as show_with() above —
            # insertWidget() reparents the carousel back here, which hides
            # it regardless of the stack (and this tab) already being
            # visible. Without this it stays invisible forever after,
            # leaving the preview area blank no matter what's imported next.
            self.carousel.show()

    def on_thumbnails(self, frames):
        """The app's frame broadcast (QImages)."""
        self.carousel.set_frames(frames)

    def _output_directory(self):
        """The folder the Save field currently points at — its own folder when
        it holds a full path (told apart from a bare directory, fresh from
        Settings, by whether it has an extension), else the default save
        location. Where the input file dialogs open, and the one part of the
        Save field an autofill keeps."""
        current = self.save_entry.text().strip().replace("\\", "/")
        directory = os.path.dirname(current) if current and os.path.splitext(current)[1] else current
        return directory or self.app.default_save_location or ""

    def _default_stem(self):
        """The file name (no extension) Settings' naming format gives the
        current input: live tokens filled in, queue-time ones (`{date}`, ...)
        left as literal text until the job is queued (`_resolve_output_tokens`).
        Falls back to the input's own name when the format comes out empty."""
        input_file = self.app.current_file_path
        values = naming.media_live_values(input_file, self.app.media_info)
        return naming.render_live(self.app.naming_template, values, fallback=values["source"])

    def _autofill_output_path(self):
        """'<directory>/<naming format><format>' — the FILENAME always follows
        the newly-selected input (and the naming format from Settings); only
        the DIRECTORY persists (a bare directory, fresh from Settings, is told
        apart from a full path by whether it has an extension)."""
        input_file = self.app.current_file_path
        if not input_file:
            return
        stem = self._default_stem()
        fmt = self.format_menu.value()
        directory = self._output_directory()
        if fmt == NO_OPTION:
            # This runs the instant a file is picked, before the tab's next
            # `_sync_controls` has lifted the no-file placeholder off the
            # Output Format dropdown. Writing the placeholder into the path
            # left an extension-less name, which the *next* autofill then
            # mistook for a folder ("...\clip—\clip.mp4").
            ext = os.path.splitext(input_file)[1].lower()
            fmt = ext if ext in formats.containers() else (self._auto_format or formats.containers()[0])
        suggested = os.path.normpath(os.path.join(directory, f"{stem}{fmt}"))
        # A format with no title/etc. can come out identical to the input's own
        # name — never suggest overwriting the source, so fall back to the
        # tab's own suffix in that one case.
        if os.path.normcase(suggested) == os.path.normcase(os.path.normpath(input_file)):
            suggested = os.path.normpath(os.path.join(directory, f"{stem}{self.OUTPUT_SUFFIX}{fmt}"))
        set_line_text(self.save_entry, suggested)
        self._auto_output = suggested

    def refresh_auto_output(self):
        """Re-derive the suggested name — the probe just delivered a title or
        chapter count, or the naming format changed — but only while the field
        still holds what was autofilled: a hand-typed or Browsed path is never
        touched. Compared without the extension, since a container snap
        rewrites that on its own."""
        if not self.app.current_file_path or not self._auto_output:
            return
        typed = os.path.splitext(self.save_entry.text().strip())[0]
        if typed == os.path.splitext(self._auto_output)[0]:
            self._autofill_output_path()

    def _resolve_output_tokens(self, settings):
        """The queue-time pass: fill `{date}` `{time}` `{creation-time}`
        `{quality}` `{bitrate}` into the job's output path, from the job's own
        settings. The Save field keeps showing the tokens, so queueing again
        later stamps its own time."""
        path = settings.get("output_path") or ""
        if "{" in os.path.basename(path):
            values = naming.media_queue_values(
                settings.get("input_file"), self.app.media_info, settings)
            settings["output_path"] = naming.resolve_path(path, values)

    def select_save_location(self):
        """Pick a full output FILE path."""
        input_file = self.app.current_file_path
        fmt = self.format_menu.value()
        if input_file:
            initial_dir = os.path.dirname(input_file)
            default_name = f"{self._default_stem()}{fmt}"
        else:
            initial_dir = self.app.default_save_location
            default_name = f"output{fmt}"
        existing = self.save_entry.text().strip()
        if existing and os.path.dirname(existing):
            initial_dir = os.path.dirname(existing)
        path, _ = QFileDialog.getSaveFileName(
            self, "Select Output File", os.path.join(initial_dir or "", default_name),
            f"{fmt.lstrip('.').upper()} Video (*{fmt});;All Files (*.*)",
        )
        if path:
            set_line_text(self.save_entry, os.path.normpath(path))
            self._auto_output = None

    # ------------------------------------------------------------------ #
    #  Presets
    # ------------------------------------------------------------------ #
    def _refresh_preset_menu(self, select=None):
        self.preset_menu.set_values(presets.menu_values(self.TAB))
        if select is not None:
            self.preset_menu.set(select)

    def _on_preset_selected(self, name):
        """Applies a saved recipe — never the trim, the paths or track picks."""
        if name == presets.NONE_LABEL:
            return
        stored = presets.get(self.TAB, name)
        if stored is None:
            self._refresh_preset_menu(select=presets.NONE_LABEL)
            return
        self._apply_settings(stored)
        self.app.notify(f"Preset '{name}' applied.", go_to_queue=False)

    def _on_preset_save(self):
        current = self.preset_menu.value()
        initial = "" if current == presets.NONE_LABEL else current
        name = ask_text(self.app, "Save Preset", self.PRESET_NOTE, initial=initial)
        if name is None:
            return
        if name == presets.NONE_LABEL:
            show_message(self.app, "Reserved Name", "That name is reserved. Pick another.")
            return
        if presets.exists(self.TAB, name) and not ask_yes_no(
            self.app, "Overwrite Preset?", f"'{name}' already exists. Replace it?"
        ):
            return
        presets.save(self.TAB, name, self._gather_settings())
        self._refresh_preset_menu(select=name)
        self.app.notify(f"Preset '{name}' saved.", go_to_queue=False)

    def _on_preset_delete(self):
        name = self.preset_menu.value()
        if name == presets.NONE_LABEL:
            show_message(self.app, "No Preset Selected", "Pick a preset to delete first.")
            return
        if not ask_yes_no(self.app, "Delete Preset?", f"Delete the preset '{name}'?"):
            return
        presets.delete(self.TAB, name)
        self._refresh_preset_menu(select=presets.NONE_LABEL)
        self.app.notify(f"Preset '{name}' deleted.", go_to_queue=False)

    # ------------------------------------------------------------------ #
    #  Settings helpers
    # ------------------------------------------------------------------ #
    def _apply_common(self, settings):
        """The keys both tabs share, written in (inside a muted `_ready`)."""
        if settings.get("input_file"):
            self.app.update_global_file(settings["input_file"])
        if "output_path" in settings:
            set_line_text(self.save_entry, settings["output_path"])
            self._auto_output = self.save_entry.text().strip()
        if "start_secs" in settings:
            self.start_time_spinner.set_seconds(settings["start_secs"])
        if "duration_secs" in settings:
            self.duration_time_spinner.set_seconds(settings["duration_secs"])
        if "av_sync" in settings:
            self.av_sync_check.setChecked(bool(settings["av_sync"]))
        if "strip_video" in settings:
            self.strip_video_check.setChecked(bool(settings["strip_video"]))
        if "strip_audio" in settings:
            self.strip_audio_check.setChecked(bool(settings["strip_audio"]))

    def _gather_common(self):
        return {
            "input_file": self.app.current_file_path,
            "output_path": self.save_entry.text(),
            "output_format": self.format_menu.value(),
            "start_secs": self.start_time_spinner.seconds(),
            "duration_secs": self.duration_time_spinner.seconds(),
            "av_sync": self.av_sync_check.isChecked(),
        }

    @staticmethod
    def _menu_value(menu):
        """A derived dropdown's value, with the placeholders as "": `NO_OPTION`
        (nothing to pick) and `Lossless` (Bitrate on a lossless codec — there
        is no bitrate to carry into a job)."""
        value = menu.value()
        return "" if value in (NO_OPTION, formats.LOSSLESS) else value

    def _validate_settings(self, settings):
        """Minimum fields, the tab's own checks, then the output-path prompt."""
        noun = "muxed" if self.TAB == "Muxing" else "encoded"
        verb = "muxing" if self.TAB == "Muxing" else "encoding"
        if not settings["input_file"]:
            show_message(
                self.app, "No File Selected",
                f"Add a video file before queueing or {verb} — drag one onto "
                "the drop box, or double-click it to browse.",
            )
            return False
        if not settings["output_path"]:
            show_message(
                self.app, "No Save Location",
                f"Choose where the {noun} file should be saved before continuing. "
                "Use Browse, or set a default save location on the Settings tab.",
            )
            return False
        if not self._validate_specific(settings):
            return False
        queue_tab = self.app.tabs.get("Queue")
        claimed = bool(queue_tab and queue_tab.claims_output(settings["output_path"]))
        return confirm_output_path(self.app, settings["output_path"], settings["input_file"], claimed)

    def _validate_specific(self, settings):
        return True

    # ------------------------------------------------------------------ #
    #  Queue hand-off
    # ------------------------------------------------------------------ #
    def run_now(self):
        settings = self._gather_settings()
        self._resolve_output_tokens(settings)
        if not self._validate_settings(settings):
            return
        name = os.path.basename(settings["input_file"].replace("\\", "/"))
        queue_tab = self.app.tabs["Queue"]
        task_id = queue_tab.add_task(f"{name}  ·  {self.DIRECT_LABEL}", settings=settings,
                                     status="Queued", source_tab=self.TAB)
        outcome = queue_tab.start_task(task_id)
        self.app.notify({
            "started": f"{self.VERB_ING} job has begun.",
            "next": f"{self.VERB_ING} job will run next.",
            "paused": f"{self.VERB_ING} job will run next — the queue is paused.",
        }[outcome])

    def add_to_queue(self):
        settings = self._gather_settings()
        self._resolve_output_tokens(settings)
        if not self._validate_settings(settings):
            return
        name = os.path.basename(settings["input_file"].replace("\\", "/"))
        description = f"{name}  ·  {settings['duration_secs']}s from {settings['start_secs']}s"
        self.app.tabs["Queue"].add_task(description, settings=settings, status="Queued", source_tab=self.TAB)
        self.app.notify(f"{self.VERB_ING} job added to queue.")
