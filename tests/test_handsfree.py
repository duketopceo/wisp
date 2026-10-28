"""B33: hands-free by double-tap is off by default and leaves hold-to-talk
exactly as it was."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import handsfree  # noqa: E402


def feed(t, events):
    """events: (phase, time). Returns the phases the daemon would see."""
    return [t.decide(p, at) for p, at in events]


class Taps(unittest.TestCase):
    def test_default_config_is_off_and_changes_nothing(self):
        for cfg in ({}, {"handsfree": {}}, {"handsfree": {"enabled": "false"}}):
            self.assertFalse(handsfree.enabled(cfg))
            for ph in ("start", "stop", ""):
                self.assertIsNone(handsfree.intercept(cfg, ph, 1.0))

    def test_hold_to_talk_is_untouched_with_it_on(self):
        t = handsfree.Tracker()
        self.assertEqual(feed(t, [("start", 0.0), ("stop", 2.0)]),
                         ["start", "stop"])
        # a second hold later is a hold, not a double tap
        self.assertEqual(feed(t, [("start", 9.0), ("stop", 11.0)]),
                         ["start", "stop"])
        self.assertFalse(t.latched)

    def test_double_tap_latches_and_the_next_tap_stops(self):
        t = handsfree.Tracker()
        got = feed(t, [("start", 0.0), ("stop", 0.1),     # tap one
                       ("start", 0.3), ("stop", 0.4),     # tap two
                       ("start", 5.0), ("stop", 5.1)])    # tap to finish
        self.assertEqual(got, ["start", "stop", "start", None, "stop", None])
        self.assertFalse(t.latched)

    def test_latched_between_taps_two_and_three(self):
        t = handsfree.Tracker()
        feed(t, [("start", 0.0), ("stop", 0.1), ("start", 0.3), ("stop", 0.4)])
        self.assertTrue(t.latched)

    def test_slow_second_tap_is_just_another_tap(self):
        t = handsfree.Tracker()
        got = feed(t, [("start", 0.0), ("stop", 0.1), ("start", 2.0),
                       ("stop", 2.1)])
        self.assertEqual(got, ["start", "stop", "start", "stop"])
        self.assertFalse(t.latched)

    def test_the_release_that_ends_a_session_does_not_start_another(self):
        t = handsfree.Tracker()
        feed(t, [("start", 0.0), ("stop", 0.1), ("start", 0.3), ("stop", 0.4),
                 ("start", 5.0), ("stop", 5.1)])
        # a quick press right after must not look like the second half of a
        # double tap
        self.assertEqual(feed(t, [("start", 5.2), ("stop", 5.3)]),
                         ["start", "stop"])
        self.assertFalse(t.latched)

    def test_interrupt_ends_a_latched_session(self):
        handsfree._TRACKER.reset()
        cfg = {"handsfree": {"enabled": "true"}}
        for ph, at in (("start", 0.0), ("stop", 0.1), ("start", 0.3),
                       ("stop", 0.4)):
            handsfree.intercept(cfg, ph, at)
        self.assertTrue(handsfree.latched())
        handsfree.interrupted()
        self.assertFalse(handsfree.latched())

    def test_a_latched_mic_closes_itself(self):
        t = handsfree.Tracker()
        feed(t, [("start", 0.0), ("stop", 0.1), ("start", 0.3), ("stop", 0.4)])
        late = 0.4 + handsfree.MAX_LATCH_S + 1
        self.assertEqual(t.decide("start", late), "start")
        self.assertFalse(t.latched)

    def test_intercept_swallow_is_the_empty_string(self):
        handsfree._TRACKER.reset()
        cfg = {"handsfree": {"enabled": "true"}}
        out = [handsfree.intercept(cfg, p, a) for p, a in
               (("start", 0.0), ("stop", 0.1), ("start", 0.3), ("stop", 0.4))]
        self.assertEqual(out, ["start", "stop", "start", ""])
        handsfree._TRACKER.reset()


if __name__ == "__main__":
    unittest.main()
