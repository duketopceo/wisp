"""W18 notifications. The subprocess layer is a fake: no real
notification is ever sent and no D-Bus is touched."""
import os
import re
import unittest
from datetime import datetime
from unittest import mock

from wisp import notify


class FakeBus:
    """Stands in for gdbus/notify-send. Records every argv."""

    def __init__(self, caps=("body", "body-markup", "actions"),
                 server=("quickshell", "quickshell", "", "1.2"),
                 absent=False):
        self.caps, self.server, self.absent = caps, server, absent
        self.calls = []
        self.next_id = 7

    def __call__(self, argv, timeout=2.0):
        self.calls.append(list(argv))
        if argv[0] == "notify-send":
            return 0, ""
        if self.absent:
            return 1, ""
        j = " ".join(argv)
        if "GetServerInformation" in j:
            return 0, "(%s,)\n" % ", ".join(repr(s) for s in self.server)
        if "GetCapabilities" in j:
            return 0, "([%s],)\n" % ", ".join(repr(c) for c in self.caps)
        if ".Notify" in j:
            rid = int(argv[argv.index("org.freedesktop.Notifications.Notify")
                      + 2])
            nid = rid or self.next_id
            if not rid:
                self.next_id += 1
            return 0, "(uint32 %d,)\n" % nid
        return 1, ""

    def notifies(self):
        return [c for c in self.calls
                if "org.freedesktop.Notifications.Notify" in c]


def mk(bus=None, now=None, cfg=None, **kw):
    bus = bus or FakeBus()
    kw.setdefault("monitor", lambda secs: iter(()))  # never spawn gdbus
    t = {"t": 1000.0}
    n = notify.Notifier(runner=bus, clock=lambda: t["t"],
                        now=now or (lambda: datetime(2026, 1, 1, 12, 0)),
                        cfg=cfg or {}, sync=True, os_name="linux", **kw)
    return n, bus, t


class TestServer(unittest.TestCase):
    def test_detects_server_and_caps(self):
        n, bus, _ = mk()
        info = n.server()
        self.assertEqual(info["name"], "quickshell")
        self.assertIn("actions", info["caps"])
        n.server()
        self.assertEqual(
            sum("GetServerInformation" in " ".join(c) for c in bus.calls), 1)

    def test_absent_server_falls_back_to_notify_send(self):
        n, bus, _ = mk(FakeBus(absent=True))
        self.assertIsNone(n.server())
        # the fallback argv comes from platform.notify_cmd, which keys
        # off the host OS, not the Notifier's os_name: pin it
        with mock.patch.dict(os.environ, {"WISP_OS": "linux"}):
            self.assertEqual(n.send("hello"), "sent")
        self.assertEqual(bus.calls[-1][0], "notify-send")
        self.assertIn("hello", bus.calls[-1])

    def test_macos_path_unchanged(self):
        bus = FakeBus()
        n = notify.Notifier(runner=bus, sync=True, os_name="macos", cfg={})
        with mock.patch.dict(os.environ, {"WISP_OS": "macos"}):
            n.send("hi")
        self.assertEqual(bus.calls[-1][0], "osascript")
        self.assertFalse(bus.notifies())


class TestSend(unittest.TestCase):
    def test_replace_id_per_turn(self):
        n, bus, _ = mk()
        n.send("listening", turn="t1")
        n.send("done", level="success", turn="t1")
        n.send("other", turn="t2")
        ids = [c[c.index("org.freedesktop.Notifications.Notify") + 2]
               for c in bus.notifies()]
        self.assertEqual(ids, ["0", "7", "0"])

    def test_dedupe_window(self):
        n, bus, t = mk()
        self.assertEqual(n.send("same", turn="a"), "sent")
        self.assertEqual(n.send("same", turn="b"), "deduped")
        t["t"] += 61
        self.assertEqual(n.send("same", turn="c"), "sent")
        self.assertEqual(len(bus.notifies()), 2)

    def test_explicit_key_dedupes(self):
        n, bus, _ = mk()
        n.send("one", key="k")
        self.assertEqual(n.send("two", key="k"), "deduped")

    def test_quiet_hours_across_midnight(self):
        cfg = {"notify": {"quiet": "22:00-07:00"}}
        for hh, mm, quiet in ((23, 0, True), (3, 30, True), (6, 59, True),
                              (7, 0, False), (12, 0, False),
                              (21, 59, False)):
            n, bus, _ = mk(now=lambda h=hh, m=mm: datetime(2026, 1, 1, h, m),
                           cfg=cfg)
            self.assertEqual(n.send("x"), "quiet" if quiet else "sent",
                             (hh, mm))
            self.assertEqual(bool(bus.notifies()), not quiet)

    def test_quiet_same_day_and_bad_value(self):
        self.assertTrue(notify.in_quiet("09:00-17:00", datetime(2026, 1, 1, 10)))
        self.assertFalse(notify.in_quiet("09:00-17:00", datetime(2026, 1, 1, 18)))
        for bad in ("", "nonsense", "25:00-07:00", "10:00-10:00"):
            self.assertFalse(notify.in_quiet(bad, datetime(2026, 1, 1, 10)))

    def test_disabled(self):
        n, bus, _ = mk(cfg={"notify": {"enabled": "false"}})
        self.assertEqual(n.send("x"), "disabled")
        self.assertFalse(bus.calls)

    def test_cancel_and_stale_never_toast(self):
        n, bus, _ = mk()
        self.assertEqual(n.send("Cancelled", code="cancelled"), "cancelled")
        self.assertEqual(n.send("late", stale=True), "stale")
        self.assertFalse(bus.calls)

    def test_spoken_suppressed_only_when_tts_on(self):
        n, bus, _ = mk(cfg={"voice": {"enabled": "true"}})
        self.assertEqual(n.send("answer", spoken=True), "spoken")
        self.assertEqual(
            n.send("boom", level="error", spoken=True, key="e"), "sent")
        n2, bus2, _ = mk(cfg={"voice": {"enabled": "false"}})
        self.assertEqual(n2.send("answer", spoken=True), "sent")

    def test_urgency_mapping(self):
        n, bus, _ = mk()
        for lvl, urg in (("info", 0), ("success", 0), ("attention", 1),
                         ("error", 2)):
            n.send("m " + lvl, level=lvl)
            self.assertIn("<byte %d>" % urg, bus.notifies()[-1][-2])
        n.send("jev", code="jev_down")
        self.assertIn("<byte 2>", bus.notifies()[-1][-2])
        n.send("slow", code="timeout")
        self.assertIn("<byte 1>", bus.notifies()[-1][-2])

    def test_body_escaping_with_markup_cap(self):
        n, bus, _ = mk()
        n.send("a <b>&</b> 'q'")
        body = bus.notifies()[-1]
        self.assertIn("a &lt;b&gt;&amp;&lt;/b&gt; ", " ".join(body))
        self.assertNotIn("<b>&", " ".join(body))

    def test_no_markup_cap_leaves_text(self):
        n, bus, _ = mk(FakeBus(caps=("body",)))
        n.send("a <b>")
        self.assertIn("a <b>", " ".join(bus.notifies()[-1]))

    def test_gvariant_quoting(self):
        self.assertEqual(notify.gv_str("it's\n\\"), r"'it\'s\n\\'")

    def test_copy_has_no_emoji_or_em_dash(self):
        for s in list(notify.COPY.values()) + [notify.TITLE]:
            self.assertNotIn("—", s)
            self.assertFalse(re.search("[\U0001F300-\U0001FAFF☀-➿]", s))


class TestActions(unittest.TestCase):
    def test_actions_sent_when_advertised(self):
        n, bus, _ = mk()
        n.send("Jev is down", level="error", code="jev_down",
               actions=[("retry", "Retry", lambda: None)])
        self.assertIn("['retry', 'Retry']", bus.notifies()[-1])

    def test_actions_dropped_without_capability(self):
        n, bus, _ = mk(FakeBus(caps=("body",)))
        n.send("x", actions=[("retry", "Retry", lambda: None)])
        self.assertIn("[]", bus.notifies()[-1])
        self.assertNotIn("Retry", " ".join(bus.notifies()[-1]))

    def test_actions_dropped_on_fallback(self):
        n, bus, _ = mk(FakeBus(absent=True))
        n.send("x", actions=[("retry", "Retry", lambda: None)])
        self.assertNotIn("Retry", " ".join(bus.calls[-1]))

    def test_action_callback_runs_for_matching_id(self):
        hits = []
        lines = [
            "/org/freedesktop/Notifications: org.freedesktop.Notifications"
            ".ActionInvoked (uint32 99, 'retry')",
            "/org/freedesktop/Notifications: org.freedesktop.Notifications"
            ".ActionInvoked (uint32 7, 'retry')",
        ]
        n, bus, _ = mk(monitor=lambda secs: iter(lines))
        n.send("x", level="error", actions=[("retry", "Retry",
                                             lambda: hits.append(1))])
        self.assertEqual(hits, [1])

    def test_callback_error_is_swallowed(self):
        lines = ["x ActionInvoked (uint32 7, 'a')"]
        n, bus, _ = mk(monitor=lambda secs: iter(lines))
        def boom():
            raise RuntimeError("x")
        n.send("x", actions=[("a", "A", boom)])


class TestNonBlocking(unittest.TestCase):
    def test_async_send_returns_before_delivery(self):
        import threading
        gate = threading.Event()
        calls = []
        def slow(argv, timeout=2.0):
            gate.wait(2)
            calls.append(argv)
            return 1, ""
        n = notify.Notifier(runner=slow, os_name="linux", cfg={})
        self.assertEqual(n.send("x"), "sent")
        self.assertEqual(calls, [])
        gate.set()
        n.join(2)
        self.assertTrue(calls)

    def test_runner_exception_never_raises(self):
        def bad(argv, timeout=2.0):
            raise OSError("no gdbus")
        n = notify.Notifier(runner=bad, os_name="linux", cfg={}, sync=True)
        n.send("x")


class TestPipelineWiring(unittest.TestCase):
    def test_pipeline_notify_delegates(self):
        from wisp import pipeline
        with mock.patch.object(notify, "send", return_value="sent") as s:
            pipeline.notify("hi", level="success", turn="t")
        s.assert_called_once()
        self.assertEqual(s.call_args.args[0], "hi")
        self.assertEqual(s.call_args.kwargs["level"], "success")


if __name__ == "__main__":
    unittest.main()
