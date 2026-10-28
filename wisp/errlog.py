"""Typed errors, kept locally for `wispd bugreport`.

One line per turn that ended in an error: the time, the closed-set error
code (wisp/errors_codes.py) and the exception's type name. Never the
message, the transcript or anything the exception carried. Bounded, 0600,
and read by nothing that sends it anywhere.
"""
import json
from datetime import datetime, timezone

from . import config, private

FILE = config.DATA_DIR / "errors.jsonl"
KEEP = 200


def record(code: str, exc=None, path=None) -> None:
    """Append one entry. Never raises."""
    path = path or FILE
    rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "code": str(code or "internal")[:40],
           "exc": type(exc).__name__ if exc is not None else ""}
    try:
        with private.open_append(path) as f:
            f.write(json.dumps(rec) + "\n")
        if path.stat().st_size > KEEP * 100:
            _trim(path)
    except OSError:
        pass


def _trim(path) -> None:
    lines = path.read_text().splitlines()[-KEEP:]
    tmp = path.with_name(path.name + ".tmp")
    with private.open_write(tmp) as f:
        f.write("\n".join(lines) + "\n")
    tmp.replace(path)


def recent(n: int = 10, path=None) -> list:
    """The last `n` entries, newest last. Unreadable or corrupt lines are
    skipped."""
    path = path or FILE
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("code"):
            out.append({"ts": str(r.get("ts", "")),
                        "code": str(r["code"]),
                        "exc": str(r.get("exc", ""))})
    return out[-n:] if n > 0 else []
