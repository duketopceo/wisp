"""Sense layer — cheap, passive activity capture for the proactive loop.

Runs as one daemon thread on a slow tick. Sources are deliberately free
and local: Hyprland active-window deltas and `dayflow today --json`
block tails (dayflow already pays the screenshot/summarize cost — we
read its journal, we don't re-observe the screen). Everything lands in
~/.local/share/wisp/activity.jsonl, rotated past _MAX_BYTES.

Guardrails (S6): the loop is single-flight by construction (ticks run
inline), every tick is wrapped so a broken source can never kill the
daemon, and `[sense] enabled=false` is the default kill switch.
"""
import json
import subprocess
import threading
import time
from datetime import datetime, timezone

from . import config, pipeline, platform

ACTIVITY_FILE = config.DATA_DIR / "activity.jsonl"
_MAX_BYTES = 2 * 1024 * 1024


def _rotate(path) -> None:
    try:
        if path.stat().st_size > _MAX_BYTES:
            prev = path.with_suffix(".1.jsonl")
            prev.unlink(missing_ok=True)
            path.rename(prev)
    except OSError:
        pass


def _append(rec: dict, path=ACTIVITY_FILE) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate(path)
        with path.open("a") as f:
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")
    except OSError:
        pass


def _window() -> dict:
    """Focused window via the platform seam — the Hyprland socket on Linux, System
    Events on macOS, Win32 on Windows. Shelling hyprctl directly here
    meant macOS recorded nothing, silently, forever."""
    try:
        return platform.active_window()
    except Exception:
        return {}


def _dayflow_tail(env: dict, keep: int = 6) -> list:
    """Newest summarized blocks from the dayflow journal — text, not
    frames. Empty when dayflow isn't installed/running."""
    try:
        r = subprocess.run(["dayflow", "today", "--json"],
                           capture_output=True, text=True, timeout=20,
                           env=env)
        data = json.loads(r.stdout or "[]")
        blocks = data.get("blocks", data) if isinstance(data, dict) \
            else data
        out = []
        for b in (blocks or [])[-keep:]:
            if isinstance(b, dict):
                out.append({"title": b.get("title", "")[:120],
                            "category": b.get("category", ""),
                            "start": b.get("start", b.get("time", ""))})
        return out
    except Exception:
        return []


def tick(cfg: dict, seen: dict | None = None,
         path=ACTIVITY_FILE, log=None) -> dict:
    """One collection pass. Returns the record written (or {})."""
    sense = cfg.get("sense", {})
    env = pipeline.hypr_env()
    now = datetime.now(timezone.utc).isoformat()
    rec: dict = {"ts": now}
    w = _window()
    if w:
        rec["window"] = w
    if sense.get("dayflow", "true") == "true":
        n = max(1, int(sense.get("dayflow_every", "4") or 4))
        seen = seen if seen is not None else {}
        i = seen.get("ticks", 0) + 1
        seen["ticks"] = i
        if i % n == 0 or not seen.get("dayflow_done"):
            blocks = _dayflow_tail(env)
            if blocks:
                rec["dayflow"] = blocks
                seen["dayflow_done"] = True
    if len(rec) == 1:
        return {}  # nothing new worth storing
    _append(rec, path)
    return rec


def read_window(hours: float = 3.0, path=ACTIVITY_FILE) -> list:
    """Records newer than `hours` — the miner's input."""
    cutoff = time.time() - hours * 3600
    out = []
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return out
    for line in lines[-5000:]:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            ts = datetime.fromisoformat(
                rec.get("ts", "")).timestamp()
        except (ValueError, OSError):
            continue
        if ts >= cutoff:
            out.append(rec)
    return out


def run(cfg: dict, stop: threading.Event, log=None) -> None:
    """Daemon thread: tick every [sense] interval_s until `stop` sets.
    Never raises out — the observer must not take the daemon down."""
    log = log or (lambda m: None)
    seen = {}
    interval = int(cfg.get("sense", {}).get("interval_s", "300"))
    while not stop.wait(max(30, interval)):
        try:
            rec = tick(cfg, seen, log=log)
            if rec:
                log(f"sense: {list(rec.keys())[1:]} recorded")
        except Exception as e:
            log(f"sense error: {e}")
    log("sense: stopped")


def enabled(cfg: dict) -> bool:
    return cfg.get("sense", {}).get("enabled", "false") == "true"
