# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""The one UI scale factor. Every size is authored in reference pixels (the `BASE_W` x
`BASE_H` window) and multiplied by `factor()` where it becomes real pixels.

  * Layout, fixed sizes, margins and spacing go through `px()`, via the bound helpers (`fixed`,
    `margins`, `spacing`, `bind`) when set once, so a scale change re-applies them.
  * Custom painting is in design space: `begin(p)` scales the painter; `ref_size`, `ref_rect`
    and `ref_pos` convert sizes and mouse positions.
  * Text goes through the scaled painter too (`ScaledLabel` etc.): Qt snaps widget fonts to
    whole pixels, so they'd step during a drag."""
import itertools
import weakref

from PySide6.QtCore import QObject, QPointF, QRectF, Signal
from PySide6.QtWidgets import QBoxLayout, QSizePolicy, QSpacerItem
from shiboken6 import isValid

BASE_W, BASE_H = 896, 540      # the reference window: 35% x 37.5% of a 2560x1440 screen
WINDOW_W_FRAC = 0.35           # the window's share of the screen's width...
WINDOW_H_FRAC = 0.375          # ...and the most of its height it may take
_MIN, _MAX = 0.25, 8.0


class _Notifier(QObject):
    changed = Signal()


_notifier = _Notifier()
changed = _notifier.changed    # emitted after every factor change (and after the bound setters re-ran)
_factor = 1.0
_bound = {}                    # {(weakref to widget, key): fn} — re-run on every change, in creation order
_uid = itertools.count()       # keys for setters nothing else will ever replace
_prune_at = 512                # registry size that triggers a sweep for dead widgets
_after = []                    # [(weakref to widget, fn)] — re-run once the window has re-styled


def factor():
    """The current scale (1.0 = the reference layout)."""
    return _factor


def set_factor(value):
    """Adopt a new scale; re-run every bound setter, then emit `changed`."""
    global _factor
    value = max(_MIN, min(_MAX, float(value)))
    if abs(value - _factor) < 1e-6:
        return
    _factor = value
    for (ref, _key), fn in list(_bound.items()):
        w = ref()
        if w is not None and isValid(w):
            fn()
    _prune()
    changed.emit()


def fit(width, height):
    """The scale at which the reference layout fits a `width` x `height` box."""
    return min(width / BASE_W, height / BASE_H)


def window_size(screen_w, screen_h):
    """The main window's (width, height) for a screen — the reference aspect
    ratio at 35% of the screen's width (less if the screen is too short)."""
    width = min(screen_w * WINDOW_W_FRAC, screen_h * WINDOW_H_FRAC * BASE_W / BASE_H)
    return round(width), round(width * BASE_H / BASE_W)


def px(n):
    """`n` reference pixels as whole pixels at the current scale (a non-zero
    length never rounds to nothing, so hairlines and borders survive)."""
    if not n:
        return 0
    v = round(n * _factor)
    return v if v else (1 if n > 0 else -1)


def fpx(n):
    """`n` reference pixels as a float (for geometry that isn't pixel-snapped)."""
    return n * _factor


def font_px(n):
    """A reference font size as the whole-pixel size Qt will render."""
    return max(1, round(n * _factor))


def bind(widget, fn, key=None):
    """Run `fn()` now and on every scale change while `widget` lives. Binding the same `key` on
    the same widget replaces the earlier setter instead of stacking one that would re-apply an
    old value."""
    fn()
    _bound[(weakref.ref(widget), next(_uid) if key is None else key)] = fn
    if len(_bound) > _prune_at:
        _prune()


def _prune():
    """Drop setters of dead widgets; the next sweep is at twice the survivors."""
    global _prune_at
    for k in [k for k in _bound if k[0]() is None or not isValid(k[0]())]:
        del _bound[k]
    _prune_at = max(512, 2 * len(_bound))


def bind_style(widget, text_fn, key="style-text"):
    """`bind` for a widget's own stylesheet, calling setStyleSheet only when the text changed
    (a rescale often lands on the same whole-pixel values)."""
    def apply():
        text = text_fn()
        if text != getattr(widget, "_bound_style_text", None):
            widget._bound_style_text = text
            widget.setStyleSheet(text)
    bind(widget, apply, key)


def bind_after(widget, fn):
    """Run `fn()` now and after every scale change once the stylesheet is re-applied: for
    sizes measured off other widgets' hints."""
    fn()
    _after.append((weakref.ref(widget), fn))


def settle():
    """The window calls this once it has re-styled for a new scale."""
    live = []
    for ref, fn in _after:
        w = ref()
        if w is not None and isValid(w):
            live.append((ref, fn))
            fn()
    _after[:] = live


def fixed(widget, w=None, h=None):
    """Fix a widget's width and/or height at `w` / `h` reference pixels."""
    if w is not None:
        bind(widget, lambda: widget.setFixedWidth(px(w)), "fixed-w")
    if h is not None:
        bind(widget, lambda: widget.setFixedHeight(px(h)), "fixed-h")


def bounds(widget, min_w=None, min_h=None, max_w=None, max_h=None):
    """Set a widget's minimum / maximum width and height in reference pixels."""
    if min_w is not None:
        bind(widget, lambda: widget.setMinimumWidth(px(min_w)), "min-w")
    if min_h is not None:
        bind(widget, lambda: widget.setMinimumHeight(px(min_h)), "min-h")
    if max_w is not None:
        bind(widget, lambda: widget.setMaximumWidth(px(max_w)), "max-w")
    if max_h is not None:
        bind(widget, lambda: widget.setMaximumHeight(px(max_h)), "max-h")


def margins(layout, left, top=None, right=None, bottom=None):
    """A layout's contents margins in reference pixels (one value = all four)."""
    if top is None:
        top = right = bottom = left
    bind(layout, lambda: layout.setContentsMargins(px(left), px(top), px(right), px(bottom)), "margins")


def spacing(layout, n):
    """A layout's spacing in reference pixels."""
    bind(layout, lambda: layout.setSpacing(px(n)), "spacing")


def spacer(layout, n):
    """`layout.addSpacing(n)` with `n` in reference pixels, following the scale."""
    horizontal = isinstance(layout, QBoxLayout) and layout.direction() in (
        QBoxLayout.LeftToRight, QBoxLayout.RightToLeft)
    if horizontal:
        item = QSpacerItem(0, 0, QSizePolicy.Fixed, QSizePolicy.Minimum)
    else:
        item = QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Fixed)

    def apply():
        if horizontal:
            item.changeSize(px(n), 0, QSizePolicy.Fixed, QSizePolicy.Minimum)
        else:
            item.changeSize(0, px(n), QSizePolicy.Minimum, QSizePolicy.Fixed)
        layout.invalidate()
    layout.addItem(item)
    bind(layout, apply)   # one spacer item per call — deliberately unkeyed


def grid_spacing(layout, horizontal, vertical=None):
    """A grid layout's horizontal / vertical spacing in reference pixels."""
    v = horizontal if vertical is None else vertical
    bind(layout, lambda: (layout.setHorizontalSpacing(px(horizontal)), layout.setVerticalSpacing(px(v))),
         "grid-spacing")


# --------------------------------------------------------------------------- #
#  Design-space painting
# --------------------------------------------------------------------------- #
def begin(painter):
    """Scale `painter` so paint code can use reference pixels."""
    painter.scale(_factor, _factor)


def ref_size(widget):
    """(width, height) of `widget` in reference pixels."""
    return widget.width() / _factor, widget.height() / _factor


def ref_rect(widget):
    """`widget`'s rect in reference pixels."""
    w, h = ref_size(widget)
    return QRectF(0, 0, w, h)


def ref_pos(pos):
    """A widget-space mouse position mapped back into reference pixels."""
    p = QPointF(pos)
    return QPointF(p.x() / _factor, p.y() / _factor)
