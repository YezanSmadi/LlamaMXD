# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Real jobs: Mux and Encode settings run through ffmpeg_vars -> ffmpeg_build -> FfmpegJob on the
fixture clips, and their outputs probed (golden). Also: stop() mid-run leaves nothing behind,
and a job that can't run fails with a readable reason. (Downloads need the network: not here.)

Known issue recorded in the golden (fix it, then --update): an Encode with a trim and a Passthru
audio track puts the copied track ~1s ahead of the re-encoded streams (enc_multi_audio.mkv's
stream_starts)."""
import os
import time

from harness import WORK, check_golden, fixture, report

from core import ffmpeg_build, ffmpeg_vars, utilities
from core.ffmpeg_runner import FfmpegJob, partial_path

OUT = os.path.join(WORK, "jobs")
os.makedirs(OUT, exist_ok=True)


def _run(settings, tab, name, stop_after=None):
    """Run one job to its end (or stop it after `stop_after` s); `(events, output path)`."""
    final = os.path.join(OUT, name)
    for path in (final, partial_path(final)):
        if os.path.exists(path):
            os.remove(path)
    settings = dict(settings, output_path=final)
    ffmpeg_vars.load(settings, tab)
    job = FfmpegJob(ffmpeg_build.compile_command(partial_path(final)), final, partial_path(final),
                    duration_secs=settings.get("duration_secs") or 0, input_file=settings["input_file"],
                    start_secs=settings.get("start_secs") or 0, verify_hdr_tag=ffmpeg_build.uses_hdr_tonemap(),
                    label=name)
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
    info = utilities.probe_media(path)
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
    ]
    if utilities.supports_libplacebo():
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
    return ok


if __name__ == "__main__":
    run()
