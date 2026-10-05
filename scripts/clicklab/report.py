#!/usr/bin/env python3
"""clicklab run report — group records from clicklab.jsonl by
model x suite and print verified-rate, spend, and calls-per-verified
task (the learning metric: it should fall over time).

  report.py [--since TS] [--json OUT] [--file PATH]

  --since   ISO ts ("2026-10-05T14:00:00") or unix seconds; only
            records at/after it are counted. Default: all records.
  --json    also write the grouped table to a JSON file.
"""
import json
import pathlib
import sys
import time

OUT = (pathlib.Path.home() / ".local" / "share" / "wisp"
       / "clicklab.jsonl")


def _flag(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        return True
    return default


def _since(v):
    try:
        return float(v)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return time.mktime(time.strptime(v, fmt))
        except ValueError:
            continue
    raise SystemExit(f"[report] bad --since '{v}'")


def summarize(records):
    """Group by (model, suite): {n, verified, cost, calls_per_verified}."""
    groups = {}
    for r in records:
        key = (r.get("model") or "?", r.get("suite") or "?")
        g = groups.setdefault(key, {"n": 0, "verified": 0,
                                    "cost": 0.0})
        g["n"] += 1
        g["verified"] += 1 if r.get("verified") else 0
        g["cost"] += r.get("cost_usd") or 0.0
    return groups


def render(groups):
    rows = []
    for (model, suite), g in sorted(groups.items()):
        cpv = g["n"] / g["verified"] if g["verified"] else float("inf")
        rows.append({
            "model": model, "suite": suite, "tasks": g["n"],
            "verified": g["verified"],
            "rate": round(100 * g["verified"] / g["n"], 1),
            "cost_usd": round(g["cost"], 4),
            "calls_per_verified": (round(cpv, 2)
                                   if cpv != float("inf") else None)})
    return rows


def main():
    path = pathlib.Path(_flag("--file") or OUT)
    since = _flag("--since")
    floor = _since(since) if since else 0.0
    records = []
    try:
        for line in path.open():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = r.get("ts")
            try:
                tsf = float(ts) if not isinstance(ts, str) else \
                    time.mktime(time.strptime(
                        ts[:19], "%Y-%m-%dT%H:%M:%S"))
            except (ValueError, TypeError):
                tsf = 0.0
            if tsf >= floor:
                records.append(r)
    except FileNotFoundError:
        print(f"[report] no ledger at {path}")
        return
    if not records:
        print("[report] no records in window")
        return
    rows = render(summarize(records))
    print(f"[report] {len(records)} records"
          + (f" since {since}" if since else ""))
    print(f"{'model':<40} {'suite':<16} {'n':>4} {'ok':>4} "
          f"{'rate%':>6} {'$':>8} {'calls/ok':>8}")
    for r in rows:
        print(f"{r['model']:<40} {r['suite']:<16} {r['tasks']:>4} "
              f"{r['verified']:>4} {r['rate']:>6} "
              f"{r['cost_usd']:>8} "
              f"{r['calls_per_verified'] or '-':>8}")
    out = _flag("--json")
    if out:
        pathlib.Path(out).write_text(json.dumps(rows, indent=1))
        print(f"[report] wrote {out}")


if __name__ == "__main__":
    main()
