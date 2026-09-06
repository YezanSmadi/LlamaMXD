import customtkinter as ctk

_ROW_HEIGHT = 28
_PANEL_CORNER = 6
_PANEL_GAP = 3  # vertical gap between the button and the panel below it


class ThemedDropdown(ctk.CTkOptionMenu):
    """A `CTkOptionMenu` whose popup is a custom in-window panel instead of
    Tk's native menu — every dropdown in the app uses this so they all look
    and behave identically.

    Two things the native popup can't do, which is why this exists:

    1. **It stays open until an explicit dismissal** — a click on the button
       again, or a click anywhere outside the panel. Moving the pointer off it
       does nothing. The native menu is a grab-holding popup that closes on
       almost any pointer event.
    2. **Rows can report hover** (`on_hover`), which the Settings tab's theme
       picker needs to live-preview a palette. The native popup is modal on
       Windows and repaints nothing behind it, so a hover preview is invisible
       there.

    The panel is parented to the **toplevel**, not to this widget's own master,
    so it can float over whatever is beneath it (Tk's `place(in_=...)` allows
    any target that's a descendant of the placed widget's parent, and the root
    is an ancestor of everything). That does mean it isn't destroyed along with
    the tab that owns the dropdown, hence the `destroy()` override below."""

    def __init__(self, master, values, command=None, on_hover=None, **kwargs):
        # `command` is deliberately NOT handed to the base class: its own
        # value-picking path (the native menu) never runs, so we invoke the
        # caller's callback ourselves from _select.
        super().__init__(master=master, values=list(values), **kwargs)
        self._values = list(values)
        self._user_command = command
        self._on_hover = on_hover
        self._is_open = False
        self._global_click_bind = None
        self.rows = {}  # value -> row CTkButton, exposed for per-row styling

        self.panel = ctk.CTkFrame(
            master=self.winfo_toplevel(), corner_radius=_PANEL_CORNER,
            border_width=1, border_color=("gray70", "gray30"),
        )
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
        """Drops the panel beneath the button, matching its width — or flips it
        above when there isn't room below. The window is a fixed, fairly short
        size and some of these controls sit near its bottom edge (Profile and
        Level are two rows from it), where a downward panel would simply be
        clipped by the window with its last entries unreachable."""
        if self._is_open or not self.winfo_exists():
            return
        self._is_open = True

        root = self.winfo_toplevel()
        self.panel.update_idletasks()  # once per open, on a user click — not a hot path
        panel_height = self.panel.winfo_reqheight()
        button_bottom = self.winfo_rooty() - root.winfo_rooty() + self.winfo_height()
        room_below = root.winfo_height() - button_bottom - _PANEL_GAP

        if panel_height <= room_below:
            self.panel.place(in_=self, relx=0, rely=1.0, relwidth=1.0, y=_PANEL_GAP, anchor="nw")
        else:
            # anchor="sw" at the button's top-left puts the panel's BOTTOM edge
            # there, so it grows upward from the button instead of downward.
            self.panel.place(in_=self, relx=0, rely=0, relwidth=1.0, y=-_PANEL_GAP, anchor="sw")
        self.panel.lift()
        # add="+" so we don't clobber other toplevel bindings; the funcid lets
        # us remove exactly this one again on close.
        self._global_click_bind = self.winfo_toplevel().bind(
            "<Button-1>", self._on_global_click, add="+"
        )

    def close(self):
        """Hides the panel and stops listening for outside clicks."""
        if not self._is_open:
            return
        self._is_open = False
        if self._global_click_bind is not None:
            try:
                self.winfo_toplevel().unbind("<Button-1>", self._global_click_bind)
            except Exception:
                pass
            self._global_click_bind = None
        if self.panel.winfo_exists():
            self.panel.place_forget()

    def _on_global_click(self, event):
        """Closes on any click outside both the panel and the button itself. A
        click on the button is left alone so `_toggle` owns that case (both
        handlers fire for it, and closing here first would let the toggle
        immediately reopen)."""
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

    def destroy(self):
        """Takes the panel down too. It lives on the toplevel rather than under
        this widget's master, so destroying the owning tab would otherwise
        orphan it — which matters because a live theme switch rebuilds every
        tab (see LlamaGUI.apply_theme)."""
        self.close()
        if self.panel.winfo_exists():
            self.panel.destroy()
        super().destroy()
