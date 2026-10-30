"""Dev tuning mode session (the switch): on/off, when it started and how
many runs it has seen. It lives in a daemon-owned file in the data dir,
never in config.toml, so turning the session off restores the owner's
settings exactly. The fifth completed run turns it off.

While a session is on, tracing is on (wisp/trace.py asks `is_on()`);
the owner's own `[debug] trace` value is never touched.
"""
import json
import os
import threading
from datetime import datetime, timezone

from . import config

MAX_RUNS = 5
_lock = threading.Lock()
_cache = (None, None)        # ((mtime_ns, size), parsed) for is_on()


def path():
    return config.DATA_DIR / "dev_session.json"


def _blank() -> dict:
    return {"on": False, "started_at": None, "runs_done": 0,
            "max_runs": MAX_RUNS}


def _read() -> dict:
    out = _blank()
    try:
        raw = json.loads(path().read_text())
    except (OSError, ValueError):
        return out
    if isinstance(raw, dict):
        out["on"] = raw.get("on") is True
        out["started_at"] = raw.get("started_at")
        try:
            out["runs_done"] = max(0, int(raw.get("runs_done", 0)))
            out["max_runs"] = max(1, int(raw.get("max_runs", MAX_RUNS)))
        except (TypeError, ValueError):
            pass
    return out


def _write(s: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(s, separators=(",", ":")))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def _view(s: dict) -> dict:
    return {**s, "runs_left": max(0, s["max_runs"] - s["runs_done"])
            if s["on"] else 0}


def status() -> dict:
    with _lock:
        return _view(_read())


def is_on() -> bool:
    """Cheap and cached on the file's stamp: trace.emit asks this on
    every event."""
    global _cache
    try:
        st = path().stat()
        key = (st.st_mtime_ns, st.st_size, str(path()))
    except OSError:
        return False
    if _cache[0] == key:
        return _cache[1]
    on = _read()["on"]
    _cache = (key, on)
    return on


def state_field(s: dict | None = None) -> dict:
    """The `dev` field published on the state stream."""
    s = s if s is not None else status()
    return {"on": bool(s["on"]), "runs_left": int(s["runs_left"])}


def turn_on() -> dict:
    with _lock:
        s = _read()
        if not s["on"]:
            s = {**_blank(), "on": True,
                 "started_at": datetime.now(timezone.utc).isoformat()}
            _write(s)
        return _view(s)


def turn_off() -> dict:
    with _lock:
        s = {**_blank()}
        _write(s)
        return _view(s)


def complete_run() -> dict:
    """Count one finished run; the last one of the session turns it off.
    No-op when the session is off."""
    with _lock:
        s = _read()
        if not s["on"]:
            return _view(s)
        s["runs_done"] += 1
        if s["runs_done"] >= s["max_runs"]:
            s["on"] = False
        _write(s)
        return _view(s)
