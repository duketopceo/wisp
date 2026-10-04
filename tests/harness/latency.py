"""Latency measurement from the replay harness (W2).

Runs a fixed set of fixture turns against the fakes (no models, no
network, no hardware) and extracts one sample per budget path from the
trace spans and state events. Fakes answer in about a millisecond, so
these numbers bound the CODE overhead of a path, not model latency: a
live baseline is still needed for real STT / Jev / brain / UI-TARS time.
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE.parent))

from wisp import telemetry  # noqa: E402
from harness import runner  # noqa: E402

# fixture -> flags. `offline` fixtures also yield P10; `stop` yields P9.
SUITE = [
    ("ask", {}),
    ("act_click_cua", {}),
    ("cancel_mid_act", {}),
    ("brain_down", {"offline": True}),
    ("jev_down", {"offline": True}),
]


def samples(res, offline: bool = False) -> dict:
    """{path id: ms} for the paths this one turn exercised."""
    sp = {}
    for e in res.trace:
        if e.get("kind") == "span" and isinstance(e.get("ms"),
                                                   (int, float)):
            sp[e["step"]] = e["ms"]
    out = {}
    for pid, name in (("P3", "stt"), ("P5", "first_token"),
                      ("P6", "tts_start"), ("P7", "first_step")):
        if name in sp:
            out[pid] = sp[name]
    if "route" in sp:
        out["P4"] = sp["route"] + sp.get("context", 0)
    if all(k in sp for k in ("stt", "route", "first_token")):
        out["E2E"] = (sp["stt"] + sp.get("context", 0) + sp["route"]
                      + sp["first_token"])
    stop = runner.stop_ms(res)
    if stop is not None:
        out["P9"] = stop
    if offline:
        err = [e["t_ms"] for e in res.events if e["status"] == "error"]
        if err:
            out["P10"] = err[0]
    return out


def measure(runs: int = 3, suite=SUITE) -> dict:
    """{path id: [ms, ...]} over `runs` passes of the suite."""
    series: dict = {}
    for _ in range(runs):
        for name, flags in suite:
            res = runner.run_turn(name)
            for pid, ms in samples(res, **flags).items():
                series.setdefault(pid, []).append(ms)
    return series


def summarize(series: dict) -> dict:
    table = {p["id"]: p for p in telemetry.load_budgets()["paths"]}
    out = {}
    for pid, vals in series.items():
        out[pid] = {"label": table[pid]["label"], "n": len(vals),
                    "p50": telemetry._pct(vals, 50),
                    "p90": telemetry._pct(vals, 90), "max": max(vals),
                    "budget_p50_ms": table[pid]["budget_p50_ms"]}
    return out


def check(series: dict) -> list:
    """Regressions: p50 over the budget, or p90 over 1.5x the budget."""
    bad = []
    for pid, row in summarize(series).items():
        if row["p50"] > row["budget_p50_ms"]:
            bad.append(f"{pid} p50 {row['p50']} ms > budget "
                       f"{row['budget_p50_ms']} ms")
        if row["p90"] > row["budget_p50_ms"] * telemetry.P90_FACTOR:
            bad.append(f"{pid} p90 {row['p90']} ms > "
                       f"{telemetry.P90_FACTOR}x budget "
                       f"{row['budget_p50_ms']} ms")
    return bad


def baseline(runs: int = 5) -> dict:
    """The document committed as docs/baselines/latency-harness.json."""
    import datetime
    series = measure(runs)
    table = telemetry.load_budgets()["paths"]
    return {
        "recorded": datetime.date.today().isoformat(),
        "fakes_only": True,
        "runs_per_fixture": runs,
        "fixtures": [n for n, _ in SUITE],
        "note": "Replay-harness numbers with fake models: they bound "
                "pipeline code overhead, not model latency.",
        "needs_live_baseline": [
            p["id"] for p in table if p["harness"] != "measured"]
        + ["live model time for P3 P5 P7 (STT, brain, UI-TARS), "
           "P6 (TTS), P10 (real unreachable endpoints)"],
        "paths": summarize(series),
    }


if __name__ == "__main__":
    print(json.dumps(baseline(), indent=2))
