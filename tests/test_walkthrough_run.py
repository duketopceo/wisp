"""Phase 7 / R7: the walkthrough runs end to end and points label-first."""
import json
import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import (stage_execute, stage_route, stage_speak,  # noqa: E402
                  walkthrough as wt, walkthrough_run as wr)


class Intent(unittest.TestCase):
    def test_goal_is_extracted(self):
        for said, goal in (
                ("walk me through setting up a git repo", "setting up a git repo"),
                ("Wisp, guide me through exporting a PDF.", "exporting a PDF"),
                ("teach me how to rebase", "rebase"),
                ("please take me through the settings", "the settings")):
            self.assertEqual(wr.walk_intent(said), goal, said)

    def test_questions_and_commands_are_not_walkthroughs(self):
        for said in ("how do I rebase", "open firefox", "walk me through",
                     "what is a walkthrough", ""):
            self.assertIsNone(wr.walk_intent(said), said)


class Parse(unittest.TestCase):
    def test_fenced_json_with_prose(self):
        raw = ('Sure!\n```json\n{"steps": [{"say": "Open the menu", '
               '"label": "File"}, {"say": "Click Export", "label": ""}]}\n```')
        steps = wr.parse_steps(raw)
        self.assertEqual([s.text for s in steps],
                         ["Open the menu", "Click Export"])
        self.assertEqual(steps[0].label, "File")

    def test_bad_entries_are_dropped_and_count_is_capped(self):
        items = [{"say": f"s{i}"} for i in range(30)] + [{"say": ""}, 5, None]
        steps = wr.parse_steps(json.dumps({"steps": items}))
        self.assertEqual(len(steps), wt.MAX_STEPS)
        self.assertEqual(wr.parse_steps("no json"), [])
        self.assertEqual(wr.parse_steps('{"steps": "x"}'), [])
        self.assertEqual(wr.parse_steps("{bad json}"), [])

    def test_model_coordinates_become_the_fallback_point(self):
        s = wr.parse_steps('{"steps":[{"say":"a","label":"Save","x":10,'
                           '"y":20}]}')[0]
        self.assertEqual(s.point, {"x": 10, "y": 20, "label": "Save"})

    def test_plan_attaches_the_screen_only_for_vision_brains(self):
        seen = {}

        def chat(messages, cfg, timeout=0):
            seen["content"] = messages[0]["content"]
            return {"content": '{"steps":[{"say":"go"}]}'}
        with mock.patch("wisp.brain.supports_vision", return_value=True):
            steps = wr.plan("do it", {}, "abc", chat=chat)
        self.assertEqual(len(steps), 1)
        self.assertIsInstance(seen["content"], list)
        self.assertTrue(seen["content"][1]["image_url"]["url"]
                        .startswith("data:image/png;base64,abc"))
        with mock.patch("wisp.brain.supports_vision", return_value=False):
            wr.plan("do it", {}, "abc", chat=chat)
        self.assertIsInstance(seen["content"], str)


MONS = [{"x": 0, "y": 0, "width": 1000, "height": 1000, "scale": 1}]


def target(x, y, rect=None):
    return SimpleNamespace(x=x, y=y, rect=rect)


class Snap(unittest.TestCase):
    def test_labelled_element_wins_over_model_coordinates(self):
        calls = []

        def ground(label, cfg):
            calls.append((label, cfg["ground"]["providers"]))
            return target(300, 400, (290, 390, 20, 20))
        step = wt.Step("Click Save", point={"x": 1, "y": 2}, label="Save")
        pt = wr.snap_point(step, {}, ground=ground, monitors=MONS)
        self.assertEqual(pt, {"x": 300, "y": 400, "label": "Save"})
        self.assertEqual(calls, [("Save", "control,a11y")])

    def test_container_is_skipped_for_the_model_point(self):
        ground = lambda label, cfg: target(500, 500, (0, 0, 900, 900))
        step = wt.Step("Click Save", point={"x": 11, "y": 22}, label="Save")
        pt = wr.snap_point(step, {}, ground=ground, monitors=MONS)
        self.assertEqual((pt["x"], pt["y"]), (11, 22))

    def test_refusal_falls_back_to_model_point_then_nothing(self):
        def refuse(label, cfg):
            raise RuntimeError("not_found")
        with_pt = wt.Step("x", point={"x": 5, "y": 6}, label="Save")
        self.assertEqual(wr.snap_point(with_pt, {}, ground=refuse,
                                       monitors=MONS)["x"], 5)
        bare = wt.Step("x", label="Save")
        self.assertIsNone(wr.snap_point(bare, {}, ground=refuse,
                                        monitors=MONS))

    def test_no_label_never_grounds(self):
        ground = mock.Mock()
        step = wt.Step("look here", point={"x": 7, "y": 8})
        self.assertEqual(wr.snap_point(step, {}, ground=ground)["x"], 7)
        ground.assert_not_called()


class Script:
    """A scripted desktop: windows[i] is what the user's screen shows
    on the i-th poll; time advances `dt` per poll."""

    def __init__(self, windows, dt=1.0):
        self.windows, self.dt, self.t, self.i = windows, dt, 0.0, 0
        self.said = []
        self.published = []
        self.state = mock.Mock()
        self.state.transition.side_effect = \
            lambda status, **kw: self.published.append((status, kw))

    def window(self):
        w = self.windows[min(self.i, len(self.windows) - 1)]
        return dict(w)

    def sleep(self, s):
        self.i += 1
        self.t += self.dt

    def env(self, interrupted=None):
        return wr._Env({}, self.state, speak=self.said.append,
                       window=self.window, sleep=self.sleep,
                       clock=lambda: self.t, check=lambda: None,
                       interrupted=interrupted)


def W(title, cls="app"):
    return {"class": cls, "title": title}


def steps(*texts):
    return [wt.Step(t) for t in texts]


class RunTests(unittest.TestCase):
    def run_it(self, sc, texts, ask=None, **kw):
        return wr.run("goal", {}, sc.state, ask=ask, steps=steps(*texts),
                      env=sc.env(kw.pop("interrupted", None)), **kw)

    def test_three_step_lesson_advances_on_window_change(self):
        sc = Script([W("a"), W("a"), W("b"), W("b"), W("c"), W("c"), W("d")])
        out = self.run_it(sc, ["one", "two", "three"])
        self.assertEqual(sc.said, ["one", "two", "three"])   # no repeats
        self.assertTrue(out.startswith("WALKED (3 steps)"), out)
        self.assertEqual(sc.state.method_calls and
                         sc.published[0][0], "speaking")
        self.assertEqual(sc.published[0][1]["answer"], "one")

    def test_step_beacon_is_published_with_the_text(self):
        sc = Script([W("a"), W("b")])
        step = wt.Step("Click Save", point={"x": 4, "y": 5}, label="")
        wr.run("g", {}, sc.state, steps=[step], env=sc.env())
        self.assertEqual(sc.published[0][1]["points"][0]["x"], 4)

    def test_loading_page_waits_then_continues(self):
        sc = Script([W("home"), W("Loading..."), W("Loading..."),
                     W("ready"), W("ready")])
        out = self.run_it(sc, ["open it", "next"])
        self.assertEqual(sc.said, ["open it", "next"])
        self.assertIn("WALKED", out)

    def test_stuck_prompt_done_marks_step_and_moves_on(self):
        sc = Script([W("same")], dt=7.0)
        asked = []

        def ask(q, options):
            asked.append((q, options))
            return "done"
        out = self.run_it(sc, ["one", "two"], ask=ask)
        self.assertEqual(sc.said[:2], ["one", "two"])
        self.assertEqual(asked[0], ("Done, or stuck?", ["done", "stuck"]))
        self.assertTrue(out.startswith("WALKED (2 steps)"), out)

    def test_stuck_means_skip_that_step_not_repeat_it(self):
        sc = Script([W("same")], dt=7.0)
        picks = iter(["stuck", "done"])
        out = self.run_it(sc, ["one", "two"], ask=lambda q, o: next(picks))
        self.assertEqual(sc.said, ["one", "two"])
        self.assertTrue(out.startswith("WALKED (1 steps)"), out)

    def test_no_answer_to_the_stuck_prompt_stops_the_lesson(self):
        sc = Script([W("same")], dt=7.0)
        out = self.run_it(sc, ["one", "two"], ask=lambda q, o: None)
        self.assertEqual(sc.said, ["one"])
        self.assertIn("stopping here", out)
        out = self.run_it(Script([W("same")], dt=7.0), ["one"], ask=None)
        self.assertIn("stopping here", out)

    def test_stops_at_the_step_limit(self):
        windows = [W(f"w{i}") for i in range(60)]
        sc = Script(windows)
        out = self.run_it(sc, [f"s{i}" for i in range(wt.MAX_STEPS + 3)])
        self.assertEqual(len(sc.said), wt.MAX_STEPS)
        self.assertIn("step limit", out)

    def test_interrupt_cancels_and_clears(self):
        sc = Script([W("same")])
        flag = {"on": False}

        def interrupted():
            return flag["on"]
        orig = sc.sleep

        def sleep(s):
            orig(s)
            flag["on"] = True
        sc.sleep = sleep
        out = self.run_it(sc, ["one", "two"], interrupted=interrupted)
        self.assertEqual(sc.said, ["one"])
        self.assertIn("stopped", out)
        self.assertTrue(any(s == "idle" for s, _ in sc.published))

    def test_unplannable_goal_says_so(self):
        sc = Script([W("a")])
        with mock.patch.object(wr, "plan", return_value=[]):
            out = wr.run("g", {}, sc.state, env=sc.env())
        self.assertIn("couldn't work out steps", out)
        self.assertEqual(sc.said, [])

    def test_a_walkthrough_never_sends_input(self):
        sc = Script([W("a"), W("b")])
        with mock.patch("wisp.tools.run") as tools_run, \
                mock.patch("wisp.cua_safety.Guard") as guard:
            self.run_it(sc, ["one"])
        tools_run.assert_not_called()
        guard.assert_not_called()


class Wiring(unittest.TestCase):
    def test_spoken_request_routes_to_walkthrough(self):
        self.assertEqual(
            stage_route.fixed_route("walk me through exporting a PDF", "act"),
            ("walkthrough", "exporting a PDF"))
        self.assertEqual(
            stage_route.fixed_route("walk me through exporting a PDF",
                                    "chat"),
            ("walkthrough", "exporting a PDF"))
        self.assertEqual(stage_route.fixed_route("open firefox", "act"),
                         ("act", None))

    def test_router_off_still_clarifies(self):
        self.assertEqual(
            stage_route.fixed_route("walk me through x", "off"),
            ("clarify", None))

    def test_execute_dispatches_the_walkthrough_route(self):
        answers = {"route": {"choice": "walkthrough"}}
        with mock.patch.object(wr, "run",
                               return_value="WALKED (1 steps): all done.") \
                as run:
            out = stage_execute.execute(answers, {}, detail="exporting",
                                        initial_image="img",
                                        interrupted=lambda: False)
        self.assertEqual(out, "WALKED (1 steps): all done.")
        self.assertEqual(run.call_args.args[0], "exporting")
        self.assertEqual(run.call_args.kwargs["image_b64"], "img")

    def test_the_closing_line_is_spoken(self):
        self.assertEqual(
            stage_speak._spoken_payload("WALKED (3 steps): all done."),
            "all done.")
        self.assertEqual(
            stage_speak._spoken_payload("ACTED (1 steps): ok"), "ok")


class DemonstrateMode(unittest.TestCase):
    def test_intent(self):
        self.assertEqual(wr.demo_intent("demonstrate how to export a PDF"),
                         "export a PDF")
        self.assertEqual(wr.demo_intent("Wisp, demo me the share dialog."),
                         "the share dialog")
        self.assertIsNone(wr.demo_intent("walk me through x"))
        self.assertIsNone(wr.demo_intent("demonstrate"))
        self.assertEqual(wr.split_mode("demonstrate: x y"), ("x y", True))
        self.assertEqual(wr.split_mode("x y"), ("x y", False))

    def test_routes_with_the_mode_in_the_detail(self):
        self.assertEqual(
            stage_route.fixed_route("demonstrate how to export", "act"),
            ("walkthrough", "demonstrate: export"))

    def test_execute_passes_the_mode(self):
        with mock.patch.object(wr, "run", return_value="WALKED (0 steps): x") \
                as run:
            stage_execute.execute({"route": {"choice": "walkthrough"}}, {},
                                  detail="demonstrate: export",
                                  initial_image=None,
                                  interrupted=lambda: False)
        self.assertEqual(run.call_args.args[0], "export")
        self.assertTrue(run.call_args.kwargs["demonstrate"])

    def test_every_step_is_spoken_and_pointed_without_waiting(self):
        sc = Script([W("a")])           # the screen never changes
        asked, polled = [], []
        env = sc.env()
        env._window = lambda: polled.append(1) or W("a")
        out = wr.run("g", {}, sc.state, steps=steps("one", "two", "three"),
                     env=env, demonstrate=True,
                     ask=lambda *a: asked.append(a))
        self.assertEqual(sc.said, ["one", "two", "three"])
        self.assertEqual(len(sc.published), 3)
        self.assertEqual(asked, [])
        self.assertEqual(polled, [])        # no watching for a click
        self.assertEqual(sc.i, 0)           # and no waiting
        self.assertTrue(out.startswith("WALKED (3 steps)"), out)

    def test_zero_input_events(self):
        sc = Script([W("a")])
        with mock.patch("wisp.tools.run") as tools_run, \
                mock.patch("wisp.cua_safety.Guard") as guard:
            wr.run("g", {}, sc.state, steps=steps("one"), env=sc.env(),
                   demonstrate=True)
        tools_run.assert_not_called()
        guard.assert_not_called()

    def test_interrupt_stops_a_demonstration(self):
        sc = Script([W("a")])
        out = wr.run("g", {}, sc.state, steps=steps("one", "two"),
                     env=sc.env(interrupted=lambda: True), demonstrate=True)
        self.assertIn("stopped", out)


class SkillPriming(unittest.TestCase):
    def prompt_for(self, window, skill_match):
        seen = {}

        def chat(messages, cfg, timeout=0):
            seen["p"] = messages[0]["content"]
            return {"content": '{"steps":[{"say":"go"}]}'}
        sc = Script([window])
        with mock.patch("wisp.brain.chat", chat), \
                mock.patch("wisp.brain.supports_vision", return_value=False):
            wr.run("g", {}, sc.state, env=sc.env(), skill_match=skill_match,
                   demonstrate=True)
        return seen["p"]

    def test_a_matching_skill_is_in_the_prompt(self):
        p = self.prompt_for(W("t", "1password"),
                            lambda cls: "Quick Access is Ctrl+Shift+Space")
        self.assertIn("Quick Access is Ctrl+Shift+Space", p)

    def test_no_skill_means_no_notes(self):
        p = self.prompt_for(W("t", "foot"), lambda cls: "")
        self.assertNotIn("Notes about the app", p)

    def test_no_window_class_never_asks_for_a_skill(self):
        def boom(cls):
            raise AssertionError("looked up")
        self.assertEqual(wr.app_skill({}, boom), "")
        self.assertEqual(wr.app_skill({"class": ""}, boom), "")

    def test_a_failing_matcher_does_not_stop_the_lesson(self):
        def boom(cls):
            raise OSError("disk")
        self.assertEqual(wr.app_skill({"class": "x"}, boom), "")

    def test_the_seeded_skill_is_found_for_its_app(self):
        from wisp import skills
        body = wr.app_skill({"class": "1password"}, skills.match_app_skill)
        self.assertIn("Quick Access", body)
        self.assertEqual(
            wr.app_skill({"class": "no-such-app"}, skills.match_app_skill),
            "")


if __name__ == "__main__":
    unittest.main()
