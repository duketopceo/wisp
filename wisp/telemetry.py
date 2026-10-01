"""Telemetry digest — reads decisions.jsonl (which already carries
timing_ms per turn) + trace.jsonl for step-level detail. Local-only;
no new writes — the ledger is decisions/trace, this is the lens.
"""
import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from . import config, trace

DECISIONS = config.DECISIONS


def _load(path) -> list:
    try:
        return [json.loads(l) for l in path.read_text().splitlines()
                if l.strip()]
    except OSError:
        return []


def digest(hours: int = 24, decisions_file=None,
           trace_file=None) -> dict:
    """{turns, routes{}, avg_ms{}, outcomes{}, per_hour[24],
    model_latency_ms}"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    decs, routes, outcomes = [], Counter(), Counter()
    ms_sums, ms_n = Counter(), Counter()
    per_hour = [0] * min(hours, 24)
    for d in _load(decisions_file or DECISIONS):
        try:
            ts = datetime.fromisoformat(d.get("ts", ""))
        except ValueError:
            continue
        if ts < cutoff:
            continue
        decs.append(d)
        route = (d.get("answers", {}).get("route") or {}) \
            .get("choice", "?")
        routes[route] += 1
        res = d.get("result", "")
        ok = not res.startswith(("ABORTED", "BLOCKED", "ERROR",
                                 "CANCELLED", "FAIL", "SKIP"))
        outcomes["ok" if ok else "fail"] += 1
        per_hour[max(0, min(hours - 1, int(
            (datetime.now(timezone.utc) - ts).total_seconds()
            // 3600)))] += 1
        for k, v in (d.get("timing_ms") or {}).items():
            if isinstance(v, (int, float)):
                ms_sums[k] += v
                ms_n[k] += 1
    spans = _load(trace_file or trace.TRACE_FILE)
    tools = Counter(s.get("step") for s in spans
                    if s.get("kind") == "act")
    return {
        "turns": len(decs),
        "routes": dict(routes),
        "outcomes": dict(outcomes),
        "avg_ms": {k: round(ms_sums[k] / ms_n[k]) for k in ms_sums},
        "per_hour": list(reversed(per_hour)),
        "top_tools": dict(tools.most_common(8)),
    }


def text(hours: int = 24) -> str:
    d = digest(hours)
    if not d["turns"]:
        return f"no turns in the last {hours}h"
    rate = (100 * d["outcomes"].get("ok", 0)
            / max(1, d["turns"]))
    lines = [f"telemetry {hours}h — {d['turns']} turns, "
             f"{rate:.0f}% ok"]
    lines.append("  routes: " + ", ".join(
        f"{k}:{v}" for k, v in
        sorted(d["routes"].items(), key=lambda kv: -kv[1])))
    if d["avg_ms"]:
        lines.append("  avg ms: " + ", ".join(
            f"{k}={v}" for k, v in sorted(d["avg_ms"].items())))
    if d["top_tools"]:
        lines.append("  tools: " + ", ".join(
            f"{k}×{v}" for k, v in d["top_tools"].items()))
    return "\n".join(lines)
