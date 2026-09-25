# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""The live keyboard shortcuts: `core.keybinds`' table plus what the user changed, and the Qt
side of matching a key event against it."""
from PySide6.QtCore import QKeyCombination, QObject, Qt, Signal
from PySide6.QtGui import QKeySequence

from core import keybinds

_MODIFIER_KEYS = (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr,
                  Qt.Key_CapsLock, Qt.Key_NumLock, Qt.Key_ScrollLock, Qt.Key_Super_L, Qt.Key_Super_R)


def event_spec(event):
    """A key event as a portable key string ("Left", "Shift+Tab", "F11"), or "" for a bare
    modifier. The keypad's Enter is Return and Shift+Tab (which Qt reports as Backtab) is
    Shift+Tab, so what is captured and what is matched agree."""
    key = event.key()
    if key in _MODIFIER_KEYS or key == Qt.Key_unknown:
        return ""
    mods = event.modifiers() & ~Qt.KeypadModifier & ~Qt.GroupSwitchModifier
    if key == Qt.Key_Enter:
        key = Qt.Key_Return
    elif key == Qt.Key_Backtab:
        key, mods = Qt.Key_Tab, mods | Qt.ShiftModifier
    return QKeySequence(QKeyCombination(mods, Qt.Key(key))).toString(QKeySequence.PortableText)


def canonical(spec):
    """`spec` in Qt's own spelling ("Escape" -> "Esc", "Enter" -> "Return"), or "" if Qt can't read it."""
    seq = QKeySequence(spec, QKeySequence.PortableText)
    if seq.isEmpty() or seq.count() != 1:
        return ""
    text = seq.toString(QKeySequence.PortableText)
    return "Return" if text == "Enter" else text


def _with_shift(spec):
    """`spec` with Shift held, or "" when it already has it (nothing to reverse with)."""
    return "" if "Shift+" in spec else "Shift+" + spec


class KeyMap(QObject):
    """Every action's key and on/off state. `changed` fires after any edit."""

    changed = Signal()

    def __init__(self, stored=None):
        super().__init__()
        self._bindings = keybinds.normalize(stored, key_ok=lambda key: bool(canonical(key)))
        for entry in self._bindings.values():
            entry["key"] = canonical(entry["key"])

    def key(self, action_id):
        return self._bindings[action_id]["key"]

    def enabled(self, action_id):
        return self._bindings[action_id]["enabled"]

    def to_dict(self):
        """What settings.json stores."""
        return {action_id: dict(entry) for action_id, entry in self._bindings.items()}

    def conflict(self, action_id, spec):
        """The other enabled action already using `spec` where `action_id` can fire, or None."""
        return keybinds.conflict(self._bindings, action_id, spec)

    def set_key(self, action_id, spec):
        spec = canonical(spec)
        if spec and spec != self.key(action_id):
            self._bindings[action_id]["key"] = spec
            self.changed.emit()

    def set_enabled(self, action_id, on):
        if bool(on) != self.enabled(action_id):
            self._bindings[action_id]["enabled"] = bool(on)
            self.changed.emit()

    def reset(self):
        """Every shortcut back to its default key and switched on."""
        self._bindings = keybinds.defaults()
        self.changed.emit()

    def matches(self, action_id, event):
        """Does this key press trigger `action_id` (on, and its key)?"""
        return self.enabled(action_id) and event_spec(event) == self.key(action_id)

    def step(self, action_id, event):
        """+1 when the press is the action's key, -1 when it is that key with Shift held (the
        way Tab has always had Shift+Tab), else 0."""
        if not self.enabled(action_id):
            return 0
        spec = event_spec(event)
        if spec == self.key(action_id):
            return 1
        return -1 if spec and spec == _with_shift(self.key(action_id)) else 0
