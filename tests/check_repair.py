# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""core/repair.py and the release lookups Repair uses, offline: a file list written and read back, then each kind of
damage (a missing file, one changed at the same size, a truncated one, a bad or absent list) reported, files that
aren't on the list ignored, a tool that an update made newer accepted but one that is older, equal or won't run
refused; the installer found for an exact version (drafts, missing checksums and pre-releases handled); and a
downloaded installer reused only while its checksum still matches."""
import hashlib
import os
import shutil

from harness import WORK, report

from core import repair, updates

ROOT = os.path.join(WORK, "repair")
TOOLS = {"ffmpeg": "9.0.2", "yt-dlp": "2026.08.19", "deno": "2.9.7"}


def _tree(name):
    """A small stand-in app folder, with its file list written."""
    folder = os.path.join(ROOT, name)
    shutil.rmtree(folder, ignore_errors=True)
    for rel, data in {"LlamaMXD.exe": b"exe" * 100, "_internal/python313.dll": b"dll" * 500,
                      "_internal/assets/logo.svg": b"<svg/>", "manual/manual.html": b"<html/>",
                      "dependables/ffmpeg.exe": b"ffmpeg-9.0.2", "dependables/ffprobe.exe": b"ffprobe-9.0.2",
                      "dependables/yt-dlp.exe": b"ytdlp-2026.08.19", "dependables/deno.exe": b"deno-2.9.7"}.items():
        path = os.path.join(folder, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
    repair.write_manifest(folder, "1.0.0", TOOLS)
    return folder


def _write(folder, rel, data):
    with open(os.path.join(folder, *rel.split("/")), "wb") as fh:
        fh.write(data)


def _verify():
    problems = []
    folder = _tree("intact")
    result = repair.verify(folder)
    if not result.manifest_found or result.problems or result.total != 8 or result.version != "1.0.0":
        problems.append(f"an intact copy: found={result.manifest_found} problems={result.problems} total={result.total}")
    seen = []
    repair.verify(folder, lambda done, total: seen.append((done, total)))
    if not seen or seen[-1] != (8, 8):
        problems.append(f"progress ended at {seen[-1:]}, expected (8, 8)")

    # each kind of damage
    os.remove(os.path.join(folder, "manual", "manual.html"))
    _write(folder, "_internal/python313.dll", b"xyz" * 500)          # same size, different bytes
    _write(folder, "_internal/assets/logo.svg", b"<sv")              # truncated
    open(os.path.join(folder, "notes.txt"), "w").write("not on the list")   # an extra file is ignored
    got = repair.verify(folder).problems
    want = [("_internal/assets/logo.svg", "damaged"), ("_internal/python313.dll", "damaged"),
            ("manual/manual.html", "missing")]
    if got != want:
        problems.append(f"damage: {got}, expected {want}")

    # the list itself
    os.remove(os.path.join(folder, repair.MANIFEST))
    if repair.verify(folder).manifest_found:
        problems.append("a missing list was reported as found")
    _write(folder, repair.MANIFEST, b"{ this is not json")
    if repair.verify(folder).manifest_found:
        problems.append("an unreadable list was reported as found")
    _write(folder, repair.MANIFEST, b'{"files": 5}')
    if repair.verify(folder).manifest_found:
        problems.append("a list of the wrong shape was reported as found")
    return problems


def _tools():
    problems = []
    versions = {"yt-dlp": "2026.10.26", "deno": "2.9.7", "ffmpeg": "9.0.2"}
    folder = _tree("tools")
    reading = lambda path: versions.get({"yt-dlp.exe": "yt-dlp", "deno.exe": "deno", "ffmpeg.exe": "ffmpeg",
                                         "ffprobe.exe": "ffmpeg"}.get(os.path.basename(path)))  # noqa: E731

    _write(folder, "dependables/yt-dlp.exe", b"a newer yt-dlp")                       # an in-app update
    got = repair.verify(folder, read=reading).problems
    if got:
        problems.append(f"a newer yt-dlp was refused: {got}")

    versions["yt-dlp"] = "2026.08.19"                                                 # changed, same version
    got = repair.verify(folder, read=reading).problems
    if got != [("dependables/yt-dlp.exe", "damaged")]:
        problems.append(f"a changed tool of the same version: {got}")

    versions["yt-dlp"] = "2026.01.01"                                                 # older
    got = repair.verify(folder, read=reading).problems
    if got != [("dependables/yt-dlp.exe", "damaged")]:
        problems.append(f"an older tool: {got}")

    versions["yt-dlp"] = None                                                         # won't run
    got = repair.verify(folder, read=reading).problems
    if got != [("dependables/yt-dlp.exe", "damaged")]:
        problems.append(f"a tool that won't run: {got}")

    versions["yt-dlp"] = "2026.10.26"
    _write(folder, "dependables/ffprobe.exe", b"a newer ffprobe")                      # ffprobe follows ffmpeg's version
    versions["ffmpeg"] = "9.1.0"
    got = repair.verify(folder, read=reading).problems
    if [p for p in got if p[0] == "dependables/ffprobe.exe"]:
        problems.append(f"a newer ffprobe was refused: {got}")

    # a non-tool file is never excused by a version
    _write(folder, "LlamaMXD.exe", b"other")
    if ("LlamaMXD.exe", "damaged") not in repair.verify(folder, read=reading).problems:
        problems.append("a changed LlamaMXD.exe was accepted")
    return problems


def _release(tag, name=None, digest=True, **extra):
    assets = []
    if name:
        assets.append({"name": name, "browser_download_url": "http://x/" + name, "size": 10,
                       "digest": "sha256:" + "ab" * 32 if digest else None})
    return {"tag_name": tag, "html_url": "http://x/" + tag, "assets": assets, "draft": False, "prerelease": False, **extra}


def _lookups():
    problems = []
    real = updates._get_json
    listing = [
        _release("v1.1.0", "LlamaMXD-Setup-1.1.0.exe"),
        _release("v1.0.0", "LlamaMXD-Setup-1.0.0.exe"),
        _release("v0.9.0", "LlamaMXD-Setup-0.9.0.exe", draft=True),
        _release("v0.8.0", "LlamaMXD-Setup-0.8.0.exe", digest=False),
        _release("v1.2.0-beta.1", "LlamaMXD-Setup-1.2.0-beta.1.exe", prerelease=True),
    ]
    updates._get_json = lambda url: listing
    try:
        for ask, want in (("v1.0.0", "1.0.0"), ("1.0.0", "1.0.0"), ("1.1.0", "1.1.0"), ("0.9.0", None),
                          ("0.8.0", None), ("2.0.0", None)):
            got = updates.release_for(ask)
            if (got.version if got else None) != want:
                problems.append(f"release_for({ask!r}) = {got and got.version!r}, expected {want!r}")
        if updates.release_for("1.2.0-beta.1") is None:
            problems.append("a beta wasn't found for someone running that beta")
        if updates.release_for("1.0.0-beta.9") is not None:
            problems.append("an unpublished beta matched")
        newest = updates.newest_installer("1.0.0")
        if not newest or newest.version != "1.1.0":
            problems.append(f"newest_installer for a stable user: {newest and newest.version}")
        newest = updates.newest_installer("1.2.0-beta.0")
        if not newest or newest.version != "1.2.0-beta.1":
            problems.append(f"newest_installer for a beta user: {newest and newest.version}")
        updates._get_json = lambda url: None
        if updates.release_for("1.0.0") is not None or updates.newest_installer("1.0.0") is not None:
            problems.append("no releases should give None")
    finally:
        updates._get_json = real
    return problems


def _cache():
    problems = []
    data = os.urandom(200_000)
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    asset = updates.Asset("LlamaMXD-Setup-0.0.1-test.exe", "http://127.0.0.1:1/never", len(data), digest)
    update = updates.AppUpdate("0.0.1-test", "", asset)
    folder = os.path.join(os.environ.get("TEMP", ROOT), "LlamaMXD-update")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, asset.name)
    seen = []
    try:
        with open(path, "wb") as fh:
            fh.write(data)
        got = updates.download_installer(update, lambda done, total: seen.append((done, total)))
        if got != path or seen != [(len(data), len(data))]:
            problems.append(f"a matching file wasn't reused: {got!r} {seen}")
        with open(path, "wb") as fh:
            fh.write(data[:-1] + b"x")        # a damaged leftover must not be trusted: the (unreachable) URL is tried
        try:
            updates.download_installer(update)
            problems.append("a damaged leftover installer was reused")
        except updates.UpdateError:
            pass
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return problems


def run():
    shutil.rmtree(ROOT, ignore_errors=True)
    os.makedirs(ROOT)
    report("repair: the file list and what verify reports", _verify())
    report("repair: tools an update made newer, and ones that are not", _tools())
    report("repair: the installer found for a version", _lookups())
    report("repair: a downloaded installer is reused only while it matches", _cache())


if __name__ == "__main__":
    run()
