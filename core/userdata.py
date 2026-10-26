# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Where the user's own files (settings.json, presets.json) live: beside main.py when run from source,
`%LOCALAPPDATA%/LlamaMXD` in an installed (frozen) build, which is writable and survives an update."""
import os
import sys

from core import llamalog

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_frozen():
    """Whether this is a packaged build rather than a source checkout."""
    return bool(getattr(sys, "frozen", False))


def data_dir():
    """The folder holding the user's files (made if needed, best-effort)."""
    if not is_frozen():
        return _REPO_ROOT
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    folder = os.path.join(base, "LlamaMXD")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as exc:
        llamalog.get("settings").warning("couldn't create %s: %s", folder, exc)
    return folder


def user_file(name):
    """Full path of the user file `name` in the data folder (never beside the exe)."""
    return os.path.join(data_dir(), name)
