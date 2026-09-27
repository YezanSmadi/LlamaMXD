# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""GPU detection and hardware-encoder selection for the Hardware Acceleration switch. Only a
dedicated GPU counts; with none the switch is forced off. Every lookup is best-effort and
cached, and any failure means software encoding, as if the switch were off."""
import re
import subprocess

from core import llamalog, winproc
from core.tools import tool_path


# With several dedicated adapters, NVENC wins over AMF over Quick Sync.
_VENDOR_PRIORITY = ["nvidia", "amd", "intel"]

_VENDOR_MARKERS = {
    "nvidia": ("nvidia", "geforce", "quadro", "rtx", "gtx"),
    "amd": ("amd", "radeon", "ati "),
    "intel": ("intel",),
}

# Which adapters are dedicated, by name (WMI has no reliable flag; AdapterRAM caps at 4GB and
# counts an iGPU's carve-out). Every NVIDIA adapter counts. AMD integrated: a name ending
# "Graphics" or a bare Radeon 6xx/7xx "M" (780M). Intel dedicated: Arc A/B-series and Data
# Center / Flex; "Arc Graphics", UHD, Iris and HD Graphics are integrated.
_AMD_INTEGRATED = re.compile(r"graphics\s*$|radeon\W*(?:tm\W*)?[67]\d\dm\b", re.I)
_AMD_DEDICATED = re.compile(r"\brx\b|\bpro\b|\bvii\b|firepro|instinct|\br[579]\s*\d{3}|\bhd\s*\d{4}", re.I)
_INTEL_DEDICATED = re.compile(r"\barc\b\W*(?:tm\W*)?(?:pro\s+)?[ab]\d{2,3}\b|data center gpu|\bflex\b", re.I)

# Display codec -> {vendor: encoder id}: the three codecs every vendor's encoder supports.
# Everything else always runs in software.
_HW_ENCODERS = {
    "H.264": {"nvidia": "h264_nvenc", "amd": "h264_amf", "intel": "h264_qsv"},
    "H.265": {"nvidia": "hevc_nvenc", "amd": "hevc_amf", "intel": "hevc_qsv"},
    "AV1": {"nvidia": "av1_nvenc", "amd": "av1_amf", "intel": "av1_qsv"},
}

# Each vendor's own name for its encoder, for `summary_label`.
_ENCODER_BRAND = {"nvidia": "NVENC", "amd": "AMF", "intel": "Quick Sync"}

_vendor = None          # None = not checked yet; "" = checked, no dedicated GPU
_adapter_names = None
_available_encoders = None


def _query_adapter_names():
    """Every video controller's name via WMI: wmic, else PowerShell's CIM cmdlet (wmic is
    being removed from newer Windows)."""
    for cmd in (
        ["wmic", "path", "win32_VideoController", "get", "name"],
        ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name"],
    ):
        try:
            completed = winproc.run(cmd, text=True, timeout=10)
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
    """Every detected GPU's name, cached for the process."""
    global _adapter_names
    if _adapter_names is None:
        _adapter_names = _query_adapter_names()
    return _adapter_names


def _adapter_vendor(name):
    """"nvidia" / "amd" / "intel" for an adapter name, or ""."""
    low = name.lower()
    for v, markers in _VENDOR_MARKERS.items():
        if any(m in low for m in markers):
            return v
    return ""


def is_dedicated(name):
    """Whether adapter `name` is a dedicated GPU of a supported vendor (patterns above)."""
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
    """The vendor to encode with (the first in `_VENDOR_PRIORITY` among dedicated adapters),
    or "" when there is none. Cached; a WMI failure caches as ""."""
    global _vendor
    if _vendor is None:
        found = {_adapter_vendor(name) for name in dedicated_adapters()}
        _vendor = next((v for v in _VENDOR_PRIORITY if v in found), "")
    return _vendor


def has_dedicated():
    """Whether Hardware Acceleration can be offered: a supported dedicated GPU was found."""
    return bool(vendor())


def display_name():
    """The GPU name for the system info: the dedicated adapter if any, else the first
    detected, else a placeholder."""
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
        completed = winproc.run([tool_path("ffmpeg"), "-hide_banner", "-encoders"], text=True, timeout=10)
        return set(re.findall(r"\s([a-z0-9]+_(?:nvenc|qsv|amf))\s", completed.stdout or ""))
    except (OSError, subprocess.SubprocessError) as exc:
        llamalog.get("gpu").warning("Couldn't list ffmpeg's hardware encoders: %s", exc)
        return set()


def available_encoders():
    """Every hardware encoder id compiled into this ffmpeg (`ffmpeg -encoders`), cached. Listed
    doesn't guarantee it runs on this GPU."""
    global _available_encoders
    if _available_encoders is None:
        _available_encoders = _query_available_encoders()
    return _available_encoders


def hw_encoder_for(codec):
    """The hardware encoder id for display codec `codec` on this machine, or None (no
    supported vendor, no encoder for the codec, or not in this build): software then."""
    v = vendor()
    if not v:
        return None
    encoder = _HW_ENCODERS.get(codec, {}).get(v)
    if encoder and encoder in available_encoders():
        return encoder
    return None


def rate_control_kwargs(hw_encoder, quality):
    """Output kwargs standing in for -crf on a hardware encoder, clamped to 0-51:
      NVENC: -rc vbr -cq <q>; QSV: -global_quality <q>; AMF: -rc cqp -qp_i/-qp_p/-qp_b <q>."""
    q = max(0, min(51, int(quality if quality is not None else 23)))
    if hw_encoder.endswith("_nvenc"):
        return {"rc": "vbr", "cq": q}
    if hw_encoder.endswith("_qsv"):
        return {"global_quality": q}
    if hw_encoder.endswith("_amf"):
        return {"rc": "cqp", "qp_i": q, "qp_p": q, "qp_b": q}
    return {}


def summary_label():
    """The Settings line naming exactly what the switch would use when on."""
    v = vendor()
    if not v:
        return "No dedicated GPU detected — hardware acceleration is unavailable."
    codecs = [c for c in _HW_ENCODERS if hw_encoder_for(c)]
    if not codecs:
        return f"{display_name()} detected, but this ffmpeg build has no matching hardware encoder."
    brand = _ENCODER_BRAND.get(v, v.upper())
    return f"{display_name()} — {brand} encoding for {', '.join(codecs)}."
