"""Wisp knows itself (B30).

"What model are you", "what did I spend today", "what version is this",
"copy that", "say that again" and "what went wrong" are answered from
local state with no model call: model names from config and the usage
ledger, spend from the ledger, version from the deploy record, the last
answer from the session log, the last error from the error log.

Each phrase is matched only as the WHOLE utterance (so "explain what
version control is" is left to the brain) and every answer is built from
data on this machine, so it cannot name a model that is not configured or
a number that is not in the ledger.
"""
import re
from urllib.parse import urlparse

PREFIX = "self:"

_PRE = r"^\s*(?:(?:hey\s+)?wisp[,\s]+)?(?:please\s+|can\s+you\s+|could\s+you\s+)?"
_END = r"(?:\s+please)?[\s.!?]*$"

_PHRASES = {
    "model": (
        r"what(?:'s|\s+is)?\s+(?:model|llm|brain)\s+(?:are\s+you|is\s+this|"
        r"are\s+you\s+(?:using|running(?:\s+on)?))",
        r"which\s+(?:model|llm|brain)\s+(?:are\s+you|is\s+this)"
        r"(?:\s+(?:using|running(?:\s+on)?))?",
        r"what\s+are\s+you\s+running\s+on",
        r"what\s+(?:model|llm|brain)\s+do\s+you\s+use",
        r"what\s+(?:model|llm|brain)\s+am\s+i\s+(?:talking|speaking)\s+to",
    ),
    "spend_today": (
        r"what\s+(?:did|have)\s+i\s+(?:spend|spent)\s+today",
        r"what(?:'s|\s+is)\s+my\s+spend(?:ing)?\s+today",
        r"how\s+much\s+(?:did|have)\s+i\s+(?:spend|spent)(?:\s+today)",
        r"how\s+much\s+(?:have\s+you|did\s+you)\s+cost\s+(?:me\s+)?today",
        r"what\s+(?:have\s+)?i\s+spent\s+today",
    ),
    "spend_week": (
        r"what\s+(?:did|have)\s+i\s+(?:spend|spent)\s+this\s+week",
        r"what(?:'s|\s+is)\s+my\s+spend(?:ing)?\s+this\s+week",
        r"how\s+much\s+(?:did|have)\s+i\s+(?:spend|spent)\s+this\s+week",
        r"how\s+much\s+(?:have\s+you|did\s+you)\s+cost\s+(?:me\s+)?"
        r"this\s+week",
    ),
    "version": (
        r"what\s+version\s+(?:is\s+this|are\s+you|am\s+i\s+(?:on|running)|"
        r"of\s+wisp\s+(?:is\s+this|am\s+i\s+(?:on|running)|are\s+you))",
        r"which\s+version\s+(?:is\s+this|are\s+you|of\s+wisp\s+"
        r"(?:is\s+this|am\s+i\s+(?:on|running)))",
        r"what(?:'s|\s+is)\s+(?:your|the)\s+version",
    ),
    "copy": (
        r"copy\s+(?:that|this|it)(?:\s+to\s+(?:the\s+)?clipboard)?",
        r"copy\s+(?:your|the)\s+(?:last\s+)?(?:answer|reply|response)"
        r"(?:\s+to\s+(?:the\s+)?clipboard)?",
    ),
    "again": (
        r"say\s+(?:that|it)\s+again",
        r"repeat\s+(?:that|yourself)",
        r"what\s+did\s+you\s+(?:just\s+)?say",
        r"(?:come\s+again|pardon|sorry\s+what)",
    ),
    "wrong": (
        r"what\s+went\s+wrong(?:\s+(?:there|just\s+now|with\s+that))?",
        r"why\s+did\s+that\s+(?:fail|break|not\s+work)",
        r"what\s+(?:was|is)\s+the\s+(?:last\s+)?error",
        r"what\s+happened\s+(?:there|just\s+now)",
    ),
}
_RX = {k: re.compile(_PRE + "(?:" + "|".join(v) + ")" + _END, re.IGNORECASE)
       for k, v in _PHRASES.items()}

KINDS = tuple(_PHRASES)
CLIP_CAP = 20000


def intent(text: str):
    """The kind for a whole-utterance self question, else None."""
    t = " ".join((text or "").split())
    if not t or len(t) > 80:
        return None
    for kind, rx in _RX.items():
        if rx.match(t):
            return kind
    return None


# -- the answers --------------------------------------------------------

def _money(usd: float) -> str:
    if usd <= 0:
        return "nothing"
    if usd < 0.01:
        return "under a cent"
    return f"${usd:.2f}"


def _calls(n: int) -> str:
    return f"{n} call" + ("" if n == 1 else "s")


def _split(spec: str) -> tuple:
    name, _, model = (spec or "").strip().partition(":")
    return (name, model) if model else ("", name)


def _brain_entry(spec: str) -> str:
    name, model = _split(spec)
    if not model:
        return ""
    return f"{model} through {name}" if name else model


def models_line(cfg: dict, last=None) -> str:
    """Every model this install is configured to call, and the one the
    last recorded call really used."""
    b = cfg.get("brain", {}) or {}
    default = _brain_entry(b.get("default") or "openrouter:meta-llama/"
                           "llama-4-maverick")
    parts = [f"I answer with {default}"]
    backups = [e for e in (_brain_entry(s)
                           for s in (b.get("fallback") or "").split(","))
               if e]
    if backups:
        parts[0] += ", falling back to " + " then ".join(backups)
    if str(b.get("router", "act")) == "jev":
        m = (cfg.get("agent", {}) or {}).get("model", "")
        if m:
            parts.append(f"the router is {m}")
    from . import config
    stt = config.stt_settings(cfg)
    if stt.get("provider") == "openai":
        host = urlparse(stt.get("base_url", "")).hostname or "a hosted service"
        parts.append(f"I hear you with {stt.get('model')} at {host}")
    else:
        parts.append("I hear you with whisper on this machine")
    line = ". ".join(parts) + "."
    if last:
        line += (f" My last call used {last['model']} "
                 f"through {last['provider']}.")
    return line


def spend_line(kind: str, cfg: dict, now=None, path=None) -> str:
    from . import ledger
    if kind == "spend_week":
        w = ledger.window(7, now, path)
        span = "in the last seven days"
        usd, calls = w["usd"], w["calls"]
    else:
        t = ledger.totals(now, path)
        span = "today"
        usd, calls = t["today_usd"], t["calls_today"]
    if not calls:
        return f"You haven't made any model calls {span}."
    paid = _money(usd)
    line = (f"You've spent {paid} {span}, across {_calls(calls)}."
            if usd > 0 else
            f"You've spent nothing {span}: {_calls(calls)}, all free "
            "or on your machine.")
    if kind == "spend_today":
        daily, _monthly = ledger.caps(cfg)
        if daily is not None:
            line += f" Your daily cap is ${daily:g}."
    return line


def version_line() -> str:
    from . import deploy, update
    rec = deploy.read() or {}
    ver = update.installed_version()
    commit = str(rec.get("commit") or "unknown")
    if ver == "unknown":
        return "I can't tell which version this is: there's no deploy " \
               "record on this machine."
    if commit != "unknown" and not ver.startswith(commit[:7]):
        return f"This is Wisp {ver}, commit {commit[:7]}."
    return f"This is a development build, commit {commit[:7]}."


def last_reply(session_tail=None) -> str:
    """The last thing Wisp said that was an answer (not a setting or one
    of these self answers)."""
    if session_tail is None:
        from . import session
        session_tail = session.tail(20)
    for turn in reversed(session_tail):
        if turn.get("route") == "setting":
            continue
        reply = str(turn.get("reply") or "").strip()
        if reply:
            return reply
    return ""


def wrong_line(errors=None) -> str:
    from . import copy as _copy
    if errors is None:
        from . import errlog
        errors = errlog.recent(1)
    if not errors:
        return "Nothing has gone wrong that I know of."
    code = errors[-1]["code"]
    msg, hint = _copy.ERRORS.get(code, _copy.ERRORS[_copy.UNKNOWN_ERROR])
    line = f"The last error: {msg}."
    return line + (f" {hint[0].upper()}{hint[1:]}." if hint else "")


def answer(kind: str, cfg: dict, *, copier=None, session_tail=None,
           now=None, ledger_path=None, errors=None, last=None) -> str:
    """The sentence to speak for `kind`. Reads local state only."""
    if kind == "model":
        if last is None:
            from . import ledger
            try:
                last = ledger.last_call()
            except Exception:
                last = None
        return models_line(cfg, last)
    if kind in ("spend_today", "spend_week"):
        try:
            return spend_line(kind, cfg, now, ledger_path)
        except Exception:
            return "I can't read the usage ledger right now."
    if kind == "version":
        return version_line()
    if kind == "again":
        reply = last_reply(session_tail)
        return reply[:1200] if reply else "I haven't said anything yet."
    if kind == "copy":
        reply = last_reply(session_tail)
        if not reply:
            return "I have nothing to copy yet."
        if copier is None:
            from . import dictate
            copier = dictate.copy_to_clipboard
        return "Copied." if copier(reply[:CLIP_CAP]) else \
            "I couldn't copy it: the clipboard tool isn't available."
    if kind == "wrong":
        return wrong_line(errors)
    return ""


def run(kind: str, cfg: dict) -> str:
    """Execute-stage entry: the result string the speak stage reads."""
    line = answer(kind, cfg)
    if not line:
        return "SKIP (unknown self question)"
    return f"ACTED (0 steps): {line}"
