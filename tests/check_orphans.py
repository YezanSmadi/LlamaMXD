# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""No process outlives the app. The real app (main.main, sandboxed, offscreen) runs as a child,
imports the HDR fixture and turns HDR->SDR on, so tone-map ffmpegs are running; then it closes its
window, or is killed outright (a crash, End Task). Each run must have had ffmpeg running at that
moment (else it proves nothing), and none of the app's descendants may be alive once it's gone."""
import ctypes
import subprocess
import sys
import time
from ctypes import wintypes

from harness import ROOT, WORK, fixture, report

_APP = r'''
import os, sys
work = sys.argv[3]
os.environ["LOCALAPPDATA"] = os.path.join(work, "orphans-appdata")
os.environ["TEMP"] = os.environ["TMP"] = os.path.join(work, "orphans-temp")
os.makedirs(os.environ["TEMP"], exist_ok=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, sys.argv[4])
os.chdir(sys.argv[4])
import ui.tabs.settings as st
st.save_settings = lambda *a, **k: None
from PySide6.QtCore import QTimer
import ui.app
ui.app.MainWindow.perform_when_done = lambda *a, **k: None
_present = ui.app.MainWindow.present
def present(self):
    _present(self)
    self.media.select_file(sys.argv[1])
    def busy():
        frames = self.media.hdr_frames or []
        if self.media._hdr and self.media._hdr["busy"]:
            print("BUSY", flush=True)
            if sys.argv[2] == "close":
                QTimer.singleShot(150, self.close)
            return
        if self.media.thumb_frames_path == sys.argv[1]:
            enc = self.tabs["Encoding"]
            if not enc.hdr_switch.isChecked():
                enc.hdr_switch.setChecked(True)
                enc._on_hdr_toggle()
        QTimer.singleShot(20, busy)
    QTimer.singleShot(200, busy)
ui.app.MainWindow.present = present
import main
main.main()
'''

_k32 = ctypes.WinDLL("kernel32")
_k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
_k32.OpenProcess.restype = ctypes.c_void_p


class _PE(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("u", wintypes.DWORD), ("pid", wintypes.DWORD),
                ("heap", ctypes.c_size_t), ("mod", wintypes.DWORD), ("threads", wintypes.DWORD),
                ("ppid", wintypes.DWORD), ("pri", ctypes.c_long), ("flags", wintypes.DWORD),
                ("exe", ctypes.c_wchar * 260)]


def _descendants(root):
    snap = _k32.CreateToolhelp32Snapshot(2, 0)
    pe = _PE()
    pe.dwSize = ctypes.sizeof(pe)
    procs = {}
    ok = _k32.Process32FirstW(ctypes.c_void_p(snap), ctypes.byref(pe))
    while ok:
        procs[pe.pid] = (pe.ppid, pe.exe)
        ok = _k32.Process32NextW(ctypes.c_void_p(snap), ctypes.byref(pe))
    _k32.CloseHandle(ctypes.c_void_p(snap))
    found, frontier = {}, {root}
    while frontier:
        frontier = {pid for pid, (ppid, _) in procs.items() if ppid in frontier and pid not in found and pid != root}
        found.update({pid: procs[pid][1] for pid in frontier})
    return found


def _alive(pid):
    handle = _k32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    code = ctypes.c_ulong()
    _k32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))
    _k32.CloseHandle(ctypes.c_void_p(handle))
    return code.value == 259


def _run(mode):
    """`(ffmpegs running when the app went, descendants still alive after)`."""
    app = subprocess.Popen([sys.executable, "-c", _APP, fixture("hdr.mkv"), mode, WORK, ROOT],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    seen, busy = {}, []
    end = time.monotonic() + 90
    while time.monotonic() < end and app.poll() is None:
        line = app.stdout.readline()
        if "BUSY" in line:
            seen.update(_descendants(app.pid))
            busy = [pid for pid, exe in seen.items() if exe.lower() == "ffmpeg.exe" and _alive(pid)]
            if mode == "kill":
                app.kill()
            break
    try:
        app.wait(timeout=30)
    except subprocess.TimeoutExpired:
        app.kill()
    left = [pid for pid in seen if _alive(pid)]
    for pid in left:
        subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"], capture_output=True)
    return len(busy), [seen[pid] for pid in left]


def run():
    problems = []
    for mode in ("close", "kill"):
        busy, left = _run(mode)
        if not busy:
            problems.append(f"{mode}: no ffmpeg was running when the app went (the check proved nothing)")
        if left:
            problems.append(f"{mode}: still running after the app exited: {left}")
    return report("no process outlives the app (closed, and killed mid-render)", problems)


if __name__ == "__main__":
    run()
