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
│   ├── animated_switch.py
│   ├── dialogs.py
│   ├── drop_box.py
│   ├── dropdown.py
│   ├── sidebar.py
│   ├── thumbnail_carousel.py
│   ├── time_spinner.py
│   └── toast.py
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
| `opencv-python` | 5.0.0 | Imported as `cv2`; used only to seek and grab video frames for thumbnail/preview generation. |
| `Pillow` | 11.3.0 | Imported as `PIL`; converts OpenCV's raw frame arrays into `Image` objects and loads the sidebar logo PNG. |

Notably absent: `ffmpeg`/`yt-dlp` Python bindings — the app shells out to
neither yet (see the "No real ffmpeg pipeline yet" note under `queue_tab.py`
below). `ffmpeg` is expected to already be on the system `PATH`, per
`CLAUDE.md`.

### `LICENSE`

The [Unlicense](https://unlicense.org) — public-domain dedication. States
the software is released with no copyright restrictions and no warranty.

### `.gitignore`

Excludes Python bytecode/cache artifacts, virtual environment directories,
and the two local-only generated files from version control:

```
__pycache__/
*.pyc
*.pyo
*.pyd
.venv/
venv/
settings.json
_generated_themes/
```

`settings.json` is the per-user preference file written by the Settings tab
(see `core/theme.py` and `tabs/settings_tab.py` below); `_generated_themes/`
holds the CTk theme JSON files `core/theme.py` builds on demand. Both are
machine-local build/runtime artifacts, not shared repo state.

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
  restart once the Settings tab's Save button has written it; `__init__` then
  best-effort `os.makedirs`es it so the first save dialog opens somewhere
  real), `self.gpu_enabled` (the global hardware-acceleration preference,
  `bool()`-coerced from settings, moved off the Encoding tab onto Settings),
  `self.tab_ui_registry` (a list of per-tab
  UI hooks — see `register_tab_ui` below), the preview-thumbnail cache/queue
  state (`self._thumb_frames`, `self._thumb_frames_path`, `self._thumb_token`,
  `self._thumb_queue`, `self._thumb_pending` — see `_load_thumbnails` below),
  `self._preview_index` (the frame index both tab carousels are scrubbed to —
  see `sync_preview_index`), `self._tab_indicator_job` (an
  `after()` job id used to debounce the tab indicator's positioning — see
  below), `self._current_tab_name` (starts as `"Muxing"`, kept in sync by
  `show_tab` — this is what lets `apply_theme` re-show whichever tab was
  active before a live theme rebuild), and `self.toasts` (a `ToastManager`,
  built before the tabs so anything constructed below can post a
  notification).
- Calls `apply_ctk_theme(load_settings()["theme"])` (from `core/theme.py`)
  *before* constructing any widget below — this loads (generating on first
  use) a CTk theme JSON where every default-styled widget's accent color
  has been swapped to the active theme's secondary color, so checkboxes,
  switches, sliders, dropdowns, and the sidebar's nav buttons all pick it
  up from their very first construction.
- Constructs `self.sidebar` (a `Sidebar` instance) and grids it into column
  0.
- Constructs the active-tab indicator: `self.tab_indicator`, a flat
  (`corner_radius=0`) `CTkFrame` in the active theme's primary color, and
  `self.tab_indicator_line`, a narrower band in the secondary color that
  crosses it through the vertical middle. Both are positioned with `.place()`
  (independent of the grid), not packed or gridded. Both also pin `bg_color`
  to the primary rather than leaving it at its default: CTk floors a drawn
  shape to an even number of pixels, and any strip of raw canvas that leaves
  exposed paints `bg_color`, which defaulted to a snapshot of the dark root
  window and showed as a dark line under the pipe.
- Builds `self.tabs`, a `dict` mapping tab name → tab instance, constructing
  all five tabs eagerly at startup: `MuxingTab`, `EncodingTab`, `QueueTab`,
  `YtDlpTab`, `SettingsTab` — each is given `master=self, app=self`.
- Calls `self.show_tab("Muxing")` to display the first tab.

`register_tab_ui(self, label_widget, img_widget, on_thumbnail=None)`:
Lets a tab opt into the cross-tab file-selection broadcast (see
`update_global_file` below). `on_thumbnail` receives the whole *list* of
preview frames (`PIL.Image`s), not a single image. If the caller doesn't
supply one, a default handler is created inline that renders `frames[0]` as a
fixed 350×200 `CTkImage` on `img_widget`. The tab's `label`/`img`/
`on_thumbnail` triple is appended to `self.tab_ui_registry`.

`update_global_file(self, file_path)`: The single method that ever changes
`self.current_file_path`. Strips tkdnd's `{}` path-wrapping and surrounding
whitespace; if the result is empty, bails out. Otherwise:
1. Sets `self.current_file_path` — and, only if the path *actually* changed,
   resets `self._preview_index` to 0 (so re-broadcasting the same file during
   a theme rebuild keeps the scrub position).
2. Walks `self.tab_ui_registry`, updating each entry's label text to
   `f"Selected File:\n{self.current_file_path}"`.
3. Walks every tab in `self.tabs`, and for any tab that has a `drop_box`
   attribute, calls `tab.drop_box.hide_drop_text()` (collapsing that tab's
   drop-target hint/border now that a file is selected); for any tab
   exposing `_autofill_output_path`, calls it so the suggested output path
   updates for the newly-selected input.
4. Calls `self._load_thumbnails(path)` to resolve the preview frames
   (see below).

`_load_thumbnails(self, path)`: Resolves the ten preview frames for `path`
and broadcasts them to every registered tab's `on_thumbnail`. Bumps
`self._thumb_token` on every call (so an in-flight decode for a
since-replaced file is discarded on arrival).
- **Cache hit** — `path == self._thumb_frames_path` and `self._thumb_frames`
  already populated — broadcasts the cached list synchronously. This is why a
  live theme rebuild (which re-runs `update_global_file` via
  `load_settings`) and every plain tab switch cost nothing.
- **Miss** — increments `self._thumb_pending`, starts a daemon thread
  (`_decode_worker`) that calls `extract_video_thumbnails(path, count=10)` and
  puts `(token, path, frames)` on `self._thumb_queue`. A single self-re-arming
  main-thread poller, `_drain_thumbnails` (every 80ms while
  `_thumb_pending > 0`), delivers results via `_deliver_thumbnails`. The
  worker never touches a widget or calls `after()` — Tkinter is not
  thread-safe, so the queue is the only channel back.

`_deliver_thumbnails(self, token, path, frames)`: Drops the result if `token`
is stale or `frames` is empty; otherwise stores `self._thumb_frames` /
`self._thumb_frames_path` and calls `_broadcast_thumbnails(frames)`, which
hands the list to every `tab_ui_registry` entry's `on_thumbnail` and then
calls `sync_index(self._preview_index)` on each carousel (0 for a fresh file;
the preserved scrub index on a theme-rebuild re-broadcast, since `set_frames`
resets each freshly-built carousel to 0).

`sync_preview_index(self, index)`: a carousel was scrubbed to `index` (via its
`on_index` callback); mirrors it onto every other registered carousel with
`carousel.sync_index(index)` so the selected preview frame is shared across
tabs. `sync_index` doesn't fire `on_index` back, so this can't loop.

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
via `self.sidebar.buttons`, then sizes and places both indicator pieces (via
`.configure()` for width/height, since CTk widgets don't accept those through
`.place()`). The strip runs from the button's right edge (`button_x +
button_w`) to the tab frame's left edge (`sidebar_width + 10`, matching
`show_tab`'s padx), at the button's own height; the band is 12px tall (any
even value works — see below), same horizontal span, centered on the button.
Both are `.lift()`ed. Because the
strip is primary-on-primary against the sidebar, only the part crossing the
gutter is actually visible.

Three details are load-bearing here:
- The strip starts *at* the button's right edge rather than overlapping into
  it. The pipes are square-cornered, so any overlap would square off the
  active button's own rounded corner. At mid-height the button's rounded edge
  has reached its full bounding width, so the two still meet flush.
- The band's height must stay **even**. CTk floors a drawn shape's dimensions
  to the nearest even number, so at its original 9px it painted 8 rows and
  left the 9th showing the widget's raw canvas — a 1px dark line that read as
  a drop shadow.
- `update_idletasks()` is called **only** when the button's geometry is still
  the 1px placeholder, not unconditionally. That call synchronously
  re-lays-out and redraws the whole window; profiling measured it at ~47ms,
  28% of the cost of a tab switch, paid every switch for a geometry answer
  the 50ms defer above has already made valid.

`notify(self, message, go_to_queue=True)`: posts a notification toast through
`self.toasts`. By default clicking it jumps to the Queue tab, since every
notification so far concerns a job that landed there.

`apply_theme(self, theme_name)`: makes a theme switch actually live, no
restart, called from `SettingsTab._on_save` when the theme changed. Since
`ctk.set_default_color_theme()` (called here via `core.theme.
apply_ctk_theme`) only affects widgets constructed *after* the call, the
only way to make CTk-default-styled widgets (checkboxes, switches,
sliders, dropdowns, the sidebar's nav buttons) genuinely change color live
is to reload the theme and then reconstruct the widgets that read it:
1. `apply_ctk_theme(theme_name)` — reload CTk's default theme, then
   `self.toasts.clear()`, since live toasts are positioned against tab frames
   that are about to be destroyed and carry the outgoing palette.
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

`on_close(self)`: Bound to the OS close button. Asks
`QueueTab.pending_task_count()` how many tasks are not yet `Done`; if any
are, it **pauses the queue**, raises a Yes/No confirmation
(`components.dialogs.ask_yes_no`) saying that closing would cancel them, and
either proceeds or resumes processing and returns. Pausing matters twice
over: without it a job would keep animating (and could finish) behind a
modal dialog asking whether to cancel it, and `pause_queue` — unlike
`stop_queue` — keeps the in-flight task's progress in `_paused_state`, so
`start_queue` resumes from the exact step it left off at. Once confirmed (or
if nothing was pending) it calls `self.destroy()` then `sys.exit(0)` — a
clean full process exit rather than leaving the Python process lingering.

### `core/theme.py`

The app's central color-theming and settings-persistence module. Every
other file that used to hardcode the brand yellow (`"#FDCA3C"`) now imports
from here instead.

**`THEMES`**: a dict of seven named palettes, each a `{"primary": ...,
"secondary": ...}` pair of flat hex strings (plus an optional
`"primary_hover"` override, used only by `"Lemon"`):

- `"Lemon"` — `#FDCA3C` primary, `#3B8ED0` secondary. This is the
  original/default look; secondary is CTk's own stock button-blue,
  flattened to a single shade (CTk's own default varies it between light
  and dark mode; this app's theme colors deliberately never do).
- `"Cupid"` — `#FA6E99` primary, `#780219` secondary.
- `"Lilac"` — `#a58fd7` primary, `#3e6d04` secondary.
- `"Ranger"` — `#F98524` primary, `#104E4B` secondary.
- `"Noir"` — `#131317` primary, `#5A5B63` secondary. The near-black primary
  is why text color is adaptive rather than hardcoded (see
  `readable_text_on` below) — on this theme the label color resolves to
  white on the primary.
- `"Luck"` — `#ADBCDE` primary, `#0E5914` secondary.
- `"Vaporwave"` — `#3B41B8` primary, `#ED72D4` secondary.

**`STOP_RED` / `STOP_RED_HOVER`** (`#E5484D` / `#C93C40`): the destructive/
halting red, a permanent theme-independent exception to the primary/secondary
scheme. Used by the Stop Queue button (`queue_tab.py` aliases them as
`_STOP_RED` / `_STOP_RED_HOVER`) and the Encoding tab's Strip Video checkbox.

**`_darken(hex_color, factor=0.87)`**: returns a slightly-darker shade of a
given hex color for hover states, by scaling each RGB channel down by
`factor` and re-encoding. `0.87` was chosen to match the ratio already
implicit in the brand yellow's pre-existing, hand-picked hover
(`#FDCA3C` → `#e0b234`).

**`_relative_luminance(hex_color)`**: the WCAG 2.x relative luminance of an
`#rrggbb` color as a float in `[0, 1]` — each channel normalized to `[0,1]`,
gamma-expanded (`c/12.92` below the 0.03928 knee, `((c+0.055)/1.055)**2.4`
above it), then combined `0.2126 R + 0.7152 G + 0.0722 B`.

**`readable_text_on(hex_color)`**: returns `"black"` or `"white"` —
whichever has the higher WCAG contrast ratio against `hex_color`
(`contrast_black = (L+0.05)/0.05` vs `contrast_white = 1.05/(L+0.05)`, where
`L` is `_relative_luminance`). This is what lets any theme's primary/
secondary color carry legible text without a hand-picked per-theme text
color. Public (no leading underscore) because `queue_tab.py` also calls it
directly for the Stop Queue button's fixed red.

**`get_theme(name=None)`**: returns the *full* palette for a theme name —
`primary`, `primary_hover`, `primary_text`, `secondary`, `secondary_hover`,
`secondary_text` — filling in any missing hover color via `_darken()` and
deriving the two `*_text` entries via `readable_text_on()` (they are *not*
stored in `THEMES`, so adding a palette never needs a matching text color
picked by hand). Falls back to `DEFAULT_THEME_NAME` (`"Lemon"`) for an
unrecognized or `None` name, so callers never need to guard against a bad
theme name themselves. Current `*_text` results: black on every primary
except `Noir` (white); white on every secondary except `Lemon`'s brighter
`#3B8ED0` (black).

**`load_settings()` / `save_settings(settings)`**: read/write a small
`settings.json` file at the repo root (derived from this file's own
location via `os.path.dirname(os.path.dirname(...))`, not a bare relative
path, so it doesn't depend on the process's current working directory the
way `llama.ico`/`llama.png` do). `settings.json` is `.gitignore`d — it's a
local user preference file, not shared repository state, and is created on
first save rather than checked in. `load_settings()` returns defaults
(`{"theme": "Lemon", "appearance_mode": "System", "default_save_location":
default_output_dir(), "gpu_enabled": True}`) for any key missing from the
file, and for the file not existing or failing to parse at all
(`json.JSONDecodeError`/`OSError` are both caught silently) — so a first run,
or a hand-edited/corrupted settings file, degrades to sane defaults instead
of crashing the app at startup.

**`default_output_dir()`**: the out-of-the-box export folder,
`<user home>/Videos/LlamaMXD Export` — `default_save_location`'s fallback on
a fresh install (no `settings.json` yet). The folder itself is created lazily
by `LlamaGUI.__init__` (best-effort `os.makedirs(..., exist_ok=True)`, a
failed create just falls back to the save dialog's own default), not here.

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

A tiny, stateless helper module for pulling preview frames out of a video.

`extract_video_thumbnails(video_path, count=10)`: Opens `video_path` with
`cv2.VideoCapture` and reads `count` frames spread evenly across the video's
*interior* — sample points are the fractions `(i+1)/(count+1)` of the frame
count (i.e. 1/11, 2/11 … 10/11 for the default), deliberately avoiding a
black/blank first frame and an end-credits or fade-out last frame. For each
point it `cap.set(cv2.CAP_PROP_POS_FRAMES, target)` then `cap.read()`,
converts BGR→RGB, and wraps the frame in a `PIL.Image` via
`Image.fromarray`. Returns a list of raw, unsized images:
- 1–`count` long — shorter if the clip is too short to yield that many
  distinct frame indices (the target set is deduped) or some seeks fail;
- a single first-frame read when `CAP_PROP_FRAME_COUNT` is `<= 0` (some
  webm / streamed sources report no usable count);
- an empty list if nothing decodes at all (not a video, missing codec).

The capture handle is released in a `finally`. Callers scale each frame
themselves (see `ThumbnailCarousel`).

`extract_video_thumbnail(video_path)`: Back-compat shim — returns
`extract_video_thumbnails(video_path, count=1)[0]`, or `None` if the list is
empty. Still used by the Queue tab's per-row thumbnail.

---

## `components/` — reusable, tab-agnostic widgets

### `components/dialogs.py`

Defines the app's modal message boxes. Custom CTk widgets rather than
`tkinter.messagebox` because the native Windows dialogs ignore the app's
theme entirely, and the whole look here is theme-driven.

**Class `MessageDialog(ctk.CTkToplevel)`** —
`__init__(self, app, title, message, buttons=("OK",))` builds a fixed-size,
non-resizable toplevel holding a bold title label, a wrapped message label,
and one button per entry in `buttons`. The **first** button is treated as the
affirmative one and gets the theme's `primary`; the rest get `secondary`.
`.result` holds the label of whichever button was pressed, or `None` if the
window was closed outright.

Ordering details that matter:
- `grab_set()` raises *"window not viewable"* if called before the toplevel
  is mapped, so modality is claimed only after `deiconify()` +
  `wait_visibility()`.
- CTk re-applies its own titlebar styling roughly 200ms after construction,
  which clobbers an icon set immediately — so `_apply_icon` runs from an
  `after(250, ...)`, wrapped in a bare `except` since a missing `llama.ico`
  must never take a dialog down with it.
- `<Return>` confirms (first button); `<Escape>` and the titlebar close box
  both resolve to `None`.

`_center_on(app)` positions the dialog over the main window (horizontally
centered, one third of the way down). `show()` blocks via
`self.master.wait_window(self)` and returns `.result`.

Two module-level helpers wrap it: `show_message(app, title, message)` for a
single-OK notice, and `ask_yes_no(app, title, message)` which returns `True`
**only** on an explicit `"Yes"` — every other outcome, including Escape and
the close box, counts as No, so a dismissed confirmation can never destroy
work. Used for: no input file, no save location (both from
`_validate_settings` in Muxing/Encoding), the close confirmation in
`LlamaGUI.on_close`, and `QueueTab.clear_all`.

### `components/dropdown.py`

Defines **`ThemedDropdown(ctk.CTkOptionMenu)`**, which every dropdown in the
app uses — Theme and Appearance Mode on Settings, Encoder / Format / Profile /
Level on Encoding, and Output Format on Muxing. Don't add a bare
`CTkOptionMenu`.

It subclasses `CTkOptionMenu` for its button appearance but reassigns
`self._open_dropdown_menu = self._toggle`, redirecting the click away from
Tk's native popup to a custom panel in a borderless `Toplevel` of its own.
Two reasons the native popup can't be used:
1. It closes on almost any pointer event. This panel **stays open until an
   explicit dismissal** — a click on the button again, or anywhere outside
   the panel (`_on_global_click`, a `<Button-1>` binding added on the main
   toplevel with `add="+"` while open and removed by its funcid on close).
   Moving the pointer off it does nothing.
2. It can't report row hover. `on_hover` fires per row, which is what the
   Settings tab's theme picker needs to live-preview a palette; the native
   popup is modal on Windows and repaints nothing behind it, so a preview
   there would be invisible.

`command` is deliberately **not** passed to the base class — the native
value-picking path never runs, so `_select` calls `set(value)` and then
invokes the caller's callback itself.

`self.panel` is a bordered, rounded `CTkFrame` holding one transparent
`CTkButton` per value (exposed as `self.rows` for per-row styling), `place()`d
at `(0, 0)` inside **`self._popup`, a borderless `tk.Toplevel`**
(`overrideredirect(True)`, withdrawn until `open()`). The panel used to be `place()`d directly over the
main window, which clipped a near-bottom dropdown's lower entries at the
window edge; a separate window overflows that edge instead (`Baseline` now
hangs below the app window). Costs: the popup isn't destroyed with the owning
tab — hence the `destroy()` override, which matters on a live theme rebuild —
and it doesn't move with the main window, so `open()` also binds the main
toplevel's `<Configure>` / `<Unmap>` to `_on_root_change` (→ `close()`,
guarded on `event.widget is` the toplevel).

`open()` **always drops the popup straight down** at the button's bottom edge
(`winfo_rooty() + winfo_height() + _PANEL_GAP`, screen coords) and the
button's width — never shifted or flipped (an upward-flip-when-cramped
branch, then a stay-on-screen `y`-clamp, were both removed on request). It
also pins the popup's own `bg` to the panel's resolved fill so the CTkFrame's
rounded-corner nooks don't show a mismatched square. Encoding's
Encoder/Format/Profile/Level row (and Muxing's Output Format row) sit two
rows from the window's bottom edge, so their panels overflow it downward.

`_anim(step, opening)` **animates open/close**: the popup *unrolls* — its
window height grows ~0→full (ease-out over `_ANIM_OPEN_STEPS`) while
`self.panel` stays full-size (`place(relwidth=1.0)`, *not* pack, so the
shorter window frames **clip** it rather than compressing the rows) — with
`-alpha` fading `_ANIM_MIN_ALPHA`→1 in step. Close is the reverse over
`_ANIM_CLOSE_STEPS` (fewer), ending in `withdraw()`. One `after` job
(`self._anim_job`); `destroy()` and `_on_root_change` call `close(animate=
False)` for a synchronous hide.

### `components/animated_switch.py`

Defines **`AnimatedSwitch(ctk.CTkSwitch)`** — a switch whose knob slides
between off and on instead of snapping. CTkSwitch positions its knob straight
from the boolean `_check_state`; this keeps a parallel float `_anim_value`
(0..1), eases it toward the new state over `_STEPS` (8) ticks of
`_INTERVAL_MS` (12ms) on every `set()` — the common path for
`toggle`/`select`/`deselect`/a bound variable — and passes it to the draw
engine's `draw_rounded_slider_with_border_and_button(..., slider_value, ...)`,
which already accepts a float. Nothing about colours, the disabled look,
hover, the label or `get()` is reimplemented. `_draw` is overridden to
re-apply the fractional position after CTk's own redraws (resize, appearance
mode, colour changes) re-snap the knob to 0/1. Reaches into `_draw_engine` /
`_draw` (private CTk API), same tack as `ThemedDropdown`; customtkinter is
version-pinned. Only the Encoding tab's HDR-to-SDR toggle uses it so far.

### `components/toast.py`

Defines the drop-down notifications, reached through `LlamaGUI.notify()`.

**Class `Toast(tkinter.Toplevel)`** — a borderless notification that slides
down from above the current tab frame's top-right corner, holds ~2.2s, then
fades out and destroys itself. Clicking it runs `on_click` (in practice: jump
to the Queue tab) and dismisses it immediately.

It is a **separate window, not a frame inside the main one**, and that is
what makes its rounded corners real. Tk has no per-pixel transparency for an
in-window widget: a rounded `CTkFrame` must paint *something* in the four
corner nooks outside its shape, and any flat colour chosen is only invisible
where it happens to match — so as a child widget it showed grey corner
squares wherever a toast overlapped a queue row or a thumbnail. A Toplevel
can do better on Windows: `overrideredirect(True)` plus
`-transparentcolor _TRANSPARENT_KEY` punches every pixel of that key colour
clean out of the window. `-topmost` is also set, without which the main
window rises above the toast the moment the user clicks anything — including
the very button that posted it.

- `_draw_body(color)` paints the rounded rectangle onto a raw
  `tkinter.Canvas` — **not** a `CTkFrame`. A colour key only punches pixels
  matching it *exactly*, and CTk anti-aliases its rounded corners against
  `bg_color`; those blend pixels match neither fill nor key and survive as a
  magenta fringe. Tk's canvas primitives don't anti-alias, so the shape is
  built by hand (two overlapping rectangles forming a plus, plus a
  quarter-circle pieslice in each corner) leaving every pixel exactly the
  fill or exactly the key. The trade is slightly stair-stepped corners.
- `_label_font()` returns the family and size CTk's own labels render at.
  `ThemeManager.theme["CTkFont"]` stores a *positive* size but CTk applies it
  as a **negative** Tk size (pixels, not points), so this negates it —
  passing the positive value straight to a canvas renders noticeably larger
  than every other label in the app.
- `start(x, rest_y)` / `_slide` animate the window's screen position with an
  ease-out; `move_to`/`reposition` snap it without animating.
- `_fade(step, total, interval)` sets `-alpha` on the whole window. Real
  alpha, replacing an earlier colour-interpolation fade that had to blend
  toward an assumed backdrop (wrong for the same reason the corners were) and
  cost a full CTk redraw per step. Both layered attributes apply together.
- `retire()` cuts straight to a fast fade, skipping any remaining hold, and
  sets `is_retiring` so the toast stops claiming a stack slot immediately
  while staying visible for the length of that fade.
- `dismiss()` cancels every pending `after()` id and destroys the window; it
  is safe to call twice.

**Class `ToastManager`** — owns the live toasts for a window, keeps them from
overlapping, and bounds how much animation work can be in flight.

`show(message, on_click=None)` anchors a new toast to the current tab frame's
top-right corner in **screen** coordinates (`winfo_rootx/rooty`, since a
toast is its own window). At most `_MAX_VISIBLE` (3) toasts hold a slot; a
further arrival `retire()`s the oldest first. That cap is a performance fix,
not a cosmetic one: every toast runs its own `after()` chain, so an uncapped
stack turned button-mashing into dozens of concurrent timer chains competing
with the UI thread. Measured as event-loop latency (how late a 10ms heartbeat
actually fires) under 60 rapid notifications: **p90 79.7ms uncapped vs 6.1ms
capped**, against a 6.0ms idle baseline.

`forget()` (called by a toast as it dies) triggers `_relayout()`, which
re-seats surviving slot-holders so a dismissed toast doesn't leave a hole —
survivors *snap* rather than animating, since one more timer chain per
survivor is exactly the cost being avoided. Retiring toasts are skipped;
they stay put while they fade rather than making everything below them jump.

Because a toast is a separate window it doesn't follow the main one, so the
manager binds the app's `<Configure>` (re-anchor when the window is dragged)
and `<Unmap>` (clear on minimize — they're topmost and would otherwise be
left floating over the desktop). Both handlers check `event.widget is app`,
since a toplevel binding also receives its descendants' events. `clear()`
drops every live toast and is also called by `LlamaGUI.apply_theme`.

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

### `components/thumbnail_carousel.py`

Defines `ThumbnailCarousel(ctk.CTkFrame)` — the selected file's preview,
shown by both `MuxingTab` and `EncodingTab` in place of the old single
`img_label` + `display_image`/`_resize_thumbnail`. Shows one of up to ten
frames at a time with prev/next chevrons that fade in on hover; stepping
between frames slides.

`__init__(self, master, on_reselect=None, on_populated=None, on_index=None)`:
Wraps a single `CTkLabel` (`self.img_label`, packed `fill="both",
expand=True`). Binds its own `<Configure>` (re-fit on resize) and, on the
label, `<Enter>`/`<Leave>` (fade the arrows in/out) and **both** `<Button-1>`
and `<Double-Button-1>` to `_handle_press` — Tk delivers only
`<Double-Button-1>` for the 2nd+ press of a rapid burst, so binding just
`<Button-1>` would drop every other spam-click. `on_index` is fired with the
new frame index on every scrub (`_step`) — Muxing/Encoding pass
`app.sync_preview_index` so the other tab's carousel mirrors the frame.

`sync_index(self, index)`: the receiving end of that — jump to `index` with
no slide (`_centered_dot_start` for the dot row), never re-firing `on_index`.
No-op if already there, out of range, or not yet populated. Also used to
restore the scrub position after a live theme rebuild (`_broadcast_thumbnails`
re-applies `app._preview_index` after each `set_frames`).

`set_frames(self, frames)`: the `on_thumbnail` broadcast target. Stores the
raw PIL list, resets to index 0, and — the first time a non-empty list
arrives — fires `on_populated` (the tab uses it to swap the DropBox out for
the carousel). The first render is deferred via `after(50, ...)` because CTk
widget geometry is unreliable until the widget's first map pass.

**Two layers, kept separate.** `_base_scaled` is the *pure* fitted video
frame — nothing is ever drawn onto it. `_overlay` is a standalone RGBA layer
holding just the chevrons + dot indicators for the current index, transparent
elsewhere. `_push` composites overlay-onto-frame *at paint time*
(`Image.alpha_composite`, the overlay's alpha scaled by `_arrow_alpha` for
the hover fade). They can't be real Tk widgets — Tk has no per-pixel
transparency for an in-window widget (the same limitation behind the toast's
hand-drawn corners and the queue fill's backdrop handling), so an overlaid
`CTkButton` would be opaque with un-colour-matchable corner nooks over the
video — but keeping them as an image layer gets the same result while leaving
the frames clean and drawing the overlay once per (index, size, theme).

Internals:
- `_rescale(render=True)` — fits the current frame to the widget
  (aspect-preserving `min` scale, from the old `_resize_thumbnail`) into
  `_base_scaled` (pure RGB), and rebuilds `_overlay` for the current index.
  Runs only on a real `<Configure>`, a new frame set, or an index change.
  `render=False` (used by `_step`) skips the push to the label so a slide
  can play instead; `overlay=False` (also `_step`) additionally skips the
  ~12ms full-supersample overlay rebuild, since the slide's first tick
  rebuilds it anyway.
- `_build_overlay(w, h, dot_t=1.0, ss=_OVERLAY_SS)` / `_draw_dots()` /
  `_draw_chevron()` — the actual PIL drawing, onto a transparent RGBA layer
  (never onto a frame). **Antialiased by supersampling**: PIL's `ellipse` /
  `line` don't AA, so everything is drawn at `ss`x (`_OVERLAY_SS` 4 at rest,
  `_OVERLAY_SS_ANIM` 2 for `_slide_step`'s per-tick rebuilds) and box-filtered
  down — in **premultiplied-alpha space** (`.convert("RGBa")` around the
  `.resize()`), or LANCZOS bleeds the transparent border's black into a grey
  edge fringe.
  - The prev/next control is a **disc in the theme's `primary` colour**
    (near-solid, `alpha 230`, so it reads over a bright frame region as well
    as a dark one) with a chevron in `readable_text_on(primary)` (black or
    white). Both colours are resolved once in `__init__` — a live theme
    switch rebuilds the carousel with its tab. The chevron gets an
    **optical-centre nudge** (`_draw_chevron`, `0.13` of its half-width toward
    the point) — the two arm-ends outweigh the tip, so a geometrically centred
    V looks shifted toward its opening; the nudge doesn't touch
    `_disc_centers` or the hit-test.
  - `_disc_centers(w, h)` is the single source of truth for disc geometry —
    used by both the drawing and the click hit-test. The disc is **sized
    from each frame's own dimensions** (`min(w,h)*0.12`, capped at `w*0.16` /
    `h*0.42`) and sits **flush against the frame edge** (`margin + disc_r`
    in). A fixed fractional inset — the first implementation — clipped the
    disc on letterboxed / narrow (2.40:1) frames.
  - Navigation **clamps** at both ends: `_disc_centers` returns `None` for
    the left chevron at index 0 and the right chevron at the last index, so
    neither is drawn or clickable there.
  - `_draw_dots()` / `_dot_geometry()` / `_resolve_dot_start()` render a
    **three-size dot row that moves and resizes**. The centre `_DOT_CLUSTER`
    (3) dots are large and **screen-stationary** (cluster midpoint pinned to
    `w/2`); `_DOT_LOOK` (2) dots per side taper medium-then-small, and only
    existing frames get a dot — so the row is 7 wide in the interior
    (`s m L L L m s`), 5 at the ends (`L L L m s`, mirrored). The highlight
    **rides the cluster edge it's heading for** (right when advancing, left
    when retreating); a step only scrolls the row once the highlight is
    already at that edge, so a direction change walks the highlight back
    through the middle slot first, dots held still. `_dot_start` is the state,
    `_dot_anim = (prev_start, prev_index)` the from-state during a re-flow.
    `_slide_step` rebuilds `_overlay` each tick with the dots interpolated
    (`_draw_dots(anim, t)` — enter from `r=0`, leave to it, highlight
    cross-fades) on the picture slide's own eased clock. Dots stay
    white/translucent (theme-independent — white reads on any frame).
- `_push(base)` — puts `base` (a pure RGB frame, whole at rest or a crop
  mid-slide) on the label with `_overlay` composited on top at the current
  `_arrow_alpha`. The overlay is a *fixed* layer — it does not move when
  `base` does. Records `base` as `_displayed_base` (what the next slide
  starts *from*).
- `_update_image()` — `_push`es the resting frame `_base_scaled`.
- `_cancel_anim()` — cancels whichever of `_fade_job` / `_anim_job` is live.
  The fade and the slide share this one channel so they never both drive the
  label at once. Also settles the dot row (clears `_dot_anim`, rebuilds the
  overlay) if a slide is cut short mid-re-flow.
- `_fade_to()` / `_fade_step()` — steps `_arrow_alpha` toward a target over
  up to `_FADE_STEPS` (6) ticks of `_FADE_INTERVAL_MS` (16ms).
- `_animate_slide(direction, from_base, to_base, dot_anim=None)` /
  `_slide_step(i)` — the preview-to-preview transition. Builds a
  `[current | next]` strip of *pure* frames (order flipped for a backward
  step) and crops a window across it over `_SLIDE_STEPS` (7) ease-out ticks.
  The chevrons in `_overlay` stay put so the **image scrolls under stationary
  chevrons**; the dot row, if `dot_anim` is given, re-flows — `_slide_step`
  rebuilds `_overlay` each tick at `dot_t=eased`. `from_base` is always
  `_displayed_base`, so an interrupting `_step` (a spam-click) restarts from
  the current partial rather than snapping.
- `_event_image_xy(event)` — the event's position in image-local pixels,
  from **screen coords** (`event.x_root`/`y_root` vs `img_label.winfo_rootx()`
  + the centring offset). `CTkLabel.bind()` binds both the inner `tk.Label`
  and the inner canvas, which report `event.x`/`.y` in different origins
  (content-local vs frame-local), so a widget-relative formula is only ever
  right for one of them — screen coords are unambiguous.
- `_hit_disc_at(x, y)` — `"left"` / `"right"` / `None` for an image-local
  point, boxing it against `_disc_centers` (the whole button, not one side).
- `_in_chevron_band(x, w)` — is `x` in the left/right edge strip a disc lives
  in (drawn or not)? Clicks there never count as a frame double-click.
- `_handle_press(event, repeat)` — the single click handler for both
  `<Button-1>` (`repeat=False`, first press of a burst) and
  `<Double-Button-1>` (`repeat=True`, every press after — Tk stops sending
  `<Button-1>` once `<Double>` is bound). On a disc → `_step`, always, so a
  spam-click runs to the end. In the central area → a `repeat` press whose
  predecessor was also central calls `on_reselect`; edge-strip and single
  presses don't, so spamming a chevron past the last preview never pops the
  file dialog while a deliberate double-click on the frame still does.
- `_step(delta)` — clamps the new index, resolves the new `_dot_start`
  (`_resolve_dot_start`), `_rescale(render=False)`s it (so `_base_scaled` +
  settled `_overlay` are ready for the destination), then `_animate_slide`s
  from `_displayed_base` with `dot_anim=(prev_start, prev_index)` (falls back
  to `_update_image` if there's nothing shown yet or the sizes disagree).
  Callers only ever pass `delta` ±1; a larger jump snaps the row to the
  target edge.

### `components/sidebar.py`

Defines `Sidebar(ctk.CTkFrame)` — the persistent left-hand navigation panel.

`__init__(self, master, app)`: Builds a fixed-width (`180`), unrounded
frame colored with the active theme's primary color
(`get_active_theme()["primary"]` — see `core/theme.py`). The palette is
grabbed once as `theme` at the top so `title_label` and `footer_label` can
use `theme["primary_text"]` (the adaptive black/white label color for that
primary). From top to bottom:
1. `title_label` — bold "LlamaMXD" text in `theme["primary_text"]`.
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
   v0.5.0-alpha.2"`, in `theme["primary_text"]`) is packed first so it
   claims the literal bottom edge; `btn_settings` packs second, landing
   just above it.
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
  Start Time and Clip Duration `TimeSpinner`s side by side, an **Output
  Format** row (`format_menu`, a `ThemedDropdown` over `.mp4/.mkv/.mov/.webm`,
  default `.mp4`, `command=_on_format_change`; its `format_frame` is packed
  `pady=(6, 4)` so the spacing around it matches Encoding's equivalent row),
  a save-location
  row (`CTkEntry` + "Browse" button wired to `select_save_location`), and
  an `action_frame` with two evenly-split (`grid_columnconfigure(...,
  weight=1, uniform="action")`) buttons: `"Queue Task"` (the active theme's
  *secondary* color + `secondary_text`, `add_to_queue`) and `"Mux"` (the
  active theme's *primary* color + `primary_text`, `mux_now`) — fill, hover,
  *and* label color all read from `core.theme.get_active_theme()` at
  construction time rather than hardcoding them (see `core/theme.py`;
  `*_text` is the adaptive black/white label color for that background).
- `top_container` is packed *after*, `fill="both", expand=True`, absorbing
  all leftover vertical space. It holds a hidden-until-populated `label`
  (filename header), a `ThumbnailCarousel` (`self.carousel`, the multi-frame
  preview — see `components/thumbnail_carousel.py`), and a `DropBox`
  (height 380) that fills the container while it's the only thing packed
  there.
- Registers `label`/`carousel` with the app via `app.register_tab_ui(...,
  on_thumbnail=self.carousel.set_frames)` so the tab receives the global
  file-selection broadcast, feeding the frame list straight into the
  carousel. The carousel is constructed with `on_reselect=self.select_input_file`
  (double-click) and `on_populated=self._reveal_preview`.

**Methods**:
- `select_input_file()`: opens a native open-file dialog scoped to common
  video extensions (`*.mp4 *.mkv *.avi *.mov *.webm`) plus "All Files",
  forwarding any selection to `app.update_global_file`.
- `_reveal_preview()`: fired once by the carousel's `on_populated` when the
  first frame set arrives — packs in the filename `label` and the carousel
  (both start unpacked so the empty `DropBox` gets their screen space
  instead) and unpacks the `DropBox` entirely. This is the only part of the
  old `display_image` that stayed in the tab; the thumbnail caching and
  resize logic moved into `ThumbnailCarousel`.
- `toggle_time_spinners()`: enables/disables both `TimeSpinner`s (and greys
  their labels) based on whether "Retain Video Length" is checked.
- `select_save_location()`: opens a native save-file dialog, pre-filling a
  sensible default filename (`"{basename}_muxed{fmt}"`, where `fmt` is the
  `format_menu` value) and starting directory derived from the
  currently-selected input file (falling back to `app.default_save_location`,
  set from the Settings tab, if no input file is loaded yet), or from
  whatever's already typed in the save-path entry if that's non-empty. Its
  `defaultextension` is `fmt` too.
- `_on_format_change(value=None)`: the `format_menu`'s callback — rewrites the
  save entry's extension to the newly-picked format, but only when the path
  already has an extension to replace (before a file is picked the entry
  holds just a folder, which `_autofill_output_path` completes). Keeps
  `_auto_output` in step if the path was still auto-managed.
- `_gather_settings()`: returns a plain dict — `input_file, output_path,
  output_format, start_secs, duration_secs, retain_length` — capturing the
  tab's full current state. This is the smaller of the two settings shapes in
  the app (Encoding's has five more keys; `output_format` is shared);
  `QueueTab`'s details popup relies on the *absence* of the encoding-only keys
  (not just falsy values) to correctly hide those fields for Mux tasks.
- `load_settings(settings)`: the inverse of `_gather_settings` — restores a
  previously-captured dict back into the UI (used if a queued task were
  ever re-opened for editing, though the "double-click to re-edit" feature
  this exists for was later removed from `QueueTab` — see below).
- `_validate_settings(settings)`: returns `False` if `input_file` or
  `output_path` is empty, raising a modal `show_message` dialog (see
  `components/dialogs.py`) naming the first thing missing — "No File
  Selected" or "No Save Location". These used to be bare `print` calls, i.e.
  invisible to the user.
- `mux_now()`: gathers settings, validates them, builds a description
  string (`"{filename} · Direct Mux"`), and — if the Queue tab exists —
  calls `queue_tab.add_task(..., source_tab="Muxing")` immediately followed
  by `queue_tab.start_task(task_id)`, i.e. queues *and* starts it right
  away, then posts a "Muxing job has begun." toast via `app.notify`. Falls
  back to printing a message if the Queue tab is somehow unavailable.
- `add_to_queue()`: same settings-gathering/validation, but only queues the
  task (does not start it), with a description built from the clip's
  start/duration instead (`"{filename} · {duration}s from {start}s"`), and
  posts a "Muxing job added to queue." toast. Clicking either toast jumps to
  the Queue tab.

### `tabs/encoding_tab.py`

Defines `EncodingTab` — structurally identical to `MuxingTab` (same
bottom-anchored controls / top-flexible DropBox pattern, same
`_gather_settings`/`load_settings`/`_validate_settings` shape, same
`ThumbnailCarousel` preview and `_reveal_preview` wiring, same
Queue-Task-vs-do-it-now button pair), but with a larger, two-column control
area and several extra encode-specific fields.

**Layout differences from `MuxingTab`**:
- `main_options_row` splits into `left_col` and `right_col`
  (`anchor="s"` on both, so the whole block bottom-aligns against the save-
  location row beneath it, maximizing the DropBox's vertical room above).
- **Left column**: the same Retain-Length checkbox + time spinners as
  Muxing, plus — new here — a codec-options row of **four** `ThemedDropdown`s
  in order: `encoder_menu` (`H.264 (x264)/H.265 (x265)/MPEG-4/MPEG-2` —
  display strings only for now, `encoder` settings key), then `format_menu`
  (the shared Output-Format dropdown `.mp4/.mkv/.mov/.webm`, here labeled
  just "Format:", second because it's the one that renames the file), then
  `profile_menu` (`High/Main/Main 10/Baseline`) and `level_menu`
  (`4.0/4.1/5.0/5.1`). Widths are hand-tuned tight (122/74/92/64) so all
  four fit `left_col` without crowding `right_col`. All sit two rows from
  the window's bottom edge, so their panels drop straight down and their
  lower entries run off the window — see `components/dropdown.py`.
- **Right column**, top to bottom:
  - **`strip_video_check`** — a `CTkCheckBox` in the destructive red
    (`STOP_RED` from `core/theme.py`, the Stop Queue colour;
    `checkmark_color` picked by `readable_text_on`). Its command
    `_on_strip_video_toggle` blanket-`configure(state=...)`s every option
    control (the retain checkbox, all four dropdowns, the HDR switch, the CRF
    slider) plus the spinners, and dims their labels to one shared
    `_DISABLED_LABEL` grey. It's a plain binary disable — an already-disabled
    control (spinners under Retain Video Length) just stays put — and
    unticking hands the spinners back to `toggle_time_spinners` rather than a
    blanket "normal". `toggle_time_spinners` early-returns while Strip Video
    is on so the two don't fight.
  - a label-left "HDRtoSDR" row (`self.hdr_switch`) — an **`AnimatedSwitch`**
    (`components/animated_switch.py`; slides instead of snapping), built with
    `text=""` and `width=42` so a separate label sits to its *left* (a code
    comment explains `CTkSwitch`'s internal grid always reserves a weighted
    text column even with empty text, hence the explicit narrow width); the
    label is bound to toggle it on click. A "Hardware Acceleration (GPU)"
    switch used to sit here too but is now a global Settings preference, read
    as `self.app.gpu_enabled` in `_gather_settings`.
  - a CRF ("Quality") slider (`crf_slider`, range 40→0 — deliberately
    reversed so low values read as low quality on the left and "Placebo"
    quality on the right — default 23), whose live value is mirrored into
    `crf_label`'s text via `_on_crf_change`.
- The action row's "do it now" button is labeled `"Encode"` (calling
  `encode_now`) instead of `"Mux"`.

**Settings shape** (`_gather_settings`): the same six Muxing keys
(`input_file, output_path, output_format, start_secs, duration_secs,
retain_length`) plus `encoder, gpu_enabled, hdr_to_sdr, strip_video, crf,
profile, level` — seven keys unique to Encoding. `load_settings` restores all
of them (Strip Video applied *last*, since it re-disables everything set
above), including `format_menu` and re-running `_on_crf_change` after setting
the slider so the
live readout label stays in sync.

`encode_now()` / `add_to_queue()` mirror Muxing's `mux_now()`/
`add_to_queue()` exactly — same dialogs on invalid settings, same toasts on
success — but pass `source_tab="Encoding"`, build descriptions with
`"Direct Encode"` instead of `"Direct Mux"`, and say "Encoding job has begun."
/ "Encoding job added to queue." (Muxing says "Muxing …").

`_autofill_output_path()` (present on both tabs, called from
`LlamaGUI.update_global_file`) suggests
`"<default folder>/<input basename>_encoded<fmt>"` in the output field (`fmt`
= the `format_menu` value; Muxing uses `_muxed` for the suffix), but
only while the user hasn't set their own path — `self._auto_output` holds the
last value auto-filled, and is set to `None` once the user picks via Browse.
`_on_format_change` (also on both tabs) swaps the current path's extension
when the format dropdown changes.

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
  (solid theme primary color, with `text`/`remove_text` set to the theme's
  adaptive `primary_text`) versus running/done (grey, default theme text
  color). `refresh_theme()` rewrites the `_QUEUED_STYLE` color keys in place
  on a live theme switch.
- `_STOP_RED` / `_STOP_RED_HOVER` / `_STOP_TEXT`: the Stop Queue button's
  permanently-red fill/hover (never theme-driven), plus `_STOP_TEXT =
  readable_text_on(_STOP_RED)` — the label still picks black/white for
  contrast against that fixed red the same way themed colors do.
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
  The current fields, in order: `input_file` (Input File), `output_path`
  (Output Path), `encoder` (Encoder), `output_format` (Format),
  `start_secs`/`duration_secs` (`"time"`), `retain_length` (`"bool"`), then
  the encoding-only `strip_video`/`gpu_enabled`/`hdr_to_sdr` (`"bool"`),
  `crf`, `profile`, `level`.
- `_format_seconds(total_seconds)`: a small helper converting an int
  seconds count into `"HH:MM:SS"`.
- `_SCROLLBAR_GUTTER` (18) / `_autohide_scrollbar_in_gutter(scroll_frame)`: a
  module-level helper that makes a `CTkScrollableFrame`'s vertical scrollbar
  appear only while content overflows, *without the row area ever changing
  width*. CTk grids the bar into its own column and nothing else, so the bar
  turning on both steals ~18px from the rows and — since the canvas re-fits
  only on its next `<Configure>` — briefly draws over them before they reflow
  narrower. The helper (1) gives `scroll_frame._parent_frame`'s column 1 a
  permanent `minsize` of `_SCROLLBAR_GUTTER`, so the gutter is always
  reserved whether the bar is in it or not (the caller trims its own right
  pad `20 → 3` so the gutter comes from the window margin, not the rows); and
  (2) re-routes the canvas's `yscrollcommand` through a relay that still
  forwards every update to the real `CTkScrollbar.set` but `grid()`/
  `grid_remove()`s the bar as the content crosses the overflow line. Reaches
  for `_parent_frame` / `_scrollbar` / `_parent_canvas`. Called once in
  `__init__` on `list_frame` only — `detail_scroll` is fixed-height and
  deliberately scrolls.

**`QueueTab.__init__`**: builds, top to bottom:
1. `self.progress_bar` — an overall `CTkProgressBar` (`corner_radius=0`, to
   avoid a stray dot of color at value 0 from its rounded end-caps)
   tracking `done / total` across all current rows.
2. `self.list_frame` — a `CTkScrollableFrame` holding one row per task, plus
   `self.empty_label` ("No tasks queued yet."), shown/hidden as tasks are
   added/removed. Packed `padx=(20, 3)` (trimmed on the right) and run
   through `_autohide_scrollbar_in_gutter`, so its scrollbar only appears
   once the rows overflow — into a fixed gutter that never resizes them.
3. `self.detail_frame` — the job-details popup, hidden (`pack_forget`'d
   implicitly by never being packed initially) until a row is clicked.
   Contains a header row (title label + "✕" close button) and a fixed-
   height `detail_scroll` (`CTkScrollableFrame`, `fill="x"` only — no
   `expand` — so it stays at its configured height regardless of content,
   letting Encode's longer field list scroll instead of growing the popup).
4. `self.controls_frame` — bottom row with `"Clear Completed"` (the active
   theme's secondary color + `secondary_text` label, left-aligned), and,
   packed right-to-left, `"Start Queue"`/`"Pause Queue"` (the active theme's
   primary color + `primary_text` label, toggles via `_set_running`) and
   `"Stop Queue"` (the fixed `_STOP_RED` — the one deliberate,
   theme-independent fill departure from the brand palette, chosen to read
   as destructive; its label still goes through `readable_text_on`).
   Also binds `<Unmap>` (tab switched away from) to `_on_hide`.

**`add_task(description, settings=None, status="Queued", source_tab=
"Encoding")`**: builds one full row and returns its integer `task_id`.
Each row (a `CTkFrame`, `corner_radius=8`) contains:
- `description_label` — the task's filename/description text, `anchor="w"`,
  packed with `fill="x", expand=True` so it claims all space between the
  thumbnail and the status label.
- `base_canvas` / `base_text_item` and `progress_canvas` /
  `progress_text_item` — **two** stacked raw `tkinter.Canvas`es (not
  `CTkLabel`s) that between them render the whole description area while a
  row is running. `base_canvas` spans the entire description region painted
  in the row's grey; `progress_canvas` is the same drawing clipped to
  `fill_width` and painted in the theme's primary. Each holds its own
  `create_text` copy of the description — the base one in CTk's normal label
  color, the fill one in the theme's adaptive `primary_text`.

  Two canvases rather than one because the fill edge has to be able to cut a
  glyph in half, so the text either side of it must come from the *same*
  renderer at the *same* coordinates. An earlier version had one canvas
  painting over `description_label`, which put the seam between a
  canvas-rendered glyph half and a `CTkLabel`-rendered one — and measuring
  them against each other showed the canvas copy landing exactly **1px right
  and 1px down** of the label's (identical text width, so the font matched;
  only the origin differed). Every glyph the edge crossed visibly sheared.
  Covering the label entirely with `base_canvas` means the seam is only ever
  between two canvases, which cannot disagree. `description_label` still owns
  the row's layout and still renders the text itself while the row is
  `Queued` or `Done`, when both canvases are hidden.

  See `CLAUDE.md`'s "Per-row progress visualization" for the earlier
  approaches tried and rejected (a single width-clipped `CTkLabel`, one
  individually-recolored `CTkLabel` per character, and a two-widget
  fill-plus-canvas version with an intermittent 1px seam).
- `thumb_label` — a 60×40 `CTkLabel`, filled in by `_load_thumbnail` if the
  task's settings include an `input_file` (reuses
  `core.utilities.extract_video_thumbnail`).
- `status_label` — fixed-width (80px) text (`"Queued"`, `"Encoding..."`/
  `"Muxing..."`, or `"Done"`).
- `remove_btn` — a transparent "✕" `CTkButton` calling `remove_task`.

These are deliberately **constructed** in the order `description_label`,
`base_canvas`, `progress_canvas`, `thumb_label` — Tk's default widget
stacking order is construction order (later = higher), so this ordering alone
gives every widget the z-position it needs (both canvases above
`description_label` so they can override what's underneath; the fill above
the grey base; `thumb_label` above all of it so the thumbnail is never
covered) with no explicit `.lift()`/`.lower()` calls. **Packing** (the actual visual left-to-right
layout: thumbnail, then description, then status, then remove button)
happens afterward and independently, in whatever order produces the
correct layout.

A single-click binding (`<Button-1>`) on `row`, `thumb_label`,
`description_label`, `status_label`, `base_canvas`, and `progress_canvas`
(deliberately *not* `remove_btn`) opens the details popup via
`_show_details`. The two canvases are in the list because while a job runs
they sit on top of `description_label` and would otherwise swallow every
click landing on the description text — leaving only the thumbnail end and
the status-label-onward part of the row able to open the popup. The full
widget set is stored
in `self._rows[task_id]` as a dict, `_apply_row_style` is called once to
set initial colors, and `_update_overall_progress` recalculates the top
progress bar.

**`_load_thumbnail(thumb_label, input_file)`**: thin wrapper around
`extract_video_thumbnail`, no-ops if there's no input file or extraction
fails.

**`_apply_row_style(task_id)`**: reads the row's current status text and
applies either `_QUEUED_STYLE` (solid theme primary color) or `_GREY_STYLE`
(grey), and
hides **both** canvases outright whenever the status is `"Queued"` or
`"Done"` — which hands the description back to `description_label`'s own
rendering. Any other status is treated as "mid-run", and their geometry is
left alone for `_animate_progress` to own.

**`refresh_theme()`**: the counterpart to `LlamaGUI.apply_theme`'s live
theme switch — called on this tab specifically *instead of* destroying and
rebuilding it (see `core/app.py`), so `self._rows` (the task list),
`self._is_running`, and any in-flight animation survive completely
untouched. Reassigns the module-level `_THEME` to a fresh
`get_active_theme()`, updates `_QUEUED_STYLE`'s `bg`/`remove_hover`/`text`/
`remove_text` in place, then explicitly `.configure()`s `progress_bar`,
`clear_btn`, `clear_all_btn`, and `start_all_btn` with the new fill/hover
*and* adaptive label colors, and for every existing row, `.configure()`s both
canvases' `bg`, `.itemconfigure()`s each text item's `fill`, and re-runs
`_apply_row_style` (now picking up the updated `_QUEUED_STYLE`).
This works without any of the
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

**`remove_task(task_id)` / `clear_completed()` / `clear_all()`**:
`remove_task` pops the row from `self._rows` and destroys its frame,
re-showing the empty-state label if nothing's left. `clear_completed` calls
`remove_task` for every row currently showing `"Done"`. `clear_all` empties
the queue outright: it confirms first via `ask_yes_no` **only when something
unfinished would be thrown away** (an all-`Done` or already-empty queue
clears with no prompt), then calls `stop_queue()` *before* removing rows so
no pending animation tick can fire against a row that no longer exists. Its
button sits to the right of Clear Completed at the bottom-left.

**`is_running()` / `pending_task_count()`**: small read-only accessors used
from outside the tab. `pending_task_count` counts every row not yet `"Done"`
— in-flight *and* still queued, i.e. everything that would be lost — and is
read by both `LlamaGUI.on_close` and `clear_all` to decide whether to
confirm. `is_running` reports whether processing is active; `on_close` uses
it to know whether to resume the queue after a declined close prompt.

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

**`_flatten_color(color)` / `_grey_row_text()` / `_row_backdrop_bg(row)`**:
small colour helpers. A raw `tkinter.Canvas` can only take a single Tk
colour, never a CTk `(light, dark)` pair, so `_flatten_color` picks the half
matching the current appearance mode. `_grey_row_text` returns the label
colour a running row's text uses, so `base_canvas` reproduces
`description_label` exactly. `_row_backdrop_bg` returns the colour visible
*behind* a row — CTk already resolves this for every frame as its `bg_color`
(what it paints outside the rounded rectangle it draws in `fg_color`), so the
helper just reads it back.

That backdrop is what both canvases use as their Tk `bg`, and it matters: a
canvas is a hard rectangle sitting on the row's left end, and the only pixels
the fill shapes leave unpainted are the two ~8px corner nooks outside the
rounded left corners. Painting those the *row's* grey (as an earlier version
did) filled the row's own corner cutouts with a solid block, so a running row
read as a square grey box with a rounded fill floating inside it.

**`_paint_row_canvas(canvas, text_item, w, h, color, backdrop, text_xy)`**:
draws one canvas — a `w`×`h` block of `color` with its two **left** corners
rounded (radius `_ROW_CORNER`, echoing the row) and a square right edge, with
`text_item` raised on top at `text_xy`. The right edge stays square because
on the fill canvas it is mid-row and moving; a rounded end there reads as a
floating blob. The shape is a body rectangle plus a left edge-strip and two
quarter-circle `create_arc` pieslices — *not* one `create_polygon` with
`smooth=True`, whose spline bowed the straight top/bottom/right edges into
visible curves.

**`_paint_progress(row, fill_width, max_fill_width, row_height)`**: repaints
a running row by calling `_paint_row_canvas` twice — `base_canvas` at
`max_fill_width` in the row's grey, then `progress_canvas` at `fill_width` in
the theme's primary, both drawing their text at the *identical* local
coordinate so the fill edge can cut a glyph in half and the halves still line
up. The fill canvas stays hidden until `fill_width` reaches the corner
radius, so it never flashes a partial square corner on the way in.
`fill_width` is a single number computed once by the caller and used directly
for both the visible fill width and the text-clip edge — there is no second,
independently-computed width for it to disagree with. Because a raw
`tkinter.Canvas` genuinely clips whatever it draws to its configured
dimensions (unlike `CTkLabel`, confirmed by testing to silently ignore a
`width` smaller than its natural text size and always render unclipped), the
clip edge is hard and pixel-exact.

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
3. Computes `fill_width = round(fraction * max_fill_width)` and passes it,
   along with `max_fill_width`, straight to `_paint_progress`.
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
header, four option rows (each a bold `("Arial", 11, "bold")` label above its
control), and a Save button:

- **Theme** — a `ThemedDropdown` (`theme_menu`) listing every key of
  `core.theme.THEMES`, initialized from `load_settings()["theme"]` rather
  than a hardcoded default. Beside it sit two 26×26 `CTkFrame` colour
  swatches (`theme_primary_swatch`/`theme_secondary_swatch`, each
  `pack_propagate(False)` so their size isn't squeezed by having no content)
  and a name label, driven by `_show_theme_preview` — the dropdown text alone
  ("Cupid") doesn't convey what pink/red actually look like. That method is
  wired to the dropdown's `on_hover`, so simply *hovering* a row previews
  that palette without committing it; the panel's `<Unmap>` resets the
  preview back to the committed selection. Picking a row fires
  `_on_theme_change`, which applies the theme **live across the whole app
  immediately** — no Save needed.
- **Appearance Mode** — a `ThemedDropdown` (`appearance_menu`, values
  `"System"/"Light"/"Dark"`, initialized from
  `load_settings()["appearance_mode"]`) whose `command`,
  `_on_appearance_change`, calls `ctk.set_appearance_mode(value.lower())`
  immediately and persists.
- **Default Save Location** — a `CTkEntry` (pre-filled from
  `self.app.default_save_location` if already set, otherwise showing the
  placeholder "No default location set...") plus a "Browse" button.
  `_browse_save_location` opens `filedialog.askdirectory()` — a folder
  picker, not a file picker, since this is a starting directory rather than a
  specific output file — and writes the result to both the entry and
  `self.app.default_save_location` immediately. A hand-typed path counts too:
  the entry's `<FocusOut>` pushes it into app state via
  `_sync_state_from_widgets`.
- **Hardware Acceleration (GPU)** — a `CTkSwitch` (`gpu_switch`), moved here
  off the Encoding tab so it's a single global preference every Encode task
  inherits. `_on_gpu_toggle` updates `self.app.gpu_enabled` and persists;
  `EncodingTab._gather_settings` reads that app-level value rather than any
  control of its own.

**Persistence is automatic.** `_settings_snapshot(theme=None)` renders the
current state of every control as a `settings.json`-shaped dict;
`_sync_state_from_widgets` pushes the entry/switch values into shared app
state so a live theme rebuild (which reconstructs this tab) doesn't lose
them; and `_autosave` — bound to `<Unmap>`, so it fires on tab switch and on
minimize — writes the lot to disk. `on_leave` (called by `LlamaGUI.show_tab`
just before this tab is switched away from) closes both dropdown panels and
then runs the same autosave, giving the tab-switch case a deterministic flush
rather than relying on event ordering.

The **Save button** (`save_btn`, styled with the active theme's primary
colour + adaptive `primary_text` label) is therefore largely redundant, kept
for reassurance: `_on_save` syncs and persists, then posts a "Settings
saved." toast via `self.app.notify(..., go_to_queue=False)` (this replaced an
inline `save_status_label` under the button — that widget no longer exists).
It only falls back to `self.app.apply_theme(...)` if the theme somehow hadn't
already live-applied — in which case it returns immediately without touching
`self` again (and posts no toast: `apply_theme` destroys and rebuilds this
very tab, and clears live toasts on the way).

`app.default_save_location` is shared app state (see `core/app.py`) read from
`core.theme.load_settings()` at startup, and used by both
`MuxingTab.select_save_location` and `EncodingTab.select_save_location` as
the save dialog's starting directory whenever no input file is loaded yet.

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

`settings.json` (repo root) is the per-user preference file — written
automatically whenever the Settings tab is left or a control changed, holding
`theme`, `appearance_mode`, `default_save_location`, and `gpu_enabled`. Read
via `core.theme.load_settings()`, written via `save_settings()`; a missing or
corrupt file falls back to defaults (`Lemon` / `System` /
`default_output_dir()` / `True`), so a fresh checkout with no file behaves
normally.

`_generated_themes/` (repo root) holds one `<theme>.json` per palette,
generated by `core.theme._ctk_theme_path()` — customtkinter's bundled
`blue.json` with every accent color swapped for that theme's secondary. They
are regenerated (unconditionally, it's cheap) whenever a theme is applied,
so deleting the directory is harmless.
