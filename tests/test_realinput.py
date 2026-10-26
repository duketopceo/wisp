#!/usr/bin/env python3
"""Real-input yield watch — wisp/realinput.py. Pipe fds stand in for
/dev/input devices: a closed pipe is a dead fd (unplugged device), a
written pipe is real input. No evdev, no root, no sleeps beyond
bounded polls.
"""
import os
import pathlib
import sys
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import cancel, realinput  # noqa: E402


def _pipe():
    """(watch fd, write end) — the read end plays the evdev device."""
    return os.pipe()


def _wait_for(fn, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if fn():
            return True
        time.sleep(0.01)
    return False


class EvdevWatch(unittest.TestCase):
    def setUp(self):
        self._opened = []

    def tearDown(self):
        for fd in self._opened:
            try:
                os.close(fd)
            except OSError:
                pass

    def _watch(self, devices):
        for _r, w in devices:
            self._opened.append(w)
        w = realinput.Watch(devices=[r for r, _w in devices])
        self.addCleanup(w.close)
        return w

    def test_real_input_yields_once_armed(self):
        w = self._watch([_pipe()])
        self.assertEqual(w.start(), "evdev")
        w.arm()
        os.write(self._opened[0], b"\0" * 24)
        self.assertTrue(_wait_for(w.yielded))
        self.assertRaises(cancel.Cancelled, w.check)

    def test_input_before_arm_never_yields(self):
        # the backlog drain in begin() must eat input buffered while
        # the run wasn't driving — a stale event can't yield a fresh run
        w = self._watch([_pipe()])
        w.start()
        os.write(self._opened[0], b"\0" * 24)
        time.sleep(0.1)                    # let the reader see it
        w.begin()                          # disarm + drain + clear
        w.arm()
        self.assertFalse(w.yielded())

    def test_dead_fd_is_removed_not_spun_on(self):
        # a closed pipe reports readable forever (EOF) — the reader must
        # unregister and close it; with no live fds left the watch goes
        # off instead of hot-looping select
        w = self._watch([_pipe()])
        w.start()
        os.close(self._opened.pop(0))      # writer gone → read EOFs
        self.assertTrue(_wait_for(lambda: w.mode == "off"))
        self.assertEqual(w._fds, [])
        # mode flips before the thread returns (sel.close() runs in its
        # finally): synchronize on exit, don't race it
        w._thread.join(timeout=2)
        self.assertFalse(w._thread.is_alive())

    def test_one_dead_fd_leaves_the_rest_watching(self):
        pipes = [_pipe(), _pipe()]
        w = self._watch(pipes)
        w.start()
        os.close(self._opened[0])          # first device dies
        self._opened.pop(0)
        self.assertTrue(_wait_for(lambda: len(w._fds) == 1))
        self.assertEqual(w.mode, "evdev")  # still sensing
        w.arm()
        os.write(self._opened[0], b"\0" * 24)
        self.assertTrue(_wait_for(w.yielded))

    def test_the_reader_survives_a_yield(self):
        # the yield flag must not kill the sensor thread — a second run
        # on the same Watch still detects takeover
        w = self._watch([_pipe()])
        w.start()
        w.arm()
        os.write(self._opened[0], b"\0" * 24)
        self.assertTrue(_wait_for(w.yielded))
        self.assertTrue(w._thread.is_alive())
        # next run: begin() drains + disarms; input yields again
        w.begin()
        w.arm()
        self.assertFalse(w.yielded())
        os.write(self._opened[0], b"\0" * 24)
        self.assertTrue(_wait_for(w.yielded))
        self.assertTrue(w._thread.is_alive())


class DriftWatch(unittest.TestCase):
    """Cursor-drift sensing — no evdev needed; cursor_pos injected."""

    def test_drift_past_the_threshold_yields_and_the_loop_survives(self):
        pos = {"p": (100, 100)}
        w = realinput.Watch(devices=[], cursor_pos=lambda: pos["p"],
                            poll_s=0.02)
        self.addCleanup(w.close)
        self.assertEqual(w.start(), "drift")
        w.expect(100, 100)
        pos["p"] = (100 + w._drift_px + 5, 100)
        self.assertTrue(_wait_for(w.yielded))
        # the thread kept polling — a second run re-arms and re-yields
        self.assertTrue(w._thread.is_alive())
        w.begin()
        w.expect(500, 500)
        pos["p"] = (500 + w._drift_px + 5, 500)
        self.assertTrue(_wait_for(w.yielded))

    def test_commanded_motion_does_not_yield(self):
        pos = {"p": (100, 100)}
        w = realinput.Watch(devices=[], cursor_pos=lambda: pos["p"],
                            poll_s=0.02)
        self.addCleanup(w.close)
        w.start()
        w.expect(100, 100)
        pos["p"] = (105, 104)              # within DRIFT_PX
        time.sleep(0.15)
        self.assertFalse(w.yielded())
        # the drive's own move: expect() rebases, no yield
        w.expect(200, 200)
        pos["p"] = (200, 200)
        time.sleep(0.15)
        self.assertFalse(w.yielded())


class BeginGuards(unittest.TestCase):
    def test_begin_without_drive_never_creates_a_watch(self):
        realinput._stop_for_test()
        self.addCleanup(realinput._stop_for_test)
        # no pointer drive config → begin() is "off" and no Watch exists
        self.assertEqual(realinput.begin({"agent": {}}), "off")
        self.assertIsNone(realinput._WATCH)


if __name__ == "__main__":
    unittest.main()
