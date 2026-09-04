import customtkinter as ctk

class YtDlpTab(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master=master)
        self.app = app

        # Shared File Display (Synced across tabs)
        self.label = ctk.CTkLabel(master=self, text="YT-DLP", font=ctk.CTkFont(size=45, weight="bold"))
        self.label.pack(pady=(20, 10))

        self.img_label = ctk.CTkLabel(master=self, text="")
        self.img_label.pack(pady=5)

        # YT-DLP Specific URL Input Section
        self.url_entry = ctk.CTkEntry(master=self, placeholder_text="Paste Video URL Here", width=350)
        self.url_entry.pack(pady=10)

        self.download_btn = ctk.CTkButton(master=self, text="Download Video")
        self.download_btn.pack(pady=5)

        # Still register labels so switching to YT-DLP shows active file details
        # self.app.register_tab_ui(self.label, self.img_label)