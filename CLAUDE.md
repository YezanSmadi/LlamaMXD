# LlamaMXD (LlamaPY GUI)

A Windows desktop GUI for video muxing/encoding, built with CustomTkinter. Wraps
(eventually) ffmpeg and yt-dlp behind a tabbed interface. Repo:
`https://github.com/YezanSmadi/LlamaMXD`. Public domain (Unlicense). Currently
v0.5.0-alpha.1 (see `components/sidebar.py`'s footer).

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
configured size — see "DropBox / expand+fill gotchas" below before changing it.

### Active-tab indicator

A flat strip of brand yellow (`self.tab_indicator`, a plain `CTkFrame`) that
pokes out from behind the sidebar into the gutter beside whichever sidebar
button is active — deliberate choice over recoloring the button or adding a
highlight. It's positioned with `.place()` (independent of the grid) and
`.lower()`ed once at creation so the sidebar and the active tab's own frame
(both opaque) render on top of it wherever they overlap; only the thin
uncovered sliver between them actually shows through.

`show_tab(name)` re-aligns it on every switch via `_update_tab_indicator`,
but **deferred through `self.after(50, ...)`, not called synchronously**:
the very first call happens during `__init__`, before `mainloop()` has run
even once, and at that point the sidebar buttons haven't actually been mapped
onscreen — `winfo_height()` on them still returns a stale 1px placeholder
even after `update_idletasks()` and even via `after_idle` (both still fire
before the window's first real `<Configure>`/map pass). A real timed delay is
what actually works. Each call cancels any not-yet-fired previous one
(`self._tab_indicator_job`) so rapid tab switching can't let a stale,
out-of-order callback overwrite a newer one.

`Sidebar.buttons` (a `{name: button}` dict) is what `_update_tab_indicator`
looks up to know which button to align to.

### File selection is a broadcast, not a per-tab event

Any DropBox (drop or double-click or Browse) calls `app.update_global_file(path)`.
That method is the *only* place the selected file changes. It:

1. Strips tkdnd's `{}` wrapping from the path.
2. Extracts a thumbnail via `core.utilities.extract_video_thumbnail` (cv2 first frame → PIL).
3. Walks `tab_ui_registry` updating every registered label + thumbnail widget.
4. Calls `hide_drop_text()` on every tab that has a `drop_box`.

Tabs opt into this by calling `app.register_tab_ui(label, img_label, on_thumbnail=...)`
in their `__init__`. If `on_thumbnail` is omitted, a default handler renders a
fixed 350x200 `CTkImage`; Muxing and Encoding both pass their own so they can
cache the raw PIL image and rescale on `<Configure>` (see `display_image`/
`_resize_thumbnail` in either tab — identical logic in both, see "Muxing and
Encoding duplicate a lot of code" below).

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

`THEMES` is the source of truth: three named palettes — `Lemon` (`#FDCA3C`
primary / `#3B8ED0` secondary — the original look), `Cupid` (`#FA6E99` /
`#780219`), `Lilac` (`#B769D6` / `#154D33`). Every color is a **flat hex
string, not a `(light, dark)` tuple** — deliberate, so appearance mode never
changes a theme's colors. Hover shades are auto-derived by `_darken()`
(~0.87 brightness, matching the brand yellow's pre-existing `#FDCA3C` →
`#e0b234` ratio) except Lemon's primary hover, which keeps that exact
historical value. Text on any primary color is hardcoded `"black"`
everywhere, and `"white"` on any secondary — verified deliberately, not
assumed: WCAG relative luminance contrast for black-on-`#FDCA3C`/`#FA6E99`/
`#B769D6` comes out to roughly 13.7:1 / 7.8:1 / 6.0:1, all comfortably clear
of the 4.5:1 AA threshold, so no adaptive per-theme text-color logic was
needed.

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
  `.configure()` directly on `progress_bar`, `clear_btn`, `start_all_btn`,
  and every existing row's `progress_canvas`/style — recoloring in place
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
shared repo state), holding `theme`, `appearance_mode`, and
`default_save_location`; missing keys or a missing/corrupt file fall back
to defaults (`Lemon` / `"System"` / `""`) rather than raising.

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
  that queues *and* immediately starts the task. Encoding additionally has
  Profile/Level dropdowns, GPU/HDR switches, and a CRF slider (all Encoding-
  only fields); Muxing has just the Retain Video Length checkbox + time
  spinners. Keep `_gather_settings`/`load_settings` in sync when adding a
  control to either tab.
- **Queue** (`tabs/queue_tab.py`) — the most complex tab; see its own section
  below.
- **Settings** (`tabs/settings_tab.py`) — a left-aligned settings form with
  three options plus a Save button, each option a bold label above its
  control: **Theme** (`CTkOptionMenu` over `core.theme.THEMES` — see
  "Theming" above for the full palette/persistence/live-rebuild design —
  plus a small two-swatch live color preview, since the dropdown text alone
  doesn't convey the actual colors, and the change itself isn't applied
  until Save is clicked); **Appearance Mode** (`CTkOptionMenu`,
  System/Light/Dark, wired live to `ctk.set_appearance_mode()` on
  change — this takes effect the instant it's picked, no Save needed); and
  **Default Save Location** (`CTkEntry` + "Browse" button opening
  `filedialog.askdirectory()`, updating `app.default_save_location`
  immediately so it's live within the session even before Save is
  pressed). The **Save** button (`_on_save`) persists all three to
  `settings.json`, and — only if the theme actually changed — calls
  `self.app.apply_theme(new_theme)` to apply it live (see "Theming"), which
  rebuilds this tab too: `_on_save` returns immediately after that call
  rather than touching `self` again. `app.default_save_location` (read from
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

**Per-row progress visualization** (`progress_canvas`, grown each tick by
`_animate_progress` — see "Pixel-accurate progress-text clip" below for the
full mechanism and history): a raw `tkinter.Canvas`, not a `CTkFrame`, so
it has no `corner_radius` to worry about — it's a plain rectangle, which is
correct here since it only ever spans a *partial* width; a rounded shape
would render in the middle of the row (not at the row's true edges),
reading as a floating rounded blob rather than a flat fill. The row's own
rounded background is drawn by an **internal canvas created synchronously
inside `CTkFrame.__init__`**, i.e. before any of `row`'s own children
(including `progress_canvas`) exist — a widget placed without accounting
for this can end up stacked *below* that internal canvas (permanently
invisible); see the construction-order explanation below for how
`progress_canvas` avoids this.

**Pixel-accurate progress-text clip**: `progress_canvas` is a single raw
`tkinter.Canvas` (not a `CTkLabel`, and not a separate `CTkFrame` fill
*plus* a canvas — see below) per row. Its own `bg` *is* the active theme's
primary fill color, and it holds one black-on-primary copy of the
description drawn once via `create_text` (`progress_text_item`) at row
creation. Each
animation tick, `_update_progress_canvas` resizes this one canvas to
`fill_width` pixels wide and repositions the text item to
`description_label`'s current spot — `fill_width` is computed once in
`_animate_progress` (`round(fraction * max_fill_width)`) and used directly,
with no second calculation anywhere for anything to disagree with. Because
the fill color and the clipped text are the *same widget*, they cannot
desync by construction: there is only one number in play, not two. A raw
`Canvas` genuinely clips whatever it draws to its own configured
width/height, so the visible black text always ends exactly where the
primary-colored fill does — no gap, no drift, no separate background of its
own to draw. Hidden (`place_forget`) whenever `fill_width` is 0 or the row
isn't actively running (`Queued` or `Done`), in `_apply_row_style`.

This one-canvas design replaced an earlier two-widget version (a plain
`CTkFrame` fill *plus* a separately-clipped text canvas) that needed the
text canvas to read the fill's own already-resolved geometry back
(`fill.winfo_x() + fill.winfo_width()`, after an explicit
`update_idletasks()`) specifically because two independently-rounded
`fraction * width` calculations — one via `place(relwidth=...)`'s internal
rounding, one via a plain Python float passed to `canvas.configure
(width=...)` — didn't always round to the same pixel, which surfaced as an
intermittent 1px seam between the two edges. Merging them into one widget
doesn't just work around that mismatch, it makes it structurally
impossible, since there's no longer a second independent number for
anything to disagree with.

**Widget stacking order for the merged canvas**: `progress_canvas` needs to
sit *above* `description_label` (so its own paint can replace what's
underneath once the fill sweeps past) but *below* `thumb_label` (so the
thumbnail image is never covered, regardless of how far the fill grows).
Tk's default stacking order is construction order (later-constructed
siblings sit higher) — `add_task` exploits this directly instead of calling
`.lift()`/`.lower()`: `description_label` is *constructed* (but not yet
packed) first, then `progress_canvas`, then `thumb_label` — giving exactly
the above/below relationship needed, confirmed by isolating this exact
order and comparing rendered pixels. Packing (the actual left-to-right
visual layout — thumbnail first, then description) happens afterward, in
whatever order produces the right layout; pack() call order and
construction order are independent knobs, so this doesn't conflict with
`thumb_label` needing to be visually first.

Three approaches were tried before landing on the merged single canvas
(see the gotchas below for the full detail on each): a single opaque
overlay label clipped via `configure(width=...)` never worked because
**`CTkLabel` silently ignores a `width` smaller than its natural text size
and always renders the full, unclipped string** — confirmed by direct
pixel sampling. Individually-recoloring one `CTkLabel` per character
(matching `fg_color` to whatever was behind each glyph) got contrast
working but only at per-character granularity, so the black/grey boundary
visibly drifted ahead of or behind the fill's own smoothly-moving edge
instead of lining up with it exactly — and needed one extra widget per
character to boot. A two-widget canvas-clip approach (a separate `CTkFrame`
fill plus a separately-sized text canvas) fixed both of those but
introduced the rounding-mismatch problem described above, which is what
motivated merging the two into the current single canvas.

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
one (GPU/HDR/CRF/Profile/Level, absent from Mux) scrolls inside the same
box. `_DETAIL_FIELDS` drives which settings keys get shown and how
(`None`/`"time"`/`"bool"` formatting); a key simply absent from a task's
settings dict is skipped, which is how Mux tasks naturally omit the
encoding-only fields. Popup is packed with `before=self.controls_frame` so
it always lands directly above the bottom buttons regardless of call order.
Single-click (not double-click — that binding was deliberately removed, see
below) shows it; the popup's own "✕" just calls `self.detail_frame.pack_forget`.

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

### Components

- **DropBox** (`components/drop_box.py`) — self-packing (`self.pack()` in
  `__init__`, so callers don't need to). Takes an `on_file_selected` callback
  (in practice always `app.update_global_file`) and an optional `height`
  (default 280; Muxing/Encoding both pass 380). Drop/double-click are bound
  on the frame, its content frame, and the label, since tkdnd doesn't
  propagate to children.
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
  (`{year} Yezan Smadi · v0.5.0-alpha.1`) down to the sidebar's bottom edge.
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
`input_file, output_path, start_secs, duration_secs, gpu_enabled, hdr_to_sdr,
retain_length, crf, profile, level`. Muxing's is the same minus the five
encoding-only keys (`gpu_enabled, hdr_to_sdr, crf, profile, level`) — the
Queue tab's details popup relies on those keys being *absent* (not just
falsy) to correctly hide them for Mux tasks.

## Conventions

- The brand accent (sidebar fill, DropBox border, primary action buttons,
  active-tab indicator, queued/in-progress queue rows) is **theme-driven,
  not a hardcoded color** — see "Theming" above. The default `Lemon` theme's
  primary is `#FDCA3C` with `#e0b234` as its hover, and black text on top of
  it — that black-on-primary pairing is used consistently across all three
  themes (queued row text, the dark-text sweep overlay, switch/checkbox
  labels) rather than introducing new color pairs. The Stop Queue button is
  the one deliberate departure — red (`#E5484D`, hover `#C93C40`) to read
  as destructive/halting rather than a primary action, and this **never**
  changes with the theme.
- Widgets are stored as `self.` attributes even when not obviously reused.
- Comments are used generously as section markers (`# --- Bottom Section ---`) and
  to explain *why* a layout choice was made, especially for Tk/CTk gotchas that
  aren't obvious from the code alone (see the gotchas list below) — match that density.
- Every non-trivial method gets a one-line docstring.
- Tab classes take `(self, master, app)` and subclass `ctk.CTkFrame`.

## Known issues / gotchas

- **Individual queue progress fill's known bugs (box occlusion, pixel
  misalignment) are fixed; treat further visual polish requests on it as
  new, not a reopened old bug.** `progress_canvas`'s width is explicitly
  capped at `status_label`'s own left edge instead of spanning the full row
  (see `_animate_progress`) — letting it reach further used to run into
  `status_label`/`remove_btn` being `fg_color="transparent"` (a frozen,
  one-time snapshot per the gotcha below), so their own stale background
  would occlude the fill there, showing as a solid grey box cut into it.
  The fill and its text clip are now the same single canvas (see
  "Pixel-accurate progress-text clip") rather than two separately-sized
  widgets, which is what previously caused an intermittent 1px misalignment
  between them. Both were confirmed by direct pixel/geometry verification
  across a full animation run, not just visual inspection.
- **Muxing and Encoding duplicate a lot of code** — `display_image`,
  `_on_resize`, `_resize_thumbnail`, `select_input_file`,
  `toggle_time_spinners`, and most of `select_save_location` are near-verbatim
  copies between the two tabs. This was done deliberately per explicit
  instruction ("do the same thing to the muxing tab") rather than refactored
  into a shared base, but if a third tab needs the same pattern, that's the
  point to actually extract it rather than copy a third time.
- **`fg_color="transparent"` on a CTk widget is not real per-pixel
  transparency.** `CTkBaseClass._detect_color_of_master()` resolves it
  exactly once, at widget-creation time, to a static snapshot of the
  master's own `fg_color` — it never re-samples afterward. A "transparent"
  widget placed over something that changes color underneath it later (e.g.
  the queue's progress fill sliding past) still paints that frozen original
  color forever, not what's currently beneath it. Confirmed by sampling
  actual rendered pixels while prototyping the queue's progress-text
  contrast as one `CTkLabel` per character (an approach since replaced by
  `progress_canvas`'s single-canvas clip — see "Pixel-accurate
  progress-text clip" above): a `fg_color="transparent"` char label over
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
  Hit while prototyping the queue's progress-text contrast as one `CTkLabel`
  per character (since replaced by `progress_canvas`'s single-canvas clip —
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
- **CTk widgets don't take `width`/`height` via `.place()`** — only via
  `.configure()` (raises `ValueError` otherwise). Hit twice in this codebase
  (the tab indicator, and the queue's dark-text overlay): always
  `widget.configure(width=..., height=...)` then `widget.place(x=..., y=...)`.
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
