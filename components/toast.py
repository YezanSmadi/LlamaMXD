import tkinter

import customtkinter as ctk

from core.theme import get_active_theme

_TOAST_WIDTH = 260
_TOAST_HEIGHT = 44
_INSET = 12          # gap from the tab frame's top-right corner
_STACK_GAP = 6       # vertical gap between simultaneously-visible toasts
_MAX_VISIBLE = 3     # a 4th arrival retires the oldest immediately
_CORNER = 10
_PAD = 14            # left/right text inset

# Colour-key for Windows layered-window transparency: every pixel of this
# exact colour is punched out of the toast entirely. Nothing else in the app
# uses it, and no theme's palette contains it.
_TRANSPARENT_KEY = "#FF00FE"

_SLIDE_STEPS = 10
_SLIDE_INTERVAL_MS = 20
_HOLD_MS = 2200
_FADE_STEPS = 20
_FADE_INTERVAL_MS = 35
_RETIRE_STEPS = 8      # the fast fade used when a toast is pushed out early
_RETIRE_INTERVAL_MS = 25


class Toast(tkinter.Toplevel):
    """A transient notification that drops in from above the tab frame's
    top-right corner, holds, then fades out and destroys itself. Clicking it
    runs `on_click` and dismisses it immediately.

    **It's a borderless Toplevel, not a frame inside the main window, and that
    is what makes the rounded corners real.** Tk has no per-pixel transparency
    for an in-window widget: a rounded `CTkFrame` still has to paint
    *something* in the four corner nooks outside its rounded shape, and
    whatever flat colour you choose is only invisible where it happens to
    match. As a child of the main window this meant grey corner squares
    wherever a toast overlapped a queue row or a thumbnail instead of bare
    tab background.

    A Toplevel can do better on Windows: `-transparentcolor` punches every
    pixel of `_TRANSPARENT_KEY` clean out of the window, so anything painted
    in that key leaves genuinely nothing behind — real rounded edges over
    arbitrary content.

    **The body is drawn on a raw `tkinter.Canvas`, not a rounded `CTkFrame`,
    and that part is not optional.** A colour key only punches pixels that
    match it *exactly*, and CTk anti-aliases its rounded corners against
    `bg_color` — those blend pixels sit between the fill and the key, match
    neither, and survive as a visible magenta fringe around every corner. Tk's
    canvas primitives don't anti-alias, so drawing the rounded rectangle by
    hand (a plus-shaped pair of rectangles plus four quarter-circle pieslices,
    same construction the queue's progress fill uses) leaves every pixel
    either exactly the fill or exactly the key. The trade is slightly
    stair-stepped corners; the alternative was coloured fringing.

    The same layering also gets the fade for free: `-alpha` on the whole
    window replaces the old colour-interpolation trick, which had to blend
    toward an assumed backdrop (wrong for the same reason the corners were)
    and cost a full CTk redraw per step. Both attributes apply together."""

    def __init__(self, manager, app, message, on_click=None):
        super().__init__(master=app)
        theme = get_active_theme()
        self.manager = manager
        self.app = app
        self._on_click = on_click
        self._jobs = []           # every pending after() id, so dismiss can cancel them
        self._dismissed = False
        self._retiring = False
        self._x = 0
        self._rest_y = 0

        self.overrideredirect(True)   # no titlebar, no taskbar entry, takes no focus
        self.configure(bg=_TRANSPARENT_KEY)
        self.attributes("-transparentcolor", _TRANSPARENT_KEY)
        # Without topmost the main window rises above the toast the moment the
        # user clicks anything — including the very button that posted it.
        self.attributes("-topmost", True)
        self.geometry(f"{_TOAST_WIDTH}x{_TOAST_HEIGHT}+0+0")

        self.canvas = tkinter.Canvas(
            master=self, width=_TOAST_WIDTH, height=_TOAST_HEIGHT,
            bg=_TRANSPARENT_KEY, highlightthickness=0, bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self._draw_body(theme["primary"])
        self.canvas.create_text(
            _PAD, _TOAST_HEIGHT // 2, anchor="w", text=message,
            fill=theme["primary_text"], font=self._label_font(),
            width=_TOAST_WIDTH - 2 * _PAD,
        )
        self.canvas.configure(cursor="hand2")
        self.canvas.bind("<Button-1>", lambda e: self._clicked())

    @staticmethod
    def _label_font():
        """The same family/size CTk's own labels render at. CTk stores the size
        as a positive number but applies it to widgets as a NEGATIVE Tk size
        (pixels, not points) — passing the positive value straight to a canvas
        would render noticeably larger than every other label in the app."""
        config = ctk.ThemeManager.theme.get("CTkFont", {})
        return config.get("family", "Roboto"), -abs(config.get("size", 13))

    def _draw_body(self, color):
        """Paints an aliased rounded rectangle filling the whole toast: two
        overlapping rectangles forming a plus, then a quarter-circle pieslice
        in each corner. Everything the shape doesn't cover stays the colour
        key, i.e. punched out."""
        w, h, r = _TOAST_WIDTH, _TOAST_HEIGHT, _CORNER
        self.canvas.create_rectangle(r, 0, w - r, h, fill=color, outline=color)
        self.canvas.create_rectangle(0, r, w, h - r, fill=color, outline=color)
        for x0, y0, start in (
            (0, 0, 90),                  # top-left
            (w - 2 * r, 0, 0),           # top-right
            (0, h - 2 * r, 180),         # bottom-left
            (w - 2 * r, h - 2 * r, 270),  # bottom-right
        ):
            self.canvas.create_arc(
                x0, y0, x0 + 2 * r, y0 + 2 * r, start=start, extent=90,
                style="pieslice", fill=color, outline=color,
            )

    # ------------------------------------------------------------------ #
    #  Animation
    # ------------------------------------------------------------------ #
    def start(self, x, rest_y):
        """Slides the toast down to `rest_y`. Coordinates are SCREEN coords —
        this is its own window, not a child placed in the main one."""
        self._x, self._rest_y = x, rest_y
        self._slide(0)

    def move_to(self, rest_y):
        """Repositions an already-resting toast (used when an earlier one dies
        and the stack closes up). Snaps rather than animating — one more timer
        chain per survivor is exactly the cost this class avoids."""
        self._rest_y = rest_y
        if not self._dismissed:
            self.geometry(f"{_TOAST_WIDTH}x{_TOAST_HEIGHT}+{self._x}+{rest_y}")

    def reposition(self, x, rest_y):
        """Re-anchors to new screen coords — the manager calls this when the
        main window is dragged, since a separate window doesn't follow it."""
        self._x = x
        self.move_to(rest_y)

    def _slide(self, step):
        if self._dismissed:
            return
        fraction = step / _SLIDE_STEPS
        # Ease-out so it decelerates into place rather than stopping dead.
        eased = 1 - (1 - fraction) ** 3
        start_y = self._rest_y - _TOAST_HEIGHT - _INSET
        y = round(start_y + (self._rest_y - start_y) * eased)
        self.geometry(f"{_TOAST_WIDTH}x{_TOAST_HEIGHT}+{self._x}+{y}")
        if step < _SLIDE_STEPS:
            self._after(_SLIDE_INTERVAL_MS, lambda: self._slide(step + 1))
        else:
            self._after(_HOLD_MS, lambda: self._fade(0, _FADE_STEPS, _FADE_INTERVAL_MS))

    def retire(self):
        """Cuts straight to a fast fade, skipping any remaining hold — used
        when a newer toast pushes this one past the on-screen limit. Marked
        `_retiring` so it stops claiming a stack slot immediately, even though
        it's still visible for the length of the fade."""
        if self._dismissed or self._retiring:
            return
        self._retiring = True
        self._cancel_jobs()
        self._fade(0, _RETIRE_STEPS, _RETIRE_INTERVAL_MS)

    def _fade(self, step, total_steps, interval):
        if self._dismissed:
            return
        # One window attribute per step, no widget redraw at all.
        self.attributes("-alpha", max(0.0, 1.0 - step / total_steps))
        if step < total_steps:
            self._after(interval, lambda: self._fade(step + 1, total_steps, interval))
        else:
            self.dismiss()

    # ------------------------------------------------------------------ #
    #  Lifecycle
    # ------------------------------------------------------------------ #
    def _after(self, delay, callback):
        self._jobs.append(self.after(delay, callback))

    def _cancel_jobs(self):
        for job in self._jobs:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        self._jobs.clear()

    def _clicked(self):
        callback = self._on_click
        self.dismiss()
        if callback:
            callback()

    def dismiss(self):
        """Cancels any in-flight animation step and removes the toast. Safe to
        call twice (a click landing during the fade would otherwise re-enter)."""
        if self._dismissed:
            return
        self._dismissed = True
        self._cancel_jobs()
        self.manager.forget(self)
        self.destroy()

    @property
    def is_retiring(self):
        """True once this toast has been pushed out and is only finishing its
        fade — it no longer occupies a slot in the stack."""
        return self._retiring


class ToastManager:
    """Owns the live toasts for a window, keeps them from overlapping, and —
    importantly — bounds how much animation work can be in flight at once.

    **Why the cap matters.** Every toast runs its own `after()` chain, so an
    uncapped stack turned button-mashing into dozens of concurrent timer
    chains competing with the UI thread — which showed up as tab switches
    lagging. At most `_MAX_VISIBLE` toasts hold a slot; a further arrival
    immediately `retire()`s the oldest into a fast fade, so the work in flight
    stays roughly constant no matter how hard the triggering button is
    spammed."""

    def __init__(self, app):
        self.app = app
        self._toasts = []
        # Toasts are separate windows, so they don't move with the main one and
        # don't hide when it's minimized — both have to be wired up by hand.
        # Guarded on event.widget because a toplevel binding also receives its
        # descendants' <Configure> events, which fire constantly.
        app.bind("<Configure>", self._on_app_configure, add="+")
        app.bind("<Unmap>", self._on_app_unmap, add="+")

    def show(self, message, on_click=None):
        """Drops a new toast in at the current tab frame's top-right corner."""
        tab = self._current_tab()
        if tab is None:
            return None

        # Push the oldest slot-holder out before adding, so the visible count
        # never exceeds the cap (the retiring one keeps its position and fades
        # out where it stands rather than making everything below it jump).
        active = [t for t in self._toasts if not t.is_retiring]
        while len(active) >= _MAX_VISIBLE:
            active.pop(0).retire()

        # update_idletasks() forces a full synchronous layout pass, so it's
        # only worth paying when the frame genuinely hasn't been laid out yet.
        if tab.winfo_width() <= 1:
            self.app.update_idletasks()

        toast = Toast(self, self.app, message, on_click=on_click)
        self._toasts.append(toast)
        toast.start(self._slot_x(tab), self._slot_y(tab, len(active)))
        return toast

    def _current_tab(self):
        return self.app.tabs.get(self.app._current_tab_name)

    def _slot_x(self, tab):
        """Screen x — toasts hang off the tab frame's right edge, inset."""
        return tab.winfo_rootx() + tab.winfo_width() - _TOAST_WIDTH - _INSET

    def _slot_y(self, tab, index):
        """Screen y for the `index`-th slot down the stack."""
        return tab.winfo_rooty() + _INSET + index * (_TOAST_HEIGHT + _STACK_GAP)

    def forget(self, toast):
        """Called by a toast as it destroys itself; closes the gap it leaves."""
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._relayout()

    def _relayout(self):
        """Re-seats the surviving slot-holders so a dismissed toast doesn't
        leave a hole in the stack. Retiring toasts are skipped — they're mid
        fade-out and stay where they are."""
        tab = self._current_tab()
        if tab is None:
            return
        index = 0
        for toast in self._toasts:
            if toast.is_retiring:
                continue
            toast.reposition(self._slot_x(tab), self._slot_y(tab, index))
            index += 1

    def _on_app_configure(self, event):
        """Keeps toasts glued to the window when it's dragged."""
        if event.widget is self.app and self._toasts:
            self._relayout()

    def _on_app_unmap(self, event):
        """Minimizing the app must take its toasts with it — they're topmost
        windows and would otherwise be left floating over the desktop."""
        if event.widget is self.app:
            self.clear()

    def clear(self):
        """Drops every live toast — used on a theme rebuild, which destroys
        the tab frames these are positioned against, and on minimize."""
        for toast in list(self._toasts):
            toast.dismiss()
