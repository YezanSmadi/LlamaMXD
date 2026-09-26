# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""The selected-file pipeline, offscreen: a file loaded, re-selected from cache, an HDR file's
background tone-mapped render and its cancellation by a file change, an audio-only file, an
unreadable file rejected, a video that decodes to no frames, and the shared scrub position.
After each step the pipeline's state, both media tabs' preview state and any dialog raised are
recorded (golden)."""
import os
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import harness  # noqa: E402
from harness import WORK, check_golden, fixture, report  # noqa: E402

from check_ui import settle, window  # noqa: E402

try:
    import ui.media_session as pipeline  # noqa: E402
except ImportError:                       # before the pipeline left MainWindow
    import ui.app as pipeline  # noqa: E402

dialogs = []
pipeline.show_message = lambda parent, title, message: dialogs.append(title)
probes = []
_probe = pipeline.probe_media
pipeline.probe_media = lambda path: (probes.append(os.path.basename(path)), _probe(path))[1]

media = getattr(window, "media", None)


def select(path):
    (media.select_file if media else window.update_global_file)(path)


def pipe(name):
    """Pipeline state by its current name, whichever side of the refactor this runs on."""
    if media:
        return getattr(media, {"media_info": "info", "_media_info_path": "info_path"}.get(name, name))
    return getattr(window, name)


def tabs():
    return [window.tabs["Muxing"], window.tabs["Encoding"]]


def wait(done, limit=60):
    end = time.monotonic() + limit
    while time.monotonic() < end and not done():
        settle(0.1)
    settle(0.3)


def rel(path):
    return os.path.basename(path) if path else path


def hdr_done():
    """Which tone-mapped frames are rendered (a list with None for the rest, per frame)."""
    return [i for i, f in enumerate(pipe("hdr_frames") or []) if f is not None]


def hdr_rendering():
    render = media._hdr if media else None
    return render["path"] if render and (render["queue"] or render["busy"]) else None


def switch(on):
    """Encoding's HDR->SDR switch, as a click leaves it."""
    enc = window.tabs["Encoding"]
    enc.hdr_switch.setChecked(on)
    enc._on_hdr_toggle()


def state():
    info = pipe("media_info")
    out = {
        "file": rel(pipe("current_file_path")),
        "info_path": rel(pipe("_media_info_path")),
        "info": {k: info.get(k) for k in ("container", "video", "audio", "hdr", "has_video", "has_audio")},
        "frames": len(pipe("thumb_frames") or []), "frames_path": rel(pipe("thumb_frames_path")),
        "hdr_frames": hdr_done(), "hdr_frames_path": rel(pipe("hdr_frames_path")),
        "hdr_rendering": rel(hdr_rendering()),
        "dialogs": list(dialogs), "probes": list(probes),
    }
    for tab in tabs():
        c = tab.carousel
        out[tab.TAB] = {"shown": tab._preview_stack.currentWidget().__class__.__name__,
                        "frames": len(c._frames or []), "index": c._index, "audio_only": c._audio_only,
                        "populated": c._populated, "drop_text": tab.drop_box.prompt.text(),
                        "selected": tab.file_label.text().replace(os.path.dirname(fixture("sdr.mp4")), "<fixtures>")
                        .replace(WORK, "<work>")}
    hdr = pipe("hdr_frames") or []
    out["Encoding"]["tone_mapped_shown"] = sum(
        1 for i, f in enumerate(window.tabs["Encoding"].carousel._frames or []) if i < len(hdr) and f is hdr[i])
    del dialogs[:]
    del probes[:]
    return out


def run():
    trace = []

    def step(label, action):
        action()
        trace.append({"step": label, **state()})

    sdr, hdr, audio = fixture("sdr.mp4"), fixture("hdr.mkv"), fixture("audio.m4a")
    window.show_tab("Encoding")
    step("load sdr.mp4", lambda: (select(sdr), wait(lambda: pipe("thumb_frames_path") == sdr)))
    step("scrub to frame 3", lambda: (tabs()[1].carousel.indexChanged.emit(3), settle(0.2)))
    step("re-select sdr.mp4 (cache hit, no probe)", lambda: (select(sdr), settle(0.5)))
    step("load hdr.mkv (the view and the next two tone-map in the background, then it stops)",
         lambda: (select(hdr), wait(lambda: len(hdr_done()) >= 3, 120), settle(3)))
    step("scrub to frame 6 (6-8 tone-map too)",
         lambda: (tabs()[1].carousel.indexChanged.emit(6), wait(lambda: {6, 7, 8} <= set(hdr_done()), 60), settle(2)))
    step("HDR->SDR on (the rest, and the carousel shows them)",
         lambda: (switch(True), wait(lambda: len(hdr_done()) == 10, 120), settle(0.5)))
    step("HDR->SDR off", lambda: (switch(False), settle(0.3)))
    step("back to sdr.mp4 (the HDR set is dropped)", lambda: (select(sdr), settle(0.5)))

    def cancel_midway():
        select(hdr)
        switch(True)
        wait(lambda: 1 <= len(hdr_done()) < 10, 60)
        select(sdr)
        settle(4)             # long enough for frames already rendering to land and be dropped
    step("hdr.mkv, then sdr.mp4 before its render finishes (cancelled)", cancel_midway)
    step("load audio.m4a (Wave Loop, no frames)",
         lambda: (select(audio), wait(lambda: pipe("_media_info_path") == audio), settle(0.5)))

    junk = os.path.join(WORK, "unreadable.mp4")
    with open(junk, "wb") as f:
        f.write(os.urandom(64 * 1024))
    step("load an unreadable file (rejected)", lambda: (select(junk), wait(lambda: dialogs, 30)))

    real = pipeline.extract_preview_frames
    pipeline.extract_preview_frames = lambda *a, **k: ([], [])
    step("a video that decodes to no frames (No Preview)",
         lambda: (select(fixture("late.mkv")), wait(lambda: dialogs, 30)))
    pipeline.extract_preview_frames = real
    step("then a file with frames (the carousel comes back)",
         lambda: (select(fixture("multi.mkv")), wait(lambda: pipe("thumb_frames_path") == fixture("multi.mkv"))))
    return report(f"selected-file pipeline ({len(trace)} steps)", check_golden("media", trace))


if __name__ == "__main__":
    run()
    harness.finish()
