"""B12: save a finished walkthrough as a lesson and replay it with no model."""
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import (lessons, stage_execute, stage_route,  # noqa: E402
                  walkthrough as wt, walkthrough_run as wr)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_walkthrough_run import Script, W, steps  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = pathlib.Path(td.name)
        self.root = root / "lessons"
        for name, val in (("PAUSED_FILE", root / "p.json"),
                          ("LAST_FILE", root / "last.json")):
            patcher = mock.patch.object(wr, name, val)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(lessons, "_dir", lambda: self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def finish_one(self, goal="export a pdf", texts=("open file", "export")):
        sc = Script([W("a"), W("b"), W("b"), W("c"), W("c")])
        out = wr.run(goal, {}, sc.state, steps=steps(*texts), env=sc.env())
        self.assertIn("all done", out)
        return sc


class Intent(unittest.TestCase):
    def test_save_phrases(self):
        for said, title in (
                ("save that as a lesson called export pdf", "export pdf"),
                ("save that lesson", ""),
                ("Wisp, save this walkthrough as a lesson named git", "git"),
                ("keep that walkthrough", "")):
            self.assertEqual(wr.lesson_intent(said), ("save", title), said)

    def test_replay_phrases(self):
        for said, name in (("replay that lesson", ""),
                           ("replay the lesson about export pdf",
                            "export pdf"),
                           ("redo my walkthrough called git", "git"),
                           ("play back the saved lesson", "")):
            self.assertEqual(wr.lesson_intent(said), ("replay", name), said)

    def test_ordinary_speech_is_not_a_lesson_command(self):
        for said in ("save that", "save the file", "run the tests",
                     "replay the video", "open my lessons folder"):
            self.assertIsNone(wr.lesson_intent(said), said)


class Store(Base):
    def dump(self, goal="g", n=2):
        return {"goal": goal, "steps": [
            {"text": f"s{i}", "label": f"L{i}", "point": None, "done": True}
            for i in range(n)]}

    def test_save_find_and_replace_by_title(self):
        self.assertEqual(lessons.save("Export PDF", self.dump("export")),
                         "export-pdf")
        rec = lessons.find("export pdf")
        self.assertEqual([s["text"] for s in rec["steps"]], ["s0", "s1"])
        lessons.save("Export PDF", self.dump("export", n=1))
        self.assertEqual(len(lessons.all_lessons()), 1)
        self.assertEqual(len(lessons.find("export pdf")["steps"]), 1)

    def test_find_by_words_then_newest(self):
        lessons.save("git rebase", self.dump("rebase my branch"))
        lessons.save("make a pdf", self.dump("export a pdf"))
        self.assertEqual(lessons.find("the lesson about rebase")["title"],
                         "git rebase")
        self.assertEqual(lessons.find("")["title"], "make a pdf")
        self.assertIsNone(lessons.find("quantum"))

    def test_nothing_to_save(self):
        self.assertIsNone(lessons.save("x", {"goal": "x", "steps": []}))
        self.assertIsNone(lessons.save("", {"goal": "", "steps": [
            {"text": "a"}]}))
        self.assertIsNone(lessons.find(""))

    def test_a_corrupt_lesson_is_skipped(self):
        lessons.save("ok", self.dump())
        (self.root / "bad.json").write_text("{nope")
        self.assertEqual([r["title"] for r in lessons.all_lessons()], ["ok"])


class SaveAndReplay(Base):
    def test_finish_then_save_then_replay_with_zero_model_calls(self):
        self.finish_one()
        out = wr.save_lesson("export pdf")
        self.assertIn("saved the lesson export pdf", out)

        sc = Script([W("a"), W("b"), W("b"), W("c"), W("c")])
        model = mock.Mock(side_effect=AssertionError("model called"))
        ask = mock.Mock(side_effect=AssertionError("asked"))
        with mock.patch("wisp.brain.chat", model), \
                mock.patch("wisp.brain.supports_vision", model):
            out = wr.replay_lesson("export pdf", {}, sc.state,
                                   env=sc.env(), ask=ask)
        self.assertEqual(sc.said, ["open file", "export"])
        self.assertIn("(2 steps)", out)
        model.assert_not_called()
        ask.assert_not_called()

    def test_replay_points_by_the_saved_label(self):
        sc = Script([W("a"), W("b")])
        wr.run("g", {}, sc.state,
               steps=[wt.Step("click save", label="Save")], env=sc.env())
        wr.save_lesson("save it")
        ground = mock.Mock(return_value={
            "ok": True, "x": 5, "y": 6, "w": 10, "h": 10})
        sc2 = Script([W("a"), W("b")])
        with mock.patch.object(wr, "snap_point",
                               return_value={"x": 5, "y": 6,
                                             "label": "Save"}) as snap:
            wr.replay_lesson("save it", {}, sc2.state, env=sc2.env(),
                             ground=ground)
        self.assertEqual(snap.call_args.args[0].label, "Save")
        self.assertEqual(sc2.published[0][1]["points"][0]["label"], "Save")

    def test_nothing_finished_means_nothing_to_save(self):
        self.assertIn("no finished walkthrough",
                      wr.save_lesson("x"))

    def test_an_unfinished_or_demonstrated_run_is_not_saveable(self):
        sc = Script([W("a")])
        wr.run("g", {}, sc.state, steps=steps("one"), env=sc.env(),
               ask=lambda *a: None)             # stuck, no answer: paused
        self.assertIsNone(wr.last_finished())
        wr.run("g", {}, sc.state, steps=steps("one"), env=sc.env(),
               demonstrate=True)
        self.assertIsNone(wr.last_finished())

    def test_unknown_lesson_says_so(self):
        out = wr.replay_lesson("nope", {}, None)
        self.assertIn("don't have a saved lesson", out)


class Wiring(Base):
    def test_routes(self):
        self.assertEqual(
            stage_route.fixed_route("save that as a lesson called x", "act"),
            ("walkthrough", wr.SAVE_PREFIX + "x"))
        self.assertEqual(
            stage_route.fixed_route("replay that lesson", "chat"),
            ("walkthrough", wr.REPLAY_PREFIX))

    def test_execute_saves_and_replays(self):
        self.finish_one(goal="export pdf")
        out = stage_execute.execute(
            {"route": {"choice": "walkthrough"}}, {},
            detail=wr.SAVE_PREFIX + "export", initial_image=None,
            interrupted=lambda: False)
        self.assertIn("saved the lesson export", out)
        with mock.patch.object(wr, "run",
                               return_value="WALKED (2 steps): all done.") \
                as run:
            out = stage_execute.execute(
                {"route": {"choice": "walkthrough"}}, {},
                detail=wr.REPLAY_PREFIX + "export", initial_image=None,
                interrupted=lambda: False)
        self.assertEqual(out, "WALKED (2 steps): all done.")
        self.assertEqual([s.text for s in run.call_args.kwargs["steps"]],
                         ["open file", "export"])


if __name__ == "__main__":
    unittest.main()
