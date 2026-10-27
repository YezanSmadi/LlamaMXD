# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""The file list of a built copy (files.json, written by packaging/build.py) and the check of an installed
copy against it, for Settings > About's Repair. No Qt."""
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

from core import llamalog, updates, winproc

MANIFEST = "files.json"
TOOLS_DIR = "dependables"
# Each tool file, the flag that makes it print its version, and how to read it.
_TOOL_FILES = {
    "ffmpeg.exe": ("ffmpeg", "-version", r"ffmpeg version n?(\d+(?:\.\d+)+)"),
    "ffprobe.exe": ("ffmpeg", "-version", r"ffprobe version n?(\d+(?:\.\d+)+)"),
    "yt-dlp.exe": ("yt-dlp", "--version", r"^(\d{4}\.\d{2}\.\d{2}(?:\.\d+)?)"),
    "deno.exe": ("deno", "--version", r"deno (\d+\.\d+\.\d+)"),
}


@dataclass
class Result:
    total: int = 0
    problems: list = field(default_factory=list)   # (relative path, "missing" | "damaged"), sorted
    manifest_found: bool = True
    version: str = ""


def app_dir():
    """The folder this installed copy runs from, or None when running from source."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return None


def _hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(folder, version, tool_versions):
    """Record every file under `folder` (size and SHA-256) and the bundled tools' versions in files.json."""
    files = {}
    for root, _, names in os.walk(folder):
        for name in names:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, folder).replace("\\", "/")
            if rel != MANIFEST:
                files[rel] = [os.path.getsize(full), _hash(full)]
    with open(os.path.join(folder, MANIFEST), "w", encoding="utf-8") as fh:
        json.dump({"version": version, "tools": tool_versions, "files": dict(sorted(files.items()))}, fh, indent=1)
    return len(files)


def tool_version(path):
    """The version an installed tool file reports, or None when it won't run."""
    entry = _TOOL_FILES.get(os.path.basename(path).lower())
    if not entry:
        return None
    try:
        out = winproc.run([path, entry[1]], text=True, timeout=30).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(entry[2], out, re.M)
    return match.group(1) if match else None


def _newer_tool(folder, rel, bundled, read):
    """Whether tool file `rel` differs from the bundled one only because an in-app update made it newer."""
    parts = rel.split("/")
    entry = _TOOL_FILES.get(parts[-1].lower())
    if len(parts) != 2 or parts[0] != TOOLS_DIR or not entry or not bundled.get(entry[0]):
        return False
    have = read(os.path.join(folder, *parts))
    old, new = updates.parse_version(bundled[entry[0]]), updates.parse_version(have)
    return bool(have and old and new and new > old)


def verify(folder, progress=None, read=tool_version):
    """Compare `folder` with its files.json: what is missing or damaged. A tool that an update made newer is
    fine, and files that aren't on the list are ignored. `progress(done, total)` is called as it goes."""
    try:
        with open(os.path.join(folder, MANIFEST), encoding="utf-8") as fh:
            data = json.load(fh)
        files, bundled = data["files"], data.get("tools") or {}
        if (not isinstance(files, dict) or not isinstance(bundled, dict)
                or not all(isinstance(v, list) and len(v) == 2 for v in files.values())):
            raise ValueError("unexpected shape")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        llamalog.get("repair").info("No readable %s in %s", MANIFEST, folder)
        return Result(manifest_found=False)
    result = Result(total=len(files), version=data.get("version", ""))
    for done, (rel, (size, sha)) in enumerate(files.items(), 1):
        full = os.path.join(folder, *rel.split("/"))
        if not os.path.isfile(full):
            result.problems.append((rel, "missing"))
        elif os.path.getsize(full) != size or _hash(full) != sha:
            if not _newer_tool(folder, rel, bundled, read):
                result.problems.append((rel, "damaged"))
        if progress:
            progress(done, result.total)
    result.problems.sort()
    llamalog.get("repair").info("Checked %d files in %s: %d missing or damaged", result.total, folder, len(result.problems))
    return result
