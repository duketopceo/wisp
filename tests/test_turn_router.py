import json
import pathlib
import unittest
from types import SimpleNamespace
from unittest import mock

from wisp import grader, pipeline, turn_router

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures"
                  / "router_turns.json").read_text())
APPS = {"firefox": {}, "Spotify": {}}
CFG = {"brain": {"router": "act"},
       "router": {"ambiguity_model": "openrouter:nvidia/nemotron-3.5-lightning"}}


class Chat:
    def __init__(self, reply="answer", boom=False):
        self.calls, self.reply, self.boom = [], reply, boom

    def __call__(self, msgs, cfg, timeout=0):
        self.calls.append((msgs, cfg, timeout))
        if self.boom:
            raise OSError("down")
        return {"content": self.reply}


def settled_by_rules(text):
    from wisp import stage_route
    return (stage_route.fixed_route(text, "act", True) != ("act", None)
            or bool(stage_route.fast_route(text, APPS, {}))
            or not turn_router.ambiguity(text, APPS))


class Fixtures(unittest.TestCase):
    def test_fixture_split_matches_the_rules(self):
        for t in FIX:
            with self.subTest(t["text"]):
                self.assertEqual(settled_by_rules(t["text"]),
                                 t["expect"] == "rule")

    def test_rule_settled_turns_never_call_the_model(self):
        chat = Chat()
        for t in FIX:
            if t["expect"] == "rule":
                self.assertIsNone(
                    turn_router.resolve(t["text"], CFG, APPS, active=False,
                                        chat=chat) if not settled_by_rules(
                        t["text"]) else None)
        self.assertEqual(chat.calls, [])

    def test_ambiguous_turns_get_exactly_one_call(self):
        for t in FIX:
            if t["expect"] == "ambiguous":
                chat = Chat("teach")
                d = turn_router.resolve(t["text"], CFG, APPS, active=False,
                                        chat=chat)
                self.assertEqual(len(chat.calls), 1, t["text"])
                self.assertEqual((d.lane, d.route), ("model", "teach"))
                # the request is quoted data in the user turn only
                self.assertIn(t["text"], chat.calls[0][0][1]["content"])
                self.assertEqual(chat.calls[0][1]["brain"]["default"],
                                 "openrouter:nvidia/nemotron-3.5-lightning")
                self.assertEqual(chat.calls[0][1]["brain"]["fallback"], "")


class Guards(unittest.TestCase):
    TEXT = "my screen looks too bright"

    def test_off_by_default(self):
        chat = Chat()
        self.assertIsNone(turn_router.resolve(self.TEXT, {}, APPS,
                                              active=False, chat=chat))
        self.assertEqual(chat.calls, [])

    def test_running_job_never_calls_a_model(self):
        chat = Chat()
        d = turn_router.resolve(self.TEXT, CFG, APPS, active=True, chat=chat)
        self.assertEqual((d.lane, d.route), ("locked", "act"))
        self.assertEqual(chat.calls, [])

    def test_paused_walkthrough_counts_as_a_running_job(self):
        with mock.patch("wisp.walkthrough_run.paused",
                        return_value={"goal": "g", "steps": [1]}):
            self.assertTrue(turn_router.job_active())
            chat = Chat()
            d = turn_router.resolve(self.TEXT, CFG, APPS, chat=chat)
            self.assertEqual(d.lane, "locked")
            self.assertEqual(chat.calls, [])

    def test_failure_and_garbage_fall_back_to_act(self):
        for chat in (Chat(boom=True), Chat("banana"), Chat("act or answer")):
            d = turn_router.resolve(self.TEXT, CFG, APPS, active=False,
                                    chat=chat)
            self.assertEqual((d.lane, d.route), ("fallback", "act"))

    def test_reply_parsing(self):
        self.assertEqual(turn_router.parse_reply(" Answer. "), "answer")
        self.assertEqual(turn_router.parse_reply('{"route": "agent"}'), "agent")
        self.assertEqual(turn_router.parse_reply("act and teach"), "")

    def test_route_shapes(self):
        d = lambda r: turn_router.Decision(r, "model")  # noqa: E731
        self.assertEqual(turn_router.as_route(d("answer"), "x"),
                         ("answer", None))
        self.assertEqual(turn_router.as_route(d("teach"), "x"),
                         ("walkthrough", "x"))
        self.assertEqual(turn_router.as_route(d("agent"), "x"), ("act", "x"))
        self.assertEqual(turn_router.as_route(d("act"), "x"), ("act", None))


class Stage(unittest.TestCase):
    def ctx(self, text, cfg):
        return SimpleNamespace(
            text=text, cfg=cfg, detail=text, state=mock.Mock(),
            sp=mock.MagicMock(), turn="t", token=mock.Mock(), model="n",
            harness={"apps": APPS}, context="", wait_for_choice=None,
            answers={}, result="", reply="", app="none")

    def test_route_stage_uses_the_model_for_the_residue_only(self):
        chat = Chat("answer")
        with mock.patch("wisp.brain.chat", chat), \
                mock.patch("wisp.trace.emit"), \
                mock.patch("wisp.walkthrough_run.paused", return_value=None):
            c = self.ctx("my screen looks too bright", CFG)
            self.assertTrue(pipeline.route_stage(c))
            self.assertEqual(c.answers["route"]["choice"], "answer")
            self.assertEqual(len(chat.calls), 1)
            c = self.ctx("click the save button", CFG)
            self.assertTrue(pipeline.route_stage(c))
            self.assertEqual(len(chat.calls), 1)      # rules decided it


class Grader(unittest.TestCase):
    CFG = {"grader": {"enabled": "true",
                      "model": "openrouter:google/gemma-4-31b-it"}}

    def test_off_by_default_makes_no_call(self):
        chat = Chat()
        self.assertIsNone(grader.grade("t", [], "done", {}, chat=chat))
        self.assertEqual(chat.calls, [])

    def test_grades_and_logs_a_lesson(self):
        import tempfile
        chat = Chat('{"grade": "partial", "lesson": "open the menu first"}')
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "grades.jsonl"
            rec = grader.grade("crop it", [{"tool": "click", "arg": "x"}],
                               "done", self.CFG, chat=chat, path=path)
            self.assertEqual(rec["grade"], "partial")
            line = json.loads(path.read_text().splitlines()[0])
            self.assertEqual(line["lesson"], "open the menu first")
        self.assertEqual(len(chat.calls), 1)

    def test_bad_reply_and_failure_write_nothing(self):
        import tempfile
        for chat in (Chat("nope"), Chat(boom=True)):
            with tempfile.TemporaryDirectory() as d:
                path = pathlib.Path(d) / "g.jsonl"
                self.assertIsNone(grader.grade("t", [], "o", self.CFG,
                                               chat=chat, path=path))
                self.assertFalse(path.exists())

    def test_model_falls_back_to_agent_model(self):
        self.assertEqual(
            grader.model_spec({"grader": {"enabled": "true"},
                               "agent": {"model": "x/y"}}), "openrouter:x/y")

    def test_runs_in_the_background_writer_after_the_task(self):
        from wisp import act
        order = []
        with mock.patch("wisp.bgwriter.submit", side_effect=lambda f: f()), \
                mock.patch("wisp.trajectories.record",
                           side_effect=lambda *a, **k: order.append("rec")), \
                mock.patch("wisp.grader.grade",
                           side_effect=lambda *a, **k: order.append("grade")):
            act._record_traj("t", None, [{"tool": "click"}], "ok", {})
        self.assertEqual(order, ["rec", "grade"])


if __name__ == "__main__":
    unittest.main()
