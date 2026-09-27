"""Small shared helpers."""
import re


def slug(text: str, max_len: int = 48, default: str = "x") -> str:
    """Filesystem/tool-name-safe slug — shared by agents and skills so
    naming can't drift."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:max_len]
    return s.rstrip("-") or default
