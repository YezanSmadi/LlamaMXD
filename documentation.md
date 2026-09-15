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
│   ├── llama.ico, llama.png
│   ├── audio-mute.png, audio-mute.svg
│   ├── Wave Loop.json
│   ├── info-icon-dark.png, info-icon-light.png
│   ├── fonts/  (Roboto-Regular.ttf, Roboto-Medium.ttf)
│   └── (source design files: dark/light mode info icon .eps/.jpg, not read by code)
├── scripts/
│   └── make_info_badges.py
├── core/
│   ├── downloader.py
│   ├── ffmpeg_build.py
│   ├── ffmpeg_runner.py
│   ├── ffmpeg_vars.py
│   ├── formats.py
│   ├── presets.py
│   ├── theme.py
│   ├── tools.py
│   ├── utilities.py
│   └── ytdlp_runner.py
└── ui/
    ├── app.py
    ├── theme.py
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
        └── toast.py
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
- **`llama.png`** — the sidebar logo, scaled to 140×140 at the screen's
  device-pixel ratio (`ui/widgets/panels.py`'s `Sidebar`).
- **`audio-mute.png`** / **`audio-mute.svg`** — the red speaker-with-X badge
  drawn top-left on the preview while audio is stripped
  (`ui/widgets/carousel.py`). The `.svg` is source artwork, not loaded.
- **`Wave Loop.json`** — the Bodymovin/Lottie dot-wave animation shown in
  place of a stripped-video or audio-only preview, rendered by
  `rlottie-python`.
- **`info-icon-dark.png`** / **`info-icon-light.png`** — the bottom-left info
  badge (one per resolved appearance mode), generated from the checked-in
  `.jpg` source art by `scripts/make_info_badges.py`. The `.eps` files are
  original vector art, not read by code.
- **`fonts/`** — Roboto Regular and Medium (Apache 2.0), the app typeface,
  registered by `main.py` so text renders the same with or without Roboto
  installed.

### `scripts/make_info_badges.py`

A one-off conversion script, not imported by the app: turns the two source
JPGs (`dark mode info icon.jpg` / `light mode info icon vector.jpg`) into the
transparent-cornered `info-icon-dark.png` / `info-icon-light.png` badges.
`content_bbox` finds the drawn circle's bounding box (everything that isn't
near-white), crops to a square around its center, then clips to a
supersampled circular alpha mask sized to that box — preserving each icon's
interior fill exactly rather than chroma-keying white (which would hollow out
the light badge). Run manually (`python scripts/make_info_badges.py`) only
when a source `.jpg` is replaced.

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
  (`default_output_dir()`), `gpu_enabled` (`True`). Missing keys or a
  missing/corrupt file fall back to those defaults.

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

### `core/presets.py`

Named codec/quality recipes, persisted to a gitignored `presets.json` at the
repo root shaped `{tab: {name: settings}}`.

A preset is a **recipe, not a job**: `PRESET_KEYS` limits what's stored to
the container, the `av_sync` flag and the codec/quality choices, and
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
`audio_streams` (every audio stream, each described by
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
ffmpeg-ready form; a Passthru stream (forced on for `formats.
is_passthru_only` codecs, or a deliberate pick) always comes out
`"copy"`/`None`/`None`/`None` regardless of its other display fields.

`MASTERING_MAX_NITS`/`MAX_CLL` carry the source's probed HDR static
metadata through (snapshotted at queue time by `EncodingTab._gather_
settings`, not read live) — both together decide `build_encode_command`'s
`peak_detect` argument; see `core/utilities.py`'s `libplacebo_tonemap_vf`
above.

A key belonging to the other tab keeps a default that happens to be
correct for it too — e.g. a Mux job's `VIDEO_CODEC_ARG` comes out `"copy"`,
exactly right since Muxing always is. Muxing never touches `AUDIO_STREAMS`
at all; it maps its single `AUDIO_TRACK`/`AUDIO_TRACK_INDEX` straight
through `build_mux_command`.

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

HDR→SDR (`uses_hdr_tonemap()` gates it) adds `core.utilities.
libplacebo_tonemap_vf(peak_detect=...)` as `-vf`, plus explicit
`-color_primaries/-color_trc/-colorspace bt709` output tags (libplacebo's
target colorspace doesn't reliably propagate to the output stream's own tags
on its own). Raises `ValueError` if `HDR_TO_SDR` is set but
`supports_libplacebo()` is false — should be unreachable in practice
(`EncodingTab._validate_specific` blocks it first), but this is the last
line of defense, caught by `QueueTab._process_next`'s "couldn't build the
ffmpeg command" Failed-task path.

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
window), at the OS's normal process priority (profiled: throttling it bought
no protection and only slowed encodes down, so a `BELOW_NORMAL_PRIORITY_
CLASS` attempt was removed).

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
- `_folder_bytes` uses `os.stat(path)`, not `DirEntry.stat()` — the latter is
  stale for a file another process still has open.

---

## `ui/` — the PySide6 interface

### `ui/app.py`

`MainWindow(QWidget)` — the window and the app's hub; every tab receives it as
`app`.

- **State**: `current_file_path`, `default_save_location` (created at startup,
  best-effort), `gpu_enabled`, `media_info` (`_empty_media_info()` — every
  probe key `None`, `audio_streams` `[]`), `thumb_frames` /
  `thumb_frames_path`, `hdr_frames` / `hdr_frames_path`, `ytdlp_cache`,
  `deno_missing`, `tabs` (built once — `Queue` first — and stacked in a
  `QStackedWidget`), `media_tabs`, `current_tab`.
- **Layout**: fixed at 35% x 37.5% of the screen and centred; `Sidebar` on the
  left, `#TabFrame` (holding the stack) on the right, the `TabIndicator` and a
  `ToastManager` on top.
- `show_tab(name, animate=True)` — the outgoing tab's `on_leave`, switch,
  align the pipe, take focus back from anything but a line edit, re-seat
  toasts. `showEvent` does the first alignment after geometry settles.
- `notify(message, go_to_queue=True)` — posts a toast.
- **File selection**: `register_media_tab(tab)`; `update_global_file(path)`
  (the only place the selected file changes — resets scrub index and
  `media_info` on a new path, updates each media tab, starts
  `_load_thumbnails`); `_load_thumbnails` (cache hit → broadcast; miss → one
  worker: `probe_media` delivered early via `emit_progress`, then ten frames;
  token-guarded); `_deliver_media_info`, `_is_audio_only`,
  `_broadcast_audio_only`, `_broadcast_media_info`, `_deliver_thumbnails`,
  `_broadcast_thumbnails`, `sync_preview_index(index)`.
- **HDR preview**: `start_hdr_render(path)` / `_deliver_hdr` — one tone-mapped
  render per file, cached, token-guarded, broadcast to `on_hdr_frames_ready`.
- **Downloader**: `fetch_ytdlp_info(url)` / `_deliver_ytdlp_info` (worker fetch
  + thumbnail, token-guarded, cached in `ytdlp_cache`); `_deliver_deno_check`
  (the startup Deno check).
- `_restyle` — re-applies the stylesheet on `ThemeManager.changed`.
- `closeEvent` — confirms (pausing the queue for the prompt) when jobs are
  unfinished, autosaves Settings, kills the active job, quits; `_closing`
  stops the close Qt re-sends during `quit()` from prompting twice.

`_Keybinds(QObject)` — an application-level event filter: Left/Right step the
current tab's carousel (not while a text field has focus); Space toggles the
queue on the Queue tab (not for auto-repeat, text fields, buttons or combo
boxes); inactive while a modal is open.

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
- `_on_control_change`, `_on_trim_change` (rundown only), `_on_format_change`
  (stops auto-adopting the source container, swaps the save path's
  extension).
- `select_input_file`, `set_selected_file`, `_reveal_preview`,
  `on_thumbnails`, `_autofill_output_path`, `select_save_location`.
- Presets: `_refresh_preset_menu`, `_on_preset_selected`, `_on_preset_save`,
  `_on_preset_delete`.
- `_apply_common` / `_gather_common` (the shared settings keys),
  `_menu_value` (the `—` placeholder as `""`), `_validate_settings` (input,
  save location, the subclass's `_validate_specific`, then
  `confirm_output_path`), `run_now`, `add_to_queue`.

### `ui/tabs/muxing.py`

`MuxingTab(MediaTab)` — container change and stream selection, always a copy.
`_stream_panel(kind)` builds each of the Video/Audio panels (track dropdown,
`Browse…` for an external file, the Strip checkbox). `_browse_external`,
`_track_values`, `_audio_track_values` (tracks labelled with their probed
codec), `_external_for`. `_sync_controls` (stream presence, track lists, the
container inversion via `_retarget_container` — which toasts a snap and keeps
the save path's extension in step — and panel enabled state),
`_refresh_summary` (with the `· keyframe` trim caveat), `on_media_info`
(adopts the source container), `_gather_settings`, `_apply_settings`,
`_set_menu` (also matches the leading `Track N` token).

### `ui/tabs/encoding.py`

`EncodingTab(MediaTab)` — the re-encode tab.

- `build_video` — Encoder / Profile / Level / Encoder Preset, the quality
  slider (`crf_slider`, inverted; `crf_label`, `crf_low_label`,
  `crf_high_label`), `hdr_label` + `hdr_switch`, `strip_video_check`.
- `build_audio` — `audio_track_menu`, `choose_streams_btn`, `audio_codec_menu`,
  `passthru_check`, `audio_bitrate_menu`, `audio_channels_menu`,
  `audio_samplerate_menu`, `strip_audio_check`; dropdowns sized with
  `Dropdown.width_for` to their longest possible entry.
- `_on_encoder_change`, `_toggle_hdr`, `_on_quality_change`.
- HDR preview: `_on_hdr_toggle`, `on_thumbnails`, `on_hdr_frames_ready`,
  `_apply_preview_frames`.
- `_sync_controls` (the six rules), `_retarget` (toasts a forced snap),
  `_speed_values` / `_apply_speed`, `_apply_quality` / `_update_quality_label`.
- Multi-stream audio: `_audio_track_values`, `_index_from_track_label`,
  `_save_active_audio_stream`, `_active_stream_info`,
  `_apply_passthru_values`, `_load_active_audio_stream`,
  `_on_audio_track_change`, `_open_stream_picker`,
  `_auto_select_audio_streams`.
- `_refresh_summary`, `on_media_info` → `_auto_select_codecs`,
  `_gather_settings`, `_apply_settings` (dependency order),
  `_validate_specific`.

### `ui/tabs/downloader.py`

Helpers `_human_size`, `_hms`, `_dropped_link(mime)` (the one http(s) link a
drag carries, or None). `_Thumbnail` (the fetched thumbnail, fitted with
rounded corners) and `_LinkDropFrame` (the preview box, accepting only a
link).

`DownloaderTab(QWidget)` — `set_deno_missing`, `paste_and_fetch`,
`_on_link_drop`, `fetch`, `on_ytdlp_info`, `_apply_info` (adopts a video,
resetting every pick), `_sync_controls` (Mode → Video Codec → Quality → Audio
Codec → Format, or Format → Quality for Audio Only; resolves the plan for the
size readout and extension), `_show_audio_picker`, `_retarget`, `_menu_value`,
`_current_directory`, `_autofill_output_path`, `_apply_output_extension`,
`select_save_location`, `_gather_settings`, `_validate_settings` (nothing
fetched, link edited since the fetch, no save location, then
`confirm_output_path`), `_describe`, `download_now`, `add_to_queue`.

### `ui/tabs/queue.py`

- `_DETAIL_FIELDS`, `_VIDEO_DETAIL_KEYS`, `_AUDIO_DETAIL_KEYS` — which settings
  keys the details popup shows, and which a stripped stream hides.
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
    `stop_queue`, `shutdown`, `start_task`, `_running_label`;
  - jobs — `_process_next`, `_start_download`, `_start_timers` /
    `_stop_timers`, `_poll` (100ms event drain), `_animate_fill` (16ms fill
    easing), `_halt_active`, `_finish_task`, `_fail_task`, `_show_errors`.

### `ui/tabs/settings.py`

`_Swatch` (a 26px colour chip for the previewed palette). `SettingsTab(QWidget)`
— `_settings_snapshot`, `_sync_state_from_widgets`, `autosave`, `on_leave`,
`_show_swatches`, `_preview_theme` (hover), `_end_preview` (list closed),
`_on_theme_change` (commit), `_on_appearance_change`, `_browse_save_location`,
`_on_gpu_toggle`, `_on_save`.

### `ui/widgets/controls.py`

Helpers: `NO_OPTION` (`"—"`), `ui_font(px, bold, family)`, `field_label`,
`labeled(label_text, widget)` → `(box, label)`, `button(text, role, width,
height)` (NoFocus, pointing cursor), `restyle(widget)`, `set_enabled(widget,
label, enabled)`, `anim(owner, duration, on_value, curve)`,
`draw_cross(painter, rect, color)`.

- `IconButton(QPushButton)` — a painted ✕ / ▲ / ▼ glyph.
- `ClickableLabel(QLabel)` — emits `clicked`.
- `Dropdown(QComboBox)` — self-painted; `picked`, `hovered`, `popupClosed`;
  `value`, `values`, `set` (display override for an unlisted value),
  `set_values`, `close`, `width_for`; the popup unrolls via an animated mask.
- `CheckBox(QAbstractButton)` — `color_key`, fading fill, greyed when
  disabled.
- `Switch(QAbstractButton)` — sliding knob.
- `SegmentedButton(QWidget)` — sliding selection pill; `changed`, `value`,
  `set`.
- `_TimeField(QWidget)` + `TimeSpinner(QWidget)` — the HH:MM:SS field and its
  accelerating ▲/▼ stepper; `seconds`, `set_seconds`, `valueChanged`.
- `MarqueeLabel(QWidget)` — scrolls overflowing text; `setText`, `text`,
  `set_color_key`, `doubleClicked`.

### `ui/widgets/panels.py`

Constants `ASSETS`, `VERSION`, `MEDIA_FILTER`; `local_paths(mime)` (local
files carried by a drag).

- `SubTabBar(QWidget)` — `changed`, `active`, `set_active`, `set_marked`.
- `DropBox(QWidget)` — `fileSelected`, `collapse`, `browse`; drag-over
  highlight.
- `BorderedFrame(QWidget)` — the primary rounded border alone.
- `SummaryPanel(QWidget)` — `set_values(rows)`.
- `Sidebar(QWidget)` — `navigate` signal, `buttons` dict, `WIDTH`.
- `TabIndicator(QWidget)` — `align_to(button, frame_left, animate)`.

### `ui/widgets/carousel.py`

Module helpers: `_force_white_fills(node)` (flattens Bodymovin fills to
white), `_wave()` (the cached rlottie animation, frame count and fps),
`_asset_image(name)`, `_info_badge_image()` (per resolved appearance mode,
with a drawn fallback).

- `WaveLayer(QWidget)` — the Wave Loop visualiser, a mouse-transparent child
  of the tab; `start`, `stop`, time-based `_index`, `_render` (rlottie →
  ARGB32 `QImage`, band crop, gradient via `SourceIn`, cached per frame and
  size).
- `_InfoTooltip(QLabel)` — the info badge's tooltip window.
- `ThumbnailCarousel(QWidget)` — signals `reselect`, `populated`,
  `indexChanged`, `fileDropped`; public `set_frames`, `set_strip_state`,
  `set_audio_only`, `set_media_info`, `current_index`, `step`, `sync_index`;
  geometry (`_frame_rect`, `_pixmap`, `_disc_centers`, `_dot_geometry`,
  `_resolve_dot_start`, `_centered_dot_start`); painting (`_paint_dots`,
  `_paint_chevrons`, `paint_badges`); animation (`_fade_to`, `_step`,
  slide/fade state); input (`_press` for press and double-click, drop
  handling, `_over_info_badge`, tooltip text via `_info_text` /
  `_mastering_text`).

### `ui/widgets/dialogs.py`

- `MessageDialog(QDialog)` — title, wrapped message, optional entry,
  buttons (first = primary); Enter confirms, Escape/close decline;
  `show_modal()` returns the pressed label or None. `_build_extra` is the
  subclass hook.
- `show_message`, `ask_yes_no`, `ask_text`, `confirm_output_path`.
- `AudioStreamPickerDialog(MessageDialog)` / `choose_audio_streams` — one
  checkbox per probed stream; never returns an empty set.

### `ui/widgets/toast.py`

- `Toast(QWidget)` — slide in, hold, fade; `start`, `reposition`, `retire`,
  `dismiss`; click runs its callback.
- `ToastManager` — `show(message, on_click)` (retires the oldest past three),
  `relayout`, `forget`, `clear`; slots hang off the tab frame's top-right.
