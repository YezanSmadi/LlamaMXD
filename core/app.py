import sys
import customtkinter as ctk
from tkinterdnd2 import TkinterDnD
from PIL import Image

from core.utilities import extract_video_thumbnail
from components.sidebar import Sidebar
from tabs.muxing_tab import MuxingTab
from tabs.encoding_tab import EncodingTab
from tabs.ytdlp_tab import YtDlpTab

class LlamaGUI(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self):
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)

        # Window Setup
        width, height = self.winfo_screenwidth(), self.winfo_screenheight()
        scaled_w, scaled_h = int(width * 0.35), int(height * 0.4)
        x_center = (width - scaled_w) // 2
        y_center = (height - scaled_h) // 2
        self.geometry(f"{scaled_w}x{scaled_h}+{x_center}+{y_center}")
        self.title("LlamaMXD")
        self.iconbitmap("llama.ico")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Grid Config
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # Shared State & Registry
        self.current_file_path = ""
        self.tab_ui_registry = []

        # UI Components
        self.sidebar = Sidebar(master=self, app=self)
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        # Tabs
        self.tabs = {
            "Muxing": MuxingTab(master=self, app=self),
            "Encoding": EncodingTab(master=self, app=self),
            "YT-DLP": YtDlpTab(master=self, app=self),
        }
        self.show_tab("Muxing")

    def register_tab_ui(self, label_widget, img_widget, on_thumbnail=None):
        """Registers a tab's UI controls for batch cross-tab updates."""
        if on_thumbnail is None:
            def on_thumbnail(pil_img, _img_widget=img_widget):
                ctk_img = ctk.CTkImage(
                    light_image=pil_img, dark_image=pil_img, size=(350, 200)
                )
                _img_widget.configure(image=ctk_img, text="")

        self.tab_ui_registry.append(
            {"label": label_widget, "img": img_widget, "on_thumbnail": on_thumbnail}
        )

    def update_global_file(self, file_path):
        """Central method triggered by drop box imports."""
        clean_path = file_path.strip("{}").strip()
        if not clean_path:
            return

        self.current_file_path = clean_path
        raw_thumbnail = extract_video_thumbnail(self.current_file_path)

        for ui in self.tab_ui_registry:
            if ui["label"]:
                ui["label"].configure(text=f"Selected File:\n{self.current_file_path}")
            if raw_thumbnail is not None:
                ui["on_thumbnail"](raw_thumbnail)

        for tab in self.tabs.values():
            if hasattr(tab, "drop_box"):
                tab.drop_box.hide_drop_text()

    def show_tab(self, name):
        for tab in self.tabs.values():
            tab.grid_forget()
        self.tabs[name].grid(row=0, column=1, sticky="nsew", padx=10, pady=10)

    def on_close(self):
        self.destroy()
        sys.exit(0)