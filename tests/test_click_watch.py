"""U4: click and hover observation from a pointer source and frames."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from wisp import click_watch as cw  # noqa: E402
import frames as fr  # noqa: E402

TARGET, RADIUS = (100, 100), 30


class Desk:
    """A scripted pointer and screen. `tick` advances per sleep."""

    def __init__(self, pointer, screen):
        self.pointer, self.screen = pointer, screen
        self.t = 0.0
        self.tick = 0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s
        self.tick += 1

    def cursor(self):
        return self.pointer(self.tick)

    def frame(self):
        return self.screen(self.tick)


def at(pos):
    return lambda tick: pos


def reacts_at(n):
    return lambda tick: fr.BLANK if tick < n else fr.MENU


def wait(desk, timeout=5.0):
    return cw.wait_click(TARGET, RADIUS, timeout, cursor=desk.cursor,
                         frame=desk.frame, sleep=desk.sleep, clock=desk.now)


class Click(unittest.TestCase):
    def test_a_reaction_with_the_pointer_in_the_radius_is_clicked_in(self):
        self.assertEqual(wait(Desk(at((110, 95)), reacts_at(8))),
                         "clicked-in")

    def test_a_reaction_elsewhere_after_travelling_is_clicked_out(self):
        pointer = lambda tick: (100, 100) if tick < 3 else (600, 400)
        self.assertEqual(wait(Desk(pointer, reacts_at(10))), "clicked-out")

    def test_a_page_animating_under_a_parked_far_pointer_is_not_a_click(self):
        self.assertEqual(wait(Desk(at((600, 400)), reacts_at(8))), "none")

    def test_a_pointer_in_the_radius_but_no_reaction_is_none(self):
        self.assertEqual(wait(Desk(at((100, 100)), reacts_at(10 ** 6))),
                         "none")

    def test_screen_change_while_the_pointer_is_moving_is_not_a_click(self):
        pointer = lambda tick: (100 + tick, 100)        # never rests
        self.assertEqual(wait(Desk(pointer, reacts_at(4))), "none")

    def test_the_radius_edge_counts_as_inside(self):
        self.assertEqual(wait(Desk(at((130, 100)), reacts_at(8))),
                         "clicked-in")
        self.assertEqual(wait(Desk(lambda t: (100, 100) if t < 3 else (131, 100),
                                   reacts_at(10))), "clicked-out")

    def test_no_pointer_source_or_frames_means_none(self):
        self.assertEqual(wait(Desk(at(None), reacts_at(2)), timeout=2.0),
                         "none")
        self.assertEqual(wait(Desk(at((100, 100)), lambda t: None),
                              timeout=2.0), "none")

    def test_poll_interval_and_rest_are_named(self):
        self.assertGreater(cw.CLICK_POLL_S, 0)
        self.assertGreaterEqual(cw.CLICK_REST_S, cw.CLICK_POLL_S)


class Hover(unittest.TestCase):
    def run_hover(self, pointer):
        desk = Desk(pointer, None)
        watch = cw.HoverWatch(TARGET, RADIUS, desk.cursor)
        while desk.t < 5.0:
            if watch.poll(desk.now()):
                return desk.t
            desk.sleep(watch.poll_s)
        return None

    def test_rest_inside_the_radius_advances_after_the_interval(self):
        t = self.run_hover(at((105, 100)))
        self.assertGreaterEqual(t, cw.HOVER_REST_S)
        self.assertLess(t, cw.HOVER_REST_S + 2 * cw.CLICK_POLL_S)

    def test_a_pointer_that_keeps_moving_never_rests(self):
        self.assertIsNone(self.run_hover(lambda tick: (90 + tick % 5, 100)))

    def test_resting_outside_the_radius_does_not_advance(self):
        self.assertIsNone(self.run_hover(at((400, 400))))

    def test_leaving_resets_the_rest_timer(self):
        pointer = lambda tick: (400, 400) if 3 <= tick < 6 else (100, 100)
        t = self.run_hover(pointer)
        self.assertGreaterEqual(t, 0.6 + cw.HOVER_REST_S)


class Cursor(unittest.TestCase):
    def test_hypr_cursor_reads_the_socket_and_fails_to_none(self):
        from unittest import mock
        with mock.patch("wisp.hypr.query", return_value={"x": 3, "y": 4}):
            self.assertEqual(cw.hypr_cursor(), (3, 4))
        with mock.patch("wisp.hypr.query", side_effect=RuntimeError("down")):
            self.assertIsNone(cw.hypr_cursor())


if __name__ == "__main__":
    unittest.main()
