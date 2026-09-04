import customtkinter as ctk

class TimeSpinner(ctk.CTkFrame):
    def __init__(self, master, initial_seconds=0):
        super().__init__(master=master, fg_color="transparent")
        self.total_seconds = initial_seconds

        # Minus Button
        self.btn_minus = ctk.CTkButton(
            self, text="-", width=30, height=30, command=self.decrement
        )
        self.btn_minus.pack(side="left", padx=(0, 5))

        # Time Entry Field
        self.entry = ctk.CTkEntry(self, width=90, justify="center")
        self.entry.pack(side="left")
        self.update_display()

        # Plus Button
        self.btn_plus = ctk.CTkButton(
            self, text="+", width=30, height=30, command=self.increment
        )
        self.btn_plus.pack(side="left", padx=(5, 0))

    def format_time(self, total_secs):
        """Converts total seconds into 00:00:00 string format."""
        hrs = total_secs // 3600
        mins = (total_secs % 3600) // 60
        secs = total_secs % 60
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"

    def update_display(self):
        """Refreshes the entry box text."""
        self.entry.delete(0, "end")
        self.entry.insert(0, self.format_time(self.total_seconds))

    def increment(self):
        """Adds 1 second (or change step to 10/60 as needed)."""
        self.total_seconds += 1
        self.update_display()

    def decrement(self):
        """Subtracts 1 second, clamping at zero."""
        if self.total_seconds > 0:
            self.total_seconds -= 1
            self.update_display()

    def get(self):
        """Returns the current formatted string '00:00:00'."""
        return self.entry.get()