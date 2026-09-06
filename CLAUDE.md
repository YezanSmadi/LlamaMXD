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
configured size — see "DropBox / expand+fill gotchas" below before changing it.

The OS close button is bound (`WM_DELETE_WINDOW` → `on_close`) to
`self.destroy()` then `sys.exit(0)`, a hard full-process exit rather than
letting the Python process linger after the window goes away.

### Active-tab indicator

A flat strip of the theme's `primary` (`self.tab_indicator`, a plain
`CTkFrame`) that pokes out from behind the sidebar into the gutter beside
whichever sidebar button is active, with a narrower 8px `secondary` band
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
**even** (`line_h = 8`), and both pipes pin `bg_color` to `primary` instead of
letting it default. CTk floors a drawn shape's width/height to the nearest
even number, so at the band's original height of 9 it painted 8 rows and left
the 9th showing the widget's own raw canvas — which, at the default
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
constant `#E5484D` (`_STOP_TEXT` in `queue_tab.py`, resolves to black).

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
— Theme and Appearance Mode on Settings, Profile and Level on Encoding. It
subclasses `CTkOptionMenu` but redirects `_open_dropdown_menu` to a custom
in-window panel, because the native popup can't do two things this app needs:

1. **Stay open until an explicit dismissal.** A click on the button again, or
   anywhere outside the panel (`_on_global_click`, a `<Button-1>` binding
   added on the toplevel with `add="+"` while open and removed by funcid on
   close). Moving the pointer off it does nothing — an earlier `<Leave>` +
   pointer-position close was removed on request.
2. **Report row hover** (`on_hover`), which the theme picker needs for its
   live palette preview. The native popup is modal on Windows and repaints
   nothing behind it, so a hover preview is invisible there.

`command` is deliberately **not** passed to the base class — the native
value-picking path never runs, so `_select` invokes the caller's callback
itself.

**The panel is parented to the toplevel**, not to the dropdown's own master,
so it can float over anything beneath it (Tk's `place(in_=...)` accepts any
target that's a descendant of the placed widget's parent, and the root is an
ancestor of everything). The cost of that is it *isn't* destroyed along with
the tab that owns the dropdown — hence the `destroy()` override, which
matters because a live theme switch rebuilds every tab.

**It flips upward when there's no room below.** The window is a fixed, fairly
short size and Profile/Level sit two rows from its bottom edge, where a
downward panel is clipped by the window with its last entries unreachable
(Baseline was simply invisible). `open()` compares the panel's `reqheight`
against the room below the button and places with `anchor="sw"` at the
button's top-left instead — which puts the panel's *bottom* edge there so it
grows upward. Verified for all four dropdowns: every panel lands fully inside
the window.

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
`after()` chain, and each fade step is a `configure(fg_color=...)` that
forces CTk to redraw the widget's rounded rectangle — so an uncapped stack
turned button-mashing into dozens of concurrent timer chains competing with
the UI thread. Measured as event-loop latency (how late a 10ms heartbeat
actually fires) under 60 rapid notifications: **p90 79.7ms uncapped vs 6.1ms
capped**, against a 6.0ms idle baseline. A further arrival calls `retire()`
on the oldest slot-holder, which skips any remaining hold and cuts to a fast
fade; retiring toasts stop claiming a slot immediately (`is_retiring`) but
stay put while they fade rather than making everything below them jump.
`forget()` triggers `_relayout()` so a dismissed toast doesn't leave a hole —
survivors *snap* to their new slot rather than animating, since one more
timer chain per survivor is exactly the cost being avoided. Two smaller cuts
in the same spirit: the toast is `lift()`ed once at the start rather than on
every slide step (restacking costs far more than the `place()` that moves
it), and `show()` only forces an `update_idletasks()` layout pass when the
tab frame genuinely hasn't been laid out yet.

**The fade is color interpolation, not alpha.** Tk has no per-widget
transparency (only a whole `Toplevel` takes `-alpha`), and CTk's
`fg_color="transparent"` is a frozen one-time snapshot rather than real
see-through (see Known Issues). So `_fade` walks the toast's `fg_color` and
`text_color` toward the backdrop color over 20 steps. The blend goes through
`winfo_rgb()` so it accepts Tk color names (`gray17`, what the tab backdrop
resolves to) as readily as the theme's hex. The toast also pins `bg_color` to
the backdrop for the same even-flooring reason the tab indicator does.

Current toasts: "Job added to queue." (Queue Task on either tab) and
"Encoding/Muxing job has begun." (the direct Encode/Mux buttons).

### Components

- **ThemedDropdown** (`components/dropdown.py`) — see "Dropdowns" above. Every
  dropdown in the app uses it; don't add a bare `CTkOptionMenu`.
- **MessageDialog** (`components/dialogs.py`) and **Toast / ToastManager**
  (`components/toast.py`) — see "User feedback: dialogs and toasts" above.
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
`input_file, output_path, start_secs, duration_secs, gpu_enabled, hdr_to_sdr,
retain_length, crf, profile, level`. Muxing's is the same minus the five
encoding-only keys (`gpu_enabled, hdr_to_sdr, crf, profile, level`) — the
Queue tab's details popup relies on those keys being *absent* (not just
falsy) to correctly hide them for Mux tasks.

## Conventions

- The brand accent (sidebar fill, DropBox border, primary action buttons,
  active-tab indicator, queued/in-progress queue rows) is **theme-driven,
  not a hardcoded color** — see "Theming" above. The default `Lemon` theme's
  primary is `#FDCA3C` with `#e0b234` as its hover. Text placed on any
  primary or secondary color is **not** a hardcoded literal — it comes from
  `theme["primary_text"]` / `theme["secondary_text"]`, which
  `readable_text_on()` resolves to black or white per-color for contrast
  (see "Theming" above). The Stop Queue button is the one deliberate
  fill-color departure — red (`#E5484D`, hover `#C93C40`) to read as
  destructive/halting rather than a primary action, and that red **never**
  changes with the theme (its label still goes through `readable_text_on`).
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
