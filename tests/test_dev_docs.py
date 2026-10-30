#!/usr/bin/env python3
"""U6: the starter task list and DEV_MODE.md. Every task in the starter
list must pre-screen (devrun's own function) to a route the runner does
not skip, and the doc must only name commands that exist (also covered by
test_docs_lint)."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

STARTER = ROOT / "docs" / "dev-tasks" / "starter.txt"
DOC = ROOT / "docs" / "DEV_MODE.md"
UNSAFE = ("type ", "send ", "buy ", "purchase", "delete", "post ", "email",
          "message ", "pay ", "order ")


class TestStarter(unittest.TestCase):
    def tasks(self):
        from wisp import devrun
        self.assertTrue(STARTER.exists(), STARTER)
        return devrun.read_tasks(STARTER)

    def test_about_ten_tasks_with_the_owner_pair(self):
        t = [x.lower() for x in self.tasks()]
        self.assertGreaterEqual(len(t), 8)
        self.assertLessEqual(len(t), 14)
        self.assertIn("pause youtube", t)
        self.assertIn("open my stripe tab", t)

    def test_every_task_prescreens_to_a_runnable_route(self):
        from wisp import config, devrun
        cfg = config._default_cfg_dict()
        for goal in self.tasks():
            route, skip = devrun.prescreen(goal, cfg)
            self.assertFalse(skip, f"{goal!r} pre-screens to skipped {route}")

    def test_no_unsafe_verbs(self):
        for goal in self.tasks():
            low = goal.lower() + " "
            for bad in UNSAFE:
                self.assertNotIn(bad, low, goal)

    def test_comments_are_allowed(self):
        self.assertIn("#", STARTER.read_text())


class TestDoc(unittest.TestCase):
    def test_doc_covers_the_surface(self):
        self.assertTrue(DOC.exists())
        s = DOC.read_text()
        for needle in ("wispd dev on", "wispd dev run", "--vs",
                       "wispd dev review", "wispd dev runs", "wispd dev stop",
                       "wispd dev off", "5 runs", "owner-confirmed",
                       "starter.txt"):
            self.assertIn(needle, s)

    def test_readme_links_the_doc(self):
        self.assertIn("DEV_MODE.md", (ROOT / "README.md").read_text())


if __name__ == "__main__":
    unittest.main()
