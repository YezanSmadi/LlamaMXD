"""Finds the external command-line tools this app launches -- `ffmpeg`,
`ffprobe`, `yt-dlp` and `deno` -- as absolute paths.

Releases ship all of them beside the app (the setup wizard copies them in),
so a bundled copy always wins over whatever happens to be on PATH. Search
order, first hit wins:

1. Beside the frozen app's own exe, or in a `dependables/` folder next to it
   (either installer layout works).
2. The repo's own `dependables/` folder -- the same binaries, for running
   from source with `python main.py`. Gitignored; see CLAUDE.md.
3. PATH.

**Absolute paths are the point, not a nicety.** yt-dlp silently ignores a
relative `--js-runtimes deno:dependables/deno.exe` (reported "no JS runtime
found"; the same path made absolute worked -- confirmed directly), and a bare
`ffmpeg` handed to yt-dlp or subprocess is left to Windows' own search order,
which only happens to hit the app's folder when frozen. Nothing here touches
Tk. Results are cached per process -- the tools don't move mid-run.
"""

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
    """What to put in an argv for tool `name`: its absolute path, or the bare
    name when it can't be found anywhere -- so launching it still raises the
    usual FileNotFoundError that every caller already turns into a readable
    "isn't installed" message, rather than a None blowing up mid-argv."""
    return find_tool(name) or name


def tool_dir(name):
    """The folder holding tool `name`, or None when it can't be found. What
    yt-dlp's `--ffmpeg-location` wants (it pairs ffmpeg with the ffprobe
    beside it)."""
    path = find_tool(name)
    return os.path.dirname(path) if path else None
