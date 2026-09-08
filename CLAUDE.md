# LlamaMXD (LlamaPY GUI)

A Windows desktop GUI for video muxing/encoding, built with CustomTkinter. Wraps
(eventually) ffmpeg and yt-dlp behind a tabbed interface. Repo:
`https://github.com/YezanSmadi/LlamaMXD`. Public domain (Unlicense). Currently
v0.5.0-alpha.2 (see `components/sidebar.py`'s footer).

## Running

```bash
python main.py
```

Must be launched **from the repo root** — `core/app.py` and `components/sidebar.py`
load `llama.ico` / `llama.png` by relative path and will crash otherwise.

Environment: Python 3.13, system interpreter (no venv). Dependencies are pinned
in `requirements.txt` (`pip install -r requirements.txt`) but still installed
globally in practice: `customtkinter` 6.0, `tkinterdnd2` 0.6.2, `opencv-python`
(cv2) 5.0, `Pillow` 11.3. `ffmpeg` is on PATH but **not yet called by any code**
— see "No real ffmpeg pipeline yet" below.

## Architecture

```
main.py              entry point: sets appearance mode, constructs LlamaGUI, mainloop
core/app.py          LlamaGUI — the root window, owns shared state, tab routing, active-tab indicator
core/utilities.py    stateless helpers (currently just thumbnail extraction)
components/          reusable widgets, tab-agnostic
tabs/                one CTkFrame subclass per tab
```

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
   output path refreshes for the new input.
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
`YtDlpTab` deliberately does not (the call is commented out at
`tabs/ytdlp_tab.py:23`).

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
  theme. `Muxing`/`Encoding`'s field values are snapshotted via
  `_gather_settings()` first and restored via `load_settings()` after, so
  the user doesn't lose an in-progress form.
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

**Persistence**: `load_settings()`/`save_settings()` read/write a small
`settings.json` at the repo root (gitignored — a local preference file, not
shared repo state), holding `theme`, `appearance_mode`, `default_save_location`,
and `gpu_enabled`; missing keys or a missing/corrupt file fall back to
defaults (`Lemon` / `"System"` / `default_output_dir()` — i.e.
`~/Videos/LlamaMXD Export` — / `True`) rather than raising.

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
  that queues *and* immediately starts the task. Both also have an **Output
  Format** `ThemedDropdown` (`format_menu`, values `.mp4/.mkv/.mov/.webm`,
  default `.mp4`) — its value is the `output_format` settings key, and
  `_on_format_change` swaps the suggested output path's extension to match
  (only when the path already has one to replace; before a file is picked
  the entry holds just a folder and `_autofill_output_path` supplies the
  extension). `select_save_location`'s default filename and
  `defaultextension` follow it too. On Encoding it's the second of the four
  dropdowns in the codec-options row (`Encoder` / `Format` / `Profile` /
  `Level` — `Encoder` leads, `Format` follows since it's the one that
  renames the file); on Muxing it's its own row, whose `pady` is hand-set to
  `(6, 4)` so the gap around it matches Encoding's (which comes for free
  there from `main_options_row`'s bottom pad — Muxing has no such wrapper
  row). The four Encoding dropdowns' widths are hand-tuned tight
  (122/74/92/64) so the row fits `left_col` without crowding the CRF slider
  in `right_col`.
  Encoding additionally has: the **Encoder** dropdown (`encoder_menu`, values
  `H.264 (x264)` / `H.265 (x265)` / `MPEG-4` / `MPEG-2` — display strings
  only, no ffmpeg mapping yet, `encoder` settings key); Profile/Level
  dropdowns; a CRF slider; an HDR-to-SDR toggle that's an **`AnimatedSwitch`**
  (slides instead of snapping — see Components); and a **Strip Video**
  checkbox (`strip_video_check`) in the red `STOP_RED` (the Stop Queue
  colour), which `_on_strip_video_toggle` uses to blanket-`state="disabled"`
  every option control at once — a plain binary disable, so a control that's
  already disabled (spinners under Retain Video Length) just stays as it
  looks, and unticking restores each control to the state it *should* be in
  (spinners back under `toggle_time_spinners`). All Encoding-only fields — GPU
  acceleration used to be a switch here too but is now the global Settings
  preference `app.gpu_enabled`, which `EncodingTab._gather_settings` reads
  directly; Muxing has just the Retain Video Length checkbox + time spinners.
  Keep `_gather_settings`/`load_settings` in sync when adding a control to
  either tab.
  Both show the selected file as a **`ThumbnailCarousel`** (see Components) in
  their `top_container`, in place of the old single `img_label` +
  `display_image`/`_resize_thumbnail`. The tab keeps only a thin
  `_reveal_preview()` (packs the filename header + carousel in, `pack_forget`s
  the DropBox) that the carousel fires via its `on_populated` callback on the
  first frame set; double-clicking the carousel reselects the input file
  (`on_reselect`). The carousel also takes `on_index` — it fires
  `app.sync_preview_index(i)` on every scrub so the **other tab's carousel
  mirrors the same frame** (see the file-selection broadcast section); the
  receiving `carousel.sync_index()` jumps with no slide and doesn't re-fire
  `on_index`, so there's no loop.
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
- **YT-DLP** (`tabs/ytdlp_tab.py`) — stub. URL entry and a button with no command.

### Queue tab

`QueueTab` tracks tasks in `self._rows` (`task_id -> row dict`), keyed by an
incrementing int. Each task carries a `source_tab` string (`"Encoding"` or
`"Muxing"`) recording who queued it, used by the details popup to label
itself correctly and to pick the in-progress status text
(`"Encoding..."` vs `"Muxing..."`).

**Row styling is status-driven, not positional.** `_apply_row_style` reads
the row's current status text and applies one of two style dicts
(`_QUEUED_STYLE` = solid yellow, `_GREY_STYLE` = grey base) — "Queued" is
yellow, "Done" is flat grey, anything else (an in-progress label) is grey
with the fill visible. This replaced an earlier alternating-stripe scheme;
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

`fill_width` is computed once in `_animate_progress`
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

**Start / Pause / Stop**: `start_all_btn` toggles between "Start Queue" and
"Pause Queue" (`_set_running`). Pausing (`pause_queue`) cancels the pending
`self.after(...)` tick but keeps `self._paused_state = (task_id, step, rest)`,
so clicking Start again resumes `_animate_progress` from that exact step
rather than restarting. Stopping (`stop_queue`) does the same cancellation
but also reverts the in-flight task back to "Queued", discarding its
progress. `self._animation_job` is the one in-flight `after()` id; every
path that halts processing must cancel it or a stray tick can fire later.

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

**Overall progress bar** (`self.progress_bar`, top of the tab, replaced an
earlier plain "Encoding Queue" header label): tracks `done / total` across
*current* rows, recalculated in `_update_overall_progress` on every add/
remove/status change. `corner_radius=0` here too, for the same reason
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

`pending_task_count()` reports how many tasks are not yet `Done` (in-flight
*and* still-queued — everything that would be lost on quit); `LlamaGUI.
on_close` reads it to decide whether to confirm before exiting, and
`clear_all` reads it for the same reason.

**Bottom-left buttons**: `Clear Completed` removes only `Done` rows;
`Clear All` (to its right) empties the queue outright. `clear_all` confirms
first via `ask_yes_no` **only when something unfinished would be thrown
away** — an all-`Done` or already-empty queue clears with no prompt — then
calls `stop_queue()` *before* removing rows, so no pending animation tick can
fire against a row that no longer exists.

### Dropdowns

**Every dropdown in the app is a `ThemedDropdown`** (`components/dropdown.py`)
— Theme and Appearance Mode on Settings, Encoder / Format / Profile / Level
on Encoding (Encoder leads; Format follows it — the one that renames the
file), Output Format on Muxing. It
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

Current dialogs: no input file, no save location (both raised from
`_validate_settings` in Muxing/Encoding, which used to just `print`), and the
close confirmation in `LlamaGUI.on_close`.

**`on_close` pauses the queue for the duration of its prompt** and resumes it
if the user backs out. Otherwise a job would keep animating (and could even
finish) behind a modal dialog asking whether to cancel it. *Pausing* rather
than stopping is what makes that reversible — `pause_queue` keeps the
in-flight task's progress in `_paused_state`, so `start_queue` resumes from
the exact step it left off at, while `stop_queue` would discard it.

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
tab), "Encoding/Muxing job has begun." (the direct Encode/Mux buttons), and
"Settings saved." (Settings tab's Save button — `go_to_queue=False`, so
clicking it does nothing; it replaced an inline status label under the
button). The Save button's other path — an actual theme change — posts no
toast, since `apply_theme` rebuilds the tab (and clears live toasts) and is
its own visible feedback.

### Components

- **ThemedDropdown** (`components/dropdown.py`) — see "Dropdowns" above. Every
  dropdown in the app uses it; don't add a bare `CTkOptionMenu`.
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
  Delete clears in place without moving. +/- buttons auto-repeat with an
  accelerating delay (400ms → 30ms, ×0.85 per tick). Every key handler returns
  `"break"` to stop Tk's default entry behavior — preserve that when editing.
- **Sidebar** (`components/sidebar.py`) — title, logo, then the four main
  nav buttons (Muxing/Encoding/Queue/YT-DLP), then a spacer
  (`fill="both", expand=True`) that pushes Settings + the footer
  (`{year} Yezan Smadi · v0.5.0-alpha.2`) down to the sidebar's bottom edge.
  **Pack call order matters here and is easy to get backwards**: Settings and
  the footer are `side="bottom"` but are packed *before* the spacer in code,
  not after — Tk carves cavity space in `.pack()` call order regardless of
  `side`, so an `expand=True` widget claims whatever cavity remains *at the
  moment it's packed*; packing the spacer first would leave nothing for
  anything packed after it, no matter which side they request. `buttons`
  (a `{name: button}` dict) is exposed for `app._update_tab_indicator`'s lookup.

## Encoding flow (current state)

`Encode`/`Mux` and `Queue Task` both build the same settings dict and hand it
to QueueTab; the yellow "do it now" button additionally calls `start_task()`
to run it immediately. Both source tabs pass `source_tab="Encoding"` /
`"Muxing"` explicitly to `add_task()`.

**There is no real encoding/muxing pipeline yet.** `QueueTab._process_next` /
`_animate_progress` print the settings and *simulate* work by animating each
row's progress fill over a fixed 1.5s (`_PROGRESS_STEPS` × `_PROGRESS_INTERVAL_MS`)
before marking the task "Done". This is the designated seam for the ffmpeg
pipeline: replace the simulated tick loop with a real subprocess call that
reports actual progress, feeding it through the same `update_status`/fill-width
plumbing. Keep it off the Tk main thread — a blocking `subprocess.run` there
will freeze the UI.

Encoding settings dict shape (`_gather_settings`):
`input_file, output_path, encoder, output_format, start_secs, duration_secs,
gpu_enabled, hdr_to_sdr, retain_length, strip_video, crf, profile, level`.
Muxing's is the same minus the seven encoding-only keys (`encoder,
gpu_enabled, hdr_to_sdr, strip_video, crf, profile, level`) — `output_format`
is shared, present on both. The Queue tab's details popup (`_DETAIL_FIELDS`)
relies on the encoding-only keys being *absent* (not just falsy) to correctly
hide them for Mux tasks.

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

- **The queue progress fill's known bugs are all fixed; treat further visual
  polish requests on it as new, not a reopened old bug.** The list, each
  confirmed fixed by direct pixel/geometry verification rather than visual
  inspection: box occlusion (fill width is capped at `status_label`'s own
  left edge in `_animate_progress` — letting it reach further ran into
  `status_label`/`remove_btn` being `fg_color="transparent"`, a frozen
  one-time snapshot per the gotcha below, whose stale background occluded
  the fill as a solid grey box cut into it); 1px fill/text-clip
  misalignment (fill and clip are now driven by one number); edge warping
  (`smooth=True` polygon → explicit rectangles + arcs); squared-off row
  corners (canvas `bg` is the row's backdrop, not its grey); and glyph
  shearing at the fill edge (the seam is now between two canvases instead
  of a canvas and a `CTkLabel`). See the Queue tab section for each.
- **Muxing and Encoding duplicate a lot of code** — `select_input_file`,
  `toggle_time_spinners`, `_autofill_output_path`, `_on_format_change`, the
  `_OUTPUT_FORMATS` list, `_reveal_preview`, and most of
  `select_save_location` are near-verbatim copies between the two tabs. This
  was done deliberately per explicit instruction ("do the same thing to the
  muxing tab") rather than refactored into a shared base, but if a third tab
  needs the same pattern, that's the point to actually extract it rather than
  copy a third time. (The thumbnail half — `display_image` / `_on_resize` /
  `_resize_thumbnail` / `_raw_pil_image` — *was* extracted, into
  `ThumbnailCarousel`, when the multi-frame preview landed.)
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
