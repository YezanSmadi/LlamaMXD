import os
import re
import customtkinter as ctk
from tkinter import filedialog
from tkinterdnd2 import DND_TEXT

from components.dialogs import confirm_output_path, show_message
from components.dropdown import ThemedDropdown
from components.marquee_label import MarqueeLabel
from core import downloader
from core.theme import get_active_theme

_DISABLED_LABEL = "gray50"
_NO_OPTION = "—"
_TAB = "Downloader"

# The Deno warning is a fixed amber, not theme-driven — like STOP_RED, a
# warning shouldn't change colour with the palette.
_WARN_BG = ("#FFF1C2", "#4A3A0E")
_WARN_TEXT = ("#5C4300", "#F6D77E")

# Extensions the save field can end in, so an extension swap never mistakes
# part of a title ("v1.2 final") for one.
_KNOWN_EXTS = set(downloader.VIDEO_CONTAINERS) | set(downloader.AUDIO_CONVERSIONS) | {
    ".webm", ".m4a", ".mp4", ".mkv", ".ogg", ".mp3", ".aac", ".flv", ".3gp", ".mov"}

# Room kept under the thumbnail for the title + details lines.
_INFO_ROWS_HEIGHT = 50

# What a dropped link has to look like to be accepted — see _on_link_drop.
_URL_RE = re.compile(r"^https?://\S+$")


def _human_size(num_bytes):
    """Bytes as "268 MB" / "1.3 GB"."""
    if not num_bytes:
        return ""
    mb = num_bytes / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    return f"{mb:.1f} MB" if mb < 10 else f"{mb:.0f} MB"


def _hms(total_seconds):
    """Seconds as H:MM:SS / M:SS."""
    total_seconds = int(total_seconds or 0)
    hours, rest = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


class YtDlpTab(ctk.CTkFrame):
    """Downloads a video (or just its audio) from a link, through the queue.

    A link can be pasted, typed, or dragged onto the preview box — the box
    only registers DND_TEXT (never DND_FILES, unlike the media tabs' file
    DropBox), and `_on_link_drop` re-checks the dropped text is one real
    http(s) link before treating it as anything, so a link is the only thing
    actually draggable onto it.

    Fetch runs `yt-dlp -J` on a worker (`LlamaGUI.fetch_ytdlp_info`) and the
    result — cached on the app, so a live theme rebuild never re-fetches —
    drives every dropdown here. The option tree is one-directional, same as
    the other tabs, and decided in one place (`_sync_controls`): Mode ->
    Video Codec -> Quality -> Format, where each list only ever holds what
    this video can really deliver without re-encoding (see
    `core/downloader.py`). Video + Audio inserts Audio Codec between Video
    Codec and Quality visually (Video Codec -> Audio Codec -> Quality ->
    Video Format on screen), but resolves it right after Quality internally
    so Video Format can adapt to fit whichever audio codec was picked,
    rather than the audio pick being limited to whatever Format already
    held. Audio Only swaps Format and Quality entirely, since its bitrate
    choices depend on whether the output is the original stream or a
    conversion.

    Every dropdown's `command` is wired at construction (`_panel_dropdown`'s
    `command` param), not via a later `.configure(command=...)` — see that
    method's docstring for why the latter is a silent no-op on
    `ThemedDropdown` and was actually the bug behind an early version of
    this tab where picking a value never re-ran `_sync_controls` at all,
    leaving the size estimate (and everything else _sync_controls drives)
    looking frozen after the initial fetch.

    Queueing hands `core.downloader.resolve()`'s exact plan to the queue as
    the task's `download` key; `core.ytdlp_runner.YtDlpJob` runs it."""

    def __init__(self, master, app):
        super().__init__(master=master)
        self.app = app
        theme = get_active_theme()
        self._label_color = ctk.ThemeManager.theme["CTkLabel"]["text_color"]
        self._ready = False
        # The fetched video: its URL (which the queued job uses, even if the
        # entry has been edited since), yt-dlp's info, the parsed format
        # list, the thumbnail, and the resolved plan for the current picks.
        self._url = None
        self._info = None
        self._fmts = []
        self._thumb = None
        self._thumb_image = None
        self._plan = None
        self._fetching = False
        self._last_mode = None
        self._resize_job = None
        self._fitted_size = None

        # --- Bottom Section: Fixed Controls ---
        self.controls_frame = ctk.CTkFrame(master=self, fg_color="transparent")
        self.controls_frame.pack(side="bottom", fill="x", padx=10, pady=(0, 4))

        self.mode_row = ctk.CTkFrame(master=self.controls_frame, fg_color="transparent")
        self.mode_row.pack(fill="x", pady=(2, 2))
        self.mode_label = ctk.CTkLabel(master=self.mode_row, text="Mode:", font=("Arial", 12, "bold"))
        self.mode_label.pack(anchor="w", pady=(0, 1))
        self.mode_switch = ctk.CTkSegmentedButton(
            master=self.mode_row, values=downloader.MODES, command=self._on_control_change,
        )
        self.mode_switch.set(downloader.MODE_AV)
        self.mode_switch.pack(anchor="w")

        self.options_row = ctk.CTkFrame(master=self.controls_frame, fg_color="transparent")
        self.options_row.pack(fill="x", pady=(2, 4))
        self.codec_label, self.codec_menu = self._panel_dropdown(
            self.options_row, "Video Codec:", [downloader.BEST_CODEC], 132,
            command=self._on_control_change,
        )
        self.quality_label, self.quality_menu = self._panel_dropdown(
            self.options_row, "Quality:", [downloader.BEST_QUALITY], 120, padx=(10, 0),
            command=self._on_control_change,
        )
        self.format_label, self.format_menu = self._panel_dropdown(
            self.options_row, "Video Format:", [".mp4"], 96, padx=(10, 0),
            command=self._on_control_change,
        )
        # Video + Audio only: the separate audio stream's codec, positioned
        # *before* Quality's own frame — see _show_audio_picker. Built here
        # (after Video Format) purely because _panel_dropdown needs a parent
        # to pack into; immediately unpacked so it starts hidden like the
        # other modes leave it, and so _show_audio_picker's own
        # `not self.audio_frame.winfo_manager()` check (its signal for "this
        # is a hidden->shown transition, reposition it") is actually true the
        # first time a fetch lands in AV mode — otherwise this would show up
        # in *this* construction-time position (after Video Format) forever,
        # since _sync_controls doesn't even call _show_audio_picker until
        # something's been fetched (has_info is False until then).
        self.audio_label, self.audio_menu = self._panel_dropdown(
            self.options_row, "Audio Codec:", [downloader.BEST_CODEC], 132, padx=(10, 0),
            command=self._on_control_change,
        )
        self.audio_frame = self.audio_menu.master
        self.audio_frame.pack_forget()
        # Estimated download size for the current picks, beside the dropdowns.
        self.size_label = ctk.CTkLabel(
            master=self.options_row, text="", font=("Arial", 12), text_color=_DISABLED_LABEL,
        )
        self.size_label.pack(side="left", anchor="s", padx=(12, 0), pady=(0, 3))

        # Save Location Section
        self.save_frame = ctk.CTkFrame(master=self.controls_frame, fg_color="transparent")
        self.save_frame.pack(fill="x", pady=4)
        self.save_entry = ctk.CTkEntry(master=self.save_frame, placeholder_text="Save file as...")
        self.save_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        if self.app.default_save_location:
            self.save_entry.insert(0, self.app.default_save_location)
        self.browse_save_btn = ctk.CTkButton(
            master=self.save_frame, text="Browse", width=80, command=self.select_save_location
        )
        self.browse_save_btn.pack(side="right")

        # Action Buttons Row: Queue Task (secondary) + Download (primary)
        self.action_frame = ctk.CTkFrame(master=self.controls_frame, fg_color="transparent")
        self.action_frame.pack(fill="x", pady=(5, 0))
        self.action_frame.grid_columnconfigure(0, weight=1, uniform="action")
        self.action_frame.grid_columnconfigure(1, weight=1, uniform="action")
        self.queue_btn = ctk.CTkButton(
            master=self.action_frame, text="Queue Task",
            fg_color=theme["secondary"], hover_color=theme["secondary_hover"],
            text_color=theme["secondary_text"], command=self.add_to_queue,
        )
        self.queue_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.download_btn = ctk.CTkButton(
            master=self.action_frame, text="Download",
            fg_color=theme["primary"], hover_color=theme["primary_hover"],
            text_color=theme["primary_text"], text_color_disabled=theme["primary_disabled_text"],
            command=self.download_now,
        )
        self.download_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        # --- Top Flexible Section ---
        self.top_container = ctk.CTkFrame(master=self, fg_color="transparent")
        self.top_container.pack(side="top", fill="both", expand=True, padx=10, pady=(5, 5))

        # Deno warning — packed only while the startup check says it's
        # missing (`set_deno_missing`). Warn-only: nothing is blocked, and
        # most sites don't need Deno at all.
        self.deno_banner = ctk.CTkFrame(master=self.top_container, fg_color=_WARN_BG, corner_radius=6)
        self.deno_banner_label = ctk.CTkLabel(
            master=self.deno_banner, text_color=_WARN_TEXT, font=("Arial", 12), anchor="w",
            text="⚠  Deno wasn't found — YouTube downloads may be limited or fail. Reinstall LlamaMXD.",
        )
        self.deno_banner_label.pack(fill="x", padx=10, pady=4)

        self.url_row = ctk.CTkFrame(master=self.top_container, fg_color="transparent")
        self.url_row.pack(fill="x", pady=(0, 6))
        self.url_entry = ctk.CTkEntry(master=self.url_row, placeholder_text="Paste a video link here...")
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.url_entry.bind("<Return>", lambda _e: self.fetch())
        # text_color_disabled matches the enabled text_color on purpose: the
        # button is disabled while "Fetching..." purely to block a second
        # click, not to look inactive, so its text shouldn't fade at all.
        self.fetch_btn = ctk.CTkButton(
            master=self.url_row, text="Fetch", width=80,
            fg_color=theme["primary"], hover_color=theme["primary_hover"],
            text_color=theme["primary_text"], text_color_disabled=theme["primary_text"],
            command=self.fetch,
        )
        self.fetch_btn.pack(side="right")
        self.paste_btn = ctk.CTkButton(
            master=self.url_row, text="Paste", width=70, command=self.paste_and_fetch
        )
        self.paste_btn.pack(side="right", padx=(0, 5))

        # Preview: the DropBox's bordered look while empty, the thumbnail +
        # title once a fetch lands.
        self.preview_frame = ctk.CTkFrame(
            master=self.top_container, corner_radius=10, border_width=2,
            border_color=theme["primary"],
        )
        self.preview_frame.pack(fill="both", expand=True)
        self.preview_frame.pack_propagate(False)

        self.placeholder_label = ctk.CTkLabel(
            master=self.preview_frame, font=ctk.CTkFont(size=14),
            text="Paste a video link above, then press Fetch.",
        )
        self.placeholder_label.pack(expand=True)

        self.thumb_label = ctk.CTkLabel(master=self.preview_frame, text="")
        self.info_frame = ctk.CTkFrame(master=self.preview_frame, fg_color="transparent")
        self.title_label = MarqueeLabel(
            master=self.info_frame, text="", font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
        )
        self.title_label.pack(fill="x")
        self.meta_label = ctk.CTkLabel(
            master=self.info_frame, text="", font=("Arial", 12), anchor="w", text_color=_DISABLED_LABEL
        )
        self.meta_label.pack(fill="x")
        self.preview_frame.bind("<Configure>", self._on_preview_resize, add="+")

        # Links are draggable onto the preview box — and the *only* thing
        # draggable onto it, unlike the media tabs' file DropBox. Only
        # DND_TEXT is registered (never DND_FILES), so a dragged file is
        # never even offered a drop; bound on every widget that can visually
        # sit on top of the box (empty placeholder, or a loaded thumbnail +
        # title/meta), same reasoning as DropBox's own multi-widget binding —
        # tkdnd doesn't propagate a drop target registration to children.
        for widget in (self.preview_frame, self.placeholder_label, self.thumb_label,
                       self.info_frame, self.title_label, self.meta_label):
            widget.drop_target_register(DND_TEXT)
            widget.dnd_bind("<<Drop>>", self._on_link_drop)

        if getattr(self.app, "deno_missing", False):
            self.set_deno_missing(True)
        self._sync_controls()
        self._ready = True

    # ------------------------------------------------------------------ #
    #  Building blocks
    # ------------------------------------------------------------------ #
    def _panel_dropdown(self, parent, label_text, values, width, padx=(0, 0), command=None):
        """Bold label above a ThemedDropdown in its own frame, packed left
        into `parent`. Returns `(label, menu)`.

        `command` MUST be passed here, at construction — not wired up later
        via `menu.configure(command=...)`. ThemedDropdown never uses the
        native CTkOptionMenu selection path (its whole point is a custom
        popup — see components/dropdown.py), so `_select` calls
        `self._user_command`, which is only ever set from the `command`
        kwarg *inside* `CTkOptionMenu.__init__`. A later `.configure(command=
        ...)` just sets the base class's unused `self._command` instead —
        confirmed directly: a menu wired that way never re-ran
        `_sync_controls` on a manual pick, which is what made the file-size
        estimate (and every other cascade update — Quality/Format/Audio
        retargeting) look "stuck" after fetching, changing only when Mode
        was touched (a plain CTkSegmentedButton, unaffected by this)."""
        frame = ctk.CTkFrame(master=parent, fg_color="transparent")
        frame.pack(side="left", anchor="s", padx=padx)
        label = ctk.CTkLabel(master=frame, text=label_text, font=("Arial", 12, "bold"))
        label.pack(anchor="w", pady=(0, 1))
        menu = ThemedDropdown(master=frame, values=values, width=width, command=command)
        menu.pack(anchor="w")
        return label, menu

    def set_deno_missing(self, missing):
        """Shows or hides the Deno warning (the app's startup check calls
        this once its answer lands)."""
        if missing and not self.deno_banner.winfo_ismapped():
            self.deno_banner.pack(fill="x", pady=(0, 6), before=self.url_row)
        elif not missing and self.deno_banner.winfo_ismapped():
            self.deno_banner.pack_forget()

    # ------------------------------------------------------------------ #
    #  Fetch
    # ------------------------------------------------------------------ #
    def paste_and_fetch(self):
        """Replaces the link with the clipboard's text and fetches it."""
        try:
            text = self.clipboard_get().strip()
        except Exception:
            text = ""
        if not text:
            return
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, text)
        self.fetch()

    def _on_link_drop(self, event):
        """A link was dragged onto the preview box: fills the URL entry and
        fetches it, same as Paste. Only DND_TEXT is registered on this box
        (never DND_FILES — see __init__), but that alone still accepts any
        dragged text, not just a link, so this re-checks the dropped string
        actually looks like one real http(s) link before doing anything with
        it; anything else (a file, a sentence, several links at once) is
        silently ignored rather than fed to Fetch."""
        text = (event.data or "").strip()
        if text.startswith("{") and text.endswith("}"):
            text = text[1:-1].strip()
        if not _URL_RE.match(text):
            return
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, text)
        self.fetch()

    def fetch(self):
        """Starts fetching the entered link's info off the Tk thread."""
        url = self.url_entry.get().strip()
        if not url:
            show_message(self.app, "No Link", "Paste a video link first, then press Fetch.")
            return
        self._fetching = True
        self.fetch_btn.configure(text="Fetching...", state="disabled")
        if not self._info:
            self.placeholder_label.configure(text="Fetching video info...")
        self.app.fetch_ytdlp_info(url)

    def on_ytdlp_info(self, url, info, error, thumb):
        """A fetch landed (delivered on the Tk thread by the app)."""
        self._fetching = False
        self.fetch_btn.configure(text="Fetch", state="normal")
        if error:
            if not self._info:
                self.placeholder_label.configure(text="Paste a video link above, then press Fetch.")
            # after(0): a modal blocks in a nested event loop, and this runs
            # inside the app's worker poll — never open one from a tick.
            self.after(0, lambda: show_message(self.app, "Couldn't Fetch Link", error))
            return
        self._apply_info(url, info, thumb)
        self._autofill_output_path()

    def _apply_info(self, url, info, thumb):
        """Adopts a fetched video: resets every pick to its best default and
        shows the preview."""
        self._url, self._info, self._thumb = url, info, thumb
        self._fmts = downloader.parse_formats(info)
        self._fitted_size = None

        was_ready, self._ready = self._ready, False
        try:
            modes = downloader.modes_for(self._fmts)
            self.mode_switch.configure(values=downloader.MODES)
            self.mode_switch.set(modes[0] if modes else downloader.MODE_AV)
            self.codec_menu.set(downloader.BEST_CODEC)
            self.quality_menu.set(downloader.BEST_QUALITY)
            self.format_menu.set(".mp4")
            self.audio_menu.set(downloader.BEST_CODEC)
            self._last_mode = None
            self._sync_controls()
        finally:
            self._ready = was_ready

        self.placeholder_label.pack_forget()
        self.info_frame.pack(side="bottom", fill="x", padx=12, pady=(0, 8))
        self.thumb_label.pack(side="top", expand=True, pady=(8, 4))
        self.title_label.configure(text=info.get("title") or "Untitled")
        self._refresh_meta()
        self._fit_thumbnail()

    # ------------------------------------------------------------------ #
    #  Preview
    # ------------------------------------------------------------------ #
    def _on_preview_resize(self, _event=None):
        """Re-fits the thumbnail after the preview area changes size
        (debounced — Configure fires several times during layout)."""
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(40, self._fit_thumbnail)

    def _fit_thumbnail(self):
        """Scales the thumbnail to the largest size that fits the preview."""
        self._resize_job = None
        if self._thumb is None or not self.preview_frame.winfo_exists():
            self.thumb_label.configure(image=None)
            return
        scaling = self._get_widget_scaling()
        avail_w = self.preview_frame.winfo_width() / scaling - 24
        avail_h = self.preview_frame.winfo_height() / scaling - _INFO_ROWS_HEIGHT - 20
        if avail_w < 20 or avail_h < 20:
            return
        ratio = min(avail_w / self._thumb.width, avail_h / self._thumb.height)
        size = (max(1, int(self._thumb.width * ratio)), max(1, int(self._thumb.height * ratio)))
        if size == self._fitted_size:
            return
        self._fitted_size = size
        self._thumb_image = ctk.CTkImage(light_image=self._thumb, dark_image=self._thumb, size=size)
        self.thumb_label.configure(image=self._thumb_image)

    def _refresh_meta(self):
        """The details line under the title: uploader and length."""
        info = self._info or {}
        bits = [b for b in (info.get("uploader") or info.get("channel"),
                            _hms(info.get("duration")) if info.get("duration") else "") if b]
        self.meta_label.configure(text="  ·  ".join(bits))

    # ------------------------------------------------------------------ #
    #  The single constraint pass
    # ------------------------------------------------------------------ #
    def _on_control_change(self, *_):
        """Any control changed — re-derive everything."""
        self._sync_controls()

    def _sync_controls(self, *_):
        """Rewrites every dependent option list, selection and enabled state
        from the current picks. Idempotent; the one place the rules live.

        1. Nothing fetched -> every download control is disabled.
        2. Mode offers only the modes this video supports.
        3. Video Codec lists the codecs that mode can use.
        4. Video modes: Quality (the codec's resolutions) -> in Video +
           Audio, Audio Codec (every codec a real separate audio stream
           actually offers, independent of Format) -> Format (the containers
           that fit the video pick *and* whichever audio codec was just
           picked) — resolved in that order (Audio Codec before Format) so a
           real audio codec beyond the default isn't hidden behind Format's
           own default pick, even though Audio Codec is *displayed* earlier
           still, ahead of Quality (see _show_audio_picker). Audio Only:
           Format (Original or a conversion) -> Quality (source bitrates,
           target bitrates, or nothing for lossless).
        5. The resolved plan drives the size estimate and output extension.
        A snap caused by the user's own change toasts; one caused by
        switching Mode (whose lists are a different kind) doesn't."""
        has_info = bool(self._fmts)
        for widget, label in ((self.mode_switch, self.mode_label), (self.codec_menu, self.codec_label),
                              (self.quality_menu, self.quality_label), (self.format_menu, self.format_label)):
            self._set_enabled(widget, label, has_info)
        self._set_enabled(self.audio_menu, self.audio_label, has_info)
        for button in (self.queue_btn, self.download_btn):
            button.configure(state="normal" if has_info else "disabled")
        if not has_info:
            self._plan = None
            self.size_label.configure(text="")
            return

        fmts = self._fmts
        modes = downloader.modes_for(fmts)
        if self.mode_switch.get() not in modes and modes:
            self.mode_switch.set(modes[0])
        mode = self.mode_switch.get()
        mode_changed = self._last_mode is not None and mode != self._last_mode
        announce = self._ready and not mode_changed
        self._last_mode = mode
        self._show_audio_picker(mode)

        codecs = downloader.codecs_for(fmts, mode)
        self._retarget(self.codec_menu, codecs, downloader.BEST_CODEC, "Video Codec" if announce else None)
        codec = self.codec_menu.get()

        audio_codec = downloader.BEST_CODEC
        if mode == downloader.MODE_AUDIO:
            allowed = downloader.formats_for(fmts, mode, codec, None)
            self._retarget(self.format_menu, allowed, downloader.default_format(mode, allowed),
                           "Audio Format" if announce else None)
            qualities = downloader.qualities_for(fmts, mode, codec, self.format_menu.get())
            self._retarget(self.quality_menu, qualities, qualities[0] if qualities else None,
                           "Quality" if announce else None)
        else:
            qualities = downloader.qualities_for(fmts, mode, codec)
            self._retarget(self.quality_menu, qualities, downloader.BEST_QUALITY,
                           "Quality" if announce else None)
            quality = self.quality_menu.get()

            # Audio is resolved before Format in this mode (and only this
            # mode) so a real audio codec beyond the default isn't hidden
            # behind whatever container Format happens to already hold —
            # see audio_codecs_for/formats_for.
            if mode == downloader.MODE_AV:
                audio_codecs = downloader.audio_codecs_for(fmts, mode, codec, quality)
                self._retarget(self.audio_menu, audio_codecs, downloader.BEST_CODEC,
                               "Audio Codec" if announce else None)
                self._set_enabled(self.audio_menu, self.audio_label, bool(audio_codecs))
                audio_codec = self._menu_value(self.audio_menu) or downloader.BEST_CODEC

            allowed = downloader.formats_for(fmts, mode, codec, quality, audio_codec)
            self._retarget(self.format_menu, allowed, downloader.default_format(mode, allowed),
                           "Video Format" if announce else None)
        self._set_enabled(self.quality_menu, self.quality_label, bool(qualities))
        self._set_enabled(self.format_menu, self.format_label, bool(allowed))

        self._plan = downloader.resolve(
            fmts, mode, codec, self._menu_value(self.quality_menu), self._menu_value(self.format_menu),
            (self._info or {}).get("duration") or 0, audio_codec=audio_codec,
        )
        if self._plan:
            size = sum(p["size"] for p in self._plan["parts"])
            if self._plan["post"] and self._plan["post"]["kind"] == "convert":
                size = self._plan["post"]["expected_bytes"]
            text = _human_size(size)
            self.size_label.configure(text=f"≈ {text}" if text else "")
            self._apply_output_extension(self._plan["ext"])
        else:
            self.size_label.configure(text="")

    def _show_audio_picker(self, mode):
        """Video + Audio shows Audio Codec, placed *before* Quality (so the
        row reads Video Codec -> Audio Codec -> Quality -> Video Format);
        the other modes hide it and the surviving Format dropdown is
        relabelled "Audio Format:" for Audio Only, "Video Format:" otherwise."""
        show = mode == downloader.MODE_AV
        if show and not self.audio_frame.winfo_manager():
            self.audio_frame.pack(side="left", anchor="s", padx=(10, 0), before=self.quality_menu.master)
        elif not show and self.audio_frame.winfo_manager():
            self.audio_frame.pack_forget()
        self.format_label.configure(
            text="Audio Format:" if mode == downloader.MODE_AUDIO else "Video Format:"
        )

    def _retarget(self, menu, values, default, what=None):
        """Points a derived dropdown at a fresh option list, snapping to
        `default` when the current pick is no longer in it — and saying so
        in a toast when `what` is given (a silent swap feels haunted)."""
        before = menu.get()
        menu.set_values(values or [_NO_OPTION])
        if values and before not in values:
            menu.set(default if default in values else values[0])
        after = menu.get()
        if what and before != after and before != _NO_OPTION and values:
            self.app.notify(f"{what} switched to {after} — {before} isn't available for this pick.",
                            go_to_queue=False)

    def _set_enabled(self, widget, label, enabled):
        """Enables/disables a control and dims its label to match."""
        widget.configure(state="normal" if enabled else "disabled")
        if label is not None:
            label.configure(text_color=self._label_color if enabled else _DISABLED_LABEL)

    @staticmethod
    def _menu_value(menu):
        """A dropdown's value, or None for the `—` placeholder."""
        value = menu.get()
        return None if value == _NO_OPTION else value

    # ------------------------------------------------------------------ #
    #  Output path
    # ------------------------------------------------------------------ #
    def _current_directory(self):
        """The folder part of the save field — which may hold a full file
        path or a bare folder (fresh off __init__), told apart by a known
        extension so a folder's last segment is never stripped off."""
        current = self.save_entry.get().strip().replace("\\", "/")
        root, ext = os.path.splitext(current)
        directory = os.path.dirname(current) if ext.lower() in _KNOWN_EXTS else current
        return directory or self.app.default_save_location or ""

    def _autofill_output_path(self):
        """After a fetch: '<current folder>/<video title><ext>'. Like the
        other tabs, the FILENAME always follows the newly-fetched video and
        only the folder persists."""
        if not self._info:
            return
        ext = self._plan["ext"] if self._plan else ".mp4"
        stem = downloader.safe_stem(self._info.get("title"))
        path = os.path.normpath(os.path.join(self._current_directory(), stem + ext))
        self.save_entry.delete(0, "end")
        self.save_entry.insert(0, path)

    def _apply_output_extension(self, ext):
        """Swaps the save field's extension to `ext` when it has one."""
        current = self.save_entry.get().strip()
        root, old = os.path.splitext(current)
        if old and old.lower() in _KNOWN_EXTS and old.lower() != ext.lower():
            self.save_entry.delete(0, "end")
            self.save_entry.insert(0, root + ext)

    def select_save_location(self):
        """Lets the user pick a full output FILE path."""
        ext = self._plan["ext"] if self._plan else ".mp4"
        stem = downloader.safe_stem((self._info or {}).get("title")) if self._info else "download"
        path = filedialog.asksaveasfilename(
            title="Select Output File",
            initialdir=self._current_directory(),
            initialfile=stem + ext,
            defaultextension=ext,
            filetypes=[(f"{ext.lstrip('.').upper()} File", f"*{ext}"), ("All Files", "*.*")],
        )
        if path:
            self.save_entry.delete(0, "end")
            self.save_entry.insert(0, path)
            self._sync_controls()

    # ------------------------------------------------------------------ #
    #  Settings in / out
    # ------------------------------------------------------------------ #
    def _gather_settings(self):
        """The current download as a plain dict. `download` is the resolved
        plan the queue's YtDlpJob runs; the rest is what the details popup
        shows and what a theme rebuild restores."""
        info = self._info or {}
        return {
            "url": self._url or self.url_entry.get().strip(),
            "title": info.get("title") or "",
            "thumbnail_url": info.get("thumbnail") or "",
            "output_path": self.save_entry.get().strip(),
            "output_format": self._menu_value(self.format_menu) or "",
            "mode": self.mode_switch.get(),
            "video_codec": self.codec_menu.get(),
            # Only meaningful for Video + Audio; absent otherwise, so the
            # queue's details popup skips the row.
            **({"audio_codec": self._menu_value(self.audio_menu) or downloader.BEST_CODEC}
               if self.mode_switch.get() == downloader.MODE_AV else {}),
            "quality": self._menu_value(self.quality_menu) or "",
            "download": self._plan,
            "url_text": self.url_entry.get(),
        }

    def load_settings(self, settings):
        """Restores the form after a live theme rebuild, re-using the app's
        cached fetch rather than fetching again."""
        if not settings:
            return
        was_ready, self._ready = self._ready, False
        try:
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, settings.get("url_text") or "")
            cache = getattr(self.app, "ytdlp_cache", None)
            if cache and settings.get("url") and cache["url"] == settings["url"]:
                self._apply_info(cache["url"], cache["info"], cache["thumb"])
                self.mode_switch.set(settings.get("mode") or downloader.MODE_AV)
                self._last_mode = None
                self._sync_controls()
                for menu, key in ((self.codec_menu, "video_codec"), (self.format_menu, "output_format"),
                                  (self.quality_menu, "quality"), (self.format_menu, "output_format"),
                                  (self.audio_menu, "audio_codec")):
                    if settings.get(key) in menu.cget("values"):
                        menu.set(settings[key])
                    self._sync_controls()
            if settings.get("output_path"):
                self.save_entry.delete(0, "end")
                self.save_entry.insert(0, settings["output_path"])
        finally:
            self._ready = was_ready

    def _validate_settings(self, settings):
        """Checks a download is ready to queue."""
        if not self._info or not settings["download"]:
            show_message(self.app, "Nothing Fetched",
                         "Paste a video link and press Fetch before downloading.")
            return False
        if self.url_entry.get().strip() != self._url:
            show_message(self.app, "Link Changed",
                         "The link was edited after it was fetched. Press Fetch again so the "
                         "download matches what's in the box.")
            return False
        if not settings["output_path"]:
            show_message(self.app, "No Save Location",
                         "Choose where the download should be saved. Use Browse, or set a "
                         "default save location on the Settings tab.")
            return False
        queue_tab = self.app.tabs.get("Queue")
        claimed = bool(queue_tab and queue_tab.claims_output(settings["output_path"]))
        return confirm_output_path(self.app, settings["output_path"], None, claimed)

    # ------------------------------------------------------------------ #
    #  Queue hand-off
    # ------------------------------------------------------------------ #
    def _describe(self, settings):
        """A queue row's description line."""
        bits = [settings["mode"], settings["quality"], settings["output_format"]]
        return f"{settings['title'] or 'Download'}  ·  " + " · ".join(b for b in bits if b)

    def download_now(self):
        """Queues the download and starts it right away."""
        settings = self._gather_settings()
        if not self._validate_settings(settings):
            return
        queue_tab = self.app.tabs.get("Queue")
        if queue_tab:
            task_id = queue_tab.add_task(self._describe(settings), settings=settings,
                                         status="Queued", source_tab=_TAB)
            outcome = queue_tab.start_task(task_id)
            self.app.notify({
                "started": "Download has begun.",
                "next": "Download will run next.",
                "paused": "Download will run next — the queue is paused.",
            }[outcome])

    def add_to_queue(self):
        """Queues the download without starting it."""
        settings = self._gather_settings()
        if not self._validate_settings(settings):
            return
        queue_tab = self.app.tabs.get("Queue")
        if queue_tab:
            queue_tab.add_task(self._describe(settings), settings=settings,
                               status="Queued", source_tab=_TAB)
            self.app.notify("Download added to queue.")
