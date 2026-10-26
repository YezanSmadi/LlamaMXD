# LlamaMXD — File-by-File Documentation

This document goes through every file in the repository and explains what it
contains and what it does. For narrative architecture notes, the rules each
tab enforces, known gotchas, and conventions, see [`CLAUDE.md`](CLAUDE.md) —
this file is a per-file reference instead.

Directory layout:

```
LlamaMXD/
├── main.py
├── requirements.txt
├── LICENSE.txt
├── .gitignore
├── .vscode/
│   └── settings.json
├── assets/
│   ├── llama.ico, LlamaMXD-Logo.svg, LlamaMXD-Logo2.svg, RCA Cable Yellow.svg
│   ├── audio-mute.svg, info.svg, expand.svg, shrink.svg
│   ├── select-multiple.svg, deselect-multiple.svg, undo.svg, redo.svg
│   ├── close-window.svg, maximize-window.svg, minimize-window.svg
│   ├── Wave Loop.json
│   └── fonts/  (Roboto-Regular.ttf, Roboto-Medium.ttf, Oswald-VariableFont_wght.ttf)
├── core/
│   ├── downloader.py
│   ├── ffmpeg_build.py
│   ├── ffmpeg_runner.py
│   ├── ffmpeg_vars.py
│   ├── formats.py
│   ├── gpu.py
│   ├── naming.py
│   ├── power.py
│   ├── presets.py
│   ├── priority.py
│   ├── startup_tab.py
│   ├── system_info.py
│   ├── theme.py
│   ├── tools.py
│   ├── utilities.py
│   ├── window_mode.py
│   ├── window_style.py
│   └── ytdlp_runner.py
└── ui/
    ├── app.py
    ├── scale.py
    ├── theme.py
    ├── tips.py
    ├── workers.py
    ├── tabs/
    │   ├── media_tab.py
    │   ├── muxing.py
    │   ├── encoding.py
    │   ├── downloader.py
    │   ├── queue.py
    │   └── settings.py
    └── widgets/
        ├── controls.py
        ├── panels.py
        ├── carousel.py
        ├── dialogs.py
        ├── frameless.py
        ├── toast.py
        ├── tracklist.py
        └── tooltip.py
```

Not shown: `settings.json`, `presets.json` (gitignored runtime files created on
first use) and `dependables/` (gitignored bundled tool binaries — see
`core/tools.py`).

There are no `__init__.py` files anywhere — `core`, `ui`, `ui/tabs` and
`ui/widgets` work as implicit namespace packages, and every import is
absolute from the repo root (e.g. `from ui.widgets.panels import DropBox`).
`main.py` puts the repo root on `sys.path`, and every file path the app reads
is `__file__`-anchored, so it can be launched from any directory.

`core/` never imports Qt; `ui/` is the only UI code.

---

## Root files

### `main.py`

The entry point. `main()` creates the `QApplication` (name `LlamaMXD`, Fusion
style — a consistent base for the stylesheet on every Windows version),
registers the bundled fonts (`_load_fonts` → `QFontDatabase.
addApplicationFont` for every `.ttf`/`.otf` in `assets/fonts`), adopts the UI
scale for the primary screen (`scale.set_factor(scale.fit(*scale.window_size(...)))`
— the stylesheet is generated from it, so it has to come first) and makes Roboto
the application font at `scale.font_px(13)`, with hinting off
(`QFont.PreferNoHinting`, inherited by every widget font — see `ui/scale.py`).
Then — in this order, because each needs the one before — `init_workers()` (the
GUI-thread signal bridge), `T.init_theme()` (the `ThemeManager`, which reads
`settings.json`) and `app.setStyleSheet(T.stylesheet())`. Only then does it
import `ui.app.MainWindow`, call `window.present()` (which shows it the way its
Window Mode wants — fullscreen or not) and enter `app.exec()`.

### `requirements.txt`

Pinned third-party dependencies (`pip install -r requirements.txt`; in
practice installed globally, no venv):

| Package | Version | Used for |
|---|---|---|
| `opencv-python` | 5.0.0 | `cv2` — seeks and grabs preview frames (`core/utilities.py`). |
| `numpy` | 2.4.1 | Crops the sidebar's RCA cable art to its drawn content (`ui/widgets/panels.py`); also a dependency of `opencv-python`. |
| `Pillow` | 11.3.0 | `PIL` — frame images, badge generation, thumbnail downloads. |
| `rlottie-python` | 1.3.8 | Renders the `Wave Loop.json` visualiser (`ui/widgets/carousel.py`); optional at runtime. |
| `ffmpeg-python` | 0.2.0 | Builds ffmpeg command lines (`core/ffmpeg_build.py`). |
| `future` | 1.0.0 | A dependency of `ffmpeg-python`. |
| `yt-dlp[default]` | 2026.08.19 | Dev environment for the Downloader; the app runs the bundled `yt-dlp.exe`. |
| `PySide6` | 6.11.2 | The UI toolkit (Qt 6). |

`ffmpeg.exe`, `ffprobe.exe`, `ffplay.exe`, `yt-dlp.exe` and `deno.exe` are not
pip packages — they're bundled in the gitignored `dependables/` folder and
resolved by `core/tools.py`.

### `LICENSE.txt`

The [GNU General Public License, version 3](https://www.gnu.org/licenses/gpl-3.0.html), or
(at your option) any later version — `GPL-3.0-or-later`. Every source file carries an
`SPDX-License-Identifier` line and a copyright line at its top, which is where the "or later" is
stated. Releases before this relicense (up to v0.5.0-beta.3) were published under the Unlicense
and stay public domain. The About tab in Settings shows GNU's short notice and has a
View License button that opens this file (a `.txt`, so Windows opens it in the default text editor).

### `licenses/`

The licenses of the programs, libraries and fonts LlamaMXD uses, in 15 files: `README.txt` (an index with
each component's version, license and source URL), one file per library or font (each opens with a header
and then holds that component's license texts, unedited), and a folder each for ffmpeg and yt-dlp — the
two GPL programs — with a `SOURCE.txt` pointing to their exact source. The GPL text for all of them is the
root `LICENSE.txt`. Unlike `dependables/`, the folder is tracked in git. The installer ships it, and `LICENSE.txt`,
beside the app; Settings > About has a button that opens it.

### `.gitignore`

Excludes Python bytecode/caches, virtual environments, the two local
preference files (`settings.json` — written by the Settings tab; `presets.json`
— saved recipes) and `dependables/` (the bundled tool binaries, each far over
GitHub's 100MB file limit, copied in by the release's setup wizard).

### `.vscode/settings.json`

`"python-envs.defaultEnvManager": "ms-python.python:system"` — tells VS Code's
Python extension to use the system interpreter rather than prompting for a
virtual environment, matching the project's no-venv setup.

### `assets/`

Everything the app loads at runtime, all read `__file__`-anchored.

- **`llama.ico`** — the window icon for the main window and every dialog.
- **`LlamaMXD-Logo.svg`** — the sidebar logo (a vector), rendered at 4x
  oversample and re-tinted to `primary_text` so it follows the theme
  (`ui/widgets/panels.py`'s `Sidebar._load_logo`).
- **`RCA Cable Yellow.svg`** — the RCA cable that plugs from the active nav
  button into the tab frame (`_TabPipe`, `ui/widgets/panels.py`). Drawn in its
  own fixed colours — not theme-tinted.
- **`audio-mute.svg`** — the red speaker-with-X badge drawn top-left on the
  preview while audio is stripped (`ui/widgets/carousel.py`); rendered exactly
  as authored.
- **`info.svg`** — the bottom-left info badge: a solid disc with the "i" cut
  out as a hole. `carousel._paint_info_badge` paints a plain disc in the glyph
  colour first, then this SVG (its `fill="currentColor"` string-replaced with
  the disc colour) on top, so the hole shows the glyph colour through.
- **`expand.svg`** / **`shrink.svg`** — the preview's expand / collapse corner
  icon.
- **`select-multiple.svg`** / **`deselect-multiple.svg`** / **`undo.svg`** /
  **`redo.svg`** — the Select All / Deselect All / Undo / Redo icons on Muxing's
  track boxes. Stroke-drawn in black; `controls._icon_svg` swaps the stroke for
  the button's own text colour.
- **`close-window.svg`** / **`maximize-window.svg`** / **`minimize-window.svg`** —
  the Borderless window's own Close / Maximise / Minimise icons
  (`ui/widgets/frameless.py`'s `WindowControls`). They ship in three different colours
  (black, near-black, navy), so `_tinted_svg` swaps every painted `fill` in the file text
  for the colour it wants and renders the result as a vector.
- **`Wave Loop.json`** — the Bodymovin/Lottie dot-wave animation shown in
  place of a stripped-video or audio-only preview, rendered by
  `rlottie-python`.
- **`fonts/`** — Roboto Regular and Medium (Apache 2.0), the app typeface,
  plus Oswald, all registered by `main.py` so text renders the same with or
  without them installed.

Every icon and badge is an SVG rendered through `QSvgRenderer`, not a scaled
bitmap: a raster downscaled to a badge's actual ~20-40px on-screen size showed
a visible stepped edge even through `SmoothPixmapTransform`, which a vector
doesn't have at any size.

---

## `core/` — the engine (no UI code)

### `core/theme.py`

Brand palettes, contrast helpers and the settings file.

- `THEMES` — ten palettes (`Lemon`, `Cupid`, `Lilac`, `Ranger`, `Noir`,
  `Luck`, `Vaporwave`, `Dreamsicle`, `Funk`, `Terminal`), each a flat-hex
  `primary` and `secondary`. Optional keys: `primary_hover` (Lemon keeps its
  historical `#e0b234`; Terminal names `#1c1c1c`, since black's derived hover is
  black again), `sidebar_text` (a colour, or the keyword `"primary"` /
  `"secondary"` — Funk's is `"white"`, Terminal's `"secondary"`),
  `swap_subtabs` and `swap_action_buttons` (both Terminal — see `get_theme`).
  `DEFAULT_THEME_NAME` is `Lemon`.
- `STOP_RED` / `STOP_RED_HOVER` — the theme-independent destructive red.
- `_darken(hex, factor=0.87)` — derives hover shades.
- `readable_text_on(hex)` — `"black"` or `"white"`, whichever has the higher
  WCAG contrast ratio against `hex` (via `_relative_luminance`).
- `disabled_text_on(hex, target_ratio=3.0)` — a grey solved to hit the target
  contrast against `hex`, on the side `readable_text_on` picks (via
  `_gray_hex_for_luminance`) — legible greyed-out text on a disabled button or
  dropdown that keeps its accent fill. 3.0 is WCAG's UI-component minimum;
  4.5 read as ordinary enabled text.
- `get_theme(name)` — the palette plus derived `*_hover`, `*_text` and
  `*_disabled_text`, falling back to the default theme for an unknown name. Also:
  `sidebar_text` (the sidebar's title and logo only — `primary_text` unless the
  theme names its own) and `subtab_active` / `subtab_inactive` (each with `_hover`
  and `_text`: the fills `SubTabBar` uses for the selected and the other tabs —
  primary / secondary, swapped for a `swap_subtabs` theme, whose black primary
  would vanish as a selected tab on the dark frame). `swap_action_buttons` is read
  by `ui/theme.py`, which aliases the `action` / `queue` button roles from it.
- `default_output_dir()` — `~/Videos/LlamaMXD Export`.
- `load_settings()` / `save_settings(settings)` — `settings.json` beside
  `main.py`: `theme`, `appearance_mode` (`System`), `default_save_location`
  (`default_output_dir()`), `gpu_enabled` (`True`),
  `downloader_separate_save` (`False`), `downloader_save_location` (`""`),
  `naming_template` (`core.naming.DEFAULT_TEMPLATE`), `when_done` (`Do
  Nothing`), `when_done_reset` (`True`), `priority_level` (`Normal`),
  `window_mode` (`Fixed`), `borderless_fullscreen` (`False`), `startup_tab`
  (`Encoding`). Missing keys or a missing/corrupt file fall back to those
  defaults, and so does a stored `naming_template` / `when_done` /
  `priority_level` / `window_mode` / `startup_tab` that's no longer valid (a
  hand-edited file) — checked against `core.naming`, `core.power`,
  `core.priority`, `core.window_mode` and `core.startup_tab`, which this module
  imports for that; `borderless_fullscreen` is only ever `True` if it is
  literally `true` in the file. The
  separate-save pair backs Settings' "Separate Save for Downloader" toggle —
  see `ui/tabs/settings.py` below.

### `core/tools.py`

Resolves the bundled tools to absolute paths. `find_tool(name)` returns an
absolute path or None; `tool_path(name)` the path or the bare name (so a
failed launch still raises the usual `FileNotFoundError` every caller turns
into a readable message); `tool_dir(name)` the containing folder (what
yt-dlp's `--ffmpeg-location` wants). Search order: beside the frozen app's
exe or in a `dependables/` folder next to it, then the repo's `dependables/`,
then PATH. Cached per process. **Every** ffmpeg/ffprobe/yt-dlp/deno launch
goes through it — and absolute paths matter for yt-dlp: a relative
`--js-runtimes deno:dependables/deno.exe` made it report "no JS runtime
found".

### `core/formats.py`

Pure data + lookups (no UI code): the container/codec compatibility matrix and
the option cascade that hangs off it. **One root — the output container.**
It decides which video and audio codecs are legal; the chosen video codec
then decides which profiles/levels exist and what kind of rate control
applies. Nothing flows the other way, which is what makes an illegal
combination unrepresentable rather than something a dialog has to catch.

- `SELECT` (`"Select"`) — the one "nothing picked/resolved yet" placeholder,
  shared by every derived list in this module (Encoder, Audio Codec, Audio
  Channels, Audio Sample Rate, Audio Bitrate). It's the default until a file
  is probed, at which point `EncodingTab` auto-resolves each of those
  controls to whatever the source already has (`core.utilities.probe_media`)
  — never a silent stream copy; that's Muxing's job. Encoder/Audio Codec
  additionally block the job in `_validate_specific` while left on `Select`
  with the stream actually present; Channels/Sample Rate/Bitrate don't need
  that, since omitting `-ac`/`-ar`/`-b:a` is always a valid "follow the
  source" outcome.
- `VIDEO_ENCODERS` / `AUDIO_ENCODERS` — display name → ffmpeg encoder id,
  read by `core/ffmpeg_vars.py` when building a real job's argv. Video:
  H.264/H.265/MPEG-4/MPEG-2/VP8/VP9/AV1 plus three mezzanine/archival
  intermediates — **ProRes** (`prores_ks`), **DNxHR** (`dnxhd` — the same
  ffmpeg encoder covers classic DNxHD and the modern DNxHR tiers), and
  **CineForm** (`cfhd`) — and lossless **FFV1**. Audio: AAC/AC3/E-AC-3/MP3/
  FLAC/Opus/Vorbis/ALAC/PCM.
- `PASSTHRU_ONLY_CODECS` (`{"DTS", "Dolby TrueHD"}`) / `is_passthru_only
  (codec)` — codecs `probe_media` can identify but this app has no re-encode
  path for at all (surround/Atmos transcoding is out of scope); a track
  holding one always passes through untouched. `EncodingTab` auto-forces its
  Passthru checkbox and greys the rest of the audio controls the moment one
  of these is probed, rather than leaving it stranded on `SELECT`.
- `_CONTAINERS` — the matrix, now four containers: `.mp4`, `.mkv` (the
  permissive catch-all — every codec this app has), `.mov` (the native
  container for the three professional intermediates above, alongside
  H.264/H.265/MPEG-4), and `.webm` (VP8/VP9/AV1 + Opus/Vorbis only — it
  shares no video codec with mp4/mov, which is why this table exists at
  all: before it, picking `.webm` left every encoder in the list illegal).
  Read by `containers()`, `video_codecs_for(container)` and
  `audio_codecs_for(container)` (both `SELECT`-first).
- `_ENCODER_SPECS` — per-codec `profiles`, `levels` and `quality`. Profile
  names are deliberately *not* shared between codecs, and CRF is not assumed
  universal: MPEG-4/MPEG-2 take a **qscale on 1-31**, VP8/VP9/AV1 use 0-63,
  H.264/H.265 use 0-51. `quality_for(encoder)` returns kind/label/range/
  default/end-labels together so the UI can re-range its slider — `None` for
  `SELECT` (nothing picked yet) *and* for ProRes/DNxHR/FFV1/CineForm, which
  genuinely have no CRF/qscale knob at all: ProRes/DNxHR's "quality" is a
  fixed-bitrate profile tier, CineForm's is its own `-quality` preset ladder
  riding the Profile dropdown slot instead (see `core/ffmpeg_vars.py`'s
  `_QUALITY_PRESET_ARGS`/`_NO_PROFILE_FLAG` below), and FFV1 is lossless. An
  empty `profiles`/`levels` list means the codec has none and the UI
  disables that dropdown rather than borrowing H.264's values.
- `_SPEED_SPECS` / `speed_values_for` / `speed_kind_for` / `speed_default_for`
  — per-encoder speed control: a named `-preset` ladder for H.264/H.265/AV1,
  or libvpx's numeric `-cpu-used` (+ a fixed `-deadline good`) for VP8/VP9.
  AV1's static fallback list is overridden by the installed ffmpeg's own
  reported preset range when available (`core.utilities.av1_preset_range` —
  SVT-AV1's ceiling varies a lot by build). Absent for MPEG-2/MPEG-4/`SELECT`.
- `audio_bitrates_for(codec)` — empty for copy/lossless codecs, whose rate
  isn't ours to set. `AUDIO_BITRATES`' own entries are display text, not
  raw numbers — `"96 kbps"` … `"768 kbps"`, then `"1 Mbps"`/`"1.5 Mbps"`
  once a value clears 1024 kbps (`_format_bitrate`; 1024/1536 are exact
  multiples of 1024 so the division is always clean). `bitrate_arg_for`
  converts a display value back to the plain `"<n>k"` ffmpeg's `-b:a`
  wants; `bitrate_display_for` snaps a probed bits/sec value to the
  closest display entry.
- `LOSSLESS` (`"Lossless"`) / `LOSSLESS_AUDIO` (`{"FLAC", "ALAC", "PCM"}`) /
  `is_lossless_audio(codec)` / `probed_audio_is_lossless(codec_name, profile)` — a
  lossless codec has no bitrate, and the Bitrate dropdown says `Lossless` for it rather
  than the `—` it shows when nothing is picked yet. `Lossless` is a display placeholder
  like `—`: the tabs' `_menu_value` reports it as `""`, so a job never carries the text.
  `probed_audio_is_lossless` answers for a *probed* stream, wider than
  `is_lossless_audio` because a source can hold codecs this app can't encode to: FLAC,
  ALAC, TrueHD/MLP and every `pcm_*` variant are lossless, and DTS is lossless only when
  its profile says `MA` (DTS-HD Master Audio — a DTS core or DTS-HD HRA is lossy).
- `containers_for(video_codec, audio_codec)` — **the Muxing inversion**:
  given the codecs a source holds, which containers can it be remuxed into
  without re-encoding. A `None` codec constrains nothing, so an unprobed
  file still offers everything.
- `SOURCE_RESOLUTION`/`RESOLUTIONS`/`resolutions_for(source_height)`/
  `resolution_height_for(resolution)` — Encoding Video's optional downscale:
  `"Source"` (no scaling) plus a fixed ladder (`"2160p"` … `"360p"`).
  `resolutions_for` caps the offered list to the source's own probed height
  or below — never an upscale — falling back to the full ladder when the
  height isn't known yet. `resolution_height_for` is the reverse lookup
  `ffmpeg_vars._scale_vf` uses to build the actual `-vf scale=-2:<height>`.
- `SOURCE_FPS` / `FPS_VALUES` / `fps_values_for(source_fps)` /
  `fps_arg_for(fps)` — Encoding Video's optional frame-rate change, the same
  idea as Resolution: `"Source"` (no change) plus a fixed ladder — `120`, `60`,
  `59.94`, `50`, `48`, `30`, `29.97`, `25`, `24`, `23.976`, then `12` / `8` for
  deliberately choppy output. **The three NTSC rungs are exact rationals on the
  command line**: `fps_arg_for` maps `"23.976"` / `"29.97"` / `"59.94"` to
  `24000/1001` / `30000/1001` / `60000/1001` (`_FPS_ARGS`), since the rounded decimal
  would retime a true NTSC source a hair off and drift audio sync over a long file.
  Because that value is no longer a bare number, comparisons go through
  `fps_number_for(fps)` (a float, `None` for `"Source"` — `float("24000/1001")`
  doesn't parse). `fps_values_for` caps the list to `"Source"` plus every rung at or
  below the source's own rate — never a speed-up — with a 0.1 tolerance so a true
  29.97/23.976 source still offers the round 30/24 just above it, and offers
  the full ladder when the rate isn't known yet. `fps_arg_for` is the reverse
  lookup `ffmpeg_vars._fps_arg` uses (`None` for `"Source"`). The FPS dropdown
  must stay as wide as Resolution's (83 reference px; `"23.976"` fits).
- `FFPROBE_VIDEO` / `FFPROBE_AUDIO` — ffprobe `codec_name` → display name,
  consumed by `utilities.probe_media`. Includes the two passthru-only codecs
  above (`"dts"` → `"DTS"`, `"truehd"` → `"Dolby TrueHD"`).
- `AUDIO_EXTENSIONS` — file extensions treated as audio-only when no probe
  can run; only decides whether the preview shows the Wave Loop visualiser
  instead of video thumbnails.
- `short_name(codec)` — `"H.264 (x264)"` → `"H.264"`, for the width-starved
  Overview rundown (a no-op for every current codec, kept defensively).
  `coerce(value, allowed, fallback)` snaps a value into a list and reports
  whether it changed.

### `core/naming.py`

The output file-name template Settings stores (`DEFAULT_TEMPLATE` =
`{source}-{title}`, held on `app.naming_template`) and the tokens it can hold.
Pure data + string handling, no UI code. Tokens split by *when* they can be
known:

- **Live** (`LIVE_TOKENS`) — `{source}` (the input's name; a download's site),
  `{title}` (the embedded title tag; a download's video title), `{chapters}`
  (`12ch`). Facts about the picked input, so a tab fills them into the Save
  field as soon as it has them and refills as the probe lands.
- **Queue-time** (`QUEUE_TOKENS`) — `{date}` `{time}` `{creation-time}`
  `{quality}` `{bitrate}`. They depend on the clock or on settings still being
  changed, so the Save field shows them as literal text and `resolve_path` fills
  them into the job's own output path when it's queued.

`ALL_TOKENS`; `unknown_tokens(template)`; `template_error(template)` (why a
template can't be a file name — empty, illegal characters, unknown `{token}` —
or `None`; what Settings' naming field validates against); `render(template,
values, tokens)` (fills only the named tokens, leaves other braces literal, and
**a token that resolves to nothing takes its neighbouring separator with it**, so
`{source}-{title}` on an untitled file is `clip`, not `clip-`); `finalize(stem)`
(Windows-safe: illegal characters, trailing dots, length cap); `render_live`
(the Save-field name) and `resolve_path` (the queue-time pass; a name with no
braces comes back unchanged). Value builders: `media_live_values(path, info)` /
`download_live_values(info)` for the live pass, `media_queue_values(path, info,
settings)` / `download_queue_values(info, settings)` for the queue-time one —
`{quality}` is `crf22`/`q5` for an Encode (empty for Muxing and rate-control-less
codecs) and the Resolution pick for a download; `{bitrate}` is the source's
overall bitrate (a download's is the chosen streams' size over its length);
`{creation-time}` is the media's creation tag, else the file's, or a download's
upload date.

### `core/power.py`

Settings' "When Done" — what the machine (or the app) does once the Queue has
finished its last job. No UI code. `ACTIONS` = Do Nothing / Shutdown / Sleep /
Hibernate / Lock System / Log Off / Quit LlamaMXD; `SYSTEM_ACTIONS` (Shutdown,
Sleep, Hibernate, Log Off) are the four that end or suspend the user's session,
which the UI gives a cancellable countdown first. `command_for(action)` is the
`shutdown.exe` argv for Shutdown / Hibernate / Log Off (`/t 0`, and no `/f` so
an app holding unsaved work can still object); `perform(action)` carries it out
and returns an error string or `None`. Sleep calls `SetSuspendState` through
ctypes rather than `rundll32 powrprof.dll,SetSuspendState`, which is known to
hibernate instead when hibernation is enabled; Lock calls `LockWorkStation`.
`Quit` isn't handled here — closing the app is the window's job.

### `core/priority.py`

Process priority for the jobs the Queue runs (Settings' "Priority Level").
`LEVELS` = High / Above Normal / Normal / Below Normal / Low (`DEFAULT_LEVEL`
Normal), mapped to Windows priority classes by the names Task Manager uses.
**Realtime is deliberately not offered** — it can starve the mouse and keyboard
drivers. `creation_flag(level)` is the `Popen(creationflags=...)` bit that starts
a process at a level; `set_process_priority(pid, level)` moves a running one
(`OpenProcess` + `SetPriorityClass` via ctypes) and returns whether it worked;
`get_process_priority(pid)` reads it back, for verification. Read by
`core/ffmpeg_runner.py` and `core/ytdlp_runner.py`.

### `core/window_mode.py`

Settings' "Window Mode" — plain names only. `WINDOWED` (the usual title bar and
frame, freely resizable), `BORDERLESS` (no title bar or frame; resizable, optionally
fullscreen) and `FIXED` (the reference-shaped window, not resizable);
`MODES` = [Windowed, Borderless, Fixed], `DEFAULT_MODE` = Fixed. Turning a name
into window flags and size limits is `MainWindow._apply_window_mode`'s job — none of
that is UI-free.

### `core/startup_tab.py`

Settings' "Startup Tab" — which tab the app opens on. `TABS` = Muxing / Encoding /
Downloader / Queue, matching `MainWindow.tabs` (Settings itself isn't offered: it is
a place to visit, not to live), `DEFAULT_TAB` = Encoding.

### `core/window_style.py`

Win32 window styles Qt doesn't keep in step when a live window's frame or size limits
change (Settings' Window Mode does exactly that), through ctypes — every function is a
no-op off Windows. `set_maximize_box(hwnd, enabled)` sets `WS_MAXIMIZEBOX`
explicitly (off for Fixed, on otherwise): Fixed -> Windowed left the button disabled and
Borderless -> Fixed left it enabled on a pinned window, where a click just moved the
window to the top-left at the same size. `set_dark_titlebar(hwnd, dark)` sets DWM's
`DWMWA_USE_IMMERSIVE_DARK_MODE` (attribute 20; 19 before Windows 10 2004): Qt only sets
it when it creates a native window that already has a frame, so a window launched
Borderless and later given a frame came up with a white title bar over a dark app.
Setting the attribute doesn't repaint the caption on Windows 10, so it then bounces
`WM_NCACTIVATE` (off, then on), putting the window's real active state back so a
background window doesn't suddenly look focused. Called from
`MainWindow._apply_window_mode` / `_sync_titlebar`.

### `core/presets.py`

Named codec/quality recipes, persisted to a gitignored `presets.json` at the
repo root shaped `{tab: {name: settings}}`.

A preset is a **recipe, not a job**: `PRESET_KEYS` limits what's stored to
the container, the `av_sync` flag and the codec/quality choices (including
the Resolution and FPS picks), and
deliberately excludes the trim, the input/output paths and (on Muxing) the
track picks — so loading one can't quietly re-trim a clip or repoint its
output. Presets are scoped
per source tab, since Muxing and Encoding no longer share a settings shape.

`names(tab)` / `menu_values(tab)` (the latter prepends `NONE_LABEL`,
`"— none —"`), `get(tab, name)`, `save(tab, name, settings)` (runs
`extract` first, so only recipe keys land on disk), `delete(tab, name)`,
`exists(tab, name)`. Every read is best-effort — a missing or corrupt file
yields `{}` rather than raising — and `_write_all` swallows `OSError` so a
failed write can't take the app down mid-interaction.

### `core/gpu.py`

GPU detection and hardware-encoder selection for the Settings tab's Hardware
Acceleration switch. No UI code. **Only a dedicated (discrete) GPU counts** — an
integrated one is still listed in the system info, but never offered for
acceleration; with none present the switch is forced off and greyed out.

- `adapter_names()` — every video controller's display name, via `wmic path
  win32_VideoController get name` (PowerShell's `Get-CimInstance
  Win32_VideoController` as a fallback for a Windows build where `wmic` has
  been removed), cached for the process's lifetime.
- `is_dedicated(name)` / `dedicated_adapters()` — WMI has no reliable
  "discrete" flag (`AdapterRAM` is a 32-bit field that caps at 4GB and reports
  an iGPU's carve-out as if it were VRAM), so adapters are classified by name.
  Every NVIDIA adapter counts (there are no integrated NVIDIA desktop parts);
  AMD is dedicated on `RX` / `PRO` / `VII` / FirePro / Instinct / R5-R9 / HD
  numbering unless the name is an APU's (ends in "Graphics", or a bare Radeon
  6xx/7xxM); Intel is dedicated only for Arc A-/B-series, Data Center GPU and
  Flex — "Arc(TM) Graphics" (Meteor Lake) and every UHD / Iris / HD Graphics is
  integrated. (`_adapter_vendor(name)` maps a name to its vendor.)
- `vendor()` — the vendor to hardware-encode with: `"nvidia"` / `"amd"` /
  `"intel"`, the first in that priority among the *dedicated* adapters, or `""`
  when there are none (integrated graphics alone never count). `has_dedicated()`
  is whether Hardware Acceleration can be offered at all. `display_name()` is
  the dedicated adapter this app would accelerate with, else the first detected
  adapter (an iGPU is still worth showing), for the Settings system-info block.
- `available_encoders()` — every `*_nvenc`/`*_qsv`/`*_amf` id the installed
  ffmpeg build actually reports (`ffmpeg -encoders`), cached like
  `core.utilities.supports_fps_mode`.
- `hw_encoder_for(codec)` — the hardware encoder id for a
  `formats.VIDEO_ENCODERS` display name (H.264/H.265/AV1 only — the one set
  every vendor's consumer encoder actually supports) on this machine's
  vendor, or `None` if there's no supported vendor, no mapping for that
  codec, or this ffmpeg build doesn't have the encoder compiled in. Read by
  `core.ffmpeg_vars.derive()` when `gpu_enabled` is set.
- `rate_control_kwargs(hw_encoder, quality)` — the rate-control flags
  standing in for `-crf` on a hardware encoder (`-rc vbr -cq` for NVENC,
  `-global_quality` for QSV, `-rc cqp -qp_i/-qp_p/-qp_b` for AMF), quality
  clamped to 0-51. Read by `core.ffmpeg_build.build_encode_command`.
- `summary_label()` — the human-readable line the Settings tab shows under
  the switch: the GPU, its vendor's own encoder brand name (`_ENCODER_BRAND`
  — "NVENC" / "Quick Sync" / "AMF", not a generic "hardware encoding"), and
  which codecs it would accelerate — or "No dedicated GPU detected — hardware
  acceleration is unavailable." when there isn't one.

### `core/system_info.py`

CPU / RAM / disk facts for the Settings tab's system-info block. No UI code;
every lookup is best-effort and returns a placeholder rather than raising.

- `cpu_name()` — the CPU's marketing name from the registry
  (`HARDWARE\DESCRIPTION\System\CentralProcessor\0`'s `ProcessorNameString`;
  `platform.processor()` only returns the raw architecture string on
  Windows), cached.
- `ram_total_bytes()` — installed physical RAM via `GlobalMemoryStatusEx`
  (ctypes; no `psutil` dependency), cached.
- `format_bytes(n)` — `"512.3 GB"`, binary (1024-based) units, matching how
  Windows itself reports sizes.
- `disk_usage(path)` — `(total_bytes, free_bytes)` for the drive holding
  `path` (falling back to its parent directory for a not-yet-created path),
  or `(None, None)` if that doesn't resolve to a reachable drive.

### `core/utilities.py`

A stateless helper module: preview-frame extraction, ffprobe-based media
probing, HDR tone-mapping helpers, and a few one-per-process ffmpeg
capability checks. No UI code.

**Thumbnails**

`extract_video_thumbnails(video_path, count=10)`: `count` frames spread evenly
across the video's *interior* (`_interior_sample_frames` — the fractions
`(i+1)/(count+1)`, deliberately avoiding a black/blank first frame and an
end-credits/fade-out last frame): OpenCV first (`_extract_thumbnails_cv2` — opens
`video_path` with `cv2.VideoCapture`; for each point it seeks, reads, converts
BGR→RGB and wraps the frame in a `PIL.Image`; it stops after three failed seeks
in a row, each failed seek being ~0.3s), and **ffmpeg only if OpenCV produced
nothing at all** (`_extract_thumbnails_ffmpeg`). Returns 1–`count` images
(shorter if the clip is too short or some seeks fail), a single first-frame read
when the container reports no usable frame count, or `[]` if nothing decodes at
all.

`_extract_thumbnails_ffmpeg(video_path, count)`: the fallback for a file OpenCV
can't seek — it works from the container's frame count, which is wrong for a file
whose header duration is an end timestamp (see `_effective_duration` below), so
every interior seek lands before the first real frame. One short ffmpeg process
per frame at the same fractions of the file's real length (`probe_duration`,
corrected), as input-side `-ss` seeks (which count from the file's own start
whatever its timestamps say), scaled to at most `_PREVIEW_MAX_WIDTH` (1920) wide,
as **rgb24** PPM over a pipe — `format=rgb24` is load-bearing: a 10-bit source
otherwise comes out as a 16-bit PPM, which Pillow needs ~1.4s a frame to read
(0.01s as 8-bit). It gives up after `_PREVIEW_MAX_MISSES` (3) misses in a row with
none found, and returns `[]` for a file whose first video stream is cover art
(`_has_previewable_video`, checks `attached_pic`) so an audio file keeps its Wave
Loop instead of turning into a "video" of ten identical frames.

`extract_video_thumbnail(video_path)`: back-compat single-frame shim, still
used by the Queue tab's per-row thumbnail.

`extract_hdr_tonemapped_thumbnails(video_path, count=10)`: like the above,
but for a real HDR source — cv2's plain decode has no color management and
just clips/rescales the wide-range PQ/BT.2020 values into a washed-out 8-bit
picture, not a preview of the actual export. This instead runs one real
short-lived ffmpeg process **per frame** (an approximate input-side `-ss`
seek, then a single-frame decode through the exact same `libplacebo_tonemap_vf`
chain `core/ffmpeg_build.py` uses for the real encode), targeting the same
frame indices `extract_video_thumbnails` samples so the two sets stay
index-aligned. Returns `[]` if `supports_libplacebo()` is false or the
geometry probe fails — callers must check the former to tell "no HDR" apart
from "libplacebo unavailable". Runs subprocesses; keep off the GUI thread
(`MainWindow.start_hdr_render` does).

**Media probing**

`probe_media(path)`: best-effort `ffprobe`, returning a dict with —
`container`, `video`/`audio` (display codec names via `formats.FFPROBE_*`),
`video_profile`/`video_level` (codec-aware conversions — see
`_normalize_video_profile`/`_ffprobe_level` below), `hdr` (bool, from the
stream's `color_transfer` tag — `smpte2084`/`arib-std-b67`), `width`/
`height`/`duration`/`file_size`, `audio_channels`/`audio_sample_rate`/
`audio_bitrate` (display values for the first audio stream, via
`formats.channels_display_for`/`sample_rate_display_for`/
`bitrate_display_for`), `has_video`/`has_audio` (whether a stream of that
kind exists *at all* — `False` only once the probe ran and found none,
`None` while unknown, never conflated with "unrecognized codec"),
`fps` (the video stream's `r_frame_rate` as a plain float — `_parse_frame_rate`
converts ffprobe's rational `"24000/1001"` string to 23.976, or `None` for a
missing / `"0/0"` value; `fps_text` turns one back into display text: 23.976023 →
`"23.976"`, 30.0 → `"30"`), and the container's `title` / `chapters` (a count) /
`bit_rate` (overall bits per second) / `creation_time` — the values behind the
`{title}` `{chapters}` `{bitrate}` `{creation-time}` naming tokens
(`core/naming.py`), each `None` when the file has none. `audio_streams` (every
audio stream, each described by
`_describe_audio_stream` — codec/channels/rate/bitrate/language, plus a `lossless` flag
(`formats.probed_audio_is_lossless`) — for the
Encoding tab's multi-track picker), `video_streams` (every video stream, each
described by `_describe_video_stream` — codec, profile, level, size, `fps`,
bit rate (`_bitrate_text`), `color_format` (`"10-bit 4:2:0"`, from `pix_fmt` /
`bits_per_raw_sample` — `_describe_pix_format`) and `hdr_display` (`HDR10` / `HLG` / `SDR` — anything that
isn't PQ/HLG counts as SDR, the same call `hdr` makes) — for Muxing's track rows and
"Add Stream(s)" picker), and, only for HDR content,
`mastering_max_nits`/`mastering_min_nits`/`max_cll`/`max_fall` (a separate
frame-level probe, `_probe_hdr_static_metadata` — ffprobe only exposes this
on a decoded *frame*'s side data, not the stream-level query the rest of
this dict comes from).

This is what gives `SELECT` a concrete meaning: `EncodingTab` auto-resolves
Encoder/Audio Codec/Profile/Level/Channels/Sample Rate/Bitrate from it, lets
both tabs default the output container to the input's own, and (Muxing,
which never re-encodes) drives `formats.containers_for`. Entirely optional —
every failure path returns an all-`None`/`[]` "unknown" shape rather than
raising. Runs a subprocess with `CREATE_NO_WINDOW`; keep off the GUI thread
(`MainWindow` runs it on the same worker as the thumbnails).

`_normalize_video_profile(codec_name, profile)`: ffprobe's raw `profile`
string already matches this app's own display names for H.264/HEVC/etc., but
not for ProRes (`"standard"` → `"422"`, `"hq"` → `"422 HQ"`, …) or DNxHR
(`"DNXHR HQX"` → `"HQX"`); classic legacy DNxHD's bare `"DNxHD"` profile has
no DNxHR-tier equivalent and is deliberately left unmatched.

`_ffprobe_level(codec_name, level)`: **not one universal formula** — H.264's
raw `level` is 10× the display value, HEVC's is 30× (confirmed empirically:
raw `120` is really "4.0", not "12.0"), AV1's is a `seq_level_idx` table
lookup (`_AV1_LEVELS`), and MPEG-2's is a named-level code
(`_MPEG2_LEVEL_NAMES`, mirroring `ffmpeg_vars._LEVEL_ARGS["MPEG-2"]` in
reverse) rather than a major.minor number at all.

`probe_duration(path)`: best-effort length in seconds, used as the Queue's
progress denominator for an untrimmed job (`FfmpegJob` calls it off the GUI
thread) and to place the ffmpeg fallback's preview frames. Same
all-`None`-on-failure contract, and the same corrected length as
`probe_media`'s `duration`.

`_effective_duration(path, header, start)` / `_tail_end_time(path, start,
header)`: **a file's real length can differ from its header.** A clip cut out of
a film with its original timestamps kept starts far into the timeline (one
started at 5465.5s) and its header duration is the END timestamp, not the length
(5501.162s for a 35s clip). ffmpeg itself is unaffected — it rebases every output
to 0 — but the tooltip, the `{bitrate}` token, the queue's progress denominator and
OpenCV's frame count (so every preview seek) were all wrong. The rule: a start time
at or under `_START_TRUST_SECS` (1s) trusts the header (nearly every file, no extra
work); otherwise `_tail_end_time` seeks to the last ~10s and reads on to the end (one
~40ms ffprobe call) for the file's last real timestamp, and the header is treated as
an end time — length = header − start — only if that timestamp sits within
`_END_MATCH_SECS` of `header` and not of `start + header` (an honest header on a
late-starting file, e.g. broadcast TS). Anything unclear keeps the header, so it is
never worse than trusting it. **The interval needs an explicit end** (`T%end`): the
open-ended `T%` returned an empty result with rc 0 on 8 of 30 runs of the identical
command, where the closed form was 30/30; one retry covers the rest.
`_probe_frame_geometry` (the HDR→SDR preview's frame count) applies the same
correction only when OpenCV's implied length is over 1.5x the real one, so a merely
variable-frame-rate file keeps cv2's count and the tone-mapped set stays
index-for-index aligned with the raw one.

**HDR tone-mapping**

`libplacebo_tonemap_vf(peak_detect=True)`: builds the BT.2390 `-vf
libplacebo=...` filter string shared by the real encode
(`core/ffmpeg_build.py`) and the HDR preview thumbnails above — kept here
rather than in `ffmpeg_build.py` specifically so both can read the identical
string without a circular import. `peak_detect` isn't a fixed default:
callers should pass `False` only when the source has *both* a mastering peak
**and** a genuine nonzero MaxCLL (confirmed empirically both ways — trusting
a real MaxCLL cuts highlight clipping 87-98% on one real HDR source, while
trusting a mastering peak alone with no real MaxCLL measurement makes
another real source's output measurably dimmer/lower-contrast). `apply_
dolbyvision=true` is explicit (Profile 5/8.x sources embed their own dynamic
RPU metadata on top of the BT.2390 base layer). `VULKAN_DEVICE_FLAGS`
(`-init_hw_device vulkan=vk -filter_hw_device vk`) lives alongside it — the
bare filter segfaults outright on a real hybrid dual-vendor GPU with several
Vulkan overlay layers installed unless the device is created explicitly.

`verify_hdr_sdr_tag(path)`: best-effort post-encode check — does `path`'s
video stream actually read as SDR now? `True`/`False`/`None` (probe failed —
"unknown", not "wrong"). Used by `FfmpegJob` right after an HDR→SDR job
finishes as a safety net on top of the filter already being verified to work
at development time — catches a future ffmpeg/libplacebo regression or an
unusual muxer that doesn't propagate the requested color tags.

**Capability checks** — each is a lazy, process-lifetime cache (`None` means
"not checked yet"), since re-running the underlying `ffmpeg`/`ffprobe`
subprocess every job would be wasted work for an answer that can't change
mid-run:

- `supports_fps_mode()` — whether the installed ffmpeg has `-fps_mode`
  (5.1+); parses `ffmpeg -h full`. Any failure caches `False`, the safe
  fallback (an older `-vsync cfr` still runs).
- `libplacebo_problem()` — why HDR→SDR isn't available, or `None` when it is:
  `LIBPLACEBO_MISSING` (the filter isn't in `ffmpeg -filters`) or
  `LIBPLACEBO_NO_VULKAN` (it is, but a one-frame probe of the real
  `libplacebo_tonemap_vf()` on an explicit `VULKAN_DEVICE_FLAGS` device doesn't
  run — a crash, a hang and a missing ffmpeg all count). **Being listed proves
  nothing about being runnable**, so it is two checks (`_libplacebo_listed`,
  `_libplacebo_runs`), cached behind a lock (a caller arriving mid-probe waits for
  that answer). The probe is a real ffmpeg run (~0.7s here), so `MainWindow` warms it
  on a worker at startup. `libplacebo_problem_text()` is the one sentence of wording
  the switch's tooltip, the queue-time dialog and the builder's `ValueError` all use.
- `supports_libplacebo()` — `libplacebo_problem() is None`. A failure the probe can't
  foresee still surfaces as a normal Failed job.
- `av1_preset_range()` — `(lo, hi)` for SVT-AV1's `-preset`, parsed from
  `ffmpeg -h encoder=libsvtav1` (confirmed to swing wildly by build — `(0,
  8)` on one install, `(-2, 13)` after updating ffmpeg on the same machine).
  Falls back to `(0, 8)` if parsing fails.

### `core/ffmpeg_vars.py`

Flattens one queued job's settings dict into module-level globals
(`INPUT_FILE`, `START_TIME`, `VIDEO_CODEC_ARG`, …) — `load(settings,
source_tab)` populates them; `derive(settings, source_tab)` is the pure
version returning the same values as a plain dict. Always read through the
module (`from core import ffmpeg_vars as v`), never `from ... import NAME`
(which copies the value once and misses a later `load()`).

Most variables come in a raw UI-display form and, where they differ, an
ffmpeg-ready `*_ARG`/`*_KWARGS` form — the translation tables at the top of
the file (`_PROFILE_ARGS`, `_PIX_FMT_ARGS`, `_QUALITY_PRESET_ARGS`,
`_LEVEL_ARGS`, `_CHANNEL_COUNTS`) cover the encoders whose ffmpeg option
values don't just match their display name: ProRes/DNxHR/CineForm each need
an explicit `-pix_fmt` (H.264/HEVC/etc. happily follow whatever the source
decodes to; `dnxhd` outright refuses to run without one), CineForm's
"profile" slot is really its own `-quality` preset name
(`_QUALITY_PRESET_ARGS`/`_NO_PROFILE_FLAG` — it must never fall through to a
literal `-profile:v`, which `cfhd` doesn't have), and MPEG-2's levels are
named codes rather than numbers.

**`AUDIO_STREAMS` is the one list-shaped variable, not a scalar** — an
Encoding job can include more than one *output* audio stream (see `ui/tabs/encoding.py` below), each with its own codec/bitrate/channels/sample-rate.
`_audio_stream_args(entry)` turns one settings-dict stream entry into its
ffmpeg-ready form (`{"src_index", "source", "file", "codec_arg", "bitrate_arg",
"channels_arg", "sample_rate_arg", "language"}` — `source`/`file` name the input a stream is
read from, so `build_encode_command` can map one added from another file from its own
`ffmpeg.input`); a Passthru stream (forced
on for `formats.is_passthru_only` codecs, or a deliberate pick) always
comes out `"copy"`/`None`/`None`/`None`/`None` regardless of its other
display fields — `language` is `None` there too, since nothing about a
copied stream's tags goes stale (see `core/ffmpeg_build.py`'s
stale-metadata note below).

**`RESOLUTION`/`SOURCE_HEIGHT`/`SCALE_VF`** back Encoding Video's Resolution
downscale (`core/formats.py`'s `RESOLUTIONS` ladder). `SOURCE_HEIGHT` is the
probed source height snapshotted at queue time, same convention as
`MASTERING_MAX_NITS`/`MAX_CLL` below; `SCALE_VF` (`_scale_vf`) is the
resulting `-vf` fragment (`"scale=-2:<height>"`), `None` for `"Source"` or
when there's no real downscale to do — re-validated against `SOURCE_HEIGHT`
at derive time rather than trusting the caller, since a saved preset applied
to a smaller/differently-probed file could still name a rung too tall for it.

**`FPS`/`SOURCE_FPS`/`FPS_ARG`** are the identical pattern for Encoding Video's
frame-rate change (`core/formats.py`'s `FPS_VALUES`): `SOURCE_FPS` is the probed
source rate snapshotted at queue time, and `FPS_ARG` (`_fps_arg`) is the `-r`
value — an exact rational (`24000/1001`) for the three NTSC picks, a plain number
otherwise — or `None` for `"Source"` or when the pick is no longer at or below the
source's own rate (compared with `formats.fps_number_for`; the same re-validation
`_scale_vf` does, for the same reason).

`MASTERING_MAX_NITS`/`MAX_CLL` carry the source's probed HDR static
metadata through (snapshotted at queue time by `EncodingTab._gather_
settings`, not read live) — both together decide `build_encode_command`'s
`peak_detect` argument; see `core/utilities.py`'s `libplacebo_tonemap_vf`
above.

A key belonging to the other tab keeps a default that happens to be
correct for it too — e.g. a Mux job's `VIDEO_CODEC_ARG` comes out `"copy"`,
exactly right since Muxing always is. Muxing never touches `AUDIO_STREAMS`
at all; it maps its own `VIDEO_TRACKS`/`AUDIO_TRACKS` — **lists**, one entry
per *checked* row in that panel's `TrackListBox` (`{"source": "primary"/
"external", "file": path|None, "index": N}`), not the single scalar
`AUDIO_TRACK`/`AUDIO_TRACK_INDEX` a much earlier single-dropdown UI used —
straight through `build_mux_command`. (Those scalar `VIDEO_TRACK*`/
`AUDIO_TRACK*` globals still exist in the module but `derive()`/`load()`
never populate them any more; dead code left over from before the
multi-track rewrite.)

**Trim gotcha, verified against real ffmpeg output**: an input-side `-ss`
rebases the output timeline to 0, so an output-side `-to` then behaves as a
raw *duration* equal to its own value, not "stop at this timestamp" — never
pass `END_TIME`/`END_SECS` as an output-side `-to` paired with an
output-side (or absent) `-ss`. `core/ffmpeg_build.py`'s `_trim_kwargs`
always uses input-side `-ss` + output-side `-t` (`DURATION_TIME`), which
sidesteps the whole issue.

### `core/ffmpeg_build.py`

Builds an ffmpeg-python `Stream` from whatever's currently loaded in
`core/ffmpeg_vars.py`. Two separate builders — `build_mux_command()` (always
`-c copy`; maps whichever tracks/external files the Muxing tab's track
pickers selected) and `build_encode_command()` (re-encodes whichever stream
isn't stripped) — rather than one function covering both, mirroring the
Muxing/Encoding split described under `ui/tabs/muxing.py` /
`ui/tabs/encoding.py` below. `build_command()` dispatches on
`ffmpeg_vars.SOURCE_TAB`.

`build_encode_command` assembles one `-map`-able stream per kept
video/audio track — a bare `ffmpeg.output(stream, ...)` with no explicit
`-map` only ever gets ffmpeg's own "one best video + one best audio"
default, which breaks the moment more than one output audio stream is
possible. **Per-stream option suffixes (`-c:a:0`, `-b:a:0`, …) address the
stream's position in the *output* file, not its source index** — confirmed
directly that an unqualified `-ac:0`/`-ar:0` (unlike `-c:a:0`/`-b:a:0`,
which already carry the `a:` type qualifier) counts across every output
stream including video, silently landing on the kept video stream instead
and shifting every audio value onto the next stream's slot; the code always
emits the qualified `-ac:a:{i}`/`-ar:a:{i}` form.

When `FPS_ARG` is set, `build_encode_command` sets the `r` output option
directly — `-r` is a plain output option, not a `-vf` filter, so it has no
interaction with the tonemap/scale filter chain below.

When `ffmpeg_vars.HW_ENCODER` is set (GPU acceleration resolved a hardware
encoder for this job — see `core/gpu.py`), the video stream's rate control
comes from `gpu.rate_control_kwargs(HW_ENCODER, QUALITY)` instead of
`-crf`/`-q:v` — none of NVENC/QSV/AMF take either flag.

HDR→SDR (`uses_hdr_tonemap()` gates it) adds `core.utilities.
libplacebo_tonemap_vf(peak_detect=...)` as (part of) `-vf`, plus explicit
`-color_primaries/-color_trc/-colorspace bt709` output tags (libplacebo's
target colorspace doesn't reliably propagate to the output stream's own tags
on its own). Raises `ValueError` (with `libplacebo_problem_text()` — missing filter or no
working Vulkan) if `HDR_TO_SDR` is set but
`supports_libplacebo()` is false — should be unreachable in practice
(`EncodingTab._validate_specific` blocks it first), but this is the last
line of defense, caught by `QueueTab._process_next`'s "couldn't build the
ffmpeg command" Failed-task path. **The Resolution downscale
(`ffmpeg_vars.SCALE_VF`) chains onto that same `-vf`**, after the tonemap
filter when both are active (one comma-joined `-vf`, independent of
`HDR_TO_SDR` otherwise) — safe to chain directly since libplacebo's own
filter string already ends back on a plain software `yuv420p` frame, no
format conversion needed in between.

**A re-encoded stream's stale per-track statistics tags are stripped.**
ffmpeg's default metadata mapping otherwise carries a *source* stream's own
Matroska tags (`title`, `BPS-<lang>`, `DURATION-<lang>`, …) onto the output
stream even when it's genuinely re-encoded to a different codec/bitrate/
length — confirmed directly (a trimmed 2-minute re-encode of an 87-minute
source still reported the source's own bitrate via its stale `BPS-eng` tag).
`build_encode_command` always adds `-map_metadata:s:v:0 -1` for the kept
video stream (Encoding never copies video when kept, so this is
unconditional); for audio, only per genuinely re-encoded (non-Passthru)
`AUDIO_STREAMS` entry, `-map_metadata:s:a:{i} -1` wipes it and
`-metadata:s:a:{i} language=<lang>` immediately reapplies just the
language tag (a video track's language isn't used for playback the way an
audio one is, so it's simply dropped there instead).

`-map_metadata:s:v:0 -1` also switches off ffmpeg's default per-stream metadata
copy for *every* stream, which used to strip the language/title from Passthru
(`-c:a copy`) audio. So each straight-copy audio entry gets
`-map_metadata:s:a:{i} <input>:s:a:{src_index}` — from the stream actually mapped, where
`<input>` is that file's real `-i` position (`_input_positions`: ffmpeg-python numbers
inputs by graph order and drops unmapped ones, so it isn't always 0).

`-strict -2` (experimental compliance) is set **globally, not audio-scoped**
— confirmed a real TrueHD-in-MP4 source still hard-fails with `-strict:a -2`
alone (the muxer's own compliance gate, not the audio codec context, is what
objects). `+faststart` is added only for `.mp4`/`.mov` output (a private,
purely cosmetic mp4/mov-muxer option; this build happens to ignore it
silently elsewhere, but that's not a documented guarantee).

`compile_command(output_path)` returns the full argv `core/ffmpeg_runner.py`
launches — the runner's global flags (`-hide_banner -nostdin -loglevel error
-nostats -progress pipe:1`) plus, when `uses_hdr_tonemap()`, the Vulkan
device-init flags — all placed in the `cmd` prefix (via ffmpeg-python's
`compile(cmd=...)`), never `.global_args()`, which appends *after* the
compiled output spec and would make ffmpeg reject `-filter_hw_device`
outright.

### `core/ffmpeg_runner.py`

`FfmpegJob` — one real ffmpeg process plus the two daemon threads that watch
it, no UI code in the module. `start()` launches the compiled argv via a plain
`subprocess.Popen` (not ffmpeg-python's `run_async()`, which can't pass
`creationflags` — `CREATE_NO_WINDOW` matters, or every job flashes a console
window). It runs at the OS's normal process priority unless Settings' "Priority
Level" says otherwise: the constructor's `priority` argument is ORed into
`creationflags` via `core.priority.creation_flag`, and `set_priority(level)`
moves a running process (the level changed mid-job). Normal stays the default
because throttling was profiled to be pure downside — event-loop lateness
during a full-speed encode came back the same as idle either way, and a
below-normal encode finished within 0.3% of a normal one.

Two threads per job: one drains stderr continuously (mandatory — a full
pipe blocks ffmpeg forever, and the tail becomes the failure reason), one
parses `-progress pipe:1` off stdout (`out_time_us` — `out_time_ms` is
*also* microseconds despite its name) and settles the job once ffmpeg exits.
Windows' `select()` only works on sockets, not arbitrary pipe handles, so
reading two blocking pipes without stalling needs one thread apiece.
Everything reaches the GUI thread only via `poll_events()` (non-blocking,
drains a `queue.Queue` of `("progress", fraction)` / `("done",)` /
`("failed", reason)` tuples) — `QueueTab._poll` drains it on its own timer
tick.

The progress denominator starts as the job's own `duration_secs`, else the
input's probed duration minus `start_secs` (`probe_duration`, off-thread);
if the actual encode runs past that estimate, `_watch` stretches it upward
(`total = seconds * 1.05`) rather than clamping to 1.0 and freezing the bar
at "done" while ffmpeg keeps working — confirmed real-world trigger: a VFR
source whose container-reported duration undersold its true playable length
over 10x.

`suspend()`/`resume()` freeze/thaw the whole process via ntdll's
`NtSuspendProcess`/`NtResumeProcess` (no psutil) — verified zero progress
lines over a 3s suspend, then resuming from the exact frame. `stop()` kills
the process (works while suspended too), waits, and deletes the partial
output.

Output goes to `<stem>.partial<ext>` (`partial_path`) first, replaced onto
the real path only on a clean exit, via `_replace_output` rather than a bare
`os.replace` — confirmed two real Windows "Access is denied" causes: the
destination is read-only (cleared first, best-effort), or something else
transiently has it open (a short retry loop, `_REPLACE_ATTEMPTS` ×
`_REPLACE_DELAY_SECS`, clears this without bothering the user). A stopped or
failed job only ever deletes the temp file it created, never a file the user
already had at the final path.

If the job's compiled command actually ran the HDR tonemap
(`verify_hdr_tag=True`, set by the caller from `ffmpeg_build.
uses_hdr_tonemap()`), a clean exit is followed by `core.utilities.
verify_hdr_sdr_tag` — if that comes back `False` (still reads HDR), the
event is `("failed", ...)` even though the file is real and playable and is
left in place (not deleted) for inspection; a `None` result (probe itself
failed) is "unknown" and falls through to `("done",)`.

### `core/downloader.py`

The Downloader's logic, with no UI code. **Everything runs through the bundled
`yt-dlp.exe`** — one copy for fetch *and* download, updatable without an app
release.

- `base_args()` — every argv starts `yt-dlp.exe --ignore-config --no-playlist`
  plus absolute `--js-runtimes deno:<path>` and `--ffmpeg-location <dir>`.
  `--ignore-config` is required: a user-level `%APPDATA%\yt-dlp\config.txt`
  would otherwise silently steer every job (confirmed on the dev machine).
  `subprocess_env()` adds `PYTHONIOENCODING=utf-8` so titles survive the pipe.
- `deno_path()` — Deno resolved via `core.tools` and `deno --version` ≥ 2.3.0
  (yt-dlp's minimum), cached behind a lock (the startup check runs on a worker
  while the GUI thread may already be building an argv). Warn-only: YouTube
  still worked without it on the day it was tested, which is exactly why "it
  works without Deno" must not be trusted.
- `fetch_info(url)` → `(info, error)` — `yt-dlp --flat-playlist -J`, blocking
  (seconds on YouTube); a playlist URL is refused with a readable message;
  `error_reason(lines)` turns yt-dlp's last `ERROR:` line into user text.
- `download_thumbnail(url)` — the video's thumbnail as a PIL image (or None).
- `safe_stem(title)` — a Windows-safe filename stem (illegal characters
  swapped, length capped).
- `parse_formats(info)` — compacts yt-dlp's format list, which comes sorted
  worst → best by yt-dlp's own preference (so "best matching X" is simply the
  last match): drops storyboards and `-drc` duplicates, maps vcodec/acodec
  strings to this app's codec names, fills a missing size from
  `tbr × duration`.
- The option lists, one-directional like every tab: `modes_for`,
  `codecs_for(fmts, mode)`, `qualities_for(fmts, mode, codec, audio_format)`,
  `audio_codecs_for(fmts, mode, codec, quality)`,
  `formats_for(fmts, mode, codec, quality, audio_codec)`, `default_format`.
  Containers are judged by `core.formats.containers_for` — the same matrix
  Muxing uses — so VP9 never offers `.mp4` and `.webm` never takes AAC.
- `resolve(fmts, mode, codec, quality, container, duration, audio_codec)` →
  the plan (JSON-safe, it rides in the queued task): `format` (pinned IDs, then
  a fallback selector), `ext`, the mode's `args` (`--merge-output-format` /
  `--remux-video` / `-x --audio-format --audio-quality`), `parts` (`id`,
  `kind`, `size`) and `post` (`merge` / `remux` / `convert` with
  `expected_bytes`, `media_secs`). **The fallback's audio alternatives are
  parenthesised** — in yt-dlp's selector grammar `/` binds looser than `+`, so
  `bv+ba[x]/ba[y]` means "(bv+ba[x]) or an audio-only ba[y]".
- `build_download_args(plan, url, work_dir)` — the full download argv.
- `MODES`, `MODE_AV` / `MODE_VIDEO` / `MODE_AUDIO`, `BEST_CODEC`,
  `BEST_QUALITY`, `VIDEO_CONTAINERS`, `AUDIO_CONVERSIONS` — shared constants.

### `core/ytdlp_runner.py`

`YtDlpJob(url, plan, final_path)` — one download, off the GUI thread, with the
same control/event contract as `FfmpegJob` (`start` / `suspend` / `resume` /
`stop` / `poll_events`) plus a `("stage", text)` event ("Downloading video…",
"Merging…", "Converting audio…", "Finishing…").

- **Process tree in a Windows Job Object.** yt-dlp.exe is a PyInstaller bundle
  that starts its own ffmpeg; the first process is created
  `CREATE_SUSPENDED`, assigned to a kill-on-close job, then resumed, so nothing
  escapes. `stop()` terminates the job; `suspend()`/`resume()` enumerate its
  PIDs and suspend each (`ffmpeg_runner._set_suspended`). Verified: pause froze
  the byte count, Stop mid-download and mid-conversion left no process and no
  files, and killing Python outright took the tree with it.
- **Private work folder** — yt-dlp writes only into a hidden
  `.llamamxd-download-XXXXXXXX` beside the output; on success the file named by
  `--print after_move:filepath` is moved onto `final_path` with
  `ffmpeg_runner._replace_output`'s retrying replace. Stop/failure just deletes
  the folder — a user's existing file is never touched unless the download
  succeeded.
- **One pipe** (`stderr=STDOUT`) — progress comes on stdout, post-processing
  events and errors on stderr. Marker lines (`LLAMA_FORMATS`, `LLAMA_FORMAT`,
  `LLAMA_DL`, `LLAMA_PP`, `LLAMA_FILE`) carry the chosen formats, per-stream
  progress, post-processor status and the final path; if the fallback selector
  picked different IDs, the byte budget is rebuilt from what was chosen.
- **Progress is time-based**: `elapsed / (elapsed + remaining)`, computed in
  `poll_events()` on the GUI thread, never backward, capped at 0.99 until the
  file is in place, paused time excluded. Remaining = bytes left ÷ speed (bytes
  received over a 20s window, not yt-dlp's instantaneous figure) plus the post
  step (learned from the last measured rate this session, then from how fast
  the work folder grows). The value eases toward its target so a spike only
  nudges it.
- **Priority** (`priority` argument, `set_priority(level)`) is applied to the
  whole process tree, not just yt-dlp.exe: a child only inherits its parent's
  class when that class is Low or Below Normal, so yt-dlp's own ffmpeg (started
  later for a merge) would otherwise run at Normal under a High parent.
  `_sync_priority` re-sets every PID in the tree, and `poll_events` re-runs it
  about once a second (`_PRIORITY_SYNC_SECS`) while the level isn't Normal. A Job
  Object priority limit was tried instead and refused — Windows rejects High
  there without a privilege a normal user lacks.
- `_folder_bytes` uses `os.stat(path)`, not `DirEntry.stat()` — the latter is
  stale for a file another process still has open.

---

## `ui/` — the PySide6 interface

### `ui/app.py`

`MainWindow(QWidget)` — the window and the app's hub; every tab receives it as
`app`.

- **State**: `current_file_path`, `default_save_location` (created at startup,
  best-effort), `gpu_preference` (what the user chose and what gets saved) vs.
  `gpu_enabled` (what jobs use — forced off without a dedicated GPU, without
  overwriting the saved choice, so a GPU added later picks it back up),
  `naming_template`, `priority_level`, `window_mode` / `borderless_fullscreen`,
  `startup_tab` (`current_tab` starts on it), `when_done` (starts on Do Nothing when
  `when_done_reset` is set, so a Shutdown chosen last session can't surprise
  this one), `downloader_separate_save` /
  `downloader_save_location` (the Downloader's own optional save folder,
  off by default), `media_info` (`_empty_media_info()` — every
  probe key `None`, `audio_streams` `[]`), `thumb_frames` /
  `thumb_frames_path`, `hdr_frames` / `hdr_frames_path`, `ytdlp_cache`,
  `deno_missing`, `tabs` (built once — `Queue` first — and stacked in a
  `QStackedWidget`), `media_tabs`, `current_tab`.
- **Layout**: starts at 35% of the screen's width at the reference aspect ratio
  (`scale.window_size` — 896x540 on a 2560x1440 screen) and centred; `Sidebar` on the
  left, `_TabFrame` (holding the stack) on the right, the `TabIndicator`, a
  `ToastManager`, the `ResizeGrips` and (Borderless) the sidebar's `WindowControls` on
  top. The layout is a `_MainLayout` — `QHBoxLayout` that opts out of height-for-width
  (a word-wrapped label deep in Settings otherwise made Qt restore a maximised window
  at the height it wanted at the *outgoing* scale) — with `SetNoConstraint`, so its own
  minimum at the current scale can't stop a shrinking window from lowering it.
  `_TabFrame` and the window background are **painted** (`paintEvent`), not styled by
  `#TabFrame` / `#Root` rules: a widget-level sheet on a big container cascades over
  its whole subtree.
- `show_tab(name, animate=True)` — the outgoing tab's `on_leave`, `setCurrentWidget`,
  `_style` of the new page (a page that isn't showing catches up here) and
  `scale.settle()`, `indicator.set_active` (plugs the new button's cable in and pulls
  the old one out), take focus back from anything but a line edit, re-seat
  toasts. `showEvent` does the first alignment after geometry settles.
- **Window mode** (Settings → Appearance → Window Mode, `core/window_mode.py`):
  `set_window_mode(mode, fullscreen)` stores it and calls `_apply_window_mode`, which
  also runs at launch, and `present()` shows the window the way it wants
  (`showFullScreen` after `_prescale_for_screen`, else `show()`). Fixed is the
  reference-shaped window, `setFixedSize`, centred, not resizable. Windowed and
  Borderless are freely resizable, and **the default size is also the minimum**
  (`scale.window_size` of the window's screen). Borderless sets
  `FramelessWindowHint`: a press on the sidebar or the margin around the tab frame that
  no child took starts a native move (`mousePressEvent` → `startSystemMove`; the tab
  frame itself doesn't, so an empty spot in a page can't pick the window up), and
  `ResizeGrips` start native resizes. `_wants_fullscreen()` (Borderless *and* the
  Fullscreen setting) is what the maximise guard reads — not `isFullScreen()`, since a
  maximised frameless window reports `Maximized|FullScreen` and that swallowed the
  restore click. `_sync_window_chrome` shows the controls (Borderless only, fullscreen
  included) and the grips (only while resizable, un-maximised, not fullscreen);
  `_toggle_maximized` is the Maximise button; `changeEvent` re-syncs the chrome on
  `WindowStateChange`. Four Windows quirks that only show up in the *native* window are
  handled in `_apply_window_mode` (found by measuring `GetClientRect` / `GWL_STYLE`,
  since Qt's own `width()` agreed with itself): a frame flip leaves the client area a
  title bar smaller than Qt believes, so the size is bounced to `size+1` then `size`;
  `WS_MAXIMIZEBOX` is set explicitly (`core.window_style.set_maximize_box`); leaving
  maximised/fullscreen goes through `showNormal()` + `processEvents()` *before* the
  flag changes, with the size read from `normalGeometry()` beforehand; and the dark
  title bar is set by `_sync_titlebar` (`core.window_style.set_dark_titlebar`) after
  every mode change and on every theme change. Closing from Borderless's Close goes
  through `close`, so the unfinished-jobs prompt still applies.
- **UI scale**: `resizeEvent` sets the scale (`scale.fit(width, height)` →
  `scale.set_factor`) on **every** resize event, so the whole window follows a drag
  live, and finishes everything a resize needs before it returns — `_settle_layout`
  (three passes of `sendPostedEvents(LayoutRequest)`; a layout only posts its parent's
  request once its own size changed) and `_replace_overlays` (the tab pipe, toasts) —
  because Windows paints between a resize and the next posted event, and anything left
  to a queued request was painted one frame late. `_on_scale_changed` (the
  `scale.changed` slot): `_restyle`, `_settle_layout`, `scale.settle()`,
  `_schedule_replace` (a zero-delay timer, deduplicated by `_replace_pending`; used
  by `_apply_window_mode`). `_replace_overlays` re-lays the tab pipe and toasts, and
  `_restack` restores the stacking order, bottom to top: tab pipe, an expanded
  preview overlay, the toasts (`ToastManager.raise_all`), the resize grips.
- **Styling** (`_style(target)`, `_restyle`): `QApplication.setStyleSheet` (~185ms on
  ~500 widgets) runs **once**, in `main.py`, so widgets measured during construction see
  the right lengths; afterwards the sheet is applied *on the widget* — the sidebar and
  the page on screen only (~13ms), which overrides the app-level one. `_style` compares
  the sheet's *text* (every length is a whole pixel, so nearby scales often give an
  identical sheet — nothing to re-apply) and separately keys the layouts' invalidation
  on the *scale*, since a `ScaledLabel`'s hint follows the scale continuously, and it
  invalidates every layout in the subtree (a restyle only refreshes visible widgets'
  cached hints, so a page's hidden panels kept old-scale hints).
- `notify(message, go_to_queue=True)` — posts a toast.
- **File selection**: `register_media_tab(tab)`; `update_global_file(path)`
  (the only place the selected file changes — resets scrub index and
  `media_info` on a new path, updates each media tab, cancels any in-flight
  HDR render for the outgoing file, starts `_load_thumbnails`);
  `_load_thumbnails` (cache hit → broadcast; miss → one
  worker: `probe_media` delivered early via `emit_progress`, then ten frames;
  token-guarded); `_deliver_media_info` (rejects a probe with neither video
  nor audio at all — a corrupt/unreadable file, not a legitimate audio-only
  input — via `_reject_file` before it ever reaches a tab), `_reject_file`
  (undoes the selection entirely: every media tab's `clear_selected_file`,
  cache/state reset, "Couldn't Read This File" dialog), `_is_audio_only`,
  `_broadcast_audio_only`, `_broadcast_media_info`, `_deliver_thumbnails`,
  `_broadcast_thumbnails`, `sync_preview_index(index)`.
- **HDR preview**: `start_hdr_render(path)` / `_deliver_hdr` — one tone-mapped
  render per file, cached, token-guarded, broadcast to `on_hdr_frames_ready`.
  `_cancel_hdr_render()` (a `threading.Event` passed into the render as
  `should_cancel`) interrupts one still running for a file that's no longer
  selected, called from `update_global_file`/`_reject_file`.
- **Downloader**: `fetch_ytdlp_info(url)` / `_deliver_ytdlp_info` (worker fetch
  + thumbnail, token-guarded, cached in `ytdlp_cache`); `_deliver_deno_check`
  (the startup Deno check); `downloader_default_location()` (the Downloader's
  own separate folder if set and enabled, else the shared default);
  `set_default_save_location`, `set_downloader_separate_save`,
  `set_downloader_save_location` — each also refreshes the Downloader tab's
  own autofilled path via `DownloaderTab.refresh_default_location()`.
- **Settings-driven**: `set_naming_template(template)` (every tab whose Save
  field still holds an autofilled name re-derives it, via `refresh_auto_output`),
  `set_priority_level(level)` (applied at once to a running job through
  `QueueTab.apply_priority`), `perform_when_done()` (the queue just emptied —
  Shutdown / Sleep / Hibernate / Log Off get a 30-second cancellable
  `confirm_countdown` first; Lock and Quit act at once; a failure is shown).
  `_broadcast_media_info` also calls each media tab's `refresh_auto_output`,
  since the probe may carry a title / chapter count the naming format uses.
- `_restyle` — on `ThemeManager.changed` and on a scale change: restyles what is on
  screen (see Styling above).
- `closeEvent` — confirms (pausing the queue for the prompt) when jobs are
  unfinished, autosaves Settings, kills the active job, quits; `_closing`
  stops the close Qt re-sends during `quit()` from prompting twice.

`_Keybinds(QObject)` — an application-level event filter: Left/Right step the
current tab's carousel (not while a text field has focus); Escape collapses
whichever media tab's carousel preview is currently expanded, if any; Space
toggles the queue on the Queue tab (not for auto-repeat, text fields,
buttons or combo boxes); inactive while a modal is open. The same filter also
watches `MouseButtonPress`: since every clickable is `Qt.NoFocus`, a click on a
button or empty space never moved focus, leaving a line edit (or the
TimeSpinner's field) visibly focused — cursor still blinking, still first in line
for Ctrl+A/paste. If the focused widget is one of those and the click lands on
some *other* object, its focus is cleared before the click is delivered.

### `ui/theme.py`

- `_NEUTRALS` — the non-brand greys for `Dark` and `Light` (window, frame,
  entry, text, muted, label_disabled, track, knob, check_border, menu_*,
  segment, row, panel, disabled, tooltip_bg, warn_*).
- `ThemeManager(QObject)` — `name`, `mode`, `changed` signal; `set_theme`,
  `set_mode`, `resolved_mode()`, `hex(key)`, `color(key)`. `_rebuild_colors`
  drives the native title bar's colour scheme (unsetting it first for System
  mode), merges `core.theme.get_theme` with the neutrals and adds `stop*`,
  `stop_disabled_text` and `*_pressed`, and aliases `action_btn*` / `queue_btn*`
  (fill, `_hover`, `_pressed`, `_text`, `_disabled_text`) from whichever of
  primary / secondary the theme assigns them (swapped for `swap_action_buttons`).
  Follows the OS scheme live while in System mode.
- `init_theme()` / module global `theme` — the one instance.
- `lerp(a, b, t)` / `with_alpha(color, alpha)` — QColor helpers used by the
  painted widgets.
- `stylesheet()` — the stylesheet for stock widgets, regenerated on a scale change
  (every length is `px()` / `font_px()` of the current scale, so it is a function of
  the scale); keyed by a dynamic `role` property on buttons (`primary`, `danger`,
  `ghost`, `stepper`, `compact` — the 22px-tall variant — and the two a theme can swap,
  `action` and `queue`) and labels (`field`, `field11`, `muted`, `meta`, `hint`, `title`,
  `dialogTitle`, `detailTitle`, `detailKey`, `error`, `empty`, `warn`,
  `sidebarTitle`, `sidebarFooter`), plus line edits, the slider, scrollbars
  and the combo popup (`combobox-popup: 0` so it drops below the button).
  `ScaledLabel` / `ScaledButton` / `ScaledLineEdit` take their `font-size` in
  **reference** pixels (`13px`, not `font_px(13)`), since they paint through the scaled
  painter. The slider knob's size, margin and radius are derived together (`groove`,
  `knob`, `knob_margin`): Qt's handle box is groove + 2 x margin, and rounding
  `px(16)` / `px(4)` / `px(-6)` separately left it a pixel off the knob at some scales,
  drawn as a square instead of a circle. The `sidebarTitle` colour is `sidebar_text`.

### `ui/scale.py`

The one UI scale factor. **Every size in the app is authored in reference pixels —
those of the 896x540 window (`BASE_W` x `BASE_H`) the layout was designed at — and
multiplied by one factor where it becomes real pixels**; tune a size by changing its
reference number, never write a bare pixel count into layout, fixed-size or paint code.
- `factor()` / `set_factor(value)` (clamped to 0.25-8; re-runs every bound setter, then
  emits `changed`) / `fit(width, height)` (`min(width/896, height/540)`) /
  `window_size(screen_w, screen_h)` (the main window's size for a screen: the
  reference aspect ratio at 35% of the screen's width, less if the screen is too short).
- `px(n)` (whole pixels, never rounding a non-zero length to nothing) / `fpx(n)` (float)
  / `font_px(n)`.
- Bound helpers — each applies now *and* on every scale change, keyed so binding the
  same thing on the same widget again *replaces* the earlier setter (a raw
  `layout.setSpacing()` after a bound one comes back on the next rescale):
  `bind(widget, fn, key=None)`, `fixed(widget, w=, h=)`, `bounds(...)`,
  `margins(layout, ...)`, `spacing(layout, n)`, `spacer(layout, n)` (in place of
  `addSpacing`), `grid_spacing(layout, h, v)`. The registry holds weak references and
  prunes dead widgets.
- `bind_after(widget, fn)` + `settle()` — for sizes measured off other widgets' size hints
  (Muxing's track box takes the Overview page's height): re-run once the window has
  re-applied the stylesheet, so they read the new hints, not the old.
- Design-space painting: `begin(painter)` right after creating the painter,
  `ref_size(widget)` / `ref_rect(widget)` for the widget's size, `ref_pos(pos)` for mouse
  hits; every literal in the paint code stays a reference number.
- `changed` — the signal emitted after every change.

Text is painted through the scaled painter (`ScaledLabel` / `ScaledButton` /
`ScaledLineEdit` in `controls.py`, and every custom widget) rather than left to Qt,
because Qt snaps every widget font to a whole pixel size, so stock text hopped between
sizes as the window was dragged; fonts are also unhinted (hinted advances are irregular
and glyphs land on whole pixels). Only the combo popup rows still use `font_px`.

### `ui/workers.py`

- `init_workers()` — creates the GUI-thread `_Bridge` (call once, after the
  QApplication).
- `run_async(fn, on_done, *args)` — runs `fn` on a daemon thread and delivers
  `on_done(result)` on the GUI thread through a queued signal; an exception is
  printed and delivered as `None`.
- `emit_progress(on_value, value)` — delivers an intermediate value from a
  worker (the early probe result).
- `pil_to_qimage(image)` — a detached `QImage` copy of a PIL image; safe on a
  worker thread (unlike `QPixmap`).

### `ui/tips.py`

Shared hover-tooltip copy, used by Encoding, Muxing, Downloader and
Settings: `SELECT_VIDEO_CODEC_TIP` / `SELECT_AUDIO_CODEC_TIP` /
`BEST_VIDEO_CODEC_TIP` / `BEST_AUDIO_CODEC_TIP` (shown before a real value's
picked) and the dicts `VIDEO_CODEC_TIPS` / `AUDIO_CODEC_TIPS` /
`CONTAINER_TIPS` / `AUDIO_FORMAT_TIPS` (per-value explanations). Pure data,
no imports at all — each tab wires a value up with `ui.widgets.tooltip.tip()`.

### `ui/tabs/media_tab.py`

Helpers `hrow(spacing, align_bottom)` (a plain horizontal row), `hms(seconds)`
and `set_line_text(entry, text)` (sets text and shows its start).

`MediaTab(QWidget)` — the frame Muxing and Encoding share. Class constants
`TAB`, `ACTION_TEXT`, `OUTPUT_SUFFIX`, `VERB_ING`, `DIRECT_LABEL`,
`PRESET_NOTE`. Builds the header (`sub_tab_bar`, `file_label`), the preview
stack (`drop_box` until the carousel's `populated`, then `carousel`), the
`panels` stack (`_build_overview()` + the subclass's `build_video()` /
`build_audio()`), the save row and the actions, then registers with the app
and runs the first `_sync_controls`.

- `_init_state()` — hook for per-instance state before panels are built.
- `_build_overview()` — Output Format, the preset row, the trim
  (`start_time_spinner`, `duration_time_spinner`), `av_sync_check`, and the
  `summary` rundown. `stream_page()` — an empty `(page, left, right)` panel.
- `_apply_import_gate(extra=())` — run last in every `_sync_controls`. With no
  file imported, every Overview/Video/Audio dropdown reads `—` (`NO_OPTION`,
  centred) and disables: Output Format and Preset here, plus whatever
  `(menu, label)` pairs `extra` names. Start Time, Clip Duration, A/V Sync, the
  preset Save/Delete buttons and the Queue Job / Mux / Encode action buttons
  (`queue_btn` / `go_btn`; roles `queue` / `action`, which a theme can swap) disable
  with them (values untouched). Output Format/Preset/the spinners/the action buttons
  get their enabled state set *both ways* unconditionally, because nothing else ever
  re-enables them; `extra` dropdowns only need the no-file side, since each one's own
  enabled state is recomputed fresh every pass by the rest of `_sync_controls`. With a
  file, it also un-blanks Preset (`—` → `presets.NONE_LABEL`): its option list never
  changes after an import, so nothing else clears the placeholder the no-file pass left.
- `_on_control_change`, `_on_trim_change` (rundown only), `_on_format_change`
  (stops auto-adopting the source container, swaps the save path's
  extension).
- `show_no_preview()` — the file stays selected and usable but has no preview frames:
  collapses any expanded preview, clears the carousel, `forget_populated()`s it and puts
  the drop box (now reading "No Preview Available", `DropBox.show_no_preview`) back over
  it. `_menu_value` reports both `—` and `Lossless` as `""`.
- `select_input_file`, `set_selected_file`, `clear_selected_file` (the
  reverse — undoes `set_selected_file` and the autofill, called when a just-
  picked file turns out unreadable), `_reveal_preview`, `_on_expand_toggled`
  (the carousel's expand/shrink icon — reparents the same `ThumbnailCarousel`
  instance into/out of a shared `_ExpandedPreviewOverlay`, see `ui/widgets/
  carousel.py` below), `on_thumbnails`, `_autofill_output_path`,
  `select_save_location`.
- Output naming: `_output_directory()` (the folder the Save field points at —
  where the input file dialogs and the DropBox's Browse open, and the one part
  of the field an autofill keeps), `_default_stem()` (Settings' naming format
  filled with the live tokens; queue-time ones stay as literal text),
  `refresh_auto_output()` (re-derives the suggested name when the probe lands or
  the format changes, but only while the field still holds what was autofilled,
  compared extension-less — a Browsed or hand-typed path is never touched),
  `_resolve_output_tokens(settings)` (the queue-time pass, run in `run_now` /
  `add_to_queue` before validation; the field keeps the tokens so each queue
  stamps its own time). `_autofill_output_path` falls back to `OUTPUT_SUFFIX`
  only when the name would equal the input's own path, and takes the input's own
  extension while the Output Format still shows `—`.
- Presets: `_refresh_preset_menu`, `_on_preset_selected`, `_on_preset_save`,
  `_on_preset_delete`.
- `_apply_common` / `_gather_common` (the shared settings keys),
  `_menu_value` (the `—` placeholder as `""`), `_validate_settings` (input,
  save location, the subclass's `_validate_specific`, then
  `confirm_output_path`), `run_now`, `add_to_queue`.

**INVARIANT — the DropBox/preview must always render at the identical size
and proportion in Muxing and Encoding.** It's a *consequence*, not a
separate setting: `panels` (a `QStackedWidget`) sizes to its tallest page,
and since both tabs' Overview page is identical, the preview comes out the
same size in both tabs *only as long as neither tab's Video or Audio page is
ever allowed to size taller than that tab's own Overview page*. There is no
automatic guard against this — it's enforced by hand at the point a control
is added to a Video/Audio panel. See `ui/tabs/muxing.py`'s `_track_panel`
and `ui/tabs/encoding.py`'s Video-panel layout below for the two
worked examples, and CLAUDE.md's "Muxing and Encoding" section for the full
explanation.

### `ui/tabs/muxing.py`

`MuxingTab(MediaTab)` — container change and stream selection, always a
copy; mixes and matches any combination of a file's own tracks plus tracks
pulled in from other files, via `TrackListBox` (`ui/widgets/tracklist.py`),
not the single `Auto`/`Track N` dropdown an earlier version of this tab
used.

- `_track_panel(kind)` builds each of the Video/Audio panels: the
  `TrackListBox` itself, a top line of two **icon buttons** — Select All /
  Deselect All (`IconButton` `select-multiple` / `deselect-multiple`, with hover
  tooltips) sized to half of the Add/Remove buttons' width and stretched
  vertically to fill whatever column height is left — then `Add Stream(s)`, then
  `Remove Stream(s)` (danger-role), then **Undo / Redo** (`undo` / `redo` icon
  buttons, 4px apart) with the Strip checkbox to their right. The
  two-across rows are what keep the four-row column under the box's fixed
  height — and even so it only just fits: the icon rows are `role="compact"`
  (min 22px; the Undo/Redo/Strip row is 24, the checkbox's height), the column's gaps are
  4px, and Select/Deselect All take whatever the box has left. Fixes the box's height to exactly
  `self.panels.widget(0).sizeHint().height()` (Overview's own height) — the
  DropBox-height invariant above, enforced here specifically (verified: the
  Video/Audio pages are never taller than Overview at 42 scales from 0.8x to 2.6x).
- `_tracks` — the list each box shows, per kind: entries `{"id", "source"
  ("primary"/"external"), "file", "index", "stream", "name"}`, seeded from the
  probe (`_reseed_tracks`, whenever a new `media_info` object arrives — which also
  clears the undo history) with any externally-added entries kept after the source's
  own. It, not the probe, is the truth for what a box lists, so a source track can be
  removed like any other.
- `_add_stream(kind)` browses a second file and probes it off the GUI
  thread; `_stream_probed(kind, path, info)` adds its lone matching-kind
  stream straight away, or opens `ExternalStreamPickerDialog` (`ui/widgets/
  dialogs.py`, via `pick_external_streams`, with a compact per-stream caption —
  the dialog is a fixed 400px) when it has more than one. Added streams are
  appended to `_tracks[kind]` as `ext:` entries, independent of the primary input.
- `_select_all(kind)` / `_deselect_all(kind)` check / uncheck every row
  (`TrackListBox.item_ids()`, regardless of current state) without adding or
  removing any — the non-destructive counterpart to Remove.
- `_remove_streams(kind)` removes every currently-checked row from the list —
  the source file's own tracks included — and the rows below move up, so track
  numbers ripple (`_items_for` numbers by position). Shows a message rather than
  doing nothing when nothing's checked. `_validate_specific` refuses a job with no
  track left to map at all.
- `_reorder_tracks(kind, ids)` — a drag in the box ended: reorders `_tracks[kind]` to
  `ids` through `_edit_tracks`, so a move is one undo step (see `tracklist.py` below).
- `_edit_tracks` / `_track_toggled` / `_push_history` / `_undo` / `_redo` / `_travel` /
  `_snapshot` — Undo / Redo of every edit to a box: Add and Remove Stream(s), reorders **and
  which rows are ticked** (a checkbox click, Select All, Deselect All — the last two only when
  they change something), one history per kind, capped at 50. A snapshot is the list plus the
  checked ids; a click's step is the state from before it (`_checked_baseline`, the ticked
  ids as of the last `_sync_controls`); going back or forward restores every row's ticks
  (`_restore_checked` → `set_items(checked=...)`).
- `_items_for(kind)` builds `TrackListBox.set_items`' row list from `_tracks`, each
  labelled `Track N  ·  [External: name  ·]  details` by its position (`_row_label`);
  video details are codec · profile · level · size · fps · HDR kind · bit depth +
  chroma · bit rate · language (`_stream_details`). `_track_args(kind)` turns the
  box's *checked* rows, in the box's order, into the `video_tracks`/`audio_tracks`
  settings shape (`{"source", "file", "index"}`, one entry per checked row).
- `_sync_controls` (stream presence, the track boxes via `_items_for`, the
  container inversion via `_retarget_container` — which toasts a snap and
  keeps the save path's extension in step — and panel enabled state),
  `_refresh_summary` (with the `· keyframe` trim caveat), `on_media_info`
  (adopts the source container), `_gather_settings`, `_apply_settings`.

### `ui/tabs/encoding.py`

`EncodingTab(MediaTab)` — the re-encode tab. Its Video panel keeps the same
DropBox-height invariant (above): the rule is that a new control is never free
height *or* free width just because there's a blank stretch nearby — a row's
height is set by its tallest column, and two controls that need to align
against each other should be literal siblings in one layout call, not one
stacked inside a wrapper. CLAUDE.md's "Encoding's own worked example" has the
full history of the layouts tried.

- `build_video` — one row of Encoder / Profile / Level / Encoder Preset /
  `resolution_menu` (the downscale ceiling — `core.formats.RESOLUTIONS`); a
  caption row beneath it ("Quality (CRF): NN" beside "FPS:"); then a controls
  row with the quality slider (`crf_slider`, inverted; `crf_label`,
  `crf_low_label`, `crf_high_label`) beside the bare `fps_menu` (a frame-rate
  ceiling — `core.formats.FPS_VALUES`). The slider and its caption are
  **fixed to span exactly Encoder..Encoder Preset** (so "Placebo" lands flush
  with Encoder Preset's right edge), and FPS's caption is width-matched to its
  dropdown the same way; the FPS dropdown sits in the gap the slider leaves,
  landing directly under Resolution. The right column holds `hdr_label` +
  `hdr_switch` (top) and `strip_video_check` (bottom), right-aligned.
- `build_audio` — `audio_track_menu`, `choose_streams_btn`, `passthru_check`
  on one row; `audio_codec_menu`, `audio_bitrate_menu`, `audio_channels_menu`,
  `audio_samplerate_menu` on the next; `strip_audio_check`; dropdowns sized
  with `Dropdown.width_for` to their longest possible entry.
- `_on_encoder_change`, `_toggle_hdr`, `_on_quality_change`.
- HDR preview: `_on_hdr_toggle`, `on_thumbnails`, `on_hdr_frames_ready`,
  `_apply_preview_frames`, `reset_hdr_preview` (turns HDR→SDR back off
  without a raw/tone-mapped frame flash — called when a new file arrives).
- `_sync_controls` (the six rules, then `_apply_import_gate` with every
  Encoder..Sample Rate dropdown as `extra`, plus a block disabling the
  non-dropdown controls — quality slider and captions, both Strip checkboxes,
  Choose Stream(s), Passthru — while no file is imported), `_retarget` (toasts a
  forced snap), `_retarget_resolution` / `_retarget_fps` (cap Resolution / FPS to
  the newly-probed source height / rate, each with its own toast wording since
  the reason is the file, not the container; all three skip the toast when the
  prior value was the no-file `—`),
  `_speed_values` / `_apply_speed`, `_apply_quality` / `_update_quality_label`.
  The Bitrate dropdown says `Lossless` (`formats.LOSSLESS`) for a resolved lossless codec
  (disabled), and in Passthru mirrors `Lossless` for a lossless source stream
  (`formats.probed_audio_is_lossless` via the probe's per-stream `lossless` flag — which
  also covers Dolby TrueHD, which reports no bitrate, and DTS-HD MA); the rundown leaves
  the bitrate out for those. HDR→SDR's switch is disabled and forced off when
  `supports_libplacebo()` is false, and on an HDR source its tooltip then appends
  `libplacebo_problem_text()`; `_validate_specific` shows the same text in its dialog.
- Multi-stream audio: state is `_audio_list` (entries `{"id", "source", "file", "index",
  "stream", "name"}` — Muxing's shape — in the Choose Stream(s) popup's order, which is the
  output's), `_audio_included` (ids), `_active_audio_id`, `_audio_stream_settings[id]`,
  `_audio_track_ids` (dropdown label -> id). Methods: `_included_audio`,
  `_audio_track_values` (labels `Track N (codec)`, N by place in the popup's list),
  `_save_active_audio_stream`, `_active_stream_info`, `_apply_passthru_values`,
  `_load_active_audio_stream`, `_on_audio_track_change`, `_open_stream_picker` (opens the
  popup on the list; on OK swaps the result in), `_reactivate_audio_stream`,
  `_default_audio_settings(stream)`, `_auto_select_audio_streams` (re-seeds the source's
  streams per file, keeping streams added from other files). Each gathered `audio_streams`
  entry carries `id`, `source`, `file` and the entry's probed `language` (see
  `core/ffmpeg_build.py`'s stale-metadata note).
- `_refresh_summary`, `on_media_info` → `_auto_select_codecs`,
  `_gather_settings` (also carries `resolution`/`fps` and snapshots
  `source_height`/`source_fps`, facts about the input at queue time, same
  convention as `mastering_max_nits`/`max_cll`), `_apply_settings` (dependency order), `_validate_specific`.

### `ui/tabs/downloader.py`

Helpers `_human_size`, `_hms`, `_dropped_link(mime)` (the one http(s) link a
drag carries, or None). `_Thumbnail` (the fetched thumbnail, fitted with
rounded corners) and `_LinkDropFrame` (the preview box, accepting only a
link).

`DownloaderTab(QWidget)` — `set_deno_missing` (also `_apply_banner_gap`: the gap under
the Deno banner is 6 reference px while it shows, and follows the scale), Paste / Queue
Task use the `queue` role and Fetch / Download the `action` role (a theme can swap them),
`paste_and_fetch`,
`_on_link_drop`, `fetch`, `on_ytdlp_info`, `_apply_info` (adopts a video,
resetting every pick), `_sync_controls` (Mode → Video Codec → Resolution →
Audio Codec → Format, or Format → Resolution for Audio Only; resolves the
plan for the size readout and extension; with nothing fetched every dropdown
reads `—`, the same no-file convention as `MediaTab._apply_import_gate`,
inlined here since this isn't a `MediaTab`), `_show_audio_picker`, `_retarget`,
`_menu_value`, `_current_directory`, `_name_info` / `_default_stem` (the fetched
video run through Settings' naming format — `{source}` is the site, `{title}`
the video's title, made file-name-safe with `downloader.safe_stem`, which swaps
illegal characters for look-alikes instead of dropping them),
`_autofill_output_path` (records `_auto_output`), `refresh_auto_output` (the
naming format changed — re-derive only while the field still holds the
autofill), `_resolve_output_tokens` (the queue-time pass, in `download_now` /
`add_to_queue`), `_apply_output_extension`, `select_save_location`, `_gather_settings`,
`_validate_settings` (nothing fetched, link edited since the fetch, no save
location, then `confirm_output_path`), `_describe`, `download_now`,
`add_to_queue`, `has_fetched()`, `refresh_default_location()` (re-adopts
`app.downloader_default_location()` when Settings' folder changes — but
only *before* a fetch, `has_fetched()`-gated, so it never overwrites a
post-fetch save path from underneath a completed fetch). **The Resolution
label is on-screen only** — internally still `quality_menu`, settings key
still `"quality"` (see "Tabs → Encoding" above for the same convention on
Encoder Preset/`speed`); see "Tabs → Queue" below for how the details popup
tells this apart from Encoding's own unrelated `"quality"`.

### `ui/tabs/queue.py`

- `_DETAIL_FIELDS`, `_VIDEO_DETAIL_KEYS`, `_AUDIO_DETAIL_KEYS` — which settings
  keys the details popup shows, and which a stripped stream hides.
  `_DETAIL_FIELDS` includes `resolution` and `fps` (both hidden under
  `strip_video`, same as `quality`/`profile`/`level`/`speed`). `_show_details` special-cases
  `key == "quality"` for a Downloader task specifically, relabeling that one
  row "Resolution" — the same settings key holds Encoding's own CRF/qscale
  value for an Encoding task, so the row needs to say something different
  depending on which tab queued it. Encoding's `audio_streams` and Muxing's
  `video_tracks`/`audio_tracks` each render one detail row per entry
  (per checked track, for Muxing).
- The empty state ("No tasks queued yet.") is its own page in `_list_stack`, a
  `QStackedLayout` beside the real row list (`scroll`) — not a widget sharing
  the list's layout: a stretch item there stays live after real rows arrive and
  pushes the populated list off-centre, whereas a stack shows exactly one page,
  switched explicitly by `add_task` / `remove_task`.
- `QueueRow(QWidget)` — one painted task row (`set_status`, `set_fraction`;
  signals `clicked`, `removeRequested`), authored in design space (`scale.begin`,
  `ref_size`, `ref_pos`). Start Queue / Pause Queue is the `action` role.
- `ProgressStrip(QWidget)` — the flat overall bar (`set_value`).
- `_DetailPanel(QWidget)` — the rounded details container.
- `QueueTab(QWidget)`:
  - rows — `add_task`, `_status`, `_load_thumbnail`, `update_status`,
    `_update_overall_progress`, `remove_task`, `clear_completed`,
    `clear_all`;
  - queries — `is_running`, `pending_task_count`, `claims_output`,
    `on_leave`;
  - details — `_show_details`, `_go_to_detail_file`;
  - control — `_set_running`, `toggle_queue`, `start_queue`, `pause_queue`,
    `stop_queue`, `shutdown`, `start_task`, `_running_label`,
    `apply_priority` (Settings' Priority Level changed: move the running job to
    it; later jobs read `app.priority_level` themselves), `_run_when_done`
    (posted with a zero-delay timer when a batch ends; waits out any open
    failure dialog and drops out if more work was queued meanwhile, then calls
    `app.perform_when_done`);
  - jobs — `_process_next`, `_start_download`, `_start_timers` /
    `_stop_timers`, `_poll` (100ms event drain), `_animate_fill` (16ms fill
    easing), `_halt_active`, `_finish_task`, `_fail_task`, `_show_errors`.

### `ui/tabs/settings.py`

`SETTINGS_PAGES` = Appearance / Output / Performance. `_Swatch` (a 26px colour
chip for the previewed palette). `SettingsTab(QWidget)` — the same `SubTabBar`
Muxing/Encoding use, over a `QStackedWidget` inside a scroll area (so a revealed
row can never clip), with a read-only, fixed-width System info label (CPU / GPU /
RAM, from `core.system_info` / `core.gpu`) sharing the tab bar's row, top-right
(not a row of its own — a long CPU name sizing to its own content could overflow
the tab frame). Side padding (`_SIDE_PAD` 10) and the tab bar's top padding
(`_TOP_PAD` 5) match Muxing/Encoding's, so the bar sits in the same place on every
tab. Reset to Default / Save are pinned below the pages and act on *every*
setting, whichever page is showing.

- **Appearance** — Theme (a `Dropdown` + two colour swatches: hovering a row
  previews that palette across the whole app, picking commits and saves, closing
  the list without picking reverts), Appearance Mode (System / Light / Dark) and
  Window Mode (Windowed / Borderless / Fixed, applied live through
  `app.set_window_mode`), whose **Fullscreen** checkbox exists only while Borderless is
  selected — unchecked by default, and its choice is remembered while another mode is
  on. (The row is added to its layout *before* it is shown: a still-parentless widget
  made visible is its own top-level window, which flashed a small "LlamaMXD" window at
  every Borderless launch.)
- **Output** — Default Save Location (entry + Browse, with the drive's total/free
  space beneath, in STOP_RED at or below 25GB free), Separate Save for Downloader
  (reveals a second entry + Browse for the Downloader's own folder), and File
  Naming (an entry with the token list beneath it turning into a STOP_RED reason
  while what's typed is invalid; nothing is applied until Enter/focus-out, and
  never while invalid).
- **Performance** — Hardware Acceleration (GPU) (a `Switch` with a status line
  naming the GPU, its encoder brand and the codecs it covers — or that none was
  found; forced off and greyed out without a dedicated GPU), Priority Level
  (High … Low, applied to a running job immediately), When Done (with a
  "Reset to 'Do Nothing' when the app is relaunched" checkbox, on by default) and
  Startup Tab (Muxing / Encoding / Downloader / Queue, default Encoding — only changes
  what the *next* launch opens on, not the running session).

Methods: `_settings_snapshot` (persists `app.gpu_preference`, not the
possibly-forced-off switch; and the Downloader's entry text only while
separate-save is on — the display text while it's off is the shared default shown
as a fallback, never itself a real separate location), `_sync_state_from_widgets`,
`autosave`, `on_leave`, `on_enter` (refreshes disk usage — free space can change
while the app sits elsewhere), `_show_swatches`, `_preview_theme` (hover),
`_end_preview` (list closed), `_on_theme_change` (commit), `_on_appearance_change`,
`_on_window_mode_change` / `_on_fullscreen_toggle` (show or hide the Fullscreen row, then
`app.set_window_mode`), `_on_startup_tab_change`, `_browse_save_location`, `_refresh_disk_usage`, `_on_downloader_separate_toggle`,
`_browse_downloader_location`, `_validate_naming_text` / `_commit_naming` (against
`core.naming.template_error`; pushes a valid format to
`app.set_naming_template`), `_on_priority_change`, `_on_when_done_change`,
`_on_when_done_reset_toggle`, `_on_gpu_toggle` (also refreshes the status label
via `_refresh_gpu_status`), `_on_save` (persists and toasts "Settings saved." — no
jump to the Queue), `_on_reset_defaults` (`ask_yes_no`-confirmed — resets theme,
appearance mode, window mode (back to Fixed, Fullscreen off), default save location,
the Downloader's separate-save toggle and location, GPU acceleration, file naming,
priority level, When Done and Startup Tab all back to their defaults in one action,
then autosaves). Settings also autosave when the tab
is left and on close.

### `ui/widgets/controls.py`

Helpers: `NO_OPTION` (`"—"`), `ui_font(size, bold, family)` (a font at *reference*
pixels, unhinted — for custom painters, which scale the glyphs, and for measuring text
in reference pixels), `set_font_px(widget, size, bold, family)` (a real widget's font
at a reference size, re-applied on every scale change — a stylesheet's own font rules
override it on a label), `field_label`, `labeled(label_text, widget)` → `(box, label)`,
`button(text, role, width, height)` (a `ScaledButton`; NoFocus, pointing cursor; width
and height are reference px, bound), `button_width_for(texts)` (fits the widest of
several button labels, in reference px), `restyle(widget)`, `set_enabled(widget, label,
enabled)`, `anim(owner, duration, on_value, curve)`, `draw_cross(painter, rect, color)`.

**Text on a stock widget goes through the scaled painter** (`ui/scale.py`): Qt snaps a
widget font to a whole pixel size, so stylesheet-sized text hopped between sizes as the
window was dragged. Never use a bare `QLabel` with text or a bare `QLineEdit`:
- `ScaledLabel(QLabel)` — paints its text through `scale.begin`; its stylesheet
  `font-size` is in *reference* pixels and its font is unhinted (`_unhinted`). It takes
  no size from Qt: `_unwrapped_hint` measures the text with the reference font and adds
  the stylesheet's box (`_chrome`, real pixels — Qt folds a real-pixel `min-height` /
  `min-width` into a hint, so scaling a hint whole multiplied the minimum too: a 26px
  caption box came out 104px at 2x); a word-wrapped one computes its own width hints
  (`_wrap_widths`: ideal ≈ 4:1 wide, minimum = the longest word) and `heightForWidth`;
  a rich-text one (Settings' system info) paints through a `QTextDocument`.
- `ScaledButton(QPushButton)` — the stylesheet still draws the box (fill, radius, hover,
  pressed, per-state text colour); only the text moves to the scaled painter, and the
  size hint is measured the same way.
- `ScaledLineEdit(QLineEdit)` — `QLineEdit` paints through a painter it opens itself, so
  this takes over the two things that touch the font: painting (the stylesheet still draws
  the box, focus border and disabled colour; text, placeholder, selection band and caret
  are drawn from the reference font, with its own scroll-to-caret and blink) and
  mouse-to-character mapping (press, drag, double-click, shift-click). Keys, undo, the
  clipboard, the selection model and every signal stay Qt's. Not reimplemented:
  dragging selected text out of the field, IME pre-edit drawing.

- `IconButton(QPushButton)` — a painted ✕ / ▲ / ▼ glyph, or an SVG icon
  (`select-multiple` / `deselect-multiple` / `undo` / `redo`). `role="compact"` is
  the 22px-tall variant (the stylesheet's stock 28px `min-height` overrides any fixed
  height, so a shorter button needs its own role) whose glyph fills 72% of it;
  `_ICON_FRACTION` overrides that per icon (undo/redo draw at 100% — their arrow only fills
  ~16x8 of the viewBox). SVG icons go through `_icon_svg(name,
  color)`, a cached `QSvgRenderer` whose literal black strokes (both the inline
  `stroke="#000000"` attribute and a `stroke: #000;` CSS property — each asset
  uses a different one) and `fill="currentColor"` are string-replaced with the
  button's own text colour before parsing. Drawn square (0.56 of the shorter
  side) and centred — `render(rect)` on a wide rect would stretch the icon.
- `ClickableLabel(ScaledLabel)` — emits `clicked` (only while enabled).
- `Dropdown(QComboBox)` — self-painted (the `NO_OPTION` placeholder is centred,
  real text left-aligned); `picked`, `hovered`, `popupClosed`;
  `value`, `values`, `set` (display override for an unlisted value),
  `set_values` (an override is not a legal pick: it no longer survives an unchanged
  list, which is what left Resolution on its no-file `—` after a tall source was
  imported), `close`, `width_for`; the popup unrolls via an animated mask
  (`_set_unroll_mask`), drops 3px below the button — or, when the list would run off
  the screen's available area and there is more room above (a tall list near the bottom,
  most obviously in fullscreen), opens upward and rolls out from the button's edge.
- `CheckBox(QAbstractButton)` — `color_key`, fading fill, greyed when
  disabled; `set_hover(bool)` lets a caption-less checkbox's row drive its hover
  shade.
- `Switch(QAbstractButton)` — sliding knob.
- `SegmentedButton(QWidget)` — sliding selection pill; `changed`, `value`,
  `set`.
- `_TimeField(QWidget)` + `TimeSpinner(QWidget)` — the HH:MM:SS field and its
  accelerating ▲/▼ stepper; `seconds`, `set_seconds`, `valueChanged`.
- `MarqueeLabel(QWidget)` — scrolls overflowing text; `setText`, `text`,
  `set_color_key`, `doubleClicked`. `MarqueeGroup` — one shared clock **and
  timer** several `MarqueeLabel`s can join (`SummaryPanel`'s Video/Audio/Length
  rows and every `TrackListBox` row do; a standalone label gets a private group) so
  they all sweep and restart in step rather than drifting apart. The group ticks
  every 16ms, reads the clock once per tick (`now`) and `update()`s every scrolling
  member in that tick; labels paint from that snapshot (`phase()`), so rows never
  creep relative to each other, and `period()` is cached. `unregister(label)` drops
  a label about to be destroyed, and a label that *starts* scrolling restarts the
  shared loop rather than landing mid-phase. The timer is parented to the
  `QApplication` — a parentless one crashed the interpreter at exit.

### `ui/widgets/panels.py`

Constants `ASSETS`, `VERSION`, `MEDIA_FILTER`; `local_paths(mime)` (local
files carried by a drag).

- `SubTabBar(QWidget)` — `changed`, `active`, `set_active`, `set_marked`. The
  active tab is `subtab_active` (primary — secondary in a `swap_subtabs` theme) at
  30px, inactive `subtab_inactive` at 24px, bottom-aligned and standing on a 4px
  square-ended line (`_LINE_H`) in the selected tab's colour that runs the bar's
  whole width — the tabs are drawn a corner-radius taller and clipped so their feet sit
  flat on it (34px in total). The feet and the line's top edge (`foot`) are snapped to a
  whole device pixel: at a scale where 30 reference px lands mid-pixel the clip and the
  line's own antialiased edge each covered part of the same row and the window colour
  showed through as a thin seam.
- `DropBox(QWidget)` — `fileSelected`, an optional `start_dir` callable (the
  folder Browse opens in — `MediaTab._output_directory`, not the app's working
  folder), `collapse` (leaves only Browse once a
  file is chosen), `reset` (the reverse — back to pristine, used when a
  picked file turns out unreadable), `browse`; drag-over highlight. `show_no_preview()` is the third state: the border and
  Browse stay, with "No Preview Available" in STOP_RED (`_set_prompt(text, role)`, the
  `error` label role) in place of the drag/drop prompt and no "— or —" — for a file that
  is selected and usable but has no preview frames; `collapse()` / `reset()` restore the
  prompt.
- `BorderedFrame(QWidget)` — the border alone; `color_key` defaults to
  `primary`, `TrackListBox` (`ui/widgets/tracklist.py`) passes `secondary`.
- `SummaryPanel(QWidget)` — `set_values(rows)`.
- `Sidebar(QWidget)` — `navigate` signal, `buttons` dict, `WIDTH`,
  `NAV_BUTTON_WIDTH` (110 — narrower than the sidebar, so the gap the cable runs
  through is wide enough to see its lead trail out from behind the button); the
  logo (`assets/LlamaMXD-Logo.svg`) is rendered at 4x oversample and re-tinted to
  `sidebar_text` (`primary_text` unless the theme names its own — Funk, Terminal) via
  `CompositionMode_SourceIn` (`_load_logo`, re-run on every scale change), so it changes
  colour with the theme the same way the title text does. The top 24px strip is left
  free for Borderless mode's `WindowControls` (`ui/widgets/frameless.py`).
- `_cable_base_image()` / `_cable_pixmap(height)` — the RCA cable art
  (`assets/RCA Cable Yellow.svg`): rendered once at 3x and cropped to its drawn
  content with numpy (the SVG's viewBox is ~3x wider than the plug, so an
  uncropped rotation squashed it into one end of its frame), then rotated 90°
  clockwise so the grey collar faces the tab frame and the cable trails back
  toward the button, cached per height and oversampled 4x.
- `_TabPipe(QWidget)` — one nav button's own pipe: the cable sliding out of the
  button and toward the frame. `extension` (0 hidden … 1 plugged in) slides the
  whole cable; at 1 the long thin pin (`_PIN_FRAC`) is entirely past the frame's
  edge, hidden like a real pin in a jack, while the wider base collar right
  behind it, the yellow shell and the cable stay visible. One per button so an
  outgoing and an incoming pipe animate at once.
- `TabIndicator(QWidget)` — owns the pipes (created lazily per button, shown
  explicitly since a child created after its parent is on screen doesn't inherit
  that); `set_active(name, buttons, frame_left, animate)` re-lays out every
  pipe's geometry (a button's position is only final once the window's shown) and
  animates the outgoing/incoming pair together. Paints nothing of its own and is
  transparent to the mouse.

### `ui/widgets/carousel.py`

Module helpers: `_force_white_fills(node)` (flattens Bodymovin fills to
white), `_wave()` (the cached rlottie animation, frame count and fps),
`_svg_renderer(name, color=None)` (a cached `QSvgRenderer`, optionally
recoloring every `fill="currentColor"` via a raw string replace before
parsing — not a pre-rendered bitmap, which showed a visible stepped edge at
badge scale even through `SmoothPixmapTransform`), `_paint_info_badge` /
`_paint_info_badge_faded` (the info badge, full and hover-faded-while-
expanded variants, both painting a plain disc in the glyph colour first
so `info.svg`'s cut-out "i" hole shows it through).

- `WaveLayer(QWidget)` — the Wave Loop visualiser (loops `_loop_length` = 238 frames: the file's last two duplicate its first two, which made every restart step backwards; frames are paced by a single-shot timer armed for each frame's own due time); `_close_wave_seam` re-times the wrap-around dot column in the parsed JSON (start 240 -> 238, the wave's real period) so the two halves of the picture no longer meet 2 frames out of phase and split the centre column of dots, a mouse-transparent child
  of the tab; `start`, `stop`, time-based `_index`, `_render` (rlottie →
  ARGB32 `QImage`, band crop, gradient via `SourceIn`, cached per frame and
  size).
- `_InfoTooltip(ScaledLabel)` — the info badge's tooltip window. Positioned above the badge itself (`ThumbnailCarousel._badge_global_rect`), clear of its hover area — anchored to the carousel's corner it landed on the badge in the expanded preview and flickered — and an interactive window: the pointer can move onto it and keep it up (mouse-driven hides wait a 50ms grace, `_tooltip_grace` / `_grace_expired`, which judges from where the cursor is then).
- `_ExpandedPreviewOverlay(QWidget)` — a translucent scrim, sized to the
  main window's own footprint (not a separate top-level window — that stole
  window activation and broke the app-level Left/Right keybind), that
  temporarily reparents a `ThumbnailCarousel` into itself at a bigger,
  centred size while its expand icon is on; `show_with(carousel)` /
  `release()` do the reparenting, `mousePressEvent` collapses back on a
  click outside the carousel's own bounds. One instance per `MediaTab`
  (`ui/tabs/media_tab.py`'s `_on_expand_toggled` owns it).
- `ThumbnailCarousel(QWidget)` — signals `reselect`, `populated`,
  `indexChanged`, `fileDropped`, `expandToggled(bool)`; public `set_frames`,
  `set_strip_state`, `set_audio_only`, `set_media_info`, `current_index`,
  `step`, `sync_index`, `force_collapse` (shrinks back from expanded, used
  when the previewed file is about to change out from under it),
  `forget_populated()` (`populated` fires once per carousel; a tab that puts its drop box
  back over the carousel — a rejected import, or a file with no preview frames — calls
  this, or the box stayed up over a later file that did load);
  the info tooltip's placement and lifetime (`_badge_global_rect` — above the badge, from
  the Wave Loop layer's own rect in wave mode; `_refresh_open_tooltip` — re-words and
  re-anchors an open tip when the mode flips; `_hide_tooltip_soon` / `_grace_expired` —
  the 50ms `_TIP_GRACE_MS` window); the hover hit-test in wave mode maps the pointer onto
  the layer through *screen* coordinates, since the layer is a sibling of the carousel, not
  an ancestor (a `mapTo` toward a non-ancestor never registered a hover on the badge);
  the carousel paints in **real pixels** (its frame and hit-testing are fractions of a real
  rect), with `px()` / `fpx()` on its few absolute constants;
  geometry (`_frame_rect`, `_pixmap`, `_disc_centers`, `_dot_geometry`,
  `_resolve_dot_start`, `_centered_dot_start`, `_expand_icon_rect`);
  painting (`_paint_dots`, `_paint_chevrons`, `paint_badges`,
  `_paint_expand_icon`); animation (`_fade_to`, `_step`, slide/fade state);
  input (`_press` for press and double-click, drop handling,
  `_over_info_badge`, `_over_expand_icon`, `_toggle_expand`, tooltip text
  via `_info_text` / `_mastering_text`). While `_expanded`: the dot row
  scales 1.5x (`_dot_scale`), the mute badge would scale 0.5x
  (`_icon_scale`) but in practice is never painted at all, the info badge
  fades with hover instead of always showing (`_info_badge_scale`,
  `_paint_info_badge_faded`), and double-click-to-reselect is disabled.

### `ui/widgets/dialogs.py`

- `MessageDialog(QDialog)` — title, wrapped message, optional entry,
  buttons (first = the `action` role, the rest `queue` — a theme can swap them); Enter
  confirms, Escape/close decline; `show_modal()` returns the pressed label or None.
  `_build_extra` is the subclass hook. **Every popup is borderless**
  (`Qt.FramelessWindowHint` + `WA_TranslucentBackground`, all subclasses inherit it):
  `paintEvent` draws the rounded panel (`_RADIUS` 8, the window colour outlined
  `_BORDER` 2px in the theme's `primary`) and, with no title bar, `mousePressEvent` — a
  left press on any part a child didn't take — drags it with `startSystemMove`. It styles
  itself in its constructor (`T.stylesheet()` plus `QDialog { background: transparent; }`
  so the sheet's square fill doesn't show at the corners): a window restyles only what is
  on screen, so a dialog built later must not inherit a stale application-level sheet.
  The OS file pickers stay native.
- `show_message`, `ask_yes_no`, `ask_text`, `confirm_output_path`.
- `CountdownDialog(MessageDialog)` / `confirm_countdown(parent, title, message,
  seconds=30, now_label="Now")` — a confirmation that goes ahead by itself:
  `message` (with `{n}` for the seconds left) counts down once a second and the
  dialog answers "Now" at zero. The first button acts immediately; Cancel,
  Escape and the close box call it off. Returns True when it ran out or "Now" was
  pressed. Used for When Done's Shutdown / Sleep / Hibernate / Log Off.
- `AudioStreamPickerDialog(MessageDialog)` / `choose_audio_streams` — Encoding's Choose
  Stream(s): only the tracks (`SHOW_HEADER = False`: no title or text) in a `TrackListBox`
  (tick to include, drag to reorder), then one bottom row — Add Stream(s), Remove Stream(s)
  (left, via the `_build_leading_buttons` hook), OK, Cancel (right); `WIDTH = 500` (a class
  attribute on `MessageDialog`, default 400) to fit it; edits a copy of the list (Cancel discards). Add appends another file's audio
  stream(s) ticked; Remove takes ticked rows out, the source's own included. OK returns
  `(entries, ticked ids)`, never none ticked while rows exist; Cancel returns None.
  `MessageDialog.SHOW_HEADER` (class attribute, default True) is what lets a dialog skip its
  title and message.
- `ExternalStreamPickerDialog(MessageDialog)` / `pick_external_streams` —
  same checkbox-per-stream shape, for choosing which stream(s) of a second,
  browsed-in file Muxing's "Add Stream(s)" pulls in.

### `ui/widgets/frameless.py`

The Borderless window's own chrome — a frameless window has no OS title bar or border.
- `_tinted_svg(name, color)` — a cached `QSvgRenderer` for `assets/<name>` with every
  painted `fill` swapped for `color` (a string swap, so it stays a vector and is smooth
  at any scale; the three window icons ship in three different colours).
- `WindowControls(QWidget)` — Close, Maximise, Minimise, in that order, as the bare
  icons (no shapes behind them), signals `closeRequested` / `maximizeRequested` /
  `minimizeRequested`. A child of the `Sidebar` placed by absolute geometry in its 24px
  top strip (`LEFT`, `SLOT_W`, `HEIGHT`), so it takes no part in the sidebar's layout
  and cannot move the title. Icons draw in `primary_text`; each lights up under the
  pointer by recolouring the icon — Close in STOP_RED, the others in the theme's
  secondary. `ICON_SIZES` = (20, 16, 16): the close X fills 60% of its 24-unit box where
  the maximise square fills 83%, so equal sizes made Close look small. The
  straight-edged icons are snapped to whole device pixels (`_icon_rect`, painted in real
  pixels): the maximise square is only 2 of 24 units thick, and a fractional position
  put each line across two pixels at ~67% coverage, visibly lighter at some scales.
  `set_maximize_enabled` dims Maximise (borderless fullscreen).
- `ResizeGrips(window)` / `_Grip` — eight invisible real-pixel strips (`_EDGE` 5px,
  `_CORNER` 10px) on the window's outline; a left press calls
  `windowHandle().startSystemResize(edges)`, so it is the native resize, snapping and
  cursors included. Real pixels on purpose: they stand in for OS chrome, which doesn't
  scale with the app. `set_active(bool)` shows or hides them, `place()` re-lays them
  above everything else after every resize.

### `ui/widgets/toast.py`

- `Toast(QWidget)` — slide in, hold, fade; `start`, `reposition`, `retire`,
  `dismiss`; click runs its callback.
- `ToastManager` — `show(message, on_click)` (retires the oldest past three),
  `relayout`, `raise_all` (brings every live toast back above whatever was raised since —
  `MainWindow._restack`), `forget`, `clear`; slots hang off the tab frame's top-right.
  Sizes are reference px (`scale.fixed`, `px()` for the slide and stack offsets).

### `ui/widgets/tracklist.py`

Row text, shared by Muxing's boxes and Encoding's Choose Stream(s) popup (their rows are
the same shape of entry): `stream_details(kind, stream, compact=False)` (the descriptive
fields of one stream in row order — video: codec, profile, level, size, fps, HDR kind, bit
depth + chroma, bit rate, language; audio: codec, channels, sample rate, language;
`compact` is the "Add Stream(s)" picker's shorter version, HDR only when it is),
`describe_stream(kind, stream)` (the picker's caption: the stream's own track number *in
its file*, then the compact details) and `row_label(kind, entry, number)` (`Track N  ·
[External: name  ·]  details`, N being the row's place in the list — removing a track
renumbers the ones below it).

- `_DragGhost(QWidget)` — the snapshot of a row that follows the cursor during a drag, on
  a rounded (`px(6)`) slab in the `window` colour. The snapshot is rendered onto a
  transparent pixmap (`snapshot`) and clipped to the same rounded path, so the corners stay
  round — `QWidget.grab()`'s opaque background rectangle used to cover them.
- `_TrackRow(QWidget)` — one row: a text-less `CheckBox` plus a `MarqueeLabel`
  (Arial 12 bold, matching the checkbox's old caption) joined to the box's one
  `MarqueeGroup`, so a long label (an `External: …` row) scrolls while short ones
  sit still. A click anywhere on the row toggles the checkbox, and hover is
  forwarded through `CheckBox.set_hover`.
- `TrackListBox(QWidget)` — Muxing's checkable, scrollable track picker
  (replaced the original single `Auto`/`Track N` dropdown): one checkbox row
  per stream, any combination checked maps into the output. `set_items(items,
  reset=False)` is its own single constraint pass — diffs by row id when
  `reset=False` (an id already present keeps its checked state, just gets
  its label refreshed), tears down and rebuilds from scratch when `True` (a
  new input file — a same-named row from a different file must never be
  mistaken for a carried-over pick). A brand new row starts checked — every track is
  selected by default (unless `set_items(checked=...)` is given: it
  then decides every row's ticks, existing rows too — an undo/redo). It also puts the rows in the order of the
  list it's given. `set_checked(row_id, checked)` (the
  programmatic counterpart of clicking a row's own checkbox — doesn't emit
  `changed`), `item_count()`, `item_ids()` (every row's id, checked or not —
  what Select All / Deselect All iterate, unlike `checked_ids()`). **Drag to reorder**: a
  press that moves past `QApplication.startDragDistance()` picks the row up
  (`_begin_drag`; any row, checked or not — the row's `CheckBox` is mouse-transparent so
  the drag can start on it, and a press without movement still toggles). The row stays in
  the layout as a dimmed placeholder, moved through it by `_follow_cursor` as a
  `_DragGhost` tracks the cursor; a 16ms `_autoscroll` timer scrolls the list near its
  top/bottom edge; `_end_drag` emits `reordered(ids)` (every id, top to bottom) only if the
  order changed. `setFixedHeight` — fixed, not a minimum, so a
  heavily-populated box never grows the panel around it (`MuxingTab.
  _track_panel` sets it to exactly `Overview`'s own `sizeHint().height()` —
  see the DropBox-height invariant note under `ui/widgets/panels.py` above).
  Empty state ("No tracks available") is dead-centered, not the scroll
  list's own first row.

### `ui/widgets/tooltip.py`

- `tip(widget, text)` — attaches a shared, themed hover tooltip to any
  widget via one app-wide `_TooltipManager` event filter (a tip shows once the cursor has hovered *and stopped* for
  `TIP_DELAY_MS` = 400ms — the cursor is sampled every 30ms (`_POLL_MS`) while one is pending
  and a drift of ≤1px counts as still, so any real move restarts the wait; the
  carousel's info-badge tip does not follow this rule — it shows at once); works even on a disabled widget, and syncs the cursor to a plain
  arrow while disabled.
- `_Tooltip(ScaledLabel)` — the shared popup itself (fade-in only). The manager sizes it
  itself — width clamped to the maximum, then `heightForWidth` *at that width* — rather
  than `adjustSize`, which works the height out at the unclamped hint width and cut the
  last lines off a long tip.
- `_TooltipManager` — the single installed event filter every `tip()` call
  registers with, rather than each widget running its own timer/popup pair.
- `hold_tips(held)` — suspends every tooltip (hiding the one showing) until released; the
  track list holds them for the length of a row drag, since a press on a row never reaches
  the box the tip is registered on. Releasing re-arms the hover delay if the cursor is still
  over the last-hovered widget.
