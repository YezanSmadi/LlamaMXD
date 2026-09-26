# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Scripted interactions, offscreen: picks made the way a click makes them (value + `picked`),
files switched under earlier picks, a fetched link walked through the Downloader's dropdowns.
After each step every dropdown's value, the Save path and the toasts it raised are recorded
(golden): the constraint passes, the snap toasts and the autofill in one trace."""
import os
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import check_commands  # noqa: E402  (the stand-in yt-dlp format list)
import harness  # noqa: E402
from harness import WORK, check_golden, fixture, report  # noqa: E402

from check_ui import settle, window  # noqa: E402
from ui.widgets.dropdown import Dropdown  # noqa: E402
from ui.widgets.toggles import SegmentedButton  # noqa: E402

toasts = []
window.notify = lambda message, go_to_queue=True: toasts.append(message)


def pick(menu, value):
    """A user pick: the value, then the `picked` signal a click emits."""
    menu.set(value)
    menu.picked.emit(value)
    settle(0.05)


def load(path):
    window.media.select_file(path)
    end = time.monotonic() + 30
    while time.monotonic() < end and not (window.media.thumb_frames_path == path and window.media.info_path == path):
        settle(0.1)
    settle(0.3)


def state(tab_name):
    tab = window.tabs[tab_name]
    menus = {name: w.value() for name, w in sorted(vars(tab).items()) if isinstance(w, (Dropdown, SegmentedButton))}
    save = tab.save_entry.text().replace(WORK.replace("\\", "/"), "<work>").replace(WORK, "<work>")
    return {"menus": menus, "save": save}


def run():
    trace = []

    def step(label, tab_name, action):
        del toasts[:]
        action()
        settle(0.2)
        trace.append({"step": label, "toasts": list(toasts), **state(tab_name)})

    enc, mux, dl = (window.tabs[n] for n in ("Encoding", "Muxing", "Downloader"))
    window.show_tab("Encoding")
    step("encoding: load sdr.mp4", "Encoding", lambda: load(fixture("sdr.mp4")))
    step("encoding: container -> .webm (H.264/AAC can't go)", "Encoding", lambda: pick(enc.format_menu, ".webm"))
    step("encoding: container -> .mov", "Encoding", lambda: pick(enc.format_menu, ".mov"))
    step("encoding: resolution 360p", "Encoding", lambda: pick(enc.resolution_menu, "360p"))
    step("encoding: load late.mkv (180p, 25fps)", "Encoding", lambda: load(fixture("late.mkv")))
    step("encoding: fps 25", "Encoding", lambda: pick(enc.fps_menu, "25"))
    step("encoding: load sdr.mp4 (24fps)", "Encoding", lambda: load(fixture("sdr.mp4")))
    step("encoding: encoder H.265", "Encoding", lambda: pick(enc.encoder_menu, "H.265"))
    step("encoding: load multi.mkv", "Encoding", lambda: load(fixture("multi.mkv")))

    window.show_tab("Muxing")
    step("muxing: load sdr.mp4", "Muxing", lambda: load(fixture("sdr.mp4")))
    step("muxing: container -> .mov", "Muxing", lambda: pick(mux.format_menu, ".mov"))
    step("muxing: load vp9.webm (VP9 can't go in .mov)", "Muxing", lambda: load(fixture("vp9.webm")))
    step("muxing: load multi.mkv (H.264 + AAC + Opus)", "Muxing", lambda: load(fixture("multi.mkv")))
    step("muxing: container -> .mp4", "Muxing", lambda: pick(mux.format_menu, ".mp4"))

    def untick_aac():
        mux.audio_box.set_checked("src:0", False)
        mux._track_toggled("audio")
    step("muxing: untick the AAC track (Opus now decides)", "Muxing", untick_aac)
    step("muxing: load hdr.mkv", "Muxing", lambda: load(fixture("hdr.mkv")))

    window.show_tab("Downloader")
    step("downloader: fetched", "Downloader",
         lambda: dl._apply_info("https://www.youtube.com/watch?v=fixture", check_commands.YT_INFO, None))
    step("downloader: codec VP9", "Downloader", lambda: pick(dl.codec_menu, "VP9"))
    step("downloader: resolution top", "Downloader", lambda: pick(dl.quality_menu, dl.quality_menu.values()[1]))
    step("downloader: codec H.264 (that resolution may be gone)", "Downloader", lambda: pick(dl.codec_menu, "H.264"))
    step("downloader: audio codec Opus", "Downloader", lambda: pick(dl.audio_menu, "Opus"))
    step("downloader: mode Audio Only", "Downloader",
         lambda: dl.mode_switch.select(dl.mode_switch._options.index("Audio Only")))
    step("downloader: format .mp3", "Downloader", lambda: pick(dl.format_menu, ".mp3"))
    step("downloader: mode Video Only", "Downloader", lambda: dl.mode_switch.select(dl.mode_switch._options.index("Video Only")))
    return report(f"scripted interactions ({len(trace)} steps: values, save paths, toasts)",
                  check_golden("behaviour", trace))


if __name__ == "__main__":
    run()
    harness.finish()
