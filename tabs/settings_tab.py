import customtkinter as ctk
from tkinter import filedialog

from core.theme import THEMES, get_theme, get_active_theme, load_settings, save_settings

class SettingsTab(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master=master)
        self.app = app
        settings = load_settings()
        theme = get_active_theme()

        self.header_label = ctk.CTkLabel(
            master=self, text="Settings", font=ctk.CTkFont(size=28, weight="bold")
        )
        self.header_label.pack(anchor="w", padx=30, pady=(20, 20))

        self.options_frame = ctk.CTkFrame(master=self, fg_color="transparent")
        self.options_frame.pack(anchor="w", fill="x", padx=30)

        # -- Theme --
        self.theme_row = ctk.CTkFrame(master=self.options_frame, fg_color="transparent")
        self.theme_row.pack(anchor="w", pady=(0, 16))

        self.theme_label = ctk.CTkLabel(
            master=self.theme_row, text="Theme:", font=("Arial", 11, "bold")
        )
        self.theme_label.pack(anchor="w", pady=(0, 4))

        self.theme_menu = ctk.CTkOptionMenu(
            master=self.theme_row,
            values=list(THEMES.keys()),
            width=150,
            command=self._on_theme_change,
        )
        self.theme_menu.set(settings["theme"])
        self.theme_menu.pack(anchor="w")

        # Small live preview of the selected theme's two colors — the
        # dropdown text alone ("Cupid") doesn't convey what that actually
        # looks like, and the change itself isn't applied until Save is
        # clicked (see _on_save), so this is the only feedback available
        # while still choosing.
        self.theme_swatch_row = ctk.CTkFrame(master=self.theme_row, fg_color="transparent")
        self.theme_swatch_row.pack(anchor="w", pady=(6, 0))

        self.theme_primary_swatch = ctk.CTkFrame(
            master=self.theme_swatch_row, width=24, height=24, corner_radius=4
        )
        self.theme_primary_swatch.pack(side="left", padx=(0, 6))
        self.theme_primary_swatch.pack_propagate(False)

        self.theme_secondary_swatch = ctk.CTkFrame(
            master=self.theme_swatch_row, width=24, height=24, corner_radius=4
        )
        self.theme_secondary_swatch.pack(side="left")
        self.theme_secondary_swatch.pack_propagate(False)

        self._update_theme_swatches(settings["theme"])

        self.theme_note = ctk.CTkLabel(
            master=self.theme_row,
            text="Applies immediately when you click Save — no restart needed.",
            font=("Arial", 10),
            text_color="gray60",
        )
        self.theme_note.pack(anchor="w", pady=(6, 0))

        # -- Appearance Mode (Light / Dark / System) --
        self.appearance_row = ctk.CTkFrame(master=self.options_frame, fg_color="transparent")
        self.appearance_row.pack(anchor="w", pady=(0, 16))

        self.appearance_label = ctk.CTkLabel(
            master=self.appearance_row, text="Appearance Mode:", font=("Arial", 11, "bold")
        )
        self.appearance_label.pack(anchor="w", pady=(0, 4))

        self.appearance_menu = ctk.CTkOptionMenu(
            master=self.appearance_row,
            values=["System", "Light", "Dark"],
            width=150,
            command=self._on_appearance_change,
        )
        self.appearance_menu.set(settings["appearance_mode"])
        self.appearance_menu.pack(anchor="w")

        # -- Default Save Location --
        self.save_location_row = ctk.CTkFrame(master=self.options_frame, fg_color="transparent")
        self.save_location_row.pack(anchor="w", fill="x", pady=(0, 16))

        self.save_location_label = ctk.CTkLabel(
            master=self.save_location_row, text="Default Save Location:", font=("Arial", 11, "bold")
        )
        self.save_location_label.pack(anchor="w", pady=(0, 4))

        self.save_location_entry_row = ctk.CTkFrame(master=self.save_location_row, fg_color="transparent")
        self.save_location_entry_row.pack(anchor="w")

        self.save_location_entry = ctk.CTkEntry(
            master=self.save_location_entry_row,
            placeholder_text="No default location set...",
            width=300,
        )
        if self.app.default_save_location:
            self.save_location_entry.insert(0, self.app.default_save_location)
        self.save_location_entry.pack(side="left", padx=(0, 8))

        self.browse_save_location_btn = ctk.CTkButton(
            master=self.save_location_entry_row,
            text="Browse",
            width=80,
            command=self._browse_save_location,
        )
        self.browse_save_location_btn.pack(side="left")

        # -- Save --
        self.save_btn = ctk.CTkButton(
            master=self.options_frame,
            text="Save",
            width=150,
            fg_color=theme["primary"],
            text_color="black",
            hover_color=theme["primary_hover"],
            command=self._on_save,
        )
        self.save_btn.pack(anchor="w", pady=(4, 4))

        self.save_status_label = ctk.CTkLabel(
            master=self.options_frame, text="", font=("Arial", 10), text_color="gray60"
        )
        self.save_status_label.pack(anchor="w")

    def _on_theme_change(self, value):
        """Updates the color preview swatches — the theme change itself
        doesn't take effect anywhere else until Save is clicked (see
        _on_save)."""
        self._update_theme_swatches(value)

    def _update_theme_swatches(self, theme_name):
        palette = get_theme(theme_name)
        self.theme_primary_swatch.configure(fg_color=palette["primary"])
        self.theme_secondary_swatch.configure(fg_color=palette["secondary"])

    def _on_appearance_change(self, value):
        """Live-switches light/dark/system appearance mode."""
        ctk.set_appearance_mode(value.lower())

    def _browse_save_location(self):
        """Lets the user pick a folder used as the starting directory for
        Encoding/Muxing's save-file dialogs when no input file is loaded yet."""
        folder = filedialog.askdirectory(title="Select Default Save Location")
        if folder:
            self.app.default_save_location = folder
            self.save_location_entry.delete(0, "end")
            self.save_location_entry.insert(0, folder)

    def _on_save(self):
        """Persists the theme, appearance mode, and default save location
        to settings.json, and — if the theme changed — live-applies it via
        LlamaGUI.apply_theme immediately, no restart needed."""
        new_theme = self.theme_menu.get()
        theme_changed = new_theme != load_settings()["theme"]
        save_settings({
            "theme": new_theme,
            "appearance_mode": self.appearance_menu.get(),
            "default_save_location": self.app.default_save_location,
        })
        if theme_changed:
            # Rebuilds this tab (among others) — nothing below this line
            # should touch self, since the widget it belongs to is about
            # to be destroyed as part of that rebuild.
            self.app.apply_theme(new_theme)
            return
        self.save_status_label.configure(text="Settings saved.")
