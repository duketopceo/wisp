"""U5 delivery modes (KTD5): honest background/pointer marking per op,
the real-input yield watch (evdev + drift fallback), blocked
desktop-scope gestures, and the [cua] delivery policy — auto /
background / pointer — with the escalation recorded end to end.

All backends faked (same Rig pattern as test_pointer_registry)."""
import json
import os
import pathlib
import shutil
import stat
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import fakes  # noqa: E402
from fakes import FakeHypr, ok_handler  # noqa: E402

from wisp import act, cancel, cua_safety, delivery, platform, pointer, realinput, \
    tools  # noqa: E402
from wisp.tools import system  # noqa: E402

# U4: unfaked loop calls reach a live cua-driver's recording + pack
# write; the pack seam is stubbed module-wide (its suite is elsewhere)
_WRITE_PACK = None


def setUpModule():
    global _WRITE_PACK
    _WRITE_PACK = mock.patch.object(act, "_write_pack")
    _WRITE_PACK.start()


def tearDownModule():
    _WRITE_PACK.stop()


DRIVE = {"pointer": {"mode": "drive", "backend": "auto"}}


def _cfg(**kw):
    c = {"pointer": {"mode": "drive", "backend": "auto"}}
    c.update(kw)
    return c


class Rig:
    """PATH with a chosen subset of fake injectors; mirrors
    test_pointer_registry.Rig (kept local so this file stands alone)."""

    def __init__(self, live=("cua", "hyprctl", "ydotool", "wlrctl"),
                 cua_script=None, hypr=True):
        self.live = set(live)
        self.td = tempfile.TemporaryDirectory()
        t = pathlib.Path(self.td.name)
        self.bins = fakes.BinDir(t / "bin")
        self.log = t / "calls.log"
        for n in ("ydotool", "wlrctl"):
            if n in self.live:
                p = self.bins.path / n
                p.write_text(f'#!/bin/sh\necho "{n} $*" >> "{self.log}"\n'
                             'exit 0\n')
                p.chmod(p.stat().st_mode | stat.S_IXUSR)
        if "hyprctl" in self.live:
            p = self.bins.path / "hyprctl"
            p.write_text('#!/bin/sh\nexit 0\n')
            p.chmod(p.stat().st_mode | stat.S_IXUSR)
        script = dict(cua_script or {})
        script["mode"] = "live" if "cua" in self.live else "absent"
        self.cua = fakes.FakeCua(t, self.bins, script)
        self.hypr = FakeHypr(ok_handler) if hypr else None
        self.env = mock.patch.dict(os.environ, {
            "HOME": self.td.name, "USERPROFILE": self.td.name, "PATH": str(self.bins.path),
            "WISP_OS": "linux",
            "WISP_DESKTOP": "hyprland" if hypr else "x11"})
        # Delivery fixtures run on an identified benign Notes window,
        # not an unknown surface requiring an independent consent card.
        self.window = mock.patch.object(platform, "active_window", return_value={
            "class": "org.example.notes", "title": "Synthetic notes"})

    def shell(self):
        return self.log.read_text().splitlines() if self.log.exists() \
            else []

    def __enter__(self):
        if self.hypr:
            self.hypr.__enter__()
        self.cua.start()
        self.env.start()
        self.window.start()
        return self

    def __exit__(self, *a):
        self.window.stop()
        self.env.stop()
        self.cua.stop()
        if self.hypr:
            self.hypr.__exit__(*a)
        self.td.cleanup()


class FakeWatch:
    """Module-level _WATCH double: begin/arm/expect no-op; the test
    flips _yield to simulate a human's real input."""

    def __init__(self, mode="evdev"):
        self.mode = mode
        self._yield = threading.Event()
        self.begun = 0
        self.armed = 0

    def begin(self):
        self.begun += 1

    def arm(self):
        self.armed += 1

    def expect(self, x, y):
        pass

    def check(self):
        if self._yield.is_set():
            raise cancel.Cancelled("real input took the pointer")

    def yielded(self):
        return self._yield.is_set()

    def finish(self):
        pass

    def close(self):
        pass


def _wait(flag, s=2.0):
    t0 = time.monotonic()
    while not flag() and time.monotonic() - t0 < s:
        time.sleep(0.005)
    return flag()


class _Iso(unittest.TestCase):
    """Isolate the process-level watch: earlier suites may have left
    the real /dev/input or drift watch armed and yielded — module-level
    realinput calls must see _WATCH=None unless the test installs one."""

    def setUp(self):
        realinput._stop_for_test()


class Mode(_Iso):
    def test_choices_and_default(self):
        self.assertEqual(delivery.mode({}), "auto")
        self.assertEqual(delivery.mode(
            {"cua": {"delivery": "background"}}), "background")
        self.assertEqual(delivery.mode(
            {"cua": {"delivery": "pointer"}}), "pointer")
        self.assertEqual(delivery.mode(
            {"cua": {"delivery": "sneaky"}}), "auto")
        self.assertEqual(delivery.mode(
            {"cua": {"delivery": " Pointer "}}), "pointer")

    def test_default_config_is_auto(self):
        from wisp import config
        self.assertIn('delivery = "auto"', config.DEFAULT_CONFIG)
        self.assertEqual(config._default_cfg_dict()["cua"]["delivery"],
                         "auto")


class TruthTable(_Iso):
    def test_backend_delivery(self):
        self.assertEqual(delivery.backend_delivery("cua", "click"),
                         "background")
        self.assertEqual(delivery.backend_delivery("cua", "move"),
                         "pointer")
        for b in ("hyprcursor", "ydotool", "wlrctl", "hypr"):
            self.assertEqual(delivery.backend_delivery(b, "click"),
                             "pointer", b)
            self.assertEqual(delivery.backend_delivery(b, "move"),
                             "pointer", b)
        self.assertEqual(delivery.backend_delivery("guide", "click"),
                         "guide")
        self.assertEqual(delivery.backend_delivery(None, "click"),
                         "guide")

    def test_planned(self):
        for t in ("type_text", "key", "fill", "scroll", "focus", "tab",
                  "workspace", "launch", "close"):
            self.assertEqual(delivery.planned(t, {}), "background", t)
        for t in ("click", "move"):
            self.assertEqual(delivery.planned(t, {}), "guide", t)
        self.assertEqual(delivery.planned("screenshot", {}), "")
        self.assertEqual(delivery.planned("bogus", {}), "")
        dom = {"screen": {"dom_page": "p"},
               "pointer": {"mode": "drive"}}
        self.assertEqual(delivery.planned("click", dom), "background")


class Stamps(_Iso):
    """The tool function stamps the channel it actually used."""

    def tearDown(self):
        delivery.clear()

    def test_type_text_is_background(self):
        with tempfile.TemporaryDirectory() as td:
            b = pathlib.Path(td) / "wtype"
            b.write_text("#!/bin/sh\nexit 0\n")
            b.chmod(0o755)
            with mock.patch.dict(os.environ,
                                 {"PATH": td, "WISP_OS": "linux",
                                  "WISP_DESKTOP": "hyprland"}):
                self.assertEqual(system.type_text("hi", DRIVE), "TYPED")
        self.assertEqual(delivery.last(), "background")

    def test_dom_click_is_background(self):
        cfg = {"screen": {"dom_page": "p"}, "pointer": {"mode": "drive"}}
        with mock.patch.object(system, "_dom_eval",
                               return_value="hit:ok-btn"):
            self.assertEqual(system.click("ok-btn", cfg), "CLICKED ok-btn")
        self.assertEqual(delivery.last(), "background")

    def test_ydotool_click_is_pointer(self):
        # Direct numeric dispatch here represents a literal human request.
        with Rig(("ydotool",), hypr=False), system.pointer_context(
                user_request="click at 10,20@logical"):
            out = system.click("10,20@logical", DRIVE)
            self.assertTrue(out.startswith("CLICKED"), out)
        self.assertEqual(delivery.last(), "pointer")

    def test_cua_click_is_background_cua_move_is_pointer(self):
        with Rig(("cua",), hypr=False), system.pointer_context(
                user_request="click at 10,20@logical"):
            out = system.click("10,20@logical", DRIVE)
            self.assertTrue(out.startswith("CLICKED"), out)
            self.assertEqual(delivery.last(), "background")
            out = system.move("10,20@logical", DRIVE)
            self.assertTrue(out.startswith("MOVED"), out)
            self.assertEqual(delivery.last(), "pointer")

    def test_key_scroll_fill_are_background(self):
        with Rig(("ydotool",), hypr=False):
            system.key("enter", DRIVE)
            self.assertEqual(delivery.last(), "background")
            system.scroll("down", DRIVE)
            self.assertEqual(delivery.last(), "background")
        cfg = {"screen": {"dom_page": "p"}}
        with mock.patch.object(system, "_dom_eval",
                               return_value="filled:f=v"):
            system.fill("f v", cfg)
        self.assertEqual(delivery.last(), "background")

    def test_guide_stamp(self):
        with Rig((), hypr=False):
            out = system.click("10,20@logical", DRIVE)
            self.assertTrue(out.startswith("GUIDE"), out)
        self.assertEqual(delivery.last(), "guide")


class Policy(_Iso):
    """[cua] delivery picks the channel: auto / background / pointer."""

    def tearDown(self):
        delivery.clear()

    def test_auto_uses_each_ops_natural_channel(self):
        with Rig():
            self.assertEqual(delivery.resolve_backend(
                _cfg(), "click"), "cua")
            self.assertEqual(delivery.resolve_backend(
                _cfg(), "move"), "cua")   # cua move is a real-pointer move
        with Rig(("ydotool",), hypr=False):
            self.assertEqual(delivery.resolve_backend(
                _cfg(), "click"), "ydotool")

    def test_background_refuses_the_real_pointer(self):
        with Rig(("ydotool",), hypr=False):
            self.assertIsNone(delivery.resolve_backend(
                _cfg(cua={"delivery": "background"}), "click"))
            out = system.click("10,20@logical",
                               _cfg(cua={"delivery": "background"}))
            self.assertEqual(out,
                             "GUIDE(10,20) (background delivery only)")
            self.assertEqual(delivery.last(), "guide")

    def test_background_still_uses_a_true_background_path(self):
        # cua clicks never touch the real cursor — they still dispatch
        # under delivery=background
        with Rig(("cua",), hypr=False), system.pointer_context(
                user_request="click at 10,20@logical"):
            out = system.click("10,20@logical",
                               _cfg(cua={"delivery": "background"}))
            self.assertTrue(out.startswith("CLICKED"), out)
            self.assertEqual(delivery.last(), "background")
            # but a MOVE is real-pointer on cua (scope:"desktop") —
            # it guides instead of injecting
            out = system.move("10,20@logical",
                              _cfg(cua={"delivery": "background"}))
            self.assertTrue(out.startswith("MOVE-GUIDE"), out)
            self.assertIn("background delivery only", out)

    def test_pointer_escalates_clicks_off_cua(self):
        # escalation IS the visible behaviour: with cua live, auto would
        # click on the agent cursor — pointer mode takes ydotool instead
        with Rig() as r, system.pointer_context(
                user_request="click at 10,20@logical"):
            cfg = _cfg(cua={"delivery": "pointer"})
            self.assertEqual(delivery.resolve_backend(cfg, "click"),
                             "hyprcursor")
            out = system.click("10,20@logical", cfg)
            self.assertTrue(out.startswith("CLICKED"), out)
            self.assertEqual(delivery.last(), "pointer")
            self.assertEqual(r.cua.calls, [])
            self.assertTrue(r.shell())   # a real-pointer backend ran
            # moves are pointer either way — auto still picks cua here
            self.assertEqual(delivery.resolve_backend(cfg, "move"),
                             "cua")

    def test_pointer_falls_back_to_cua_when_nothing_real(self):
        with Rig(("cua",), hypr=False):
            cfg = _cfg(cua={"delivery": "pointer"})
            # no real-pointer backend exists — cua stays, honestly
            # marked background rather than silently "pointer"
            self.assertEqual(delivery.resolve_backend(cfg, "click"),
                             "cua")
            self.assertEqual(delivery.planned("click", cfg),
                             "background")


class WatchPaths(_Iso):
    """The real-input yield watch: evdev primary, drift fallback, off."""

    def test_evdev_real_event_yields(self):
        r, w = os.pipe()
        watch = realinput.Watch(devices=[r], poll_s=0.01)
        try:
            self.assertEqual(watch.start(), "evdev")
            os.write(w, b"\0" * 24)   # BEFORE the drive: no flag
            self.assertFalse(_wait(watch.yielded, s=0.2))
            watch.arm()
            os.write(w, b"\0" * 24)   # real input mid-drive
            self.assertTrue(_wait(watch.yielded))
            with self.assertRaises(cancel.Cancelled):
                watch.check()
        finally:
            watch.close()
            os.close(w)

    def test_events_before_arm_are_drained_not_yielded(self):
        r, w = os.pipe()
        watch = realinput.Watch(devices=[r], poll_s=0.01)
        try:
            self.assertEqual(watch.start(), "evdev")
            os.write(w, b"\0" * 48)   # buffered pre-run input
            watch.begin()             # fresh run clears it
            self.assertFalse(watch.yielded())
        finally:
            watch.close()
            os.close(w)

    def test_begin_resets_a_yielded_watch(self):
        r, w = os.pipe()
        watch = realinput.Watch(devices=[r], poll_s=0.01)
        try:
            watch.start()
            watch.arm()
            os.write(w, b"\0" * 24)
            self.assertTrue(_wait(watch.yielded))
            watch.begin()
            self.assertFalse(watch.yielded())
        finally:
            watch.close()
            os.close(w)

    def test_drift_watches_the_real_cursor(self):
        pos = [(0, 0)]
        watch = realinput.Watch(devices=[], cursor_pos=lambda: pos[0],
                                poll_s=0.01, drift_px=32)
        try:
            self.assertEqual(watch.start(), "drift")
            watch.expect(100, 100)
            pos[0] = (110, 100)        # drive jitter, inside the margin
            time.sleep(0.05)
            self.assertFalse(watch.yielded())
            pos[0] = (200, 100)        # a human moved the mouse
            self.assertTrue(_wait(watch.yielded))
        finally:
            watch.close()

    def test_drift_expected_follows_the_drive(self):
        pos = [(100, 100)]
        watch = realinput.Watch(devices=[], cursor_pos=lambda: pos[0],
                                poll_s=0.01, drift_px=32)
        try:
            self.assertEqual(watch.start(), "drift")
            watch.expect(100, 100)
            # the drive itself commands the next position — its own
            # move must not trip the yield
            pos[0] = (300, 300)
            watch.expect(300, 300)
            time.sleep(0.05)
            self.assertFalse(watch.yielded())
        finally:
            watch.close()

    def test_off_when_neither_path_exists(self):
        watch = realinput.Watch(devices=[], cursor_pos=lambda: None,
                                poll_s=0.01)
        self.assertEqual(watch.start(), "off")
        watch.arm()
        self.assertFalse(watch.yielded())   # graceful: just off

    def test_virtual_devices_are_filtered(self):
        with mock.patch.object(realinput.os, "listdir",
                               return_value=["event0", "event1",
                                             "event2", "mice"]), \
             mock.patch.object(realinput.os, "open",
                               side_effect=[11, 12, 13]), \
             mock.patch.object(
                 realinput, "_device_name",
                 side_effect=["ydotoold virtual device",
                              "AT Translated Set 2 keyboard",
                              "wlrctl"]), \
             mock.patch.object(realinput.os, "close") as closed:
            fds = realinput.real_devices("/fake")
        # the keyboard is the only real device; the uinput injector and
        # a wisp-owned source are filtered out; 'mice' isn't an eventN
        self.assertEqual(fds, [12])
        self.assertEqual(closed.call_count, 2)

    def test_begin_stays_off_for_non_drive_runs(self):
        self.assertEqual(realinput.begin({}), "off")
        self.assertEqual(realinput.begin(
            {"screen": {"dom_page": "p"},
             "pointer": {"mode": "drive"}}), "off")
        self.assertEqual(realinput.begin(
            {"pointer": {"mode": "guide"}}), "off")


class YieldMidDrive(_Iso):
    """A real-input event while a pointer op runs cancels the drive."""

    def test_mid_sequence_yield_skips_the_rest(self):
        # ydotool click = mousemove + click: a real event landing during
        # the move must stop the click argv from ever running
        with tempfile.TemporaryDirectory() as td:
            t = pathlib.Path(td)
            fifo = t / "event0"
            os.mkfifo(fifo)
            # O_RDWR: a read-only fifo with no writer EOFs instantly —
            # the reader (correctly) reaps EOF'd fds as unplugged
            # devices. A held-writer fd stays live like a real evdev node.
            rfd = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
            watch = realinput.Watch(devices=[rfd], poll_s=0.01)
            watch.start()
            log = t / "calls.log"
            bins = t / "bin"
            bins.mkdir()
            ydo = bins / "ydotool"
            # write the "human" event, then linger so the watch thread
            # has read it by the time the process exits
            # PATH is restricted to `bins`, so `sleep` must be linked in
            # — without it the linger silently fails, the stub exits at
            # once and the second argv races the watch thread's read
            sleep_bin = shutil.which("sleep")
            self.assertIsNotNone(sleep_bin)
            (bins / "sleep").symlink_to(sleep_bin)
            ydo.write_text(f'#!/bin/sh\necho "ydo $*" >> "{log}"\n'
                           f'printf x > "{fifo}"\nsleep 0.5\nexit 0\n')
            ydo.chmod(0o755)
            env = mock.patch.dict(os.environ, {
                "PATH": str(bins), "WISP_OS": "linux",
                "WISP_DESKTOP": "x11"})
            env.start()
            try:
                with mock.patch.object(realinput, "_WATCH", watch):
                    reg = pointer.Registry(DRIVE)
                    with self.assertRaises(cancel.Cancelled):
                        reg.click(10, 10, backend="ydotool")
            finally:
                env.stop()
                watch.close()
            lines = log.read_text().splitlines()
            # the move argv ran (that is the drive); the click argv did not
            self.assertEqual(len(lines), 1, lines)
            self.assertIn("mousemove", lines[0])

    def test_subsequent_dispatch_after_yield_refuses(self):
        r, w = os.pipe()
        watch = realinput.Watch(devices=[r], poll_s=0.01)
        watch.start()
        try:
            with mock.patch.object(realinput, "_WATCH", watch):
                watch.arm()
                os.write(w, b"\0" * 24)
                self.assertTrue(_wait(watch.yielded))
                reg = pointer.Registry(DRIVE)
                with self.assertRaises(cancel.Cancelled):
                    reg.click(1, 2, backend="guide")
                with self.assertRaises(cancel.Cancelled):
                    reg.move(1, 2, backend="guide")
        finally:
            watch.close()
            os.close(w)

    def test_yield_composes_with_the_loop_interrupt(self):
        """realinput.yielded() feeds the same interrupted() callback the
        user's Esc rides — the run ends INTERRUPTED like any stop."""
        fake = FakeWatch()
        calls = []

        def drive_then_yield(name, arg, cfg, harness=None):
            calls.append(name)
            fake._yield.set()       # a human grabbed the mouse mid-drive
            return "CLICKED"

        replies = [
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "c1", "type": "function",
                             "function": {"name": "click",
                                          "arguments":
                                          '{"arg": "10,20"}'}}]},
            {"role": "assistant", "content": "done"},
        ]
        cfg = {"agent": {}, "pointer": {"mode": "drive"}}
        with mock.patch.object(realinput, "_WATCH", fake), \
                mock.patch.object(platform, "active_window", return_value={
                    "class": "org.example.notes", "title": "Synthetic notes"}), \
                mock.patch.object(act, "_post", side_effect=replies), \
                mock.patch.object(tools, "run",
                                  side_effect=drive_then_yield):
            r = act.run_act_loop("click it", cfg, initial_image="aGk=")
        self.assertEqual(r, "INTERRUPTED (user)")
        self.assertEqual(calls, ["click"])
        self.assertGreaterEqual(fake.begun, 1)


class Blocked(_Iso):
    def test_blocked_tools_return_a_legible_refusal(self):
        for name in ("drag", "double_click", "right_click",
                     "mouse_down"):
            out = tools.run(name, "10,20", {})
            self.assertTrue(out.startswith("BLOCKED"), (name, out))
            self.assertIn("pointer", out)

    def test_blocked_never_gates_or_confirms(self):
        # safe tier → no checkpoint card for a call that can never run
        for name in system.BLOCKED_INPUT:
            self.assertEqual(tools.risk_of(name), "safe", name)
        # and the gate agrees — a blocked gesture must not prompt
        self.assertIsNone(
            act._gate("double_click", "10,20", {"agent": {}}, None))

    def test_action_text_gestures_parse_to_blocked_names(self):
        r = act._parse_action_text("Action: left_double(10, 20)")
        self.assertEqual(r["actions"], [("double_click", "left_double")])
        r = act._parse_action_text("Action: right_single(10, 20)")
        self.assertEqual(r["actions"], [("right_click", "right_single")])
        r = act._parse_action_text(
            "Action: drag(start_box='(1,2)', end_box='(3,4)')")
        self.assertEqual(r["actions"], [("drag", "drag")])


class AuditAndSteps(_Iso):
    def tearDown(self):
        delivery.clear()

    def test_audit_line_carries_delivery(self):
        with tempfile.TemporaryDirectory() as td:
            ap = pathlib.Path(td) / "cua.jsonl"
            with Rig(("ydotool",), hypr=False), system.pointer_context(
                    user_request="click at 10,20@logical"):
                g = cua_safety.Guard(DRIVE, audit_path=ap,
                                     turn="t1")
                r = g.run("click", "10,20",
                          lambda: system.click("10,20@logical", DRIVE))
                self.assertTrue(r.startswith("CLICKED"), r)
                self.assertEqual(g.last_delivery, "pointer")
                rows = [json.loads(l) for l in
                        ap.read_text().splitlines() if l.strip()]
            self.assertEqual(rows[-1]["delivery"], "pointer")
            self.assertEqual(rows[-1]["tool"], "click")

    def test_audit_refusal_records_planned_delivery(self):
        with tempfile.TemporaryDirectory() as td:
            ap = pathlib.Path(td) / "cua.jsonl"
            cfg = dict(DRIVE)
            cfg["cua"] = {"kill_switch": "true"}
            g = cua_safety.Guard(cfg, audit_path=ap, turn="t2")
            ran = []
            r = g.run("click", "10,20", lambda: ran.append(1))
            self.assertTrue(r.startswith("REFUSED"), r)
            self.assertEqual(ran, [])
            rows = [json.loads(l) for l in
                    ap.read_text().splitlines() if l.strip()]
            self.assertEqual(rows[-1]["decision"], "deny")
            self.assertIn(rows[-1]["delivery"],
                          ("guide", "pointer", "background"))
            self.assertEqual(g.last_delivery, rows[-1]["delivery"])

    def test_steps_and_stream_entries_carry_delivery(self):
        steps = []
        replies = [
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "c1", "type": "function",
                             "function": {"name": "type_text",
                                          "arguments":
                                          '{"arg": "hi"}'}}]},
            {"role": "assistant", "content": "done"},
        ]
        with mock.patch.object(act, "_post", side_effect=replies), \
                mock.patch.object(tools, "run", return_value="TYPED"):
            r = act.run_act_loop("type it", {"agent": {}},
                                 steps_out=steps)
        self.assertTrue(r.startswith("ACTED"), r)
        self.assertEqual(steps[0]["delivery"], "background")

    def test_escalation_is_recorded_in_the_step(self):
        # auto → the cua click would be background; delivery=pointer
        # escalates to the real-pointer backend — the record proves it
        steps = []
        replies = [
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "c1", "type": "function",
                             "function": {"name": "click",
                                          "arguments":
                                          '{"arg": "10,20@logical"}'}}]},
            {"role": "assistant", "content": "done"},
        ]
        with Rig():
            cfg = {"agent": {},
                   "pointer": {"mode": "drive", "backend": "auto"},
                   "cua": {"delivery": "pointer"}}
            # a FakeWatch: a real drift watch would read the actual
            # desktop cursor, which never moves on fake injectors
            with mock.patch.object(act, "_post", side_effect=replies), \
                    mock.patch.object(realinput, "_WATCH", FakeWatch()):
                r = act.run_act_loop("click it", cfg, steps_out=steps,
                                     initial_image="aGk=",
                                     user_request="click at 10,20@logical")
            self.assertTrue(r.startswith("ACTED"), r)
            self.assertEqual(steps[0]["delivery"], "pointer")


class ConfirmUnchanged(_Iso):
    def test_confirm_always_still_promotes(self):
        cfg = {"cua": {"confirm": "always", "delivery": "pointer"}}
        self.assertEqual(cua_safety.effective_tier("click", cfg),
                         "mutating")
        self.assertEqual(cua_safety.effective_tier("type_text", cfg),
                         "mutating")
        cfg["cua"]["delivery"] = "background"
        self.assertEqual(cua_safety.effective_tier("click", cfg),
                         "mutating")


if __name__ == "__main__":
    unittest.main()
