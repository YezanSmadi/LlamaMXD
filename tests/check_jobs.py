# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Real jobs: Mux and Encode settings run through ffmpeg_vars -> ffmpeg_build -> FfmpegJob on the
fixture clips, and their outputs probed (golden). Also: stop() mid-run leaves nothing behind,
and a job that can't run fails with a readable reason. (Downloads: check_runners, offline.)


`stream_starts` guards A/V sync: a trimmed Encode with a Passthru track once put the copied track
~1s ahead of the re-encoded streams (enc_multi_audio.mkv, enc_trim_passthru_aac.mp4).

Subtitles and chapters are checked by what a player would see: each track's cues (as SRT), its
language and flags, the chapter list, a picture track's timing, and burned-in pixels."""
import os
import subprocess
import time

from harness import WORK, check_golden, fixture, report

from core import capabilities, ffmpeg_build, ffmpeg_vars, probe
from core.ffmpeg_runner import FfmpegJob, partial_path
from core.tools import tool_path

OUT = os.path.join(WORK, "jobs")
os.makedirs(OUT, exist_ok=True)


def _run(settings, tab, name, stop_after=None):
    """Run one job to its end (or stop it after `stop_after` s); `(events, output path)`."""
    final = os.path.join(OUT, name)
    for path in (final, partial_path(final)):
        if os.path.exists(path):
            os.remove(path)
    settings = dict(settings, output_path=final)
    job_vars = ffmpeg_vars.derive(settings, tab)
    job = FfmpegJob(ffmpeg_build.compile_command(job_vars, partial_path(final)), final, partial_path(final),
                    duration_secs=job_vars.duration_secs, input_file=job_vars.input_file,
                    start_secs=job_vars.start_secs, verify_hdr_tag=ffmpeg_build.uses_hdr_tonemap(job_vars),
                    prepare=ffmpeg_build.prepare_commands(job_vars, partial_path(final)), label=name)
    job.start()
    events, t0 = [], time.monotonic()
    while True:
        events += job.poll_events()
        if any(e[0] in ("done", "failed") for e in events):
            break
        if stop_after is not None and time.monotonic() - t0 > stop_after:
            job.stop()
            break
        if time.monotonic() - t0 > 120:
            job.stop()
            events.append(("failed", "timed out"))
            break
        time.sleep(0.05)
    return events, final


def _summary(path):
    """What a probe says about an output, minus build-dependent byte counts."""
    if not os.path.exists(path):
        return None
    info = probe.probe_media(path)
    return {
        "container": info["container"], "video": info["video"], "profile": info["video_profile"],
        "size": [info["width"], info["height"]], "fps": info["fps"] and round(info["fps"], 3), "hdr": info["hdr"],
        "duration": info["duration"] and round(info["duration"], 1),
        "stream_starts": _starts(path),
        "video_streams": [[s["codec"], s["color_format"], s["hdr_display"]] for s in info["video_streams"]],
        "audio_streams": [[s["codec"], s["channels_display"], s["sample_rate_display"], s["language"]]
                          for s in info["audio_streams"]],
    }


def _starts(path):
    """Each stream's start time: streams out of step with each other are an A/V sync fault."""
    import subprocess
    from core.tools import tool_path
    out = subprocess.run([tool_path("ffprobe"), "-v", "error", "-show_entries", "stream=codec_name,start_time",
                          "-of", "csv=p=0", path], capture_output=True, text=True).stdout.split()
    return [f"{codec}@{round(float(start), 2)}" for codec, start in (line.split(",")[:2] for line in out)]


def _outcome(events):
    last = [e for e in events if e[0] in ("done", "failed")]
    progress = [e[1] for e in events if e[0] == "progress"]
    return {"end": last[-1][0] if last else "stopped", "reached_100": bool(progress) and max(progress) >= 0.999}


def _audio(index, codec, bitrate="128 kbps", channels="Stereo", rate="48000 Hz", passthru=False, language=None):
    return {"id": f"src:{index}", "source": "primary", "file": None, "index": index, "codec": codec,
            "bitrate": bitrate, "channels": channels, "sample_rate": rate, "passthru": passthru, "language": language}


def cases():
    multi, sdr, hdr = fixture("multi.mkv"), fixture("sdr.mp4"), fixture("hdr.mkv")
    mux = {"input_file": multi, "output_format": ".mp4", "start_secs": 0, "duration_secs": 0, "av_sync": True,
           "video_tracks": [{"source": "primary", "file": None, "index": 0}], "strip_video": False,
           "audio_tracks": [{"source": "primary", "file": None, "index": 1},
                            {"source": "primary", "file": None, "index": 0}], "strip_audio": False}
    enc = {"input_file": sdr, "output_format": ".mp4", "start_secs": 1, "duration_secs": 2, "av_sync": True,
           "encoder": "H.264", "profile": "High", "level": "4.0", "speed": "ultrafast", "quality": 28,
           "resolution": "Source", "source_height": 360, "fps": "Source", "source_fps": 24,
           "gpu_enabled": False, "hdr_to_sdr": False, "mastering_max_nits": None, "max_cll": None,
           "strip_video": False, "strip_audio": False, "audio_streams": [_audio(0, "AAC", "96 kbps")]}
    out = [
        ("Muxing", "mux_reordered.mkv", dict(mux, output_format=".mkv")),
        ("Muxing", "mux_strip_audio.mp4", dict(mux, audio_tracks=[], strip_audio=True)),
        ("Encoding", "enc_h264_trim.mp4", enc),
        ("Encoding", "enc_vp9_opus.webm", dict(enc, output_format=".webm", encoder="VP9", profile="0", level="",
                                               speed="8", quality=40, audio_streams=[_audio(0, "Opus")])),
        ("Encoding", "enc_multi_audio.mkv", dict(enc, input_file=multi, output_format=".mkv", audio_streams=[
            _audio(1, "Opus", passthru=True, language="jpn"), _audio(0, "MP3", "192 kbps", "Mono", "44100 Hz", language="eng")])),
        ("Encoding", "enc_downscale_retime.mp4", dict(enc, resolution="360p", fps="12")),
        ("Encoding", "enc_trim_passthru_aac.mp4", dict(enc, audio_streams=[_audio(0, "AAC", passthru=True)])),
    ]
    if capabilities.supports_libplacebo():
        out.append(("Encoding", "enc_hdr_to_sdr.mp4", dict(enc, input_file=hdr, encoder="H.265", profile="Main",
                                                           level="4.0", hdr_to_sdr=True, mastering_max_nits=1000.0,
                                                           max_cll=1000, audio_streams=[], strip_audio=True)))
    return out


def run():
    results = {}
    for tab, name, settings in cases():
        events, final = _run(settings, tab, name)
        results[name] = {"outcome": _outcome(events), "output": _summary(final),
                         "partial_left": os.path.exists(partial_path(final))}
    ok = report(f"real Mux / Encode jobs ({len(results)}) and their outputs", check_golden("jobs", results))

    long_enc = dict(cases()[2][2], input_file=fixture("long.mp4"), start_secs=0, duration_secs=0,
                    speed="veryslow", quality=10, audio_streams=[], strip_audio=True)
    events, final = _run(long_enc, "Encoding", "stopped.mp4", stop_after=1.5)
    problems = [p for p, bad in (("stop left the partial file", os.path.exists(partial_path(final))),
                                 ("stop created the final file", os.path.exists(final)),
                                 ("stop reported an end event", any(e[0] in ("done", "failed") for e in events)))
                if bad]
    ok &= report("stop() mid-run leaves nothing behind", problems)

    events, final = _run(dict(cases()[2][2], input_file=os.path.join(WORK, "missing.mp4")), "Encoding", "fail.mp4")
    failed = [e for e in events if e[0] == "failed"]
    ok &= report("a job that can't run fails with a reason",
                 [] if failed and failed[-1][1] else [f"events: {events}"])
    ok &= report("subtitles and chapters: tracks, cues, flags, trims, burn-in, chapters", subtitle_problems())
    return ok


# --------------------------------------------------------------------------- #
#  Subtitles and chapters
# --------------------------------------------------------------------------- #
def _sub(index=0, codec="subrip", language="eng", default=False, forced=False, source="primary", file=None,
         start_time=None):
    return {"source": source, "file": file, "index": index, "codec_name": codec, "language": language,
            "default": default, "forced": forced, "start_time": start_time}


def _cues(path, n):
    """Subtitle track `n` of `path` as "start-end" pairs (whole seconds), read back as SRT."""
    text = subprocess.run([tool_path("ffmpeg"), "-v", "error", "-i", path, "-map", f"0:s:{n}", "-f", "srt", "-"],
                          capture_output=True, text=True).stdout
    def secs(stamp):
        h, m, rest = stamp.strip().split(":")
        return round(int(h) * 3600 + int(m) * 60 + float(rest.replace(",", ".")))
    return [f"{secs(a)}-{secs(b)}" for a, b in (line.split("-->") for line in text.splitlines() if "-->" in line)]


def _tracks(path):
    """`[(codec, language, "default"/"forced" flags)]` for each subtitle track, and the chapters."""
    import json
    data = json.loads(subprocess.run(
        [tool_path("ffprobe"), "-v", "error", "-select_streams", "s", "-show_entries",
         "stream=codec_name:stream_disposition=default,forced:stream_tags=language", "-show_entries",
         "chapter=start_time,end_time:chapter_tags=title", "-of", "json", path], capture_output=True, text=True).stdout)
    tracks = [(s["codec_name"], (s.get("tags") or {}).get("language"),
               "+".join(f for f in ("default", "forced") if (s.get("disposition") or {}).get(f)) or "-")
              for s in data.get("streams", [])]
    chapters = [(round(float(c["start_time"])), round(float(c["end_time"])), (c.get("tags") or {}).get("title"))
                for c in data.get("chapters", [])]
    return tracks, chapters


def _bar(path, t, box):
    """The mean grey of `box` (x, y, w, h) at `t` seconds: 255 where the white bar is."""
    x, y, w, h = box
    raw = subprocess.run([tool_path("ffmpeg"), "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1", "-vf",
                          f"crop={w}:{h}:{x}:{y},scale=1:1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True).stdout
    return raw[0] if raw else None


def _strip_diff(a, ta, b, tb, rows=70):
    """Mean difference of the bottom `rows` rows of `a` at `ta` and `b` at `tb` (grey, 0-255):
    near 0 for the same picture, well above for one with a caption drawn in."""
    def strip(path, t):
        return subprocess.run([tool_path("ffmpeg"), "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1",
                               "-vf", f"crop=iw:{rows}:0:ih-{rows}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                              capture_output=True).stdout
    x, y = strip(a, ta), strip(b, tb)
    return round(sum(abs(p - q) for p, q in zip(x, y)) / max(1, len(x)), 1) if x and len(x) == len(y) else None


def subtitle_problems():
    subs, pgs, srt, sup = fixture("subs.mkv"), fixture("pgs.mkv"), fixture("subs.srt"), fixture("bar.sup")
    video = [{"source": "primary", "file": None, "index": 0}]
    chapters = [{"start": 0.0, "title": "Intro"}, {"start": 4.0, "title": "Main = best; #1"}]
    problems = []

    def expect(label, got, want):
        if got != want:
            problems.append(f"{label}: {got!r}, expected {want!r}")

    def run(name, settings, tab):
        events, final = _run(settings, tab, name)
        if not any(e[0] == "done" for e in events):
            problems.append(f"{name}: {events}")
        leftovers = [f for f in os.listdir(OUT) if f.startswith(os.path.splitext(name)[0] + ".partial")]
        if leftovers:
            problems.append(f"{name}: left behind {leftovers}")
        return final

    # Mux to .mp4, trimmed 2..7: the source's SRT (converted in place) and an external .srt (prepared:
    # cut by a copy first) both keep only the 5-8 cue, at 3-6; the edited chapters are shifted and cut.
    out = run("sub_mux_mp4_trim.mp4", {
        "input_file": subs, "output_format": ".mp4", "start_secs": 2, "duration_secs": 5, "video_tracks": video,
        "audio_tracks": [], "subtitle_tracks": [_sub(default=True), _sub(source="external", file=srt, language="fre")],
        "chapters": chapters, "source_duration": 10, "source_has_chapters": True}, "Muxing")
    tracks, chaps = _tracks(out)
    expect("mux mp4 tracks", tracks, [("mov_text", "eng", "default"), ("mov_text", "fre", "-")])
    expect("mux mp4 source cues", _cues(out, 0), ["3-6"])
    expect("mux mp4 external cues (prepared)", _cues(out, 1), ["3-6"])
    expect("mux mp4 chapters", chaps, [(0, 2, "Intro"), (2, 5, "Main = best; #1")])

    # Mux to .mkv, untrimmed: SRT and ASS copied with their own flags edited; the source's chapters.
    out = run("sub_mux_mkv.mkv", {
        "input_file": subs, "output_format": ".mkv", "video_tracks": video, "audio_tracks": [],
        "subtitle_tracks": [_sub(index=1, codec="ass", language="ger", forced=True), _sub(language="jpn")],
        "source_has_chapters": True}, "Muxing")
    tracks, chaps = _tracks(out)
    expect("mux mkv tracks", tracks, [("ass", "ger", "forced"), ("subrip", "jpn", "-")])
    expect("mux mkv cues", _cues(out, 1), ["1-3", "5-8"])
    expect("mux mkv chapters", chaps, [(0, 4, "Intro"), (4, 10, "Main")])

    # An external .sup, trimmed from 3s: its pictures (1-4, 6-8) must stay on their own timeline.
    out = run("sub_mux_sup.mkv", {
        "input_file": subs, "output_format": ".mkv", "start_secs": 3, "duration_secs": 6, "video_tracks": video,
        "audio_tracks": [], "subtitle_tracks": [_sub(source="external", file=sup, codec="hdmv_pgs_subtitle",
                                                     start_time=1.0)]}, "Muxing")
    packets = subprocess.run([tool_path("ffprobe"), "-v", "error", "-select_streams", "s", "-show_entries",
                              "packet=pts_time", "-of", "csv=p=0", out], capture_output=True, text=True).stdout.split()
    expect("mux .sup packet times (clear, show, clear)", [round(float(p)) for p in packets], [1, 3, 5])

    # Strip both.
    out = run("sub_mux_strip.mkv", {
        "input_file": subs, "output_format": ".mkv", "video_tracks": video, "audio_tracks": [],
        "subtitle_tracks": [_sub()], "strip_subtitles": True, "strip_chapters": True,
        "source_has_chapters": True}, "Muxing")
    expect("strip", _tracks(out), ([], []))

    encode = {"output_format": ".mp4", "encoder": "H.264", "speed": "ultrafast", "quality": 23,
              "strip_audio": True, "audio_streams": []}
    # Burn the source's SRT, trimmed from 3s: "Hello two" (5-8) is in the picture at 2-5, not at 1 or 5.5;
    # the ASS stays a (converted) track.
    out = run("sub_enc_burn_text.mp4", dict(encode, input_file=subs, start_secs=3, duration_secs=6,
                                            burn_subtitle={"source": "primary", "file": None, "index": 0, "image": False},
                                            subtitle_tracks=[_sub(index=1, codec="ass", language="spa", forced=True)],
                                            source_width=640, source_height=360), "Encoding")
    shown = [_strip_diff(out, t, subs, t + 3) for t in (1.0, 3.0, 5.5)]
    if None in shown or not (shown[1] > 4 * max(shown[0], shown[2], 0.5)):
        problems.append(f"burned text: bottom strip differs from the source by {shown} at 1 / 3 / 5.5s "
                        "(only 3s should show the line)")
    # MP4 marks the first track of a kind default when none is: Forced comes out default+forced.
    expect("burn text soft track", _tracks(out)[0], [("mov_text", "spa", "default+forced")])

    # Burn the picture track (1920x1080 canvas onto 1280x720): the bar is in the picture at 2 and 7.
    out = run("sub_enc_burn_pgs.mp4", dict(encode, input_file=pgs, source_width=1280, source_height=720,
                                           burn_subtitle={"source": "primary", "file": None, "index": 0,
                                                          "image": True, "width": 1920, "height": 1080}), "Encoding")
    bar = [_bar(out, t, (510, 642, 260, 36)) for t in (2.0, 5.0, 7.0)]
    if not (bar[0] == 255 and bar[2] == 255 and bar[1] is not None and bar[1] < 200):
        problems.append(f"burned picture bar grey {bar} at 2 / 5 / 7s (expected 255, lower, 255)")

    # A burn-in from a path with an apostrophe, brackets and a comma.
    odd_dir = os.path.join(WORK, "it's [odd], dir")
    os.makedirs(odd_dir, exist_ok=True)
    odd = os.path.join(odd_dir, "a;b.srt")
    with open(srt, "rb") as src, open(odd, "wb") as dst:
        dst.write(src.read())
    run("sub_enc_burn_odd_path.mkv", dict(encode, input_file=subs, output_format=".mkv", duration_secs=2,
                                          burn_subtitle={"source": "external", "file": odd, "index": 0, "image": False}),
        "Encoding")
    return problems


if __name__ == "__main__":
    run()
