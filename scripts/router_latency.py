#!/usr/bin/env python3
"""Decision latency of the turn router over fixture utterances. No network.

    python scripts/router_latency.py [--model-ms 600] [--runs 200]

Prints, for tests/fixtures/router_turns.json:
- before: every turn takes the rule path and ambiguous turns fall to act
  (what shipped before wisp/turn_router.py): decision latency is the rule
  cost only.
- after, rule lane: the same rules plus the ambiguity check, for the turns
  the rules settle (the common case, no model).
- after, model lane: the ambiguity check plus ONE model call, for the turns
  the rules leave open. The call is a stub that sleeps --model-ms (an
  ASSUMED round trip for a small hosted model; nothing is sent), so this
  row shows the cost structure, not a measured model latency.
- the blended mean: rule_ms + open_fraction * (model_ms).
"""
import argparse
import json
import pathlib
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

APPS = {"firefox": {}, "Spotify": {}}
FIXTURE = ROOT / "tests" / "fixtures" / "router_turns.json"


def _p(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def is_open(text):
    """True when the rules leave the turn to the ambiguity model."""
    from wisp import stage_route, turn_router
    return (stage_route.fixed_route(text, "act", True) == ("act", None)
            and not stage_route.fast_route(text, APPS, {})
            and bool(turn_router.ambiguity(text, APPS)))


def measure(turns, runs, model_ms, cfg):
    from wisp import stage_route, turn_router

    def stub(msgs, c, timeout=0):
        time.sleep(model_ms / 1000)
        return {"content": "act"}

    before, rule_lane, model_lane = [], [], []
    for t in turns:
        text = t["text"]
        for _ in range(runs):
            t0 = time.perf_counter()
            stage_route.fixed_route(text, "act", True)
            stage_route.fast_route(text, APPS, cfg)
            before.append((time.perf_counter() - t0) * 1000)
        open_ = is_open(text)
        # the model lane is sampled a few times only (it sleeps)
        for _ in range(runs if not open_ else min(runs, 3)):
            t0 = time.perf_counter()
            stage_route.fixed_route(text, "act", True)
            fast = stage_route.fast_route(text, APPS, cfg)
            if not fast and open_:
                turn_router.resolve(text, cfg, APPS, active=False, chat=stub)
            ms = (time.perf_counter() - t0) * 1000
            (model_lane if open_ else rule_lane).append(ms)
    return before, rule_lane, model_lane


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=200)
    ap.add_argument("--model-ms", type=float, default=600.0)
    a = ap.parse_args()
    turns = json.loads(FIXTURE.read_text())
    cfg = {"router": {"ambiguity_model":
                      "openrouter:nvidia/nemotron-3.5-lightning"}}
    from wisp import turn_router
    open_n = sum(1 for t in turns if is_open(t["text"]))
    b, r, m = measure(turns, a.runs, a.model_ms, cfg)
    frac = open_n / len(turns)

    def row(name, xs):
        if xs:
            print(f"{name:<28} n={len(xs):<5} p50 {statistics.median(xs):8.3f} "
                  f"ms   p95 {_p(xs, .95):8.3f} ms")
    print(f"{open_n}/{len(turns)} fixture turns left open by the rules "
          f"({frac:.0%})")
    row("before (rules only)", b)
    row("after: rule lane", r)
    row("after: model lane (stub)", m)
    if m and r:
        blended = statistics.mean(r) * (1 - frac) + statistics.mean(m) * frac
        print(f"after: blended mean          {blended:8.1f} ms "
              f"(model round trip ASSUMED {a.model_ms:.0f} ms)")


if __name__ == "__main__":
    main()
