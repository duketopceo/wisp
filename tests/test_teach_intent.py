"""Teach mode: a learner's "how do I X" starts a walkthrough, and each
step carries a short "why" so the user learns the idea, not just clicks."""
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import (lessons, stage_route, walkthrough as wt,  # noqa: E402
                  walkthrough_run as wr)


class TeachIntent(unittest.TestCase):
    def test_learner_phrasings_give_the_goal(self):
        for said, goal in (
                ("Wisp, show me how to split a pane?", "split a pane"),
                ("show me how to rebase", "rebase"),
                ("show me how I can crop", "crop"),
                ("teach me vim macros", "vim macros"),
                ("I want to learn how to use layers", "use layers"),
                ("I'm trying to set up a git repo", "set up a git repo")):
            self.assertEqual(wr.teach_intent(said), goal, said)

    def test_facts_and_commands_are_not_lessons(self):
        for said in ("how do I open a new tab", "how to crop an image",
                     "how does git work", "how much memory is free",
                     "how do I know if it saved", "how do I tell which one",
                     "open firefox", "what is a layer", "teach me", "",
                     "how do I"):
            self.assertIsNone(wr.teach_intent(said), said)

    def test_walk_intent_is_unchanged(self):
        self.assertIsNone(wr.walk_intent("how do I rebase"))


class Routing(unittest.TestCase):
    def test_learner_request_routes_to_a_walkthrough_on_both_routers(self):
        for router in ("act", "chat"):
            self.assertEqual(
                stage_route.fixed_route("teach me to export a PDF", router),
                ("walkthrough", "export a PDF"), router)

    def test_teach_can_be_turned_off(self):
        self.assertEqual(
            stage_route.fixed_route("teach me vim macros", "act",
                                    teach=False), ("act", None))

    def test_a_bare_how_do_i_is_not_hijacked(self):
        self.assertEqual(
            stage_route.fixed_route("how do i open a new tab", "act"),
            ("act", None))

    def test_commands_still_reach_act(self):
        self.assertEqual(stage_route.fixed_route("click save", "act"),
                         ("act", None))


class Why(unittest.TestCase):
    RAW = ('{"steps": [{"say": "Open the File menu", "label": "File", '
           '"why": "Export lives under File."}, {"say": "Pick Export"}]}')

    def test_why_is_parsed_and_defaults_empty(self):
        a, b = wr.parse_steps(self.RAW)
        self.assertEqual(a.why, "Export lives under File.")
        self.assertEqual(b.why, "")

    def test_why_is_spoken_after_the_instruction(self):
        a, b = wr.parse_steps(self.RAW)
        self.assertEqual(wr.spoken(a),
                         "Open the File menu Export lives under File.")
        self.assertEqual(wr.spoken(b), "Pick Export")

    def test_prompt_asks_for_why_and_knows_the_desktop(self):
        self.assertIn('"why"', wr._PROMPT)
        self.assertIn("Hyprland", wr._PROMPT)

    def test_why_survives_save_and_replay(self):
        steps = wr.parse_steps(self.RAW)
        dump = {"goal": "export", "steps": [
            {"text": s.text, "label": s.label, "point": s.point,
             "why": s.why} for s in steps]}
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            name = lessons.save("export", dump, root=root)
            rec = lessons.find("export", root=root)
        self.assertTrue(name)
        self.assertEqual(wr.steps_from(rec)[0].why, "Export lives under File.")

    def test_why_does_not_change_the_step_key(self):
        self.assertEqual(wt.Step(text="x", why="a").key,
                         wt.Step(text="x", why="b").key)


if __name__ == "__main__":
    unittest.main()
