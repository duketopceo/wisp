"""U7 adaptive clicklab — verdict fallback chain, failure buckets,
promotion gate, and the bucket-driven adaptive task loop."""
import json
import pathlib
import random
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
CL = ROOT / "scripts" / "clicklab"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(CL))

import adaptive  # noqa: E402
from wisp import judge, train  # noqa: E402


def _jev_resp(succ="no", score=0, waste="re_aim", fc="model", ff=None):
    a = {"success": {"choice": succ},
         "efficiency": {"score": score},
         "waste": {"choice": waste},
         "failure_class": {"choice": fc}}
    if ff is not None:
        a["first_fault"] = {"score": ff}
    return {"answers": a}


def _rec(task="scroll the list to the bottom", ok=False, cls="model",
         verified=None, judged=True, surface="browser-dom",
         steps=None):
    verified = ok if verified is None else verified
    return {"task": task, "surface": surface, "suite": "core",
            "verified": verified,
            "judge": {"success": None if not judged else ok,
                      "failure_class": cls,
                      "efficiency": 1.0 if ok else 0.0,
                      "first_fault": -1, "waste": "none",
                      "by": "jev" if judged else "none",
                      "judged": judged},
            "steps": steps if steps is not None else
            [{"tool": "scroll", "arg": "down", "result": "OK"}],
            "ts": 1.0}


class VerdictChainTest(unittest.TestCase):
    """clicklab.judge: jev → brain fallback → unjudged. 'off' → oracle."""
    CFG = {"agent": {"model": "typesafe/jev-1.13"},
           "clicklab": {"judge": "jev"}}

    def test_jev_verdict_parsed_with_failure_class(self):
        with mock.patch("wisp.pipeline.ask_jev",
                        return_value=_jev_resp("no", 0, "re_aim",
                                               "tool")) as aj:
            v = judge.verdict("click ALPHA", [], "FAIL", self.CFG,
                              verified=False)
        self.assertFalse(v["success"])
        self.assertEqual(v["failure_class"], "tool")
        self.assertEqual(v["by"], "jev")
        self.assertTrue(v["judged"])
        aj.assert_called_once()

    def test_jev_down_falls_back_to_brain(self):
        with mock.patch("wisp.pipeline.ask_jev",
                        side_effect=RuntimeError("jev_down")), \
             mock.patch("wisp.brain.chat", return_value={
                 "content": '{"success": false, "failure_class": '
                            '"environment", "efficiency": 0.2,'
                            ' "waste": "none", "first_fault": -1}'}) \
                as bc:
            v = judge.verdict("click ALPHA", [], "FAIL", self.CFG,
                              verified=False)
        self.assertFalse(v["success"])
        self.assertEqual(v["failure_class"], "environment")
        self.assertEqual(v["by"], "brain")
        self.assertTrue(v["judged"])
        self.assertEqual(v["fallback_from"], "jev")
        bc.assert_called_once()

    def test_both_down_is_unjudged(self):
        with mock.patch("wisp.pipeline.ask_jev",
                        side_effect=RuntimeError("jev_down")), \
             mock.patch("wisp.brain.chat",
                        side_effect=RuntimeError("brain_down")):
            v = judge.verdict("t", [], "x", self.CFG)
        self.assertIsNone(v["success"])
        self.assertFalse(v["judged"])
        self.assertEqual(v["by"], "none")
        self.assertEqual(v["waste"], "judge_error")
        self.assertIn("brain", v["note"])

    def test_judge_off_is_oracle_only(self):
        cfg = {"clicklab": {"judge": "off"}, "agent": {}}
        with mock.patch("wisp.pipeline.ask_jev") as aj, \
             mock.patch("wisp.brain.chat") as bc:
            v = judge.verdict("t", [], "x", cfg, verified=True)
        self.assertTrue(v["success"])
        self.assertEqual(v["by"], "oracle")
        self.assertTrue(v["judged"])
        aj.assert_not_called()
        bc.assert_not_called()

    def test_judge_brain_skips_jev(self):
        cfg = {"clicklab": {"judge": "brain"}, "agent": {}}
        with mock.patch("wisp.pipeline.ask_jev") as aj, \
             mock.patch("wisp.brain.chat", return_value={
                 "content": '{"success": true}'}) as bc:
            v = judge.verdict("t", [], "x", cfg, verified=True)
        self.assertTrue(v["success"])
        self.assertEqual(v["by"], "brain")
        aj.assert_not_called()
        bc.assert_called_once()

    def test_brain_garbage_is_unjudged(self):
        with mock.patch("wisp.pipeline.ask_jev",
                        side_effect=RuntimeError("jev_down")), \
             mock.patch("wisp.brain.chat",
                        return_value={"content": "sure, looks fine"}):
            v = judge.verdict("t", [], "x", self.CFG)
        self.assertFalse(v["judged"])
        self.assertEqual(v["by"], "none")

    def test_brain_messy_json_rescued_by_regex(self):
        with mock.patch("wisp.brain.chat", return_value={
                "content": 'hmm {"success": "false"} trailing...'}), \
             mock.patch("wisp.pipeline.ask_jev",
                        side_effect=RuntimeError("down")):
            v = judge.verdict("t", [], "x", self.CFG)
        self.assertFalse(v["success"])
        self.assertEqual(v["by"], "brain")

    def test_evidence_state_reaches_the_judge(self):
        with mock.patch("wisp.pipeline.ask_jev",
                        return_value=_jev_resp()) as aj:
            judge.verdict("t", [], "x", self.CFG, verified=False,
                          evidence={"state": '{"scroll_top": 0}'})
        self.assertIn("scroll_top", aj.call_args[0][0])


class BucketTest(unittest.TestCase):
    def test_model_failures_bucket_by_skill_and_surface(self):
        recs = [_rec("scroll the list to the bottom"),
                _rec("scroll the list to the bottom"),
                _rec("scroll the list down partway"),
                _rec("click the button labeled ALPHA", ok=True)]
        b = train.compute_buckets(recs)
        self.assertEqual(b["fails"], 3)
        self.assertEqual(b["by_class"]["model"], 3)
        self.assertEqual(b["by_skill"]["scroll"], 3)
        self.assertEqual(b["by_surface"]["browser-dom"], 3)
        self.assertEqual(b["cells"]["model|scroll|browser-dom"], 3)
        self.assertEqual(b["top"], "model|scroll|browser-dom")

    def test_unjudged_runs_are_not_failures(self):
        # judge down on an otherwise-verified run: no evidence either
        # way — counted 'unjudged', never a failure
        b = train.compute_buckets([_rec(ok=True, judged=False)])
        self.assertEqual(b["fails"], 0)
        self.assertEqual(b["unjudged"], 1)

    def test_judge_dissent_is_a_failure_even_when_verified(self):
        r = _rec(ok=True)
        r["judge"]["success"] = False
        b = train.compute_buckets([r])
        self.assertEqual(b["fails"], 1)

    def test_environment_class_from_flake_fallback(self):
        r = _rec(cls=None)
        r["judge"]["failure_class"] = None
        r["steps"] = [{"tool": "click", "result": "ERROR mcp"}]
        self.assertEqual(train.failure_class(r), "environment")

    def test_first_fault_tool_drives_skill(self):
        r = _rec("click the button labeled ALPHA")
        r["judge"]["first_fault"] = 0
        r["steps"] = [{"tool": "scroll", "result": "OK"}]
        self.assertEqual(train.fail_skill(r), "scroll")

    def test_rebuild_writes_buckets_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "buckets.json"
            b = train.rebuild_buckets(
                path=p, records=[_rec(), _rec(ok=True)])
            self.assertTrue(p.exists())
            self.assertEqual(json.loads(p.read_text())["fails"], 1)
            self.assertEqual(b["top"], "model|scroll|browser-dom")


class TaskSkillTest(unittest.TestCase):
    def test_leading_verb_wins(self):
        self.assertEqual(train.task_skill(
            "scroll the list to the bottom then click ECHO"), "scroll")
        self.assertEqual(train.task_skill(
            "type 'wisp' into the text field then click BRAVO"), "type")
        self.assertEqual(train.task_skill(
            "select 'gamma' in the dropdown"), "select")
        self.assertEqual(train.task_skill(
            "click the button labeled ALPHA"), "click")
        self.assertEqual(train.task_skill(
            "click the chess tab and move the pawn on e2 to e4"),
            "click")
        self.assertEqual(train.task_skill("click the settings tab and "
                                          "set the theme to Dark"),
                         "click")


class PickTaskTest(unittest.TestCase):
    SUITE = [("click the button labeled ALPHA",
              "return s.counts['btn-alpha'] >= 1", 1),
             ("scroll the list to the bottom",
              "return s.scroll_top > 400", 1),
             ("type 'x' into the text field",
              "return (s.typed['textin']||'').includes('x')", 2)]

    def test_scroll_failures_pull_a_scroll_task(self):
        recs = [_rec("scroll the list to the bottom") for _ in range(3)]
        b = train.compute_buckets(recs)
        t = adaptive.pick_task(b, self.SUITE, random.Random(0))
        self.assertEqual(t[3]["source"], "pool")
        self.assertEqual(train.task_skill(t[0]), "scroll")
        self.assertIn("scroll", t[1])

    def test_below_cluster_floor_picks_suite(self):
        b = train.compute_buckets([_rec()])
        t = adaptive.pick_task(b, self.SUITE, random.Random(0))
        self.assertEqual(t[3]["source"], "suite")

    def test_non_lab_page_falls_back_to_same_skill_suite_task(self):
        recs = [_rec("scroll the list to the bottom") for _ in range(3)]
        b = train.compute_buckets(recs)
        suite = [("scroll the app list", "return s.x > 0", 1),
                 ("click thing", "return s.y", 1)]
        t = adaptive.pick_task(b, suite, random.Random(0),
                               page="apps.html")
        self.assertEqual(t[3]["source"], "suite-skill")
        self.assertIn("scroll", t[0])

    def test_unseen_suite_tasks_pick_first(self):
        seen = {"click the button labeled ALPHA",
                "type 'x' into the text field"}
        t = adaptive.pick_task(train.compute_buckets([]),
                               self.SUITE, random.Random(0), seen=seen)
        self.assertEqual(t[0], "scroll the list to the bottom")
        self.assertEqual(t[3]["source"], "suite")

    def test_exhausted_suite_falls_back_to_repeats(self):
        seen = {t[0] for t in self.SUITE}
        t = adaptive.pick_task(train.compute_buckets([]),
                               self.SUITE, random.Random(0), seen=seen)
        self.assertIsNotNone(t)
        self.assertEqual(t[3]["source"], "suite")


class PromotionTest(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        mock.patch.object(train, "BANK_FILE",
                          self.dir / "skillbank.json").start()
        self.addCleanup(mock.patch.stopall)

    def _ok(self):
        return _rec(ok=True)

    def test_promote_after_config_shortens_streak(self):
        cfg = {"clicklab": {"promote_after": "2"}}
        train.update_bank(self._ok(), cfg=cfg)
        e = train.update_bank(self._ok(), cfg=cfg)
        self.assertEqual(e["status"], "graduated")
        self.assertEqual(e["verified"], 2)

    def test_unjudged_run_does_not_count_toward_promotion(self):
        train.update_bank(self._ok())
        train.update_bank(self._ok())
        train.update_bank(_rec(ok=True, judged=False))  # neutral
        e = next(iter(train.load_bank().values()))
        self.assertEqual(e["streak"], 2)   # not broken, not counted
        self.assertEqual(e["status"], "candidate")
        e = train.update_bank(self._ok())
        self.assertEqual(e["status"], "graduated")

    def test_unjudged_does_not_demote_graduated(self):
        for _ in range(train.GRAD_STREAK):
            train.update_bank(self._ok())
        e = train.update_bank(_rec(ok=True, judged=False))
        self.assertEqual(e["status"], "graduated")

    def test_failure_post_promotion_demotes(self):
        for _ in range(train.GRAD_STREAK):
            train.update_bank(self._ok())
        e = train.update_bank(_rec(ok=False))
        self.assertEqual(e["status"], "demoted")

    def test_judge_dissent_blocks_count(self):
        r = self._ok()
        r["judge"]["success"] = False
        train.update_bank(r)
        e = next(iter(train.load_bank().values()))
        self.assertEqual(e["streak"], 0)


class AdaptiveLoopTest(unittest.TestCase):
    def test_stops_at_cap(self):
        calls = []
        done = adaptive.run_adaptive(
            lambda t, c, o, m: calls.append(t) or
            _rec(t, ok=True),
            PickTaskTest.SUITE, cap=4, rng=random.Random(1))
        self.assertEqual(len(done), 4)
        self.assertEqual(len(calls), 4)

    def test_bucket_drives_task_order(self):
        """3 scroll failures in history → the first pick is a scroll
        task even though the suite leads with clicks."""
        hist = [_rec("scroll the list to the bottom")
                for _ in range(3)]
        picked = []
        adaptive.run_adaptive(
            lambda t, c, o, m: picked.append(t) or _rec(t, ok=True),
            PickTaskTest.SUITE, cap=2, rng=random.Random(0),
            history=hist)
        self.assertEqual(train.task_skill(picked[0]), "scroll")

    def test_halt_stops_the_loop(self):
        n = [0]

        def one(t, c, o, m):
            n[0] += 1
            return _rec(t, ok=True)
        out = adaptive.run_adaptive(one, PickTaskTest.SUITE, cap=9,
                                    rng=random.Random(0),
                                    halt=lambda: n[0] >= 2)
        self.assertEqual(len(out), 2)

    def test_failures_steer_following_picks(self):
        """A cluster already at the floor keeps pulling that skill —
        the loop hammers the weak skill, not the suite order."""
        hist = [_rec("scroll the list to the bottom")
                for _ in range(2)]
        seen_skills = []

        def one(t, c, o, m):
            seen_skills.append(train.task_skill(t))
            return _rec(t, ok=train.task_skill(t) != "scroll")
        adaptive.run_adaptive(one, PickTaskTest.SUITE, cap=6,
                              rng=random.Random(3), history=hist)
        self.assertGreaterEqual(seen_skills.count("scroll"), 4)


if __name__ == "__main__":
    unittest.main()
