# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""The preview carousel: up to ten frames of the selected file with hover chevrons, a sliding
transition, a dot row and the info / mute badges. The Wave Loop (`wave`), the badge tooltip
(`info_badge`) and the expanded view (`preview_overlay`) live beside it.

Dot row: the centre three dots are large and fixed; beyond them two per side taper, only for
frames that exist. The highlight rides toward the edge it's heading for and the row scrolls
only once it's there."""
from PySide6.QtCore import QEasingCurve, QPointF, QRect, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from core.probe import fps_text
from ui import theme as T
from ui.scale import fpx, px
from ui.widgets.info_badge import _InfoTooltip, _paint_info_badge, _paint_info_badge_faded
from ui.widgets.panels import local_paths
from ui.widgets.svg import svg_renderer
from ui.widgets.wave import WaveLayer

_DOT_R_LARGE = 4.0
_DOT_R_MED = 3.0
_DOT_R_SMALL = 2.0
_DOT_GAP = 16.0
_DOT_CLUSTER = 3
_DOT_LOOK = 2
_DOT_ON = QColor(255, 255, 255, 235)
_DOT_OFF = QColor(255, 255, 255, 90)
_FADE_MS = 100


# Size the chevrons and expand icon grow to under the pointer.
_HOVER_GROW = 1.2
_HOVER_MS = 120
_TIP_GRACE_MS = 50      # how long the info tip outlasts the pointer leaving the badge
_SLIDE_MS = 115
_SCALED_CACHE = 4       # scaled frames kept: the slide pair plus a step back and forth


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
        # Mouse-driven hides wait a moment, so the pointer can cross from the badge to the tip.
        self._tooltip_grace = QTimer(self)
        self._tooltip_grace.setSingleShot(True)
        self._tooltip_grace.setInterval(_TIP_GRACE_MS)
        self._tooltip_grace.timeout.connect(self._grace_expired)
        self._expanded = False

        self._arrow_alpha = 0.0
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(_FADE_MS)
        self._fade.valueChanged.connect(self._set_alpha)

        # How far each control is into its hover growth, 0 (normal) to 1 (full size).
        self._hover = {"left": 0.0, "right": 0.0, "expand": 0.0}
        self._hover_anims = {}
        for name in self._hover:
            anim = QVariantAnimation(self)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.valueChanged.connect(lambda value, n=name: self._set_hover(n, value))
            self._hover_anims[name] = anim

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
        """Drop the frames at once, so the previous file's preview never lingers while a new one
        decodes."""
        self._frames = []
        self._index = 0
        self._dot_start = 0
        self._dot_anim = None
        self._scaled.clear()
        self._cancel_anim()
        self._arrow_alpha = 0.0
        self._audio_only = False
        self._reset_hover()
        self._sync_wave()
        self.update()

    def forget_populated(self):
        """Back to "nothing imported": the next frames (or audio-only file) fire `populated`
        again, so the carousel is revealed."""
        self._populated = False

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
        self._sync_hover()
        self._sync_wave()
        self.update()

    def replace_frames(self, frames):
        """Swap the pictures of the frames on show (the same count; else `set_frames`): the
        position, chevrons, hover and a slide in progress carry on untouched."""
        frames = [f for f in (frames or []) if f is not None and not f.isNull()]
        if not self._frames or len(frames) != len(self._frames):
            self.set_frames(frames)
            return
        changed = {i for i, (old, new) in enumerate(zip(self._frames, frames)) if old is not new}
        if not changed:
            return
        self._frames = frames
        self._scaled = {key: pix for key, pix in self._scaled.items() if key[0] not in changed}
        self.update()

    def set_strip_state(self, strip_video, strip_audio):
        if (bool(strip_video), bool(strip_audio)) == (self._strip_video, self._strip_audio):
            return
        self._strip_video, self._strip_audio = bool(strip_video), bool(strip_audio)
        self._refresh_open_tooltip()      # what it says depends on the mode
        self._cancel_anim()
        self._arrow_alpha = 0.0
        self._sync_wave()
        self.update()

    def set_audio_only(self, audio_only):
        if bool(audio_only) == self._audio_only:
            return
        self._audio_only = bool(audio_only)
        self._refresh_open_tooltip()
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
            # The wave layer is placed relative to the tab: collapse the expanded view first.
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
        self._reset_hover()

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
        inset = px(8)
        if iw <= 0 or ih <= 0 or self.width() <= inset or self.height() <= inset:
            return QRectF()
        k = min((self.width() - inset) / iw, (self.height() - inset) / ih)
        w, h = max(1.0, iw * k), max(1.0, ih * k)
        return QRectF(round((self.width() - w) / 2), round((self.height() - h) / 2), round(w), round(h))

    def _pixmap(self, index, rect):
        dpr = self.devicePixelRatioF() or 1.0
        key = (index, int(rect.width()), int(rect.height()), dpr)
        pix = self._scaled.pop(key, None)
        if pix is None:
            image = self._frames[index].scaled(
                round(rect.width() * dpr), round(rect.height() * dpr),
                Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            pix = QPixmap.fromImage(image)
            pix.setDevicePixelRatio(dpr)
        self._scaled[key] = pix             # most recently used last
        # Only the last few: an expanded frame is ~13MB, and rescaling one costs a millisecond or two.
        while len(self._scaled) > _SCALED_CACHE:
            del self._scaled[next(iter(self._scaled))]
        return pix

    def _icon_scale(self):
        """The mute badge's scale: half once expanded (it isn't drawn then anyway)."""
        return 0.5 if self._expanded else 1.0

    def _info_badge_scale(self):
        """The info badge keeps its proportional size when expanded (2x on top read as huge)."""
        return 1.0

    def _expand_icon_scale(self):
        """The expand/shrink icon's multiplier, one value for both so they read as one button."""
        return 1.125

    def _dot_scale(self):
        """The dot row grows 1.5x when expanded, to stay legible as the at-a-glance position."""
        return 1.5 if self._expanded else 1.0

    def _disc_centers(self, w, h):
        """`(left_center, right_center, radius)` in frame-local pixels, None for a chevron that
        isn't drawn. Shared by drawing and hit-testing."""
        if w <= 0 or h <= 0:
            return None, None, 0.0
        disc_r = max(fpx(14.0), min(w, h) * 0.12)
        disc_r = min(disc_r, w * 0.16, h * 0.42)
        disc_r *= 0.75
        margin = max(fpx(4.0), disc_r * 0.14)
        cy = h / 2
        last = len(self._frames) - 1
        left = (margin + disc_r, cy) if self._index > 0 else None
        right = (w - margin - disc_r, cy) if self._index < last else None
        return left, right, disc_r

    def _dot_geometry(self, w, h, dot_start):
        k = self._dot_scale()
        n = len(self._frames)
        cluster_lo, cluster_hi = dot_start, dot_start + _DOT_CLUSTER - 1
        lo = max(0, cluster_lo - _DOT_LOOK)
        hi = min(n - 1, cluster_hi + _DOT_LOOK)
        cluster_mid = dot_start + (_DOT_CLUSTER - 1) / 2
        geo = {}
        for f in range(lo, hi + 1):
            dist = cluster_lo - f if f < cluster_lo else f - cluster_hi if f > cluster_hi else 0
            r = fpx(_DOT_R_LARGE if dist == 0 else _DOT_R_MED if dist == 1 else _DOT_R_SMALL) * k
            geo[f] = (w / 2 + (f - cluster_mid) * fpx(_DOT_GAP) * k, r)
        return geo, h - fpx(18) * k

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

        # Even a single-frame preview can be expanded.
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
        left, right, base_r = self._disc_centers(w, h)
        secondary = T.theme.color("secondary")
        disc = T.with_alpha(secondary, 230 / 255)
        arrow = T.theme.color("secondary_text")
        for name, center, direction in (("left", left, -1), ("right", right, 1)):
            if center is None:
                continue
            disc_r = base_r * self._hover_scale(name)
            # Grows about its centre but stays inside the picture on a large preview.
            cx, cy = min(max(center[0], disc_r), w - disc_r), center[1]
            p.setPen(Qt.NoPen)
            p.setBrush(disc)
            p.drawEllipse(QPointF(cx, cy), disc_r, disc_r)
            half_w, half_h = disc_r * 0.38, disc_r * 0.45
            ox = direction * half_w * 0.13   # optical-centre nudge toward the tip
            pen = QPen(arrow, max(fpx(2.0), disc_r * 0.135))
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
        mute_size = max(px(18), round(short * 0.14 * self._icon_scale()))
        info_size = max(px(18), round(short * 0.09 * self._info_badge_scale()))
        return mute_size, info_size

    def _info_badge_rect(self, rect):
        _, info_size = self._badge_sizes(rect)
        margin = max(px(4), round(info_size * 0.35))
        return QRectF(rect.left() + margin, rect.bottom() - info_size - margin, info_size, info_size)

    def _expand_icon_rect(self, rect):
        short = min(rect.width(), rect.height())
        size = max(px(20), round(short * 0.11 * self._expand_icon_scale()))
        margin = max(px(4), round(size * 0.35))
        return QRectF(rect.right() - size - margin, rect.bottom() - size - margin, size, size)

    def _paint_expand_icon(self, p, rect):
        """Bottom-right, on hover like the chevrons: expand.svg embedded, shrink.svg expanded."""
        icon_rect = self._expand_icon_rect(rect)
        grown = icon_rect.width() * self._hover_scale("expand")
        icon_rect = QRectF(icon_rect.center().x() - grown / 2, icon_rect.center().y() - grown / 2, grown, grown)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self._arrow_alpha)
        p.setPen(Qt.NoPen)
        p.setBrush(T.with_alpha(T.theme.color("secondary"), 230 / 255))
        p.drawEllipse(icon_rect)
        name = "shrink.svg" if self._expanded else "expand.svg"
        inset = icon_rect.width() * 0.22
        svg_renderer(name, T.theme.hex("secondary_text")).render(p, icon_rect.adjusted(inset, inset, -inset, -inset))
        p.restore()

    def paint_badges(self, p, rect):
        """The mute badge (top-left, audio stripped; not in the expanded view) and the info
        badge (bottom-left, once probed; fades in with the hover UI when expanded) over `rect`.
        Shared with the WaveLayer."""
        p.setRenderHint(QPainter.Antialiasing)
        mute_size, _ = self._badge_sizes(rect)
        if self._strip_audio and not self._expanded:
            margin = max(px(4), round(mute_size * 0.28))
            svg_renderer("audio-mute.svg").render(
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

    def _hover_scale(self, name):
        """The size factor for control `name` ("left", "right" or "expand") right now."""
        return 1.0 + (_HOVER_GROW - 1.0) * self._hover[name]

    def _set_hover(self, name, value):
        self._hover[name] = value
        self.update()

    def _hover_to(self, name, target):
        """Ease control `name` toward `target` (1 grown, 0 normal); a reversal takes only as long
        as the distance left."""
        anim = self._hover_anims[name]
        current = self._hover[name]
        if abs(current - target) < 1e-3 and anim.state() != QVariantAnimation.Running:
            return
        if anim.state() == QVariantAnimation.Running and anim.endValue() == float(target):
            return
        anim.stop()
        anim.setDuration(max(1, round(_HOVER_MS * abs(target - current))))
        anim.setStartValue(current)
        anim.setEndValue(float(target))
        anim.start()

    def _hovered_control(self, pos):
        """Which control a pointer at `pos` is on — the same hit areas a click uses — or None."""
        if self._wave_mode() or not self._frames:
            return None
        if self._over_expand_icon(pos):
            return "expand"
        if len(self._frames) > 1:
            xy, rect = self._local_frame_xy(pos)
            if xy is not None:
                return self._hit_disc(xy[0], xy[1], rect.width(), rect.height())
        return None

    def _sync_hover(self, pos=None):
        """Grow the control under the pointer and ease the rest back. With no `pos`, the cursor
        is read (the controls moved under a still pointer)."""
        if pos is None:
            cursor = self.mapFromGlobal(QCursor.pos())
            pos = QPointF(cursor) if self.isVisible() and self.rect().contains(cursor) else None
        target = self._hovered_control(pos) if pos is not None else None
        for name in self._hover:
            self._hover_to(name, 1.0 if name == target else 0.0)

    def _reset_hover(self):
        """Everything back to normal size at once (the controls just moved or went)."""
        for name, anim in self._hover_anims.items():
            anim.stop()
            self._hover[name] = 0.0
        self.update()

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
        # The outgoing picture is what's on screen now, mid-slide included, so spam-clicks chain.
        old_pix = self._pixmap(self._index, old_rect) if not old_rect.isEmpty() else None
        prev_index, prev_start = self._index, self._dot_start
        self._slide.stop()
        self._index = new_index
        self.indexChanged.emit(new_index)
        self._dot_start = self._resolve_dot_start(new_index, delta, prev_index, prev_start)
        self._sync_hover()      # the chevron under the pointer may have just gone (first / last frame)
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
        # >= 1 frame: the expand icon is worth showing on a single-frame preview.
        if self._frames and not self._wave_mode():
            self._fade_to(1.0)

    def leaveEvent(self, e):
        self._fade_to(0.0)
        self._hide_tooltip_soon()
        for name in self._hover:
            self._hover_to(name, 0.0)

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
        """Excludes a side from the central double-click area only while its chevron is drawn."""
        left, right, radius = self._disc_centers(w, h)
        reach = radius * 2.0 + fpx(16.0)
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
            # Not while expanded: an accidental double-click shouldn't open a file browser.
            self.reselect.emit()
        self._prev_press_central = central

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            if self._over_expand_icon(e.position()):
                self._toggle_expand()
                return
            if self._expanded and not self._within_frame(e.position()):
                # A click on the letterbox bars dismisses the expanded view, like the scrim.
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
        self._sync_hover(e.position())
        if self._over_info_badge(e.position()):
            # Already up: re-showing it on every move made the popup flicker.
            self._tooltip_grace.stop()
            if self._tooltip is None or not self._tooltip.isVisible():
                self._show_tooltip()
        else:
            self._hide_tooltip_soon()
        self.setCursor(self._hover_cursor(e.position()))

    def _over_chevron(self, pos):
        if self._wave_mode() or len(self._frames) <= 1:
            return False
        xy, rect = self._local_frame_xy(pos)
        if xy is None:
            return False
        return self._hit_disc(xy[0], xy[1], rect.width(), rect.height()) is not None

    def _within_frame(self, pos):
        """Whether `pos` is on the letterboxed picture, not just the carousel's bounds."""
        rect = self._frame_rect()
        return not rect.isEmpty() and rect.contains(pos)

    def _hover_cursor(self, pos):
        """A pointing hand everywhere on the small preview; on the expanded one an arrow except
        over the info badge, chevrons and shrink icon (and never outside the picture)."""
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
            # Via screen coordinates: the wave layer is a sibling, and `mapTo` only walks up.
            wave_pos = self.wave.mapFromGlobal(self.mapToGlobal(pos.toPoint()))
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
        """Not offered in wave mode, like the chevrons."""
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
        # The carousel was just reparented and resized under a still mouse: re-read the cursor.
        self.setCursor(self._hover_cursor(self.mapFromGlobal(QCursor.pos())))
        self._reset_hover()     # the icon jumped to a new place; whatever is under the pointer now grows afresh
        self._sync_hover()

    def toggle_expand(self):
        """The keyboard's route to the corner icon: shrinks whenever expanded, expands only where
        the icon is offered (frames to show, not the Wave Loop). True if it did anything."""
        if not self._expanded and (self._wave_mode() or not self._frames):
            return False
        self._toggle_expand()
        return True

    def force_collapse(self):
        """Shrink back if expanded (the previewed file is about to change)."""
        if self._expanded:
            self._toggle_expand()

    def _show_tooltip(self):
        if self._tooltip is None:
            self._tooltip = _InfoTooltip()
            self._tooltip.entered.connect(self._tooltip_grace.stop)
            self._tooltip.left.connect(self._hide_tooltip_soon)
        self._tooltip_grace.stop()
        self._tooltip.setText(self._info_text())
        self._tooltip.adjustSize()
        # Anchored above the badge, never over it: a tip under the cursor stole the mouse, and
        # the carousel hid it again in a flickering loop.
        badge = self._badge_global_rect()
        gap = max(px(12), round(badge.height() * 0.4))     # clears the badge's own hover margin
        x, y = badge.left(), badge.top() - self._tooltip.height() - gap
        screen = self.screen()
        if screen is not None:
            avail = screen.availableGeometry()
            x = max(avail.left(), min(x, avail.right() - self._tooltip.width()))
            if y < avail.top():           # no room above: beside the badge instead
                x, y = badge.right() + gap, max(avail.top(), badge.bottom() - self._tooltip.height())
        self._tooltip.move(x, y)
        self._tooltip.show()

    def _badge_global_rect(self):
        """The info badge in screen coordinates — where it is actually drawn, which
        is on the Wave Loop layer (not the carousel) in wave mode."""
        if self._wave_mode():
            rect, host = self._info_badge_rect(QRectF(self.wave.rect())), self.wave
        else:
            rect, host = self._info_badge_rect(self._frame_rect()), self
        box = rect.toRect()
        return QRect(host.mapToGlobal(box.topLeft()), box.size())

    def _refresh_open_tooltip(self):
        """Re-words (and re-anchors: the badge moves between the picture and the wave
        layer) a tip that is showing while the preview's mode changes under it."""
        if self._tooltip is not None and self._tooltip.isVisible():
            self._show_tooltip()

    def _hide_tooltip(self):
        """Hides the tip at once — for a change of state (file, collapse, teardown)."""
        self._tooltip_grace.stop()
        if self._tooltip is not None:
            self._tooltip.hide()

    def _hide_tooltip_soon(self):
        """The pointer left the badge (or the tip): hide after a short grace, so it can
        travel from one to the other and keep the tip up."""
        if self._tooltip is not None and self._tooltip.isVisible():
            self._tooltip_grace.start()

    def _grace_expired(self):
        """Hides the tip unless the pointer has come to rest on it or back on the badge —
        judged from where the cursor is now, so a missed enter/leave can't strand it."""
        if self._tooltip is None or not self._tooltip.isVisible():
            return
        cursor = QCursor.pos()
        if self._tooltip.frameGeometry().contains(cursor):
            return
        if self._over_info_badge(QPointF(self.mapFromGlobal(cursor))):
            return
        self._tooltip.hide()

    @staticmethod
    def _mastering_text(info):
        max_nits = info.get("mastering_max_nits")
        # A zero MaxCLL/MaxFALL is unset, not a measurement.
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
        # Wave Loop showing (stripped video or audio-only): describe the audio only.
        if self._wave_mode():
            pass
        elif info.get("has_video") is False:
            lines.append("Video: none")
        elif info.get("video"):
            bits = [info["video"]]
            if info.get("video_profile"):
                bits.append(info["video_profile"])
            if info.get("video_level"):
                bits.append(f"L{info['video_level']}")
            if info.get("width") and info.get("height"):
                bits.append(f"{info['width']}x{info['height']}")
            if info.get("fps"):
                bits.append(f"{fps_text(info['fps'])} fps")      # right beside the resolution
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
                bits.append(f"+ {len(streams)} tracks")
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
