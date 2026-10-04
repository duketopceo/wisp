"""W4: fast trigger and speculative context.

Press publishes `listening` within the P1 budget; release publishes
`transcribing` within P2 without the fixed 300 ms sleep; screenshot and
window map are gathered speculatively at press, concurrently, and thrown
away on cancel, phantom release or after 5 s. Everything is faked: no
recorder, no screen, no network."""
import importlib.machinery
import importlib.util
import pathlib
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import context, pipeline, state as state_mod  # noqa: E402


def load_wispd():
    loader = importlib.machinery.SourceFileLoader("wispd_ft", str(ROOT / "wispd"))
    spec = importlib.util.spec_from_loader("wispd_ft", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class FakeSampler(threading.Thread):
    """Level sampler that exits as soon as its stop event is set."""

    def __init__(self, stop):
        super().__init__(daemon=True)
        self.stop_ev = stop
        self.start()

    def run(self):
        self.stop_ev.wait(5)


def fake_rec(tmp, held=2.0, with_audio=True):
    wav = pathlib.Path(tmp) / "u.wav"
    if with_audio:
        wav.write_bytes(b"\0" * 400)
    stop = threading.Event()
    proc = mock.Mock()
    proc.poll.return_value = 0  # already exited: nothing to signal
    return {"proc": proc, "out": wav, "sampler_stop": stop,
            "sampler": FakeSampler(stop), "t0": time.monotonic() - held}


class TestRecordFinishIsEventDriven(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_record_stop_returns_without_a_fixed_sleep(self):
        rec = fake_rec(self.tmp)
        slept = []
        real_sleep = time.sleep
        with mock.patch.object(pipeline.time, "sleep",
                               side_effect=lambda s: slept.append(s)
                               or real_sleep(s)):
            t = time.monotonic()
            wav = pipeline.record_stop(rec, mock.Mock())
            took = time.monotonic() - t
        self.assertEqual(wav, rec["out"])
        self.assertLess(took, 0.1, f"record_stop took {took * 1000:.0f} ms")
        self.assertEqual([s for s in slept if s >= 0.1], [])

    def test_level_zeroed_after_sampler_exits(self):
        rec = fake_rec(self.tmp)
        order = []
        state = mock.Mock()
        state.set_level.side_effect = lambda v: order.append(
            ("level", v, rec["sampler"].is_alive()))
        pipeline.record_stop(rec, state)
        self.assertEqual(order, [("level", 0.0, False)])

    def test_no_audio_raises_fast(self):
        rec = fake_rec(self.tmp, with_audio=False)
        t = time.monotonic()
        with self.assertRaises(RuntimeError):
            pipeline.record_stop(rec, mock.Mock())
        self.assertLess(time.monotonic() - t, 0.1)

    def test_stuck_sampler_is_bounded(self):
        rec = fake_rec(self.tmp)
        rec["sampler"] = mock.Mock()  # join() returns, thread never dies
        rec["sampler"].is_alive.return_value = True
        t = time.monotonic()
        pipeline.record_stop(rec, mock.Mock())
        self.assertLess(time.monotonic() - t, 0.5)


class TestSpeculative(unittest.TestCase):
    def test_gatherers_run_concurrently(self):
        gate = threading.Barrier(2, timeout=2)

        def a():
            gate.wait()  # only passes if b is running at the same time
            return "A"

        def b():
            gate.wait()
            return "B"
        sp = context.Speculative({"a": a, "b": b}).start()
        self.assertEqual(sp.take("a", wait=2), "A")
        self.assertEqual(sp.take("b", wait=2), "B")

    def test_start_returns_immediately(self):
        release = threading.Event()
        sp = context.Speculative({"slow": lambda: release.wait(5)})
        t = time.monotonic()
        sp.start()
        self.assertLess(time.monotonic() - t, 0.025)
        release.set()
        sp.cancel()

    def test_cancel_discards_finished_and_late_results(self):
        release = threading.Event()
        sp = context.Speculative({"done": lambda: "x",
                                  "late": lambda: release.wait(2) and "y"})
        sp.start()
        self.assertEqual(sp.take("done", wait=1), "x")  # consumed once
        self.assertIsNone(sp.take("done"))
        sp = context.Speculative({"done": lambda: "x",
                                  "late": lambda: release.wait(2) and "y"})
        sp.start()
        time.sleep(0.05)
        sp.cancel()
        release.set()
        time.sleep(0.05)
        self.assertIsNone(sp.take("done"))
        self.assertIsNone(sp.take("late"))

    def test_stale_after_five_seconds_is_discarded(self):
        now = [100.0]
        sp = context.Speculative({"shot": lambda: "png"},
                                 clock=lambda: now[0]).start()
        self.assertEqual(sp.take("shot", wait=1, consume=False), "png")
        now[0] += 5.1
        self.assertIsNone(sp.take("shot"))

    def test_fresh_within_five_seconds(self):
        now = [100.0]
        sp = context.Speculative({"shot": lambda: "png"},
                                 clock=lambda: now[0]).start()
        sp.take("shot", wait=1, consume=False)
        now[0] += 4.9
        self.assertEqual(sp.take("shot"), "png")

    def test_gatherer_error_is_a_miss_not_a_crash(self):
        def boom():
            raise OSError("no screen")
        sp = context.Speculative({"shot": boom}).start()
        self.assertIsNone(sp.take("shot", wait=1))

    def test_take_wait_is_bounded(self):
        release = threading.Event()
        sp = context.Speculative({"slow": lambda: release.wait(5)}).start()
        t = time.monotonic()
        self.assertIsNone(sp.take("slow", wait=0.05))
        self.assertLess(time.monotonic() - t, 0.2)
        release.set()


class TestPipelineConsumesSpeculation(unittest.TestCase):
    CFG = {"agent": {"screenshots": "true"}}

    def test_speculative_shot_skips_the_recapture(self):
        sp = context.Speculative({"screenshot": lambda: "B64"}).start()
        with mock.patch.object(pipeline, "capture_screen") as cap:
            self.assertEqual(pipeline.turn_screenshot(self.CFG, sp), "B64")
        cap.assert_not_called()

    def test_miss_falls_back_to_a_capture(self):
        sp = context.Speculative({"screenshot": lambda: None}).start()
        png = pathlib.Path(tempfile.mkdtemp()) / "s.png"
        png.write_bytes(b"png")
        with mock.patch.object(pipeline, "capture_screen",
                               return_value=png) as cap:
            out = pipeline.turn_screenshot(self.CFG, sp)
        cap.assert_called_once()
        self.assertTrue(out)
        self.assertFalse(png.exists())

    def test_screenshots_off_never_gathers(self):
        sp = mock.Mock()
        with mock.patch.object(pipeline, "capture_screen") as cap:
            self.assertIsNone(pipeline.turn_screenshot(
                {"agent": {"screenshots": "false"}}, sp))
        cap.assert_not_called()
        sp.take.assert_not_called()

    def test_speculative_context_respects_screenshots_off(self):
        sp = pipeline.speculative_context({"agent": {"screenshots": "false"}})
        self.assertNotIn("screenshot", sp.names)
        self.assertIn("windows", sp.names)


class TestDaemonTrigger(unittest.TestCase):
    def setUp(self):
        self.w = load_wispd()
        self.tmp = tempfile.mkdtemp()
        self.bus = state_mod.StateBus(
            state_file=pathlib.Path(self.tmp) / "state.json")
        self.addCleanup(self.bus.close)
        self.ctl = {"stop": threading.Event(), "busy": threading.Event(),
                    "interrupt": threading.Event(),
                    "choice_event": threading.Event(), "choice_pick": "",
                    "rec": None, "rec_lock": threading.Lock()}
        self.cfg = {}
        self.handle = self.w._handler(self.bus, self.cfg, self.ctl)
        self.spec_gate = threading.Event()
        self.addCleanup(self.spec_gate.set)
        self.spec = context.Speculative(
            {"screenshot": lambda: self.spec_gate.wait(5) and "shot"})
        self.patches = [
            mock.patch.object(self.w.pipeline, "speculative_context",
                              return_value=self.spec),
            mock.patch.object(self.w.speech, "stop"),
            mock.patch.object(self.w, "_rec_watchdog"),
            mock.patch.object(self.w, "dlog"),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def press(self, rec=None):
        rec = rec or fake_rec(self.tmp)
        rec["t0"] = time.monotonic()
        with mock.patch.object(self.w.pipeline, "record_start",
                               return_value=rec):
            return self.handle({"cmd": "listen", "phase": "start"}), rec

    def test_press_publishes_listening_within_p1_with_slow_context(self):
        slow = threading.Event()
        self.addCleanup(slow.set)

        def slow_start(*a, **k):
            slow.wait(2)
            return fake_rec(self.tmp)
        t = time.monotonic()
        with mock.patch.object(self.w.pipeline, "record_start",
                               side_effect=slow_start):
            th = threading.Thread(target=self.handle, args=(
                {"cmd": "listen", "phase": "start"},), daemon=True)
            th.start()
            deadline = time.monotonic() + 1
            while (self.bus.snapshot()["status"] != "listening"
                   and time.monotonic() < deadline):
                time.sleep(0.001)
            took = time.monotonic() - t
            self.assertEqual(self.bus.snapshot()["status"], "listening")
            self.assertLess(took, 0.025, f"P1 {took * 1000:.1f} ms")
            slow.set()
            th.join(2)

    def test_press_starts_speculation_without_blocking(self):
        t = time.monotonic()
        r, _ = self.press()
        self.assertTrue(r["ok"])
        self.assertLess(time.monotonic() - t, 0.1)
        self.assertIs(self.ctl["spec"], self.spec)

    def test_double_press_keeps_one_speculation(self):
        self.press()
        first = self.ctl["spec"]
        with mock.patch.object(self.w.pipeline,
                               "speculative_context") as again:
            r = self.handle({"cmd": "listen", "phase": "start"})
        self.assertEqual(r, {"ok": True, "recording": True})
        again.assert_not_called()
        self.assertIs(self.ctl["spec"], first)

    def test_release_publishes_transcribing_before_the_recorder_settles(self):
        _, rec = self.press()
        seen = {}
        gate = threading.Event()

        def slow_stop(rec_, state=None):
            seen["status_at_stop"] = self.bus.snapshot()["status"]
            gate.wait(2)
            return rec_["out"]
        rec["t0"] = time.monotonic() - 2
        with mock.patch.object(self.w.pipeline, "record_stop",
                               side_effect=slow_stop), \
             mock.patch.object(self.w, "_run_listen",
                               lambda *a, **k: self.ctl["busy"].clear()):
            gate.set()
            t = time.monotonic()
            r = self.handle({"cmd": "listen", "phase": "stop"})
            took = time.monotonic() - t
        self.assertTrue(r["ok"])
        self.assertEqual(seen["status_at_stop"], "transcribing")
        self.assertLess(took, 0.1)

    def test_release_with_no_audio_errors_and_drops_speculation(self):
        _, rec = self.press()
        rec["t0"] = time.monotonic() - 2
        with mock.patch.object(self.w.pipeline, "record_stop",
                               side_effect=RuntimeError("no audio")):
            r = self.handle({"cmd": "listen", "phase": "stop"})
        self.assertFalse(r["ok"])
        self.assertEqual(self.bus.snapshot()["status"], "error")
        self.assertNotIn("spec", self.ctl)
        self.assertTrue(self.spec.cancelled)

    def test_phantom_release_drops_speculation(self):
        self.press()  # t0 = now: held < 0.4 s
        r = self.handle({"cmd": "listen", "phase": "stop"})
        self.assertTrue(r.get("ignored"))
        self.assertNotIn("spec", self.ctl)
        self.assertTrue(self.spec.cancelled)

    def test_release_hands_speculation_to_the_turn(self):
        _, rec = self.press()
        rec["t0"] = time.monotonic() - 2
        got = {}

        def fake_run(st, cfg, ctl, wav=None, spans=None, turn_id=None):
            got["spec"] = ctl.get("spec")
            ctl["busy"].clear()
        with mock.patch.object(self.w.pipeline, "record_stop",
                               return_value=rec["out"]), \
             mock.patch.object(self.w, "_run_listen", fake_run):
            self.handle({"cmd": "listen", "phase": "stop"})
            for _ in range(100):
                if got:
                    break
                time.sleep(0.01)
        self.assertIs(got["spec"], self.spec)
        self.assertFalse(self.spec.cancelled)

    def test_interrupt_discards_speculation(self):
        self.press()
        self.assertTrue(self.handle({"cmd": "interrupt"})["ok"])
        self.assertTrue(self.spec.cancelled)
        self.assertNotIn("spec", self.ctl)


if __name__ == "__main__":
    unittest.main()
