"""Dynamic whisper vocabulary priming — built from what Wisp knows,
not a hand-maintained string.

Sources: learned apps (harness.json), installed skill names, omarchy
plugin names, recent window titles (activity.jsonl), MEMORY/USER proper
nouns, plus the user's static [stt] prompt appended verbatim. Result is
cached in vocab.txt and rebuilt at most once per VOCAB_TTL_S.
"""
import json
import re
import time

from . import config, skills

CACHE = config.DATA_DIR / "vocab.txt"
ACTIVITY = config.DATA_DIR / "activity.jsonl"
HARNESS = config.DATA_DIR / "harness.json"
VOCAB_TTL_S = 3600
_MAX_TERMS = 80           # ~200 tokens — well under n_text_ctx/2
_WORD = re.compile(r"[A-Za-z][\w.+-]{2,}")

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


def _title_terms() -> list:
    seen, out = set(), []
    for rec in _jsonl_tail(ACTIVITY, 40):
        win = rec.get("window") or {}
        for w in _WORD.findall(win.get("title", "") +
                               " " + win.get("app", "")):
            wl = w.lower()
            if wl in _STOP or wl in seen:
                continue
            seen.add(wl)
            out.append(w)
    return out


def _file_terms(path) -> list:
    """Capitalized words + `code spans` from a markdown file."""
    try:
        text = path.read_text()
    except OSError:
        return []
    terms = set(re.findall(r"`([^`\n]{3,30})`", text))
    terms.update(w for w in _WORD.findall(text)
                 if w[0].isupper() and w.lower() not in _STOP)
    return sorted(terms)


def collect(cfg: dict) -> list:
    """Ordered unique term list — harness apps first (most-spoken)."""
    terms, seen = [], set()

    def add(term: str):
        t = term.strip()
        k = t.lower()
        if len(t) > 2 and k not in seen and k not in _STOP:
            seen.add(k)
            terms.append(t)

    # user's static prompt terms first — explicit choices beat the cap
    for t in (cfg.get("stt", {}).get("prompt") or "").split(","):
        add(t)
    try:
        for app in json.loads(HARNESS.read_text()).get("apps", {}):
            add(app)
    except (OSError, ValueError):
        pass
    import pathlib
    plug = pathlib.Path.home() / ".config/omarchy/plugins"
    if plug.is_dir():
        for d in sorted(plug.iterdir()):
            add(d.name.split(".")[-1])  # io.github.duketopceo.wisp → wisp
    for d in sorted(skills.SKILLS_DIR.iterdir()) \
            if skills.SKILLS_DIR.is_dir() else []:
        add(d.name.replace("-", " "))
    for t in _title_terms():
        add(t)
    from . import memory
    for t in _file_terms(memory.MEMORY_FILE) + _file_terms(
            memory.USER_FILE):
        add(t)
    return terms[:_MAX_TERMS]


def build(cfg: dict) -> str:
    """Priming string for whisper. Cached VOCAB_TTL_S unless
    [stt] vocab_dynamic = "false" (then static prompt only)."""
    static = cfg.get("stt", {}).get("prompt", "")
    if cfg.get("stt", {}).get("vocab_dynamic", "true") == "false":
        return static
    try:
        if time.time() - CACHE.stat().st_mtime < VOCAB_TTL_S:
            return CACHE.read_text().strip()
    except OSError:
        pass
    terms = collect(cfg)
    text = ", ".join(terms) if terms else static
    try:
        CACHE.write_text(text + "\n")
    except OSError:
        pass
    return text
