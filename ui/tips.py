# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Shared hover-tooltip copy for the codec and container / format dropdowns, so each reads the
same in every tab."""

SELECT_VIDEO_CODEC_TIP = "Pick which video codec to encode this file's video to."
SELECT_AUDIO_CODEC_TIP = "Pick which codec to encode this stream's audio to."
BEST_VIDEO_CODEC_TIP = "Uses whichever video codec this video's best-quality stream already has."
BEST_AUDIO_CODEC_TIP = "Uses whichever audio codec this video's best-quality stream already has."

VIDEO_CODEC_TIPS = {
    "H.264": "The most compatible codec — plays everywhere at decent file sizes. The safe default unless you need better compression.",
    "H.265": "About 25-50% smaller than H.264 at the same quality, but slower to encode and less universally supported.",
    "MPEG-4": "An older, less efficient codec kept mainly for compatibility with legacy players.",
    "MPEG-2": "The old DVD/broadcast codec — large files, but readable by the oldest hardware.",
    "VP8": "An older royalty-free web codec, superseded by VP9 — mostly for legacy WebM compatibility.",
    "VP9": "A royalty-free codec comparable to H.265 — good compression, slower to encode. Used by YouTube and the web.",
    "AV1": "The newest royalty-free codec — the best compression available, but the slowest to encode and needs a modern decoder.",
    "ProRes": "Apple's editing-friendly intermediate — large, near-lossless, fast to decode. Its Profile choice sets quality, not a slider.",
    "DNxHR": "Avid's editing-friendly intermediate, the same role as ProRes. Its Profile choice sets quality, not a slider.",
    "FFV1": "Truly lossless and open — used for archival masters. No profile, level, or quality slider; just very large files.",
    "CineForm": "GoPro's editing-friendly intermediate — its Profile dropdown is really a quality-preset ladder, not a lossy slider.",
}

AUDIO_CODEC_TIPS = {
    "AAC": "The standard lossy codec for MP4 and streaming — efficient and broadly compatible.",
    "AC3": "Dolby Digital — the common surround codec for DVDs and home theater gear.",
    "E-AC-3": "Dolby Digital Plus — AC3's successor, with more channels and better efficiency.",
    "MP3": "The oldest, most universally compatible lossy codec — less efficient than AAC or Opus at the same bitrate.",
    "FLAC": "Lossless — exact audio quality, larger files than any lossy codec.",
    "Opus": "The most efficient lossy codec available — the best quality per bit, used across streaming and WebM.",
    "Vorbis": "An older open lossy codec, superseded by Opus — mostly for legacy Ogg/WebM compatibility.",
    "ALAC": "Apple's lossless codec — the same quality as FLAC, for Apple-ecosystem compatibility.",
    "PCM": "Uncompressed audio — exact quality at the largest possible file size.",
    "DTS": "A surround codec this app can't re-encode — always passed through untouched.",
    "Dolby TrueHD": "A lossless surround/Atmos codec this app can't re-encode — always passed through untouched.",
}

# Output-container dropdowns (Muxing / Encoding's Output Format, the Downloader's Video Format).
CONTAINER_TIPS = {
    ".mp4": "The most compatible video container — plays everywhere, holds H.264/H.265/MPEG-4/MPEG-2/AV1.",
    ".mkv": "The permissive catch-all container — holds any codec this app supports, video or audio.",
    ".mov": "QuickTime's native container — the right choice for the ProRes/DNxHR/CineForm editing intermediates.",
    ".webm": "The open web container — VP8/VP9/AV1 video with Opus/Vorbis audio only.",
}

# The Downloader's Audio Only Format: a conversion, so it has its own copy.
AUDIO_FORMAT_TIPS = {
    "Original": "Keeps the source audio stream exactly as served — no re-encoding, fastest and highest fidelity.",
    ".mp3": "The most compatible lossy audio format.",
    ".m4a": "AAC audio in an MP4 container — efficient, plays natively on Apple devices.",
    ".opus": "The most efficient lossy format available — smaller files at the same quality.",
    ".flac": "Lossless — exact audio quality, a larger file than any lossy conversion.",
    ".wav": "Uncompressed — exact quality, the largest possible file size.",
}

# The subtitle track editors (Muxing's Edit Subs popup, Encoding's Subtitles page).
SUBTITLE_TRACK_TIP = "The subtitle track the Language, Default and Forced settings edit."
LANGUAGE_TIP = "The track's language tag, which players use to pick a subtitle track."
DEFAULT_TIP = "Players show this track unless told otherwise. Only one track can be the default."
FORCED_TIP = "Marks the track as forced: only foreign-language dialogue and signs, shown even with subtitles off."
