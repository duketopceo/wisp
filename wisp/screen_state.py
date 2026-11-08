"""Can a screenshot be taken right now? A locked session or a desktop with
no live output has nothing to capture, and a background routine that kept
trying logged one "screenshot failed" per step all night. `unavailable()`
names the reason up front; callers skip capture-dependent work and say why
once (`report_once`). Every probe fails OPEN: if a tool is missing or the
answer is unreadable the screen is assumed available, so a broken probe
can never block a real capture."""
from __future__ import annotations

import json
import os
import subprocess
import time

PREFIX = "SKIP (screen unavailable"
_LOCKERS = ("hyprlock", "swaylock", "gtklock", "waylock")
_TTL_S = 2.0
_cache: dict = {"at": -1e9, "why": ""}
_reported: set = set()


def _run(cmd: list, timeout: float = 1.5):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _locked(run) -> bool:
    sid = os.environ.get("XDG_SESSION_ID") or "auto"
    out = run(["loginctl", "show-session", sid, "-p", "LockedHint",
               "--value"])
    if out is not None and out.strip().lower() == "yes":
        return True
    for name in _LOCKERS:
        if (run(["pgrep", "-x", name]) or "").strip():
            return True
    return False


def _no_live_output(run) -> bool:
    out = run(["hyprctl", "monitors", "-j"])
    if out is None:
        return False
    try:
        mons = json.loads(out)
    except ValueError:
        return False
    if not isinstance(mons, list):
        return False
    return not any(m.get("dpmsStatus", True) for m in mons
                   if isinstance(m, dict))


def unavailable(cfg: dict | None = None, run=None, clock=time.monotonic,
                use_cache: bool = True) -> str:
    """'' when a capture can proceed, else a short reason."""
    if ((cfg or {}).get("screen", {}) or {}).get("dom_page"):
        return ""              # a DOM shot needs no compositor output
    now = clock()
    if run is None and use_cache and now - _cache["at"] < _TTL_S:
        return _cache["why"]
    probe = run or _run
    if _locked(probe):
        why = "session locked"
    elif _no_live_output(probe):
        why = "no live output (displays off)"
    else:
        why = ""
    if run is None:
        _cache.update(at=now, why=why)
    return why


def skip_text(why: str) -> str:
    return f"{PREFIX}: {why}; capture steps wait until it is back)"


def is_unavailable(result: str) -> bool:
    return str(result).startswith(PREFIX)


def report_once(why: str, log=None) -> bool:
    """True the first time `why` is seen since the screen was last
    available; the caller logs only then. `clear()` re-arms it."""
    if why in _reported:
        return False
    _reported.add(why)
    if log:
        log(f"screen unavailable ({why}): skipping capture steps until it "
            "is back")
    return True


def clear() -> None:
    _reported.clear()
    _cache.update(at=-1e9, why="")


def clear_reported() -> None:
    """The screen is back: re-arm the once-only report."""
    _reported.clear()
