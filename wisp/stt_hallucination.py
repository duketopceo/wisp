"""Strip known trailing STT hallucinations when the audio tail was quiet."""
import re

# Longer phrases first so partial overlaps are not left behind.
_TRAILING_PHRASES = (
    r"thanks for watching[.!]?",
    r"thank you for watching[.!]?",
    r"subscribe(?:\s+and\s+hit\s+the\s+bell)?[.!]?",
    r"thanks for listening[.!]?",
    r"thank you[.!]?",
    r"thanks[.!]?",
    r"the end[.!]?",
    r"subtitles by[\w\s.-]{0,40}",
    r"transcript(?:ed)? by[\w\s.-]{0,40}",
)

_TAIL_RE = re.compile(
    r"(?:\s*(?:[,;:\-—]\s*|\s+))+(?:" + "|".join(_TRAILING_PHRASES) + r")\s*$",
    re.I)


def low_tail_energy(tail_stats: dict | None) -> bool:
    if not tail_stats:
        return False
    return bool(tail_stats.get("tail_quiet"))


def strip_trailing_hallucination(text: str,
                                 tail_stats: dict | None = None) -> tuple:
    """(cleaned_text, meta) — meta is {} when nothing changed."""
    t = " ".join((text or "").split())
    if not t or not low_tail_energy(tail_stats):
        return text, {}
    prev = None
    stripped = []
    while prev != t:
        prev = t
        m = _TAIL_RE.search(t)
        if not m:
            break
        phrase = t[m.start():].strip()
        t = t[:m.start()].rstrip(" ,;:-—")
        if phrase:
            stripped.append(phrase)
    if not stripped or t == (text or "").strip():
        return text, {}
    return t, {"stripped": stripped, "reason": "quiet_tail"}