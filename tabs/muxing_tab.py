import customtkinter as ctk
from components.drop_box import DropBox

class MuxingTab(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master=master)
        self.app = app

        self.img_label = ctk.CTkLabel(master=self, text="")
        self.img_label.pack(pady=5)

        self.label = ctk.CTkLabel(master=self, text="")
        self.label.pack(pady=(20, 10))

        # DropBox calls the central app updater directly
        self.drop_box = DropBox(master=self, on_file_selected=self.app.update_global_file)

        # Register UI widgets for global syncing
        self.app.register_tab_ui(self.label, self.img_label)