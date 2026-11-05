"""U10: the state bus carries the teaching step (kind, radius, index, total,
wait reason) so the overlay can draw it. No network, no model, no desktop."""
import json
import pathlib
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from wisp import state as state_mod  # noqa: E402
from wisp import walkthrough as wt, walkthrough_run as wr  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "states"
TEACH_KEYS = {"kind", "radius", "index", "total", "wait"}


class TeachFields(unittest.TestCase):
    def test_a_step_without_kind_or_radius_is_a_click(self):
        # works on master, before U2 adds Step.kind and Step.radius
        t = wr.teach_fields(SimpleNamespace(text="x"), 1, 3)
        self.assertEqual(t, {"kind": "click", "radius": None, "index": 1,
                             "total": 3, "wait": "click"})

    def test_each_kind_names_what_it_waits_for(self):
        want = {"click": "click", "hover": "rest", "area": "settle",
                "handle": "settle", "motion": "settle",
                "voice-confirm": "voice"}
        for kind, wait in want.items():
            t = wr.teach_fields(SimpleNamespace(kind=kind, radius=30), 2, 5)
            self.assertEqual((t["kind"], t["wait"], t["radius"]),
                             (kind, wait, 30))

    def test_unknown_kind_falls_back_to_voice_confirm(self):
        t = wr.teach_fields(SimpleNamespace(kind="teleport"), 1, 1)
        self.assertEqual((t["kind"], t["wait"]), ("voice-confirm", "voice"))

    def test_bad_radius_is_none_and_total_never_trails_index(self):
        for bad in (0, -4, "9", True, None):
            t = wr.teach_fields(SimpleNamespace(radius=bad), 4, 2)
            self.assertIsNone(t["radius"], bad)
            self.assertEqual((t["index"], t["total"]), (4, 4))

    def test_an_explicit_wait_reason_wins(self):
        t = wr.teach_fields(SimpleNamespace(kind="click"), 2, 5,
                            wait="off-target")
        self.assertEqual(t["wait"], "off-target")


class Published(unittest.TestCase):
    def test_each_step_publishes_its_kind_index_and_total(self):
        published = []
        st = mock.Mock()
        st.transition.side_effect = \
            lambda status, **kw: published.append((status, kw))
        windows = iter([{"title": "a"}, {"title": "b"}] * 10)
        last = [{"title": "a"}]

        def window():
            last[0] = next(windows)
            return dict(last[0])
        t = [0.0]

        def sleep(_):
            t[0] += 1.0
        env = wr._Env({}, st, speak=lambda s: None, window=window,
                      sleep=sleep, clock=lambda: t[0], check=lambda: None)
        planned = [wt.Step("one"), wt.Step("two"), wt.Step("three")]
        wr.run("g", {}, st, steps=planned, env=env)
        teach = [kw["teach"] for s, kw in published if "teach" in kw]
        self.assertEqual([x["index"] for x in teach[:3]], [1, 2, 3])
        self.assertEqual({x["total"] for x in teach[:3]}, {3})
        self.assertTrue(all(set(x) == TEACH_KEYS for x in teach))


class StateBus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = pathlib.Path(self.tmp.name) / "state.json"
        self.state = state_mod.State(self.path)
        self.teach = {"kind": "area", "radius": 90, "index": 2, "total": 5,
                      "wait": "settle"}

    def disk(self):
        return json.loads(self.path.read_text())

    def test_teach_is_written_while_speaking(self):
        self.state.transition("speaking", teach=self.teach)
        self.assertEqual(self.disk()["teach"], self.teach)

    def test_teach_is_null_by_default(self):
        self.assertIsNone(self.disk()["teach"])

    def test_leaving_speaking_clears_it(self):
        self.state.transition("speaking", teach=self.teach)
        self.state.transition("done")
        self.assertIsNone(self.disk()["teach"])

    def test_an_end_state_may_carry_the_wait_reason(self):
        ended = dict(self.teach, wait="off-target")
        self.state.transition("done", teach=ended)
        self.assertEqual(self.disk()["teach"]["wait"], "off-target")

    def test_a_late_status_less_write_cannot_resurrect_it(self):
        self.state.apply({"teach": self.teach})
        self.assertIsNone(self.state.snapshot()["teach"])


class GoldenFixtures(unittest.TestCase):
    def load(self, name):
        return json.loads((FIXTURES / f"{name}.json").read_text())

    def test_every_teach_fixture_has_a_well_formed_teach_object(self):
        names = sorted(p.stem for p in FIXTURES.glob("teach_*.json"))
        self.assertEqual(names, ["teach_done", "teach_off_target",
                                 "teach_voice_confirm", "teach_waiting"])
        for name in names:
            t = self.load(name)["teach"]
            self.assertEqual(set(t), TEACH_KEYS, name)
            self.assertIn(t["kind"], wr.STEP_KINDS, name)
            self.assertLessEqual(t["index"], t["total"], name)

    def test_waiting_points_at_its_target(self):
        d = self.load("teach_waiting")
        self.assertEqual(d["status"], "speaking")
        self.assertEqual(d["teach"]["wait"], "click")
        self.assertEqual(len(d["points"]), 1)

    def test_voice_confirm_has_no_mark_to_draw(self):
        d = self.load("teach_voice_confirm")
        self.assertEqual(d["teach"]["kind"], "voice-confirm")
        self.assertEqual(d["teach"]["wait"], "voice")
        self.assertEqual(d["points"], [])

    def test_off_target_and_done_end_quietly(self):
        for name, wait in (("teach_off_target", "off-target"),
                           ("teach_done", "done")):
            d = self.load(name)
            self.assertEqual(d["status"], "done", name)
            self.assertEqual(d["teach"]["wait"], wait, name)
            self.assertEqual(d["points"], [], name)
            self.assertEqual(d["answer"], "", name)


if __name__ == "__main__":
    unittest.main()
