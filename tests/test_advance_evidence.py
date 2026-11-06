"""U4: a walkthrough step advances only on evidence for its kind."""
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from wisp import walkthrough as wt, walkthrough_run as wr  # noqa: E402
import frames as fr  # noqa: E402

_TMP = None


def setUpModule():
    global _TMP
    _TMP = tempfile.TemporaryDirectory()
    wr.PAUSED_FILE = pathlib.Path(_TMP.name) / "walkthrough.json"
    wr.LAST_FILE = pathlib.Path(_TMP.name) / "walkthrough_last.json"


def tearDownModule():
    _TMP.cleanup()


class Desk:
    """Scripted pointer, screen and window; one tick per sleep."""

    def __init__(self, pointer=None, screen=None, title="Page", dt=0.1):
        self.pointer, self.screen, self.title = pointer, screen, title
        self.dt, self.t, self.tick = dt, 0.0, 0
        self.said, self.points = [], []
        self.state = mock.Mock()
        self.state.transition.side_effect = \
            lambda status, **kw: self.points.append(kw.get("points"))

    def env(self, pointer=True, frames=True):
        return wr._Env(
            {}, self.state, speak=self.said.append,
            window=lambda: {"class": "browser", "title": self.title},
            sleep=self.sleep, clock=lambda: self.t, check=lambda: None,
            cursor=(lambda: self.pointer(self.tick)) if pointer else None,
            frame=(lambda: self.screen(self.tick)) if frames else None)

    def sleep(self, s):
        self.t += s
        self.tick += 1


def at(pos):
    return lambda tick: pos


def reacts(after):
    """Blank until `after`, a menu from then on."""
    return lambda tick: fr.BLANK if tick < after else fr.MENU


def step(text, kind="click", x=100, y=100, **kw):
    return wt.Step(text, point={"x": x, "y": y, "label": ""}, kind=kind, **kw)


def run(desk, steps, **env_kw):
    return wr.run("goal", {}, desk.state, steps=steps, ask=lambda *a: None,
                  env=desk.env(**env_kw))


class Click(unittest.TestCase):
    def setUp(self):
        wr.clear_paused()
        self.addCleanup(wr.clear_paused)

    def test_a_click_inside_the_radius_advances_to_the_next_step(self):
        desk = Desk(at((105, 102)), reacts(10), title="Never changes")
        out = run(desk, [step("Click Share"), step("Click Copy link",
                                                   kind="voice-confirm")])
        self.assertEqual(desk.said, ["Click Share", "Click Copy link"])
        self.assertIn("WALKED (1 steps)", out)
        self.assertIn("continue", out)       # the voice-confirm step waits

    def test_the_title_changing_is_not_a_click(self):
        desk = Desk(at((600, 400)), lambda t: fr.BLANK)

        class Title:
            def __call__(inner):
                return {"class": "b", "title": f"t{desk.tick}"}
        env = desk.env()
        env.window = Title()
        out = wr.run("g", {}, desk.state, steps=[step("Click Share")],
                     env=env, ask=lambda *a: None)
        self.assertEqual(desk.said, ["Click Share"])
        self.assertIn("stopping here", out)      # stuck prompt, no answer

    def test_a_click_outside_says_nothing_and_pauses_resumably(self):
        pointer = lambda tick: (100, 100) if tick < 3 else (700, 500)
        desk = Desk(pointer, reacts(12))
        out = run(desk, [step("Click Share"), step("Next")])
        self.assertEqual(desk.said, ["Click Share"])     # no extra speech
        self.assertEqual(out, "WALKED (0 steps): ")
        saved = wr.paused()
        self.assertEqual(saved["goal"], "goal")
        self.assertEqual(saved["current"], "Click Share")
        self.assertEqual([s["text"] for s in saved["steps"]],
                         ["Click Share", "Next"])
        self.assertEqual(len(desk.points), 1)            # pointer left parked

    def test_off_target_pause_resumes_with_continue(self):
        pointer = lambda tick: (100, 100) if tick < 3 else (700, 500)
        run(Desk(pointer, reacts(12)), [step("Click Share"), step("Next")])
        desk = Desk(at((100, 100)), reacts(10 ** 6))
        wr.run("goal", {}, desk.state, resume=wr.paused(), ask=lambda *a: None,
               env=desk.env())
        self.assertEqual(desk.said[1:], ["Next"])    # the done step is not repeated

    def test_no_pointer_source_delivers_the_click_as_voice_confirm(self):
        desk = Desk(None, None)
        out = run(desk, [step("Click Share"), step("Next")], pointer=False,
                  frames=False)
        self.assertEqual(desk.said, ["Click Share"])
        self.assertIn("Say continue", out)
        self.assertEqual(wr.paused()["current"], "Click Share")

    def test_a_pointer_without_frames_is_still_voice_confirm(self):
        desk = Desk(at((100, 100)), None)
        out = run(desk, [step("Click Share")], frames=False)
        self.assertIn("Say continue", out)

    def test_a_planned_radius_is_used(self):
        desk = Desk(at((160, 100)), reacts(10))
        out = run(desk, [step("Click Share", radius=80)])
        self.assertIn("all done", out)               # 60 px away, radius 80

    def test_the_default_radius_rejects_a_far_click(self):
        pointer = lambda tick: (100, 100) if tick < 3 else (160, 100)
        out = run(Desk(pointer, reacts(12)), [step("Click Share")])
        self.assertEqual(out, "WALKED (0 steps): ")  # 60 px > default 30


class Hover(unittest.TestCase):
    def setUp(self):
        wr.clear_paused()
        self.addCleanup(wr.clear_paused)

    def test_a_hover_advances_after_the_pointer_rests(self):
        desk = Desk(at((102, 100)))
        out = run(desk, [step("Hover Share", kind="hover")], frames=False)
        self.assertIn("all done", out)
        self.assertGreaterEqual(desk.t, wr.click_watch.HOVER_REST_S)

    def test_a_hover_without_a_pointer_source_is_voice_confirm(self):
        out = run(Desk(None, None), [step("Hover Share", kind="hover")],
                  pointer=False, frames=False)
        self.assertIn("Say continue", out)


class Settle(unittest.TestCase):
    def setUp(self):
        wr.clear_paused()
        self.addCleanup(wr.clear_paused)

    def test_an_area_step_in_a_web_app_advances_on_settle(self):
        desk = Desk(at((0, 0)), reacts(4), title="Never changes")
        out = run(desk, [step("Look at the toolbar", kind="area"),
                         step("Grab the corner", kind="handle")], )
        self.assertEqual(desk.said[0], "Look at the toolbar")
        self.assertGreaterEqual(desk.t, 0.4 + wr.settle.SETTLE_WINDOW_S)

    def test_a_screen_still_animating_does_not_advance(self):
        desk = Desk(at((0, 0)), lambda t: fr.BLANK if t % 2 else fr.MENU)
        out = run(desk, [step("Drag it", kind="motion")])
        self.assertEqual(desk.said, ["Drag it"])
        self.assertIn("stopping here", out)          # 20 s stuck prompt

    def test_area_without_a_frame_source_is_voice_confirm(self):
        out = run(Desk(at((0, 0)), None), [step("Look", kind="area")],
                  frames=False)
        self.assertIn("Say continue", out)

    def test_settle_kinds_need_no_target_point(self):
        desk = Desk(at((0, 0)), reacts(4))
        out = run(desk, [wt.Step("Watch the panel", kind="area")])
        self.assertIn("all done", out)


class VoiceConfirm(unittest.TestCase):
    def test_a_voice_confirm_step_waits_for_continue(self):
        wr.clear_paused()
        self.addCleanup(wr.clear_paused)
        desk = Desk(at((0, 0)), reacts(2))
        out = run(desk, [wt.Step("Type the name", kind="voice-confirm"),
                         wt.Step("Save", kind="voice-confirm")])
        self.assertEqual(desk.said, ["Type the name"])
        self.assertIn("Say continue", out)
        self.assertEqual(wr.paused()["current"], "Type the name")


if __name__ == "__main__":
    unittest.main()
