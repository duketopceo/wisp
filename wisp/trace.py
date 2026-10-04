"""Dev trace — full-fidelity event stream for dogfooding (issue #23).

One append-only JSONL line per stage event at
~/.local/share/wisp/trace.jsonl (data_dir). Every turn gets a
short id so `wispd trace --turn <id>` replays a whole push-to-talk
cycle; daemon/IPC traffic logs under turn "sys".

NEVER log secrets: callers pass endpoint/model/status — never headers
or resolved key values.
"""
import json
import os
import secrets
import sys
import threading
from datetime import datetime, timezone

from . import config

TRACE_FILE = config.DATA_DIR / "trace.jsonl"
_MAX_MB = 10       # rotate trace.jsonl -> trace.1.jsonl past this
_DATA_BYTES = 8192  # per-field JSON truncation
_enabled = None    # cached after first check


def _cfg_flag() -> bool:
    global _enabled
    if _enabled is None:
        v = config.load_config().get("debug", {}).get("trace", "true")
        _enabled = str(v).lower() not in ("false", "0", "no", "off")
    return _enabled


def reset_cache() -> None:
    global _enabled
    _enabled = None


_local = threading.local()


def new_turn() -> str:
    turn = f"t{secrets.token_hex(4)}"
    _local.turn = turn
    return turn


def current() -> str:
    """Turn id for implicit emitters (tool calls inside execute)."""
    return getattr(_local, "turn", "sys")


def _clip(obj):
    """Truncate long strings inside event data."""
    if isinstance(obj, str):
        return obj if len(obj.encode()) <= _DATA_BYTES \
            else obj.encode()[:_DATA_BYTES].decode(errors="replace") + "…"
    if isinstance(obj, dict):
        return {k: _clip(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clip(v) for v in obj]
    return obj


def _rotate(path) -> None:
    try:
        if path.stat().st_size > _MAX_MB * 1024 * 1024:
            prev = path.with_suffix(".1.jsonl")
            try:
                prev.unlink()
            except FileNotFoundError:
                pass
            path.rename(prev)
    except OSError:
        pass


def emit(turn: str, step: str, kind: str,
         data: dict | None = None, ms: int | None = None) -> None:
    """Append one event. Silent no-op when disabled or on IO failure —
    tracing must never break a turn."""
    if not _cfg_flag():
        return
    ev = {"ts": datetime.now(timezone.utc).isoformat(), "turn": turn,
          "step": step, "kind": kind, "ms": ms,
          "data": _clip(data or {})}
    try:
        TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _rotate(TRACE_FILE)
        with open(TRACE_FILE, "a") as f:
            f.write(json.dumps(ev, separators=(",", ":")) + "\n")
    except OSError:
        pass


def read(path=None, tail: int = 50, turn: str = "",
         kind: str = "") -> list:
    """Parse the trace back — the debug surface for us and Jev."""
    path = path or TRACE_FILE
    events = []
    try:
        for line in path.read_text().splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(ev, dict) or "turn" not in ev \
                    or "step" not in ev:
                continue  # valid JSON but not a trace event
            if turn and ev.get("turn") != turn:
                continue
            if kind and ev.get("kind") != kind:
                continue
            events.append(ev)
    except OSError:
        return []
    return events[-tail:]


def main(argv: list) -> int:
    """`wispd trace [--tail N] [--turn id] [--kind k]` — pretty-print."""
    tail, turn, kind = 50, "", ""
    it = iter(argv)
    for a in it:
        if a == "--tail":
            tail = int(next(it, "50"))
        elif a == "--turn":
            turn = next(it, "")
        elif a == "--kind":
            kind = next(it, "")
    for ev in read(tail=tail, turn=turn, kind=kind):
        ms = f" {ev['ms']}ms" if ev.get("ms") is not None else ""
        data = json.dumps(ev.get("data", {}), ensure_ascii=False)
        print(f"{ev['ts'][11:19]} {ev['turn']} {ev['kind']}/"
              f"{ev['step']}{ms} {data[:400]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
