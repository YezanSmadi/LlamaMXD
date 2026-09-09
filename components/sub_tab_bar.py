import math
import time
import tkinter as tk
import tkinter.font as tkfont

import customtkinter as ctk

from core.theme import (
    get_active_theme,
    readable_text_on,
    STOP_RED,
    STOP_RED_HOVER,
)

# The active tab stands at full height; the inactive ones at 80% of it — a
# gentle step down that reads as "behind" the current tab, all sitting on one
# baseline so they look like tabs on a shelf.
_ACTIVE_H = 30
_INACTIVE_H = 24
_GAP = 3          # px between buttons
_RADIUS = 6       # button corner radius
_PAD_X = 13       # text padding inside a button

# Switching is animated: the chosen tab eases up to full height while its fill
# straight-RGB cross-fades to `primary`, and the old tab settles back. Drawn on
# a single Canvas (see class doc) so nothing flickers. The clock is wall-time
# (`_ANIM_MS` is just the polling interval) — `after` runs ~11ms slow on this
# box, so a step-counted version dropped frames unevenly near the end and the
# fade looked like it lurched into the final colour.
_ANIM_MS = 12
_ANIM_DURATION = 0.17   # seconds, start → settled


def _round_rect_points(x0, y0, x1, y1, r, steps=5):
    """Perimeter points of a rounded rectangle, for a single filled
    `create_polygon`. One primitive fills by one rule, so there's no seam
    where a shape meets another — an arc-plus-rectangle build leaves a 1px
    notch where the curve meets the straight edge (Tk rasterises the two a
    pixel apart), which is exactly what this replaced."""
    r = max(0.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    pts = []
    for cx, cy, a0 in ((x1 - r, y0 + r, 270), (x1 - r, y1 - r, 0),
                       (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
        for k in range(steps + 1):
            a = math.radians(a0 + 90 * k / steps)
            pts.append(cx + r * math.cos(a))
            pts.append(cy + r * math.sin(a))
    return pts


def _rgb01(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _lerp_hex(a, b, t):
    """Straight per-channel RGB interpolation between two ``#rrggbb`` colours."""
    (ar, ag, ab), (br, bg, bb) = _rgb01(a), _rgb01(b)
    return "#%02x%02x%02x" % (
        round((ar + (br - ar) * t) * 255),
        round((ag + (bg - ag) * t) * 255),
        round((ab + (bb - ab) * t) * 255),
    )


class SubTabBar(ctk.CTkFrame):
    """A compact row of mutually-exclusive tab buttons (Muxing/Encoding's
    `Overview` / `Video` / `Audio` switch), sitting top-left of the preview
    area.

    **The whole bar is one `tkinter.Canvas`**, not a row of `CTkButton`s. Each
    "button" is **one filled `create_polygon`** — a rounded rectangle whose
    corners are short arcs of points (`_round_rect_points`) — plus a centred
    text item. It used to be built from a body rect, a cross rect and four
    corner shapes, but Tk rasterises a `create_rectangle` edge and an
    adjacent `create_oval` / `pieslice` edge a pixel apart, leaving a visible
    1px notch where a corner meets a straight edge. One polygon fills by one
    rule, so there is no seam. Switching tabs animates each button's height
    and
    fill by updating those canvas items' `coords`/`itemconfig` in place — no
    widget is resized or reconfigured, so there is none of the per-frame
    redraw / text-reflow flicker that an animated `CTkButton` produced (this
    was reported three times against the `CTkButton` version).

    The active button is `primary` at `_ACTIVE_H`; inactive ones are
    `secondary` at `_INACTIVE_H`, bottom-aligned. `set_marked(name, bool)`
    cross-fades a button to/from the permanent `STOP_RED` (whether or not it's
    active) — Strip Video lives on the Video panel and Strip Audio on the
    Audio panel, so without the red tab a removed stream would silently change
    state on a panel the user can't currently see.

    Nothing to refresh on a live theme switch — the owning tab is rebuilt
    whole, so this is reconstructed and re-reads `get_active_theme()`."""

    def __init__(self, master, options, command, initial=None, **kwargs):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self._theme = get_active_theme()
        self._command = command
        self._names = list(options)
        self._marked = set()
        self._active = initial if initial in self._names else self._names[0]
        self._hover = None
        self._anim_job = None

        self._active_font = self._apply_font_scaling(ctk.CTkFont(size=13, weight="bold"))
        self._inactive_font = self._apply_font_scaling(ctk.CTkFont(size=12, weight="bold"))
        measure = tkfont.Font(font=self._active_font)
        self._widths = [max(58, measure.measure(n) + 2 * _PAD_X) for n in self._names]
        total_w = sum(self._widths) + _GAP * (len(self._names) - 1)

        self.configure(width=total_w, height=_ACTIVE_H)
        self.pack_propagate(False)

        self._cv = tk.Canvas(
            self, width=total_w, height=_ACTIVE_H, highlightthickness=0, bd=0,
            takefocus=0, cursor="hand2", bg=self._canvas.cget("bg"),
        )
        self._cv.pack(fill="both", expand=True)

        # Per-button item ids, and live (fill, height, text_colour) state.
        self._items = [self._make_items(i) for i in range(len(self._names))]
        for i in range(len(self._names)):
            self._cv.tag_raise(f"t{i}")
        self._state = {
            n: (self._fill_for(n), self._height_for(n), self._text_for(n))
            for n in self._names
        }
        self._redraw()

        self._cv.bind("<Motion>", self._on_motion, add="+")
        self._cv.bind("<Leave>", self._on_leave, add="+")
        self._cv.bind("<Button-1>", self._on_click_event, add="+")
        self.bind("<Destroy>", lambda _e: self._cancel_anim(), add="+")

    # ------------------------------------------------------------------ #
    #  Target look per button
    # ------------------------------------------------------------------ #
    def _fill_for(self, name):
        if name in self._marked:
            return STOP_RED
        return self._theme["primary"] if name == self._active else self._theme["secondary"]

    def _hover_fill_for(self, name):
        if name in self._marked:
            return STOP_RED_HOVER
        return (self._theme["primary_hover"] if name == self._active
                else self._theme["secondary_hover"])

    def _text_for(self, name):
        if name in self._marked:
            return readable_text_on(STOP_RED)
        return (self._theme["primary_text"] if name == self._active
                else self._theme["secondary_text"])

    def _height_for(self, name):
        return _ACTIVE_H if name == self._active else _INACTIVE_H

    # ------------------------------------------------------------------ #
    #  Canvas drawing
    # ------------------------------------------------------------------ #
    def _make_items(self, i):
        """Creates (at 0,0) the two canvas items for one button: the
        rounded-rect body (a single filled polygon) and the label."""
        tag = f"b{i}"
        return {
            "shape": self._cv.create_polygon(
                0, 0, 0, 0, 0, 0, width=0, joinstyle="round", tags=tag
            ),
            "text": self._cv.create_text(
                0, 0, text=self._names[i], font=self._active_font, tags=f"t{i}"
            ),
        }

    def _redraw(self):
        """Repaints every button from `self._state` (+ hover)."""
        bottom = _ACTIVE_H
        x = 0
        for i, name in enumerate(self._names):
            w = self._widths[i]
            fill, h, text_fill = self._state[name]
            if self._hover == name and self._anim_job is None:
                fill = self._hover_fill_for(name)
            self._paint(i, x, bottom - h, x + w, bottom, fill, text_fill,
                        self._active_font if name == self._active else self._inactive_font)
            x += w + _GAP

    def _paint(self, i, x0, y0, x1, y1, fill, text_fill, font):
        c, ids = self._cv, self._items[i]
        c.coords(ids["shape"], *_round_rect_points(x0, y0, x1, y1, _RADIUS))
        c.itemconfig(ids["shape"], fill=fill, outline=fill)
        c.coords(ids["text"], (x0 + x1) / 2, (y0 + y1) / 2 + 1)
        c.itemconfig(ids["text"], fill=text_fill, font=font)

    # ------------------------------------------------------------------ #
    #  Animation
    # ------------------------------------------------------------------ #
    def _display_fill(self, name):
        """The fill actually on screen for `name` right now — `_fill_for` plus
        the hover shade when the pointer is on it. Both endpoints of the fade
        use this, so the fade can't end on `_fill_for` and then snap to the
        hover shade (a visible lurch into the final colour)."""
        if self._hover == name:
            return self._hover_fill_for(name)
        return self._fill_for(name)

    def _animate(self):
        was_running = self._anim_job is not None
        self._cancel_anim()
        # `_anim_from` must be what's *on screen*: mid-interpolation values if a
        # fade was already running, else the resting look with the hover shade
        # folded in (`_state` stores the resting fill; `_redraw` adds hover).
        self._anim_from = {
            n: ((self._state[n][0] if was_running else self._display_fill(n)),
                self._state[n][1], self._state[n][2])
            for n in self._names
        }
        self._anim_to = {
            n: (self._display_fill(n), self._height_for(n), self._text_for(n))
            for n in self._names
        }
        self._anim_t0 = time.monotonic()
        self._anim_tick()

    def _anim_tick(self):
        frac = (time.monotonic() - self._anim_t0) / _ANIM_DURATION
        if frac >= 1.0:
            self._anim_job = None
            for n in self._names:
                self._state[n] = (self._fill_for(n), self._height_for(n), self._text_for(n))
            self._redraw()   # re-applies the hover shade if the pointer is on a button
            return
        eased = frac * frac * (3 - 2 * frac)   # smoothstep
        for n in self._names:
            ff, fh, ftext = self._anim_from[n]
            tf, th, ttext = self._anim_to[n]
            self._state[n] = (
                _lerp_hex(ff, tf, eased),
                fh + (th - fh) * eased,          # float — smoother than rounding per frame
                ttext if eased >= 0.5 else ftext,   # text colour snaps at the midpoint
            )
        self._redraw()
        self._anim_job = self.after(_ANIM_MS, self._anim_tick)

    def _cancel_anim(self):
        if self._anim_job is not None:
            self.after_cancel(self._anim_job)
            self._anim_job = None

    # ------------------------------------------------------------------ #
    #  Events
    # ------------------------------------------------------------------ #
    def _hit(self, x):
        cx = 0
        for i, name in enumerate(self._names):
            if cx <= x <= cx + self._widths[i]:
                return name
            cx += self._widths[i] + _GAP
        return None

    def _on_motion(self, event):
        name = self._hit(event.x)
        if name != self._hover:
            self._hover = name
            if self._anim_job is None:
                self._redraw()

    def _on_leave(self, _event):
        if self._hover is not None:
            self._hover = None
            if self._anim_job is None:
                self._redraw()

    def _on_click_event(self, event):
        name = self._hit(event.x)
        if name is not None:
            self._on_click(name)

    def _on_click(self, name):
        """Selects `name` (unless already active) and fires `command`."""
        if name == self._active:
            return
        self._active = name
        self._animate()
        self._command(name)

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #
    def set_marked(self, name, marked):
        """Cross-fades one tab button to/from `STOP_RED` to surface a stripped
        stream from whichever panel is on screen. No-ops when nothing changes,
        since `_sync_controls` calls this on every pass."""
        if name not in self._names:
            return
        if (name in self._marked) == bool(marked):
            return
        self._marked.add(name) if marked else self._marked.discard(name)
        self._animate()

    def get(self):
        """The name of the currently-active tab."""
        return self._active

    def set(self, name, fire=False):
        """Selects `name` programmatically. Fires `command` only if `fire`."""
        if name not in self._names or name == self._active:
            return
        self._active = name
        self._animate()
        if fire:
            self._command(name)
