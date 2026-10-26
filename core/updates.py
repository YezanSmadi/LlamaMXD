# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Update checks and installs for LlamaMXD and its bundled tools (ffmpeg, yt-dlp, deno) from their
GitHub releases. Every download is checked against the SHA-256 GitHub publishes for it. No Qt."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field

from core import llamalog, tools, winproc

APP_REPO = "YezanSmadi/LlamaMXD"
APP_ASSET = r"^LlamaMXD-Setup-.*\.exe$"
TIMEOUT = 20
_API = "https://api.github.com/repos/{repo}/releases"

# One entry per bundled tool: where its releases are, which asset is the Windows build, the files it
# provides, and how to read an installed copy's version.
TOOLS = (
    {"name": "ffmpeg", "label": "ffmpeg", "repo": "GyanD/codexffmpeg", "asset": r"^ffmpeg-.*-full_build\.zip$",
     "files": ("ffmpeg.exe", "ffprobe.exe"), "zip": True, "flag": "-version",
     "version": r"ffmpeg version n?(\d+(?:\.\d+)+)"},
    {"name": "yt-dlp", "label": "yt-dlp", "repo": "yt-dlp/yt-dlp", "asset": r"^yt-dlp\.exe$",
     "files": ("yt-dlp.exe",), "zip": False, "flag": "--version", "version": r"^(\d{4}\.\d{2}\.\d{2}(?:\.\d+)?)"},
    {"name": "deno", "label": "Deno", "repo": "denoland/deno", "asset": r"^deno-x86_64-pc-windows-msvc\.zip$",
     "files": ("deno.exe",), "zip": True, "flag": "--version", "version": r"deno (\d+\.\d+\.\d+)"},
)

_STAGES = {"alpha": 0, "a": 0, "beta": 1, "b": 1, "rc": 2}
_RELEASED = (99, 0)   # sorts after every alpha / beta / rc of the same number


class UpdateError(Exception):
    """A check or install that failed, worded for the user."""


@dataclass
class Asset:
    name: str
    url: str
    size: int
    digest: str   # "sha256:<hex>"


@dataclass
class AppUpdate:
    version: str
    page: str     # the release's web page
    asset: Asset


@dataclass
class ToolUpdate:
    name: str
    label: str
    installed: str
    latest: str
    asset: Asset
    files: tuple
    zipped: bool
    tools_dir: str


@dataclass
class Report:
    current: str
    app: AppUpdate = None
    tools: list = field(default_factory=list)
    versions: dict = field(default_factory=dict)   # tool name -> installed version, for those that could be read
    errors: list = field(default_factory=list)
    reached: bool = False                          # whether GitHub answered at least once


# ---------------------------------------------------------------------- #
#  Versions
# ---------------------------------------------------------------------- #
def parse_version(text):
    """A sortable key for "v1.0.0", "0.5.0-beta.5" or "2026.08.19" (a release sorts above its own
    alpha / beta / rc), or None when there is no number in it."""
    match = re.match(r"v?(\d+(?:\.\d+)*)(?:[-.]?([A-Za-z]+)\.?(\d+)?)?", (text or "").strip())
    if not match:
        return None
    nums = tuple(int(n) for n in match.group(1).split("."))
    nums += (0,) * (4 - len(nums))
    stage = match.group(2)
    pre = (_STAGES.get(stage.lower(), -1), int(match.group(3) or 0)) if stage else _RELEASED
    return nums, pre


def is_prerelease(text):
    """Whether a version string names an alpha / beta / rc."""
    key = parse_version(text)
    return bool(key) and key[1] != _RELEASED


def installed_version(spec):
    """The installed version of a bundled tool (as the tool reports it), or None."""
    path = tools.find_tool(spec["name"])
    if not path:
        return None
    try:
        out = winproc.run([path, spec["flag"]], text=True, timeout=15).stdout or ""
    except (OSError, subprocess.SubprocessError) as exc:
        llamalog.get("updates").warning("%s version check failed: %s", spec["name"], exc)
        return None
    match = re.search(spec["version"], out, re.M)
    return match.group(1) if match else None


# ---------------------------------------------------------------------- #
#  Asking GitHub
# ---------------------------------------------------------------------- #
def _get_json(url):
    """GitHub's JSON for `url`; None for a 404 (no such release yet). UpdateError for anything else."""
    request = urllib.request.Request(url, headers={"User-Agent": "LlamaMXD-updater",
                                                   "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        if exc.code in (403, 429):
            raise UpdateError("GitHub is limiting requests from this connection right now. Try again later.") from None
        raise UpdateError(f"GitHub answered with an error ({exc.code}).") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise UpdateError("GitHub couldn't be reached. Check your internet connection.") from exc


def _asset(release, pattern):
    """The release's asset whose name matches `pattern` and that carries a SHA-256 digest, or None."""
    for item in release.get("assets") or []:
        digest = item.get("digest") or ""
        if re.match(pattern, item.get("name", "")) and digest.startswith("sha256:"):
            return Asset(item["name"], item["browser_download_url"], int(item.get("size") or 0), digest)
    return None


def _check_app(current):
    """The newest published LlamaMXD installer that is newer than `current`, or None. A pre-release
    is offered only to someone already on one."""
    releases = _get_json(_API.format(repo=APP_REPO) + "?per_page=20")
    if not releases:
        return None
    allow_pre = is_prerelease(current)
    best = None
    for release in releases:
        key = parse_version(release.get("tag_name"))
        if release.get("draft") or key is None or (release.get("prerelease") and not allow_pre):
            continue
        asset = _asset(release, APP_ASSET)
        if asset and (best is None or key > best[0]):
            best = (key, release, asset)
    if best and best[0] > (parse_version(current) or ((0, 0, 0, 0), (-1, 0))):
        return AppUpdate(best[1]["tag_name"].lstrip("v"), best[1].get("html_url", ""), best[2])
    return None


def _check_tool(spec, report):
    """Add `spec`'s update to `report` when its bundled copy is older than the latest release."""
    folder = tools.bundled_dir(spec["name"])
    if not folder:
        return   # not bundled: a copy on PATH belongs to the user, not to this app
    installed = installed_version(spec)
    if not installed:
        return
    report.versions[spec["name"]] = installed
    release = _get_json(_API.format(repo=spec["repo"]) + "/latest")
    report.reached = True
    asset = _asset(release or {}, spec["asset"])
    latest = (release or {}).get("tag_name", "")
    if asset and parse_version(latest) and parse_version(latest) > parse_version(installed):
        report.tools.append(ToolUpdate(spec["name"], spec["label"], installed, latest.lstrip("v"), asset,
                                       spec["files"], spec["zip"], folder))


def check(current):
    """Look for a newer LlamaMXD and newer bundled tools; one failing doesn't stop the others."""
    report = Report(current=current)
    for spec in TOOLS:
        folder = tools.bundled_dir(spec["name"])
        if folder:
            cleanup_old(folder, spec["files"])
    try:
        report.app = _check_app(current)
        report.reached = True
    except UpdateError as exc:
        report.errors.append(f"LlamaMXD: {exc}")
    for spec in TOOLS:
        try:
            _check_tool(spec, report)
        except UpdateError as exc:
            report.errors.append(f"{spec['label']}: {exc}")
    llamalog.get("updates").info("Update check: app=%s tools=%s errors=%d", report.app and report.app.version,
                                 [(t.name, t.installed, t.latest) for t in report.tools], len(report.errors))
    return report


# ---------------------------------------------------------------------- #
#  Downloading and installing
# ---------------------------------------------------------------------- #
def _remove(path):
    """Delete `path`, ignoring failure (a file in use, or already gone)."""
    try:
        os.remove(path)
    except OSError:
        pass


def download(asset, dest, progress=None):
    """Save `asset` to `dest`, checked against its published SHA-256 (a mismatch deletes it and raises).
    `progress(bytes_done, bytes_total)` is called as it arrives."""
    expected = asset.digest.split(":", 1)[1].lower()
    digest = hashlib.sha256()
    part = dest + ".part"
    request = urllib.request.Request(asset.url, headers={"User-Agent": "LlamaMXD-updater"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response, open(part, "wb") as out:
            total = int(response.headers.get("Content-Length") or asset.size or 0)
            done = 0
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _remove(part)
        raise UpdateError("The download didn't finish. Check your internet connection.") from exc
    if digest.hexdigest() != expected:
        _remove(part)
        raise UpdateError("The download didn't match its published checksum, so it was discarded.")
    os.replace(part, dest)
    return dest


def cleanup_old(folder, names):
    """Remove the `.old` / `.new` / `.part` leftovers of earlier tool swaps in `folder`."""
    for name in names:
        for suffix in (".old", ".new", ".part"):
            _remove(os.path.join(folder, name + suffix))


def _runs(path):
    """Whether the tool at `path` starts and reports a version."""
    flag = "-version" if os.path.basename(path).lower().startswith(("ffmpeg", "ffprobe")) else "--version"
    try:
        completed = winproc.run([path, flag], text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0 and bool((completed.stdout or "").strip())


def install_tool(update, progress=None, verify=_runs):
    """Download and swap in `update`'s files in its tools folder. The old files are renamed `.old`
    first and put back if anything fails, so a failed update leaves the tool as it was. `verify(path)`
    must pass for every new file, before and after the swap."""
    work = tempfile.mkdtemp(prefix="llamamxd-update-")
    try:
        archive = download(update.asset, os.path.join(work, update.asset.name), progress)
        staged = {}
        if update.zipped:
            with zipfile.ZipFile(archive) as zf:
                for name in update.files:
                    member = next((m for m in zf.namelist()
                                   if m.lower().endswith("/" + name.lower()) or m.lower() == name.lower()), None)
                    if member is None:
                        raise UpdateError(f"{name} wasn't in the downloaded archive.")
                    staged[name] = os.path.join(work, name)
                    with zf.open(member) as src, open(staged[name], "wb") as dst:
                        shutil.copyfileobj(src, dst)
        else:
            staged[update.files[0]] = archive
        for name, path in staged.items():
            if not verify(path):
                raise UpdateError(f"The new {name} didn't start, so nothing was changed.")
        _swap(update.tools_dir, staged, verify)
    except zipfile.BadZipFile as exc:
        raise UpdateError("The downloaded archive was damaged, so nothing was changed.") from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)
    llamalog.get("updates").info("Updated %s %s -> %s in %s", update.name, update.installed, update.latest,
                                 update.tools_dir)


def _swap(folder, staged, verify):
    """Replace each file in `folder` with its staged copy, keeping the old one as `.old` until every
    new file has run; on any failure every old file is put back."""
    swapped = []
    try:
        for name, path in staged.items():
            dst = os.path.join(folder, name)
            new, old = dst + ".new", dst + ".old"
            shutil.copy2(path, new)
            _remove(old)
            os.replace(dst, old)          # renaming works even while the tool is running
            swapped.append((dst, old))
            os.replace(new, dst)
        for dst, _ in swapped:
            if not verify(dst):
                raise UpdateError(
                    f"The new {os.path.basename(dst)} didn't start after the swap; the old one was restored.")
    except (OSError, UpdateError) as exc:
        for dst, old in reversed(swapped):
            try:
                os.replace(old, dst)
            except OSError:
                llamalog.get("updates").error("Couldn't restore %s from %s", dst, old)
        for name in staged:
            _remove(os.path.join(folder, name + ".new"))
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError(f"The update couldn't replace the old files ({exc}). The old version was kept.") from exc
    for _, old in swapped:
        _remove(old)


def download_installer(update, progress=None):
    """Download and verify LlamaMXD's installer into a temp folder; the path to it."""
    folder = os.path.join(tempfile.gettempdir(), "LlamaMXD-update")
    os.makedirs(folder, exist_ok=True)
    return download(update.asset, os.path.join(folder, update.asset.name), progress)


def launch_installer(path):
    """Start the downloaded installer on its own, outside the app's kill-on-close tool job (it has to
    outlive the app), silently with a progress bar; it closes the app, updates it and starts it again."""
    flags = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([path, "/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS", "/RELAUNCH=1"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=flags, close_fds=True)
    llamalog.get("updates").info("Started the installer %s", path)


def releases_page():
    """The project's releases page, for a copy that can't update itself."""
    return f"https://github.com/{APP_REPO}/releases"
