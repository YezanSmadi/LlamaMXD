# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""GPU detection and hardware-encoder selection for the Settings tab's
Hardware Acceleration switch. **Only a dedicated (discrete) GPU counts** -- an
integrated one is still listed in the system info, but never offered for
acceleration (see `is_dedicated`); with none present the switch is forced off
and greyed out.

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

from core import llamalog
from core.tools import tool_path

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# When more than one *dedicated* adapter is present, NVENC wins over AMF over
# QSV. (An NVIDIA discrete GPU alongside an AMD or Intel integrated one -- a
# real configuration confirmed on this app's own dev machine, see CLAUDE.md's
# libplacebo/Vulkan section -- is just the NVIDIA one, the integrated adapter
# being ignored here.)
_VENDOR_PRIORITY = ["nvidia", "amd", "intel"]

_VENDOR_MARKERS = {
    "nvidia": ("nvidia", "geforce", "quadro", "rtx", "gtx"),
    "amd": ("amd", "radeon", "ati "),
    "intel": ("intel",),
}

# Which adapters are *dedicated*, by name -- WMI has no reliable "discrete"
# flag (`AdapterRAM` is a 32-bit field that caps at 4GB and reports an
# integrated GPU's carve-out as if it were VRAM). NVIDIA has no integrated
# desktop parts, so every NVIDIA adapter counts. AMD and Intel ship both kinds
# under near-identical names, told apart as follows:
#   AMD   integrated: "AMD Radeon(TM) Graphics", "Radeon 780M", "Radeon(TM)
#         Vega 8 Graphics", "Radeon RX Vega 11 Graphics" (a Ryzen APU) --
#         a name ending "Graphics", or a bare Radeon 6xx/7xx"M" (the RX-less
#         mobile iGPU series).
#   AMD   dedicated: "Radeon RX 7900 XTX", "RX 6600M", "Radeon PRO W7800",
#         "Radeon VII", "FirePro", "Instinct", "R9 290", "HD 7970".
#   Intel dedicated: Arc A-/B-series cards ("Arc(TM) A770", "Arc(TM) B580"),
#         and Data Center GPU / Flex. "Arc(TM) Graphics" (Meteor Lake) and
#         every UHD / Iris / HD Graphics is integrated.
_AMD_INTEGRATED = re.compile(r"graphics\s*$|radeon\W*(?:tm\W*)?[67]\d\dm\b", re.I)
_AMD_DEDICATED = re.compile(r"\brx\b|\bpro\b|\bvii\b|firepro|instinct|\br[579]\s*\d{3}|\bhd\s*\d{4}", re.I)
_INTEL_DEDICATED = re.compile(r"\barc\b\W*(?:tm\W*)?(?:pro\s+)?[ab]\d{2,3}\b|data center gpu|\bflex\b", re.I)

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

_vendor = None          # None = not checked yet; "" = checked, no dedicated GPU
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
        except (OSError, subprocess.SubprocessError) as exc:
            llamalog.get("gpu").debug("GPU name query via %s failed: %s", cmd[0], exc)
            continue
        lines = [ln.strip() for ln in (completed.stdout or "").splitlines()]
        names = [ln for ln in lines if ln and ln.lower() != "name"]
        if names:
            return names
    llamalog.get("gpu").warning("No GPU adapter name could be read (wmic and PowerShell both came back empty)")
    return []


def adapter_names():
    """Every detected GPU's display name, cached for the process's
    lifetime (the hardware doesn't change while the app is running)."""
    global _adapter_names
    if _adapter_names is None:
        _adapter_names = _query_adapter_names()
    return _adapter_names


def _adapter_vendor(name):
    """"nvidia" / "amd" / "intel" for an adapter name, or "" (not one this
    app has a hardware encoder for)."""
    low = name.lower()
    for v, markers in _VENDOR_MARKERS.items():
        if any(m in low for m in markers):
            return v
    return ""


def is_dedicated(name):
    """Whether the adapter called `name` is a dedicated (discrete) GPU of a
    vendor this app can hardware-encode on -- see the patterns above."""
    v = _adapter_vendor(name)
    if v == "nvidia":
        return True
    if v == "amd":
        return bool(_AMD_DEDICATED.search(name)) and not _AMD_INTEGRATED.search(name)
    if v == "intel":
        return bool(_INTEL_DEDICATED.search(name))
    return False


def dedicated_adapters():
    """The detected adapters that are dedicated GPUs, in detection order."""
    return [name for name in adapter_names() if is_dedicated(name)]


def vendor():
    """The vendor to hardware-encode with -- "nvidia" / "amd" / "intel", the
    first in `_VENDOR_PRIORITY` among the *dedicated* adapters -- or "" when
    the machine has none (integrated graphics alone never count). Cached; a
    WMI failure caches as "" (no hardware path), never raises."""
    global _vendor
    if _vendor is None:
        found = {_adapter_vendor(name) for name in dedicated_adapters()}
        _vendor = next((v for v in _VENDOR_PRIORITY if v in found), "")
    return _vendor


def has_dedicated():
    """Whether Hardware Acceleration can be offered at all: a dedicated GPU
    of a supported vendor was detected."""
    return bool(vendor())


def display_name():
    """The GPU name for the Settings system-info block: the dedicated adapter
    this app would accelerate with when there is one, else just the first
    detected adapter (a plain integrated GPU is still worth showing even
    though it's never used), else a placeholder."""
    names = adapter_names()
    if not names:
        return "Unknown GPU"
    v = vendor()
    if v:
        for name in dedicated_adapters():
            if _adapter_vendor(name) == v:
                return name
    return names[0]


def _query_available_encoders():
    try:
        completed = subprocess.run(
            [tool_path("ffmpeg"), "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW,
        )
        return set(re.findall(r"\s([a-z0-9]+_(?:nvenc|qsv|amf))\s", completed.stdout or ""))
    except (OSError, subprocess.SubprocessError) as exc:
        llamalog.get("gpu").warning("Couldn't list ffmpeg's hardware encoders: %s", exc)
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
        return "No dedicated GPU detected — hardware acceleration is unavailable."
    codecs = [c for c in _HW_ENCODERS if hw_encoder_for(c)]
    if not codecs:
        return f"{display_name()} detected, but this ffmpeg build has no matching hardware encoder."
    brand = _ENCODER_BRAND.get(v, v.upper())
    return f"{display_name()} — {brand} encoding for {', '.join(codecs)}."
