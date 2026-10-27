# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Named codec/quality recipes per tab, in the gitignored `presets.json`. A preset is a recipe,
not a job: the container and codec/quality choices, never the trim, paths or track picks, so
loading one can't re-trim a clip or repoint its output. Reads are best-effort."""

import json
import os

from core import llamalog, userdata

_PRESETS_PATH = userdata.user_file("presets.json")

# The menu entry meaning "no preset applied" (never saved).
NONE_LABEL = "— none —"

# The settings keys each tab's presets carry; anything else is job state.
PRESET_KEYS = {
    "Encoding": [
        "output_format", "av_sync",
        "encoder", "profile", "level", "speed", "quality", "resolution", "fps", "hdr_to_sdr",
        "strip_video", "strip_audio", "strip_subtitles", "strip_chapters",
    ],
    "Muxing": [
        "output_format", "av_sync", "strip_video", "strip_audio", "strip_subtitles", "strip_chapters",
    ],
}
# No `audio_streams`: which of a particular file's streams to include is job state.


def _read_all():
    """The whole `{tab: {name: settings}}` store, or {} if unreadable."""
    if not os.path.exists(_PRESETS_PATH):
        return {}
    try:
        with open(_PRESETS_PATH, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        llamalog.get("settings").warning("presets.json couldn't be read (%s); treating it as empty", exc)
        return {}


def _write_all(data):
    """Persist the whole store, best-effort."""
    try:
        with open(_PRESETS_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except OSError as exc:
        llamalog.get("settings").warning("presets.json couldn't be saved: %s", exc)


def names(tab):
    """Saved preset names for `tab`, alphabetical."""
    return sorted(_read_all().get(tab, {}))


def menu_values(tab):
    """Dropdown values: the none-entry followed by every saved name."""
    return [NONE_LABEL] + names(tab)


def get(tab, name):
    """One preset's settings dict, or None if there's no such preset."""
    return _read_all().get(tab, {}).get(name)


def extract(tab, settings):
    """A settings dict cut down to `tab`'s recipe keys (keys it lacks are skipped)."""
    keys = PRESET_KEYS.get(tab, [])
    return {key: settings[key] for key in keys if key in settings}


def save(tab, name, settings):
    """Saves (or overwrites) `name` for `tab`, storing only the recipe keys."""
    data = _read_all()
    data.setdefault(tab, {})[name] = extract(tab, settings)
    _write_all(data)


def delete(tab, name):
    """Removes `name` from `tab`. No-op if it isn't there."""
    data = _read_all()
    if data.get(tab, {}).pop(name, None) is not None:
        _write_all(data)


def exists(tab, name):
    """Whether `tab` already has a preset called `name` (for overwrite
    confirmation)."""
    return name in _read_all().get(tab, {})
