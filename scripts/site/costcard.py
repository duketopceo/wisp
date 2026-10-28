#!/usr/bin/env python3
"""Write site/costs.json from the owner's own spend ledger.

    python3 scripts/site/costcard.py [--ledger PATH] [--days 30] [--out site/costs.json]

Reads `usage.jsonl` (the ledger `wispd spend` reads) and states what ONE
person spent: median USD per paid model call, median and maximum USD on a
day of use, median calls per day. Every item names its source and the date
window. Local-model rows (usd 0) and unpaid rows are not counted as paid
calls. It never sends anything anywhere.
"""
import argparse
import datetime as dt
import json
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


def card(rows, today, days=30) -> dict:
    """Pure: ledger rows -> the costs.json dict."""
    start = today - dt.timedelta(days=days)
    paid, per_day = [], {}
    for r in rows:
        ts = str(r.get("ts", ""))[:10]
        try:
            d = dt.date.fromisoformat(ts)
        except ValueError:
            continue
        if not (start <= d <= today):
            continue
        try:
            usd = float(r.get("usd") or 0)
        except (TypeError, ValueError):
            continue
        if not r.get("paid") or usd <= 0:
            continue
        paid.append(usd)
        per_day.setdefault(d, []).append(usd)
    win = f"{start.isoformat()} to {today.isoformat()}"
    out = {"status": "pending", "generated": today.isoformat(),
           "note": "These are one person's numbers, not a promise. The "
                   "model bill is the only cost.",
           "items": []}
    if not paid:
        out["note"] += " No paid calls in the window, so there are no " \
                       "measured numbers yet."
        return out
    sums = [sum(v) for v in per_day.values()]
    src = f"owner's usage.jsonl, {win}, {len(per_day)} days of use, " \
          f"{len(paid)} paid calls"
    for label, val in (
            ("Median cost of one paid model call",
             f"${statistics.median(paid):.4f}"),
            ("Median cost of a day of use",
             f"${statistics.median(sums):.2f}"),
            ("Most expensive day",
             f"${max(sums):.2f}"),
            ("Median paid calls on a day of use",
             f"{statistics.median(len(v) for v in per_day.values()):g}")):
        out["items"].append({"label": label, "value": val, "kind": "ledger",
                             "source": src, "as_of": today.isoformat()})
    out["status"] = "measured"
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--out", default=str(ROOT / "site" / "costs.json"))
    a = ap.parse_args(argv)
    from wisp import ledger
    target = pathlib.Path(a.ledger) if a.ledger else ledger.path()
    data = card(list(ledger._rows(target)), dt.date.today(), a.days)
    base = json.loads((ROOT / "site" / "costs.json").read_text("utf-8"))
    # keep the code defaults, add the measured numbers after them
    data["items"] = [i for i in base["items"] if i["kind"] == "repo"] + \
        data["items"]
    pathlib.Path(a.out).write_text(
        json.dumps(data, indent=1) + "\n", "utf-8")
    print(f"{data['status']}: {len(data['items'])} items -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
