# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""UI geometry: the real MainWindow, offscreen, with its own settings.json. Records every
visible widget's rect on every page at three scales (golden), runs the squeeze scan (a layout
squeezed below its own minimum clips a control), and checks the Muxing / Encoding preview-size
invariant."""
import json
import os
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import harness  # noqa: E402
from harness import WORK, check_golden, fixture, report  # noqa: E402

from core import presets, theme  # noqa: E402

# Isolated settings: Windowed (freely resizable), a fixed theme and mode, no presets.
_SETTINGS = os.path.join(WORK, "settings.json")
with open(_SETTINGS, "w", encoding="utf-8") as fh:
    json.dump({"theme": "Lemon", "appearance_mode": "Dark", "window_mode": "Windowed",
               "default_save_location": os.path.join(WORK, "out").replace("\\", "/")}, fh)
theme._SETTINGS_PATH = _SETTINGS
presets._PRESETS_PATH = os.path.join(WORK, "no-presets.json")

import main as M  # noqa: E402
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QWidget  # noqa: E402

SCALES = (1.0, 1.5, 2.0)
# Squeezes that predate the test suite: (state prefix, widget path suffix). Reported, not failed.
KNOWN_SQUEEZE = [
    # The About page's license box is 1px narrower than its content at 1.5x.
    ("Settings/About@1.5", "/BorderedFrame#0: needs 967x170, has 966x"),
]
BASE_W, BASE_H = 896, 540

# Free disk space changes as tests write files, and Settings shows it: pin it.
from core import system_info  # noqa: E402

system_info.disk_usage = lambda path: (500 * 1024 ** 3, 100 * 1024 ** 3)

app = M._make_app(log_qt=False)
M.init_workers()
M._apply_theme(app)
from ui.app import MainWindow  # noqa: E402

window = MainWindow()
window.present()


def settle(seconds=0.45):
    """Let layouts, animations (tab pipe 220ms, sub-tab 170ms) and posted events finish."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def set_scale(k):
    window.resize(round(BASE_W * k), round(BASE_H * k))
    settle()


def _paths(widget, prefix, out):
    """`{path: widget}` for every visible descendant; a path is class#n per level (n counting
    same-class siblings), so it is stable from run to run."""
    seen = {}
    for child in widget.children():
        if not isinstance(child, QWidget) or not child.isVisible() or child.isWindow():
            continue
        name = type(child).__name__
        seen[name] = seen.get(name, -1) + 1
        path = f"{prefix}/{name}#{seen[name]}"
        out[path] = child
        _paths(child, path, out)
    return out


def geometry():
    rects = {}
    for path, w in _paths(window, "", {}).items():
        at = w.mapTo(window, QPoint(0, 0))
        rects[path] = [at.x(), at.y(), w.width(), w.height()]
    return rects


def squeezed():
    """Visible widgets whose layout's minimum doesn't fit them."""
    bad = []
    for path, w in _paths(window, "", {}).items():
        lay = w.layout()
        if lay is None:
            continue
        need = lay.totalMinimumSize()
        if need.width() > w.width() or need.height() > w.height():
            bad.append(f"{path}: needs {need.width()}x{need.height()}, has {w.width()}x{w.height()}")
    return bad


def states():
    """(label, setup) for every page worth capturing."""
    out = []
    for tab in ("Muxing", "Encoding"):
        for sub in ("Overview", "Video", "Audio"):
            out.append((f"{tab}/{sub}", lambda t=tab, s=sub: (window.show_tab(t), window.tabs[t].sub_tab_bar.set_active(s))))
    out.append(("Downloader", lambda: window.show_tab("Downloader")))
    out.append(("Queue", lambda: window.show_tab("Queue")))
    for page in ("Appearance", "Output", "Performance", "Shortcuts", "About"):
        out.append((f"Settings/{page}", lambda p=page: (window.show_tab("Settings"),
                                                        window.tabs["Settings"].sub_tab_bar.set_active(p))))
    return out


def run():
    shots, squeeze, invariant = {}, [], []
    set_scale(1.0)
    for tab in ("Muxing", "Encoding"):                    # before any file: the no-file gate
        window.show_tab(tab)
        window.tabs[tab].sub_tab_bar.set_active("Overview")
        settle()
        shots[f"{tab}/Overview (no file)@1.0"] = geometry()

    path = fixture("sdr.mp4")
    window.media.select_file(path)
    deadline = time.monotonic() + 30
    while not (window.media.thumb_frames_path == path and window.media.thumb_frames) and time.monotonic() < deadline:
        settle(0.1)
    settle(0.8)
    window.tabs["Queue"].add_task("Fixture Clip", {"input_file": path, "output_path": os.path.join(WORK, "o.mp4")})

    for k in SCALES:
        set_scale(k)
        for label, setup in states():
            setup()
            settle()
            shots[f"{label}@{k}"] = geometry()
            squeeze += [f"{label}@{k}: {line}" for line in squeezed()]
        sizes = {}
        for tab in ("Muxing", "Encoding"):
            window.show_tab(tab)
            settle()
            t = window.tabs[tab]
            sizes[tab] = (t.carousel.width(), t.carousel.height(), t.panels.height())
        if sizes["Muxing"] != sizes["Encoding"]:
            invariant.append(f"@{k}: Muxing preview/panels {sizes['Muxing']} != Encoding {sizes['Encoding']}")

    known = [line for line in squeeze if any(line.startswith(k) and v in line for k, v in KNOWN_SQUEEZE)]
    squeeze = [line for line in squeeze if line not in known]
    ok = report(f"UI geometry ({len(shots)} page states, {sum(map(len, shots.values()))} widget rects)",
                check_golden("ui_geometry", shots))
    ok &= report("squeeze scan (no layout below its own minimum)", squeeze)
    for line in known:
        print(f"  KNOWN {line}")
    ok &= report("Muxing / Encoding previews identical at every scale", invariant)
    return ok


if __name__ == "__main__":
    run()
    harness.finish()
