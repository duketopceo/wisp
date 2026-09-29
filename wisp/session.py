"""Persistent conversation memory — append-only JSONL session log.

Each completed turn appends one record. tail() reads the last N turns so
follow-ups ("repeat that", "yes do it") resolve against prior context.
Single writer (the daemon); readers tolerate a torn final line."""
import json
from datetime import datetime, timezone

from . import config


def append_turn(transcript: str, route: str = "", reply: str = "",
                result: str = "", path=config.SESSION_FILE) -> None:
    rec = {"ts": datetime.now(timezone.utc).isoformat(),
           "transcript": transcript, "route": route,
           "reply": reply, "result": result}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def tail(n: int = 8, path=config.SESSION_FILE) -> list[dict]:
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 65536))  # tail only the last 64KB
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-max(n * 2, 16):]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # tolerate a torn write
    return out[-n:]


def as_text(turns: list[dict]) -> str:
    """Compact transcript for Jev's state / the chat model."""
    parts = []
    for t in turns:
        said = t.get("transcript", "")
        reply = t.get("reply") or t.get("result", "")
        if said:
            parts.append(f"user: {said}")
        if reply:
            parts.append(f"wisp: {reply}")
    return "\n".join(parts)
