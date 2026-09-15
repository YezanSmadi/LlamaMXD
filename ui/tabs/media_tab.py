"""The shared Muxing/Encoding frame.

In CTk these two tabs were near-verbatim copies (see CLAUDE.md's Known
issues — "if a third tab needs the same pattern, that's the point to
extract it"). The port is that point: the header, preview area, sub-tab
panels, save row, action buttons, presets, output-path logic and queue
hand-off live here once; each tab supplies its own panels and its own
`_sync_controls` (the two rulesets genuinely differ — Encoding cascades
container → codec, Muxing inverts it).

The hardest part of the old layout, `_pin_options_height` + `_prewarm_
subtabs` (pinning three stacked panels to one height so the drop box didn't
jump, and pre-painting them so the first switch didn't fill in), is simply
a `QStackedWidget`: it sizes to its tallest page and a page switch is one
double-buffered frame."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QStackedLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core import formats, presets
from ui.widgets.carousel import ThumbnailCarousel
from ui.widgets.controls import CheckBox, Dropdown, MarqueeLabel, TimeSpinner, button, labeled
from ui.widgets.dialogs import ask_text, ask_yes_no, confirm_output_path, show_message
from ui.widgets.panels import MEDIA_FILTER, DropBox, SubTabBar, SummaryPanel

SUBTABS = ("Overview", "Video", "Audio")


def hrow(spacing=0, align_bottom=True):
    """A plain horizontal row widget + its layout."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
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
    """Replace a QLineEdit's text and show its start (paths are long)."""
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
        root.setContentsMargins(10, 5, 10, 4)
        root.setSpacing(0)

        # --- Header: sub-tab switch + the selected file.
        header, hl = hrow(spacing=10, align_bottom=False)
        self.sub_tab_bar = SubTabBar(SUBTABS)
        hl.addWidget(self.sub_tab_bar, 0, Qt.AlignBottom)
        self.file_label = MarqueeLabel("", pixel_size=11)
        self.file_label.doubleClicked.connect(self.select_input_file)
        hl.addWidget(self.file_label, 1, Qt.AlignVCenter)
        root.addWidget(header)
        root.addSpacing(15)

        # --- Preview: the DropBox until the first frames land, then the
        # carousel in its place.
        preview = QWidget()
        self._preview_stack = QStackedLayout(preview)
        self.drop_box = DropBox()
        self.drop_box.fileSelected.connect(app.update_global_file)
        self.carousel = ThumbnailCarousel(host=self)
        self.carousel.reselect.connect(self.select_input_file)
        self.carousel.populated.connect(self._reveal_preview)
        self.carousel.indexChanged.connect(app.sync_preview_index)
        self.carousel.fileDropped.connect(app.update_global_file)
        self._preview_stack.addWidget(self.drop_box)
        self._preview_stack.addWidget(self.carousel)
        root.addWidget(preview, 1)
        root.addSpacing(18)

        # --- Sub-tab panels.
        self.panels = QStackedWidget()
        self.panels.addWidget(self._build_overview())
        self.panels.addWidget(self.build_video())
        self.panels.addWidget(self.build_audio())
        self.sub_tab_bar.changed.connect(lambda n: self.panels.setCurrentIndex(SUBTABS.index(n)))
        root.addWidget(self.panels)
        root.addSpacing(11)

        # --- Save row.
        save, sl = hrow(spacing=6, align_bottom=False)
        self.save_entry = QLineEdit()
        self.save_entry.setPlaceholderText("Save file as...")
        self.save_entry.setFixedHeight(28)
        set_line_text(self.save_entry, app.default_save_location)
        sl.addWidget(self.save_entry, 1)
        self.browse_save_btn = button("Browse", width=80)
        self.browse_save_btn.clicked.connect(self.select_save_location)
        sl.addWidget(self.browse_save_btn)
        root.addWidget(save)
        root.addSpacing(10)

        # --- Queue Task (secondary) + the do-it-now button (primary).
        actions, al = hrow(spacing=8, align_bottom=False)
        self.queue_btn = button("Queue Task")
        self.queue_btn.clicked.connect(self.add_to_queue)
        self.go_btn = button(self.ACTION_TEXT, role="primary")
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
        outer.setSpacing(20)

        left = QVBoxLayout()
        left.setSpacing(6)
        left.addStretch(1)
        row1, r1 = hrow(spacing=8)
        self.format_menu = Dropdown(formats.containers(), width=92)
        self.format_menu.picked.connect(self._on_format_change)
        box, self.format_label = labeled("Output Format:", self.format_menu)
        r1.addWidget(box)
        r1.addSpacing(6)
        self.preset_menu = Dropdown(presets.menu_values(self.TAB), width=132)
        self.preset_menu.set(presets.NONE_LABEL)
        self.preset_menu.picked.connect(self._on_preset_selected)
        box, self.preset_label = labeled("Preset:", self.preset_menu)
        r1.addWidget(box)
        self.preset_save_btn = button("Save", width=54)
        self.preset_save_btn.clicked.connect(self._on_preset_save)
        self.preset_delete_btn = button("Delete", width=54)
        self.preset_delete_btn.clicked.connect(self._on_preset_delete)
        r1.addWidget(self.preset_save_btn, 0, Qt.AlignBottom)
        r1.addWidget(self.preset_delete_btn, 0, Qt.AlignBottom)
        left.addWidget(row1)

        # There is no "Retain Video Length" checkbox: Duration 00:00:00
        # already means "to the end of the file".
        row2, r2 = hrow(spacing=14)
        self.start_time_spinner = TimeSpinner()
        self.duration_time_spinner = TimeSpinner()
        for spinner in (self.start_time_spinner, self.duration_time_spinner):
            spinner.valueChanged.connect(self._on_trim_change)
        box, self.start_label = labeled("Start Time:", self.start_time_spinner)
        r2.addWidget(box)
        box, self.duration_label = labeled("Clip Duration:", self.duration_time_spinner)
        r2.addWidget(box)
        r2.addSpacing(2)
        self.av_sync_check = CheckBox("A/V Sync", checked=True)
        self.av_sync_check.clicked.connect(self._on_control_change)
        r2.addWidget(self.av_sync_check, 0, Qt.AlignBottom)
        left.addWidget(row2)
        outer.addLayout(left)

        right = QVBoxLayout()
        right.addStretch(1)
        self.summary = SummaryPanel(["Video", "Audio", "Length"])
        right.addWidget(self.summary)
        right.addSpacing(4)
        outer.addLayout(right, 1)
        return page

    @staticmethod
    def stream_page():
        """An empty sub-tab page: `(page, left_layout, right_layout)`, the
        left bottom-anchored."""
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(20)
        left = QVBoxLayout()
        left.setSpacing(6)
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

    def _on_format_change(self, _value=None):
        """The user picked a container: stop auto-adopting the source's,
        swap the output path's extension, and re-sync."""
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
    #  File selection / output path
    # ------------------------------------------------------------------ #
    def select_input_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Video File", "", MEDIA_FILTER)
        if path:
            self.app.update_global_file(path)

    def set_selected_file(self, path):
        self.file_label.setText(f"Selected File:  {path}")
        self.drop_box.collapse()

    def _reveal_preview(self):
        self._preview_stack.setCurrentWidget(self.carousel)

    def on_thumbnails(self, frames):
        """The app's frame broadcast (QImages)."""
        self.carousel.set_frames(frames)

    def _autofill_output_path(self):
        """'<directory>/<input basename><suffix><format>' — the FILENAME
        always follows the newly-selected input; only the DIRECTORY persists
        (a bare directory, fresh from Settings, is told apart from a full
        path by whether it has an extension)."""
        input_file = self.app.current_file_path
        if not input_file:
            return
        base = os.path.splitext(os.path.basename(input_file.replace("\\", "/")))[0]
        current = self.save_entry.text().strip().replace("\\", "/")
        directory = os.path.dirname(current) if current and os.path.splitext(current)[1] else current
        directory = directory or self.app.default_save_location or ""
        suggested = os.path.normpath(
            os.path.join(directory, f"{base}{self.OUTPUT_SUFFIX}{self.format_menu.value()}")
        )
        set_line_text(self.save_entry, suggested)
        self._auto_output = suggested

    def select_save_location(self):
        """Pick a full output FILE path."""
        input_file = self.app.current_file_path
        fmt = self.format_menu.value()
        if input_file:
            base = os.path.splitext(os.path.basename(input_file.replace("\\", "/")))[0]
            initial_dir = os.path.dirname(input_file)
            default_name = f"{base}{self.OUTPUT_SUFFIX}{fmt}"
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
        """A derived dropdown's value, with the `—` placeholder as ""."""
        value = menu.value()
        return "" if value == "—" else value

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
        if not self._validate_settings(settings):
            return
        name = os.path.basename(settings["input_file"].replace("\\", "/"))
        description = f"{name}  ·  {settings['duration_secs']}s from {settings['start_secs']}s"
        self.app.tabs["Queue"].add_task(description, settings=settings, status="Queued", source_tab=self.TAB)
        self.app.notify(f"{self.VERB_ING} job added to queue.")
