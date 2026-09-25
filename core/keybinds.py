# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""The app's remappable keyboard shortcuts (Settings' "Shortcuts" page): which actions exist, their
default keys and where each one applies. Plain data and string keys in Qt's portable form
("Left", "Space", "F11", "Ctrl+F") — nothing here imports Qt, so `ui/keymap.py` does the
key-event side. Stored in settings.json as `{action id: {"key": str, "enabled": bool}}`."""
from collections import namedtuple

# `contexts` say where an action can fire. Two enabled actions may share a key only when they
# can never fire together — Up/Down mean "previous/next tab" in the window and "previous/next
# option" inside an open dropdown, so both pairs keep their arrows.
WINDOW, DROPDOWN = "window", "dropdown"

Action = namedtuple("Action", "id name key contexts tip")

ACTIONS = (
    Action("preview_prev", "Scroll Preview Left", "Left", (WINDOW,),
           "Steps the preview to the previous frame (Muxing and Encoding)."),
    Action("preview_next", "Scroll Preview Right", "Right", (WINDOW,),
           "Steps the preview to the next frame (Muxing and Encoding)."),
    Action("expand_preview", "Expand Preview", "F", (WINDOW,),
           "Blows the preview up over the whole window; press it again to shrink it back."),
    Action("collapse_preview", "Exit Expanded Preview", "Esc", (WINDOW,),
           "Shrinks an expanded preview back to its normal size."),
    Action("toggle_queue", "Start / Pause Queue", "Space", (WINDOW,),
           "Starts the queue, or pauses it while it runs (Queue tab)."),
    Action("tab_prev", "Previous Tab", "Up", (WINDOW,),
           "Goes to the tab above in the sidebar. Not while the preview is expanded."),
    Action("tab_next", "Next Tab", "Down", (WINDOW,),
           "Goes to the tab below in the sidebar. Not while the preview is expanded."),
    Action("focus_next", "Select Next Option", "Tab", (WINDOW,),
           "Selects the first button, box or dropdown on the tab, then moves on to the next one "
           "each press. Hold Shift to go backwards."),
    Action("activate", "Press Selected Option", "Return", (WINDOW, DROPDOWN),
           "Clicks the selected button or checkbox, opens the selected dropdown, or picks the "
           "highlighted option of an open dropdown."),
    Action("dropdown_prev", "Dropdown — Previous Option", "Up", (DROPDOWN,),
           "Moves up the list while a dropdown is open."),
    Action("dropdown_next", "Dropdown — Next Option", "Down", (DROPDOWN,),
           "Moves down the list while a dropdown is open."),
    Action("fullscreen", "Fullscreen Window", "F11", (WINDOW,),
           "Fills the screen; press it again to go back. In Borderless mode this is Settings' "
           "Fullscreen box."),
)

BY_ID = {a.id: a for a in ACTIONS}


def defaults():
    """Every action at its default key, all switched on."""
    return {a.id: {"key": a.key, "enabled": True} for a in ACTIONS}


def normalize(stored, key_ok=lambda key: bool(key)):
    """A stored `keybinds` value made safe: every action present, unknown ids dropped, and a
    key that is missing / not a string / rejected by `key_ok` (the UI passes a check that Qt can
    read it) put back to the default. A hand-edited settings.json can't break the shortcuts."""
    result = defaults()
    if not isinstance(stored, dict):
        return result
    for action_id, entry in stored.items():
        if action_id not in result or not isinstance(entry, dict):
            continue
        key = entry.get("key")
        if isinstance(key, str) and key_ok(key):
            result[action_id]["key"] = key
        if isinstance(entry.get("enabled"), bool):
            result[action_id]["enabled"] = entry["enabled"]
    return result


def conflict(bindings, action_id, key):
    """The other, enabled action that already uses `key` where `action_id` can fire — or None."""
    mine = set(BY_ID[action_id].contexts)
    for other in ACTIONS:
        if other.id == action_id or not bindings[other.id]["enabled"]:
            continue
        if bindings[other.id]["key"] == key and mine & set(other.contexts):
            return other
    return None
