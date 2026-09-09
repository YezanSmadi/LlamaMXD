"""Named codec/quality recipes, persisted to `presets.json` at the repo root.

A preset is a **recipe, not a job**: it captures the container and every
codec/quality choice, and deliberately captures *nothing* that belongs to a
particular file. Trim, input/output paths, and (on Muxing) track selection
are per-job and reset every time, so loading "YouTube 1080p" never silently
re-trims your clip or points it at last week's output path.

Presets are scoped per source tab -- an Encoding preset can't be loaded into
Muxing, since the two tabs no longer share a settings shape at all.

`presets.json` is gitignored, same as `settings.json`: local preferences,
not shared repo state. Every read is best-effort; a missing or corrupt file
yields an empty set rather than raising.
"""

import json
import os

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PRESETS_PATH = os.path.join(_REPO_ROOT, "presets.json")

# The menu entry that means "no preset applied". Kept out of the saved data;
# the dropdown just prepends it.
NONE_LABEL = "— none —"

# Exactly which settings keys each tab's presets carry. Everything absent
# from these lists (input_file, output_path, start_secs, duration_secs, and
# Muxing's per-file track picks) is job state, not recipe state.
PRESET_KEYS = {
    "Encoding": [
        "output_format", "av_sync",
        "encoder", "profile", "level", "quality", "hdr_to_sdr", "strip_video",
        "audio_codec", "audio_bitrate", "audio_channels", "audio_sample_rate",
        "strip_audio",
    ],
    "Muxing": [
        "output_format", "av_sync", "strip_video", "strip_audio",
    ],
}


def _read_all():
    """The whole `{tab: {name: settings}}` store, or {} if unreadable."""
    if not os.path.exists(_PRESETS_PATH):
        return {}
    try:
        with open(_PRESETS_PATH, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_all(data):
    """Persists the whole store. Best-effort — a failed write must never take
    the app down mid-interaction."""
    try:
        with open(_PRESETS_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


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
    """Strips a full settings dict down to just the recipe keys for `tab`.
    Keys the tab doesn't currently expose are skipped, so this stays valid
    as controls come and go."""
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
