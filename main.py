import customtkinter as ctk
from core.app import LlamaGUI

if __name__ == "__main__":
    ctk.set_appearance_mode("system")
    app = LlamaGUI()
    app.mainloop()