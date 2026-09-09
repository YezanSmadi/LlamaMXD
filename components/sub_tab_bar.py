import customtkinter as ctk

from core.theme import get_active_theme

_MARK = " ⊘"


class SubTabBar(ctk.CTkFrame):
    """A compact row of mutually-exclusive tab buttons (Muxing/Encoding's
    `Overview` / `Video` / `Audio` switch), sitting top-left of the preview
    area.

    The active button is filled with the theme's `primary` colour and the
    inactive ones with `secondary` — the same two-role palette every themed
    control in the app uses, with the adaptive black/white label colour on
    each (`readable_text_on`, via the theme's `*_text` keys). Clicking an
    inactive button calls `command(name)`; re-clicking the active one does
    nothing.

    **Buttons can carry a state marker** (`set_marked`), which is what keeps
    cross-panel rules honest: Strip Video lives on the Video panel and Strip
    Audio on the Audio panel, so without a marker, removing a stream would
    silently change state on a panel the user can't currently see. A `⊘` on
    the tab button makes that visible from anywhere.

    There's nothing to refresh on a live theme switch — the owning tab is
    destroyed and rebuilt whole, so this widget is reconstructed and
    re-reads `get_active_theme()` from scratch."""

    def __init__(self, master, options, command, initial=None, **kwargs):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self._theme = get_active_theme()
        self._command = command
        self._buttons = {}
        self._marked = set()
        self._active = initial if initial in options else options[0]

        for name in options:
            # Width tracks the label so "Overview" isn't clipped while
            # "Video" doesn't float in dead space; padx=(0, 2) butts the
            # buttons together like a segmented control rather than leaving
            # them as separate floating pills.
            button = ctk.CTkButton(
                master=self,
                text=name,
                width=max(58, len(name) * 8 + 16),
                height=26,
                corner_radius=6,
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda n=name: self._on_click(n),
            )
            button.pack(side="left", padx=(0, 2))
            self._buttons[name] = button

        self._repaint()

    def _on_click(self, name):
        """Selects `name` (unless it's already active) and fires `command`."""
        if name == self._active:
            return
        self._active = name
        self._repaint()
        self._command(name)

    def _repaint(self):
        """Paints the active button `primary`, every other one `secondary`,
        and re-applies each button's marker suffix."""
        for name, button in self._buttons.items():
            marker = _MARK if name in self._marked else ""
            if name == self._active:
                button.configure(
                    text=name + marker,
                    fg_color=self._theme["primary"],
                    hover_color=self._theme["primary_hover"],
                    text_color=self._theme["primary_text"],
                )
            else:
                button.configure(
                    text=name + marker,
                    fg_color=self._theme["secondary"],
                    hover_color=self._theme["secondary_hover"],
                    text_color=self._theme["secondary_text"],
                )

    def set_marked(self, name, marked):
        """Shows/hides the `⊘` state marker on one tab button — used to
        surface a stripped stream from whichever panel is on screen. No-ops
        when nothing changes, since `_sync_controls` calls this on every
        pass."""
        if name not in self._buttons:
            return
        already = name in self._marked
        if already == bool(marked):
            return
        self._marked.add(name) if marked else self._marked.discard(name)
        self._repaint()

    def get(self):
        """The name of the currently-active tab."""
        return self._active

    def set(self, name, fire=False):
        """Selects `name` programmatically. Fires `command` only if `fire`."""
        if name not in self._buttons or name == self._active:
            return
        self._active = name
        self._repaint()
        if fire:
            self._command(name)
