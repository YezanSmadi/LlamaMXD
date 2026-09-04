import customtkinter as ctk

class TimeSpinner(ctk.CTkFrame):
    def __init__(self, master, initial_seconds=0):
        super().__init__(master=master, fg_color="transparent")
        
        # Internal state representation [H, H, M, M, S, S]
        self.digits = ["0", "0", "0", "0", "0", "0"]
        self._set_from_seconds(initial_seconds)

        # Start cursor on far-right digit (index 7 in "HH:MM:SS" string)
        self.cursor_pos = 7

        # Auto-repeat loop tracking attributes
        self._repeat_job = None
        self._current_delay = 400  # Initial delay before accelerating (ms)
        self._min_delay = 30       # Speed cap for fast-scrolling (ms)

        # Minus Button
        self.btn_minus = ctk.CTkButton(
            self, text="-", width=30, height=30
        )
        self.btn_minus.pack(side="left", padx=(0, 5))
        
        # Bind press/release events for accelerating auto-repeat
        self.btn_minus.bind("<ButtonPress-1>", lambda e: self._start_hold(self.decrement))
        self.btn_minus.bind("<ButtonRelease-1>", lambda e: self._stop_hold())
        self.btn_minus.bind("<Leave>", lambda e: self._stop_hold())

        # Time Entry Field
        self.entry = ctk.CTkEntry(
            self, 
            width=100, 
            justify="center"
        )
        self.entry.pack(side="left")

        # Explicit key bindings to intercept native Tkinter overrides
        self.entry.bind("<Key>", self._on_key_press)
        self.entry.bind("<BackSpace>", self._on_delete_backspace)
        self.entry.bind("<Delete>", self._on_delete_backspace)
        self.entry.bind("<Button-1>", lambda e: self.after(10, self._on_click))
        self.entry.bind("<FocusIn>", lambda e: self.after(10, self._render_block_cursor))
        self.entry.bind("<FocusOut>", lambda e: self._on_focus_out())

        self.update_display()

        # Plus Button
        self.btn_plus = ctk.CTkButton(
            self, text="+", width=30, height=30
        )
        self.btn_plus.pack(side="left", padx=(5, 0))

        # Bind press/release events for accelerating auto-repeat
        self.btn_plus.bind("<ButtonPress-1>", lambda e: self._start_hold(self.increment))
        self.btn_plus.bind("<ButtonRelease-1>", lambda e: self._stop_hold())
        self.btn_plus.bind("<Leave>", lambda e: self._stop_hold())

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

    def _get_digit_index(self, str_pos):
        """Maps 'HH:MM:SS' string index (0-7) to self.digits index (0-5)."""
        mapping = {0: 0, 1: 1, 3: 2, 4: 3, 6: 4, 7: 5}
        return mapping.get(str_pos, 5)

    def _hide_caret(self):
        """Enforces absolute removal of the native vertical blinking caret."""
        try:
            self.entry._entry.config(insertwidth=0, insertbackground=self.entry._entry.cget("bg"))
        except Exception:
            pass

    def _on_delete_backspace(self, event):
        """Dedicated handler to ensure Backspace/Delete cascade works reliably."""
        digit_idx = self._get_digit_index(self.cursor_pos)
        
        left_side = ["0"] + self.digits[:digit_idx]
        right_side = self.digits[digit_idx + 1:]
        self.digits = (left_side + right_side)[:6]
        
        self.update_display()
        return "break"

    def _on_key_press(self, event):
        """Handles numeric typing and arrow navigation."""
        if event.keysym in ("Tab", "ISO_Left_Tab"):
            return

        if event.char.isdigit():
            digit_idx = self._get_digit_index(self.cursor_pos)
            self.digits[digit_idx] = event.char
            
            self._validate_and_clamp_limits()

            self.cursor_pos -= 1
            if self.cursor_pos in (2, 5):
                self.cursor_pos -= 1
            
            self.update_display()
            return "break"

        elif event.keysym == "Left":
            self.cursor_pos -= 1
            if self.cursor_pos in (2, 5):
                self.cursor_pos -= 1
            self.cursor_pos = max(0, min(7, self.cursor_pos))
            self.after(1, self._render_block_cursor)
            return "break"

        elif event.keysym == "Right":
            self.cursor_pos += 1
            if self.cursor_pos in (2, 5):
                self.cursor_pos += 1
            self.cursor_pos = max(0, min(7, self.cursor_pos))
            self.after(1, self._render_block_cursor)
            return "break"

        return "break"

    def _validate_and_clamp_limits(self):
        """Ensures minutes and seconds do not exceed 59."""
        mins = int(f"{self.digits[2]}{self.digits[3]}")
        secs = int(f"{self.digits[4]}{self.digits[5]}")

        if mins > 59:
            self.digits[2], self.digits[3] = "5", "9"
        if secs > 59:
            self.digits[4], self.digits[5] = "5", "9"

    def _on_click(self):
        """Syncs internal cursor position when clicking into the box."""
        click_idx = self.entry.index("insert")
        if click_idx in (2, 5):
            click_idx -= 1
        self.cursor_pos = max(0, min(7, click_idx))
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
            
        if self.cursor_pos in (2, 5):
            self.cursor_pos -= 1
            
        self.cursor_pos = max(0, min(7, self.cursor_pos))

        self._hide_caret()
        self.entry.select_range(self.cursor_pos, self.cursor_pos + 1)

    def update_display(self):
        """Writes formatted HH:MM:SS text and updates cursor if focused."""
        formatted = f"{self.digits[0]}{self.digits[1]}:{self.digits[2]}{self.digits[3]}:{self.digits[4]}{self.digits[5]}"
        
        self.entry.delete(0, "end")
        self.entry.insert(0, formatted)
        
        # Only highlight cursor block if this field is currently focused
        if self._is_focused():
            self.after(1, self._render_block_cursor)

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

    def set_state(self, state="normal"):
        """Enables ('normal') or greys out/disables ('disabled') the spinner."""
        self.entry.configure(state=state)
        self.btn_minus.configure(state=state)
        self.btn_plus.configure(state=state)
        
        if state == "disabled":
            self.entry.configure(text_color="gray50")
            self.entry.selection_clear()
        else:
            self.entry.configure(text_color=ctk.ThemeManager.theme["CTkEntry"]["text_color"])
            if self._is_focused():
                self._render_block_cursor()