"""LLM-aware dictation (plan U6, KTD6/KTD7): dictate -> mode/profile
rewrite -> insert at the focused cursor.

Modes (resolved per call — spoken token > per-app profile >
`[dictation] mode`, default `cleanup`):

  raw     — the transcript verbatim (what dictation always did)
  cleanup — a brain pass fixing grammar/spelling/punctuation that
            preserves the user's words; nothing is invented
  compose — the transcript is an *idea*; the model writes the finished
            text for the focused app's genre ("write an email to sam")

Per-app profiles (VoiceInk Power Mode, thin) are `[dictation.profiles.
<pattern>]` sections matched `*pattern*` against the focused window
class, longest pattern winning: `mode`, `style` (a free-text hint folded
into the system prompt) and `auto_send` (true = press Return after the
insert — sending is irreversible, so it is T2-gated through the turn's
confirm callable; a denied or absent gate means draft-only).

The newline guard (KTD7): into a terminal-class window every mode
collapses newlines to spaces — dictated text can never execute as a
command — unless the send path was armed AND confirmed, which is the
only way a user says "run this". The class list is the built-ins plus
`[dictation] terminal_classes` (comma list).

Personal corrections live in ~/.local/share/wisp/dictation.json
({"corrections": {heard: meant}, "profiles_seen": {app: {n, last}}}).
`wispd dictate correct heard meant` / the `dictate_correct` IPC command
records one; cleanup/compose prompts carry the table and the output is
exact-match corrected post-LLM. A brain that errors or empties never
eats a dictation — the raw transcript is inserted instead.
"""
import fnmatch
import json
import re
import time
from datetime import datetime, timezone

from . import cancel as _cancel
from . import config, platform

FILE = config.DATA_DIR / "dictation.json"

MODES = ("raw", "cleanup", "compose")
DEFAULT_MODE = "cleanup"

# substring match on the focused window class, lowercase; the
# configurable dictation.terminal_classes csv extends it
TERMINALS = ("foot", "alacritty", "kitty", "ghostty", "wezterm")

# leading spoken tokens that pick a mode per call — 'dictate raw ...'
# bypasses the brain. Kept to raw/verbatim on purpose: cleanup is the
# default anyway (no token needed) and words like 'clean' or 'compose'
# are too common mid-sentence to eat as control tokens — compose has
# the intent-verb path below instead.
_MODE_WORDS = {"raw": "raw", "verbatim": "raw"}
_COMPOSE_VERBS = {"write", "draft", "compose", "send", "reply",
                  "respond", "jot"}
_COMPOSE_NOUN = re.compile(
    r"\b(?:e-?mails?|mails?|messages?|notes?|replies|memo|letters?|"
    r"texts?|doc(?:ument)?s?|posts?|dm|reports?|reviews?|comments?|"
    r"issues?|summar(?:y|ies)|updates?|blurbs?)\b", re.I)

_PASTE_DELAY_S = 0.4   # let the app read the clip before restore
_TYPED_MAX = 300       # chars: wtype char-typing gets slow and drops
                       # glyphs on big bodies — longer text paste-first


def _csv(v) -> list:
    return [s.strip().lower() for s in str(v or "").split(",")
            if s.strip()]


def _truthy(v) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def settings(cfg: dict | None) -> dict:
    d = (cfg or {}).get("dictation", {}) or {}
    mode = str(d.get("mode") or DEFAULT_MODE).strip().lower()
    return {"mode": mode if mode in MODES else DEFAULT_MODE,
            "model": str(d.get("model") or "").strip(),
            "terminal_classes": _csv(d.get("terminal_classes"))}


# -- focused window / profiles -----------------------------------------

def _focused(state) -> dict:
    """Focused window as {"class", "title"}: the turn's press-time
    focus (state.focus {app,title}) before a live query — dictating
    must resolve against the app the user was in, not whatever the
    card grabbed."""
    f = getattr(state, "focus", None) if state is not None else None
    if isinstance(f, dict) and (f.get("app") or f.get("class")):
        return {"class": f.get("class") or f.get("app") or "",
                "title": f.get("title") or ""}
    try:
        w = platform.active_window() or {}
    except Exception:
        w = {}
    return {"class": w.get("class") or w.get("app") or "",
            "title": w.get("title") or ""}


def _match(pat: str, cls: str) -> bool:
    pat = pat.strip().strip('"').lower()
    if not pat:
        return False
    glob = pat if any(g in pat for g in "*?") else f"*{pat}*"
    return fnmatch.fnmatch(cls, glob)


def profile_for(cls: str, cfg: dict | None) -> dict:
    """The `[dictation.profiles.<pattern>]` section whose pattern best
    matches the focused class ({mode, style, auto_send}; {} when none).
    A pattern without glob chars matches as `*pattern*`; the longest
    match wins so 'chromium-beta' can refine 'chromium'."""
    cls = (cls or "").lower()
    prefix = "dictation.profiles."
    best, hits = -1, {}
    for key, prof in (cfg or {}).items():
        if not key.startswith(prefix) or not isinstance(prof, dict):
            continue
        pat = key[len(prefix):]
        if _match(pat, cls) and len(pat) > best:
            best, hits = len(pat), prof
    return hits


def is_terminal(cls: str, cfg: dict | None) -> bool:
    hay = (cls or "").lower()
    names = TERMINALS + tuple(settings(cfg)["terminal_classes"])
    return any(t and t in hay for t in names)


def collapse_newlines(text: str) -> str:
    """The terminal guard: line joins never reach a shell as Return."""
    return re.sub(r"\s*[\r\n]+\s*", " ", text).strip()


# -- mode selection -----------------------------------------------------

def _spoken_mode(text: str) -> tuple:
    """'raw buy milk' -> ('raw', 'buy milk'); (None, text) otherwise."""
    first, _, rest = (text or "").partition(" ")
    mode = _MODE_WORDS.get(first.strip(",:").lower())
    if mode and rest.strip():
        return mode, rest.strip()
    return None, text


def _compose_intent(text: str) -> bool:
    """'write an email to sam' — a lead verb plus a doc-ish noun inside
    the first few words marks a ramble-to-draft request."""
    head = (text or "").strip().lower().split(None, 6)
    return bool(head) and head[0].rstrip(",:") in _COMPOSE_VERBS \
        and bool(_COMPOSE_NOUN.search(" ".join(head[:6])))


def pick_mode(text: str, cfg: dict | None, profile: dict | None = None,
              mode: str | None = None) -> tuple:
    """-> (mode, transcript). Explicit > spoken token > profile >
    [dictation] mode; compose intent promotes any default."""
    if mode in MODES:
        return mode, text
    spoken, rest = _spoken_mode(text)
    if spoken:
        return spoken, rest
    default = (profile or {}).get("mode") or settings(cfg)["mode"]
    default = default if default in MODES else DEFAULT_MODE
    if default != "compose" and _compose_intent(text):
        return "compose", text
    return default, text


# -- corrections --------------------------------------------------------

def _read(path=None) -> dict:
    try:
        data = json.loads((path or FILE).read_text())
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("corrections", {})
    data.setdefault("profiles_seen", {})
    return data


def _write(data: dict, path=None) -> None:
    p = path or FILE
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    except OSError:
        pass


def corrections(path=None) -> dict:
    return dict(_read(path)["corrections"])


def add_correction(heard: str, meant: str, path=None) -> str:
    """Record heard->meant; both prompts and the post-LLM pass use it."""
    heard, meant = (heard or "").strip(), (meant or "").strip()
    if not heard or not meant:
        return "SKIP (correction needs 'heard' and 'meant')"
    data = _read(path)
    data["corrections"][heard.lower()] = meant
    _write(data, path)
    return f"CORRECTED {heard!r} -> {meant!r}"


def apply_corrections(text: str, corr: dict | None) -> str:
    """Exact-phrase, case-insensitive swap of learned forms; longest
    key first so overlapping entries don't split each other."""
    for said in sorted((corr or {}), key=len, reverse=True):
        if not said:
            continue
        text = re.sub(r"(?i)\b" + re.escape(said) + r"\b",
                      lambda _m, t=corr[said]: t, text)
    return text


def _seen(cls: str, path=None) -> None:
    """`profiles_seen` bookkeeping: which apps get dictated into and
    how often — the evidence a future profile suggestion reads."""
    data = _read(path)
    rec = data["profiles_seen"].setdefault(cls or "?", {"n": 0})
    rec["n"] = int(rec.get("n") or 0) + 1
    rec["last"] = datetime.now(timezone.utc).isoformat()
    _write(data, path)


# -- rewrite ------------------------------------------------------------

_PROMPTS = {
    "cleanup": (
        "You are a dictation cleanup pass. Fix grammar, spelling and "
        "punctuation and drop filler sounds (um, uh). Preserve the "
        "user's words and meaning exactly — never add, reorder or "
        "invent content. Output ONLY the corrected text: no quotes, "
        "no commentary."),
    "compose": (
        "You are a dictation composer. The transcript is an IDEA, not "
        "finished text — write the finished text the user wants, "
        "ready to insert at their cursor (an email, a message, a doc). "
        "Match the genre of the app it lands in. Output ONLY the text "
        "to insert: no preamble, no quotes, no explanation."),
}


def _system(mode: str, win: dict, profile: dict, corr: dict) -> str:
    app = (win.get("class") or "").strip()
    title = (win.get("title") or "").strip()[:80]
    sys_p = _PROMPTS[mode]
    if app:
        sys_p += f"\nInserting into {app}" \
                 + (f' ("{title}")' if title else "") + "."
    style = str((profile or {}).get("style") or "").strip()
    if style:
        sys_p += f"\nStyle: {style}."
    if corr:
        pairs = "; ".join(f"{k} -> {v}" for k, v in
                          sorted(corr.items()))[:600]
        sys_p += "\nPersonal corrections — always use the " \
                 f"right-hand form: {pairs}"
    return sys_p


def _chat(messages: list, cfg: dict) -> dict:
    """brain.chat through the configured chain; `[dictation] model`
    (a 'provider:model' spec like [brain] default) overrides just this
    call, keeping the same providers/base_urls/fallbacks."""
    from . import brain
    spec = settings(cfg)["model"]
    if spec:
        cfg = dict(cfg)
        cfg["brain"] = dict(cfg.get("brain") or {})
        cfg["brain"]["default"] = spec
    return brain.chat(messages, cfg, timeout=30)


def _session_tail() -> str:
    """Recent turns as compact text for compose context (U4 seam);
    capped so a chatty session can't bloat the prompt."""
    try:
        from . import session
        return session.as_text(session.tail(4))[:1200]
    except Exception:
        return ""


def rewrite(mode: str, text: str, cfg: dict, win: dict, profile: dict,
            corr: dict) -> str:
    """The cleanup/compose pass. raw never calls the brain; a brain
    error or empty reply degrades to the raw transcript — a dead model
    must not swallow a dictation."""
    if mode == "raw":
        return text
    user = text
    tail = _session_tail() if mode == "compose" else ""
    if tail:
        user = f"{text}\n\nRecent conversation (context only):\n{tail}"
    messages = [{"role": "system",
                 "content": _system(mode, win, profile, corr)},
                {"role": "user", "content": user}]
    try:
        out = (_chat(messages, cfg).get("content") or "").strip()
    except _cancel.Cancelled:
        raise
    except Exception as e:
        try:
            from . import trace
            trace.emit(trace.current(), "dictate_fallback", "brain",
                       {"mode": mode, "err": str(e)[:120]})
        except Exception:
            pass
        return text
    return out or text


# -- insertion ----------------------------------------------------------

def _clip_get() -> str | None:
    """Current clipboard text for a post-paste restore (best effort)."""
    import shutil
    if not shutil.which("wl-paste"):
        return None
    try:
        r = _cancel.run(["wl-paste", "--no-newline"],
                        capture_output=True, timeout=5)
    except Exception:
        return None
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 \
        else None


def _paste(text: str, cfg: dict) -> bool:
    """Clipboard-paste insert (the WordInk approach): wl-copy the text,
    chord ctrl+v through the key tool, then restore the user's clip —
    the paste must not destroy what they had."""
    import shutil
    if not shutil.which("wl-copy"):
        return False
    try:
        r = _cancel.run(["wl-copy"], input=text.encode(),
                        capture_output=True, timeout=10)
    except Exception:
        return False
    if r.returncode != 0:
        return False
    prior = _clip_get()
    from . import tools
    ok = tools.run("key", "ctrl+v", cfg).startswith("KEY")
    if prior is not None:
        time.sleep(_PASTE_DELAY_S)
        try:
            _cancel.run(["wl-copy"], input=prior.encode(),
                        capture_output=True, timeout=5)
        except Exception:
            pass
    return ok


def insert(text: str, cfg: dict) -> tuple:
    """wordink TextInserter -> type_text -> clipboard paste; long text
    (> _TYPED_MAX) skips the typer — the plan's wtype-short/paste-long
    split. -> (via, err): 'wordink' | 'typed' | 'paste' | '' with the
    last failure reason (nothing landed)."""
    if not text:
        return "", "SKIP (nothing to type)"
    try:
        import wordink
        if wordink.TextInserter().insert_text(text):
            return "wordink", ""
    except Exception:
        pass
    out = ""
    if len(text) <= _TYPED_MAX:
        from . import tools
        out = tools.run("type_text", text, cfg)
        if out.startswith("TYPED"):
            return "typed", ""
    if _paste(text, cfg):
        return "paste", ""
    return "", out or "SKIP (no insert path — wtype/wl-copy missing)"


_CORRECT_RE = re.compile(
    r"^/correct\s+[\"']([^\"']+)[\"']\s+[\"']([^\"']+)[\"']\s*$")


def _maybe_correction(text: str) -> str | None:
    """`/correct "heard" "meant"` dictated in-stream records a personal
    correction instead of inserting — the voice-side path into the
    same dictation.json store `dictate_correct` IPC writes."""
    m = _CORRECT_RE.match((text or "").strip())
    if m:
        return add_correction(m.group(1), m.group(2))
    if (text or "").strip().startswith("/correct"):
        return 'SKIP (/correct needs "heard" "meant" quoted)'
    return None


def _send_ok(profile: dict, confirm, app: str, text: str) -> bool:
    """auto_send's T2 gate (U3): the profile declared intent to send,
    the confirm card still decides — denied/absent means draft-only."""
    if not _truthy(profile.get("auto_send")) or confirm is None:
        return False
    from . import policy
    prompt = f"send in {app or 'the app'}? {text[:80]}".strip()
    ok, _last = policy._ask(confirm, prompt[:160])
    return ok


def run(text: str, cfg: dict, state=None, confirm=None,
        mode: str | None = None) -> str:
    """The dictation dispatch: pick the mode, maybe rewrite, guard
    terminals, insert, maybe send. -> the result string the action
    stream records (DICTATED / INSERTED / SKIP / BLOCKED shapes)."""
    cor = _maybe_correction(text)
    if cor is not None:
        return cor
    win = _focused(state)
    cls = win.get("class") or ""
    profile = profile_for(cls, cfg)
    mode, text = pick_mode(text, cfg, profile, mode)
    corr = corrections()
    out = rewrite(mode, text, cfg, win, profile, corr)
    if mode != "raw":
        out = apply_corrections(out, corr)
    if not out.strip():
        return "SKIP (nothing to type)"
    terminal = is_terminal(cls, cfg)
    from . import tools
    if terminal and tools.denied(out):
        # refuse before any card — a denylisted command never reaches
        # the shell, typed or pasted
        return "REFUSED (denylisted command)"
    send = _send_ok(profile, confirm, cls, out)
    if terminal and not send:
        # KTD7: typed newlines ARE Return presses at a shell — spoken
        # text must never execute; the confirmed send path keeps them
        out = collapse_newlines(out)
    via, err = insert(out, cfg)
    if not via:
        return err or "SKIP (no insert path — wtype/wl-copy missing)"
    sent = False
    if send:
        from . import tools
        sent = tools.run("key", "enter", cfg).startswith("KEY")
    _seen(cls)
    tag = "DICTATED" if via == "wordink" else "INSERTED"
    if via == "paste":
        tag += " (paste)"
    if sent:
        tag += " +sent"
    return f"{tag}: {out.replace(chr(10), ' ')[:140]}"
