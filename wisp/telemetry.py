"""Telemetry digest — reads decisions.jsonl (which already carries
timing_ms per turn) + trace.jsonl for step-level detail. Local-only;
no new writes — the ledger is decisions/trace, this is the lens.
"""
import json
import math
import pathlib
from collections import Counter
from datetime import datetime, timedelta, timezone

from . import config, trace

DECISIONS = config.DECISIONS


def _load(path) -> list:
    """Parsed JSON lines; unreadable files and corrupt lines are skipped."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        if not ln.strip():
            continue
        try:
            row = json.loads(ln)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


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


# --- latency report (U1) ---------------------------------------------
# The budget table is data: wisp/budgets.json (plan section 7). Each path
# has a p50 ceiling; the verdict also requires p90 <= P90_FACTOR x budget.
BUDGETS_FILE = pathlib.Path(__file__).with_name("budgets.json")


def load_budgets() -> dict:
    return json.loads(BUDGETS_FILE.read_text())


_TABLE = load_budgets()
BUDGETS = [(p["id"], p["label"], p["budget_p50_ms"])
           for p in _TABLE["paths"]]
P90_FACTOR = _TABLE["p90_factor"]   # Definition of Done: p90 within 1.5x
_SPAN = {p["id"]: p["span"] for p in _TABLE["paths"]}
BASELINE_FILE = (pathlib.Path(__file__).resolve().parent.parent
                 / "docs" / "baselines" / "latency-harness.json")


def budgets_text() -> str:
    t = load_budgets()
    lines = [f"latency budgets (p50 ms; p90 <= {t['p90_factor']}x)",
             f"  {'path':<36}{'budget':>8}  harness"]
    for p in t["paths"]:
        lines.append(f"  {p['id'] + ' ' + p['label']:<36}"
                     f"{p['budget_p50_ms']:>8}  {p['harness']}")
    r = t["resources"]
    lines.append(f"  wispd <= {r['wispd_rss_mb']} MB RSS and "
                 f"{r['wispd_idle_cpu_pct']}% idle CPU; cua-driver "
                 f"MemoryMax={r['cua_driver_memory_max']}; Companion <= "
                 f"{r['companion_idle_cpu_pct_120hz']}% CPU at 120 Hz idle")
    return "\n".join(lines)


def load_baseline() -> dict:
    """The committed harness baseline (fakes only), or {} if absent."""
    try:
        return json.loads(BASELINE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def parse_since(s) -> float:
    """'24h' | '90m' | '2d' | '6' -> hours."""
    s = str(s).strip().lower()
    try:
        if s.endswith("d"):
            return float(s[:-1]) * 24
        if s.endswith("m"):
            return float(s[:-1]) / 60
        return float(s[:-1] if s.endswith("h") else s)
    except ValueError:
        return 24.0


def _pct(vals: list, p: float):
    """Nearest-rank percentile."""
    v = sorted(vals)
    return v[max(1, math.ceil(p * len(v) / 100)) - 1]


def latency_report(since_hours: float = 24, trace_file=None) -> dict:
    """{turns, rows:[{id,label,n,p50,p90,budget_p50,verdict}]} from the
    `span` events in trace.jsonl. P4 and E2E are composed per turn."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    per_turn: dict = {}
    for e in _load(trace_file or trace.TRACE_FILE):
        if e.get("kind") != "span" or not isinstance(e.get("ms"),
                                                      (int, float)):
            continue
        try:
            if datetime.fromisoformat(e.get("ts", "")) < cutoff:
                continue
        except ValueError:
            continue
        per_turn.setdefault(e["turn"], {})[e["step"]] = e["ms"]
    series = {k: [] for k, _, _ in BUDGETS}
    for m in per_turn.values():
        for pid, name in _SPAN.items():
            if pid not in ("P4", "E2E") and name in m:
                series[pid].append(m[name])
        if "route" in m:
            series["P4"].append(m["route"] + m.get("context", 0))
        if all(k in m for k in ("stt", "route", "first_token")):
            series["E2E"].append(m["stt"] + m.get("context", 0)
                                 + m["route"] + m["first_token"])
    rows = []
    for pid, label, budget in BUDGETS:
        vals = series[pid]
        row = {"id": pid, "label": label, "n": len(vals),
               "budget_p50": budget, "p50": None, "p90": None,
               "verdict": "no data"}
        if vals:
            row["p50"], row["p90"] = _pct(vals, 50), _pct(vals, 90)
            ok = row["p50"] <= budget and row["p90"] <= budget * P90_FACTOR
            row["verdict"] = "ok" if ok else "MISS"
        rows.append(row)
    return {"turns": len(per_turn), "rows": rows}


def latency_text(since_hours: float = 24, trace_file=None) -> str:
    rep = latency_report(since_hours, trace_file)
    h = f"{since_hours:g}h"
    if not rep["turns"]:
        return f"no spans in the last {h} (run a turn first)"
    lines = [f"latency {h} - {rep['turns']} turns "
             f"(ms; verdict: p50 <= budget and p90 <= {P90_FACTOR}x)",
             f"  {'path':<36}{'n':>4}{'p50':>7}{'p90':>7}{'budget':>8}  "]
    for r in rep["rows"]:
        if r["n"]:
            lines.append(f"  {r['id'] + ' ' + r['label']:<36}{r['n']:>4}"
                         f"{r['p50']:>7}{r['p90']:>7}"
                         f"{r['budget_p50']:>8}  {r['verdict']}")
        else:
            lines.append(f"  {r['id'] + ' ' + r['label']:<36}{0:>4}"
                         f"{'-':>7}{'-':>7}{r['budget_p50']:>8}  no data")
    return "\n".join(lines)
