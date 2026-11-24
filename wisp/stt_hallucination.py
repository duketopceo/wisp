"""Strip known trailing STT hallucinations when the audio tail was quiet."""
import re

# Unambiguous outros/credits only — not ordinary "thanks" or "thank you".
_HALLUCINATION_ENDINGS = (
    r"the end",
    r"thanks for watching",
    r"thank you for watching",
    r"thanks for listening",
    r"thank you for listening",
    r"subscribe(?:\s+and\s+hit\s+(?:the\s+)?bell)?",
    r"subtitles by[\w\s .-]{0,48}",
    r"subtitle by[\w\s .-]{0,48}",
    r"transcript(?:ed)? by[\w\s .-]{0,48}",
)

_TAIL_RE = re.compile(
    r"^(?P<body>.*?)(?:\s*[,;:\-—]\s*|\s+)?(?:"
    + "|".join(_HALLUCINATION_ENDINGS)
    + r")[.!?]*\s*$",
    re.I | re.DOTALL,
)

_ONLY_RE = re.compile(
    r"^(?:"
    + "|".join(_HALLUCINATION_ENDINGS)
    + r")[.!?]*\s*$",
    re.I,
)


def low_tail_energy(tail_stats: dict | None) -> bool:
    if not tail_stats or "tail_quiet" not in tail_stats:
        return False
    return bool(tail_stats["tail_quiet"])


def strip_trailing_hallucination(text: str,
                                 tail_stats: dict | None = None) -> tuple:
    """(cleaned_text, meta) — meta is {} when nothing changed."""
    raw = " ".join((text or "").split())
    if not raw or not low_tail_energy(tail_stats):
        return text, {}
    if _ONLY_RE.match(raw):
        return "", {"stripped": [raw], "reason": "quiet_tail_only"}
    m = _TAIL_RE.match(raw)
    if not m or not m.group("body").strip():
        return text, {}
    body = m.group("body").rstrip(" ,;:-—")
    phrase = raw[len(body):].strip(" ,;:-—")
    if not phrase:
        return text, {}
    if body == raw:
        return text, {}
    return body, {"stripped": [phrase], "reason": "quiet_tail"}