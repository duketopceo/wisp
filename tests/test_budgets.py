#!/usr/bin/env python3
"""Latency budget table, harness measurement and baseline (W2).

The budget table is data (wisp/budgets.json). The replay harness (fakes,
no models, no network) measures every path it can reach; a regression
past a budget ceiling fails here. Live-model numbers are NOT measured
here: see the "live baseline" note in docs/baselines/latency-harness.json.
"""
import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from wisp import telemetry  # noqa: E402
from harness import latency as hl  # noqa: E402

BASELINE = ROOT / "docs" / "baselines" / "latency-harness.json"
PLAN_BUDGETS = {"P1": 25, "P2": 25, "P3": 600, "P4": 200, "P5": 500,
                "P6": 150, "P7": 1200, "P8": 300, "P9": 150,
                "P10": 1000, "E2E": 1400}


class BudgetTableTest(unittest.TestCase):
    def test_table_matches_the_plan_numbers(self):
        got = {p["id"]: p["budget_p50_ms"]
               for p in telemetry.load_budgets()["paths"]}
        self.assertEqual(got, PLAN_BUDGETS)

    def test_every_row_declares_its_harness_coverage(self):
        for p in telemetry.load_budgets()["paths"]:
            self.assertIn(p["harness"], ("measured", "live-only",
                                         "pending"), p["id"])

    def test_resource_budgets_present(self):
        res = telemetry.load_budgets()["resources"]
        self.assertEqual(res["wispd_rss_mb"], 250)
        self.assertEqual(res["cua_driver_memory_max"], "512M")

    def test_report_rows_come_from_the_table(self):
        self.assertEqual([r[0] for r in telemetry.BUDGETS],
                         list(PLAN_BUDGETS))


class ReportTest(unittest.TestCase):
    def _trace(self, spans_by_turn):
        f = pathlib.Path(tempfile.mkdtemp()) / "trace.jsonl"
        now = datetime.now(timezone.utc).isoformat()
        with open(f, "w") as fh:
            for turn, spans in spans_by_turn.items():
                for step, ms in spans.items():
                    fh.write(json.dumps({"ts": now, "turn": turn,
                                         "step": step, "kind": "span",
                                         "ms": ms, "data": {}}) + "\n")
            fh.write("{corrupt\n")
        return f

    def test_stop_and_offline_rows_from_real_spans(self):
        f = self._trace({"a": {"stop": 40, "offline_error": 300},
                         "b": {"stop": 400}})
        rows = {r["id"]: r for r in
                telemetry.latency_report(trace_file=f)["rows"]}
        self.assertEqual(rows["P9"]["n"], 2)
        self.assertEqual(rows["P9"]["verdict"], "MISS")
        self.assertEqual(rows["P10"]["verdict"], "ok")
        self.assertEqual(rows["P8"]["verdict"], "no data")

    def test_empty_trace(self):
        f = self._trace({})
        self.assertEqual(telemetry.latency_report(trace_file=f)["turns"], 0)

    def test_budget_text_lists_every_path(self):
        txt = telemetry.budgets_text()
        for pid in PLAN_BUDGETS:
            self.assertIn(pid, txt)
        self.assertIn("live-only", txt)


class SamplesTest(unittest.TestCase):
    class R:
        interrupt_fired = False
        interrupt_t_ms = 0
        events = []
        trace = []

    def _res(self, spans, events=(), interrupt=None):
        r = self.R()
        r.trace = [{"kind": "span", "step": k, "ms": v}
                   for k, v in spans.items()]
        r.events = list(events)
        if interrupt is not None:
            r.interrupt_fired, r.interrupt_t_ms = True, interrupt
        return r

    def test_composed_paths(self):
        s = hl.samples(self._res({"stt": 10, "context": 30, "route": 5,
                                  "first_token": 20}))
        self.assertEqual(s["P4"], 35)
        self.assertEqual(s["E2E"], 65)

    def test_stop_is_interrupt_to_terminal_event(self):
        ev = [{"status": "acting", "t_ms": 50},
              {"status": "idle", "t_ms": 640}]
        s = hl.samples(self._res({}, ev, interrupt=600))
        self.assertEqual(s["P9"], 40)

    def test_offline_is_error_event_time(self):
        s = hl.samples(self._res({}, [{"status": "error", "t_ms": 55}]),
                       offline=True)
        self.assertEqual(s["P10"], 55)

    def test_ceiling_check_flags_regression(self):
        bad = hl.check({"P3": [900, 900, 900]})
        self.assertTrue(any("P3" in b for b in bad))
        self.assertEqual(hl.check({"P3": [10, 10, 10]}), [])


class BaselineFileTest(unittest.TestCase):
    def setUp(self):
        self.b = json.loads(BASELINE.read_text())

    def test_covers_every_harness_measured_path_within_ceiling(self):
        measured = {p["id"] for p in telemetry.load_budgets()["paths"]
                    if p["harness"] == "measured"}
        self.assertEqual(set(self.b["paths"]), measured)
        for pid, row in self.b["paths"].items():
            self.assertLessEqual(row["p50"], row["budget_p50_ms"], pid)
            self.assertLessEqual(row["p90"], row["budget_p50_ms"] * 1.5, pid)

    def test_records_what_needs_a_live_baseline(self):
        live = set(self.b["needs_live_baseline"])
        self.assertTrue({"P1", "P2", "P8"} <= live)
        self.assertTrue(self.b["fakes_only"])


class HarnessCeilingTest(unittest.TestCase):
    """Run the fake-backed suite and fail on any budget regression."""

    def test_harness_measured_paths_stay_under_their_budgets(self):
        series = hl.measure(runs=2)
        self.assertTrue({"P3", "P4", "P5", "P7", "P9", "P10", "E2E"}
                        <= set(series), sorted(series))
        self.assertEqual(hl.check(series), [], series)


class CliTest(unittest.TestCase):
    def _run(self, argv):
        sys.path.insert(0, str(ROOT / "tests"))
        import cli_env
        with cli_env.CliEnv() as env:
            return env.run(argv)

    def test_latency_budgets_flag(self):
        code, out, _ = self._run(["latency", "--budgets"])
        self.assertEqual(code, 0)
        self.assertIn("P9", out)

    def test_latency_baseline_flag_json(self):
        code, out, _ = self._run(["latency", "--baseline", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)["data"]
        self.assertIn("P3", data["paths"])


if __name__ == "__main__":
    unittest.main()
