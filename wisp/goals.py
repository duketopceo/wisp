"""Active goal — what Wisp is working on across turns.

A voice-driven computer-use session is one goal ("get me to GDX on
robinhood") spoken as several utterances. Until now each utterance was
a fresh act and the "it's open right here" continuation restarted from
zero. goals.py holds the live goal; pipeline joins utterances to it by
shared focus-app or topic overlap; act.py reads it so the model sees
the running task + its recent steps.

TTL: [agent] goal_ttl_s (default 600). Status: open|done|failed.
"""
import re
import time

_WORDS = re.compile(r"[a-z0-9]+")

CURRENT: dict | None = None


def _tokens(text: str) -> set:
    return set(_WORDS.findall((text or "").lower()))


def related(a: str, b: str) -> bool:
    """Topic overlap via containment — a short follow-up that shares a
    content token with the open goal ('click on GDX' after 'get to GDX
    on robinhood') is a continuation, not a new task."""
    ta, tb = _tokens(a) - {"the", "a", "it", "to", "on", "in", "and"}, \
        _tokens(b) - {"the", "a", "it", "to", "on", "in", "and"}
    if not ta or not tb:
        return False
    return len(ta & tb) / min(len(ta), len(tb)) >= 0.5


def _fresh(cfg: dict) -> bool:
    if not CURRENT:
        return False
    ttl = float(cfg.get("agent", {}).get("goal_ttl_s", "600"))
    return time.time() - CURRENT.get("ts", 0) < ttl


def join_or_new(text: str, app: str, cfg: dict) -> tuple:
    """Return (goal, joined). Continues the open goal when same focus app
    or the utterance is topically related; else starts a new one."""
    global CURRENT
    if _fresh(cfg) and CURRENT.get("status") == "open":
        same_app = app and app == CURRENT.get("app")
        if same_app or related(CURRENT.get("text", ""), text):
            CURRENT["text"] += " ; then: " + text
            CURRENT["ts"] = time.time()
            return CURRENT, True
    CURRENT = {"text": text, "app": app or "", "ts": time.time(),
               "steps": [], "status": "open"}
    return CURRENT, False


def record_steps(steps: list) -> None:
    if CURRENT is not None:
        CURRENT["steps"] = (CURRENT.get("steps", []) + list(steps))[-12:]


def close(status: str = "done") -> None:
    global CURRENT
    if CURRENT is not None:
        CURRENT["status"] = status
    CURRENT = None if status == "done" else CURRENT


def snapshot() -> dict | None:
    return dict(CURRENT) if CURRENT else None


def context_text() -> str:
    """'[goal] get to gdx on robinhood (steps: launch → click…)' —
    injected into the act user message so continuations see the trail."""
    if not CURRENT:
        return ""
    steps = CURRENT.get("steps", [])
    tail = " → ".join(s.get("tool", "?") for s in steps[-6:]) \
        if steps else "starting"
    return (f"[goal] {CURRENT['text'][:160]} "
            f"(app={CURRENT.get('app') or '?'}; steps so far: {tail})")
