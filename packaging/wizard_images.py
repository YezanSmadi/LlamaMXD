# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""The installer's wizard images, drawn like the app's own sidebar (Lemon yellow, the Oswald title and its
underline, the llama, the copyright line) at every size Inno Setup picks from for each DPI setting."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

from core.theme import THEMES  # noqa: E402

# Inno Setup 6.6+: the large image's area at 100 / 125 / 150 / 175 / 200 / 225 / 250% scaling (aspect 164:314),
# and the square small image's.
LARGE_SIZES = ((202, 386), (269, 515), (336, 643), (403, 772), (430, 824), (498, 953), (534, 1022))
SMALL_SIZES = (58, 77, 97, 116, 124, 143, 159)

_REF_W, _REF_H = 202, 386   # the layout below is authored at the 100% size and scaled


def _app():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    folder = os.path.join(ROOT, "assets", "fonts")
    for name in os.listdir(folder):
        if name.lower().endswith((".ttf", ".otf")):
            QFontDatabase.addApplicationFont(os.path.join(folder, name))
    return app


def _title_font(px):
    font = QFont("Oswald")
    font.setPixelSize(px)
    font.setBold(True)
    font.setHintingPreference(QFont.PreferNoHinting)
    return font


def _draw_large(width, height, version):
    """The large image at `width` x `height` (any size of the 164:314 shape)."""
    k = width / _REF_W
    brand = THEMES["Lemon"]
    img = QImage(width, height, QImage.Format_ARGB32)
    img.fill(QColor(brand["primary"]))
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
    p.scale(k, k)
    ink = QColor("#000000")

    title_font = _title_font(34)
    fm = QFontMetricsF(title_font)
    title_w = fm.horizontalAdvance("LlamaMXD")
    p.setFont(title_font)
    p.setPen(ink)
    title_top = 42
    p.drawText(QRectF(0, title_top, _REF_W, fm.height()), Qt.AlignHCenter | Qt.AlignVCenter, "LlamaMXD")
    bar_y = title_top + fm.height() + 2
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(brand["secondary"]))
    p.drawRoundedRect(QRectF((_REF_W - title_w) / 2, bar_y, title_w, 3.5), 1.75, 1.75)

    logo = QSvgRenderer(os.path.join(ROOT, "assets", "LlamaMXD-Logo.svg"))
    box = logo.viewBoxF()
    logo_w = 158.0
    logo_h = logo_w * box.height() / box.width()
    logo.render(p, QRectF((_REF_W - logo_w) / 2, bar_y + 26, logo_w, logo_h))

    small = QFont("Roboto")
    small.setPixelSize(9)
    p.setFont(small)
    p.setPen(ink)
    p.drawText(QRectF(0, _REF_H - 30, _REF_W, 14), Qt.AlignHCenter | Qt.AlignVCenter, f"© 2026 Yezan Smadi   v{version}")
    p.end()
    return img


def _draw_small(side):
    """The square top-right image: the llama on the brand yellow."""
    img = QImage(side, side, QImage.Format_ARGB32)
    img.fill(QColor(THEMES["Lemon"]["primary"]))
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    logo = QSvgRenderer(os.path.join(ROOT, "assets", "LlamaMXD-Logo.svg"))
    box = logo.viewBoxF()
    h = side * 0.82
    w = h * box.width() / box.height()
    logo.render(p, QRectF((side - w) / 2, (side - h) / 2, w, h))
    p.end()
    return img


def make(out_dir, version):
    """Write the wizard PNGs into `out_dir`; the (large files, small files) comma-separated Inno lists."""
    _app()
    os.makedirs(out_dir, exist_ok=True)
    large, small = [], []
    for w, h in LARGE_SIZES:
        path = os.path.join(out_dir, f"side-{w}x{h}.png")
        _draw_large(w, h, version).save(path)
        large.append(path)
    for s in SMALL_SIZES:
        path = os.path.join(out_dir, f"small-{s}.png")
        _draw_small(s).save(path)
        small.append(path)
    return large, small


if __name__ == "__main__":
    out = os.path.join(ROOT, "build", "wizard")
    make(out, "1.0.0")
    print("wrote", out)
