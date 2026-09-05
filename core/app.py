import sys
import customtkinter as ctk
from tkinterdnd2 import TkinterDnD
from PIL import Image

from core.utilities import extract_video_thumbnail
from core.theme import get_active_theme, load_settings, apply_ctk_theme
from components.sidebar import Sidebar
from tabs.muxing_tab import MuxingTab
from tabs.encoding_tab import EncodingTab
from tabs.queue_tab import QueueTab
from tabs.ytdlp_tab import YtDlpTab
from tabs.settings_tab import SettingsTab

class LlamaGUI(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self):
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)

        # Window Setup
        width, height = self.winfo_screenwidth(), self.winfo_screenheight()
        # 0.375 = a quarter shorter than the 0.5 this briefly was. 0.5 fixed
        # an earlier bug where the window was too short for its content and
        # the packer silently compressed the DropBox below its configured
        # size — but it also made the window look too square. The DropBox's
        # expand+fill still lets it shrink gracefully at this shorter height;
        # it just won't grow as tall as it did at 0.5.
        scaled_w, scaled_h = int(width * 0.35), int(height * 0.375)
        x_center = (width - scaled_w) // 2
        y_center = (height - scaled_h) // 2
        self.geometry(f"{scaled_w}x{scaled_h}+{x_center}+{y_center}")
        self.title("LlamaMXD")
        self.iconbitmap("llama.ico")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Grid Config
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # Shared State & Registry
        self.current_file_path = ""
        self.default_save_location = load_settings()["default_save_location"]
        self.tab_ui_registry = []
        self._tab_indicator_job = None
        self._current_tab_name = "Muxing"

        # Loads (generating on first use) a CTk theme JSON where every
        # default-styled widget's accent color — checkboxes, switches,
        # sliders, dropdowns, the sidebar's nav buttons — has been swapped
        # to the active theme's secondary color. Must happen before any
        # widget below is constructed; see core/theme.py's apply_ctk_theme.
        apply_ctk_theme(load_settings()["theme"])

        # UI Components
        self.sidebar = Sidebar(master=self, app=self)
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        # Active-tab indicator: a strip of the brand primary color that
        # pokes out from behind the sidebar into the gutter beside whichever
        # sidebar button is active, rather than recoloring the button or
        # adding a highlight. Placed with .place() so it can float
        # independently of the grid, and lowered so the sidebar and the
        # active tab's own frame (both opaque) render on top of it wherever
        # they overlap — only the uncovered sliver in between actually
        # shows through.
        self.tab_indicator = ctk.CTkFrame(master=self, fg_color=get_active_theme()["primary"], corner_radius=0)
        self.tab_indicator.lower()

        # Tabs
        self.tabs = {
            "Muxing": MuxingTab(master=self, app=self),
            "Encoding": EncodingTab(master=self, app=self),
            "Queue": QueueTab(master=self, app=self),
            "YT-DLP": YtDlpTab(master=self, app=self),
            "Settings": SettingsTab(master=self, app=self),
        }
        self.show_tab("Muxing")

    def register_tab_ui(self, label_widget, img_widget, on_thumbnail=None):
        """Registers a tab's UI controls for batch cross-tab updates."""
        if on_thumbnail is None:
            def on_thumbnail(pil_img, _img_widget=img_widget):
                ctk_img = ctk.CTkImage(
                    light_image=pil_img, dark_image=pil_img, size=(350, 200)
                )
                _img_widget.configure(image=ctk_img, text="")

        self.tab_ui_registry.append(
            {"label": label_widget, "img": img_widget, "on_thumbnail": on_thumbnail}
        )

    def update_global_file(self, file_path):
        """Central method triggered by drop box imports."""
        clean_path = file_path.strip("{}").strip()
        if not clean_path:
            return

        self.current_file_path = clean_path
        raw_thumbnail = extract_video_thumbnail(self.current_file_path)

        for ui in self.tab_ui_registry:
            if ui["label"]:
                ui["label"].configure(text=f"Selected File:\n{self.current_file_path}")
            if raw_thumbnail is not None:
                ui["on_thumbnail"](raw_thumbnail)

        for tab in self.tabs.values():
            if hasattr(tab, "drop_box"):
                tab.drop_box.hide_drop_text()

    def show_tab(self, name):
        self._current_tab_name = name
        for tab in self.tabs.values():
            tab.grid_forget()
        self.tabs[name].grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        # Deferred: the very first call happens during __init__, before
        # mainloop() has run even once — at that point the sidebar buttons
        # haven't actually been mapped onscreen yet, so winfo_height() on
        # them still reports a stale placeholder (1px), even after
        # update_idletasks() and even via after_idle (still too early — the
        # window hasn't received its first <Configure>/map pass yet). A short
        # real delay gives mainloop time to actually map the window first.
        # Cancel any not-yet-fired update so switching tabs quickly can't
        # leave a stale, out-of-order callback overwriting a newer one.
        if self._tab_indicator_job is not None:
            self.after_cancel(self._tab_indicator_job)
        self._tab_indicator_job = self.after(50, lambda: self._update_tab_indicator(name))

    def _update_tab_indicator(self, name):
        """Aligns the accent strip's vertical span with the active sidebar button."""
        button = self.sidebar.buttons.get(name)
        if not button:
            return

        self.update_idletasks()
        sidebar_width = self.sidebar.winfo_width()
        # Straddles the sidebar/content seam: starts a little inside the
        # sidebar (invisible there — same yellow) and tucks a little under
        # the tab frame's left edge (hidden — the frame renders on top).
        # CTk widgets take width/height via configure(), not place().
        self.tab_indicator.configure(width=24, height=button.winfo_height())
        self.tab_indicator.place(x=sidebar_width - 8, y=button.winfo_y())

    def apply_theme(self, theme_name):
        """Live-applies a theme with no restart required. CTk never
        retroactively recolors an already-built widget — set_default_
        color_theme only affects widgets constructed *after* the call — so
        the only way to make every default-styled control (checkboxes,
        switches, sliders, dropdowns, the sidebar's nav buttons) genuinely
        change color live is to reload the theme and then rebuild the
        widgets that read it.

        Muxing/Encoding/YT-DLP/Settings are destroyed and rebuilt from
        scratch; Muxing/Encoding's field values are snapshotted first and
        restored via load_settings() so the user doesn't lose an in-progress
        form. The Queue tab is deliberately *not* rebuilt — destroying it
        would discard its task list — it instead gets its own in-place
        QueueTab.refresh_theme() call, recoloring its already-built widgets
        without touching self._rows or any in-flight animation."""
        apply_ctk_theme(theme_name)

        muxing_settings = self.tabs["Muxing"]._gather_settings()
        encoding_settings = self.tabs["Encoding"]._gather_settings()
        active_tab_name = self._current_tab_name

        self.sidebar.destroy()
        self.tab_indicator.destroy()
        for name in ("Muxing", "Encoding", "YT-DLP", "Settings"):
            self.tabs[name].destroy()
        self.tab_ui_registry = []  # entries above pointed at widgets just destroyed

        self.sidebar = Sidebar(master=self, app=self)
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        self.tab_indicator = ctk.CTkFrame(master=self, fg_color=get_active_theme()["primary"], corner_radius=0)
        self.tab_indicator.lower()

        self.tabs["Muxing"] = MuxingTab(master=self, app=self)
        self.tabs["Encoding"] = EncodingTab(master=self, app=self)
        self.tabs["YT-DLP"] = YtDlpTab(master=self, app=self)
        self.tabs["Settings"] = SettingsTab(master=self, app=self)

        self.tabs["Muxing"].load_settings(muxing_settings)
        self.tabs["Encoding"].load_settings(encoding_settings)
        self.tabs["Queue"].refresh_theme()

        self.show_tab(active_tab_name)

    def on_close(self):
        self.destroy()
        sys.exit(0)