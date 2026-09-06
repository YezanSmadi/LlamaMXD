import customtkinter as ctk

from core.theme import get_active_theme

_DIALOG_WIDTH = 400
_WRAP = _DIALOG_WIDTH - 60


class MessageDialog(ctk.CTkToplevel):
    """A small themed modal message box — a bold title, a wrapped message, and
    one or two buttons. Blocks the caller until dismissed; `.result` is the
    label of the button that was pressed, or None if the window was closed
    outright (so a close counts as declining, never as confirming).

    Deliberately a custom CTkToplevel rather than tkinter.messagebox: the
    native Windows boxes ignore the app's theme entirely, and this app's whole
    look is theme-driven (see CLAUDE.md's Theming section)."""

    def __init__(self, app, title, message, buttons=("OK",)):
        super().__init__(master=app)
        theme = get_active_theme()
        self.result = None
        self._buttons = buttons

        self.title(title)
        self.resizable(False, False)
        # transient() keeps it above the main window and off the taskbar;
        # closing it via the titlebar leaves result=None (i.e. "No"/cancel).
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", lambda: self._dismiss(None))

        self.body = ctk.CTkFrame(master=self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=20, pady=(18, 14))

        self.title_label = ctk.CTkLabel(
            master=self.body, text=title, font=ctk.CTkFont(size=15, weight="bold"),
            anchor="w", justify="left",
        )
        self.title_label.pack(anchor="w", pady=(0, 6))

        self.message_label = ctk.CTkLabel(
            master=self.body, text=message, wraplength=_WRAP, anchor="w", justify="left",
        )
        self.message_label.pack(anchor="w", fill="x")

        self.button_row = ctk.CTkFrame(master=self.body, fg_color="transparent")
        self.button_row.pack(anchor="e", pady=(16, 0))

        # The FIRST button is the affirmative one (OK / Yes) and gets the
        # brand primary; anything after it is a decline and stays secondary.
        for index, label in enumerate(buttons):
            is_primary = index == 0
            button = ctk.CTkButton(
                master=self.button_row,
                text=label,
                width=90,
                fg_color=theme["primary"] if is_primary else theme["secondary"],
                hover_color=theme["primary_hover"] if is_primary else theme["secondary_hover"],
                text_color=theme["primary_text"] if is_primary else theme["secondary_text"],
                command=lambda choice=label: self._dismiss(choice),
            )
            button.pack(side="left", padx=(8, 0))

        self._center_on(app)
        # grab_set() fails with "window not viewable" if the toplevel hasn't
        # been mapped yet, so wait for visibility before claiming modality.
        self.deiconify()
        self.wait_visibility()
        self.grab_set()
        self.focus_force()
        # Enter confirms, Escape declines — Escape resolves to the LAST button
        # (the decline in a two-button dialog, the only button in a one-button
        # one), matching what the window's close box does.
        self.bind("<Return>", lambda e: self._dismiss(buttons[0]))
        self.bind("<Escape>", lambda e: self._dismiss(None))
        # CTk re-applies its own titlebar styling ~200ms after construction, so
        # an icon set now gets clobbered; set it after that settles. Best-effort
        # — a missing llama.ico must never take a dialog down with it.
        self.after(250, self._apply_icon)

    def _apply_icon(self):
        try:
            self.iconbitmap("llama.ico")
        except Exception:
            pass

    def _center_on(self, app):
        """Centers this dialog over the main window."""
        self.update_idletasks()
        width = max(_DIALOG_WIDTH, self.winfo_reqwidth())
        height = self.winfo_reqheight()
        x = app.winfo_rootx() + (app.winfo_width() - width) // 2
        y = app.winfo_rooty() + (app.winfo_height() - height) // 3
        self.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")

    def _dismiss(self, choice):
        self.result = choice
        self.grab_release()
        self.destroy()

    def show(self):
        """Blocks until the dialog is dismissed, then returns `.result`."""
        self.master.wait_window(self)
        return self.result


def show_message(app, title, message):
    """Single-OK notice. Returns once the user acknowledges it."""
    return MessageDialog(app, title, message, buttons=("OK",)).show()


def ask_yes_no(app, title, message):
    """Yes/No confirmation. Returns True only on an explicit Yes — closing the
    dialog or pressing Escape both count as No."""
    return MessageDialog(app, title, message, buttons=("Yes", "No")).show() == "Yes"
