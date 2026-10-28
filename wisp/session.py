"""Persistent conversation memory — append-only JSONL session log.

Each completed turn appends one record. tail() reads the last N turns so
follow-ups ("repeat that", "yes do it") resolve against prior context.
Each record carries the focused app's window class, and tail(app=...)
returns only that app's turns, so a chat in the terminal does not leak
into a chat in the browser. Records from before the app field existed
have no app and only appear in an unscoped tail().
Single writer (the daemon); readers tolerate a torn final line."""
import json
from datetime import datetime, timezone

from . import config


def append_turn(transcript: str, route: str = "", reply: str = "",
                result: str = "", path=config.SESSION_FILE,
                app: str = "") -> None:
    rec = {"ts": datetime.now(timezone.utc).isoformat(),
           "transcript": transcript, "route": route,
           "reply": reply, "result": result, "app": _norm_app(app)}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def _norm_app(app) -> str:
    return str(app or "").strip().lower()


def tail(n: int = 8, path=config.SESSION_FILE,
         app: str | None = None) -> list[dict]:
    """The last `n` turns. With `app` (a window class) only that app's
    turns; an empty `app` matches turns logged with no app. None is the
    unscoped tail."""
    scoped = app is not None
    want = _norm_app(app)
    # a scoped tail reads further back: other apps' turns are skipped
    window = 262144 if scoped else 65536
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - window))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []
    out = []
    for line in (lines if scoped else lines[-max(n * 2, 16):]):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue  # tolerate a torn write
        if not isinstance(rec, dict):
            continue
        if scoped and _norm_app(rec.get("app")) != want:
            continue
        out.append(rec)
    return out[-n:]


def _spoken_result(result: str) -> str:
    """Turn an act-loop outcome into conversation — 'ACTED (3 steps):
    opened it' reads as 'opened it'; raw SKIP/ERROR noise becomes a
    short honest admission instead of internal jargon."""
    import re
    if not result:
        return ""
    m = re.match(r"^ACTED \(\d+ steps\):\s*(.*)", result, re.S)
    if m:
        return m.group(1).strip()
    m = re.match(r"^ASK_USER[ :]\s*(.*)", result, re.S)
    if m:
        # act loop logs 'ASK_USER x'; the answer route logs 'ASK_USER: x'
        return "asked: " + m.group(1).strip()
    if result.startswith(("SKIP", "ERROR", "ABORTED", "INTERRUPTED")):
        # strip the status word + parenthesized cause → human reason
        cause = re.sub(r"^\w+\s*\((.*)\)\s*$", r"\1", result).strip()
        cause = cause.split(":", 1)[-1].strip()[:80] or "it failed"
        return "couldn't do that — " + cause
    return result


def as_text(turns: list[dict]) -> str:
    """Compact transcript for Jev's state / the chat model."""
    parts = []
    for t in turns:
        said = t.get("transcript", "")
        reply = t.get("reply") or _spoken_result(t.get("result", ""))
        if said:
            parts.append(f"user: {said}")
        if reply:
            parts.append(f"wisp: {reply}")
    return "\n".join(parts)
