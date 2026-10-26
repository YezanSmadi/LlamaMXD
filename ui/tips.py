# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Shared hover-tooltip copy for the codec and container / format dropdowns, so each reads the
same in every tab."""

SELECT_VIDEO_CODEC_TIP = "Pick which video codec to encode this file's video to."
SELECT_AUDIO_CODEC_TIP = "Pick which codec to encode this stream's audio to."
BEST_VIDEO_CODEC_TIP = "Uses whichever video codec this file's best-quality stream already has."
BEST_AUDIO_CODEC_TIP = "Uses whichever audio codec this file's best-quality stream already has."

VIDEO_CODEC_TIPS = {
    "H.264": "The most compatible codec. Plays everywhere at decent file sizes. The safe default unless you need better compression.",
    "H.265": "About 25-50% smaller than H.264 at the same quality, but slower to encode and less universally supported.",
    "MPEG-4": "An older, less efficient codec kept mainly for compatibility with legacy players.",
    "MPEG-2": "The old DVD/broadcast codec. Large files, but readable by the oldest hardware.",
    "VP8": "An older royalty-free web codec, superseded by VP9. Mostly for legacy WebM compatibility.",
    "VP9": "A royalty-free codec comparable to H.265. Good compression, slower to encode. Used by YouTube and the web.",
    "AV1": "The newest royalty-free codec. The best compression available, but the slowest to encode and needs a modern decoder.",
    "ProRes": "Apple's editing-friendly intermediate. Large, near-lossless, fast to decode. Its Profile choice sets quality, not a slider.",
    "DNxHR": "Avid's editing-friendly intermediate, Its Profile choice sets quality, not a slider.",
    "FFV1": "Lossless and open format. Used for archival masters. No profile, level, or quality slider; just very large files.",
    "CineForm": "GoPro's editing-friendly intermediate — its Profile dropdown is really a quality-preset ladder, not a lossy slider.",
}

AUDIO_CODEC_TIPS = {
    "AAC": "The standard lossy codec for MP4 and streaming. Efficient and broadly compatible.",
    "AC3": "Dolby Digital. The common surround codec for DVDs and home theater gear.",
    "E-AC-3": "Dolby Digital Plus. AC3's successor, with more channels and better efficiency.",
    "MP3": "The oldest, most universally compatible lossy codec. Less efficient than AAC or Opus at the same bitrate.",
    "FLAC": "Lossless; exact audio quality, larger files than any lossy codec.",
    "Opus": "The most efficient lossy codec available. The best quality per bit, used across streaming and WebM.",
    "Vorbis": "An older open lossy codec, superseded by Opus. Mostly for legacy Ogg/WebM compatibility.",
    "ALAC": "Apple's lossless codec. The same quality as FLAC, for Apple-ecosystem compatibility.",
    "PCM": "Uncompressed audio. Exact quality at the largest possible file size.",
    "DTS": "Surround-sound codec common on DVDs and Blu-rays. Always passed through untouched.",
    "Dolby TrueHD": "Lossless surround codec used on Blu-rays, often carrying Dolby Atmos. Always passed through untouched.",
}

# Output-container dropdowns (Muxing / Encoding's Output Format, the Downloader's Video Format).
CONTAINER_TIPS = {
    ".mp4": "The most compatible video container. Plays everywhere. Holds H.264/H.265/MPEG-4/MPEG-2/AV1.",
    ".mkv": "The permissive catch-all container. Holds any codec this app supports, video or audio.",
    ".mov": "QuickTime's native container. The right choice for the ProRes/DNxHR/CineForm editing intermediates.",
    ".webm": "The open web container. VP8/VP9/AV1 video with Opus/Vorbis audio only.",
}

# The Downloader's Audio Only Format: a conversion, so it has its own copy.
AUDIO_FORMAT_TIPS = {
    "Original": "Keeps the source audio stream exactly as served. No re-encoding, fastest and highest fidelity.",
    ".mp3": "The most compatible lossy audio format.",
    ".m4a": "AAC audio in an MP4 container. Efficient, plays natively on Apple devices.",
    ".opus": "The most efficient lossy format available. Smaller files at the same quality.",
    ".flac": "Lossless; exact audio quality. A larger file than any lossy conversion.",
    ".wav": "Uncompressed; exact quality. The largest possible file size.",
}

# The subtitle track editors (Muxing's Edit Subs popup, Encoding's Subtitles page).
SUBTITLE_TRACK_TIP = "The subtitle track that the Language, Default and Forced settings edit."
LANGUAGE_TIP = "The track's language tag, which players use to pick a subtitle track."
DEFAULT_TIP = "Players show this track unless told otherwise. Only one track can be the default."
STREAM_TRACK_TIP = "The track the Default setting edits."
STREAM_DEFAULT_TIP = ("Players use this track unless the viewer picks another. "
                      "Only one track of a kind can be the default.")
FORCED_TIP = "Marks the track as forced; only foreign-language dialogue and signs. Shown even with subtitles off."
