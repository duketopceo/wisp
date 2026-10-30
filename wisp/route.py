"""Local transcript/catalog rules for the no-model routing fast path."""
import re
import time

_RISK = {"launch": 0, "answer": 0, "dictation": 0, "clarify": 0,
         "tool": 1, "agent": 1, "learn": 1, "act": 2}

# -- heuristic ----------------------------------------------------------

_POLITE = re.compile(
    r"^(?:(?:hey|ok|okay)\s+)?(?:wisp[,:]?\s+)?"
    r"(?:(?:can|could|would|will)\s+you\s+)?(?:please\s+)?", re.I)
_DICTATE = re.compile(
    r"^(?:dictate|dictation|take dictation|type this|write this down|"
    r"write down)\b", re.I)
_AGENT = re.compile(
    r"^(?:have an agent|spawn (?:an? )?agent|delegate\b|agent[,:]|"
    r"(?:have |let |run )?(?:opencode|claude|codex|devin)\b|"
    r"(?:debug|fix|investigate) (?:this|it) in the background\b)", re.I)
_LEARN = re.compile(
    r"^(?:learn (?:how|to|that)\b|remember (?:this|how|that)\b|"
    r"add a skill\b|save (?:this )?as (?:my |a )?.{0,40}?\broutine\b|"
    r"create a routine\b)", re.I)
_WH = re.compile(
    r"^(?:what|what's|whats|who|whom|whose|when|where|why|how|which|"
    r"is|are|am|was|were|do|does|did|should|tell me|explain|define|"
    r"summari[sz]e|describe|give me|"
    r"show me (?:what|what's|whats|why|how|where|which))\b", re.I)
_SCREENSHOT = re.compile(r"\bscreenshot\b", re.I)
_WORKSPACE = re.compile(
    r"^(?:go to|switch to|move to|jump to)\s+workspace\s+\d+\b", re.I)
_LAUNCH = re.compile(
    r"^(?:open|launch|start|run|pull up|bring up|switch to|focus)\s+"
    r"(?P<rest>.+)$", re.I)
_ACT = re.compile(
    r"^(?:click|scroll|go to|navigate|search(?: for)?|find|type|press|"
    r"select|fill|close|quit|drag|play|pause|download|log ?in|sign in|"
    r"open|check|inspect|review|debug|fix|troubleshoot)\b|"
    r"\b(?:and then|then)\b", re.I)
_FILLER = re.compile(r"\b(?:the|app|application|up)\b", re.I)
_DEICTIC = re.compile(r"\b(?:this|that|these|those|here)\b", re.I)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _catalog_app(rest: str, apps: dict) -> str:
    if _DEICTIC.search(rest or ""):
        return ""
    want = _norm(_FILLER.sub(" ", rest))
    if not want:
        return ""
    for name in apps or {}:
        if _norm(name) == want:
            return name
    return ""


def _is_compound(rest: str) -> bool:
    return bool(re.search(r"\b(?:on|in|to|at|for|into|and|then|with)\s+\S",
                          rest, re.I))


def heuristic(text: str, apps: dict | None = None) -> dict:
    """Deterministic route from the transcript and the app catalog.
    -> {route, rule, app, tool, bare_launch}. Never raises."""
    t0 = time.perf_counter()
    out = _heuristic(text or "", apps or {})
    out["ms"] = round((time.perf_counter() - t0) * 1000, 2)
    return out


def _result(route, rule, app="", tool="", bare=False):
    return {"route": route, "rule": rule, "app": app, "tool": tool,
            "bare_launch": bare}


def _heuristic(text: str, apps: dict) -> dict:
    t = text.strip().rstrip(".!")
    t = _POLITE.sub("", t).strip()
    if not t or t.startswith("[") or not re.search(r"\w", t):
        return _result("clarify", "empty")
    if _DICTATE.match(t):
        return _result("dictation", "dictate_verb")
    if _AGENT.match(t):
        return _result("agent", "agent_verb")
    if _LEARN.match(t):
        return _result("learn", "learn_verb")
    if _WH.match(t):
        return _result("answer", "question_word")
    if _WORKSPACE.match(t):
        return _result("tool", "workspace", tool="workspace")
    if _SCREENSHOT.search(t):
        return _result("tool", "screenshot", tool="screenshot")
    m = _LAUNCH.match(t)
    if m:
        rest = m.group("rest")
        app = _catalog_app(rest, apps)
        if app and not _is_compound(rest):
            return _result("launch", "bare_launch", app=app, bare=True)
        return _result("act", "launch_compound" if app else "launch_unknown")
    if _ACT.search(t):
        return _result("act", "act_verb")
    if t.endswith("?"):
        return _result("answer", "question_mark")
    return _result("answer", "default_answer")


def heuristic_answers(h: dict) -> dict:
    """Typed route answers consumed by the execution stage."""
    conf = 0.95 if h["bare_launch"] else 0.7
    ans = {"route": {"choice": h["route"], "confidence": conf},
           "app": {"choice": h["app"] or "none", "confidence": conf},
           "risk": {"score": _RISK.get(h["route"], 2)}}
    if h["tool"]:
        ans["tool"] = {"choice": h["tool"]}
    return ans
