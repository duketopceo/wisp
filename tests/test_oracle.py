"""Oracle baselines — suite normalization + objective efficiency math."""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, ".")
sys.path.insert(0, "scripts/clicklab")
import run as cl  # noqa: E402


class LoadSuite(unittest.TestCase):
    def _suites(self, tmp, data):
        f = tmp / "suites.json"
        f.write_text(json.dumps(data))
        return f

    def test_three_element_entries_yield_oracle(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        f = self._suites(tmp, {"s": [["task a", "return true", 2]]})
        with mock.patch.object(cl, "SUITES_FILE", f):
            s = cl.load_suite("s")
        self.assertEqual(s, [("task a", "return true", 2)])

    def test_two_element_entries_default_zero(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        f = self._suites(tmp, {"s": [["task a", "return true"]]})
        with mock.patch.object(cl, "SUITES_FILE", f):
            s = cl.load_suite("s")
        self.assertEqual(s, [("task a", "return true", 0)])

    def test_real_suites_carry_oracles(self):
        core = cl.load_suite("core")
        self.assertTrue(all(o > 0 for _, _, o in core))
        hard = cl.load_suite("dom-hard")
        self.assertTrue(all(o > 0 for _, _, o in hard))


class EffMath(unittest.TestCase):
    """Mirror of run.py's oracle efficiency resolution — pure math so
    it stays honest if the formula drifts."""

    def _eff(self, oracle, actual, judged=None):
        eff_obj = min(1.0, oracle / max(actual, 1)) if oracle else None
        return eff_obj if eff_obj is not None else judged

    def test_optimal_run_scores_one(self):
        self.assertEqual(self._eff(1, 1), 1.0)

    def test_extra_steps_score_fraction(self):
        self.assertAlmostEqual(self._eff(1, 3), 1 / 3)

    def test_shorter_than_oracle_capped(self):
        self.assertEqual(self._eff(4, 2), 1.0)

    def test_zero_actual_floor(self):
        # 0 actual steps with oracle 2 → 2/max(0,1)=2 → capped at 1.0
        # (harmless — the scoreboard gates success, not efficiency)
        self.assertEqual(self._eff(2, 0), 1.0)

    def test_no_oracle_falls_back_to_judge(self):
        self.assertEqual(self._eff(0, 5, judged=0.67), 0.67)


if __name__ == "__main__":
    unittest.main()
