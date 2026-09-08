import os
import customtkinter as ctk
from tkinter import filedialog
from components.dialogs import show_message
from components.drop_box import DropBox
from components.dropdown import ThemedDropdown
from components.thumbnail_carousel import ThumbnailCarousel
from components.time_spinner import TimeSpinner
from core.theme import get_active_theme

# Container formats offered by the Output Format dropdown — the leading dot is
# kept so the value drops straight onto a filename stem.
_OUTPUT_FORMATS = [".mp4", ".mkv", ".mov", ".webm"]

class MuxingTab(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master=master)
        self.app = app
        theme = get_active_theme()

        # --- Bottom Section: Video Length Option ---
        # Packed FIRST with side="bottom" to anchor at the bottom edge
        self.controls_frame = ctk.CTkFrame(master=self, fg_color="transparent")
        self.controls_frame.pack(side="bottom", fill="x", padx=10, pady=(0, 4))

        self.checkbox = ctk.CTkCheckBox(
            master=self.controls_frame,
            text="Retain Video Length",
            command=self.toggle_time_spinners
        )
        self.checkbox.pack(anchor="w")
        self.checkbox.select()  # Default to retaining the source video length

        self.time_container = ctk.CTkFrame(master=self.controls_frame, fg_color="transparent")
        self.time_container.pack(anchor="w", pady=(4, 0))

        # Start Timestamp Sub-Frame
        self.start_frame = ctk.CTkFrame(master=self.time_container, fg_color="transparent")
        self.start_frame.pack(side="left", padx=(0, 15))

        self.start_label = ctk.CTkLabel(master=self.start_frame, text="Start Time:", font=("Arial", 11, "bold"))
        self.start_label.pack(anchor="w", pady=(0, 1))

        self.start_time_spinner = TimeSpinner(master=self.start_frame, initial_seconds=0)
        self.start_time_spinner.pack(anchor="w")

        # Clip Duration Sub-Frame
        self.duration_frame = ctk.CTkFrame(master=self.time_container, fg_color="transparent")
        self.duration_frame.pack(side="left")

        self.duration_label = ctk.CTkLabel(master=self.duration_frame, text="Clip Duration:", font=("Arial", 11, "bold"))
        self.duration_label.pack(anchor="w", pady=(0, 1))

        self.duration_time_spinner = TimeSpinner(master=self.duration_frame, initial_seconds=0)
        self.duration_time_spinner.pack(anchor="w")

        self.toggle_time_spinners()  # Reflect the checkbox's default checked state

        # Output container format — feeds the extension of the suggested save
        # path (and the save dialog's default) via _on_format_change /
        # _autofill_output_path, and rides along in _gather_settings as
        # "output_format".
        # pady=(6, 4): matches the effective spacing around Encoding's
        # codec-options row — 6 above, and 4 below to sit level with the 8px
        # total gap Encoding gets from its `main_options_row` bottom pad plus
        # `save_frame`'s top pad (Muxing has no `main_options_row`).
        self.format_frame = ctk.CTkFrame(master=self.controls_frame, fg_color="transparent")
        self.format_frame.pack(anchor="w", pady=(6, 4))

        self.format_label = ctk.CTkLabel(master=self.format_frame, text="Output Format:", font=("Arial", 11, "bold"))
        self.format_label.pack(anchor="w", pady=(0, 1))

        self.format_menu = ThemedDropdown(
            master=self.format_frame,
            values=_OUTPUT_FORMATS,
            width=110,
            command=self._on_format_change,
        )
        self.format_menu.pack(anchor="w")

        # Save Location Section
        self.save_frame = ctk.CTkFrame(master=self.controls_frame, fg_color="transparent")
        self.save_frame.pack(fill="x", pady=4)

        self.save_entry = ctk.CTkEntry(
            master=self.save_frame,
            placeholder_text="Save file as..."
        )
        self.save_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

        # Pre-fill with the default save folder and keep refining it to
        # "<folder>/<input name>_muxed<format>" as files are picked, until the
        # user overrides it themselves (tracked via self._auto_output).
        self._auto_output = ""
        if self.app.default_save_location:
            self.save_entry.insert(0, self.app.default_save_location)
            self._auto_output = self.app.default_save_location

        self.browse_save_btn = ctk.CTkButton(
            master=self.save_frame,
            text="Browse",
            width=80,
            command=self.select_save_location
        )
        self.browse_save_btn.pack(side="right")

        # Action Buttons Row: Queue Task (blue) + Mux (yellow), each half-width
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
            command=self.add_to_queue
        )
        self.queue_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.mux_btn = ctk.CTkButton(
            master=self.action_frame,
            text="Mux",
            fg_color=theme["primary"],
            text_color=theme["primary_text"],
            hover_color=theme["primary_hover"],
            command=self.mux_now
        )
        self.mux_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        # --- Top Flexible Section: DropBox & Dynamic Image ---
        self.top_container = ctk.CTkFrame(master=self, fg_color="transparent")
        self.top_container.pack(side="top", fill="both", expand=True, padx=10, pady=(5, 5))

        # Selected File Text Header — left unpacked until a file is actually
        # selected, so the DropBox gets its space while empty. _reveal_preview()
        # packs it (and the carousel) in on the first thumbnail set.
        self.label = ctk.CTkLabel(master=self.top_container, text="", font=ctk.CTkFont(size=11))
        self.label.bind("<Double-Button-1>", lambda e: self.select_input_file())

        # Multi-frame preview carousel — owns the thumbnail label, its resize
        # math, and the fade-in prev/next chevrons. Double-clicking it (like
        # the old single thumbnail label) reselects the input file.
        self.carousel = ThumbnailCarousel(
            master=self.top_container,
            on_reselect=self.select_input_file,
            on_populated=self._reveal_preview,
            on_index=self.app.sync_preview_index,   # keep both tabs on the same frame
        )

        # DropBox fills all available space in top_container while it's the
        # only thing packed there.
        self.drop_box = DropBox(master=self.top_container, on_file_selected=self.app.update_global_file, height=380)
        self.drop_box.pack(fill="both", expand=True)

        # Register controls with main app — the carousel's set_frames is the
        # thumbnail-broadcast target.
        self.app.register_tab_ui(self.label, self.carousel, on_thumbnail=self.carousel.set_frames)

    def select_input_file(self):
        """Allows user to pick a video file via file dialog."""
        file_path = filedialog.askopenfilename(
            title="Select Video File",
            filetypes=[("Video Files", "*.mp4 *.mkv *.avi *.mov *.webm"), ("All Files", "*.*")]
        )
        if file_path:
            self.app.update_global_file(file_path)

    def _reveal_preview(self):
        """First thumbnail set has arrived: swap the DropBox out for the
        filename header + preview carousel. (The non-thumbnail half of the
        old display_image.)"""
        if not self.label.winfo_ismapped():
            self.label.pack(pady=(0, 0))
        self.drop_box.pack_forget()
        if not self.carousel.winfo_ismapped():
            self.carousel.pack(pady=(2, 2), fill="both", expand=True)

    def _autofill_output_path(self):
        """Suggests '<default folder>/<input basename>_muxed<format>' in the
        output field (format = the current format_menu value) — but only while
        the user hasn't set their own path (self._auto_output holds the last
        value we filled; None once the user picks via Browse)."""
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
        """Swaps the output path's extension to the newly-picked format. Only
        touches a path that already has an extension to replace — before a file
        is picked the entry holds just a folder, which _autofill_output_path
        completes with the right extension once there's an input."""
        current = self.save_entry.get().strip()
        root, ext = os.path.splitext(current)
        if not ext:
            return
        updated = root + self.format_menu.get()
        self.save_entry.delete(0, "end")
        self.save_entry.insert(0, updated)
        if self._auto_output is not None:
            self._auto_output = updated

    def toggle_time_spinners(self):
        is_checked = self.checkbox.get() == 1
        state = "disabled" if is_checked else "normal"
        label_color = "gray50" if is_checked else ctk.ThemeManager.theme["CTkLabel"]["text_color"]

        self.start_time_spinner.set_state(state)
        self.duration_time_spinner.set_state(state)

        self.start_label.configure(text_color=label_color)
        self.duration_label.configure(text_color=label_color)

    def select_save_location(self):
        """Lets the user pick a full output FILE path (not just a folder)."""
        input_file = self.app.current_file_path

        fmt = self.format_menu.get()  # e.g. ".mkv" — already dotted

        if input_file:
            input_name = input_file.split("/")[-1]
            base_name = input_name.rsplit(".", 1)[0] if "." in input_name else input_name
            initial_dir = "/".join(input_file.replace("\\", "/").split("/")[:-1])
            default_name = f"{base_name}_muxed{fmt}"
        else:
            initial_dir = self.app.default_save_location
            default_name = f"output{fmt}"

        # Pre-fill the dialog's starting folder from whatever's already typed, if valid
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
            filetypes=[
                ("MP4 Video", "*.mp4"),
                ("MKV Video", "*.mkv"),
                ("All Files", "*.*"),
            ],
        )
        if file_path:
            self.save_entry.delete(0, "end")
            self.save_entry.insert(0, file_path)
            self._auto_output = None  # user chose their own — stop auto-filling

    def _gather_settings(self):
        """Collects the current Muxing tab state into a plain dict."""
        return {
            "input_file": self.app.current_file_path,
            "output_path": self.save_entry.get(),
            "output_format": self.format_menu.get(),
            "start_secs": self.start_time_spinner.get_total_seconds(),
            "duration_secs": self.duration_time_spinner.get_total_seconds(),
            "retain_length": bool(self.checkbox.get()),
        }

    def load_settings(self, settings):
        """Restores a settings dict (e.g. from a queued task) into the UI."""
        if not settings:
            return

        input_file = settings.get("input_file")
        if input_file:
            self.app.update_global_file(input_file)

        self.format_menu.set(settings.get("output_format", _OUTPUT_FORMATS[0]))

        self.save_entry.delete(0, "end")
        self.save_entry.insert(0, settings.get("output_path", ""))
        self._auto_output = self.save_entry.get().strip()

        self.start_time_spinner.set(settings.get("start_secs", 0))
        self.duration_time_spinner.set(settings.get("duration_secs", 0))

        if settings.get("retain_length"):
            self.checkbox.select()
        else:
            self.checkbox.deselect()
        self.toggle_time_spinners()

    def _validate_settings(self, settings):
        """Checks that the minimum required fields are filled in before
        queueing/muxing, raising a modal dialog on the first thing missing.
        Returns True if valid, else False."""
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
