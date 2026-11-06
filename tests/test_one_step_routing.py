"""U6: a bare "how do I <task>" can teach in one step or many, and
`[teach] auto = "false"` restores the routing from before."""
import json
import pathlib
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from wisp import pipeline, stage_route, walkthrough as wt  # noqa: E402
from wisp import walkthrough_run as wr  # noqa: E402

_TMP = None


def setUpModule():
    global _TMP
    _TMP = tempfile.TemporaryDirectory()
    wr.PAUSED_FILE = pathlib.Path(_TMP.name) / "walkthrough.json"
    wr.LAST_FILE = pathlib.Path(_TMP.name) / "walkthrough_last.json"


def tearDownModule():
    _TMP.cleanup()


TASKS = ("how do I export this as a PDF", "how can I set up a git repo",
         "how do i crop an image", "how to rebase onto main",
         "Wisp, how would I resize this layer?", "how do I connect to wifi")
ONE_LINERS = ("how do i open a new tab", "how do I undo this",
              "how do i move this tab to the other window",
              "what does this error mean", "what time is it",
              "how does git work", "how much memory is free")
NOT_PROCEDURES = ("how do I know if it saved", "how do I tell which one",
                  "how do I decide between them", "how can I trust this")


class Intent(unittest.TestCase):
    def test_task_questions_give_the_goal(self):
        self.assertEqual(wr.howto_intent("how do I export this as a PDF"),
                         "export this as a PDF")
        self.assertEqual(wr.howto_intent("Wisp, how would I resize this layer?"),
                         "resize this layer")
        for said in TASKS:
            self.assertIsNotNone(wr.howto_intent(said), said)

    def test_one_liners_and_facts_stay_out(self):
        for said in ONE_LINERS + NOT_PROCEDURES + ("", "how do I"):
            self.assertIsNone(wr.howto_intent(said), said)

    def test_the_not_procedure_guard_is_the_one_teach_intent_uses(self):
        for said in NOT_PROCEDURES:
            self.assertIsNone(wr.teach_intent("teach me " + said[9:]), said)
            self.assertIsNone(wr.howto_intent(said), said)

    def test_the_prefix_round_trips(self):
        self.assertEqual(wr.split_one_step(wr.ONE_STEP_PREFIX + "crop it"),
                         ("crop it", True))
        self.assertEqual(wr.split_one_step("crop it"), ("crop it", False))


class Routing(unittest.TestCase):
    def test_a_task_question_routes_to_the_planner_on_both_routers(self):
        for router in ("act", "chat"):
            self.assertEqual(
                stage_route.fixed_route("how do I export this as a PDF",
                                        router),
                ("walkthrough", wr.ONE_STEP_PREFIX + "export this as a PDF"),
                router)

    def test_one_liners_keep_their_old_routes(self):
        for said in ONE_LINERS + NOT_PROCEDURES:
            self.assertEqual(stage_route.fixed_route(said, "act"),
                             ("act", None), said)

    def test_auto_false_restores_the_old_routing_for_every_phrase(self):
        for said in TASKS + ONE_LINERS + NOT_PROCEDURES:
            self.assertEqual(
                stage_route.fixed_route(said, "act", teach=False),
                ("act", None), said)
            self.assertEqual(
                stage_route.fixed_route(said, "chat", teach=False),
                ("answer", None), said)

    def test_the_config_switch_reaches_the_route_stage(self):
        for auto, want in (("true", "walkthrough"), ("false", "act")):
            ctx = SimpleNamespace(
                text="how do I export this as a PDF",
                cfg={"brain": {"router": "act"}, "teach": {"auto": auto},
                     "voice": {"enabled": "false"}},
                detail="", state=mock.Mock(), sp=mock.MagicMock(),
                turn="t", token=mock.Mock(), model="never-called",
                harness={"apps": {}}, context="", wait_for_choice=None,
                answers={}, result="", reply="", app="none")
            with mock.patch("wisp.trace.emit"), \
                    mock.patch.object(stage_route, "fast_route",
                                      return_value=None):
                self.assertTrue(pipeline.route_stage(ctx))
            self.assertEqual(ctx.answers["route"]["choice"], want, auto)


class Desk:
    def __init__(self):
        self.said, self.points = [], []
        self.state = mock.Mock()
        self.state.transition.side_effect = \
            lambda status, **kw: self.points.append(kw.get("points"))
        self.slept = 0

    def sleep(self, s):
        self.slept += 1

    def env(self):
        return wr._Env({}, self.state, speak=self.said.append,
                       window=lambda: {"class": "app", "title": "t"},
                       sleep=self.sleep, clock=lambda: 0.0,
                       check=lambda: None)


def reply(*labels):
    return json.dumps({"steps": [{"say": f"Press {l}.", "label": l,
                                  "why": "It does the job."}
                                 for l in labels]})


class Delivery(unittest.TestCase):
    def setUp(self):
        wr.clear_paused()
        self.addCleanup(wr.clear_paused)

    def run_it(self, raw, one_step=True):
        desk = Desk()
        ground = lambda label, cfg: SimpleNamespace(  # noqa: E731
            x=40, y=30, rect=None)
        with mock.patch("wisp.brain.chat",
                        lambda m, c, timeout=0: {"content": raw}), \
                mock.patch("wisp.brain.supports_vision", return_value=False):
            out = wr.run("split this pane", {}, desk.state, env=desk.env(),
                         ground=ground, monitors=[{"width": 1000,
                                                   "height": 1000}],
                         skill_match=lambda c: "", one_step=one_step)
        return desk, out

    def test_a_one_step_plan_is_point_and_say_with_no_wait_loop(self):
        with mock.patch.object(wr, "_do_step") as do_step:
            desk, out = self.run_it(reply("Split pane"))
        do_step.assert_not_called()
        self.assertEqual(desk.said, ["Press Split pane. It does the job."])
        pt = desk.points[-1][0]
        self.assertEqual((pt["x"], pt["y"], pt["label"]),
                         (40, 30, "Split pane"))
        self.assertEqual(desk.slept, 0)
        self.assertEqual(out, "WALKED (1 steps): ")     # nothing more to say
        self.assertIsNone(wr.paused())

    def test_a_longer_plan_runs_as_a_walkthrough(self):
        calls = []

        def fake(w, ev, env, ask, ground, monitors):
            calls.append(ev["step"].label)
            w.mark_step_done()
            return w.issue_step(now=0.0)
        with mock.patch.object(wr, "_do_step", fake), \
                mock.patch.object(wr, "plan", side_effect=[
                    wr.parse_steps(reply("File", "Export")), []]):
            desk = Desk()
            wr.run("export", {}, desk.state, env=desk.env(), one_step=True,
                   skill_match=lambda c: "",
                   ground=lambda label, cfg: SimpleNamespace(
                       x=1, y=1, rect=None))
        self.assertEqual(calls, ["File", "Export"])

    def test_without_the_allowance_one_step_is_a_normal_walkthrough(self):
        with mock.patch.object(wr, "_do_step") as do_step:
            do_step.return_value = {"action": "complete", "spoken": ""}
            self.run_it(reply("Split pane"), one_step=False)
        do_step.assert_called_once()

    def test_a_failed_plan_is_not_a_one_step_answer(self):
        desk, out = self.run_it("no json at all")
        self.assertIn("couldn't work out steps", out)
        self.assertEqual(desk.said, [])


class Wiring(unittest.TestCase):
    def test_execute_hands_the_allowance_to_the_runner(self):
        from wisp import stage_execute
        for detail, want in ((wr.ONE_STEP_PREFIX + "crop it", True),
                             ("crop it", False)):
            with mock.patch.object(wr, "run",
                                   return_value="WALKED (0 steps): x") as run:
                stage_execute.execute({"route": {"choice": "walkthrough"}},
                                      {}, detail=detail, initial_image=None,
                                      interrupted=lambda: False)
            self.assertEqual(run.call_args.args[0], "crop it")
            self.assertEqual(run.call_args.kwargs.get("one_step", False), want)


if __name__ == "__main__":
    unittest.main()
