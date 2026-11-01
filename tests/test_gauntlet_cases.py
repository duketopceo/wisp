#!/usr/bin/env python3
"""The gauntlet case battery (U7): every case is sound, safe and fits the
categories the gauntlet scores. Offline; nothing is launched."""
import importlib.util
import json
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

_spec = importlib.util.spec_from_file_location(
    "gauntlet_script", ROOT / "scripts" / "gauntlet.py")
G = importlib.util.module_from_spec(_spec)
sys.modules["gauntlet_script"] = G
_spec.loader.exec_module(G)

CASES_FILE = ROOT / "docs" / "dev-tasks" / "gauntlet.jsonl"
SEEDS = ROOT / "wisp" / "skills_seed" / "apps"
UNSAFE = re.compile(
    r"\b(send|sends|submit|buy|purchase|pay|checkout|delete|remove|erase|"
    r"trash|post|publish|email|log ?in|sign ?in|password|account|"
    r"credit|invoice)\b", re.I)
TYPING = re.compile(
    r"\b(type|typing|enter|write|fill|set|apply|change|toggle|enable|"
    r"disable|install|select an? option|choose)\b", re.I)


class Battery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = G.load_cases(CASES_FILE)

    def test_every_case_parses_and_validates(self):
        self.assertGreaterEqual(len(self.cases), 18)
        self.assertLessEqual(len(self.cases), 24)
        ids = [c["id"] for c in self.cases]
        self.assertEqual(len(ids), len(set(ids)))
        for c in self.cases:
            self.assertEqual(G.validate_case(c), [], c["id"])

    def test_each_case_names_a_sandbox_app_or_the_menu_and_a_check(self):
        for c in self.cases:
            self.assertTrue(c["app"] in G.sandbox.APPS or
                            (c["category"] == "menu" and c["app"] == "menu"),
                            c["id"])
            self.assertIn(c["check"]["type"], G.CHECK_TYPES, c["id"])
            # a case with no deterministic check says so: judge fallback
            if c["check"]["type"] == "judge":
                self.assertEqual(c["check"], {"type": "judge"})

    def test_no_goal_sends_submits_buys_deletes_or_posts(self):
        for c in self.cases:
            self.assertIsNone(UNSAFE.search(c["goal"]),
                              f"{c['id']}: {c['goal']}")

    def test_no_case_touches_accounts_or_leaves_the_sandbox(self):
        for c in self.cases:
            blob = json.dumps(c)
            self.assertNotIn("..", blob, c["id"])
            self.assertNotRegex(blob, r"(?i)gmail|slack|stripe|github\.com|"
                                r"localhost|127\.0\.0\.1", c["id"])
            for name in (c.get("setup") or {}).get("files", {}):
                self.assertFalse(name.startswith("/"), c["id"])

    def test_menu_cases_open_and_close_only(self):
        menu = [c for c in self.cases if c["category"] == "menu"]
        self.assertGreaterEqual(len(menu), 2)
        for c in menu:
            self.assertEqual(c["app"], "menu")
            self.assertIsNone(TYPING.search(c["goal"]), c["goal"])
            self.assertEqual(c["check"]["type"], "judge")
            self.assertFalse(c["learnable"])
            self.assertEqual(G.case_apps(c), [])      # no sandbox window

    def test_learnable_cases_name_a_sandbox_app_with_a_skill_seed(self):
        learnable = [c for c in self.cases if c["learnable"]]
        self.assertGreaterEqual(len(learnable), 8)
        for c in learnable:
            self.assertIn(c["app"], G.sandbox.APPS, c["id"])
            self.assertTrue((SEEDS / c["skill_seed"] / "SKILL.md").exists(),
                            f"{c['id']}: seed {c['skill_seed']}")

    def test_held_out_cases_cover_every_category(self):
        held = [c for c in self.cases if c["held_out"]]
        self.assertEqual({c["category"] for c in held},
                         set(G.CATEGORIES))
        share = len(held) / len(self.cases)
        self.assertTrue(0.25 <= share <= 0.45, share)

    def test_every_category_has_tuning_cases_to_rank_failures_from(self):
        tuning = {c["category"] for c in self.cases if not c["held_out"]}
        self.assertEqual(tuning, set(G.CATEGORIES))

    def test_goals_fit_a_task_line_and_the_learn_turn_routes_to_learn(self):
        from wisp import route
        for c in self.cases:
            self.assertLessEqual(len(c["goal"]), G.TASK_CHARS)
            lg = G.learn_goal(c, "chromium")
            self.assertLessEqual(len(lg), G.TASK_CHARS)
            self.assertEqual(route.heuristic(lg, None).get("route"),
                             "learn", lg)
            self.assertIn("app_classes: chromium", lg)

    def test_window_cases_open_the_apps_they_check(self):
        for c in self.cases:
            if c["check"]["type"] in ("window_workspace", "geometry_changed",
                                      "window_focused"):
                self.assertIn(c["check"]["app"], G.case_apps(c), c["id"])

    def test_a_dry_run_walks_every_case(self):
        lines = []
        code = G.main(["--dry-run"], out=lines.append)
        self.assertEqual(code, 0)
        for c in self.cases:
            self.assertTrue(any(c["id"] in ln for ln in lines), c["id"])
        self.assertTrue(all("x2 arms" in ln for ln in lines))


class Validation(unittest.TestCase):
    def good(self):
        return {"id": "x-1", "category": "files", "app": "files",
                "goal": "open the folder", "learnable": False,
                "held_out": False, "minimal_steps": 2,
                "check": {"type": "judge"}}

    def test_a_sound_case_has_no_problems(self):
        self.assertEqual(G.validate_case(self.good()), [])

    def test_each_defect_is_named(self):
        for key, bad in (("id", "Bad Id"), ("category", "mail"),
                         ("app", "firefox"), ("goal", ""),
                         ("learnable", "yes"), ("minimal_steps", 0),
                         ("check", {"type": "magic"})):
            c = self.good()
            c[key] = bad
            self.assertTrue(G.validate_case(c), key)

    def test_a_learnable_case_needs_a_seed_and_a_sandbox_app(self):
        c = self.good()
        c["learnable"] = True
        self.assertTrue(G.validate_case(c))
        c["skill_seed"] = "nautilus"
        self.assertEqual(G.validate_case(c), [])
        c["app"], c["category"] = "menu", "menu"
        self.assertTrue(G.validate_case(c))

    def test_load_names_the_line_and_refuses_duplicates(self):
        import shorttmp
        with shorttmp.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "c.jsonl"
            good = json.dumps(self.good())
            p.write_text(f"# hi\n{good}\n{good}\n")
            with self.assertRaisesRegex(G.CaseError, "line 3.*duplicate"):
                G.load_cases(p)
            p.write_text("not json\n")
            with self.assertRaisesRegex(G.CaseError, "line 1"):
                G.load_cases(p)
            p.write_text("# nothing\n")
            with self.assertRaises(G.CaseError):
                G.load_cases(p)


if __name__ == "__main__":
    unittest.main()
