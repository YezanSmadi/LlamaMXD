import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD
import cv2
from PIL import Image

def extract_video_thumbnail(video_path, max_size=(1920, 1080)):
    cap = cv2.VideoCapture(video_path)
    success, frame = cap.read()
    cap.release()

    if not success or frame is None:
        return None

    orig_h, orig_w, _ = frame.shape
    max_w, max_h = max_size
    scale = min(max_w / orig_w, max_h / orig_h)

    if scale < 1.0:
        new_w = int(orig_w * scale)
        new_h = int(orig_h * scale)
    else:
        new_w, new_h = orig_w, orig_h

    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(frame_rgb)

    return ctk.CTkImage(
        light_image=pil_img,
        dark_image=pil_img,
        size=(new_w, new_h)
    )