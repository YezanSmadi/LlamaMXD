# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""The selected-file pipeline, offscreen: a file loaded, re-selected from cache, an HDR file's
background tone-mapped render and its cancellation by a file change, an audio-only file, an
unreadable file rejected, a video that decodes to no frames, and the shared scrub position.
After each step the pipeline's state, both media tabs' preview state and any dialog raised are
recorded (golden). Then the loading spinner's frames being released once it's hidden, and the
Subtitles / Chapters pages driven on a file with both."""
import os
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import harness  # noqa: E402
from harness import WORK, check_golden, fixture, report  # noqa: E402

import ui.widgets.panels as panels  # noqa: E402

# The spinner's release waits, shortened (read when its timers are made, at the first hide).
panels._RELEASE_GRACE_MS, panels._RELEASE_IDLE_MS = 1_000, 3_000

from check_ui import set_scale, settle, window  # noqa: E402

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


def overlay_steady():
    """Tone-mapped frames landing swap the pictures only: the chevrons stay lit and the
    position holds (they used to vanish at each frame until the pointer re-entered)."""
    problems = []
    window.show_tab("Encoding")
    enc = tabs()[1]
    select(fixture("hdr.mkv"))
    wait(lambda: enc.carousel.isVisible() and enc.hdr_switch.isEnabled(), 60)
    enc.carousel.step(5)
    enc.carousel.enterEvent(None)             # the pointer on the preview: chevrons fade in
    settle(0.3)
    switch(True)
    low, seen = 1.0, set()
    end = time.monotonic() + 60
    while time.monotonic() < end and len(hdr_done()) < 10:
        settle(0.005)
        low, seen = min(low, enc.carousel._arrow_alpha), seen | {enc.carousel.current_index()}
    if low < 1.0:
        problems.append(f"the chevrons dimmed to {low:.2f} while tone-mapped frames landed")
    if seen != {5}:
        problems.append(f"the position moved while frames landed: {sorted(seen)}")
    switch(False)
    return report("the preview's overlay holds while tone-mapped frames land", problems)


def spinner_release():
    """No spinner plays behind an expanded preview. Frames of another size go after the grace,
    all but the first few after the idle time; the first ones stay, at the size needed."""
    problems = []
    window.show_tab("Muxing")
    carousel = window.tabs["Muxing"].carousel
    select(fixture("sdr.mp4"))
    wait(lambda: carousel.isVisible())
    carousel.toggle_expand()
    settle(0.5)
    if panels.LoadingSpinner._showing:
        problems.append("the drop box's spinner plays behind an expanded preview")
    carousel.toggle_expand()
    settle(0.3)
    window.tabs["Muxing"].clear_selected_file()      # the drop box, not a loaded file's carousel
    box = window.tabs["Muxing"].drop_box

    def sizes():
        return [f[0].width() if f else None for f in panels._LOADING.get("frames") or []]

    def expect(label, keep_all):
        need, got = panels._LOADING.get("need"), sizes()
        if got[: panels._LOADING_KEEP] != [need] * panels._LOADING_KEEP:
            problems.append(f"{label}: the first frames aren't all {need}px: {got[:panels._LOADING_KEEP]}")
        rest = got[panels._LOADING_KEEP:]
        if keep_all and rest != [need] * len(rest):
            problems.append(f"{label}: frames were released too early: {sorted(set(map(str, rest)))}")
        if not keep_all and any(rest):
            problems.append(f"{label}: {sum(map(bool, rest))} frames past the first few were kept")

    set_scale(2.0)
    box.collapse()
    settle(0.1)
    if not box.spinner.isVisible():
        return report("the loading spinner's frames are released when hidden", ["the spinner never showed"])
    settle(4)                                    # the whole loop decodes at the big size
    box.reset()
    set_scale(1.0)
    settle(2)
    expect("big frames, 1s past the grace after shrinking", keep_all=False)
    box.collapse()
    settle(4)                                    # the whole loop decodes as it plays (2.4s)
    box.reset()
    settle(0.5)
    expect("frames at the size needed, before the idle time", keep_all=True)
    settle(3)
    expect("after the idle time", keep_all=False)
    return report("the loading spinner's frames are released when hidden", problems)


def subtitle_pages():
    """Muxing's subtitle editor (language, one default, undo), the format narrowing to .mkv for a
    picture track, the chapter list (add, rename, remove, undo) and Encoding's burn-in, as the
    settings a job would get."""
    import core.probe
    import ui.widgets.chapters as chapters_page
    problems = []

    def expect(label, got, want):
        if got != want:
            problems.append(f"{label}: {got!r}, expected {want!r}")

    answers, messages, toasts = [], [], []
    chapters_page.ask_text = lambda *a, **k: answers.pop(0)
    chapters_page.show_message = lambda parent, title, message: messages.append(title)
    notify, window.notify = window.notify, lambda text, **k: toasts.append(text)
    subs = fixture("subs.mkv")
    select(subs)
    wait(lambda: pipe("_media_info_path") == subs)

    mux = tabs()[0]
    window.show_tab("Muxing")
    flags = lambda: [(t["codec_name"], t["language"], t["default"], t["forced"]) for t in mux._track_args("subtitle")]
    expect("mux subtitle rows", flags(), [("subrip", "eng", True, False), ("ass", "spa", False, True)])
    mux._on_subtitle_track_pick("Track 2")
    mux._on_subtitle_language_pick("German")
    mux.subtitle_default_check.setChecked(True)
    mux._set_subtitle_flag("default")
    expect("one default, language edited", flags(), [("subrip", "eng", False, False), ("ass", "ger", True, True)])
    mux._undo("subtitle")
    expect("undo the default", flags(), [("subrip", "eng", True, False), ("ass", "ger", False, True)])
    mux.format_menu.set(".mp4")
    mux._on_format_change()
    mux._stream_probed("subtitle", fixture("bar.sup"), core.probe.probe_media(fixture("bar.sup")))
    expect("a PGS track narrows the format", (mux.format_menu.value(), mux.format_menu.values()), (".mkv", [".mkv"]))
    expect("its toast", toasts[-1:], ["Container switched to .mkv — .mp4 can't hold PGS subtitles."])
    expect("the .sup keeps its own start", mux._track_args("subtitle")[-1]["start_time"], 1.0)
    mux._undo("subtitle")
    expect("undo the .sup: .mp4 is offered again", ".mp4" in mux.format_menu.values(), True)

    editor = mux.chapter_editor
    rows = lambda: [editor.box._rows[i][0].label.text().split("  ·  ", 1)[1] for i in editor.box.item_ids()]
    expect("source chapters, left to ffmpeg", (rows(), mux._gather_settings()["chapters"]),
           (["00:00:00  ·  Intro", "00:00:04  ·  Main"], None))
    editor.at_spinner.set_seconds(7)
    answers.append("Credits")
    editor._add()
    editor.box.set_checked(editor.box.item_ids()[0], True)
    answers.append("Opening")
    editor._rename()
    expect("add + rename", rows(), ["00:00:00  ·  Opening", "00:00:04  ·  Main", "00:00:07  ·  Credits"])
    editor._remove()
    expect("remove the ticked one", rows(), ["00:00:04  ·  Main", "00:00:07  ·  Credits"])
    editor.undo_btn.click()
    expect("undo", mux._gather_settings()["chapters"], [
        {"start": 0.0, "title": "Opening"}, {"start": 4.0, "title": "Main"}, {"start": 7.0, "title": "Credits"}])
    editor.at_spinner.set_seconds(99)
    editor._add()
    expect("a chapter past the end is refused", messages[-1:], ["Past the End"])

    enc = tabs()[1]
    window.show_tab("Encoding")
    expect("encoding tracks", enc.sub_track_menu.values(), ["Track 1 (SRT)", "Track 2 (ASS)"])
    enc.sub_burn_check.setChecked(True)
    enc._on_burn_toggle()
    settings = enc._gather_settings()
    expect("burned track", (settings["burn_subtitle"] or {}).get("index"), 0)
    expect("the rest stay tracks", [t["index"] for t in settings["subtitle_tracks"]], [1])
    expect("a burned track has no language of its own", enc.sub_language_menu.isEnabled(), False)
    enc.strip_video_check.setChecked(True)
    enc._on_control_change()
    expect("no burn-in without video", (enc._gather_settings()["burn_subtitle"], enc.sub_burn_check.isEnabled()),
           (None, False))
    enc.strip_video_check.setChecked(False)
    enc._on_control_change()
    window.notify = notify
    return report("Subtitles / Chapters pages: editor, narrowing, chapters, burn-in", problems)


if __name__ == "__main__":
    run()
    overlay_steady()
    spinner_release()
    subtitle_pages()
    harness.finish()
