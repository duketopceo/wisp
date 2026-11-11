"""Short whisper vocabulary priming.

A speech model treats the prompt as text that came just before the clip,
so a long list of names gets echoed back as the transcript. The prompt is
therefore small on purpose: the user's static [stt] prompt, a few core
terms, the focused app, and the few apps used most lately. Never the
installed-app inventory. The result is also written to vocab.txt.
"""
import json

from . import config

CACHE = config.DATA_DIR / "vocab.txt"
ACTIVITY = config.DATA_DIR / "activity.jsonl"
_MAX_TERMS = 14           # hard cap on the whole prompt
_MAX_CHARS = 160
_TOP_APPS = 3
# product names a speaker may say that a model would otherwise misspell
CORE_TERMS = ("Wisp", "Omarchy", "Hyprland", "OpenRouter")

# window-title noise — generic tokens that add nothing
_STOP = {"the", "and", "for", "with", "this", "that", "com", "www",
         "mozilla", "firefox", "untitled", "home", "new", "tab",
         "http", "https", "file", "google", "search", "page"}


def _jsonl_tail(path, n: int) -> list:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    out = []
    for l in lines[-n:]:
        try:
            out.append(json.loads(l))
        except ValueError:
            pass
    return out


def _app_terms() -> list:
    """The focused window's app class, then the most-used recent apps."""
    out = []
    try:
        from . import platform
        app = (platform.active_window() or {}).get("app", "")
        if app:
            out.append(app)
    except Exception:
        pass
    counts = {}
    for rec in _jsonl_tail(ACTIVITY, 200):
        app = ((rec.get("window") or {}).get("app") or "").strip()
        if app:
            counts[app] = counts.get(app, 0) + 1
    out += sorted(counts, key=lambda a: (-counts[a], a))[:_TOP_APPS]
    return out


def collect(cfg: dict) -> list:
    """Ordered unique short term list: the user's static prompt first
    (explicit choices), then core terms, the focused app and a few
    most-used apps. At most _MAX_TERMS terms and _MAX_CHARS characters."""
    terms, seen = [], set()
    size = 0

    def add(term: str):
        nonlocal size
        t = term.strip()
        k = t.lower()
        if len(t) > 2 and k not in seen and k not in _STOP \
                and len(terms) < _MAX_TERMS \
                and size + len(t) + 2 <= _MAX_CHARS:
            seen.add(k)
            terms.append(t)
            size += len(t) + 2

    for t in (cfg.get("stt", {}).get("prompt") or "").split(","):
        add(t)
    for t in CORE_TERMS:
        add(t)
    for t in _app_terms():
        add(t)
    return terms


def build(cfg: dict) -> str:
    """Priming string for the speech model, used by every provider that
    takes a prompt. [stt] vocab_dynamic = "false" -> static prompt only."""
    static = cfg.get("stt", {}).get("prompt", "")
    if cfg.get("stt", {}).get("vocab_dynamic", "true") == "false":
        return static
    terms = collect(cfg)
    text = ", ".join(terms) if terms else static
    try:
        CACHE.write_text(text + "\n")
    except OSError:
        pass
    return text
