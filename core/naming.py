"""Output file naming: the template Settings stores (`{source}-{title}` by
default) and the tokens it can hold. Pure data + string handling, no UI code.

Tokens split by *when* they can be known:

* **Live** — `{source}` `{title}` `{chapters}` are facts about the picked
  input (or fetched video), so a tab fills them into the Save field the moment
  it has them, and refills as the probe lands or the template changes.
* **Queue-time** — `{date}` `{time}` `{creation-time}` `{quality}` `{bitrate}`
  depend on the clock or on settings still being changed, so the Save field
  shows them as literal text and they're filled in when a job is actually
  queued (`resolve_path`), against the job's final settings.

A token that resolves to nothing (a file with no title tag, no chapters, ...)
takes its neighbouring separator with it, so `{source}-{title}` on an untitled
file is `clip`, not `clip-`.
"""
import os
import re
from datetime import datetime

from core import formats

DEFAULT_TEMPLATE = "{source}-{title}"

LIVE_TOKENS = ("source", "title", "chapters")
QUEUE_TOKENS = ("date", "time", "creation-time", "quality", "bitrate")
ALL_TOKENS = LIVE_TOKENS + QUEUE_TOKENS

_TOKEN_RE = re.compile(r"\{([A-Za-z-]+)\}")
_SEPARATORS = " _-."
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_STEM = 200


def _clean(value):
    """A token's value as file-name-safe text."""
    text = _ILLEGAL.sub("", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def unknown_tokens(template):
    """`{names}` in `template` that aren't a real token, in order."""
    return [m.group(0) for m in _TOKEN_RE.finditer(template or "")
            if m.group(1).lower() not in ALL_TOKENS]


def template_error(template):
    """Why `template` can't be a file name, or None when it's fine."""
    text = (template or "").strip()
    if not text:
        return "Enter a naming format."
    if _ILLEGAL.search(text):
        return 'A file name can\'t contain any of  < > : " / \\ | ? *'
    bad = unknown_tokens(text)
    if bad:
        return "Unknown: " + " ".join(bad)
    return None


def render(template, values, tokens):
    """Fills every `{token}` of `template` named in `tokens` from `values`
    (`{name: text}`), leaving all other braces literal. An empty result
    removes the token together with the separator run beside it."""
    result = ""
    strip_next = False
    pos = 0

    def add_literal(text):
        nonlocal result, strip_next
        if strip_next:
            text = text.lstrip(_SEPARATORS)
            strip_next = bool(not text)
        result += text

    for match in _TOKEN_RE.finditer(template):
        name = match.group(1).lower()
        if name not in tokens:
            continue
        add_literal(template[pos:match.start()])
        pos = match.end()
        text = _clean(values.get(name))
        if text:
            result += text
            strip_next = False
        elif result.strip(_SEPARATORS):
            result = result.rstrip(_SEPARATORS)
        else:
            result = ""
            strip_next = True
    add_literal(template[pos:])
    return result.rstrip(_SEPARATORS) if result.strip(_SEPARATORS) else result


def finalize(stem, fallback="output"):
    """A stem that's safe as a Windows file name (length, trailing dots)."""
    stem = _ILLEGAL.sub("", stem or "").strip().rstrip(". ")
    return stem[:_MAX_STEM].rstrip(". ") or fallback


def render_live(template, values, fallback=""):
    """The Save-field name: live tokens filled, queue-time ones left as text."""
    stem = finalize(render(template or DEFAULT_TEMPLATE, values, LIVE_TOKENS), fallback="")
    return stem or finalize(fallback)


def resolve_path(path, values):
    """`path` with every token in its file name filled in — the queue-time
    pass. A name with no braces comes back unchanged."""
    directory, name = os.path.split(path)
    stem, ext = os.path.splitext(name)
    if "{" not in stem:
        return path
    return os.path.join(directory, finalize(render(stem, values, ALL_TOKENS)) + ext)


# ---------------------------------------------------------------------- #
#  Values
# ---------------------------------------------------------------------- #
def _count_text(count):
    return f"{count}ch" if count else ""


def _kbps_text(bits_per_second):
    return f"{round(bits_per_second / 1000)}kbps" if bits_per_second else ""


def _stamp(moment, with_time):
    return moment.strftime("%Y-%m-%d_%H-%M-%S" if with_time else "%Y-%m-%d")


def _file_creation(path):
    """When the file was made on disk — the fallback for `{creation-time}`
    when the media carries no creation_time tag of its own."""
    try:
        return datetime.fromtimestamp(os.path.getctime(path))
    except (OSError, ValueError, TypeError):
        return None


def _tagged_creation(value):
    """A media `creation_time` tag ("2024-03-05T10:20:30.000000Z") as local time."""
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.astimezone() if moment.tzinfo else moment


def media_live_values(path, info):
    """Live tokens for a picked input file, from its probe."""
    info = info or {}
    return {
        "source": os.path.splitext(os.path.basename((path or "").replace("\\", "/")))[0],
        "title": info.get("title"),
        "chapters": _count_text(info.get("chapters")),
    }


def download_live_values(info):
    """Live tokens for a fetched video (`yt-dlp -J`): the site, the title,
    the chapter count."""
    info = info or {}
    return {
        "source": info.get("extractor_key") or info.get("extractor"),
        "title": info.get("title"),
        "chapters": _count_text(len(info.get("chapters") or [])),
    }


def media_queue_values(path, info, settings, now=None):
    """Every token for a Mux/Encode job about to be queued. `settings` is the
    job's own dict, so `{quality}` follows the CRF/qscale actually chosen."""
    info = info or {}
    now = now or datetime.now()
    values = media_live_values(path, info)
    created = _tagged_creation(info.get("creation_time")) or _file_creation(path)
    quality = ""
    spec = formats.quality_for(settings.get("encoder"))
    if spec and settings.get("quality") is not None:
        quality = ("crf" if spec["kind"] == "crf" else "q") + str(settings["quality"])
    bitrate = info.get("bit_rate")
    if not bitrate and info.get("file_size") and info.get("duration"):
        bitrate = info["file_size"] * 8 / info["duration"]
    values.update({
        "date": _stamp(now, False),
        "time": now.strftime("%H-%M-%S"),
        "creation-time": _stamp(created, True) if created else "",
        "quality": quality,
        "bitrate": _kbps_text(bitrate),
    })
    return values


def download_queue_values(info, settings, now=None):
    """Every token for a download about to be queued: `{creation-time}` is
    the video's upload date, `{quality}` the Resolution pick, `{bitrate}` the
    chosen streams' average (their combined size over the video's length)."""
    info = info or {}
    now = now or datetime.now()
    values = download_live_values(info)
    upload = None
    try:
        upload = datetime.strptime(str(info.get("upload_date") or ""), "%Y%m%d")
    except ValueError:
        pass
    plan = settings.get("download") or {}
    total = sum(part.get("size") or 0 for part in plan.get("parts") or [])
    duration = info.get("duration")
    values.update({
        "date": _stamp(now, False),
        "time": now.strftime("%H-%M-%S"),
        "creation-time": upload.strftime("%Y-%m-%d") if upload else "",
        "quality": str(settings.get("quality") or "").replace(" ", ""),
        "bitrate": _kbps_text(total * 8 / duration) if total and duration else "",
    })
    return values
