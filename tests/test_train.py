"""Training arena — skill bank streaks, graduation, demotion, stats."""
import pathlib
import tempfile
import unittest
from unittest import mock

from wisp import train


def _rec(task="click alpha", ok=True, eff=1.0, surface="browser-dom",
         suite="core"):
    return {"task": task, "surface": surface, "suite": suite,
            "verified": ok,
            "judge": {"success": ok, "efficiency": eff,
                      "waste": "none"},
            "steps": [{"tool": "click", "arg": "1,2",
                       "result": "CLICKED btn-alpha"}],
            "ts": 1.0}


class TrainTest(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.bank = self.dir / "skillbank.json"
        self.results = self.dir / "clicklab.jsonl"
        mock.patch.object(train, "BANK_FILE", self.bank).start()
        mock.patch.object(train, "RESULTS", self.results).start()
        self.addCleanup(mock.patch.stopall)

    def test_graduates_on_streak(self):
        for _ in range(train.GRAD_STREAK):
            e = train.update_bank(_rec())
        self.assertEqual(e["status"], "graduated")
        self.assertTrue(e["changed"])

    def test_no_graduation_below_efficiency_floor(self):
        for _ in range(train.GRAD_STREAK + 1):
            e = train.update_bank(_rec(eff=0.5))
        self.assertEqual(e["status"], "candidate")

    def test_fail_resets_streak(self):
        train.update_bank(_rec())
        train.update_bank(_rec())
        train.update_bank(_rec(ok=False, eff=0.0))
        e = train.update_bank(_rec())
        self.assertEqual(e["status"], "candidate")
        self.assertEqual(e["streak"], 1)

    def test_demotion(self):
        for _ in range(train.GRAD_STREAK):
            train.update_bank(_rec())
        e = train.update_bank(_rec(ok=False, eff=0.0))
        self.assertEqual(e["status"], "demoted")

    def test_regraduate_after_demotion(self):
        for _ in range(train.GRAD_STREAK):
            train.update_bank(_rec())
        train.update_bank(_rec(ok=False, eff=0.0))
        for _ in range(train.GRAD_STREAK):
            e = train.update_bank(_rec())
        self.assertEqual(e["status"], "graduated")

    def test_surfaces_stay_separate(self):
        train.update_bank(_rec(surface="browser-dom"))
        train.update_bank(_rec(surface="desktop"))
        bank = train.load_bank()
        self.assertEqual(len(bank), 2)

    def test_judge_dissent_blocks_streak(self):
        r = _rec()
        r["judge"]["success"] = False
        train.update_bank(r)
        e = train.update_bank(_rec())
        self.assertEqual(e["streak"], 1)

    def test_hint_for_graduated_only(self):
        train.update_bank(_rec())  # candidate — no hint yet
        self.assertEqual(train.hint_for("click alpha", "browser-dom"),
                         "")
        for _ in range(train.GRAD_STREAK - 1):
            train.update_bank(_rec())
        h = train.hint_for("click alpha", "browser-dom")
        self.assertIn("proven sequence", h)
        # wrong surface → no hint
        self.assertEqual(train.hint_for("click alpha", "desktop"), "")

    def test_recipe_id_on_promotion(self):
        # candidates have no recipe id; graduation stamps a stable one
        train.update_bank(_rec())
        train.update_bank(_rec())
        bank = train.load_bank()
        e = next(iter(bank.values()))
        self.assertNotIn("recipe_id", e)
        e = train.update_bank(_rec())
        rid = e["recipe_id"]
        self.assertTrue(rid.startswith("recipe-"))
        # survives demotion + re-graduation
        train.update_bank(_rec(ok=False, eff=0.0))
        for _ in range(train.GRAD_STREAK):
            e = train.update_bank(_rec())
        self.assertEqual(e["recipe_id"], rid)

    def test_stats_buckets(self):
        self.results.write_text(
            "\n".join(__import__("json").dumps(r) for r in
                      [_rec(), _rec(ok=False, eff=0.0),
                       _rec(surface="desktop")]) + "\n")
        s = train.stats()
        self.assertEqual(s["runs"], 3)
        self.assertEqual(s["surfaces"]["browser-dom"]["pass"], 1)
        self.assertEqual(s["surfaces"]["desktop"]["pass"], 1)


class DistillTest(unittest.TestCase):
    """Streak-rich wasteful candidates: distill the banked trajectory,
    re-verify on a fresh seed, graduate the shorter path."""

    def test_distill_drops_passive_and_no_effect(self):
        steps = [
            {"tool": "click", "arg": "tab", "result": "CLICKED tab"},
            {"tool": "screenshot", "arg": "", "result": "SHOT x"},
            {"tool": "screenshot", "arg": "(auto re-observe)",
             "result": "SHOT x"},
            {"tool": "move", "arg": "1,2", "result": "MOVED(1,2)"},
            {"tool": "click", "arg": "nope", "result": "SKIP (miss)"},
            {"tool": "key", "arg": "enter", "result": "ERROR (x)"},
            {"tool": "fill", "arg": "f v", "result": "FILLED f=v"},
        ]
        d = train.distill_steps(steps)
        self.assertEqual([s["tool"] for s in d],
                         ["click", "fill"])

    def test_candidates_need_streak_check_and_shrink(self):
        base = {"status": "candidate", "streak": 5, "check": "1",
                "steps": [{"tool": "screenshot", "result": "SHOT"},
                          {"tool": "click", "arg": "a",
                           "result": "CLICKED"}]}
        self.assertEqual(train.distill_candidates({"k": base}), [base])
        for e in (dict(base, steps=[{"tool": "click", "arg": "a",
                                     "result": "CLICKED"}]),
                  dict(base, streak=1),
                  dict(base, status="graduated"),
                  dict(base, check="")):
            self.assertEqual(train.distill_candidates({"k": e}), [], e)

    def test_promote_stamps_recipe(self):
        e = {"key": "abc", "status": "candidate",
             "steps": [{"tool": "click"}, {"tool": "screenshot"},
                       {"tool": "click"}]}
        d = train.distill_steps(e["steps"])
        train.promote(e, d)
        self.assertEqual(e["status"], "graduated")
        self.assertTrue(e["optimized"])
        self.assertEqual(e["orig_steps"], 3)
        self.assertEqual(e["steps"], d)
        self.assertTrue(e["recipe_id"].startswith("recipe-"))


class ModelMatrix(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.bank = self.dir / "skillbank.json"
        self.results = self.dir / "clicklab.jsonl"
        mock.patch.object(train, "BANK_FILE", self.bank).start()
        mock.patch.object(train, "RESULTS", self.results).start()
        self.addCleanup(mock.patch.stopall)

    def test_model_keyed_entries_do_not_collide(self):
        r = _rec()
        r["model"] = "gemini"
        for _ in range(train.GRAD_STREAK):
            train.update_bank(dict(r))
        for _ in range(train.GRAD_STREAK):
            e = train.update_bank(_rec())  # unkeyed run
        bank = train.load_bank(self.bank)
        self.assertEqual(len(bank), 2)
        self.assertTrue(any("gemini" in k for k in bank))

    def test_stats_groups_by_model(self):
        r = _rec()
        r["model"] = "uitars"
        import json as _j
        with self.results.open("a") as f:
            f.write(_j.dumps(r) + "\n")
            f.write(_j.dumps(_rec()) + "\n")
        s = train.stats()
        models = s.get("models", {})
        self.assertIn("uitars", models)
        self.assertEqual(models["uitars"]["runs"], 1)

    def test_hint_for_prefers_model_keyed(self):
        r = _rec()
        r["model"] = "fast"
        r2 = _rec()
        r2["steps"] = [{"tool": "click", "arg": "9,9",
                        "result": "CLICKED"}]
        for _ in range(train.GRAD_STREAK):
            train.update_bank(dict(r))     # model-keyed, step arg 1,2
            train.update_bank(dict(r2))    # unkeyed, step arg 9,9
        h = train.hint_for("click alpha", "browser-dom", model="fast")
        self.assertIn("1,2", h)
        h2 = train.hint_for("click alpha", "browser-dom", model="other")
        self.assertIn("9,9", h2)  # falls back to unkeyed


class Reliability(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.bank = self.dir / "skillbank.json"
        self.results = self.dir / "clicklab.jsonl"
        mock.patch.object(train, "BANK_FILE", self.bank).start()
        mock.patch.object(train, "RESULTS", self.results).start()
        self.addCleanup(mock.patch.stopall)

    def _write(self, recs):
        import json as _j
        with self.results.open("a") as f:
            for r in recs:
                f.write(_j.dumps(r) + "\n")

    def test_pass_rate_per_task(self):
        rs = [dict(_rec(ok=True), model="m1"),
              dict(_rec(ok=True), model="m1"),
              dict(_rec(ok=False), model="m1")]
        rs[2]["judge"]["success"] = False
        self._write(rs)
        s = train.stats()
        rel = [r for r in s["reliability"] if r["model"] == "m1"]
        self.assertEqual(len(rel), 1)
        self.assertEqual(rel[0]["runs"], 3)
        self.assertEqual(rel[0]["pass"], 2)
        self.assertAlmostEqual(rel[0]["pass_rate"], 2 / 3, places=2)

    def test_models_bucket_separately(self):
        self._write([dict(_rec(ok=True), model="m1"),
                     dict(_rec(ok=False), model="m2")])
        s = train.stats()
        # each model has 1 run — below the runs>=2 floor
        self.assertEqual(s["reliability"], [])

    def test_surfaces_bucket_separately(self):
        self._write([dict(_rec(ok=True), surface="browser-dom"),
                     dict(_rec(ok=False), surface="desktop"),
                     dict(_rec(ok=True), surface="desktop")])
        s = train.stats()
        self.assertEqual(len(s["reliability"]), 1)
        self.assertEqual(s["reliability"][0]["surface"], "desktop")

    def test_empty_results_no_crash(self):
        s = train.stats()
        self.assertEqual(s["reliability"], [])


class FlakeTaxonomy(unittest.TestCase):
    def test_verified_pass_is_none(self):
        self.assertEqual(train.classify_flake(_rec(ok=True)), "none")

    def test_verified_pass_judge_dissent_is_judge_fn(self):
        r = _rec(ok=True)
        r["judge"]["success"] = False
        self.assertEqual(train.classify_flake(r), "judge_fn")

    def test_all_error_steps_is_env(self):
        r = _rec(ok=False)
        r["steps"] = [{"tool": "click", "result": "ERROR mcp"},
                      {"tool": "key", "result": "ERROR mcp"}]
        self.assertEqual(train.classify_flake(r), "env")

    def test_env_hint_in_any_step_is_env(self):
        r = _rec(ok=False)
        r["steps"] = [{"tool": "click", "result": "CLICKED DIV"},
                      {"tool": "key", "result": "ERROR mcp timeout"}]
        self.assertEqual(train.classify_flake(r), "env")

    def test_short_stall_is_timing(self):
        r = _rec(ok=False)
        r["steps"] = [{"tool": "click", "result": "CLICKED DIV"}]
        r["verdict"] = "ABORTED: no tools"
        self.assertEqual(train.classify_flake(r), "timing")

    def test_real_fail_is_model(self):
        r = _rec(ok=False)
        r["steps"] = [{"tool": "click", "result": "CLICKED wrong"},
                      {"tool": "click", "result": "CLICKED wrong"},
                      {"tool": "click", "result": "CLICKED wrong"}]
        r["verdict"] = "ACTED (3 steps): hmm"
        self.assertEqual(train.classify_flake(r), "model")

    def test_stats_histogram_counts_flakes(self):
        import tempfile, pathlib, json as _j
        with tempfile.TemporaryDirectory() as d:
            res = pathlib.Path(d) / "r.jsonl"
            rs = [_rec(ok=True), _rec(ok=False)]
            rs[1]["steps"] = [{"tool": "x", "result": "ERROR mcp"}]
            with res.open("w") as f:
                for r in rs:
                    f.write(_j.dumps(r) + "\n")
            with mock.patch.object(train, "RESULTS", res), \
                 mock.patch.object(train, "BANK_FILE",
                                   pathlib.Path(d) / "b.json"):
                s = train.stats()
        self.assertEqual(s["flakes"], {"env": 1})

    def test_stats_uses_stored_flake_field(self):
        import tempfile, pathlib, json as _j
        with tempfile.TemporaryDirectory() as d:
            res = pathlib.Path(d) / "r.jsonl"
            r = _rec(ok=True)
            r["flake"] = "env"   # stored label wins over re-classify
            with res.open("w") as f:
                f.write(_j.dumps(r) + "\n")
            with mock.patch.object(train, "RESULTS", res), \
                 mock.patch.object(train, "BANK_FILE",
                                   pathlib.Path(d) / "b.json"):
                s = train.stats()
        self.assertEqual(s["flakes"], {"env": 1})

if __name__ == "__main__":
    unittest.main()
