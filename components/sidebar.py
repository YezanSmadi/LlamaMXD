import customtkinter as ctk
from PIL import Image

class Sidebar(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master=master, width=180, corner_radius=0, fg_color="#FDCA3C")
        self.app = app

        # Title Label
        self.title_label = ctk.CTkLabel(
            master=self,
            text="LlamaMXD",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="black",
        )
        self.title_label.pack(padx=20, pady=(20, 10))

        # Logo
        self.pil_llama = Image.open("llama.png")
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
            master=self, text="YT-DLP", command=lambda: self.app.show_tab("YT-DLP")
        )
        self.btn_tab3.pack(padx=20, pady=10)