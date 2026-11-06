"""U5: a walkthrough plans a few steps, recaptures, and plans again.

No test here calls a model: the planner is a recorded reply and the user's
click is a fake that advances a recorded screen.
"""
import json
import pathlib
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from wisp import replan, walkthrough as wt, walkthrough_run as wr  # noqa: E402

CASES = HERE / "fixtures" / "replan"
SNAPSHOT = HERE / "fixtures" / "replan_prompt.txt"
MONS = [{"x": 0, "y": 0, "width": 1000, "height": 1000, "scale": 1}]
_TMP = None


def setUpModule():
    global _TMP
    _TMP = tempfile.TemporaryDirectory()
    wr.PAUSED_FILE = pathlib.Path(_TMP.name) / "walkthrough.json"
    wr.LAST_FILE = pathlib.Path(_TMP.name) / "walkthrough_last.json"


def tearDownModule():
    _TMP.cleanup()


def reply(*steps):
    return json.dumps({"steps": list(steps)})


def st(label, say=None, kind="click"):
    return {"say": say or f"Press {label}.", "label": label, "kind": kind}


class Sim:
    """A recorded desk: screens[i] = (labels on it, planner reply, {label:
    next screen}). The planner answers for the current screen; the user
    'presses' every step Wisp delivers, which moves to the next screen."""

    def __init__(self, screens, cfg=None):
        self.screens, self.cur = screens, 0
        self.cfg = cfg or {}
        self.prompts, self.delivered, self.blind = [], [], 0
        self.said = []
        self.state = mock.Mock()
        self.fail_on = None            # plan call number that raises
        self.during_plan = None        # callable run inside a plan call

    # -- seams -----------------------------------------------------------
    def chat(self, messages, cfg, timeout=0):
        self.prompts.append(messages[0]["content"])
        n = len(self.prompts)
        if self.fail_on == n:
            raise RuntimeError("planner down")
        out = self.screens[self.cur][1]
        if self.during_plan:
            self.during_plan(n)
        return {"content": out}

    def ground(self, label, cfg):
        if label in self.screens[self.cur][0]:
            return SimpleNamespace(x=50, y=50, rect=None)
        return None

    def do_step(self, w, ev, env, ask, ground, monitors):
        step = ev["step"]
        if step.label and step.label not in self.screens[self.cur][0]:
            self.blind += 1
        if step.label in self.delivered:
            self.blind += 1
        self.delivered.append(step.label)
        w.mark_step_done()
        self.cur = self.screens[self.cur][2].get(step.label, self.cur)
        return w.issue_step(now=0.0)

    def env(self, window=None):
        return wr._Env(self.cfg, self.state, speak=self.said.append,
                       window=window or (lambda: {"class": "app",
                                                  "title": f"s{self.cur}"}),
                       sleep=lambda s: None, clock=lambda: 0.0,
                       check=lambda: None)

    def run(self, goal="goal", resume=None, ask=None):
        with mock.patch("wisp.brain.chat", self.chat), \
                mock.patch("wisp.brain.supports_vision", return_value=False), \
                mock.patch.object(wr, "_do_step", self.do_step):
            return wr.run(goal, self.cfg, self.state, env=self.env(),
                          ground=self.ground, monitors=MONS, ask=ask,
                          skill_match=lambda c: "", resume=resume)


def case_screens(path):
    """A recorded case directory as Sim screens."""
    data = json.loads((path / "case.json").read_text())
    rows = [(data["elements"], data["reply"], data["after"])] + [
        (t["elements"], t["reply"], t["after"]) for t in data["then"]]
    return data, [
        ([e["label"] for e in els],
         json.loads((path / rp).read_text())["raw"], after)
        for els, rp, after in rows]


def recorded_cases():
    return sorted(p for p in CASES.iterdir()
                  if (p / "case.json").exists()
                  and "then" in json.loads((p / "case.json").read_text()))


class Recorded(unittest.TestCase):
    def setUp(self):
        wr.clear_paused()
        self.addCleanup(wr.clear_paused)

    def test_there_are_recorded_sequences(self):
        self.assertGreaterEqual(len(recorded_cases()), 3)

    def test_each_sequence_delivers_what_it_expects(self):
        for path in recorded_cases():
            with self.subTest(case=path.name):
                data, screens = case_screens(path)
                sim = Sim(screens)
                out = sim.run(data["goal"])
                self.assertEqual(sim.delivered, data["expected_delivery"])
                self.assertEqual(len(sim.prompts), data["expected_plans"])
                self.assertEqual(sim.blind, 0)
                self.assertIn("all done", out)
                self.assertLessEqual(
                    data["expected_plans"], replan.DEFAULT_TURN_BUDGET - 2)

    def test_planning_once_would_point_at_missing_controls(self):
        """Before/after on the recorded sequences: the old plan-once flow
        delivers every step of the first reply whether or not the screen
        still shows it; the loop never does."""
        before = after = 0
        for path in recorded_cases():
            data, screens = case_screens(path)
            cur, seen = 0, []
            for s in wr.parse_steps(screens[0][1]):
                if s.label not in screens[cur][0] or s.label in seen:
                    before += 1
                seen.append(s.label)
                cur = screens[cur][2].get(s.label, cur)
            sim = Sim(screens)
            sim.run(data["goal"])
            after += sim.blind
        self.assertGreater(before, 0)
        self.assertEqual(after, 0)

    def test_a_recapture_where_the_user_did_the_next_step_skips_it(self):
        _, screens = case_screens(CASES / "settings-night-light")
        sim = Sim(screens)
        sim.run()
        self.assertNotIn("Night light toggle", sim.delivered)
        self.assertIn("Steps the user has finished so far", sim.prompts[1])

    def test_the_same_opener_is_never_pointed_at_twice(self):
        _, screens = case_screens(CASES / "browser-tab-group")
        sim = Sim(screens)
        sim.run()
        self.assertEqual(sim.delivered.count("Tab menu"), 1)
        # the second prompt tells the planner what was already pointed at
        self.assertIn("never point at them again): tab menu.",
                      sim.prompts[1])


class Budget(unittest.TestCase):
    def setUp(self):
        wr.clear_paused()
        self.addCleanup(wr.clear_paused)

    def screens(self):
        return [(["A", "B"], reply(st("A"), st("B")), {"A": 1}),
                (["B", "C"], reply(st("B"), st("C")), {"B": 2}),
                (["C"], reply(), {})]

    def test_the_default_is_small_and_bad_values_fall_back(self):
        self.assertEqual(replan.turn_budget({}), replan.DEFAULT_TURN_BUDGET)
        self.assertEqual(replan.turn_budget({"teach": {"turn_budget": "x"}}),
                         replan.DEFAULT_TURN_BUDGET)
        self.assertEqual(replan.turn_budget({"teach": {"turn_budget": "3"}}), 3)
        self.assertEqual(replan.turn_budget({"teach": {"turn_budget": 99}}),
                         replan.MAX_TURN_BUDGET)
        self.assertEqual(replan.turn_budget({"teach": {"turn_budget": "-2"}}), 0)
        self.assertLessEqual(replan.DEFAULT_TURN_BUDGET, 8)

    def test_running_out_ends_with_a_wrap_up_not_another_step(self):
        sim = Sim([(["A"], reply(st("A")), {"A": 1}),
                   (["Z"], reply(st("Z")), {})],
                  cfg={"teach": {"turn_budget": "1"}})
        out = sim.run("make a thing")
        self.assertEqual(sim.delivered, ["A"])        # no step past the plan
        self.assertEqual(len(sim.prompts), 1)
        self.assertIn("(1 steps)", out)
        self.assertIn("as far as I can take you", out)
        self.assertIn("make a thing", out)
        self.assertIsNone(wr.paused())

    def test_the_last_turn_is_told_so(self):
        sim = Sim(self.screens(), cfg={"teach": {"turn_budget": "2"}})
        sim.run()
        self.assertIn("counting this one: 2.", sim.prompts[0])
        self.assertIn("counting this one: 1.", sim.prompts[1])

    def test_zero_budget_wraps_up_without_planning(self):
        sim = Sim(self.screens(), cfg={"teach": {"turn_budget": "0"}})
        out = sim.run("make a thing")
        self.assertEqual(sim.prompts, [])
        self.assertEqual(sim.delivered, [])
        self.assertIn("WALKED (0 steps)", out)
        self.assertIn("make a thing", out)

    def test_a_walkthrough_cannot_plan_more_than_its_budget(self):
        endless = [(["A"], reply(st(f"S{i}")), {}) for i in range(1)]
        sim = Sim(endless, cfg={"teach": {"turn_budget": "3"}})
        # every plan offers a brand new control the screen does not show
        # steps for, so only the budget ends it
        counter = iter(range(100))

        def chat(messages, cfg, timeout=0):
            sim.prompts.append(messages[0]["content"])
            return {"content": reply(st(f"S{next(counter)}"))}
        sim.chat = chat
        sim.ground = lambda label, cfg: SimpleNamespace(x=1, y=1, rect=None)
        sim.run()
        self.assertEqual(len(sim.prompts), 3)


class Freshness(unittest.TestCase):
    def setUp(self):
        wr.clear_paused()
        self.addCleanup(wr.clear_paused)

    def test_a_user_action_during_planning_sets_the_flag(self):
        sim = Sim([(["A"], reply(st("A")), {"A": 1}),
                   (["B"], reply(st("B")), {"B": 2}),
                   (["B"], reply(), {})])
        # the user switches window while the first plan is in flight
        sim.during_plan = lambda n: setattr(sim, "cur", 1) if n == 1 else None
        sim.run()
        self.assertNotIn("acted while you were still planning",
                         sim.prompts[0])
        self.assertIn("acted while you were still planning", sim.prompts[1])
        self.assertEqual(sim.delivered, ["B"])        # planned from newer screen

    def test_no_user_action_means_no_flag(self):
        sim = Sim([(["A"], reply(st("A")), {"A": 1}), (["A"], reply(), {})])
        sim.run()
        self.assertTrue(all("acted while you were" not in p
                            for p in sim.prompts))

    def test_a_changing_screen_costs_one_extra_plan_not_a_loop(self):
        sim = Sim([(["A"], reply(st("A")), {})])
        ticks = iter(range(100))
        sim.env = lambda window=None, _e=sim.env: _e(
            lambda: {"class": "app", "title": f"t{next(ticks)}"})
        sim.run()
        # each planning cycle retries once from the newer screen: the first
        # plan and the plan after step A, two calls each
        self.assertEqual(len(sim.prompts), 4)


class Failure(unittest.TestCase):
    def setUp(self):
        wr.clear_paused()
        self.addCleanup(wr.clear_paused)

    def screens(self):
        return [(["A"], reply(st("A")), {"A": 1}),
                (["B"], reply(st("B")), {"B": 2}),
                (["B"], reply(), {})]

    def test_a_failed_replan_pauses_and_resumes(self):
        sim = Sim(self.screens())
        sim.fail_on = 2
        out = sim.run("make a thing")
        self.assertIn("Say continue", out)
        data = wr.paused()
        self.assertEqual(data["goal"], "make a thing")
        self.assertEqual(data["steps"][0]["text"], "Press A.")
        self.assertTrue(data["steps"][0]["done"])
        self.assertEqual(data["replan"]["budget"], replan.DEFAULT_TURN_BUDGET - 1)
        # the planner is back: continue picks up and finishes
        sim.fail_on = None
        out = sim.run(resume=wr.paused())
        self.assertEqual(sim.delivered, ["A", "B"])
        self.assertIn("all done", out)
        self.assertIsNone(wr.paused())

    def test_a_reply_with_no_step_list_counts_as_a_failure(self):
        sim = Sim([(["A"], reply(st("A")), {"A": 1}),
                   (["B"], "I could not tell what is on screen", {})])
        out = sim.run()
        self.assertIn("Say continue", out)
        self.assertIsNotNone(wr.paused())

    def test_a_failed_first_plan_says_so(self):
        sim = Sim(self.screens())
        sim.fail_on = 1
        out = sim.run()
        self.assertIn("couldn't work out steps", out)

    def test_a_failed_turn_does_not_spend_budget(self):
        sim = Sim(self.screens())
        sim.fail_on = 2
        sim.run()
        self.assertEqual(wr.paused()["replan"]["budget"],
                         replan.DEFAULT_TURN_BUDGET - 1)


class Prompt(unittest.TestCase):
    ARGS = dict(
        goal="export this as a PDF", max_steps=replan.PLAN_STEPS,
        started=False, skill="Export is under the File menu.",
        completed=["Open the File menu.", "Choose Export as PDF."],
        prev_kind="click", prev_outcome=replan.DONE, budget=3, fresh=True,
        pointed=["file", "export as pdf"])

    def build(self, **kw):
        a = dict(self.ARGS, **kw)
        return wr.build_prompt(a.pop("goal"), a.pop("max_steps"), **a)

    def test_the_prompt_is_deterministic_and_matches_the_snapshot(self):
        text = self.build()
        self.assertEqual(text, self.build())
        self.assertEqual(text, SNAPSHOT.read_text().rstrip("\n"))

    def test_each_input_changes_the_prompt(self):
        base = self.build()
        for kw in ({"completed": ["only one"]}, {"prev_kind": "hover"},
                   {"prev_outcome": replan.SKIPPED}, {"budget": 1},
                   {"fresh": False}, {"pointed": []}, {"skill": ""},
                   {"started": True}):
            with self.subTest(kw=kw):
                self.assertNotEqual(self.build(**kw), base)

    def test_a_whole_task_plan_has_no_lookahead_rules(self):
        text = wr.build_prompt("g", wt.MAX_STEPS)
        self.assertNotIn("never plan past what is visible", text)
        self.assertIn("At most 15 steps", text)

    def test_the_prompt_separates_revealing_from_committing(self):
        text = self.build()
        self.assertIn("only reveals its choices", text)
        self.assertIn("A choice is committed only when", text)


class Persistence(unittest.TestCase):
    def test_the_session_survives_a_pause(self):
        rs = replan.Session(4, ["file"], "click", replan.DONE)
        back = replan.Session.load(rs.dump(), {})
        self.assertEqual(back.dump(), rs.dump())
        self.assertEqual(replan.Session.load(None, {}).budget,
                         replan.DEFAULT_TURN_BUDGET)

    def test_hover_and_click_openers_are_tracked_other_kinds_are_not(self):
        s = replan.Session(3)
        for kind, tracked in (("click", True), ("hover", True),
                              ("area", False), ("voice-confirm", False)):
            self.assertEqual(
                bool(replan.opener_key(wt.Step("x", label="File", kind=kind))),
                tracked)
        s.note_pointed(wt.Step("x", label=" File "))
        self.assertFalse(s.admits(wt.Step("again", label="file"),
                                  wt.Walkthrough("g")))
        self.assertTrue(s.admits(wt.Step("other", label="Save"),
                                 wt.Walkthrough("g")))


class Lessons(unittest.TestCase):
    def test_a_saved_lesson_is_not_replanned(self):
        """Replays go straight to the runner: no planner call, no budget."""
        sim = Sim([(["A"], reply(st("A")), {})])
        with mock.patch("wisp.brain.chat", sim.chat), \
                mock.patch.object(wr, "_do_step", sim.do_step):
            out = wr.run("g", {}, sim.state, env=sim.env(),
                         steps=[wt.Step("one", label="A")])
        self.assertEqual(sim.prompts, [])
        self.assertIn("all done", out)


if __name__ == "__main__":
    unittest.main()
