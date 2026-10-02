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
