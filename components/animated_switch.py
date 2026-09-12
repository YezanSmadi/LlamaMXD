import customtkinter as ctk

# Knob-slide animation for CTkSwitch, which otherwise snaps between states.
# Short + cheap: each tick is one draw-engine reposition of the existing
# canvas polygon, not a full redraw.
_STEPS = 8
_INTERVAL_MS = 12


class AnimatedSwitch(ctk.CTkSwitch):
    """A `CTkSwitch` whose knob slides between off and on instead of jumping.

    CTkSwitch positions its knob straight from the boolean `_check_state`.
    This keeps a parallel float `_anim_value` (0 = off, 1 = on), eases it
    toward the new state over a few ticks on every `set()` — which is what
    `toggle` / `select` / `deselect` / a bound variable all route through —
    and feeds *that* to the draw engine's `slider_value`, which already takes
    a float. No drawing code is reimplemented: colours, the disabled look,
    hover, the label and `get()` are the stock widget untouched.

    Reaches into `_draw_engine` / `_draw` (private CTk API), the same tack as
    `ThemedDropdown`; `customtkinter` is version-pinned (see CLAUDE.md)."""

    def __init__(self, *args, **kwargs):
        # Both must exist before super().__init__ — it calls self._draw().
        self._anim_value = 0.0
        self._anim_job = None
        super().__init__(*args, **kwargs)
        self._anim_value = 1.0 if self._check_state else 0.0
        self._position_knob()

    def set(self, state, from_variable_callback=False):
        """Snap the widget's own state + colours to `state` (super's job),
        then start the knob easing toward the matching end."""
        super().set(state, from_variable_callback)
        self._ease_to(1.0 if self._check_state else 0.0)

    def _draw(self, no_color_updates=False):
        """CTk redraws (resize, appearance mode, a colour change, *or a hover
        state change* — `_on_enter`/`_on_leave` both call this) re-snap the
        knob to 0/1 from `_check_state`. Put it straight back wherever the
        animation actually has it — unconditionally, not just when no tick is
        in flight.

        This used to skip the correction while `_anim_job` was set, on the
        theory that the next queued tick would fix it anyway — but a redraw
        can land *between* ticks (a stray hover during the ease, a tooltip,
        anything that touches `_draw`), and for that one frame the knob would
        visibly snap to the final position before the next tick pulled it
        back: the reported jiggle. Reapplying every time is cheap (one
        draw-engine `coords()` call, not a redraw) so there's no reason to
        skip it."""
        super()._draw(no_color_updates)
        self._position_knob()

    # ------------------------------------------------------------------ #
    #  Animation
    # ------------------------------------------------------------------ #
    def _ease_to(self, target):
        if self._anim_job is not None:
            self.after_cancel(self._anim_job)
            self._anim_job = None
        if abs(target - self._anim_value) < 1e-3:
            self._anim_value = target
            self._position_knob()
            return
        self._tick(self._anim_value, target, 1)

    def _tick(self, start, target, i):
        eased = 1 - (1 - i / _STEPS) ** 3          # ease-out, matches the carousel
        self._anim_value = start + (target - start) * eased
        self._position_knob()
        if i < _STEPS:
            self._anim_job = self.after(_INTERVAL_MS, lambda: self._tick(start, target, i + 1))
        else:
            self._anim_value = target
            self._anim_job = None
            self._position_knob()

    def _position_knob(self):
        """Re-run just the slider geometry at the current fractional value.
        The draw-engine call reuses the canvas items it created on the first
        pass (`coords()` after that) and leaves their fill colours — already
        set for the destination state by `super().set()`'s `_draw` — alone."""
        if not self._canvas.winfo_exists():
            return
        s = self._apply_widget_scaling
        self._draw_engine.draw_rounded_slider_with_border_and_button(
            s(self._switch_width), s(self._switch_height), s(self._corner_radius),
            s(self._border_width), s(self._button_length), s(self._corner_radius),
            self._anim_value, "w",
        )

    def destroy(self):
        if self._anim_job is not None:
            self.after_cancel(self._anim_job)
            self._anim_job = None
        super().destroy()
