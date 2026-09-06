import os
import customtkinter as ctk
from tkinter import filedialog
from PIL import Image
from components.dialogs import show_message
from components.drop_box import DropBox
from components.dropdown import ThemedDropdown
from components.time_spinner import TimeSpinner
from core.theme import get_active_theme

class EncodingTab(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master=master)
        self.app = app
        theme = get_active_theme()
        self._raw_pil_image = None  # Cache original loaded PIL image for resizing

        # --- Bottom Section: Fixed Encoding Controls ---
        # Packed FIRST with side="bottom" to anchor at the bottom edge
        self.controls_frame = ctk.CTkFrame(master=self, fg_color="transparent")
        self.controls_frame.pack(side="bottom", fill="x", padx=10, pady=(0, 4))

        # 1. Main Options Row — two columns sharing one row so nothing is
        # stacked further down than it needs to be:
        #   left  = Retain Video Length checkbox, time spinners, Profile/Level
        #   right = GPU/HDR switches stacked directly above the CRF slider
        # Both columns bottom-align (anchor="s") so this whole block hugs the
        # save-file row beneath it rather than floating at the top — leaving
        # the DropBox above as much vertical room as possible.
        self.main_options_row = ctk.CTkFrame(master=self.controls_frame, fg_color="transparent")
        self.main_options_row.pack(fill="x", pady=(2, 4))

        self.left_col = ctk.CTkFrame(master=self.main_options_row, fg_color="transparent")
        self.left_col.pack(side="left", anchor="s", padx=(0, 20))

        self.right_col = ctk.CTkFrame(master=self.main_options_row, fg_color="transparent")
        self.right_col.pack(side="left", anchor="s", fill="x", expand=True)

        # -- Left column: Retain Video Length + time spinners + Profile/Level --
        self.checkbox = ctk.CTkCheckBox(
            master=self.left_col,
            text="Retain Video Length",
            command=self.toggle_time_spinners
        )
        self.checkbox.pack(anchor="w")
        self.checkbox.select()  # Default to retaining the source video length

        self.time_container = ctk.CTkFrame(master=self.left_col, fg_color="transparent")
        self.time_container.pack(anchor="w", pady=(4, 0))

        # Start Timestamp Sub-Frame
        self.start_frame = ctk.CTkFrame(master=self.time_container, fg_color="transparent")
        self.start_frame.pack(side="left", padx=(0, 15))

        self.start_label = ctk.CTkLabel(master=self.start_frame, text="Start Time:", font=("Arial", 12, "bold"))
        self.start_label.pack(anchor="w", pady=(0, 1))

        self.start_time_spinner = TimeSpinner(master=self.start_frame, initial_seconds=0)
        self.start_time_spinner.pack(anchor="w")

        # Clip Duration Sub-Frame
        self.duration_frame = ctk.CTkFrame(master=self.time_container, fg_color="transparent")
        self.duration_frame.pack(side="left")

        self.duration_label = ctk.CTkLabel(master=self.duration_frame, text="Clip Duration:", font=("Arial", 12, "bold"))
        self.duration_label.pack(anchor="w", pady=(0, 1))

        self.duration_time_spinner = TimeSpinner(master=self.duration_frame, initial_seconds=0)
        self.duration_time_spinner.pack(anchor="w")

        self.toggle_time_spinners()  # Reflect the checkbox's default checked state

        # Profile / Level Dropdowns, underneath the time spinners
        self.codec_options_frame = ctk.CTkFrame(master=self.left_col, fg_color="transparent")
        self.codec_options_frame.pack(anchor="w", pady=(6, 0))

        self.profile_frame = ctk.CTkFrame(master=self.codec_options_frame, fg_color="transparent")
        self.profile_frame.pack(side="left", padx=(0, 15))

        self.profile_label = ctk.CTkLabel(master=self.profile_frame, text="Profile:", font=("Arial", 12, "bold"))
        self.profile_label.pack(anchor="w", pady=(0, 1))

        self.profile_menu = ThemedDropdown(
            master=self.profile_frame,
            values=["High", "Main", "Main 10", "Baseline"],
            width=110,
        )
        self.profile_menu.pack(anchor="w")

        self.level_frame = ctk.CTkFrame(master=self.codec_options_frame, fg_color="transparent")
        self.level_frame.pack(side="left")

        self.level_label = ctk.CTkLabel(master=self.level_frame, text="Level:", font=("Arial", 12, "bold"))
        self.level_label.pack(anchor="w", pady=(0, 1))

        self.level_menu = ThemedDropdown(
            master=self.level_frame,
            values=["4.0", "4.1", "5.0", "5.1"],
            width=90,
        )
        self.level_menu.pack(anchor="w")

        # -- Right column: HDR switch (label to the LEFT of the toggle), then
        # the CRF slider directly beneath it. Hardware Acceleration (GPU)
        # used to live here too but is now a global preference on the
        # Settings tab (read as self.app.gpu_enabled in _gather_settings). --

        # HDR to SDR Conversion Switch — built without its own text so a
        # separate label can sit to its left instead of CTkSwitch's default
        # label-on-the-right layout; clicking the label toggles the switch.
        # CTkSwitch's internal grid always reserves its (here-empty) text
        # column with weight=1, so it defaults to a 100px-wide widget even
        # with text="" — width=42 trims that down to just the toggle track,
        # so anchor="e" on the row actually lands the visible switch flush
        # against the right edge instead of leaving phantom label space.
        self.hdr_row = ctk.CTkFrame(master=self.right_col, fg_color="transparent")
        self.hdr_row.pack(anchor="e", pady=2)

        self.hdr_label = ctk.CTkLabel(master=self.hdr_row, text="HDRtoSDR")
        self.hdr_label.pack(side="left", padx=(0, 8))
        self.hdr_label.bind("<Button-1>", lambda e: self.hdr_switch.toggle())

        self.hdr_switch = ctk.CTkSwitch(master=self.hdr_row, text="", width=42)
        self.hdr_switch.pack(side="left")

        # CRF (Quality) Slider — longer, title centered above it.
        # Range is 0 (best) to 40 (worst), reversed so the slider still reads
        # low-quality-on-the-left, placebo-quality-on-the-right.
        self.crf_frame = ctk.CTkFrame(master=self.right_col, fg_color="transparent")
        self.crf_frame.pack(fill="x", pady=(6, 0))

        self.crf_label = ctk.CTkLabel(master=self.crf_frame, text="Quality (CRF):", font=("Arial", 12, "bold"))
        self.crf_label.pack(anchor="center", pady=(0, 1))

        self.crf_slider_row = ctk.CTkFrame(master=self.crf_frame, fg_color="transparent")
        self.crf_slider_row.pack(anchor="center")

        self.crf_low_label = ctk.CTkLabel(master=self.crf_slider_row, text="Low", text_color="gray60", font=("Arial", 11))
        self.crf_low_label.pack(side="left", padx=(0, 4))

        self.crf_slider = ctk.CTkSlider(
            master=self.crf_slider_row,
            from_=40,
            to=0,
            number_of_steps=40,
            width=180,
            command=self._on_crf_change,
        )
        self.crf_slider.pack(side="left")
        self.crf_slider.set(23)  # Common default CRF
        self._on_crf_change(23)

        self.crf_high_label = ctk.CTkLabel(master=self.crf_slider_row, text="Placebo", text_color="gray60", font=("Arial", 12))
        self.crf_high_label.pack(side="left", padx=(4, 0))

        # 4. Save Location Section
        self.save_frame = ctk.CTkFrame(master=self.controls_frame, fg_color="transparent")
        self.save_frame.pack(fill="x", pady=4)

        self.save_entry = ctk.CTkEntry(
            master=self.save_frame,
            placeholder_text="Save file as..."
        )
        self.save_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

        # Pre-fill with the default save folder and keep refining it to
        # "<folder>/<input name>_encoded.mp4" as files are picked, until the
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

        # 5. Action Buttons Row: Queue Task (blue) + Encode (yellow), each half-width
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

        self.encode_btn = ctk.CTkButton(
            master=self.action_frame,
            text="Encode",
            fg_color=theme["primary"],
            text_color=theme["primary_text"],
            hover_color=theme["primary_hover"],
            command=self.encode_now
        )
        self.encode_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        # --- Top Flexible Section: DropBox & Dynamic Image ---
        self.top_container = ctk.CTkFrame(master=self, fg_color="transparent")
        self.top_container.pack(side="top", fill="both", expand=True, padx=10, pady=(5, 5))

        # Selected File Text Header — doubles as a "click to change file" hint.
        # Left unpacked until a file is actually selected: these two labels
        # are empty until then, but packing them unconditionally still
        # reserves their (nonzero, font-driven) height permanently, which is
        # exactly the vertical room the empty DropBox should get instead.
        # display_image() packs both in on the first thumbnail.
        self.label = ctk.CTkLabel(master=self.top_container, text="", font=ctk.CTkFont(size=11))

        # Video Thumbnail Label — click it to reselect a file (no separate button needed).
        self.img_label = ctk.CTkLabel(master=self.top_container, text="")
        self.img_label.configure(cursor="hand2")
        self.img_label.bind("<Double-Button-1>", lambda e: self.select_input_file())
        self.label.bind("<Double-Button-1>", lambda e: self.select_input_file())

        # DropBox fills all available space in top_container while it's the
        # only thing packed there.
        self.drop_box = DropBox(master=self.top_container, on_file_selected=self.app.update_global_file, height=380)
        self.drop_box.pack(fill="both", expand=True)

        # Register controls with main app
        self.app.register_tab_ui(self.label, self.img_label, on_thumbnail=self.display_image)

        # Bind resize listener for image thumbnail scaling
        self.top_container.bind("<Configure>", self._on_resize)

    def select_input_file(self):
        """Allows user to pick a video file via file dialog."""
        file_path = filedialog.askopenfilename(
            title="Select Video File",
            filetypes=[("Video Files", "*.mp4 *.mkv *.avi *.mov *.webm"), ("All Files", "*.*")]
        )
        if file_path:
            self.app.update_global_file(file_path)

    def display_image(self, pil_image):
        """Called when a file is selected to display its thumbnail."""
        self._raw_pil_image = pil_image

        # Pack the filename header + thumbnail label in on first use — they
        # sit unpacked until now so the DropBox gets their space while empty.
        if not self.label.winfo_ismapped():
            self.label.pack(pady=(0, 0))
        if not self.img_label.winfo_ismapped():
            self.img_label.pack(pady=(2, 2), expand=True)

        # Hide initial dropbox now that a file/thumbnail is shown
        self.drop_box.pack_forget()
        self._resize_thumbnail()

    def _on_resize(self, event):
        """Dynamic resize handler for the video thumbnail."""
        if self._raw_pil_image is not None:
            self._resize_thumbnail()

    def _resize_thumbnail(self):
        if self._raw_pil_image is None:
            return

        container_w = max(100, self.top_container.winfo_width() - 20)
        label_h = self.label.winfo_reqheight()
        container_h = max(100, self.top_container.winfo_height() - label_h - 20)

        img_w, img_h = self._raw_pil_image.size
        if img_w == 0 or img_h == 0:
            return

        scale_w = container_w / img_w
        scale_h = container_h / img_h
        scale = min(scale_w, scale_h)

        new_w = max(1, int(img_w * scale))
        new_h = max(1, int(img_h * scale))

        ctk_img = ctk.CTkImage(
            light_image=self._raw_pil_image, 
            dark_image=self._raw_pil_image, 
            size=(new_w, new_h)
        )
        self.img_label.configure(image=ctk_img)

    def _autofill_output_path(self):
        """Suggests '<default folder>/<input basename>_encoded.mp4' in the
        output field — but only while the user hasn't set their own path
        (self._auto_output holds the last value we filled; None once the
        user picks via Browse)."""
        current = self.save_entry.get().strip()
        if current and current != self._auto_output:
            return
        input_file = self.app.current_file_path
        if not input_file:
            return
        base = os.path.splitext(os.path.basename(input_file.replace("\\", "/")))[0]
        suggested = os.path.normpath(
            os.path.join(self.app.default_save_location or "", f"{base}_encoded.mp4")
        )
        self.save_entry.delete(0, "end")
        self.save_entry.insert(0, suggested)
        self._auto_output = suggested

    def _on_crf_change(self, value):
        """Updates the live CRF value readout in the slider's title label."""
        self.crf_label.configure(text=f"Quality (CRF): {int(round(value))}")

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

        if input_file:
            input_name = input_file.split("/")[-1]
            base_name = input_name.rsplit(".", 1)[0] if "." in input_name else input_name
            initial_dir = "/".join(input_file.replace("\\", "/").split("/")[:-1])
            default_name = f"{base_name}_encoded.mp4"
        else:
            initial_dir = self.app.default_save_location
            default_name = "output.mp4"

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
            defaultextension=".mp4",
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
        """Collects the current Encoding tab state into a plain dict.
        `gpu_enabled` is the global Settings-tab preference, not a per-tab
        control anymore."""
        return {
            "input_file": self.app.current_file_path,
            "output_path": self.save_entry.get(),
            "start_secs": self.start_time_spinner.get_total_seconds(),
            "duration_secs": self.duration_time_spinner.get_total_seconds(),
            "gpu_enabled": bool(self.app.gpu_enabled),
            "hdr_to_sdr": bool(self.hdr_switch.get()),
            "retain_length": bool(self.checkbox.get()),
            "crf": int(round(self.crf_slider.get())),
            "profile": self.profile_menu.get(),
            "level": self.level_menu.get(),
        }

    def load_settings(self, settings):
        """Restores a settings dict (e.g. from a queued task) into the UI."""
        if not settings:
            return

        input_file = settings.get("input_file")
        if input_file:
            self.app.update_global_file(input_file)

        self.save_entry.delete(0, "end")
        self.save_entry.insert(0, settings.get("output_path", ""))
        self._auto_output = self.save_entry.get().strip()

        self.start_time_spinner.set(settings.get("start_secs", 0))
        self.duration_time_spinner.set(settings.get("duration_secs", 0))

        if settings.get("hdr_to_sdr"):
            self.hdr_switch.select()
        else:
            self.hdr_switch.deselect()

        if settings.get("retain_length"):
            self.checkbox.select()
        else:
            self.checkbox.deselect()
        self.toggle_time_spinners()

        crf = settings.get("crf", 23)
        self.crf_slider.set(crf)
        self._on_crf_change(crf)

        self.profile_menu.set(settings.get("profile", "High"))
        self.level_menu.set(settings.get("level", "4.1"))

    def _validate_settings(self, settings):
        """Checks that the minimum required fields are filled in before
        queueing/encoding, raising a modal dialog on the first thing missing.
        Returns True if valid, else False."""
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
            self.app.notify("Job added to queue.")
        else:
            print(f"Queue tab unavailable — would have queued: {settings}")