import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD
import cv2
from PIL import Image


def extract_video_thumbnails(video_path, count=10):
    """Grabs `count` frames spread evenly across the video's *interior* as
    raw PIL Images (unsized).

    Sample positions are the fractions 1/(count+1) … count/(count+1) of the
    frame count — deliberately interior, so a black/blank first frame and an
    end-credits or fade-out last frame don't get picked.

    Returns a list 1..count long — shorter if the clip is too short to yield
    that many distinct frames or some seeks fail, and falling back to a
    single first-frame read when the container reports no usable frame count
    (some webm / streamed sources). Returns an empty list if nothing decodes
    at all (not a video, unreadable, missing codec)."""
    cap = cv2.VideoCapture(video_path)
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        # No reliable frame count — just take the first frame we can read.
        if total <= 0:
            success, frame = cap.read()
            if not success or frame is None:
                return []
            return [Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))]

        # Even interior sample points; dedupe so a very short clip doesn't
        # ask for the same frame index five times.
        targets = sorted({
            min(total - 1, max(0, round(total * (i + 1) / (count + 1))))
            for i in range(count)
        })

        frames = []
        for target in targets:
            cap.set(cv2.CAP_PROP_POS_FRAMES, target)
            success, frame = cap.read()
            if success and frame is not None:
                frames.append(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        return frames
    finally:
        cap.release()


def extract_video_thumbnail(video_path):
    """Back-compat single-frame helper — the first interior sample, or None."""
    frames = extract_video_thumbnails(video_path, count=1)
    return frames[0] if frames else None