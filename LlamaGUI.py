import sys
import customtkinter as ctk
from tkinter import filedialog
from tkinterdnd2 import DND_FILES, TkinterDnD
import cv2
from PIL import Image


#Main Window Setup with Drag & Drop capabilities
class TkinterDnDCTk(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.TkdndVersion = TkinterDnD._require(self)



ctk.set_appearance_mode("system")

app = TkinterDnDCTk()
width, height = app.winfo_screenwidth(), app.winfo_screenheight()
scaled_width = int(width * .35)
scaled_height = int(height * .4)
X_center = (width - scaled_width)  // 2
Y_center = (height - scaled_height) // 2
app.geometry(f"{scaled_width}x{scaled_height}+{X_center}+{Y_center}") 
app.title("LlamaMXD")
app.iconbitmap("llama.ico")
app.resizable(False, False)

app.grid_rowconfigure(0, weight=1) # Configure main grid
app.grid_columnconfigure(1, weight=1)


# Close behavior
def on_close():
    app.destroy()
    sys.exit(0)


app.protocol("WM_DELETE_WINDOW", on_close)

# Globale file path
current_file_path = ""





# Update and clean file path for Encoding and Muxing
def process_file_path(file_path, label_widget, img_label):
    current_file_path = file_path.strip("{}").strip()
    if current_file_path:
        label_widget.configure(text=f"Selected File:\n{current_file_path}")

    thumbnail = extract_video_thumbnail(current_file_path, max_size=(350, 200))
    if thumbnail:
        img_label.configure(image=thumbnail, text="")


def import_file(label_widget, img_label):
    current_file_path = filedialog.askopenfilename(
        title="Select a File", filetypes=[("All Files", "*.*")]
    )
    if current_file_path:
        process_file_path(current_file_path, label_widget, img_label)


# Create a Drag & Drop Box
def create_drop_box(parent_frame, target_label, img_label):
    # Outer frame container
    drop_box = ctk.CTkFrame(
        master=parent_frame,
        width=350,
        height=250,
        corner_radius=10,
        border_width=2,
        border_color="#FDCA3C",
    )
    drop_box.pack(pady=10)
    drop_box.pack_propagate(False)

    content_frame = ctk.CTkFrame(master=drop_box, fg_color="transparent")
    content_frame.pack(expand=True)  # Centers the entire group inside drop_box

    drop_label = ctk.CTkLabel(
        master=content_frame,
        text="Drag & Drop File Here\n\n— or —\n",
        font=ctk.CTkFont(size=14),
    )
    drop_label.pack(pady=(0, 10))  # Small gap below the text

    import_btn = ctk.CTkButton(
        master=content_frame,
        text="Browse File",
        command=lambda: import_file(target_label, img_label),
    )
    import_btn.pack(pady=(0, 0))

    for widget in (drop_box, content_frame, drop_label):  # Register Drag & Drop events
        widget.drop_target_register(DND_FILES)
        widget.dnd_bind(
            "<<Drop>>",
            lambda event: process_file_path(
                event.data, target_label, img_label)
        )
        widget.bind(
            "<Double-Button-1>", 
            lambda event: import_file(
                target_label, img_label)
                    )


    return drop_box


# Tab Switcher
def show_tab(tab_name):
    tab1_frame.grid_forget()
    tab2_frame.grid_forget()
    tab3_frame.grid_forget()

    if tab_name == "Tab 1":
        tab1_frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
    elif tab_name == "Tab 2":
        tab2_frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
    elif tab_name == "Tab 3":
        tab3_frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)


# Left Sidebar Frame
sidebar = ctk.CTkFrame(master=app, width=180, corner_radius=0, fg_color="#FDCA3C")
sidebar.grid(row=0, column=0, sticky="nsew")

title_label = ctk.CTkLabel(
    master=sidebar, text="LlamaMXD", font=ctk.CTkFont(size=20, weight="bold"), text_color="black"
)
title_label.pack(padx=20, pady=(20, 10))
pil_llama = Image.open("llama.png")  # Logo
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

btn_tab3 = ctk.CTkButton(
    master=sidebar, text="YT-DLP", command=lambda: show_tab("Tab 3")
)
btn_tab3.pack(padx=20, pady=10)


# Tab 1: Muxing
tab1_frame = ctk.CTkFrame(master=app)
tab1_label = ctk.CTkLabel(
    master=tab1_frame, text=""
)
tab1_label.pack(pady=(20, 10))
tab1_img_label = ctk.CTkLabel(master=tab1_frame, text="")
tab1_img_label.pack(pady=5)
create_drop_box(tab1_frame, tab1_label, tab1_img_label)


# Tab 2: Encoding
tab2_frame = ctk.CTkFrame(master=app)
tab2_label = ctk.CTkLabel(
    master=tab2_frame, text=""
)
tab2_label.pack(pady=(20, 10))
tab2_img_label = ctk.CTkLabel(master=tab2_frame, text="")
tab2_img_label.pack(pady=5)
create_drop_box(tab2_frame, tab2_label, tab2_img_label)


# Tab 3: YT-DLP
tab3_frame = ctk.CTkFrame(master=app)
tab3_label = ctk.CTkLabel(
    master=tab3_frame, text="Nothin but us birds", font=ctk.CTkFont(size=14)
)
tab3_label.pack(pady=(20, 10))


show_tab("Tab 1")  # Launch on Tab 1
app.mainloop()
