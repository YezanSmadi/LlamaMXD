import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD
import cv2
from PIL import Image

def extract_video_thumbnail(video_path):
    """Extracts the first frame of a video as a raw PIL Image (unsized)."""
    cap = cv2.VideoCapture(video_path)
    success, frame = cap.read()
    cap.release()

    if not success or frame is None:
        return None

    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return Image.fromarray(frame_rgb)