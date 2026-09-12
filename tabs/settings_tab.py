from tkinter import filedialog

import customtkinter as ctk

from components.dropdown import ThemedDropdown
from core.theme import THEMES, get_theme, get_active_theme, load_settings, save_settings


class SettingsTab(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master=master)
        self.app = app
        settings = load_settings()
        theme = get_active_theme()

        self._selected_theme = settings["theme"]

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

        # Dropdown on the left, live two-color preview + name to its right.
        # on_hover previews a palette without committing it — the whole reason
        # ThemedDropdown exists rather than a stock CTkOptionMenu.
        self.theme_pick_row = ctk.CTkFrame(master=self.theme_row, fg_color="transparent")
        self.theme_pick_row.pack(anchor="w")

        self.theme_menu = ThemedDropdown(
            master=self.theme_pick_row,
            values=list(THEMES.keys()),
            width=150,
            command=self._on_theme_change,
            on_hover=self._show_theme_preview,
        )
        self.theme_menu.set(self._selected_theme)
        self.theme_menu.pack(side="left")

        self.theme_preview_row = ctk.CTkFrame(master=self.theme_pick_row, fg_color="transparent")
        self.theme_preview_row.pack(side="left", padx=(12, 0))

        self.theme_primary_swatch = ctk.CTkFrame(
            master=self.theme_preview_row, width=26, height=26, corner_radius=4
        )
        self.theme_primary_swatch.pack(side="left", padx=(0, 5))
        self.theme_primary_swatch.pack_propagate(False)

        self.theme_secondary_swatch = ctk.CTkFrame(
            master=self.theme_preview_row, width=26, height=26, corner_radius=4
        )
        self.theme_secondary_swatch.pack(side="left", padx=(0, 8))
        self.theme_secondary_swatch.pack_propagate(False)

        self.theme_name_label = ctk.CTkLabel(
            master=self.theme_preview_row, text="", font=("Arial", 11)
        )
        self.theme_name_label.pack(side="left")

        # Closing the panel drops any hover preview back to what's committed.
        self.theme_menu.panel.bind("<Unmap>", lambda e: self._show_theme_preview(self._selected_theme))

        self._show_theme_preview(self._selected_theme)

        self.theme_note = ctk.CTkLabel(
            master=self.theme_row,
            text="Applies instantly — no restart. Saves automatically when you leave.",
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

        self.appearance_menu = ThemedDropdown(
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
        # A hand-typed path counts too — push it into app state on focus-out.
        self.save_location_entry.bind("<FocusOut>", lambda e: self._sync_state_from_widgets())

        self.browse_save_location_btn = ctk.CTkButton(
            master=self.save_location_entry_row,
            text="Browse",
            width=80,
            command=self._browse_save_location,
        )
        self.browse_save_location_btn.pack(side="left")

        # -- Hardware Acceleration (GPU) — moved here from the Encoding tab
        #    so it's a single global preference every Encode task inherits.
        self.gpu_row = ctk.CTkFrame(master=self.options_frame, fg_color="transparent")
        self.gpu_row.pack(anchor="w", pady=(0, 16))

        self.gpu_label = ctk.CTkLabel(
            master=self.gpu_row, text="Hardware Acceleration (GPU):", font=("Arial", 11, "bold")
        )
        self.gpu_label.pack(anchor="w", pady=(0, 4))

        self.gpu_switch = ctk.CTkSwitch(
            master=self.gpu_row, text="", width=42, command=self._on_gpu_toggle
        )
        if self.app.gpu_enabled:
            self.gpu_switch.select()
        self.gpu_switch.pack(anchor="w")

        # -- Save --
        self.save_btn = ctk.CTkButton(
            master=self.options_frame,
            text="Save",
            width=150,
            fg_color=theme["primary"],
            text_color=theme["primary_text"],
            hover_color=theme["primary_hover"],
            command=self._on_save,
        )
        self.save_btn.pack(anchor="w", pady=(4, 4))

        # Minimizing / unmapping auto-persists too (on_leave, called by
        # LlamaGUI.show_tab, handles the tab-switch case deterministically).
        self.bind("<Unmap>", self._autosave)

    def on_leave(self):
        """Called by LlamaGUI.show_tab just before this tab is switched
        away from — flushes all settings to disk."""
        self.theme_menu.close()
        self.appearance_menu.close()
        self._autosave()

    # ------------------------------------------------------------------ #
    #  Settings snapshot / persistence helpers
    # ------------------------------------------------------------------ #
    def _settings_snapshot(self, theme=None):
        """The current state of every control as a settings.json-shaped dict."""
        location = self.save_location_entry.get().strip()
        return {
            "theme": theme or self._selected_theme,
            "appearance_mode": self.appearance_menu.get(),
            "default_save_location": location or self.app.default_save_location,
            "gpu_enabled": bool(self.gpu_switch.get()),
        }

    def _sync_state_from_widgets(self):
        """Pushes the entry/switch values into shared app state so a live
        theme rebuild (which reconstructs this tab) doesn't lose them."""
        location = self.save_location_entry.get().strip()
        if location:
            self.app.default_save_location = location
        self.app.gpu_enabled = bool(self.gpu_switch.get())

    def _autosave(self, event=None):
        """Persists all settings — bound to <Unmap> (tab switch / minimize)."""
        if not self.winfo_exists():
            return
        self._sync_state_from_widgets()
        save_settings(self._settings_snapshot())

    # ------------------------------------------------------------------ #
    #  Theme
    # ------------------------------------------------------------------ #
    def _show_theme_preview(self, theme_name):
        """Point the big swatches + name label at `theme_name`."""
        if not self.winfo_exists():
            return
        palette = get_theme(theme_name)
        self.theme_primary_swatch.configure(fg_color=palette["primary"])
        self.theme_secondary_swatch.configure(fg_color=palette["secondary"])
        self.theme_name_label.configure(text=theme_name)

    def _on_theme_change(self, value):
        """Commits a theme pick — persists it and live-applies it across the
        whole app immediately (same as appearance mode). apply_theme rebuilds
        this tab, so nothing below the call may touch self."""
        if value == load_settings().get("theme"):
            return
        self._sync_state_from_widgets()
        save_settings(self._settings_snapshot(theme=value))
        self.app.apply_theme(value)

    # ------------------------------------------------------------------ #
    #  Appearance / save location / GPU
    # ------------------------------------------------------------------ #
    def _on_appearance_change(self, value):
        """Live-switches light/dark/system appearance mode and persists it."""
        ctk.set_appearance_mode(value.lower())
        # CTk's own widgets re-theme themselves automatically on this call;
        # the info badge doesn't (it's a PIL composite, not a CTk-drawn
        # widget), so it needs an explicit nudge to update right away rather
        # than waiting on some unrelated repaint.
        self.app.refresh_previews_appearance()
        save_settings(self._settings_snapshot())

    def _browse_save_location(self):
        """Lets the user pick the folder new outputs default into (also the
        starting directory for the Encoding/Muxing save dialogs)."""
        folder = filedialog.askdirectory(title="Select Default Save Location")
        if folder:
            self.app.default_save_location = folder
            self.save_location_entry.delete(0, "end")
            self.save_location_entry.insert(0, folder)
            save_settings(self._settings_snapshot())

    def _on_gpu_toggle(self):
        """Flips the global hardware-acceleration preference and persists it."""
        self.app.gpu_enabled = bool(self.gpu_switch.get())
        save_settings(self._settings_snapshot())

    def _on_save(self):
        """Explicit Save — redundant with the auto-saves, kept for clarity/
        reassurance. Only falls back to apply_theme if the selection somehow
        didn't already live-apply."""
        new_theme = self._selected_theme
        theme_changed = new_theme != load_settings().get("theme")
        self._sync_state_from_widgets()
        save_settings(self._settings_snapshot())
        if theme_changed:
            # apply_theme rebuilds this tab (and clears toasts on the way), so
            # the rebuild itself is the feedback — nothing to post here.
            self.app.apply_theme(new_theme)
            return
        self.app.notify("Settings saved.", go_to_queue=False)
