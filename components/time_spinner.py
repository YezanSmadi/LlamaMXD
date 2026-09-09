import customtkinter as ctk

class TimeSpinner(ctk.CTkFrame):
    # String index (within "HH:MM:SS") of each of the 6 digit slots, in order.
    _SEGMENT_POSITIONS = (0, 1, 3, 4, 6, 7)

    def __init__(self, master, initial_seconds=0, command=None):
        super().__init__(master=master, fg_color="transparent")

        # Fired on every value change (typing, +/-, backspace, set()) so a
        # live readout — the Overview rundown's trim line — can update as the
        # user types rather than only on the next _sync_controls pass.
        self._command = command

        # Internal state representation [H, H, M, M, S, S]
        self.digits = ["0", "0", "0", "0", "0", "0"]
        self._set_from_seconds(initial_seconds)

        # cursor_pos indexes directly into self.digits (0-5) — the single
        # source of truth for where the block cursor sits. Only rendering
        # needs to translate that into a string position (see _SEGMENT_POSITIONS).
        self.cursor_pos = 5

        # Auto-repeat loop tracking attributes
        self._repeat_job = None
        self._current_delay = 400  # Initial delay before accelerating (ms)
        self._min_delay = 30       # Speed cap for fast-scrolling (ms)

        # Time Entry Field — sits on the left; the stepper goes to its right.
        self.entry = ctk.CTkEntry(
            self,
            width=100,
            justify="center"
        )
        self.entry.pack(side="left")

        # Explicit key bindings to intercept native Tkinter overrides
        self.entry.bind("<Key>", self._on_key_press)
        self.entry.bind("<BackSpace>", self._on_backspace)
        self.entry.bind("<Delete>", self._on_delete)
        self.entry.bind("<Button-1>", lambda e: self.after(10, self._on_click))
        self.entry.bind("<FocusIn>", lambda e: self.after(10, self._render_block_cursor))
        self.entry.bind("<FocusOut>", lambda e: self._on_focus_out())

        self.update_display()

        # Up/Down stepper, to the RIGHT of the time. The two arrows stacked
        # together take up the width one +/- button used to — a compact pair
        # rather than two buttons flanking the field. btn_plus/btn_minus keep
        # their names (set_state configures them).
        self._stepper = ctk.CTkFrame(self, fg_color="transparent")
        self._stepper.pack(side="left", padx=(5, 0))

        self.btn_plus = ctk.CTkButton(
            self._stepper, text="▲", width=30, height=13, corner_radius=3,
            font=ctk.CTkFont(size=9),
        )
        self.btn_plus.pack(side="top")

        self.btn_minus = ctk.CTkButton(
            self._stepper, text="▼", width=30, height=13, corner_radius=3,
            font=ctk.CTkFont(size=9),
        )
        self.btn_minus.pack(side="top", pady=(2, 0))

        # Bind press/release events for accelerating auto-repeat on both.
        for _btn, _action in ((self.btn_plus, self.increment), (self.btn_minus, self.decrement)):
            _btn.bind("<ButtonPress-1>", lambda e, a=_action: self._start_hold(a))
            _btn.bind("<ButtonRelease-1>", lambda e: self._stop_hold())
            _btn.bind("<Leave>", lambda e: self._stop_hold())

    def _start_hold(self, action):
        """Starts the repeating action loop on button press."""
        self._stop_hold()  # Clear any previous pending job
        self._current_delay = 400  # Reset back to initial delay
        action()  # Run action immediately on initial press
        self._run_hold_loop(action)

    def _run_hold_loop(self, action):
        """Recursively schedules the next step, accelerating delay over time."""
        self._current_delay = max(self._min_delay, int(self._current_delay * 0.85))
        self._repeat_job = self.after(self._current_delay, lambda: self._step_and_continue(action))

    def _step_and_continue(self, action):
        """Executes action and continues the repeat loop."""
        action()
        self._run_hold_loop(action)

    def _stop_hold(self):
        """Cancels any pending auto-repeat job."""
        if self._repeat_job is not None:
            self.after_cancel(self._repeat_job)
            self._repeat_job = None

    def _nearest_digit_index(self, str_pos):
        """Maps a raw string index (e.g. from a click, which may land on a
        colon) to the closest digit segment."""
        distances = [abs(seg - str_pos) for seg in self._SEGMENT_POSITIONS]
        return distances.index(min(distances))

    def _hide_caret(self):
        """Enforces absolute removal of the native vertical blinking caret."""
        try:
            self.entry._entry.config(insertwidth=0, insertbackground=self.entry._entry.cget("bg"))
        except Exception:
            pass

    def _on_backspace(self, event):
        """Steps the cursor back and clears that digit — the mirror image of
        typing a digit (which writes, then steps forward)."""
        if self.cursor_pos > 0:
            self.cursor_pos -= 1
        self.digits[self.cursor_pos] = "0"
        self.update_display()
        return "break"

    def _on_delete(self, event):
        """Clears the digit under the cursor without moving it."""
        self.digits[self.cursor_pos] = "0"
        self.update_display()
        return "break"

    def _on_key_press(self, event):
        """Handles numeric typing and cursor navigation."""
        if event.keysym in ("Tab", "ISO_Left_Tab"):
            return

        if event.char.isdigit():
            self.digits[self.cursor_pos] = event.char
            self._validate_and_clamp_limits()
            self.cursor_pos = min(5, self.cursor_pos + 1)
            self.update_display()
            return "break"

        if event.keysym == "Left":
            self.cursor_pos = max(0, self.cursor_pos - 1)
            self.after(1, self._render_block_cursor)
            return "break"

        if event.keysym == "Right":
            self.cursor_pos = min(5, self.cursor_pos + 1)
            self.after(1, self._render_block_cursor)
            return "break"

        if event.keysym == "Home":
            self.cursor_pos = 0
            self.after(1, self._render_block_cursor)
            return "break"

        if event.keysym == "End":
            self.cursor_pos = 5
            self.after(1, self._render_block_cursor)
            return "break"

        return "break"

    def _validate_and_clamp_limits(self):
        """Ensures minutes and seconds do not exceed 59."""
        mins = int("".join(self.digits[2:4]))
        secs = int("".join(self.digits[4:6]))

        if mins > 59:
            self.digits[2:4] = ["5", "9"]
        if secs > 59:
            self.digits[4:6] = ["5", "9"]

    def _on_click(self):
        """Syncs internal cursor position when clicking into the box."""
        click_idx = self.entry.index("insert")
        self.cursor_pos = self._nearest_digit_index(click_idx)
        self._render_block_cursor()

    def _on_focus_out(self):
        """Clears selection highlight when focus is lost."""
        self.entry.selection_clear()

    def _is_focused(self):
        """Checks if the internal entry widget holds active keyboard focus."""
        try:
            return self.focus_get() == self.entry._entry
        except Exception:
            return False

    def _render_block_cursor(self):
        """Draws pure block selection and suppresses native caret line when focused."""
        if not self.entry.winfo_exists():
            return

        if not self._is_focused():
            self.entry.selection_clear()
            return

        self._hide_caret()
        str_pos = self._SEGMENT_POSITIONS[self.cursor_pos]
        self.entry.select_range(str_pos, str_pos + 1)

    def update_display(self):
        """Writes formatted HH:MM:SS text and updates cursor if focused."""
        formatted = f"{self.digits[0]}{self.digits[1]}:{self.digits[2]}{self.digits[3]}:{self.digits[4]}{self.digits[5]}"

        self.entry.delete(0, "end")
        self.entry.insert(0, formatted)

        # Only highlight cursor block if this field is currently focused
        if self._is_focused():
            self.after(1, self._render_block_cursor)

        # Notify a listener (e.g. the Overview rundown) of the new value.
        if self._command is not None:
            self._command()

    def increment(self):
        """Adds 1 second and updates display."""
        total = self.get_total_seconds() + 1
        self._set_from_seconds(total)
        self.update_display()

    def decrement(self):
        """Subtracts 1 second and updates display."""
        total = max(0, self.get_total_seconds() - 1)
        self._set_from_seconds(total)
        self.update_display()

    def _set_from_seconds(self, total_secs):
        hrs = min(99, total_secs // 3600)
        mins = (total_secs % 3600) // 60
        secs = total_secs % 60

        s_str = f"{hrs:02d}{mins:02d}{secs:02d}"
        self.digits = list(s_str)

    def get_total_seconds(self):
        """Returns total time represented in seconds."""
        hrs = int(f"{self.digits[0]}{self.digits[1]}")
        mins = int(f"{self.digits[2]}{self.digits[3]}")
        secs = int(f"{self.digits[4]}{self.digits[5]}")
        return (hrs * 3600) + (mins * 60) + secs

    def get(self):
        """Returns formatted string 'HH:MM:SS'."""
        return f"{self.digits[0]}{self.digits[1]}:{self.digits[2]}{self.digits[3]}:{self.digits[4]}{self.digits[5]}"

    def set(self, total_seconds):
        """Sets the spinner's value from a total-seconds count and refreshes the display."""
        self._set_from_seconds(total_seconds)
        self.update_display()

    def set_state(self, state="normal"):
        """Enables ('normal') or greys out/disables ('disabled') the spinner."""
        self.entry.configure(state=state)
        self.btn_minus.configure(state=state)
        self.btn_plus.configure(state=state)

        if state == "disabled":
            self.entry.configure(text_color="gray35")
            self.entry.selection_clear()
        else:
            self.entry.configure(text_color=ctk.ThemeManager.theme["CTkEntry"]["text_color"])
            if self._is_focused():
                self._render_block_cursor()
