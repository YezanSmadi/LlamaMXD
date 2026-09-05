import customtkinter as ctk
from core.app import LlamaGUI
from core.theme import load_settings

if __name__ == "__main__":
    ctk.set_appearance_mode(load_settings()["appearance_mode"])
    app = LlamaGUI()
    app.mainloop()