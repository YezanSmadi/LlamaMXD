import customtkinter as ctk
from tkinter import filedialog
from tkinterdnd2 import DND_FILES

from core.theme import get_active_theme

class DropBox(ctk.CTkFrame):
    def __init__(self, master, on_file_selected, height=280):
        super().__init__(
            master=master,
            width=350,
            height=height,
            corner_radius=10,
            border_width=2,
            border_color=get_active_theme()["primary"],
        )
        self.on_file_selected = on_file_selected
        self.pack(pady=10)
        self.pack_propagate(False)

        self.content_frame = ctk.CTkFrame(master=self, fg_color="transparent")
        self.content_frame.pack(expand=True)

        # Saved as an instance variable (self.) so we can unpack it later
        self.drop_label = ctk.CTkLabel(
            master=self.content_frame,
            text="Drag & Drop File Here\n\n— or —\n",
            font=ctk.CTkFont(size=14),
        )
        self.drop_label.pack(pady=(0, 10))

        self.import_btn = ctk.CTkButton(
            master=self.content_frame, text="Browse File", command=self.browse_file
        )
        self.import_btn.pack()

        # Event Binding
        for widget in (self, self.content_frame, self.drop_label):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", lambda e: self.on_file_selected(e.data))
            widget.bind("<Double-Button-1>", lambda e: self.browse_file())

    def hide_drop_text(self):
            # Removes the outer box border and hides the drop prompt.
            self.drop_label.pack_forget()
            # Strip away borders and background
            self.configure(border_width=0, fg_color="transparent", height=40)

    def browse_file(self):
        selected = filedialog.askopenfilename(
            title="Select a File",
            filetypes=[
                ("Media files",
                 "*.mp4 *.mkv *.mov *.webm *.avi *.m4v *.mxf "
                 "*.mp3 *.m4a *.aac *.flac *.wav *.opus *.ogg *.wma *.aiff"),
                ("All files", "*.*"),
            ],
        )
        if selected:
            self.on_file_selected(selected)