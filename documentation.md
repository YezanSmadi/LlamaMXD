# LlamaMXD — File-by-File Documentation

This document goes through every file in the repository and explains what it
contains and what it does. For narrative architecture notes, the rules each
tab enforces, known gotchas, and conventions, see [`CLAUDE.md`](CLAUDE.md) —
this file is a per-file reference instead.

Directory layout:

```
LlamaPY GUI/
├── main.py
├── requirements.txt
├── LICENSE
├── .gitignore
├── .vscode/
│   └── settings.json
├── assets/
│   ├── llama.ico, LlamaMXD-Logo.svg, RCA Cable Yellow.svg
│   ├── audio-mute.svg, info.svg, expand.svg, shrink.svg
│   ├── select-multiple.svg, deselect-multiple.svg
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
│   ├── system_info.py
│   ├── theme.py
│   ├── tools.py
│   ├── utilities.py
│   └── ytdlp_runner.py
└── ui/
    ├── app.py
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
addApplicationFont` for every `.ttf`/`.otf` in `assets/fonts`) and makes
Roboto 13px the application font, then — in this order, because each needs
the one before — `init_workers()` (the GUI-thread signal bridge),
`T.init_theme()` (the `ThemeManager`, which reads `settings.json`) and
`app.setStyleSheet(T.stylesheet())`. Only then does it import and show
`ui.app.MainWindow` and enter `app.exec()`.

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

### `LICENSE`

The [Unlicense](https://unlicense.org) — public-domain dedication, no
copyright restrictions and no warranty.

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
- **`select-multiple.svg`** / **`deselect-multiple.svg`** — the Select All /
  Deselect All icons on Muxing's track boxes. Stroke-drawn in black;
  `controls._icon_svg` swaps the stroke for the button's own text colour.
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

- `THEMES` — seven palettes (`Lemon`, `Cupid`, `Lilac`, `Ranger`, `Noir`,
  `Luck`, `Vaporwave`), each a flat-hex `primary` and `secondary` (optionally
  an explicit `primary_hover`; Lemon keeps its historical `#e0b234`).
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
  `*_disabled_text`, falling back to the default theme for an unknown name.
- `default_output_dir()` — `~/Videos/LlamaMXD Export`.
- `load_settings()` / `save_settings(settings)` — `settings.json` beside
  `main.py`: `theme`, `appearance_mode` (`System`), `default_save_location`
  (`default_output_dir()`), `gpu_enabled` (`True`),
  `downloader_separate_save` (`False`), `downloader_save_location` (`""`),
  `naming_template` (`core.naming.DEFAULT_TEMPLATE`), `when_done` (`Do
  Nothing`), `when_done_reset` (`True`), `priority_level` (`Normal`).
  Missing keys or a missing/corrupt file fall back to those defaults, and so
  does a stored `naming_template` / `when_done` / `priority_level` that's no
  longer valid (a hand-edited file) — checked against `core.naming`,
  `core.power` and `core.priority`, which this module imports for that. The
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
  idea as Resolution: `"Source"` (no change) plus a fixed ladder of round
  rates (`"60"` … `"24"`, then `"12"`/`"8"` for deliberately choppy output —
  whole numbers, not the NTSC-exact 29.97/23.976, since ffmpeg's `-r` retimes
  onto an integer without this app reproducing drop-frame arithmetic).
  `fps_values_for` caps the list to `"Source"` plus every rung at or below the
  source's own rate — never a speed-up — with a 0.1 tolerance so a true
  29.97/23.976 source still offers the round 30/24 just above it, and offers
  the full ladder when the rate isn't known yet. `fps_arg_for` is the reverse
  lookup `ffmpeg_vars._fps_arg` uses (`None` for `"Source"`).
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

`extract_video_thumbnails(video_path, count=10)`: Opens `video_path` with
`cv2.VideoCapture` and reads `count` frames spread evenly across the video's
*interior* (`_interior_sample_frames` — the fractions `(i+1)/(count+1)`,
deliberately avoiding a black/blank first frame and an end-credits/fade-out
last frame). For each point it seeks, reads, converts BGR→RGB, and wraps the
frame in a `PIL.Image`. Returns 1–`count` images (shorter if the clip is too
short or some seeks fail), a single first-frame read when the container
reports no usable frame count, or `[]` if nothing decodes at all.

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
missing / `"0/0"` value), and the container's `title` / `chapters` (a count) /
`bit_rate` (overall bits per second) / `creation_time` — the values behind the
`{title}` `{chapters}` `{bitrate}` `{creation-time}` naming tokens
(`core/naming.py`), each `None` when the file has none. `audio_streams` (every
audio stream, each described by
`_describe_audio_stream` — codec/channels/rate/bitrate/language — for the
Encoding tab's multi-track picker), and, only for HDR content,
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
thread). Same all-`None`-on-failure contract.

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
- `supports_libplacebo()` — whether `libplacebo` is compiled in; parses
  `ffmpeg -filters`. A filter merely *listed* but failing at runtime (no
  usable Vulkan device) still surfaces as a normal Failed job.
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
ffmpeg-ready form (`{"src_index", "codec_arg", "bitrate_arg",
"channels_arg", "sample_rate_arg", "language"}`); a Passthru stream (forced
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
value — `None` for `"Source"` or when the pick is no longer at or below the
source's own rate (the same re-validation `_scale_vf` does, for the same
reason).

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
on its own). Raises `ValueError` if `HDR_TO_SDR` is set but
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
  `naming_template`, `priority_level`, `when_done` (starts on Do Nothing when
  `when_done_reset` is set, so a Shutdown chosen last session can't surprise
  this one), `downloader_separate_save` /
  `downloader_save_location` (the Downloader's own optional save folder,
  off by default), `media_info` (`_empty_media_info()` — every
  probe key `None`, `audio_streams` `[]`), `thumb_frames` /
  `thumb_frames_path`, `hdr_frames` / `hdr_frames_path`, `ytdlp_cache`,
  `deno_missing`, `tabs` (built once — `Queue` first — and stacked in a
  `QStackedWidget`), `media_tabs`, `current_tab`.
- **Layout**: fixed at 35% x 37.5% of the screen and centred; `Sidebar` on the
  left, `#TabFrame` (holding the stack) on the right, the `TabIndicator` and a
  `ToastManager` on top.
- `show_tab(name, animate=True)` — the outgoing tab's `on_leave`, switch,
  `indicator.set_active` (plugs the new button's cable in and pulls the old one
  out), take focus back from anything but a line edit, re-seat
  toasts. `showEvent` does the first alignment after geometry settles.
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
- `_restyle` — re-applies the stylesheet on `ThemeManager.changed`.
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
  mode), merges `core.theme.get_theme` with the neutrals and adds `stop*` and
  `*_pressed`. Follows the OS scheme live while in System mode.
- `init_theme()` / module global `theme` — the one instance.
- `lerp(a, b, t)` / `with_alpha(color, alpha)` — QColor helpers used by the
  painted widgets.
- `stylesheet()` — the app-wide stylesheet for stock widgets, keyed by a
  dynamic `role` property on buttons (`primary`, `danger`, `ghost`,
  `stepper`) and labels (`field`, `field11`, `muted`, `meta`, `hint`, `title`,
  `dialogTitle`, `detailTitle`, `detailKey`, `error`, `empty`, `warn`,
  `sidebarTitle`, `sidebarFooter`), plus line edits, the slider, scrollbars
  and the combo popup (`combobox-popup: 0` so it drops below the button).

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
  `(menu, label)` pairs `extra` names. Start Time, Clip Duration, A/V Sync and
  the preset Save/Delete buttons disable with them (values untouched). Output
  Format/Preset/the spinners get their enabled state set *both ways*
  unconditionally, because nothing else ever re-enables them; `extra` dropdowns
  only need the no-file side, since each one's own enabled state is recomputed
  fresh every pass by the rest of `_sync_controls`.
- `_on_control_change`, `_on_trim_change` (rundown only), `_on_format_change`
  (stops auto-adopting the source container, swaps the save path's
  extension).
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
  `Remove Stream(s)` (danger-role) sharing a line with the Strip checkbox. The
  two-across rows are what keep the four-row column under the box's fixed
  height. Fixes the box's height to exactly
  `self.panels.widget(0).sizeHint().height()` (Overview's own height) — the
  DropBox-height invariant above, enforced here specifically.
- `_add_stream(kind)` browses a second file and probes it off the GUI
  thread; `_stream_probed(kind, path, info)` adds its lone matching-kind
  stream straight away, or opens `ExternalStreamPickerDialog` (`ui/widgets/
  dialogs.py`, via `pick_external_streams`) when it has more than one. Added
  streams are kept in `_video_external`/`_audio_external`
  (`{row_id: {"file", "index", "label"}}`), independent of the primary
  input.
- `_select_all(kind)` / `_deselect_all(kind)` check / uncheck every row
  (`TrackListBox.item_ids()`, regardless of current state) without adding or
  removing any — the non-destructive counterpart to Remove.
- `_remove_streams(kind)` acts on every currently-checked row: an external
  row is dropped from the box outright, a source row (the primary file's
  own track, which can't actually be deleted) is unchecked instead
  (`TrackListBox.set_checked`). Shows a message rather than doing nothing
  when nothing's checked.
- `_items_for(kind)` builds `TrackListBox.set_items`' row list (the primary
  file's own probed streams plus whatever's in `_video_external`/
  `_audio_external`); `_track_args(kind)` turns the box's *checked* rows into
  the `video_tracks`/`audio_tracks` settings shape (`{"source", "file",
  "index"}`, one entry per checked row).
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
- Multi-stream audio: `_audio_track_values`, `_index_from_track_label`,
  `_save_active_audio_stream`, `_active_stream_info`,
  `_apply_passthru_values`, `_load_active_audio_stream`,
  `_on_audio_track_change`, `_open_stream_picker`,
  `_auto_select_audio_streams`, `_stream_language(index)` (the probed
  language tag for one stream, snapshotted into each gathered
  `audio_streams` entry — see `core/ffmpeg_build.py`'s stale-metadata note).
- `_refresh_summary`, `on_media_info` → `_auto_select_codecs`,
  `_gather_settings` (also carries `resolution`/`fps` and snapshots
  `source_height`/`source_fps`, facts about the input at queue time, same
  convention as `mastering_max_nits`/`max_cll`), `_apply_settings` (dependency order), `_validate_specific`.

### `ui/tabs/downloader.py`

Helpers `_human_size`, `_hms`, `_dropped_link(mime)` (the one http(s) link a
drag carries, or None). `_Thumbnail` (the fetched thumbnail, fitted with
rounded corners) and `_LinkDropFrame` (the preview box, accepting only a
link).

`DownloaderTab(QWidget)` — `set_deno_missing`, `paste_and_fetch`,
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
  signals `clicked`, `removeRequested`).
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
  the list without picking reverts) and Appearance Mode (System / Light / Dark).
- **Output** — Default Save Location (entry + Browse, with the drive's total/free
  space beneath, in STOP_RED at or below 25GB free), Separate Save for Downloader
  (reveals a second entry + Browse for the Downloader's own folder), and File
  Naming (an entry with the token list beneath it turning into a STOP_RED reason
  while what's typed is invalid; nothing is applied until Enter/focus-out, and
  never while invalid).
- **Performance** — Hardware Acceleration (GPU) (a `Switch` with a status line
  naming the GPU, its encoder brand and the codecs it covers — or that none was
  found; forced off and greyed out without a dedicated GPU), Priority Level
  (High … Low, applied to a running job immediately) and When Done (with a
  "Reset to 'Do Nothing' when the app is relaunched" checkbox, on by default).

Methods: `_settings_snapshot` (persists `app.gpu_preference`, not the
possibly-forced-off switch; and the Downloader's entry text only while
separate-save is on — the display text while it's off is the shared default shown
as a fallback, never itself a real separate location), `_sync_state_from_widgets`,
`autosave`, `on_leave`, `on_enter` (refreshes disk usage — free space can change
while the app sits elsewhere), `_show_swatches`, `_preview_theme` (hover),
`_end_preview` (list closed), `_on_theme_change` (commit), `_on_appearance_change`,
`_browse_save_location`, `_refresh_disk_usage`, `_on_downloader_separate_toggle`,
`_browse_downloader_location`, `_validate_naming_text` / `_commit_naming` (against
`core.naming.template_error`; pushes a valid format to
`app.set_naming_template`), `_on_priority_change`, `_on_when_done_change`,
`_on_when_done_reset_toggle`, `_on_gpu_toggle` (also refreshes the status label
via `_refresh_gpu_status`), `_on_save` (persists and toasts "Settings saved." — no
jump to the Queue), `_on_reset_defaults` (`ask_yes_no`-confirmed — resets theme,
appearance mode, default save location, the Downloader's separate-save toggle and
location, GPU acceleration, file naming, priority level and When Done all back to
their defaults in one action, then autosaves). Settings also autosave when the tab
is left and on close.

### `ui/widgets/controls.py`

Helpers: `NO_OPTION` (`"—"`), `ui_font(px, bold, family)`, `field_label`,
`labeled(label_text, widget)` → `(box, label)`, `button(text, role, width,
height)` (NoFocus, pointing cursor), `button_width_for(texts)` (fits the
widest of several button labels), `restyle(widget)`, `set_enabled(widget,
label, enabled)`, `anim(owner, duration, on_value, curve)`,
`draw_cross(painter, rect, color)`.

- `IconButton(QPushButton)` — a painted ✕ / ▲ / ▼ glyph, or an SVG icon
  (`select-multiple` / `deselect-multiple`). SVG icons go through `_icon_svg(name,
  color)`, a cached `QSvgRenderer` whose literal black strokes (both the inline
  `stroke="#000000"` attribute and a `stroke: #000;` CSS property — each asset
  uses a different one) and `fill="currentColor"` are string-replaced with the
  button's own text colour before parsing. Drawn square (0.56 of the shorter
  side) and centred — `render(rect)` on a wide rect would stretch the icon.
- `ClickableLabel(QLabel)` — emits `clicked`.
- `Dropdown(QComboBox)` — self-painted (the `NO_OPTION` placeholder is centred,
  real text left-aligned); `picked`, `hovered`, `popupClosed`;
  `value`, `values`, `set` (display override for an unlisted value),
  `set_values`, `close`, `width_for`; the popup unrolls via an animated mask.
- `CheckBox(QAbstractButton)` — `color_key`, fading fill, greyed when
  disabled; `set_hover(bool)` lets a caption-less checkbox's row drive its hover
  shade.
- `Switch(QAbstractButton)` — sliding knob.
- `SegmentedButton(QWidget)` — sliding selection pill; `changed`, `value`,
  `set`.
- `_TimeField(QWidget)` + `TimeSpinner(QWidget)` — the HH:MM:SS field and its
  accelerating ▲/▼ stepper; `seconds`, `set_seconds`, `valueChanged`.
- `MarqueeLabel(QWidget)` — scrolls overflowing text; `setText`, `text`,
  `set_color_key`, `doubleClicked`. `MarqueeGroup` — one shared clock several
  `MarqueeLabel`s can join (`SummaryPanel`'s Video/Audio/Length rows and every
  `TrackListBox` row do) so they all sweep and restart in step rather than
  drifting apart; `unregister(label)` drops a label about to be destroyed, and a
  label that *starts* scrolling restarts the shared loop rather than landing
  mid-phase.

### `ui/widgets/panels.py`

Constants `ASSETS`, `VERSION`, `MEDIA_FILTER`; `local_paths(mime)` (local
files carried by a drag).

- `SubTabBar(QWidget)` — `changed`, `active`, `set_active`, `set_marked`. The
  active tab is `primary` at 30px, inactive `secondary` at 24px, bottom-aligned
  and standing on a 4px square-ended `primary` line (`_LINE_H`) that runs the
  bar's whole width — the tabs are drawn a corner-radius taller and clipped so
  their feet sit flat on it (34px in total).
- `DropBox(QWidget)` — `fileSelected`, an optional `start_dir` callable (the
  folder Browse opens in — `MediaTab._output_directory`, not the app's working
  folder), `collapse` (leaves only Browse once a
  file is chosen), `reset` (the reverse — back to pristine, used when a
  picked file turns out unreadable), `browse`; drag-over highlight.
- `BorderedFrame(QWidget)` — the border alone; `color_key` defaults to
  `primary`, `TrackListBox` (`ui/widgets/tracklist.py`) passes `secondary`.
- `SummaryPanel(QWidget)` — `set_values(rows)`.
- `Sidebar(QWidget)` — `navigate` signal, `buttons` dict, `WIDTH`,
  `NAV_BUTTON_WIDTH` (110 — narrower than the sidebar, so the gap the cable runs
  through is wide enough to see its lead trail out from behind the button); the
  logo (`assets/LlamaMXD-Logo.svg`) is rendered at 4x oversample and re-tinted to
  `primary_text` via `CompositionMode_SourceIn` (`_load_logo`), so it changes
  colour with the theme the same way the title text does.
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

- `WaveLayer(QWidget)` — the Wave Loop visualiser, a mouse-transparent child
  of the tab; `start`, `stop`, time-based `_index`, `_render` (rlottie →
  ARGB32 `QImage`, band crop, gradient via `SourceIn`, cached per frame and
  size).
- `_InfoTooltip(QLabel)` — the info badge's tooltip window.
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
  when the previewed file is about to change out from under it);
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
  buttons (first = primary); Enter confirms, Escape/close decline;
  `show_modal()` returns the pressed label or None. `_build_extra` is the
  subclass hook.
- `show_message`, `ask_yes_no`, `ask_text`, `confirm_output_path`.
- `CountdownDialog(MessageDialog)` / `confirm_countdown(parent, title, message,
  seconds=30, now_label="Now")` — a confirmation that goes ahead by itself:
  `message` (with `{n}` for the seconds left) counts down once a second and the
  dialog answers "Now" at zero. The first button acts immediately; Cancel,
  Escape and the close box call it off. Returns True when it ran out or "Now" was
  pressed. Used for When Done's Shutdown / Sleep / Hibernate / Log Off.
- `AudioStreamPickerDialog(MessageDialog)` / `choose_audio_streams` — one
  checkbox per probed stream; never returns an empty set.
- `ExternalStreamPickerDialog(MessageDialog)` / `pick_external_streams` —
  same checkbox-per-stream shape, for choosing which stream(s) of a second,
  browsed-in file Muxing's "Add Stream(s)" pulls in.

### `ui/widgets/toast.py`

- `Toast(QWidget)` — slide in, hold, fade; `start`, `reposition`, `retire`,
  `dismiss`; click runs its callback.
- `ToastManager` — `show(message, on_click)` (retires the oldest past three),
  `relayout`, `forget`, `clear`; slots hang off the tab frame's top-right.

### `ui/widgets/tracklist.py`

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
  mistaken for a carried-over pick). A brand new row defaults to checked
  only in the very first position. `set_checked(row_id, checked)` (the
  programmatic counterpart of clicking a row's own checkbox — doesn't emit
  `changed`), `item_count()`, `item_ids()` (every row's id, checked or not —
  what Select All / Deselect All iterate, unlike `checked_ids()`). `setFixedHeight` — fixed, not a minimum, so a
  heavily-populated box never grows the panel around it (`MuxingTab.
  _track_panel` sets it to exactly `Overview`'s own `sizeHint().height()` —
  see the DropBox-height invariant note under `ui/widgets/panels.py` above).
  Empty state ("No tracks available") is dead-centered, not the scroll
  list's own first row.

### `ui/widgets/tooltip.py`

- `tip(widget, text)` — attaches a shared, themed hover tooltip to any
  widget via one app-wide `_TooltipManager` event filter (400ms hover
  delay); works even on a disabled widget, and syncs the cursor to a plain
  arrow while disabled.
- `_Tooltip(QWidget)` — the shared popup itself (fade-in only).
- `_TooltipManager` — the single installed event filter every `tip()` call
  registers with, rather than each widget running its own timer/popup pair.
