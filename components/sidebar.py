from datetime import datetime

import customtkinter as ctk
from PIL import Image

from core.theme import get_active_theme

class Sidebar(ctk.CTkFrame):
    def __init__(self, master, app):
        theme = get_active_theme()
        super().__init__(master=master, width=180, corner_radius=0, fg_color=theme["primary"])
        self.app = app

        # Title Label
        self.title_label = ctk.CTkLabel(
            master=self,
            text="LlamaMXD",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=theme["primary_text"],
        )
        self.title_label.pack(padx=20, pady=(20, 10))

        # Logo
        self.pil_llama = Image.open("assets/llama.png")
        self.title_llama = ctk.CTkImage(
            light_image=self.pil_llama, dark_image=self.pil_llama, size=(140, 140)
        )
        self.image_label = ctk.CTkLabel(master=self, image=self.title_llama, text="")
        self.image_label.pack(pady=10)

        # Tab Navigation Buttons (Calls app.show_tab)
        self.btn_tab1 = ctk.CTkButton(
            master=self, text="Muxing", command=lambda: self.app.show_tab("Muxing")
        )
        self.btn_tab1.pack(padx=20, pady=10)

        self.btn_tab2 = ctk.CTkButton(
            master=self, text="Encoding", command=lambda: self.app.show_tab("Encoding")
        )
        self.btn_tab2.pack(padx=20, pady=10)

        self.btn_tab3 = ctk.CTkButton(
            master=self, text="Downloader", command=lambda: self.app.show_tab("Downloader")
        )
        self.btn_tab3.pack(padx=20, pady=10)

        self.btn_tab4 = ctk.CTkButton(
            master=self, text="Queue", command=lambda: self.app.show_tab("Queue")
        )
        self.btn_tab4.pack(padx=20, pady=10)

        # Settings + footer anchor to the sidebar's bottom edge via
        # side="bottom", and must be packed BEFORE the expanding spacer below.
        # Tk carves cavity space in .pack() *call order*, independent of
        # side — an expand=True widget claims whatever's left at the moment
        # it's packed, so packing it first would leave nothing for anything
        # packed after it, regardless of side. (Same call-order convention as
        # controls_frame/top_container in EncodingTab.) footer_label is
        # packed first so it claims the true bottom edge; btn_settings packs
        # second, landing just above it.
        self.footer_label = ctk.CTkLabel(
            master=self,
            text=f"{datetime.now().year} Yezan Smadi     v0.5.0-alpha.6",
            font=ctk.CTkFont(size=10),
            text_color=theme["primary_text"],
        )
        self.footer_label.pack(side="bottom", pady=(0, 10))

        self.btn_settings = ctk.CTkButton(
            master=self, text="Settings", command=lambda: self.app.show_tab("Settings")
        )
        self.btn_settings.pack(side="bottom", padx=20, pady=(10, 4))

        # Spacer: consumes whatever cavity remains between the tab group above
        # and Settings/footer below, visually separating them.
        self.spacer = ctk.CTkFrame(master=self, fg_color="transparent")
        self.spacer.pack(fill="both", expand=True)

        # Lookup used by the app to align the active-tab accent strip with
        # whichever button is currently selected.
        self.buttons = {
            "Muxing": self.btn_tab1,
            "Encoding": self.btn_tab2,
            "Downloader": self.btn_tab3,
            "Queue": self.btn_tab4,
            "Settings": self.btn_settings,
        }