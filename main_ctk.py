"""The legacy CustomTkinter UI, kept runnable while the PySide6 port is
reviewed. `python main.py` launches the new UI."""
import customtkinter as ctk
from core.app import LlamaGUI
from core.theme import load_settings

if __name__ == "__main__":
    ctk.set_appearance_mode(load_settings()["appearance_mode"])
    app = LlamaGUI()
    app.mainloop()
