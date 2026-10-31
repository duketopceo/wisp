#!/usr/bin/env python3
"""Scenario corpus (W6): every turn fixture under tests/fixtures/turns
runs through the replay harness and meets its own `expect` block.

The corpus is also indexed in docs/SCENARIOS.md; a fixture missing from
the index (or an index row without a fixture) fails here. Fakes only: no
network, no live hyprctl or cua-driver.
"""
import json
import pathlib
import sys
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from harness import runner  # noqa: E402

DIR = ROOT / "tests" / "fixtures" / "turns"
INDEX = ROOT / "docs" / "SCENARIOS.md"
FIXTURES = sorted(p for p in DIR.glob("*.json"))

# the plan's scenario list (W6) and the fixture tag that covers each.
# Budget-blocked (W14) landed on master with the ledger, so it is required.
REQUIRED = {"answer", "act click via cua", "cancel mid-act", "retired endpoint down",
            "budget blocked", "cua down", "deny-listed app", "rate limit hit", "kill switch",
            "dry-run", "guide mode", "choose/confirm", "notify paths",
            "STT failure", "offline daemon"}
PENDING = set()


def _load(p):
    return json.loads(p.read_text())


class CorpusShapeTest(unittest.TestCase):
    def test_every_fixture_is_described_tagged_and_has_expectations(self):
        for p in FIXTURES:
            fx = _load(p)
            self.assertEqual(fx.get("name"), p.stem, p)
            self.assertTrue(fx.get("description"), p)
            self.assertTrue(fx.get("scenario"), f"{p.name}: no scenario tag")
            self.assertTrue(fx.get("expect"), f"{p.name}: empty expect")

    def test_required_scenarios_are_covered(self):
        tags = {_load(p)["scenario"] for p in FIXTURES}
        self.assertEqual(REQUIRED - tags, set())

    def test_pending_scenarios_not_faked(self):
        tags = {_load(p)["scenario"] for p in FIXTURES}
        self.assertEqual(PENDING & tags, set())

    def test_index_lists_every_fixture_and_nothing_else(self):
        text = INDEX.read_text()
        listed = set()
        for ln in text.splitlines():
            if ln.startswith("| `"):
                listed.add(ln.split("`")[1])
        self.assertEqual(listed, {p.stem for p in FIXTURES})
        for scen in PENDING:
            self.assertIn(scen, text)


class ExpectationKeysTest(unittest.TestCase):
    def _res(self, **kw):
        r = runner.TurnResult(expect=kw.pop("expect"))
        for k, v in kw.items():
            setattr(r, k, v)
        return r

    def test_steps_contain_checks_each_step(self):
        r = self._res(expect={"steps_contain": ["REFUSED"]},
                      final={"steps": ["click 1,2 → REFUSED (x)"]})
        self.assertEqual(runner.check_expectations(r), [])
        r = self._res(expect={"steps_contain": ["REFUSED"]},
                      final={"steps": ["click 1,2 → CLICKED(1,2)"]})
        self.assertTrue(runner.check_expectations(r))
        r = self._res(expect={"steps_contain": ["REFUSED"]},
                      final={"steps": []})
        self.assertTrue(runner.check_expectations(r))

    def test_jev_calls(self):
        r = self._res(expect={"jev_calls": 0},
                      calls={"jev": [{"path": "/x"}]})
        self.assertTrue(runner.check_expectations(r))

    def test_stray_jev_hop_fails_a_fixture_that_did_not_declare_it(self):
        calls = {"jev": [{"path": "/x"}]}
        r = self._res(expect={}, calls=calls)
        bad = runner.check_expectations(r)
        self.assertEqual(len(bad), 1)
        self.assertIn("stray hop", bad[0])
        # declaring the count is the explicit opt-in, and no hop is clean
        self.assertEqual(runner.check_expectations(
            self._res(expect={"jev_calls": 1}, calls=calls)), [])
        self.assertEqual(runner.check_expectations(
            self._res(expect={}, calls={"jev": []})), [])

    def test_stop_within_ms(self):
        ev = [{"status": "acting", "t_ms": 10},
              {"status": "idle", "t_ms": 640}]
        r = self._res(expect={"stop_within_ms": 150}, events=ev,
                      interrupt_fired=True, interrupt_t_ms=600)
        self.assertEqual(runner.check_expectations(r), [])
        r.interrupt_t_ms = 100  # 540ms late — over-bound even w/ CI jitter
        self.assertTrue(runner.check_expectations(r))

    def test_points_growth_and_gap(self):
        def ev(status, n, t):
            return {"status": status, "points": [{}] * n, "t_ms": t}
        ex = {"points_growth": [1, 2], "points_gap_ms_min": 200}
        r = self._res(expect=ex, events=[
            ev("speaking", 0, 10), ev("speaking", 1, 20),
            ev("speaking", 2, 400), ev("done", 2, 500)])
        self.assertEqual(runner.check_expectations(r), [])
        r.events = [ev("speaking", 0, 10), ev("speaking", 2, 20)]
        self.assertEqual(len(runner.check_expectations(r)), 2)
        r.events = [ev("speaking", 1, 20), ev("speaking", 2, 100)]
        self.assertEqual(len(runner.check_expectations(r)), 1)


    def test_drawings_growth_gap_and_tag_free(self):
        def ev(status, n, t, ans="x"):
            return {"status": status, "drawings": [{}] * n, "points": [],
                    "answer": ans, "t_ms": t}
        ex = {"drawings_growth": [1, 2], "drawings_gap_ms_min": 200,
              "tag_free": True}
        r = self._res(expect=ex, events=[
            ev("speaking", 0, 10), ev("speaking", 1, 20),
            ev("speaking", 2, 400), ev("done", 0, 500)])
        self.assertEqual(runner.check_expectations(r), [])
        r.events = [ev("speaking", 1, 20, "a [RING:1,2,3]"),
                    ev("speaking", 2, 100), ev("done", 2, 200)]
        self.assertEqual(len(runner.check_expectations(r)), 3)


TURN_CAP_MS = 4000


class CorpusRunTest(unittest.TestCase):
    def test_every_fixture_meets_its_expectations_within_turn_cap(self):
        t0 = time.monotonic()
        bad = {}
        slow = {}
        for p in FIXTURES:
            res = runner.run_turn(_load(p) | {"_dir": str(DIR)})
            problems = runner.check_expectations(res)
            if res.violations:
                problems.append(f"network violations {res.violations}")
            if problems:
                bad[p.stem] = problems
            turn_ms = runner._spans(res).get("turn_ms")
            self.assertIsNotNone(turn_ms, f"{p.stem}: no state events")
            if turn_ms > TURN_CAP_MS * runner.JITTER:
                slow[p.stem] = turn_ms
        self.assertEqual(bad, {})
        self.assertEqual(
            slow, {}, f"fixture turn exceeded {TURN_CAP_MS * runner.JITTER:.0f}"
            " ms (per-turn latency, excludes child spawn)")
        # Latency is bounded per turn (the harness's own turn_ms, which
        # excludes child-process spawn), so it measures the product rather
        # than how loaded the test machine is. Idle max is ~1.9 s (act
        # turns: start/stop_recording + session mint); cap is ~2x that.
        # The whole-corpus bound below is only a hang guard.
        self.assertLess(time.monotonic() - t0, 60.0 * runner.JITTER)


if __name__ == "__main__":
    unittest.main()
