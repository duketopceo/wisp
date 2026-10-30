#!/usr/bin/env python3
"""B1: "fast" is a number in CI.

A stage slowed on purpose must trip the budget gate. Endpoint stages use
the replay harness; routing uses the actual local routing span. Both feed
the same harness samples/budget checks. The unmodified fixture must pass,
and `wispd eval` shows measured p50 and p90 next to each budget.
"""
import copy
import io
import json
import pathlib
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from wisp import stage_route, telemetry, trace  # noqa: E402
from harness import latency as hl, runner  # noqa: E402


def slowed(stage: str, ms: int = 1500) -> dict:
    """The `ask` fixture with one stage's fake endpoint made slow."""
    fx = copy.deepcopy(runner.load_fixture("ask"))
    ep = fx["endpoints"]
    if stage == "stt":
        ep["whisper"]["latency_ms"] = ms
    elif stage == "first_token":
        ep["brain"]["responses"][0]["latency_ms"] = ms
    else:
        raise ValueError(stage)
    return fx


def measure_one(fx: dict) -> dict:
    res = runner.run_turn(fx)
    series = {}
    for pid, ms in hl.samples(res).items():
        series.setdefault(pid, []).append(ms)
    return series


def measure_slow_local_route(ms: int = 1500) -> dict:
    """Delay the current local decision boundary inside its real span.

    Routing has no endpoint after Jev retirement. Keep the actual
    route_stage -> Spans -> replay samples -> budget-check chain instead
    of pretending a retired server still contributes latency.
    """
    spans = trace.Spans()
    events = []
    ctx = SimpleNamespace(
        cfg={"brain": {"router": "act"}}, text="what is a shell",
        detail="what is a shell", sp=spans, turn="slow-local-route",
        token=mock.Mock(), harness={"apps": {}})

    def emit(turn, step, kind, data=None, ms=None):
        events.append({"turn": turn, "step": step, "kind": kind, "ms": ms})

    def slow_fixed_route(*args):
        time.sleep(ms / 1000)
        return "act", None

    try:
        with mock.patch.object(trace, "emit", side_effect=emit), \
             mock.patch.object(stage_route, "fixed_route",
                               side_effect=slow_fixed_route):
            spans.bind(ctx.turn)
            spans.record("stt", spans.now())
            if not stage_route.route_stage(ctx):
                raise AssertionError("the delayed local route did not finish")
    finally:
        spans.close()
    result = runner.TurnResult(trace=events)
    return {pid: [value] for pid, value in hl.samples(result).items()}


class SlowedStageTrips(unittest.TestCase):
    """Each slowed stage must fail its own path at the exact budget."""

    def assertTrips(self, stage: str, pid: str):
        bad = hl.check(measure_one(slowed(stage)), budget_scale=1.0)
        self.assertTrue(any(b.startswith(pid + " ") for b in bad),
                        (stage, bad))

    def test_slow_speech_to_text_fails_p3(self):
        self.assertTrips("stt", "P3")

    def test_slow_first_token_fails_p5(self):
        self.assertTrips("first_token", "P5")

    def test_slow_route_fails_the_route_or_e2e_budget(self):
        series = measure_slow_local_route()
        self.assertGreaterEqual(series["P4"][0], 1500)
        bad = hl.check(series, budget_scale=1.0)
        self.assertTrue(any(b.startswith("P4 ") for b in bad), bad)

    def test_the_unmodified_fixture_passes(self):
        series = measure_one(runner.load_fixture("ask"))
        self.assertEqual(hl.check(series, budget_scale=hl.ci_scale()), [],
                         series)


class GateMargin(unittest.TestCase):
    def test_ci_gets_the_stated_margin_and_a_desktop_none(self):
        self.assertEqual(hl.ci_scale({}), 1.0)
        self.assertEqual(hl.ci_scale({"CI": "true"}), hl.CI_SCALE)
        self.assertEqual(hl.ci_scale({"GITHUB_ACTIONS": "true"}),
                         hl.CI_SCALE)
        self.assertEqual(hl.CI_SCALE, 2.0)

    def test_the_margin_is_what_separates_a_pass_from_a_fail(self):
        series = {"P3": [700, 700, 700]}      # budget 600 ms
        self.assertTrue(hl.check(series, budget_scale=1.0))
        self.assertEqual(hl.check(series, budget_scale=hl.CI_SCALE), [])

    def test_no_budget_is_looser_than_the_plan(self):
        plan = {"P1": 25, "P2": 25, "P3": 600, "P4": 200, "P5": 500,
                "P6": 150, "P6G": 1500, "P7": 1200, "P8": 300, "P9": 150,
                "P10": 1000, "E2E": 1400}
        got = {p["id"]: p["budget_p50_ms"]
               for p in telemetry.load_budgets()["paths"]}
        for pid, ms in got.items():
            self.assertLessEqual(ms, plan[pid], pid)


class EvalShowsLatency(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.trace = pathlib.Path(td.name) / "trace.jsonl"
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for i, ms in enumerate((100, 300, 500)):
            rows.append({"kind": "span", "turn": f"t{i}", "step": "stt",
                         "ms": ms, "ts": now})
        self.trace.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    def run_eval(self, *argv):
        buf = io.StringIO()
        from wisp import cli
        with mock.patch.object(telemetry.trace, "TRACE_FILE", self.trace), \
                mock.patch("wisp.config.load_config", return_value={}), \
                redirect_stdout(buf):
            code = cli.main(["eval", *argv], host=None)
        return code, buf.getvalue()

    def test_text_has_p50_p90_and_budget_for_the_measured_span(self):
        code, out = self.run_eval()
        self.assertEqual(code, 0)
        line = next(l for l in out.splitlines() if "P3" in l)
        self.assertIn("300", line)      # p50
        self.assertIn("500", line)      # p90
        self.assertIn("600", line)      # budget
        self.assertIn("ok", line)

    def test_json_carries_latency_rows(self):
        code, out = self.run_eval("--json")
        data = json.loads(out)
        data = data.get("data", data)
        p3 = next(r for r in data["latency"] if r["id"] == "P3")
        self.assertEqual((p3["p50"], p3["p90"], p3["budget_p50"]),
                         (300, 500, 600))


if __name__ == "__main__":
    unittest.main()
