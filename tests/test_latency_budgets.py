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


def voiced(stage: str = "", ms: int = 0) -> dict:
    """A fixture turn with the voice on (fake TTS), optionally slowed."""
    fx = copy.deepcopy(runner.load_fixture("answer_points_timed"))
    if stage == "stt":
        fx["endpoints"]["whisper"]["latency_ms"] = ms
    return fx


class FirstVoiceComposite(unittest.TestCase):
    """U11: key release to first voice, from the existing spans."""

    def test_replayed_turn_records_the_composite_and_stages_sum_to_it(self):
        res = runner.run_turn(voiced())
        ms = {e["step"]: e["ms"] for e in res.trace
              if e.get("kind") == "span" and e.get("ms") is not None}
        self.assertIn(trace.FIRST_VOICE, ms)
        fv = trace.first_voice(ms)
        self.assertEqual(fv["total"], ms[trace.FIRST_VOICE])
        self.assertAlmostEqual(sum(s["ms"] for s in fv["stages"]),
                               fv["total"], delta=2)
        names = [s["name"] for s in fv["stages"]]
        self.assertEqual(names[-1], trace.FIRST_VOICE_REST)
        self.assertIn("stt", names)

    def test_stages_sum_to_the_composite_for_known_spans(self):
        fv = trace.first_voice({"first_voice": 2000, "stt": 400,
                                "context": 260, "route": 80,
                                "first_token": 540})
        self.assertEqual(fv["total"], 2000)
        self.assertEqual(sum(s["ms"] for s in fv["stages"]), 2000)
        self.assertEqual(fv["stages"][-1], {"name": "speech", "ms": 720})

    def test_a_turn_that_never_speaks_has_no_composite_and_passes(self):
        self.assertIsNone(trace.first_voice({"stt": 400, "route": 80}))
        series = {"P3": [400], "P4": [80]}      # no FV sample at all
        self.assertEqual(hl.check(series, budget_scale=1.0), [])
        for name in ("brain_down", "ask"):      # offline; voice off
            res = runner.run_turn(runner.load_fixture(name))
            self.assertNotIn("FV", hl.samples(res, offline=name == "brain_down"))

    def test_exceeding_the_budget_names_the_path_and_the_slow_stage(self):
        bad = hl.check(measure_one(voiced("stt", 3000)), budget_scale=1.0)
        self.assertTrue(any(b.startswith("FV ") for b in bad), bad)
        self.assertTrue(any(b.startswith("P3 ") for b in bad), bad)

    def test_record_once_keeps_the_first_instant(self):
        sp = trace.Spans(clock=iter(range(0, 10**12, 5_000_000)).__next__)
        start = sp.now()
        self.assertTrue(sp.record_once("first_voice", start))
        first = sp.ms["first_voice"]
        self.assertFalse(sp.record_once("first_voice", start))
        self.assertEqual(sp.ms["first_voice"], first)

    def test_trace_baseline_is_aggregate_only_and_ignores_typed_turns(self):
        rows = []
        for i, (stt, ctx, fv) in enumerate(
                [(500, 300, None), (600, 400, None), (0, 100, None),
                 (700, 500, 2400)]):
            spans = {"stt": stt, "context": ctx, "route": 5,
                     "first_token": 400, "tts_start": 10}
            if fv:
                spans["first_voice"] = fv
            for k, v in spans.items():
                rows.append({"kind": "span", "turn": f"t{i}", "step": k,
                             "ms": v, "ts": "x"})
        with tempfile.TemporaryDirectory() as td:
            f = pathlib.Path(td) / "trace.jsonl"
            f.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            rep = telemetry.trace_baseline(f)
        self.assertEqual(rep["turns"], 3)          # the stt=0 turn is typed
        c = rep["composite"]
        self.assertEqual((c["n"], c["derived"]), (3, 2))
        self.assertEqual(c["p50"], 1415)           # 600+400+5+400+10
        self.assertEqual(c["p90"], 2400)
        self.assertNotIn("t0", json.dumps(rep))

    def test_the_budget_row_is_seeded_from_traces(self):
        table = telemetry.load_budgets()
        fv = next(p for p in table["paths"] if p["id"] == "FV")
        self.assertEqual(fv["span"], "first_voice")
        self.assertIn("p90_factor_source", table)
        self.assertGreater(table["p90_factor"], 1.0)


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
                "P10": 1000, "E2E": 1400, "FV": 2500}
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
