import customtkinter as ctk
from PIL import Image, ImageDraw

from core.theme import get_active_theme, readable_text_on

# How many fade ticks between fully-hidden and fully-shown arrows, and how
# long each tick is. Short and cheap — each tick is a single PIL Image.blend
# of two already-rendered images (see _update_image), not a re-composite.
_FADE_STEPS = 6
_FADE_INTERVAL_MS = 16

# Slide-transition between previews: crop a moving window across a [current |
# next] strip. Kept short so spam-clicking a chevron still feels immediate —
# a new step just restarts the slide from whatever's on screen.
_SLIDE_STEPS = 7
_SLIDE_INTERVAL_MS = 16

# PIL's ellipse / line primitives don't antialias, so the overlay is drawn at
# _OVERLAY_SS x size and box-filtered down (premultiplied — see _build_overlay
# — so the transparent edges don't pick up a dark fringe). Full factor for the
# resting / settled overlay; a lighter one for the per-tick rebuilds during a
# slide, where a marginally softer in-between frame is invisible in motion.
_OVERLAY_SS = 4
_OVERLAY_SS_ANIM = 2

# Dot indicators: a row of position dots centred along the bottom edge, in
# three sizes. The centre _DOT_CLUSTER (3) dots are large and *screen-
# stationary* — always at w/2-gap, w/2, w/2+gap — and the current-frame
# highlight rides between those three fixed slots. Beyond the cluster,
# _DOT_LOOK (2) dots per side taper medium-then-small. Only frames that
# actually exist get a dot, so the row is 7 wide in the interior
# (S M L L L M S), 5 at the ends (L L L M S, mirrored), and grows/shrinks
# between as look-behind dots come into range.
#
# The highlight sits at the cluster edge it's heading toward — the right
# large slot when advancing, the left one when going back — for a bit of
# visible lead. A single step *past* that edge is what scrolls the whole row
# by one gap; until then the surrounding dots hold still and only the
# highlight hops slot to slot. So a direction change walks the highlight back
# across the middle large slot before any dot moves. White reads on any
# frame, so these stay theme-independent (only the chevrons follow the theme).
_DOT_R_LARGE = 4.0
_DOT_R_MED = 3.0
_DOT_R_SMALL = 2.0
_DOT_GAP = 16.0
_DOT_CLUSTER = 3      # large, screen-stationary centre dots
_DOT_LOOK = 2         # medium-then-small taper dots each side
_DOT_ON_RGBA = (255, 255, 255, 235)
_DOT_OFF_RGBA = (255, 255, 255, 90)


class ThumbnailCarousel(ctk.CTkFrame):
    """Shows one of several preview frames at a time, with left/right chevrons
    that fade in while the pointer is over the preview.

    **Two layers, kept separate.** `_base_scaled` is the *pure* fitted video
    frame — nothing is ever drawn onto it. `_overlay` is a standalone RGBA
    layer holding just the chevrons + dot indicators for the current index,
    transparent everywhere else. `_push` composites overlay-onto-frame *at
    paint time* (`Image.alpha_composite`, the overlay's alpha scaled by
    `_arrow_alpha` for the hover fade). They can't be real Tk widgets — Tk
    has no per-pixel transparency for an in-window widget (see CLAUDE.md:
    the toast, the tab indicator, the queue fill), so an overlaid `CTkButton`
    would be opaque with un-colour-matchable corner nooks over the video —
    but keeping them as their own image layer gets the same result: the
    frames stay clean, and the overlay is drawn once per (index, size,
    theme), not baked into anything.

    **The slide moves the picture, not the buttons.** `_animate_slide` crops
    a window across a `[current | next]` strip of *pure* frames; `_push`
    drops the *same fixed* `_overlay` on each tick, so the image content
    scrolls under stationary chevrons.

    The prev/next control is a disc in the active theme's **primary** colour
    with a chevron in whichever of black/white stays legible on it
    (`readable_text_on(primary)` — the same call the themed buttons use). A
    near-solid primary disc rather than a translucent scrim so it reads the
    same over a bright frame region as a dark one. Both colours are resolved
    once at construction: the carousel is destroyed and rebuilt with its tab
    on a live theme switch, so there's nothing to re-read in place. The disc
    is sized from each frame's own dimensions and sits flush against its
    edge, so it's never clipped whatever the aspect ratio.

    A click steps a preview only when it falls **on a chevron disc** —
    `_hit_disc_at` tests the whole disc box against the same `_disc_centers`
    geometry the drawing uses (in screen coords — see `_event_image_xy` for
    why), so the target is the full button and moves with it as it's
    repositioned per frame. **Every click in a rapid burst steps** — both
    `<Button-1>` (the first click) and `<Double-Button-1>` (Tk delivers
    *only* this for the 2nd, 3rd, … clicks of a burst, never `<Button-1>`
    again) route through `_handle_press`, so spam-clicking runs all the way
    to the end. Reselecting the input file (`on_reselect`) needs a
    repeat-click in the frame's **central area** whose predecessor was also
    central — clicks in the left/right edge strip (`_in_chevron_band`, where
    a disc lives, or lived before the clamp) never count, so hammering a
    chevron past the last preview won't pop the file dialog; a deliberate
    double-click on the middle of the frame still does.

    The slide shares the animation channel with the arrow fade
    (`_cancel_anim` covers both) and always starts from whatever pure frame
    is currently on screen (`_displayed_base`), so an interrupting step — a
    spam-click — chains seamlessly.

    **The dot row moves and resizes too.** It's part of `_overlay`, and while
    a slide runs `_slide_step` rebuilds the overlay each tick with the dots
    interpolated from their old layout to the new one — on the same eased
    clock as the picture — so the two settle together. The layout itself
    (`_dot_geometry` / `_resolve_dot_start`) keeps the three large centre
    dots pinned to screen centre; a step first walks the highlight toward the
    edge it's heading for and only scrolls the row once the highlight is
    already there. See the dot-indicator comment block up top."""

    def __init__(self, master, on_reselect=None, on_populated=None, on_index=None):
        super().__init__(master=master, fg_color="transparent")
        self._on_reselect = on_reselect
        self._on_populated = on_populated
        # Reports the current preview index whenever the user steps it, so the
        # app can mirror the scrub position onto the other tab's carousel
        # (LlamaGUI.sync_preview_index). `sync_index` is the receiving end and
        # deliberately does NOT re-fire this.
        self._on_index = on_index

        # Disc = theme primary (near-solid so it shows over any frame);
        # chevron = whichever of black/white stays legible on it. Resolved
        # once — a theme switch rebuilds this widget.
        theme = get_active_theme()
        self._disc_rgba = self._hex_to_rgb(theme["primary"]) + (230,)
        self._arrow_rgba = (
            (0, 0, 0, 255) if readable_text_on(theme["primary"]) == "black"
            else (255, 255, 255, 255)
        )

        self._frames = []           # raw PIL Images, unscaled
        self._index = 0
        self._dot_start = 0         # frame index sitting in the leftmost large dot slot
        self._dot_anim = None       # (prev_dot_start, prev_index) while the dot row re-flows
        self._base_scaled = None    # PIL RGB, the pure fitted frame (no chrome)
        self._overlay = None        # RGBA layer: chevrons + dots for _index
        self._displayed_base = None  # the pure frame currently on the label
        self._rendered_size = (0, 0)  # size of the last CTkImage — for click math
        self._arrow_alpha = 0.0
        self._fade_job = None
        self._anim_job = None       # in-flight slide-transition tick
        self._slide = None          # (strip, w, h, x0, x1) while a slide runs
        self._last_config = (0, 0)
        self._populated = False
        self._ctk_img = None        # keep a ref so Tk doesn't GC the image
        self._prev_press_central = False  # was the previous press in the frame's central area

        self.img_label = ctk.CTkLabel(master=self, text="", cursor="hand2")
        self.img_label.pack(fill="both", expand=True)

        self.bind("<Configure>", self._on_configure)
        self.img_label.bind("<Enter>", self._on_enter)
        self.img_label.bind("<Leave>", self._on_leave)
        # Both: <Button-1> is the first click of a burst, <Double-Button-1>
        # every click after it (Tk stops sending <Button-1> once <Double> is
        # bound). Routing both through _handle_press is what lets a spam-click
        # advance every time instead of just once.
        self.img_label.bind("<Button-1>", lambda e: self._handle_press(e, repeat=False))
        self.img_label.bind("<Double-Button-1>", lambda e: self._handle_press(e, repeat=True))

    # ------------------------------------------------------------------ #
    #  Public API — the app's file-selection broadcast calls set_frames
    # ------------------------------------------------------------------ #
    def set_frames(self, frames):
        """Swaps in a new list of preview frames (the `on_thumbnail` target in
        LlamaGUI.register_tab_ui). Resets to the first preview. The first time
        a non-empty set arrives, fires `on_populated` so the owning tab can
        reveal the carousel in place of its DropBox."""
        self._frames = list(frames or [])
        self._index = 0
        self._dot_start = 0
        self._dot_anim = None
        self._arrow_alpha = 0.0
        self._cancel_anim()

        if self._frames and not self._populated:
            self._populated = True
            if self._on_populated:
                self._on_populated()

        # The on_populated callback may have only just packed us in, so our
        # geometry isn't valid yet — defer the first render to after the
        # resulting <Configure>. A real delay, not after_idle: CTk geometry is
        # unreliable until the widget's first map pass (CLAUDE.md).
        self._rescale()
        self.after(50, self._rescale)

    # ------------------------------------------------------------------ #
    #  Rendering
    # ------------------------------------------------------------------ #
    def _rescale(self, render=True, overlay=True):
        """Re-fits the current frame to the widget and rebuilds the overlay
        for the current index. Cheap-guarded so the many spurious early
        <Configure> events (and the deferred call above) are no-ops until
        there's both a frame and a real size. `render=False` skips the push
        to the label; `overlay=False` skips the (full-supersample, ~12ms)
        overlay rebuild — both used by `_step`, which shows a slide instead
        and lets `_slide_step` rebuild the overlay per tick."""
        if not self._frames:
            return
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1 or h <= 1:
            return

        frame = self._frames[self._index]
        iw, ih = frame.size
        if iw == 0 or ih == 0:
            return

        scale = min((w - 8) / iw, (h - 8) / ih)
        nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))

        self._base_scaled = frame.convert("RGB").resize((nw, nh), Image.LANCZOS)
        self._rendered_size = (nw, nh)
        if overlay:
            self._overlay = self._build_overlay(nw, nh)
        if render:
            self._update_image()

    def _build_overlay(self, w, h, dot_t=1.0, ss=_OVERLAY_SS):
        """The chevrons + dot indicators for the current index as a standalone
        RGBA layer (transparent everywhere else) — never composited into a
        frame, just laid on at paint time by `_push`. Rebuilt on an index /
        size / theme change, and once per tick during a slide (`_slide_step`)
        so the dot row can animate. `dot_t` < 1 draws the row partway through
        its re-flow from `_dot_anim`'s stored previous state to the current
        one; the chevrons are unaffected by it (they never move).

        Drawn at `ss`x and box-filtered down for antialiasing — the downscale
        runs in premultiplied-alpha space (`RGBa`), without which LANCZOS
        bleeds the transparent border's black RGB into the edge pixels as a
        grey fringe."""
        bw, bh = w * ss, h * ss
        overlay = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        if len(self._frames) > 1:
            draw = ImageDraw.Draw(overlay)
            self._draw_dots(draw, w, h, self._dot_anim, dot_t, ss)
            # Only the chevron that leads somewhere is drawn (clamped at both
            # ends); positions come from _disc_centers so the click hit-test
            # uses the exact same geometry (in unscaled coords).
            left, right, disc_r = self._disc_centers(w, h)
            if left is not None:
                self._draw_chevron(draw, left[0] * ss, left[1] * ss, disc_r * ss, "left")
            if right is not None:
                self._draw_chevron(draw, right[0] * ss, right[1] * ss, disc_r * ss, "right")
        if ss != 1:
            overlay = overlay.convert("RGBa").resize((w, h), Image.LANCZOS).convert("RGBA")
        return overlay

    def _disc_centers(self, w, h):
        """`(left_center, right_center, radius)` for the chevron discs at the
        current index, in image-local pixels — `None` for a chevron that
        isn't drawn (index 0 has no left, the last index no right).

        The disc is sized from the frame's own dimensions and sits flush
        against its edge, so it stays fully visible whatever the aspect ratio
        (a fixed fractional inset clipped it on letterboxed / narrow frames).
        This is the single source of truth for both the drawing and the
        click hit-test."""
        if w <= 0 or h <= 0:
            return None, None, 0.0
        disc_r = max(14.0, min(w, h) * 0.12)
        disc_r = min(disc_r, w * 0.16, h * 0.42)
        margin = max(4.0, disc_r * 0.14)
        cy = h / 2
        last = len(self._frames) - 1
        left = (margin + disc_r, cy) if self._index > 0 else None
        right = (w - margin - disc_r, cy) if self._index < last else None
        return left, right, disc_r

    def _dot_geometry(self, w, h, dot_start, s=1.0):
        """`({frame_index: (cx, radius)}, cy)` for the dot row anchored with
        `dot_start` in the leftmost of the three large centre slots. `w`, `h`
        are unscaled; every coordinate and radius comes back multiplied by `s`
        (the overlay supersample factor).

        The cluster's midpoint is pinned to the frame's horizontal centre, so
        the three large slots always sit at the same x (w/2-gap, w/2, w/2+gap)
        whatever the index — that's what lets the highlight visibly move
        *between* them. Dots outside the cluster taper medium (one out) then
        small (two out); only frames that actually exist get one, which is why
        the row is five wide at the ends and seven in the middle."""
        n = len(self._frames)
        cluster_lo, cluster_hi = dot_start, dot_start + _DOT_CLUSTER - 1
        lo = max(0, cluster_lo - _DOT_LOOK)
        hi = min(n - 1, cluster_hi + _DOT_LOOK)
        cluster_mid = dot_start + (_DOT_CLUSTER - 1) / 2
        cy = (h - 18) * s
        geo = {}
        for f in range(lo, hi + 1):
            dist = (cluster_lo - f if f < cluster_lo
                    else f - cluster_hi if f > cluster_hi else 0)
            r = (_DOT_R_LARGE if dist == 0
                 else _DOT_R_MED if dist == 1 else _DOT_R_SMALL)
            geo[f] = ((w / 2 + (f - cluster_mid) * _DOT_GAP) * s, r * s)
        return geo, cy

    def _draw_dots(self, draw, w, h, anim=None, t=1.0, s=1.0):
        """The position-dot row (`w`, `h` unscaled; `s` = overlay supersample
        factor). With `anim` = `(prev_start, prev_index)` and `t` < 1, every
        dot is drawn partway between its old and new (x, radius): dots entering
        the row grow from r=0, dots leaving shrink to it, and the white
        highlight cross-fades from the old current-frame dot to the new one.
        `_slide_step` drives `t` on the picture slide's own eased clock, so
        dots and image settle together. At `t` >= 1 (or no `anim`) it's just
        the settled row for the current index."""
        geo_b, cy = self._dot_geometry(w, h, self._dot_start, s)
        if anim is None or t >= 1.0:
            for f, (cx, r) in geo_b.items():
                fill = _DOT_ON_RGBA if f == self._index else _DOT_OFF_RGBA
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
            return

        prev_start, prev_index = anim
        geo_a, _ = self._dot_geometry(w, h, prev_start, s)
        for f in set(geo_a) | set(geo_b):
            a, b = geo_a.get(f), geo_b.get(f)
            if a and b:
                cx = a[0] + (b[0] - a[0]) * t
                r = a[1] + (b[1] - a[1]) * t
            elif b:                       # entering on the leading edge
                cx, r = b[0], b[1] * t
            else:                         # leaving off the trailing edge
                cx, r = a[0], a[1] * (1 - t)
            if f == self._index == prev_index:
                fill = _DOT_ON_RGBA
            elif f == self._index:
                fill = self._blend_rgba(_DOT_OFF_RGBA, _DOT_ON_RGBA, t)
            elif f == prev_index:
                fill = self._blend_rgba(_DOT_ON_RGBA, _DOT_OFF_RGBA, t)
            else:
                fill = _DOT_OFF_RGBA
            if r > 0.05:
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)

    @staticmethod
    def _blend_rgba(c0, c1, t):
        """Linear blend between two RGBA tuples."""
        return tuple(round(v0 + (v1 - v0) * t) for v0, v1 in zip(c0, c1))

    def _draw_chevron(self, draw, cx, cy, disc_r, direction):
        """A primary-colour disc with a contrasting chevron. `cx`, `cy` and
        `disc_r` arrive already in overlay-supersampled pixels.

        The chevron is nudged ~a fifth of its half-width toward the point: its
        two arm-ends carry more visual weight than the single tip, so a
        geometrically centred V reads as shifted toward its opening. (The disc
        edge / hit-test still use the true centre from `_disc_centers`.)"""
        draw.ellipse(
            [cx - disc_r, cy - disc_r, cx + disc_r, cy + disc_r],
            fill=self._disc_rgba,
        )
        half_w = disc_r * 0.38
        half_h = disc_r * 0.45
        point = 1 if direction == "right" else -1
        ox = point * half_w * 0.13          # shift toward the tip
        tip = (cx + ox + point * half_w, cy)
        back_top = (cx + ox - point * half_w, cy - half_h)
        back_bot = (cx + ox - point * half_w, cy + half_h)
        draw.line(
            [back_top, tip, back_bot],
            fill=self._arrow_rgba, width=max(2, round(disc_r * 0.135)),
            joint="curve",
        )

    @staticmethod
    def _hex_to_rgb(value):
        value = value.lstrip("#")
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))

    def _push(self, base):
        """Put `base` (a pure RGB frame — a whole frame at rest, a crop of
        the strip mid-slide) on the label, with `_overlay` composited on top
        at its current fade level. The overlay is a fixed layer: it does not
        move when `base` does, so a slide reads as the picture scrolling
        under stationary buttons. `base` is remembered as `_displayed_base`
        so the next slide can start from it."""
        self._displayed_base = base
        alpha = min(1.0, max(0.0, self._arrow_alpha))
        if alpha <= 0.01 or self._overlay is None or base.size != self._overlay.size:
            disp = base
        else:
            full = Image.alpha_composite(base.convert("RGBA"), self._overlay).convert("RGB")
            disp = full if alpha >= 0.99 else Image.blend(base, full, alpha)
        self._ctk_img = ctk.CTkImage(light_image=disp, dark_image=disp, size=self._rendered_size)
        self.img_label.configure(image=self._ctk_img)

    def _update_image(self):
        """Repaints the resting frame (`_base_scaled`) at the current fade."""
        if self._base_scaled is not None:
            self._push(self._base_scaled)

    # ------------------------------------------------------------------ #
    #  Animation (fade + slide share one job channel)
    # ------------------------------------------------------------------ #
    def _cancel_anim(self):
        """Cancels any in-flight fade or slide. A slide cut short this way also
        gets its dot row settled — the overlay's last rebuild was at some
        `dot_t` < 1, so leave it and the dots freeze mid-flow."""
        for attr in ("_fade_job", "_anim_job"):
            job = getattr(self, attr)
            if job is not None:
                self.after_cancel(job)
                setattr(self, attr, None)
        self._slide = None
        if self._dot_anim is not None:
            self._dot_anim = None
            if self._frames and self._rendered_size[0] > 0:
                self._overlay = self._build_overlay(*self._rendered_size)

    def _fade_to(self, target):
        """Steps `_arrow_alpha` toward `target` over up to _FADE_STEPS ticks,
        cancelling any animation already in flight (single-job pattern, like
        the tab indicator)."""
        self._cancel_anim()
        self._fade_step(target)

    def _fade_step(self, target):
        increment = 1.0 / _FADE_STEPS
        if abs(target - self._arrow_alpha) <= increment + 1e-6:
            self._arrow_alpha = target
            self._update_image()
            return
        self._arrow_alpha += increment if target > self._arrow_alpha else -increment
        self._update_image()
        self._fade_job = self.after(_FADE_INTERVAL_MS, lambda: self._fade_step(target))

    def _animate_slide(self, direction, from_base, to_base, dot_anim=None):
        """Slides the *picture*: a window crops across a `[current | next]`
        strip of pure frames (order flipped for a backward step). `_push`
        drops the `_overlay` on every tick; the chevrons in it stay put while
        the image scrolls, and the dot row re-flows if `dot_anim` (a
        `(prev_start, prev_index)` pair) is given. `direction` is +1 forward
        (content exits left), -1 back. Restarts cleanly mid-slide — the caller
        passes the currently-shown pure frame as `from_base`."""
        self._cancel_anim()
        self._dot_anim = dot_anim   # set after _cancel_anim, which clears it
        w, h = to_base.size
        strip = Image.new("RGB", (w * 2, h))
        if direction > 0:
            strip.paste(from_base, (0, 0))
            strip.paste(to_base, (w, 0))
            x0, x1 = 0, w
        else:
            strip.paste(to_base, (0, 0))
            strip.paste(from_base, (w, 0))
            x0, x1 = w, 0
        self._slide = (strip, w, h, x0, x1)
        self._slide_step(1)

    def _slide_step(self, i):
        if self._slide is None:   # cancelled between schedule and fire
            return
        strip, w, h, x0, x1 = self._slide
        eased = 1 - (1 - i / _SLIDE_STEPS) ** 3   # ease-out, shared by both layers
        x = round(x0 + (x1 - x0) * eased)
        if self._dot_anim is not None:
            # lighter supersample per tick — softness mid-motion is invisible
            self._overlay = self._build_overlay(w, h, dot_t=eased, ss=_OVERLAY_SS_ANIM)
        self._push(strip.crop((x, 0, x + w, h)))
        if i < _SLIDE_STEPS:
            self._anim_job = self.after(_SLIDE_INTERVAL_MS, lambda: self._slide_step(i + 1))
        else:
            self._anim_job = None
            self._slide = None
            self._dot_anim = None
            self._overlay = self._build_overlay(w, h)   # settle at full supersample
            self._update_image()

    # ------------------------------------------------------------------ #
    #  Events
    # ------------------------------------------------------------------ #
    def _on_configure(self, event):
        if (event.width, event.height) == self._last_config:
            return
        self._last_config = (event.width, event.height)
        self._cancel_anim()
        self._rescale()

    def _on_enter(self, _event):
        if len(self._frames) > 1:
            self._fade_to(1.0)

    def _on_leave(self, _event):
        self._fade_to(0.0)

    def _event_image_xy(self, event):
        """The event's position in image-local pixels, or `None` before the
        first render.

        Screen coords (`x_root`/`y_root`) on purpose: `CTkLabel.bind()` binds
        both the inner `tk.Label` and the inner canvas, and the two report
        `event.x`/`.y` in different origins (image-local on the image,
        frame-local on the letterbox). Screen coords are unambiguous. The
        image is centred in `img_label`."""
        w, h = self._rendered_size
        if w <= 0:
            return None
        img_x = self.img_label.winfo_rootx() + (self.img_label.winfo_width() - w) / 2
        img_y = self.img_label.winfo_rooty() + (self.img_label.winfo_height() - h) / 2
        return event.x_root - img_x, event.y_root - img_y

    def _hit_disc_at(self, x, y):
        """Which chevron disc (`"left"`/`"right"`/`None`) the image-local
        point `(x, y)` is on. The whole disc box counts, not one half."""
        w, h = self._rendered_size
        left, right, radius = self._disc_centers(w, h)
        for name, center in (("left", left), ("right", right)):
            if center is not None:
                if abs(x - center[0]) <= radius and abs(y - center[1]) <= radius:
                    return name
        return None

    def _in_chevron_band(self, x, w):
        """True if `x` is within the left/right edge strip the chevrons live
        in — whether or not a disc is actually drawn there right now. A click
        here is never treated as a frame double-click, so spamming a chevron
        past the last preview (where its disc has vanished) won't pop the
        file dialog."""
        _, _, radius = self._disc_centers(w, self._rendered_size[1])
        reach = radius * 2.0 + 16.0
        return x < reach or x > w - reach

    def _handle_press(self, event, repeat):
        """One press of a click burst. `repeat` is False for the first press
        (`<Button-1>`) and True for every one after it — Tk sends only
        `<Double-Button-1>` for the 2nd, 3rd, … so both bindings route here
        and every press counts.

        On a chevron disc → step (always, so a spam-click runs to the end).
        In the chevron's edge strip but not on the disc → nothing. In the
        central area → a repeat press reselects the input file, but only if
        the press before it was also central (so one stray click mid-spam is
        harmless, while a deliberate double-click on the frame still works)."""
        xy = self._event_image_xy(event) if len(self._frames) > 1 else None
        if xy is not None:
            x, y = xy
            w = self._rendered_size[0]
            hit = self._hit_disc_at(x, y)
            if hit == "left":
                self._step(-1)
                self._prev_press_central = False
                return
            if hit == "right":
                self._step(1)
                self._prev_press_central = False
                return
            central = not self._in_chevron_band(x, w)
        else:
            central = False

        if central and repeat and self._prev_press_central and self._on_reselect:
            self._on_reselect()
        self._prev_press_central = central

    def _step(self, delta):
        """Moves `delta` previews (clamped) with a slide transition from
        whatever's currently on screen, re-flowing the dot row to match."""
        if not self._frames:
            return
        new_index = max(0, min(len(self._frames) - 1, self._index + delta))
        if new_index == self._index:
            return
        direction = 1 if new_index > self._index else -1
        from_base = self._displayed_base
        prev_index, prev_start = self._index, self._dot_start
        self._index = new_index
        if self._on_index is not None:
            self._on_index(new_index)   # mirror the scrub onto the other tab
        self._dot_start = self._resolve_dot_start(new_index, delta, prev_index, prev_start)
        self._arrow_alpha = 1.0   # pointer is over the preview
        self._rescale(render=False, overlay=False)   # _base_scaled only; slide rebuilds _overlay
        if (from_base is None or self._base_scaled is None
                or from_base.size != self._base_scaled.size):
            self._dot_anim = None
            self._overlay = self._build_overlay(*self._rendered_size)
            self._update_image()
            return
        self._animate_slide(direction, from_base, self._base_scaled,
                            dot_anim=(prev_start, prev_index))

    def _resolve_dot_start(self, new_index, delta, prev_index, prev_start):
        """Where the leftmost large dot lands after a step. A single step nudges
        the highlight one slot toward the edge it's heading for (the right
        large slot when advancing, the left one when retreating) and only
        scrolls the row once the highlight is already sitting at that edge —
        so a direction change walks back through the middle slot with the row
        held still. A multi-step jump snaps straight to the target edge. The
        result is clamped so the row always has three large dots and the
        highlight stays inside them."""
        n = len(self._frames)
        hi_start = max(0, n - _DOT_CLUSTER)
        cluster = prev_index - prev_start          # 0 .. _DOT_CLUSTER - 1
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
        """`_dot_start` placing `index` as near the middle large slot as the
        ends allow — the neutral choice for a jump with no direction (an
        external `sync_index`), vs `_resolve_dot_start`'s directional
        hysteresis."""
        n = len(self._frames)
        lo = max(0, index - (_DOT_CLUSTER - 1))
        hi = min(max(0, n - _DOT_CLUSTER), index)
        return max(lo, min(index - (_DOT_CLUSTER - 1) // 2, hi))

    def sync_index(self, index):
        """Jump to preview `index` with no slide — used to mirror the other
        tab's carousel position (LlamaGUI.sync_preview_index) and to restore
        the scrub position after a theme rebuild. No-op if already there, out
        of range, or not yet populated. Never re-fires `on_index`."""
        if (not self._frames or index == self._index
                or not 0 <= index < len(self._frames)):
            return
        self._cancel_anim()
        self._index = index
        self._dot_start = self._centered_dot_start(index)
        self._arrow_alpha = 0.0
        self._rescale()
