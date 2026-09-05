# LlamaMXD — File-by-File Documentation

This document goes through every file in the repository and explains what it
contains and what it does. For narrative architecture notes, known gotchas,
and conventions, see [`CLAUDE.md`](CLAUDE.md) — this file is a per-file
reference instead.

Directory layout:

```
LlamaPY GUI/
├── main.py
├── requirements.txt
├── LICENSE
├── .gitignore
├── .vscode/
│   └── settings.json
├── llama.ico
├── llama.png
├── core/
│   ├── app.py
│   ├── theme.py
│   └── utilities.py
├── components/
│   ├── drop_box.py
│   ├── sidebar.py
│   └── time_spinner.py
└── tabs/
    ├── muxing_tab.py
    ├── encoding_tab.py
    ├── queue_tab.py
    ├── settings_tab.py
    └── ytdlp_tab.py
```

There are no `__init__.py` files anywhere — `core`, `components`, and `tabs`
work as Python implicit namespace packages, and every import in the project
is absolute from the repo root (e.g. `from components.drop_box import
DropBox`), which is also why the app must be launched from the repo root.

---

## Root files

### `main.py`

The application's entry point. It imports `customtkinter`, `LlamaGUI`
(from `core.app`), and `load_settings` (from `core.theme`), and under
`if __name__ == "__main__":` sets CustomTkinter's appearance mode from the
persisted setting (`ctk.set_appearance_mode(load_settings()
["appearance_mode"])` — defaults to `"System"` if nothing's been saved
yet), constructs a single `LlamaGUI` instance, and calls `app.mainloop()`
to start the Tk event loop. It holds no other logic — everything else
lives in `core/app.py` and below. This has to run *before* `LlamaGUI` is
constructed, since appearance mode can only be set process-wide, not
per-window.

### `requirements.txt`

Pinned third-party dependencies, installed with `pip install -r
requirements.txt` (though in practice, per `CLAUDE.md`, they're installed
globally rather than in a virtual environment):

| Package | Version | Used for |
|---|---|---|
| `customtkinter` | 6.0.0 | The whole UI toolkit — every widget in the app is a `ctk.*` widget wrapping standard Tkinter. |
| `tkinterdnd2` | 0.6.2 | Native OS drag-and-drop support (`DND_FILES`, `TkinterDnD.DnDWrapper`), used by `DropBox` and the root window. |
| `opencv-python` | 5.0.0 | Imported as `cv2`; used only to grab a video's first frame for thumbnail generation. |
| `Pillow` | 11.3.0 | Imported as `PIL`; converts OpenCV's raw frame arrays into `Image` objects and loads the sidebar logo PNG. |

Notably absent: `ffmpeg`/`yt-dlp` Python bindings — the app shells out to
neither yet (see the "No real ffmpeg pipeline yet" note under `queue_tab.py`
below). `ffmpeg` is expected to already be on the system `PATH`, per
`CLAUDE.md`.

### `LICENSE`

The [Unlicense](https://unlicense.org) — public-domain dedication. States
the software is released with no copyright restrictions and no warranty.

### `.gitignore`

Excludes Python bytecode/cache artifacts and virtual environment
directories from version control:

```
__pycache__/
*.pyc
*.pyo
*.pyd
.venv/
venv/
```

### `.vscode/settings.json`

A single VS Code workspace setting:
`"python-envs.defaultEnvManager": "ms-python.python:system"` — tells the
VS Code Python extension to use the system Python interpreter rather than
prompting to create/select a virtual environment, consistent with the
project's "installed globally, no venv" setup described in `CLAUDE.md`.

### `llama.ico`

The Windows application icon (used by `LlamaGUI.iconbitmap("llama.ico")` in
`core/app.py`). Binary `.ico` asset — must exist in the repo root at launch
time since it's loaded by a relative path.

### `llama.png`

The llama logo image shown in the sidebar (loaded via `PIL.Image.open` in
`components/sidebar.py` and rendered at 140×140 as a `CTkImage`). Also
loaded by relative path — this is the other reason the app must be run from
the repo root.

---

## `core/` — application shell and shared utilities

### `core/app.py`

Defines `LlamaGUI`, the root application window and the hub every other
piece of UI reaches through. This is the largest and most structurally
important file outside of `tabs/queue_tab.py`.

**Class `LlamaGUI(ctk.CTk, TkinterDnD.DnDWrapper)`**

Inherits from both `ctk.CTk` (the CustomTkinter root window) and
`TkinterDnD.DnDWrapper`, so drag-and-drop works anywhere in the window, not
just inside a single widget. `self.TkdndVersion = TkinterDnD._require(self)`
in `__init__` is what actually wires up the tkdnd extension for this Tk
interpreter instance.

`__init__(self)`:
- Computes the window size as a fraction of the screen: `scaled_w = width *
  0.35`, `scaled_h = height * 0.375`, then centers the window
  (`x_center`/`y_center`) and calls `self.geometry(...)`. A code comment
  explains the 0.375 height was chosen (down from an earlier 0.5) to avoid
  both an overly-square window (at 0.5) and a window too short for its
  content, which used to let the packer silently compress the DropBox below
  its configured size.
- Sets the window title to `"LlamaMXD"`, loads `llama.ico` as the taskbar/
  title-bar icon, and calls `self.resizable(False, False)` — the window is
  permanently fixed-size.
- Binds `WM_DELETE_WINDOW` (the OS close button) to `self.on_close`.
- Configures a 1-column-of-two, 1-row grid: column 0 (the sidebar) is
  fixed-width by default, column 1 (whichever tab is showing) has
  `weight=1` so it absorbs all extra horizontal space; row 0 has
  `weight=1` so tab content fills the full window height.
- Initializes shared state: `self.current_file_path` (the single globally-
  selected input file, starts as `""`), `self.default_save_location` (the
  starting directory for Encoding/Muxing's save dialogs when no input file
  is loaded yet — read from `core.theme.load_settings()`, so it survives a
  restart once the Settings tab's Save button has written it),
  `self.tab_ui_registry` (a list of per-tab UI hooks — see
  `register_tab_ui` below), `self._tab_indicator_job` (an `after()` job
  id used to debounce the tab indicator's positioning — see below), and
  `self._current_tab_name` (starts as `"Muxing"`, kept in sync by
  `show_tab` — this is what lets `apply_theme` re-show whichever tab was
  active before a live theme rebuild).
- Calls `apply_ctk_theme(load_settings()["theme"])` (from `core/theme.py`)
  *before* constructing any widget below — this loads (generating on first
  use) a CTk theme JSON where every default-styled widget's accent color
  has been swapped to the active theme's secondary color, so checkboxes,
  switches, sliders, dropdowns, and the sidebar's nav buttons all pick it
  up from their very first construction.
- Constructs `self.sidebar` (a `Sidebar` instance) and grids it into column
  0.
- Constructs `self.tab_indicator`: a flat, unrounded `CTkFrame` colored
  with the active theme's primary color (`core.theme.get_active_theme()
  ["primary"]` — see `core/theme.py` below), immediately `.lower()`ed so it
  renders behind everything else that might overlap it. This is the
  active-tab accent strip described in `CLAUDE.md` — a sliver of the brand
  color that pokes out from behind the sidebar next to whichever nav
  button is currently selected. It's positioned with `.place()`
  (independent of the grid), not packed or
  gridded.
- Builds `self.tabs`, a `dict` mapping tab name → tab instance, constructing
  all five tabs eagerly at startup: `MuxingTab`, `EncodingTab`, `QueueTab`,
  `YtDlpTab`, `SettingsTab` — each is given `master=self, app=self`.
- Calls `self.show_tab("Muxing")` to display the first tab.

`register_tab_ui(self, label_widget, img_widget, on_thumbnail=None)`:
Lets a tab opt into the cross-tab file-selection broadcast (see
`update_global_file` below). If the caller doesn't supply `on_thumbnail`, a
default handler is created inline that renders the thumbnail as a fixed
350×200 `CTkImage` on `img_widget`. The tab's `label`/`img`/`on_thumbnail`
triple is appended to `self.tab_ui_registry`.

`update_global_file(self, file_path)`: The single method that ever changes
`self.current_file_path`. Strips tkdnd's `{}` path-wrapping and surrounding
whitespace; if the result is empty, bails out. Otherwise:
1. Sets `self.current_file_path`.
2. Calls `extract_video_thumbnail` (from `core/utilities.py`) once, up
   front, producing one raw `PIL.Image` shared by every registered tab.
3. Walks `self.tab_ui_registry`, updating each entry's label text to
   `f"Selected File:\n{self.current_file_path}"` and, if a thumbnail was
   successfully extracted, calling that entry's `on_thumbnail` callback
   with it.
4. Walks every tab in `self.tabs`, and for any tab that has a `drop_box`
   attribute, calls `tab.drop_box.hide_drop_text()` (collapsing that tab's
   drop-target hint/border now that a file is selected).

`show_tab(self, name)`: records `name` into `self._current_tab_name`, then
`grid_forget()`s every tab, then `grid()`s only the
requested one into `(row=0, column=1)` with 10px padding on all sides. It
then (re)schedules `_update_tab_indicator(name)` via `self.after(50, ...)`
— deliberately delayed rather than called synchronously, and any
previously-scheduled-but-not-yet-fired call is cancelled first
(`self.after_cancel` on `self._tab_indicator_job`) so rapid tab-switching
can't let a stale callback overwrite a newer one. The delay exists because,
per the in-code comment, the very first call happens during `__init__`
before `mainloop()` has run even once, at which point the sidebar buttons
haven't been mapped onscreen yet and `winfo_height()` on them would return a
stale placeholder even after `update_idletasks()`.

`_update_tab_indicator(self, name)`: Looks up the sidebar button for `name`
via `self.sidebar.buttons`, calls `update_idletasks()` to force fresh
geometry, then sizes `self.tab_indicator` to `width=24,
height=button.winfo_height()` (via `.configure()`, since CTk widgets don't
accept width/height through `.place()`) and places it at
`x=sidebar_width - 8, y=button.winfo_y()` — straddling the sidebar/content
seam so it's invisible over the sidebar (both are the same theme primary
color) and hidden under the tab frame's left edge, leaving only a thin
visible sliver.

`apply_theme(self, theme_name)`: makes a theme switch actually live, no
restart, called from `SettingsTab._on_save` when the theme changed. Since
`ctk.set_default_color_theme()` (called here via `core.theme.
apply_ctk_theme`) only affects widgets constructed *after* the call, the
only way to make CTk-default-styled widgets (checkboxes, switches,
sliders, dropdowns, the sidebar's nav buttons) genuinely change color live
is to reload the theme and then reconstruct the widgets that read it:
1. `apply_ctk_theme(theme_name)` — reload CTk's default theme.
2. Snapshot `Muxing`/`Encoding`'s current field values via
   `_gather_settings()`, and the currently-active tab name.
3. `.destroy()` the sidebar, the tab indicator, and the `Muxing`/
   `Encoding`/`YT-DLP`/`Settings` tab instances — *not* `Queue` (see
   below) — and reset `self.tab_ui_registry` (its old entries pointed at
   widgets that no longer exist).
4. Reconstruct the sidebar, tab indicator, and those same four tabs fresh
   — each one, by virtue of being newly constructed, reads the just-loaded
   CTk theme and the active `core.theme` palette correctly.
5. Restore `Muxing`/`Encoding`'s snapshotted settings via `load_settings()`.
6. Call `self.tabs["Queue"].refresh_theme()` — `Queue` is deliberately
   *never* destroyed here, since that would discard its task list
   (`self._rows`) and any in-flight animation; instead it gets its own
   in-place recolor (see `QueueTab.refresh_theme` below).
7. `self.show_tab(active_tab_name)` — re-show whatever was on screen
   before the rebuild.

`on_close(self)`: Calls `self.destroy()` then `sys.exit(0)` — a clean full
process exit on window close, rather than leaving the Python process
lingering.

### `core/theme.py`

The app's central color-theming and settings-persistence module. Every
other file that used to hardcode the brand yellow (`"#FDCA3C"`) now imports
from here instead.

**`THEMES`**: a dict of three named palettes, each a `{"primary": ...,
"secondary": ...}` pair of flat hex strings (plus an optional
`"primary_hover"` override, used only by `"Lemon"`):

- `"Lemon"` — `#FDCA3C` primary, `#3B8ED0` secondary. This is the
  original/default look; secondary is CTk's own stock button-blue,
  flattened to a single shade (CTk's own default varies it between light
  and dark mode; this app's theme colors deliberately never do).
- `"Cupid"` — `#FA6E99` primary, `#780219` secondary.
- `"Lilac"` — `#B769D6` primary, `#154D33` secondary.

**`_darken(hex_color, factor=0.87)`**: returns a slightly-darker shade of a
given hex color for hover states, by scaling each RGB channel down by
`factor` and re-encoding. `0.87` was chosen to match the ratio already
implicit in the brand yellow's pre-existing, hand-picked hover
(`#FDCA3C` → `#e0b234`).

**`get_theme(name=None)`**: returns the *full* four-color palette for a
theme name — `primary`, `primary_hover`, `secondary`, `secondary_hover` —
filling in any missing hover color via `_darken()`. Falls back to
`DEFAULT_THEME_NAME` (`"Lemon"`) for an unrecognized or `None` name, so
callers never need to guard against a bad theme name themselves.

**`load_settings()` / `save_settings(settings)`**: read/write a small
`settings.json` file at the repo root (derived from this file's own
location via `os.path.dirname(os.path.dirname(...))`, not a bare relative
path, so it doesn't depend on the process's current working directory the
way `llama.ico`/`llama.png` do). `settings.json` is `.gitignore`d — it's a
local user preference file, not shared repository state, and is created on
first save rather than checked in. `load_settings()` returns defaults
(`{"theme": "Lemon", "appearance_mode": "System", "default_save_location":
""}`) for any key missing from the file, and for the file not existing or
failing to parse at all (`json.JSONDecodeError`/`OSError` are both caught
silently) — so a first run, or a hand-edited/corrupted settings file,
degrades to sane defaults instead of crashing the app at startup.

**`get_active_theme()`**: the convenience accessor nearly every explicitly-
colored widget calls — `get_theme(load_settings().get("theme"))`, i.e. "the
palette for whatever theme is currently persisted."

**`_CTK_ACCENT` / `_CTK_ACCENT_HOVER` / `_CTK_ACCENT_PRESSED`**: the three
hardcoded color-pair values (`["#3B8ED0","#1F6AA5"]`, `["#36719F",
"#144870"]`, `["#27577D","#203A4F"]`) that CTk's own bundled `blue.json`
theme reuses across every widget's accent-colored property — confirmed by
dumping that file in full. `CTkOptionMenu` alone uses the third, even-darker
pair for its own dropdown-arrow-button's hover state; every other accent
property uses just the first two.

**`_substitute_ctk_accents(node, secondary, secondary_hover,
secondary_pressed)`**: recursively walks a parsed CTk theme JSON structure
(dicts and lists), replacing any list that equals one of the three constants
above with `[color, color]` (the *same* value repeated for both the light
and dark slots — flattening it, so appearance mode can't reintroduce a color
difference the rest of this module works to avoid). This is a **value-based**
substitution rather than a per-widget/per-key list — it doesn't need to know
which widgets or JSON keys hold accent colors, it just replaces the values
wherever they appear, which is what lets one small function retint every
CTk-default-styled widget (buttons, checkboxes, switches, sliders, option
menus, segmented buttons) consistently.

**`_ctk_theme_path(theme_name)`**: generates (or regenerates — it's cheap,
so no caching-invalidation logic is needed) a full CTk theme JSON file for
`theme_name`. Loads customtkinter's own bundled `blue.json` (located via
`os.path.dirname(ctk.__file__)`) as a base, runs it through
`_substitute_ctk_accents` with that theme's `secondary`/`secondary_hover`
and a `_darken()`-ed `secondary_pressed`, writes the result to
`_generated_themes/<name>.json` (gitignored — a build artifact, not
source), and returns that path.

**`apply_ctk_theme(theme_name)`**: `ctk.set_default_color_theme
(_ctk_theme_path(theme_name))` — loads the generated theme as CTk's
process-wide default. Critically, this only affects widgets *constructed
after* this call; CTk never retroactively recolors an existing widget. Both
`LlamaGUI.__init__` (on every launch) and `LlamaGUI.apply_theme` (see
`core/app.py` below, for the live in-session switch) call this before
constructing anything that should read the new colors.

### `core/utilities.py`

A tiny, stateless helper module — currently a single function.

`extract_video_thumbnail(video_path)`: Opens `video_path` with
`cv2.VideoCapture`, reads exactly one frame (`cap.read()`), and immediately
releases the capture handle. If the read failed or returned no frame,
returns `None`. Otherwise converts the frame from OpenCV's native BGR
channel order to RGB (`cv2.cvtColor(..., cv2.COLOR_BGR2RGB)`) and wraps it
in a `PIL.Image` via `Image.fromarray`. Returns a raw, unsized image — every
caller is responsible for scaling it to whatever size it needs (this is why
`update_global_file` extracts the thumbnail once and hands the same raw
image to every registered tab's own resize logic, rather than each tab
re-decoding the video itself).

---

## `components/` — reusable, tab-agnostic widgets

### `components/drop_box.py`

Defines `DropBox(ctk.CTkFrame)`, a self-contained drag-and-drop / browse
target used identically by both `MuxingTab` and `EncodingTab`.

`__init__(self, master, on_file_selected, height=280)`: Builds a bordered
frame (`corner_radius=10`, `border_width=2`, `border_color=` the active
theme's primary color via `get_active_theme()["primary"]` — see
`core/theme.py` — fixed `width=350`, configurable `height`). Stores the
`on_file_selected`
callback (in practice always `app.update_global_file`). Calls `self.pack
(pady=10)` itself — callers don't pack a `DropBox`, it packs itself — and
`self.pack_propagate(False)` so its configured size doesn't get squeezed by
its children.

Inside, a `content_frame` (transparent background) holds:
- `self.drop_label`: a `CTkLabel` reading `"Drag & Drop File Here\n\n— or —
  \n"`, kept as an instance attribute so it can be unpacked later.
- `self.import_btn`: a `"Browse File"` `CTkButton` wired to
  `self.browse_file`.

Event binding: for each of `self`, `content_frame`, and `drop_label`
(tkdnd events don't propagate to children, so each widget needs its own
bindings), it registers `DND_FILES` as a drop target, binds `<<Drop>>` to
call `self.on_file_selected(e.data)`, and binds `<Double-Button-1>`
(double-click) to also call `self.browse_file()`.

`hide_drop_text(self)`: Called once a file has actually been selected.
Unpacks `drop_label` (the drag-and-drop prompt disappears) and reconfigures
the frame itself to `border_width=0, fg_color="transparent", height=40` —
collapsing the whole box down to a slim, borderless 40px strip rather than
leaving a big empty bordered box behind.

`browse_file(self)`: Opens a native `filedialog.askopenfilename` (any file
type), and if the user picked something, forwards the path to
`self.on_file_selected`.

### `components/sidebar.py`

Defines `Sidebar(ctk.CTkFrame)` — the persistent left-hand navigation panel.

`__init__(self, master, app)`: Builds a fixed-width (`180`), unrounded
frame colored with the active theme's primary color
(`get_active_theme()["primary"]` — see `core/theme.py`). From top to
bottom:
1. `title_label` — bold "LlamaMXD" text in black.
2. `image_label` — the llama logo (`llama.png`, loaded via `PIL.Image.open`
   and wrapped as a 140×140 `CTkImage`).
3. Four navigation buttons (`btn_tab1`–`btn_tab4`, labeled Muxing /
   Encoding / Queue / YT-DLP), each wired to `lambda:
   self.app.show_tab(<name>)`.
4. `footer_label` and `btn_settings` — packed with `side="bottom"`, packed
   *before* the spacer described next. A code comment explains why this
   order matters: Tk's `pack()` carves out layout space in call order, not
   by `side` — an `expand=True` widget claims whatever space remains *at
   the moment it's packed*, so packing the spacer first would starve
   anything packed after it of space regardless of its own `side`.
   `footer_label` (copyright/version text, `"{year} Yezan Smadi
   v0.5.0-alpha.1"`) is packed first so it claims the literal bottom edge;
   `btn_settings` packs second, landing just above it.
5. `self.spacer` — a transparent, `fill="both", expand=True` frame packed
   *last*, consuming whatever vertical space is left between the nav button
   group above and the Settings button/footer below, visually separating
   them.

`self.buttons` is a `{name: button}` dict (`"Muxing"`, `"Encoding"`,
`"Queue"`, `"YT-DLP"`, `"Settings"`) exposed so `LlamaGUI._update_tab_
indicator` can look up which button to align the accent strip to.

### `components/time_spinner.py`

Defines `TimeSpinner(ctk.CTkFrame)` — a custom HH:MM:SS input widget with a
fake block-style text cursor, used by both `MuxingTab` and `EncodingTab` for
their Start Time / Clip Duration fields. This is the most intricate
component in the codebase.

**Internal model**: `self.digits` is a 6-element list of single-character
strings (`["H","H","M","M","S","S"]`), the single source of truth for the
displayed value. `self.cursor_pos` is an integer index (0–5) directly into
that list — also a single source of truth, for *where* the cursor sits.
`_SEGMENT_POSITIONS = (0, 1, 3, 4, 6, 7)` is the one place that maps a digit
index to its character offset in the rendered `"HH:MM:SS"` string (skipping
over the two `:` characters) — used both to draw the selection highlight and
to translate a raw click position back into the nearest digit.

**Construction**: builds, left to right: a `-` button (`btn_minus`), a
`CTkEntry` (`self.entry`, width 100, centered text) used purely as a
read/display surface for the formatted string, and a `+` button
(`btn_plus`). Both buttons bind `<ButtonPress-1>`/`<ButtonRelease-1>`/
`<Leave>` to start/stop an accelerating auto-repeat loop (see below) that
calls `self.increment`/`self.decrement`. The entry itself binds `<Key>`,
`<BackSpace>`, `<Delete>`, `<Button-1>`, `<FocusIn>`, and `<FocusOut>` to
custom handlers that intercept and replace Tkinter's native text-editing
behavior — every key handler returns `"break"` to stop Tk's default entry
behavior from also firing.

**Auto-repeat** (`_start_hold`, `_run_hold_loop`, `_step_and_continue`,
`_stop_hold`): pressing `+`/`-` runs the action immediately, then
repeatedly reschedules itself via `self.after(...)`, shrinking the delay
each time by a factor of 0.85 (down to a floor of `_min_delay = 30`ms) so
holding the button accelerates from 400ms steps to near-continuous ticking.
Releasing the button or the mouse leaving it (`<Leave>`) cancels the
pending `after()` job.

**Typing** (`_on_key_press`): a typed digit overwrites `self.digits
[cursor_pos]`, calls `_validate_and_clamp_limits()` (caps minutes/seconds
at 59 by forcing them to `["5","9"]` if they'd otherwise exceed it), then
advances the cursor one position (capped at index 5) and redraws.
Arrow keys (`Left`/`Right`) move the cursor by one (clamped to `[0,5]`);
`Home`/`End` jump to index 0/5. `Tab`/`ISO_Left_Tab` are explicitly passed
through (not intercepted) so focus traversal still works. Every other key
is swallowed (`return "break"` with no action).

**Backspace vs. Delete** are deliberately different: `_on_backspace` steps
the cursor *back* first, then clears that digit — mirroring typing in
reverse (undoing the last advance). `_on_delete` clears the digit under the
cursor *without* moving it.

**Cursor rendering** (`_render_block_cursor`): the widget suppresses the
native blinking text caret entirely via `_hide_caret` (sets the underlying
raw entry's `insertwidth` to 0 and its `insertbackground` to match its own
background, making the native caret invisible even if it were drawn), and
instead draws a one-character `select_range` highlight at
`_SEGMENT_POSITIONS[cursor_pos]` to visually indicate cursor position. This
only actually draws anything if `_is_focused()` (checked by comparing
`self.focus_get()` against the entry's internal raw widget).

**Clicking** (`_on_click`, bound via `<Button-1>` with a 10ms `self.after`
delay to let Tk's own click-positioning resolve first): reads where Tk
would have placed its native insertion cursor (`self.entry.index
("insert")`), and maps that string index to the nearest actual digit slot
via `_nearest_digit_index` (minimizing distance to any value in
`_SEGMENT_POSITIONS` — this is what lets a click land correctly even if the
user clicks on a `:` separator or between characters).

**Public API**: `get_total_seconds()` / `get()` (formatted `"HH:MM:SS"`
string) read the current value; `set(total_seconds)` writes a new value and
redraws; `increment()`/`decrement()` step by exactly one second (with
`decrement` floored at 0); `set_state("normal"|"disabled")` enables/disables
all three child widgets and greys out the text when disabled (used by the
"Retain Video Length" checkbox in both Muxing and Encoding tabs to disable
the time fields when the source length is being kept as-is).

---

## `tabs/` — one `CTkFrame` subclass per sidebar tab

All five tab classes take `(self, master, app)` and subclass `ctk.CTkFrame`.

### `tabs/muxing_tab.py`

Defines `MuxingTab` — the simpler of the two "do work on a video" tabs (the
other being `EncodingTab`, which shares most of its structure but adds
encode-specific controls).

**Layout** (`__init__`): built bottom-up so the fixed-height controls anchor
to the window's bottom edge and the flexible `DropBox` above absorbs
whatever space is left:
- `controls_frame` is packed *first*, `side="bottom"`, containing (top to
  bottom): the "Retain Video Length" `CTkCheckBox` (checked by default,
  wired to `toggle_time_spinners`), a `time_container` row holding the
  Start Time and Clip Duration `TimeSpinner`s side by side, a save-location
  row (`CTkEntry` + "Browse" button wired to `select_save_location`), and
  an `action_frame` with two evenly-split (`grid_columnconfigure(...,
  weight=1, uniform="action")`) buttons: `"Queue Task"` (the active theme's
  *secondary* color, white text, `add_to_queue`) and `"Mux"` (the active
  theme's *primary* color, black text, `mux_now`) — both read their colors
  from `core.theme.get_active_theme()` at construction time rather than
  hardcoding them (see `core/theme.py`).
- `top_container` is packed *after*, `fill="both", expand=True`, absorbing
  all leftover vertical space. It holds a hidden-until-populated `label`
  (filename header) and `img_label` (thumbnail, double-click to reselect a
  file), plus a `DropBox` (height 380) that fills the container while it's
  the only thing packed there.
- Registers `label`/`img_label` with the app via `app.register_tab_ui(...,
  on_thumbnail=self.display_image)` so this tab receives the global file-
  selection broadcast with its own thumbnail handler (rather than the
  app's generic default), and binds `top_container`'s `<Configure>` event
  to `_on_resize` for live thumbnail rescaling.

**Methods**:
- `select_input_file()`: opens a native open-file dialog scoped to common
  video extensions (`*.mp4 *.mkv *.avi *.mov *.webm`) plus "All Files",
  forwarding any selection to `app.update_global_file`.
- `display_image(pil_image)`: the registered thumbnail callback. Caches the
  raw PIL image (`self._raw_pil_image`), packs in `label`/`img_label` on
  first use (they start unpacked so the empty `DropBox` gets their screen
  space instead), unpacks the `DropBox` entirely, and calls
  `_resize_thumbnail()`.
- `_on_resize(event)` / `_resize_thumbnail()`: recomputes the thumbnail's
  displayed size to fit `top_container`'s current dimensions (minus the
  filename label's own height and some padding) while preserving the
  source image's aspect ratio (`scale = min(scale_w, scale_h)`), then
  rebuilds and reassigns the `CTkImage`. Called both on-demand
  (`display_image`) and whenever the container's layout changes
  (`<Configure>`).
- `toggle_time_spinners()`: enables/disables both `TimeSpinner`s (and greys
  their labels) based on whether "Retain Video Length" is checked.
- `select_save_location()`: opens a native save-file dialog, pre-filling a
  sensible default filename (`"{basename}_muxed.mp4"`) and starting
  directory derived from the currently-selected input file (falling back to
  `app.default_save_location`, set from the Settings tab, if no input file
  is loaded yet), or from whatever's already typed in the save-path entry
  if that's non-empty.
- `_gather_settings()`: returns a plain dict — `input_file, output_path,
  start_secs, duration_secs, retain_length` — capturing the tab's full
  current state. This is the smaller of the two settings shapes in the app
  (Encoding's has five more keys); `QueueTab`'s details popup relies on the
  *absence* of the encoding-only keys (not just falsy values) to correctly
  hide those fields for Mux tasks.
- `load_settings(settings)`: the inverse of `_gather_settings` — restores a
  previously-captured dict back into the UI (used if a queued task were
  ever re-opened for editing, though the "double-click to re-edit" feature
  this exists for was later removed from `QueueTab` — see below).
- `_validate_settings(settings)`: returns `False` (and prints a message) if
  `input_file` or `output_path` is empty; `True` otherwise.
- `mux_now()`: gathers settings, validates them, builds a description
  string (`"{filename} · Direct Mux"`), and — if the Queue tab exists —
  calls `queue_tab.add_task(..., source_tab="Muxing")` immediately followed
  by `queue_tab.start_task(task_id)`, i.e. queues *and* starts it right
  away. Falls back to printing a message if the Queue tab is somehow
  unavailable.
- `add_to_queue()`: same settings-gathering/validation, but only queues the
  task (does not start it), with a description built from the clip's
  start/duration instead (`"{filename} · {duration}s from {start}s"`).

### `tabs/encoding_tab.py`

Defines `EncodingTab` — structurally identical to `MuxingTab` (same
bottom-anchored controls / top-flexible DropBox pattern, same
`_gather_settings`/`load_settings`/`_validate_settings`/thumbnail-resize
logic, same Queue-Task-vs-do-it-now button pair), but with a larger,
two-column control area and several extra encode-specific fields.

**Layout differences from `MuxingTab`**:
- `main_options_row` splits into `left_col` and `right_col`
  (`anchor="s"` on both, so the whole block bottom-aligns against the save-
  location row beneath it, maximizing the DropBox's vertical room above).
- **Left column**: the same Retain-Length checkbox + time spinners as
  Muxing, plus — new here — a Profile/Level codec-options row:
  `profile_menu` (`CTkOptionMenu`, values `High/Main/Main 10/Baseline`) and
  `level_menu` (values `4.0/4.1/5.0/5.1`).
- **Right column**: two label-left `CTkSwitch` rows —
  "Hardware Acceleration (GPU)" (`self.switch`) and "HDRtoSDR"
  (`self.hdr_switch`) — each built with `text=""` and `width=42` so a
  separate label can sit to its *left* instead of `CTkSwitch`'s default
  label-on-the-right layout (a code comment explains `CTkSwitch`'s internal
  grid always reserves a weighted text column even with empty text, hence
  the explicit narrow width); each label is bound to toggle its switch on
  click. Beneath both switches sits a CRF ("Quality") slider
  (`crf_slider`, range 40→0 — deliberately reversed so low values read as
  low quality on the left and "Placebo" quality on the right — default 23),
  whose live value is mirrored into `crf_label`'s text via
  `_on_crf_change`.
- The action row's "do it now" button is labeled `"Encode"` (calling
  `encode_now`) instead of `"Mux"`.

**Settings shape** (`_gather_settings`): the same four Muxing keys plus
`gpu_enabled, hdr_to_sdr, crf, profile, level` — five keys unique to
Encoding. `load_settings` restores all of them, including re-running
`_on_crf_change` after setting the slider so the live readout label stays
in sync.

`encode_now()` / `add_to_queue()` mirror Muxing's `mux_now()`/
`add_to_queue()` exactly, but pass `source_tab="Encoding"` and build
descriptions with `"Direct Encode"` instead of `"Direct Mux"`.

### `tabs/queue_tab.py`

Defines `QueueTab` — by far the most complex tab, responsible for tracking,
displaying, animating, and (eventually) actually running every
encode/mux job. See the "Queue tab" and "Encoding flow" sections of
`CLAUDE.md` for the full design rationale and history of visual bugs found
and fixed here; this section summarizes what the file currently contains.

**Module-level constants**:
- `_THEME = get_active_theme()`: read once at import time, and reassigned
  by `refresh_theme()` (see below) on a live theme switch. Every row
  construction and style lookup reads this module-level name at call time
  rather than a value captured once, so a reassignment here is picked up
  everywhere without needing to touch any other code.
- `_QUEUED_STYLE` / `_GREY_STYLE`: two style dicts (`bg`, `text`,
  `remove_text`, `remove_hover`) describing how a row looks while queued
  (solid theme primary color, black text) versus running/done (grey,
  default theme text color).
- `_THUMB_SIZE = (60, 40)`: the small per-row thumbnail size.
- `_PROGRESS_STEPS = 15`, `_PROGRESS_INTERVAL_MS = 100`: the simulated
  per-task animation runs 15 ticks at 100ms each (1.5s total).
- `_DETAIL_SCROLL_HEIGHT = 140`: fixed height of the scrollable area inside
  the job-details popup.
- `_DETAIL_FIELDS`: an ordered list of `(settings_key, display_label,
  value_kind)` triples driving what the details popup shows and how
  (`None` = plain text, `"time"` = format as `HH:MM:SS`, `"bool"` = format
  as `Yes`/`No`). A key simply absent from a given task's settings dict
  (e.g. `crf` for a Mux task) is skipped, which is how Mux tasks naturally
  omit encoding-only fields.
- `_format_seconds(total_seconds)`: a small helper converting an int
  seconds count into `"HH:MM:SS"`.

**`QueueTab.__init__`**: builds, top to bottom:
1. `self.progress_bar` — an overall `CTkProgressBar` (`corner_radius=0`, to
   avoid a stray dot of color at value 0 from its rounded end-caps)
   tracking `done / total` across all current rows.
2. `self.list_frame` — a `CTkScrollableFrame` holding one row per task, plus
   `self.empty_label` ("No tasks queued yet."), shown/hidden as tasks are
   added/removed.
3. `self.detail_frame` — the job-details popup, hidden (`pack_forget`'d
   implicitly by never being packed initially) until a row is clicked.
   Contains a header row (title label + "✕" close button) and a fixed-
   height `detail_scroll` (`CTkScrollableFrame`, `fill="x"` only — no
   `expand` — so it stays at its configured height regardless of content,
   letting Encode's longer field list scroll instead of growing the popup).
4. `self.controls_frame` — bottom row with `"Clear Completed"` (the active
   theme's secondary color, left-aligned), and, packed right-to-left,
   `"Start Queue"`/`"Pause Queue"` (the active theme's primary color,
   toggles via `_set_running`) and `"Stop Queue"` (red — the one
   deliberate, theme-independent departure from the brand palette, chosen
   to read as destructive; see `core/theme.py`).
   Also binds `<Unmap>` (tab switched away from) to `_on_hide`.

**`add_task(description, settings=None, status="Queued", source_tab=
"Encoding")`**: builds one full row and returns its integer `task_id`.
Each row (a `CTkFrame`, `corner_radius=8`) contains:
- `description_label` — the task's filename/description text, `anchor="w"`,
  packed with `fill="x", expand=True` so it claims all space between the
  thumbnail and the status label.
- `progress_canvas` / `progress_text_item` — a single raw `tkinter.Canvas`
  (not a `CTkLabel`, and not a separate fill widget plus a text widget)
  whose own `bg` *is* the active theme's primary color (read once into the
  module-level `_THEME` at import time — see below), holding one
  black-on-primary copy of the description text drawn once via
  `create_text`. Growing/shrinking this one canvas's pixel width each tick
  (`_update_progress_canvas`) simultaneously grows the visible fill *and*
  clips the black text at exactly the same edge, since they're the same
  widget — see `CLAUDE.md`'s "Pixel-accurate progress-text clip" section
  for the three earlier
  approaches that were tried and rejected before landing on this (a single
  width-clipped `CTkLabel`, one individually-recolored `CTkLabel` per
  character, and a two-widget fill-plus-canvas version that needed careful
  synchronization to avoid an intermittent 1px seam) and exactly why each
  one fell short.
- `thumb_label` — a 60×40 `CTkLabel`, filled in by `_load_thumbnail` if the
  task's settings include an `input_file` (reuses
  `core.utilities.extract_video_thumbnail`).
- `status_label` — fixed-width (80px) text (`"Queued"`, `"Encoding..."`/
  `"Muxing..."`, or `"Done"`).
- `remove_btn` — a transparent "✕" `CTkButton` calling `remove_task`.

These are deliberately **constructed** in the order `description_label`,
then `progress_canvas`, then `thumb_label` — Tk's default widget stacking
order is construction order (later = higher), so this ordering alone gives
`progress_canvas` exactly the z-position it needs (above `description_
label`, so its own paint can override what's underneath; below
`thumb_label`, so the thumbnail is never covered) with no explicit
`.lift()`/`.lower()` calls. **Packing** (the actual visual left-to-right
layout: thumbnail, then description, then status, then remove button)
happens afterward and independently, in whatever order produces the
correct layout.

A single-click binding (`<Button-1>`) on `row`, `thumb_label`,
`description_label`, and `status_label` (deliberately *not* `remove_btn`)
opens the details popup via `_show_details`. The full widget set is stored
in `self._rows[task_id]` as a dict, `_apply_row_style` is called once to
set initial colors, and `_update_overall_progress` recalculates the top
progress bar.

**`_load_thumbnail(thumb_label, input_file)`**: thin wrapper around
`extract_video_thumbnail`, no-ops if there's no input file or extraction
fails.

**`_apply_row_style(task_id)`**: reads the row's current status text and
applies either `_QUEUED_STYLE` (solid theme primary color) or `_GREY_STYLE`
(grey), and
hides `progress_canvas` outright whenever the status is `"Queued"` or
`"Done"` — any other status is treated as "mid-run", and its geometry is
left alone for `_animate_progress` to own.

**`refresh_theme()`**: the counterpart to `LlamaGUI.apply_theme`'s live
theme switch — called on this tab specifically *instead of* destroying and
rebuilding it (see `core/app.py`), so `self._rows` (the task list),
`self._is_running`, and any in-flight animation survive completely
untouched. Reassigns the module-level `_THEME` to a fresh
`get_active_theme()`, updates `_QUEUED_STYLE["bg"]`/`["remove_hover"]` in
place, then explicitly `.configure()`s `progress_bar`, `clear_btn`, and
`start_all_btn` with the new colors, and for every existing row,
`.configure()`s `progress_canvas`'s `bg` and re-runs `_apply_row_style` (now
picking up the updated `_QUEUED_STYLE`). This works without any of the
CTk-default-styled-widget machinery `apply_theme` needs elsewhere, because
every one of this tab's themed elements was already explicitly colored to
begin with — there was never a CTk-default accent color here that needed a
fresh widget construction to pick up.

**`_show_details(task_id)`**: populates `detail_scroll` by destroying any
previous children and rebuilding one row per entry in `_DETAIL_FIELDS`
present in this task's settings dict (formatted per that field's `kind`),
sets the popup's title to `"Encode Details"` or `"Mux Details"` based on
`source_tab`, then packs `detail_frame` in immediately above
`controls_frame` (via `before=self.controls_frame`, so it always lands in
the same place regardless of call order).

**`update_status(task_id, status)`**: updates a row's status text, re-runs
`_apply_row_style`, and recalculates the overall progress bar. Used both by
the simulated animation and (eventually) by whatever real backend replaces
it.

**`_update_overall_progress()`**: sets `self.progress_bar` to
`done_count / total_count` across current rows (0 if there are none).

**`_on_hide()`**: bound to `<Unmap>`; resets the overall progress bar to 0
if it was showing 100% when the tab was switched away from, so returning
later (or starting a fresh batch) doesn't show a stale "done" bar.

**`remove_task(task_id)` / `clear_completed()`**: `remove_task` pops the
row from `self._rows` and destroys its frame, re-showing the empty-state
label if nothing's left. `clear_completed` calls `remove_task` for every
row currently showing `"Done"`.

**Queue playback controls**:
- `_set_running(is_running)`: flips `start_all_btn` between "Start Queue"/
  `start_queue` and "Pause Queue"/`pause_queue`.
- `start_queue()`: if a paused job exists (`self._paused_state`), resumes
  it exactly where it left off via `_animate_progress(task_id, step,
  rest)`; otherwise collects every row still `"Queued"` and starts
  processing them in order via `_process_next`.
- `pause_queue()`: cancels the pending `after()` animation job but
  preserves `self._paused_state`, so a later `start_queue()` call resumes
  from that exact tick.
- `stop_queue()`: cancels the pending animation job *and* discards
  progress — if a job was paused, its status is reverted back to
  `"Queued"`.
- `start_task(task_id)`: runs a single task immediately, independent of the
  rest of the queue (used by Encoding/Muxing's "do it now" buttons).
- `_process_next(remaining_ids)`: pops the next task id off the list,
  sets its status to `"Encoding..."`/`"Muxing..."` (based on
  `source_tab`), prints a debug line with its settings (the seam where a
  real ffmpeg call will eventually go), and kicks off
  `_animate_progress(task_id, 0, rest)`.

**`_update_progress_canvas(row, fill_width, row_height)`**: the core of the
pixel-accurate fill/text-contrast effect. If `fill_width <= 0`, hides
`progress_canvas` entirely (`place_forget`) and returns. Otherwise resizes
`progress_canvas` to exactly `fill_width` pixels wide by `row_height` tall,
repositions its text item to `description_label`'s current `(x, y)`, and
places the canvas at the row's own origin `(0, 0)`. `fill_width` is a
single number computed once by the caller (`_animate_progress`) and used
directly here for both the visible fill width and the text-clip edge —
there is no second, independently-computed width anywhere for it to
disagree with. Because a raw `tkinter.Canvas` genuinely clips whatever it
draws to its own configured dimensions (unlike `CTkLabel`, which was
confirmed by testing to silently ignore a `width` smaller than its natural
text size and always render unclipped), this reveals exactly the
black-on-primary-color portion of the text that the fill has swept under,
with a hard pixel-perfect edge that cannot drift out of sync with the
fill's own edge.

**`_animate_progress(task_id, step, rest)`**: the simulated per-task
progress loop, and the intended seam for a real ffmpeg/yt-dlp backend
later. Each tick:
1. Records `self._paused_state = (task_id, step, rest)` so pausing/resuming
   always know exactly where to pick back up.
2. Computes `fraction = step / _PROGRESS_STEPS` and a `max_fill_width`
   capped at `status_label`'s own left edge — **not** the full row width.
   This cap exists because `status_label` and `remove_btn` are
   `fg_color="transparent"`, which (per the `CLAUDE.md` gotcha on
   "transparent" not being real per-pixel transparency) is a frozen
   snapshot of the row's pre-style color; letting the fill grow underneath
   either widget used to show as a solid grey box cut into the fill, since
   their own stale background would occlude it.
3. Computes `fill_width = round(fraction * max_fill_width)` and passes it
   straight to `_update_progress_canvas`.
4. If this was the final step, calls `_finish_task`; otherwise reschedules
   itself via `self.after(_PROGRESS_INTERVAL_MS, ...)`, storing the job id
   in `self._animation_job` so pause/stop can cancel it.

**`_finish_task(task_id, rest)`**: marks the task `"Done"` (if it still
exists — it may have been removed mid-run) and immediately continues to the
next queued task via `_process_next`.

There is currently no real encoding/muxing pipeline — `_process_next` only
prints the settings dict, and `_animate_progress` purely simulates elapsed
work with a fixed-duration fill animation. Replacing that simulated loop
with a real, non-blocking (off the Tk main thread) subprocess call that
reports genuine progress, feeding it through the same `update_status`/
fill-width plumbing, is the designated integration point for actual
ffmpeg/yt-dlp support.

### `tabs/settings_tab.py`

Defines `SettingsTab` — a left-aligned settings form with a bold "Settings"
header, three option rows (each a bold `("Arial", 11, "bold")` label above
its control), and a Save button:

- **Theme** — a `CTkOptionMenu` (`theme_menu`) listing the three keys of
  `core.theme.THEMES` (`"Lemon"`, `"Cupid"`, `"Lilac"` — see
  `core/theme.py`), initialized from `load_settings()["theme"]` rather than
  a hardcoded default. Its `command` callback, `_on_theme_change`, doesn't
  apply anything itself — the actual switch only happens on Save (see
  below) — it just calls `_update_theme_swatches`, which updates two small
  fixed-size (`24×24`, `corner_radius=4`) `CTkFrame` color swatches
  (`theme_primary_swatch`/`theme_secondary_swatch`, `pack_propagate(False)`
  so their size doesn't get squeezed by the absence of content) to preview
  the selected theme's actual colors, since the dropdown text alone
  ("Cupid") doesn't convey what pink/red actually look like. A small grey
  caption label underneath says the change applies immediately once Save
  is clicked, with no restart needed.
- **Appearance Mode** — a `CTkOptionMenu` (`appearance_menu`, values
  `"System"/"Light"/"Dark"`, initialized from `load_settings()
  ["appearance_mode"]`) whose `command` callback, `_on_appearance_change`,
  calls `ctk.set_appearance_mode(value.lower())` immediately — this takes
  effect the instant it's picked, before Save is even pressed.
- **Default Save Location** — a `CTkEntry` (pre-filled from
  `self.app.default_save_location` if already set, otherwise showing the
  placeholder "No default location set...") plus a "Browse" button.
  `_browse_save_location` opens `filedialog.askdirectory()` (a folder
  picker, not a file picker — this is a starting directory, not a specific
  output file) and, if the user picks one, writes it to both the entry and
  `self.app.default_save_location` immediately (live within the session,
  same as appearance mode).
- **Save button** (`save_btn`, styled with the active theme's primary
  color) — `_on_save` persists all three settings to `settings.json` via
  `core.theme.save_settings()` (appearance mode and save location already
  took effect live in-session, but still need to be written to disk to
  survive an actual restart later). It compares the selected theme against
  `load_settings()["theme"]` (the *previous* persisted value) taken
  *before* saving: if it changed, it calls `self.app.apply_theme
  (new_theme)` (see `core/app.py`) to apply the new theme live across the
  whole app right away, then returns immediately without touching `self`
  again — `apply_theme` destroys and rebuilds this very tab as part of that
  call, among others. If the theme didn't change, it just updates
  `save_status_label` to `"Settings saved."` in place.

`app.default_save_location` is a piece of shared app state (see
`core/app.py` below) read from `core.theme.load_settings()` at startup and
read by both `MuxingTab.select_save_location` and `EncodingTab.
select_save_location` as the save dialog's starting directory whenever no
input file is loaded yet (previously both hardcoded this fallback to
`""`).

### `tabs/ytdlp_tab.py`

Defines `YtDlpTab` — also a stub, one step more built-out than
`SettingsTab`. Contains a large "YT-DLP" header label, an (unused) image
label (`img_label`), a URL entry (`CTkEntry`, placeholder "Paste Video URL
Here"), and a `"Download Video"` button that currently has no `command`
wired up at all. The call to `self.app.register_tab_ui(self.label,
self.img_label)` — which would opt this tab into the global file-selection
broadcast like every other tab — is present but commented out, meaning this
tab deliberately does *not* update when a file is selected elsewhere in the
app.

---

## Files referenced in `.gitignore` but not present in a checkout

`__pycache__/` directories and `.pyc`/`.pyo`/`.pyd` files are Python's
compiled-bytecode cache, one per source module, regenerated automatically
on every run — they carry no source of their own and aren't described
above. `.venv/`/`venv/` (virtual environment directories) are similarly
excluded and, per `CLAUDE.md`, not actually used in this project's normal
workflow (dependencies are installed into the system interpreter instead).
