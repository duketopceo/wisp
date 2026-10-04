#!/usr/bin/env python3
"""StateBus single publisher (backend U2)."""
import json
import pathlib
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import state as state_mod, trace  # noqa: E402


class BusCase(unittest.TestCase):
    def setUp(self):
        self.td = pathlib.Path(tempfile.mkdtemp())
        self.f = self.td / "state.json"
        self.bus = None
        self._tf = mock.patch.object(trace, "TRACE_FILE",
                                     self.td / "trace.jsonl")
        self._tf.start()
        self.addCleanup(self._tf.stop)

    def make(self, **kw):
        self.bus = state_mod.StateBus(state_file=self.f, **kw)
        self.addCleanup(self.bus.close)
        return self.bus

    def disk(self):
        return json.loads(self.f.read_text())


class PublishTest(BusCase):
    def test_current_turn_updates_snapshot_and_seq_steps_by_one(self):
        bus = self.make()
        t = bus.begin_turn()
        s0 = bus.snapshot()["seq"]
        self.assertTrue(bus.publish(t, status="listening", transcript="hi"))
        s1 = bus.snapshot()
        self.assertEqual(s1["seq"], s0 + 1)
        self.assertEqual(s1["transcript"], "hi")
        self.assertTrue(bus.publish(t, status="deciding"))
        self.assertEqual(bus.snapshot()["seq"], s0 + 2)
        d = self.disk()
        self.assertEqual((d["seq"], d["status"]), (s0 + 2, "deciding"))

    def test_every_write_is_stamped(self):
        bus = self.make()
        t = bus.begin_turn()
        bus.publish(t, status="listening")
        d = self.disk()
        self.assertEqual(d["turn_id"], t)
        self.assertEqual(d["contract_version"], state_mod.CONTRACT_VERSION)
        self.assertTrue(d["updated_at"])
        self.assertIsInstance(d["seq"], int)

    def test_stale_turn_is_dropped_and_snapshot_unchanged(self):
        bus = self.make()
        old = bus.begin_turn()
        bus.publish(old, status="listening", transcript="old")
        new = bus.begin_turn()
        bus.publish(new, status="deciding", transcript="new")
        before = bus.snapshot()
        with mock.patch.object(trace, "emit") as emit:
            self.assertFalse(bus.publish(old, status="done", result="late"))
        self.assertEqual(bus.snapshot(), before)
        self.assertEqual(self.disk()["transcript"], "new")
        self.assertEqual(emit.call_args[0][1], "stale_publish")

    def test_daemon_level_publish_needs_no_turn(self):
        bus = self.make()
        bus.begin_turn()
        self.assertTrue(bus.publish(None, tasks={"a": "running"}))
        self.assertEqual(self.disk()["tasks"], {"a": "running"})

    def test_unchanged_publish_does_not_bump_seq(self):
        bus = self.make()
        t = bus.begin_turn()
        bus.publish(t, status="deciding")
        s = bus.snapshot()["seq"]
        bus.publish(t, status="deciding")
        self.assertEqual(bus.snapshot()["seq"], s)

    def test_guide_cleared_on_exit_from_acting(self):
        bus = self.make()
        t = bus.begin_turn()
        bus.publish(t, status="acting", guide={"x": 1, "y": 2})
        bus.publish(t, status="done")
        self.assertIsNone(self.disk()["guide"])

    def test_suggest_race_publish_dropped_after_new_turn(self):
        from wisp import suggest, sense
        bus = self.make()
        cfg = {"sense": {"model": "x"}}
        win = [{"ts": "x"}] * 6
        sug = self.td / "sugg.jsonl"
        payload = json.dumps({"suggestions": [
            {"title": "t", "evidence": "e", "routine": "open x",
             "confidence": 0.9}]})

        def slow_chat(*a, **k):
            bus.begin_turn()  # user presses the key mid-computation
            return {"content": payload}
        with mock.patch.object(sense, "read_window", return_value=win), \
                mock.patch.object(suggest, "_worth_mining",
                                  return_value=True), \
                mock.patch.object(suggest, "_budget_ok", return_value=True), \
                mock.patch.object(suggest, "SUGGESTIONS_FILE", sug), \
                mock.patch("wisp.brain.chat", side_effect=slow_chat):
            out = suggest.mine(cfg, state=bus)
        self.assertEqual(len(out), 1)           # still recorded on disk
        self.assertIsNone(bus.snapshot()["suggestion"])  # not published
        self.assertNotEqual(bus.snapshot()["status"], "suggestion")


class CoalesceTest(BusCase):
    def test_100_level_updates_in_1s_at_most_13_writes(self):
        bus = self.make(rate_hz=12)
        t = bus.begin_turn()
        w0 = bus.write_count
        for i in range(100):
            bus.publish(t, level=(i + 1) / 100)
            time.sleep(0.01)
        time.sleep(0.25)
        self.assertLessEqual(bus.write_count - w0, 13)
        self.assertGreaterEqual(bus.write_count - w0, 5)
        self.assertAlmostEqual(self.disk()["level"], 1.0)

    def test_noncoalesced_publish_flushes_pending_level(self):
        bus = self.make(rate_hz=1)
        t = bus.begin_turn()
        bus.publish(t, level=0.2)
        bus.publish(t, level=0.9)       # deferred (1 Hz)
        bus.publish(t, status="deciding")
        d = self.disk()
        self.assertEqual((d["status"], d["level"]), ("deciding", 0.9))

    def test_answer_delta_coalesce_flag(self):
        bus = self.make(rate_hz=1)
        t = bus.begin_turn()
        bus.publish(t, status="speaking", answer="a", coalesce=True)
        n = bus.write_count
        bus.publish(t, status="speaking", answer="ab", coalesce=True)
        self.assertEqual(bus.write_count, n)
        self.assertEqual(bus.snapshot()["answer"], "ab")


class PauseTest(BusCase):
    def test_paused_publishes_queue_then_one_write_on_resume(self):
        bus = self.make()
        t = bus.begin_turn()
        bus.publish(t, status="listening")
        n = bus.write_count
        bus.pause()
        bus.publish(t, status="deciding", transcript="a")
        bus.publish(t, status="acting", transcript="b")
        self.assertEqual(bus.write_count, n)
        self.assertEqual(self.disk()["status"], "listening")
        bus.resume()
        self.assertEqual(bus.write_count, n + 1)
        d = self.disk()
        self.assertEqual((d["status"], d["transcript"]), ("acting", "b"))


class SubscriberTest(BusCase):
    def test_subscriber_gets_snapshot_then_diffs_in_seq_order(self):
        bus = self.make()
        t = bus.begin_turn()
        sub = bus.subscribe()
        self.assertEqual(sub.snapshot["status"], "idle")
        bus.publish(t, status="listening")
        bus.publish(t, status="deciding", transcript="x")
        e1, e2 = sub.get(1), sub.get(1)
        self.assertEqual((e1["type"], e1["diff"]["status"]),
                         ("state", "listening"))
        self.assertEqual(e2["seq"], e1["seq"] + 1)
        self.assertEqual(e2["diff"]["transcript"], "x")

    def test_two_subscribers_identical_sequences(self):
        bus = self.make()
        t = bus.begin_turn()
        a, b = bus.subscribe(), bus.subscribe()
        for s in ("listening", "deciding", "done"):
            bus.publish(t, status=s)
        ea = [a.get(1) for _ in range(3)]
        eb = [b.get(1) for _ in range(3)]
        self.assertEqual(ea, eb)

    def test_slow_subscriber_dropped_with_overflow_bus_keeps_writing(self):
        bus = self.make()
        t = bus.begin_turn()
        slow, good = bus.subscribe(maxsize=3), bus.subscribe(maxsize=100)
        for i in range(10):
            bus.publish(t, transcript=str(i))
        self.assertTrue(slow.closed)
        evs = []
        while True:
            e = slow.get(0.01)
            if e is None:
                break
            evs.append(e)
        self.assertEqual(evs[-1], {"type": "event", "name": "overflow"})
        self.assertEqual(self.disk()["transcript"], "9")
        self.assertFalse(good.closed)
        self.assertEqual(bus.subscriber_count(), 1)

    def test_unsubscribe_removes(self):
        bus = self.make()
        s = bus.subscribe()
        bus.unsubscribe(s)
        self.assertEqual(bus.subscriber_count(), 0)


class HeartbeatTest(BusCase):
    def _beats(self, sub):
        n = 0
        while True:
            e = sub.get(0.01)
            if e is None:
                return n
            n += "heartbeat_at" in e.get("diff", {})

    def test_fires_while_acting_and_stops_at_idle(self):
        bus = self.make(heartbeat_s=0.1)
        t = bus.begin_turn()
        sub = bus.subscribe()
        bus.publish(t, status="acting")
        time.sleep(0.45)
        self.assertGreaterEqual(self._beats(sub), 2)
        bus.publish(t, status="idle")
        self._beats(sub)
        time.sleep(0.35)
        self.assertEqual(self._beats(sub), 0)


class LegacyShimTest(BusCase):
    def test_turn_handle_publishes_for_its_turn(self):
        bus = self.make()
        t1 = bus.begin_turn()
        h1 = bus.turn(t1)
        h1.transition("listening", transcript="a")
        h1.set_level(0.5)
        self.assertEqual(bus.snapshot()["level"], 0.5)
        bus.begin_turn()
        h1.transition("done", result="late")       # stale -> dropped
        self.assertEqual(bus.snapshot()["status"], "listening")
        self.assertEqual(h1.status, "listening")   # reads proxy through

    def test_state_mutators_route_through_bus_when_attached(self):
        bus = self.make()
        bus.begin_turn()
        n = bus.write_count
        bus.state.transition("error", error="x")
        self.assertEqual(bus.write_count, n + 1)
        self.assertEqual(self.disk()["seq"], bus.snapshot()["seq"])


if __name__ == "__main__":
    unittest.main()
