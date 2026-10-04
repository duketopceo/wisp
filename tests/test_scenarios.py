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
# Budget-blocked (W14, PR #88) is pending until the ledger is on master.
REQUIRED = {"answer", "act click via cua", "cancel mid-act", "Jev down",
            "cua down", "deny-listed app", "rate limit hit", "kill switch",
            "dry-run", "guide mode", "choose/confirm", "notify paths",
            "STT failure", "offline daemon"}
PENDING = {"budget blocked"}


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

    def test_stop_within_ms(self):
        ev = [{"status": "acting", "t_ms": 10},
              {"status": "idle", "t_ms": 640}]
        r = self._res(expect={"stop_within_ms": 150}, events=ev,
                      interrupt_fired=True, interrupt_t_ms=600)
        self.assertEqual(runner.check_expectations(r), [])
        r.interrupt_t_ms = 400
        self.assertTrue(runner.check_expectations(r))


class CorpusRunTest(unittest.TestCase):
    def test_every_fixture_meets_its_expectations_under_20s(self):
        t0 = time.monotonic()
        bad = {}
        for p in FIXTURES:
            res = runner.run_turn(_load(p) | {"_dir": str(DIR)})
            problems = runner.check_expectations(res)
            if res.violations:
                problems.append(f"network violations {res.violations}")
            if problems:
                bad[p.stem] = problems
        self.assertEqual(bad, {})
        self.assertLess(time.monotonic() - t0, 20.0)


if __name__ == "__main__":
    unittest.main()
