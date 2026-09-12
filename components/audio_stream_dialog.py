"""A themed modal dialog for picking which of a source file's audio streams
get included in an Encoding job's output -- the "Choose Stream(s)" button on
the Audio sub-tab. One checkbox per probed stream (core.utilities.
probe_media's `audio_streams` list); OK returns the set of checked indices,
Cancel (or closing the window) returns None, so the caller can tell "nothing
changed" apart from "the user chose zero streams" -- which this dialog
refuses to actually produce; see `_ok`.

Modelled on components.dialogs.MessageDialog (same theming/centering/icon
conventions), but with a variable number of checkbox rows instead of a fixed
message + button row.
"""

import customtkinter as ctk

from core.theme import get_active_theme

_DIALOG_WIDTH = 420


class AudioStreamPickerDialog(ctk.CTkToplevel):
    """Lists every audio stream `probe_media` found for the current input,
    each with a checkbox pre-checked to match `included`. Blocks the caller
    until dismissed; `.result` is the chosen index set on OK, or None if the
    dialog was cancelled/closed."""

    def __init__(self, app, streams, included):
        super().__init__(master=app)
        theme = get_active_theme()
        self.result = None
        self._streams = streams

        self.title("Choose Audio Streams")
        self.resizable(False, False)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self.body = ctk.CTkFrame(master=self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=20, pady=(18, 14))

        ctk.CTkLabel(
            master=self.body, text="Choose Audio Streams",
            font=ctk.CTkFont(size=15, weight="bold"), anchor="w", justify="left",
        ).pack(anchor="w", pady=(0, 6))
        ctk.CTkLabel(
            master=self.body,
            text="Pick which of this file's audio streams to include in the "
                 "output. Each included stream keeps its own codec settings — "
                 "select it from the Audio Track dropdown to edit them.",
            wraplength=_DIALOG_WIDTH - 60, anchor="w", justify="left",
            text_color="gray60",
        ).pack(anchor="w", fill="x", pady=(0, 10))

        self._vars = {}
        for stream in streams:
            index = stream["index"]
            var = ctk.BooleanVar(value=index in included)
            self._vars[index] = var
            ctk.CTkCheckBox(
                master=self.body, text=self._describe(stream), variable=var,
                onvalue=True, offvalue=False,
            ).pack(anchor="w", pady=3)

        if not streams:
            ctk.CTkLabel(
                master=self.body, text="This file has no audio streams.", text_color="gray60"
            ).pack(anchor="w")

        self.button_row = ctk.CTkFrame(master=self.body, fg_color="transparent")
        self.button_row.pack(anchor="e", pady=(16, 0))

        ctk.CTkButton(
            master=self.button_row, text="OK", width=90,
            fg_color=theme["primary"], hover_color=theme["primary_hover"],
            text_color=theme["primary_text"], command=self._ok,
        ).pack(side="left", padx=(8, 0))
        ctk.CTkButton(
            master=self.button_row, text="Cancel", width=90,
            fg_color=theme["secondary"], hover_color=theme["secondary_hover"],
            text_color=theme["secondary_text"], command=self._cancel,
        ).pack(side="left", padx=(8, 0))

        self._center_on(app)
        self.deiconify()
        self.wait_visibility()
        self.grab_set()
        self.focus_force()
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self._cancel())
        # CTk re-applies its own titlebar styling ~200ms after construction
        # (see MessageDialog) -- best-effort, a missing icon must never take
        # this dialog down.
        self.after(250, self._apply_icon)

    @staticmethod
    def _describe(stream):
        """One checkbox's label: "Track 1  ·  AAC  ·  Stereo  ·  48000 Hz  ·
        eng" -- every bit conditional, so a stream this app couldn't fully
        identify still gets a sensible, non-empty label."""
        bits = [f"Track {stream['index'] + 1}"]
        for key in ("codec", "channels_display", "sample_rate_display", "language"):
            value = stream.get(key)
            if value:
                bits.append(str(value))
        return "  ·  ".join(bits)

    def _apply_icon(self):
        try:
            self.iconbitmap("llama.ico")
        except Exception:
            pass

    def _center_on(self, app):
        self.update_idletasks()
        width = max(_DIALOG_WIDTH, self.winfo_reqwidth())
        height = self.winfo_reqheight()
        x = app.winfo_rootx() + (app.winfo_width() - width) // 2
        y = app.winfo_rooty() + (app.winfo_height() - height) // 3
        self.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")

    def _ok(self):
        chosen = {index for index, var in self._vars.items() if var.get()}
        if not chosen and self._vars:
            # An empty result isn't a real choice here — "no audio at all" is
            # already the Strip Audio checkbox's job (see EncodingTab's
            # _sync_controls: one rule per bit of state, no duplicates). Snap
            # the first stream back on instead of letting OK produce the
            # same outcome through a second door.
            self._vars[min(self._vars)].set(True)
            return
        self.result = chosen
        self.grab_release()
        self.destroy()

    def _cancel(self):
        self.result = None
        self.grab_release()
        self.destroy()

    def show(self):
        """Blocks until dismissed, then returns `.result`."""
        self.master.wait_window(self)
        return self.result


def choose_audio_streams(app, streams, included):
    """Opens the picker; returns the chosen index set, or None if cancelled."""
    return AudioStreamPickerDialog(app, streams, included).show()
