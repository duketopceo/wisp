"""Dev trace — full-fidelity event stream for dogfooding (issue #23).

One append-only JSONL line per stage event at
~/.local/state/wisp/trace.jsonl (data_dir). Every turn gets a
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
import time
from contextlib import contextmanager
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


# Spans bound to a live turn, so the first tool call a turn makes can
# close its `first_step` span without act.py knowing about spans.
_ACTIVE: dict = {}


def emit(turn: str, step: str, kind: str,
         data: dict | None = None, ms: int | None = None) -> None:
    """Append one event. Silent no-op when disabled or on IO failure —
    tracing must never break a turn."""
    if kind == "tool" and step == "tool_call":
        sp = _ACTIVE.get(turn)
        if sp is not None:
            sp.fire("first_step")
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


_T0_MAX_AGE_NS = 10_000_000_000   # older client stamps are not trusted
_T0_MAX_SKEW_NS = 50_000_000      # client clock a hair ahead is tolerated


class Spans:
    """Stage spans for one turn, timed from the keypress (U1).

    Each span is a duration from a named start to now, emitted as a
    trace event `kind=span`, `step=<name>`, `ms=<duration>`, with
    `data.offset_ms` (time since the turn's t0) and `data.t0_source`.
    `t0` is the client's wall-clock ns (`time.time_ns()`, which a shell
    client can also produce); the daemon converts it onto its own
    monotonic clock. A missing or implausible stamp starts the turn at
    request receipt and flags `t0_source = daemon`.

    Spans buffer until `bind(turn)` supplies the turn id (the press
    happens before the pipeline thread mints it).
    """

    def __init__(self, t0_ns=None, clock=time.monotonic_ns,
                 wall=time.time_ns):
        self._clock = clock
        self._wall = wall
        self.t0, self.t0_source = self._resolve(t0_ns)
        self.rel0, self.rel0_source = self.t0, self.t0_source
        self.turn = None
        self.ms = {}
        self._end = {}
        self._pending = []
        self._armed = {}
        self._lock = threading.Lock()

    def _resolve(self, t0_ns):
        now = self._clock()
        if isinstance(t0_ns, int) and not isinstance(t0_ns, bool) \
                and t0_ns > 0:
            age = self._wall() - t0_ns
            if -_T0_MAX_SKEW_NS <= age <= _T0_MAX_AGE_NS:
                return now - max(age, 0), "client"
        return now, "daemon"

    def now(self) -> int:
        return self._clock()

    def set_release(self, t0_ns=None) -> None:
        """Key-up instant: a client wall-clock stamp, else now."""
        self.rel0, self.rel0_source = self._resolve(t0_ns)

    def adopt_release(self, other: "Spans") -> None:
        """Take another request's start as this turn's key-up (the
        daemon builds a Spans per request, then hands the release one
        to the turn's Spans)."""
        self.rel0, self.rel0_source = other.t0, other.t0_source

    def mark_ns(self, name: str) -> int:
        """End instant of an already recorded span."""
        return self._end[name]

    def record(self, name: str, start_ns: int, **data) -> int:
        end = self._clock()
        ms = round((end - start_ns) / 1e6)
        with self._lock:
            self.ms[name] = ms
            self._end[name] = end
            ev = (name, ms, dict(
                data, offset_ms=round((end - self.t0) / 1e6),
                t0_source=self.t0_source))
            if self.turn is None:
                self._pending.append(ev)
                return ms
        emit(self.turn, ev[0], "span", ev[2], ms=ev[1])
        return ms

    @contextmanager
    def timed(self, name: str, **data):
        start = self._clock()
        try:
            yield
        finally:
            self.record(name, start, **data)

    def bind(self, turn: str) -> None:
        """Attach the turn id, flush buffered spans, and go live."""
        with self._lock:
            self.turn = turn
            pending, self._pending = self._pending, []
        _ACTIVE[turn] = self
        for name, ms, data in pending:
            emit(turn, name, "span", data, ms=ms)

    def close(self) -> None:
        if self.turn:
            _ACTIVE.pop(self.turn, None)

    def arm(self, name: str, start_ns=None) -> None:
        """Let the next `fire(name)` record a span from now."""
        self._armed[name] = start_ns if start_ns is not None \
            else self._clock()

    def fire(self, name: str) -> None:
        start = self._armed.pop(name, None)
        if start is not None:
            self.record(name, start)

    def legacy_timing(self) -> dict:
        """The pre-U1 aggregate keys, derived from spans, for
        decisions.jsonl consumers (`evalroute`, `tele`)."""
        m = self.ms
        out = {"record_ms": m.get("record", 0)}
        if "stt" in m:
            out["stt_ms"] = m["stt"]
        if "context" in m or "route" in m:
            out["jev_ms"] = m.get("context", 0) + m.get("route", 0)
        if "done" in m:
            out["act_ms"] = m["done"]
        return out


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
    """`wispd trace [--tail N] [--turn id] [--kind k]` — pretty-print;
    `wispd trace --latency [--since 24h]` — p50/p90 per budget path."""
    tail, turn, kind = 50, "", ""
    latency, since = False, "24h"
    it = iter(argv)
    for a in it:
        if a == "--latency":
            latency = True
        elif a == "--since":
            since = next(it, "24h")
        elif a == "--tail":
            tail = int(next(it, "50"))
        elif a == "--turn":
            turn = next(it, "")
        elif a == "--kind":
            kind = next(it, "")
    if latency:
        from . import telemetry
        print(telemetry.latency_text(telemetry.parse_since(since)))
        return 0
    for ev in read(tail=tail, turn=turn, kind=kind):
        ms = f" {ev['ms']}ms" if ev.get("ms") is not None else ""
        data = json.dumps(ev.get("data", {}), ensure_ascii=False)
        print(f"{ev['ts'][11:19]} {ev['turn']} {ev['kind']}/"
              f"{ev['step']}{ms} {data[:400]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
