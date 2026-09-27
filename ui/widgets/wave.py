# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""The Wave Loop visualiser, shown for stripped video and audio-only input: `Wave Loop.json`
rendered by rlottie, with the fixes its artwork needs (loop length, the centre seam)."""
import json
import math
import os
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QImage, QLinearGradient, QPainter
from PySide6.QtWidgets import QWidget

from core import llamalog
from ui import theme as T
from ui.widgets.panels import ASSETS, force_white_fills

# Wave Loop: rendered by rlottie, dots flattened to white, tinted primary -> secondary, the dot
# band cropped and scaled to fill.
_WAVE_BAND_LO = 0.42
_WAVE_BAND_HI = 0.95
_WAVE_FILL = 0.88
_CACHE = {}


def _shift_layer_time(layer, delta):
    """Move a Lottie layer `delta` frames: its start, out point and every keyframe inside it."""
    layer["st"] = layer.get("st", 0) + delta
    layer["op"] = layer.get("op", 0) + delta

    def walk(node):
        if isinstance(node, dict):
            if "t" in node and "s" in node:
                node["t"] += delta
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(layer.get("ks"))
    walk(layer.get("shapes"))


def _close_wave_seam(data):
    """Fix the split down the middle of the Wave Loop, in the parsed JSON. The picture is a
    precomp of "Main Dot" columns placed twice side by side; the last column is the first's
    wrap-around twin but starts at 240 where the 238-frame bob period needs 238, so the halves
    of the centre dots met 2 frames out of phase. Moves that column 2 frames. Guarded on that
    exact structure, so another animation is left alone."""
    every_layer = list(data.get("layers", [])) + [l for a in data.get("assets", []) for l in a.get("layers", [])]
    for asset in data.get("assets", []):
        columns = [l for l in asset.get("layers", []) if str(l.get("nm", "")).startswith("Main Dot")]
        width = next((l["w"] for l in every_layer if l.get("refId") == asset.get("id") and l.get("w")), None)
        if len(columns) < 3 or not width:
            continue
        try:
            def x_of(layer):
                return layer["ks"]["p"]["k"][0]["s"][0]

            first, last = min(columns, key=x_of), max(columns, key=x_of)
            keys = first["ks"]["p"]["k"]
            period = keys[2]["t"] - keys[0]["t"]
            if period <= 0 or abs(x_of(last) - x_of(first) - width) > 1:
                continue
            delta = round(last["st"] / period) * period - last["st"]
        except (KeyError, IndexError, TypeError):
            continue
        if 0.5 < abs(delta) < period / 4:
            _shift_layer_time(last, delta)


def _loop_length(animation, total):
    """How many of `total` frames make one loop: Wave Loop.json's last two frames repeat
    frames 0 and 1, and playing them stepped backwards at every restart. The shortest length
    near the end whose frame matches frame 0 (and the next, frame 1); `total` if none. Judged on
    a tiny alpha render, once."""
    width, height = 96, 54

    def alpha(index):
        return animation.lottie_animation_render(
            frame_num=index, width=width, height=height, bytes_per_line=width * 4)[3::4]

    def gap(a, b):
        return sum(abs(x - y) for x, y in zip(a, b)) / len(a)

    first, second = alpha(0), alpha(1)
    step = gap(first, second)
    if step <= 0:
        return total
    for length in range(max(total // 2, total - 8), total):
        if gap(alpha(length), first) > 0.05 * step:
            continue
        if length + 1 < total and gap(alpha(length + 1), second) > 0.05 * step:
            continue
        return length
    return total


def _wave():
    """`(animation, loop_frames, fps)` for Wave Loop.json, loaded once, or `(None, 0, 30)` if
    rlottie or the file is unavailable."""
    if "wave" not in _CACHE:
        _CACHE["wave"] = (None, 0, 30.0)
        try:
            from rlottie_python import LottieAnimation

            with open(os.path.join(ASSETS, "Wave Loop.json"), encoding="utf-8") as fh:
                data = json.load(fh)
            force_white_fills(data)
            _close_wave_seam(data)
            animation = LottieAnimation.from_data(json.dumps(data))
            total = animation.lottie_animation_get_totalframe() or 0
            _CACHE["wave"] = (
                animation,
                _loop_length(animation, total) if total > 1 else total,
                animation.lottie_animation_get_framerate() or 30.0,
            )
        except Exception:
            llamalog.get("ui").warning("The Wave Loop animation is unavailable (rlottie missing, or the file "
                                       "didn't load); a plain gradient is drawn instead", exc_info=True)
    return _CACHE["wave"]


class WaveLayer(QWidget):
    """The Wave Loop visualiser. A child of the tab, not the carousel, so it bleeds past the
    preview's margin; transparent to the mouse, so clicks and drops reach the carousel."""

    def __init__(self, carousel, host):
        super().__init__(host)
        self.carousel = carousel
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()
        self._frame = None       # QImage — the current tinted frame
        self._frame_key = None   # (idx, w, h, dpr, theme)
        self._t0 = time.monotonic()
        # Re-armed for when the next frame is due: a 16ms poll showed each ~33ms frame for an
        # uneven 2 or 3 ticks.
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)
        T.theme.changed.connect(self._invalidate)

    def start(self):
        if not self._timer.isActive():
            self._t0 = time.monotonic()
            if _wave()[0] is not None:
                self._schedule()
        self.show()
        self.raise_()
        self.update()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _invalidate(self):
        self._frame_key = None
        self.update()

    def _index(self):
        animation, frames, fps = _wave()
        if not frames:
            return 0
        return int((time.monotonic() - self._t0) * fps) % frames

    def _tick(self):
        if not self.isVisible():
            return          # not re-armed: `start()` does that when it is shown again
        idx = self._index()
        if self._frame_key is None or self._frame_key[0] != idx:
            self.update()
        self._schedule()

    def _schedule(self):
        """Arm the timer for when the next frame is due (rounded up, never just before it)."""
        _animation, _frames, fps = _wave()
        elapsed = time.monotonic() - self._t0
        due = (int(elapsed * fps) + 1) / fps
        self._timer.start(max(1, math.ceil((due - elapsed) * 1000)))

    def _render(self, idx):
        dpr = self.devicePixelRatioF() or 1.0
        w, h = max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr))
        key = (idx, w, h, dpr, T.theme.name, T.theme.resolved_mode())
        if key == self._frame_key and self._frame is not None:
            return self._frame
        out = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        out.fill(Qt.transparent)
        painter = QPainter(out)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        animation, frames, _fps = _wave()
        gradient = QLinearGradient(0, 0, w, 0)
        gradient.setColorAt(0, T.theme.color("primary"))
        gradient.setColorAt(1, T.theme.color("secondary"))
        if animation is None or frames <= 0:
            painter.setOpacity(0.12)
            painter.fillRect(0, 0, w, h, gradient)
        else:
            rw = max(8, w)
            rh = max(8, round(rw * 1080 / 1920))
            buffer = animation.lottie_animation_render(
                frame_num=idx % frames, width=rw, height=rh, bytes_per_line=rw * 4)
            dots = QImage(buffer, rw, rh, rw * 4, QImage.Format_ARGB32_Premultiplied)
            y0 = round(_WAVE_BAND_LO * rh)
            y1 = max(y0 + 1, round(_WAVE_BAND_HI * rh))
            band_h = max(1, round(h * _WAVE_FILL))
            painter.drawImage(QRectF(0, (h - band_h) / 2, w, band_h), dots,
                              QRectF(0, y0, rw, y1 - y0))
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(0, 0, w, h, gradient)
        painter.end()
        out.setDevicePixelRatio(dpr)
        self._frame, self._frame_key = out, key
        return out

    def paintEvent(self, _event):
        p = QPainter(self)
        p.drawImage(0, 0, self._render(self._index()))
        self.carousel.paint_badges(p, QRectF(self.rect()))
