#!/usr/bin/env python3
"""Measure the latency budgets from the replay harness (fakes only).

    python scripts/latency_baseline.py            # print the report
    python scripts/latency_baseline.py --json     # machine-readable
    python scripts/latency_baseline.py --record   # rewrite the baseline
    python scripts/latency_baseline.py --check    # exit 1 past a ceiling
    python scripts/latency_baseline.py --from-trace FILE [FILE ...]
        # aggregate p50/p90 and the first-voice composite from recorded
        # trace files (read-only; no per-turn data is printed)

Never touches live models, hardware, hyprctl or cua-driver. The
baseline lands in docs/baselines/latency-harness.json.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from harness import latency  # noqa: E402
from wisp import telemetry  # noqa: E402


def from_trace(files: list) -> int:
    rep = telemetry.trace_baseline(*files)
    print(f"spoken turns: {rep['turns']}")
    print(f"{'stage':<12}{'n':>4}{'p50':>7}{'p90':>7}")
    for name, r in rep["stages"].items():
        print(f"{name:<12}{r['n']:>4}{r['p50']:>7}{r['p90']:>7}")
    c = rep["composite"]
    if c:
        print(f"first voice  n={c['n']} p50={c['p50']} p90={c['p90']} "
              f"p90/p50={c['ratio']} (derived lower bound for "
              f"{c['derived']} of {c['n']})")
    else:
        print("first voice  no spoken turns with the needed spans")
    return 0


def main(argv: list) -> int:
    if "--from-trace" in argv:
        return from_trace(argv[argv.index("--from-trace") + 1:])
    runs = 5
    series = latency.measure(runs)
    doc = latency.baseline(runs) if "--record" in argv else None
    bad = latency.check(series)
    if "--record" in argv:
        telemetry.BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
        telemetry.BASELINE_FILE.write_text(json.dumps(doc, indent=2) + "\n")
        print(f"recorded {telemetry.BASELINE_FILE}")
    rows = latency.summarize(series)
    if "--json" in argv:
        print(json.dumps({"paths": rows, "regressions": bad}, indent=2))
    else:
        print(f"{'path':<6}{'n':>3}{'p50':>6}{'p90':>6}{'budget':>8}")
        for pid, r in rows.items():
            print(f"{pid:<6}{r['n']:>3}{r['p50']:>6}{r['p90']:>6}"
                  f"{r['budget_p50_ms']:>8}")
        for b in bad:
            print("REGRESSION:", b)
    return 1 if bad and ("--check" in argv or "--record" in argv) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
