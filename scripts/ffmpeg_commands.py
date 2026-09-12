import threading
import ffmpeg
from core import ffmpeg_vars as v


def trim_kwargs():
    input_kwargs = {"ss": v.START_TIME} if v.START_TIME else {}
    output_kwargs = {"t": v.DURATION_TIME} if v.DURATION_TIME else {}
    return input_kwargs, output_kwargs

#Muxing
def build_mux_command():
    input_kwargs, output_kwargs = trim_kwargs()
    primary = ffmpeg.input(v.INPUT_FILE **input_kwargs)

    streams = []
    if not v.STRIP_VIDEO:
        if v.VIDEO_TRACK_FILE:
            streams.append(ffmpeg.input(v.INPUT_FILE **input_kwargs)["v"])
        elif v.VIDEO_TRACK_INDEX is not None:
            streams.append(primary[f"v:{v.VIDEO_TRACK_INDEX}"])
        else:
            streams.append(primary["v"])
    if not v.STRIP_AUDIO:
        if v.AUDIO_TRACK:
            streams.append(ffmpeg.input(v.AUDIO_TRACK_FILE, **input_kwargs)["a"])
        elif v.AUDIO_TRACK_INDEX is not None:
            streams.append(primary[f"a:{v.AUDIO_TRACK_INDEX}"])
        else:
            streams.append(primary["a"])
    output_kwargs["c"] = "copy"
    output_kwargs["movflags"] = "+faststart"

    return ffmpeg.output(*streams, v.OUTPUT_PATH, **output_kwargs).overwrite_output()


# Encoding
def build_encode_command():
    input_kwargs, output_kwargs = trim_kwargs()
    primary = ffmpeg.input(v.INPUT_FILE **input_kwargs)

    if v.STRIP_VIDEO:
        output_kwargs["vn"] = None
    else:
        output_kwargs["c:v"] = v.VIDEO_CODEC_ARG
        if v.QUALITY_KIND == "crf":
            output_kwargs["crf"] = v.QUALITY
        elif v.QUALITY_KIND == "qscale":
            output_kwargs["q:v"] = v.QUALITY
        if v.PROFILE_ARG:
            output_kwargs["profile:v"] = v.PROFILE_ARG
        if v.LEVEL_ARG:
            output_kwargs["level:v"] = v.LEVEL_ARG
        # if v.HDR_TO_SDR
        #     TO DO
    
    if v.STRIP_AUDIO:
        output_kwargs["an"] = None
    else:
        output_kwargs["c:a"] = v.AUDIO_CODEC_ARG
        if v.AUDIO_BITRATE_ARG:
            output_kwargs["b:a"] = v.AUDIO_BITRATE_ARG
        if v.AUDIO_CHANNELS_ARG:
            output_kwargs["ac"] = v.AUDIO_CHANNELS_ARG
        if v.AUDIO_SAMPLE_RATE_ARG:
            output_kwargs["ar"] = v.AUDIO_SAMPLE_RATE_ARG

    output_kwargs["movflags"] = "+faststart"

    return ffmpeg.output(primary, v.OUTPUT_PATH, **output_kwargs).overwrite_output()

def build_comand():
    if v.SOURCE_TAB == "Muxing":
        return build_mux_command()
    return build_encode_command()


    # (
    #     ffmpeg
    #     .input(v.INPUT_FILE)
    #     .output(
    #         v.OUTPUT_PATH
    #         **{"c:a": v.AUDIO_CODEC_ARG, "c:v": v.VIDEO_CODEC_ARG, "crf": v.QUALITY,
    #         "movflags": "faststart", "t": v.DURATION_TIME},
    #     )
    #     .overwrite_output()
    #     .run()
    # )









