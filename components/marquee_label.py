import tkinter as tk
import tkinter.font as tkfont

import customtkinter as ctk

_TICK_MS = 16                 # ~60 fps
_SPEED_PX_PER_SEC = 42.0      # how fast the text slides while scrolling
_GAP_PX = 64                  # blank gap between the text's tail and its repeat


class MarqueeLabel(ctk.CTkFrame):
    """A single-line label that *smoothly* scrolls its text sideways (pixel by
    pixel, ~60fps) when the text is wider than the space it's given, and sits
    perfectly still when it fits.

    Drop-in for the header-row `CTkLabel` it replaced — `configure(text=...)`
    is intercepted, so `app.update_global_file` (which just rewrites the
    "Selected File:" line) needs no changes. It renders onto a raw
    `tkinter.Canvas` rather than a `CTkLabel` specifically so the scroll can
    advance by sub-character amounts: a `tk.Label` can only be shifted a whole
    glyph at a time, which is what made the first version jerky.

    The canvas is packed *over* CTkFrame's own placed background canvas — they
    coexist because they use different geometry managers (place vs pack) — and
    its `bg` is pinned to that background's resolved colour, so the widget
    still disappears into a `fg_color="transparent"` parent. Two text items,
    one trailing the other by `text width + gap`, give a seamless loop: when
    the leading copy has scrolled a full span off the left edge, the offset
    snaps back by one span and the trailing copy is now the leading one."""

    def __init__(self, master, text="", font=None, anchor="w",
                 speed=_SPEED_PX_PER_SEC, gap=_GAP_PX, **kwargs):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self._full_text = text or ""
        self._px_per_tick = speed * _TICK_MS / 1000.0
        self._gap = gap
        self._offset = 0.0
        self._seg_w = 0
        self._avail = 0
        self._cy = 0
        self._job = None
        # None = the plain CTkLabel theme color; a real value (e.g. STOP_RED)
        # overrides it -- set via configure(text_color=...), same convention
        # as a real CTkLabel. Tracked separately from `_fill` (the resolved,
        # appearance-mode-applied colour actually drawn) so a light/dark flip
        # re-resolves the override instead of falling back to the default.
        self._color_override = None

        self._font = font if font is not None else ctk.CTkFont(size=12)
        # The scaled (family, size, style) tuple CTk would render this font at
        # — used for both the canvas items and the width measurement, so the
        # overflow test matches what's actually drawn.
        self._font_spec = self._apply_font_scaling(self._font)
        self._measure = tkfont.Font(font=self._font_spec)
        self._fill = self._apply_appearance_mode(
            ctk.ThemeManager.theme["CTkLabel"]["text_color"]
        )

        # A bare tk.Canvas defaults to ~378x266 and would inflate the header
        # row — pin its height to one text line and let width come from the
        # fill="x" pack.
        line_h = self._measure.metrics("linespace") + 4
        self._cy = line_h / 2
        self._cv = tk.Canvas(self, highlightthickness=0, bd=0, takefocus=0,
                             height=line_h, width=1, bg=self._canvas.cget("bg"))
        self._cv.pack(fill="x", expand=True)
        common = dict(anchor="w", font=self._font_spec, fill=self._fill, tags="txt")
        self._item_a = self._cv.create_text(0, 0, text=self._full_text, **common)
        self._item_b = self._cv.create_text(0, 0, text=self._full_text,
                                            state="hidden", **common)

        self._cv.bind("<Configure>", self._on_configure, add="+")
        self._cv.bind("<Map>", lambda _e: self._restart(), add="+")
        self._cv.bind("<Unmap>", lambda _e: self._cancel(), add="+")
        self.bind("<Destroy>", lambda _e: self._cancel(), add="+")

    # ------------------------------------------------------------------ #
    #  CTk plumbing
    # ------------------------------------------------------------------ #
    def _draw(self, no_color_updates=False):
        """Keep the overlay canvas' background and text colour in step with
        CTk's own redraws (appearance-mode flip, scaling change) -- re-applies
        the colour override (if any) rather than always falling back to the
        plain theme default, so it survives a live appearance-mode switch."""
        super()._draw(no_color_updates)
        if not hasattr(self, "_cv"):
            return
        self._cv.configure(bg=self._canvas.cget("bg"))
        color = self._color_override or ctk.ThemeManager.theme["CTkLabel"]["text_color"]
        self._fill = self._apply_appearance_mode(color)
        self._cv.itemconfigure("txt", fill=self._fill)

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #
    def configure(self, require_redraw=False, **kwargs):
        """Intercepts `text=`/`text_color=` to feed the marquee; everything
        else passes straight through to `CTkFrame.configure`."""
        if "text_color" in kwargs:
            self.set_text_color(kwargs.pop("text_color"))
        if "text" in kwargs:
            self.set_text(kwargs.pop("text"))
        if kwargs or require_redraw:
            super().configure(require_redraw=require_redraw, **kwargs)

    def set_text_color(self, color):
        """Overrides the text colour (e.g. STOP_RED for a removed stream),
        or clears the override back to the plain theme default when `color`
        is falsy -- the same `color or default` convention SummaryPanel's
        own set_values already uses for a real CTkLabel."""
        self._color_override = color or None
        self._fill = self._apply_appearance_mode(
            color or ctk.ThemeManager.theme["CTkLabel"]["text_color"]
        )
        self._cv.itemconfigure("txt", fill=self._fill)

    def cget(self, key):
        """Reports the full (un-scrolled) string for `"text"`."""
        if key == "text":
            return self._full_text
        return super().cget(key)

    def bind(self, sequence=None, command=None, add="+"):
        """Also bind the visible canvas, so a handler the tab attaches
        (double-click -> reselect the file) fires when the text is clicked."""
        super().bind(sequence, command, add)
        if hasattr(self, "_cv"):
            self._cv.bind(sequence, command, add="+")

    def set_text(self, text):
        """Sets the full string and re-decides scroll vs. stand-still."""
        text = text or ""
        if text == self._full_text:
            return
        self._full_text = text
        self._cv.itemconfigure("txt", text=text)
        self._offset = 0.0
        self._restart()

    # ------------------------------------------------------------------ #
    #  Internals
    # ------------------------------------------------------------------ #
    def _on_configure(self, event):
        """Width/height changed — re-measure and re-decide."""
        self._avail = event.width
        self._cy = event.height / 2
        self._restart()

    def _cancel(self):
        """Stops the scroll loop."""
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None

    def _restart(self):
        """Starts (or stops) the scroll depending on whether the text
        overflows the current width."""
        self._cancel()
        if not self._cy:
            self._cy = (self._cv.winfo_height() or 2) / 2
        self._seg_w = self._measure.measure(self._full_text)
        if self._avail > 1 and self._seg_w > self._avail:
            self._cv.itemconfigure(self._item_b, state="normal")
            self._tick()
        else:
            self._offset = 0.0
            self._cv.itemconfigure(self._item_b, state="hidden")
            self._cv.coords(self._item_a, 0, self._cy)

    def _tick(self):
        """Advances the scroll by one frame's worth of pixels."""
        span = self._seg_w + self._gap
        self._offset -= self._px_per_tick
        if -self._offset >= span:
            self._offset += span
        self._cv.coords(self._item_a, self._offset, self._cy)
        self._cv.coords(self._item_b, self._offset + span, self._cy)
        self._job = self.after(_TICK_MS, self._tick)
