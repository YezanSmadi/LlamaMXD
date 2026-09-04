import customtkinter as ctk
from tkinter import filedialog
from components.drop_box import DropBox
from components.time_spinner import TimeSpinner

class EncodingTab(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master=master)
        self.app = app

        # --- Shared File Display & DropBox ---
        self.label = ctk.CTkLabel(master=self, text="")
        self.label.pack(pady=(10, 5))

        self.img_label = ctk.CTkLabel(master=self, text="")
        self.img_label.pack(pady=5)

        self.drop_box = DropBox(master=self, on_file_selected=self.app.update_global_file)

        # Register controls for cross-tab sync
        self.app.register_tab_ui(self.label, self.img_label)

        # --- Encoding Controls Container ---
        self.controls_frame = ctk.CTkFrame(master=self, fg_color="transparent")
        self.controls_frame.pack(fill="x", padx=20, pady=10)

        # 1. Checkbox
        self.checkbox = ctk.CTkCheckBox(master=self.controls_frame, text="Enable Custom Processing")
        self.checkbox.pack(anchor="w", pady=(5, 5))

        # 2. Time Spinner (Under Checkbox)
        self.time_spinner = TimeSpinner(master=self.controls_frame, initial_seconds=0)
        self.time_spinner.pack(anchor="w", pady=(0, 10), padx=(25, 0))

        # 3. Switch
        self.switch = ctk.CTkSwitch(master=self.controls_frame, text="Hardware Acceleration (GPU)")
        self.switch.pack(anchor="w", pady=5)

        # 4. Save Location Section (Input Box + Browse Button)
        self.save_frame = ctk.CTkFrame(master=self.controls_frame, fg_color="transparent")
        self.save_frame.pack(fill="x", pady=10)

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

        # 5. Queue Button
        self.queue_btn = ctk.CTkButton(
            master=self.controls_frame, 
            text="Queue Task", 
            fg_color="#FDCA3C", 
            text_color="black",
            hover_color="#e0b234",
            command=self.add_to_queue
        )
        self.queue_btn.pack(fill="x", pady=(15, 5))

    def select_save_location(self):
        #Opens a directory chooser dialog and inserts the folder path
        folder = filedialog.askdirectory(title="Select Save Directory")
        if folder:
            self.save_entry.delete(0, "end")
            self.save_entry.insert(0, folder)

    def add_to_queue(self):
        #Action handler when clicking Queue.
        output_dir = self.save_entry.get()
        selected_preset = self.spinner.get()
        gpu_enabled = self.switch.get()
        custom_processing = self.checkbox.get()
        
        print(f"Queued: Preset='{selected_preset}', GPU={gpu_enabled}, Custom={custom_processing}, Save='{output_dir}'")