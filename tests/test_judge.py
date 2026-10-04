"""Jev judge — success + efficiency verdicts from step traces."""
import unittest
from unittest import mock

from wisp import judge


class JudgeTest(unittest.TestCase):
    def setUp(self):
        self.cfg = {"agent": {"model": "typesafe/jev-1.13"}}

    def _resp(self, succ="yes", score=3, waste="none"):
        return {"answers": {
            "success": {"choice": succ},
            "efficiency": {"score": score},
            "waste": {"choice": waste}}}

    def test_pass_optimal(self):
        with mock.patch("wisp.pipeline.ask_jev",
                        return_value=self._resp()) as aj:
            v = judge.verdict(
                "click ALPHA",
                [{"tool": "click", "arg": "127,607",
                  "result": "CLICKED btn-alpha"}],
                "ACTED (1 steps): done", self.cfg, verified=True)
        self.assertTrue(v["success"])
        self.assertEqual(v["efficiency"], 1.0)
        self.assertEqual(v["waste"], "none")
        # judge receives the ground truth, not just agent claims
        state = aj.call_args[0][0]
        self.assertIn("PASS", state)
        self.assertIn("btn-alpha", state)

    def test_failed_run_scored_wasteful(self):
        with mock.patch("wisp.pipeline.ask_jev",
                        return_value=self._resp("no", 0, "re_aim")):
            v = judge.verdict("click ALPHA", [],
                              "ABORTED", self.cfg, verified=False)
        self.assertFalse(v["success"])
        self.assertEqual(v["efficiency"], 0.0)
        self.assertEqual(v["waste"], "re_aim")

    def test_partial(self):
        with mock.patch("wisp.pipeline.ask_jev",
                        return_value=self._resp("partial", 1)):
            v = judge.verdict("t", [], "x", self.cfg)
        self.assertIsNone(v["success"])
        self.assertAlmostEqual(v["efficiency"], 0.34)

    def test_jev_failure_returns_unknowns(self):
        with mock.patch("wisp.pipeline.ask_jev",
                        side_effect=RuntimeError("offline")):
            v = judge.verdict("t", [], "x", self.cfg)
        self.assertIsNone(v["success"])
        self.assertIsNone(v["efficiency"])
        self.assertEqual(v["waste"], "judge_error")

    def test_out_of_range_waste_normalized(self):
        with mock.patch("wisp.pipeline.ask_jev",
                        return_value=self._resp(waste="invented")):
            v = judge.verdict("t", [], "x", self.cfg)
        self.assertEqual(v["waste"], "none")

    def test_describe(self):
        s = judge.describe({"success": True, "efficiency": 0.9,
                            "waste": "none"})
        self.assertIn("ok", s)
        self.assertIn("0.90", s)


if __name__ == "__main__":
    unittest.main()


class FirstFault(unittest.TestCase):
    def setUp(self):
        self.cfg = {"agent": {}}
        self.steps = [{"tool": "click", "arg": "1,2",
                       "result": "CLICKED DIV"}] * 3

    def _resp(self, ff):
        return {"answers": {
            "success": {"choice": "no"},
            "efficiency": {"score": 1},
            "waste": {"choice": "re_aim"},
            "first_fault": {"score": ff}}}

    def test_fault_step_maps_to_zero_indexed(self):
        with mock.patch("wisp.pipeline.ask_jev",
                        return_value=self._resp(2)):
            v = judge.verdict("t", self.steps, "x", self.cfg,
                              verified=False)
        self.assertEqual(v["first_fault"], 1)  # step 2 → index 1

    def test_none_maps_to_minus_one(self):
        with mock.patch("wisp.pipeline.ask_jev",
                        return_value=self._resp(0)):
            v = judge.verdict("t", self.steps, "x", self.cfg)
        self.assertEqual(v["first_fault"], -1)

    def test_out_of_range_clamped(self):
        with mock.patch("wisp.pipeline.ask_jev",
                        return_value=self._resp(20)):
            v = judge.verdict("t", self.steps, "x", self.cfg)
        self.assertEqual(v["first_fault"], 2)  # clamped to len-1

    def test_missing_answer_defaults_minus_one(self):
        r = {"answers": {"success": {"choice": "yes"},
                         "efficiency": {"score": 3},
                         "waste": {"choice": "none"}}}
        with mock.patch("wisp.pipeline.ask_jev", return_value=r):
            v = judge.verdict("t", self.steps, "x", self.cfg)
        self.assertEqual(v["first_fault"], -1)

    def test_judge_error_carries_minus_one(self):
        with mock.patch("wisp.pipeline.ask_jev",
                        side_effect=RuntimeError("x")):
            v = judge.verdict("t", self.steps, "x", self.cfg)
        self.assertEqual(v["first_fault"], -1)

    def test_describe_shows_fault(self):
        s = judge.describe({"success": False, "efficiency": 0.5,
                            "waste": "re_aim", "first_fault": 2})
        self.assertIn("fault@3", s)
