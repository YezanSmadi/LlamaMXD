# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Leaks, offscreen: each user action is repeated after a warm-up, and nothing that should come
and go may grow per round — live QObjects under the window, widgets, top-level windows, threads,
theme-signal connections, scale bindings. (Memory isn't compared: the allocator and one-off caches
make it noisy.) Actions: importing files (video and audio), dialogs, toasts, queue rows and their
details, theme and tab switches, expanding the preview, a dropdown's popup, a Downloader fetch."""
import os
import threading

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import harness  # noqa: E402
from harness import fixture, report  # noqa: E402

from check_ui import app, settle, window  # noqa: E402  (isolated settings + the offscreen MainWindow)
import check_commands  # noqa: E402  (the stand-in yt-dlp format list)
from PySide6.QtCore import QEvent, QObject, QTimer, SIGNAL  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.theme import THEMES  # noqa: E402
from ui import scale  # noqa: E402
from ui import theme as T  # noqa: E402
from ui.widgets import dialogs  # noqa: E402

ROUNDS = 6
window.perform_when_done = lambda *a, **k: None


def counts():
    """What should come and go, after deferred deletes run and dead bindings are swept (a real
    event loop and the next rescale do both; this harness pumps events itself)."""
    for _ in range(3):
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
    scale._prune()
    return {
        "qobjects": len(window.findChildren(QObject)),
        "widgets": len(QApplication.allWidgets()),
        "top-level windows": len(QApplication.topLevelWidgets()),
        "threads": threading.active_count(),
        "theme connections": T.theme.receivers(SIGNAL("changed()")),
        "scale bindings": len(scale._bound),
    }


def close_modal_soon():
    def close():
        modal = QApplication.activeModalWidget()
        if modal is not None:
            modal.reject()
        else:
            QTimer.singleShot(20, close)
    QTimer.singleShot(30, close)


def act_import():
    for name in ("sdr.mp4", "multi.mkv", "audio.m4a"):
        path = fixture(name)
        window.media.select_file(path)
        for _ in range(200):
            if window.media.info_path == path:
                break
            settle(0.05)
        settle(0.3)


def act_dialogs():
    close_modal_soon()
    dialogs.show_message(window, "Leak check", "A message.")
    close_modal_soon()
    dialogs.ask_yes_no(window, "Leak check", "A question?")


def act_toasts():
    for i in range(4):
        window.notify(f"toast {i}", go_to_queue=False)
    settle(3.6)


def act_queue():
    queue = window.tabs["Queue"]
    settings = window.tabs["Encoding"]._gather_settings()
    ids = [queue.add_task("leak check", dict(settings), status="Queued", source_tab="Encoding") for _ in range(3)]
    queue._show_details(ids[0])
    settle(0.2)
    for task_id in ids:
        queue.remove_task(task_id)
    settle(0.2)


def act_theme():
    for name in list(THEMES)[:3] + ["Lemon"]:
        T.theme.set_theme(name)
        settle(0.02)


def act_tabs():
    for name in ("Muxing", "Encoding", "Downloader", "Queue", "Settings", "Encoding"):
        window.show_tab(name)
        settle(0.03)


def act_expand():
    carousel = window.tabs["Encoding"].carousel
    carousel.toggle_expand()
    settle(0.1)
    carousel.toggle_expand()
    settle(0.1)


def act_dropdown():
    menu = window.tabs["Encoding"].format_menu
    menu.showPopup()
    settle(0.2)
    menu.hidePopup()
    settle(0.2)


def act_downloader():
    window.tabs["Downloader"]._apply_info("https://www.youtube.com/watch?v=fixture", check_commands.YT_INFO, None)
    settle(0.1)


ACTIONS = [("importing files", act_import), ("dialogs", act_dialogs), ("toasts", act_toasts),
           ("queue rows + details", act_queue), ("theme switches", act_theme), ("tab switches", act_tabs),
           ("expanding the preview", act_expand), ("a dropdown's popup", act_dropdown),
           ("a Downloader fetch", act_downloader)]


def run():
    window.show_tab("Encoding")
    act_import()
    problems = []
    for label, action in ACTIONS:
        for _ in range(2):                 # warm-up: caches fill once
            action()
        before = counts()
        for _ in range(ROUNDS):
            action()
        after = counts()
        problems += [f"{label}: {key} {before[key]} -> {after[key]} over {ROUNDS} rounds"
                     for key in before if after[key] > before[key]]
    return report(f"no growth when actions repeat ({len(ACTIONS)} actions x {ROUNDS} rounds)", problems)


if __name__ == "__main__":
    run()
    harness.finish()
