import tkinter as tk

import customtkinter as ctk

_ROW_HEIGHT = 28
_PANEL_CORNER = 6
_PANEL_GAP = 3  # vertical gap between the button and the panel below it

# Open/close animation: the popup window unrolls (its height grows from ~0 to
# full while the panel inside stays full-size and is clipped) and fades in
# together. Close runs the same in reverse, shorter, then withdraws.
_ANIM_OPEN_STEPS = 9
_ANIM_CLOSE_STEPS = 6
_ANIM_INTERVAL_MS = 12
_ANIM_MIN_ALPHA = 0.25   # popup starts this visible, not fully transparent


class ThemedDropdown(ctk.CTkOptionMenu):
    """A `CTkOptionMenu` whose popup is a custom panel instead of Tk's native
    menu — every dropdown in the app uses this so they all look and behave
    identically.

    Two things the native popup can't do, which is why this exists:

    1. **It stays open until an explicit dismissal** — a click on the button
       again, or a click anywhere outside the panel. Moving the pointer off it
       does nothing. The native menu is a grab-holding popup that closes on
       almost any pointer event.
    2. **Rows can report hover** (`on_hover`), which the Settings tab's theme
       picker needs to live-preview a palette. The native popup is modal on
       Windows and repaints nothing behind it, so a hover preview is invisible
       there.

    **The panel is a borderless `Toplevel` of its own** (`self._popup`),
    withdrawn until `open()`. It used to be a `CTkFrame` `place()`d over the
    main window, which meant a dropdown near the window's short bottom edge
    (Encoding's Encoder/Format/Profile/Level row, Muxing's Output Format) had
    its lower entries clipped by the window. A separate window can extend past
    that edge instead. The trade-off is a window that isn't torn down with the
    tab that owns the dropdown — hence the `destroy()` override — and doesn't
    move with the main window, so `open()` also drops the panel on any main-
    window `<Configure>` / `<Unmap>`.

    **Open/close is animated** (`_anim`): the popup unrolls — its window height
    grows from ~0 to full while `self.panel` sits at full size, placed at
    `(0, 0)` and clipped by the shorter window — and its `-alpha` fades in at
    the same time (ease-out). Close is the same reversed, fewer steps, then
    `withdraw()`. One `after` job (`self._anim_job`), cancelled by every
    `open`/`close`/`destroy` so spam-clicking can't leave it stuck."""

    def __init__(self, master, values, command=None, on_hover=None, **kwargs):
        # `command` is deliberately NOT handed to the base class: its own
        # value-picking path (the native menu) never runs, so we invoke the
        # caller's callback ourselves from _select.
        super().__init__(master=master, values=list(values), **kwargs)
        self._values = list(values)
        self._user_command = command
        self._on_hover = on_hover
        self._is_open = False
        self._global_binds = []  # (sequence, funcid) pairs on the main toplevel
        self._anim_job = None
        self._geo = None         # (w, h, x, y) of the fully-open popup
        self.rows = {}  # value -> row CTkButton, exposed for per-row styling

        # Borderless popup window holding the panel. Withdraw first thing so it
        # never flashes onscreen at its default position.
        self._popup = tk.Toplevel(self)
        self._popup.withdraw()
        self._popup.overrideredirect(True)
        try:
            self._popup.transient(self.winfo_toplevel())
        except tk.TclError:
            pass

        # place() (not pack) at full width + natural height so that when the
        # window is shorter than the panel — every animation frame — the panel
        # is *clipped*, not compressed. relwidth (relative) is fine here; it's
        # the absolute width=/height= on place() that CTk rejects (see CLAUDE.md).
        self.panel = ctk.CTkFrame(
            master=self._popup, corner_radius=_PANEL_CORNER,
            border_width=1, border_color=("gray70", "gray30"),
        )
        self.panel.place(x=0, y=0, relwidth=1.0)
        for value in self._values:
            row = ctk.CTkButton(
                master=self.panel,
                text=value,
                anchor="w",
                height=_ROW_HEIGHT,
                corner_radius=4,
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                command=lambda v=value: self._select(v),
            )
            row.pack(fill="x", padx=3, pady=1)
            if on_hover is not None:
                row.bind("<Enter>", lambda e, v=value: on_hover(v))
            self.rows[value] = row

        # Redirect the button's click away from the native popup.
        self._open_dropdown_menu = self._toggle

    # ------------------------------------------------------------------ #
    #  Open / close
    # ------------------------------------------------------------------ #
    def _toggle(self):
        if self._is_open:
            self.close()
        else:
            self.open()

    def open(self):
        """Shows the popup straight below the button, matching its width, and
        unrolls it open.

        Always downward, never shifted or flipped (both were tried and removed
        on request); entries past the main window's bottom edge overflow it
        because the popup is a window of its own."""
        if self._is_open or not self.winfo_exists():
            return
        self._is_open = True
        self._cancel_anim()

        w = self.winfo_width()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + _PANEL_GAP
        # Size to full width (still transparent + withdrawn) so the rows lay
        # out at their final width before we measure the panel's height.
        self._popup.geometry(f"{w}x400+{x}+{y}")
        try:
            self._popup.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        self._popup.deiconify()
        self._popup.update_idletasks()
        h = self.panel.winfo_reqheight()
        if h <= 1:  # not laid out yet — fall back to a computed estimate
            h = len(self._values) * (_ROW_HEIGHT + 2) + 4
        self._geo = (w, h, x, y)

        # Match the popup's own bg to the panel's fill so the CTkFrame's
        # rounded-corner nooks don't show a mismatched square (the recurring
        # "no per-pixel transparency" gotcha — see CLAUDE.md).
        try:
            self._popup.configure(bg=self.panel._apply_appearance_mode(self.panel._fg_color))
        except Exception:
            pass
        self._popup.lift()
        self._popup.attributes("-topmost", True)

        root = self.winfo_toplevel()
        # add="+" so other toplevel bindings survive; funcids let close()
        # remove exactly these again.
        self._global_binds = [
            ("<Button-1>", root.bind("<Button-1>", self._on_global_click, add="+")),
            ("<Configure>", root.bind("<Configure>", self._on_root_change, add="+")),
            ("<Unmap>", root.bind("<Unmap>", self._on_root_change, add="+")),
        ]

        self._anim(1, opening=True)

    def close(self, animate=True):
        """Rolls the popup shut and hides it, and stops listening for outside
        clicks / window moves. `animate=False` (used by `destroy`) skips
        straight to hidden."""
        if not self._is_open:
            return
        self._is_open = False
        self._cancel_anim()

        root = self.winfo_toplevel()
        for sequence, funcid in self._global_binds:
            try:
                root.unbind(sequence, funcid)
            except Exception:
                pass
        self._global_binds = []

        if not self._popup.winfo_exists():
            return
        if animate and self._geo is not None:
            self._anim(1, opening=False)
        else:
            self._popup.withdraw()
            try:
                self._popup.attributes("-alpha", 1.0)
            except tk.TclError:
                pass

    def _anim(self, step, opening):
        """One tick of the unroll (opening) or roll-up (closing). Grows/shrinks
        the popup window's height with ease-out and moves `-alpha` in step;
        the last closing tick withdraws the window."""
        if not self._popup.winfo_exists() or self._geo is None:
            return
        w, h, x, y = self._geo
        steps = _ANIM_OPEN_STEPS if opening else _ANIM_CLOSE_STEPS
        t = step / steps
        frac = 1 - (1 - t) ** 3 if opening else (1 - t) ** 2   # 0→1 open, 1→0 close
        gh = max(1, round(h * frac))
        self._popup.geometry(f"{w}x{gh}+{x}+{y}")
        try:
            self._popup.attributes("-alpha", round(_ANIM_MIN_ALPHA + (1 - _ANIM_MIN_ALPHA) * frac, 3))
        except tk.TclError:
            pass

        if step < steps:
            self._anim_job = self.after(_ANIM_INTERVAL_MS, lambda: self._anim(step + 1, opening))
            return

        self._anim_job = None
        if opening:
            self._popup.geometry(f"{w}x{h}+{x}+{y}")
            try:
                self._popup.attributes("-alpha", 1.0)
            except tk.TclError:
                pass
        else:
            self._popup.withdraw()
            try:
                self._popup.attributes("-alpha", 1.0)
            except tk.TclError:
                pass

    def _cancel_anim(self):
        if self._anim_job is not None:
            try:
                self.after_cancel(self._anim_job)
            except Exception:
                pass
            self._anim_job = None

    def _on_root_change(self, event):
        """The main window moved or was minimized — the popup doesn't follow
        it, so drop it. A toplevel binding also receives its descendants'
        `<Configure>` events, hence the widget check."""
        if event.widget is self.winfo_toplevel():
            self.close(animate=False)

    def _on_global_click(self, event):
        """Closes on any click outside both the panel and the button itself.
        Clicks inside the popup are a separate window and never reach this, so
        they can't close it; a click on the button is left for `_toggle`
        (closing here first would let the toggle immediately reopen)."""
        if not self._is_open:
            return
        for widget in (self.panel, self):
            if not widget.winfo_exists():
                continue
            x0, y0 = widget.winfo_rootx(), widget.winfo_rooty()
            if (x0 <= event.x_root < x0 + widget.winfo_width()
                    and y0 <= event.y_root < y0 + widget.winfo_height()):
                return
        self.close()

    def _select(self, value):
        """A row click commits the value and fires the caller's command."""
        self.close()
        self.set(value)
        if self._user_command is not None:
            self._user_command(value)

    def set_values(self, values):
        """Replaces the option list, rebuilding the popup's rows.

        Needed because the Encoding/Muxing option lists are *derived* — the
        output container decides which codecs exist, the encoder decides
        which profiles/levels exist (see `core/formats.py`), so these menus
        get retargeted on every `_sync_controls` pass.

        **No-ops when the list is unchanged**, which is the common case on a
        sync: rebuilding the row buttons every keystroke would both flicker
        and churn widgets pointlessly. An empty list renders a single em-dash
        placeholder — callers pair that with `state="disabled"` for an option
        the current codec simply doesn't have.

        Does not fire `command`; the caller owns any value change it causes."""
        values = list(values) or ["—"]
        if values == self._values:
            return
        current = self.get()

        self.close(animate=False)
        self._geo = None          # cached open geometry — height just changed
        for row in self.rows.values():
            row.destroy()
        self.rows.clear()
        self._values = values

        for value in values:
            row = ctk.CTkButton(
                master=self.panel,
                text=value,
                anchor="w",
                height=_ROW_HEIGHT,
                corner_radius=4,
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                command=lambda v=value: self._select(v),
            )
            row.pack(fill="x", padx=3, pady=1)
            if self._on_hover is not None:
                row.bind("<Enter>", lambda e, v=value: self._on_hover(v))
            self.rows[value] = row

        # Keep the base class's own notion of the options in step, then put
        # the selection back if it survived the retarget (configure(values=)
        # resets it to the first entry).
        super().configure(values=values)
        self.set(current if current in values else values[0])

    def destroy(self):
        """Takes the popup window down too — it's a `Toplevel` of its own, not
        a child of the owning tab, so a live theme switch's tab rebuild (see
        LlamaGUI.apply_theme) would otherwise orphan it."""
        self._cancel_anim()
        self.close(animate=False)
        if self._popup.winfo_exists():
            self._popup.destroy()
        super().destroy()
