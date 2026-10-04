"""Background writer (W30): bounded, drop-oldest, flushed, never blocks."""
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, ".")
from wisp import act, bgwriter, pipeline  # noqa: E402


class Writer(unittest.TestCase):
    def setUp(self):
        bgwriter.reopen()
        bgwriter.flush(2)
        self._s0 = bgwriter.stats()
        bgwriter.configure({})

    def tearDown(self):
        bgwriter.configure({})

    def _delta(self, key):
        return bgwriter.stats()[key] - self._s0[key]

    def test_runs_jobs_in_order_off_the_caller_thread(self):
        seen = []
        for i in range(5):
            bgwriter.submit(lambda i=i: seen.append(
                (i, threading.current_thread().name)))
        self.assertTrue(bgwriter.flush(2))
        self.assertEqual([i for i, _ in seen], [0, 1, 2, 3, 4])
        self.assertEqual({n for _, n in seen}, {"wisp-bgwriter"})

    def test_submit_never_blocks_on_a_stuck_job(self):
        gate = threading.Event()
        bgwriter.submit(gate.wait)          # occupies the writer
        t0 = time.monotonic()
        for _ in range(50):
            bgwriter.submit(lambda: None)
        self.assertLess(time.monotonic() - t0, 0.5)
        gate.set()
        self.assertTrue(bgwriter.flush(2))

    def test_overflow_drops_oldest_and_counts(self):
        bgwriter.configure({"agents": {"writer_queue_max": "3"}})
        gate, ran = threading.Event(), []
        bgwriter.submit(gate.wait)
        time.sleep(0.05)                    # writer now holds the gate job
        for i in range(7):
            bgwriter.submit(ran.append, i)
        self.assertEqual(self._delta("dropped"), 4)
        gate.set()
        self.assertTrue(bgwriter.flush(2))
        self.assertEqual(ran, [4, 5, 6])    # the newest three survive

    def test_failing_job_is_counted_not_raised(self):
        bgwriter.submit(lambda: 1 / 0)
        self.assertTrue(bgwriter.flush(2))
        self.assertEqual(self._delta("failed"), 1)

    def test_flush_times_out_when_stuck(self):
        gate = threading.Event()
        bgwriter.submit(gate.wait)
        self.assertFalse(bgwriter.flush(0.05))
        gate.set()
        self.assertTrue(bgwriter.flush(2))

    def test_stop_flushes_then_runs_inline(self):
        ran = []
        bgwriter.submit(ran.append, 1)
        self.assertTrue(bgwriter.stop(2))
        self.assertEqual(ran, [1])
        bgwriter.submit(ran.append, 2)      # closing: written inline
        self.assertEqual(ran, [1, 2])
        bgwriter.reopen()

    def test_bad_queue_size_keeps_default(self):
        bgwriter.configure({"agents": {"writer_queue_max": "lots"}})
        self.assertEqual(bgwriter.stats()["max"], bgwriter.DEFAULT_MAX)


class HotPath(unittest.TestCase):
    def setUp(self):
        bgwriter.reopen()

    def test_trajectory_write_is_queued_with_a_step_copy(self):
        steps = [{"tool": "launch", "arg": "x", "result": "ok"}]
        got = []
        gate = threading.Event()
        bgwriter.submit(gate.wait)
        with mock.patch("wisp.trajectories.record",
                        side_effect=lambda *a, **k: got.append(a)), \
                mock.patch.object(act, "_app", return_value="app"):
            act._record_traj("t", None, steps, "ACTED", {})
            steps.clear()                   # caller reuses the list
            self.assertEqual(got, [])       # not written on the hot path
            gate.set()
            self.assertTrue(bgwriter.flush(2))
        self.assertEqual(got[0][2], [{"tool": "launch", "arg": "x",
                                      "result": "ok"}])

    def test_act_limits_come_from_agents_section(self):
        cfg = {"agents": {"act_max_steps": "3", "act_max_errors": "x"}}
        self.assertEqual(act._limit(cfg, "act_max_steps", 8), 3)
        self.assertEqual(act._limit(cfg, "act_max_errors", 2), 2)
        self.assertEqual(act._limit({}, "act_max_parse_misses", 1), 1)

    def test_error_budget_is_configurable(self):
        calls = [{"id": "c", "type": "function",
                  "function": {"name": "bogus",
                               "arguments": '{"arg": ""}'}}]
        msg = {"role": "assistant", "content": None, "tool_calls": calls}
        for limit, expect_steps in (("0", 1), ("4", 5)):
            cfg = {"agent": {}, "agents": {"act_max_errors": limit}}
            with mock.patch.object(act, "_post", return_value=msg), \
                    mock.patch.object(act, "_record_traj"):
                out = act.run_act_loop("x", cfg)
            self.assertTrue(out.startswith("ABORTED (repeated failures)"))
            self.assertEqual(out.count("bogus"), min(3, expect_steps))


class Layout(unittest.TestCase):
    def test_stage_names_still_import_from_pipeline(self):
        for name in ("record", "record_start", "record_stop", "transcribe",
                     "capture_screen", "turn_screenshot", "ask_jev",
                     "ask_chat", "execute", "build_questions",
                     "JEV_QUESTIONS", "log_decision", "notify",
                     "run_listen", "_publish_error", "_end_speaking",
                     "_shadow_decision", "hypr_env", "fuzzy_app"):
            self.assertTrue(hasattr(pipeline, name), name)


if __name__ == "__main__":
    unittest.main()
