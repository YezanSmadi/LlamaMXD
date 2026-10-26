# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Golden command lines: the exact ffmpeg argv for a spread of Mux / Encode settings, and the
yt-dlp plan + argv for every combination of the Downloader's dropdowns on a stand-in format
list. Machine-dependent answers (ffmpeg's -fps_mode support, libplacebo, the GPU) are pinned so
the goldens are identical everywhere."""
import copy

from harness import check_golden, report

from core import downloader, ffmpeg_build, ffmpeg_vars, gpu

# Pinned capabilities: a current ffmpeg with libplacebo, and an NVIDIA GPU with NVENC.
ffmpeg_build.supports_fps_mode = lambda: True
ffmpeg_build.supports_libplacebo = lambda: True
gpu.vendor = lambda: "nvidia"
gpu.available_encoders = lambda: {"h264_nvenc", "hevc_nvenc", "av1_nvenc"}
downloader.deno_path = lambda: "C:/tools/deno.exe"
downloader.tool_dir = lambda name: "C:/tools"
downloader.tool_path = lambda name: f"<{name}>"

IN, OUT = "C:/in/clip.mkv", "C:/out/clip.mp4"


def _sub(index=0, codec="subrip", language="eng", default=False, forced=False, source="primary", file=None,
         start_time=None):
    return {"source": source, "file": file, "index": index, "codec_name": codec, "language": language,
            "default": default, "forced": forced, "start_time": start_time}


CHAPTERS = [{"start": 0.0, "title": "Intro"}, {"start": 40.0, "title": "Main: part = 1"}]


def _audio(index=0, codec="AAC", bitrate="192 kbps", channels="Stereo", rate="48000 Hz",
           passthru=False, language="eng", source="primary", file=None):
    return {"id": f"src:{index}", "source": source, "file": file, "index": index, "codec": codec,
            "bitrate": bitrate, "channels": channels, "sample_rate": rate, "passthru": passthru,
            "language": language}


ENCODE_BASE = {
    "input_file": IN, "output_path": OUT, "output_format": ".mp4", "start_secs": 0,
    "duration_secs": 0, "av_sync": True, "encoder": "H.264", "profile": "High", "level": "4.0",
    "speed": "medium", "quality": 22, "resolution": "Source", "source_height": 1080, "fps": "Source",
    "source_fps": 29.97, "gpu_enabled": False, "hdr_to_sdr": False, "mastering_max_nits": None,
    "max_cll": None, "strip_video": False, "strip_audio": False, "audio_streams": [_audio()],
}


def encode(name, **changes):
    s = copy.deepcopy(ENCODE_BASE)
    s.update(changes)
    return name, s


ENCODE_CASES = [
    encode("h264_basic"),
    encode("trimmed", start_secs=65, duration_secs=10),
    encode("no_av_sync", av_sync=False),
    encode("h265_main10", encoder="H.265", profile="Main 10", level="5.1", speed="slow", quality=18,
           output_path="C:/out/clip.mkv", output_format=".mkv"),
    encode("h264_gpu", gpu_enabled=True),
    encode("h265_gpu", encoder="H.265", profile="Main", level="4.1", gpu_enabled=True),
    encode("av1_software", encoder="AV1", profile="Main", level="5.0", speed="8", quality=30,
           output_path="C:/out/clip.mkv", output_format=".mkv"),
    encode("av1_gpu", encoder="AV1", profile="Main", level="5.0", speed="8", quality=60, gpu_enabled=True,
           output_path="C:/out/clip.mkv", output_format=".mkv"),
    encode("vp9_webm", encoder="VP9", profile="0", level="", speed="4", quality=32,
           output_path="C:/out/clip.webm", output_format=".webm",
           audio_streams=[_audio(codec="Opus", bitrate="128 kbps")]),
    encode("vp8_webm", encoder="VP8", profile="", level="", speed="2", quality=10,
           output_path="C:/out/clip.webm", output_format=".webm",
           audio_streams=[_audio(codec="Vorbis", bitrate="192 kbps")]),
    encode("mpeg2", encoder="MPEG-2", profile="Main", level="High", speed="", quality=4,
           output_path="C:/out/clip.mkv", output_format=".mkv", audio_streams=[_audio(codec="AC3")]),
    encode("mpeg4", encoder="MPEG-4", profile="Advanced Simple", level="", speed="", quality=5),
    encode("prores_hq", encoder="ProRes", profile="422 HQ", level="", speed="", quality=None,
           output_path="C:/out/clip.mov", output_format=".mov",
           audio_streams=[_audio(codec="PCM", bitrate="")]),
    encode("dnxhr_hqx", encoder="DNxHR", profile="HQX", level="", speed="", quality=None,
           output_path="C:/out/clip.mov", output_format=".mov"),
    encode("cineform", encoder="CineForm", profile="Film 3+", level="", speed="", quality=None,
           output_path="C:/out/clip.mov", output_format=".mov"),
    encode("ffv1_flac", encoder="FFV1", profile="", level="", speed="", quality=None,
           output_path="C:/out/clip.mkv", output_format=".mkv",
           audio_streams=[_audio(codec="FLAC", bitrate="")]),
    encode("downscale_retime", resolution="720p", fps="23.976"),
    encode("upscale_ignored", resolution="2160p", fps="60", source_height=720, source_fps=30),
    encode("hdr_to_sdr_trusted", encoder="H.265", profile="Main", level="5.0", hdr_to_sdr=True,
           mastering_max_nits=1000.0, max_cll=1000, source_height=2160, resolution="1080p"),
    encode("hdr_to_sdr_peak_detect", encoder="H.265", profile="Main", level="5.0", hdr_to_sdr=True,
           mastering_max_nits=4000.0, max_cll=0),
    encode("strip_audio", strip_audio=True, audio_streams=[]),
    encode("strip_video", strip_video=True, output_path="C:/out/clip.m4a", output_format=".mp4",
           audio_streams=[_audio(codec="AAC", bitrate="256 kbps")]),
    encode("multi_audio", output_path="C:/out/clip.mkv", output_format=".mkv", audio_streams=[
        _audio(index=1, codec="Dolby TrueHD", passthru=True, language="eng"),
        _audio(index=0, codec="Opus", bitrate="128 kbps", channels="5.1", rate="48000 Hz", language="jpn"),
        dict(_audio(index=0, codec="AAC", bitrate="96 kbps", channels="Mono", language="fre",
                    source="external", file="C:/in/extra.m4a"), id="ext:12345678"),
    ]),
    encode("trimmed_passthru", start_secs=65, duration_secs=10, output_path="C:/out/clip.mkv",
           output_format=".mkv", audio_streams=[_audio(index=0, passthru=True),
                                                _audio(index=1, codec="Opus", language="jpn")]),
    encode("external_first_video_stripped", strip_video=True, output_path="C:/out/clip.mka",
           output_format=".mkv", audio_streams=[
               dict(_audio(index=0, passthru=True, source="external", file="C:/in/extra.m4a"), id="ext:1"),
               _audio(index=1, passthru=True, language="jpn"),
           ]),
    encode("subtitles_mp4", subtitle_tracks=[_sub(default=True), _sub(index=1, codec="ass", language="spa", forced=True)]),
    encode("subtitles_webm_trimmed_external", output_path="C:/out/clip.webm", output_format=".webm", encoder="VP9",
           profile="0", level="", speed="4", audio_streams=[_audio(codec="Opus")], start_secs=30, duration_secs=20,
           subtitle_tracks=[_sub(), _sub(source="external", file="C:/in/extra.srt", language="fre")]),
    encode("burn_text_trimmed", start_secs=30, source_start=0.5,
           burn_subtitle={"source": "primary", "file": None, "index": 1, "image": False}),
    encode("burn_external_text_hdr_scaled", hdr_to_sdr=True, resolution="720p",
           burn_subtitle={"source": "external", "file": "C:/in/it's [dir]/a,b;c.srt", "index": 0, "image": False}),
    encode("burn_image_scaled", output_format=".mkv", output_path="C:/out/clip.mkv", source_width=1280,
           source_height=720, resolution="480p", burn_subtitle={"source": "primary", "file": None, "index": 0,
                                                              "image": True, "width": 1920, "height": 1080}),
    encode("burn_image_video_stripped", strip_video=True, output_path="C:/out/clip.m4a",
           burn_subtitle={"source": "primary", "file": None, "index": 0, "image": True}),
    encode("chapters_edited_trimmed", start_secs=30, duration_secs=60, source_duration=600, chapters=CHAPTERS),
    encode("chapters_all_trimmed_away", start_secs=100, source_duration=50, chapters=CHAPTERS[:1]),
    encode("chapters_spanning_trim", start_secs=100, source_duration=600, chapters=CHAPTERS[:1]),
    encode("strip_subtitles_chapters", strip_subtitles=True, strip_chapters=True, subtitle_tracks=[_sub()]),
]

MUX_BASE = {
    "input_file": IN, "output_path": OUT, "output_format": ".mp4", "start_secs": 0, "duration_secs": 0,
    "av_sync": True, "video_tracks": [{"source": "primary", "file": None, "index": 0}],
    "strip_video": False, "audio_tracks": [{"source": "primary", "file": None, "index": 0}],
    "strip_audio": False,
}


def mux(name, **changes):
    s = copy.deepcopy(MUX_BASE)
    s.update(changes)
    return name, s


MUX_CASES = [
    mux("basic"),
    mux("trimmed", start_secs=30, duration_secs=5),
    mux("mkv_reordered_audio", output_path="C:/out/clip.mkv", output_format=".mkv", audio_tracks=[
        {"source": "primary", "file": None, "index": 2}, {"source": "primary", "file": None, "index": 0}]),
    mux("external_tracks", output_path="C:/out/clip.mkv", output_format=".mkv", audio_tracks=[
        {"source": "primary", "file": None, "index": 0},
        {"source": "external", "file": "C:/in/dub.m4a", "index": 0},
        {"source": "external", "file": "C:/in/dub.m4a", "index": 1}]),
    mux("strip_audio", strip_audio=True, audio_tracks=[]),
    mux("strip_video", strip_video=True, video_tracks=[], output_path="C:/out/clip.m4a"),
    mux("subtitles_mkv_trimmed_externals", output_path="C:/out/clip.mkv", output_format=".mkv", start_secs=30,
        duration_secs=5, subtitle_tracks=[
            _sub(default=True), _sub(index=1, codec="mov_text", language="ger"),
            _sub(source="external", file="C:/in/sub.sup", codec="hdmv_pgs_subtitle", start_time=1.0),
            _sub(source="external", file="C:/in/sub.srt", forced=True)]),
    mux("subtitles_mp4_trimmed_external_prepared", start_secs=30, duration_secs=5, subtitle_tracks=[
        _sub(), _sub(source="external", file="C:/in/sub.ass", codec="ass", language="jpn")]),
    mux("picture_subtitle_in_mp4_dropped", subtitle_tracks=[_sub(codec="hdmv_pgs_subtitle")]),
    mux("chapters_source_with_external", source_has_chapters=True, audio_tracks=[
        {"source": "external", "file": "C:/in/dub.m4a", "index": 0}]),
    mux("chapters_edited", chapters=CHAPTERS, source_duration=600),
    mux("default_flags", output_path="C:/out/clip.mkv", output_format=".mkv",
        video_tracks=[{"source": "primary", "file": None, "index": 0, "default": True}],
        audio_tracks=[{"source": "primary", "file": None, "index": 0, "default": False},
                      {"source": "primary", "file": None, "index": 1, "default": True},
                      {"source": "external", "file": "C:/in/dub.m4a", "index": 0, "default": False}]),
]


def ffmpeg_commands():
    out = {}
    for tab, cases in (("Encoding", ENCODE_CASES), ("Muxing", MUX_CASES)):
        for name, settings in cases:
            job = ffmpeg_vars.derive(settings, tab)
            try:
                argv = ffmpeg_build.compile_command(job, "C:/out/temp.partial.mp4")
                out[f"{tab}/{name}"] = {"argv": argv, "hdr_tonemap": ffmpeg_build.uses_hdr_tonemap(job)}
                prepare = ffmpeg_build.prepare_commands(job, "C:/out/temp.partial.mp4")
                if prepare:
                    out[f"{tab}/{name}"]["prepare"] = [{"argv": a, "path": p} for a, p in prepare]
            except Exception as exc:        # a refusal is a result too
                out[f"{tab}/{name}"] = {"error": f"{type(exc).__name__}: {exc}"}
    out["Encoding/h264_basic@detailed"] = ffmpeg_build.compile_command(
        ffmpeg_vars.derive(ENCODE_CASES[0][1], "Encoding"), "C:/out/t.mp4", loglevel="level+info")
    return out


# A stand-in for `yt-dlp -J` on a YouTube video: H.264 / VP9 / AV1 at several heights, an HDR
# VP9 rung, AAC and Opus audio (plus a DRC duplicate and a storyboard, which must be dropped),
# and one combined format.
def _fmt(fid, ext, vcodec, acodec, height=None, fps=None, tbr=0, abr=None, size=None, hdr=False):
    return {"format_id": fid, "ext": ext, "vcodec": vcodec, "acodec": acodec, "height": height,
            "width": height and height * 16 // 9, "fps": fps, "tbr": tbr, "abr": abr, "filesize": size,
            "dynamic_range": "HDR10" if hdr else "SDR"}


YT_INFO = {
    "id": "fixture", "title": "Fixture: A / Video?", "duration": 213, "extractor_key": "Youtube",
    "webpage_url_domain": "youtube.com", "upload_date": "20240305", "formats": [
        {"format_id": "sb0", "ext": "mhtml", "vcodec": "images", "acodec": "none"},
        _fmt("139", "m4a", "none", "mp4a.40.5", tbr=49, abr=49),
        _fmt("249", "webm", "none", "opus", tbr=53, abr=53),
        _fmt("140-drc", "m4a", "none", "mp4a.40.2", tbr=129, abr=129),
        _fmt("140", "m4a", "none", "mp4a.40.2", tbr=129, abr=129, size=3441000),
        _fmt("251", "webm", "none", "opus", tbr=135, abr=135),
        _fmt("18", "mp4", "avc1.42001E", "mp4a.40.2", 360, 30, tbr=500),
        _fmt("134", "mp4", "avc1.4d401e", "none", 360, 30, tbr=300),
        _fmt("243", "webm", "vp9", "none", 360, 30, tbr=280),
        _fmt("136", "mp4", "avc1.4d401f", "none", 720, 30, tbr=1200),
        _fmt("247", "webm", "vp9", "none", 720, 30, tbr=1000),
        _fmt("398", "mp4", "av01.0.05M.08", "none", 720, 30, tbr=900),
        _fmt("137", "mp4", "avc1.640028", "none", 1080, 30, tbr=2500),
        _fmt("248", "webm", "vp9", "none", 1080, 30, tbr=2200),
        _fmt("299", "mp4", "avc1.64002a", "none", 1080, 60, tbr=4000),
        _fmt("303", "webm", "vp9", "none", 1080, 60, tbr=3500),
        _fmt("399", "mp4", "av01.0.08M.08", "none", 1080, 30, tbr=1800),
        _fmt("337", "webm", "vp09.02.51.10", "none", 2160, 60, tbr=18000, hdr=True),
        _fmt("401", "mp4", "av01.0.12M.08", "none", 2160, 30, tbr=9000),
    ],
}


def download_tree():
    """Every Mode x Video Codec x Resolution x Format (x Audio Codec) the dropdowns can reach,
    with the resolved plan and the full argv."""
    fmts = downloader.parse_formats(YT_INFO)
    tree = {"parsed": fmts, "modes": downloader.modes_for(fmts), "plans": {}}
    for mode in downloader.modes_for(fmts):
        for codec in downloader.codecs_for(fmts, mode):
            if mode == downloader.MODE_AUDIO:
                combos = [(q, c, downloader.BEST_CODEC)
                          for c in downloader.formats_for(fmts, mode, codec, None)
                          for q in downloader.qualities_for(fmts, mode, codec, c) or [None]]
            else:
                combos = []
                for q in downloader.qualities_for(fmts, mode, codec):
                    audio_codecs = (downloader.audio_codecs_for(fmts, mode, codec, q)
                                    if mode == downloader.MODE_AV else [downloader.BEST_CODEC])
                    for a in audio_codecs:
                        for c in downloader.formats_for(fmts, mode, codec, q, a):
                            combos.append((q, c, a))
            for quality, container, audio_codec in combos:
                plan = downloader.resolve(fmts, mode, codec, quality, container, YT_INFO["duration"], audio_codec)
                key = f"{mode} | {codec} | {quality} | {container} | {audio_codec}"
                tree["plans"][key] = {"plan": plan, "argv": plan and downloader.build_download_args(
                    plan, "https://www.youtube.com/watch?v=fixture", "C:/out/.work")}
    tree["defaults"] = {m: downloader.default_format(m, downloader.formats_for(
        fmts, m, downloader.BEST_CODEC, downloader.BEST_QUALITY)) for m in downloader.modes_for(fmts)}
    tree["safe_stem"] = downloader.safe_stem(YT_INFO["title"])
    return tree


def run():
    ok = report("ffmpeg command lines (Mux / Encode)", check_golden("commands_ffmpeg", ffmpeg_commands()))
    tree = download_tree()
    ok &= report(f"yt-dlp plans + argv ({len(tree['plans'])} dropdown combinations)",
                 check_golden("commands_ytdlp", tree))
    return ok


if __name__ == "__main__":
    run()
