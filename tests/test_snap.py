"""U7: the model proposes a point, the accessibility tree disposes.

Every case runs on a recorded-tree fixture (tests/fixtures/trees, drawn by
make_trees.py) behind FakeElementTree: no AT-SPI, no compositor."""
import json
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from fakes.elementtree import FakeElementTree  # noqa: E402
from wisp import elementtree as et  # noqa: E402
from wisp import walkthrough as wt, walkthrough_run as wr  # noqa: E402

TREES = pathlib.Path(__file__).resolve().parent / "fixtures" / "trees"
MONS = [{"width": 1920, "height": 1080, "scale": 1}]


def tree(name):
    return FakeElementTree.from_file(TREES / f"{name}.json")


def snap(step, name, ground=None):
    return wr.snap_point(step, {}, ground=ground or (lambda *_: None),
                         monitors=MONS, tree=tree(name))


class AxLayer(unittest.TestCase):
    def test_point_near_a_labelled_button_snaps_to_its_center(self):
        step = wt.Step("Click Save", point={"x": 720, "y": 650}, label="Save")
        pt = snap(step, "settings_dialog")
        self.assertEqual((pt["x"], pt["y"]), (740, 656))   # Save's center
        self.assertEqual((pt["snap"], pt["via"]), ("ax", "label"))
        self.assertEqual(pt["ax_status"], "ok")
        self.assertEqual(pt["app"], "fixture-settings")
        self.assertEqual(pt["confidence"], 1.0)

    def test_point_in_a_large_container_keeps_the_model_box(self):
        step = wt.Step("Click Zoom", point={"x": 400, "y": 300}, label="Zoom")
        pt = snap(step, "patchy")
        self.assertEqual((pt["x"], pt["y"]), (400, 300))
        self.assertEqual(pt["snap"], "model")
        self.assertEqual(pt["ax_status"], "ok")      # tree was consulted

    def test_container_role_is_never_a_target_even_when_small(self):
        step = wt.Step("x", point={"x": 5000, "y": 5000}, label="Content")
        # "Content" is a panel in settings_dialog: matched by label, refused
        pt = snap(step, "settings_dialog")
        self.assertEqual(pt["snap"], "model")

    def test_two_matches_pick_the_one_nearest_the_model_point(self):
        near_second = wt.Step("Run it", point={"x": 640, "y": 520},
                              label="Run")
        near_first = wt.Step("Run it", point={"x": 40, "y": 30}, label="Run")
        self.assertEqual(snap(near_second, "two_windows")["x"], 630)
        self.assertEqual(snap(near_first, "two_windows")["x"], 50)

    def test_label_in_an_unfocused_window_is_not_snapped_to(self):
        # "Apply" exists only in the second window of the same app; the
        # model point sits on the focused window's second Run button
        step = wt.Step("Apply", point={"x": 640, "y": 520}, label="Apply")
        pt = snap(step, "two_windows")
        self.assertEqual((pt["snap"], pt["via"]), ("ax", "contains"))
        self.assertEqual(pt["label"], "Run")         # the control it holds
        # and with no control under the point it keeps the model box
        away = wt.Step("Apply", point={"x": 450, "y": 350}, label="Apply")
        self.assertEqual(snap(away, "two_windows")["snap"], "model")

    def test_label_under_another_window_falls_through(self):
        step = wt.Step("Export", point={"x": 600, "y": 300}, label="Export")
        pt = snap(step, "occluded")
        self.assertEqual((pt["snap"], pt["x"], pt["y"]), ("model", 600, 300))
        clear = wt.Step("Open", point={"x": 600, "y": 300}, label="Open")
        self.assertEqual(snap(clear, "occluded")["snap"], "ax")

    def test_unlabelled_step_snaps_to_the_control_holding_the_point(self):
        step = wt.Step("this toggle", point={"x": 310, "y": 310})
        pt = snap(step, "settings_dialog")
        self.assertEqual((pt["snap"], pt["via"], pt["label"]),
                         ("ax", "contains", "Dark mode"))

    def test_ground_providers_still_resolve_when_the_tree_cannot(self):
        ground = lambda label, cfg: mock.Mock(x=9, y=8, rect=(0, 0, 10, 10),
                                              confidence=0.9)
        step = wt.Step("Save", point={"x": 1, "y": 2}, label="Save")
        pt = snap(step, "unavailable", ground=ground)
        self.assertEqual((pt["x"], pt["y"], pt["via"]), (9, 8, "ground"))


class Unreachable(unittest.TestCase):
    def test_unavailable_returns_the_model_box_and_logs_none(self):
        step = wt.Step("Save", point={"x": 33, "y": 44}, label="Save")
        pt = snap(step, "unavailable")
        self.assertEqual((pt["x"], pt["y"]), (33, 44))
        self.assertEqual(pt["snap"], "none")
        self.assertEqual(pt["ax_status"], "unavailable")
        self.assertIn("gi/Atspi", pt["ax_reason"])

    def test_unbound_is_reported_apart_from_no_match(self):
        step = wt.Step("Save", point={"x": 33, "y": 44}, label="Save")
        unbound = snap(step, "unbound")
        nomatch = snap(wt.Step("Zoom", point={"x": 33, "y": 44},
                               label="Zoom"), "patchy")
        self.assertEqual((unbound["snap"], unbound["ax_status"]),
                         ("none", "unbound"))
        self.assertEqual((nomatch["snap"], nomatch["ax_status"]),
                         ("model", "ok"))

    def test_a_tree_that_raises_is_a_quiet_fall(self):
        class Boom(et.ElementTree):
            def state(self):
                raise RuntimeError("bus gone")
        step = wt.Step("x", point={"x": 1, "y": 2}, label="Save")
        pt = wr.snap_point(step, {}, ground=lambda *_: None,
                           monitors=MONS, tree=Boom())
        self.assertEqual((pt["x"], pt["snap"]), (1, "none"))
        self.assertEqual(pt["ax_status"], "unavailable")

    def test_default_tree_without_a_compositor_is_unavailable(self):
        t = et.default_tree()           # hermetic env: no Hyprland
        self.assertEqual(t.state()[0], et.UNAVAILABLE)

    def test_no_point_and_no_match_points_nowhere(self):
        self.assertIsNone(snap(wt.Step("Zoom", label="Zoom"), "patchy"))


class Record(unittest.TestCase):
    def test_trace_gets_a_snap_event_for_every_step(self):
        events = []
        with mock.patch("wisp.trace.emit",
                        lambda *a, **k: events.append(a)):
            snap(wt.Step("Save", point={"x": 720, "y": 650}, label="Save"),
                 "settings_dialog")
            snap(wt.Step("Zoom", label="Zoom"), "unavailable")   # no point
        self.assertEqual([e[1] for e in events], ["snap", "snap"])
        first, second = events[0][3], events[1][3]
        self.assertEqual((first["snap"], first["pointed"]), ("ax", True))
        self.assertEqual((second["snap"], second["pointed"],
                          second["ax_status"]), ("none", False,
                                                 "unavailable"))

    def test_published_point_and_step_dump_carry_snap(self):
        published = []
        state = mock.Mock()
        state.transition.side_effect = \
            lambda status, **kw: published.append(kw)
        step = wt.Step("Click Save", point={"x": 720, "y": 650},
                       label="Save")
        t = [0.0]
        env = wr._Env({}, state, speak=lambda _t: None,
                      window=lambda: {"class": "a", "title": "t"},
                      sleep=lambda s: t.__setitem__(0, t[0] + s),
                      clock=lambda: t[0], check=lambda: None,
                      tree=tree("settings_dialog"))
        wr.run("g", {}, state, steps=[step], env=env, monitors=MONS,
               demonstrate=True)
        pt = published[0]["points"][0]
        self.assertEqual((pt["snap"], pt["x"], pt["y"]), ("ax", 740, 656))
        self.assertEqual(env.snaps[step.key]["snap"], "ax")
        dump = wr._dump(wt.Walkthrough("g", [step]), [step], None, env.snaps)
        self.assertEqual(dump["steps"][0]["snap"]["via"], "label")
        json.dumps(dump)


if __name__ == "__main__":
    unittest.main()
