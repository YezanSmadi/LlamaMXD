"""The preview carousel — up to ten frames of the selected file, with hover
chevrons, a sliding transition, a re-flowing dot row, the info badge + its
tooltip, the mute badge, and the Wave Loop visualiser for stripped video /
audio-only input.

The chevron discs and dots are antialiased QPainter shapes, the hover fade
is painter opacity, the slide draws two cached pixmaps at an offset, and the
Wave Loop paints straight onto a widget.

The dot row: the centre three dots are large and screen-stationary; beyond
them two per side taper medium-then-small, and only frames that exist get a
dot (7 wide in the interior, 5 at the ends). The current-frame highlight
rides toward the cluster edge it's heading for and the row only scrolls once
it's already there, so a direction change walks the highlight back across
the middle slot first. The row re-flows on the same eased clock as the
picture slide."""
import json
import os
import time

from PySide6.QtCore import QByteArray, QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QLabel, QWidget

from ui import theme as T
from ui.widgets.panels import ASSETS, local_paths

# Dot indicators (see the module docstring for the design).
_DOT_R_LARGE = 4.0
_DOT_R_MED = 3.0
_DOT_R_SMALL = 2.0
_DOT_GAP = 16.0
_DOT_CLUSTER = 3
_DOT_LOOK = 2
_DOT_ON = QColor(255, 255, 255, 235)
_DOT_OFF = QColor(255, 255, 255, 90)

_FADE_MS = 100
_SLIDE_MS = 115

# Wave Loop: rendered by rlottie, dots flattened to white and tinted with the
# primary→secondary gradient; the dot band is cropped and scaled to fill.
_WAVE_INTERVAL_MS = 16
_WAVE_BAND_LO = 0.42
_WAVE_BAND_HI = 0.95
_WAVE_FILL = 0.88

_CACHE = {}


def _force_white_fills(node):
    """Flatten every static Bodymovin shape fill to opaque white, so a frame
    is a clean coverage mask the gradient can tint."""
    if isinstance(node, dict):
        if node.get("ty") == "fl":
            colour = node.get("c")
            if (isinstance(colour, dict) and isinstance(colour.get("k"), list)
                    and colour["k"] and not isinstance(colour["k"][0], dict)):
                colour["k"] = [1, 1, 1, 1]
        for value in node.values():
            _force_white_fills(value)
    elif isinstance(node, list):
        for value in node:
            _force_white_fills(value)


def _wave():
    """`(animation, total_frames, fps)` for Wave Loop.json, loaded once — or
    `(None, 0, 30)` if rlottie isn't importable / the file won't parse."""
    if "wave" not in _CACHE:
        _CACHE["wave"] = (None, 0, 30.0)
        try:
            from rlottie_python import LottieAnimation

            with open(os.path.join(ASSETS, "Wave Loop.json"), encoding="utf-8") as fh:
                data = json.load(fh)
            _force_white_fills(data)
            animation = LottieAnimation.from_data(json.dumps(data))
            _CACHE["wave"] = (
                animation,
                animation.lottie_animation_get_totalframe() or 0,
                animation.lottie_animation_get_framerate() or 30.0,
            )
        except Exception:
            pass
    return _CACHE["wave"]


def _svg_renderer(name, color=None):
    """A cached `QSvgRenderer` for `assets/<name>`, optionally with every
    `fill="currentColor"` in the file swapped for a literal `color` hex
    string before parsing — how the info badge gets a runtime, appearance-
    aware recolor without touching the SVG asset itself (see
    `_paint_info_badge`). `color=None` renders the file exactly as authored
    (the mute badge's own fixed red/white never changes with the theme)."""
    key = f"svg:{name}:{color}"
    if key not in _CACHE:
        with open(os.path.join(ASSETS, name), "r", encoding="utf-8") as fh:
            data = fh.read()
        if color:
            data = data.replace('fill="currentColor"', f'fill="{color}"')
        _CACHE[key] = QSvgRenderer(QByteArray(data.encode("utf-8")))
    return _CACHE[key]


def _paint_info_badge(painter, rect):
    """The info badge, rendered from `assets/info.svg` rather than hand-drawn
    primitives. That SVG is a single solid disc with the "i" glyph cut out
    as a hole (confirmed by rendering it over a contrasting backdrop, where
    the hole never reaches past ~70% of the circle's own radius) — so the
    two-tone, appearance-aware look comes from painting a plain circle in
    the glyph colour first and the SVG, recoloured to the disc colour, on
    top of it: everywhere the SVG is solid it covers that circle with the
    disc colour, and everywhere it's the letter-shaped hole, the glyph-
    coloured circle underneath shows through as the "i". Dark mode gets a
    dark disc with a white glyph, light mode a white disc with a dark glyph
    — deliberately colour-neutral in every theme rather than the theme's own
    accent colour, matching the artwork this replaces.

    The backdrop circle is drawn noticeably smaller than `rect`, not the
    same size — the SVG's own circle touches `rect`'s edge exactly, and a
    same-size backdrop's antialiased edge doesn't quite land on the same
    pixels as the SVG renderer's own, leaving a faint ring of the glyph
    colour peeking past the disc's outer edge (confirmed: visible as a thin
    white outline around the dark-mode disc). Shrinking it to 80% comfortably
    clears the hole's ~70%-of-radius reach while staying well clear of that
    seam."""
    light = T.theme.resolved_mode() == "Light"
    disc_color = "#FFFFFF" if light else "#2B2B2B"
    glyph_color = "#2B2B2B" if light else "#FFFFFF"
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(glyph_color))
    inset = rect.width() * 0.1
    painter.drawEllipse(rect.adjusted(inset, inset, -inset, -inset))
    _svg_renderer("info.svg", disc_color).render(painter, rect)
    painter.restore()


def _paint_info_badge_faded(painter, rect, alpha, dpr=1.0):
    """`_paint_info_badge`, fading as one flattened unit instead of each of
    its two layers separately. The hole-punch trick above only reads
    correctly (glyph showing only through the "i"-shaped hole) when the SVG
    disc layer is fully opaque relative to the glyph circle beneath it —
    applying a single `QPainter.setOpacity()` around both draw calls fades
    the disc too, which lets the glyph colour bleed through the *entire*
    disc rather than just the hole (confirmed: the two theme colours
    visibly blend into each other partway through the fade instead of the
    badge just dimming). Composited at full opacity onto an offscreen
    buffer first, then that flattened result is drawn once at `alpha`."""
    w, h = max(1, round(rect.width() * dpr)), max(1, round(rect.height() * dpr))
    buf = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    buf.fill(Qt.transparent)
    buf.setDevicePixelRatio(dpr)
    bp = QPainter(buf)
    _paint_info_badge(bp, QRectF(0, 0, rect.width(), rect.height()))
    bp.end()
    painter.save()
    painter.setOpacity(alpha)
    painter.drawImage(rect.topLeft(), buf)
    painter.restore()


class WaveLayer(QWidget):
    """The Wave Loop visualiser. A child of the owning *tab* (not the
    carousel) so it bleeds past the preview's inner margin to the tab frame's
    edges; transparent to the mouse, so clicks and drops land on the carousel
    beneath it."""

    def __init__(self, carousel, host):
        super().__init__(host)
        self.carousel = carousel
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()
        self._frame = None       # QImage — the current tinted frame
        self._frame_key = None   # (idx, w, h, dpr, theme)
        self._t0 = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        T.theme.changed.connect(self._invalidate)

    def start(self):
        if not self._timer.isActive():
            self._t0 = time.monotonic()
            if _wave()[0] is not None:
                self._timer.start(_WAVE_INTERVAL_MS)
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
            return
        idx = self._index()
        if self._frame_key is None or self._frame_key[0] != idx:
            self.update()

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


class _InfoTooltip(QLabel):
    """The info badge's hover tooltip — dark body, primary border."""

    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        # Without this, the tooltip — a real top-level window — can end up
        # sitting directly under the cursor once shown (worse the bigger the
        # info icon renders, i.e. the expanded preview): the OS then routes
        # the next move to *it* instead of the carousel, which reads as the
        # carousel's mouse having left, fading the whole hover overlay out
        # and hiding the tooltip, which puts the carousel back under the
        # cursor and re-triggers everything — a rapid flicker loop. Same
        # fix WaveLayer already uses for the same class of problem.
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setTextFormat(Qt.PlainText)
        self._restyle()
        T.theme.changed.connect(self._restyle)

    def _restyle(self):
        self.setStyleSheet(
            f"QLabel {{ background: {T.theme.hex('tooltip_bg')}; color: white;"
            f" border: 1px solid {T.theme.hex('primary')}; padding: 8px 10px;"
            f" font-family: Arial; font-size: 13px; }}"
        )


class ThumbnailCarousel(QWidget):
    """Shows one preview frame at a time. See the module docstring."""

    reselect = Signal()
    populated = Signal()
    indexChanged = Signal(int)
    fileDropped = Signal(str)
    expandToggled = Signal(bool)

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.wave = WaveLayer(self, host)

        self._frames = []            # QImages
        self._index = 0
        self._dot_start = 0
        self._dot_anim = None        # (prev_start, prev_index) while the row re-flows
        self._populated = False
        self._strip_video = False
        self._strip_audio = False
        self._audio_only = False
        self._media_info = {}
        self._scaled = {}            # (index, w, h, dpr) -> QPixmap
        self._prev_press_central = False
        self._tooltip = None
        self._expanded = False

        self._arrow_alpha = 0.0
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(_FADE_MS)
        self._fade.valueChanged.connect(self._set_alpha)

        self._slide_t = 1.0
        self._slide_from = None      # (pixmap, rect) of the outgoing frame
        self._slide_dir = 1
        self._slide = QVariantAnimation(self)
        self._slide.setStartValue(0.0)
        self._slide.setEndValue(1.0)
        self._slide.setDuration(_SLIDE_MS)
        self._slide.setEasingCurve(QEasingCurve.OutCubic)
        self._slide.valueChanged.connect(self._set_slide)
        self._slide.finished.connect(self._end_slide)
        T.theme.changed.connect(self.update)

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #
    def clear_preview(self):
        """Drop the current frames immediately, so the previous file's
        preview never lingers on screen while the newly-selected one is
        still probing/decoding on a worker (`_frames` empty short-circuits
        `paintEvent`, same as before anything was ever loaded). Called right
        when the global file selection changes -- see `app.update_global_file`
        -- so a cache-hit re-selection that rebroadcasts synchronously never
        even shows the blank frame; only a genuine decode does."""
        self._frames = []
        self._index = 0
        self._dot_start = 0
        self._dot_anim = None
        self._scaled.clear()
        self._cancel_anim()
        self._arrow_alpha = 0.0
        self._audio_only = False
        self._sync_wave()
        self.update()

    def set_frames(self, frames):
        """New frame list (QImages). Resets to the first frame; the first
        non-empty set fires `populated` so the tab can reveal the carousel."""
        self._frames = [f for f in (frames or []) if f is not None and not f.isNull()]
        self._index = 0
        self._dot_start = 0
        self._dot_anim = None
        self._scaled.clear()
        self._cancel_anim()
        self._arrow_alpha = 0.0
        if self._frames and not self._populated:
            self._populated = True
            self.populated.emit()
        self._sync_wave()
        self.update()

    def set_strip_state(self, strip_video, strip_audio):
        if (bool(strip_video), bool(strip_audio)) == (self._strip_video, self._strip_audio):
            return
        self._strip_video, self._strip_audio = bool(strip_video), bool(strip_audio)
        self._cancel_anim()
        self._arrow_alpha = 0.0
        self._sync_wave()
        self.update()

    def set_audio_only(self, audio_only):
        if bool(audio_only) == self._audio_only:
            return
        self._audio_only = bool(audio_only)
        self._cancel_anim()
        self._arrow_alpha = 0.0
        if self._audio_only:
            self._frames = []
            self._index = 0
            if not self._populated:
                self._populated = True
                self.populated.emit()
        self._sync_wave()
        self.update()

    def set_media_info(self, info):
        self._media_info = info or {}
        if self._tooltip is not None and self._tooltip.isVisible():
            self._show_tooltip()
        self.update()
        self.wave.update()

    def current_index(self):
        return self._index

    def step(self, delta):
        """The Left/Right keybind: step without lighting the chevrons."""
        if len(self._frames) > 1 and not self._wave_mode():
            self._step(delta, show_arrows=False)

    def sync_index(self, index):
        """Jump with no slide (mirroring the other tab). Never re-emits."""
        if not self._frames or index == self._index or not 0 <= index < len(self._frames):
            return
        self._cancel_anim()
        self._index = index
        self._dot_start = self._centered_dot_start(index)
        self._arrow_alpha = 0.0
        self.update()

    # ------------------------------------------------------------------ #
    #  Wave layer placement
    # ------------------------------------------------------------------ #
    def _wave_mode(self):
        return self._strip_video or self._audio_only

    def _sync_wave(self):
        if self._wave_mode() and self.isVisible():
            # The Wave Loop layer positions itself relative to the tab
            # hosting this carousel (`_place_wave`'s `mapTo(host, ...)`),
            # which is meaningless while detached into the expanded overlay
            # -- drop back to the embedded view first.
            self.force_collapse()
            self._place_wave()
            self.wave.start()
        else:
            self.wave.stop()

    def _place_wave(self):
        host = self.wave.parentWidget()
        top = self.mapTo(host, self.rect().topLeft())
        self.wave.setGeometry(0, top.y(), host.width(), self.height())

    def showEvent(self, e):
        self._sync_wave()

    def hideEvent(self, e):
        self.wave.stop()
        self._hide_tooltip()

    def resizeEvent(self, e):
        self._scaled.clear()
        self._cancel_anim()
        if self._wave_mode():
            self._place_wave()

    def moveEvent(self, e):
        if self._wave_mode():
            self._place_wave()

    # ------------------------------------------------------------------ #
    #  Geometry
    # ------------------------------------------------------------------ #
    def _frame_rect(self, index=None):
        """The fitted, centred rect frame `index` is drawn in."""
        frames = self._frames
        if not frames:
            return QRectF()
        image = frames[self._index if index is None else index]
        iw, ih = image.width(), image.height()
        if iw <= 0 or ih <= 0 or self.width() <= 8 or self.height() <= 8:
            return QRectF()
        scale = min((self.width() - 8) / iw, (self.height() - 8) / ih)
        w, h = max(1.0, iw * scale), max(1.0, ih * scale)
        return QRectF(round((self.width() - w) / 2), round((self.height() - h) / 2), round(w), round(h))

    def _pixmap(self, index, rect):
        dpr = self.devicePixelRatioF() or 1.0
        key = (index, int(rect.width()), int(rect.height()), dpr)
        pix = self._scaled.get(key)
        if pix is None:
            image = self._frames[index].scaled(
                round(rect.width() * dpr), round(rect.height() * dpr),
                Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            pix = QPixmap.fromImage(image)
            pix.setDevicePixelRatio(dpr)
            self._scaled[key] = pix
        return pix

    def _icon_scale(self):
        """The mute badge's own scale — half size once expanded, mirroring
        the expand icon's baseline. Moot in practice: the mute badge is
        never painted while expanded at all (see `paint_badges`), kept here
        only so the size stays sane if that ever changes."""
        return 0.5 if self._expanded else 1.0

    def _info_badge_scale(self):
        """The info badge, unlike the mute badge, stays visible while
        expanded. It's already proportionally bigger in absolute terms
        purely because the expanded frame itself is so much bigger — an
        extra 2x multiplier on top of that read as comically huge, so this
        stays at the same proportional size as the embedded preview's."""
        return 1.0

    def _expand_icon_scale(self):
        """The expand/shrink icon's own multiplier on top of the plain
        percentage-of-frame formula — one constant for both the embedded
        expand icon and the expanded shrink icon, like the chevrons'
        single 0.75, rather than two different multipliers fighting the
        frame-size difference between them. 1.125 is the shrink icon's own
        settled size; giving the embedded expand icon anything else made
        the two feel inconsistent rather than like the same button."""
        return 1.125

    def _dot_scale(self):
        """The dot row grows instead of shrinking — it's the primary
        at-a-glance cue for which frame you're on, and needs to stay
        legible at a much bigger size rather than shrinking with everything
        else. 1.5x embedded once expanded (25% smaller than a plain 2x,
        which crowded the frame)."""
        return 1.5 if self._expanded else 1.0

    def _disc_centers(self, w, h):
        """`(left_center, right_center, radius)` in frame-local pixels — None
        for a chevron that isn't drawn. Shared by drawing and hit-testing.
        Chevrons are 75% their old proportional size everywhere — both the
        small embedded preview and the expanded one — unlike badges/the
        expand icon, which only shrink once expanded."""
        if w <= 0 or h <= 0:
            return None, None, 0.0
        disc_r = max(14.0, min(w, h) * 0.12)
        disc_r = min(disc_r, w * 0.16, h * 0.42)
        disc_r *= 0.75
        margin = max(4.0, disc_r * 0.14)
        cy = h / 2
        last = len(self._frames) - 1
        left = (margin + disc_r, cy) if self._index > 0 else None
        right = (w - margin - disc_r, cy) if self._index < last else None
        return left, right, disc_r

    def _dot_geometry(self, w, h, dot_start):
        scale = self._dot_scale()
        n = len(self._frames)
        cluster_lo, cluster_hi = dot_start, dot_start + _DOT_CLUSTER - 1
        lo = max(0, cluster_lo - _DOT_LOOK)
        hi = min(n - 1, cluster_hi + _DOT_LOOK)
        cluster_mid = dot_start + (_DOT_CLUSTER - 1) / 2
        geo = {}
        for f in range(lo, hi + 1):
            dist = cluster_lo - f if f < cluster_lo else f - cluster_hi if f > cluster_hi else 0
            r = (_DOT_R_LARGE if dist == 0 else _DOT_R_MED if dist == 1 else _DOT_R_SMALL) * scale
            geo[f] = (w / 2 + (f - cluster_mid) * _DOT_GAP * scale, r)
        return geo, h - 18 * scale

    def _resolve_dot_start(self, new_index, delta, prev_index, prev_start):
        n = len(self._frames)
        hi_start = max(0, n - _DOT_CLUSTER)
        cluster = prev_index - prev_start
        if abs(delta) == 1:
            if delta > 0:
                start = prev_start + (1 if cluster >= _DOT_CLUSTER - 1 else 0)
            else:
                start = prev_start - (1 if cluster <= 0 else 0)
        else:
            start = new_index - (_DOT_CLUSTER - 1) if delta > 0 else new_index
        lo = max(0, new_index - (_DOT_CLUSTER - 1))
        return max(lo, min(start, hi_start, new_index))

    def _centered_dot_start(self, index):
        n = len(self._frames)
        lo = max(0, index - (_DOT_CLUSTER - 1))
        hi = min(max(0, n - _DOT_CLUSTER), index)
        return max(lo, min(index - (_DOT_CLUSTER - 1) // 2, hi))

    # ------------------------------------------------------------------ #
    #  Painting
    # ------------------------------------------------------------------ #
    def paintEvent(self, _event):
        if self._wave_mode() or not self._frames:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = self._frame_rect()
        if rect.isEmpty():
            return
        clip = QPainterPath()
        clip.addRect(rect)

        if self._slide_from is not None and self._slide_t < 1.0:
            from_pix, from_rect = self._slide_from
            offset = rect.width() * self._slide_t * self._slide_dir
            p.save()
            p.setClipPath(clip)
            p.drawPixmap(from_rect.translated(-offset, 0), from_pix, QRectF(from_pix.rect()))
            incoming = rect.translated(rect.width() * self._slide_dir - offset, 0)
            p.drawPixmap(incoming, self._pixmap(self._index, rect), QRectF(0, 0, rect.width() * self.devicePixelRatioF(), rect.height() * self.devicePixelRatioF()))
            p.restore()
        else:
            p.drawPixmap(rect.toRect(), self._pixmap(self._index, rect))

        if self._arrow_alpha > 0.01 and len(self._frames) > 1:
            p.save()
            p.translate(rect.topLeft())
            p.setOpacity(self._arrow_alpha)
            self._paint_dots(p, rect.width(), rect.height())
            self._paint_chevrons(p, rect.width(), rect.height())
            p.restore()

        # Not gated to len(frames) > 1 like the chevrons/dots above — even a
        # single-frame preview can still be expanded.
        if self._arrow_alpha > 0.01:
            self._paint_expand_icon(p, rect)

        self.paint_badges(p, rect)

    def _paint_dots(self, p, w, h):
        geo_b, cy = self._dot_geometry(w, h, self._dot_start)
        p.setPen(Qt.NoPen)
        t = self._slide_t
        if self._dot_anim is None or t >= 1.0:
            for f, (cx, r) in geo_b.items():
                p.setBrush(_DOT_ON if f == self._index else _DOT_OFF)
                p.drawEllipse(QPointF(cx, cy), r, r)
            return
        prev_start, prev_index = self._dot_anim
        geo_a, _ = self._dot_geometry(w, h, prev_start)
        for f in set(geo_a) | set(geo_b):
            a, b = geo_a.get(f), geo_b.get(f)
            if a and b:
                cx, r = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            elif b:
                cx, r = b[0], b[1] * t
            else:
                cx, r = a[0], a[1] * (1 - t)
            if f == self._index == prev_index:
                fill = _DOT_ON
            elif f == self._index:
                fill = T.lerp(_DOT_OFF, _DOT_ON, t)
            elif f == prev_index:
                fill = T.lerp(_DOT_ON, _DOT_OFF, t)
            else:
                fill = _DOT_OFF
            if r > 0.05:
                p.setBrush(fill)
                p.drawEllipse(QPointF(cx, cy), r, r)

    def _paint_chevrons(self, p, w, h):
        left, right, disc_r = self._disc_centers(w, h)
        primary = T.theme.color("primary")
        disc = T.with_alpha(primary, 230 / 255)
        arrow = T.theme.color("primary_text")
        for center, direction in ((left, -1), (right, 1)):
            if center is None:
                continue
            cx, cy = center
            p.setPen(Qt.NoPen)
            p.setBrush(disc)
            p.drawEllipse(QPointF(cx, cy), disc_r, disc_r)
            half_w, half_h = disc_r * 0.38, disc_r * 0.45
            ox = direction * half_w * 0.13   # optical-centre nudge toward the tip
            pen = QPen(arrow, max(2.0, disc_r * 0.135))
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPolyline([
                QPointF(cx + ox - direction * half_w, cy - half_h),
                QPointF(cx + ox + direction * half_w, cy),
                QPointF(cx + ox - direction * half_w, cy + half_h),
            ])

    def _badge_sizes(self, rect):
        short = min(rect.width(), rect.height())
        mute_size = max(18, round(short * 0.14 * self._icon_scale()))
        info_size = max(18, round(short * 0.09 * self._info_badge_scale()))
        return mute_size, info_size

    def _info_badge_rect(self, rect):
        _, info_size = self._badge_sizes(rect)
        margin = max(4, round(info_size * 0.35))
        return QRectF(rect.left() + margin, rect.bottom() - info_size - margin, info_size, info_size)

    def _expand_icon_rect(self, rect):
        short = min(rect.width(), rect.height())
        size = max(20, round(short * 0.11 * self._expand_icon_scale()))
        margin = max(4, round(size * 0.35))
        return QRectF(rect.right() - size - margin, rect.bottom() - size - margin, size, size)

    def _paint_expand_icon(self, p, rect):
        """Bottom-right, hover-only like the chevrons — expand.svg while
        embedded, shrink.svg once expanded, on the same primary disc the
        chevrons use."""
        icon_rect = self._expand_icon_rect(rect)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self._arrow_alpha)
        p.setPen(Qt.NoPen)
        p.setBrush(T.with_alpha(T.theme.color("primary"), 230 / 255))
        p.drawEllipse(icon_rect)
        name = "shrink.svg" if self._expanded else "expand.svg"
        inset = icon_rect.width() * 0.22
        _svg_renderer(name, T.theme.hex("primary_text")).render(p, icon_rect.adjusted(inset, inset, -inset, -inset))
        p.restore()

    def paint_badges(self, p, rect):
        """Mute badge (top-left, while audio is stripped) and the info badge
        (bottom-left, once a probe has landed) over `rect`. Shared with the
        WaveLayer so both preview modes carry the same badges. The mute
        badge is a status indicator and normally always stays on — except
        in the expanded preview, where it's left off entirely rather than
        competing with the big picture (the strip state is already visible
        from the embedded preview it was expanded from). The info badge is
        interactive chrome like the chevrons — unlike the small embedded
        preview (always on, out of the way in a corner), an expanded
        preview fades it in with the rest of the hover UI instead of
        leaving it permanently competing with the big picture."""
        p.setRenderHint(QPainter.Antialiasing)
        mute_size, _ = self._badge_sizes(rect)
        if self._strip_audio and not self._expanded:
            margin = max(4, round(mute_size * 0.28))
            _svg_renderer("audio-mute.svg").render(
                p, QRectF(rect.left() + margin, rect.top() + margin, mute_size, mute_size))
        if self._media_info:
            if self._expanded:
                _paint_info_badge_faded(p, self._info_badge_rect(rect), self._arrow_alpha,
                                        self.devicePixelRatioF() or 1.0)
            else:
                _paint_info_badge(p, self._info_badge_rect(rect))

    # ------------------------------------------------------------------ #
    #  Animation
    # ------------------------------------------------------------------ #
    def _set_alpha(self, value):
        self._arrow_alpha = value
        self.update()

    def _fade_to(self, target):
        self._fade.stop()
        self._fade.setStartValue(self._arrow_alpha)
        self._fade.setEndValue(float(target))
        self._fade.start()

    def _set_slide(self, t):
        self._slide_t = t
        self.update()

    def _end_slide(self):
        self._slide_t = 1.0
        self._slide_from = None
        self._dot_anim = None
        self.update()

    def _cancel_anim(self):
        self._fade.stop()
        if self._slide.state() == QVariantAnimation.Running:
            self._slide.stop()
        self._end_slide()

    def _step(self, delta, show_arrows=True):
        if not self._frames or self._wave_mode():
            return
        new_index = max(0, min(len(self._frames) - 1, self._index + delta))
        if new_index == self._index:
            return
        direction = 1 if new_index > self._index else -1
        old_rect = self._frame_rect()
        # The outgoing picture is whatever's on screen *right now* — mid-slide
        # included, so a spam-click chains on from the partial position.
        old_pix = self._pixmap(self._index, old_rect) if not old_rect.isEmpty() else None
        prev_index, prev_start = self._index, self._dot_start
        self._slide.stop()
        self._index = new_index
        self.indexChanged.emit(new_index)
        self._dot_start = self._resolve_dot_start(new_index, delta, prev_index, prev_start)
        if show_arrows:
            self._fade.stop()
            self._arrow_alpha = 1.0
        new_rect = self._frame_rect()
        if old_pix is None or old_rect.size() != new_rect.size():
            self._end_slide()
            return
        self._slide_from = (old_pix, old_rect)
        self._slide_dir = direction
        self._dot_anim = (prev_start, prev_index)
        self._slide_t = 0.0
        self._slide.start()

    # ------------------------------------------------------------------ #
    #  Input
    # ------------------------------------------------------------------ #
    def enterEvent(self, e):
        # >= 1 frame, not > 1 — the expand icon (unlike the chevrons/dots)
        # is still worth showing for a single-frame preview.
        if self._frames and not self._wave_mode():
            self._fade_to(1.0)

    def leaveEvent(self, e):
        self._fade_to(0.0)
        self._hide_tooltip()

    def _local_frame_xy(self, pos):
        rect = self._frame_rect()
        if rect.isEmpty():
            return None, rect
        return (pos.x() - rect.left(), pos.y() - rect.top()), rect

    def _hit_disc(self, x, y, w, h):
        left, right, radius = self._disc_centers(w, h)
        for name, center in (("left", left), ("right", right)):
            if center is not None and abs(x - center[0]) <= radius and abs(y - center[1]) <= radius:
                return name
        return None

    def _in_chevron_band(self, x, w, h):
        """Excludes a side from the "central" double-click-to-reselect area
        only while that side's chevron is actually drawn there — on the
        first frame (no left chevron) or the last (no right chevron), that
        side is just dead space and should double-click like anywhere else."""
        left, right, radius = self._disc_centers(w, h)
        reach = radius * 2.0 + 16.0
        return (left is not None and x < reach) or (right is not None and x > w - reach)

    def _press(self, pos, repeat):
        if self._wave_mode():
            if repeat:
                self.reselect.emit()
            return
        central = False
        if len(self._frames) > 1:
            xy, rect = self._local_frame_xy(pos)
            if xy is not None:
                hit = self._hit_disc(xy[0], xy[1], rect.width(), rect.height())
                if hit:
                    self._step(-1 if hit == "left" else 1)
                    self._prev_press_central = False
                    return
                central = not self._in_chevron_band(xy[0], rect.width(), rect.height())
        elif self._frames:
            central = True
        if central and repeat and self._prev_press_central and not self._expanded:
            # Double-click-to-import is a small/embedded-preview affordance
            # only — while looking at a big expanded picture, an accidental
            # double-click shouldn't pop a file browser open over it.
            self.reselect.emit()
        self._prev_press_central = central

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            if self._over_expand_icon(e.position()):
                self._toggle_expand()
                return
            if self._expanded and not self._within_frame(e.position()):
                # The expanded carousel widget fills nearly the whole
                # overlay, but the actual picture inside it is letterboxed
                # — clicking the bars above/below (or beside) it should
                # dismiss the expanded view exactly like clicking the thin
                # scrim border around the carousel already does, not be
                # swallowed as an on-picture click.
                self.force_collapse()
                return
            self._press(e.position(), repeat=False)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            if self._over_expand_icon(e.position()):
                return
            if self._expanded and not self._within_frame(e.position()):
                return
            self._press(e.position(), repeat=True)

    def mouseMoveEvent(self, e):
        if self._over_info_badge(e.position()):
            self._show_tooltip()
        else:
            self._hide_tooltip()
        self.setCursor(self._hover_cursor(e.position()))

    def _over_chevron(self, pos):
        if self._wave_mode() or len(self._frames) <= 1:
            return False
        xy, rect = self._local_frame_xy(pos)
        if xy is None:
            return False
        return self._hit_disc(xy[0], xy[1], rect.width(), rect.height()) is not None

    def _within_frame(self, pos):
        """Whether `pos` lands on the actual letterboxed picture, not just
        somewhere in the carousel widget's own (much larger, once
        expanded) bounds. The expand icon's own hit-test already stays
        within this by construction (it's inset from the frame rect's own
        corner), so callers don't need to check it separately."""
        rect = self._frame_rect()
        return not rect.isEmpty() and rect.contains(pos)

    def _hover_cursor(self, pos):
        """The small embedded preview keeps a pointing-hand cursor
        everywhere — a click almost anywhere on it does something (step a
        chevron, double-click to reselect). The expanded preview is mostly
        just a big picture to look at, so it stays a plain arrow except
        over the info icon, the chevrons, or the shrink button — the only
        spots that actually do anything there — and never lights up at all
        outside the picture itself (the letterbox bars around it), since a
        click there dismisses the expanded view rather than acting on
        anything drawn under the cursor."""
        if not self._expanded:
            return Qt.PointingHandCursor
        if not self._within_frame(pos):
            return Qt.ArrowCursor
        if self._over_info_badge(pos) or self._over_expand_icon(pos) or self._over_chevron(pos):
            return Qt.PointingHandCursor
        return Qt.ArrowCursor

    def dragEnterEvent(self, e):
        if local_paths(e.mimeData()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = local_paths(e.mimeData())
        if paths:
            self.fileDropped.emit(paths[0])

    # ------------------------------------------------------------------ #
    #  Info tooltip
    # ------------------------------------------------------------------ #
    def _over_info_badge(self, pos):
        if not self._media_info:
            return False
        if self._wave_mode():
            wave_pos = self.mapTo(self.wave, pos.toPoint())
            badge = self._info_badge_rect(QRectF(self.wave.rect()))
            point = QPointF(wave_pos)
        else:
            rect = self._frame_rect()
            if rect.isEmpty():
                return False
            badge = self._info_badge_rect(rect)
            point = pos
        c = badge.center()
        radius = badge.width() / 2 * 1.3
        return (point.x() - c.x()) ** 2 + (point.y() - c.y()) ** 2 <= radius ** 2

    def _over_expand_icon(self, pos):
        """Not offered in wave mode — nothing there to usefully expand, same
        scope as the chevrons/dots."""
        if self._wave_mode() or not self._frames:
            return False
        rect = self._frame_rect()
        if rect.isEmpty():
            return False
        icon = self._expand_icon_rect(rect)
        c = icon.center()
        radius = icon.width() / 2 * 1.3
        return (pos.x() - c.x()) ** 2 + (pos.y() - c.y()) ** 2 <= radius ** 2

    def _toggle_expand(self):
        self._expanded = not self._expanded
        self.update()
        self.expandToggled.emit(self._expanded)
        # The listener reparents/resizes the carousel synchronously inside
        # that emit, so the icon's on-screen position just moved out from
        # under a mouse that hasn't — re-derive the cursor from the current
        # global position rather than assuming it's still over anything.
        self.setCursor(self._hover_cursor(self.mapFromGlobal(QCursor.pos())))

    def force_collapse(self):
        """Shrink back from the expanded overlay if currently expanded —
        used when the file being previewed is about to change out from
        under it (a rejected import) rather than left stranded showing
        something that's disappearing."""
        if self._expanded:
            self._toggle_expand()

    def _show_tooltip(self):
        if self._tooltip is None:
            self._tooltip = _InfoTooltip()
        self._tooltip.setText(self._info_text())
        self._tooltip.adjustSize()
        origin = self.mapToGlobal(self.rect().bottomLeft())
        self._tooltip.move(origin.x() + 8, origin.y() - self._tooltip.height() - 34)
        self._tooltip.show()

    def _hide_tooltip(self):
        if self._tooltip is not None:
            self._tooltip.hide()

    @staticmethod
    def _mastering_text(info):
        max_nits = info.get("mastering_max_nits")
        # A literal 0 MaxCLL/MaxFALL reads as absent — the SEI is present but
        # unset, not a real measurement (no video has zero peak brightness).
        max_cll = info.get("max_cll") or None
        max_fall = info.get("max_fall") or None
        if max_nits is None and max_cll is None and max_fall is None:
            return "Mastering: not tagged — tonemap uses scene analysis"
        bits = [f"{max_nits:g} nits" if max_nits is not None else "not tagged"]
        if max_cll is not None or max_fall is not None:
            cll = f"{max_cll:g}" if max_cll is not None else "?"
            fall = f"{max_fall:g}" if max_fall is not None else "?"
            bits.append(f"MaxCLL {cll}/{fall}")
        return "Mastering: " + " · ".join(bits)

    def _info_text(self):
        info = self._media_info or {}
        lines = []
        if info.get("container"):
            lines.append(f"Container: {info['container']}")
        if info.get("has_video") is False:
            lines.append("Video: none")
        elif info.get("video"):
            bits = [info["video"]]
            if info.get("video_profile"):
                bits.append(info["video_profile"])
            if info.get("video_level"):
                bits.append(f"L{info['video_level']}")
            if info.get("width") and info.get("height"):
                bits.append(f"{info['width']}x{info['height']}")
            if info.get("hdr"):
                bits.append("HDR")
            lines.append("Video: " + " · ".join(bits))
            if info.get("hdr"):
                lines.append(self._mastering_text(info))
        if info.get("has_audio") is False:
            lines.append("Audio: none")
        elif info.get("audio"):
            bits = [info["audio"]]
            for key in ("audio_channels", "audio_sample_rate", "audio_bitrate"):
                if info.get(key):
                    bits.append(info[key])
            streams = info.get("audio_streams") or []
            if len(streams) > 1:
                bits.append(f"{len(streams)} tracks")
            lines.append("Audio: " + " · ".join(bits))
        if info.get("duration"):
            total = int(info["duration"])
            hours, rest = divmod(total, 3600)
            minutes, seconds = divmod(rest, 60)
            lines.append(f"Duration: {hours:02d}:{minutes:02d}:{seconds:02d}")
        if info.get("file_size"):
            size = float(info["file_size"])
            for unit in ("B", "KB", "MB", "GB"):
                if size < 1024 or unit == "GB":
                    lines.append(f"Size: {size:.0f} {unit}" if unit == "B" else f"Size: {size:.1f} {unit}")
                    break
                size /= 1024
        return "\n".join(lines) if lines else "Gathering file info…"

    def deleteLater(self):
        self._hide_tooltip()
        super().deleteLater()


class _ExpandedPreviewOverlay(QWidget):
    """A translucent scrim that temporarily hosts a tab's `ThumbnailCarousel`
    at a bigger, centred size while its expand icon is on — the same widget
    instance is reparented in and back out, so every one of its own
    behaviors (chevrons, dots, badges, drag/drop, the shrink icon, arrow-key
    stepping) keeps working unchanged; nothing here duplicates any of that.

    Sized to the *main window's own footprint*, not the monitor — filling
    the whole screen as a separate top-level OS window was tried first and
    reverted: becoming its own window stole window activation from the main
    window, which is why the app-level Left/Right keybind (gated on
    `window.isActiveWindow()`) silently stopped working while expanded.
    Staying a plain child widget of the main window sidesteps that
    entirely, and doubles as the "cover the app" dimming scrim behind the
    carousel for free — it already sits above the sidebar and tab content
    in z-order and blocks clicks from reaching them.

    The carousel fills that whole area (minus `_MARGIN`) — a "carousel at
    half size, centred" cut was tried and reverted: it read as the preview
    having shrunk, not expanded. The margin alone still leaves a thin scrim
    border to click for `mousePressEvent`'s click-outside-to-dismiss.
    Positioned with plain `setGeometry()`, not a layout, since sizing needs
    to be recomputed from `_MARGIN` on demand rather than baked into a
    layout margin at construction time.

    One instance per `MediaTab` (Muxing and Encoding each have their own,
    since expanding one's preview has nothing to do with the other's)."""

    _SCRIM = QColor(0, 0, 0, 175)
    _MARGIN = 20

    def __init__(self, main_window):
        super().__init__(main_window)
        self._carousel = None
        self.hide()

    def paintEvent(self, _event):
        QPainter(self).fillRect(self.rect(), self._SCRIM)

    def resizeEvent(self, _event):
        self._layout_carousel()

    def _layout_carousel(self):
        if self._carousel is None:
            return
        avail = self.rect().adjusted(self._MARGIN, self._MARGIN, -self._MARGIN, -self._MARGIN)
        self._carousel.setGeometry(avail)

    def show_with(self, carousel):
        self._carousel = carousel
        carousel.setParent(self)
        self.setGeometry(self.parentWidget().rect())
        self._layout_carousel()
        self.show()
        # QWidget.setParent() hides the widget as a side effect of
        # reparenting, regardless of the new parent's own visibility —
        # show() on the overlay alone leaves the carousel itself invisible
        # (a blank overlay) without this.
        carousel.show()
        self.raise_()

    def release(self):
        """Give the carousel back — the caller re-parents it into its
        normal home immediately after calling this."""
        self._carousel = None
        self.hide()

    def mousePressEvent(self, e):
        """Clicking the scrim (anywhere outside the carousel's own bounds,
        the only other thing that can receive a click here) shrinks back —
        a click actually on the carousel is delivered to it directly and
        never reaches this handler."""
        if e.button() == Qt.LeftButton and self._carousel is not None:
            self._carousel.force_collapse()
