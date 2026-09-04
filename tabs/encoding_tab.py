import customtkinter as ctk
from tkinter import filedialog
from PIL import Image
from components.drop_box import DropBox
from components.time_spinner import TimeSpinner

class EncodingTab(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master=master)
        self.app = app
        self._raw_pil_image = None  # Cache original loaded PIL image for resizing

        # --- Bottom Section: Fixed Encoding Controls ---
        # Packed FIRST with side="bottom" to anchor at the bottom edge
        self.controls_frame = ctk.CTkFrame(master=self, fg_color="transparent")
        self.controls_frame.pack(side="bottom", fill="x", padx=10, pady=(0, 4))

        # 1. Checkbox
        self.checkbox = ctk.CTkCheckBox(
            master=self.controls_frame, 
            text="Retain Video Length",
            command=self.toggle_time_spinners
        )
        self.checkbox.pack(anchor="w", pady=(2, 2))

        # 2. Time Spinners Container
        self.time_container = ctk.CTkFrame(master=self.controls_frame, fg_color="transparent")
        self.time_container.pack(anchor="w", pady=(2, 5), padx=(25, 0))

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

        # 3. Hardware Acceleration Switch
        self.switch = ctk.CTkSwitch(master=self.controls_frame, text="Hardware Acceleration (GPU)")
        self.switch.pack(anchor="w", pady=3)

        # 3b. HDR to SDR Conversion Switch
        self.hdr_switch = ctk.CTkSwitch(master=self.controls_frame, text="HDRtoSDR Conversion")
        self.hdr_switch.pack(anchor="w", pady=3)

        # 4. Save Location Section
        self.save_frame = ctk.CTkFrame(master=self.controls_frame, fg_color="transparent")
        self.save_frame.pack(fill="x", pady=5)

        self.save_entry = ctk.CTkEntry(
            master=self.save_frame, 
            placeholder_text="Select output directory..."
        )
        self.save_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

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
            command=self.add_to_queue
        )
        self.queue_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.encode_btn = ctk.CTkButton(
            master=self.action_frame,
            text="Encode",
            fg_color="#FDCA3C",
            text_color="black",
            hover_color="#e0b234",
            command=self.encode_now
        )
        self.encode_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        # --- Top Flexible Section: DropBox & Dynamic Image ---
        self.top_container = ctk.CTkFrame(master=self, fg_color="transparent")
        self.top_container.pack(side="top", fill="both", expand=True, padx=10, pady=(5, 5))

        # Selected File Text Header — doubles as a "click to change file" hint
        self.label = ctk.CTkLabel(master=self.top_container, text="", font=ctk.CTkFont(size=11))
        self.label.pack(pady=(0, 0))

        # Video Thumbnail Label — click it to reselect a file (no separate button needed)
        self.img_label = ctk.CTkLabel(master=self.top_container, text="")
        self.img_label.pack(pady=(2, 2), expand=True)
        self.img_label.configure(cursor="hand2")
        self.img_label.bind("<Double-Button-1>", lambda e: self.select_input_file())
        self.label.bind("<Double-Button-1>", lambda e: self.select_input_file())

        # DropBox wide & vertically centered (fill="x" + expand=True matching screenshot 3)
        self.drop_box = DropBox(master=self.top_container, on_file_selected=self.app.update_global_file)
        self.drop_box.pack(fill="x", expand=True)

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

    def toggle_time_spinners(self):
        is_checked = self.checkbox.get() == 1
        state = "disabled" if is_checked else "normal"
        label_color = "gray50" if is_checked else ctk.ThemeManager.theme["CTkLabel"]["text_color"]

        self.start_time_spinner.set_state(state)
        self.duration_time_spinner.set_state(state)

        self.start_label.configure(text_color=label_color)
        self.duration_label.configure(text_color=label_color)

    def select_save_location(self):
        folder = filedialog.askdirectory(title="Select Save Directory")
        if folder:
            self.save_entry.delete(0, "end")
            self.save_entry.insert(0, folder)

    def encode_now(self):
        output_dir = self.save_entry.get()
        start_time = self.start_time_spinner.get()
        start_secs = self.start_time_spinner.get_total_seconds()

        duration = self.duration_time_spinner.get()
        duration_secs = self.duration_time_spinner.get_total_seconds()

        gpu_enabled = self.switch.get()
        hdr_to_sdr = self.hdr_switch.get()
        retain_length = self.checkbox.get()

        print(
            f"Encoding Now: Start='{start_time}' ({start_secs}s), "
            f"Duration='{duration}' ({duration_secs}s), "
            f"GPU={gpu_enabled}, HDRtoSDR={hdr_to_sdr}, RetainLength={retain_length}, Save='{output_dir}'"
        )

    def add_to_queue(self):
        output_dir = self.save_entry.get()
        start_time = self.start_time_spinner.get()
        start_secs = self.start_time_spinner.get_total_seconds()
        
        duration = self.duration_time_spinner.get()
        duration_secs = self.duration_time_spinner.get_total_seconds()
        
        gpu_enabled = self.switch.get()
        hdr_to_sdr = self.hdr_switch.get()
        retain_length = self.checkbox.get()
        
        print(
            f"Queued: Start='{start_time}' ({start_secs}s), "
            f"Duration='{duration}' ({duration_secs}s), "
            f"GPU={gpu_enabled}, HDRtoSDR={hdr_to_sdr}, RetainLength={retain_length}, Save='{output_dir}'"
        )