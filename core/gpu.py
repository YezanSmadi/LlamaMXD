"""GPU vendor detection and hardware-encoder selection for the Settings
tab's Hardware Acceleration switch.

No UI code here -- `ui/tabs/settings.py` reads `display_name()` /
`summary_label()` for the system-info block, and `core/ffmpeg_vars.derive()`
reads `hw_encoder_for()` to swap in a hardware encoder id when the switch is
on. Every lookup is best-effort and caches as "nothing found" on failure --
the same "guess False, never break a job" posture as `core.utilities.
supports_fps_mode`/`supports_libplacebo`, so a machine with no supported GPU
(or an ffmpeg build missing the encoder) just silently keeps encoding in
software, exactly as if the switch were off.
"""
import re
import subprocess

from core.tools import tool_path

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# When a machine has more than one adapter -- an NVIDIA discrete GPU
# alongside an AMD or Intel integrated one, a real configuration confirmed
# on this app's own dev machine (see CLAUDE.md's libplacebo/Vulkan section)
# -- the discrete GPU is almost always the faster, more capable encoder, so
# NVENC wins over AMF over QSV whenever more than one vendor is present.
_VENDOR_PRIORITY = ["nvidia", "amd", "intel"]

_VENDOR_MARKERS = {
    "nvidia": ("nvidia", "geforce", "quadro", "rtx", "gtx"),
    "amd": ("amd", "radeon", "ati "),
    "intel": ("intel",),
}

# Display codec name (formats.VIDEO_ENCODERS) -> {vendor: ffmpeg encoder id}.
# Limited to the three codecs every vendor's consumer-grade hardware encoder
# actually supports -- VP8/VP9 and the mezzanine intermediates (ProRes/
# DNxHR/CineForm/FFV1) have spotty-to-nonexistent hardware encode support
# and are left running in software, same as before this existed.
_HW_ENCODERS = {
    "H.264": {"nvidia": "h264_nvenc", "amd": "h264_amf", "intel": "h264_qsv"},
    "H.265": {"nvidia": "hevc_nvenc", "amd": "hevc_amf", "intel": "hevc_qsv"},
    "AV1": {"nvidia": "av1_nvenc", "amd": "av1_amf", "intel": "av1_qsv"},
}

# Each vendor's own marketing name for its hardware encoder block, for
# `summary_label` -- "NVENC"/"Quick Sync"/"AMF" tells a user what's about to
# run far better than a generic "hardware encoding".
_ENCODER_BRAND = {"nvidia": "NVENC", "amd": "AMF", "intel": "Quick Sync"}

_vendor = None          # None = not checked yet; "" = checked, none found
_adapter_names = None
_available_encoders = None


def _query_adapter_names():
    """Every video controller's display name, via WMI -- wmic first (present
    on every Windows 10 box this app targets), PowerShell's CIM cmdlet as a
    fallback for a build where wmic has been removed (Microsoft has been
    deprecating it since Windows 11 22H2)."""
    for cmd in (
        ["wmic", "path", "win32_VideoController", "get", "name"],
        ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name"],
    ):
        try:
            completed = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        lines = [ln.strip() for ln in (completed.stdout or "").splitlines()]
        names = [ln for ln in lines if ln and ln.lower() != "name"]
        if names:
            return names
    return []


def adapter_names():
    """Every detected GPU's display name, cached for the process's
    lifetime (the hardware doesn't change while the app is running)."""
    global _adapter_names
    if _adapter_names is None:
        _adapter_names = _query_adapter_names()
    return _adapter_names


def vendor():
    """"nvidia" / "amd" / "intel" / "" (nothing recognised) -- whichever
    vendor's marker appears first in `_VENDOR_PRIORITY` among the detected
    adapter names. Cached; a WMI failure caches as "" (no hardware path),
    never raises."""
    global _vendor
    if _vendor is None:
        found = set()
        for name in adapter_names():
            low = name.lower()
            for v, markers in _VENDOR_MARKERS.items():
                if any(m in low for m in markers):
                    found.add(v)
        _vendor = next((v for v in _VENDOR_PRIORITY if v in found), "")
    return _vendor


def display_name():
    """The GPU name for the Settings system-info block: the vendor this app
    would actually accelerate with if there's a supported one, else just the
    first detected adapter (a plain integrated GPU is still worth showing
    even with no usable hardware encoder), else a placeholder."""
    names = adapter_names()
    if not names:
        return "Unknown GPU"
    v = vendor()
    if v:
        for name in names:
            if any(m in name.lower() for m in _VENDOR_MARKERS[v]):
                return name
    return names[0]


def _query_available_encoders():
    try:
        completed = subprocess.run(
            [tool_path("ffmpeg"), "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW,
        )
        return set(re.findall(r"\s([a-z0-9]+_(?:nvenc|qsv|amf))\s", completed.stdout or ""))
    except (OSError, subprocess.SubprocessError):
        return set()


def available_encoders():
    """Every hardware encoder id this ffmpeg build actually has compiled in
    (`ffmpeg -encoders`), cached like `core.utilities.supports_fps_mode`.
    Being *listed* here doesn't guarantee it runs on this particular GPU
    (same caveat documented on supports_libplacebo) -- it only stops the
    switch from pointing at an encoder id this build has never heard of."""
    global _available_encoders
    if _available_encoders is None:
        _available_encoders = _query_available_encoders()
    return _available_encoders


def hw_encoder_for(codec):
    """The hardware encoder id for `codec` (a formats.VIDEO_ENCODERS display
    name) on this machine's detected GPU, or None when there's no supported
    vendor, no hardware encoder for that codec, or this ffmpeg build doesn't
    have it compiled in -- any of which means "fall back to software",
    silently, the same posture as every other capability check in this app."""
    v = vendor()
    if not v:
        return None
    encoder = _HW_ENCODERS.get(codec, {}).get(v)
    if encoder and encoder in available_encoders():
        return encoder
    return None


def rate_control_kwargs(hw_encoder, quality):
    """Output kwargs standing in for -crf on a hardware encoder -- each
    vendor's family exposes rate control through a completely different
    flag, and none of them is named -crf:
      NVENC: -rc vbr -cq <q>             constant-quality VBR, 0=best/51=worst
      QSV:   -global_quality <q>         switches the qsv wrapper to ICQ mode
      AMF:   -rc cqp -qp_i/-qp_p/-qp_b   constant QP, 0=best/51=worst
    All three cap out well below AV1's own 0-63 CRF range (SVT-AV1's, not any
    hardware encoder's), so the UI's quality value is clamped to 51 here
    rather than handed through unchanged."""
    q = max(0, min(51, int(quality if quality is not None else 23)))
    if hw_encoder.endswith("_nvenc"):
        return {"rc": "vbr", "cq": q}
    if hw_encoder.endswith("_qsv"):
        return {"global_quality": q}
    if hw_encoder.endswith("_amf"):
        return {"rc": "cqp", "qp_i": q, "qp_p": q, "qp_b": q}
    return {}


def summary_label():
    """Human-readable line for the Settings tab describing exactly what the
    Hardware Acceleration switch would use if turned on -- so flipping it is
    never a leap of faith about what it actually does."""
    v = vendor()
    if not v:
        return "No supported GPU detected — encodes will run in software."
    codecs = [c for c in _HW_ENCODERS if hw_encoder_for(c)]
    if not codecs:
        return f"{display_name()} detected, but this ffmpeg build has no matching hardware encoder."
    brand = _ENCODER_BRAND.get(v, v.upper())
    return f"{display_name()} — {brand} encoding for {', '.join(codecs)}."
