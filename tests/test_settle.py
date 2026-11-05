"""U4: settle watches frames for change-then-quiet, from synthetic frames."""
import pathlib
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from wisp import settle  # noqa: E402
import frames as fr  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def source(seq):
    it = iter(seq)
    last = [None]

    def frame():
        try:
            last[0] = next(it)
        except StopIteration:
            pass
        return last[0]
    return frame


class Threshold(unittest.TestCase):
    def test_constant_sits_between_a_blink_and_a_dropdown(self):
        blink = settle.frame_diff(fr.BLANK, fr.BLINK)
        menu = settle.frame_diff(fr.BLANK, fr.MENU)
        self.assertLess(blink, settle.SETTLE_DIFF)
        self.assertGreater(menu, settle.SETTLE_DIFF)
        self.assertAlmostEqual(blink, 0.0007, places=4)
        self.assertAlmostEqual(menu, 0.08, places=2)

    def test_mismatched_or_missing_frames_count_as_changed(self):
        self.assertEqual(settle.frame_diff(b"ab", b"abc"), 1.0)
        self.assertEqual(settle.frame_diff(b"", b"abc"), 1.0)


class Wait(unittest.TestCase):
    def run_wait(self, seq, timeout=10.0, **kw):
        c = Clock()
        got = settle.wait_settled(source(seq), timeout, sleep=c.sleep,
                                  clock=c.now, **kw)
        return got, c.t

    def test_change_then_hold_is_settled_only_after_the_hold_window(self):
        seq = [fr.BLANK, fr.BLANK, fr.MENU] + [fr.MENU] * 20
        got, t = self.run_wait(seq)
        self.assertTrue(got)
        # changed at the third poll (0.6 s), then quiet for the full window
        self.assertGreaterEqual(t, 0.6 + settle.SETTLE_WINDOW_S)
        self.assertLess(t, 0.6 + settle.SETTLE_WINDOW_S + 2 * settle.SETTLE_POLL_S)

    def test_continuous_animation_times_out_not_settled(self):
        seq = [fr.BLANK, fr.MENU] * 40
        got, t = self.run_wait(seq, timeout=5.0)
        self.assertFalse(got)
        self.assertGreaterEqual(t, 5.0)

    def test_a_screen_that_never_changes_is_not_settled(self):
        self.assertFalse(self.run_wait([fr.BLANK] * 50, timeout=5.0)[0])

    def test_a_blinking_cursor_alone_is_not_a_change(self):
        self.assertFalse(self.run_wait([fr.BLANK, fr.BLINK] * 30,
                                       timeout=5.0)[0])

    def test_a_dead_frame_source_never_settles(self):
        self.assertFalse(self.run_wait([None] * 50, timeout=3.0)[0])

    def test_check_hook_runs_between_polls(self):
        c = Clock()
        calls = []
        settle.wait_settled(source([fr.BLANK] * 9), 1.0, sleep=c.sleep,
                            clock=c.now, check=lambda: calls.append(1))
        self.assertTrue(calls)


class Grim(unittest.TestCase):
    PPM = b"P6\n2 1\n255\n\x0a\x0a\x0a\xff\xff\xff"

    def test_ppm_becomes_luma_even_when_pixels_look_like_whitespace(self):
        self.assertEqual(settle._gray(self.PPM), b"\x0a\xff")
        self.assertIsNone(settle._gray(b"P6\n2 1\n255\n\x00"))
        self.assertIsNone(settle._gray(b"junk"))

    def test_grim_frame_asks_for_the_active_window_downsampled(self):
        done = subprocess.CompletedProcess([], 0, stdout=self.PPM)
        with mock.patch("subprocess.run", return_value=done) as run:
            got = settle.grim_frame({"at": [10, 20], "size": [300, 200]})
        self.assertEqual(got, b"\x0a\xff")
        cmd = run.call_args[0][0]
        self.assertIn("0.05", cmd)
        self.assertEqual(cmd[cmd.index("-g") + 1], "10,20 300x200")

    def test_grim_missing_or_failing_gives_no_frame(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertIsNone(settle.grim_frame())
        bad = subprocess.CompletedProcess([], 1, stdout=b"")
        with mock.patch("subprocess.run", return_value=bad):
            self.assertIsNone(settle.grim_frame())


if __name__ == "__main__":
    unittest.main()
