# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Pixels: every SVG asset through each recolouring path, and a grab of every page at 1.0 and
1.5x, compared as hashes (golden). Anything that moves on its own clock is masked: marquees,
the loading spinner, a text caret. Hashes depend on this machine's fonts and Qt build, so a new
machine needs one `--update`. On a mismatch the new and old images are saved for comparison."""
import hashlib
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from harness import GOLDEN, WORK, check_golden, fixture, report  # noqa: E402

import check_ui  # noqa: E402  (isolated settings + the offscreen MainWindow)
from check_ui import app, settle, set_scale, states, window  # noqa: E402
from PySide6.QtCore import QPoint, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402

from ui.widgets.controls import MarqueeLabel  # noqa: E402
from ui.widgets.panels import ASSETS, LoadingSpinner  # noqa: E402

SHOTS = os.path.join(WORK, "render")
os.makedirs(SHOTS, exist_ok=True)
_COLORS = ("#ff0000", "#1a1a1a")


def _renderers(name, color):
    """{path name: QSvgRenderer} for asset `name` through every recolouring helper."""
    try:
        from ui.widgets.svg import svg_renderer
        return {"ink": svg_renderer(name, color, "ink"), "fills": svg_renderer(name, color, "fills"),
                "current": svg_renderer(name, color, "current"), "as-is": svg_renderer(name)}
    except ImportError:
        from ui.widgets import carousel, controls, frameless
        return {"ink": controls._icon_svg(name, color), "fills": frameless._tinted_svg(name, color),
                "current": carousel._svg_renderer(name, color), "as-is": carousel._svg_renderer(name)}


def _hash(image):
    image = image.convertToFormat(QImage.Format_ARGB32)
    return hashlib.sha1(bytes(image.constBits())[: image.sizeInBytes()]).hexdigest()[:16]


def icons():
    out = {}
    for name in sorted(n for n in os.listdir(ASSETS) if n.endswith(".svg")):
        for color in _COLORS:
            for path, renderer in _renderers(name, color).items():
                image = QImage(64, 64, QImage.Format_ARGB32_Premultiplied)
                image.fill(Qt.transparent)
                p = QPainter(image)
                renderer.render(p, QRectF(0, 0, 64, 64))
                p.end()
                out[f"{name} {path} {color}"] = _hash(image)
    return out


def page(label):
    """The window as painted, with anything clock-driven blanked."""
    image = window.grab().toImage()
    p = QPainter(image)
    for w in window.findChildren(MarqueeLabel) + window.findChildren(LoadingSpinner):
        if w.isVisible():
            at = w.mapTo(window, QPoint(0, 0))
            p.fillRect(at.x(), at.y(), w.width(), w.height(), QColor("#ff00ff"))
    p.end()
    image.save(os.path.join(SHOTS, label.replace("/", "_") + ".png"))
    return _hash(image)


def run():
    ok = report("SVG assets through every recolouring path", check_golden("render_icons", icons()))
    path = fixture("sdr.mp4")
    window.update_global_file(path)
    while not (window.thumb_frames_path == path and window.thumb_frames):
        settle(0.1)
    settle(0.8)
    window.setFocus()                       # no caret blinking in a text field
    shots = {}
    for k in (1.0, 1.5):
        set_scale(k)
        for label, setup in states():
            setup()
            settle()
            shots[f"{label}@{k}"] = page(f"{label}@{k}")
    ok &= report(f"page pixels ({len(shots)} page states; images in {SHOTS})", check_golden("render_pages", shots))
    return ok


if __name__ == "__main__":
    run()
