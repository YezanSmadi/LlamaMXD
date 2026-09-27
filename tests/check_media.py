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
    """Muxing's Add/Edit Subs popup (adds inside the popup, edits language/flags, one undo step,
    cancel, the empty-list em-dash), deselecting/removing every track of a kind acting exactly
    like the old Strip checkbox (video, audio and subtitles alike), the format narrowing to .mkv
    for a picture track, the Chapters page (Select/Deselect All, the Add/Edit Chapters popup,
    remove, undo, the same strip-by-ticks rule) and Encoding's burn-in, as the settings a job
    would get."""
    import core.probe
    import ui.tabs.muxing as muxing_page
    import ui.widgets.chapters as chapters_page
    from ui.widgets.dropdown import NO_OPTION
    from ui.widgets.edit_dialogs import AddEditChaptersDialog, EditSubtitlesDialog
    problems = []

    def expect(label, got, want):
        if got != want:
            problems.append(f"{label}: {got!r}, expected {want!r}")

    messages, toasts = [], []
    chapters_page.show_message = lambda parent, title, message: messages.append(title)
    notify, window.notify = window.notify, lambda text, **k: toasts.append(text)
    subs = fixture("subs.mkv")
    select(subs)
    wait(lambda: pipe("_media_info_path") == subs)

    mux = tabs()[0]
    window.show_tab("Muxing")
    flags = lambda: [(t["codec_name"], t["language"], t["default"], t["forced"]) for t in mux._track_args("subtitle")]
    expect("mux subtitle rows", flags(), [("subrip", "eng", True, False), ("ass", "spa", False, True)])
    expect("the subtitle buttons", [b.text() for b in (mux.subtitle_add_edit_btn, mux.subtitle_remove_btn)],
           ["Add/Edit Subs", "Remove Subs"])

    def run_add_edit(edits):
        """Open Add/Edit Subs, let `edits(dialog)` play the user's part, press OK (or Cancel when
        it returns "Cancel"), and let `_add_edit_subtitles` act on the result."""
        def fake(parent, entries, start_dir=""):
            dialog = EditSubtitlesDialog(parent, entries, start_dir)
            choice = edits(dialog)
            dialog._dismiss(choice or "OK")
            return dialog.result_entries
        muxing_page.edit_subtitles = fake
        mux._add_edit_subtitles()

    def edit_track_two(dialog):
        dialog._on_track_pick("Track 2 (ASS)")
        dialog.language_menu.set("German")
        dialog._on_language_pick("German")
        dialog.default_check.setChecked(True)
        dialog._set_flag("default", dialog.default_check)

    run_add_edit(edit_track_two)
    expect("one default, language edited", flags(), [("subrip", "eng", False, False), ("ass", "ger", True, True)])
    mux._undo("subtitle")
    expect("all of Add/Edit Subs' changes are one undo step", flags(),
           [("subrip", "eng", True, False), ("ass", "spa", False, True)])
    run_add_edit(lambda dialog: (edit_track_two(dialog), "Cancel")[1])
    expect("cancel changes nothing", (flags(), len(mux._history["subtitle"]["undo"])),
           ([("subrip", "eng", True, False), ("ass", "spa", False, True)], 0))
    run_add_edit(lambda dialog: None)
    expect("OK with no edit adds no undo step", len(mux._history["subtitle"]["undo"]), 0)

    # Adding a stream now happens inside the same Add/Edit popup, driven directly rather than
    # through a real file dialog.
    def add_inside_and_ok(dialog):
        dialog._stream_probed(fixture("bar.sup"), core.probe.probe_media(fixture("bar.sup")))
        return "OK"

    run_add_edit(add_inside_and_ok)
    expect("Add inside the popup appends a track", len(mux._tracks["subtitle"]), 3)
    expect("the .sup keeps its own start", mux._track_args("subtitle")[-1]["start_time"], 1.0)
    mux._undo("subtitle")
    expect("undo takes the added track back out too", len(mux._tracks["subtitle"]), 2)

    # An empty list still opens the popup (Add/Edit is always live once a file's loaded — it's
    # also how the first track gets added).
    empty_dialog = EditSubtitlesDialog(window, [])
    expect("an empty list shows an em-dash and greys the fields",
           (empty_dialog.track_menu.value(), empty_dialog.language_menu.isEnabled(),
            empty_dialog.default_check.isEnabled()), (NO_OPTION, False, False))

    mux.format_menu.set(".mp4")
    mux._on_format_change()
    mux._stream_probed("subtitle", fixture("bar.sup"), core.probe.probe_media(fixture("bar.sup")))
    expect("a PGS track narrows the format", (mux.format_menu.value(), mux.format_menu.values()), (".mkv", [".mkv"]))
    expect("its toast", toasts[-1:], ["Container switched to .mkv — .mp4 can't hold PGS subtitles."])
    mux._undo("subtitle")
    expect("undo the .sup: .mp4 is offered again", ".mp4" in mux.format_menu.values(), True)

    # Deselecting or removing every track of a kind is now this app's one "strip" signal — check
    # it directly on video and audio too, since there's no checkbox left to compare against.
    mux._deselect_all("audio")
    settings = mux._gather_settings()
    expect("deselecting every audio track strips it, same as the old checkbox",
           (settings["strip_audio"], settings["audio_tracks"], "Audio" in mux.sub_tab_bar._marked), (True, [], True))
    mux._undo("audio")
    expect("undo restores the audio ticks", mux._gather_settings()["strip_audio"], False)
    mux._remove_streams("video")
    expect("removing every video track strips it the same way",
           (mux._gather_settings()["strip_video"], "Video" in mux.sub_tab_bar._marked), (True, True))
    expect("Add Stream(s) and Undo stay live on an emptied panel",
           (mux.video_add_btn.isEnabled(), mux.video_undo_btn.isEnabled()), (True, True))
    mux._undo("video")
    expect("undo brings the video track back", mux._gather_settings()["strip_video"], False)

    editor = mux.chapter_editor
    rows = lambda: [editor.box._rows[i][0].label.text().split("  ·  ", 1)[1] for i in editor.box.item_ids()]
    expect("source chapters, every one ticked, left to ffmpeg",
           (rows(), editor.box.checked_ids() == editor.box.item_ids(), mux._gather_settings()["chapters"]),
           (["00:00:00  ·  Intro", "00:00:04  ·  Main"], True, None))

    def run_add_edit_chapters(edits):
        """Open Add/Edit Chapters, let `edits(dialog)` play the user's part, press OK, and let
        `_add_edit` act on the result."""
        def fake(parent, chapters, duration):
            dialog = AddEditChaptersDialog(parent, chapters, duration)
            edits(dialog)
            dialog._dismiss("OK")
            return dialog.result_chapters
        chapters_page.add_edit_chapters = fake
        editor._add_edit()

    def add_then_rename_first(dialog):
        dialog.at_spinner.set_seconds(7)
        dialog.new_name_entry.setText("Credits")
        dialog._on_new_typed("Credits")
        dialog._add()
        first_id = editor._chapters[0]["id"]
        dialog._on_chapter_pick(next(label for label, cid in dialog._labels.items() if cid == first_id))
        dialog.name_entry.setText("Opening")
        dialog._on_name("Opening")

    run_add_edit_chapters(add_then_rename_first)
    expect("add + rename in one popup session", rows(),
           ["00:00:00  ·  Opening", "00:00:04  ·  Main", "00:00:07  ·  Credits"])
    expect("the new chapter starts ticked", editor.box.checked_ids(), editor.box.item_ids())
    run_add_edit_chapters(lambda dialog: dialog.time_spinner.set_seconds(9))
    expect("moving the chapter shown re-sorts it", rows(),
           ["00:00:04  ·  Main", "00:00:07  ·  Credits", "00:00:09  ·  Opening"])
    editor.undo_btn.click()

    editor._deselect_all()
    editor.box.set_checked(editor.box.item_ids()[0], True)
    editor._remove()
    expect("remove the ticked one", rows(), ["00:00:04  ·  Main", "00:00:07  ·  Credits"])
    editor.undo_btn.click()
    expect("undo brings the removed chapter back", rows(),
           ["00:00:00  ·  Opening", "00:00:04  ·  Main", "00:00:07  ·  Credits"])

    editor._deselect_all()
    mux._sync_chapters()
    expect("deselecting every chapter strips them, same as the old checkbox",
           (mux._gather_settings()["strip_chapters"], mux._gather_settings()["chapters"],
            "Chapters" in mux.sub_tab_bar._marked), (True, [], True))
    expect("Add/Edit and Undo stay live with nothing ticked",
           (editor.add_edit_btn.isEnabled(), editor.undo_btn.isEnabled()), (True, True))
    editor._select_all()
    mux._sync_chapters()
    expect("select all brings them all back", (mux._gather_settings()["strip_chapters"],
           "Chapters" in mux.sub_tab_bar._marked), (False, False))
    editor._remove()
    expect("removing every chapter strips them the same way", mux._gather_settings()["strip_chapters"], True)
    editor.undo_btn.click()

    add = AddEditChaptersDialog(window, [], 10.0)
    expect("an empty chapter list shows an em-dash and greys Time/Name",
           (add.chapter_menu.value(), add.time_spinner.isEnabled(), add.name_entry.isEnabled(),
            add.add_btn.isEnabled()), (NO_OPTION, False, False, True))
    add.at_spinner.set_seconds(99)
    expect("Add refuses a time past the end",
           (add.add_btn.isEnabled(), add.add_problem.text().startswith("This file is only")), (False, True))
    add.at_spinner.set_seconds(6)
    expect("the new chapter's name follows Add At until one is typed", add.new_name_entry.text(), "Chapter 1")
    add.new_name_entry.setText("Mine")
    add._on_new_typed("Mine")
    add.at_spinner.set_seconds(1)
    expect("a typed name is kept", add.new_name_entry.text(), "Mine")
    add.new_name_entry.setText("  ")
    add._add()
    expect("adding the first chapter into an empty list, a blank name falling back to the default",
           (len(add._order), add.chapter_menu.value() != NO_OPTION, add._chapters[add._current]["title"]),
           (1, True, "Chapter 1"))

    chapters = [{"id": "a", "start": 0.0, "title": "One"}, {"id": "b", "start": 4.5, "title": "Two"}]
    edit = AddEditChaptersDialog(window, chapters, 10.0)
    edit._on_chapter_pick(next(label for label, cid in edit._labels.items() if cid == "b"))
    edit.time_spinner.set_seconds(0)
    expect("editing refuses another chapter's time",
           (edit._button_widgets["OK"].isEnabled(), edit._chapters["b"]["start"]), (False, 4.5))
    edit.time_spinner.set_seconds(4)
    expect("a time left alone keeps its exact start", edit._chapters["b"]["start"], 4.5)
    edit.time_spinner.set_seconds(5)
    expect("a new time replaces it", edit._chapters["b"]["start"], 5.0)

    for row_id in editor.box.item_ids():
        editor.box.set_checked(row_id, False)
    editor._remove()
    expect("nothing ticked: Remove Chapter(s) says so", messages[-1:], ["Nothing to Remove"])

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
    return report("Subtitles / Chapters pages: Add/Edit popups, strip-by-ticks, chapters, burn-in", problems)


def clear_button():
    """Clear: disabled with no file; asks first (Yes clears, No cancels); "Don't ask again"
    skips the dialog from then on; the cleared file leaves no trace in MediaSession."""
    import ui.tabs.media_tab as media_tab_page
    from ui.media_session import _empty_media_info
    problems = []

    def expect(label, got, want):
        if got != want:
            problems.append(f"{label}: {got!r}, expected {want!r}")

    mux = tabs()[0]
    window.show_tab("Muxing")
    window.media.clear_selection()     # a prior check may have left a file selected
    expect("Clear starts disabled with no file", mux.clear_btn.isEnabled(), False)

    path = fixture("sdr.mp4")
    select(path)
    wait(lambda: pipe("_media_info_path") == path)
    expect("Clear enables once a file is selected", mux.clear_btn.isEnabled(), True)

    answers = []
    real_ask = media_tab_page.ask_yes_no_remember
    media_tab_page.ask_yes_no_remember = lambda parent, title, message: answers.pop(0)
    window.confirm_clear_selection = True

    answers.append((False, False))
    mux._on_clear()
    expect("No leaves the file selected", window.media.current_file_path, path)
    expect("No doesn't touch the preference", window.confirm_clear_selection, True)

    answers.append((True, True))
    mux._on_clear()
    expect("Yes clears the selection", window.media.current_file_path, "")
    expect("Yes + Don't ask again turns the preference off", window.confirm_clear_selection, False)
    expect("nothing is left behind",
           (window.media.info, window.media.info_path, window.media.thumb_frames, mux.file_label.text()),
           (_empty_media_info(), None, [], ""))

    select(path)
    wait(lambda: pipe("_media_info_path") == path)
    answers.append((False, False))    # would cancel — must never be read, since the pref is off now
    mux._on_clear()
    expect("with the preference off, Clear acts at once (no dialog read)", window.media.current_file_path, "")
    expect("the pending No/No answer was never consumed", answers, [(False, False)])

    window.confirm_clear_selection = True
    mux._on_clear()
    expect("Clear on an already-empty selection is a no-op (no dialog)", answers, [(False, False)])
    media_tab_page.ask_yes_no_remember = real_ask
    return report("Clear: confirmation, Don't ask again, and a full teardown", problems)


if __name__ == "__main__":
    run()
    overlay_steady()
    spinner_release()
    subtitle_pages()
    clear_button()
    harness.finish()
