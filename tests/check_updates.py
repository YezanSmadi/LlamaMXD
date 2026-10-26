# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""core/updates.py, offline: version ordering; what `check` reports for a faked GitHub (a newer app,
pre-releases only for someone on one, drafts and assets without a checksum ignored, a 404, every request
failing); a download checked against its SHA-256 (served from a local server); and a tool swap: replaced,
rolled back when the new file won't run, untouched when its archive is wrong, and done over a running exe."""
import hashlib
import http.server
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile

from harness import WORK, report

from core import tools, updates

ROOT = os.path.join(WORK, "updates")


def _asset(name, data, port):
    return updates.Asset(name, f"http://127.0.0.1:{port}/{name}", len(data), "sha256:" + hashlib.sha256(data).hexdigest())


def _release(tag, asset_name=None, digest=True, **extra):
    assets = []
    if asset_name:
        assets.append({"name": asset_name, "browser_download_url": "http://x/" + asset_name, "size": 10,
                       "digest": "sha256:ab" * 16 if digest else None})
    return {"tag_name": tag, "html_url": "http://x/" + tag, "assets": assets, "draft": False,
            "prerelease": False, **extra}


def _versions():
    problems = []
    v = updates.parse_version
    for lo, hi in (("0.5.0-beta.5", "v1.0.0"), ("0.5.0-beta.5", "0.5.0"), ("0.5.0-alpha.9", "0.5.0-beta.1"),
                   ("0.5.0-beta.5", "0.5.0-beta.10"), ("2026.08.19", "2026.10.21"), ("1.0", "1.0.1"),
                   ("0.5.0-rc.1", "0.5.0")):
        if not v(lo) < v(hi):
            problems.append(f"{lo} should sort below {hi}")
    if v("1.0") != v("1.0.0") or v("v2.9.7") != v("2.9.7"):
        problems.append("1.0 / v-prefixed forms don't compare equal")
    if updates.is_prerelease("v1.0.0") or not updates.is_prerelease("0.5.0-beta.5"):
        problems.append("is_prerelease is wrong")
    if v("nonsense") is not None:
        problems.append("a version with no number should parse to None")
    return problems


def _checks():
    problems = []
    tool_dir = os.path.join(ROOT, "dependables")
    os.makedirs(tool_dir, exist_ok=True)
    fake = {}
    real = (updates._get_json, tools.bundled_dir, updates.installed_version)
    updates._get_json = lambda url: _answer(fake, url)
    tools.bundled_dir = lambda name: tool_dir
    updates.installed_version = lambda spec: {"ffmpeg": "9.0.2", "yt-dlp": "2026.08.19", "deno": "2.9.7"}[spec["name"]]
    try:
        app_url = "repos/" + updates.APP_REPO + "/releases"
        fake[app_url] = [
            _release("v1.1.0", "LlamaMXD-Setup-1.1.0.exe"),
            _release("v1.2.0-beta.1", "LlamaMXD-Setup-1.2.0-beta.1.exe", prerelease=True),
            _release("v1.3.0", "LlamaMXD-Setup-1.3.0.exe", draft=True),
            _release("v1.4.0", "LlamaMXD-Setup-1.4.0.exe", digest=False),
            _release("v0.9.0", "LlamaMXD-Setup-0.9.0.exe"),
        ]
        fake["repos/yt-dlp/yt-dlp/releases/latest"] = _release("2026.10.21", "yt-dlp.exe")
        fake["repos/denoland/deno/releases/latest"] = _release("v2.9.7", "deno-x86_64-pc-windows-msvc.zip")
        fake["repos/GyanD/codexffmpeg/releases/latest"] = _release("9.0.2", "ffmpeg-9.0.2-full_build.zip")

        r = updates.check("v1.0.0")
        if not (r.app and r.app.version == "1.1.0"):
            problems.append(f"stable user: expected app 1.1.0, got {r.app and r.app.version}")
        if [(t.name, t.latest) for t in r.tools] != [("yt-dlp", "2026.10.21")]:
            problems.append(f"expected only a yt-dlp update, got {[(t.name, t.latest) for t in r.tools]}")
        if r.errors or not r.reached or set(r.versions) != {"ffmpeg", "yt-dlp", "deno"}:
            problems.append(f"unexpected errors / versions: {r.errors} {r.versions}")

        r = updates.check("v0.5.0-beta.5")
        if not (r.app and r.app.version == "1.2.0-beta.1"):
            problems.append(f"beta user: expected the newest release incl. pre-releases (1.2.0-beta.1), got {r.app and r.app.version}")

        r = updates.check("v1.1.0")
        if r.app is not None:
            problems.append(f"current v1.1.0 offered {r.app.version}")

        fake[app_url] = None
        r = updates.check("v1.0.0")
        if r.app is not None or r.errors:
            problems.append("a 404 for the app's releases should mean no update and no error")

        fake.clear()
        updates._get_json = lambda url: (_ for _ in ()).throw(updates.UpdateError("offline"))
        r = updates.check("v1.0.0")
        if r.reached or len(r.errors) < 2:
            problems.append(f"every request failing: reached={r.reached} errors={r.errors}")
    finally:
        updates._get_json, tools.bundled_dir, updates.installed_version = real
    return problems


def _answer(fake, url):
    key = url.split("api.github.com/", 1)[1].split("?")[0]
    return fake.get(key)


class _Server:
    """Serves ROOT/www on localhost for the download tests."""

    def __init__(self):
        self.dir = os.path.join(ROOT, "www")
        os.makedirs(self.dir, exist_ok=True)
        handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=self.dir, **k)  # noqa: E731
        handler.log_message = lambda *a: None
        http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def put(self, name, data):
        with open(os.path.join(self.dir, name), "wb") as fh:
            fh.write(data)
        return _asset(name, data, self.port)

    def close(self):
        self.httpd.shutdown()


def _downloads(server):
    problems = []
    data = os.urandom(3_000_000)
    asset = server.put("blob.bin", data)
    seen = []
    dest = os.path.join(ROOT, "got.bin")
    updates.download(asset, dest, lambda done, total: seen.append((done, total)))
    if open(dest, "rb").read() != data:
        problems.append("a good download was saved wrongly")
    if not seen or seen[-1][0] != len(data):
        problems.append(f"progress did not reach the end: {seen[-1:] }")

    bad = updates.Asset("blob.bin", asset.url, asset.size, "sha256:" + "0" * 64)
    bad_dest = os.path.join(ROOT, "bad.bin")
    try:
        updates.download(bad, bad_dest)
        problems.append("a checksum mismatch was accepted")
    except updates.UpdateError:
        pass
    if os.path.exists(bad_dest) or os.path.exists(bad_dest + ".part"):
        problems.append("a download that failed its checksum was left on disk")
    return problems


def _tool(folder, name, content):
    path = os.path.join(folder, name)
    with open(path, "wb") as fh:
        fh.write(content)
    return path


def _zip(server, name, members):
    path = os.path.join(ROOT, name)
    with zipfile.ZipFile(path, "w") as zf:
        for member, data in members.items():
            zf.writestr(member, data)
    return server.put(name, open(path, "rb").read())


def _update(asset, folder, files, zipped):
    return updates.ToolUpdate("tool", "Tool", "1", "2", asset, files, zipped, folder)


def _swaps(server):
    problems = []
    folder = os.path.join(ROOT, "swap")
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    accept = lambda path: True  # noqa: E731

    # A single exe (yt-dlp's shape): replaced, nothing left behind.
    old = _tool(folder, "t.exe", b"old")
    updates.install_tool(_update(server.put("t.exe", b"new"), folder, ("t.exe",), False), verify=accept)
    if open(old, "rb").read() != b"new" or sorted(os.listdir(folder)) != ["t.exe"]:
        problems.append(f"single-file swap: {open(old, 'rb').read()!r} {sorted(os.listdir(folder))}")

    # A zip with two files under a folder (ffmpeg's shape).
    _tool(folder, "a.exe", b"a-old")
    _tool(folder, "b.exe", b"b-old")
    asset = _zip(server, "pair.zip", {"pkg/bin/a.exe": b"a-new", "pkg/bin/b.exe": b"b-new", "pkg/readme": b"x"})
    updates.install_tool(_update(asset, folder, ("a.exe", "b.exe"), True), verify=accept)
    if open(os.path.join(folder, "a.exe"), "rb").read() != b"a-new" or open(os.path.join(folder, "b.exe"), "rb").read() != b"b-new":
        problems.append("zip swap didn't replace both files")

    # The second new file fails once everything is in place: both old files come back.
    _tool(folder, "a.exe", b"a-old")
    _tool(folder, "b.exe", b"b-old")
    reject_b = lambda path: not (os.path.basename(path) == "b.exe" and open(path, "rb").read() == b"b-new" and os.path.dirname(path) == folder)  # noqa: E731
    try:
        updates.install_tool(_update(asset, folder, ("a.exe", "b.exe"), True), verify=reject_b)
        problems.append("a swap whose new file failed afterwards was accepted")
    except updates.UpdateError:
        pass
    if open(os.path.join(folder, "a.exe"), "rb").read() != b"a-old" or open(os.path.join(folder, "b.exe"), "rb").read() != b"b-old":
        problems.append("rollback didn't restore the old files")
    left = [n for n in os.listdir(folder) if n.endswith((".old", ".new", ".part"))]
    if left:
        problems.append(f"rollback left {left}")

    # A new file that won't run is refused before anything changes.
    try:
        updates.install_tool(_update(server.put("t.exe", b"new"), folder, ("a.exe",), False), verify=lambda p: False)
        problems.append("a new file that doesn't run was installed")
    except updates.UpdateError:
        pass
    if open(os.path.join(folder, "a.exe"), "rb").read() != b"a-old":
        problems.append("a refused update changed the old file")

    # An archive without the file, and one that isn't a zip.
    for label, asset in (("missing member", _zip(server, "no.zip", {"x/other.exe": b"z"})),
                         ("not a zip", server.put("bad.zip", b"this is not a zip"))):
        try:
            updates.install_tool(_update(asset, folder, ("a.exe",), True), verify=accept)
            problems.append(f"{label}: accepted")
        except updates.UpdateError:
            pass
        if open(os.path.join(folder, "a.exe"), "rb").read() != b"a-old":
            problems.append(f"{label}: touched the old file")
    return problems


def _running(server):
    """Replacing an exe that is running (Windows lets it be renamed, not overwritten), with the real
    version check on a copy of Python."""
    problems = []
    folder = os.path.join(ROOT, "running")
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    exe = os.path.join(folder, "py.exe")
    shutil.copy2(sys.executable, exe)
    proc = subprocess.Popen([exe, "-c", "import time; time.sleep(8)"])
    time.sleep(0.5)
    try:
        asset = server.put("py.exe", b"MZ-replacement")
        updates.install_tool(_update(asset, folder, ("py.exe",), False), verify=lambda p: True)
        if open(exe, "rb").read() != b"MZ-replacement":
            problems.append("a running exe wasn't replaced")
    finally:
        proc.kill()
        proc.wait()
    updates.cleanup_old(folder, ("py.exe",))
    if [n for n in os.listdir(folder) if n != "py.exe"]:
        problems.append(f"cleanup_old left {os.listdir(folder)}")
    if not updates._runs(sys.executable) or updates._runs(os.path.join(folder, "does-not-exist.exe")):
        problems.append("_runs misjudged a working / missing exe")
    return problems


def run():
    shutil.rmtree(ROOT, ignore_errors=True)
    os.makedirs(ROOT)
    server = _Server()
    try:
        report("updates: version ordering", _versions())
        report("updates: what a check reports (faked GitHub)", _checks())
        report("updates: downloads checked against their SHA-256", _downloads(server))
        report("updates: tool swap, rollback and refusals", _swaps(server))
        report("updates: replacing a running exe, leftovers cleaned", _running(server))
    finally:
        server.close()


if __name__ == "__main__":
    run()
