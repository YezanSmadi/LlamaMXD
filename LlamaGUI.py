import sys
import customtkinter as ctk
from tkinter import filedialog
from tkinterdnd2 import DND_FILES, TkinterDnD
from PIL import Image


# 1. Main Window Setup with Drag & Drop capabilities
class TkinterDnDCTk(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.TkdndVersion = TkinterDnD._require(self)


app = TkinterDnDCTk()
app.geometry("850x650")
app.title("LlamaGUI")

# Configure main grid
app.grid_rowconfigure(0, weight=1)
app.grid_columnconfigure(1, weight=1)


def on_close():
    app.destroy()
    sys.exit(0)


app.protocol("WM_DELETE_WINDOW", on_close)


# Helper function to clean paths from TkinterDnD
def process_file_path(file_path, label_widget):
    clean_path = file_path.strip("{}").strip()
    if clean_path:
        label_widget.configure(text=f"Selected File:\n{clean_path}")


def import_file(label_widget):
    path = filedialog.askopenfilename(
        title="Select a File", filetypes=[("All Files", "*.*")]
    )
    process_file_path(path, label_widget)


# 2. Reusable Component: Create a Drag & Drop Box
def create_drop_box(parent_frame, target_label):
    # Outer frame container
    drop_box = ctk.CTkFrame(
        master=parent_frame,
        width=350,
        height=120,
        corner_radius=10,
        border_width=2,
        border_color="#1f538d",
    )
    drop_box.pack(pady=10)
    drop_box.pack_propagate(False)

    # Internal instruction text
    drop_label = ctk.CTkLabel(
        master=drop_box,
        text="Drag & Drop File Here\n— or —",
        font=ctk.CTkFont(size=14),
    )
    drop_label.pack(expand=True)

    # Register Drag & Drop event
    drop_box.drop_target_register(DND_FILES)
    drop_box.dnd_bind(
        "<<Drop>>", lambda event: process_file_path(event.data, target_label)
    )

    return drop_box


# 3. Tab Switcher Function
def show_tab(tab_name):
    tab1_frame.grid_forget()
    tab2_frame.grid_forget()

    if tab_name == "Tab 1":
        tab1_frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
    elif tab_name == "Tab 2":
        tab2_frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)


# 4. Left Sidebar Frame
sidebar = ctk.CTkFrame(master=app, width=180, corner_radius=0)
sidebar.grid(row=0, column=0, sticky="nsew")

title_label = ctk.CTkLabel(
    master=sidebar, text="LlamaMXD", font=ctk.CTkFont(size=20, weight="bold")
)
title_label.pack(padx=20, pady=(20, 10))

# Logo
pil_llama = Image.open("llama.png")
title_llama = ctk.CTkImage(
    light_image=pil_llama, dark_image=pil_llama, size=(140, 140)
)
image_label = ctk.CTkLabel(master=sidebar, image=title_llama, text="")
image_label.pack(pady=10)

btn_tab1 = ctk.CTkButton(
    master=sidebar, text="Muxing", command=lambda: show_tab("Tab 1")
)
btn_tab1.pack(padx=20, pady=10)

btn_tab2 = ctk.CTkButton(
    master=sidebar, text="Encoding", command=lambda: show_tab("Tab 2")
)
btn_tab2.pack(padx=20, pady=10)


# 5. Tab 1 Content Frame (Muxing)
tab1_frame = ctk.CTkFrame(master=app)

tab1_label = ctk.CTkLabel(
    master=tab1_frame, text="No file selected", font=ctk.CTkFont(size=14)
)
tab1_label.pack(pady=(20, 10))

# Add Drop Box & Import Button to Tab 1
create_drop_box(tab1_frame, tab1_label)

tab1_import_btn = ctk.CTkButton(
    master=tab1_frame,
    text="Import File to Tab 1",
    command=lambda: import_file(tab1_label),
)
tab1_import_btn.pack(pady=10)


# 6. Tab 2 Content Frame (Encoding)
tab2_frame = ctk.CTkFrame(master=app)

tab2_label = ctk.CTkLabel(
    master=tab2_frame, text="No file selected", font=ctk.CTkFont(size=14)
)
tab2_label.pack(pady=(20, 10))

# Add Drop Box & Import Button to Tab 2
create_drop_box(tab2_frame, tab2_label)

tab2_import_btn = ctk.CTkButton(
    master=tab2_frame,
    text="Import File to Tab 2",
    command=lambda: import_file(tab2_label),
)
tab2_import_btn.pack(pady=10)


# Start on Tab 1
show_tab("Tab 1")
app.mainloop()
