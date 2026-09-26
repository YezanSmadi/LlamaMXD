# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Composite pieces: the sub-tab switch, the drop box, the export rundown, and
the sidebar + active-tab pipe."""
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import numpy as np
from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFileDialog, QGridLayout, QLabel, QVBoxLayout, QWidget

from core import llamalog
from ui import scale
from ui import theme as T
from ui import workers
from ui.scale import px
from ui.widgets.controls import button, restyle
from ui.widgets.marquee import MarqueeGroup, MarqueeLabel
from ui.widgets.text import ScaledLabel, ui_font

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSETS = os.path.join(_REPO_ROOT, "assets")
VERSION = "v0.5.0-beta.4"

MEDIA_FILTER = (
    "Media files (*.mp4 *.mkv *.mov *.webm *.avi *.m4v *.mxf *.ts *.vob "
    "*.mp3 *.m4a *.aac *.flac *.wav *.opus *.ogg *.wma *.aiff);;All files (*.*)"
)


def local_paths(mime):
    """Local file paths carried by a drag's mime data."""
    if not mime.hasUrls():
        return []
    return [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]


def force_white_fills(node):
    """Flatten every static Bodymovin shape fill and stroke to opaque white, so a
    rendered frame is a clean coverage mask a theme colour or gradient can tint."""
    if isinstance(node, dict):
        if node.get("ty") in ("fl", "st"):
            colour = node.get("c")
            if (isinstance(colour, dict) and isinstance(colour.get("k"), list)
                    and colour["k"] and not isinstance(colour["k"][0], dict)):
                colour["k"] = [1, 1, 1, 1]
        for value in node.values():
            force_white_fills(value)
    elif isinstance(node, list):
        for value in node:
            force_white_fills(value)


# --------------------------------------------------------------------------- #
#  SubTabBar
# --------------------------------------------------------------------------- #
class SubTabBar(QWidget):
    """Overview / Video / Audio: the active tab in `subtab_active` at full height, the others
    in `subtab_inactive` at 80%, standing flat on a line in the active colour. Height and fill
    ease between states. `set_marked` cross-fades a tab to STOP_RED (a stream removed on a panel
    out of sight)."""

    changed = Signal(str)

    _ACTIVE_H = 30.0
    _LINE_H = 4.0
    _INACTIVE_H = 24.0
    _GAP = 3.0
    _RADIUS = 6.0
    _PAD_X = 13.0

    def __init__(self, names, parent=None):
        super().__init__(parent)
        self._names = list(names)
        self._active = self._names[0]
        self._marked = set()
        self._hover = None
        self._bold13 = ui_font(13, bold=True)
        self._bold12 = ui_font(12, bold=True)
        fm = QFontMetricsF(self._bold13)
        self._widths = [max(58.0, fm.horizontalAdvance(n) + 2 * self._PAD_X) for n in self._names]
        total = sum(self._widths) + self._GAP * (len(self._names) - 1)
        scale.fixed(self, int(total + 0.999), int(self._ACTIVE_H + self._LINE_H))
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

        self._cur = {n: self._target(n) for n in self._names}
        self._from = dict(self._cur)
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(170)
        self._anim.setEasingCurve(QEasingCurve.InOutSine)
        self._anim.valueChanged.connect(self._step)
        T.theme.changed.connect(self._snap)

    def active(self):
        return self._active

    def set_active(self, name, emit=True):
        if name in self._names and name != self._active:
            self._active = name
            self._animate()
            if emit:
                self.changed.emit(name)

    def set_marked(self, name, marked):
        if (name in self._marked) != bool(marked):
            (self._marked.add if marked else self._marked.discard)(name)
            self._animate()

    def _target(self, name):
        """(fill, height, text colour) this button should settle on."""
        th = T.theme
        if name in self._marked:
            key = "stop"
        elif name == self._active:
            key = "subtab_active"
        else:
            key = "subtab_inactive"
        fill = th.color(f"{key}_hover" if name == self._hover else key)
        height = self._ACTIVE_H if name == self._active else self._INACTIVE_H
        return fill, height, th.color(f"{key}_text")

    def _animate(self):
        if not self.isVisible():
            self._snap()
            return
        self._from = dict(self._cur)
        self._anim.stop()
        self._anim.start()

    def _snap(self):
        self._anim.stop()
        self._cur = {n: self._target(n) for n in self._names}
        self.update()

    def _step(self, t):
        for n in self._names:
            (f0, h0, c0), (f1, h1, c1) = self._from[n], self._target(n)
            self._cur[n] = (T.lerp(f0, f1, t), h0 + (h1 - h0) * t, T.lerp(c0, c1, t))
        self.update()

    def _hit(self, x):
        edge = 0.0
        for n, w in zip(self._names, self._widths):
            if edge <= x < edge + w:
                return n
            edge += w + self._GAP
        return None

    def mouseMoveEvent(self, e):
        h = self._hit(scale.ref_pos(e.position()).x())
        if h != self._hover:
            self._hover = h
            self._animate()

    def leaveEvent(self, e):
        if self._hover is not None:
            self._hover = None
            self._animate()

    def mousePressEvent(self, e):
        n = self._hit(scale.ref_pos(e.position()).x())
        if n:
            self.set_active(n)

    def nav_stops(self):
        """The keyboard's stops: `(rect in real pixels, activate)` per tab."""
        f = scale.factor()
        edge, stops = 0.0, []
        for n, w in zip(self._names, self._widths):
            stops.append((QRectF(edge * f, 0, w * f, self._ACTIVE_H * f).toRect(),
                          lambda n=n: self.set_active(n)))
            edge += w + self._GAP
        return stops

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        scale.begin(p)
        width, height = scale.ref_size(self)
        # Snapped to a whole device pixel: mid-pixel, the tab clip and the line's edge each cover
        # part of the row and a seam shows under the tab.
        foot = round(self._ACTIVE_H * scale.factor()) / scale.factor()
        edge = 0.0
        p.save()
        p.setClipRect(QRectF(0, 0, width, foot))
        for n, w in zip(self._names, self._widths):
            fill, h, text = self._cur[n]
            rect = QRectF(edge, foot - h, w, h)
            # A radius taller than visible, so the clip cuts off the bottom rounding.
            path = QPainterPath()
            path.addRoundedRect(rect.adjusted(0, 0, 0, self._RADIUS), self._RADIUS, self._RADIUS)
            p.fillPath(path, fill)
            p.setPen(text)
            p.setFont(self._bold13 if n == self._active else self._bold12)
            p.drawText(rect, Qt.AlignCenter, n)
            edge += w + self._GAP
        p.restore()
        # In the selected tab's colour, so tab and line read as one piece.
        p.fillRect(QRectF(0, foot, width, height - foot), T.theme.color("subtab_active"))


# --------------------------------------------------------------------------- #
#  LoadingSpinner
# --------------------------------------------------------------------------- #
# A spinning CD-R (assets/LlamaDiscLoading, a PNG sequence), drawn as is except the pink stripe
# and rim on the label side, which take the theme's primary (`_recolor`).
_LOADING_DIR = os.path.join(ASSETS, "LlamaDiscLoading")
_LOADING_FPS = 60.0
_LOADING_FRAMES = 143
_LOADING_SOURCE = 640   # the PNGs' own size
# Colours as rendered into the PNGs. Themed: the pink stripe and rim, and the hub's inner edge,
# which is the translucent hub overlay over that pink (see `_ring_colour`).
_STROKE_PINK = np.array([223, 97, 164], dtype=np.float32)
_HUB_OVERLAY = np.array([250, 211, 155], dtype=np.float32)
_OVERLAY_ALPHA = 0.5
# What each is drawn against: an edge pixel is a blend of a stroke colour and one of these.
_LABEL_ORANGE = np.array([255, 186, 84], dtype=np.float32)
_HUB_COLLAR = np.array([214, 151, 67], dtype=np.float32)


def _ring_colour(base):
    """The hub overlay at 50% alpha composited onto `base`: `alpha * overlay + (1 - alpha) * base`."""
    return _OVERLAY_ALPHA * _HUB_OVERLAY + (1 - _OVERLAY_ALPHA) * base


# (rendered colour, colours it blends with at its edges): stripe/rim, then the hub's inner edge.
_STROKES = (
    (_STROKE_PINK, (_LABEL_ORANGE, _HUB_COLLAR)),
    (_ring_colour(_STROKE_PINK), (_HUB_COLLAR, _HUB_OVERLAY)),
)
_TOLERANCE = 16   # how far off the blend line (in 0-255 colour units) still counts
_LOADING = {}


def _candidate_box():
    """`(lo, hi)` RGB bounds holding every colour `_share` can score above 0: each blend line
    from its background through the stroke colour to where it leaves the colour cube (a share
    is measured off the infinite line, capped at 1), widened by the tolerance."""
    lo, hi = np.full(3, 255.0), np.zeros(3)
    for colour, backgrounds in _STROKES:
        for background in backgrounds:
            step = colour - background
            with np.errstate(divide="ignore"):
                exits = np.where(step > 0, (255 - background) / step,
                                 np.where(step < 0, -background / step, np.inf))
            end = background + (exits.min() + _TOLERANCE / np.linalg.norm(step)) * step
            lo, hi = np.minimum(lo, np.minimum(background, end)), np.maximum(hi, np.maximum(background, end))
    return (np.clip(np.floor(lo - _TOLERANCE), 0, 255).astype(np.uint8),
            np.clip(np.ceil(hi + _TOLERANCE), 0, 255).astype(np.uint8))


_BOX_LO, _BOX_HI = _candidate_box()


def _share(rgb, colour, backgrounds):
    """Each pixel's 0-1 share of `colour`, as a blend with the nearest of `backgrounds`, if
    within `_TOLERANCE` of that line (which keeps the rainbow's own pinks out)."""
    best = np.zeros(len(rgb), dtype=np.float32)
    for background in backgrounds:
        line = colour - background
        t = (rgb - background) @ line / float(line @ line)
        off = np.linalg.norm(rgb - (background + t[..., None] * line), axis=-1)
        best = np.maximum(best, np.clip(t, 0, 1) * np.clip(1 - off / _TOLERANCE, 0, 1))
    return best


def _stroke_weights(pixels):
    """`(indices, weights, kinds)` of a frame's themed pixels: each one's share of its stroke
    colour and which of `_STROKES` it is. Pixels under 20% are ignored."""
    # Only visible pixels inside the candidate box can score; of those, each distinct colour is
    # scored once (flat-colour art) and looked up.
    flat = pixels.reshape(-1, 4)
    inside = flat[:, 3] > 0
    for channel in range(3):
        inside &= (flat[:, channel] >= _BOX_LO[channel]) & (flat[:, channel] <= _BOX_HI[channel])
    candidates = np.flatnonzero(inside)
    sub = flat[candidates]
    packed = (sub[:, 0].astype(np.int32) << 16) | (sub[:, 1].astype(np.int32) << 8) | sub[:, 2]
    colours, inverse = np.unique(packed, return_inverse=True)
    rgb = np.stack([colours >> 16, (colours >> 8) & 255, colours & 255], axis=-1).astype(np.float32)
    shares = np.stack([_share(rgb, colour, backgrounds) for colour, backgrounds in _STROKES])
    kinds = shares.argmax(0)[inverse]
    best = shares.max(0)[inverse]
    # Without the stripe (the rainbow side, edge-on frames) any match is a look-alike.
    if ((kinds == 0) & (best > 0.6)).sum() < 100:
        empty = np.empty(0, dtype=np.intp)
        return empty, np.empty(0, dtype=np.float32), np.empty(0, dtype=np.intp)
    keep = np.flatnonzero(best > 0.2)
    return candidates[keep], np.clip((best[keep] - 0.2) / 0.8, 0, 1), kinds[keep]


def _frame_side(side):
    """The decode size for a spinner `side` px across: up to a multiple of 64 (so a drag
    doesn't re-decode each step), at most the PNGs' own size."""
    return max(64, min(_LOADING_SOURCE, math.ceil(side / 64) * 64))


def _load_frames(side):
    """Decode the sequence at `side` px (worker thread): `[(QImage, indices, deltas, original)]`
    or None. The image is premultiplied; `deltas` (n x 2) are each themed pixel's move per unit
    of each stroke's change. Weights are scored at full size and shrunk with the image's area
    filter: recolouring is linear, so this equals recolour-then-scale (scoring the shrunk frame
    left a pink fringe on the thin rim)."""
    # Frames are independent and numpy / OpenCV / Qt work outside the GIL: split them over up to
    # half the CPUs, leaving the rest to the window being built meanwhile.
    workers = max(1, min(3, (os.cpu_count() or 1) // 2))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        frames = list(pool.map(lambda n: _load_frame(n, side), range(_LOADING_FRAMES)))
    return None if any(frame is None for frame in frames) else frames


def _load_frame(n, side):
    """Frame `n` of the sequence as `_load_frames` describes, or None if it can't be read."""
    import cv2   # only needed here, on the worker
    image = QImage(os.path.join(_LOADING_DIR, f"{n:03d}.png"))
    if image.isNull():
        return None
    image = image.convertToFormat(QImage.Format_RGBA8888)
    h, w = image.height(), image.width()
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8,
                           count=h * image.bytesPerLine()).reshape(h, image.bytesPerLine())[:, : w * 4].reshape(h, w, 4)
    idx, weights, kinds = _stroke_weights(pixels)
    alpha = pixels[..., 3].astype(np.float32) / 255
    premult = pixels.astype(np.float32)
    premult[..., :3] *= alpha[..., None]
    deltas = np.zeros((h * w, 2), dtype=np.float32)
    deltas[idx, kinds] = weights * alpha.ravel()[idx]
    deltas = deltas.reshape(h, w, 2)
    if side < w:
        premult = cv2.resize(premult, (side, side), interpolation=cv2.INTER_AREA)
        deltas = cv2.resize(deltas, (side, side), interpolation=cv2.INTER_AREA)
    out = np.ascontiguousarray(np.clip(np.rint(premult), 0, 255).astype(np.uint8))
    small = QImage(out.data, out.shape[1], out.shape[0], out.shape[1] * 4,
                   QImage.Format_RGBA8888_Premultiplied).copy()
    deltas = deltas.reshape(-1, 2)
    themed = np.flatnonzero(deltas.max(1) > 1e-3)
    return small, themed, deltas[themed], premult.reshape(-1, 4)[themed]


def _request_frames(side):
    """Decode the frames for a spinner `side` px across on a worker, unless that size is loaded
    or loading. A spinner keeps drawing the previous size meanwhile."""
    want = _frame_side(side)
    _LOADING["want"] = want
    if _LOADING.get("failed") or _LOADING.get("busy") or _LOADING.get("side") == want:
        return
    _LOADING["busy"] = True

    def done(frames):
        _LOADING["busy"] = False
        if frames:
            # Resized again meanwhile: keep this only if there is nothing to draw yet.
            if _LOADING["want"] == want or not _LOADING.get("frames"):
                _LOADING["frames"], _LOADING["side"] = frames, want
            if _LOADING["want"] != want:
                _request_frames(_LOADING["want"])
        else:
            _LOADING["failed"] = True
            llamalog.get("ui").warning("The loading animation (assets/LlamaDiscLoading) failed to "
                                       "load; the spinner stays blank")

    def work():
        try:
            return _load_frames(want)
        except Exception:
            llamalog.get("ui").warning("Decoding the loading animation failed", exc_info=True)
            return None

    workers.run_async(work, done)


def _recolor(frame, rgb):
    """A copy of a frame with its themed pixels moved to `rgb`: the stripe and rim from the
    pink to `rgb`, the hub's inner edge from `_ring_colour(pink)` to `_ring_colour(rgb)`."""
    image, idx, deltas, original = frame
    out = image.copy()
    if len(idx):
        pixels = np.frombuffer(out.bits(), dtype=np.uint8, count=out.height() * out.bytesPerLine())
        pixels = pixels.reshape(out.height(), out.bytesPerLine())[:, : out.width() * 4].reshape(-1, 4)
        theme = np.array(rgb, dtype=np.float32)
        moves = np.stack([theme - _STROKES[0][0], _ring_colour(theme) - _STROKES[1][0]])
        shifted = original[:, :3] + deltas @ moves
        pixels[idx, :3] = np.rint(np.clip(shifted, 0, original[:, 3:])).astype(np.uint8)
    return out


class LoadingSpinner(QWidget):
    """The LlamaDisc spinner. Plays only while shown, lets mouse events through, and draws
    nothing until (or unless) its frames are decoded."""

    DEFAULT_SIZE = 64  # real px, until the host calls set_side()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.resize(self.DEFAULT_SIZE, self.DEFAULT_SIZE)
        self._t0 = time.monotonic()
        # Re-armed for when the next frame is due (a 16ms poll gives uneven frames).
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)
        # Decoded for the size the host settles on, not every size a drag passes.
        self._size_timer = QTimer(self)
        self._size_timer.setSingleShot(True)
        self._size_timer.setInterval(300)
        self._size_timer.timeout.connect(self._request_frames)
        T.theme.changed.connect(self.update)

    def _request_frames(self):
        # Only for a host on screen: a never-shown tab's drop box is an unlaid-out 640x480.
        host = self.parentWidget()
        if host is None or host.isVisible():
            _request_frames(self.width() * (self.devicePixelRatioF() or 1.0))

    def showEvent(self, e):
        self._t0 = time.monotonic()
        self._size_timer.stop()
        self._request_frames()
        self._schedule()

    def hideEvent(self, e):
        self._timer.stop()

    def set_side(self, side):
        """A `side` x `side` square in real px, from the host. A plain resize: this is a
        floating overlay, not layout-managed."""
        side = max(1, round(side))
        if side != self.width() or side != self.height():
            self.resize(side, side)
            self._size_timer.start()

    def _tick(self):
        if self.isVisible():
            self.update()
            self._schedule()

    def _schedule(self):
        """Arm the timer for when the next frame is due (rounded up)."""
        elapsed = time.monotonic() - self._t0
        due = (int(elapsed * _LOADING_FPS) + 1) / _LOADING_FPS
        self._timer.start(max(1, math.ceil((due - elapsed) * 1000)))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        idx = int((time.monotonic() - self._t0) * _LOADING_FPS) % _LOADING_FRAMES
        frames = _LOADING.get("frames")
        if frames:
            primary = T.theme.color("primary")
            p.drawImage(self.rect(), _recolor(frames[idx], (primary.red(), primary.green(), primary.blue())))


# --------------------------------------------------------------------------- #
#  DropBox
# --------------------------------------------------------------------------- #
class DropBox(QWidget):
    """The secondary-bordered drop target: drop a file, double-click, or Browse. Once a file
    is picked, `collapse()` swaps the prompt, border and Browse for the loading spinner."""

    fileSelected = Signal(str)

    def __init__(self, prompt="Drag & Drop File Here", parent=None, start_dir=None):
        """`start_dir`: an optional callable giving the folder Browse opens in."""
        super().__init__(parent)
        self._start_dir = start_dir
        self._prompt_text = prompt
        self.setAcceptDrops(True)
        self._dragging = False
        self._collapsed = False

        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        scale.spacing(lay, 14)
        self.prompt = ScaledLabel(prompt)
        # An instance-level rule, not `set_font_px`: a plain setFont is overridden by the
        # class rule at the next polish, and a hidden tab missed that re-polish after a rescale.
        self.prompt.setStyleSheet("font-size: 14px;")
        self.prompt.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.prompt)
        self.or_label = ScaledLabel("— or —")
        self.or_label.setStyleSheet("font-size: 14px;")
        self.or_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.or_label)
        self.browse_btn = button("Browse File", width=140)
        self.browse_btn.clicked.connect(self.browse)
        lay.addWidget(self.browse_btn, 0, Qt.AlignCenter)
        # A floating overlay, not in `lay`: a layout-managed spinner's size would floor the
        # box's minimum, so it could never shrink again. Hidden until `collapse()`.
        self.spinner = LoadingSpinner(self)
        self.spinner.hide()
        T.theme.changed.connect(self.update)

    def _set_prompt(self, text, role=""):
        """The prompt's wording and stylesheet role (`error` is STOP_RED), restyled."""
        self.prompt.setText(text)
        self.prompt.setProperty("role", role)
        restyle(self.prompt)

    def _resize_spinner(self):
        """Fill the box's height with the spinner (less a margin), centred; height, since the
        box is normally landscape."""
        margin = scale.px(8)
        side = max(1, min(self.height(), self.width()) - margin * 2)
        self.spinner.set_side(side)
        self.spinner.move((self.width() - side) // 2, (self.height() - side) // 2)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._resize_spinner()

    def collapse(self):
        """A file was picked and its previews are loading: show the spinner instead."""
        self._collapsed = True
        self._set_prompt(self._prompt_text)
        self.prompt.hide()
        self.or_label.hide()
        self.browse_btn.hide()
        self._resize_spinner()
        self.spinner.raise_()
        self.spinner.show()
        self.update()

    def show_no_preview(self):
        """A file is in use but has no preview frames: the border and Browse stay, the prompt
        says so in red."""
        self._collapsed = False
        self._set_prompt("No Preview Available", "error")
        self.prompt.show()
        self.or_label.hide()
        self.spinner.hide()
        self.browse_btn.show()
        self.update()

    def reset(self):
        """Undo `collapse()`: back to the pristine drag/drop prompt (a rejected import)."""
        self._collapsed = False
        self._set_prompt(self._prompt_text)
        self.prompt.show()
        self.or_label.show()
        self.spinner.hide()
        self.browse_btn.show()
        self.update()

    def browse(self):
        start = self._start_dir() if self._start_dir else ""
        path, _ = QFileDialog.getOpenFileName(self, "Select a File", start, MEDIA_FILTER)
        if path:
            self.fileSelected.emit(path)

    def mouseDoubleClickEvent(self, e):
        self.browse()

    def dragEnterEvent(self, e):
        if local_paths(e.mimeData()):
            e.acceptProposedAction()
            self._dragging = True
            self.update()

    def dragLeaveEvent(self, e):
        self._dragging = False
        self.update()

    def dropEvent(self, e):
        self._dragging = False
        self.update()
        paths = local_paths(e.mimeData())
        if paths:
            self.fileSelected.emit(paths[0])

    def paintEvent(self, _event):
        if self._collapsed and not self._dragging:
            return
        th = T.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        scale.begin(p)
        rect = scale.ref_rect(self).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        if self._dragging:
            p.fillPath(path, T.with_alpha(th.color("secondary"), 0.11))
        p.setPen(QPen(th.color("secondary_hover" if self._dragging else "secondary"), 2))
        p.drawPath(path)


class BorderedFrame(QWidget):
    """The DropBox's rounded border without the drop behaviour (the Downloader preview,
    Muxing's track box)."""

    def __init__(self, parent=None, color_key="primary"):
        super().__init__(parent)
        self._color_key = color_key
        T.theme.changed.connect(self.update)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        scale.begin(p)
        path = QPainterPath()
        path.addRoundedRect(scale.ref_rect(self).adjusted(1, 1, -1, -1), 10, 10)
        p.setPen(QPen(T.theme.color(self._color_key), 2))
        p.drawPath(path)


# --------------------------------------------------------------------------- #
#  SummaryPanel
# --------------------------------------------------------------------------- #
class SummaryPanel(QWidget):
    """The Overview rundown: `label  value` rows whose values marquee when long."""

    def __init__(self, labels, parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        scale.grid_spacing(grid, 0, 12)
        self._values = []
        # One group, so every row sweeps and restarts in step.
        marquee_group = MarqueeGroup()
        for row, text in enumerate(labels):
            lab = ScaledLabel(text)
            lab.setProperty("role", "muted")
            lab.setStyleSheet("font-weight: bold;")
            scale.fixed(lab, w=72)
            grid.addWidget(lab, row, 0)
            val = MarqueeLabel("—", pixel_size=11, group=marquee_group)
            grid.addWidget(val, row, 1)
            self._values.append(val)
        grid.setColumnStretch(1, 1)

    def set_values(self, rows):
        """`rows` = [(text, color_key_or_None), ...] in label order."""
        for label, (text, color) in zip(self._values, rows):
            label.setText(text)
            label.set_color_key(color or "text")


class _AccentBar(QWidget):
    """A thin secondary-coloured bar: the sidebar title's underline."""

    def __init__(self, width, height=4, parent=None):
        super().__init__(parent)
        scale.fixed(self, width, height)
        T.theme.changed.connect(self.update)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        scale.begin(p)
        p.setPen(Qt.NoPen)
        p.setBrush(T.theme.color("secondary"))
        rect = scale.ref_rect(self)
        r = rect.height() / 2
        p.drawRoundedRect(rect, r, r)


# --------------------------------------------------------------------------- #
#  Sidebar + active-tab pipe
# --------------------------------------------------------------------------- #
class Sidebar(QWidget):
    """Title, logo, the four nav buttons, then Settings and the footer at the bottom."""

    navigate = Signal(str)
    WIDTH = 200
    LOGO_SIZE = 170

    def __init__(self, parent=None):
        super().__init__(parent)
        scale.fixed(self, w=self.WIDTH)
        lay = QVBoxLayout(self)
        scale.margins(lay, 0, 24, 0, 10)
        lay.setSpacing(0)

        title = ScaledLabel("LlamaMXD")
        title.setProperty("role", "sidebarTitle")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        title_width = QFontMetricsF(ui_font(36, bold=True, family="Oswald")).horizontalAdvance("LlamaMXD")
        underline = _AccentBar(round(title_width))
        lay.addWidget(underline, 0, Qt.AlignHCenter)
        scale.spacer(lay, 20)

        self.logo = QLabel()
        scale.fixed(self.logo, self.LOGO_SIZE, self.LOGO_SIZE)
        self._load_logo()
        lay.addWidget(self.logo, 0, Qt.AlignHCenter)
        scale.spacer(lay, 10)

        self.buttons = {}
        for name in ("Muxing", "Encoding", "Downloader", "Queue"):
            scale.spacer(lay, 10)
            self._add_nav(lay, name)
            scale.spacer(lay, 10)
        lay.addStretch(1)
        self._add_nav(lay, "Settings")
        scale.spacer(lay, 8)

        footer = ScaledLabel(f"© {datetime.now().year} Yezan Smadi     {VERSION}")
        footer.setProperty("role", "sidebarFooter")
        footer.setAlignment(Qt.AlignCenter)
        lay.addWidget(footer)
        T.theme.changed.connect(self._load_logo)
        scale.changed.connect(self._load_logo)
        T.theme.changed.connect(self.update)

    NAV_BUTTON_WIDTH = 110  # narrower than the sidebar, so the cable's lead shows behind it

    def _add_nav(self, lay, name):
        btn = button(name)
        scale.fixed(btn, self.NAV_BUTTON_WIDTH, 28)
        btn.clicked.connect(lambda _=False, n=name: self.navigate.emit(n))
        lay.addWidget(btn, 0, Qt.AlignHCenter)
        self.buttons[name] = btn

    _LOGO_OVERSAMPLE = 4  # rendered above any real screen DPR, then scaled down — never up
    _logo_renderer = None  # the parsed SVG, loaded once and reused by every Sidebar instance

    def _load_logo(self):
        """Re-render the tinted logo, only when its pixel size or tint changed (it is called
        on every live-resize step)."""
        box = px(self.LOGO_SIZE) * self._LOGO_OVERSAMPLE
        color = T.theme.color("sidebar_text")
        key = (box, color.rgba())
        if getattr(self, "_logo_key", None) == key:
            return
        if Sidebar._logo_renderer is None:
            Sidebar._logo_renderer = QSvgRenderer(os.path.join(ASSETS, "LlamaMXD-Logo.svg"))
        renderer = Sidebar._logo_renderer
        if not renderer.isValid():
            return
        self._logo_key = key
        native = renderer.defaultSize()
        k = box / max(native.width(), native.height())
        w, h = native.width() * k, native.height() * k
        x, y = (box - w) / 2, (box - h) / 2
        img = QImage(box, box, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        renderer.render(p, QRectF(x, y, w, h))
        p.end()

        # Tinted like the title (`sidebar_text`); SourceIn keeps the art's alpha.
        tint = QPainter(img)
        tint.setCompositionMode(QPainter.CompositionMode_SourceIn)
        tint.fillRect(img.rect(), color)
        tint.end()

        pix = QPixmap.fromImage(img)
        pix.setDevicePixelRatio(self._LOGO_OVERSAMPLE)
        self.logo.setPixmap(pix)

    def paintEvent(self, _event):
        QPainter(self).fillRect(self.rect(), T.theme.color("primary"))


_CABLE_SVG = os.path.join(ASSETS, "RCA Cable Yellow.svg")
_CABLE_OVERSAMPLE = 4  # rendered above any real screen DPR, then scaled down — never up
_cable_base_cache = {}
_cable_pixmap_cache = {}


def _cable_base_image():
    """The RCA cable art rendered once at high resolution, cropped to what it draws (its
    viewBox is ~3x wider than the plug)."""
    cached = _cable_base_cache.get("img")
    if cached is not None:
        return cached
    renderer = QSvgRenderer(_CABLE_SVG)
    if not renderer.isValid():
        return None
    native = renderer.defaultSize()
    k = 3
    w, h = round(native.width() * k), round(native.height() * k)
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p, QRectF(0, 0, w, h))
    p.end()

    stride = img.bytesPerLine()
    raw = np.frombuffer(img.constBits(), dtype=np.uint8, count=h * stride).reshape(h, stride)[:, : w * 4]
    raw = raw.reshape(h, w, 4)
    alpha = raw[:, :, 3]
    cols = np.where(alpha.any(axis=0))[0]
    rows = np.where(alpha.any(axis=1))[0]
    if len(cols) and len(rows):
        img = img.copy(int(cols[0]), int(rows[0]), int(cols[-1] - cols[0] + 1), int(rows[-1] - rows[0] + 1))
    _cable_base_cache["img"] = img
    return img


def _cable_pixmap(height):
    """The cropped cable rotated 90° clockwise (collar toward the tab frame, cable toward the
    button), `height` px tall, cached per height."""
    cached = _cable_pixmap_cache.get(height)
    if cached is not None:
        return cached
    base = _cable_base_image()
    if base is None or base.isNull():
        return None
    w0 = height * _CABLE_OVERSAMPLE
    h0 = w0 * base.height() / base.width()
    scaled = base.scaled(round(w0), round(h0), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    pix = QPixmap.fromImage(scaled).transformed(QTransform().rotate(90), Qt.SmoothTransformation)
    pix.setDevicePixelRatio(_CABLE_OVERSAMPLE)
    _cable_pixmap_cache[height] = pix
    return pix


class _TabPipe(QWidget):
    """One nav button's RCA cable, sliding from the button toward the tab frame. `extension`
    0 is hidden (flush with the button's edge); at 1 the thin pin has gone past the frame's
    edge, like a pin into a jack, while the collar and shell stay visible. One per button, so
    the outgoing and incoming cables animate at once."""

    # Share of the art's length taken by the thin pin (its wider base collar excluded).
    _PIN_FRAC = 142.23 / 825.37
    _MARGIN = 6  # vertical breathing room within the button's own row height

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._extension = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._set_extension)
        T.theme.changed.connect(self.update)

    def _set_extension(self, value):
        self._extension = value
        self.update()

    def set_active(self, active, animate=True):
        target = 1.0 if active else 0.0
        self._anim.stop()
        if animate:
            self._anim.setStartValue(self._extension)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._set_extension(target)

    def paintEvent(self, _event):
        if self._extension <= 0:
            return
        pix = _cable_pixmap(max(1, self.height() - px(self._MARGIN)))
        if pix is None:
            return
        dpr = pix.devicePixelRatio()
        img_w, img_h = pix.width() / dpr, pix.height() / dpr

        # Hidden: the tip flush with x=0 (the button's edge). Shown: the tip past the frame's
        # edge by exactly the pin's width.
        hidden_x = -img_w
        shown_x = self.width() - img_w * (1 - self._PIN_FRAC)
        x = hidden_x + (shown_x - hidden_x) * self._extension
        y = (self.height() - img_h) / 2

        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawPixmap(QPointF(x, y), pix)


class TabIndicator(QWidget):
    """Owns one `_TabPipe` per nav button: selecting a tab plugs its cable in while the
    previous one pulls out. Paints nothing itself."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._buttons = {}
        self._pipes = {}
        self._active = None
        self._frame_left = 0
        T.theme.changed.connect(self.update)

    def set_active(self, name, buttons, frame_left, animate=True):
        """Re-lay every pipe (a button's position is final only once shown), then animate the
        outgoing pipe out and the incoming one in."""
        self._buttons = buttons
        self._frame_left = frame_left
        parent = self.parentWidget()
        self.setGeometry(0, 0, parent.width(), parent.height())
        for btn_name, btn in buttons.items():
            top_left = btn.mapTo(parent, btn.rect().topLeft())
            x = top_left.x() + btn.width()
            pipe = self._pipes.get(btn_name)
            if pipe is None:
                pipe = _TabPipe(self)
                # Created after its parent was shown, so it must be shown explicitly.
                pipe.show()
                self._pipes[btn_name] = pipe
            pipe.setGeometry(x, top_left.y(), max(1, frame_left - x), btn.height())
        self._active = name
        for btn_name, pipe in self._pipes.items():
            pipe.set_active(btn_name == name, animate=animate)
        self.show()
        self.raise_()
        for pipe in self._pipes.values():
            pipe.raise_()
        self.update()

