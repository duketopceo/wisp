"""U2: step kinds, the tolerant fallback, the planner contract, and the
round trip through pause, save and replay dumps."""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import step_kinds as sk, walkthrough as wt  # noqa: E402
from wisp import walkthrough_run as wr  # noqa: E402


def one(**fields):
    raw = json.dumps({"steps": [{"say": "do it", "label": "Save", **fields}]})
    return wr.parse_steps(raw)[0]


class Parse(unittest.TestCase):
    def setUp(self):
        sk._reset_warned()

    def test_each_of_the_six_kinds_parses_to_itself(self):
        for kind in sk.KINDS:
            self.assertEqual(one(kind=kind).kind, kind)

    def test_the_table_covers_every_kind(self):
        self.assertEqual(set(sk.TABLE), set(sk.KINDS))
        self.assertEqual(sk.TABLE[sk.VOICE_CONFIRM][1], "continue")

    def test_unknown_kind_falls_back_to_voice_confirm_and_logs_once(self):
        with self.assertLogs("wisp.step_kinds", level="WARNING") as cm:
            a = one(kind="teleport")
            b = one(kind="teleport")
        self.assertEqual((a.kind, b.kind), ("voice-confirm",) * 2)
        self.assertEqual(len(cm.output), 1)

    def test_a_non_string_kind_never_raises(self):
        for bad in (7, [], {"a": 1}, True):
            self.assertEqual(one(kind=bad).kind, "voice-confirm")

    def test_missing_kind_is_a_click_with_no_radius(self):
        s = one()
        self.assertEqual((s.kind, s.radius), ("click", None))

    def test_spelling_variants_are_accepted(self):
        self.assertEqual(one(kind="Voice_Confirm").kind, "voice-confirm")
        self.assertEqual(one(kind=" HOVER ").kind, "hover")

    def test_radius_is_kept_when_sane_and_dropped_otherwise(self):
        self.assertEqual(one(radius=45).radius, 45)
        for bad in (0, -5, 5000, "big", None, True):
            self.assertIsNone(one(radius=bad).radius)

    def test_default_radius_applies_to_clicks_only(self):
        self.assertEqual(sk.effective_radius("click", None),
                         sk.DEFAULT_CLICK_RADIUS)
        self.assertEqual(sk.effective_radius("click", 50), 50)
        self.assertIsNone(sk.effective_radius("area", None))


class TextEntry(unittest.TestCase):
    def test_a_typing_step_planned_as_click_becomes_voice_confirm(self):
        for label in ("Search box", "Address bar", "Password field"):
            s = one(kind="click", label=label)
            self.assertEqual(s.kind, "voice-confirm", label)

    def test_a_type_verb_is_enough(self):
        raw = '{"steps":[{"say":"Type your name","kind":"click"}]}'
        self.assertEqual(wr.parse_steps(raw)[0].kind, "voice-confirm")

    def test_a_plain_button_stays_a_click(self):
        self.assertEqual(one(kind="click", label="Save").kind, "click")

    def test_other_kinds_are_left_alone(self):
        self.assertEqual(one(kind="hover", label="Search box").kind, "hover")


class Prompt(unittest.TestCase):
    def test_the_planner_prompt_states_the_rule_and_every_kind(self):
        seen = {}

        def chat(messages, cfg, timeout=0):
            seen["c"] = messages[0]["content"]
            return {"content": '{"steps":[]}'}
        wr.plan("export a pdf", {}, None, chat=chat)
        for kind in sk.KINDS:
            self.assertIn(kind, seen["c"])
        self.assertIn("visibly react", seen["c"])
        self.assertIn("say continue", seen["c"])


class RoundTrip(unittest.TestCase):
    def steps(self):
        return [wt.Step(text="a", label="Save", why="keeps it", kind="hover",
                        radius=40),
                wt.Step(text="b", kind="voice-confirm"),
                wt.Step(text="c")]

    def check(self, got):
        self.assertEqual([(s.kind, s.radius, s.why) for s in got],
                         [("hover", 40, "keeps it"),
                          ("voice-confirm", None, ""),
                          ("click", None, "")])

    def test_save_then_replay_dump_preserves_kind_radius_and_why(self):
        planned = self.steps()
        w = wt.Walkthrough("g", planned)
        self.check(wr.steps_from(wr._dump(w, planned, None)))

    def test_paused_dump_restores_kind_radius_and_why(self):
        planned = self.steps()
        w = wt.Walkthrough("g", planned)
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "p.json"
            wr.save_paused(w, planned, planned[0], path=path)
            data = wr.paused(path=path)
        _, restored = wr._restore(data)
        self.check(restored)

    def test_a_dump_from_before_kinds_reads_back_as_clicks(self):
        got = wr.steps_from({"steps": [{"text": "old", "why": "w"}]})
        self.assertEqual((got[0].kind, got[0].radius), ("click", None))

    def test_a_corrupt_saved_kind_degrades_instead_of_raising(self):
        got = wr.steps_from({"steps": [{"text": "x", "kind": 9,
                                        "radius": "wide"}]})
        self.assertEqual((got[0].kind, got[0].radius),
                         ("voice-confirm", None))


if __name__ == "__main__":
    unittest.main()
