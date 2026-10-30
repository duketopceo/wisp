"""PR 259: exact installed titles outrank deictic launch heuristics.

Review: https://github.com/duketopceo/wisp/pull/259#discussion_r4421725064
Fakes only; no desktop, processes or model calls.
"""
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import route, stage_route


class ExactCatalogLaunch(unittest.TestCase):
    APPS = {"This War of Mine": {}, "Firefox": {}, "Settings": {}}

    def setUp(self):
        for target in ("wisp.brain.chat", "wisp.brain.chat_stream",
                       "urllib.request.urlopen", "subprocess.Popen",
                       "subprocess.run"):
            patch = mock.patch(
                target, side_effect=AssertionError("launch routing must be local"))
            patch.start()
            self.addCleanup(patch.stop)

    def test_installed_this_war_of_mine_keeps_the_bare_launch(self):
        result = route.heuristic("open This War of Mine", self.APPS)
        self.assertEqual(result["route"], "launch", result)
        self.assertEqual(result["app"], "This War of Mine")
        self.assertTrue(result["bare_launch"])
        answers, rule = stage_route.fast_route(
            "open This War of Mine", self.APPS, {})
        self.assertEqual(rule, "bare_launch")
        self.assertEqual(answers["app"]["choice"], "This War of Mine")

    def test_other_exact_installed_deictic_titles_still_launch(self):
        for title in ("That Game", "These Games", "Those Who Remain",
                      "Here Comes Niko!"):
            with self.subTest(title=title):
                apps = {**self.APPS, title: {}}
                answers, rule = stage_route.fast_route(
                    f"open {title}", apps, {})
                self.assertEqual(rule, "bare_launch")
                self.assertEqual(answers["app"]["choice"], title)

    def test_case_politeness_and_terminal_punctuation_keep_exact_title(self):
        for text in ("Open this war of mine.",
                     "could you please launch THIS WAR OF MINE!",
                     "wisp, pull up This War of Mine"):
            with self.subTest(text=text):
                answers, rule = stage_route.fast_route(text, self.APPS, {})
                self.assertEqual(rule, "bare_launch")
                self.assertEqual(answers["app"]["choice"], "This War of Mine")

    def test_full_title_wins_before_filler_stripping(self):
        apps = {"Game": {}, "The Game": {}}
        answers, _ = stage_route.fast_route("open The Game", apps, {})
        self.assertEqual(answers["app"]["choice"], "The Game")

    def test_existing_non_deictic_filler_launch_still_works(self):
        answers, _ = stage_route.fast_route(
            "open the Firefox application", self.APPS, {})
        self.assertEqual(answers["app"]["choice"], "Firefox")

    def test_unresolved_deictic_and_complex_requests_stay_in_act(self):
        for text in (
                "open this setting", "open up this setting", "open that app",
                "open these tabs", "open those files", "open here",
                "open This War of Mine and open Firefox",
                "open This War of Mine on the settings page",
                "open This War of Mine in fullscreen",
                "open This War of Mine then check achievements",
                "open This War of Mine with a controller",
                "open This War", "open War of Mine", "open This War of Mines"):
            with self.subTest(text=text):
                result = route.heuristic(text, self.APPS)
                self.assertEqual(result["route"], "act", result)
                self.assertFalse(result["bare_launch"])
                self.assertIsNone(stage_route.fast_route(text, self.APPS, {}))

    def test_title_is_not_fast_launched_when_absent_or_fast_path_disabled(self):
        self.assertIsNone(stage_route.fast_route(
            "open This War of Mine", {"Firefox": {}}, {}))
        self.assertIsNone(stage_route.fast_route(
            "open This War of Mine", self.APPS,
            {"brain": {"fast_path": "false"}}))


if __name__ == "__main__":
    unittest.main()
