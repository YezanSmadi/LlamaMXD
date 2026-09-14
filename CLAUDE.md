# LlamaMXD (LlamaPY GUI)

A Windows desktop GUI for video muxing/encoding/downloading, built with
CustomTkinter. Wraps ffmpeg and yt-dlp behind a tabbed interface. Repo:
`https://github.com/YezanSmadi/LlamaMXD`. Public domain (Unlicense). Currently
v0.5.0-alpha.6 (see `components/sidebar.py`'s footer).

## Running

```bash
python main.py
```

Must be launched **from the repo root** — `core/app.py` and `components/sidebar.py`
load `assets/llama.ico` / `assets/llama.png` by relative path and will crash
otherwise. (`ThumbnailCarousel`'s `audio-mute.png` / `Wave Loop.json` are loaded
`__file__`-anchored to `assets/`, so those are launch-dir independent.)

Environment: Python 3.13, system interpreter (no venv). Dependencies are pinned
in `requirements.txt` (`pip install -r requirements.txt`) but still installed
globally in practice: `customtkinter` 6.0, `tkinterdnd2` 0.6.2, `opencv-python`
(cv2) 5.0, `Pillow` 11.3, `rlottie-python` 1.3.8 (the stripped-video preview's
Wave Loop animation — `ThumbnailCarousel`; a missing/broken import degrades to a
flat gradient wash, never a crash), `ffmpeg-python` 0.2.0 (+ its `future`
dependency — builds the ffmpeg commands), `yt-dlp[default]` 2026.08.19 (the
YT-DLP tab's dev environment; `default` pulls in `yt-dlp-ejs`, the YouTube JS
challenge solver — the app itself runs the bundled `yt-dlp.exe`, not this
package). No `deno` extra: pip puts `deno.exe` in the *user* Scripts folder,
which yt-dlp's own lookup doesn't search.

**External tools are bundled, not pip-installed**: `ffmpeg.exe`, `ffprobe.exe`,
`ffplay.exe` (unused so far, kept for later), `yt-dlp.exe` and `deno.exe` live
in `dependables/` at the repo root — **gitignored**, each is far over GitHub's
100MB file limit — and the release's setup wizard copies them beside the app.
Every launch goes through `core/tools.py` (see "External tools" below), so
nothing needs to be on PATH; PATH is only the last fallback.

## Architecture

```
main.py              entry point: sets appearance mode, constructs LlamaGUI, mainloop
core/app.py          LlamaGUI — the root window, owns shared state, tab routing, active-tab indicator
core/formats.py      container/codec compatibility + the option cascade (pure data, no Tk)
core/presets.py      named codec/quality recipes, persisted to presets.json
core/utilities.py    stateless helpers (thumbnail extraction, ffprobe media probe + duration)
core/ffmpeg_vars.py  one queued job's settings flattened into module globals (raw + ffmpeg-ready *_ARG)
core/ffmpeg_build.py builds a Mux or Encode job's ffmpeg-python Stream / full argv
core/ffmpeg_runner.py  runs one ffmpeg job off the Tk thread (progress, suspend/resume, stop)
core/tools.py        resolves ffmpeg/ffprobe/yt-dlp/deno to absolute paths (bundled first, then PATH)
core/downloader.py   YT-DLP logic, no Tk: fetch (-J), format model + option lists, resolve, argv
core/ytdlp_runner.py runs one download off the Tk thread (job object, stages, time-based progress)
components/          reusable widgets, tab-agnostic
tabs/                one CTkFrame subclass per tab
```

### External tools (`core/tools.py`)

`find_tool(name)` returns an absolute path or None; `tool_path(name)` the path
or the bare name (so a launch still raises the usual FileNotFoundError every
caller already turns into a readable message); `tool_dir(name)` the folder
(what yt-dlp's `--ffmpeg-location` wants). Search order: beside the frozen
app's exe or in a `dependables/` folder next to it (both installer layouts
work), then the repo's `dependables/`, then PATH. Cached per process.

**Every** ffmpeg/ffprobe call goes through it — `ffmpeg_build.compile_command`'s
argv[0], and all eight `subprocess.run`s in `core/utilities.py` (probe,
duration, HDR metadata/tag checks, the `supports_*` capability checks, the
HDR preview frames). Verified by running a real Mux and Encode job with every
ffmpeg folder removed from PATH: both launched `dependables\ffmpeg.exe`.

**Absolute paths are load-bearing for yt-dlp**, not tidiness: a relative
`--js-runtimes deno:dependables/deno.exe` made yt-dlp report "no JS runtime
found" (the same path made absolute worked — confirmed), and a bare `ffmpeg`
is left to Windows' search order, which only hits the app's folder when
frozen.

There are no `__init__.py` files; the subfolders work as implicit namespace
packages. Imports are absolute from the repo root (`from components.drop_box import DropBox`).

### The app object is the hub

`LlamaGUI` (`core/app.py`) subclasses both `ctk.CTk` and `TkinterDnD.DnDWrapper`
so drag-and-drop works on the main window. Every tab and component receives
`app=self` and reaches shared behavior through it. Key things live on the app:

- `self.current_file_path` — the single globally-selected input file.
- `self.tabs` — dict of name → tab instance (`Muxing`, `Encoding`, `Queue`,
  `YT-DLP`, `Settings`), built once at startup. All tabs are constructed
  eagerly; `show_tab(name)` just `grid_forget()`s all of them and `grid()`s
  one. Cross-tab calls go through `self.app.tabs.get("Queue")`.
- `self.tab_ui_registry` — list of `{label, img, on_thumbnail}` dicts for the
  file-selection broadcast (below).
- `self.tab_indicator` — the active-tab accent strip (below).

Window sizing: `scaled_w, scaled_h = width*0.35, height*0.375` of the screen,
fixed and non-resizable (`resizable(False, False)`). The 0.375 height was
tuned specifically so the Encoding tab's content (controls + DropBox minimum)
fits without the packer being forced to compress the DropBox below its
configured size — see the **Tabs** section (the bottom-up `controls_frame` /
`top_container` pack pattern) and the `pack()` cavity-order gotcha in **Known
issues** before changing it. Adding a control row to Muxing or Encoding eats
into the same budget.

The OS close button is bound (`WM_DELETE_WINDOW` → `on_close`) to
`self.destroy()` then `sys.exit(0)`, a hard full-process exit rather than
letting the Python process linger after the window goes away.

### Active-tab indicator

A flat strip of the theme's `primary` (`self.tab_indicator`, a plain
`CTkFrame`) that pokes out from behind the sidebar into the gutter beside
whichever sidebar button is active, with a narrower 12px `secondary` band
(`self.tab_indicator_line`) crossing it through the vertical middle. Both are
positioned with `.place()` (independent of the grid) and `.lift()`ed, running
from the active button's right edge (`button_x + button_w`) to the tab
frame's left edge (`sidebar_width + 10`, matching `show_tab`'s padx), so they
stop exactly at the frame edge and never cover content. Since the strip is
`primary` on a `primary` sidebar, only the part crossing the gutter is
actually visible.

**Both pipes are `corner_radius=0`, and that's load-bearing on two counts.**
Rounded pipes read wrong, but more subtly, a rounded `CTkFrame` paints its
*master's* color in the corner nooks outside the rounded shape — the master
here is the root window (dark) while the pipes sit over the sidebar
(`primary`), so those nooks rendered as dark notches that looked exactly like
a drop shadow on the pipe. Flat corners have no nooks. Being square-cornered
is also why the strip starts *at* `button_x + button_w` rather than
overlapping back into the button: any overlap would square off the active
button's own rounded corner. At mid-height (where the line band crosses) the
button's rounded edge has reached its full bounding width, so the two still
meet flush with no gap — verified by sampling the pixels across the junction.

**Two more anti-seam measures, both required.** The band's height must stay
**even** (`line_h = 12` currently — any even value is fine), and both pipes
pin `bg_color` to `primary` instead of letting it default. CTk floors a drawn
shape's width/height to the nearest even number, so at the band's original
height of 9 it painted 8 rows and left the 9th showing the widget's own raw
canvas — which, at the default
`bg_color` (a stale snapshot of the dark root window), rendered as a 1px dark
line under the pipe that read as a drop shadow. A vertical pixel scan showed
exactly that: 8 rows of `secondary`, then one row of `(36,36,36)`, then the
strip. Even height removes the flooring loss; the pinned `bg_color` makes any
strip that does get exposed match its surroundings. This is the general
gotcha in Known Issues, hit here for the second time.

This is a **deliberate design choice over recoloring the active button**. An
attempt at the latter (active button solid `secondary`, the rest ghost
transparent) was built and rejected on sight — don't reintroduce it.

`show_tab(name)` re-aligns both on every switch via `_update_tab_indicator`,
but **deferred through `self.after(50, ...)`, not called synchronously**:
the very first call happens during `__init__`, before `mainloop()` has run
even once, and at that point the sidebar buttons haven't actually been mapped
onscreen — `winfo_height()` on them still returns a stale 1px placeholder
even after `update_idletasks()` and even via `after_idle` (both still fire
before the window's first real `<Configure>`/map pass). A real timed delay is
what actually works. Each call cancels any not-yet-fired previous one
(`self._tab_indicator_job`) so rapid tab switching can't let a stale,
out-of-order callback overwrite a newer one.

`_update_tab_indicator` calls `update_idletasks()` **only when the button's
geometry is still the 1px placeholder**, not unconditionally. That call
synchronously re-lays-out and redraws the whole window; profiling put it at
~47ms, **28% of the cost of a tab switch**, paid on every switch for a
geometry answer the 50ms defer above has already made valid. The guard keeps
the safety net for the one call that actually needs it — the first, during
`__init__` — without charging every later switch. (What remains of a tab
switch is Tk's own redraw of the newly-mapped tab's widgets; `show_tab`
itself profiles at ~1ms.)

`Sidebar.buttons` (a `{name: button}` dict) is what `_update_tab_indicator`
looks up to know which button to align to.

### File selection is a broadcast, not a per-tab event

Any DropBox (drop or double-click or Browse) calls `app.update_global_file(path)`.
That method is the *only* place the selected file changes. It:

1. Strips tkdnd's `{}` wrapping from the path.
2. Walks `tab_ui_registry` updating every registered filename label.
3. Calls `hide_drop_text()` on every tab that has a `drop_box`.
4. Calls `_autofill_output_path()` on every tab that exposes one (Muxing and
   Encoding), so the suggested `<name>_muxed<fmt>` / `<name>_encoded<fmt>`
   output path refreshes for the new input. **The FILENAME always re-derives
   from whichever file was just picked; only the DIRECTORY persists** —
   whatever's currently in the save-path field (the default save location
   the first time, or wherever the user last Browsed to since), never reset
   back to the default just because a new file came in. This used to also
   gate on `self._auto_output` (a flag meaning "the user hasn't Browsed a
   custom path"), which skipped the refresh *entirely* once it had — so the
   filename silently froze on whatever file was selected at that moment,
   mismatching every file imported afterward, for the rest of the session.
   A directory the user picked is worth remembering across a file swap; a
   stale filename from the previous input never is. Telling "the field
   holds a bare directory" (fresh off `__init__`, just
   `default_save_location` with no filename) apart from "the field holds a
   full file path" (an earlier auto-fill or a manual Browse pick) matters
   here — `os.path.dirname()` on the former strips its last real folder
   segment instead of leaving it alone, so both tabs check for a file
   extension first to decide which case they're in.
5. Kicks off preview-thumbnail resolution via `_load_thumbnails(path)` (below).

**Thumbnails are ten frames, decoded off the Tk thread, cached on the app.**
`core.utilities.extract_video_thumbnails(path, count=10)` grabs ten frames
evenly spaced across the video's *interior* (fractions 1/11 … 10/11 of the
frame count — skips a black first frame / end-credits last frame), returning
a list 1–10 long (shorter for a very short clip, `[]` if nothing decodes).

Ten frame-seeks are too slow to run synchronously on the Tk loop, so
`_load_thumbnails`:
- **Cache hit** — `path == self._thumb_frames_path` and frames already
  decoded — broadcasts `self._thumb_frames` immediately. This is what makes a
  live theme rebuild (which re-calls `update_global_file` via
  `load_settings`) and every plain tab switch cost nothing.
- **Miss** — bumps `self._thumb_token`, starts a daemon thread
  (`_decode_worker`) that puts `(token, path, frames)` on `self._thumb_queue`.
  A single main-thread poller (`_drain_thumbnails`, self-re-arming every 80ms
  while `_thumb_pending > 0`) delivers results. **The worker never touches a
  widget or calls `after()`** — Tkinter isn't thread-safe; the queue is the
  only channel back. `_deliver_thumbnails` drops a result whose token is
  stale (user picked another file mid-decode) or empty, else caches + calls
  `_broadcast_thumbnails`.

Tabs opt into this by calling `app.register_tab_ui(label, img_widget,
on_thumbnail=...)` in their `__init__`. **`on_thumbnail` receives the whole
frame *list*** (not a single image). If omitted, a default handler renders
`frames[0]` at a fixed 350x200. Muxing and Encoding both pass
`self.carousel.set_frames` — see **ThumbnailCarousel** under Components.

**The scrub position is shared across tabs.** `self._preview_index` on the
app is the frame index both carousels show. A carousel reports every scrub
through its `on_index` callback → `app.sync_preview_index(i)`, which mirrors
it onto every other registered carousel via `carousel.sync_index(i)` (an
instant jump, no slide, no `on_index` re-fire — so it can't loop).
`_preview_index` resets to 0 only when the input file *actually* changes
(checked in `update_global_file`), so it survives a live theme rebuild:
`_broadcast_thumbnails` re-applies it with a `sync_index` after each
`on_thumbnail`, since `set_frames` resets every freshly-built carousel to 0.

**When adding a tab that should show the selected file, call `register_tab_ui`.**
`YtDlpTab` deliberately does not — it previews a fetched *link*, never the
selected input file.

**The same worker also probes the file** (`core.utilities.probe_media`, a
best-effort `ffprobe`), because Encoding's `Select` needs to mean something
concrete: the result (`app.media_info` — container, video/audio codec, video
profile/level, audio channels/sample rate/bitrate, and `has_video`/
`has_audio`) is what lets EncodingTab auto-resolve Encoder, Audio Codec,
Profile, Level, Audio Channels, Audio Sample Rate, and Audio Bitrate — every
codec-detail control it has — from the source instead of leaving them a
placeholder, lets both tabs default the output container to the input's
own, and — on Muxing, which never re-encodes — work out which containers
the file can legally be remuxed into. Video Level in particular needed a
**codec-aware** conversion, not one universal formula: ffprobe's raw
`level` is ten times the display value for H.264 (`40` -> "4.0"), but
*thirty* times for HEVC (confirmed empirically — a source ffprobe reported
raw `120` is really "4.0", not the naive-formula "12.0"), a `seq_level_idx`
table lookup for AV1 (also confirmed empirically: a naturally-encoded 720p30
clip's raw `5` is level "3.1", matching that table's index 5), and a named-
level code for MPEG-2 (mirrors `ffmpeg_vars._LEVEL_ARGS["MPEG-2"]` in
reverse) — see `core.utilities._ffprobe_level`. Audio Channels/Sample Rate
match a probed value against `formats.channels_display_for`/
`sample_rate_display_for` (an exact match, or no match at all — a source's
7.1 or 22050 Hz has no offered option to land on); Bitrate instead *snaps to
the closest* entry in `formats.AUDIO_BITRATES` (`formats.bitrate_display_for`)
since a real source's exact bitrate essentially never lands precisely on one
of those round numbers. `AUDIO_BITRATES`' own entries are display text, not
raw numbers — `"96 kbps"` … `"768 kbps"`, then `"1 Mbps"`/`"1.5 Mbps"` once
the value clears 1024 kbps (`core.formats._format_bitrate`; 1024/1536 are
deliberately exact multiples of 1024 so that division lands clean rather
than showing "1.024 Mbps"). `bitrate_arg_for(display)` is the inverse,
turning a dropdown's display text back into the plain `"<n>k"` ffmpeg wants
for `-b:a`; `bitrate_display_for`'s snap-to-closest works in raw kbps
underneath, via `_BITRATE_KBPS_BY_DISPLAY`.

`has_video`/`has_audio` answer a different question than `video`/
`audio`: whether a stream of that kind exists *at all* (`False` only once a
probe genuinely ran and found none, `None` while unknown), independent of
whether its codec was one this app recognizes — that's what drives the
Video/Audio sub-tab greying-out described under "Option compatibility"
below. The queue carries **tagged messages** (`("info", …)` then
`("frames", …)`) rather than bare tuples, so the ~50ms probe can land and
settle the defaults long before the ten frame-seeks finish; `"frames"` is
always last and is what clears the pending count. Delivery is broadcast by
`_broadcast_media_info` to any tab exposing `on_media_info`. Every field may
be None and every failure path (no ffmpeg found, unreadable file) returns
Nones rather than raising — nothing here is required for the UI to work, it
only ever *improves* defaults.

**Audio-only inputs.** `extract_video_thumbnails` returns `[]` for an audio
file, so there'd be nothing to reveal — the carousel would sit behind a
collapsed DropBox. `_is_audio_only(path)` (probe says audio-but-no-video, or,
with no probe, the extension is in `formats.AUDIO_EXTENSIONS`) gates
`_broadcast_audio_only(True)`, called from *both* `_deliver_media_info` (the
probe usually lands first) and `_deliver_thumbnails` (the empty result).
That flips every registered carousel to `set_audio_only(True)` → it reveals
itself and shows the **Wave Loop visualiser** (the same render path as a
stripped video — it *is* an audio visualiser), navigation disabled.
`_broadcast_thumbnails` clears the flag (`set_audio_only(False)`) whenever
real frames arrive, so an audio→video swap flips back. Nothing downstream
(formats, the settings dict, the real ffmpeg pipeline — see "Encoding flow"
below) keys off audio-only yet — the tabs' video controls stay live but inert.

**The info badge and its hover tooltip** (`ThumbnailCarousel`, bottom-left of
the preview) surface the probe's raw findings as text, once one lands —
container, `Video: H.264 · High · L4.0 · 1920x1080 · HDR` (each bit
conditional on what was actually identified), `Audio: AAC · Stereo · 48000 Hz
· 192 kbps` (plus `"N tracks"` once `probe_media`'s `audio_streams` has more
than one), duration, and file size. When the video is HDR, a second line
(`_mastering_text`) reports whether the source actually carries ST 2086
mastering-display luminance and MaxCLL/MaxFALL — the same numbers that decide
whether the BT.2390 tonemap's `peak_detect` runs (see "Encoding flow" below)
— rather than leaving that decision invisible to the user. The badge itself
(`info-icon-dark.png`/`info-icon-light.png`, matching the current appearance
mode, generated from source artwork by `scripts/make_info_badges.py`; falls
back to a procedurally-drawn disc if the files are missing) sits opposite the
mute badge's top-left corner and is theme-independent, same reasoning as the
mute badge always being red. `set_media_info(info)` is the broadcast target
(`app._broadcast_media_info` → any tab exposing `on_media_info` → the
carousel), separate from `set_frames`/thumbnails; the tooltip is a borderless
`Toplevel` (same family as the toast/dropdown popups) that refreshes its text
live if a probe lands while the user is already hovering.

### Keybinds

Global keybinds are bound once on the root in `LlamaGUI.__init__` (the root
outlives the live theme rebuild, so they survive it — unlike anything bound
on a tab). The set so far:

- **Left / Right** → `_nudge_preview(∓1)` → steps the *current* tab's
  `ThumbnailCarousel` (`carousel.step(delta)`, the public wrapper around
  `_step`). Ignored while a `tkinter.Entry` has focus (the `TimeSpinner` /
  save-path fields own the arrow keys for cursor movement), and a no-op on
  tabs with no `carousel`. A keyboard step doesn't light the hover chevrons
  (`_step(..., show_arrows=False)`) — there's no pointer over the preview to
  justify it.
- **Space** → `_toggle_queue` → `QueueTab.toggle_queue()` (start / pause,
  mirroring `start_all_btn`). Only fires on the **Queue** tab, and only when
  focus isn't on a control Space already means something for — an
  `Entry`/`Text`, or (walking up from `focus_get()`) a `CTkButton` /
  `CTkCheckBox` / `CTkSwitch` / `CTkSegmentedButton` / `CTkOptionMenu`.
  **`show_tab` calls `self.focus_set()`** (unless an `Entry` is focused) so
  this works the instant you click the sidebar nav button — a CTk button
  keeps focus after a click and swallows `<space>`/`<Return>`, so before
  that the keybind only woke up once you clicked somewhere non-focusable in
  the tab.

This is meant to grow; keep new binds here rather than scattering them onto
individual tabs.

### Theming (`core/theme.py`)

The app's brand colors are **not** hardcoded per-widget, and switching
theme is **live — no restart** (this took two iterations to get right; see
below for why the first one wasn't enough). Every file that used to write a
literal `"#FDCA3C"` (sidebar, `DropBox`'s border, `EncodingTab`/
`MuxingTab`'s "do it now" buttons, the queue's fill/queued-row color/overall
progress bar, `LlamaGUI`'s tab indicator) reads `get_active_theme()["primary"
]`/`["primary_hover"]` instead. A second role, `secondary`/`secondary_hover`,
covers the "Queue Task"/"Clear Completed" buttons, which used to just be
CTk's implicit default button blue. **`"Stop Queue"`'s red is a deliberate,
permanent exception** (see Conventions) — never theme-driven.

`THEMES` is the source of truth: seven named palettes —
`Lemon` (`#FDCA3C` primary / `#3B8ED0` secondary — the original look),
`Cupid` (`#FA6E99` / `#780219`), `Lilac` (`#a58fd7` / `#3e6d04`),
`Ranger` (`#F98524` / `#104E4B`), `Noir` (`#131317` / `#5A5B63`),
`Luck` (`#ADBCDE` / `#0E5914`), and `Vaporwave` (`#3B41B8` / `#ED72D4`).
Every color is a **flat hex string, not a `(light, dark)` tuple** —
deliberate, so appearance mode never changes a theme's colors. Hover shades
are auto-derived by `_darken()` (~0.87 brightness, matching the brand
yellow's pre-existing `#FDCA3C` → `#e0b234` ratio) except Lemon's primary
hover, which keeps that exact historical value.

**Text color on primary/secondary is adaptive, not hardcoded.**
`get_theme()` also returns `primary_text` and `secondary_text`, each
`"black"` or `"white"` — whichever has the higher WCAG contrast ratio
against that color, computed by `readable_text_on()` (`_relative_luminance`
→ compare contrast-vs-black against contrast-vs-white). This replaced an
earlier scheme that hardcoded `"black"` on every primary and `"white"` on
every secondary, which broke for `Noir`'s near-black primary `#131317`
(black-on-black). Every explicitly primary/secondary-colored widget now
reads these keys instead of a literal: the sidebar title + footer, the
`Mux`/`Encode`/`Save`/`Start Queue` buttons (primary), the `Queue Task` /
`Clear Completed` buttons (secondary), and the queue's queued-row text +
progress-fill text sweep. Current outcomes: black text on every primary
except `Noir` (white); white on every secondary except `Lemon`'s `#3B8ED0`
(black — brighter blue than the dark-red/green/teal secondaries). The
`Stop Queue` button's fixed red gets the same treatment against its
constant `STOP_RED` `#E5484D` (`core/theme.py`; `_STOP_TEXT` in
`queue_tab.py` resolves to black). The Encoding tab's `Strip Video`
checkbox reuses the same `STOP_RED`.

CTk's own default-styled widgets (sidebar nav buttons, checkboxes,
switches) still carry CTk's stock near-white label color from the generated
theme JSON — `_substitute_ctk_accents` only swaps accent *fill* colors, not
text — which is fine since every theme's secondary is dark enough. Only the
explicitly-colored widgets above go through `readable_text_on`.

**Making CTk's own default-styled widgets follow the theme too**: checkboxes,
switches, sliders, `CTkOptionMenu`s, and the sidebar's nav buttons don't set
`fg_color` explicitly — they use whatever CTk's *currently-loaded default
color theme* says, which out of the box is always CTk's stock blue
regardless of this app's own theme. `core/theme.py` fixes this by generating
a real custom CTk theme JSON per app-theme: `_ctk_theme_path()` loads CTk's
own bundled `blue.json`, and `_substitute_ctk_accents()` walks it replacing
every occurrence of CTk's three hardcoded accent-color value-pairs
(`_CTK_ACCENT`/`_CTK_ACCENT_HOVER`, plus a third even-darker
`_CTK_ACCENT_PRESSED` that only `CTkOptionMenu` uses for its own
button-hover state) with `[secondary, secondary]` etc. — flattened to one
shade, same as everywhere else. This is a **value-based** substitution, not
a per-widget-key list — confirmed by dumping `blue.json` in full, CTk
reuses the exact same two color pairs across every widget's accent
property, so replacing by value catches all of them (`CTkButton`,
`CTkCheckBox`, `CTkRadioButton`, `CTkSwitch`, `CTkProgressBar`, `CTkSlider`,
`CTkOptionMenu`, `CTkSegmentedButton`) without needing to enumerate them,
and automatically leaves every *non*-accent color (backgrounds, borders,
neutral greys) untouched. Generated files land in `_generated_themes/`
(gitignored — build artifacts, not source) and `apply_ctk_theme(theme_name)`
loads one via `ctk.set_default_color_theme()`.

**Why a full rebuild — not just reloading the CTk theme — is what makes
this live**: `ctk.set_default_color_theme()` only affects widgets
constructed *after* the call; it never retroactively recolors an
already-built widget (this is a hard CTk limitation, not a bug). Merely
calling `apply_ctk_theme()` on its own — which is all an earlier version of
this feature did — changes nothing visible until the next launch, and even
then, only the two colors this app sets *explicitly* (primary/secondary)
would be right; the CTk-default-styled widgets (checkboxes, switches,
sliders, sidebar nav buttons) would still be stuck on whatever CTk theme
was active when the process started. So `LlamaGUI.apply_theme(theme_name)`
(called from `SettingsTab._on_save` when the theme actually changed) does
both: reloads the CTk default theme, *and* destroys + reconstructs every
widget that needs to pick it up. Specifically:
- `Sidebar`, the tab indicator, and the `Muxing`/`Encoding`/`YT-DLP`/
  `Settings` tabs are destroyed and rebuilt from scratch — the only way for
  their default-styled children to actually read the newly-loaded CTk
  theme. `Muxing`/`Encoding`/`YT-DLP`'s field values are snapshotted via
  `_gather_settings()` first and restored via `load_settings()` after, so
  the user doesn't lose an in-progress form. YT-DLP restores from the app's
  cached fetch (`app.ytdlp_cache`) — a theme switch never re-fetches.
- **`Queue` is deliberately never rebuilt** — destroying it would discard
  its task list (`self._rows`) and any in-flight animation. Instead it gets
  `QueueTab.refresh_theme()`, which re-reads `get_active_theme()` into the
  module-level `_THEME` (also updating `_QUEUED_STYLE` in place) and calls
  `.configure()` directly on `progress_bar`, `clear_btn`, `clear_all_btn`,
  `start_all_btn`, and every existing row's `base_canvas`/`progress_canvas`/
  style — recoloring in place
  without touching any task data. This works because Queue never used
  CTk-default-styled widgets in the first place (see Conventions) — every
  one of its themed elements was already explicitly colored, so there was
  nothing that *needed* a fresh construction to pick up the new CTk theme.
- `self.tab_ui_registry` is reset before rebuilding, since its old entries
  point at widgets that are about to be destroyed; the freshly-constructed
  Muxing/Encoding tabs re-populate it via their own `register_tab_ui` calls.

`main.py` and `LlamaGUI.__init__` both call `apply_ctk_theme(load_settings()
["theme"])` before constructing any widgets, so a fresh launch starts on
the correct theme without needing `apply_theme`'s rebuild machinery at all
— that path only exists for the *live* in-session switch.

**Presets** (`core/presets.py`) are a separate, gitignored `presets.json`
at the repo root, shaped `{tab: {name: settings}}`. A preset is a **recipe,
not a job**: `PRESET_KEYS` limits it to the container and the codec/quality
choices, and deliberately excludes the trim, the input/output paths, and
(on Muxing) the track picks — so loading "YouTube 1080p" can never quietly
re-trim a clip or repoint its output. Scoped per tab, since Muxing and
Encoding no longer share a settings shape at all. Every read is best-effort;
a missing or corrupt file yields an empty set rather than raising.

**Persistence**: `load_settings()`/`save_settings()` read/write a small
`settings.json` at the repo root (gitignored — a local preference file, not
shared repo state), holding `theme`, `appearance_mode`, `default_save_location`,
and `gpu_enabled`; missing keys or a missing/corrupt file fall back to
defaults (`Lemon` / `"System"` / `default_output_dir()` — i.e.
`~/Videos/LlamaMXD Export` — / `True`) rather than raising.

### Option compatibility (`core/formats.py`)

Pure data + lookups, no Tk. **The option tree has exactly one root: the
output container.** It decides which video and audio codecs are legal; the
chosen video codec then decides which profiles and levels exist and what
kind of quality control applies. Nothing flows the other way. That
one-directional rule is what makes an illegal combination
*unrepresentable* — you never need a dialog telling someone their codec
doesn't fit their container, because the list never offered it.

`_CONTAINERS` is the compatibility matrix. It exists because of WebM, which
shares **no** video codec with mp4/mov: before this table, picking `.webm`
left every entry in the encoder list illegal (H.264/H.265/MPEG-4/MPEG-2 are
all unusable there), so the format was silently broken. WebM now offers
VP8/VP9/AV1 + Opus/Vorbis and nothing else. Video display names dropped
their library suffix — `"H.264 (x264)"`/`"H.265 (x265)"` are now plain
`"H.264"`/`"H.265"` (`VIDEO_ENCODERS` keys, `_CONTAINERS` entries,
`_ENCODER_SPECS`/`_SPEED_SPECS` keys, `FFPROBE_VIDEO` values, and
`ffmpeg_vars._PROFILE_ARGS` keys all follow) — freeing enough width in
Encoding's Video codec row to fit a fourth dropdown (Encoder Preset) beside
Encoder/Profile/Level; see "Tabs" below. `short_name()` is a no-op for every
current codec now but stays as a defensive one rather than being removed,
in case a future codec name grows a parenthetical again.

**A fourth container, `.mov`, and four mezzanine/archival codecs since
joined the original four (H.264/H.265/MPEG-4/MPEG-2/VP8/VP9/AV1).**
`.mov` is the native/canonical delivery container for all three professional
intermediates below, as well as this app's existing consumer codecs.
`ProRes` (`prores_ks`) and `DNxHR` (`dnxhd` — the same ffmpeg encoder covers
classic DNxHD and the modern DNxHR tiers) each model their "quality" as the
**profile choice itself** rather than a CRF/qscale — a fixed target bitrate
per tier, not a continuously variable rate control — so `quality_for()`
returns `None` for both (same as `Select`) and the UI's quality slider
disables rather than showing a meaningless number under their name (`
EncodingTab._sync_controls` distinguishes this "genuinely no such knob" case
from `Select`'s "nothing picked yet, slider stays live"). `CineForm`
(`cfhd`) follows the identical pattern — its "profile" list
(`Low`…`Film 3+`) is really `cfhd`'s own named `-quality` ladder
(`ffmpeg_vars._QUALITY_PRESET_ARGS`/`_NO_PROFILE_FLAG` — CineForm's Profile
slot must never fall through to a literal `-profile:v`, which `cfhd` doesn't
have at all). `FFV1` is lossless with no profiles, levels, or quality
control whatsoever. `_PIX_FMT_ARGS` (`core/ffmpeg_vars.py`) covers the
fourth wrinkle these three share: unlike H.264/HEVC/etc., which happily
follow whatever pixel format the source decodes to, `dnxhd` actively
*refuses to run* without an explicit, profile-legal `-pix_fmt`, and
`prores_ks`/`cfhd` silently lock in the wrong one without it.

**`PASSTHRU_ONLY_CODECS`** (`{"DTS", "Dolby TrueHD"}`) names two codecs
`probe_media` can identify but this app will never offer through a dropdown
— transcoding surround/Atmos codecs is out of scope, so a track holding one
always passes through untouched. `is_passthru_only(codec)` is what lets
EncodingTab auto-force its Passthru checkbox and grey the rest of the audio
controls the instant one is probed, rather than leaving it stranded on
`Select` the way a codec this app simply doesn't recognize would.

`_ENCODER_SPECS` carries each codec's profiles, levels and rate-control
spec. Two things it deliberately does *not* do: share profile names between
codecs (`Main 10` is H.265's, `High`/`Baseline` are H.264's), or assume CRF
is universal — MPEG-4/MPEG-2 take a **qscale on 1-31** rather than a CRF on
0-51, and VP8/VP9/AV1 use 0-63. `quality_for()` returns the kind, range,
default and slider end-labels together so the UI can re-range the slider
rather than showing one codec's numbers under another's name. An empty
`profiles`/`levels` list means the codec genuinely has none, and the UI
disables that dropdown rather than borrowing H.264's values.

**Speed** (`_SPEED_SPECS`/`speed_values_for`/`speed_kind_for`/
`speed_default_for`) now covers VP8 too (`cpu-used` + a fixed `-deadline
good`, same as VP9), not just x264/x265/AV1's named `-preset` ladder.
MPEG-4/MPEG-2 and `Select` still have no speed knob at all.

**`SELECT` (`"Select"`) is the one "nothing picked/resolved yet" placeholder,
shared by every derived list in this module** — Encoder, Audio Codec, Audio
Channels, Audio Sample Rate, and Audio Bitrate all use it (an earlier
version had Channels/Sample Rate on a separate `SOURCE` constant instead;
retired once those two also gained real auto-fill — see below — since at
that point there was no longer a meaningful difference from Encoder/Audio
Codec's own placeholder). It's the default until a file is probed, at which
point EncodingTab auto-resolves *every one* of those controls to whatever
the source already has — see "File selection is a broadcast" above and
`EncodingTab._auto_select_codecs`. A value the probe couldn't identify, or
that isn't legal in the current container, simply leaves the control on
`Select`. Encoder/Audio Codec additionally block the job in
`_validate_settings` while left that way with the stream actually present —
Encoding never falls back to a silent stream copy, that's what Muxing is
for — but Channels/Sample Rate/Bitrate don't need that: `ffmpeg_vars`
translates an unresolved one to "omit the flag" (`-ac`/`-ar`/`-b:a`), which
is always a valid, sensible "just follow the source" outcome, so nothing
blocks a job over those three. `quality_for` returns `None` for `Select`
(nothing to rate-control); most codec-detail controls follow that and
disable, though the Encoding tab deliberately keeps HDR→SDR and the quality
slider live on `Select` anyway (see `_sync_controls` rule 5).

`containers_for(video, audio)` is **the Muxing inversion** — given the
codecs a source actually holds, which containers can it be remuxed into
without re-encoding. A `None` codec means "unknown, or no such stream" and
constrains nothing, so an unprobed file still offers everything rather than
being narrowed on a guess.

### Tabs

- **Muxing** (`tabs/muxing_tab.py`) and **Encoding** (`tabs/encoding_tab.py`)
  now share the same structural pattern: a `top_container` (DropBox that
  fills all available vertical space, expanding into the leftover room above
  a fixed-height `controls_frame`) and a bottom controls section built
  bottom-up (`controls_frame` packed with `side="bottom"` *first*, so it
  anchors to the window edge; `top_container` packed after with
  `expand=True` absorbs whatever's left). Both have `_gather_settings()` →
  plain dict, `load_settings(dict)` → restore UI, `_validate_settings()`,
  a `Queue Task` button, and a yellow "do it now" button (`Encode`/`Mux`)
  that queues *and* immediately starts the task.

  **The two tabs are not variations on each other — Muxing never
  re-encodes.** Muxing is container change + stream selection, everything
  `-c copy`; it has no codec controls at all. "Copy video, re-encode audio"
  is therefore *not* a Muxing job — it's an Encoding job with Audio Codec
  set and Encoder auto-resolved to the source's own codec (Encoding always
  re-encodes; it never falls back to a bare copy). Encoding is the superset. That split is what stops
  the two tabs from collapsing into one fuzzy thing.

  Both have an **Output Format** `ThemedDropdown` (`format_menu`, values
  from `formats.containers()`) on their **Overview** sub-tab — its value is
  the `output_format` settings key, and `_on_format_change` swaps the
  suggested output path's extension to match (only when the path already has
  one to replace; before a file is picked the entry holds just a folder and
  `_autofill_output_path` supplies the extension). `select_save_location`'s
  default filename and `defaultextension` follow it too. It lives on
  Overview because it is **the root of the whole option tree** (see
  `core/formats.py`): it filters *both* codec lists, so the panel that owns
  it has to be reachable from either side.
  Encoding's **Video** sub-tab has the `Encoder` / `Profile` / `Level` codec
  row, a quality slider, an HDR-to-SDR toggle that's an **`AnimatedSwitch`**
  (slides instead of snapping — see Components), and a **Strip Video**
  checkbox (`strip_video_check`) in the red `STOP_RED` (the Stop Queue
  colour). GPU acceleration used to be a switch here too but is now the
  global Settings preference `app.gpu_enabled`, which
  `EncodingTab._gather_settings` reads directly. Keep
  `_gather_settings`/`load_settings` in sync when adding a control to either
  tab.
  Both show the selected file as a **`ThumbnailCarousel`** (see Components) in
  their `top_container`, in place of the old single `img_label` +
  `display_image`/`_resize_thumbnail`. The tab keeps only a thin
  `_reveal_preview()` (packs the carousel in, `pack_forget`s the DropBox)
  that the carousel fires via its `on_populated` callback on the first frame
  set; double-clicking the carousel reselects the input file
  (`on_reselect`). The carousel also takes `on_index` — it fires
  `app.sync_preview_index(i)` on every scrub so the **other tab's carousel
  mirrors the same frame** (see the file-selection broadcast section); the
  receiving `carousel.sync_index()` jumps with no slide and doesn't re-fire
  `on_index`, so there's no loop.

  **Overview / Video / Audio sub-tabs.** Both tabs' `top_container` opens
  with a persistent `header_row`: a **`SubTabBar`** (`components/sub_tab_bar.py`
  — see Components) top-left, then the `Selected File:` label filling the
  rest (a **`MarqueeLabel`** — single-line, set by `app.update_global_file`;
  scrolls when the path doesn't fit). The `SubTabBar`'s `command` is
  `_show_subtab`.

  `controls_frame` has **one two-column `options_row`**. Each sub-tab owns
  *both* columns — `left_col` (`anchor="s"`) takes that panel's dropdown
  rows, `right_col` (`anchor="s"`, `fill="x"`) its checkbox/slider stack.
  `_build_overview_panel(left_parent, right_parent)`,
  `_build_video_panel(...)` and `_build_audio_panel(...)` each return a
  `(left, right)` frame pair, built once and returned unpacked.
  `_gather_settings` reads **every** field regardless of which sub-tab is
  showing — all six frames' widgets stay alive — so switching never loses
  input.

  **`_pin_options_height()` freezes every panel to its own footprint and
  stacks them — width independent per sub-tab, height shared by all
  three.** It measures each pair's natural `winfo_reqheight()`/
  `winfo_reqwidth()` first, then pins every panel's height to **Overview's**
  own measured height specifically (the tallest of the three: 128px here vs.
  Video/Audio's 124/120 on Encoding, 96/96 on Muxing) rather than each
  panel's own — width still varies per panel (Video's wide codec row doesn't
  squeeze Overview's rundown, and vice versa). `configure`s every `left`
  frame to `(own_width, shared_height)` and every `right` to
  `(height=shared_height, relwidth=1.0)`, each `pack_propagate(False)`,
  packs a `fill="both", expand=True` spacer `before` the first content row
  so the content floats to the panel's bottom, and finally **`.place()`s
  all six at their column origin, stacked**. `_show_subtab(name)` resizes
  `left_col`/`right_col` to the target panel's own width (height stays the
  shared constant throughout) and lifts — no re-pack, no relayout, no
  synchronous flush.

  **Height wasn't always shared — each panel used to keep its own,
  independently of the others**, which meant `controls_frame`'s total
  height (and therefore how much room the DropBox/preview carousel above it
  got) changed on every sub-tab switch: confirmed visually, the DropBox
  visibly grew and shrank as you clicked Overview/Video/Audio. Pinning every
  panel to Overview's own height fixed that, but naively — just resizing
  the shared `left_col`/`right_col` containers at switch time while leaving
  each panel's own `left`/`right` frame built at its *own*, shorter,
  natural height — doesn't actually work: `left`/`right` are real child
  windows, and Tk clips a child to its parent's rectangle, not the other
  way around. Once the now-taller container stopped clipping that far down,
  a still-shorter, merely-lifted sibling left whatever sat directly behind
  it (a taller *inactive* sibling — Overview's own trim row, still placed at
  the same origin) visible in the leftover strip beneath it. Confirmed by
  screenshot: Muxing's Video panel (96px) showed Overview's trim spinners
  bleeding through its bottom 32px once `left_col` grew to Overview's 128px.
  The fix is to build every panel's own `left`/`right` frame at the shared
  height from construction, not patch the outer containers at switch time —
  each panel's own spacer-before-content then simply grows to fill the
  extra room instead of leaving it uncovered, and one shared footprint +
  `lift` is what killed the switch flicker on top of that: the incoming
  panel covers exactly what the outgoing one did (no vacated strip of stale
  pixels, no sideways shift of the rundown), and there's no progressive
  dropdown redraw. The three panels legitimately differ in natural height;
  the slack lands as padding *below the preview* rather than a gap between
  control groups.

  **`_prewarm_subtabs`** (bound once to `<Map>`) cycles every panel onscreen
  briefly right after the tab first appears — chained through `after(40)` so
  CTk's deferred `_draw`s land between steps — then settles on the active
  one. Without it a panel that has only ever been stacked *behind* another is
  unpainted, so its first real reveal fills in over a few frames.

  - **Overview** — the globals: `Output Format` + the preset row
    (`Preset` dropdown + `Save` + `Delete`) on one line, the **single global
    trim** (`Start Time` / `Clip Duration` `TimeSpinner`s + an `A/V Sync`
    checkbox to their right) below it, and the export rundown
    (**`SummaryPanel`**) on the right. The spinners pass `command=
    _on_trim_change`, which refreshes just the rundown so the Length line
    updates live as you type. There is exactly one trim and it is global;
    stripping a stream just means the trimmed output lacks that stream. **There is no `Retain Video Length` checkbox any
    more** — `Duration 00:00:00` already means "to the end of the file", so
    it was a second way to say the same thing, and an ambiguous one whenever
    the two disagreed.
  - **Encoding / Video** — `encoder_menu` / `profile_menu` / `level_menu` /
    `speed_menu` all on one row (left) + `hdr_switch` (top) / a flexible
    spacer / `strip_video_check` (bottom) in the right column, plus the
    quality slider directly under the dropdown row (left). `speed_menu`
    briefly lived in the right column instead (a 4th dropdown on the left
    row pushed the quality slider's high-end label off the fixed-width
    window) — it moved back once shortening the video codec display names
    ("H.264 (x264)"/"H.265 (x265)" -> "H.264"/"H.265"; see "Option
    compatibility" above) freed enough width to fit all four **and**
    widened the row is now genuinely at its budget, confirmed by screenshot
    (widths: Encoder 80, Profile 96, Level 80, Encoder Preset 90).
    **On-screen label only — "Encoder Preset:", not "Speed:"** —
    `speed_menu`, the `speed` settings key, `ffmpeg_vars.SPEED`/
    `SPEED_ARG`, and `formats.speed_values_for`/etc. all kept their internal
    name, same as "Quality (CRF)" not matching its own `crf_slider`/
    `quality` internals. Profile, Level, Speed, and the quality control's
    *kind and range* are all derived from the encoder, not hardcoded — see
    "Option compatibility" below (`formats.speed_values_for`/
    `speed_default_for`) and `EncodingTab._apply_speed`/`_speed_values`.
    Unlike Profile/Level (handled generically by `_retarget`, which snaps to
    the new list's first entry), a Speed retarget snaps to the encoder's own
    recommended default instead — the first entry in a slow-to-fast list
    (e.g. x264's "ultrafast") is its least representative choice to land on
    silently. AV1's value list is a live probe
    (`core.utilities.av1_preset_range`), not formats.py's static fallback —
    SVT-AV1's preset ceiling varies a lot by ffmpeg build, confirmed
    firsthand on this same machine: 0–8 before updating ffmpeg, -2 to 13
    after.

    **HDR->SDR and Strip Video are deliberately separated, not stacked
    together** — HDR pinned to the *top* of the right column (aligned with
    the dropdown row's own top, via a special case in `_pin_options_height`:
    a fixed-height spacer sized to match the left column's own top gap,
    rather than the generic expand-spacer every other panel uses), Strip
    Video pinned to the *bottom* (via a flexible spacer between the two),
    mirroring where Strip Audio sits alone at the bottom of the Audio
    panel's own right column. They used to sit stacked directly on top of
    each other near the panel's bottom; by request, a real gap now reads
    them as two distinct controls rather than one cluster.

    **The quality slider spans the full width of the dropdown row above
    it** — "Low"'s own left edge lands flush with Encoder's left edge and
    "Placebo"'s own right edge flush with Encoder Preset's right edge
    (`crf_slider_row` fills `left`'s full width; the slider itself is
    packed between the two labels with `fill="x", expand=True`, so it's
    simply whatever room is left between them) — rather than being
    centered as a narrower, fixed-width unit the way it used to be.

    **HDR->SDR forces itself off, not just disabled, the moment it's
    unavailable** (`_sync_controls`: libplacebo missing, the source isn't
    actually HDR, or the stream's stripped/absent) — a switch left on from
    before (a file swap, a preset from a different source) with nothing
    backing it any more would otherwise silently keep tone-mapping "on"
    behind a control whose state the user can no longer see clearly.
    Both this and Strip Video/Strip Audio's mutual-disable needed more than
    `state="disabled"` to actually *look* disabled: `AnimatedSwitch`
    (CTkSwitch) and `CTkCheckBox` alike only dim their own text label on
    disabled — the knob/track colours and the checkbox's own destructive
    STOP_RED fill/border are read by their `_draw` unconditionally of
    state, so a `state="disabled"` switch or checkbox stayed fully bright.
    `EncodingTab._set_hdr_enabled` and `_set_strip_enabled` (mirrored on
    MuxingTab) swap those colours explicitly to a flat grey when disabled,
    same fix shape as `_set_quality_enabled` already used for the slider.
  - **Encoding / Audio** — two rows on the left: `audio_track_menu` +
    `choose_streams_btn` on row one, `audio_codec_menu` / `passthru_check` /
    `audio_bitrate_menu` / `audio_channels_menu` / `audio_samplerate_menu`
    together on row two; the right column holds only a red
    `strip_audio_check`, same as every other panel's single destructive
    checkbox. **`passthru_check`'s own label reads "Passthru" (no colon,
    unlike the dropdown labels beside it) and both it and the checkbox
    below are packed `anchor="center"`, not `anchor="w"`** — the checkbox
    mark (~24px) is much narrower than the label text, so left-anchoring
    both left the checkbox sitting under the label's leading edge rather
    than centered under the word itself. Settings keys `audio_codec`, `audio_bitrate`,
    `audio_channels`, `audio_sample_rate`, `strip_audio`, plus `passthru`
    and the per-stream picks the "Choose Stream(s)" dialog manages (see
    "Multi-stream audio" below). All four codec-detail dropdowns (not just
    Audio Codec) auto-resolve from the probed source and block nothing
    while left on `Select` — see "Option compatibility" above and
    `EncodingTab._auto_select_codecs`; each has its own `_auto_*` tracking
    flag (`_auto_channels`/`_auto_samplerate`/`_auto_bitrate`, alongside the
    existing `_auto_encoder`/`_auto_audio_codec`) and dedicated `command`
    (`_on_channels_change`/`_on_samplerate_change`/`_on_bitrate_change`) so a
    deliberate user pick freezes auto-tracking, same pattern throughout.
    **Every dropdown here is sized by `_measure_dropdown_width`** to the
    exact pixel width its own longest *possible* entry needs (built and
    torn down off-screen at panel-build time via a throwaway
    `dynamic_resizing=True` `CTkOptionMenu`, not an eyeballed guess) —
    Audio Track's worst case is synthesized (`_audio_track_universe`,
    `"Track 9 (<codec>)"` for the longest codec name this app recognizes)
    since the real label only exists once a file's probed. This precision is
    what keeps five controls on one row affordable: an eyeballed Audio
    Codec width (150px, guessed for "Dolby TrueHD") pushed this same
    arrangement to 566px in an earlier version — well past Video's own
    371px — and was why it used to be split across three rows. Width is
    independent per sub-tab (see `_pin_options_height` above), so Audio's
    own width no longer has any bearing on Overview's rundown regardless;
    measuring precisely just keeps Audio's own panel itself affordable —
    Audio Codec only needs 118px and Bitrate/Channels/Sample Rate
    75/76/92px, fitting all five on one row.
  - **Muxing / Video** and **Muxing / Audio** — a track picker
    (`video_track_menu` / `audio_track_menu`, values `Auto` / `Track 1-3`)
    plus a **`Browse…`** button that pulls a stream in from a *second file*
    (`_browse_external`); the chosen path is kept in
    `_video_ext_file`/`_audio_ext_file` and shows in the dropdown as
    `External: <name>`. Each panel's right column is its Strip checkbox.
    Settings keys `video_track`, `video_track_file`, `audio_track`,
    `audio_track_file`, `strip_video`, `strip_audio`.

  The sub-tab selection resets to `Overview` on a live theme rebuild (the
  tab is destroyed and reconstructed); the field *values* survive via the
  `_gather_settings` → `load_settings` snapshot `apply_theme` already does.
  The `_DETAIL_FIELDS` list in `queue_tab.py` has rows for every key —
  skipped when absent, so a Mux task's popup naturally omits the
  Encode-only fields and vice-versa.

#### `_sync_controls` — the single constraint pass

**Every derived UI state in both tabs is decided in one function.** Each
control's `command` just calls `_sync_controls()`, which reads the whole
form and rewrites every dependent widget's option list, selection and
enabled-state *from scratch*. It's idempotent, so call order stops
mattering.

This replaced a pile of pairwise handlers (`_on_strip_video_toggle`,
`_on_strip_audio_toggle`, `_on_format_change`, `toggle_time_spinners`) that
each clobbered the others' work — `toggle_time_spinners` needed an
early-return guard purely to stop Strip Video fighting it. With N
interacting controls, pairwise handlers need N² of them and there is no one
place to read the ruleset. **Don't add a new pairwise handler; add a rule to
`_sync_controls`.**

The rules it applies, in dependency order:

1. **Stream presence.** Ticking one Strip checkbox disables the other via
   `_set_strip_enabled` (not a bare `state="disabled"` — see the Video
   sub-tab bullet above for why that alone isn't enough to actually look
   disabled), so "both streams removed" (an empty file) is unreachable
   rather than something a validation dialog has to catch. Because that
   rule spans two panels, it also calls `SubTabBar.set_marked(...)` to turn
   the other tab's button red (`STOP_RED`) — otherwise removing a stream
   would silently change state on a panel the user can't see — and
   `carousel.set_strip_state(...)` so the preview shows it too (gradient
   waveform for stripped video, mute badge for stripped audio).
2. **Container → codec lists** (Encoding), via `formats.video_codecs_for` /
   `audio_codecs_for`. **Muxing inverts this**: nothing is re-encoded, so
   the *source's* codecs decide which containers are reachable
   (`formats.containers_for`) — an H.264 file simply isn't offered `.webm`.
3. **Video codec → profile / level / rate-control.** `'4.0'` means different
   things to H.264 and H.265, VP8 has no profiles at all, and the MPEG-era
   encoders take a **qscale (1-31), not CRF** — so the Profile/Level lists
   *and the quality slider's kind, range, default and end labels* all come
   from `formats.quality_for` (see `_apply_quality`). `Select` has no spec of
   its own, so the slider falls back to `_FALLBACK_QUALITY` (a plain 0-51
   CRF) rather than freezing on the previous codec's range.
4. **Audio codec → bitrate relevance.** Lossless codecs and an unresolved
   `Select` have no bitrate to set, so the dropdown empties and disables. The
   same "nothing picked yet" state *does* still disable channels / sample-rate
   (genuine re-encode-only knobs).
5. **Enabled state for everything a *removed*, absent, or unresolved stream
   makes meaningless** — Strip Video disables its whole panel, and a stream
   the source genuinely doesn't have (`media_info["has_video"] is False`)
   does too, without touching the checkbox (see "Stream presence /
   absence" below). **HDR→SDR and the quality slider stay live even before a
   codec's picked (`Select`)** (a deliberate choice — you can dial them in
   and let the encoder follow once it's picked); only a removed or absent
   stream greys them. When the slider *is* disabled, `_set_quality_enabled`
   greys the knob + fill too (`_DISABLED_SLIDER`), not just the labels — a
   bare `state="disabled"` leaves a CTk slider looking active.
6. **The rundown**, which is the only cross-panel view.

**Stream presence / absence.** `probe_media`'s `has_video`/`has_audio`
(`core/utilities.py`) answer "does this stream exist at all", independent of
whether the codec was recognized (`False` only once a probe genuinely ran
and found none; `None` — unknown — must never read as absent). Both
`EncodingTab._sync_controls` and `MuxingTab._sync_controls` OR this into the
exact same mechanism Strip Video/Strip Audio already use: the sub-tab button
goes red (`SubTabBar.set_marked`) and the whole panel greys, but the Strip
checkbox itself is only *disabled* (nothing to strip) — never forced checked
or unchecked. On Encoding, a present-or-unknown stream left on `Select`
additionally blocks the job in `_validate_settings`; an absent one is exempt
(nothing to pick for a stream that isn't there).

`_retarget(menu, values, what)` is how a derived dropdown gets a new list:
it calls `ThemedDropdown.set_values`, and when the current pick has become
illegal and had to snap, **posts a toast saying so** ("Encoder switched to
VP9 — .webm can't carry H.265 (x265)"). Silently swapping a codec out from
under the user is exactly what makes an options screen feel haunted. The
`self._ready` flag mutes those toasts while a settings dict is being written
into the form (theme rebuild, preset load), where a snap isn't the user
changing anything.
- **Queue** (`tabs/queue_tab.py`) — the most complex tab; see its own section
  below.
- **Settings** (`tabs/settings_tab.py`) — a left-aligned settings form with
  four options plus a Save button, each option a bold label above its
  control: **Theme** (a `ThemedDropdown` over `core.theme.THEMES`, using its
  `on_hover` hook to live-preview a palette without committing it — see
  "Theming" above for the full palette/persistence/live-rebuild design —
  plus a small two-swatch live color preview, since the dropdown text alone
  doesn't convey the actual colors. The panel's `<Unmap>` resets the preview
  back to the committed selection); **Appearance
  Mode** (a `ThemedDropdown`,
  System/Light/Dark, wired live to `ctk.set_appearance_mode()` on
  change — this takes effect the instant it's picked, no Save needed); and
  **Default Save Location** (`CTkEntry` + "Browse" button opening
  `filedialog.askdirectory()`, updating `app.default_save_location`
  immediately so it's live within the session even before Save is
  pressed — a hand-typed path is pushed to app state on `<FocusOut>`); and
  **Hardware Acceleration (GPU)** (a `CTkSwitch`, `gpu_switch`, moved here off
  the Encoding tab so it's one global preference — `_on_gpu_toggle` writes
  `app.gpu_enabled` and persists immediately, and `EncodingTab._gather_
  settings` reads that app value rather than a control of its own). The
  **Save** button (`_on_save`) persists everything to
  `settings.json` and then posts a **"Settings saved." toast** via
  `app.notify(..., go_to_queue=False)` — this replaced an inline
  `save_status_label` under the button, which is gone. The one exception: if
  the theme actually changed it calls `self.app.apply_theme(new_theme)` to
  apply it live (see "Theming") and returns immediately without posting
  anything — `apply_theme` rebuilds this tab (clearing live toasts) and is
  its own feedback, and nothing below the call may touch `self`. `app.default_save_location` (read from
  `settings.json` in `LlamaGUI.__init__`, alongside `current_file_path`) is
  read by both `MuxingTab.select_save_location` and
  `EncodingTab.select_save_location` as the starting directory for their
  save dialogs whenever no input file is loaded yet (previously hardcoded
  to `""`).
- **YT-DLP** (`tabs/ytdlp_tab.py`) — downloads a link's video or audio
  through the Queue. Same bottom-up layout as Muxing/Encoding: top has the
  Deno warning banner (packed only when the startup check found no usable
  Deno — warn-only, nothing is blocked), a URL entry + `Paste` (fills from
  the clipboard *and* fetches) + `Fetch` (primary; Enter in the entry does
  the same), and a `preview_frame` in the DropBox's bordered look — a
  placeholder until a fetch lands, then the thumbnail (fit to the frame,
  debounced `<Configure>` refit) over a `MarqueeLabel` title and an
  "uploader · length" line. Bottom has a `Mode` `CTkSegmentedButton`
  (`Video + Audio` / `Video Only` / `Audio Only`), a `Codec` / `Quality` /
  `Format` dropdown row with an `≈ size` readout — in Video + Audio the
  Format dropdown is labelled **`Video:`** and a fourth **`Audio:`** dropdown
  (`audio_menu`, the separate audio stream's codec) sits beside it; the other
  modes hide it (`_show_audio_picker`) and say `Format:` — the save row, and
  `Queue Task` / `Download` (queue + start, same toasts pattern as Mux/
  Encode). Everything below the URL row is disabled until a fetch succeeds.

  **Fetch** is `app.fetch_ytdlp_info(url)`: a daemon worker runs
  `downloader.fetch_info` (`yt-dlp -J`) plus `download_thumbnail`, and hands
  back `("ytdlp_info", token, url, (info, error, thumb))` on the app's
  existing `_thumb_queue` / `_drain_thumbnails` poller (its own
  `_ytdlp_token` drops a superseded fetch). `on_ytdlp_info` either shows the
  error (via `after(0)` — never a modal from inside the poll) or adopts the
  video: every pick resets to its best default and the save path's FILENAME
  becomes `downloader.safe_stem(title)` + the plan's extension, keeping the
  folder (same rule as the other tabs). The fetched URL is what's queued;
  editing the entry after a fetch blocks queueing ("Link Changed") until
  it's fetched again.

  **`_sync_controls` is the single constraint pass**, same contract as the
  other tabs: Mode (only modes the video supports) → Codec (`Best
  Available` + codecs that mode can use) → for video modes Quality
  (resolutions/fps/HDR of that codec, `Best` first) → Format (containers
  that exact pick fits *without re-encoding*) → in Video + Audio, Audio
  (`Best Available` + the audio codecs that can sit beside that video in
  that container — `downloader.audio_codecs_for`; so `.mp4` offers AAC,
  `.webm` Opus, `.mkv` both, and it's disabled when the picked stream
  already carries its own audio). Format decides Audio, never the other way
  round, same one-directional rule as everywhere. For Audio Only the last two
  swap — Format (`Original` + `.mp3/.m4a/.opus/.flac/.wav`) → Quality
  (source bitrates for Original, target bitrates for lossy, empty/disabled
  for lossless). A snap toasts (`_retarget`) unless it was caused by a Mode
  switch, whose lists are a different kind. The resolved plan
  (`downloader.resolve`) drives the size readout and the save path's
  extension. Settings keys: `url, title, thumbnail_url, output_path,
  output_format, mode, video_codec, audio_codec, quality, download,
  url_text` — `audio_codec` only in Video + Audio (absent otherwise, so the
  details popup skips its "Audio Codec" row); `download`
  is the resolved plan the queue runs; `url_text` only exists for the theme
  rebuild.

### Queue tab

`QueueTab` tracks tasks in `self._rows` (`task_id -> row dict`), keyed by an
incrementing int. Each task carries a `source_tab` string (`"Encoding"` or
`"Muxing"`) recording who queued it, used by the details popup to label
itself correctly and to pick the in-progress status text
(`"Encoding..."` vs `"Muxing..."`).

**Row styling is status-driven, not positional.** `_apply_row_style` reads
the row's current status text and applies one of three style dicts
(`_QUEUED_STYLE` = solid yellow, `_GREY_STYLE` = grey base, `_FAILED_STYLE` =
solid `STOP_RED`) — "Queued" is yellow, "Done" is flat grey, "Failed" is red,
anything else (an in-progress label, or "Paused") is grey with the fill
visible. `_FINISHED = ("Done", "Failed")` is the set a row can end on. This replaced an earlier alternating-stripe scheme;
there's no reason to reintroduce positional coloring here.

**Per-row progress visualization — TWO stacked raw `tkinter.Canvas`es, not
one.** While a row is running, its whole description area is repainted by
`_paint_progress` on every tick:

- `base_canvas` — spans the *entire* description region (`0` to
  `max_fill_width`, i.e. `status_label.winfo_x()`), drawn in the row's own
  grey, with the description text in the normal label color.
- `progress_canvas` — the *same* drawing clipped to `fill_width`, in the
  theme's `primary`, with the description text in `primary_text`.

Both are painted by the shared `_paint_row_canvas`, which draws a `w`x`h`
block with its **two left corners rounded** (radius `_ROW_CORNER`, echoing
the row) and a **square right edge** (on the fill canvas that edge is mid-row
and moving; a rounded end there reads as a floating blob). The shape is a
body `create_rectangle` plus a left edge-strip rectangle and two
quarter-circle `create_arc` pieslices — *not* one `create_polygon` with
`smooth=True`, which bowed the straight top/bottom/right edges into visible
curves.

**Why two canvases and not one over the label.** The fill edge has to be able
to cut a glyph in half, so the text either side of it must come from the same
renderer at the same coordinates. An earlier version had one canvas painting
over `description_label`, which put the seam between a *canvas*-rendered
glyph half and a *CTkLabel*-rendered one — and those two renderers do not
agree. Measured against each other by rendering both states and comparing ink
columns/rows: identical text width (263px, so the font matches), but the
canvas copy landed exactly **1px right and 1px down** of the label's. Every
glyph the fill edge crossed visibly sheared. Covering the label entirely with
`base_canvas` means the seam is only ever between two canvases drawing the
same string, same font, same local coords — they cannot disagree. Verified by
parking the fill edge mid-glyph at several widths and inspecting the seam.
`description_label` still owns the row's *layout*, and still renders the text
itself while the row is `Queued` or `Done` (both canvases `place_forget`n by
`_apply_row_style`).

A raw `Canvas` is what makes the clip possible at all: it genuinely crops
whatever it draws to its configured width/height, unlike `CTkLabel`, which
silently ignores a `width` smaller than its natural text size and renders the
full unclipped string (confirmed by direct pixel sampling).

**Both canvases' `bg` is the row's *backdrop*, not the row's own grey**
(`_row_backdrop_bg`, which just reads CTk's own already-resolved
`row.cget("bg_color")` — the color a `CTkFrame` paints outside the rounded
rectangle it draws in `fg_color`). This matters because a canvas is a hard
rectangle sitting on the row's left end, and the only pixels of it the shape
leaves unpainted are the two ~8px corner nooks outside the rounded left
corners. Painting those the row grey (as an earlier version did) filled the
row's own corner cutouts with a solid block, so a running row read as a
square grey box with a rounded fill floating inside it. With the backdrop
there instead, the row stays visibly rounded on all four corners whether or
not a fill is present — confirmed by capturing the window and sampling the
corner pixels (backdrop `gray17`) against the fill (`primary`). The row's own
rounded background is drawn by an **internal canvas created synchronously
inside `CTkFrame.__init__`**, i.e. before any of `row`'s own children exist —
a widget placed without accounting for this can end up stacked *below* that
internal canvas (permanently invisible); see the construction order below for
how these avoid it.

`fill_width` is computed once in `_paint_fraction`
(`round(fraction * max_fill_width)`) and passed straight through, so the
visible fill edge and the text clip edge are the same number by
construction — there is no second, independently-rounded width for anything
to disagree with.

**Widget stacking order is construction order.** Tk stacks later-constructed
siblings higher, and `add_task` leans on that directly rather than calling
`.lift()`/`.lower()` anywhere. Constructing in the order
`description_label` → `base_canvas` → `progress_canvas` → `thumb_label`
yields exactly the z-relationships needed: both canvases paint over the
label, the fill paints over the grey base, and the thumbnail stays above all
of it so the fill can never cover it however far it grows. Confirmed by
isolating this exact order and comparing rendered pixels. Packing (the actual
left-to-right visual layout — thumbnail first, then description) happens
afterward in whatever order produces the right layout; pack() call order and
construction order are independent knobs.

**The right-hand `remove_btn` and `status_label` are packed
(`side="right"`) *before* the expanding `description_label`.** `pack()`
carves the cavity in call order, so when the description was packed first,
any long file name requested more than the row had left and squeezed both
out entirely: unmapped, `winfo_x()` 0, no status text, no ✕. That also
zeroed the progress fill, which is capped at `status_label`'s left edge.
Found by printing row geometry while a real job ran. Packed last, the
description just gets whatever room remains and clips.

Several approaches were tried before this one (see the gotchas below for the
detail on each): a single opaque overlay label clipped via
`configure(width=...)`, defeated by `CTkLabel`'s width behavior above;
individually-recoloring one `CTkLabel` per character (matching `fg_color` to
whatever was behind each glyph), which got contrast working but only at
per-character granularity, so the boundary visibly drifted ahead of or behind
the fill's smoothly-moving edge — and cost one widget per character; and a
two-widget version (a `CTkFrame` fill plus a separately-sized text canvas)
whose two independently-rounded `fraction * width` calculations — one via
`place(relwidth=...)`'s internal rounding, one via a float passed to
`canvas.configure(width=...)` — didn't always land on the same pixel, showing
as an intermittent 1px seam.

**Start / Pause / Stop act on a real ffmpeg process** (see "Encoding flow").
`start_all_btn` toggles between "Start Queue" and "Pause Queue"
(`_set_running`). `self._active` is the one job with a process —
`{"task_id", "job", "rest", "paused", "fraction", "drawn"}` or None.
- **Pause** (`pause_queue`) *suspends* the ffmpeg process in place
  (`FfmpegJob.suspend` → `NtSuspendProcess`), cancels the poll, and shows
  "Paused". Nothing encodes while paused; **Start** (`start_queue`) thaws it
  and it carries on from the exact frame it froze on.
- **Stop** (`stop_queue`) kills the process (works while suspended too),
  deletes its `.partial` output, and reverts the row to "Queued".
- **Removing the active row** (`remove_task`) kills its process first — a
  process must never outlive its row — and continues with the next job if
  the queue was running.
- `self._poll_job` is the one in-flight `after()` id (`_schedule_poll` /
  `_cancel_poll`); every path that halts processing goes through
  `_cancel_poll`, so a stray tick can't fire later.

**Details popup** (`self.detail_frame`, hidden until a row is single-clicked
via `_show_details`): fixed overall height regardless of task kind — a
`CTkScrollableFrame` (`self.detail_scroll`, `height=_DETAIL_SCROLL_HEIGHT`,
packed with `fill="x"` and *no* `expand`, which matters — `expand=True` here
would let it stretch to whatever space is available instead of staying
capped, defeating the fixed-height point) holds the field rows, so a Mux
task's short field list fits without scrolling while an Encode task's longer
one (Encoder/GPU/HDR/Strip Video/CRF/Profile/Level, absent from Mux) scrolls
inside the same box. `_DETAIL_FIELDS` drives which settings keys get shown and how
(`None`/`"time"`/`"bool"` formatting); a key simply absent from a task's
settings dict is skipped, which is how Mux tasks naturally omit the
encoding-only fields. Popup is packed with `before=self.controls_frame` so
it always lands directly above the bottom buttons regardless of call order.
Single-click (not double-click — that binding was deliberately removed, see
below) shows it; the popup's own "✕" just calls `self.detail_frame.pack_forget`.

**The single-click binding is on `base_canvas` and `progress_canvas` too**,
not just `row`/`thumb_label`/`description_label`/`status_label`. While a job
runs those two canvases sit *on top of* `description_label`, so without their
own bindings a click on the description text of a running row hit dead space —
the popup would only open from the thumbnail end or from `status_label`
onward. `remove_btn` stays unbound (its own click must not also open details).

**The task list's scrollbar auto-hides into a fixed gutter.**
`CTkScrollableFrame` grids its scrollbar into its own column and nothing
else, so the bar turning on steals ~18px from the rows — and because the
canvas re-fits only on its next `<Configure>`, the bar spends a beat drawn
*over* the rows before they reflow narrower (a visible flicker, then a
click-triggered truncation). `_autohide_scrollbar_in_gutter(self.list_frame)`
(module function, once in `__init__`) fixes both halves:
- `_parent_frame`'s column 1 gets a permanent `minsize` (`_SCROLLBAR_GUTTER`
  = 18) so the gutter is always reserved whether the bar sits in it or not —
  the row area's width never changes. `list_frame`'s own right pad is trimmed
  `20 → 3` to match, so that gutter comes out of the window margin, not the
  rows (rows stay exactly as wide as they were with no bar).
- the inner canvas's `yscrollcommand` is routed through a relay that still
  forwards every update to the real `CTkScrollbar.set` but `grid()`/
  `grid_remove()`s the bar as the content crosses the overflow line.

Touches `_parent_frame` / `_scrollbar` / `_parent_canvas` — CTk exposes no
public hook. Only `list_frame` gets this; `detail_scroll` is fixed-height and
deliberately scrolls.

**Download rows** (`source_tab="YT-DLP"`). `_process_next` hands them to
`_start_download`, which builds a `YtDlpJob` from the task's `download` plan
(argv built on the Tk thread and printed, same as ffmpeg jobs). The job
shares FfmpegJob's control/event contract plus a `("stage", text)` event:
`_poll` stores it on `self._active["stage"]` and sets the row's status to it
("Preparing..." → "Downloading video..." → "Downloading audio..." →
"Merging..." / "Converting audio..." → "Finishing...") while the fill keeps
going — **any event other than progress/stage is terminal**, so a new event
kind needs a branch there. `_running_label(task_id, active)` returns that
stage, which is how Start after Pause restores "Downloading audio..." rather
than a generic label. Rows show the video's online thumbnail
(`thumbnail_url` — the tab's cached one when it's the same link, else fetched
on the row-thumbnail worker), the details popup titles itself "Download
Details" with Title/Link/Mode/Video Codec/Audio Codec rows, and a failure reads "“<title>”
couldn't be downloaded." Verified through the real Queue: stage sequence,
pause/resume label, a forced-bad format failing with yt-dlp's own reason,
and an ordinary Mux job still running to Done alongside the changes.

**Overall progress bar** (`self.progress_bar`, top of the tab, replaced an
earlier plain "Encoding Queue" header label): tracks `(done + the active
job's own live fraction) / total` across *current* rows, recalculated in
`_update_overall_progress` on every add/remove/status change **and on every
`_poll` tick** — it used to be `done / total` with no live term, so it sat
completely still for the entire length of whichever job was actively
running and only ever jumped at Queued/Done/Failed transitions; the running
job's own row-level fill (`_paint_fraction`) was live the whole time but the
bar above it wasn't. `corner_radius=0` here too, for the same reason
`progress_canvas` is a plain rectangle — `CTkProgressBar`'s rounded end-caps
are drawn as full
circles regardless of fill amount, so even at value 0 two overlapping caps
paint a visible dot of `progress_color`; flat corners avoid that. It resets
to 0 (`_on_hide`, bound to `<Unmap>`) whenever the tab is switched away from
*while at 100%*, so returning later or starting a new batch doesn't show a
stale "done" bar from a batch already dealt with.

Double-click used to reopen a task's settings back into its source tab; that
binding was **removed on request** — single-click-for-details is now the
only click behavior on a row. `_edit_task` no longer exists.

`pending_task_count()` reports how many tasks are not yet finished — in-flight,
paused *and* still-queued, i.e. everything that would be lost on quit (a
`Failed` row has nothing left to lose, so it doesn't count); `LlamaGUI.
on_close` reads it to decide whether to confirm before exiting, and
`clear_all` reads it for the same reason.

**Bottom-left buttons**: `Clear Completed` removes finished rows (`Done` and
`Failed`);
`Clear All` (to its right) empties the queue outright. `clear_all` confirms
first via `ask_yes_no` **only when something unfinished would be thrown
away** — an all-`Done` or already-empty queue clears with no prompt — then
calls `stop_queue()` *before* removing rows, so no pending animation tick can
fire against a row that no longer exists.

### Dropdowns

**Every dropdown in the app is a `ThemedDropdown`** (`components/dropdown.py`)
— Theme and Appearance Mode on Settings; Output Format and Preset on both
tabs' Overview panel; Encoder / Profile / Level / Speed and the four audio
dropdowns on Encoding; the track pickers on Muxing. Most of those are **derived** —
their option lists are rewritten by `_sync_controls` via `set_values`, not
fixed at construction. It
subclasses `CTkOptionMenu` but redirects `_open_dropdown_menu` to a custom
panel, because the native popup can't do two things this app needs:

1. **Stay open until an explicit dismissal.** A click on the button again, or
   anywhere outside the panel (`_on_global_click`, a `<Button-1>` binding
   added on the main toplevel with `add="+"` while open and removed by funcid
   on close). Moving the pointer off it does nothing — an earlier `<Leave>` +
   pointer-position close was removed on request.
2. **Report row hover** (`on_hover`), which the theme picker needs for its
   live palette preview. The native popup is modal on Windows and repaints
   nothing behind it, so a hover preview is invisible there.

`command` is deliberately **not** passed to the base class — the native
value-picking path never runs, so `_select` invokes the caller's callback
itself.

**The panel lives in its own borderless `Toplevel` (`self._popup`)**,
withdrawn until `open()`. It used to be a `CTkFrame` `place()`d over the main
window — but the window is fixed and short, so a dropdown near its bottom
edge (Encoding's Encoder/Format/Profile/Level row, Muxing's Output Format)
had its lower entries clipped by the window edge. A separate window can
overflow that edge instead (verified — `Baseline` now hangs *below* the app
window). Consequences: (a) the popup isn't torn down with the tab that owns
the dropdown, hence the `destroy()` override — matters on a live theme
rebuild; (b) it doesn't move with the main window, so `open()` also drops it
on any main-window `<Configure>` / `<Unmap>` (`_on_root_change`, guarded on
`event.widget is` the toplevel since a toplevel binding also sees children's
configures); (c) `open()` pins the popup's own `bg` to the panel's fill so
the `CTkFrame`'s rounded-corner nooks don't show a mismatched square.

**It always opens straight downward, never shifted.** By request — there used
to be an upward-flip-when-cramped branch here (`anchor="sw"`, grow up), then
a stay-on-screen `y`-clamp; both removed. `open()` positions the popup window
at the button's bottom edge (`winfo_rooty() + winfo_height() + _PANEL_GAP`,
screen coords) at the button's width. Because the popup is its own window
(above), entries past the app window's bottom edge overflow it rather than
being clipped.

**Open and close are animated (`_anim`).** The popup *unrolls*: `self.panel`
sits at full size, `place()`d at `(0, 0)` and clipped by a popup window whose
height animates from ~0 to full (ease-out), with `-alpha` fading
`_ANIM_MIN_ALPHA`→1 in step. Close is the reverse, fewer steps
(`_ANIM_CLOSE_STEPS` vs `_ANIM_OPEN_STEPS`, both × `_ANIM_INTERVAL_MS`),
ending in `withdraw()`. `self.panel` uses `place(relwidth=1.0)` — *not* pack
— specifically so the shorter-than-panel window frames **clip** it instead of
compressing the rows (relative `relwidth` is fine on `.place()`; it's
absolute `width=`/`height=` that CTk rejects there). One `after` job
(`self._anim_job`), cancelled by every `open`/`close`/`destroy`. `destroy`
and `_on_root_change` pass `animate=False` to `close()` for a synchronous
hide.

### User feedback: dialogs and toasts

Two separate mechanisms, deliberately not interchangeable. **Blocking
problems get a modal dialog** the user has to acknowledge; **things that just
happened get a toast** that goes away on its own.

**`components/dialogs.py` — `MessageDialog`**, a themed modal `CTkToplevel`
with a bold title, a wrapped message, and one or two buttons. Two helpers
wrap it: `show_message(app, title, message)` (single OK) and
`ask_yes_no(app, title, message)` (returns True *only* on an explicit Yes —
Escape, the titlebar close box, and any other outcome all count as No, so a
dismissed confirmation can never destroy work). The first button in the list
is the affirmative one and gets `primary`; the rest get `secondary`.

This is a custom CTk toplevel rather than `tkinter.messagebox` because the
native Windows boxes ignore the app's theme completely. Two ordering details
matter: `grab_set()` raises "window not viewable" if called before the
toplevel is mapped, so it comes after `deiconify()` + `wait_visibility()`;
and CTk re-applies its own titlebar styling ~200ms after construction, so the
window icon is set from an `after(250, ...)` (best-effort — a missing
`llama.ico` must never take a dialog down with it).

Current dialogs:
- **Raised from `_validate_settings` in Muxing/Encoding:** no input file; no
  save location; and the output checks in `confirm_output_path`
  (`components/dialogs.py`). Those refuse a folder or the input file itself,
  and ask **"File Already Exists"** when the path is on disk *or* already
  claimed by an unfinished job (`QueueTab.claims_output`). No means the job
  isn't queued. Asking at queue time is what lets the queue run without ever
  stopping to prompt.
- **"Job Failed"** (see "Encoding flow").
- **The close confirmation** in `LlamaGUI.on_close`.

**`show_message`/`ask_yes_no` block in a *nested* event loop**
(`wait_window`), and `after()` callbacks keep firing inside it. So never open
one from inside a recurring tick (e.g. the queue's `_poll`): the tick
re-enters itself and dialogs can stack. `QueueTab._show_errors` posts failure
notices via `after(0)` and shows them one at a time behind an
`_error_dialog_open` guard.

**`on_close` pauses the queue for the duration of its prompt** and resumes it
if the user backs out. Otherwise a job would keep encoding (and could even
finish) behind a modal dialog asking whether to cancel it. *Pausing* rather
than stopping is what makes that reversible: `pause_queue` suspends the
in-flight ffmpeg in place, so `start_queue` resumes it from the exact frame
it froze on, while `stop_queue` would kill it. On confirm it calls
`QueueTab.shutdown()` before `destroy()`. **Windows doesn't take a child
process down with its parent**, so without that an encode would keep running
(or stay frozen) after the app is gone.

**`components/toast.py` — `Toast` / `ToastManager`**, reached through
`app.notify(message)`. A toast drops in from above the *current tab frame's*
top-**right** corner (read off the live tab's own `winfo_rootx/rooty/width`,
not recomputed from sidebar width + padding), holds ~2.2s, then fades and
destroys itself. Clicking one jumps to the Queue tab and dismisses it.
`clear()` drops them all — `apply_theme` calls it, since live toasts are
positioned against tab frames that a theme rebuild is about to destroy.

**A toast is a borderless `Toplevel`, not a frame inside the main window, and
that's what makes its rounded corners real.** Tk has no per-pixel
transparency for an in-window widget: a rounded `CTkFrame` must paint
*something* in the four corner nooks outside its shape, and any flat colour
you pick is only invisible where it happens to match. As a child of the main
window that produced grey corner squares wherever a toast overlapped a queue
row or a thumbnail. A Toplevel can do better on Windows —
`-transparentcolor` punches every pixel of `_TRANSPARENT_KEY` (`#FF00FE`)
clean out of the window. Verified by sampling each corner pixel with and
without a toast present: 12/12 identical, including corners over a queue
row's fill.

Three consequences worth knowing:

- **The body is drawn on a raw `tkinter.Canvas`, not a `CTkFrame`.** A colour
  key only punches pixels matching it *exactly*, and CTk anti-aliases its
  rounded corners against `bg_color` — those blend pixels match neither fill
  nor key and survived as a visible magenta fringe. Tk's canvas primitives
  don't anti-alias, so `_draw_body` lays down the rounded rect by hand (two
  overlapping rectangles forming a plus, plus four quarter-circle pieslices —
  the same construction the queue's progress fill uses). Every pixel ends up
  exactly the fill or exactly the key. The trade is slightly stair-stepped
  corners.
- **The fade is real `-alpha`** on the window, replacing an earlier
  colour-interpolation fade that had to blend toward an assumed backdrop
  (wrong for the same reason the corners were) and cost a full CTk redraw per
  step. Both layered attributes apply together.
- **Being a separate window means it doesn't follow the main one.**
  `ToastManager` binds the app's `<Configure>` to re-anchor toasts when the
  window is dragged, and its `<Unmap>` to clear them on minimize (they're
  `-topmost`, so they'd otherwise be left floating over the desktop). Both
  handlers check `event.widget is app`, since a toplevel binding also
  receives its descendants' events.
- Canvas text needs the font CTk labels actually render at:
  `ThemeManager.theme["CTkFont"]` stores a *positive* size but CTk applies it
  as a **negative** Tk size (pixels, not points), so `_label_font` negates it.
  Passing the positive value straight through renders noticeably larger than
  every other label in the app.

**At most `_MAX_VISIBLE` (3) toasts hold a slot, and that cap is a
performance fix, not just a cosmetic one.** Every toast runs its own
`after()` chain (slide, hold, fade) — so an uncapped stack turned
button-mashing into dozens of concurrent timer chains competing with the UI
thread, which showed up as tab switches lagging. When this was investigated
(against an earlier CTk-redraw-per-step fade, since replaced by the `-alpha`
one), event-loop latency under 60 rapid notifications measured **p90 79.7ms
uncapped vs 6.1ms capped** against a 6.0ms idle baseline; the current alpha
fade is lighter per step but the cap on concurrent chains is what keeps it
bounded. A further arrival calls `retire()` on the oldest slot-holder, which
skips any remaining hold and cuts to a fast fade; retiring toasts stop
claiming a slot immediately (`is_retiring`) but stay put while they fade
rather than making everything below them jump. `forget()` triggers
`_relayout()` so a dismissed toast doesn't leave a hole — survivors *snap*
to their new slot rather than animating, since one more timer chain per
survivor is exactly the cost being avoided. `show()` also only forces an
`update_idletasks()` layout pass when the tab frame genuinely hasn't been
laid out yet.

`_fade` steps `-alpha` on the whole window from 1 toward 0 (no widget redraw
at all); the toast still pins its canvas `bg` to `_TRANSPARENT_KEY` and the
window's `-transparentcolor` to match, so the rounded corners stay punched
out for the life of the fade.

Current toasts: "Encoding/Muxing job added to queue." (Queue Task on either
tab), "Encoding/Muxing job has begun." / "…will run next." / "…will run next
— the queue is paused." (the direct Encode/Mux buttons, picked by
`start_task`'s return value), and
"Settings saved." (Settings tab's Save button — `go_to_queue=False`, so
clicking it does nothing; it replaced an inline status label under the
button). The Save button's other path — an actual theme change — posts no
toast, since `apply_theme` rebuilds the tab (and clears live toasts) and is
its own visible feedback.

### Components

- **ThemedDropdown** (`components/dropdown.py`) — see "Dropdowns" above. Every
  dropdown in the app uses it; don't add a bare `CTkOptionMenu`.
  **`set_values(values)`** replaces the option list and rebuilds the popup's
  rows, which is what makes the derived Encoding/Muxing menus possible (the
  container decides which codecs exist, the encoder decides which
  profiles/levels do). It **no-ops when the list is unchanged** — the common
  case on a `_sync_controls` pass — because rebuilding row buttons every
  keystroke would flicker and churn widgets pointlessly. An empty list
  renders a single `—` placeholder, paired with `state="disabled"` for an
  option the current codec simply doesn't have. It never fires `command`;
  the caller owns any value change it causes.
- **SubTabBar** (`components/sub_tab_bar.py`) — the `Overview` / `Video` /
  `Audio` switch. **The whole bar is one `tkinter.Canvas`**, not a row of
  `CTkButton`s — each "button" is **one filled `create_polygon`** (a
  rounded rect, corners built as short point-arcs by `_round_rect_points`)
  plus a centred text item. It was a body rect + cross rect + four corner
  shapes, but Tk rasterises a `create_rectangle` edge and an adjacent
  `create_oval` / `pieslice` edge ~1px apart, so a notch showed where any
  corner met a straight edge (seen on the left first, then the right — same
  cause). One polygon fills by one rule → no seam. Switching animates each
  button's height + fill by
  updating those items' `coords`/`itemconfig` **in place**; no widget is
  resized or reconfigured, so there's none of the per-frame redraw /
  text-reflow flicker an animated `CTkButton` produced (reported three
  times). Active = theme `primary` at `_ACTIVE_H`; inactive = `secondary` at
  `_INACTIVE_H` (80%), bottom-aligned so the current tab reads as raised.
  `_animate` → `_anim_tick` runs the transition on a **wall-clock** ease
  (`_ANIM_DURATION` 0.17s; `_ANIM_MS` is only the poll interval) — a
  step-counted version dropped frames unevenly on this box (`after` runs
  ~11ms slow) and the fade looked like it lurched into the final colour.
  `smoothstep` on height (kept float, not rounded per frame), straight-RGB
  `_lerp_hex` on fill, text colour snapping at the midpoint. **Both fade
  endpoints go through `_display_fill`** (which folds in the hover shade when
  the pointer is on a button) so the fade can't settle on `_fill_for` and
  then snap to `_hover_fill_for` — that end-snap *was* the "flicker near the
  end of the fade". `_redraw`/`_paint` repaint from `self._state`.
  Hover/click are hit-tested
  by x against the button ranges (`_hit`). `set_marked(name, bool)`
  cross-fades a button to/from the permanent `STOP_RED` whether or not it's
  active — that's what keeps the cross-panel Strip rule honest, since
  removing a stream otherwise changes state on a panel the user can't see.
  Canvas `bg` is pinned to the header's resolved colour (`self._canvas.cget`)
  so the bar blends in. Nothing to refresh on a live theme switch — the
  owning tab is rebuilt whole. **Do not name an attribute `self._options`** —
  that shadows a real `tkinter.Misc` method and breaks every `.configure()`;
  it's `self._names`.
- **SummaryPanel** (`components/summary_panel.py`) — the Overview sub-tab's
  export rundown, a compact `label  value` list. It's structural, not
  decorative: the Video and Audio panels each hide the other's state and
  several rules span them, so this is the one place every cross-panel
  consequence is visible at once (a removed stream shows `— removed —` in
  `STOP_RED`). Its rows are `Video` / `Audio` / `Length` (renamed from
  `Trim`; the "whole file" value is now capitalized `Whole File` to match)
  — the output container is **not** listed, since the Output Format
  dropdown sits right next to it and already says it. Rows are built once
  from `labels` and only ever *reconfigured* by `set_values` — `_sync_
  controls` refreshes it on every control change, and widget churn at that
  rate flickers. Text is kept terse because it shares its row with the
  controls and has ~260px to work with.

  **The value column is a `MarqueeLabel`, not a plain `CTkLabel`** — a
  genuinely long value (a multi-stream audio summary with a "+N more"
  tail, say) would otherwise silently overflow rather than scroll
  (`CTkLabel` ignores a width smaller than its natural text size; see
  Known Issues), extending past this panel's own narrow budget. Sits still
  when the text already fits, same as everywhere else `MarqueeLabel`'s
  used. This required extending `MarqueeLabel` itself with a `text_color`
  override (`set_text_color` / `configure(text_color=...)`, tracked
  separately from its resolved, appearance-mode-applied `_fill` so a
  light/dark flip re-resolves the override instead of falling back to the
  plain theme default) — `SummaryPanel.set_values` already called
  `label.configure(text=..., text_color=...)` for the `STOP_RED` "removed"
  states, which a bare `CTkFrame.configure` has no `text_color` kwarg for.
- **AnimatedSwitch** (`components/animated_switch.py`) — a `CTkSwitch`
  subclass whose knob *slides* between off/on instead of snapping. Keeps a
  float `_anim_value` (0..1) alongside CTk's boolean `_check_state`, eases it
  on every `set()` (the common path for `toggle`/`select`/`deselect`/a bound
  variable), and feeds it to the draw engine's `slider_value` (which already
  takes a float) — so nothing about colours, the disabled look, hover or the
  label is reimplemented. Overrides `_draw` to re-apply the fractional knob
  position after CTk's own redraws (resize / appearance / colour changes
  re-snap it to 0/1). Reaches into `_draw_engine` / `_draw` — private CTk
  API, same as ThemedDropdown; customtkinter is version-pinned. Currently
  only the Encoding tab's HDR-to-SDR toggle uses it (Settings' GPU switch is
  still a stock `CTkSwitch`).
- **MessageDialog** (`components/dialogs.py`) and **Toast / ToastManager**
  (`components/toast.py`) — see "User feedback: dialogs and toasts" above.
- **AudioStreamPickerDialog** (`components/audio_stream_dialog.py`) — the
  "Choose Stream(s)" modal on Encoding's Audio panel; modelled on
  `MessageDialog`'s own theming/centering/icon conventions but with one
  checkbox row per probed audio stream instead of a fixed message + button
  row. See "Multi-stream audio" under "Encoding flow" below for the full
  picture (what it returns, and how the chosen streams flow into a job).
- **DropBox** (`components/drop_box.py`) — self-packing (`self.pack()` in
  `__init__`, so callers don't need to). Takes an `on_file_selected` callback
  (in practice always `app.update_global_file`) and an optional `height`
  (default 280; Muxing/Encoding both pass 380). Drop/double-click are bound
  on the frame, its content frame, and the label, since tkdnd doesn't
  propagate to children.
- **ThumbnailCarousel** (`components/thumbnail_carousel.py`) — shows one of up
  to ten preview frames at a time (Muxing + Encoding). Owns the thumbnail
  `CTkLabel`, the fit-to-widget resize math (from the old
  `_resize_thumbnail`), and the prev/next navigation. `set_frames(list)` is
  the `on_thumbnail` broadcast target; `on_populated` fires once so the tab
  can reveal it; `on_reselect` is the double-click handler.

  **Strip state / audio-only.** Each tab's `_sync_controls` calls
  `carousel.set_strip_state(strip_video, strip_audio)`; `app` calls
  `carousel.set_audio_only(bool)` when the imported file has no video stream
  (see "Audio-only inputs" above). **Both** paths render the same
  `Wave Loop` visualiser (`_render_stripped` runs when
  `_strip_video or _audio_only`); `set_audio_only(True)` additionally clears
  any stale video `_frames` and fires `on_populated` so an audio import
  reveals the carousel. Video stripped
  replaces the whole preview (`_render_stripped`) with the **`Wave Loop.json`**
  Bodymovin dot-wave animation, played by a self-re-arming `after` tick
  (`_start_wave` / `_stop_wave` / `_wave_tick`) that only runs while the video
  is stripped — a niche state — and stops the instant it isn't (and on
  `destroy`, so a live theme rebuild can't leave a tick firing at a dead
  widget). Every frame is rendered by **rlottie** (`_wave_animation`, a
  process-lifetime singleton) with all dot fills flattened to white
  (`_force_white_fills` — rlottie has no expression support, so the JSON's
  `Main Dot color` expression is already moot and only the baked `k` matters),
  then that frame's alpha composites the horizontal `primary`→`secondary`
  gradient over the resolved backdrop colour (`_wave_frame_rgb` /
  `_wave_gradient`, both cached per size) — an **opaque** RGB image (the dots
  read lit, the gaps as the app backdrop; opaque because `ImageTk` is faster
  than carrying an alpha channel and the wave fills the frame anyway).

  **Painted on a bare `tk.Label` (`_wave_label`), never a `CTkImage`.**
  `CTkImage.configure` runs a per-widget DPI-scaling pass that measured
  **~150ms for a full-size frame** on this 175%-scaled DPI-unaware process —
  the animation ran at ~6fps. A plain `ImageTk.PhotoImage` on a raw
  `tk.Label` is ~2ms → a steady ~32fps. See the Known Issues entry.
  `_wave_label` carries the press bindings so a double-click still reselects;
  `_stop_wave` `place_forget`s it to reveal the normal preview underneath.

  **`_wave_label` is a child of the *selected tab's frame* (`_wave_host` — the
  last ancestor before the toplevel), not the carousel — so the wave bleeds
  past the DropBox / `top_container` inner padding but stops at the tab
  frame's own edges.** `_wave_geometry` places it at the carousel's vertical
  band, full tab-frame width (`_place_wave_label` re-renders only when that
  size actually changes — it's stable). Parenting to the tab frame means it
  hides and is destroyed *with the tab* like a normal child (a live theme
  rebuild throws the tab away); `_wave_tick` still `place_forget`s it while
  `self.winfo_viewable()` is false and re-places + `lift`s on return, and
  `destroy()` also kills it, both belt-and-braces. `_wave_geometry` falls
  back to the carousel's own box until the tab-frame geometry is readable.

  Playback is **time-based**: `_wave_frame_at` maps wall-clock elapsed since
  `_wave_t0` → a loop frame index at `_WAVE_SPEED`× the comp's own rate, so
  `after`-cadence jitter never changes playback speed, and `_wave_tick`
  repaints nothing when the index hasn't moved. `_WAVE_INTERVAL_MS` (16) is
  well under a frame because Tcl's `after` adds ~11ms of its own. The tick
  skips the repaint while the tab is hidden (`winfo_viewable`) but keeps the
  clock running so it resumes at the right phase.

  rlottie scales the 1920×1080 comp to the render *width* (dots stay round at
  any width), so `_wave_frame_rgb` renders at natural aspect — oversampled
  `_WAVE_SS`× (1.5) for crispness on the DPI-scaled display — crops the dot
  band (`_WAVE_BAND_LO`..`_WAVE_BAND_HI`, *outside* the true ~0.48–0.89
  envelope so nothing clips) and scales it to `_WAVE_FILL` (0.88) of the
  height, centred with a small vertical margin — a gentle ~1.3× stretch, dots
  stay round-ish. Horizontally it fills the (bled-out) label width, so the
  wave's sparse left/right taper reaches the tab frame's edges rather than
  stopping short at the DropBox's inner margin. Earlier attempts
  at a tighter fill either stretched the dots into blurry ovals or clipped
  the crests. If rlottie can't be imported, `_wave_frame_rgb` degrades to a
  faint flat gradient wash and no tick is armed. Navigation is disabled (no previews to step); a double-click
  still reselects. Audio stripped composites the **`audio-mute.png`** badge
  into the **top-left** corner (`_with_badge`, applied in `_push` for the
  audio-only case; `_wave_frame_rgb` does its own badge paste when the video
  is stripped too). `audio-mute.png` and `Wave Loop.json` sit beside
  `llama.png` in `assets/`; `audio-mute.svg` (the badge's source) is
  checked in too.

  **The bottom-left info badge and its hover tooltip** are a separate,
  permanent fixture (not a strip-state indicator) — see "File selection is a
  broadcast" above for what they show and where the info comes from
  (`set_media_info` / `app._broadcast_media_info`).

  **Two layers, kept separate — the chevrons/dots are their own layer, not
  baked into any frame.** `_base_scaled` is the *pure* fitted video frame;
  `_overlay` is a standalone RGBA layer (transparent except the chevrons +
  dots for the current index), rebuilt only on an index / size / theme
  change (`_build_overlay`). `_push(base)` composites overlay-onto-frame *at
  paint time* — `Image.alpha_composite`, with the overlay's alpha scaled by
  `_arrow_alpha` for the hover fade. They can't be real Tk widgets — Tk has
  no per-pixel transparency for an in-window widget (same root cause as the
  toast's corners, the tab indicator's nooks, the queue fill's backdrop), so
  an overlaid `CTkButton` would be opaque with un-colour-matchable corner
  nooks over the video — but keeping them as an image *layer* gets the same
  result without dirtying the frames.

  **The slide moves the picture, not the buttons** (`_animate_slide` /
  `_slide_step`): a window crops across a `[current | next]` strip of
  *pure* frames (`_SLIDE_STEPS` ticks, ease-out); `_push` drops the *same
  fixed* `_overlay` on every tick, so the image content scrolls under
  stationary chevrons (one set — the destination's — not two sliding past
  each other). The fade and the slide **share one job channel**
  (`_cancel_anim` covers both `_fade_job` and `_anim_job`), so they can't
  fight over the label. Every slide starts from `_displayed_base` (the pure
  frame literally on screen right now), so an interrupting step — a
  spam-click — chains straight on from the current partial instead of
  restarting.

  **The prev/next control is a disc in the theme's `primary` colour** with a
  chevron in `readable_text_on(primary)` (black or white — the same call the
  themed buttons use). Near-solid (`alpha 230`) rather than a translucent
  scrim, so it reads the same over a bright frame region as a dark one — an
  earlier translucent version vanished against matching pixels. Both colours
  are resolved once in `__init__`; a live theme switch rebuilds the carousel
  with its tab, so there's nothing to re-read in place. **The disc is sized
  from each frame's own dimensions** (`min(w,h)*0.12`, capped at `w*0.16` /
  `h*0.42`) and sits flush against the frame edge (`margin + disc_r` in from
  it) — a fixed fractional inset clipped the disc on letterboxed / narrow
  (2.40:1) frames. The chevron itself is drawn with an **optical-centre
  nudge** (`0.13` of its half-width toward the point in `_draw_chevron`): its
  two arm-ends outweigh the single tip, so a geometrically centred V reads as
  shifted toward its opening. The nudge is cosmetic only — `_disc_centers` /
  the click hit-test still use the true centre.

  **The whole overlay is antialiased by supersampling.** PIL's `ellipse` /
  `line` have no AA of their own, so `_build_overlay` draws at `_OVERLAY_SS`
  (4x) — `_OVERLAY_SS_ANIM` (2x) for the per-tick rebuilds mid-slide, where
  the softer in-between frame is invisible in motion — and box-filters down.
  The downscale runs in **premultiplied-alpha space** (`.convert("RGBa")`
  before `.resize()`, back to `"RGBA"` after): without it LANCZOS blends the
  transparent border's black RGB into the edge pixels as a grey fringe (same
  family of bug as the toast's magenta corner fringe). `_rescale(overlay=
  False)` from `_step` skips the ~12ms full-SS build since the slide's first
  tick rebuilds it anyway; `_slide_step`'s final tick and `_cancel_anim` both
  restore a full-SS overlay so a settled preview is never left soft.

  **Dot indicators are a three-size row that moves and resizes.** The centre
  `_DOT_CLUSTER` (3) dots are large and **screen-stationary** (always at
  `w/2-gap`, `w/2`, `w/2+gap` — `_dot_geometry` pins the cluster midpoint to
  centre); beyond them `_DOT_LOOK` (2) dots per side taper medium-then-small,
  and only frames that exist get a dot, so the row is 7 wide in the interior
  (`s m L L L m s`), 5 at the ends (`L L L m s`, mirrored), growing/shrinking
  between. The current-frame highlight *rides the cluster edge it's heading
  for* — right large slot when advancing, left when going back
  (`_resolve_dot_start`) — and a step only scrolls the whole row once the
  highlight is already at that edge; until then the surrounding dots hold
  still and just the highlight hops slot to slot, so a direction change walks
  the highlight back across the middle slot before anything scrolls. A
  multi-step jump snaps straight to the target edge. `_dot_start` (frame in
  the leftmost large slot) is the state; `_dot_anim` = `(prev_start,
  prev_index)` holds the from-state while the row re-flows. The re-flow is
  part of `_overlay`: `_slide_step` rebuilds the overlay each tick with the
  dots interpolated (`_draw_dots(anim, t)` — entering dots grow from `r=0`,
  leaving ones shrink to it, the white highlight cross-fades old→new dot) on
  the **same eased clock as the picture slide**, so both settle together.
  `_cancel_anim` settles the row if a slide is cut short. Dots stay
  white/translucent (theme-independent — white reads on any frame).

  Navigation **clamps at both ends** (only the chevron that leads somewhere
  is drawn — none at index 0's left, none at the last index's right).
  `step(delta)` is the public stepper (the app's Left/Right keybind calls it
  — see **Keybinds**); it forwards to `_step` with `show_arrows=False`.

  **Clicks all go through `_handle_press`, and every click of a spam-burst
  steps.** Tk delivers `<Button-1>` for the first press of a burst and *only*
  `<Double-Button-1>` for every press after it (never `<Button-1>` again once
  `<Double>` is bound) — so both are bound to `_handle_press`, with a
  `repeat` flag. A press on a chevron disc steps, `repeat` or not. Hit-test:
  `_event_image_xy` converts the event to image-local coords — **in screen
  coords (`x_root`/`y_root`) on purpose**, because `CTkLabel.bind()` binds
  *both* the inner `tk.Label` (sized to the image, centred) and the inner
  canvas (fills the frame), and they report `event.x`/`.y` in different
  origins, so a widget-relative formula is right for only one of them and
  half the disc went dead. `_hit_disc_at` then boxes the point against
  `_disc_centers` (the whole disc, shared with the drawing).

  **Reselect (`on_reselect`) needs a `repeat` press in the frame's central
  area whose predecessor was also central.** `_in_chevron_band` excludes the
  left/right edge strip a disc lives in — so spam-clicking a chevron *past
  the last preview* (its disc now gone) is still just harmless edge clicks,
  not a double-click that pops the file dialog. A deliberate double-click on
  the middle of the frame still reselects. The first render is deferred
  `after(50)` because CTk geometry is unreliable until the widget's first
  map pass.
- **TimeSpinner** (`components/time_spinner.py`) — the most intricate widget.
  A HH:MM:SS field with a fake block cursor: internal state is a 6-char digit
  list, and `cursor_pos` indexes directly into it (0-5) — the single source of
  truth for cursor position. `_SEGMENT_POSITIONS` is the only place that maps a
  digit index to its position in the displayed "HH:MM:SS" string (for rendering
  the selection and for translating clicks back to a digit via
  `_nearest_digit_index`). The native caret is suppressed (`_hide_caret`) and a
  one-char `select_range` is drawn instead. Typing overwrites the digit under the
  cursor and advances right; Backspace/Delete are separate handlers — Backspace
  steps back then clears (undoing the last advance, mirroring typing in reverse),
  Delete clears in place without moving. The stepper is a **stacked ▲/▼ pair
  to the right of the field** (`_stepper` frame, `btn_plus`/`btn_minus` kept
  under those names for `set_state`) — the two arrows together occupy the
  width one flanking `+`/`-` button used to. They auto-repeat with an
  accelerating delay (400ms → 30ms, ×0.85 per tick). An optional `command`
  callback fires from `update_display` on **every** value change (typing,
  stepper, backspace, `set()`), so a live readout like the Overview rundown's
  trim line updates as the user types. Every key handler returns `"break"` to
  stop Tk's default entry behavior — preserve that when editing.
- **MarqueeLabel** (`components/marquee_label.py`) — a label that **smoothly**
  scrolls its text sideways (pixel by pixel, ~60fps) when it's wider than the
  space it's given, and sits still when it fits. Both Muxing and Encoding use
  it for the header-row "Selected File:" label. It's a `CTkFrame` subclass
  that renders onto its **own raw `tkinter.Canvas`** (packed over CTkFrame's
  placed background canvas — different geometry managers, so they coexist;
  the overlay's `bg` is pinned to the background's resolved colour so a
  `transparent` parent still shows through). A canvas, not a `CTkLabel`,
  *specifically* so the scroll can move by sub-character amounts — a
  `tk.Label` only shifts a whole glyph at a time, which is what made the
  first version jerky. Two text items trail each other by `text width + gap`
  for a seamless loop. `configure(text=…)` is intercepted (so
  `app.update_global_file` needs no changes) and `bind(…)` is forwarded to
  the canvas too (so the tab's double-click-to-reselect handler still fires
  on the text). Font is measured/drawn via `_apply_font_scaling` so the
  overflow test matches what's actually rendered.
- **Sidebar** (`components/sidebar.py`) — title, logo, then the four main
  nav buttons (Muxing/Encoding/Queue/YT-DLP), then a spacer
  (`fill="both", expand=True`) that pushes Settings + the footer
  (`{year} Yezan Smadi · v0.5.0-alpha.6`) down to the sidebar's bottom edge.
  **Pack call order matters here and is easy to get backwards**: Settings and
  the footer are `side="bottom"` but are packed *before* the spacer in code,
  not after — Tk carves cavity space in `.pack()` call order regardless of
  `side`, so an `expand=True` widget claims whatever cavity remains *at the
  moment it's packed*; packing the spacer first would leave nothing for
  anything packed after it, no matter which side they request. `buttons`
  (a `{name: button}` dict) is exposed for `app._update_tab_indicator`'s lookup.

## Encoding flow

`Encode`/`Mux` and `Queue Task` both build the same settings dict and hand it
to QueueTab. Both source tabs pass `source_tab="Encoding"` / `"Muxing"`
explicitly to `add_task()`.

The "do it now" button also calls `start_task()`. That starts the job at once
when nothing is active; otherwise the job jumps the line and runs as soon as
the active one finishes. It returns `"started"`, `"next"` or `"paused"`, which
picks the toast. **Only one ffmpeg runs at a time.**

**Jobs are real ffmpeg processes.** The pipeline is four pieces:

- **`core/ffmpeg_vars.py`** — `load(settings, source_tab)` flattens one job's
  settings dict into module globals (`INPUT_FILE`, `START_TIME`,
  `VIDEO_CODEC_ARG`, …). Each comes in its raw UI form and, where they
  differ, an ffmpeg-ready `*_ARG` form. Read them through the module
  (`from core import ffmpeg_vars as v`), never `from … import NAME`, which
  copies the value once.

  **`AUDIO_STREAMS` is the one list-shaped variable here, not a scalar** —
  the direct consequence of Encoding no longer describing "the audio" as one
  codec/bitrate/channels/rate tuple. `_audio_stream_args(entry)` translates
  one settings-dict audio-stream entry into its ffmpeg-ready form
  (`{"src_index", "codec_arg", "bitrate_arg", "channels_arg",
  "sample_rate_arg"}`); a **Passthru** stream (the checkbox, forced on for
  `formats.is_passthru_only` codecs — DTS/Dolby TrueHD, which this app has no
  re-encode path for at all) always comes out `"copy"`/`None`/`None`/`None`
  regardless of what its display-value fields still say, since
  `EncodingTab` keeps showing the *source's* real values there purely for
  display while Passthru is on.
- **Multi-stream audio** ("Choose Stream(s)" on Encoding's Audio panel,
  `components/audio_stream_dialog.py`'s `AudioStreamPickerDialog`) — one
  checkbox per stream `probe_media`'s `audio_streams` reports, pre-checked to
  match what's currently included; OK returns the chosen index set (refusing
  to ever return empty — see its `_ok`, since "no audio at all" is Strip
  Audio's job, not a second door to the same outcome), Cancel/close returns
  `None` so the caller can tell "nothing changed" apart from "chose zero".
  The Audio Track dropdown then shows one included stream at a time; its own
  Codec/Bitrate/Channels/Sample Rate row + Passthru checkbox edit whichever
  stream is currently selected there, and `EncodingTab._gather_settings`
  folds the live widget values back into that stream's own saved entry
  (`_save_active_audio_stream`) before building the final `audio_streams`
  list — so switching which stream you're looking at never loses an edit to
  another one. `build_encode_command` (below) then needs one `-map` per
  *output* audio stream, not ffmpeg's default "one best audio stream" — the
  same reason `build_mux_command` already needs explicit `-map`s for an
  external track.
- **`core/ffmpeg_build.py`** — `build_mux_command` / `build_encode_command`
  turn those into an ffmpeg-python `Stream`. `compile_command(path)` returns
  the full argv, with the runner's global flags
  (`-nostdin -loglevel error -nostats -progress pipe:1`) placed right after
  `ffmpeg` via `compile(cmd=...)`. Muxing is always `-c copy`. GPU is still a
  no-op stub — `app.gpu_enabled` (the Settings switch) is read by
  `EncodingTab._gather_settings` into the job's `gpu_enabled` key but nothing
  in the builder acts on it yet, so every encode currently runs in software.
  **A/V Sync is wired**: when checked (on by default) and the video stream
  isn't stripped, `build_encode_command` adds `-fps_mode cfr` — the current,
  non-deprecated replacement for `-vsync` (same "hold a constant rate,
  duplicating/dropping frames" behaviour) — scoped to Encoding only, since
  Muxing's always a stream copy and `fps_mode` has nothing to act on without
  a real video encode. **`-fps_mode` isn't universal** — added in ffmpeg 5.1
  (mid-2022); an older install (this app's own dev machine runs a 2020
  build) doesn't recognize it at all and would fail *every* Encoding job
  outright with A/V Sync on by default. `core.utilities.supports_fps_mode()`
  checks once per process (parses `ffmpeg -h full`'s own option listing,
  cached — a subprocess per job would be wasted work for an answer that
  can't change mid-run) and `build_encode_command` falls back to the older,
  deprecated `-vsync cfr` when it's not there — same "hold a constant rate"
  behaviour either way, it's purely which flag name the installed binary
  understands. The same lazy-cache-then-branch pattern covers two more
  cases:
  - **Speed** — the Video sub-tab's `speed_menu` (see "Tabs" below); its
    value (a named `-preset` for x264/x265/AV1, or `-cpu-used` + a fixed
    `-deadline good` for the libvpx codecs — `formats.speed_kind_for`) is
    carried through as `SPEED`/`SPEED_ARG` in `ffmpeg_vars` and merged
    straight into the encode's output kwargs. Before this control existed,
    *nothing* in this app ever set an encode-speed knob at all, so every job
    silently rode whichever default the library ships (x264/x265's implicit
    "medium", etc.) — a real, measurable contributor to "this is taking way
    longer than it should" on a large or HDR source, separate from (and not
    fixed by) the GPU stub above.
  - **HDR→SDR** — when `HDR_TO_SDR` and the video isn't stripped, adds
    `-vf` from `core.utilities.libplacebo_tonemap_vf(peak_detect=...)`
    (`libplacebo=apply_dolbyvision=true:peak_detect=<bool>:tonemapping=
    bt.2390:colorspace=bt709:color_primaries=bt709:color_trc=bt709:
    format=yuv420p` — moved to `core/utilities.py`, not `ffmpeg_build.py`,
    specifically so the HDR *preview* thumbnails, below, can share the exact
    same filter string with the real encode without a circular import) plus
    explicit `-color_primaries bt709 -color_trc bt709 -colorspace bt709`
    output tags (verified: libplacebo's target colorspace doesn't reliably
    propagate to the output stream's own tags on its own, so a player/editor
    has no guarantee the result is really BT.709 without these).
    **BT.2390 (libplacebo) is deliberately the only curve this app will ever
    use — by request, never a silent lower-accuracy substitute.** The
    classic `zscale`+`tonemap` filter chain (`tonemap`'s own algorithm list
    tops out at "hable" — none/linear/gamma/clip/reinhard/hable/mobius,
    confirmed via `ffmpeg -h filter=tonemap`, no BT.2390 among them) was
    tried first and removed once a real Vulkan/libplacebo setup was
    confirmed working (see below) — don't reintroduce it as a fallback.
    `core.utilities.supports_libplacebo()` (cached, parses `ffmpeg
    -filters`) gates this two ways instead: `EncodingTab._sync_controls`
    disables (not force-unchecks) `hdr_switch` when it's False, so the
    control simply can't be turned on; and `build_encode_command` raises a
    `ValueError` if `HDR_TO_SDR` somehow reaches it anyway (e.g. a preset
    saved on a different ffmpeg install) — caught by
    `EncodingTab._validate_settings` before the job is even queued, and by
    `QueueTab._process_next`'s existing "couldn't build the ffmpeg command"
    Failed-task path as a last resort. Verified end-to-end against a real
    HDR10-tagged synthetic source, producing a correctly BT.709-tagged SDR
    output.

    **`peak_detect` is not a fixed `true`/`false` — it follows the source's
    own static HDR metadata, and getting this wrong measurably hurts either
    way.** libplacebo's `peak_detect` (on by default) dynamically estimates
    each frame's true peak brightness by analysing pixel values over a
    ~100-frame smoothing window, meant to compensate for a source with no
    static metadata to trust. `core.utilities._probe_hdr_static_metadata`
    reads the source's ST 2086 mastering-display luminance and MaxCLL/MaxFALL
    (a separate, frame-level ffprobe query — confirmed neither value shows up
    in ffprobe's *stream*-level output, only a full `-show_frames` on the
    first frame); `libplacebo_tonemap_vf`'s `peak_detect` argument is then
    `not (mastering_max_nits is not None and max_cll)` — **both** a mastering
    peak *and* a genuine, nonzero MaxCLL are required, not the peak alone.
    Confirmed both ways on real commercial sources: a file with a real
    measured MaxCLL (`Spider-Man 3 Sheriff.mp4`) cut highlight clipping
    87-98% with `peak_detect` forced off; a file with only a mastering peak
    and MaxCLL/MaxFALL both `0` (present in the SEI but unset, not a real
    measurement — the same "zero reads as absent" convention
    `ThumbnailCarousel._mastering_text` uses) came out measurably *dimmer and
    lower-contrast*, the opposite of an improvement, when the peak alone was
    trusted the same way. `EncodingTab._gather_settings` snapshots
    `mastering_max_nits`/`max_cll` from `app.media_info` into the job's
    settings dict at queue time — a fact about the input, not a user choice —
    and `ffmpeg_vars.derive()` carries them through as `MASTERING_MAX_NITS`/
    `MAX_CLL` for `build_encode_command` to read.

    **A post-encode safety net re-verifies the real output, not just the
    filter in isolation.** `core.utilities.verify_hdr_sdr_tag(path)` re-probes
    the finished file's own `color_transfer` after an HDR→SDR job completes;
    `FfmpegJob` (see `core/ffmpeg_runner.py` below) reports the task **Failed**
    — file still saved, for inspection, never deleted — rather than Done if
    it still reads an HDR transfer characteristic (`smpte2084`/`arib-std-b67`)
    instead of `bt709`. `QueueTab._process_next` only asks for this check when
    `ffmpeg_build.uses_hdr_tonemap()` says the job's compiled command actually
    ran the tonemap chain (`FfmpegJob`'s `verify_hdr_tag` kwarg). A `None`
    result (the verification probe itself failed) is "unknown", not "wrong",
    and falls through to Done — this guards specifically against a future
    ffmpeg/libplacebo regression or an unusual muxer silently failing to
    propagate the requested output tags, which is a real, worse-than-not-
    tonemapping-at-all failure mode (a file that's still HDR data under an
    SDR label, trusted and displayed wrong by every consumer with no
    warning).

    **The HDR preview thumbnails are a second, separate frame source, not
    the same ten frames re-colored.** cv2's plain decode of a real HDR (PQ/
    BT.2020) source has no color management at all — it clips/rescales the
    wide-range values into 8-bit RGB, producing a washed-out picture of the
    *untouched* HDR data rather than a preview of what the export will look
    like. `core.utilities.extract_hdr_tonemapped_thumbnails` instead runs one
    short-lived real ffmpeg + libplacebo process **per frame** (an input-side
    `-ss` approximate seek, then a single-frame decode through the identical
    `libplacebo_tonemap_vf` filter the real encode uses), targeting the exact
    same frame indices `extract_video_thumbnails`'s cv2 seek samples
    (`_interior_sample_frames`, shared by both) so the two sets stay
    index-for-index aligned. Ten short seeks measured well under the cost of
    one full linear decode on a real multi-GB HDR10 source. Empty (no preview
    change) whenever `supports_libplacebo()` is false or the geometry probe
    fails — callers must check the former themselves to tell "no HDR to show"
    apart from "libplacebo isn't available".

    **Encoding's preview carousel actually shows this tonemapped set once
    HDR→SDR is on**, not just the raw HDR frames with a switch flipped
    elsewhere. The render/cache/queue machinery (`start_hdr_render`,
    `hdr_frames`/`hdr_frames_path`, a token + poll loop mirroring
    `_load_thumbnails`'s own) lives on `LlamaGUI`, not `EncodingTab` —
    deliberately, so a live theme rebuild (which destroys and reconstructs
    the tab) doesn't throw the render away and force a several-second
    re-wait every time the user so much as changes theme; the app survives
    that rebuild, so the cache does too. `EncodingTab._apply_preview_frames`
    picks the cached tone-mapped set over the raw one whenever the switch is
    on, it's ready, and it matches the currently-shown file; flipping the
    switch off (or switching files) swaps back to the raw set instantly
    without waiting on a fresh render. This preview path is Encoding-only —
    Muxing has no HDR control at all.

    **Being *listed* as compiled in is not enough to trust libplacebo,
    though.** After updating this app's own dev ffmpeg specifically to get
    libplacebo, the simplest possible `-vf libplacebo` (no params at all)
    **segfaulted outright, zero stderr** — traced to the filter's own
    *implicit* Vulkan device selection crashing on a real hybrid dual-vendor
    GPU (NVIDIA discrete + AMD integrated) with several overlay/capture
    Vulkan layers installed (Steam, OBS, Epic Games, Rockstar — all common
    software, not an exotic setup); `vulkaninfo` itself worked perfectly
    fine, so this is specifically an ffmpeg/libplacebo device-selection bug,
    not a broken Vulkan install. Explicitly creating the device up front —
    `-init_hw_device vulkan=vk` — and binding the filter to it —
    `-filter_hw_device vk` — avoids the crash entirely (verified on that
    same machine), with no device index needed (an index would just be the
    wrong GPU on a different machine's enumeration order). These are
    genuine *global* options and must precede the input/filter graph:
    `compile_command` threads them through its `cmd` prefix (`uses_
    hdr_tonemap()` gates it — public, not module-private, since
    `QueueTab._process_next` also reads it to decide whether to ask
    `FfmpegJob` for the post-encode HDR-tag verification above — mirroring
    `build_encode_command`'s own HDR_TO_SDR check) rather than
    ffmpeg-python's `.global_args()`, which places them
    *after* the compiled output spec — confirmed ffmpeg then refuses
    `-filter_hw_device` outright ("Invalid filter device") since
    `-init_hw_device` hasn't been processed yet at that point in its own
    left-to-right option parsing.
  And `-strict -2` (experimental compliance) is set on every job — **global,
  not audio-scoped (`-strict:a`), and confirmed that distinction matters, not
  just tidier.** It exists for non-standard audio/container pairings (a real
  TrueHD-in-MP4 source, Atmos side data, etc.), and audio-scoping it looks
  like the more surgical choice — but reproduced 5/5 on a real TrueHD-in-MP4
  file: `-strict:a -2` alone still hard-fails the job outright
  (`"truehd in MP4 support is experimental, add '-strict -2'"`, then
  `"Could not write header (incorrect codec parameters?)"`, confirmed
  independent of everything else in the command — no HDR filter, no Vulkan
  device, plain `-c:v libx264`). It's the **muxer's own** compliance gate
  objecting to an experimental codec-in-container pairing, not the audio
  codec context — `-strict:a` sets the latter, which never reaches the check
  that's actually failing, so only the bare, unscoped `-strict -2` works. An
  earlier version scoped it to `-strict:a` on the theory that the video codec
  context had no business being loosened by an audio-only concern — a
  reasonable-sounding rule that turned out to be simply wrong for this case.

  **Multi-stream audio needs `i`, the stream's position in the *output*
  file, not `src_index`, its position in the *source*** — ffmpeg's
  per-stream option suffixes (`-c:a:0`, `-c:a:1`, …) address the former, and
  the two only match when every source stream up to that point was
  included. `-ac`/`-ar` have their own sharper trap on top of that:
  confirmed directly that a bare `-ac:0`/`-ar:0` (no explicit `a:` type
  qualifier, unlike `-c:a:0`/`-b:a:0`, which already carry one) counts across
  **every** output stream, video included — so with a kept video stream at
  output position 0, an unqualified `-ac:0`/`-ar:0` silently landed on the
  video stream (a no-op) and every audio stream's actual value shifted onto
  the *next* stream's slot instead of its own. `build_encode_command` always
  emits the qualified `-ac:a:{i}`/`-ar:a:{i}` form.
  `+faststart` (`_faststart_kwargs`) is only added when the
  output is actually `.mp4`/`.mov` — it's a private option of that muxer, a
  purely lossless metadata rewrite (moves the moov atom to the front so
  progressive-download/web playback can start before the whole file
  arrives), does nothing for local random-access playback or NLE import, and
  this build happens to silently ignore it on `.mkv` rather than erroring —
  but that's this build's leniency, not a documented guarantee, so it's
  conditional rather than relying on it.
- **`core/ffmpeg_runner.py` — `FfmpegJob`**, no Tk in the module. It launches
  the argv with **one plain `subprocess.Popen`, not ffmpeg-python's
  `run_async()`**, because that can't pass `creationflags`, and
  `CREATE_NO_WINDOW` matters — otherwise every job flashes a console window.
  **Runs at the OS's normal process priority, not throttled.** An earlier
  version added `BELOW_NORMAL_PRIORITY_CLASS` on the theory that x264
  otherwise saturates every core including the Tk thread's — but profiled
  event-loop lateness during a real full-speed encode came back the same as
  idle either way (~6ms p90, both), and a same-machine, uncontended,
  single-job timing comparison showed throttling bought no protection at the
  cost of the encode itself: below-normal and normal priority finished a
  fixed encode within 0.3% of each other. So the throttle was pure downside
  with no measured upside; removed.

  Two daemon threads watch the process and never touch Tk: one parses
  `-progress` off stdout (**`out_time_us`** — `out_time_ms` is *also*
  microseconds despite its name), one drains stderr. The stderr drain is
  mandatory: a full pipe blocks ffmpeg forever, and its tail becomes the
  failure reason. Results reach the Tk thread only through `poll_events()`.
  **Two threads per job (not one, not zero) is deliberate, not a place to
  "optimize" further**: Windows' `select()` only works on sockets, not
  arbitrary pipe handles, so reading two blocking pipes without stalling on
  whichever is quieter needs one thread apiece — the standard, portable
  answer on this platform (it's why `subprocess.communicate()` does the same
  internally). Only one job is ever active at once by design, so this is at
  most 2 extra threads alive at a time, not a pool to size or tune.
  - The progress denominator *starts* as the job's `duration_secs`, else
    `probe_duration(input) − start_secs`, probed in the worker thread — but
    it's only a starting guess where it comes from a probe: `_watch`
    stretches it upward on the fly (`total = seconds * 1.05`) whenever
    `out_time` runs past it, rather than clamping to 1.0 and freezing the
    bar at "done" while ffmpeg keeps working. Confirmed real-world trigger:
    a VFR source whose container-reported duration (what `probe_duration`
    reads) undersold its true playable length by over 10x (MediaInfo said
    3:30, actual playback length was 45:54) — every job past that point
    would otherwise sit pinned at 100% for most of its real run time.
  - `suspend()` / `resume()` use ntdll's `NtSuspendProcess` /
    `NtResumeProcess` via `ctypes` (no psutil). `stop()` kills (fine while
    suspended) and deletes the temp file.
  - **Output goes to `<stem>.partial<ext>` first** (`partial_path`) and is
    replaced onto the real path only when ffmpeg exits 0, via
    `_replace_output` rather than a bare `os.replace`. **A bare
    `os.replace` can fail with a genuine, reproducible Windows "Access is
    denied" (WinError 5)** — confirmed two real causes directly (not just
    from a bug report): the destination file has the read-only attribute
    set, or something else (a media player, thumbnail/preview generation, an
    antivirus scan reacting to the just-closed temp file) has it open for a
    moment. `_replace_output` clears the read-only bit first (best-effort)
    and retries the rename for a few seconds before actually giving up —
    verified against both a transient lock (released mid-retry: the job
    still succeeds) and a permanent one (never released: the job still
    reports Failed, with a message naming the likely cause, rather than
    hanging or silently losing the file). A stopped or failed job only ever
    deletes the *temp* file — never one the user already had at the final
    path.
- **`QueueTab`** — `_process_next` loads the vars, compiles the argv *on the
  Tk thread* (so workers only ever see a plain list, never the shared
  globals), starts the job, and returns immediately. It also prints the
  command. `_poll` (every `_POLL_INTERVAL_MS` — 100ms; ffmpeg itself only
  reports progress about twice a second, and profiling shows the tick costs
  nothing measurable either way, so there's no real gain to spacing it out
  further) drains events and paints the latest fraction via `_paint_fraction`
  (which itself only repaints when the drawn width/height actually changes).
  Then:
  - "done" → the row becomes Done;
  - "failed" → the row turns red "Failed", the reason goes in `row["error"]`
    (shown as an **Error** line in the details popup), a "Job Failed" notice
    is queued, and the queue moves on.
  - **The worker always queues a final `("progress", 1.0)` immediately
    before `("done",)`** (see `FfmpegJob._watch`), and that pair almost
    always lands in the *same* `_poll` batch. `_poll` paints on *every* pass
    before acting on a terminal event (it used to return the instant it saw
    "done"/"failed", which silently dropped that last progress paint — the
    fill would jump from wherever it last happened to be straight to flat
    grey, never visibly reaching 100%), and calls `update_idletasks()`
    before flipping the row's status, so the full-width frame actually
    reaches the screen instead of being coalesced away with the very next
    redraw. Verified by logging the exact drawn-width sequence against a
    real job: the last frame before "Done" is now always full width.
  - **When a whole batch finishes — the queue's last job settles, or the
    active job's row is removed with nothing left behind it — `app.notify`
    posts "All queued jobs finished."** Every path that reaches that branch
    followed at least one job actually running (`start_queue`/`start_task`
    both refuse to call `_process_next` on an empty list to begin with), so
    this can't fire spuriously.

  Row thumbnails reuse the app's already-decoded frames
  (`app._thumb_frames`) or decode on a worker, never on the Tk thread.

**Encoding can no longer produce a silent byte-for-byte copy.** `Select`
(the Encoder/Audio Codec placeholder — see "Option compatibility" above)
auto-resolves to the source's own codec the moment a file is probed, and
`_validate_settings` refuses to queue a job that still has a
present-or-unknown stream sitting on `Select` — there's no path left where
"do it now"/"Queue Task" silently produces an identical file the way the old
`Source` (stream-copy) behaviour could. Muxing is still the one tab that's
*always* a stream copy by design.

All of the above was verified against real ffmpeg with scratch harnesses:
pause stalls progress and resume continues, stop works mid-run and while
suspended, failures come back with ffmpeg's own message, no process or
`.partial` file is left behind, a real encoder pick measurably shrinks the
file, and the two `os.replace` failure modes above reproduce and recover
exactly as described.

Encoding settings dict shape (`_gather_settings`):
`input_file, output_path, output_format, start_secs, duration_secs, av_sync,
encoder, profile, level, speed, quality, gpu_enabled, hdr_to_sdr,
mastering_max_nits, max_cll, strip_video, strip_audio, audio_streams`.

**Audio is a list, not four scalar keys**, because an Encoding job can carry
more than one *output* audio stream (the Audio Track dropdown + "Choose
Stream(s)" dialog — see "Multi-stream audio" below): `audio_streams` is
`[{"index": 0, "codec": "AAC", "bitrate": "192 kbps", "channels": "Stereo",
"sample_rate": "48000 Hz", "passthru": False}, ...]`, one entry per *included*
source stream, built by `_gather_settings` from `_audio_stream_settings`
(the per-stream dict last edited through the Audio Codec/Bitrate/Channels/
Sample Rate row + Passthru checkbox for whichever stream the Audio Track
dropdown currently shows) plus every other included stream's own
last-saved values. `mastering_max_nits`/`max_cll` are a fact snapshotted
from the probed source at queue time (see the HDR→SDR bullet above), not a
user choice — carried through so a job queued now still tone-maps against
the source it was actually queued against, even if the user swaps files
before it runs.

Muxing's shape — **no codec keys at all**, since it never re-encodes:
`input_file, output_path, output_format, start_secs, duration_secs, av_sync,
video_track, video_track_file, strip_video, audio_track, audio_track_file,
strip_audio`.

Shared by both: `input_file`, `output_path`, `output_format`, `start_secs`,
`duration_secs`, `av_sync`, `strip_video`, `strip_audio`. `av_sync` is the
Overview checkbox beside the trim spinners (align A/V start + pass through
common metadata); it's a recipe key too, so presets carry it. The Queue tab's details popup
(`_DETAIL_FIELDS`) relies on each tab-specific key being *absent* (not just
falsy) from the other's dict to hide the rows that don't apply.

Two naming notes: `quality` (not `crf`) because the number is a qscale under
the MPEG-era encoders, and `retain_length` is **gone** — `duration_secs == 0`
means "to the end of the file". A derived dropdown showing the `—`
placeholder reports `""` rather than the dash (`_menu_value`), so a settings
dict never carries a placeholder around as if it were a real choice.

## Download flow (YT-DLP)

Two modules, no Tk in either. **Everything runs through the bundled
`yt-dlp.exe`** — one copy of yt-dlp for fetch *and* download, updatable
without an app release; a frozen app has no `python -m yt_dlp` anyway.

**`core/downloader.py`**
- `base_args()` starts every argv: `yt-dlp.exe --ignore-config --no-playlist`
  plus absolute `--js-runtimes deno:<path>` / `--ffmpeg-location <dir>`.
  **`--ignore-config` is required**: this dev machine's own
  `%APPDATA%\yt-dlp\config.txt` forces `-f mp4 -f best` and a fixed output
  folder, and would silently steer every job without it (confirmed).
  yt-dlp.exe runs with `PYTHONIOENCODING=utf-8` so titles survive the pipe.
- `deno_path()` — resolved via `core.tools` and `deno --version` ≥ 2.3.0
  (yt-dlp's own minimum), cached, behind a lock (the startup check runs on a
  worker while the Tk thread may already be building an argv). The app runs
  it at startup (`_deno_check_worker` → `("deno", ...)` on `_thumb_queue`) and
  sets `app.deno_missing` → `YtDlpTab.set_deno_missing`. **Without Deno,
  YouTube still worked on the day this was tested** (full format list, a
  byte-identical download, plus a deprecation warning) — yt-dlp's current
  player client happens not to need the JS challenge — which is exactly why
  it's warn-only and why "it works without Deno" must not be trusted.
- `fetch_info(url)` → `(info, error)`: `yt-dlp --flat-playlist -J`; a
  playlist URL is refused with a readable message (playlists are a later
  phase); `error_reason(lines)` turns yt-dlp's last `ERROR:` line into user
  text.
- **The option model agrees with yt-dlp's own ranking instead of
  re-implementing it**: `formats` comes back sorted worst → best by yt-dlp's
  preference, so "best matching X" is simply the *last* match.
  `parse_formats` compacts it (drops storyboards and `-drc` duplicates, maps
  vcodec/acodec strings to this app's codec names, fills a missing size from
  `tbr × duration`). Containers are judged by **`formats.containers_for`** —
  the same matrix Muxing uses — so VP9 never offers `.mp4` and `.webm` never
  takes AAC; for `.mp4`, audio falls to the best AAC stream.
- `resolve(fmts, mode, codec, quality, container, duration)` → the plan
  (JSON-safe, it rides in the task): `format` (pinned IDs, then a fallback
  selector), `ext`, mode `args` (`--merge-output-format` / `--remux-video` /
  `-x --audio-format --audio-quality`), `parts` (`id`, `kind`
  video/audio/both, `size`) and `post` (`merge`/`remux`/`convert` with
  `expected_bytes`, `media_secs`). Its `audio_codec` argument (Video + Audio's
  Audio dropdown) narrows the separate audio stream — and the fallback's
  audio selector — to that codec. **The fallback's audio alternatives are
  parenthesised** — in yt-dlp's selector grammar `/` binds looser than `+`,
  so `bv+ba[x]/ba[y]` means "(bv+ba[x]) or an audio-only ba[y]". Fallbacks
  were verified to resolve with the pinned IDs missing.

**`core/ytdlp_runner.py` — `YtDlpJob(url, plan, final_path)`**
- **Process tree in a Windows Job Object.** yt-dlp.exe is a PyInstaller
  bundle (bootloader + real child) that starts its *own* ffmpeg; the first
  process is created `CREATE_SUSPENDED`, assigned to a kill-on-close job,
  then resumed, so nothing escapes. `stop()` = `TerminateJobObject`;
  `suspend()`/`resume()` enumerate the job's PIDs and `NtSuspendProcess`
  each (reusing `ffmpeg_runner._set_suspended`). Verified: pause froze the
  byte count, ffmpeg appeared inside the job during a merge, Stop mid-
  download and mid-conversion left no process and no files, and killing the
  Python process outright took the tree with it (kill-on-close).
- **Private work folder**: yt-dlp writes only into a hidden
  `.llamamxd-download-XXXXXXXX` beside the output (`-P`, `-o download.%(ext)s`);
  on exit 0 the file named by `--print after_move:filepath` is moved onto
  `final_path` with `ffmpeg_runner._replace_output`'s retrying replace.
  Stop/failure just deletes the folder — a user's existing file is never
  touched unless the download succeeded.
- **One pipe** (`stderr=STDOUT`): yt-dlp prints download progress on stdout
  but post-processing events and errors on **stderr** (confirmed). Marker
  lines: `LLAMA_FORMATS` (a merge's chosen formats — prints `[]`, not NA, for
  a single format; that once wiped the size budget), `LLAMA_FORMAT id size`
  (single format), `LLAMA_DL <format_id> {json}` per stream,
  `LLAMA_PP {status, postprocessor}`, `LLAMA_FILE`. If the fallback selector
  picked different IDs, the byte budget is rebuilt from what was chosen.
- **Progress is time-based**: `elapsed / (elapsed + remaining)`, computed in
  `poll_events()` on the Tk thread, never backward, capped at 0.99 until the
  file is in place, paused time excluded. Remaining = bytes left across all
  parts ÷ speed, plus the post step — before it starts, guessed from the
  last measured rate this session (`_learned`); while it runs, from how fast
  the work folder is growing. Two corrections from real runs:
  **speed is bytes received over a 20s window**, not yt-dlp's instantaneous
  figure (one burst after a stall jumped the bar 15% → 78%, where
  never-backward then pinned it for two minutes), and **the bar eases
  toward its target** (`_EASE` per poll) so a momentary spike only nudges
  it. On an unthrottled audio → mp3 job the bar tracked true elapsed time
  within a few percent throughout.
- Folder size uses `os.stat(path)`, not `DirEntry.stat()` — see Known issues.

## Conventions

- The brand accent (sidebar fill, DropBox border, primary action buttons,
  active-tab indicator, queued/in-progress queue rows) is **theme-driven,
  not a hardcoded color** — see "Theming" above. The default `Lemon` theme's
  primary is `#FDCA3C` with `#e0b234` as its hover. Text placed on any
  primary or secondary color is **not** a hardcoded literal — it comes from
  `theme["primary_text"]` / `theme["secondary_text"]`, which
  `readable_text_on()` resolves to black or white per-color for contrast
  (see "Theming" above). The one deliberate fill-color departure is a
  destructive/halting red — `STOP_RED` (`#E5484D`, hover `STOP_RED_HOVER`
  `#C93C40`) in `core/theme.py`, used by the `Stop Queue` button and the
  Encoding tab's `Strip Video` checkbox. It **never** changes with the theme
  (labels/checkmarks on it still go through `readable_text_on`).
- Widgets are stored as `self.` attributes even when not obviously reused.
- Comments are used generously as section markers (`# --- Bottom Section ---`) and
  to explain *why* a layout choice was made, especially for Tk/CTk gotchas that
  aren't obvious from the code alone (see the gotchas list below) — match that density.
- Every non-trivial method gets a one-line docstring.
- Tab classes take `(self, master, app)` and subclass `ctk.CTkFrame`.

## Known issues / gotchas

- **On Windows, `os.scandir()`'s `DirEntry.stat().st_size` is stale for a
  file another process still has open** — it's the directory listing's
  cached size, which isn't updated until the handle closes. A growing
  download/merge output read as 0 bytes the whole time (confirmed); use
  `os.stat(entry.path)` for a live size (`ytdlp_runner._folder_bytes`).

- **Trim with an input-side `-ss` plus an output-side `-t`, never an
  output-side `-to`.** Verified by frame-counting real outputs: an input-side
  `-ss` rebases the output timeline to 0, so an output-side `-to X` then acts
  as a *duration* of X, not "stop at X". For example,
  `-ss 00:21:36 -i in -to 00:21:41` makes a 21m41s clip, not a 5s one.
  `ffmpeg_build._trim_kwargs` does it the safe way. `END_TIME`/`END_SECS` in
  `ffmpeg_vars` are only safe as an input-side `-to` paired with an
  input-side `-ss` (see the warning there).
- **The queue progress fill's known bugs are all fixed; treat further visual
  polish requests on it as new, not a reopened old bug.** The list, each
  confirmed fixed by direct pixel/geometry verification rather than visual
  inspection: box occlusion (fill width is capped at `status_label`'s own
  left edge in `_paint_fraction` — letting it reach further ran into
  `status_label`/`remove_btn` being `fg_color="transparent"`, a frozen
  one-time snapshot per the gotcha below, whose stale background occluded
  the fill as a solid grey box cut into it); 1px fill/text-clip
  misalignment (fill and clip are now driven by one number); edge warping
  (`smooth=True` polygon → explicit rectangles + arcs); squared-off row
  corners (canvas `bg` is the row's backdrop, not its grey); and glyph
  shearing at the fill edge (the seam is now between two canvases instead
  of a canvas and a `CTkLabel`). See the Queue tab section for each.
- **Muxing and Encoding duplicate a lot of code** — `select_input_file`,
  `_autofill_output_path`, `_on_format_change`,
  `_reveal_preview`, `_show_subtab`, `_pin_options_height`,
  `_panel_dropdown`, `_set_enabled`, `_set_menu`/`_set_check`, `_hms`, the
  whole preset block (`_refresh_preset_menu` / `_on_preset_selected` /
  `_on_preset_save` / `_on_preset_delete`), `on_media_info`, the
  `options_row` (`left_col`/`right_col`) / `header_row` construction, and
  most of `select_save_location` are near-verbatim copies between the two
  tabs. This was done deliberately per explicit instruction ("do the same
  thing to the muxing tab") rather than refactored into a shared base, but
  if a third tab needs the same pattern, that's the point to actually
  extract it rather than copy a third time. (Genuinely shared pieces *have*
  been extracted as they appeared: the thumbnail half into
  `ThumbnailCarousel`, the `Overview`/`Video`/`Audio` button strip into
  `SubTabBar`, the rundown into `SummaryPanel`, the compatibility matrix
  into `core/formats.py`, and preset storage into `core/presets.py`.)
  Note `_sync_controls` is *not* on that list — the two tabs' rulesets
  genuinely differ (Encoding cascades container→codec→profile; Muxing
  inverts it), so they are two different functions that happen to share a
  name and a contract.
- **`fg_color="transparent"` on a CTk widget is not real per-pixel
  transparency.** `CTkBaseClass._detect_color_of_master()` resolves it
  exactly once, at widget-creation time, to a static snapshot of the
  master's own `fg_color` — it never re-samples afterward. A "transparent"
  widget placed over something that changes color underneath it later (e.g.
  the queue's progress fill sliding past) still paints that frozen original
  color forever, not what's currently beneath it. Confirmed by sampling
  actual rendered pixels while prototyping the queue's progress-text
  contrast as one `CTkLabel` per character (an approach since replaced by
  the stacked `base_canvas`/`progress_canvas` pair — see "Per-row progress
  visualization" above): a `fg_color="transparent"` char label over
  the fill rendered flat grey, not the fill's yellow. This is also why
  `status_label`/`remove_btn` need the fill capped short of them rather
  than being allowed to slide underneath (see the Known Issues entry on
  this). When a widget needs to visually blend with a *dynamic* background,
  set its `fg_color` explicitly to whatever color it should currently
  match, every time that backing color can change — don't reach for
  `"transparent"`.
- **`state="disabled"` on a `CTkCheckBox` or `CTkSwitch` only dims the
  widget's own text label — it does not touch the fill/border/knob
  colours at all.** Both widgets' `_draw` reads `self._fg_color`/
  `_border_color` (checkbox) or `self._progress_color`/`_button_color`
  (switch) unconditionally of `self._state`; only the separate text label
  gets swapped to `text_color_disabled`. Confirmed directly against the
  installed customtkinter source. Practical effect: `strip_video_check`/
  `strip_audio_check` (built with an explicit destructive `fg_color=
  STOP_RED`) stayed fully bright red when the *other* Strip disabled them,
  and `hdr_switch` (an empty-text `AnimatedSwitch`, so its text label
  dimming is invisible anyway) looked completely unchanged when disabled —
  in both cases `state="disabled"` was doing something real (blocking
  interaction) while looking like it wasn't. Fixed by swapping the actual
  fill/border colours explicitly on enable/disable, the same pattern
  `_set_quality_enabled` already used for the CRF slider's knob/fill:
  `EncodingTab._set_strip_enabled`/`_set_hdr_enabled` (mirrored as
  `MuxingTab._set_strip_enabled`), reapplying the widget's real theme
  colours (`STOP_RED`/`STOP_RED_HOVER`/`readable_text_on`, or `ctk.
  ThemeManager.theme["CTkSwitch"]`'s own colours) when re-enabled rather
  than a hardcoded literal, so a theme change doesn't leave the "enabled"
  state stuck on a stale colour.
- **Tiling many small solid-colored CTk widgets edge-to-edge can show thin
  dark seams between them even with matching `fg_color`.** `_round_width_to_
  even_numbers` floors the drawn polygon's width to the nearest even number,
  which can leave a sub-pixel strip of a widget's raw canvas exposed at its
  edge — and that canvas's own `bg_color` defaults to the same one-time
  "transparent" snapshot described above, so the strip renders as whatever
  color that widget's master happened to be at creation (a seam, often dark).
  **Hit twice.** Once while prototyping the queue's progress-text contrast,
  and again on the active-tab indicator's `secondary` band, whose odd 9px
  height made CTk paint only 8 rows and leave the 9th showing dark — a 1px
  line under the pipe that read as a drop shadow (fixed by an even height
  *and* a pinned `bg_color`; see "Active-tab indicator"). **When a CTk widget
  is a solid block of color meeting other colored things, give it an even
  width/height and set `bg_color` to match its surroundings.** The first
  occurrence was the queue's progress-text contrast as one `CTkLabel`
  per character (since replaced by the stacked `base_canvas`/`progress_canvas` pair —
  see "Pixel-accurate progress-text clip" above — partly *because* of
  this): confirmed by isolating two tiled `CTkLabel`s and comparing
  rendered pixels. Fix, if tiling several such widgets is ever needed again:
  explicitly set `bg_color` to the same value as `fg_color`, not just
  `fg_color` alone.
- **`CTkLabel` silently ignores a `width` smaller than its natural text
  size** — it just renders the full, unclipped string at its natural size
  regardless (confirmed by configuring `width=60` on a label whose text
  needs ~120px: it rendered at 120px, uncropped). There is no way to get a
  hard mid-string clip out of a `CTkLabel` this way. A raw `tkinter.Canvas`
  does not have this problem — it genuinely clips whatever it draws to its
  own configured width/height, which is what `progress_canvas` (see above)
  relies on.
- **`CTkImage.configure(image=...)` is ~150ms per swap on this machine — do
  not use it for anything animating.** `CTkImage` re-runs a DPI-scaling pass
  (`_get_scaled_size` → a fresh `PhotoImage` per widget-scaling) on every
  `configure`, and on this 175%-scaled, DPI-unaware process that measured
  ~150ms for a full-preview-size frame — which pinned the `ThumbnailCarousel`
  stripped-video animation at ~6fps and made it visibly choppy. A plain
  `PIL.ImageTk.PhotoImage` set on a **raw `tkinter.Label`** (no CTk wrapper)
  is ~2ms for the same image. The carousel's Wave Loop animation paints on a
  bare `tk.Label` (`_wave_label`) placed over its `CTkLabel` for exactly this
  reason; `CTkImage` is still fine for the one-shot preview frames that only
  change on user interaction. If you animate images anywhere else, use raw
  `ImageTk` + `tk.Label`/`tk.Canvas` and keep a ref to the `PhotoImage`.
- **Screenshotting this app to verify a visual fix: use `PrintWindow`, not
  `ImageGrab`.** This machine runs at 175% display scaling and the Python
  process is DPI-unaware, so the two APIs disagree about units:
  `ImageGrab.grab()` returns *physical* pixels (4480x2520) while
  `winfo_rootx()`/`winfo_screenwidth()` report *logical* ones (2560x1440),
  and cropping a widget's Tk coords out of an ImageGrab lands on the wrong
  part of the screen entirely (also: it captures whatever window is on top,
  so an app hidden behind the editor grabs the editor). Capturing the
  toplevel directly via `ctypes` → `user32.PrintWindow(hwnd, hdc, 2)` (hwnd
  from `int(app.wm_frame(), 16)`) returns the window's own pixels in the
  *same logical* coordinate space Tk reports, so a widget crops out at
  `(widget.winfo_rootx() - frame_x, widget.winfo_rooty() - frame_y)` with no
  scaling math and no occlusion. Note a widget with an image-less
  `CTkLabel` over it (e.g. a row's blank `thumb_label`) will sample as that
  label's own color, not the fill underneath.

  **Size the capture buffer to `GetWindowRect`, not `GetClientRect`.**
  `PrintWindow(hwnd, hdc, 2)` renders starting at the *window's* own
  top-left (title bar included), not the client area's — so a buffer
  sized to `GetClientRect` (client width/height only) silently crops off
  the bottom ~30-40px and right ~15px of true window-space content (the
  title bar's own height/width, effectively), not just "no title bar in
  the shot." For a tall window this is invisible (the lost strip is blank
  margin below the last control), but for a *short* one — this app's own
  themed `MessageDialog` popups, e.g. — the Yes/No buttons sit exactly in
  that lost strip: confirmed directly, a client-sized capture of a
  "File Already Exists" dialog showed only the top few pixels of both
  buttons, and clicking where they visually appeared to be (window-relative
  coordinates computed from that truncated image) landed on the wrong one
  repeatedly. Sizing the buffer to the full `GetWindowRect` dimensions
  instead captures every pixel with no cropping, and its coordinates are
  then directly window-relative — consistent with a click computed as
  `window_rect.left + x, window_rect.top + y`, with no separate offset
  math needed.
- **CTk widgets don't take `width`/`height` via `.place()`** — only via
  `.configure()` (raises `ValueError` otherwise). Hit twice in this codebase
  (the tab indicator, and the queue's dark-text overlay): always
  `widget.configure(width=..., height=...)` then `widget.place(x=..., y=...)`.
- **`CTkLabel.bind()` binds two inner widgets, and they disagree on event
  coordinates.** It forwards the binding to *both* its inner `tk.Label` (on
  top, sized to the content, centred in the frame) and its inner `CTkCanvas`
  (behind, fills the frame). A click on the label's image goes to the inner
  label → `event.x`/`.y` are content-local; a click on the surrounding
  padding goes to the canvas → `event.x`/`.y` are frame-local. One handler
  bound via `CTkLabel.bind` sees both, with no marker saying which. The
  `ThumbnailCarousel` chevron hit-test was half-dead until it switched to
  `event.x_root`/`y_root` (screen coords, unambiguous) against the widget's
  own `winfo_rootx()` — see its `_event_image_xy`.
- **CTk widget geometry is unreliable until the widget has actually been
  mapped onscreen once** — `winfo_width()`/`winfo_height()`/`winfo_y()` can
  return stale 1px placeholders even after `update_idletasks()`, and even
  via `after_idle()`, if called before the window's first real
  `<Configure>`/map pass (e.g. synchronously during `__init__`, before
  `mainloop()` has run). A real `self.after(N, ...)` delay is what actually
  works. This also means a tab that has never been `show_tab()`-shown has
  unreliable geometry for all its descendants — test/inspect a tab after
  switching to it, not before.
- **`pack()` carves cavity space in call order, not by `side`.** An
  `expand=True` widget claims whatever cavity remains *at the moment it's
  packed* — packing it before a `side="bottom"` widget still starves that
  widget of space, regardless of side. See the Sidebar bullet above.
- The window is `resizable(False, False)`, yet EncodingTab/MuxingTab have
  `<Configure>` thumbnail rescale handlers — they only fire on layout
  changes, not user resizing (they do still fire once at initial layout).
- **PIL's `ImageDraw` primitives (`ellipse`, `line`, …) don't antialias** —
  edges come out hard-stepped. Supersample: draw onto an `ss`x-larger image,
  then `.resize((w, h), Image.LANCZOS)`. If the layer has transparency,
  downscale in **premultiplied-alpha space** — `img.convert("RGBa")` before
  the resize, `.convert("RGBA")` after — or LANCZOS mixes the transparent
  pixels' (0,0,0,0) RGB into the visible edge as a grey/dark fringe (the same
  root cause as the toast's magenta corner fringe in Known Issues). The
  `ThumbnailCarousel` overlay (chevron discs + dot row) does exactly this;
  see its section.
