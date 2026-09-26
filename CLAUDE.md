# LlamaMXD

A Windows desktop GUI for video muxing/encoding/downloading, built with
PySide6 (Qt 6). Wraps ffmpeg and yt-dlp behind a tabbed interface. Repo:
`https://github.com/YezanSmadi/LlamaMXD`. **GPL-3.0-or-later** (the `LICENSE.txt` file is the FSF's GPLv3
text; every `.py` file starts with `# SPDX-License-Identifier: GPL-3.0-or-later` and `# Copyright (C)
2026 Yezan Smadi` — **put the same two lines on any new source file**, as the "or later" is stated there).
It was the Unlicense up to v0.5.0-beta.3 (beta.4 is the first GPL release); those releases stay public domain. Currently
v0.5.0-beta.4 (the sidebar footer — `VERSION` in `ui/widgets/panels.py`).

## Running

```bash
python main.py
```

Launch-directory independent: every asset (`assets/`), `settings.json` and
`presets.json` are resolved `__file__`-anchored.

Environment: Python 3.13, system interpreter (no venv). Dependencies are pinned
in `requirements.txt` (`pip install -r requirements.txt`) but still installed
globally in practice: `PySide6` 6.11.2 (the UI), `opencv-python` (cv2) 5.0
(preview frame decode), `numpy` 2.4 (pulled in by opencv-python, but also imported
directly by `ui/widgets/panels.py` to crop the sidebar cable art), `Pillow` 11.3, `rlottie-python` 1.3.8 (the Wave Loop
visualiser and the import spinner — a missing/broken import degrades to a flat gradient
wash / a plain drawn ring, never a crash), `ffmpeg-python` 0.2.0 (+ its `future` dependency — builds the ffmpeg
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
nothing needs to be on PATH; PATH is only the last fallback. **The folder was emptied by mistake on
2026-09-21 and reinstalled the same day** from the publishers' own releases, each download checked
against the SHA-256 the publisher lists: **ffmpeg 9.0.2 full build** (`GyanD/codexffmpeg`, the
gyan.dev author's GitHub mirror — `ffmpeg-9.0.2-full_build.zip`, `bin\ffmpeg.exe` / `ffprobe.exe` /
`ffplay.exe`; it has libplacebo + Vulkan, NVENC, libx265 and SVT-AV1 with a 0-13 preset range),
**yt-dlp 2026.08.19** (`yt-dlp.exe` from `yt-dlp/yt-dlp`) and **deno 2.9.7**
(`deno-x86_64-pc-windows-msvc.zip` from `denoland/deno`; the bundled one had been 2.9.6). Verified
after: all four resolve from `dependables\` (not PATH), `libplacebo_problem()` is None, and a real
Downloader run (`fetch_info` on a public video, then a `YtDlpJob` with a merge) finished through
Preparing, Downloading video, Downloading audio, Merging and Finishing into a valid AV1 + AAC file.
The notes below that say "9.0.1" / "gyan 2025" describe the builds those measurements were taken on.

## Licenses

**The project is GPL-3.0-or-later** (`LICENSE.txt`, plus the SPDX + copyright header on every `.py` file).
The rule for everything else: *if someone else's file ends up on the user's PC, their license text goes
with it.* **`licenses/`** (tracked in git, unlike `dependables/`) is **16 files**: `README.txt` (an index:
version, license and source URL of every component), one file per library or font (`deno.txt`, `python.txt`,
`qt-pyside6.txt`, `opencv-python.txt`, `numpy.txt`, `pillow.txt`, `rlottie.txt`, `ffmpeg-python.txt`,
`future.txt`, `fonts.txt`, `artwork.txt` — the CC BY 4.0 and Lottie Simple License texts), and a folder each for the two GPL programs, which need a source pointer —
`ffmpeg/` (`SOURCE.txt` + the publisher's `gyan-build-README.txt`) and `yt-dlp/` (`SOURCE.txt` + the
publisher's `THIRD_PARTY_LICENSES.txt`). Each single file starts with a header (component, version,
license, source URL) and holds that component's license texts **verbatim**, each under a divider naming
it — that is what makes merging them sound: never edit a text, only add a header. **There is one copy of
the GPL text for the whole distribution: the root `LICENSE.txt`**, which the `SOURCE.txt` files point to (so no
per-program copies, and no Unlicense copy for yt-dlp, which has no conditions). **The installer must ship
`LICENSE.txt` and `licenses/` beside the app** (Settings > About's View License and Third-party Licenses
buttons open them). Texts came from each project's own repo or the installed package (an earlier
55-file layout was merged into these 15 with a script that checked every text still appears verbatim and
every source URL survived). The ffmpeg build's own readme says "License: GPL v3" and names its source commit;
yt-dlp's exe is GPLv3+ and its file lists what it bundles. The root `LICENSE.txt` is gnu.org's copy, which differs
from the older FSF copy some packages ship only in four `http://` -> `https://` URLs. numpy's 16 per-component
licenses are real notices (not repeated in its top-level file), so they stay inside `numpy.txt`.
**When a bundled version changes** (an ffmpeg / yt-dlp / deno update, a `requirements.txt` bump), update that
component's header version and URLs (they name exact tags) and replace the text if the license changed.
**The GPL duty for ffmpeg and yt-dlp is source availability**: `SOURCE.txt` links the exact source, and
attaching the FFmpeg source archive to each GitHub release is the robust way (a third party's link can die).
**`licenses/README.txt`'s Artwork section records every asset's origin now**: the SVG Repo icons —
`audio-mute.svg` (Public Domain), `close-window.svg`/`maximize-window.svg` (CC Attribution, Konstantin
Filatov), `select-multiple.svg` (CC Attribution, krystonschwarze), `expand.svg` (CC Attribution,
zwicon), `minimize-window.svg` (Apache 2.0, Richard9394), `undo.svg` (MIT, halfmage), `info.svg` (SIL Open Font License 1.1, kudakurage) —
plus `redo.svg`/`deselect-multiple.svg`/`shrink.svg` as Yezan Smadi's own edits of
`undo.svg`/`select-multiple.svg`/`expand.svg` (not separate SVG Repo downloads, so each inherits the
license *and* credited author of the one it was made from: MIT, halfmage; CC Attribution, krystonschwarze; CC
Attribution, zwicon); `Wave Loop.json` under the Lottie Simple License (FL 9.13.21), Copyright (c) 2021
Design Barn Inc.; and `LlamaMXD-Logo.svg`/`RCA Cable Yellow.svg`/`LlamaDiscLoading/*.png` as Yezan
Smadi's own original artwork, **deliberately not GPL'd** (GPL-3.0-or-later covers the program's source
code, not its visual identity) but not identically licensed: the logo and the loading animation, each
picturing Pak the Llama and (the animation) the coined "PAK-RW"/"LlamaDisc" wordmark, are LlamaMXD's
actual branding — Copyright (c) 2026 Yezan Smadi, all rights reserved (may not be copied, modified,
redistributed, or used to represent a modified/unofficial build of LlamaMXD, without permission) — the
same reason Mozilla/Blender/GNOME/VLC keep their own logos out of their code's open-source license —
while the cable graphic and the Queue's search icon (`search.svg`), purely decorative, are Copyright (c)
2026 Yezan Smadi under CC Attribution 4.0 (CC BY 4.0), reusable with credit. **"LlamaMXD" and "Pak the
Llama"** (`core.about.MASCOT_NAME` — the llama pictured in `LlamaMXD-Logo.svg`) **are unregistered
trademarks of Yezan Smadi** (`core.about.TRADEMARK_NOTICE`), claimed by use rather than registered with
a trademark office — hence "LlamaMXD™"/"Pak the Llama™", not the registered-mark "®" — stated in both
`licenses/README.txt` and Settings' About page, as an uncaptioned `role="hint"` line (muted, smaller
than the rest of the page) trailing under the License section's own notice box and buttons — fine print
under everything else, not a fourth row alongside GitHub/Issue Tracker/License. A build with
`--enable-nonfree` must never be bundled.

## Tests

```bash
python tests/run_all.py
```

**Run it before and after any change that isn't comment-only** (~30s; `--update` re-records the
goldens after an *intended* change; `python tests/run_all.py ui jobs` runs a subset). Each check runs
in its own process against a sandbox: the log goes to `%TEMP%\llamamxd-tests`, the UI check uses its
own settings.json / presets.json, and fixture clips are generated there by the bundled ffmpeg.
- `check_commands` — golden ffmpeg argv for 26 Encode + 6 Mux settings, and the yt-dlp plan + argv for
  all 259 Downloader dropdown combinations on a stand-in YouTube format list. `-fps_mode`,
  libplacebo, the GPU (NVIDIA / NVENC) and tool paths are pinned, so the goldens hold on any machine.
- `check_core` — goldens of `formats` (the whole cascade), `naming`, `keybinds`, and `probe_media` /
  `probe_duration` / preview frames on the fixtures (SDR, multi-audio, HDR10, audio-only, VP9, cover
  art, a late-start MKV, and `keys.mp4` / `sparse.mp4` for the keyframe path and its exact redos):
  each frame's seek, that repeating it gives the same picture, and the tone-mapped set at those seeks.

- `check_leaks` — each user action repeated after a warm-up (importing video and audio, dialogs,
  toasts, queue rows and their details, theme / tab switches, expanding the preview, a dropdown's
  popup, a Downloader fetch): live QObjects, widgets, top-level windows, threads, theme-signal
  connections and scale bindings must not grow. Deferred deletes are flushed and dead bindings swept
  first (the harness pumps events outside a real event loop, where deleteLater never runs). Memory
  isn't compared; measured by hand it plateaus (imports: +39MB at 20 rounds, +40MB at 60 — the
  spinner's frames filling in; resizes +5.5MB either way).

UI checks end through `harness.finish()` (`TerminateProcess` once their results are printed): Qt's
native teardown crashes at exit now and then (3 of 10 runs on one check, before and after any
change here), and even `os._exit` runs the DLLs' unload code where it happens.
- `check_ui` — the real `MainWindow` offscreen: every visible widget's rect on 13 pages (plus the
  no-file state) at 1.0 / 1.5 / 2.0x, the squeeze scan, and the Muxing / Encoding preview invariant.
- `check_media` — the selected-file pipeline (`MediaSession`): load, a cache-hit reselect (no
  second probe), the HDR pre-render landing and being dropped / cancelled on a file change, the
  Wave Loop for audio, an unreadable file rejected, "No Preview", and the shared scrub index.
- `check_runners` — the runners' lifecycle offline: a real `YtDlpJob` (its job object included)
  runs `tests/fake_ytdlp.py`, a stand-in speaking yt-dlp's marker lines — a merge, pause / resume,
  priority, Stop killing the tree (a child process too) and removing the work folder, a failure,
  no file, a missing exe, an unmakeable folder — plus `FfmpegJob`'s early failures and its
  controls once ended.
- `check_jobs` — real Mux / Encode jobs through `FfmpegJob`, their outputs probed (streams, languages,
  length, each stream's start time); stop() mid-run; a failing job's reason.

Each check was shown to fail on a deliberate one-line break. There are no KNOWN exceptions: the About
license box's 1px squeeze at 1.5x is fixed (the notice's width is now the box's rounded width less its
rounded margins; scaling `644 - 14` on its own came out a pixel too wide at 39 of 241 scales from 0.6x
to 3.0x). `check_runners` also reads back each job's CPU class, I/O and memory priority. The jobs
check's `stream_starts` guards the trim + Passthru fix below.

## Architecture

```
main.py                   logging first, then QApplication (Fusion style), bundled fonts, theme, MainWindow
core/formats.py           container/codec compatibility + the option cascade (pure data)
core/gpu.py               GPU vendor detection + hardware-encoder selection (NVENC/QSV/AMF)
core/system_info.py       CPU/RAM/disk facts for the Settings tab's system-info block
core/presets.py           named codec/quality recipes, persisted to presets.json
core/naming.py            output file-name template + its tokens ({source} {title} ...)
core/power.py             Settings' "When Done" actions (shutdown / sleep / ... via Windows)
core/priority.py          Settings' "Priority Level" -> Windows process priority classes
core/window_mode.py       Settings' "Window Mode" names: Windowed / Borderless / Fixed
core/window_style.py      Win32 window styles Qt leaves stale on a live window: maximize box, dark title bar
core/startup_tab.py       Settings' "Startup Tab" names: the four main tabs + the Encoding default
core/keybinds.py          the remappable shortcuts: action table, default keys, contexts, conflict rule (no Qt)
core/theme.py             brand palettes, contrast helpers, settings.json read/write
core/about.py             Settings' About page: repo / issue-tracker URLs, the GPL short notice, paths to LICENSE.txt and licenses/
core/llamalog.py          LlamaLog: the rotating log file, crash hooks, URL scrubbing, per-job output ring buffer
core/probe.py             ffprobe: probe_media, a file's real length, the HDR colour-tag check
core/capabilities.py      what the bundled ffmpeg can do: -fps_mode, libplacebo/Vulkan, AV1 presets
core/previews.py          preview frames (OpenCV, else ffmpeg) and the HDR tone-mapped set
core/ffmpeg_vars.py       one queued job's settings -> a frozen JobVars of ffmpeg-ready values
core/ffmpeg_build.py      builds a Mux or Encode job's ffmpeg-python Stream / full argv
core/process_job.py       ProcessJob, the base of both runners: launch, pause/resume, priority, stop,
                          events, the job log; set_suspended, replace_output
core/ffmpeg_runner.py     runs one ffmpeg job off the GUI thread (progress, suspend/resume, stop)
core/tools.py             resolves ffmpeg/ffprobe/yt-dlp/deno to absolute paths (bundled, then PATH)
core/downloader.py        Downloader logic: fetch (-J), format model + option lists, resolve, argv
core/ytdlp_runner.py      runs one download off the GUI thread (job object, stages, time progress)
ui/app.py                 MainWindow — the hub: shared state, background work, tab routing,
                          keybinds, toasts, close prompt
ui/media_session.py       MediaSession (`app.media`): the selected file, its probe, preview frames,
                          HDR render and scrub index, broadcast to the media tabs
ui/theme.py               ThemeManager (live theme + System/Light/Dark) + the generated stylesheet
ui/scale.py               the one UI scale factor: px()/fpx(), bound setters, design-space painting
ui/workers.py             run_async: daemon thread → result delivered on the GUI thread; pil_to_qimage
ui/qt_log.py              routes Qt's own warnings/errors into the log
ui/single_instance.py     InstanceLock: a per-user lock file so only one LlamaMXD runs (main.py checks it first)
ui/keymap.py              KeyMap: the live shortcuts + matching a QKeyEvent against them
ui/keynav.py              KeyNav: Tab / Enter selection of a tab's controls (the ring) + an open dropdown's keys
ui/tips.py                shared hover-tooltip copy (codec / container / audio-format explanations)
ui/widgets/controls.py    button / labeled / field_label / set_enabled / restyle / anim / draw_cross helpers, IconButton
                          (✕ / ▲ / ▼ / select-all / deselect-all / undo / redo)
ui/widgets/text.py        ScaledLabel / ScaledButton / ScaledLineEdit / ClickableLabel (text painted through the scaled
                          painter — see "UI scale"), ui_font, set_font_px
ui/widgets/dropdown.py    Dropdown, NO_OPTION
ui/widgets/toggles.py     CheckBox, Switch, SegmentedButton
ui/widgets/timespinner.py TimeSpinner (+ its _TimeField)
ui/widgets/marquee.py     MarqueeLabel, MarqueeGroup
ui/widgets/panels.py      SubTabBar, DropBox, LoadingSpinner, BorderedFrame, SummaryPanel, Sidebar, TabIndicator
ui/widgets/tracklist.py   TrackListBox — Muxing's checkable, scrollable track picker
ui/widgets/carousel.py    ThumbnailCarousel
ui/widgets/wave.py        WaveLayer: the Wave Loop (rlottie) and its artwork fixes
ui/widgets/info_badge.py  the preview's info badge painters + _InfoTooltip
ui/widgets/preview_overlay.py  _ExpandedPreviewOverlay: the expanded preview
ui/widgets/dialogs.py     MessageDialog, show_message / ask_yes_no / ask_text,
                          confirm_output_path, AudioStreamPickerDialog, ExternalStreamPickerDialog
ui/widgets/toast.py       Toast / ToastManager
ui/widgets/frameless.py   ResizeGrips (the borderless window's eight native-resize handles) +
                          WindowControls (its close / maximise / minimise icons)
ui/widgets/tooltip.py     tip(widget, text) — the shared themed hover tooltip
ui/widgets/svg.py         svg_renderer(name, color, mode): SVG assets recoloured by text, cached
ui/widgets/queue_controls.py  Queue's SortButton (cycling), SearchToggle + SearchBar (unrolling), SlideHost (details panel)
ui/widgets/keyfield.py    KeyField — Settings' click-then-press-a-key box
ui/tabs/media_tab.py      MediaTab — the frame Muxing and Encoding share
ui/tabs/muxing.py, encoding.py, downloader.py, queue.py, settings.py
```

`core/` has no UI code at all — nothing in it imports Qt.

### Logging (`core/llamalog.py`, `ui/qt_log.py`)

**Where and how.** `%LOCALAPPDATA%\LlamaMXD\logs\llamamxd.log` — writable wherever the app is
installed and untouched by an update; it falls back to `%TEMP%\LlamaMXD-logs`, and with no writable
folder at all `setup()` returns None and every call is a no-op (logging must never raise into the app).
A `RotatingFileHandler`, ~1MB x 5 backups. `main.py` calls `llamalog.setup(version=VERSION)` **before
anything else** (so a failure while building the window is on record), then reads `settings.json` and
applies the saved detail (`set_detail`), then `describe_environment_async()`. A line is
`2026-09-21 13:49:02.123 INFO     app        | [thread] message` — the thread's name only when it isn't
the main one; areas are `llamamxd.<area>` loggers (`app`, `queue`, `ffmpeg`, `ytdlp`, `probe`, `gpu`,
`settings`, `downloader`, `workers`, `ui`, `qt`). The session opens with a header: version, Python, OS,
the packages (PySide6 / OpenCV / numpy / Pillow / rlottie / ffmpeg-python, each with its version or
MISSING), then — from a thread, since the version checks launch processes — CPU, RAM, GPU, and each
bundled tool's path and version (a missing tool is a WARNING). Two instances running at once share the
file and can trip rotation on Windows; `logging.raiseExceptions` is off, so that is silent.

**Levels.** Settings' **Normal** is INFO and up, **Detailed** adds DEBUG (`app.log_detail`, saved as
`log_detail`). Detailed also changes what jobs record: ffmpeg runs `-loglevel level+info` instead of
`error` (`llamalog.ffmpeg_loglevel()`, passed to `compile_command(loglevel=)`), and yt-dlp runs with
`-v` (`build_download_args(verbose=)`). **The failure message must not come from that noise**: with
`level+info` every stderr line is tagged (`[error] ...`, or `[ctx @ 0x..] [error] ...`), and the last
three lines of a failed run are `[info]` ones ("Conversion failed!" is `[info]`), so
`FfmpegJob._reason` prefers the level-tagged `[error]` / `[fatal]` lines (`_errors`, tag stripped) and only
falls back to the stderr tail — which is exactly the Normal-mode behaviour, unchanged. Checked with a
real failing encode in Detailed mode.

**What it catches.** `setup()` installs `sys.excepthook`, `threading.excepthook` and
`sys.unraisablehook` (each logs at CRITICAL/ERROR with the traceback, and the default hook still runs
when there is a stderr — there is none under `pythonw`), `ui/qt_log.install()` routes Qt's message
handler into the `qt` area (warnings and up at their level, Qt's debug/info at DEBUG), and
`ui/workers.run_async` logs a failed background task with its full traceback (it printed only
`repr(exc)` before). **`faulthandler` writes native crashes to `crash.log`** (an access violation in a
driver, OpenCV or libplacebo bypasses every Python hook — this app has met several); at the next
start a `crash.log` holding more than its session header is logged as a WARNING with the first 40 lines,
set aside as `crash-<time>.log` (5 kept) and a fresh one started, so a crash is reported exactly once.
Verified by really segfaulting a subprocess with `ctypes.string_at(0)`.

**Privacy.** File paths are logged in full. **URLs are logged without their query string, fragment
and `user:pass@`**, enforced where a line is written rather than at each call site: the formatter
scrubs every line (`scrub`), `JobOutput` scrubs every stored line, and job files scrub their header.
yt-dlp echoes a link's tail *without* its scheme (`[generic] watch?v=abc&token=...: Unable to
download webpage`), which no URL pattern catches — so `scrub` remembers the query text of every link it
has seen (`_hidden`, 64, at least 6 characters) and removes it wherever else it appears (found by a real
yt-dlp failure against an unresolvable link; the token was in both the log and the job file before
this). Consequence worth knowing: a YouTube link loses its `?v=` video id, so it reads as
`https://www.youtube.com/watch`.

**Job output — the ring buffer.** Each `FfmpegJob` / `YtDlpJob` owns a `llamalog.JobOutput`: a
bounded in-memory deque (2000 lines, oldest dropped and counted) fed from the reader thread — ffmpeg's
stderr, and yt-dlp's merged output minus its per-update `LLAMA_DL` progress lines (ffmpeg's `-progress`
stdout is not fed either). When the job ends the runner calls `_record`, once (`_recorded`), which
calls `llamalog.record_job`: the main log gets one summary line (`ffmpeg job "x.mp4" failed after 1m 15s
(exit code 1) | reason | output: <path>` — ERROR for a failure, INFO otherwise) and the output goes to
`logs\jobs\<time>-<area>-<name>-<outcome>.log`, whose header carries the outcome, duration, exit code,
reason and the full command line. **A failed or stopped job's whole buffer is written** (and always gets
a file, even with no output); **a successful job's last 100 lines are** (`JOB_SUCCESS_LINES`), and a
successful job that said nothing writes no file — ffmpeg at `-loglevel error` says nothing when it
succeeds, which is why Detailed raises it. The file says how many earlier lines were not kept. Files are
pruned: the newest 50 failed and 50 stopped, the newest 20 successful (so a run of good jobs cannot push
out the failures you go looking for). Every path out of a job records it: finishing, failing (nonzero
exit, the output couldn't be saved, the HDR colour-tag check), `stop()`, and failing before the process
started (`_fail_early`). `job.log_path` is the file once the job has ended. A job's start is logged with
its full command line (this replaces the two `print`s the queue had).

**Events.** File selected, the probe summary (`_probe_summary`: container, video codec and size,
HDR, audio, duration, size), preview decode time, an audio-only file, a rejected file (WARNING), HDR
render start / finish / cancel (a cancelled render's late empty result is dropped without a WARNING and
without replacing the cached frames — `_hdr_cancelled_token`), the capability probes (libplacebo/Vulkan,
`-fps_mode`), the Deno check, link fetches, queue add / remove / start / pause / stop / finish and each
task's end, When Done, settings changes (priority, window mode, GPU, reset), and closing. **Swallowed
exceptions**: the ones whose failure means something got a line — `probe_media` failing (WARNING; it then
returns what it can), the post-encode colour-tag check and the capability checks not running, every HDR
preview frame that fails (WARNING, with ffmpeg's exit code and last stderr line; the set was silently
shorter before), GPU adapter / encoder queries, a failed power action, `presets.json` unreadable or unsaveable
(a *missing* one is normal and silent), a thumbnail fetch, a partial output that can't be deleted (not one that was
never created), a process still alive 10s after being killed, a pause / resume that didn't take,
the default save folder, and the Wave Loop / loading animations being unavailable (once, with the
traceback). The routine parse fallbacks (`_parse_frame_rate`, the per-field `ValueError`s) stay silent by
design, and the per-file duration / metadata probes log at DEBUG.

**Verified** with harnesses run against a sandboxed `LOCALAPPDATA` (never the real one): line format, both
detail levels, idempotent setup, URL scrubbing through messages, tracebacks and job files, hooks for a
thread / the main thread / `__del__`, thread names, the ring buffer (2500 lines -> 2000 + "500 earlier lines
not kept"; a successful job's last 100 of 300; none for a quiet success; a stopped job with no output),
pruning (60 failed -> 50, 30 done -> 20), rotation at 1MB, a native crash and the next-start report, no
writable folder, the temp fallback, real ffmpeg jobs (good, failing, stopped, level+info, both outcomes)
and a real yt-dlp failure in both detail levels, a real `MainWindow` (settings / Deno / libplacebo /
environment lines, an exception inside a Qt slot, a Qt warning, a failing `run_async` task, importing a
video / HDR / audio / unreadable file, the cancelled render, queue actions, the Settings section, Reset
to Default, a corrupt `settings.json`, closing), and each instrumented failure path. That last harness found
a `NameError` in a first version of the HDR-frame logging (it read a result the code never assigned) —
which would have broken every HDR preview frame; the earlier full-app run predated that edit, so
**rerun the whole set after any edit, not only the harness for the part you touched.**

**Windows-only pieces, for the later Linux / macOS port** (the app targets Windows for now; nothing
here has been run elsewhere): the log folder comes from `%LOCALAPPDATA%` (falling back to
`~/AppData/Local`, which would be the wrong place on a Mac or Linux box — they want `~/Library/Logs/LlamaMXD`
and `$XDG_STATE_HOME` / `~/.local/state/llamamxd`); `open_log_folder` uses `os.startfile` (it fails safely into
an error dialog; the equivalents are `open` and `xdg-open`); and the environment header's GPU line comes from
`core.gpu` (WMI / PowerShell). Everything else in `core/llamalog.py` is plain Python (`logging`, `faulthandler`,
the hooks, the ring buffer, scrubbing).

### External tools (`core/tools.py`)

`find_tool(name)` returns an absolute path or None; `tool_path(name)` the path
or the bare name (so a launch still raises the usual FileNotFoundError every
caller already turns into a readable message); `tool_dir(name)` the folder
(what yt-dlp's `--ffmpeg-location` wants). Search order: beside the frozen
app's exe or in a `dependables/` folder next to it (both installer layouts
work), then the repo's `dependables/`, then PATH. Cached per process.

**Every** ffmpeg/ffprobe call goes through it — `ffmpeg_build.compile_command`'s
argv[0], and `run_tool(name, *args)` / `ffprobe_json(*args)` (also here: no console window,
text output), which every query in `core/probe.py` and `core/capabilities.py` uses; the preview
frames in `core/previews.py` launch through `tool_path` with their own flags (binary output,
below-normal priority). Verified by running a real Mux and Encode job with every
ffmpeg folder removed from PATH: both launched `dependables\ffmpeg.exe`.

**Absolute paths are load-bearing for yt-dlp**, not tidiness: a relative
`--js-runtimes deno:dependables/deno.exe` made yt-dlp report "no JS runtime
found" (the same path made absolute worked — confirmed), and a bare `ffmpeg`
is left to Windows' search order, which only hits the app's folder when
frozen.

### The window is the hub (`ui/app.py`)

`MainWindow` owns the shared state every tab reads through `self.app`:

- `media` — the `MediaSession` (`ui/media_session.py`): the selected file and everything
  derived from it — `current_file_path`, `info` (the ffprobe result, below; `info_path` is
  the file it came from), `thumb_frames` / `thumb_frames_path` (its ten preview QImages),
  `hdr_frames` / `hdr_frames_path` (the tone-mapped set, if rendered), `tabs` (Muxing and
  Encoding, registered by `MediaTab.__init__` through `register_tab` as the targets of the
  broadcast). Only `MediaSession` writes any of it; tabs read `self.app.media.<name>`.
- `default_save_location`, `gpu_enabled` — from `settings.json`; the save
  folder is created at startup (best-effort).
- `downloader_separate_save`, `downloader_save_location` — also from
  `settings.json`; the Downloader's own optional save folder, off by
  default. `downloader_default_location()` is what `DownloaderTab` actually
  autofills into — see "Tabs → Settings" below.
- `ytdlp_cache` (`{"url", "info", "thumb"}`), `deno_missing`.
- `tabs` — name → tab (`Muxing`, `Encoding`, `Downloader`, `Queue`,
  `Settings`), all built once at startup and stacked in a `QStackedWidget`.
  `Queue` is constructed first since the others hand jobs to it.

**Window**: starts at 35% of the screen's width at the reference aspect
ratio (896:540 — `scale.window_size`), centred; a 2560x1440 screen gives
exactly the 896x540 reference window. Its size *is* the UI scale (see "UI
scale" below), so the layout keeps its proportions on any monitor and at any
window size. Sidebar (200 reference px) on the left; the tab frame
(`_TabFrame`, rounded, 10px margin) holds the stack.

**Window mode** (Settings → Appearance → Window Mode, `core/window_mode.py`,
persisted as `window_mode` + `borderless_fullscreen`, default `Fixed` / off),
applied live by `MainWindow._apply_window_mode` (also at launch, and
`present()` shows it — `showFullScreen` for fullscreen — instead of `show()`):

- **Fixed** — the reference-shaped window exactly as it always was: framed,
  `setFixedSize`, centred on its screen, not resizable (pixel-identical to the
  pre-mode app).
- **Windowed** — the normal frame, freely resizable and maximisable; **the
  default size is also the minimum** (the Fixed size — 896x540 on a 2560x1440
  screen, `scale.window_size` of the window's screen — set as the window's
  minimum in `_apply_window_mode`), so the scale never drops below the
  default's; no upper limit.
- **Borderless** — `FramelessWindowHint`, resizable like Windowed. With no
  title bar, a press on the sidebar or the margin around the tab frame (any
  press a child didn't take — *not* the tab frame itself) starts a native
  move (`windowHandle().startSystemMove`), and `ResizeGrips` (eight invisible
  real-pixel strips on the outline) start native resizes. Its **Fullscreen**
  checkbox (Settings shows it only while Borderless is selected; unchecked by
  default, and remembered while another mode is on) fills the screen with
  `showFullScreen`. **`WindowControls`** (`ui/widgets/frameless.py`) stand in for the
  OS buttons: Close, Maximise, Minimise — in that order — as the bare
  `assets/close-window.svg` / `maximize-window.svg` / `minimize-window.svg` icons, no
  shapes behind them, top-left of the sidebar in the 24px strip above the title. A
  child of the `Sidebar` placed by absolute geometry (`scale.bind`), *not* a layout
  item, so it cannot move the title — verified: every other sidebar widget keeps its
  exact rect with the controls shown or hidden. They draw in `primary_text` (black or
  white by contrast with the theme's primary); each lights up under the pointer by
  recolouring the icon itself (never a shape behind it) — Close in STOP_RED, Maximise
  and Minimise in the theme's `secondary` (on Noir that is a dark grey, so hover reads
  as the white icon dimming). Close is drawn at 20 reference px against the others'
  16: its X fills 60% of its 24-unit box where the maximise square fills 83%, so equal
  sizes made it look small (`ICON_SIZES`). **The straight-edged icons are snapped to
  whole device pixels** (`_icon_rect`, painted in real pixels, not design space): the
  maximise square is only 2 of 24 units thick (1.33px at the default size) and its
  position fell on a fractional pixel, so each line straddled two pixels at ~67%
  coverage — visibly lighter than at 1.1x and up, where a solid pixel row happens to
  fit. The size moves by under a pixel so the ink's width is whole, and its leading
  edges are rounded onto the grid (`devicePixelRatioF` aware). Measured as each
  side's darkest pixel row across 81 scales from 1.0 to 2.6: 4 scales were weak
  before (1.0, 1.1, 1.14, 1.16 — the default size worst), 0 after, and all four sides
  match. Judge icons like this by their real pixels: a 1px line magnified with smooth
  scaling *looks* grey. The three SVGs ship in three colours (black, near-black, navy), so
  `svg_renderer(..., "fills")` swaps every painted `fill` in the file text and renders it as a vector
  (smooth at any scale) — not a rendered-then-tinted bitmap. Shown in Borderless only
  (`MainWindow._sync_window_chrome`), fullscreen included. Close is `MainWindow.close`,
  so the unfinished-jobs prompt still applies; Maximise toggles `showMaximized` /
  `showNormal` (a frameless window fills the work area, and the resize grips switch off
  while it is maximised — `changeEvent` on `WindowStateChange`); Minimise is
  `showMinimized`. In borderless *fullscreen* Maximise is dimmed and inert, since
  fullscreen is a Settings choice rather than something to undo from a button.
  **The maximise guard must read the setting (`_wants_fullscreen()`), not
  `isFullScreen()`**: a maximised frameless window reports `Maximized|FullScreen`, so
  the live-state guard swallowed the click that restores it.

Switching flags (`setWindowFlag`) hides a visible window, so the mode change
re-`show()`s it. Four Windows/Qt quirks in that path were each found by
measuring the *native* window (`GetClientRect`, `GWL_STYLE`, `SC_MAXIMIZE`
through `SendMessage`) — Qt's own `width()`/`height()` agreed with itself and
were wrong:

- Adding or dropping the frame leaves the real client area a title bar and
  borders smaller than Qt believes (880x501 for 896x540), and Qt, seeing no
  size change, never corrects it — the page came out cropped at the bottom.
  `_apply_window_mode` frees the size limits and resizes to `size+1` then
  `size`, so Qt sends the real one.
- Qt doesn't keep `WS_MAXIMIZEBOX` in step with the size limits on a live
  window: Fixed -> Windowed left the button disabled, and Borderless -> Fixed
  left it enabled on a pinned window, where a click just moved the window to
  the top-left at the same size. `core/window_style.set_maximize_box` sets it
  explicitly (off for Fixed, on otherwise).
- Leaving maximised/fullscreen goes through `showNormal()` and then
  `QApplication.processEvents()` *before* the flag changes, with the size read
  from `normalGeometry()` beforehand — otherwise the window is re-shown
  maximised and swallows the resizes.
- **The dark title bar.** Qt sets DWM's dark-frame flag only when it creates a native
  window that *already has* a frame, so a window launched Borderless and then given a
  frame by Settings came up with the flag off — a white title bar over a dark app, for
  good (Windows reports dark, Qt reports dark, the app is dark; measured by grabbing
  the actual on-screen title-bar pixels, not by reading the flag). Launching framed was
  fine, which is why it hid. `core/window_style.set_dark_titlebar` sets
  `DWMWA_USE_IMMERSIVE_DARK_MODE` (attribute 20; 19 before Windows 10 2004) from
  `MainWindow._sync_titlebar`, after every mode change and on every theme change.
  **Setting the attribute is not enough**: neither `SWP_FRAMECHANGED` nor
  `RedrawWindow` repaints the caption on Windows 10 (still white, flag correctly 1);
  bouncing `WM_NCACTIVATE` (off, then on) does, and the window's real active state is
  put back so a background window doesn't suddenly look focused. Verified on real
  pixels: every mode-cycle combination, Light staying white, Light <-> Dark and a theme
  change while framed, and the same with the app in the background (no focus stolen).

**Tab switching** is `show_tab(name)`: calls the outgoing tab's `on_leave`
if it has one (Settings autosaves; Queue resets a completed 100% bar),
`setCurrentWidget`s the new one, tells the `TabIndicator` which button is now
active (`set_active`), and takes focus back to the window unless a line edit
has it. A switch plus a full repaint measures ~1ms. The first alignment runs
from `showEvent` via a zero-delay timer, once geometry is final.

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
`app.media.select_file(path)` (`ui/media_session.py`) — the *only* place the selected file changes.
It resets the shared scrub index and `info` when the path actually
changed — also calling `carousel.clear_preview()` on every media tab at that
point, so the *outgoing* file's frames are dropped immediately rather than
sitting on screen until the newly-picked file's own frames finish decoding
(`_load_thumbnails`, below, only rebroadcasts synchronously on a cache hit;
a genuine decode takes a worker round-trip, during which the preview would
otherwise still show the previous file) — then for each media tab:
`set_selected_file` (the marquee label; the preview area goes back to the DropBox, which now
shows only the **loading spinner** until frames arrive — see "DropBox" below — over a carousel
that is cleared and forgets it was populated, so a *replacement* file shows the spinner too
rather than a blank carousel) and `_autofill_output_path`, then `_load_thumbnails(path)`.

**`_autofill_output_path`: the FILENAME always re-derives from the file just
picked; only the DIRECTORY persists** — whatever folder is currently in the
save field (the default save location at first, or wherever the user last
Browsed). A stale filename from the previous input is never worth keeping. A
bare directory (fresh from Settings) is told apart from a full path by
whether it has an extension, since `os.path.dirname()` on a bare directory
would strip its last real folder.

**The filename itself comes from Settings' naming format** (`core/naming.py`,
default `{source}-{title}`, held on `app.naming_template`), not a fixed
`<input><suffix>`. Tokens split by when they can be known: **live** ones
(`{source}` = the input's name — for a download, the site; `{title}` = the
embedded title tag — the video title for a download; `{chapters}` = `12ch`,
the chapter count) fill into the Save field as soon as they're known, and the
field re-derives when the probe lands (`_broadcast_media_info` calls each
tab's `refresh_auto_output`) or the format changes (`app.set_naming_template`)
— but only while the field still holds what was autofilled (compared
extension-less, since a container snap rewrites the extension on its own), so
a Browsed or hand-typed path is never touched. **Queue-time** ones (`{date}`
`{time}` `{creation-time}` `{quality}` `{bitrate}`) can't be known yet, so the
field shows them as literal text and `_resolve_output_tokens` fills them into
the job's own `output_path` in `add_to_queue`/`run_now`, before
`_validate_settings` — the field keeps the tokens, so each queue stamps its own
time. `{quality}` is `crf22`/`q5` for Encoding (empty for Muxing and
rate-control-less codecs) and the Resolution pick for a download; `{bitrate}`
is the source's overall bitrate (a download's: chosen streams' size over its
length); `{creation-time}` the media's creation tag (else the file's), or a
download's upload date. A token with no value drops its neighbouring separator
(`{source}-{title}` on an untitled file is `clip`, not `clip-`). Autofill
falls back to `OUTPUT_SUFFIX` in the one case the name would equal the
input's own path. Autofill also can't read the Output Format dropdown while it
still shows the no-file `—` (it runs before the next `_sync_controls`), so it
takes the input's own extension then — writing the placeholder into the path
once made the next autofill mistake the name for a folder.

**Frames and probe, off the GUI thread, cached.** `_load_thumbnails`:
- **Cache hit** (same path already probed / decoded) → broadcast immediately.
- **Miss** → bumps `_thumb_token`; one worker runs `probe_media` first and
  delivers it early through `emit_progress` (the ~50ms probe settles the
  tabs' defaults long before the frame seeks finish), then
  `extract_preview_frames(path, count=10, info=...)` — ten frames at the video's
  *interior* (fractions 1/11 … 10/11 of the real length, skipping a black first /
  end-credits last frame), with the seek that reached each (see "Preview frames are
  keyframes" below). The probe result is passed in, so its length and `previewable`
  aren't asked for again. A result whose token is stale (the user picked another file
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
entirely — `current_file_path`, `info`, both thumbnail caches, and
every media tab's carousel/DropBox (`MediaTab.clear_selected_file`,
`DropBox.reset`) go back to their pristine pre-import state, any in-flight
HDR render for it is cancelled, and a "Couldn't Read This File" dialog
explains why — rather than a tab silently showing zeroed-out fields for a
file that was never actually usable.

**Preview frames are keyframes** (`core/previews.py`, `extract_preview_frames`). Landing on an
exact frame means decoding from the keyframe before it up to the target — hundreds of 4K frames per
preview — and OpenCV did that in-process with a decoder thread per core (each holding its own
frames). Now each preview is **the keyframe at or before its target**: one ffmpeg per frame with
`-noaccurate_seek`, **one decoder thread each** (a frame threaded across every core only slows and
bloats a single-frame decode), `preview_workers()` of them at once, as **rgb24** PPM over a pipe
(`format=rgb24` is load-bearing: a 10-bit source otherwise gives a 16-bit PPM, ~100x slower for
Pillow), shrunk in Python exactly as before (`_shrink`, `INTER_AREA`). ffmpeg's colour conversion
honours the stream's tags, where OpenCV's used BT.601 on at least one BT.709 file. Measured on the
user's files, probe + ten previews, time and the app's peak commit (old -> new): 4K AV1 15.8s 776MB
-> 1.0s 345MB; 4K HDR AV1 10.8s 804MB -> 1.4s 305MB; 1080p AV1 6.2s 333MB -> 0.5s 137MB; 4K HDR HEVC
4.5s 1174MB -> 1.5s 295MB; 4K H.264 1.6s 738MB -> 1.0s 350MB; 1080p H.264 0.42 -> 0.41s, 291 ->
132MB. Tried and rejected: several OpenCV readers in parallel (+500-900MB each, and no faster at 4 or
8 CPUs — the single reader already fills them), and capping OpenCV's decoder threads (saves memory
on HEVC / H.264 only, and costs time on any machine with more than 8 cores). The rules, in order:
- `previewable` False (audio, or a first video stream that is cover art) -> no frames, and no decode
  at all. That also retired OpenCV's hang on an audio file (below).
- **Keyframes** (`_extract_keyframes`) unless the sample gap (length / 11) is under
  `_MIN_KEYFRAME_GAP` (2s — keyframes are rarely closer, so a clip under ~22s would share them). A
  sample landing at or before the previous one's keyframe (ffmpeg's `showinfo` reports where it
  landed) is redone at its **exact** frame; past `_MAX_EXACT_REDOS` (2) of those it stops early and
  hands the file on.
- **OpenCV** at exact frame indices, as before — the short clips and sparse-keyframe files (a 13s
  Gladiator clip: 1.9s, unchanged).
- **Exact ffmpeg grabs** (`_extract_exact`) as the last resort: a file OpenCV can't seek, e.g. the
  late-start MKV below (its frame count comes from an end timestamp).

Each frame comes with its **seek** — `(seconds from the file's start, exact)` — which `MediaSession`
keeps (`_thumb_seeks`) and the HDR render repeats (see "HDR preview thumbnails"), so the two sets are
the same frames by construction: repeating a keyframe seek gives the identical picture (checked on
every file). Not the landed time: `showinfo` prints 6 significant digits, and an exact seek a hair
before a keyframe starts from the previous one and decodes the whole gap (the HDR render ran 11.5s
instead of 8s that way). The OpenCV route's seeks are its index / fps, as the HDR render always used.

**A file that reads fine but decodes to no preview frames is kept, not rejected.**
Only if every route above comes back empty does `_deliver_thumbnails` get an empty list for
something that isn't audio-only (`_is_audio_only` — an audio file legitimately has no frames and gets the Wave
Loop instead). The file **stays selected and fully usable** — the previews failing says nothing
about whether ffmpeg can mux/encode it — so nothing is undone: each media tab's
`show_no_preview()` puts the drop box back over the carousel, now reading **"No Preview
Available"** in STOP_RED (the `error` label role) where the drag/drop prompt was
(`DropBox.show_no_preview`: border and Browse stay, "— or —" goes; `collapse()` / `reset()`
restore the prompt's text and role), and a "No Preview" dialog says "No preview images could
be generated." plus "The file is still usable but the preview images could not be decoded
properly." once. A later file that does have frames reveals the carousel normally, because
`show_no_preview` (like `clear_selected_file`) calls `carousel.forget_populated()` —
`populated` fires once per carousel, and with the flag left set the drop box stayed up over a
file that had loaded.

**A file's real length can differ from its header** (`probe._effective_duration`, used by
both `probe_media`'s `duration` and `probe_duration`). Found with `GladiatorName.mkv`, a 35s
clip cut from a film with its original timestamps kept: it starts at 5465.5s and its header
Duration is 5501.162s — the END timestamp, not the length. ffmpeg itself is unaffected (it
rebases every output to 0 and writes the real length into the new header — verified on the
raw EBML Duration field: source 5501.162, mux export 35.659, all 852 video + 1110 audio frames
kept), but everything the app derives from the number was wrong: the info tooltip
(01:31:41), the `{bitrate}` token (121 kbps for 18.7 Mbps), the queue's progress denominator
(the bar stalled at 0.65% until the final snap; 99.65% now), and OpenCV's frame count
(131,896 frames for ~855, so every interior seek landed before the first frame — the cause of
the preview failure above). The rule: a start time at or under 1s trusts the header (nearly
every file, no extra work); otherwise `_tail_end_time` seeks to the last ~10s and reads to the
end (one ~40ms ffprobe call) for the file's last real timestamp, and the header is treated as
an end time — length = header − start — only if that timestamp sits at `header` and not at
`start + header` (an honest header on a late-starting file, e.g. broadcast TS). Anything
unclear keeps the header, so it is never worse than trusting it. **That probe's interval
needs an explicit end** (`T%end`): the open-ended `T%` returned an empty result with rc 0 on
8 of 30 runs of the identical command, where the closed form was 30/30. Checked against
six real files (five unchanged: 28.5 / 37.6 / 6824.8 / 166.3 / 210.1s) and 40 repeats.
`_probe_frame_geometry` (the HDR→SDR preview's frame count) applies the same correction only
when OpenCV's implied length is over 1.5x the real one, so a merely variable-frame-rate file
keeps cv2's count and its tone-mapped set stays index-for-index aligned with the raw one.

**The scrub position is shared.** A carousel's `indexChanged` →
`app.sync_preview_index(i)` → every carousel's `sync_index(i)` (an instant
jump that never re-emits, so it can't loop). The index resets only when the
input file actually changes.

**What the probe gives the tabs** (`core.probe.probe_media`, best-effort
ffprobe; every field may be None and every failure returns Nones rather than
raising — it only ever *improves* defaults): container, video/audio codec,
video profile/level, width/height, fps, HDR, duration, file size, the
container's `title` / chapter count / overall `bit_rate` / `creation_time`
(the output-name tokens below), per-stream
video and audio (`video_streams`/`audio_streams`), HDR static metadata, and
`has_video`/`has_audio`. It lets Encoding auto-resolve Encoder, Profile,
Level and every per-stream audio control, caps the Resolution and FPS
ladders to the source's own height/rate, lets Muxing populate its track
boxes (`ui/tabs/muxing.py`), lets both tabs default the output container to
the source's, and lets Muxing work out which containers the file can be
remuxed into. `fps` (`core.probe._parse_frame_rate`) converts ffprobe's
rational `r_frame_rate` string (`"24000/1001"`) into a plain float (23.976),
since neither `formats.fps_values_for` nor the UI wants to parse a fraction
string itself.

Video Level needed a **codec-aware** conversion, not one formula: ffprobe's
raw `level` is ten times the display value for H.264 (`40` → "4.0"), *thirty*
times for HEVC (confirmed empirically — raw `120` is "4.0", not "12.0"), a
`seq_level_idx` table lookup for AV1 (confirmed: a 720p30 clip's raw `5` is
"3.1"), and a named-level code for MPEG-2 (mirrors
`ffmpeg_vars._LEVEL_ARGS["MPEG-2"]` in reverse) — see
`core.probe._ffprobe_level`. Audio Channels/Sample Rate match a probed
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

**Audio-only inputs.** `extract_preview_frames` returns `[]` for an audio
file, without decoding anything. `_is_audio_only(path)` (the probe says audio-but-no-video, or with no
probe the extension is in `formats.AUDIO_EXTENSIONS`) triggers
`set_audio_only(True)` on every carousel — from the probe delivery, the
cached-probe branch of `_load_thumbnails` (a re-selected audio file has no fresh probe
to deliver it) and the empty frame delivery — which reveals the carousel and shows the Wave
Loop visualiser with navigation disabled. Real frames arriving clear it again.
The Wave Loop still comes from the probe, not from the frame delivery. **Never hand an audio file to
OpenCV: its `cap.read()` never returns there** (m4a, mp3 and flac all hung, 5/5 runs), which stranded
a worker thread per audio import until previews checked `previewable` first.

**HDR→SDR preview renders** (`start_hdr_render`, `_deliver_hdr`): one
tone-mapped render per file (`extract_hdr_tonemapped_thumbnails`), cached on
`app.media` and token-guarded; a no-op when already cached or already running for
that path. Delivered to any tab with `on_hdr_frames_ready` (which only re-applies the
frames when the HDR→SDR switch is on — the render now lands while the raw previews are
being scrubbed, and re-applying them would reset the carousel).

**The render starts on import, not on the switch.** `_prerender_hdr(path)` runs right after
the raw previews are broadcast (`_deliver_thumbnails`, and the cached-frames branch of
`_load_thumbnails`) and starts `start_hdr_render` when the probe says `hdr` is `True` — so
only an HDR file pays for it, the raw previews are never delayed, and the switch is
instant once the set is ready (0.4ms measured). A switch pressed earlier just waits for the
rest of the render already in flight. It runs **alongside a running queue job** by design
(the user can multitask); it is not held while one is active. Measured on a real 4K HDR10
file (Beauty and the Beast HDR, 210s): raw previews 4.5s, then the tone-mapped set 8-10s
after them (it was 14.6s, sequential, before). **A render in
flight is interrupted the instant the file changes**, not left to finish for
a file nobody's looking at any more: `select_file` calls
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

**Every shortcut is remappable and can be switched off** (Settings -> Shortcuts, below).
`core/keybinds.py` is the table — `ACTIONS` (id, name, default key, contexts, tooltip) — and
`MainWindow.keymap` (`ui/keymap.py`, a `KeyMap`) holds what the user has made of it, persisted as
`keybinds: {id: {"key": "Left", "enabled": true}}`. Keys are Qt's portable strings; `event_spec`
turns a key press into one (keypad Enter is `Return`, Qt's `Backtab` is `Shift+Tab`, a bare
modifier is ""), which is what both the capture box and the matcher use, so they always agree.

An application-level event filter (`_Keybinds` in `ui/app.py`) decides *when* each may fire — so
they work wherever focus is, unless a modal is open, the window isn't active, or focus is on
something the key already means something for. The defaults:

| Action | Key | When |
|---|---|---|
| Scroll Preview Left / Right | Left / Right | steps the current tab's carousel (`carousel.step`, no chevron glow); repeats while held |
| Expand Preview | F | `carousel.toggle_expand()` — expands (only where the corner icon is offered: frames, not the Wave Loop) or shrinks |
| Exit Expanded Preview | Esc | collapses whichever media tab's preview is expanded |
| Start / Pause Queue | Space | Queue tab only; not when a button / dropdown has focus |
| Previous / Next Tab | Up / Down | `MainWindow.cycle_tab`: Muxing, Encoding, Downloader, Queue, Settings, wrapping; **not while a preview is expanded** |
| Select Next Option | Tab (Shift+Tab back) | `KeyNav.step`, see below; not while a preview is expanded |
| Press Selected Option | Enter | `KeyNav.activate` |
| Dropdown: Previous / Next Option | Up / Down | only while a dropdown list is open |
| Fullscreen Window | F11 | `MainWindow.toggle_fullscreen` |

Only F11 and Tab work from inside a text field (F11 means nothing there, and Tab is how you leave
it); everything else stands aside while a line edit, the TimeSpinner field or a `KeyField` (marked
`captures_keys`) has focus. Tab is **always consumed** when it is the Select Next Option key —
Qt's own Tab hops into the next text field, which then swallowed every following shortcut (found
by a harness: Tab with the preview expanded left focus in the save-path entry and Esc / Right went
dead). Auto-repeat is swallowed for everything but the two preview keys.

**Contexts and conflicts.** Each action lists where it can fire (`window`, `dropdown`); two
*enabled* actions may share a key only if their contexts don't overlap — that is how Up / Down are
both Previous / Next Tab and the dropdown's previous / next option. Settings refuses a conflicting
capture, and refuses to switch a row on if its key was taken since — both with a "Shortcut Already Used" popup (`show_message`) naming the other shortcut, not a toast.

**An open dropdown owns the arrow keys and Enter** (`Dropdown.open_one`, checked first in the
filter, ahead of the active-window test since the list is a popup): its two option keys move the
highlight (`Dropdown.move_highlight`, which also fires `hovered` so Settings' theme preview follows)
and Press Selected Option picks it (`pick_highlighted` -> `_on_activated`, the same as a click).
Qt's own handling of Up / Down / Enter in the list is swallowed when they aren't a matching action,
so switching one off (or moving it) really turns it off. Esc is left to Qt (closes the list).

**Full-screen (F11).** In Borderless it is the Settings Fullscreen box (`SettingsTab.set_fullscreen`
-> remembered and saved). In Windowed and Fixed it is `MainWindow._session_fullscreen`: for this
session only, and picking a window mode in Settings clears it. `_wants_fullscreen()` is the flag OR
the Borderless setting; a Fixed window that is fullscreen has its size limits freed for as long as it
is (`_apply_window_mode`), and comes back to the fixed size and centre. Verified on a real display in
all three modes (fills the screen, returns to the exact size).

**Tab / Enter navigation (`ui/keynav.py`).** Every clickable is `Qt.NoFocus`, so this doesn't use
Qt's focus chain: `KeyNav` keeps its own selected stop and draws a `_Ring` (an overlay child of the
window, transparent to the mouse, following its target by a 60ms poll, kept under the toasts by
`_restack`). Stops are collected fresh on each press from the *current tab* (the sidebar has Up /
Down): every visible, enabled `QAbstractButton` (checkboxes, switches, icon buttons; a time field's
▲ / ▼ `stepper` buttons are skipped), `Dropdown`, `SegmentedButton` segment (`nav_stops`),
`SubTabBar` tab (`nav_stops`), track row (the ring goes round the whole `_TrackRow`) and text field
(`QLineEdit` / `_TimeField` take real focus, since typing needs it, and draw their own). Order is
reading order — rows top to bottom (centres within `px(10)`), left to right in a row — and it wraps.
First press selects the first stop (the last, for Shift+Tab); from a clicked-into text field it
continues from there. Enter clicks / opens / selects (`QAbstractButton.click`, `showPopup`,
`SegmentedButton.select`, `SubTabBar.set_active`); a text field lets Enter through to Qt. A mouse
press, or leaving the tab, drops the selection. Not stops: sliders (Left / Right are the preview
keys), queue rows, the carousel, and the sidebar.

Clickables are `Qt.NoFocus` (see Conventions), so clicking a sidebar button
never swallows the Space bind. Add new binds to `core/keybinds.py` and `_Keybinds`, not on tabs.

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

### UI scale (`ui/scale.py`)

**Every size in the app is authored in reference pixels — the pixels of the
896x540 window the layout was designed at — and multiplied by one scale
factor where it becomes real pixels.** The factor is `min(width/896,
height/540)` of the window (`scale.fit`), so proportions hold at any window
size; at the reference size it is exactly 1.0 and every number in the code
means what it always did. **Tune a size by changing its reference number, and
never write a bare pixel count into layout, fixed-size or paint code.**

`MainWindow.resizeEvent` sets the factor (`scale.set_factor`) **on every
resize event — the whole window follows a drag live, with no debounce** —
which re-runs every bound setter, emits `scale.changed` (`_on_scale_changed`:
`_restyle`, then `scale.settle()`). **Everything else a resize needs is also
finished inside `resizeEvent`, not left for later**: `_settle_layout` flushes
the invalidated layouts (`sendPostedEvents(LayoutRequest)`, three passes — a
layout activating only posts its parent's request once its own size has
changed, so one flush leaves a chain behind), then `_replace_overlays` re-places
the tab pipe and toasts. This is what makes a drag smooth: Windows paints
between a resize and the next posted event, so anything left to a queued
`LayoutRequest` or a `singleShot(0)` was painted one frame late — the new
window size with the previous step's layout (~60 widgets 1-2px off), the tab
pipe trailing its button. Measured by snapshotting every widget's geometry at
each paint of a stepped resize and comparing with the settled layout: 58 of 60
steps were torn before, 0 of 60-120 are now, on every tab, in Windowed and
Borderless (per-step cost unchanged, ~14ms median). `_schedule_replace`
(the timer) is still what `_apply_window_mode` uses. What's left is integer
rounding — each `px()` length flips at a slightly different scale, so a widget
can step back 1-2px for one step (a handful of 3-7px ones in 500) — which a
pixel-snapped widget layout can't avoid. A window that isn't the reference
shape scales by its tighter dimension and the flexible areas (preview, entry
fields, button rows) take up the slack. Two things keep resizing from
fighting the scale: the main layout is `SetNoConstraint` (its own minimum at
the *current* scale would otherwise stop a shrinking window from ever
lowering it), and it is a `_MainLayout` that opts out of height-for-width — a
word-wrapped label in a page (Settings has several) otherwise made Qt restore
a maximised or fullscreen window at the height those labels wanted at the
*outgoing* scale (1388px on a 540px window, half off-screen).

**What makes live resizing affordable — the stylesheet is the whole cost.**
Profiled per rescale on a loaded window (~500 widgets): bound setters, layout
and paint are ~10-15ms together; `QApplication.setStyleSheet` alone was
~185ms (the same sheet set on the window: ~45ms; on one page: ~13ms). So:

- **`QApplication.setStyleSheet` runs once, at startup** (`main.py`), and is
  never touched again. It exists so widgets *measured during construction*
  (tabs are built parentless; a `sizeHint()` taken in a constructor needs the
  sheet already in force) see the right lengths. After that the sheet is
  applied **on the widget** — `MainWindow._style(target)` — for the two things
  on screen, the sidebar and the current page; a page that isn't showing
  catches up in `show_tab` (`_style` after `setCurrentWidget`, then
  `scale.settle()`). A widget-level sheet overrides the application-level one
  (Qt's rule, whatever the specificity), so the stale app-level sheet is
  harmless. This also covers a **theme or appearance switch**, so Settings'
  hover-preview of a palette restyles ~13ms of widgets instead of all of them.
- **`_style` compares stylesheet *text* to decide whether to re-apply the
  sheet**: every length in it is a whole pixel, so a drag's tiny steps often
  produce a byte-identical sheet and nothing is re-applied. Measured: a
  2px-per-step drag costs a median 17ms/step (~58 steps/s), a coarse
  0.005-scale-per-step one ~38ms. **It is keyed on the scale as well, for the
  layouts only**: a `ScaledLabel`'s size hint follows the scale continuously,
  not the sheet's whole pixels, and a hidden page's `updateGeometry` calls
  reach nothing, so a page's layouts are invalidated whenever the scale moved
  since it last was (its sheet is left alone when the text is unchanged).
  Keyed on the text alone, a page came back from a tab switch with hints from
  an older scale, and Muxing's Overview sized 2px short.
- **A widget-level sheet on a big container cascades over its whole subtree**,
  so nothing that contains the pages may carry one: the window background and
  the tab frame are **painted** (`MainWindow.paintEvent`, `_TabFrame`), not
  styled by `#Root` / `#TabFrame` rules (pixel-identical to the QSS look), and
  `MessageDialog` styles itself in its constructor (a dialog built after a
  rescale must not inherit the stale app-level sheet). Tooltips already carry
  their own.
- **Restyling a page invalidates every layout in it** (`_style`): a restyle
  refreshes the cached size hints of visible widgets only, and a page's
  *hidden* panels (Encoding's Video/Audio while Overview shows, once they've
  been shown or grabbed) kept their old-scale hints — `panels.sizeHint()` read
  116 instead of 91 and the preview stayed the wrong height until that panel
  was next shown. The same reason a hidden *page* is restyled only after it
  is made current, never before: a hidden widget restyled doesn't invalidate
  its parent's layout.
- A rejected idea worth recording: building each `Dropdown`'s popup lazily
  (24 dropdowns x ~8 hidden widgets) — `QComboBox` creates its popup on the
  first `addItems`/row insertion whatever you do, so it would mean owning the
  item storage; not needed once the stylesheet was scoped.

**Verified end to end**: a simulated border drag (a file loaded, every
sub-tab browsed first, then 70-300 resize steps with no waiting, at several
target sizes) ends **pixel-identical to a window resized once to the same
size**, on every page including those hidden during the drag; a live theme +
appearance-mode switch matches a launch in that theme; and everything from
"Verified" below still holds.

Three rules cover every kind of size:

- **Layout, fixed sizes, margins, spacing, spacer items** go through the
  bound helpers — `scale.fixed(widget, w=, h=)`, `scale.bounds(...)`,
  `scale.margins(layout, l, t, r, b)`, `scale.spacing(layout, n)`,
  `scale.spacer(layout, n)` (in place of `addSpacing`), `scale.grid_spacing`
  — each of which applies the value now *and* again on every scale change.
  `button()`, `IconButton`, `Dropdown`, `labeled()` and `hrow()` take
  reference sizes and bind them for you. Anything else set once that depends
  on a size takes `scale.bind(widget, fn)`.
  A bound setter is **keyed** (`"spacing"`, `"fixed-w"`, ...): binding the
  same thing on the same widget again *replaces* the earlier one. A raw
  `layout.setSpacing()` after a bound one is a bug — the bound value comes
  back on the next rescale (Encoding's `left.setSpacing(0)` after
  `stream_page()` did exactly this and left every row 9px too far apart).
- **Sizes measured off other widgets' size hints** (Muxing's track box takes
  the Overview page's height, then Select/Deselect All take what's left)
  use `scale.bind_after`, which re-runs once the stylesheet has been
  re-applied — measured earlier, the hint still reflects the old scale.
- **Custom-painted widgets are authored in design space**: `scale.begin(p)`
  right after creating the painter, then `scale.ref_rect(self)` /
  `scale.ref_size(self)` for the widget's size and `scale.ref_pos(e.position())`
  for mouse hits, and every literal in the paint code stays a reference
  number. Fonts inside a painter are `ui_font(px)` — a *reference*-size
  font, which the painter scales — and text measured for a fixed size or a
  marquee is measured with that same font in reference pixels. **Text on a
  stock widget goes through the same painter**: use `ScaledLabel` (never a bare
  `QLabel` with text), `button()` (a `ScaledButton`) and `ScaledLineEdit` (never a
  bare `QLineEdit`), whose stylesheet font
  size is in *reference* pixels (`font-size: 12px`, not `font_px(12)`) and
  which paint their text in design space and turn Qt's reference-size size
  hints into real ones ("text part x scale + the stylesheet's box"). Why:
  **Qt snaps every widget font to a whole pixel size, whatever the family,
  font engine, hinting or strategy** (`setPointSizeF(12.5)` is 13px; verified
  for Roboto, Arial and Segoe UI), so stock text hopped between sizes as the
  window was dragged. Measured on a sentence swept over scale 1.0-1.5: a word's
  position wandered 5.5px rms (worst 16px, one step 29px) as a widget font,
  0.32px rms (worst 0.8px, one step 1.4px) through the scaled painter. Fonts
  are **unhinted** (`main.py`'s app font, `ui_font`, and the two widgets force
  it themselves): hinted glyph advances are irregular (a line is 227 / 236 /
  262px at 12 / 13 / 14px against a linear 224 / 242 / 261) and hinted glyphs
  are placed on whole pixels, which put 0.4px of unevenness into letter and
  word gaps once painted at a fractional scale (0.07px unhinted). Still on
  the whole-pixel path, so still stepping: only the combo popup's rows (the
  stylesheet's `font_px(13)` base rule), which are open for a click and never
  on screen while the window is being dragged. A rich-text
  `ScaledLabel` (Settings' system info) paints through a `QTextDocument`.
  **`ScaledLineEdit`** can't route Qt's own painting through a painter (`QLineEdit`
  opens one internally), so it takes over exactly the two things that touch the
  font — painting (the stylesheet still draws the box, focus border and disabled
  colour; text, placeholder, selection band and caret are drawn from the reference
  font, with its own scroll-to-caret and blink) and mouse-to-character mapping
  (press, drag, double-click, shift-click, by the same metrics as the painting) —
  and leaves keys, undo, the clipboard, the selection model and every signal to
  Qt. Measured like the labels: 5.2px rms (worst 14.6px, one step 26px) as a
  `QLineEdit`, 0.53px (worst 1.6px, one step 1.8px) as a `ScaledLineEdit`. Not
  reimplemented: dragging selected text out of the field, IME pre-edit drawing.
  **A size hint from Qt cannot be scaled whole**: the stylesheet's `min-height` is
  real pixels and Qt folds it into `sizeHint()` — and into a label's
  `heightForWidth()` — so multiplying the hint by the scale multiplied the
  minimum too (a 26px caption box came out 104px at 2x; every control under a
  caption sat that much lower, buttons came out 76px instead of 57, the preview
  above was squeezed). It is invisible at scale 1.0, which is why it shipped, and
  only obvious in fullscreen. **Qt folds `min-width` into the hint too** — a
  fixed-width label's fixed width, so a `setFixedWidth(872)` label reported 1744.
  So none of the three widgets takes a size from Qt any more: each measures its own
  text with the reference font (`ScaledLabel._unwrapped_hint`, `_wrap_widths`;
  `ScaledButton` / `ScaledLineEdit` the same, with the padding taken from the style's
  contents rect) and applies `minimumHeight()` last.
  **A word-wrapped `ScaledLabel` computes its own width hints** (`_wrap_widths`, from
  the reference font: ideal = about 4:1 wide, minimum = the longest word, minimum
  height = one line) rather than converting Qt's. Qt picks a wrapped label's ideal
  width by aspect ratio with reference-size text and real-pixel padding mixed
  together, so the answer drifted with the scale (a 132px-wide tooltip at 1x came
  out 220 at 1.9x, where 250 is proportional), and its minimum hint is the tall,
  narrowest wrapping — which a *top-level* window enforces as a floor on its height:
  the shared tooltip, reused across scales, came out 450x287 for a two-line tip
  (only on a window already created at another size, hence "sometimes"). The tooltip
  manager also sizes the popup itself (width clamped to its maximum, then
  `heightForWidth` *at that width*) instead of `adjustSize`, which works the height out
  at the unclamped hint width and cuts the last lines off a long tip. Verified by
  driving the real manager over every tip string and 7 scale changes on one reused
  window (259 sizings, 0 bad; the previous logic fails 191 of them) — reuse across
  scales is the state that matters, so test that, not a fresh window per size.
  **The regression test for this whole class of bug is a proportions check**:
  every visible widget's rect at scale K must be K x its rect at scale 1 (client
  size set with `resize`, exactly K x 896x540 — `SetWindowPos` sets the *outer*
  frame and changes the aspect), across every tab and sub-page. 531 widgets, 0
  deviations at 1.5x / 2x / 2.6x; the old code deviates by up to 104px (a check
  that can't fail proves nothing — confirm it fails on the broken code). The
  stylesheet's lengths (padding, radius, min-height) stay `px()` / `font_px()`
  calls inside `ui.theme.stylesheet()` (regenerated on a scale change), and a
  real widget's other font needs go through `set_font_px(widget, px)` (which
  the stylesheet's own font rules override on a label — it does nothing
  there: confirmed directly — right after `set_font_px` the font reads the size given, and
  the very next `ensurePolished()` [what a real show() triggers] puts it straight back to
  whatever the matching stylesheet rule says, since Qt's own style engine's `.setFont()`
  call runs after and wins over a plain one. The one thing that *does* survive a later
  restyle is the label's own *instance*-level `setStyleSheet()` — Settings' About notice
  binds `notice.setStyleSheet(f"font-size: {scale.font_px(12)}px;")` on every scale change
  for exactly this reason; see "About" under Settings below). Widths from
  `Dropdown.width_for` / `button_width_for` are reference pixels too.
  The carousel is the exception: it paints in real pixels (its frame and
  hit-testing are fractions of a real rect), with `px()` / `fpx()` on its few
  absolute constants — margins, dot sizes, badge floors.

**Scans re-run 2026-09-21** (after the loading spinner, the carousel hover growth, the LlamaLog
row, the Start Time muting and the background HDR render), each against a plain `git archive` of the
previous commit for comparison. **Squeeze: 0 squeezed of 4,660 layout checks** (19 page states x 5 scales x
exact / wider / taller windows; the previous commit: 0 of 4,615). **Proportions: the same 165 widgets
drift more than 3px, at 1.5x-2.6x, in both trees, and none of the 60 new widgets' checks exceeds
1.2px** — i.e. rounding that already existed (4 to 16 widgets per Muxing/Encoding page at 2.6x, up to
~3.6px, apart from the stale-hint case below), not something added. Both scans were shown able to fail (an unscaled +40px on a Settings
dropdown; the Video page forced 4px tall — both caught). `_Grip` (the borderless window's resize
strips) is excluded from the proportions scan: it is real pixels by design. **Two pre-existing findings
from the same runs, both identical on the previous commit**: (1) the sizing INVARIANT slips by 1px at two
of 42 scales (1.415x and 2.38x: the Encoding *Audio* page is 1px taller than Overview, so the Encoding
preview is 1px shorter than Muxing's — 352 vs 353); at 1.0x the two DropBoxes are identical (670x253);
(2) **Muxing's panel stack is left too tall after the window is dragged bigger and then smaller**
(1.0x -> 2.6x -> 1.0x gives 164px, not 118, and 1.0x -> 1.5x -> 1.0x gives 134; the stale height
sits on a *hidden* sub-page's size hint and clears when that page is shown; Encoding is unaffected).
It shrinks the preview and breaks the Muxing/Encoding invariant until then. Not fixed here (a task is
queued for it). **The scan harness needs the window in a known state: an earlier scale change can leave
this stale hint behind, which is what produced a 116px "deviation" in the first proportions run.**

**Verified**: a harness that renders every page (Muxing/Encoding x
Overview/Video/Audio with and without a file, Downloader, Queue with rows and
the details popup, Settings' three pages, a toast, and the hover chevrons,
expanded preview, Wave Loop, open dropdown, tooltips and dialogs) is
**pixel-identical to the pre-scale code at scale 1.0**, and a live rescale
(1.0 → 1.5, 1.0 → 0.75, 0.75 → 2.0, 1.5 → 1.0) is pixel-identical to a fresh
launch at the target scale. That equivalence is the regression test for any
sizing change: capture pages at 1.0 before and after; a difference means a
number moved. (The "Selected File:" marquee scrolls on the wall clock, so
that one strip differs run to run — mask it.) That equivalence was established
before `ScaledLabel` / `ScaledButton`; since, stock text is unhinted and drawn
through the scaled painter, so glyph pixels differ from a hinted whole-pixel
render even at 1.0 — compare *geometry* (widget rects) and mask text, or
re-baseline once.

### Theming (`core/theme.py` + `ui/theme.py`)

**`core/theme.py` is the source of truth for brand colour.** `THEMES` holds
ten palettes — `Lemon` (`#FDCA3C` primary / `#3B8ED0` secondary, the
original look), `Cupid` (`#FA6E99` / `#780219`), `Lilac` (`#a58fd7` /
`#3e6d04`), `Ranger` (`#F98524` / `#104E4B`), `Noir` (`#131317` / `#5A5B63`),
`Luck` (`#ADBCDE` / `#0E5914`), `Vaporwave` (`#3B41B8` / `#ED72D4`),
`Dreamsicle` (`#f9be90` / `#f97c9c`), `Funk` (`#3dbcc1` / `#4b3383`) and
`Terminal` (`#000000` / `#44fe2c`) — the last two carry the extra keys described
below (`sidebar_text`, `swap_subtabs`, `swap_action_buttons`, `primary_hover`). Every
colour is a **flat hex string, not a (light, dark) pair** — appearance mode
never changes a theme's colours. Hover shades are auto-derived by `_darken()`
(~0.87 brightness) except Lemon's primary hover, kept at its historical
`#e0b234`.

`get_theme(name)` returns the palette plus derived text colours:
- `primary_text` / `secondary_text` — `readable_text_on()`: black or white,
  whichever has the higher WCAG contrast against that fill (Noir's near-black
  primary gets white; Lemon's `#3B8ED0` secondary gets black).
- `sidebar_text` — the colour of the sidebar's **title and logo only** (the
  `sidebarTitle` role and `Sidebar._load_logo`'s tint). It is `primary_text`
  unless the theme names its own `sidebar_text` in `THEMES` — **Funk** does
  (`"white"`: its `#3dbcc1` teal derives black everywhere, but the title and llama
  read better in white) and so does **Terminal** (`"secondary"` — the keyword form,
  resolved in `get_theme`, so it tracks the theme's secondary, `#44fe2c` green). The
  sidebar footer, the Borderless window controls and everything else on a primary
  fill keep using `primary_text`.
- `subtab_active` / `subtab_inactive` (+ `_hover` / `_text` each) — the fills the
  `SubTabBar` uses for the selected tab and the others: primary / secondary, or
  **swapped for a theme with `swap_subtabs`** — **Terminal**, whose black primary
  vanishes as a selected tab on the dark frame, so its selected tab is the green
  and the others black (the line under the bar follows `subtab_active` too, so it is
  the green there and primary everywhere else). Terminal also names a
  `primary_hover` (`#1c1c1c`): black's derived hover is black again, which would
  leave the now-black inactive tabs (and every primary button) with no hover
  feedback.
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

On `changed`, `MainWindow._restyle` re-applies `ui.theme.stylesheet()` to the
sidebar and the page on screen (~13-20ms; the rest catch up when shown — see
"UI scale" above) and every custom-painted widget repaints from `T.theme` —
each connects `T.theme.changed` to its own `update()`. Nothing is destroyed,
so no form state is lost, and Settings can preview a theme across the whole
window on hover.

`_rebuild_colors` also drives the native title bar through
`QStyleHints.setColorScheme` (Qt 6.8+). **System mode must call
`unsetColorScheme()` *before* resolving the mode** — after an explicit
Light/Dark, `colorScheme()` would otherwise read back the app's own override
rather than the OS setting. A `_rebuilding` guard stops the resulting
`colorSchemeChanged` from re-entering.

**The stylesheet styles stock widgets only**, keyed by a dynamic `role`
property:
- `QPushButton` — secondary by default; `role` = `primary`, `danger`
  (STOP_RED), `ghost` (transparent), `stepper` (the TimeSpinner arrows), and two
  that **a theme can swap**: `action` (the do-it-now / affirmative buttons — Mux /
  Encode / Download, Start / Pause Queue, Settings' Save, the Downloader's Fetch and a
  dialog's first button) and `queue` (their quieter partners — Queue Task, the
  Downloader's Paste and a dialog's decline buttons, No / Cancel). They are primary and
  secondary respectively — pixel-identical to the old `primary` / default — except
  in a theme with `swap_action_buttons` (**Terminal**: black primary, so its
  Mux / Encode / Download / Start Queue / Save / Fetch / a dialog's Yes-OK are the green
  and Queue Task / Paste / No-Cancel are the black).
  `ui/theme.py`'s `_rebuild_colors` aliases `action_btn*` / `queue_btn*` (fill,
  `_hover`, `_pressed`, `_text`, `_disabled_text`) from whichever colour the theme
  assigns. Any *other* primary-role button is deliberately not swapped.
  After changing a role at runtime call `controls.restyle(widget)`.
- `QLabel` — `field` / `field11` (bold Arial captions, 26px min-height, which
  gives the airy label-above-control rhythm), `muted`, `meta`, `hint`,
  `title`, `dialogTitle`, `detailTitle`, `detailKey`, `error`, `empty`,
  `warn`, `sidebarTitle`, `sidebarFooter`. `QLabel:disabled` dims captions.
- `QLineEdit`, `QSlider` (incl. disabled handle/fill; **the knob's size, margin
  and radius are derived together in `stylesheet()`** — Qt's handle box is
  groove + 2 x margin, and rounding `px(16)` / `px(4)` / `px(-6)` separately left
  it a pixel off the knob at ~16 scales in 0.6-3.0, drawn as a square instead of a
  circle; scan pixels across scales after touching it), `QScrollBar`, and the
  combo popup (`QComboBox { combobox-popup: 0 }` so the list drops below the
  button instead of over it; the private container transparent; rounded
  view; 28px rows).

Everything with custom geometry (dropdown button, checkbox, switch, segmented
button, time field, sub-tab bar, drop box, sidebar, tab pipe, carousel, queue
rows, toasts) paints itself.

**Persistence.** `settings.json` (repo root, gitignored): `theme`,
`appearance_mode`, `default_save_location`, `gpu_enabled`,
`downloader_separate_save`, `downloader_save_location`, `naming_template`,
`priority_level`, `when_done`, `when_done_reset`, `window_mode`,
`borderless_fullscreen`, `startup_tab`, `log_detail`, `keybinds`; missing keys or a
missing/corrupt file — or a stored `naming_template` / `when_done` /
`priority_level` / `window_mode` / `startup_tab` / `log_detail` that's no longer valid (a hand-edited file) —
fall back to their defaults: `Lemon` / `System` / `~/Videos/LlamaMXD
Export` / `True` (GPU) / `False` / `""` (the last two back Settings' "Separate
Save for Downloader" — see "Tabs → Settings" below), then the naming format,
`Normal`, `Do Nothing` / `True`, `Fixed` / `False`, `Encoding` and `Normal` (the log detail). A corrupt
`settings.json` is logged as a WARNING before the defaults are used. **Presets**
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

**`FPS_VALUES`/`fps_values_for`/`fps_arg_for`** are the same idea for frame
rate: `SOURCE_FPS` (`"Source"`) plus a fixed descending ladder — `120`, `60`,
`59.94`, `50`, `48`, `30`, `29.97`, `25`, `24`, `23.976`, then `12` / `8` for
deliberately choppy/stop-motion-style output. **The three NTSC rungs are exact
rationals on the command line**: `fps_arg_for` maps `"23.976"` / `"29.97"` /
`"59.94"` to `24000/1001` / `30000/1001` / `60000/1001` (`-r` accepts them), since
the rounded decimal would retime a true NTSC source a hair off and drift audio sync
over a long file. Because that value is no longer a bare number, comparisons go
through `fps_number_for` (`float("24000/1001")` doesn't parse — `ffmpeg_vars._fps_arg`
used to call it). `fps_values_for(source_fps)` caps the list to `SOURCE_FPS` plus
every rung **at or below** the source's own rate — never a speed-up — with a 0.1
tolerance so a true 29.97/23.976 source still offers the round 30/24 sitting just
above it, and falls back to the full ladder when the rate isn't known yet.
`fps_arg_for` is the reverse lookup `ffmpeg_vars._fps_arg` uses to build the actual
`-r` value. **The FPS dropdown must stay exactly as wide as Resolution's** (83
reference px — `"23.976"` fits inside it): the Video page has ~4px of slack and FPS
lands under Resolution by having the same width.

### Tabs

#### Muxing and Encoding (`ui/tabs/media_tab.py`)

**The two tabs are not variations on each other — Muxing never re-encodes.**
Muxing is container change + stream selection, everything `-c copy`, with no
codec controls at all. "Copy video, re-encode audio" is an *Encoding* job with
the encoder auto-resolved to the source's own codec. Encoding is the superset.

They share one frame, `MediaTab`, top to bottom:
- **Header**: a `SubTabBar` (Overview / Video / Audio) and the `Selected
  File:` `MarqueeLabel` (double-click to reselect).
- **Preview**: a `QStackedLayout` holding the `DropBox` (its loading spinner, once a file
  is picked) until the carousel's
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
  Video-panel layout on Encoding) below.
- **Save row** (entry + Browse) and the **actions** (`Queue Task` secondary,
  `Mux` / `Encode` primary — queue *and* start; by role `queue` / `action`, which a
  theme can swap — see Theming).

Subclasses set `TAB`, `ACTION_TEXT`, `OUTPUT_SUFFIX` (`_muxed` / `_encoded` — now only
the fallback when the naming format would name the output after the input itself),
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
the toast. Queue Task / Mux / Encode are greyed until a file is selected
(`_apply_import_gate`, both ways — same as the Downloader's until a fetch
succeeds); everything else is validated on click.

**Muxing / Video** and **Muxing / Audio**: a `TrackListBox`
(`ui/widgets/tracklist.py`) — a scrollable box bordered in the theme's
*secondary* colour (blue on Lemon), the same border colour DropBox itself
uses — with one checkbox per stream the source actually has,
every checked one mapped into the output. This replaced the original single
`Auto`/`Track N` dropdown: Muxing now mixes and matches any combination of a
file's own tracks, not just one at a time. The box carries no caption of its
own (the sub-tab's own "Video"/"Audio" label already says what it's a box
of) and **fills the row**, stopping only where a narrow column sits to its
right: `Select All` / `Deselect All` — two **icon buttons** (`IconButton` kinds
`select-multiple` / `deselect-multiple`, `assets/select-multiple.svg` /
`deselect-multiple.svg`, recoloured to the button's own text colour by string-replacing
the SVG's black `stroke` — `svg_renderer(..., "ink")`, same trick as the carousel's
`fill="currentColor"` swap; each has a hover tooltip, since there's no caption)
sharing a line on top (checks/unchecks
every row in the box — `TrackListBox.item_ids()`, every row regardless of
current state, vs. `checked_ids()`'s already-checked-only — without adding
or removing anything, the non-destructive counterpart to `Remove
Stream(s)`), then `Add Stream(s)` beneath them, then `Remove Stream(s)`
(`role="danger"`, STOP_RED) at the same width, then on the bottom line
**`Undo` / `Redo`** — two more icon buttons (`undo.svg` / `redo.svg`, kinds `undo` /
`redo`) with the **Strip checkbox to their right**. The two-button rows
(`Select All`/`Deselect All`, `Undo`/`Redo`) each share one line rather than each getting
their own full row, which is what keeps this four-row column short enough to still fit
under the box's own fixed height (see the panel-height paragraph below for why that
specifically breaks). `Add Stream(s)`/`Remove Stream(s)` share one width
(`button_width_for`); each icon pair is half that width less half a 4px gap, so the pair
lines up under them and sits as tight as the rows do (4px between the buttons, the same as
the column's vertical gap — it was 8).

**Icon sizes.** `IconButton` draws its SVG in a square of `_ICON_FRACTION` × the button's
shorter side (default 56%, 72% for a `compact` button). Undo/redo override it to **100%**
(140%, then 120%, each judged a little too big; the default drew them tiny): their arrow only
fills ~16×8 of a 24-unit viewBox, so at the default the arrow was too small, and at 100% the
box is the button's height.

**Greyed when there's nothing to act on.** `Select All` / `Deselect All` / `Remove
Stream(s)` and the box itself are disabled while the box is empty (no file yet, or every
track removed); `Add Stream(s)` stays live. A disabled `role="danger"` button now dims its
text (`stop_disabled_text`, `disabled_text_on(STOP_RED)`) — the danger rule used to
override `QPushButton:disabled`, so a disabled Remove Stream(s) looked enabled.

**Even four rows only just fit**: Overview is 118px, and 28 + 28 (Add, Remove) +
24 (the Undo/Redo/Strip row — the checkbox's own height) + 12 (three 4px gaps) leaves 26 for
Select/Deselect All. So Undo/Redo and Select/Deselect All are `role="compact"` (stylesheet
`min-height: 22px` — the stock 28px `min-height` defeats any fixed height, so a
shorter button needs its own role), the column's gaps are 4px (they were 6 with three rows),
and Select/Deselect All take whatever height the box has left
(`size_box`: `box.height() − 2·px(28) − px(24) − 3·px(4)`, floor `px(22)`; a fixed
row height with Expanding buttons, since the button's own `min-height` overrides a
`setFixedHeight`). **The gap change is what makes it safe, not cosmetic**: with 6px
gaps the column had 0px to spare at 1.0x and, at 1.25x, five independently-rounded
`px()` lengths made it 3px taller than the box — the whole page 3px taller than
Overview, i.e. a smaller preview on Muxing than on Encoding. With 4px, the Video and
Audio pages are never taller than Overview at any of 42 scales checked from 0.8x to
2.6x (re-checked after Strip moved onto the Undo/Redo row). Re-run that scan (Video/Audio
`sizeHint().height()` against Overview's, showing
each page before measuring — a hidden page is restyled lazily, so its hint is stale)
after touching this column.

**Row text marquees, the checkbox doesn't.** Each row is a `_TrackRow`
(`ui/widgets/tracklist.py`): a text-less `CheckBox` plus a `MarqueeLabel`
(Arial 12 bold, matching the checkbox's old caption) joined to one
`MarqueeGroup` per box, so a long label (a video row's full details, an
`External: …` row) scrolls while short ones sit still, and every loop restarts
together only after the longest sweep finishes — same as the Overview rundown.
**The group owns the one 16ms timer and reads the clock once per tick**
(`MarqueeGroup.now`); every label paints from that snapshot and all of them are
`update()`d in the same tick. Each label used to run its own timer and read
`perf_counter()` at its own paint, so rows that started together were painted on
different ticks and crept relative to each other. The group also caches its
`period()` (it was recomputed — a font measurement per member — by every label on
every frame). A standalone `MarqueeLabel` gets a private group, so there is one
code path. The timer is **parented to the `QApplication`**: a parentless `QTimer`
owned by a Python object was torn down after the application at exit and crashed
the interpreter about half the time (10/10 clean once parented). A click anywhere on
the row
toggles the checkbox (`CheckBox.set_hover` forwards the hover shade);
`MarqueeGroup.unregister` runs when a row is removed so `period()` never
touches a deleted label.

**Drag a row to reorder it — any row, checked or not.** A left press that moves further
than `QApplication.startDragDistance()` is a drag instead of a click (`_TrackRow`'s
press/move/release; letting go after a drag toggles nothing, and a press-and-release
without moving still toggles the checkbox). The row's `CheckBox` is transparent for mouse
events so a drag can start *on* it — a press on a widget that takes it never reaches the
row. `TrackListBox._begin_drag` leaves the row in the layout as a 28%-opacity placeholder
and puts a `_DragGhost` (a snapshot of the row on a rounded slab in the `window` colour —
the box has no background of its own, so a bare snapshot printed over the rows beneath)
on the scroll viewport. **The ghost's corners are rounded (`px(6)`)**: the slab is painted
and the snapshot clipped to one rounded path, and the snapshot is rendered onto a
*transparent* pixmap (`_DragGhost.snapshot`, `render(..., DrawChildren)`) rather than
`QWidget.grab()`, which fills the row with its own opaque window-colour rectangle — on
Windows that rectangle covered the rounded backing and showed as a sharp-cornered band;
checked by pixel (all four corners of the ghost transparent, also with the old opaque
`grab()` forced back in, which is what the clip is for); `_follow_cursor` keeps the ghost under the
cursor (clamped to the viewport, keeping the grab offset) and moves the placeholder
through the layout to the slot the ghost's centre is over, so the other rows make room
live — the slot is worked out from the ghost's centre in *host* coordinates
(`host.mapFrom(viewport, …)`; `viewport.mapTo(host, …)` is backwards, host being the
child, and returned garbage that clamped to the last slot, which an assertion on a
drag-to-the-bottom did not catch). A 16ms timer scrolls the list while the cursor is
within 22px of the viewport's top or bottom edge, faster the deeper it is. The drop
reports every id in its new order through `TrackListBox.reordered`; nothing is reported
for a drag that ends where it began. `MuxingTab._reorder_tracks` reorders `_tracks[kind]`
through `_edit_tracks`, so a move is **one undo step** like Add and Remove, the
renumbering comes from `_items_for` as it does after a removal, and `_track_args` — which
follows the box's order — makes it the output's stream order. Verified by driving real
mouse events into a row (click still toggles; a checked row and an unchecked row dragged
to the bottom / top; undo ×2 and redo; mux args follow the order; a drag that ends where
it began adds no history). **Tooltips are held for the length of a drag**
(`tooltip.hold_tips(True)` in `_begin_drag`, `False` in `_finish_drag`): the box's own tip
is registered on the box, but a press on a row goes to the *row*, so the manager's
press-hides rule never saw it and the tip could appear (or stay) mid-drag. While held, the
popup is hidden, an Enter arms nothing and `_show` is a no-op; on release the hover delay is
re-armed if the cursor is still over the last-hovered widget, so the tip returns after its
usual 400ms of stillness rather than the instant the row drops.

**A row's text is "Track N  ·  details", N being its place in the box** (so
removing a track renumbers the ones below it) and a track from another file says
`External: <name>` after the number. **Video details are `codec · profile · level ·
size · fps · HDR kind · bit depth + chroma · bit rate · language`**
(`H.265 · Main 10 · L3.1 · 1280x720 · 23.976 fps · HDR10 · 10-bit 4:2:0 · eng`), from
`core.probe._describe_video_stream` — which now also asks ffprobe for `pix_fmt` /
`bits_per_raw_sample` and reuses the codec-aware `_ffprobe_level`. `hdr_display` is
`HDR10` (PQ), `HLG` or `SDR` — anything that isn't PQ/HLG, the same call
`probe_media`'s `hdr` makes; a stream's own bit rate is absent from most Matroska
files, and then simply isn't shown. Audio rows are unchanged (codec · channels ·
rate · language). The "Add Stream(s)" picker is a fixed 400px dialog of plain
checkbox captions, so it gets `compact=True` (codec · profile · size · HDR only when
it is · language) and its "Track N" is the stream's number in *its own file*.

`Add Stream(s)` browses a second file, probes it off the GUI thread
(`core.probe.probe_media` via `run_async` — never on the GUI thread,
same rule as everywhere else), and either adds its lone matching-kind stream
straight away or — when it has more than one — opens
`ExternalStreamPickerDialog` (`ui/widgets/dialogs.py`) to choose which. Each
added stream becomes its own row at the bottom, independent of the primary input,
so switching the primary file later doesn't clear it.

**`MuxingTab._tracks` is the list each box shows — not the probe.**
`{"video": [...], "audio": [...]}`, each entry `{"id": "src:N" | "ext:xxxxxxxx",
"source": "primary" | "external", "file", "index", "stream", "name"}` (`index` is
0-based among that file's own streams of the kind — what `-map` addresses;
`stream` is the probe's description of it, kept so a label can be re-rendered
whenever the number changes). `_reseed_tracks` builds it from `app.media.info` —
the source's streams first, any external entries kept after — whenever a **new
probe result** arrives (`info is not self._tracks_info`: the object changes per file,
not per broadcast), and clears the undo history with it, since its snapshots describe
the old file. Entries are never mutated, so a snapshot of a list is just a copy.
`_track_args` maps the checked rows *in the box's order* (the output's stream order).

**`Remove Stream(s)` removes every checked row from the list — the source file's
own tracks included** (the source file is untouched; the track just isn't offered any
more). It used to uncheck a source row it "couldn't delete"; that distinction is gone.
The rows below move up, so **track numbers ripple** (remove track 2 and track 3
becomes track 2 — `_items_for` numbers by position, and `TrackListBox.set_items`
refreshes every surviving row's label). Pressing it with nothing checked shows a
message. Removing everything from both kinds (or everything left but a stripped
kind) is caught at queue time: `_validate_specific` refuses a job with no track to
map anywhere ("Nothing to Mux"), since "no rows" no longer means "the file has none"
and ffmpeg would refuse to write an empty file. Verified end to end: removing the first
source video + audio track and running the real Mux gave an output of exactly the kept
tracks, language tags intact. The red Strip checkbox still sits beside `Remove
Stream(s)` and still means "drop this stream kind entirely" — an explicit, separate
control rather than inferred from an empty box.

**Undo / Redo** step through every edit to a box — Add Stream(s), Remove Stream(s), a
drag-reorder **and which rows are ticked** (clicking a row's checkbox, Select All,
Deselect All) — per kind (the Video and Audio panels each have their own pair and
history). A step is a snapshot `{"entries", "checked"}`, capped at 50. List edits go
through `_edit_tracks`; a tick goes through `_track_toggled`; Select All / Deselect All
push a step only if they would change something. `_push_history` also clears redo.
**A tick's step is the state from *before* the click**: the box reports a click after it
happened, so `_checked_baseline` (the ticked ids as of the last `_sync_controls`) supplies
the "before". `_travel` swaps the whole box with the top of one stack and parks the
current one on the other, and **restores the ticks of every row, not just a returning
one** (`_restore_checked` → `set_items(checked=...)`, which now applies to existing rows
too, consumed by the next `_sync_controls`) — an earlier version left surviving rows as
they were, which was right only while ticks weren't tracked. A returning row
lands **where it was**: `set_items` orders the rows to match its item list (it used to
append), and `checked_ids()` follows that order. The buttons enable from the stacks
in `_sync_controls` and are also off while the panel is stripped/absent.
Settings keys `video_tracks`, `strip_video`, `audio_tracks`, `strip_audio` — each
`*_tracks` a list of `{"source": "primary"/"external", "file": path|None,
"index": N}`, one entry per *checked* row, `N` 0-based among that file's own
streams of that kind (what `-map <input>:v:<index>` / `:a:<index>`
addresses). The Queue's details popup therefore shows a track's number *in its
file*, which after a removal differs from the number the box showed.

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
Muxing, the Video-panel layout on Encoding).

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
`_sync_controls` pass with `MuxingTab._items_for(kind)` (the tab's own track list —
see above), it diffs by row id — an id already
present keeps its checked state and just gets its label refreshed, so
clicking one checkbox (which itself triggers `_sync_controls` through the
same `_on_control_change`/`changed` wiring every other control uses) never
disturbs another row — and puts the rows in the order of the list it was given
(a row is moved only when it isn't already in place). It only tears every row down
and rebuilds from scratch
(`reset=True`) when `app.media.current_file_path` itself changed since the last
sync — a new file's stream indices don't mean what the old file's meant, so
a same-named `src:0` row from a *different* file must never be mistaken for
a carried-over pick. A brand new row (first appearance, whether from a reset
or a fresh "Add Stream(s)" pull) **starts checked — every track is selected by
default**, in Muxing and in Encoding's Choose Stream(s) alike (it used to be only the
first, on the theory that a tick means a real stream in the output; changed by
request, so nothing is silently left out and a track just added is not forgotten). A
default is not an undo step. Unless the caller passes `checked` (a set of ids), which an
undo uses to put every row's tick back as it was.

`_validate_specific` blocks a job only when a box actually has rows (a real,
probed stream exists) but the panel isn't stripped and nothing in it is
checked — an unprobed or genuinely stream-less panel is simply empty, not an
error, so an empty box never blocks anything by itself.

**Encoding / Video**: `Encoder` / `Profile` / `Level` / `Encoder Preset` /
`Resolution` on one row (the "Encoder Preset" label keeps the internal name
`speed`; `Resolution` is a downscale ceiling — `formats.RESOLUTIONS`, never
offers an upscale past the probed source's own height, see
`core.formats.resolutions_for`), then a **caption row** — "Quality (CRF):
NN" beside `"FPS:"` — and a **controls row** beneath that: the quality
slider beside the bare `FPS` dropdown (a frame-rate ceiling —
`formats.FPS_VALUES`, same never-upscale rule as Resolution, see
`core.formats.fps_values_for`) with no caption of its own *in that row* —
its caption lives one row up, in the caption row, so the slider and the
FPS dropdown are direct, un-wrapped siblings of the same height-comparison
`hrow` and align exactly the way two plain controls would, unaffected by
either one's own label. Both the slider and "Quality (CRF): NN" are
**fixed to span exactly Encoder..Encoder Preset**
(`slider_row.setFixedWidth(...)` / `crf_label.setFixedWidth(...)`, the
identical sum of those four dropdowns' own known construction widths +
3×8px spacing) — "Quality (CRF): NN" centres over the slider itself rather
than the wider Encoder..Resolution span its column spans, and "Placebo"
lands flush with Encoder Preset's own right edge; `"FPS:"` gets the same
treatment against `FPS`'s own dropdown width, so both captions sit flush
above their controls. `FPS`'s dropdown sits in the gap the slider's fixed
width leaves open, and since `Resolution`'s and `FPS`'s dropdowns both
happen to be the same width, `FPS` lands exactly under `Resolution` with
no explicit positioning math needed. The right column holds `HDRtoSDR`
(label clickable, top) then `Strip Video` (bottom), right-aligned. Profile,
Level, Speed and the quality slider's kind, range, default and end labels
all derive from the encoder (`formats.profiles_for` / `levels_for` /
`quality_for`; `_apply_speed`, `_apply_quality`). A Speed retarget snaps to
the encoder's own recommended default (`speed_default_for`), not the first
— most extreme — entry. AV1's speed list comes from a live probe
(`core.capabilities.av1_preset_range`), since SVT-AV1's preset ceiling varies by
ffmpeg build (confirmed: 0–8 before an update, -2 to 13 after). The slider
keeps its value across a codec switch while it still fits the new range.

**The Video page has no width to spare, by design — and text metrics can eat what
slack it has.** The dropdown row needs 527 reference px (98+115+102+97+83 plus 4x8)
and the HDR column 112, in a 656px page. With text measured *hinted* it fitted with
6px over (row 521, HDR 109); once fonts became unhinted — what is actually painted —
the dropdowns measured 6px wider and the HDR label 3px wider, leaving it 3px short
(and 11px short at 2.6x, since the shortfall scales too). Qt squeezed the Profile
box under its own fixed-width dropdown and cut its arrow section off; `Level`
appeared to encroach on it. The dropdown widths stay as measured (they must match
the painting); the slack came back from the gutter between the columns (`20` -> `14`,
`build_video`) and the HDR label/switch gap (`8` -> `5`): 4px minimum spare at every
scale from 1.0 to 2.6, in exact, wider and taller windows. **A width change to any
control on this page, or to how text is measured, must re-run the squeeze scan**
(below).

**The check for this class of bug is a squeeze scan**: for every visible widget that
has a layout, `layout().totalMinimumSize()` must fit inside the widget's size — a
layout squeezed below its own minimum is what clips a control. Run it over every
page at several scales and window shapes (2286 layout checks: 0 squeezed; with the
old spacing put back it flags exactly the Encoding Video page, so it can fail). The
proportions check does not catch this — a row that is 3px short is 3px short *in
proportion*.

**Encoding's own worked example of the sizing rule above, since revised
four times before landing here.** Resolution originally floated free of the
left/right columns entirely (`res_box.setParent(page)`, positioned every
resize by reading the quality slider's and Strip Video's own real
post-layout geometry) — a `labeled()` caption on its own row inside the
right column had measured 163px against Overview's 118px, and even a
`QHBoxLayout` stretch between Resolution and the columns centred it against
the *right column's own left edge* (HDRtoSDR, wider than Strip Video and
right-aligned within it, sits well left of the checkbox's real position)
rather than Strip Video's own edge. That floating approach measured 105px
against Overview's 118px and shipped for a while. It was retired once
Resolution moved into the Encoder/Profile/Level/Encoder Preset row (by
request, to sit inline with the controls it belongs with) — that widened
the row enough that the gap Resolution used to float in shrank to ~42px,
under even the narrowest dropdown's own 60px floor
(`Dropdown.width_for`'s `min_width`), so nothing could float there any
more regardless of positioning cleverness. FPS, the new control claiming
that conceptual slot, went through two more iterations that both shipped
and were both later replaced by request: first a plain
`right.addWidget(fps_box, 0, Qt.AlignRight)` between HDRtoSDR and Strip
Video (needing its own 26px caption stripped to 0 and an explicit
`right.setSpacing(0)` to land back at 118px); then stacked directly beneath
Resolution's own dropdown *inside Resolution's own column* on the first
row, which reopened the same budget problem from the opposite side —
Resolution and FPS shared that row, and a row's height is set by its
*tallest* column, so two stacked `labeled()` boxes there made the row
112px tall against the other columns' 55px (162px total), clawed back down
to 118px only by stripping Resolution's own caption floor, dropping FPS's
caption entirely, and butting the two flush (`setSpacing(0)`) — which then
drew its own complaint (read as one tall control with a seam, not two
dropdowns).

**Sidestepping the budget fight, mostly.** Once the quality slider stopped
spanning the full row width (fixed to Encoder..Encoder Preset only, for the
"Placebo" alignment request), the space under Resolution's own column on
the *slider's row* was sitting empty — putting a caption-less FPS there
cost the page nothing at all, and Resolution went back to a plain,
unstripped `labeled()` box matching its row-mates exactly. **FPS's caption
then came back by request too** (a bare dropdown under Resolution read as
unlabelled, not obviously FPS) — first as a `labeled()` box wrapping the
dropdown directly, which reopened a smaller version of the same fight
(the box, caption included, was 55px tall against the slider's own 18px,
pushing the row's height to 55px) *and* broke the slider/FPS vertical
alignment: `AlignVCenter`-ing the two against each other centred the
slider against the whole 55px box, not against the FPS *dropdown*
specifically (which occupies only the box's bottom 28px, below its own
caption), landing the slider visibly higher than the dropdown instead of
level with it. **The fix was to stop wrapping FPS's dropdown at all** —
its caption ("FPS:", width-matched to the dropdown the same way "Quality
(CRF): NN" is matched to the slider) moved up into its own row, sharing a
row with `crf_label` instead of sitting directly above the dropdown. That
leaves `slider_row` and the bare `fps_menu` as direct, un-wrapped siblings
in the controls row below — literally the same two widgets, added the same
way, as before FPS had a caption at all, so their alignment is pixel-for-
pixel identical to that (confirmed: both at `y=0, height=28`). The caption
row costs real height (was 0 extra before FPS existed, ~26px now,
comfortably under budget since the slider row alone was never the tall
one), but it's a normal cost paid once, not a per-iteration fight. The
throughline across every iteration: on either tab, a new Video/Audio
control is never free height *or* free width just because there's a blank
stretch nearby, "the row's height is set by its tallest column" cuts both
ways (a control sharing a column with something already at the ceiling
costs real height; a control sharing a row with something that has spare
width costs none *until* it grows a caption of its own), and when two
controls need to align against *each other* rather than against a shared
container, the reliable way is to make them literal siblings in the same
layout call — not stack one inside a wrapper and hope `AlignVCenter`
reads the intent, since Qt centres against the wrapper's full bounds, not
whichever part of it visually matters. Always re-measure against that
tab's own Overview page (height) and the actual remaining gap (width)
before trusting a layout "looks about right."

**Encoding / Audio** (multi-stream): `Audio Track` + `Choose Stream(s)` +
`Passthru` on row one; `Audio Codec` / `Bitrate` / `Channels` / `Sample Rate`
on row two, each dropdown sized to its longest *possible* entry
(`Dropdown.width_for`); `Strip Audio` on the right. The row edits whichever
included stream Track shows. **The audio streams are a list of entries, not probe
indices**: `_audio_list` (every stream on offer, in the popup's order, which is the
output's), `_audio_included` (the ids that go into the output), `_active_audio_id`, and
`_audio_stream_settings[id]`; an entry is `{"id": "src:N" | "ext:xxxxxxxx", "source":
"primary" | "external", "file", "index", "stream", "name"}` — Muxing's shape. The Audio Track
dropdown lists the included ones as `Track N (codec)`, **N being the stream's place in the
Choose Stream(s) list** (`_audio_track_ids` maps a label back to its id).
`_save_active_audio_stream` banks the controls into `_audio_stream_settings[id]` before a
track switch or a gather, so switching never loses an edit; `_load_active_audio_stream` writes
one back in (muted). `_auto_select_audio_streams` re-seeds the *source's* streams once per
file (guarded by path, so a re-delivered probe can't discard edits; streams added from other
files stay, with their settings and whether they were included, as in Muxing): each
defaults to its own codec/params where offered (`_default_audio_settings`), DTS / Dolby TrueHD
are named and forced to Passthru, and every stream is included (each starts as a plain
copy, so a stream whose codec the container can't carry — left on `Select` — blocks the
job until it is given a codec or unticked). **Choose Stream(s)**
(`_open_stream_picker`) opens the popup below on `_audio_list`; on OK the result replaces the
list, prunes settings of removed streams and keeps the active track an included one
(`_reactivate_audio_stream`). **Passthru**
makes the stream a copy, so Bitrate / Channels / Sample Rate mirror the
source's real values as display overrides (`_apply_passthru_values`) and
disable.

**HDR→SDR preview** (Encoding only): `on_thumbnails` records the raw frames and
`_apply_preview_frames` shows the app's tone-mapped set instead whenever the
switch is on and a render for this file is cached — keeping the scrub index
across the swap. Turning it on for an unrendered file starts
`app.media.start_hdr_render`.

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
4. **Audio codec → bitrate**: `Select` has no bitrate (the dropdown reads `—`);
   the lossless codecs (`formats.LOSSLESS_AUDIO`: FLAC / ALAC / PCM) have none either
   and **say `Lossless`** (`formats.LOSSLESS`) instead — still disabled, and only for a
   *resolved* lossless codec, never for an unresolved `Select`. `Lossless` is a display
   placeholder like `—`: `_menu_value` reports it as `""`, so a job never carries the
   text, and the rundown leaves the bitrate out for a lossless codec (the codec name
   already says it; a probed "768 kbps" would only mislead). Passthru mirrors the
   source instead — and mirrors `Lossless` for a lossless source stream, which is
   the probe's per-stream `lossless` flag (`formats.probed_audio_is_lossless`, from
   ffprobe's codec name *and* profile), not just `LOSSLESS_AUDIO`: it also covers
   **Dolby TrueHD** (always lossless, and reports no bitrate at all — it used to fall
   through to `Select`) and **DTS-HD MA** (`profile` "DTS-HD MA"; a DTS core or
   DTS-HD HRA is lossy and keeps its real bitrate). The rundown drops the bitrate
   for those too.
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
   1080p · 30fps · SDR` (the Resolution/FPS segments only appear once a real
   downscale/retime's picked — omitted entirely at `Source`), the first
   included audio stream (`+ N more`, spaced), and the trim; problems in STOP_RED
   (`— removed —`, `— no video stream —`, `— pick an encoder —`,
   `— pick a codec —`, `— no streams selected —`).

`_retarget(menu, values, what)` points a derived dropdown at a new list and,
when the pick had to snap, **toasts why** ("Encoder switched to VP9 — .webm
can't carry H.265"). Silently swapping a codec out from under the user is
what makes an options screen feel haunted. `self._ready` mutes those toasts
while a settings dict is being written in. `_retarget_resolution`/
`_retarget_fps` are the same idea for Resolution/FPS's own source-capped
lists, with their own wording ("this file is only 720p tall"/"...29.97fps")
— all three guard their toast on `before != NO_OPTION` (below), not just
`before != after`, since a dropdown that read `NO_OPTION` a moment ago was
showing the no-file placeholder, not a real prior pick.

**No file imported → every Overview/Video/Audio dropdown reads `—`,
centred (unlike a real value, which stays left-aligned — `Dropdown.
paintEvent`'s own `NO_OPTION` check) — and disables**, run last in every
`_sync_controls` via `MediaTab._apply_import_gate(extra=...)`: Output
Format and Preset (and, unconditionally both ways like those two, the Start Time/Clip
Duration spinners, A/V Sync, the preset Save/Delete buttons and the Queue Task /
Mux / Encode action buttons), plus whatever tab-specific dropdowns the subclass names
(Encoding: Encoder, Profile, Level, Encoder Preset, Resolution, FPS —
see "Tabs" below — Audio Track, Audio Codec, Bitrate, Channels, Sample
Rate). The override itself is `menu.set(NO_OPTION)` (a display override,
not a real values-list change). Encoding also disables its non-dropdown controls
with no file — the quality slider and its captions, both Strip checkboxes,
Choose Stream(s) and Passthru — in a block right after the gate call
(`EncodingTab._sync_controls`), no-file side only since each one's enabled
state is recomputed fresh earlier in the same pass.

**Output Format/Preset need their enabled state set *unconditionally, both
ways* — every `extra` dropdown does not.** Each `extra` dropdown's enabled
state is already recomputed fresh, every `_sync_controls` pass, by the rest
of that tab's own logic regardless of file presence (`set_enabled(...,
video_live)` and friends) — the gate only ever needs to *additionally*
disable+blank them on the no-file side, since the moment a file lands, that
earlier real logic already re-enables and re-derives them correctly on its
own. Output Format and Preset have no such per-pass logic anywhere else —
first shipped only disabling them on the no-file side (mirroring `extra`'s
own pattern) shipped a real bug: with a file imported, `_apply_import_gate`
correctly no-opped and never blanked their *value*, but nothing had ever
re-*enabled* them either, so once a no-file pass had disabled them they
stayed disabled forever, showing a real container value (`.mp4`) greyed
out as if it weren't legitimate. Fixed by having the gate set
`set_enabled(self.format_menu, ..., has_file)` (and Preset's) unconditionally
on every call, both directions, before checking whether to also blank their
values. **The same gate must also un-blank Preset on import**: its option list never
changes afterwards, so nothing else clears the `—` the no-file pass left in it, and an
enabled Preset dropdown read `—` (`presets.NONE_LABEL`, `— none —`, is "no preset
applied"). Output Format is un-blanked by `on_media_info` setting the source's container.
The Downloader's equivalent lives in its own `_sync_controls`
(nothing fetched → every dropdown blanked the same way) rather than sharing
this helper, since it isn't a `MediaTab`
subclass.

Muxing's rules: the same stream-presence rule; the track boxes carrying the
source's own streams plus any browsed-in external ones (see "Muxing / Video"
above for the reset-on-file-change/diff-otherwise logic); **the container
inversion** — the source's own codecs decide which containers are reachable
(`formats.containers_for`), with a toast when the pick snaps and the save
path's extension following it; a stripped or absent stream disables its
panel — and so does an **emptied** one (the user removed every track of a kind the source
has; only once the probe says `has_video`/`has_audio` is `True`, since the lists are empty
before it lands): the sub-tab goes red, the carousel shows the Wave Loop (video) / mute
badge (audio) exactly as for Strip, the box, Select/Deselect All and Remove grey out and
the rundown reads `— removed —`. `Add Stream(s)` and Undo/Redo stay live on an emptied
panel — they are the ways back, and disabling them as Strip does would strand it — and the
*other* kind's Strip checkbox is disabled (an output can't drop both); a job left with no
track to map anywhere is refused by `_validate_specific`. The rundown (`copy · H.264 · 1 track` — the codec is the first *checked* track's, not
the source's first stream — or `· 2 tracks` once more than
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
- `_process_next` derives the job's `JobVars` and compiles the argv **on the GUI
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
- When a batch ends, "All queued jobs finished." is toasted and Settings'
  "When Done" action runs (see "Tabs → Settings").

**Row info, sort, search (revamp).** A row reads thumbnail | title | length | resolution | HDR/SDR | audio codec + channels (`AAC 2.0`) | status | ✕ (11px, status shown without its trailing dots).
`QueueTab._row_meta` works the last three out at add time from the settings *as they will leave the file*
(length = the trim applied to the probed duration, so 1h minus 15s from the start reads 00:59:45; resolution =
the Encoding downscale pick if it is below the source, else the source height; audio = Encoding's first stream
codec / Muxing's first track's), from `app.media.info` (which is still the task's file when `add_task` runs) or,
for a download, `ytdlp_cache` + the settings; `—` where there is none. Column widths are measured from the widest
value each can hold (`_measure_columns`), so only the title can be cut: it scrolls (the queue's shared
`MarqueeGroup`) past 25 characters or when it overflows its box. Callers now pass just the title as `description`.
Each row records `"added"` (time.time()). **Sort By:** is a `SortDropdown` (face `Sort By: | A to Z`, the open list shows only options; A to Z default / Z to A / Recent = newest added first / Latest = oldest added first) in the middle of the bottom row, and `_apply_sort` reorders `_rows` (so run order follows), the layout and the active job's `rest` — on every pick and every add. Beside it the round `SearchToggle` opens `SearchBar`, which floats over the bottom of the list just above the buttons (placed by `QueueTab._place_search`, not in the layout, so a long queue runs on beneath it and no band cuts the rows off): it only ever grows horizontally from the middle out to both sides (and back in), takes no room at all, filters rows by title as you type and clears when closed; the X inside the box (secondary colour) only clears the text. To the right of Start Queue, `WhenDoneButton` (a small square `Dropdown` filled like Start Queue, 3px from it, with a triangle; its list is wider than the button, always opens to its left, with the current choice highlighted) sets Settings' `app.when_done`, kept in step both ways (`Queue.on_enter` / `Settings.on_enter`). The details panel is a `SlideHost`: it floats over the bottom of the list (placed by `QueueTab._place_search`, not in the layout — the list keeps its full height and runs on beneath it, nothing behind the panel but the panel), rises once, and picking another row while it is open only swaps the contents. Opening the search row with the panel open shortens the panel from the bottom (`SlideHost.set_inset`; its list `_DetailScroll` prefers 140px but gives way to 40) while its top edge stays put. The tab layout has no spacing of its own (spacers and the `GAP`), so nothing pops when the search row appears. It omits Start Time when the trim is the whole file, and Duration is
always the output length. The sort/search SVGs need the "ink" mode's `#231f20` recolour; the A/Z letters were
converted from `<text>` to outlines (Oswald) since live text rendered with colour fringes.

**Details popup** (below the list, fixed 140px scroll area so a long Encode
list scrolls): `_DETAIL_FIELDS` drives which settings keys show and how
(`time`, `bool`); a key absent from a task's dict is skipped, which is how each
task kind shows only its own. A stripped stream's codec/track rows are hidden
(`Strip Video: Yes` stays). `resolution`/`fps` are among `_DETAIL_FIELDS`'
rows, hidden under `strip_video` the same way `quality`/`profile`/`level`/
`speed` already are (Encoding's downscale/retime picks). **`quality` itself means two
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

**"No tasks queued yet." is its own `QStackedLayout` page, not a widget
sharing the row list's own layout.** It needs to sit dead-centre in the
panel while genuinely empty; a first attempt put it directly in
`list_layout` alongside real rows with a stretch on each side to centre
it, but a `QLayout` stretch item isn't tied to any one widget's visibility
— it stays live even after real rows arrive and the label itself is
hidden, which pushed the populated list down/off-centre instead of letting
it anchor to the top and scroll normally. `self._list_stack` holds two
pages — `self.scroll` (the real row list) and a small wrapper centring
`self.empty_label` between two stretches of its own — and
`add_task`/`remove_task` switch between them explicitly
(`setCurrentWidget`) rather than toggling the label's own visibility,
which never touches `list_layout`'s own stretch (just a single trailing
one, for new rows to insert before) at all.

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
fetch succeeds — every dropdown among them (`Video Codec`/`Audio Codec`/
`Resolution`/`Video Format`) also reads `—` until then, same "nothing
imported" convention `MediaTab._apply_import_gate` uses on Muxing/Encoding,
just inlined in `_sync_controls`'s own `if not has_info:` branch rather than
a shared helper (`DownloaderTab` isn't a `MediaTab`). **"Resolution" is only
the on-screen label** — internally
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

**Five sub-tabs** (the same `SubTabBar` Muxing/Encoding use, over a
`QStackedWidget` where **each page has its own `QScrollArea`** so a revealed row can never clip):
**Appearance** (Theme, Appearance Mode, Window Mode + its Borderless-only
Fullscreen checkbox), **Output** (Default Save Location +
disk space, Separate Save for Downloader, File Naming), **Performance**
(Hardware Acceleration, Priority Level, When Done, Startup Tab, and a **LlamaLog:** section at the
bottom), **Shortcuts** (one row per `core.keybinds` action: its name on the left, a `KeyField` in
the middle — click it, press the new key, it shows "Press a key…" while listening and clicking away
leaves it unchanged; every key is takeable, Esc and Tab included — and an on/off `Switch` on the right,
which dims the row; a **Reset Shortcuts** button under the list; see "Keybinds" above), **About** (the
version — `VERSION` in `ui/widgets/panels.py` —, then a **`GitHub:`** and an **`Issue Tracker:`** row (each
`SettingsTab._about_link_row`: a bold `field_label` caption beside the *actual URL text* — `core.about.REPO_URL`
/ `ISSUES_URL` — as a `ClickableLabel` styled as a real hyperlink: underlined, coloured in the theme's
`secondary`, `T.theme.changed` reconnected so it restyles live on a theme switch, `PointingHandCursor`,
`clicked` opens it in the default browser; by request, over naming these two as buttons — a URL you can
actually read beats one only a tooltip names), and under a plain `License:` caption (naming
the type isn't needed — the notice right under it already says GPL v3) GNU's **short, selectable notice**
(`about.NOTICE`: the standard "This program is free software…" text from the GPLv3's "How to Apply" section,
with the copyright line filled in), **in a secondary-bordered box** (`BorderedFrame`, the same widget as
Muxing's `TrackListBox`, its margins a little tighter — `9, 5, 5, 5` against `TrackListBox`'s own `9, 7, 5,
7` — see the fit note below for why; sized to its content, no scrolling, since the notice is always this
same short, fixed text), and two buttons below the box, **each sized to its own text, not to the wider of
the two** (`button_width_for(["View License"])` / `(["Third-party Licenses"])` separately, not one shared
`button_width_for` call over both — a narrow "View License" doesn't need to match its neighbour's width):
**View License**, which opens the full text, `LICENSE.txt` (`about.license_path()`: beside a frozen app's
exe, else the repo root), in the default text editor, and **Third-party Licenses**, which opens the
`licenses/` folder (`about.licenses_dir()`, same lookup); each shows a message if its target is missing.
This is the "about box" the GPL itself describes,
and it covers GPLv3 §5(d)'s Appropriate Legal Notices (copyright, no warranty, the right to redistribute,
how to view the license). **The full text lives in files, not in the app**, and the file is `LICENSE.txt`
rather than `LICENSE` so Windows opens it in the default text editor instead of asking which program to use.
The installer must copy `LICENSE.txt` and `licenses/` next to the app. An earlier version showed the whole
license in a scrollable box (a `TextView` widget and a paragraph-reflow helper, both removed); the notice
replaced it. **Trailing under all of it, uncaptioned**: one `role="hint"` line combining
`about.LOGO_COPYRIGHT_NOTICE` ("The LlamaMXD logo (Pak the Llama) is Copyright © 2026 Yezan Smadi, all
rights reserved") and `about.TRADEMARK_NOTICE` ("LlamaMXD™ and Pak the Llama™ are unregistered
trademarks of Yezan Smadi") — two separate legal facts (copyright protects the artwork, trademark
protects the names) in one fine-print sentence pair, Pak the Llama being `about.MASCOT_NAME`, the llama
pictured in `LlamaMXD-Logo.svg`. The trademark claim is made by use, not registration, hence "™" and not
the registered-mark "®"; both are separate from the GPL notice above, the same way the logo's own
copyright in `licenses/README.txt` is kept out of the GPL grant. By request, no `Trademark:` caption of
its own (it first shipped as a fourth captioned row alongside GitHub/Issue Tracker/License, moved here
after) — reads as fine print under the license rather than another thing to label.

**The notice is a stock `QLabel`, not `ScaledLabel`** — same reasoning and the same
`Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard` + I-beam cursor as `MessageDialog`'s message (see
"Dialogs" below), verified the same way (a real Ctrl+A/Ctrl+C round-trip through the clipboard). Unlike a
dialog, though, this label lives on the *persistent* main window, where a live rescale is a real, common
case (this app frequently launches below 1.0x — see "starts at 35% of the screen's width" — not just during
a drag), so it needs its font kept correctly scaled after the fact, not just once at build time. **`set_font_px`
does not do this — confirmed with a throwaway repro, not just CLAUDE.md's own existing warning that it "does
nothing on a label": right after `set_font_px(label, 12)` the font reads 12px, and after the very next
`ensurePolished()` — which real widgets get the moment they're actually shown — it's back to whatever the
base `QWidget { font-size: font_px(13)px }` stylesheet rule says, because that rule's `.setFont()` call from
Qt's own style engine runs *after* and unconditionally overwrites a plain `.setFont()` call. What actually
survives a later restyle is an *instance*-level stylesheet override (the same trick the system-info label
above already uses successfully, just static there since it's a `ScaledLabel` reinterpreting an unchanging
number) — so the notice's font is `scale.bind(notice, lambda: notice.setStyleSheet(f"font-size:
{scale.font_px(12)}px;"), "font-size")`, re-applied on every scale change like any other bound setter.
Verified live: 12px at 1.0x, 18px at 1.5x, still 18px after switching away to another sub-tab and back, back
to 12px on returning to 1.0x.**

**Every sub-page has its own `QScrollArea` — the five pages do *not* share one.** They used to: one shared
`QScrollArea` wrapped the whole `QStackedWidget`, and a `QStackedWidget`'s `QStackedLayout` sizes the widget
to its *tallest ever-shown* child at the C++ layout-activation level — a layer overriding `sizeHint()`/
`minimumSizeHint()` in a Python subclass can't reach (confirmed directly: even calling
`widget.resize(widget.sizeHint())` right after switching pages snapped straight back to the tallest page's
height). Measured before the fix: `self.pages.height()` was a constant 505 (Shortcuts' own height) on
*every* sub-page, so Appearance, at 244, scrolled inside a box it never needed — About did too, even once
its own content fit. Wrapping each page's own widget in its own `QScrollArea` and stacking *those* sidesteps
the whole class of problem: each scroll area only ever sizes off its own single child, so switching sub-tabs
now genuinely changes whether a scrollbar shows — Shortcuts (its many keybind rows, 505 tall) and
Performance (443, its own five sections) still get one; Appearance and Output (244 / 265) don't. **About
is right on the line and the exact call can't be trusted from a sandboxed measurement**: it briefly grew
to 430 when the trademark/copyright disclaimer (below) shipped as its own captioned `Trademark:` row
between Issue Tracker and License; moving it to an uncaptioned `hint`-role line trailing under the
License section (by request — no fourth thing to label) measured back at exactly 385/385, no scrollbar,
stable across a stress sequence of scale round-trips with every sub-tab revisited at each one — **but
that measurement used whatever font a headless `QT_QPA_PLATFORM=offscreen` process substitutes for
`role="hint"`'s CSS `font-family: Arial`, which isn't in `assets/fonts` and came back with an empty
`QFontInfo(...).family()` and no exact match in this sandbox** — i.e. a font nobody will actually see the
app render with. Swapping in Roboto (bundled, so genuinely available here) for the same text at the same
644px width wrapped to 2 lines instead of 1, ~10px taller — which would put the real, Arial-rendered page
over 385 more likely than not. **Confirm in the real app before trusting this fits**: if the About page
shows a scrollbar, the disclaimer text or a spacer above it needs trimming, the same kind of pass this
section originally took. Nothing else on this page has slack left either way — treat 385 as the ceiling.
**Getting About genuinely under its 385-tall viewport, not just close, mattered [historical — the margin
this established was spent by the trademark/copyright line above, and its exact current fit is unverified
for the reason just given]**: at 393 (its size before
the margin trim above) it was only 8px over, and right at that margin Qt's own scrollbar-visibility check
turned out to be racy — the identical content height and viewport measurement showed no scrollbar the first
time a resize-then-switch sequence was run, then *did* show one after a further 1.0x→1.5x→1.0x round-trip
with other sub-tabs visited in between (reproduced 3 times in a row before the trim; 0 times in 18 further
measurements across a 1.0/1.5/1.0/2.0/0.8/1.0 stress cycle after it, repeated 3 times). Trimmed by tightening
two spacers (10→6) and the notice box's own margins (9,7,5,7→9,5,5,5) and the spacer after it (4→2), landing
it at 379/385 — a real 6px margin, not a coin flip. **Re-run that stress sequence (several scale round-trips,
switching through every sub-tab at each one, watching each page's own `verticalScrollBar().isVisible()`) after
touching any spacer on a page that's meant to fit — a single "fits" measurement at one scale, once, is not
enough to trust near this edge.** On a relicense change `about.COPYRIGHT` and `NOTICE`
together. Nothing on the page is a setting. **The About page ends in
`addStretch(1)`**: now that this page has its own scroll area sized off nothing but its own content, this
just keeps the content hugging the top rather than being spread out once the scroll area stretches the page
to fill whatever room it's given. The header row (five tabs + the 230px system info)
has 8 reference px to spare, so a sixth tab or a wider info block would squeeze it
(`layout().totalMinimumSize()` against the row's width). Reset to Default / Save are
pinned below the pages (outside the stack entirely) and act on *every* setting, whichever page is showing.
Side padding is 10px (`_SIDE_PAD`) and the tab bar's top padding 5px
(`_TOP_PAD`), both matching Muxing/Encoding's, so the tab bar sits in the same
place on every tab. Option names use the stock 12px `field` caption role (the same size as
Muxing/Encoding's), not `field11`; the system info is 12px too.

**System info** (read-only, top-right corner of the title row, no "System:"
label): the CPU's marketing name, the detected GPU's display name, and total
RAM (`core.system_info`, `core.gpu.display_name()`), right-aligned and word-
wrapped in a fixed-width label — deliberately *not* a row in the main
column, since a bare CPU name can run past 30 characters and sizing to its
own content could grow wider than the tab frame on a smaller screen or a DPI
change from dragging the window to another monitor. It shares its row with
the sub-tab bar (tabs left, info right, top-aligned). **Theme** (`Dropdown` over
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
a leap of faith about what it does. **Only a dedicated GPU counts**
(`gpu.has_dedicated()`; `gpu.is_dedicated(name)` classifies by adapter name —
any NVIDIA, AMD RX/PRO/VII/FirePro/R9-class, Intel Arc A/B-series; AMD
"Radeon Graphics"/780M-style and Intel UHD/Iris/"Arc Graphics" iGPUs don't):
with none, the switch is forced off and greyed out along with its caption, and
the status line says none was found. `app.gpu_preference` (what the user chose,
what gets saved — never overwritten by a forced-off run, so a GPU added later
picks it back up) is kept apart from `app.gpu_enabled` (what jobs use). **Separate Save for Downloader**
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
resets theme, appearance mode, window mode (back to Fixed, Fullscreen off),
default save location, the Downloader's
separate-save toggle and location, GPU acceleration, file naming, priority
level, When Done, Startup Tab, log detail and the keyboard shortcuts all back to their defaults in one action, then autosaves — the one Settings control that
touches every persisted key at once rather than just its own. **File
Naming** (an entry under the output paths, with the token list beneath it
turning into a STOP_RED reason while what's typed is invalid — unknown
`{token}`, illegal file-name characters, empty; nothing is applied until
Enter/focus-out, and never while invalid) holds `app.naming_template`.
**Priority Level** (High / Above Normal / Normal / Below Normal / Low,
default Normal) is applied to every ffmpeg / yt-dlp job at launch
(`creationflags`) and immediately to a running one (`job.set_priority` via
`QueueTab.apply_priority`). Realtime is deliberately not offered. **Below Normal and
Low also lower the job's disk I/O and memory priority** (`priority.io_memory_for`: I/O low / very low
via `NtSetInformationProcess` class 33, which has no documented API; memory 4 / 2 of 5 via
`SetProcessInformation`), set right after launch (`ProcessJob._launch`, since the creation flag only
carries the CPU class) and on every change; Normal and up put both back to normal. Measured with two
unbuffered readers on one hard disk: the other reader got 70MB/s beside a job at normal I/O priority
and 174MB/s (185 alone) beside one at low. The HDR preview render keeps its fixed Below Normal CPU
class on purpose: under a High job it yields, under a Low one it outranks the job, which is right for
work the user is looking at. yt-dlp's
whole process tree is set, and re-set about once a second in `poll_events`
while the level isn't Normal, since a child only inherits a Low/Below Normal
parent's class (its ffmpeg merge would otherwise run at Normal under a High
yt-dlp); a Job Object priority limit was tried and refused because Windows
rejects High there without a privilege a normal user lacks. **When Done**
(Do Nothing / Shutdown / Sleep / Hibernate / Lock System / Log Off / Quit
LlamaMXD) runs when the queue empties — `QueueTab._process_next`'s "All
queued jobs finished." branch posts `_run_when_done`, which waits out any
open failure dialog and drops out if more work was queued meanwhile, then
`app.perform_when_done` gives Shutdown / Sleep / Hibernate / Log Off a
30-second cancellable countdown (`dialogs.confirm_countdown`) before
`core.power.perform`; Lock and Quit act at once. It runs after every batch,
not just once. Its checkbox ("Reset to 'Do Nothing' when the app is
relaunched", on by default) makes `MainWindow` start on Do Nothing whatever
was saved. **Startup Tab** (Muxing / Encoding / Downloader / Queue — never
Settings; `core/startup_tab.py`, default **Encoding**, held on
`app.startup_tab`) is which tab `MainWindow` opens on: `current_tab` starts as
it. Picking one only changes the *next* launch — the running session stays
where it is. **LlamaLog:** (last section of Performance, a caption over a row of two controls)
is the log detail dropdown (**Normal** / **Detailed**, `llamalog.LEVELS`, held on
`app.log_detail`, saved as `log_detail`; applied to the log at once and to jobs started
afterwards) and an **Open Log Folder** button (`llamalog.open_log_folder`, an error dialog if there
is no folder). Reset to Default puts the detail back to Normal. See "Logging" above. **Save**
persists and toasts "Settings saved." (no jump to the Queue). Settings also
autosave when the tab is left and on close.

### Widgets (`ui/widgets/`)

- **Dropdown** (`QComboBox` subclass, self-painted): opens straight down 3px
  below the button — or straight up, 3px above it, when the list would run off
  the screen's available area and there's more room above (a tall list near the
  bottom, most obviously in fullscreen) — unrolling + fading in from the button's
  edge by animating a *mask* on the popup (no per-frame resize). `picked(str)` fires on a user pick only;
  `hovered(str)` reports row hover; `popupClosed` fires only for a popup that
  was genuinely open (Qt also calls `hidePopup` on style changes). `set(value)`
  shows a value even when it isn't in the list (a display override) — always
  read with `value()`, never `currentText()`. `set_values(values)` no-ops when
  unchanged *and no override is showing*, keeps a still-legal pick, else snaps to the
  first (**an override is not a legal pick**: it used to survive an unchanged list, so
  Resolution kept its no-file `—` after a 2160p+ source was imported — its list only
  changes for shorter sources — and FPS did the same at 120fps+); an empty list
  shows `—` (`NO_OPTION`, an em dash — long enough to read as a deliberate
  placeholder glyph rather than a stray hyphen; centred in the box rather
  than left-aligned like real text, see `paintEvent` below).
  `Dropdown.width_for(values)` sizes one to its longest entry.
- **CheckBox** — 24px box, `color_key` `secondary` or `stop`; fill fades
  (120ms); disabled greys the box too. **Switch** — the knob slides (160ms).
  **SegmentedButton** — the selection pill slides (180ms); `set` is silent.
  **ClickableLabel** — a `ScaledLabel` with a `clicked` signal (only while
  enabled); Encoding's `HDRtoSDR` caption is one, so clicking the text
  toggles the switch beside it, not just the switch itself.
- **TimeSpinner** — a self-painted HH:MM:SS field (`_TimeField`) plus stacked
  ▲/▼ `IconButton`s with an accelerating auto-repeat (400ms → 30ms, ×0.85).
  State is a 6-digit list and `cursor_pos` (0–5) indexes it: typing overwrites
  and advances, Backspace steps back then clears, Delete clears in place,
  Left/Right/Home/End move, minutes/seconds clamp to 59, a click lands on the
  nearest digit, and a block cursor shows while focused. `valueChanged` fires
  on **every** change, typing and `set_seconds` included. **`mute_when_zero`** paints the
  digits in the disabled-text grey while every digit is 0 and in the normal colour the moment
  it is spun, typed into or set off 0 (and grey again if it is brought back to 0) — both
  trim spinners opt in: **Clip Duration** (00:00:00 means "to the end of the file") and
  **Start Time** (00:00:00 means "from the beginning"), so neither reads as a real value until
  the user has touched it. Start Time used to be left normal on purpose; it now matches.
  Muxing and Encoding get it together, since both build the spinners in `MediaTab`.
- **MarqueeLabel** — scrolls sub-pixel and time-based (40px/s, 1.5s hold per
  loop) only when the text overflows, and only while shown.
  **MarqueeGroup** — one shared clock *and timer* several `MarqueeLabel`s can
  join (e.g. `SummaryPanel`'s Video/Audio/Length rows, a track box's rows) so
  they all sweep and restart in step, rather than the shortest one finishing and
  holding while a longer one keeps drifting out of sync with it. Labels paint from
  the group's per-tick clock snapshot, not the clock (see "Muxing / Video" above).
- **Tooltips** (`ui/widgets/tooltip.py`) — `tip(widget, text)` attaches a
  shared, themed hover tooltip (`_Tooltip`, fade-in only) to any widget via
  a single app-wide `_TooltipManager` event filter. **A tip shows only once the cursor has hovered AND stopped** for
  `TIP_DELAY_MS` (400ms) — any move restarts the wait, so tips never pop up under a moving mouse. Stillness is
  judged by sampling `QCursor.pos()` every 30ms while a tip is pending (`_arm` / `_tick`; a drift of ≤1px counts as
  still), not from mouse-move events, which a registered container widget (the track box) never receives for its
  children and which need mouse tracking anyway. Once shown, moving within the widget doesn't hide it; leaving,
  clicking or disabling does. The carousel's own info-badge tip is **deliberately not** on this rule — it shows the moment the cursor
  is over the badge, as it always did (a delay was tried and reverted by request);
  works even on a disabled widget (exactly where an explanation is often
  most needed) and syncs the cursor to a plain arrow while disabled, since
  the widget's own hover cursor wouldn't otherwise reflect that it can't be
  interacted with. `hold_tips(bool)` suspends every tooltip (hiding the shown one) until
  released — used for the length of a track drag. Distinct from the carousel's own `_InfoTooltip` above,
  which shows structured probe data rather than a line of static copy.
  `ui/tips.py` holds the shared copy this app's dropdowns tip themselves
  with — `VIDEO_CODEC_TIPS`/`AUDIO_CODEC_TIPS`/`CONTAINER_TIPS`/
  `AUDIO_FORMAT_TIPS` (per-value explanations) plus the `SELECT_*_TIP`/
  `BEST_*_TIP` placeholders shown before a real value's picked — used across
  Encoding, Muxing, Downloader and Settings.
- **IconButton** — a stylesheet button whose ✕ / ▲ / ▼ is painted, so it
  never depends on a font having the glyph (`draw_cross` does the same for
  painted widgets); also the SVG icons (select / deselect / undo / redo, recoloured
  to the button's text colour). `role="compact"` is the 22px-tall variant.
- **SubTabBar** — active tab primary at 30px, inactive secondary at 24px (through
  the palette's `subtab_active` / `subtab_inactive`, which a theme with
  `swap_subtabs` — Terminal — reverses),
  bottom-aligned, standing on a 4px square-ended line (`_LINE_H`, in the selected tab's
  colour — `subtab_active`) that runs the
  whole bar's width — the tabs are drawn a corner-radius taller and clipped so
  their feet sit flat on it (the bar is 34px tall in total); height and colour ease (170ms) including hover;
  `set_marked(name, bool)` cross-fades a tab to STOP_RED. **The tabs' feet and
  the line's top edge (`foot` in `paintEvent`) are snapped to a whole device
  pixel** — at a scale where 30 reference px lands mid-pixel (0.7, 0.85, 1.05,
  1.2, ... — never at 1.0, 1.5, 2.0 or 2.667), the tab clip and the line's own
  antialiased edge each covered part of the same row and the window colour
  showed through as a thin seam under the selected tab. Confirmed by pixel
  colours (a row of exactly 60% primary over the frame grey); after the fix the
  worst deviation across 241 scales from 0.6 to 3.0 is 2/765.
- **DropBox** — secondary rounded border; drop / double-click / Browse (which, like
  the file label's and carousel's reselect dialog, and both **Add Stream(s)** buttons —
  Muxing's and Encoding's Choose Stream(s) popup, which is handed the folder as
  `start_dir` — opens in the tab's current
  output folder — `MediaTab._output_directory` — not the app's working folder);
  lights up
  on drag-over; `collapse()` — once a file is chosen — drops the border, prompt *and* Browse
  and shows the **`LoadingSpinner`** (below) in their place, until the carousel takes over,
  `reset()` is the reverse — back to its pristine pre-import state, used
  when a picked file turns out to be unreadable (`app.media._reject_file`, see
  "File selection is a broadcast" above) rather than leaving the box
  stranded mid-import. `show_no_preview()` is the third state: the border
  and Browse with "No Preview Available" in place of the prompt, for a file that
  is selected but has no preview frames (both it and `reset()` stop the spinner and
  bring Browse back).
  **LoadingSpinner** (`panels.py`) — `assets/LlamaDiscLoading/000.png`…`142.png`: a spinning CD-R
  (label side "PAK-RW"/"LlamaDisc" plus a llama head, flipping to a rainbow holographic underside),
  a 143-frame, 60fps, **640px PNG sequence** (exported at 2000px from Expressive Animator and
  downscaled with Pillow LANCZOS; ~14MB on disk, 234MB decoded at 640px — so it is decoded at the size it is drawn, see below). Drawn in its own full colour —
  branded art (Pak the Llama, the wordmark), not a monochrome icon. It replaced a Lottie version
  (`LlamaDisc-Loading.json`) that rlottie couldn't render correctly (no blend-mode support, a
  precomp size bug, missing keyframe end values), which had grown a keyframe rewriter, a precomp
  fix and a 306MB baked rainbow sprite sheet; **none of that exists any more** — a raster
  sequence has no renderer to work around. rlottie is still used by the Wave Loop.
  `_request_frames` decodes the sequence on a `run_async` worker (`QImage`s cross threads, as
  everywhere) **at the size the spinner is drawn** (`_frame_side`: its width in device pixels
  rounded up to a multiple of 64, at most 640) — ~37MB at the default window size (256px) against
  234MB at 640. A spinner asks on its first size change (a one-off jump such as fullscreen starts at
  once), again when a drag settles (`set_side` -> a 100ms single-shot) and when shown, **only while
  its drop box is on screen** (a tab never shown has an unlaid-out 640x480 box, which once started a
  second, 512px decode), so the frames are ready before the first import. **A new size upgrades frame
  by frame** (`_request_frames`): frames are decoded in playing order from two past the one on
  screen, and each replaces its old-size frame the moment it's ready (`emit_progress`), so a spinner
  that grew is sharp at once rather than playing stretched frames until the whole set is done — the
  decode (~110 frames/s at 640) outruns playback (60). A newer size bumps a generation that cancels
  the frames not yet started; a frame of a superseded size is still kept when its slot is empty. It
  can't starve: each decode starts at the frame about to play and every finished frame stays until
  replaced — a size change every 150ms for 4s from a cold start (27 decodes, each cancelling the
  last) loaded 44 / 72 / 105 / 133 / 143 frames by each half second, with blanks only in the first
  60ms, before any frame existed. Each frame's scoring doesn't depend on the size, so it's kept after the
  first decode (`_LOADING["scores"]`, 5MB with compact types) and a re-decode only resizes. Measured
  growing a spinner from 256 to 640px: stretched frames shown 94 (1.55s) -> 2 (0.03s), the whole set
  1.55s -> 0.9s; frames byte-identical to the previous code at 256 / 384 / 640, cold and cached; a
  live drag up and back ends on one size with every frame present, at about the same total CPU.
  Until a frame arrives, or if the frames cannot be loaded, it draws nothing (there is no fallback ring). Plays only while
  shown (`showEvent`/`hideEvent`, one single-shot timer re-armed for each frame's due time) and is
  transparent to the mouse.
  **Two things on the label side are themed**, both recoloured at paint time: the pink divider
  stripe and outer rim (to the theme's `primary`), and the hub's inner edge — the label's
  translucent hub overlay (`#FAD39B` at 50% alpha) lying over that same pink, so its colour is
  `0.5 × overlay + 0.5 × pink` = (236.5,154,159.5) ≈ `#ED9A9F`. Themed, it must be the overlay
  laid over the *theme's* colour: `_ring_colour(base) = α·overlay + (1−α)·base` with α = 0.5, so
  a pixel of the ring moves by `_ring_colour(theme) − _ring_colour(pink)` (= half the stripe's
  move). Colours are as rendered into the PNGs (pink 223,97,164 — not exactly `#DA65A4`).
  At load `_stroke_weights` scores every pixel (`_share`): a pixel is a blend of a stroke colour
  and whatever it is drawn against, so its share of the stroke is where it falls on the RGB line
  between the two, provided it is within `_TOLERANCE` (16) of that line, which keeps the rainbow's
  own pinks out. Backgrounds per stroke (`_STROKES`): the stripe/rim against the label orange
  *and the hub collar* (the collar was missing at first, and left a thin pink line where the
  stripe meets the hub — its edge pixels are pink-to-collar blends), the ring against the collar
  and the overlay. A pixel goes to the stroke it matches best. Scoring runs on each frame's
  distinct colours (`np.unique`), and only for pixels inside `_candidate_box()` — the RGB bounds of
  every blend line out to where it leaves the colour cube, widened by the tolerance, derived from the
  constants so it can't drift — which rules out ~75% of pixels with no change to the result. Frames
  decode on up to half the CPUs (at most 3), leaving the rest to the window being built. Load at the
  default size 4.9s -> 0.9s (640px: 6.1s -> 1.3s), every frame's image and themed data byte-identical.
  A frame with fewer than 100 strong stripe pixels (the whole rainbow side, and the edge-on
  frames 36-39 / 108) has nothing themed — anything that matched there is a look-alike.
  **Weights are scored at the full 640px and shrunk with the image** (`cv2.INTER_AREA`, in
  premultiplied space): recolouring is linear, so the small frame equals recolouring at 640 and then
  scaling down (measured: within 1/255 on every frame, 4 themes, 256/384/640). Scoring the
  already-shrunk frame instead left a pink fringe on the thin rim, whose pixels blend three colours.
  Stored per frame: the premultiplied image and, for its themed pixels only, their indices, per-stroke
  deltas and original colours; `_recolor` copies the frame and shifts them by `deltas @ moves` (clipped
  to the pixel's alpha) — done every paint, so a theme switch needs no cache invalidation. Checked on Lemon, Vaporwave, black and green themes; on the
  narrow squashed frames a faint dotted fringe can remain on the ring's edge.

  **It fills the DropBox's own height, not a fixed reference size**: `DropBox._resize_spinner`
  (called from `resizeEvent` and `collapse()`) sizes it to `min(box height, box width) −
  2×scale.px(8)` (no border is drawn while collapsed — see `DropBox.paintEvent` — so there's
  nothing else in the frame to leave room for) and centres it — height, not width, since the
  box is normally landscape and a square animation sized to the wider dimension would run off
  the top/bottom. **It is a floating overlay — `LoadingSpinner(self)`, never added to `lay` —
  not a layout item**, the same pattern as the Wave Loop layer or the tab pipe: a
  layout-managed widget's `setFixedSize` becomes part of its *parent's* own
  `minimumSizeHint()`, so once the spinner had grown to fill a large box it permanently
  floored that box (and the window under it) from ever shrinking back below that size again —
  confirmed directly (shrinking the host after a collapse left the box pinned at the
  last-set spinner size, satisfied only by re-checking `box.width()/height()` after each
  resize rather than trusting a single measurement). Taking it out of the layout and
  positioning it with `move()`/`resize()` from `_resize_spinner` breaks that feedback loop
  entirely; `LoadingSpinner.set_side()` also switched from `setFixedSize` to a plain `resize()`
  for the same reason (`setFixedSize` pins a widget's size *policy* to Fixed, which only
  matters for a layout-managed widget, but there's no reason to leave it set here). Verified
  across a landscape box, a short one, and a portrait one (width becomes the constraint) that
  the spinner tracks each resize and the box itself shrinks and grows freely with no residual
  floor from a larger prior size.
  **BorderedFrame** is the border alone, `color_key` defaulting to `primary`
  (Muxing's `TrackListBox`, `ui/widgets/tracklist.py`, passes `secondary` for
  a visually distinct blue-on-Lemon box). **SummaryPanel** —
  `set_values([(text, color_key_or_None), …])`.
- **Sidebar** — title, logo, four nav buttons, a stretch, Settings, footer.
  The nav buttons are `NAV_BUTTON_WIDTH` 110px wide — narrower than the 200px
  sidebar, so the gap the cable runs through is wide enough to see its lead
  trail out from behind the button. The logo (`assets/LlamaMXD-Logo.svg`, now a
  hand-built vector — the earlier raster-in-SVG version is what `LlamaMXD-Logo2.svg`
  was, and nothing loads it) is rendered at 4x oversample and re-tinted to
  `primary_text` via `CompositionMode_SourceIn` (`Sidebar._load_logo`), so it goes
  white/black with the theme the same way the title text does.
  **TabIndicator** — one independently-animated `_TabPipe` per nav button, and the
  pipe is a real **RCA cable** graphic (`assets/RCA Cable Yellow.svg`, drawn in its
  own fixed colours — not theme-tinted), not a shape the code paints. The art is
  rendered once at 3x by `_cable_base_image` and **cropped to its drawn content**
  (the SVG's viewBox is ~3x wider than the plug, so an uncropped rotation squashed
  it into one end of its frame; the crop finds the non-transparent bounds with
  numpy), then `_cable_pixmap(height)` rotates it 90° clockwise — the plug's grey
  collar (top of the source art) lands on the *right*, facing the tab frame, and the
  trailing cable on the *left*, coming out from behind the button — and caches it
  per height (every button wants the same size), oversampled 4x and scaled down,
  never up. `extension` (0 = hidden, tip flush with the button's own edge; 1 =
  plugged in) slides the *whole* cable horizontally: at 1 the long thin grey pin
  (`_PIN_FRAC`, 142.23 of the art's 825.37 length) sits entirely past the frame's
  edge, hidden behind it like a real pin in a jack, while the wider base collar
  right behind it, the yellow shell and the cable back toward the button all stay
  visible. Selecting a tab plugs that button's own cable in while, at the same time,
  the previously-selected button's pulls back out (220ms each, both at once).
  `TabIndicator.set_active(name, buttons, frame_left, animate)` (replacing
  `align_to`) re-lays out every pipe's geometry on each call — a button's position
  is only final once the window's shown — then animates the outgoing/incoming pair.
  The indicator itself paints nothing and is transparent to the mouse.

  Earlier shapes, all dropped by request: an abstract jack-plug (a slender
  `secondary` body with a flat left edge and lightly-rounded right corners, plus a
  short thin pin — replaced once a real cable graphic made the abstraction
  pointless), a fully-rounded pill, a two-piece box-plus-pin (read as disconnected —
  only the pin appeared to animate), a flat sharp-cornered band, a full-height
  `primary` band (invisible on the sidebar, but a solid yellow block where it
  crossed into the dark gap before the frame), and a static always-visible notch per
  button.

  **Stacking order** (`MainWindow._restack`, bottom to top): the tab pipe, an
  expanded preview overlay, the toasts, the resize grips. `TabIndicator` calls
  `raise_()` on itself every time it is re-laid out — a tab switch, and any
  window resize — so left alone it climbed above an expanded preview and drew
  the cable across the picture; `_restack` runs after every such re-layout
  (`show_tab`, `_replace_overlays`) to put the rest back on top of it.

  A `_TabPipe` is created lazily per button on first use and must be shown
  explicitly (`.show()`) right away — a child widget created after its
  parent is already on screen doesn't inherit that visibility, so skipping
  this left every pipe geometrically correct but silently invisible.
- **ThumbnailCarousel** — one fitted frame at a time (`(w-8)/(h-8)` fit,
  scaled pixmaps cached per size and DPR).
  - **Chevrons** are primary discs (alpha 230) with a chevron in
    `primary_text`, sized from the frame (`min(w,h)*0.12`, capped at `w*0.16`
    / `h*0.42`, floored at 14px so a very small preview doesn't shrink them
    to nothing, then an overall `*0.75` — `_disc_centers` — so they read as
    a control rather than dominating the frame) and flush to its edge, with
    an optical-centre nudge toward the tip; they and the dots fade in on
    hover (100ms). Navigation clamps at both ends (only a chevron that leads
    somewhere is drawn). **The chevrons and the expand/shrink icon grow to 1.2x while the
    pointer is on them** (`_HOVER_GROW`, eased over `_HOVER_MS` = 120ms, OutCubic) and ease
    back when it leaves — one `QVariantAnimation` per control (`_hover`, `_hover_to`), driven
    by `_sync_hover`, which uses the same hit areas a click does (`_hovered_control`), so a
    control grows exactly where it would respond. The hit areas are the *un-grown* geometry
    (growing them would flicker at the edge). A reversal partway takes only as long as the
    distance left. Called from `mouseMoveEvent`, and — with the pointer read from the cursor —
    when something changes under a still pointer: stepping (`_step`; the chevron under it may
    just have gone at the first/last frame), `set_frames`, and expanding/shrinking
    (`_toggle_expand`, where the icon jumps, so hover is reset without easing first).
    `clear_preview` and `hideEvent` reset it. A grown chevron is clamped inside the picture
    (the margin it sits in is smaller than the growth on a large preview). Verified with real
    mouse events: disc area x1.45 (1.2 squared) on the chevron and x1.47 on the icon, back to
    the exact base area after, no pixels outside the picture, and the states above.
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
    `QSvgRenderer` (`svg_renderer`), not a scaled bitmap — a raster PNG
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
    (codec · profile · level · size · **fps** right after the size · HDR), an HDR mastering line (ST 2086 peak
    and MaxCLL/MaxFALL — a literal 0 reads as "not tagged"), audio (`+ N tracks`
    when the file has more than one — N is the total count, e.g. `+ 5 tracks`), duration and size — refreshed live if a probe lands while open. **With the Wave Loop showing (video stripped, or an audio-only import) the tip reads audio
    only** — container, audio (codec · channels · rate · bitrate · `+ N tracks`), duration, size; no Video line,
    no mastering line, not even `Video: none` (`_info_text` checks `_wave_mode()`). A tip that is open when
    the mode flips is re-worded and re-anchored on the spot (`_refresh_open_tooltip`).
    **The tip is anchored to the badge, above it (`_badge_global_rect`), never over it.** It
    used to hang off the carousel's own bottom-left corner at a fixed offset: just above the
    badge in the small preview, but *on top of it* in the expanded one (bigger badge, further
    from that corner) — the popup window under the cursor, so the carousel lost the mouse,
    faded, hid the tooltip and the loop flickered without ever showing the info (found by
    computing the two rects: overlap in the expanded preview, none in the small one). The
    gap clears the badge's hit area (`max(px(12), 0.4 × the badge)`), and the popup is clamped to the
    screen (beside the badge if there is no room above). The badge's rect comes from the Wave Loop
    layer in wave mode, where it is drawn. **The hover hit test
    in wave mode maps the pointer onto that layer through screen coordinates**: it used
    `self.mapTo(self.wave, …)`, but the layer is a *sibling* of the carousel (both children of the tab),
    not an ancestor, so the mapping had nowhere to arrive and the badge never registered a hover while
    the video was stripped or for an audio-only file (the same `mapTo`-toward-a-non-ancestor mistake as
    the track drag's). Checked by putting the pointer on the badge as drawn, in the normal preview and
    both wave cases: hit-test and tooltip now agree. The layer bleeds ~2px past the carousel's left edge,
    so only that sliver of the badge's hover margin can't receive the mouse. Moving within the badge once the tip is up doesn't re-show
    it (a redundant `show()` per move made the popup itself flicker). Checked at the badge's hit
    edge in the small, expanded and wave modes.
    **The pointer can move onto the tip and keep it up.** The tip is an interactive window
    (`_InfoTooltip` emits `entered` / `left`; it was briefly made `WindowTransparentForInput`,
    the wrong fix for the flicker — the tip was in the wrong place — and it made hovering it
    impossible). Mouse-driven hides wait `_TIP_GRACE_MS` (50ms — it was 250, then 120, then 80, each judged to leave the tip hanging after the pointer had gone): leaving the badge, leaving the
    carousel or leaving the tip only *starts* `_tooltip_grace`, which the badge's hover, the tip's
    `entered` or `_show_tooltip` cancels, so the pointer can cross the gap from badge to tip. When
    it fires, `_grace_expired` decides from where the cursor is *now* — on the tip or back on
    the badge means stay — so a missed enter/leave can't strand or kill it. A change of state
    (file, collapse, hide, teardown) still hides it at once (`_hide_tooltip`). Checked in the small
    and expanded previews: leaving hides after the grace, not instantly; the pointer resting on
    the tip for a second keeps it; leaving the tip hides it after the grace; tip -> back onto the
    badge keeps it; hiding the carousel closes it.
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
    clock) and only visible while shown. Falls back to a faint gradient wash without rlottie.
    **The loop is 238 frames, not the file's 240** (`_loop_length`): frames 238 and 239 of
    `Wave Loop.json` are frames 0 and 1 again (pixel difference 0.001 against a normal step of
    1.7), so playing all 240 went ... 237, 0, 1, 0, 1, 2 ... — a step *backwards* at every
    restart, the jitter seen there. The length is found at load, not hard-coded: the shortest
    length within the last 8 frames whose frame matches frame 0 (and the next one frame 1),
    judged on a 96x54 render of the alpha channel (a few ms, once); the file's own count if
    nothing repeats. Found by checking the artwork itself rather than the player: the mean
    frame-to-frame difference is *equal* at the seam (1.715 vs 1.715, so a mean can't show it);
    the two-step / one-step ratio can — ~1.95 everywhere except the seam frames, where
    `|f238 − f0|` was 0.001 (ratio 0). After the fix the ratio is 1.93–1.98 at every frame,
    seam included. **Frames are also paced to their own due time**: a single-shot timer re-armed
    for the next frame boundary (`_schedule`, rounded up), not a 16ms poll that showed each ~33ms
    frame for 2 or 3 ticks (measured 25–54ms per frame; 24–45ms in the same harness after, whose own
    5ms sleeps add jitter).
    **The split down the middle of the dots is fixed in the parsed JSON, not the file
    (`_close_wave_seam`).** The picture is one 1920px precomp of 25 "Main Dot" columns (80px
    apart, each starting 10 frames after its neighbour) placed twice at 50% side by side
    (`double dots`). The last column (`Main Dot 49`, x 1922.6) is the wrap-around twin of the first
    (x 2.6) — one comp width away — so it must be in the same phase, but the columns bob with a
    period of **238** frames and its start time is **240**: the two halves met 2 frames out of phase,
    each showing half of every dot in the centre column, ~2px apart vertically (the same 238-vs-240
    slip as the loop length). The fix moves that one layer 2 frames (start time, out point and every
    keyframe, `_shift_layer_time`) to 238. Guarded on the structure it was found in (layers named
    `Main Dot …`, the last exactly one comp width — read from the layers that reference the precomp,
    which has no size of its own — from the first, its start not already a whole number of periods),
    idempotent, and a no-op for any other animation. Measured as the rows where the two columns either
    side of the centre disagree, over 34 frames: 61.5 before (21x the ~3 of an ordinary neighbouring
    column), 11.8 after (the rest is genuinely touching dots); a crop of the centre column through
    the real widget shows whole dots.
  - Signals: `reselect`, `populated` (first frames or audio-only — the tab
    reveals the carousel), `indexChanged` (user scrubs only), `fileDropped`,
    `expandToggled(bool)`. `step(delta)` is the keybind stepper; `sync_index`
    jumps silently.
- **Dialogs** — `MessageDialog` (a `QDialog`: bold title, wrapped **selectable** message,
  optional entry, buttons right-aligned; the **first button is the affirmative
  one** and gets the `action` role — primary — the rest the `queue` role, i.e.
  secondary, both swappable by a theme like the tab buttons). Enter confirms; Escape (and Alt+F4) decline,
  so a dismissed confirmation can never destroy work. **The message is a stock `QLabel`, not
  `ScaledLabel`** (`Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard`, an I-beam cursor;
  drag-select, Ctrl+A, Ctrl+C and the right-click Copy menu all work — verified with a real
  Ctrl+A/Ctrl+C round-trip through the system clipboard) — genuine text selection needs Qt's
  own text control, and that control only ever agrees with what's on screen when Qt paints the
  label itself; `ScaledLabel`'s custom-scaled painter draws the text somewhere else, so its hit
  areas would land wrong at any scale but 1.0. Safe here specifically because a dialog rebuilds
  its whole stylesheet fresh on every `__init__` (`T.stylesheet()`, already baked to the current
  scale) and a modal dialog can't be live-resized after that — the one place a plain `QLabel`
  genuinely doesn't need `ScaledLabel`'s continuous-rescale machinery. **The title stays a
  `ScaledLabel`** (not selectable): its `dialogTitle` role's `font-size: 15px` is a *reference*
  value only `ScaledLabel` reinterprets, so a native `QLabel` would render it as a literal,
  unscaled 15 real px — correct only exactly at 1.0x (and this app very often launches below
  1.0x — see "starts at 35% of the screen's width" above), and titles are short, fixed strings
  with no variable content worth copying anyway. `CountdownDialog`'s per-second
  `self.message_label.setText(...)` is unaffected (`QLabel.setText` either way). **Every popup is
  borderless** (`Qt.FramelessWindowHint`, all subclasses inherit it): a
  translucent window whose `paintEvent` draws the rounded panel — the window
  colour outlined 2px in the theme's `primary`, 8px radius — and, with no title
  bar, a left-press on the panel (any part a child didn't take) drags it with
  `startSystemMove`, like the Borderless window mode. Its own stylesheet clears
  the `QDialog` background (`QDialog { background: transparent; }` appended after
  `T.stylesheet()`), otherwise the sheet's square fill shows at the corners.
  Verified on the real desktop: no `WS_CAPTION`, `frameGeometry == geometry`.
  The OS file pickers (`QFileDialog`) are Windows' own and stay native. `show_message`,
  `ask_yes_no` (True only on an explicit Yes), `ask_text` (stripped text or
  None), `confirm_output_path`. **`show_modal` deletes the dialog** (`deleteLater` after `exec`,
  so callers still read its entry or picks first): the window owns every dialog, so each one used
  to live as long as the window — about 0.45MB and 23 objects per popup, found by `check_leaks`. `AudioStreamPickerDialog` /
  `choose_audio_streams` — Encoding's **Choose Stream(s)**, which holds nothing but the
  tracks: no title and no explanation (`MessageDialog.SHOW_HEADER = False` skips both), a
  `TrackListBox` (one checkbox per audio stream, drag a row to reorder, marquee for a long
  label), then **one row of buttons at the bottom: Add Stream(s), Remove Stream(s), OK,
  Cancel, left to right** (the first two at the left edge, OK / Cancel at the right). The row
  is wider than a standard dialog's, so this popup is 500 reference px wide rather than 400
  (`MessageDialog.WIDTH`; the four buttons need ~450 plus margins). The left-end buttons come
  from the `_build_leading_buttons(row)` hook, called before the stretch that pushes the
  standard buttons right. It edits a *copy* of the list, so Cancel discards ticks, added/removed tracks and
  order alike. Rows are the same shape of entry Muxing's boxes use (`{"id", "source", "file",
  "index", "stream", "name"}`) and are labelled with the shared `tracklist.row_label`
  (`Track N  ·  [External: name  ·]  codec · channels · rate · language`, N by position).
  Add browses another file (audio files, or All Files for an audio track inside a video),
  probes it off the GUI thread (`run_async`; a probe landing after OK/Cancel is dropped) and
  appends its audio stream(s) **ticked** — several ask which via
  `ExternalStreamPickerDialog` — as Muxing does. Remove takes every ticked row out of the
  list, the source file's own included. OK returns `(entries, chosen ids)`; with rows but none
  ticked it ticks the first instead of closing ("no audio" is Strip Audio's job); Cancel /
  Escape returns None.
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

- **`core/ffmpeg_vars.py`** — `derive(settings, source_tab)` returns a frozen
  `JobVars` (`input_file`, `start_time`, `video_codec_arg`, …) of ffmpeg-ready
  values, passed explicitly to every `ffmpeg_build` function
  (`compile_command(job, output_path, loglevel)`, `uses_hdr_tonemap(job)`). It
  replaced module globals set by a `load()`, which every builder read
  implicitly; the ~25 values nothing read (the old single-track picker's
  `VIDEO_TRACK*`, the unused raw forms, `END_TIME`) went with them. Upper-case
  names below (`AUDIO_STREAMS`, `SCALE_VF`, `FPS_ARG`, …) are its lower-case fields.

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

  **`FPS`/`SOURCE_FPS`/`FPS_ARG`** are the identical pattern for Encoding
  Video's optional frame-rate change (`core.formats.FPS_VALUES`, above).
  `FPS` is the raw pick (`formats.SOURCE_FPS` by default); `SOURCE_FPS` is
  the probed source fps *snapshotted at queue time*, same convention as
  `SOURCE_HEIGHT`; `FPS_ARG` (`_fps_arg`) is the resulting `-r` value, or
  `None` for `"Source"` or when the pick is no longer <= the source's own
  rate (same re-validation `_scale_vf` does for Resolution, and for the
  same reason — a saved preset applied to a different file). `-r` is a
  plain global output option, not a `-vf` filter, so it needs no
  `SCALE_VF`-style filter-string composition — `build_encode_command` just
  sets `output_kwargs["r"]` directly alongside `-fps_mode cfr` (A/V Sync).
- **Multi-stream audio** ("Choose Stream(s)" on Encoding's Audio panel,
  `ui/widgets/dialogs.py`'s `AudioStreamPickerDialog`, described under Dialogs) — a
  list of the source's audio streams plus any added from **other files**, ticked = included,
  in a drag-reorderable order that is the output's; OK returns the edited list and the
  ticked ids (never none ticked while rows exist — "no audio at all" is Strip
  Audio's job, not a second door to the same outcome), Cancel/close returns
  `None` so the caller can tell "nothing changed" apart from "chose zero". **A stream from
  another file is mapped from that file's own input**: `build_encode_command` takes each
  audio entry's `source`/`file` through `_mux_input` (the helper Muxing's tracks use — one
  `ffmpeg.input` per distinct path, cached, trimmed exactly like the primary), so the
  external audio is assumed to line up with the primary's timeline. Verified with a real
  encode: an `.m4a` added as Track 4, ticked, ordered after a source track, produced
  `-i multi.mkv -i ext.m4a -map 0:v -map 0:a:0 -map 1:a:0`, and the output's audio streams
  were the source's stereo track then the 22.05kHz external one.
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
  encoder actually supports) matching the machine's *dedicated* GPU vendor
  (`gpu.vendor()`, via `wmic`/`Get-CimInstance Win32_VideoController`,
  NVIDIA > AMD > Intel when more than one dedicated adapter is present;
  integrated adapters are ignored) *and* actually
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
  **FPS** (the Video sub-tab's frame-rate ceiling, alongside Resolution —
  see "Tabs" above) is a plain global output option, not a filter: when
  `FPS_ARG` is set, `build_encode_command` sets `output_kwargs["r"]`
  directly, no `-vf` involved and no interaction with `SCALE_VF` or the HDR
  tonemap filter chain below it.
  **A/V Sync is wired**: when checked (on by default) and the video stream
  isn't stripped, `build_encode_command` adds `-fps_mode cfr` — the current,
  non-deprecated replacement for `-vsync` (same "hold a constant rate,
  duplicating/dropping frames" behaviour) — scoped to Encoding only, since
  Muxing's always a stream copy and `fps_mode` has nothing to act on without
  a real video encode. **`-fps_mode` isn't universal** — added in ffmpeg 5.1
  (mid-2022); an older install (this app's own dev machine runs a 2020
  build) doesn't recognize it at all and would fail *every* Encoding job
  outright with A/V Sync on by default. `core.capabilities.supports_fps_mode()`
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
    `-vf` from `core.capabilities.libplacebo_tonemap_vf(peak_detect=...)`
    (`libplacebo=apply_dolbyvision=true:peak_detect=<bool>:tonemapping=
    bt.2390:colorspace=bt709:color_primaries=bt709:color_trc=bt709:
    format=yuv420p` — moved to `core/probe.py`, not `ffmpeg_build.py`,
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
    `core.capabilities.supports_libplacebo()` gates this two ways instead. It is
    `libplacebo_problem() is None`, and that is **two checks, not one**: the
    filter is listed by `ffmpeg -filters` (else `LIBPLACEBO_MISSING`), *and* a
    one-frame probe of the real `libplacebo_tonemap_vf()` on an explicit
    `VULKAN_DEVICE_FLAGS` device actually runs (else `LIBPLACEBO_NO_VULKAN` —
    a build with the filter but no usable Vulkan driver). Cached per process
    behind a lock; the probe is a real ffmpeg run (~0.7s here, and it wakes the GPU), so it
    runs on a worker **only once a file probes as HDR** (`MediaSession._check_hdr_support`,
    which re-syncs the tabs when it answers) — never at launch or for an SDR file. Until it
    has answered (`capabilities.libplacebo_checked()`), Encoding greys the switch with a
    "checking" note rather than ask, since asking runs the probe on the GUI thread; measured:
    enabled 0.58s after an HDR import, worst GUI stall 6ms. Verified against a real failure by
    pointing `VK_DRIVER_FILES` / `VK_ICD_FILENAMES` at a nonexistent driver
    (ffmpeg exits nonzero → `vulkan`; a crash or hang counts the same).
    `libplacebo_problem_text()` is the one wording used by the switch's
    tooltip (on an HDR file with the switch greyed), the queue-time dialog and
    the builder's `ValueError`. `EncodingTab._sync_controls`
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
    static metadata to trust. `core.probe._probe_hdr_static_metadata`
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
    `mastering_max_nits`/`max_cll` from `app.media.info` into the job's
    settings dict at queue time — a fact about the input, not a user choice —
    and `ffmpeg_vars.derive()` carries them through as `MASTERING_MAX_NITS`/
    `MAX_CLL` for `build_encode_command` to read.

    **A post-encode safety net re-verifies the real output, not just the
    filter in isolation.** `core.probe.verify_hdr_sdr_tag(path)` re-probes
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
    like. `core.previews.extract_hdr_tonemapped_thumbnails` instead runs one
    short-lived real ffmpeg + libplacebo process **per frame** (an input-side
    `-ss` approximate seek, then a single-frame decode through the identical
    `libplacebo_tonemap_vf` filter the real encode uses), **repeating the raw
    set's seeks** (`seeks=`, from `extract_preview_frames` — see "Preview frames
    are keyframes") so the two sets are the same frames; with no seeks it falls
    back to OpenCV's frame indices (`_interior_sample_frames`). A keyframe seek
    decodes one frame, so the render got faster too: 4K HDR AV1 8.2 -> 5.3s, 4K
    HDR HEVC 9.8 -> 7.5s. **The frames render in parallel**
    (`preview_workers`: 3 processes at once with 8 or more logical CPUs, else 2 — never 1),
    each at `-threads 4` (or the CPU count if lower) and **below-normal priority**, with a 90s
    per-frame timeout (a frame that times out is a hole in a set that must stay aligned with
    the raw one, and a frame sharing the machine with an encode takes far longer than the
    ~1.5s it takes alone). Measured on that 4K file, 10 frames: one ffmpeg at a time 14.6-15.2s;
    4 at once 7.1s but 70 CPU-seconds and ~5GB at once; **3 at once with `-threads 4` 8.8s at
    40 CPU-seconds (the sequential run's 43) and ~0.73GB per process**. Confined to 8 / 4 / 2 / 1
    logical CPUs (affinity, verified inherited by the children) 1 -> 2 -> 3 workers took
    18.6 -> 11.7 -> 10.0s / 20.1 -> 13.9 -> 13.2s / 36.5 -> 25.4 -> 24.3s / 54.4 -> 41.7 -> 41.0s:
    a third worker helps at 8, barely at 4, and two beat one even on a single CPU (each process
    waits on the GPU, using 0.5-0.7 of a core). Tried and **not** worth it, all measured: libplacebo's
    `shader_cache` (no cache file written, no speedup), hardware decode (no change — decode
    is ~6 of the 14.6s, the other ~9s is per-process libplacebo/Vulkan start-up and tone
    mapping), one ffmpeg with ten `-ss/-i` inputs (slower, 8.4s, and pixels differ by up to
    5/255 from separate processes), and downscaling in ffmpeg (no time saved; frames are shrunk
    after decoding instead, see below). **Alongside an
    encode** (12s slice of the same file, encode at normal priority; single run each, so the
    percentages are indicative): software H.265 13.5s alone / 16.0s with the render running (+18%),
    the render 9.9s alone / 13.5s with it (+37%); HDR->SDR + x264 6.5s / 8.7s (+32%), render 9.6s /
    12.6s (+32%); NVENC HEVC 3.1s / 3.8s (+22%), render 9.9s / 11.0s (+11% — the encode ended
    first, so most of that render ran alone). **Memory, measured on real 4K HDR files** (Mulan,
    3600x2160, and Beauty and the Beast; process memory from `GetProcessMemoryInfo`, the render's
    ffmpegs sampled every 80ms), **before frames were capped**: every preview frame was a `Format_RGBA8888`
    QImage — **29.7MB at 3600x2160** (4 bytes a pixel), so a set of ten was **297MB**. An HDR file
    therefore holds two sets (raw + tone-mapped) = ~594MB of frames: the app went from 811MB private
    (a window with no file) to 1146MB with the raw previews (+335MB) and 1442MB once the tone-mapped
    set landed (+296MB), and stayed there — turning the switch on, scrubbing all ten frames and
    expanding the preview added ~14MB (the carousel's scaled-pixmap cache). **While the render runs**
    the 3 ffmpeg processes hold ~2.7GB private between them (~0.9GB each on a 10-bit 3600x2160 HEVC
    source; 0.73GB measured earlier on Beauty and the Beast) and the app's own peak commit reached
    ~2GB (the worker's transient PIL images beside the QImages), for the ~10s the render takes.
    **Frames are now stored no bigger than they can be drawn**: `_preview_max_size` (`ui/media_session.py`) is the
    biggest screen in device pixels, and `extract_preview_frames` / `extract_hdr_tonemapped_thumbnails`
    take it as `max_size`, shrinking each frame as it is decoded (`previews._shrink`, `cv2.INTER_AREA`
    — 3.7ms per 4K frame against Pillow LANCZOS's 57ms); `pil_to_qimage` stores an image without alpha
    as `Format_RGB32` (Qt's native format; see below). A 4K frame on a 1440p screen is 14MB.
    **The previous file's frames — raw and tone-mapped — are dropped when the file changes**
    (`select_file`, and Encoding's own `_raw_frames` in `reset_hdr_preview`); only a reselect of the
    same file reuses them. The raw set used to wait for the next file's frames to replace it, so a
    file with none (audio, cover art, no preview) kept the old video's: 141MB of a 4K file's frames
    held behind an audio file (269MB committed -> 128MB, idle 121MB). The tone-mapped set
    used to stay until the next render (316MB held behind an SDR clip) and was never reused anyway.
    Measured on a real display, working set (before -> after): idle with the spinner ready 376 ->
    173MB, a 1080p file 464 -> 241, 4K 703 -> 288, 4K HDR with both sets 1022 -> 398, back to 1080p 785
    -> 246. Queue rows keep a thumbnail scaled to cover 240x160 (4x the slot), not the whole frame.
    `main.py` sets `OPENBLAS_NUM_THREADS=1` before numpy loads: OpenBLAS otherwise starts a thread per
    core, each reserving a buffer — ~740MB of commit (not working set) on 32 threads. Empty (no preview
    change) whenever `supports_libplacebo()` is false or the geometry probe
    fails — callers must check the former themselves to tell "no HDR to show"
    apart from "libplacebo isn't available".

    **Encoding's preview carousel actually shows this tonemapped set once
    HDR→SDR is on**, not just the raw HDR frames with a switch flipped
    elsewhere. The render and its cache (`start_hdr_render`,
    `hdr_frames`/`hdr_frames_path`, token-guarded like the thumbnails) live
    on `MediaSession` (`app.media`), one render per file. `EncodingTab._apply_preview_frames`
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
  **`-map_metadata:s:v:0 -1` has a side effect on every stream, so a copied audio
  track's tags are mapped back explicitly.** ffmpeg turns off its default per-stream
  metadata copy for *all* streams as soon as any `-map_metadata` of that type exists;
  with only the video wipe above, a Passthru (`-c:a copy`) audio track came out with no
  language or title (confirmed: the same command without the option kept `eng`/`jpn`; it
  predates the multi-input work). So for every straight-copy `AUDIO_STREAMS` entry
  `build_encode_command` adds `-map_metadata:s:a:{i} <input>:s:a:{src_index}` — tags from
  the stream actually mapped. **`<input>` is the input's real `-i` position, not `0`**:
  ffmpeg-python numbers inputs by the topological order of the graph and drops any input
  nothing maps, so with the video stripped and the first audio track from another file,
  that file is input `0` and the primary is `1` (`_input_positions` rebuilds the order
  with the same `topo_sort` `ffmpeg._run.get_args` uses). A re-encoded track is unchanged:
  wiped (`-map_metadata:s:a:{i} -1`) and only its language reapplied. Verified on real
  encodes, reading the tags back with ffprobe: two copied tracks (`eng`, `jpn`), a
  source track plus an external `.m4a`, video stripped with the external track first
  (`0:s:a:0` / `1:s:a:1`), a re-encoded track beside a copied one (the re-encoded one has
  `language` but no `title`/`BPS`), and audio stripped.
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
  **Runs at the OS's normal process priority unless Settings' "Priority
  Level" says otherwise** (`core/priority.py`; ORed into `creationflags`).
  The default stays Normal because throttling was measured to be pure
  downside. An earlier
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
    `probe_duration(input) − start_secs` (the corrected real length — see "A file's real
    length" above; a raw header once made a clip whose header said 5501s read 0.65% for
    its whole 35s), probed in the worker thread — but
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
    `process_job.replace_output` rather than a bare `os.replace`. **A bare
    `os.replace` can fail with a genuine, reproducible Windows "Access is
    denied" (WinError 5)** — confirmed two real causes directly (not just
    from a bug report): the destination file has the read-only attribute
    set, or something else (a media player, thumbnail/preview generation, an
    antivirus scan reacting to the just-closed temp file) has it open for a
    moment. `replace_output` clears the read-only bit first (best-effort)
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
  (`app.media.thumb_frames`) or decode on a worker, never on the GUI thread.

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
encoder, profile, level, speed, quality, resolution, source_height, fps,
source_fps, gpu_enabled, hdr_to_sdr, mastering_max_nits, max_cll, strip_video,
strip_audio, audio_streams`.

**Audio is a list, not four scalar keys**, because an Encoding job can carry
more than one *output* audio stream (the Audio Track dropdown + "Choose
Stream(s)" dialog — see "Multi-stream audio" above): `audio_streams` is
`[{"id": "src:0", "source": "primary", "file": None, "index": 0, "codec": "AAC",
"bitrate": "192 kbps", "channels": "Stereo", "sample_rate": "48000 Hz", "passthru": False,
"language": "eng"}, ...]` (`source`/`file` say which input a stream is read from — a stream
added from another file has its own; `index` is its position among *that file's* audio
streams), one entry per *included* stream in list order, built by `_gather_settings` from
`_audio_stream_settings` (the per-stream dict last edited through the Audio
Codec/Bitrate/Channels/Sample Rate row + Passthru checkbox for whichever
stream the Audio Track dropdown currently shows) plus every other included
stream's own last-saved values, with `language` read fresh each time
from the entry's probe description rather than stored per-stream like the
rest — it's a fact about the source stream, not something the user edits.
`mastering_max_nits`/`max_cll` are a fact snapshotted from the probed source
at queue time (see the HDR→SDR bullet above), not a user choice — carried
through so a job queued now still tone-maps against the source it was
actually queued against, even if the user swaps files before it runs.
`source_height`/`source_fps` are the same convention, for `resolution`/`fps`
(the Resolution/FPS dropdowns' picks — see `core/formats.py`'s Resolution
and FPS ladders and `ffmpeg_vars.SCALE_VF`/`FPS_ARG` above).

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
  each (`process_job.set_suspended`). Verified: pause froze the
  byte count, ffmpeg appeared inside the job during a merge, Stop mid-
  download and mid-conversion left no process and no files, and killing the
  Python process outright took the tree with it (kill-on-close).
- **Private work folder**: yt-dlp writes only into a hidden
  `.llamamxd-download-XXXXXXXX` beside the output (`-P`, `-o download.%(ext)s`);
  on exit 0 the file named by `--print after_move:filepath` is moved onto
  `final_path` with `process_job.replace_output`'s retrying replace.
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
- **No `print`.** Anything worth a line goes through `core.llamalog` (`llamalog.get("area")`, then
  `.info` / `.warning` / `.debug`); a swallowed exception whose failure matters gets a log line
  (`exc_info=True` when the traceback helps) rather than a bare `pass`.
- Layout goes through layouts (`hrow`, `labeled`, `stream_page`), never
  absolute positioning, except overlays that must float: the tab pipe, the
  Wave Loop layer, toasts.
- **Sizes are reference pixels through `ui/scale.py`** — never a bare pixel
  count in layout, fixed-size or paint code (see "UI scale" above): bound
  helpers for what's set once, design-space painting for what's painted,
  `px()` / `font_px()` in the stylesheet.
- **Comments and docstrings.** A `"""docstring"""` says *what* a module, class or function does:
  one line by default, three at most (a module's a short paragraph). A `#` comment sits on the
  line it explains and says *why* a non-obvious line is there (a verified ffmpeg / yt-dlp /
  Windows / Qt quirk), in three lines at most. Never `#` lines in place of a docstring. No
  history, "confirmed"/"verified" narratives, measurements or "by request" in code: those belong
  in commit messages and this file. Section banners are the three-line `# ---- #` form.
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
  way; `JobVars` deliberately has no end time. An end time is only safe as an
  input-side `-to` paired with an input-side `-ss`.
- **A copied track in a trimmed Encode needs `-copypriorss:a:N 0`** (`build_encode_command` adds it
  for every Passthru track when the start is trimmed). The input-side `-ss` lands on the keyframe
  before the start; re-encoded streams drop what precedes the start, but a copied one kept those
  packets, so an MKV came out with ~1s of audio before the picture (the muxer shifted the re-encoded
  streams to 0.98s) and 1s too long. MP4 hid it behind an edit list. Muxing is unchanged on purpose:
  every stream is copied there, so all start together at the keyframe (the rundown's "· keyframe").
- **`Dropdown.hidePopup` is also called by Qt on style changes** (a live theme
  switch), which is why `popupClosed` is gated on the popup having genuinely
  been open — otherwise Settings' theme preview reverted itself on every
  theme change.
- **`QApplication.quit()` re-sends close events** to open windows, including
  the one already inside `closeEvent` — hence `MainWindow._closing`.
- **A QDialog's `exec()` spins a nested event loop**; timers (the queue poll)
  keep firing under it. Post dialogs with `QTimer.singleShot(0, …)` from
  timer-driven code.
- **A parentless widget that is made visible becomes its own top-level window** —
  so `setVisible(True)` / `show()` in a constructor must come *after* the widget
  is added to a layout. Settings' Fullscreen row did it in the wrong order and
  flashed a small "LlamaMXD" window at every launch whenever the saved Window Mode
  was Borderless (Fixed/Windowed never showed it). Found by launching under
  `pythonw` and logging every top-level `QEvent.Show` with its stack (an app-level
  event filter) while polling `EnumWindows` for visible windows system-wide; the
  Vulkan probe's ffmpeg only ever creates hidden 1x1 helper windows.
- **Setting Python attributes on a PySide object before `super().__init__()`**
  is unsafe — use class-level defaults for immutables or `_init_state()` (on
  MediaTab) for per-instance state.
- **Text on a `ScaledLabel` / `ScaledButton` / `ScaledLineEdit` / painted widget
  scales continuously; what's left is the combo popup rows, which
  Qt snaps to a whole pixel size** (13px at scale 0.75 is 10px, not 9.75), and
  the whole-pixel rounding of the integer layout sizes (~1px per stacked row —
  each `px()` length flips at its own scale, so a widget can step back 1-2px
  for one step of a drag). A bare `QLabel` with text would render at its
  *reference* size at every scale (the stylesheet's label sizes are unscaled
  now): make it a `ScaledLabel` (and a `QLineEdit` a `ScaledLineEdit`). The
  pixmap-only logo `QLabel` is the one plain one.
- **A script that builds a `MainWindow` can overwrite the user's real
  `settings.json`.** Settings autosaves from many places (leaving its tab,
  every control handler, close), through `ui.tabs.settings.save_settings`; a
  harness that sets a window mode or tours the tabs left `window_mode` at
  whatever it had tested. Neutralise it before building the window:
  `import ui.tabs.settings as st; st.save_settings = lambda *a, **k: None`
  (patching one `on_leave` is not enough — three runs proved it).
- **A headless script can die with a native access violation as the interpreter exits**, after
  everything it did has already succeeded (`Windows fatal exception: access violation`, `<no Python
  frame>`, exit code 139 under bash). Measured on the same import -> expand -> shrink -> exit script:
  7 of 30 runs on a clean checkout of `HEAD` from before the logging work, 5 of 30 on the tree with it —
  so it predates LlamaLog and is Qt/native teardown, not the hooks (the script never even installs
  them). Check the *exit code* of a harness as well as its last line, and don't chase a crash after
  the final `print` without comparing against `HEAD` first. The real app would now report the same
  thing at its next start (`crash.log`, see "Logging").
- **Headless testing**: `QT_QPA_PLATFORM=offscreen` works for scripted runs and
  `widget.grab()` screenshots, but its virtual screen is tiny (the window came
  out 280px wide) — pin the window to 896x540 first (or, on a real display,
  patch `scale.window_size` to force a scale). It has no system fonts,
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
