"""B11: a multi-step reply shows one plan card and stops on a stale screen."""
import json
import sys
import unittest
from unittest import mock

sys.path.insert(0, ".")
from wisp import act, policy, tools  # noqa: E402

_WRITE_PACK = None


def setUpModule():
    global _WRITE_PACK
    _WRITE_PACK = mock.patch.object(act, "_write_pack")
    _WRITE_PACK.start()


def tearDownModule():
    _WRITE_PACK.stop()


def msg(content=None, calls=None):
    m = {"role": "assistant", "content": content}
    if calls:
        m["tool_calls"] = calls
    return m


def call(name, arg="", i=0):
    return {"id": f"c{i}_{name}", "type": "function",
            "function": {"name": name,
                         "arguments": json.dumps({"arg": arg})}}


FOUR = [("click", "10,10"), ("type_text", "hello"), ("key", "enter"),
        ("scroll", "down")]


def four_calls():
    return [call(n, a, i) for i, (n, a) in enumerate(FOUR)]


class Prompt(unittest.TestCase):
    def test_one_numbered_line_per_step(self):
        text = policy.plan_prompt(FOUR)
        lines = text.splitlines()
        self.assertEqual(lines[0], "run this plan (4 steps)?")
        self.assertEqual(lines[1:], ["1. click 10,10", "2. type_text hello",
                                     "3. key enter", "4. scroll down"])

    def test_the_card_is_bounded_to_twenty_lines(self):
        steps = [("click", f"{i},{i}") for i in range(35)]
        lines = policy.plan_prompt(steps).splitlines()
        self.assertEqual(len(lines), 1 + policy.PREVIEW_LINES + 1)
        self.assertEqual(lines[-1], "…and 15 more")

    def test_only_changing_steps_count(self):
        calls = [("screenshot", ""), ("click", "1,1"), ("screenshot", ""),
                 ("type_text", "x")]
        self.assertEqual(policy.plan_steps(calls, {"agent": {}}),
                         [("click", "1,1"), ("type_text", "x")])


class Preview(unittest.TestCase):
    def test_below_the_minimum_no_card(self):
        asked = []
        steps, refusal = policy.plan_preview(
            FOUR[:2], {"agent": {}}, lambda p: asked.append(p) or True)
        self.assertEqual((steps, refusal, asked), ([], None, []))

    def test_no_confirm_channel_no_card(self):
        self.assertEqual(policy.plan_preview(FOUR, {"agent": {}}, None),
                         ([], None))

    def test_minimum_zero_turns_it_off(self):
        self.assertEqual(
            policy.plan_preview(FOUR, {"agent": {}}, lambda p: True,
                                minimum=0), ([], None))

    def test_a_no_refuses_the_plan(self):
        steps, refusal = policy.plan_preview(FOUR, {"agent": {}},
                                             lambda p: False)
        self.assertEqual(len(steps), 4)
        self.assertEqual(refusal, "SKIPPED (plan declined by user)")

    def test_a_yes_grants_the_steps_for_the_app(self):
        st = mock.Mock()
        st.focus = {"app": "firefox"}
        st.confirmed = set()
        policy.plan_preview(FOUR, {"agent": {}}, lambda p: True, state=st)
        self.assertIn(("type_text", "firefox"), st.confirmed)

    def test_an_always_grant_skips_the_card(self):
        st = mock.Mock()
        st.focus = {"app": "x"}
        st.confirmed = {policy.ALWAYS_GRANT}
        asked = []
        steps, refusal = policy.plan_preview(
            FOUR, {"agent": {}}, lambda p: asked.append(p) or True, state=st)
        self.assertEqual((len(steps), refusal, asked), (4, None, []))


class Loop(unittest.TestCase):
    def run_loop(self, replies, confirm, windows=None, cfg=None, live_window=None):
        ran = []

        def run(name, arg, cfg_, harness=None):
            if name != "screenshot":      # auto re-observe is not input
                ran.append((name, arg))
            return "ok"
        wins = iter(windows or [])
        with mock.patch.object(act, "_post", side_effect=replies), \
                mock.patch.object(tools, "run", side_effect=run), \
                mock.patch("wisp.platform.active_window", return_value=(
                    live_window if live_window is not None else {
                        "class": "org.example.notes",
                        "title": "Synthetic notes"})), \
                mock.patch.object(act, "_focus_class",
                                  side_effect=lambda: next(wins, "term")):
            out = act.run_act_loop("do it", cfg or {"agent": {}},
                                   confirm=confirm)
        return out, ran

    def test_unknown_surface_is_not_authorized_by_the_plan_card(self):
        cards = []
        out, ran = self.run_loop(
            [msg(calls=four_calls()), msg(content="done")],
            lambda p: cards.append(p) or True, live_window={})
        self.assertEqual(len(cards), 4)  # plan + click/type/key consent
        self.assertTrue(cards[0].startswith("run this plan"))
        self.assertTrue(cards[1].startswith("run click"))
        self.assertEqual(ran, FOUR)

    def test_four_steps_make_exactly_one_card_listing_four_lines(self):
        cards = []
        out, ran = self.run_loop(
            [msg(calls=four_calls()), msg(content="all done")],
            lambda p: cards.append(p) or True)
        self.assertEqual(len(cards), 1)
        self.assertEqual(len(cards[0].splitlines()) - 1, 4)
        self.assertEqual(ran, FOUR)
        self.assertTrue(out.startswith("ACTED"), out)

    def test_declined_plan_runs_nothing(self):
        out, ran = self.run_loop([msg(calls=four_calls())], lambda p: False)
        self.assertEqual(out, "SKIPPED (plan declined by user)")
        self.assertEqual(ran, [])

    def test_a_focus_change_between_steps_stops_with_a_reason(self):
        # plan made on "term"; step 1 ok, then focus moves to "browser"
        out, ran = self.run_loop([msg(calls=four_calls())], lambda p: True,
                                 windows=["term", "term", "browser"])
        self.assertTrue(out.startswith("ABORTED (screen changed: focus "
                                       "moved from term to browser before "
                                       "step 2 of 4)"), out)
        self.assertEqual(ran, FOUR[:1])      # zero further input events

    def test_focus_change_while_the_card_was_open_stops_before_step_one(self):
        out, ran = self.run_loop([msg(calls=four_calls())], lambda p: True,
                                 windows=["term", "browser"])
        self.assertIn("before step 1 of 4", out)
        self.assertEqual(ran, [])

    def test_one_and_two_step_turns_are_unchanged(self):
        cards = []
        replies = [msg(calls=[call("click", "1,1"), call("key", "enter", 1)]),
                   msg(content="ok")]
        out, ran = self.run_loop(replies, lambda p: cards.append(p) or True,
                                 windows=["a", "b"])
        self.assertEqual(cards, [])
        self.assertEqual(len(ran), 2)
        self.assertTrue(out.startswith("ACTED"), out)

    def test_the_threshold_is_configurable(self):
        cards = []
        cfg = {"agent": {}, "agents": {"act_preview_min": "2"}}
        replies = [msg(calls=[call("click", "1,1"), call("key", "enter", 1)]),
                   msg(content="ok")]
        self.run_loop(replies, lambda p: cards.append(p) or True, cfg=cfg)
        self.assertEqual(len(cards), 1)


if __name__ == "__main__":
    unittest.main()
