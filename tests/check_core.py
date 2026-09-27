# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Golden results of the pure logic (the format cascade, naming, keybinds) and of probing /
decoding the fixture clips."""
import itertools
from datetime import datetime

from harness import UNICODE_TITLES, check_golden, fixture, report

from core import capabilities, formats, keybinds, naming, previews, probe

# Raw byte counts and bit rates follow the encoder build that made the fixtures; the snapped
# display values are what the app acts on.
_VOLATILE = {"file_size", "bit_rate", "bitrate"}


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in _VOLATILE}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def formats_snapshot():
    out = {"containers": formats.containers(), "per_container": {}, "per_encoder": {}}
    for c in formats.containers() + [".avi"]:
        out["per_container"][c] = {"video": formats.video_codecs_for(c), "audio": formats.audio_codecs_for(c)}
    for e in list(formats.VIDEO_ENCODERS) + [formats.SELECT]:
        out["per_encoder"][e] = {
            "profiles": formats.profiles_for(e), "levels": formats.levels_for(e),
            "quality": formats.quality_for(e), "speed": formats.speed_values_for(e),
            "speed_av1_range": formats.speed_values_for(e, av1_range=(-2, 13)),
            "speed_kind": formats.speed_kind_for(e), "speed_default": formats.speed_default_for(e)}
    videos = [None, "H.264", "H.265", "VP9", "AV1", "ProRes", "MPEG-2"]
    audios = [None, "AAC", "Opus", "FLAC", "PCM", "Dolby TrueHD", "DTS", "AC3"]
    out["containers_for"] = {f"{v}+{a}": formats.containers_for(v, a) for v, a in itertools.product(videos, audios)}
    out["audio_bitrates_for"] = {a: formats.audio_bitrates_for(a) for a in list(formats.AUDIO_ENCODERS) + [formats.SELECT]}
    out["resolutions_for"] = {str(h): formats.resolutions_for(h) for h in (None, 360, 719, 720, 1080, 1440, 2160, 4320)}
    out["fps_values_for"] = {str(f): formats.fps_values_for(f) for f in (None, 8, 23.976, 24, 29.97, 30, 59.94, 60, 144)}
    out["fps_args"] = {f: [formats.fps_arg_for(f), formats.fps_number_for(f)] for f in formats.FPS_VALUES}
    out["bitrate_display_for"] = {str(b): formats.bitrate_display_for(b) for b in (None, 0, 64000, 128000, 160000, 231000, 700000, 1400000, 5000000)}
    out["channels"] = {str(c): formats.channels_display_for(c) for c in range(0, 12)}
    out["sample_rates"] = {str(r): formats.sample_rate_display_for(r) for r in (22050, 44100, 48000, 96000)}
    out["lossless"] = {f"{c}/{p}": formats.probed_audio_is_lossless(c, p) for c, p in [
        ("flac", None), ("pcm_s24le", None), ("truehd", None), ("mlp", None), ("dts", "DTS"),
        ("dts", "DTS-HD MA"), ("dts", "DTS-HD MA + DTS:X"), ("dts", "DTS-HD HRA"), ("aac", "LC")]}
    out["passthru_only"] = {c: formats.is_passthru_only(c) for c in ("DTS", "Dolby TrueHD", "AAC")}
    return out


def naming_snapshot():
    now = datetime(2026, 9, 26, 14, 5, 9)
    info = {"title": "My Clip: Part 1", "chapters": 12, "bit_rate": 18_700_000, "duration": 35.0,
            "creation_time": "2024-03-05T10:20:30.000000Z"}
    templates = [naming.DEFAULT_TEMPLATE, "{title}", "{source}_{date}_{time}", "{source}-{quality}-{bitrate}",
                 "{chapters}.{creation-time}", "{nope}-{title}", "a<b", "", "   ", "{source}  -  {title}"]
    out = {"errors": {t: naming.template_error(t) for t in templates},
           "unknown": {t: naming.unknown_tokens(t) for t in templates}}
    live = naming.media_live_values("C:/in/clip.mkv", info)
    untitled = naming.media_live_values("C:/in/clip.mkv", {})
    queue = naming.media_queue_values("C:/in/clip.mkv", info, {"encoder": "H.264", "quality": 22}, now=now)
    out["live"] = {t: [naming.render_live(t, live), naming.render_live(t, untitled, fallback="clip")] for t in templates}
    # A creation tag is shown in local time: swap in a placeholder so the golden holds anywhere.
    local = naming._stamp(datetime.fromisoformat("2024-03-05T10:20:30+00:00").astimezone(), True)
    queue = {k: (v.replace(local, "<2024-03-05T10:20:30Z as local>") if isinstance(v, str) else v)
             for k, v in queue.items()}
    out["queue_values"] = queue
    out["resolve"] = {t: naming.resolve_path(f"C:/out/{t}.mp4", queue) for t in templates if t.strip()}
    dl = {"extractor_key": "Youtube", "title": "Some / Video", "chapters": [1, 2], "upload_date": "20240305",
          "duration": 100}
    out["download"] = {"live": naming.download_live_values(dl),
                       "queue": naming.download_queue_values(dl, {"quality": "1080p60",
                                                                  "download": {"parts": [{"size": 25_000_000}]}},
                                                             now=now)}
    return out


def keybinds_snapshot():
    defaults = keybinds.defaults()
    broken = {"tab_prev": {"key": 5}, "nope": {"key": "X", "enabled": True}, "fullscreen": {"enabled": False}}
    return {"defaults": defaults, "normalized_broken": keybinds.normalize(broken),
            "conflicts": {f"{a}={k}": keybinds.conflict(defaults, a, k) for a, k in [
                ("fullscreen", "Left"), ("tab_next", "Up"), ("dropdown_next", "Down"), ("activate", "Space"),
                ("toggle_queue", "F11"), ("preview_next", "Right")]}}


def _realigned(path, frames, seeks):
    """Does repeating each frame's seek (what the HDR render does) give the same picture?"""
    for frame, (at, exact) in zip(frames, seeks):
        again, _ = previews._grab_frame(path, at, (320, 180), exact=exact, threads=2)
        if again is None or again.tobytes() != frame.tobytes():
            return False
    return True


def probe_snapshot():
    out = {}
    for name in ("sdr.mp4", "multi.mkv", "hdr.mkv", "audio.m4a", "vp9.webm", "cover.m4a", "keys.mp4", "sparse.mp4",
                 "long.mp4", "late.mkv"):
        path = fixture(name)
        info = probe.probe_media(path)
        frames, seeks = previews.extract_preview_frames(path, 10, max_size=(320, 180))
        with_info = previews.extract_preview_frames(path, 10, max_size=(320, 180), info=info)[1]
        out[name] = {"probe": _strip(info),
                     "duration": round(probe.probe_duration(path) or 0, 3),
                     "previewable": probe._has_previewable_video(path),
                     "frames": [list(f.size) for f in frames],
                     # (seconds, exact): keyframe (False), redone exactly or from OpenCV (True)
                     "seeks": [[round(t, 3), exact] for t, exact in seeks],
                     "same_seeks_with_probe_info": with_info == seeks,
                     "realigned": _realigned(path, frames, seeks)}
    path = fixture("late.ts")
    out["late.ts"] = {"probe": _strip(probe.probe_media(path)), "duration": round(probe.probe_duration(path) or 0, 3)}
    for name in ("keys.mp4", "late.mkv"):                    # the OpenCV pass on files ffmpeg would take
        frames, seeks = previews._extract_thumbnails_cv2(fixture(name), 4, (200, 120))
        out[name]["opencv_frames"] = [[list(f.size) for f in frames], [[round(t, 3), e] for t, e in seeks]]
    out["hdr.mkv"]["tonemapped_frames"] = [list(f.size) for f in previews.extract_hdr_tonemapped_thumbnails(
        fixture("hdr.mkv"), 3, max_size=(200, 120))]
    seeks = previews.extract_preview_frames(fixture("keys.mp4"), 3, max_size=(200, 120))[1]
    out["keys.mp4"]["tonemapped_at_seeks"] = len(previews.extract_hdr_tonemapped_thumbnails(
        fixture("keys.mp4"), 3, max_size=(200, 120), seeks=seeks))
    out["capabilities"] = {"fps_mode": capabilities.supports_fps_mode(),
                           "libplacebo_problem": capabilities.libplacebo_problem(),
                           "av1_preset_range": list(capabilities.av1_preset_range())}
    out["hdr.mkv"]["verify_sdr_tag"] = probe.verify_hdr_sdr_tag(fixture("hdr.mkv"))
    out["sdr.mp4"]["verify_sdr_tag"] = probe.verify_hdr_sdr_tag(fixture("sdr.mp4"))
    out["missing"] = _strip(probe.probe_media("C:/nope/missing.mkv"))
    return out


def unicode_tag_problems():
    """A file whose tags aren't ASCII must be identified and its titles read back intact (the
    probe's output was once decoded as cp1252, which has no 0x8f: the whole probe came back empty)."""
    info = probe.probe_media(fixture("unicode.mkv"))
    found = {"video": info["has_video"], "audio": info["has_audio"], "container title": info["title"],
             "chapter titles": [c["title"] for c in info["chapter_list"]],
             "subtitle title": (info["subtitle_streams"] or [{}])[0].get("title")}
    wanted = {"video": True, "audio": True, "container title": UNICODE_TITLES["container"],
              "chapter titles": UNICODE_TITLES["chapters"], "subtitle title": UNICODE_TITLES["subtitle"]}
    return [f"{what}: {found[what]!r}, wanted {want!r}" for what, want in wanted.items() if found[what] != want]


def run():
    ok = report("format cascade (formats.py)", check_golden("core_formats", formats_snapshot()))
    ok &= report("file naming (naming.py)", check_golden("core_naming", naming_snapshot()))
    ok &= report("keybinds (keybinds.py)", check_golden("core_keybinds", keybinds_snapshot()))
    ok &= report("probe + preview frames on fixture clips", check_golden("core_probe", probe_snapshot()))
    ok &= report("non-ASCII tags survive the probe", unicode_tag_problems())
    return ok


if __name__ == "__main__":
    run()
