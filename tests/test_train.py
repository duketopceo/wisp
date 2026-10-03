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

    def test_stats_buckets(self):
        self.results.write_text(
            "\n".join(__import__("json").dumps(r) for r in
                      [_rec(), _rec(ok=False, eff=0.0),
                       _rec(surface="desktop")]) + "\n")
        s = train.stats()
        self.assertEqual(s["runs"], 3)
        self.assertEqual(s["surfaces"]["browser-dom"]["pass"], 1)
        self.assertEqual(s["surfaces"]["desktop"]["pass"], 1)


if __name__ == "__main__":
    unittest.main()


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
