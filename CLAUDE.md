# LlamaMXD (LlamaPY GUI)

A Windows desktop GUI for video muxing/encoding/downloading, built with
PySide6 (Qt 6). Wraps ffmpeg and yt-dlp behind a tabbed interface. Repo:
`https://github.com/YezanSmadi/LlamaMXD`. Public domain (Unlicense). Currently
v0.5.0-beta.1 (the sidebar footer — `VERSION` in `ui/widgets/panels.py`).

## Running

```bash
python main.py
```

Launch-directory independent: every asset (`assets/`), `settings.json` and
`presets.json` are resolved `__file__`-anchored.

Environment: Python 3.13, system interpreter (no venv). Dependencies are pinned
in `requirements.txt` (`pip install -r requirements.txt`) but still installed
globally in practice: `PySide6` 6.11.2 (the UI), `opencv-python` (cv2) 5.0
(preview frame decode), `Pillow` 11.3, `rlottie-python` 1.3.8 (the Wave Loop
visualiser — a missing/broken import degrades to a flat gradient wash, never
a crash), `ffmpeg-python` 0.2.0 (+ its `future` dependency — builds the ffmpeg
commands), `yt-dlp[default]` 2026.08.19 (the Downloader's dev environment;
`default` pulls in `yt-dlp-ejs`, the YouTube JS challenge solver — the app
itself runs the bundled `yt-dlp.exe`, not this package). No `deno` extra: pip
puts `deno.exe` in the *user* Scripts folder, which yt-dlp's own lookup
doesn't search. Roboto (the app typeface) is bundled in `assets/fonts` and
registered by `main.py`.

**External tools are bundled, not pip-installed**: `ffmpeg.exe`, `ffprobe.exe`,
`ffplay.exe` (unused so far, kept for later), `yt-dlp.exe` and `deno.exe` live
in `dependables/` at the repo root — **gitignored**, each is far over GitHub's
100MB file limit — and the release's setup wizard copies them beside the app.
Every launch goes through `core/tools.py` (see "External tools" below), so
nothing needs to be on PATH; PATH is only the last fallback.

## Architecture

```
main.py                   QApplication (Fusion style), bundled fonts, theme, MainWindow
core/formats.py           container/codec compatibility + the option cascade (pure data)
core/gpu.py               GPU vendor detection + hardware-encoder selection (NVENC/QSV/AMF)
core/system_info.py       CPU/RAM/disk facts for the Settings tab's system-info block
core/presets.py           named codec/quality recipes, persisted to presets.json
core/theme.py             brand palettes, contrast helpers, settings.json read/write
core/utilities.py         ffprobe media probe + duration, capability checks, preview frame decode
core/ffmpeg_vars.py       one queued job's settings flattened into module globals (raw + *_ARG)
core/ffmpeg_build.py      builds a Mux or Encode job's ffmpeg-python Stream / full argv
core/ffmpeg_runner.py     runs one ffmpeg job off the GUI thread (progress, suspend/resume, stop)
core/tools.py             resolves ffmpeg/ffprobe/yt-dlp/deno to absolute paths (bundled, then PATH)
core/downloader.py        Downloader logic: fetch (-J), format model + option lists, resolve, argv
core/ytdlp_runner.py      runs one download off the GUI thread (job object, stages, time progress)
ui/app.py                 MainWindow — the hub: shared state, file-selection broadcast, background
                          work, tab routing, keybinds, toasts, close prompt
ui/theme.py               ThemeManager (live theme + System/Light/Dark) + the generated stylesheet
ui/workers.py             run_async: daemon thread → result delivered on the GUI thread; pil_to_qimage
ui/widgets/controls.py    Dropdown, CheckBox, Switch, SegmentedButton, TimeSpinner, MarqueeLabel,
                          IconButton + helpers (button, labeled, set_enabled, draw_cross)
ui/widgets/panels.py      SubTabBar, DropBox, BorderedFrame, SummaryPanel, Sidebar, TabIndicator
ui/widgets/tracklist.py   TrackListBox — Muxing's checkable, scrollable track picker
ui/widgets/carousel.py    ThumbnailCarousel + WaveLayer + the info tooltip
ui/widgets/dialogs.py     MessageDialog, show_message / ask_yes_no / ask_text,
                          confirm_output_path, AudioStreamPickerDialog, ExternalStreamPickerDialog
ui/widgets/toast.py       Toast / ToastManager
ui/tabs/media_tab.py      MediaTab — the frame Muxing and Encoding share
ui/tabs/muxing.py, encoding.py, downloader.py, queue.py, settings.py
```

`core/` has no UI code at all — nothing in it imports Qt.

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

### The window is the hub (`ui/app.py`)

`MainWindow` owns the shared state every tab reads through `self.app`:

- `current_file_path` — the single globally-selected input file.
- `default_save_location`, `gpu_enabled` — from `settings.json`; the save
  folder is created at startup (best-effort).
- `downloader_separate_save`, `downloader_save_location` — also from
  `settings.json`; the Downloader's own optional save folder, off by
  default. `downloader_default_location()` is what `DownloaderTab` actually
  autofills into — see "Tabs → Settings" below.
- `media_info` — the ffprobe result for the selected file (below).
- `thumb_frames` / `thumb_frames_path` — its ten preview frames (QImages).
- `hdr_frames` / `hdr_frames_path` — the tone-mapped preview set, if rendered.
- `ytdlp_cache` (`{"url", "info", "thumb"}`), `deno_missing`.
- `tabs` — name → tab (`Muxing`, `Encoding`, `Downloader`, `Queue`,
  `Settings`), all built once at startup and stacked in a `QStackedWidget`.
  `Queue` is constructed first since the others hand jobs to it.
- `media_tabs` — Muxing and Encoding, registered by `MediaTab.__init__`
  (`register_media_tab`) as the targets of the file-selection broadcast.

**Window**: fixed at 35% x 37.5% of the screen, centred. Sidebar (200px) on the
left; the tab frame (`#TabFrame`, rounded, 10px margin) holds the stack.

**Tab switching** is `show_tab(name)`: calls the outgoing tab's `on_leave`
if it has one (Settings autosaves; Queue resets a completed 100% bar),
`setCurrentWidget`s the new one, glides the `TabIndicator` to the button,
and takes focus back to the window unless a line edit has it. A switch plus a
full repaint measures ~1ms. The first alignment runs from `showEvent` via a
zero-delay timer, once geometry is final.

**Background work** goes through `ui.workers.run_async(fn, on_done)`: a daemon
thread runs `fn`, and a queued signal calls `on_done(result)` on the GUI
thread. Worker functions never touch a widget; images cross threads as
`QImage` (`pil_to_qimage`), never `QPixmap`. An exception in a worker is
printed and delivered as `None`.

**Closing** (`closeEvent`): with unfinished jobs, the queue is *paused* (not
stopped) for the confirmation so backing out resumes it exactly where it was;
on confirm, Settings autosaves and `QueueTab.shutdown()` kills the active job
(Windows doesn't take a child process down with its parent). `_closing` is set
before accepting because `QApplication.quit()` re-sends a close event, which
would otherwise prompt a second time.

### File selection is a broadcast, not a per-tab event

Any DropBox (drop, double-click or Browse), the carousel (drop or a
double-click reselect), or the file label's double-click calls
`app.update_global_file(path)` — the *only* place the selected file changes.
It resets the shared scrub index and `media_info` when the path actually
changed — also calling `carousel.clear_preview()` on every media tab at that
point, so the *outgoing* file's frames are dropped immediately rather than
sitting on screen until the newly-picked file's own frames finish decoding
(`_load_thumbnails`, below, only rebroadcasts synchronously on a cache hit;
a genuine decode takes a worker round-trip, during which the preview would
otherwise still show the previous file) — then for each media tab:
`set_selected_file` (the marquee label, and the DropBox collapses to just
its Browse button) and `_autofill_output_path`, then `_load_thumbnails(path)`.

**`_autofill_output_path`: the FILENAME always re-derives from the file just
picked; only the DIRECTORY persists** — whatever folder is currently in the
save field (the default save location at first, or wherever the user last
Browsed). A stale filename from the previous input is never worth keeping. A
bare directory (fresh from Settings) is told apart from a full path by
whether it has an extension, since `os.path.dirname()` on a bare directory
would strip its last real folder.

**Frames and probe, off the GUI thread, cached.** `_load_thumbnails`:
- **Cache hit** (same path already probed / decoded) → broadcast immediately.
- **Miss** → bumps `_thumb_token`; one worker runs `probe_media` first and
  delivers it early through `emit_progress` (the ~50ms probe settles the
  tabs' defaults long before the frame seeks finish), then
  `extract_video_thumbnails(path, count=10)` — ten frames at the video's
  *interior* (fractions 1/11 … 10/11, skipping a black first / end-credits
  last frame). A result whose token is stale (the user picked another file
  mid-decode) is dropped.

`_broadcast_media_info` calls each media tab's `on_media_info` and its
carousel's `set_media_info`; `_broadcast_thumbnails` hands frames to each
tab's `on_thumbnails` (Encoding wraps it for the HDR preview) and re-applies
the shared scrub index.

**A file that probes to neither video nor audio at all is rejected, not
broadcast as an empty file.** `_deliver_media_info` treats
`has_video in (None, False) and has_audio in (None, False)` as the
signature of ffmpeg's demuxer failing outright (a corrupt file, or a
container variant this build's demuxer doesn't parse — some vendors' MXF
headers, confirmed) rather than a legitimate audio-only or video-only
input (which always has the *other* kind `True`), and routes it to
`_reject_file` before it ever reaches a tab: the selection is undone
entirely — `current_file_path`, `media_info`, both thumbnail caches, and
every media tab's carousel/DropBox (`MediaTab.clear_selected_file`,
`DropBox.reset`) go back to their pristine pre-import state, any in-flight
HDR render for it is cancelled, and a "Couldn't Read This File" dialog
explains why — rather than a tab silently showing zeroed-out fields for a
file that was never actually usable.

**The scrub position is shared.** A carousel's `indexChanged` →
`app.sync_preview_index(i)` → every carousel's `sync_index(i)` (an instant
jump that never re-emits, so it can't loop). The index resets only when the
input file actually changes.

**What the probe gives the tabs** (`core.utilities.probe_media`, best-effort
ffprobe; every field may be None and every failure returns Nones rather than
raising — it only ever *improves* defaults): container, video/audio codec,
video profile/level, width/height, HDR, duration, file size, per-stream video
and audio (`video_streams`/`audio_streams`), HDR static metadata, and
`has_video`/`has_audio`. It lets Encoding auto-resolve Encoder, Profile,
Level and every per-stream audio control, lets Muxing populate its track
boxes (`ui/tabs/muxing.py`), lets both tabs default the output container to
the source's, and lets Muxing work out which containers the file can be
remuxed into.

Video Level needed a **codec-aware** conversion, not one formula: ffprobe's
raw `level` is ten times the display value for H.264 (`40` → "4.0"), *thirty*
times for HEVC (confirmed empirically — raw `120` is "4.0", not "12.0"), a
`seq_level_idx` table lookup for AV1 (confirmed: a 720p30 clip's raw `5` is
"3.1"), and a named-level code for MPEG-2 (mirrors
`ffmpeg_vars._LEVEL_ARGS["MPEG-2"]` in reverse) — see
`core.utilities._ffprobe_level`. Audio Channels/Sample Rate match a probed
value exactly against `formats.channels_display_for` /
`sample_rate_display_for` (a 7.1 or 22050 Hz source has no option to land on);
Bitrate *snaps to the closest* `formats.AUDIO_BITRATES` entry
(`bitrate_display_for`), since a real source's bitrate essentially never lands
on a round number. `AUDIO_BITRATES` entries are display text (`"96 kbps"` …
`"768 kbps"`, then `"1 Mbps"`/`"1.5 Mbps"` — 1024/1536 are exact multiples of
1024 so the division lands clean); `bitrate_arg_for(display)` turns one back
into the `"<n>k"` ffmpeg wants.

`has_video`/`has_audio` answer "does a stream of that kind exist at all",
independent of whether its codec was recognised: `False` only once a probe
genuinely ran and found none; `None` (unknown) must never read as absent.

**Audio-only inputs.** `extract_video_thumbnails` returns `[]` for an audio
file. `_is_audio_only(path)` (the probe says audio-but-no-video, or with no
probe the extension is in `formats.AUDIO_EXTENSIONS`) triggers
`set_audio_only(True)` on every carousel — from both the probe delivery and
the empty frame delivery — which reveals the carousel and shows the Wave Loop
visualiser with navigation disabled. Real frames arriving clear it again.

**HDR→SDR preview renders** (`start_hdr_render`, `_deliver_hdr`): one
tone-mapped render per file (`extract_hdr_tonemapped_thumbnails`), cached on
the app and token-guarded; a no-op when already cached or already running for
that path. Delivered to any tab with `on_hdr_frames_ready`. **A render in
flight is interrupted the instant the file changes**, not left to finish for
a file nobody's looking at any more: `update_global_file` calls
`_cancel_hdr_render` (a `threading.Event` passed into
`extract_hdr_tonemapped_thumbnails` as `should_cancel`, checked between
per-frame ffmpeg calls) and every media tab's `reset_hdr_preview` (turns its
HDR→SDR switch back off without the raw/tone-mapped frame swap flashing,
since the carousel's about to be cleared for the new file anyway) — the
outgoing file's render never silently finishes into a cache entry nobody
asked for any more, and the new file never inherits a switch state or a
preview that was never actually about it.

**Downloader fetches** (`fetch_ytdlp_info`): `downloader.fetch_info` +
`download_thumbnail` on a worker, token-guarded so a superseded fetch is
dropped; a success is cached in `ytdlp_cache`. The Deno check
(`downloader.deno_path`) runs on a worker at startup.

### Keybinds

An application-level event filter (`_Keybinds`) so they work wherever focus
is — unless a modal is open, or focus is on something the key already means
something for:

- **Left / Right** → steps the current tab's carousel (`carousel.step`,
  which doesn't light the chevrons). Ignored while a line edit or the
  TimeSpinner field has focus (they own the arrow keys).
- **Space** → `QueueTab.toggle_queue()` (start / pause), on the Queue tab
  only, ignored for auto-repeat and when focus is on a line edit, the time
  field, a button or a combo box.
- **Escape** → collapses whichever media tab's carousel is currently
  expanded (the preview's expand/shrink icon — see `ThumbnailCarousel` in
  Widgets below), if any. Ignored while a line edit or the TimeSpinner field
  has focus, same as Left/Right.

Clickables are `Qt.NoFocus` (see Conventions), so clicking a sidebar button
never swallows the Space bind. Add new binds here rather than on tabs.

**The same filter also clears a text field's focus on a click elsewhere.**
Every clickable being `Qt.NoFocus` has a side effect Qt's own default click
handling doesn't cover: clicking a widget that never takes focus simply
leaves focus wherever it already was, so a line edit (the save-path field,
a preset-name entry, ...) stayed visibly and functionally focused — cursor
still blinking, still first in line for Ctrl+A/paste — long after a click
had landed on a button or empty space elsewhere in the window. `_Keybinds`
now also filters `QEvent.MouseButtonPress`: if the currently focused widget
is a `QLineEdit` or a `_TimeField` (TimeSpinner's own field) and the click
landed on some *other* object, that field's focus is cleared right there,
before the click is delivered to its real target — clicking a genuinely
focusable widget (another line edit, a `_TimeField`) still works exactly as
Qt's own default already handled it, since `setFocus()` on the new widget
clears the old one anyway.

### Theming (`core/theme.py` + `ui/theme.py`)

**`core/theme.py` is the source of truth for brand colour.** `THEMES` holds
seven palettes — `Lemon` (`#FDCA3C` primary / `#3B8ED0` secondary, the
original look), `Cupid` (`#FA6E99` / `#780219`), `Lilac` (`#a58fd7` /
`#3e6d04`), `Ranger` (`#F98524` / `#104E4B`), `Noir` (`#131317` / `#5A5B63`),
`Luck` (`#ADBCDE` / `#0E5914`), `Vaporwave` (`#3B41B8` / `#ED72D4`). Every
colour is a **flat hex string, not a (light, dark) pair** — appearance mode
never changes a theme's colours. Hover shades are auto-derived by `_darken()`
(~0.87 brightness) except Lemon's primary hover, kept at its historical
`#e0b234`.

`get_theme(name)` returns the palette plus derived text colours:
- `primary_text` / `secondary_text` — `readable_text_on()`: black or white,
  whichever has the higher WCAG contrast against that fill (Noir's near-black
  primary gets white; Lemon's `#3B8ED0` secondary gets black).
- `primary_disabled_text` / `secondary_disabled_text` —
  `disabled_text_on()`: a grey solved to hit 3:1 contrast against *that*
  fill, on the side `readable_text_on` would pick. A disabled button or
  dropdown keeps its accent fill, and a fixed grey nearly vanished on
  mid-brightness accents (~1.1:1 on Lemon/Vaporwave). 4.5:1 was tried first
  and read as enabled text, not disabled.

`STOP_RED` (`#E5484D`, hover `#C93C40`) is the destructive/halting red — Stop
Queue, the Strip checkboxes, a removed stream's rundown text and red sub-tab,
a failed queue row. It **never** changes with the theme.

**`ui/theme.py` makes a switch live, with no rebuild.** `ThemeManager` (one
instance, `ui.theme.theme`, created by `init_theme()` after the
QApplication) holds `name` and `mode` (`System` / `Light` / `Dark`), merges
the brand palette with `_NEUTRALS[resolved_mode()]` (window, frame, entry,
track, menu, row, disabled, tooltip, warning…) plus the `stop*` and
`*_pressed` shades, and emits `changed` on `set_theme` / `set_mode`, and on an
OS colour-scheme change while in System mode. Read colours with
`T.theme.color(key)` (QColor) or `T.theme.hex(key)`.

On `changed`, `MainWindow._restyle` re-applies `ui.theme.stylesheet()`
(~140ms, almost all stylesheet re-polish) and every custom-painted widget
repaints from `T.theme` — each connects `T.theme.changed` to its own
`update()`. Nothing is destroyed, so no form state is lost, and Settings can
preview a theme across the whole window on hover.

`_rebuild_colors` also drives the native title bar through
`QStyleHints.setColorScheme` (Qt 6.8+). **System mode must call
`unsetColorScheme()` *before* resolving the mode** — after an explicit
Light/Dark, `colorScheme()` would otherwise read back the app's own override
rather than the OS setting. A `_rebuilding` guard stops the resulting
`colorSchemeChanged` from re-entering.

**The stylesheet styles stock widgets only**, keyed by a dynamic `role`
property:
- `QPushButton` — secondary by default; `role` = `primary`, `danger`
  (STOP_RED), `ghost` (transparent), `stepper` (the TimeSpinner arrows).
  After changing a role at runtime call `controls.restyle(widget)`.
- `QLabel` — `field` / `field11` (bold Arial captions, 26px min-height, which
  gives the airy label-above-control rhythm), `muted`, `meta`, `hint`,
  `title`, `dialogTitle`, `detailTitle`, `detailKey`, `error`, `empty`,
  `warn`, `sidebarTitle`, `sidebarFooter`. `QLabel:disabled` dims captions.
- `QLineEdit`, `QSlider` (incl. disabled handle/fill), `QScrollBar`, and the
  combo popup (`QComboBox { combobox-popup: 0 }` so the list drops below the
  button instead of over it; the private container transparent; rounded
  view; 28px rows).

Everything with custom geometry (dropdown button, checkbox, switch, segmented
button, time field, sub-tab bar, drop box, sidebar, tab pipe, carousel, queue
rows, toasts) paints itself.

**Persistence.** `settings.json` (repo root, gitignored): `theme`,
`appearance_mode`, `default_save_location`, `gpu_enabled`,
`downloader_separate_save`, `downloader_save_location`; missing keys or a
missing/corrupt file fall back to `Lemon` / `System` / `~/Videos/LlamaMXD
Export` / `True` / `False` / `""`. The last two back Settings' "Separate
Save for Downloader" — see "Tabs → Settings" below. **Presets**
(`core/presets.py`) live in a gitignored
`presets.json`, shaped `{tab: {name: settings}}`. A preset is a **recipe, not
a job**: `PRESET_KEYS` limits it to the container and codec/quality choices
and excludes the trim, the paths and track picks, so loading one can never
re-trim a clip or repoint its output. Every read is best-effort.

### Option compatibility (`core/formats.py`)

Pure data + lookups, no UI code. **The option tree has exactly one root: the
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
disables rather than showing a meaningless number under their name
(`EncodingTab._sync_controls` distinguishes this "genuinely no such knob" case
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
`EncodingTab._validate_specific` while left that way with the stream actually present —
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

**`RESOLUTIONS`/`resolutions_for`/`resolution_height_for`** are Encoding
Video's optional downscale, parallel in spirit to the codec/profile/level
cascades above but keyed off the *source's probed height* rather than the
container or encoder: `SOURCE_RESOLUTION` (`"Source"`) plus a fixed ladder
(`"2160p"` … `"360p"`, each mapped to a target pixel height in
`_RESOLUTION_HEIGHTS`). `resolutions_for(source_height)` caps the offered
list to `SOURCE_RESOLUTION` plus every rung **at or below** the source's own
height — never an upscale — and falls back to the full ladder when the
height isn't known yet (nothing to cap against). `resolution_height_for`
is the reverse lookup `ffmpeg_vars._scale_vf` (below) uses to build the
actual `-vf scale=-2:<height>` argument; `-2` for the width is what lets
ffmpeg compute it from the source's own aspect ratio rather than this
module trying to precompute both dimensions.

### Tabs

#### Muxing and Encoding (`ui/tabs/media_tab.py`)

**The two tabs are not variations on each other — Muxing never re-encodes.**
Muxing is container change + stream selection, everything `-c copy`, with no
codec controls at all. "Copy video, re-encode audio" is an *Encoding* job with
the encoder auto-resolved to the source's own codec. Encoding is the superset.

They share one frame, `MediaTab`, top to bottom:
- **Header**: a `SubTabBar` (Overview / Video / Audio) and the `Selected
  File:` `MarqueeLabel` (double-click to reselect).
- **Preview**: a `QStackedLayout` holding the `DropBox` until the carousel's
  `populated` signal, then the `ThumbnailCarousel`. It takes all leftover
  height.
- **Sub-tab panels**: a `QStackedWidget`, which sizes itself to its tallest
  page — so switching sub-tabs never changes the preview's height, and a
  switch is one frame. Every field is read regardless of which page is
  showing.

  **INVARIANT — the DropBox/preview must always render at the identical
  size and proportion in Muxing and Encoding. This is load-bearing, not
  cosmetic, and every future change to either tab's Video/Audio panel must
  preserve it.** The two tabs run in an identically-sized window and the
  same sizing rule (below) governs both, so under that rule the preview
  naturally comes out the same size in both — *unless* one tab's own
  Video/Audio panel is allowed to grow taller than the other's, which
  silently and specifically shrinks *that tab's own* preview relative to
  the other's (see the sizing rule below for the mechanism). Adding a
  control to Muxing's or Encoding's Video/Audio panel always requires
  re-checking this — see the sizing rule and its two concrete
  worked examples (`TrackListBox`'s fixed height on Muxing, the
  Resolution/Strip Video row on Encoding) below.
- **Save row** (entry + Browse) and the **actions** (`Queue Task` secondary,
  `Mux` / `Encode` primary — queue *and* start).

Subclasses set `TAB`, `ACTION_TEXT`, `OUTPUT_SUFFIX` (`_muxed` / `_encoded`),
`VERB_ING`, `DIRECT_LABEL`, `PRESET_NOTE`, and implement `build_video`,
`build_audio`, `_sync_controls`, `_refresh_summary`, `on_media_info`,
`_gather_settings`, `_apply_settings` and (Encoding) `_validate_specific`.
`_init_state()` runs right after `QWidget.__init__` for per-instance state the
panels need before they're built. `stream_page()` returns an empty
`(page, left, right)` panel.

**Overview** (shared): `Output Format` + the preset row (`Preset` + `Save` +
`Delete`) on one line; the **single global trim** (`Start Time` / `Clip
Duration` TimeSpinners + an `A/V Sync` checkbox) below; the export rundown
(`SummaryPanel`: `Video` / `Audio` / `Length`) on the right. `Duration
00:00:00` means "to the end of the file" — there is no separate "retain
length" switch. The spinners refresh just the rundown as the user types. The
container isn't listed in the rundown; the Output Format dropdown beside it
already says it. Output Format lives here because it's **the root of the
whole option tree** (see `core/formats.py`), reachable from either stream
panel. Picking one (`_on_format_change`) stops auto-adopting the source's
container and swaps the save path's extension.

**Presets** (`_on_preset_selected` / `_on_preset_save` / `_on_preset_delete`): save asks for a
name (`ask_text`), refuses the reserved `NONE_LABEL`, confirms an overwrite;
applying one writes it through `_apply_settings` and toasts.

**Validation** (`_validate_settings`): no input file; no save location; the
tab's own checks; then `confirm_output_path` (a folder or the input itself is
refused; an existing path, or one an unfinished job already claims —
`QueueTab.claims_output` — asks first, and No means the job isn't queued).
Asking at queue time is what lets the queue run without ever prompting.

**Queue hand-off**: `add_to_queue` toasts "… job added to queue."; `run_now`
also calls `start_task`, whose result (`started` / `next` / `paused`) picks
the toast. The Queue/Go buttons are never disabled — validation happens on
click.

**Muxing / Video** and **Muxing / Audio**: a `TrackListBox`
(`ui/widgets/tracklist.py`) — a scrollable box bordered in the theme's
*secondary* colour (blue on Lemon), deliberately distinct from DropBox's own
primary border — with one checkbox per stream the source actually has,
every checked one mapped into the output. This replaced the original single
`Auto`/`Track N` dropdown: Muxing now mixes and matches any combination of a
file's own tracks, not just one at a time. The box carries no caption of its
own (the sub-tab's own "Video"/"Audio" label already says what it's a box
of) and **fills the row**, stopping only where a narrow column sits to its
right: `Add Stream(s)` on top, then `Remove Stream(s)` (`role="danger"`,
STOP_RED) sharing a line with the Strip checkbox below it — both buttons
share one width (`button_width_for`) so the stack lines up flush. Keeping
this column no taller than the box (rather than, say, one tall stack of
three rows) is what lets the *box's own* height stay the one thing driving
the panel's total height — see the panel-height paragraph below.

`Add Stream(s)` browses a second file, probes it off the GUI thread
(`core.utilities.probe_media` via `run_async` — never on the GUI thread,
same rule as everywhere else), and either adds its lone matching-kind stream
straight away or — when it has more than one — opens
`ExternalStreamPickerDialog` (`ui/widgets/dialogs.py`) to choose which. Each
added stream becomes its own row tagged `External: <name> — Track N · codec
· ...`, kept in `MuxingTab._video_external` / `_audio_external`
(`{row_id: {"file", "index", "label"}}`) — independent of the primary input,
so switching the primary file later doesn't clear them. **`Remove Stream(s)`
acts on every currently-checked row** — there's no per-row ✕ any more;
checking a row still means "include it" as always, and pressing this button
re-reads that same checked state as "actually, get rid of these": a row
living in `_video_external`/`_audio_external` is dropped from the box
outright, while a source row — the file's own track, which can't actually be
deleted — is simply unchecked instead (`TrackListBox.set_checked`, the
programmatic counterpart of clicking its own checkbox off). Either kind
ends up excluded from the output either way; the difference is only whether
the row itself survives. Pressing it with *nothing* checked at all shows a
message rather than silently doing nothing. The red Strip checkbox
still sits beside `Remove Stream(s)` and still means "drop this stream kind
entirely" — kept as an explicit, separate control rather than being inferred
from "the box happens to have nothing checked" (see the box's own "no
streams selected" rundown state below for that case). Settings keys
`video_tracks`, `strip_video`, `audio_tracks`, `strip_audio` — each
`*_tracks` a list of `{"source": "primary"/"external", "file": path|None,
"index": N}`, one entry per *checked* row, `N` 0-based among that file's own
streams of that kind (what `-map <input>:v:<index>` / `:a:<index>`
addresses).

**The sizing rule, stated generally (this is what the INVARIANT above rests
on): neither tab's Video or Audio page may size taller than that tab's own
Overview page.** The tab-wide preview above `self.panels` is sized off
whichever sub-tab page is tallest (the `QStackedWidget` sizes to its tallest
child) — and since Overview's own layout is identical between the two tabs,
Overview ends up the tallest page, and the preview the same height, *in
both tabs*, purely as a consequence of neither tab's Video/Audio page ever
being allowed to exceed it. The instant either tab lets one page grow past
Overview, the invariant breaks for *that tab specifically* — Muxing and
Encoding each own a separate `panels` stack, so it's never both at once,
and the symptom is always "one tab's DropBox is shorter than the other's,"
not a crash or a warning. There is no automatic guard against this; it is
enforced by hand, per control, at the point something is added to a Video
or Audio panel — see the two worked examples below (`TrackListBox` on
Muxing, the Resolution/Strip Video row on Encoding).

**Muxing's worked example — the panel stays exactly as short as Encoding's
Video/Audio panels while the box itself is maximized, not just kept under
some margin.** Rather than picking some height comfortably under Overview's
ceiling, `_track_panel` reads it straight off the already-built Overview
page — `self.panels.widget(0).sizeHint().height()` (Overview, added to
`self.panels` one line before `build_video`/`build_audio` run, so it's
already there to measure) — and sets `TrackListBox.setFixedHeight` to
exactly that, so the box grows to fill every pixel Overview was already
going to cost the layout, with nothing left on the table and nothing pushed
over it either. This tracks Overview's real height live (a future Overview
change, a different font, a different DPI) rather than freezing in whatever
pixel count one measurement happened to show.

**Fixed, not a minimum — the box's own height must never move once it has
content, however many rows land in it.** A `QScrollArea` with
`widgetResizable=True` (`TrackListBox.scroll`) takes its own `sizeHint` from
the scrolled widget's, so with only a *minimum* height on the box, five or
six probed tracks quietly grew it — and the whole panel, and the whole tab's
preview above it — taller than an empty or lightly-populated one (confirmed:
8 audio tracks alone grew the box from 118px to 234px, dragging Muxing's
`panels.sizeHint()` above Encoding's and shrinking the shared preview on
Muxing specifically). `setFixedHeight` on both `TrackListBox` itself (a
92px floor, in case something ever builds one outside `_track_panel`'s own
maximize-to-Overview call) and in `_track_panel` forces every row past what
fits into the scroll area's own internal scrollbar instead of the box.

An empty box (no file yet, or a probe that found no streams of that kind)
shows "No tracks available" dead-centered in the box — not the scroll list's
first row, which would sit top-left like a stray label rather than reading
as an empty state. It's a sibling of the scroll area in the box's own outer
layout, each toggled by `set_items` (`self.scroll.setVisible(bool(items))`);
a hidden widget costs the layout nothing, so this never fights the box's own
height.

`TrackListBox.set_items` is the box's own single constraint pass, matching
`_sync_controls`'s own idempotent-recompute philosophy: called on every
`_sync_controls` pass with the source's current streams plus whatever's in
`_video_external`/`_audio_external`, it diffs by row id — an id already
present keeps its checked state and just gets its label refreshed, so
clicking one checkbox (which itself triggers `_sync_controls` through the
same `_on_control_change`/`changed` wiring every other control uses) never
disturbs another row. It only tears every row down and rebuilds from scratch
(`reset=True`) when `app.current_file_path` itself changed since the last
sync — a new file's stream indices don't mean what the old file's meant, so
a same-named `src:0` row from a *different* file must never be mistaken for
a carried-over pick. A brand new row (first appearance, whether from a reset
or a fresh "Add Stream(s)" pull) defaults to checked only when it lands in
the very first position — every other stream starts unchecked, mirroring
Encoding's own multi-track audio picker defaulting to just the first stream
(see "Multi-stream audio" below) rather than "check everything", since a
checked box here means a real, copied stream in the output, not a dial to
tune later.

`_validate_specific` blocks a job only when a box actually has rows (a real,
probed stream exists) but the panel isn't stripped and nothing in it is
checked — an unprobed or genuinely stream-less panel is simply empty, not an
error, so an empty box never blocks anything by itself.

**Encoding / Video**: `Encoder` / `Profile` / `Level` / `Encoder Preset` on one
row (the label says "Encoder Preset"; internals keep the name `speed`), the
quality slider spanning the row beneath (`Low`…`Placebo`, inverted so worst
is left), `HDRtoSDR` (label clickable) pinned top-right, and on the
bottom-right row `Resolution` (a downscale ceiling — `formats.RESOLUTIONS`,
never offers an upscale past the probed source's own height, see
`core.formats.resolutions_for`) beside `Strip Video`. Profile, Level, Speed
and the quality slider's kind, range, default and end labels all derive from
the encoder (`formats.profiles_for` / `levels_for` / `quality_for`;
`_apply_speed`, `_apply_quality`). A Speed retarget snaps to the encoder's
own recommended default (`speed_default_for`), not the first — most
extreme — entry. AV1's speed list comes from a live probe
(`core.utilities.av1_preset_range`), since SVT-AV1's preset ceiling varies by
ffmpeg build (confirmed: 0–8 before an update, -2 to 13 after). The slider
keeps its value across a codec switch while it still fits the new range.

**Encoding's own worked example of the sizing rule above: Resolution sits
beside Strip Video on one shared bottom row, deliberately not its own
row.** A first attempt gave Resolution the standard `labeled()` caption (a
26px-min-height "field" caption above the control, same as every other
control on this page) on its own row, which by itself was enough to push
this page's `sizeHint` well past Overview's — confirmed directly (163px vs.
Overview's 118px at one tested window size), which silently shrank
Encoding's DropBox below Muxing's by the same margin. Folding it onto Strip
Video's row instead — one shared `hrow`, bottom-aligned, the same pattern
`build_audio`'s "Audio Track" + "Choose Stream(s)" pairing already uses for
a taller control beside a short one — costs no extra row at all, and the
page comes back in comfortably under Overview (115px vs. 118px). The lesson
generalizes: on either tab, a new Video/Audio control is never free height
just because there's a blank row's worth of stretch nearby — always
re-measure against that tab's own Overview page before trusting a layout
"looks about right."

**Encoding / Audio** (multi-stream): `Audio Track` + `Choose Stream(s)` +
`Passthru` on row one; `Audio Codec` / `Bitrate` / `Channels` / `Sample Rate`
on row two, each dropdown sized to its longest *possible* entry
(`Dropdown.width_for`); `Strip Audio` on the right. The row edits whichever
included stream Track shows. `_save_active_audio_stream` banks the controls
into `_audio_stream_settings[index]` before a track switch or a gather, so
switching never loses an edit; `_load_active_audio_stream` writes one back in
(muted). `_auto_select_audio_streams` initialises every probed stream once
per file (guarded by path, so a re-delivered probe can't discard edits): each
defaults to its own codec/params where offered, DTS / Dolby TrueHD are named
and forced to Passthru, and only the first stream is included. **Passthru**
makes the stream a copy, so Bitrate / Channels / Sample Rate mirror the
source's real values as display overrides (`_apply_passthru_values`) and
disable.

**HDR→SDR preview** (Encoding only): `on_thumbnails` records the raw frames and
`_apply_preview_frames` shows the app's tone-mapped set instead whenever the
switch is on and a render for this file is cached — keeping the scrub index
across the swap. Turning it on for an unrendered file starts
`app.start_hdr_render`.

#### `_sync_controls` — the single constraint pass

**Every derived UI state in each tab is decided in one function.** Each
control's user-action signal just calls `_sync_controls()`, which reads the
whole form and rewrites every dependent widget's option list, selection and
enabled state from scratch. It's idempotent, so call order never matters.
**Don't add a pairwise handler; add a rule here.** Muxing and Encoding each
have their own — the rulesets genuinely differ.

Encoding's rules, in dependency order:
1. **Stream presence.** Ticking one Strip disables the other, so "both
   streams removed" is unreachable. Because that spans two panels, the other
   sub-tab button turns red (`SubTabBar.set_marked`) and the carousel shows it
   (Wave Loop for stripped video, mute badge for stripped audio). A stream the
   source doesn't have (`has_video` / `has_audio` is False) gets the same red
   mark and greyed panel, and its Strip checkbox is disabled — never forced
   checked or unchecked.
2. **Container → codec lists** (`video_codecs_for` / `audio_codecs_for`). A
   probe-only passthru codec (DTS / TrueHD) is never snapped away.
3. **Video codec → profile / level / speed / quality.**
4. **Audio codec → bitrate**: lossless codecs and `Select` have no bitrate;
   Passthru mirrors the source instead.
5. **Enabled state** for everything a removed, absent or unresolved stream
   makes meaningless. Channels / Sample Rate reset to `Select` and disable
   while the audio codec is unresolved. HDR→SDR needs a live video stream, a
   source detected as HDR (`info["hdr"] is True`) and `supports_libplacebo()`
   — and is **forced off**, not just greyed, when unavailable, so nothing
   silently keeps tone-mapping behind a control the user can't use. The
   quality slider stays live on `Select` (dial it in ahead of a codec) but
   disables for a codec with no rate control (ProRes / DNxHR / CineForm /
   FFV1).
6. **The rundown** — the one cross-panel view: `H.264 · Main · L4.1 · CRF22 ·
   1080p · SDR` (the Resolution segment only appears once a real downscale's
   picked — omitted entirely at `Source`), the first included audio stream
   (`+N more`), and the trim; problems in STOP_RED (`— removed —`,
   `— no video stream —`, `— pick an encoder —`, `— pick a codec —`,
   `— no streams selected —`).

`_retarget(menu, values, what)` points a derived dropdown at a new list and,
when the pick had to snap, **toasts why** ("Encoder switched to VP9 — .webm
can't carry H.265"). Silently swapping a codec out from under the user is
what makes an options screen feel haunted. `self._ready` mutes those toasts
while a settings dict is being written in.

Muxing's rules: the same stream-presence rule; the track boxes carrying the
source's own streams plus any browsed-in external ones (see "Muxing / Video"
above for the reset-on-file-change/diff-otherwise logic); **the container
inversion** — the source's own codecs decide which containers are reachable
(`formats.containers_for`), with a toast when the pick snaps and the save
path's extension following it; a stripped or absent stream disables its
panel; the rundown (`copy · H.264 · 1 track`, or `· 2 tracks` once more than
one is checked, and the trim with a `· keyframe` caveat, since a copied
stream can only be cut on a keyframe).

Encoding's `_validate_specific` blocks a present-or-unknown stream left on
`Select` (Encoding never falls back to a silent copy — that's Muxing's job),
an included audio stream with no codec, and HDR→SDR without libplacebo.

`_apply_settings` writes a dict **in dependency order** — common keys and
strips, container, sync, encoder, sync, then the leaves (profile / level /
speed, `audio_streams`, HDR, quality) — so every list is legal before the next
tier's value lands in it. An absent key leaves its control alone, which is
how a preset (recipe keys only) shares the path.

#### Queue (`ui/tabs/queue.py`)

Tasks live in `self._rows` (`task_id → {"widget", "settings", "source_tab",
"error"}`); `source_tab` is `Muxing`, `Encoding` or `Downloader`.

**Rows are one widget each** (`QueueRow`, 56px, fully painted): 60x40
thumbnail, description (elided), status (80px), ✕. Colour is status-driven:
`Queued` solid primary, `Failed` solid STOP_RED, anything else (running,
`Paused`, `Done`) the neutral row grey. A running row paints its fill by
drawing the row, then clipping to the fill width and drawing it again in
primary — the fill edge cuts glyphs cleanly because both halves come from one
paint pass. The fill covers the thumbnail and description and stops at the
status column. Clicking a row opens its details; the ✕ removes it.

**One job at a time, with real process control.** `self._active` is
`{"task_id", "job", "rest", "paused", "fraction", "stage"}` or None.
- **Start** (`start_queue`) runs Queued tasks in order — or thaws a paused job
  in place. **Pause** (`pause_queue`) *suspends* the process
  (`NtSuspendProcess`); nothing encodes while paused. **Stop**
  (`stop_queue`) kills it (fine while suspended), deletes the partial output,
  reverts the row to Queued. The button reads Start Queue / Pause Queue.
- `start_task(id)` (the do-it-now path) starts at once or puts the task at the
  front of `rest`; returns `started` / `next` / `paused`.
- **Removing the active row kills its process first** — a process must never
  outlive its row — and continues with the next job if the queue was running.
- `_process_next` loads `ffmpeg_vars` and compiles the argv **on the GUI
  thread** (workers only ever see a plain list), prints it, and starts an
  `FfmpegJob`; Downloader tasks go to `_start_download` (a `YtDlpJob` from the
  task's `download` plan).
- Two timers while a job runs: `_poll` every 100ms drains `poll_events()`
  (progress, `stage` for downloads — the row's status follows it, and
  `_running_label` restores it after a resume — then `done` / `failed`), and a
  16ms frame timer eases the painted fill toward the latest fraction
  (`_EASE`). **Any event other than progress/stage is terminal** — a new event
  kind needs a branch. On a terminal event the fill snaps to 100% and repaints
  *before* the status flips, so the full bar is actually seen.
- **Failure**: the row turns red, the reason is kept for the details popup,
  and a "Job Failed" notice is queued (`“name” couldn't be encoded/muxed/
  downloaded.`) and shown through `QTimer.singleShot(0, _show_errors)` behind
  an `_error_dialog_open` guard — never from inside `_poll`, since a modal
  spins a nested event loop and the poll keeps firing under it. The queue
  keeps moving.
- When a batch ends, "All queued jobs finished." is toasted.

**Details popup** (below the list, fixed 140px scroll area so a long Encode
list scrolls): `_DETAIL_FIELDS` drives which settings keys show and how
(`time`, `bool`); a key absent from a task's dict is skipped, which is how each
task kind shows only its own. A stripped stream's codec/track rows are hidden
(`Strip Video: Yes` stays). `resolution` is one of `_DETAIL_FIELDS`' rows,
hidden under `strip_video` the same way `quality`/`profile`/`level`/`speed`
already are (Encoding's downscale pick). **`quality` itself means two
unrelated things depending on which tab queued the task** — Encoding's own
CRF/qscale value vs. the Downloader's Resolution pick, which is stored under
the same settings key (`quality_menu`'s value — see "Tabs → Downloader"
above) since the label was renamed on-screen but the key wasn't; `_show_details`
relabels that one row "Resolution" specifically for a Downloader task
(`row["source_tab"] == "Downloader"`) rather than leaving it reading
"Quality" for a value that isn't one. Encoding's `audio_streams` render one
row per stream; Muxing's `video_tracks`/`audio_tracks` (when not stripped)
render one row per *checked* track — `"Video Track"`/`"Video Track N"` (or
`"Audio ..."`), each showing `Track <N>  ·  Source` or `Track <N>  ·
<external filename>` — the same one-row-per-entry treatment the multi-track
picker itself uses, not a single summarized "Video Track: ..." line the way
the old single-dropdown UI would have. A failure adds an **Error** row in
STOP_RED. `Go to File` (enabled only once the output exists) runs `explorer
/select,"<path>"` — as one command-line *string*, since list-to-argv
quoting would break Explorer's own parsing of a path with spaces.

**Thumbnails** never decode on the GUI thread: the app's cached frame when
it's the selected file, the Downloader's cached thumbnail for the same link,
else one decoded / fetched on a worker.

**Overall progress** (flat strip, top): `(finished + active fraction) / total`,
updated on every status change and poll. `on_leave` resets a completed 100%
bar. `pending_task_count()` (running + paused + queued — what quitting would
lose) drives the close prompt and `clear_all`'s confirmation; `Clear
Completed` removes Done and Failed rows.

#### Downloader (`ui/tabs/downloader.py`)

Top: the Deno warning (shown only when the startup check found no usable
Deno — warn-only), the URL row (entry, `Paste` — fills from the clipboard
*and* fetches — and `Fetch`; Enter fetches too), and the preview box
(`BorderedFrame`: placeholder text, then the fitted thumbnail over a
`MarqueeLabel` title and an "uploader · length" line). **Only a single http(s)
link can be dropped on the box** (`_dropped_link`); files and other text are
refused. Bottom: `Mode` (`SegmentedButton`: Video + Audio / Video Only /
Audio Only), `Video Codec` / `Audio Codec` (Video + Audio only) /
`Resolution` / `Video Format` with an `≈ size` readout, the save row, and
`Queue Task` / `Download`. Everything below the URL row is disabled until a
fetch succeeds. **"Resolution" is only the on-screen label** — internally
still `quality_menu`, and the settings key is still `"quality"` (same
"label changed, internals didn't" convention as Encoding's Speed control
still being labeled "Encoder Preset"); see "Tabs → Queue" below for how the
Queue's own details popup tells this apart from Encoding's unrelated
`"quality"` (its CRF/qscale value).

A fetch adopts the video (every pick resets to its best default) and sets the
save FILENAME to `downloader.safe_stem(title)` + the plan's extension,
keeping the folder — into `app.downloader_default_location()` (the
Downloader's own separate save folder if Settings has one set, else the
same shared default every other tab uses). Editing the URL after a fetch
blocks queueing ("Link Changed") until it's fetched again.

`_sync_controls`, same contract: Mode (only modes the video supports) → Video
Codec (`Best Available` + what that mode can use) → for video modes
Resolution (resolutions / fps / HDR of that codec) → in Video + Audio, Audio
Codec (resolved *before* Format so a real audio codec isn't hidden behind
Format's default) → Format (containers that fit *without re-encoding*). For
Audio Only the last two swap: Format (`Original` + `.mp3/.m4a/.opus/.flac/
.wav`) → Resolution. A snap toasts unless a Mode switch caused it. The
resolved plan (`downloader.resolve`) drives the size readout and the save
path's extension. Settings keys: `url, title, thumbnail_url, output_path,
output_format, mode, video_codec, quality, download` plus `audio_codec` in
Video + Audio only (absent otherwise, so the details popup skips it).
`download` is the plan the queue runs.

#### Settings (`ui/tabs/settings.py`)

**System info** (read-only, top-right corner of the title row, no "System:"
label): the CPU's marketing name, the detected GPU's display name, and total
RAM (`core.system_info`, `core.gpu.display_name()`), right-aligned and word-
wrapped in a fixed-width label — deliberately *not* a row in the main
column, since a bare CPU name can run past 30 characters and sizing to its
own content could grow wider than the tab frame on a smaller screen or a DPI
change from dragging the window to another monitor. **Theme** (`Dropdown` over
`THEMES` + two colour swatches, no name label next to them — the swatches
speak for themselves): hovering a row previews that palette across the whole
app; picking commits and saves; closing the list without picking reverts to
the committed theme (posted with a zero-delay timer so a pick's `picked`
lands first). **Appearance Mode** (System / Light / Dark) applies live and
saves. **Default Save Location** (entry + Browse; a typed path is pushed to
the app on `editingFinished`), with the drive's total/free space shown
underneath (`core.system_info.disk_usage`) — free space at or below 25GB
renders in STOP_RED, refreshed on every edit/Browse and on `on_enter`
(switching back to the tab — free space can change while the app sits
elsewhere). **Hardware Acceleration (GPU)** (a global `Switch` every Encode
job reads via `app.gpu_enabled`, now real — see `core/gpu.py` and
`core/ffmpeg_build.py`'s GPU acceleration section) with a status line
underneath naming exactly what it would use — the GPU, its vendor's own
encoder brand name (NVENC / Quick Sync / AMF — `core.gpu.summary_label()`,
not a generic "hardware encoding"), and which codecs — or "Off — encodes run
in software." while unchecked, so turning it on is never
a leap of faith about what it does. **Separate Save for Downloader**
(`CheckBox`, off by default) reveals a second entry + Browse row for the
Downloader's own save folder — `app.downloader_default_location()` is what
the Downloader tab actually autofills into (its own location when this is
on *and* one's been set, else the same shared default every other tab
uses), read via `DownloaderTab.refresh_default_location()` (called whenever
Settings' own default, the separate-save toggle, or the separate location
itself changes — but, same "once a real value's in the field, only that
flow's own autofill touches it again" rule as `_autofill_output_path`, only
*before* a fetch: `DownloaderTab.has_fetched()` gates it, since overwriting
a post-fetch save path from underneath a completed fetch would be exactly
the kind of "why did my path change" surprise this app avoids everywhere
else). **Reset to Default** (`role="danger"`, `ask_yes_no` confirmation)
resets theme, appearance mode, default save location, the Downloader's
separate-save toggle and location, and GPU acceleration all back to their
defaults in one action, then autosaves — the one Settings control that
touches every persisted key at once rather than just its own. **Save**
persists and toasts "Settings saved." (no jump to the Queue). Settings also
autosave when the tab is left and on close.

### Widgets (`ui/widgets/`)

- **Dropdown** (`QComboBox` subclass, self-painted): opens straight down 3px
  below the button, unrolling + fading in by animating a *mask* on the popup
  (no per-frame resize). `picked(str)` fires on a user pick only;
  `hovered(str)` reports row hover; `popupClosed` fires only for a popup that
  was genuinely open (Qt also calls `hidePopup` on style changes). `set(value)`
  shows a value even when it isn't in the list (a display override) — always
  read with `value()`, never `currentText()`. `set_values(values)` no-ops when
  unchanged, keeps a still-legal pick, else snaps to the first; an empty list
  shows `—` (`NO_OPTION`). `Dropdown.width_for(values)` sizes one to its
  longest entry.
- **CheckBox** — 24px box, `color_key` `secondary` or `stop`; fill fades
  (120ms); disabled greys the box too. **Switch** — the knob slides (160ms).
  **SegmentedButton** — the selection pill slides (180ms); `set` is silent.
  **ClickableLabel** — a `QLabel` with a `clicked` signal (only while
  enabled); Encoding's `HDRtoSDR` caption is one, so clicking the text
  toggles the switch beside it, not just the switch itself.
- **TimeSpinner** — a self-painted HH:MM:SS field (`_TimeField`) plus stacked
  ▲/▼ `IconButton`s with an accelerating auto-repeat (400ms → 30ms, ×0.85).
  State is a 6-digit list and `cursor_pos` (0–5) indexes it: typing overwrites
  and advances, Backspace steps back then clears, Delete clears in place,
  Left/Right/Home/End move, minutes/seconds clamp to 59, a click lands on the
  nearest digit, and a block cursor shows while focused. `valueChanged` fires
  on **every** change, typing and `set_seconds` included.
- **MarqueeLabel** — scrolls sub-pixel and time-based (40px/s, 1.5s hold per
  loop) only when the text overflows; its timer runs only while shown.
  **MarqueeGroup** — one shared clock several `MarqueeLabel`s can join (e.g.
  `SummaryPanel`'s Video/Audio/Length rows) so they all sweep and restart in
  step, rather than the shortest one finishing and holding while a longer
  one keeps drifting out of sync with it.
- **Tooltips** (`ui/widgets/tooltip.py`) — `tip(widget, text)` attaches a
  shared, themed hover tooltip (`_Tooltip`, fade-in only) to any widget via
  a single app-wide `_TooltipManager` event filter (400ms hover delay);
  works even on a disabled widget (exactly where an explanation is often
  most needed) and syncs the cursor to a plain arrow while disabled, since
  the widget's own hover cursor wouldn't otherwise reflect that it can't be
  interacted with. Distinct from the carousel's own `_InfoTooltip` above,
  which shows structured probe data rather than a line of static copy.
  `ui/tips.py` holds the shared copy this app's dropdowns tip themselves
  with — `VIDEO_CODEC_TIPS`/`AUDIO_CODEC_TIPS`/`CONTAINER_TIPS`/
  `AUDIO_FORMAT_TIPS` (per-value explanations) plus the `SELECT_*_TIP`/
  `BEST_*_TIP` placeholders shown before a real value's picked — used across
  Encoding, Muxing, Downloader and Settings.
- **IconButton** — a stylesheet button whose ✕ / ▲ / ▼ is painted, so it
  never depends on a font having the glyph (`draw_cross` does the same for
  painted widgets).
- **SubTabBar** — active tab primary at 30px, inactive secondary at 24px,
  bottom-aligned; height and colour ease (170ms) including hover;
  `set_marked(name, bool)` cross-fades a tab to STOP_RED.
- **DropBox** — primary rounded border; drop / double-click / Browse; lights up
  on drag-over; `collapse()` leaves only Browse once a file is chosen,
  `reset()` is the reverse — back to its pristine pre-import state, used
  when a picked file turns out to be unreadable (`app._reject_file`, see
  "File selection is a broadcast" above) rather than leaving the box
  stranded mid-import.
  **BorderedFrame** is the border alone, `color_key` defaulting to `primary`
  (Muxing's `TrackListBox`, `ui/widgets/tracklist.py`, passes `secondary` for
  a visually distinct blue-on-Lemon box). **SummaryPanel** —
  `set_values([(text, color_key_or_None), …])`.
- **Sidebar** — title, logo, four nav buttons, a stretch, Settings, footer.
  The logo (`assets/LlamaMXD-Logo.svg`, replacing a static `llama.png`) is
  rendered at 4x oversample and re-tinted to `primary_text` via
  `CompositionMode_SourceIn` (`Sidebar._load_logo`), so it goes white/black
  with the theme the same way the title text already does, instead of
  staying a fixed colour regardless of theme.
  **TabIndicator** — the flat primary pipe from the active nav button to the
  tab frame with a 12px secondary band through its middle; square corners so
  it meets the button's rounded edge flush at mid-height; glides between
  buttons (220ms). Transparent to the mouse.
- **ThumbnailCarousel** — one fitted frame at a time (`(w-8)/(h-8)` fit,
  scaled pixmaps cached per size and DPR).
  - **Chevrons** are primary discs (alpha 230) with a chevron in
    `primary_text`, sized from the frame (`min(w,h)*0.12`, capped at `w*0.16`
    / `h*0.42`, floored at 14px so a very small preview doesn't shrink them
    to nothing, then an overall `*0.75` — `_disc_centers` — so they read as
    a control rather than dominating the frame) and flush to its edge, with
    an optical-centre nudge toward the tip; they and the dots fade in on
    hover (100ms). Navigation clamps at both ends (only a chevron that leads
    somewhere is drawn).
  - **Clicks**: a press on a disc steps (so spam-clicking runs to the end);
    a double-click in the *central* area — outside the chevron band, with the
    previous press also central — emits `reselect`. The band exclusion means
    hammering a chevron past the last frame never opens the file dialog.
  - **The slide** (115ms, OutCubic) draws the outgoing and incoming pixmaps at
    an offset under stationary chevrons; the dot row re-flows on the same
    clock. Dots: three large screen-stationary centre dots, two tapering dots
    per side, only for frames that exist; the highlight rides toward the edge
    it's heading for and the row scrolls only once it's there (see the module
    docstring and `_resolve_dot_start`).
  - **Badges**: the mute badge (`assets/audio-mute.svg`, 14% of the short
    side, top-left) while audio is stripped; the info badge (9%,
    bottom-left) once a probe lands. Both are SVGs rendered through a cached
    `QSvgRenderer` (`_svg_renderer`), not a scaled bitmap — a raster PNG
    downscaled to the badge's actual ~20-40px on-screen size showed a
    visible stepped edge even through `SmoothPixmapTransform`, which an SVG
    doesn't have at any size. The mute badge renders `audio-mute.svg`
    exactly as authored (its own fixed red/white, theme-independent by
    design). The info badge (`_paint_info_badge`) recolors `assets/info.svg`
    for the resolved appearance mode: that file is a single solid disc with
    the "i" glyph cut out as a hole (confirmed by rendering it over a
    contrasting backdrop), so a plain circle is painted first in the glyph
    colour, then the SVG — with every `fill="currentColor"` swapped for the
    disc colour via a raw string replace, not a file edit — is rendered on
    top of it: the hole lets the glyph-coloured circle underneath show
    through as the "i". Dark mode: dark disc, white glyph. Light mode: white
    disc, dark glyph. Hovering the info badge shows `_InfoTooltip` — container, video
    (codec · profile · level · size · HDR), an HDR mastering line (ST 2086 peak
    and MaxCLL/MaxFALL — a literal 0 reads as "not tagged"), audio (+ track
    count), duration and size — refreshed live if a probe lands while open.
  - **Expand/shrink** — a corner icon (`assets/expand.svg`/`shrink.svg`,
    `_paint_expand_icon`) toggles `_expanded` and emits `expandToggled(bool)`;
    the listening tab (`MediaTab._on_expand_toggled`, `ui/tabs/media_tab.py`)
    reparents the *same* carousel instance into a `_ExpandedPreviewOverlay` —
    a translucent scrim sized to the main window's own footprint (not the
    monitor: becoming a separate top-level window was tried and reverted,
    since it stole window activation from the main window and silently broke
    the app-level Left/Right keybind, which is gated on
    `window.isActiveWindow()`) — rather than any code here being duplicated,
    so every one of the carousel's own behaviors (chevrons, dots, badges,
    drag/drop, arrow-key stepping) keeps working unchanged just at a bigger,
    centred size. One overlay instance per `MediaTab` (Muxing and Encoding
    each own theirs). Clicking the scrim outside the carousel's own bounds,
    or `force_collapse()` (called when the previewed file is about to change
    out from under it — a rejected import, see "File selection is a
    broadcast" above), shrinks back. A few of the carousel's own behaviors
    scale specifically for this: the dot row grows 1.5x (`_dot_scale`,
    legibility at the bigger size matters more than shrinking with
    everything else); the mute badge would shrink to 0.5x but is in practice
    never painted while expanded at all; the info badge stays at the same
    proportional size rather than an extra 2x on top of the already-bigger
    frame (would've read as comically huge); and a double-click-to-reselect
    is disabled while expanded (an accidental reselect from inside the
    zoomed-in view would be surprising).
  - **WaveLayer** — the Wave Loop visualiser for stripped video and
    audio-only input. A child of the *tab* (not the carousel) so it bleeds
    past the preview's inner margin to the tab frame edges, placed over the
    carousel's vertical band and transparent to the mouse so clicks and drops
    reach the carousel. rlottie renders `Wave Loop.json` (every fill flattened
    to white by `_force_white_fills`) straight into an ARGB32-premultiplied
    `QImage`; the dot band (`_WAVE_BAND_LO..HI` of the height) is scaled to
    `_WAVE_FILL` and tinted with a primary→secondary gradient via
    `CompositionMode_SourceIn`. Playback is time-based (frame index from wall
    clock), repainted only when the index moves, on a 16ms timer that runs
    only while visible. Falls back to a faint gradient wash without rlottie.
  - Signals: `reselect`, `populated` (first frames or audio-only — the tab
    reveals the carousel), `indexChanged` (user scrubs only), `fileDropped`,
    `expandToggled(bool)`. `step(delta)` is the keybind stepper; `sync_index`
    jumps silently.
- **Dialogs** — `MessageDialog` (a `QDialog`: bold title, wrapped message,
  optional entry, buttons right-aligned; the **first button is the affirmative
  one** and gets primary). Enter confirms; Escape and the close box decline,
  so a dismissed confirmation can never destroy work. `show_message`,
  `ask_yes_no` (True only on an explicit Yes), `ask_text` (stripped text or
  None), `confirm_output_path`. `AudioStreamPickerDialog` /
  `choose_audio_streams` — one checkbox per probed stream; OK never returns an
  empty set ("no audio" is Strip Audio's job), Cancel returns None.
  `ExternalStreamPickerDialog` / `pick_external_streams` — the same
  checkbox-per-stream shape, for choosing which stream(s) of a *second*
  browsed-in file Muxing's "Add Stream(s)" pulls in (see "Muxing / Video"
  below). **Dialogs block in a nested event loop** — never open one from a
  recurring timer tick.
- **Toasts** — `app.notify(message, go_to_queue=True)`. A 260x44 primary child
  widget that slides in (200ms) at the tab frame's top-right (12px inset),
  holds 2.2s, and fades (700ms); clicking jumps to the Queue (unless
  `go_to_queue=False`) and dismisses it. **At most three hold a slot** — a new
  arrival retires the oldest into a fast fade (200ms); the stack closes up
  when one goes. Every toast runs its own animations, so an uncapped stack
  under button-mashing is wasted work.

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
  "sample_rate_arg", "language"}`); a **Passthru** stream (the checkbox,
  forced on for `formats.is_passthru_only` codecs — DTS/Dolby TrueHD, which
  this app has no re-encode path for at all) always comes out
  `"copy"`/`None`/`None`/`None`/`None` regardless of what its display-value
  fields still say, since `EncodingTab` keeps showing the *source's* real
  values there purely for display while Passthru is on — `language` is
  `None` for a Passthru entry specifically because nothing about a copied
  stream's tags goes stale (see the stale-metadata bullet below), so there's
  nothing for it to reapply.

  **`RESOLUTION`/`SOURCE_HEIGHT`/`SCALE_VF`** back Encoding Video's optional
  downscale (`core.formats.RESOLUTIONS`, above). `RESOLUTION` is the raw
  pick (`formats.SOURCE_RESOLUTION` by default); `SOURCE_HEIGHT` is the
  probed source height *snapshotted at queue time*
  (`EncodingTab._gather_settings`, same "a fact about the input, not a user
  choice" convention as `MASTERING_MAX_NITS`/`MAX_CLL` below) rather than
  read live, so a queued job still scales against the source it was actually
  queued against even if the user swaps files before it runs; `SCALE_VF`
  (`_scale_vf`) is the resulting `-vf` fragment (`"scale=-2:<height>"`), or
  `None` for `"Source"` or when there's no real downscale to do. It
  re-validates `RESOLUTION` against `SOURCE_HEIGHT` at derive time rather
  than trusting the caller — the UI already caps the dropdown to the
  source's own height, but a saved preset applied to a smaller or
  differently-probed file could still name a rung that's no longer legal for
  it, and this is the one place left that would ever notice.
- **Multi-stream audio** ("Choose Stream(s)" on Encoding's Audio panel,
  `ui/widgets/dialogs.py`'s `AudioStreamPickerDialog`) — one
  checkbox per stream `probe_media`'s `audio_streams` reports, pre-checked to
  match what's currently included; OK returns the chosen index set (refusing
  to ever return empty — see its `_dismiss`, since "no audio at all" is Strip
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
  same reason `build_mux_command` needs one `-map` per *checked* row in
  Muxing's own track boxes (`VIDEO_TRACKS`/`AUDIO_TRACKS`), not just for an
  external track.
- **`core/ffmpeg_build.py`** — `build_mux_command` / `build_encode_command`
  turn those into an ffmpeg-python `Stream`. `compile_command(path)` returns
  the full argv, with the runner's global flags
  (`-nostdin -loglevel error -nostats -progress pipe:1`) placed right after
  `ffmpeg` via `compile(cmd=...)`. Muxing is always `-c copy`. **GPU
  acceleration** (`core/gpu.py`) — `app.gpu_enabled` (the Settings switch) is
  read by `EncodingTab._gather_settings` into the job's `gpu_enabled` key;
  `ffmpeg_vars.derive()` then asks `gpu.hw_encoder_for(encoder)` for a
  hardware encoder id (`h264_nvenc`/`h264_qsv`/`h264_amf`, and the `hevc_*`/
  `av1_*` equivalents — the only three codecs every vendor's consumer
  encoder actually supports) matching the machine's detected GPU vendor
  (`gpu.vendor()`, via `wmic`/`Get-CimInstance Win32_VideoController`,
  NVIDIA > AMD > Intel when more than one adapter is present) *and* actually
  compiled into this ffmpeg build (`ffmpeg -encoders`); finding one swaps
  `VIDEO_CODEC_ARG` to it and empties `SPEED_ARG` (a hardware encoder's own
  `-preset` vocabulary doesn't match libx264/libx265/SVT-AV1's, so a
  hardware job just rides that encoder's default rather than guessing a
  translation). No supported vendor, no hardware encoder for that codec, or
  an ffmpeg build that doesn't have it compiled in all silently fall back to
  software — same posture as `supports_fps_mode`/`supports_libplacebo`
  below. `build_encode_command` swaps the CRF/qscale rate-control kwargs for
  `gpu.rate_control_kwargs(HW_ENCODER, QUALITY)` when `HW_ENCODER` is set
  (`-rc vbr -cq` for NVENC, `-global_quality` for QSV, `-rc cqp -qp_i/-qp_p/
  -qp_b` for AMF — none of the three take `-crf`), clamped to 0-51 since
  that's every vendor's real ceiling regardless of AV1's own 0-63 CRF range.
  Verified against real hardware on this app's own dev machine (see the
  Vulkan/libplacebo aside further down for its NVIDIA+AMD setup): a real
  `h264_nvenc`/`hevc_nvenc` encode both ran end-to-end and produced a
  correctly-tagged output; `av1_nvenc` failed with ffmpeg's own "No capable
  devices found" — a genuine driver/NVENC-API limitation on this particular
  GPU/driver combination for AV1 specifically, not a bug in the command
  built for it (H.264/H.265 through the identical code path both worked) —
  which would surface as a normal Failed job with that message, the same
  fallback path every other capability guess-gone-wrong in this file uses.
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
  - **Speed** — the Video sub-tab's `speed_menu` (see "Tabs" above); its
    value (a named `-preset` for x264/x265/AV1, or `-cpu-used` + a fixed
    `-deadline good` for the libvpx codecs — `formats.speed_kind_for`) is
    carried through as `SPEED`/`SPEED_ARG` in `ffmpeg_vars` and merged
    straight into the encode's output kwargs. Before this control existed,
    *nothing* in this app ever set an encode-speed knob at all, so every job
    silently rode whichever default the library ships (x264/x265's implicit
    "medium", etc.) — a real, measurable contributor to "this is taking way
    longer than it should" on a large or HDR source. Dropped entirely (not
    translated) the moment GPU acceleration resolves a hardware encoder —
    see above.
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
    disables `hdr_switch` — and forces it off — when it's False, so the
    control simply can't be on; and `build_encode_command` raises a
    `ValueError` if `HDR_TO_SDR` somehow reaches it anyway (e.g. a preset
    saved on a different ffmpeg install) — caught by
    `EncodingTab._validate_specific` before the job is even queued, and by
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
    elsewhere. The render and its cache (`start_hdr_render`,
    `hdr_frames`/`hdr_frames_path`, token-guarded like the thumbnails) live
    on `MainWindow`, one render per file. `EncodingTab._apply_preview_frames`
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
  **A re-encoded stream's stale per-track statistics are stripped, not
  carried through.** ffmpeg's default per-stream metadata mapping copies a
  *source* stream's own Matroska tags (`title`, `BPS-<lang>`,
  `DURATION-<lang>`, `NUMBER_OF_FRAMES-<lang>`, …) onto the corresponding
  *output* stream even when that stream is being genuinely re-encoded to a
  different codec/bitrate/length — confirmed directly on a real file: a
  trimmed 2-minute `hevc_nvenc` re-encode carved out of an 87-minute
  x265 source still carried the source's own `BPS-eng` (`7562021`) and
  `title` (`"...@ 7561 kbps"`) verbatim, so MediaInfo (and any other reader
  of those tags) reported the *source's* bitrate for the new file,
  regardless of its real resolution/bitrate/length. `build_encode_command`
  adds `-map_metadata:s:v:0 -1` for the kept video stream (always genuinely
  re-encoded when kept — Encoding never copies video) unconditionally; for
  audio, only per *genuinely re-encoded* `AUDIO_STREAMS` entry (`codec_arg
  != "copy"` — a Passthru entry's tags are still accurate, since nothing
  about a copy actually changed), `-map_metadata:s:a:{i} -1` wipes it and
  `-metadata:s:a:{i} language=<lang>` (from `cfg["language"]`, above)
  immediately reapplies just the language tag — unlike a video track's
  language (never used for playback/track-selection the way an audio one
  is, so simply dropping it costs nothing real), a wrong or missing
  language tag on an audio track is a genuine, player-visible regression
  (track selection reads it).
  **The Resolution downscale chains onto the same `-vf` the HDR→SDR tonemap
  uses**, added after it when both are active — `video_filters` collects
  the tonemap string (if any) then `SCALE_VF` (above) and joins them with a
  comma into one `-vf`, independent of `HDR_TO_SDR` otherwise (an SDR
  source with a Resolution pick gets just the scale filter, HDR→SDR gets
  just the tonemap, both get both, comma-joined). Safe to chain directly
  because libplacebo's own filter string already ends back on a plain
  software `yuv420p` frame (see `libplacebo_tonemap_vf`'s `format=yuv420p`
  below) — no format conversion needed between the two filters.
  `+faststart` (`_faststart_kwargs`) is only added when the
  output is actually `.mp4`/`.mov` — it's a private option of that muxer, a
  purely lossless metadata rewrite (moves the moov atom to the front so
  progressive-download/web playback can start before the whole file
  arrives), does nothing for local random-access playback or NLE import, and
  this build happens to silently ignore it on `.mkv` rather than erroring —
  but that's this build's leniency, not a documented guarantee, so it's
  conditional rather than relying on it.
- **`core/ffmpeg_runner.py` — `FfmpegJob`**, no UI code in the module. It launches
  the argv with **one plain `subprocess.Popen`, not ffmpeg-python's
  `run_async()`**, because that can't pass `creationflags`, and
  `CREATE_NO_WINDOW` matters — otherwise every job flashes a console window.
  **Runs at the OS's normal process priority, not throttled.** An earlier
  version added `BELOW_NORMAL_PRIORITY_CLASS` on the theory that x264
  otherwise saturates every core including the GUI thread's — but profiled
  event-loop lateness during a real full-speed encode came back the same as
  idle either way (~6ms p90, both), and a same-machine, uncontended,
  single-job timing comparison showed throttling bought no protection at the
  cost of the encode itself: below-normal and normal priority finished a
  fixed encode within 0.3% of each other. So the throttle was pure downside
  with no measured upside; removed.

  Two daemon threads watch the process and never touch a widget: one parses
  `-progress` off stdout (**`out_time_us`** — `out_time_ms` is *also*
  microseconds despite its name), one drains stderr. The stderr drain is
  mandatory: a full pipe blocks ffmpeg forever, and its tail becomes the
  failure reason. Results reach the GUI thread only through `poll_events()`.
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
  GUI thread* (so workers only ever see a plain list, never the shared
  globals), starts the job, and returns immediately. It also prints the
  command. `_poll` (every 100ms; ffmpeg itself only reports progress about
  twice a second) drains events into the active job's fraction, and a 16ms
  frame timer eases the row's painted fill toward it. Then:
  - "done" → the row becomes Done;
  - "failed" → the row turns red "Failed", the reason goes in `row["error"]`
    (shown as an **Error** line in the details popup), a "Job Failed" notice
    is queued, and the queue moves on.
  - **The worker always queues a final `("progress", 1.0)` immediately
    before `("done",)`** (see `FfmpegJob._watch`), and that pair almost
    always lands in the *same* `_poll` batch. So `_poll` applies every
    progress event before acting on the terminal one, then snaps the row's
    fill to full and repaints *before* flipping its status — otherwise the
    fill would jump from wherever the easing had got to straight to "Done",
    never visibly reaching 100%.
  - **When a whole batch finishes — the queue's last job settles, or the
    active job's row is removed with nothing left behind it — `app.notify`
    posts "All queued jobs finished."** Every path that reaches that branch
    followed at least one job actually running (`start_queue`/`start_task`
    both refuse to call `_process_next` on an empty list to begin with), so
    this can't fire spuriously.

  Row thumbnails reuse the app's already-decoded frames
  (`app.thumb_frames`) or decode on a worker, never on the GUI thread.

**Encoding can no longer produce a silent byte-for-byte copy.** `Select`
(the Encoder/Audio Codec placeholder — see "Option compatibility" above)
auto-resolves to the source's own codec the moment a file is probed, and
`_validate_specific` refuses to queue a job that still has a
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
encoder, profile, level, speed, quality, resolution, source_height,
gpu_enabled, hdr_to_sdr, mastering_max_nits, max_cll, strip_video,
strip_audio, audio_streams`.

**Audio is a list, not four scalar keys**, because an Encoding job can carry
more than one *output* audio stream (the Audio Track dropdown + "Choose
Stream(s)" dialog — see "Multi-stream audio" above): `audio_streams` is
`[{"index": 0, "codec": "AAC", "bitrate": "192 kbps", "channels": "Stereo",
"sample_rate": "48000 Hz", "passthru": False, "language": "eng"}, ...]`, one
entry per *included* source stream, built by `_gather_settings` from
`_audio_stream_settings` (the per-stream dict last edited through the Audio
Codec/Bitrate/Channels/Sample Rate row + Passthru checkbox for whichever
stream the Audio Track dropdown currently shows) plus every other included
stream's own last-saved values, with `language` looked up fresh each time
from the probe (`_stream_language`) rather than stored per-stream like the
rest — it's a fact about the source stream, not something the user edits.
`mastering_max_nits`/`max_cll` are a fact snapshotted from the probed source
at queue time (see the HDR→SDR bullet above), not a user choice — carried
through so a job queued now still tone-maps against the source it was
actually queued against, even if the user swaps files before it runs.
`source_height` is the same convention, for `resolution` (the Resolution
dropdown's pick — see `core/formats.py`'s Resolution ladder and
`ffmpeg_vars.SCALE_VF` above).

Muxing's shape — **no codec keys at all**, since it never re-encodes:
`input_file, output_path, output_format, start_secs, duration_secs, av_sync,
video_tracks, strip_video, audio_tracks, strip_audio`.

**`video_tracks`/`audio_tracks` are lists too, one entry per *checked* row in
that panel's `TrackListBox`** (see "Muxing / Video" above) — the same
list-not-scalar shape `audio_streams` uses for Encoding, for the same reason:
a Mux job can carry more than one track of a kind, not just the single
`Auto`/`Track N` pick the tab used to offer. Each entry is `{"source":
"primary"/"external", "file": path|None, "index": N}` (`_track_args`), `N`
0-based among that *file's own* streams of that kind — what `-map
<input>:v:<index>` / `:a:<index>` addresses in `build_mux_command`. An empty
list for a kind that isn't stripped means "nothing checked", which
`_validate_specific` refuses to queue when the box actually had rows to
choose from (see "Muxing / Video" above).

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

Two modules, no UI code in either. **Everything runs through the bundled
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
  worker while the GUI thread may already be building an argv). The app runs
  it on a worker at startup and sets `app.deno_missing` →
  `DownloaderTab.set_deno_missing`. **Without Deno,
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
  `poll_events()` on the GUI thread, never backward, capped at 0.99 until the
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

- **Brand colour is theme-driven**, read from `T.theme` at paint time (or via
  the stylesheet) — never a hardcoded literal. Text on a primary/secondary
  fill uses `primary_text` / `secondary_text` (black or white by contrast).
  **STOP_RED is the one permanent exception** — destructive / halting states
  only, identical in every theme.
- **User-action signals fire only on user changes** (`Dropdown.picked`,
  `CheckBox.clicked`, `Switch.clicked`, `SegmentedButton.changed`); setting a
  value in code never fires them. That's what lets `_apply_settings` write a
  form without tripping handlers. Connect behaviour to those, not to
  `toggled` / `currentTextChanged`.
- **Clickables are `Qt.NoFocus`** (`controls.button()` does it): no focus
  rings, and focus never steals the Space keybind. Only text fields take
  focus — which is why `_Keybinds` also has to clear one's focus on a click
  elsewhere (see "Keybinds" above): a NoFocus click target would otherwise
  never trigger Qt's own default focus hand-off.
- **A custom-painted widget connects `T.theme.changed` to its own `update()`**
  and reads colours inside `paintEvent`, so a theme or appearance switch
  needs no rebuild.
- **Worker threads never touch a widget**: `run_async` / `emit_progress` only,
  and `QImage` (not `QPixmap`) across threads.
- **One constraint pass per tab** (`_sync_controls`) — no pairwise handlers.
- Layout goes through layouts (`hrow`, `labeled`, `stream_page`), never
  absolute positioning, except overlays that must float: the tab pipe, the
  Wave Loop layer, toasts.
- Every non-trivial method gets a one-line docstring; comments explain *why*
  (especially verified ffmpeg / yt-dlp / Windows behaviour).
- There are no `__init__.py` files; the subfolders work as implicit namespace
  packages. Imports are absolute from the repo root
  (`from ui.widgets.panels import DropBox`).

## Known issues / gotchas

- **Non-ASCII text looks mangled in the Windows console, not in the app.**
  Printing `— none —` or `— removed —` from a script shows `� none �` (Git
  Bash) or `â€” none â€”` (PowerShell's cp1252 decoding of UTF-8). The source
  files and runtime strings are correct UTF-8 — check code points
  (`[hex(ord(c)) for c in s]`) before "fixing" an encoding bug.
- **On Windows, `os.scandir()`'s `DirEntry.stat().st_size` is stale for a
  file another process still has open** — it's the directory listing's
  cached size, not updated until the handle closes. A growing download/merge
  output read as 0 bytes the whole time (confirmed); use
  `os.stat(entry.path)` (`ytdlp_runner._folder_bytes`).
- **Trim with an input-side `-ss` plus an output-side `-t`, never an
  output-side `-to`.** Verified by frame-counting real outputs: an input-side
  `-ss` rebases the output timeline to 0, so an output-side `-to X` acts as a
  *duration* of X, not "stop at X" (`-ss 00:21:36 -i in -to 00:21:41` makes a
  21m41s clip, not a 5s one). `ffmpeg_build._trim_kwargs` does it the safe
  way. `END_TIME`/`END_SECS` in `ffmpeg_vars` are only safe as an input-side
  `-to` paired with an input-side `-ss`.
- **`Dropdown.hidePopup` is also called by Qt on style changes** (a live theme
  switch), which is why `popupClosed` is gated on the popup having genuinely
  been open — otherwise Settings' theme preview reverted itself on every
  theme change.
- **`QApplication.quit()` re-sends close events** to open windows, including
  the one already inside `closeEvent` — hence `MainWindow._closing`.
- **A QDialog's `exec()` spins a nested event loop**; timers (the queue poll)
  keep firing under it. Post dialogs with `QTimer.singleShot(0, …)` from
  timer-driven code.
- **Setting Python attributes on a PySide object before `super().__init__()`**
  is unsafe — use class-level defaults for immutables or `_init_state()` (on
  MediaTab) for per-instance state.
- **Headless testing**: `QT_QPA_PLATFORM=offscreen` works for scripted runs and
  `widget.grab()` screenshots, but its virtual screen is tiny (the window came
  out 280px wide) — pin the window to 896x540 first. It has no system fonts,
  so register `assets/fonts` (as `main.py` does) or text renders as boxes.
  Offscreen can't exercise popup-window animation, DPI scaling or OS
  drag-and-drop; verify those on a real display. **A harness that skips
  `app.setStyleSheet(T.stylesheet())` (the line `main.py` runs right after
  building the `QApplication`) under-measures every `role="field"` caption's
  real height** — confirmed directly while tuning the DropBox-height
  invariant above: the same "Resolution" caption's `sizeHint()` measured 17px
  unstyled vs. 26px with the real stylesheet applied (the stylesheet's own
  `min-height: 26px` rule for that role), which was enough to make an
  over-height Video page read as safely under Overview's when it wasn't.
  Never trust a `sizeHint()`/layout-height measurement taken without the real
  stylesheet applied.
- GPU acceleration (`core/gpu.py`) picks a hardware encoder for H.264/H.265/
  AV1 only — VP8/VP9 and the mezzanine intermediates (ProRes/DNxHR/CineForm/
  FFV1) always run in software, hardware support for them being spotty to
  nonexistent across NVENC/QSV/AMF. Vendor detection reads WMI adapter names
  once per process and caches — a GPU swapped mid-run (eGPU unplugged,
  driver reinstall) needs an app restart to be picked up, same as every
  other process-lifetime capability cache in this file.
