# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""The cursor and hover highlights under a resting pointer, offscreen (`QCursor.setPos` posts a
real mouse move there). Disabled controls show an arrow; a widget that moves out from under a still
pointer takes its cursor and hover state with it (HoverSync, through its real timer); the expanded
preview's hand goes when its chevron does; and nothing is sent while nothing changes."""
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import harness  # noqa: E402
from harness import fixture, report  # noqa: E402

from check_ui import settle, set_scale, window  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QCursor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import ui.hover as hover  # noqa: E402

# The offscreen platform can't say which widget is at a point; the window can.
hover.widget_at = lambda pos: window.childAt(window.mapFromGlobal(pos))
NAMES = {Qt.ArrowCursor: "arrow", Qt.PointingHandCursor: "hand", Qt.IBeamCursor: "ibeam"}


def shown():
    """The cursor Qt has put on the window."""
    return NAMES.get(window.windowHandle().cursor().shape(), "other")


def point_at(widget):
    QCursor.setPos(widget.mapToGlobal(widget.rect().center()))
    settle(0.1)


def run():
    problems = []

    def expect(label, got, want):
        if got != want:
            problems.append(f"{label}: {got!r}, expected {want!r}")

    set_scale(1.0)
    path = fixture("subs.mkv")
    window.media.select_file(path)
    while not (window.media.thumb_frames_path == path and window.media.thumb_frames):
        settle(0.1)
    settle(0.8)
    window.show_tab("Muxing")
    mux = window.tabs["Muxing"]
    window.hover._timer.start()          # offscreen never reports the app as active
    empty = QPoint(window.mapToGlobal(QPoint(0, 0)).x() + 5, window.mapToGlobal(QPoint(0, 0)).y() + 5)

    # A disabled control reads as one: an arrow, on entering it and when it goes under the pointer.
    mux.sub_tab_bar.set_active("Overview")
    settle(0.3)
    for label, widget, owner, enabled in (
            ("save field", mux.save_entry, mux.save_entry, "ibeam"),
            ("time field", mux.start_time_spinner.field, mux.start_time_spinner, "ibeam"),
            ("format dropdown", mux.format_menu, mux.format_menu, "hand")):
        QCursor.setPos(empty)
        settle(0.1)
        point_at(widget)
        expect(f"enabled {label}", shown(), enabled)
        owner.setEnabled(False)
        settle(0.2)
        expect(f"{label} disabled under the pointer", shown(), "arrow")
        QCursor.setPos(empty)
        settle(0.1)
        point_at(widget)
        expect(f"entering the disabled {label}", shown(), "arrow")
        owner.setEnabled(True)
        settle(0.2)

    # Something moves out from under a still pointer, without a hide or a show.
    mux.sub_tab_bar.set_active("Video")
    settle(0.4)
    button = mux.video_add_btn
    point_at(button)
    settle(0.4)
    expect("pointer resting on a button", (shown(), button.underMouse()), ("hand", True))
    x, y = button.x(), button.y()
    button.move(x, y - 80)
    settle(0.4)
    expect("the button moved off the still pointer", (shown(), button.underMouse()), ("arrow", False))
    button.move(x, y)
    settle(0.4)
    expect("...and back under it", (shown(), button.underMouse()), ("hand", True))

    # Nothing to fix, nothing sent: a stable spot, and a pointer that is being dragged.
    sent = []
    real = QApplication.sendEvent
    hover.QApplication.sendEvent = staticmethod(lambda target, event: sent.append(event) or real(target, event))
    try:
        settle(0.6)
        expect("a stable spot: mouse moves sent", len(sent), 0)
        QApplication.setOverrideCursor(Qt.ClosedHandCursor)          # a track drag holds this
        button.move(x, y - 80)
        settle(0.4)
        expect("while a drag holds the cursor: mouse moves sent", len(sent), 0)
        QApplication.restoreOverrideCursor()
        button.move(x, y)
        settle(0.4)
    finally:
        hover.QApplication.sendEvent = real

    # The expanded preview is a hand only over its controls: the last frame's chevron goes, the hand with it.
    mux.sub_tab_bar.set_active("Overview")
    settle(0.3)
    carousel = mux.carousel
    carousel.sync_index(len(carousel._frames) - 2)
    carousel.toggle_expand()
    settle(0.6)
    rect = carousel.rect()
    QCursor.setPos(carousel.mapToGlobal(QPoint(rect.right() - 40, rect.center().y())))
    settle(0.3)
    expect("on the expanded preview's right chevron", shown(), "hand")
    carousel.step(1)
    settle(0.3)
    expect("stepped to the last frame, pointer still", shown(), "arrow")
    carousel.toggle_expand()
    settle(0.3)

    expect("wanted_cursor: a disabled button", hover.wanted_cursor(_disabled_button()), Qt.ArrowCursor)
    return report("cursor and hover state under a resting pointer", problems)


def _disabled_button():
    from ui.widgets.controls import button
    disabled = button("x")
    disabled.setEnabled(False)
    return disabled


if __name__ == "__main__":
    run()
    harness.finish()
