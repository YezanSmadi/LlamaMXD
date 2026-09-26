# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Finds the external tools (`ffmpeg`, `ffprobe`, `yt-dlp`, `deno`) as absolute paths, cached.

Search order: beside the frozen app's exe or in a `dependables/` folder next to it, then the
repo's own `dependables/` (running from source), then PATH. Absolute paths matter: yt-dlp
silently ignores a relative `--js-runtimes` path, and a bare `ffmpeg` is left to Windows'
search order."""

import functools
import os
import shutil
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BUNDLE_DIR_NAME = "dependables"
_EXE_SUFFIX = ".exe" if os.name == "nt" else ""


def _search_dirs():
    """The bundled-tool folders to check, most specific first."""
    dirs = []
    if getattr(sys, "frozen", False):
        app_dir = os.path.dirname(os.path.abspath(sys.executable))
        dirs += [app_dir, os.path.join(app_dir, _BUNDLE_DIR_NAME)]
    dirs.append(os.path.join(_REPO_ROOT, _BUNDLE_DIR_NAME))
    return dirs


@functools.lru_cache(maxsize=None)
def find_tool(name):
    """Absolute path to tool `name` ("ffmpeg", "yt-dlp", ...), or None when
    it's neither bundled nor on PATH."""
    for folder in _search_dirs():
        candidate = os.path.join(folder, name + _EXE_SUFFIX)
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)
    found = shutil.which(name)
    return os.path.abspath(found) if found else None


def tool_path(name):
    """What to put in an argv for tool `name`: its absolute path, or the bare name when it can't
    be found, so launching still raises the usual FileNotFoundError callers handle."""
    return find_tool(name) or name


def tool_dir(name):
    """The folder holding tool `name`, or None: what yt-dlp's `--ffmpeg-location` wants."""
    path = find_tool(name)
    return os.path.dirname(path) if path else None
