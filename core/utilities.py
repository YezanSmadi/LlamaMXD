import json
import os
import subprocess

import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD
import cv2
from PIL import Image

from core import formats

# Windows-only flag that keeps ffprobe from flashing a console window over
# the GUI. Absent on other platforms, hence the getattr default.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def probe_media(path):
    """Best-effort ffprobe of `path`, as
    `{"container": ".mp4", "video": "H.264 (x264)", "audio": "AAC"}`.

    This is what makes `Source` mean something concrete: it lets the tabs
    default the output container to the input's own, show what a copied
    stream actually is in the Overview rundown, and — on Muxing, which never
    re-encodes — work out which containers the file can legally be remuxed
    into (`formats.containers_for`).

    Entirely optional. Any missing key comes back None, and every failure
    path (no ffmpeg on PATH, unreadable file, odd JSON, a slow probe)
    returns a dict of Nones rather than raising, because nothing here is
    required for the UI to function — it only ever *improves* defaults.

    Runs a subprocess, so callers must keep it off the Tk thread (LlamaGUI
    does it on the same decode worker as the thumbnails)."""
    unknown = {"container": None, "video": None, "audio": None}
    if not path or not os.path.exists(path):
        return unknown
    try:
        completed = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "stream=codec_type,codec_name", "-of", "json", path],
            capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW,
        )
        streams = json.loads(completed.stdout or "{}").get("streams", [])
    except (OSError, ValueError, subprocess.SubprocessError):
        return unknown

    info = dict(unknown)
    extension = os.path.splitext(path)[1].lower()
    if extension in formats.containers():
        info["container"] = extension
    # First stream of each kind wins — the app models exactly one video and
    # one audio stream, so a multi-track source is described by its first.
    for stream in streams:
        kind, name = stream.get("codec_type"), stream.get("codec_name")
        if kind == "video" and info["video"] is None:
            info["video"] = formats.FFPROBE_VIDEO.get(name)
        elif kind == "audio" and info["audio"] is None:
            info["audio"] = formats.FFPROBE_AUDIO.get(name)
    return info


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