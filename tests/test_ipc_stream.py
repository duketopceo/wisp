#!/usr/bin/env python3
"""IPC push stream (W3): `subscribe` over the unix socket."""
import json
import pathlib
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import ipc, state as state_mod, trace  # noqa: E402


class StreamCase(unittest.TestCase):
    def setUp(self):
        self.td = pathlib.Path(tempfile.mkdtemp())
        self._tf = mock.patch.object(trace, "TRACE_FILE",
                                     self.td / "trace.jsonl")
        self._tf.start()
        self.addCleanup(self._tf.stop)
        self.bus = state_mod.StateBus(state_file=self.td / "state.json")
        self.addCleanup(self.bus.close)
        self.sock = self.td / "w.sock"
        self.srv = None

    def serve(self, **kw):
        self.srv = ipc.Daemon(lambda c: {"ok": True}, sock_file=self.sock,
                              bus=self.bus, **kw)
        self.srv.start()
        self.addCleanup(self.srv.stop)
        return self.srv

    def open(self, topics=None, **extra):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(str(self.sock))
        msg = {"cmd": "subscribe", **extra}
        if topics is not None:
            msg["topics"] = topics
        s.sendall(json.dumps(msg).encode() + b"\n")
        self.addCleanup(s.close)
        f = s.makefile("rb")
        f.sock = s
        return f

    @staticmethod
    def line(f):
        raw = f.readline()
        return json.loads(raw) if raw else None

    def wait_subs(self, n):
        end = time.monotonic() + 3
        while self.bus.subscriber_count() != n and time.monotonic() < end:
            time.sleep(0.01)
        self.assertEqual(self.bus.subscriber_count(), n)


class SubscribeTest(StreamCase):
    def test_hello_then_snapshot_then_ordered_diffs(self):
        self.serve()
        f = self.open()
        hello, snap = self.line(f), self.line(f)
        self.assertEqual(hello["type"], "hello")
        self.assertTrue(hello["ok"])
        self.assertEqual(hello["contract_version"], 1)
        self.assertEqual(snap["type"], "snapshot")
        self.assertEqual(snap["state"]["status"], "idle")
        self.wait_subs(1)
        t = self.bus.begin_turn()
        for s in ("listening", "deciding", "done"):
            self.bus.publish(t, status=s)
        evs = [self.line(f) for _ in range(3)]
        self.assertEqual([e["diff"]["status"] for e in evs],
                         ["listening", "deciding", "done"])
        seqs = [e["seq"] for e in evs]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(seqs[0], snap["seq"] + 1)

    def test_two_subscribers_see_identical_streams(self):
        self.serve()
        a, b = self.open(), self.open()
        for f in (a, b):
            self.line(f), self.line(f)
        self.wait_subs(2)
        t = self.bus.begin_turn()
        self.bus.publish(t, status="acting", transcript="x")
        self.bus.emit_event("health_changed", name="jev", ok=False)
        ea = [self.line(a) for _ in range(2)]
        eb = [self.line(b) for _ in range(2)]
        self.assertEqual(ea, eb)
        self.assertEqual(ea[1]["name"], "health_changed")

    def test_reconnect_replays_last_state(self):
        self.serve()
        t = self.bus.begin_turn()
        self.bus.publish(t, status="deciding", transcript="hello")
        f1 = self.open()
        self.line(f1)
        s1 = self.line(f1)
        f1.close()
        f1.sock.close()
        self.bus.publish(t, status="done", answer="ok")
        f2 = self.open()
        self.line(f2)
        s2 = self.line(f2)
        self.assertEqual(s1["state"]["transcript"], "hello")
        self.assertEqual(s2["state"]["status"], "done")
        self.assertEqual(s2["state"]["answer"], "ok")
        self.assertGreater(s2["seq"], s1["seq"])

    def test_topics_filter(self):
        self.serve()
        f = self.open(topics=["health"])
        self.line(f), self.line(f)
        self.wait_subs(1)
        t = self.bus.begin_turn()
        self.bus.publish(t, status="acting")
        self.bus.emit_event("task_finished", name="a", status="exited")
        self.bus.emit_event("health_changed", name="jev", ok=True)
        ev = self.line(f)
        self.assertEqual((ev["type"], ev["name"]), ("event",
                                                    "health_changed"))

    def test_unknown_topic_rejected(self):
        self.serve()
        f = self.open(topics=["bogus"])
        r = self.line(f)
        self.assertFalse(r["ok"])
        self.assertIn("topic", r["error"])
        self.assertEqual(self.bus.subscriber_count(), 0)

    def test_no_bus_replies_error(self):
        srv = ipc.Daemon(lambda c: {"ok": True}, sock_file=self.sock)
        srv.start()
        self.addCleanup(srv.stop)
        f = self.open()
        r = self.line(f)
        self.assertFalse(r["ok"])

    def test_disconnect_unsubscribes(self):
        self.serve(ping_s=0.05)
        f = self.open()
        self.line(f), self.line(f)
        self.wait_subs(1)
        f.close()
        f.sock.close()
        # the server notices on its next write (ping or event)
        t = self.bus.begin_turn()
        self.bus.publish(t, status="acting")
        end = time.monotonic() + 3
        while self.bus.subscriber_count() and time.monotonic() < end:
            time.sleep(0.02)
        self.assertEqual(self.bus.subscriber_count(), 0)

    def test_idle_ping(self):
        self.serve(ping_s=0.05)
        f = self.open()
        self.line(f), self.line(f)
        self.assertEqual(self.line(f)["type"], "ping")


class BackpressureTest(StreamCase):
    def test_slow_subscriber_dropped_others_unaffected(self):
        self.serve(sub_queue=50)
        slow, good = self.open(), self.open()
        for f in (slow, good):
            self.line(f), self.line(f)
        self.wait_subs(2)
        # `good` drains concurrently; `slow` never reads
        got = []

        def drain():
            while True:
                e = self.line(good)
                if e is None:
                    return
                got.append(e)
        threading.Thread(target=drain, daemon=True).start()
        t = self.bus.begin_turn()
        for i in range(400):
            self.bus.publish(t, transcript="x" * 60000 + str(i))
            time.sleep(0.003)  # `good` keeps up at this pace
            if self.bus.subscriber_count() == 1:
                break
        self.assertEqual(self.bus.subscriber_count(), 1)
        self.assertEqual(self.bus.snapshot()["transcript"][-1:] != "", True)

    def test_overflow_event_is_last_line_then_eof(self):
        self.serve(sub_queue=2)
        f = self.open()
        self.line(f), self.line(f)
        self.wait_subs(1)
        sub = self.bus._subs[0]
        sub._cv.acquire()  # stall the writer so the queue overflows
        try:
            t = self.bus.begin_turn()
            for i in range(6):
                self.bus.publish(t, transcript=str(i))
        finally:
            sub._cv.release()
        names = []
        while True:
            e = self.line(f)
            if e is None:
                break
            names.append(e.get("name"))
        self.assertEqual(names[-1], "overflow")
        self.assertEqual(self.bus.subscriber_count(), 0)

    def test_stuck_socket_dropped_by_send_timeout(self):
        self.serve(send_timeout=0.2)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
        s.connect(str(self.sock))
        s.sendall(b'{"cmd":"subscribe"}\n')
        self.addCleanup(s.close)
        self.wait_subs(1)
        t = self.bus.begin_turn()
        end = time.monotonic() + 8
        i = 0
        while self.bus.subscriber_count() and time.monotonic() < end:
            self.bus.publish(t, transcript="y" * 60000 + str(i))
            i += 1
            time.sleep(0.005)
        self.assertEqual(self.bus.subscriber_count(), 0)


class ClientTest(StreamCase):
    def test_client_yields_events_and_stops_on_close(self):
        self.serve(ping_s=0.05)  # server notices the hangup on a ping
        it = ipc.subscribe(sock_file=self.sock, timeout=3)
        first = next(it)
        self.assertEqual(first["type"], "hello")
        self.assertEqual(next(it)["type"], "snapshot")
        t = self.bus.begin_turn()
        self.bus.publish(t, status="acting")
        self.assertEqual(next(it)["diff"]["status"], "acting")
        it.close()
        self.wait_subs(0)

    def test_watch_reconnects_after_daemon_restart(self):
        self.serve()
        out = []
        stop = threading.Event()

        def run():
            for ev in ipc.watch(sock_file=self.sock, retry_s=0.05,
                                stop=stop):
                out.append(ev)
        th = threading.Thread(target=run, daemon=True)
        th.start()
        end = time.monotonic() + 3
        while len(out) < 2 and time.monotonic() < end:
            time.sleep(0.01)
        self.srv.stop()
        self.bus.publish(None, status="acting")
        self.serve()
        end = time.monotonic() + 5
        snaps = lambda: [e for e in out if e["type"] == "snapshot"]
        while len(snaps()) < 2 and time.monotonic() < end:
            time.sleep(0.02)
        stop.set()
        self.assertEqual(len(snaps()), 2)
        self.assertEqual(snaps()[1]["state"]["status"], "acting")


class TopicFilterTest(StreamCase):
    def test_subscription_filters_at_offer_so_noise_cannot_overflow(self):
        sub = self.bus.subscribe(maxsize=2, topics={"health"})
        t = self.bus.begin_turn()
        for i in range(10):
            self.bus.publish(t, transcript=str(i))
        self.assertFalse(sub.closed)
        self.bus.emit_event("health_changed", name="x", ok=True)
        self.assertEqual(sub.get(0.1)["name"], "health_changed")


if __name__ == "__main__":
    unittest.main()
