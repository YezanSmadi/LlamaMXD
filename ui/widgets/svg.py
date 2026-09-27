# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""SVG assets recoloured by rewriting the file's text before parsing, so they stay vector and
smooth at any size. One cached QSvgRenderer per (asset, colour, mode)."""
import os
import re

from PySide6.QtCore import QByteArray
from PySide6.QtSvg import QSvgRenderer

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets")

_BLACK_STROKE = re.compile(r'stroke(=")#000(?:000)?"|stroke(:\s*)#000(?:000)?(;?)')
_PAINTED_FILL = re.compile(r'fill="(?!none")[^"]*"')   # a group's fill="none" stays
_cache = {}


def _recolor(data, color, mode):
    if mode == "ink":
        # Stroke-drawn icons: black strokes (attribute or CSS), currentColor fills, and the
        # Illustrator near-black #231f20 the sort / search icons use.
        data = _BLACK_STROKE.sub(
            lambda m: f'stroke="{color}"' if m.group(1) else f"stroke{m.group(2)}{color}{m.group(3)}", data)
        return data.replace('fill="currentColor"', f'fill="{color}"').replace("#231f20", color)
    if mode == "fills":
        return _PAINTED_FILL.sub(f'fill="{color}"', data)       # icons shipped in assorted colours
    return data.replace('fill="currentColor"', f'fill="{color}"')      # "current"


def svg_renderer(name, color=None, mode="current"):
    """A cached renderer for `assets/<name>`, recoloured to `color` (a hex string) by `mode`:
    "current" swaps `fill="currentColor"`, "ink" also black strokes and #231f20, "fills" every
    painted fill. No `color`: the file as authored."""
    key = (name, color, mode if color else None)
    if key not in _cache:
        with open(os.path.join(ASSETS, name), "r", encoding="utf-8") as fh:
            data = fh.read()
        if color:
            data = _recolor(data, color, mode)
        _cache[key] = QSvgRenderer(QByteArray(data.encode("utf-8")))
    return _cache[key]
