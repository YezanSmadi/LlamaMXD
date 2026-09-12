import customtkinter as ctk

from components.marquee_label import MarqueeLabel

_LABEL_WIDTH = 72
_FONT_SIZE = 11
_ROW_PADY = 1


class SummaryPanel(ctk.CTkFrame):
    """The Overview sub-tab's export rundown — a compact `label  value` list.

    It exists to solve a structural problem, not just to look informative:
    the Video and Audio sub-tabs each hide the other's state, and several
    rules span them (the container filters *both* codec lists; Strip Video
    and Strip Audio mutually exclude). The rundown is the one place where
    every cross-panel consequence is visible at once, so the user never has
    to switch sub-tabs to find out what a setting did.

    Rows are built once from `labels` and only ever *reconfigured* — never
    destroyed and rebuilt — because `_sync_controls` refreshes this on every
    single control change, and widget churn at that rate flickers.
    `set_values` takes `(text, color)` pairs positionally; a `color` of None
    means the normal label colour (used for `STOP_RED` on a removed stream).
    """

    def __init__(self, master, labels, **kwargs):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self._labels = list(labels)
        self._value_labels = []

        bold = ctk.CTkFont(size=_FONT_SIZE, weight="bold")
        plain = ctk.CTkFont(size=_FONT_SIZE)
        self._default_color = ctk.ThemeManager.theme["CTkLabel"]["text_color"]

        for text in self._labels:
            row = ctk.CTkFrame(master=self, fg_color="transparent")
            row.pack(fill="x", pady=_ROW_PADY)

            ctk.CTkLabel(
                master=row, text=text, font=bold, width=_LABEL_WIDTH,
                anchor="w", text_color="gray60",
            ).pack(side="left")

            # A MarqueeLabel, not a plain CTkLabel -- a genuinely long value
            # (a multi-stream audio summary, e.g.) would otherwise silently
            # overflow (CTkLabel ignores a width smaller than its natural
            # text size; see CLAUDE.md) rather than scroll, extending past
            # this panel's own narrow ~260px budget. Sits still when the
            # text already fits, same as everywhere else this component's
            # used.
            value = MarqueeLabel(master=row, text="—", font=plain, anchor="w")
            value.pack(side="left", fill="x", expand=True)
            self._value_labels.append(value)

    def set_values(self, values):
        """Rewrites every row's value in one pass. `values` is a list of
        `(text, color)` positionally matching the construction `labels`; a
        short list leaves trailing rows blank rather than raising, so a
        caller can omit rows that don't apply."""
        for index, label in enumerate(self._value_labels):
            if index < len(values):
                text, color = values[index]
            else:
                text, color = "—", None
            label.configure(text=text or "—", text_color=color or self._default_color)
