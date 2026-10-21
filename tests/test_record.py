"""Turn-scoped cua recording (U1).

The act loop wraps a run in `start_recording`/`stop_recording` on the
stable "wisp" session label into `rec/<turn-id>/`; the driver writes a
`turn-NNNNN/` per dispatched action tool, and each mutating cua
dispatch is attributed to its dir by matching `action.json`
tool+args+timestamp. Non-cua mutating tools record `turn_dir: null` +
verdict `not_recorded`; read-only calls aren't recorded at all.

The cua boundary is faked at `wisp.cancel.run` — argv in,
CompletedProcess out — plus a fake driver that writes turn dirs like
the real one. Nothing here touches a live daemon.
"""
import json
import pathlib
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import act, cancel, cua, cua_safety, platform, realinput, \
    record, tools  # noqa: E402
from wisp import trace as _trace  # noqa: E402


def _msg(content=None, calls=None):
    msg = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = calls
    return msg


def _call(name, arg=""):
    return {"id": f"c_{name}_{arg[:8]}", "type": "function",
            "function": {"name": name,
                         "arguments": json.dumps({"arg": arg})}}


# drive mode on the cua backend, tools-capable brain with vision off so
# the loop never asks the fake tools.run for a screenshot
DRIVE = {"pointer": {"mode": "drive", "backend": "auto"},
         "brain": {"default": "lmstudio:fake"},
         "brain.lmstudio": {"tools": "true", "vision": "false",
                            "kind": "openai_compat",
                            "base_url": "http://127.0.0.1:1"}}


class FakeDriver:
    """`cua-driver call` boundary fake. Records argv, answers the
    session/recording control tools; `action()` simulates the daemon
    writing `turn-NNNNN/action.json` for a dispatched action tool."""

    def __init__(self, up=True):
        self.up = up
        self.argv = []          # [(tool, args)]
        self.rec_dir = None     # last start_recording output_dir
        self.seq = 0
        self.mints = 0
        self.starts = 0
        self.stops = 0

    def run(self, argv, **kw):
        # same contract as the real cancel.run — a cancelled bound
        # token kills the call before the child spawns
        cancel.check()
        if argv[:2] != ["cua-driver", "call"]:
            raise AssertionError(f"not a cua call: {argv}")
        if not self.up:
            raise OSError("cua-driver: daemon not running")
        tool = argv[2]
        args = json.loads(argv[3]) if len(argv) > 3 else {}
        self.argv.append((tool, args))
        if tool == "start_session":
            self.mints += 1
            return self._done({"active": True, "revived": False,
                               "session": args.get("session")})
        if tool == "start_recording":
            self.rec_dir = pathlib.Path(args["output_dir"])
            self.starts += 1
            return self._done({"recording": True})
        if tool == "stop_recording":
            self.stops += 1
            return self._done({"recording": False})
        if tool == "get_recording_state":
            return self._done({"recording": self.rec_dir is not None})
        return self._done({"tool": tool})

    @staticmethod
    def _done(result, rc=0):
        return subprocess.CompletedProcess(
            ["cua-driver"], rc,
            stdout=json.dumps(result).encode(), stderr=b"")

    def action(self, tool, x=None, y=None, ts=None):
        """Write `turn-NNNNN/action.json` under the live rec dir — what
        the real driver does per dispatched action (tool, args,
        action_truth, monotonic ms + epoch ts)."""
        assert self.rec_dir is not None
        self.seq += 1
        d = pathlib.Path(self.rec_dir) / f"turn-{self.seq:05d}"
        d.mkdir(parents=True, exist_ok=True)
        args = {"session": cua.SESSION, "scope": "desktop"}
        if x is not None:
            args["x"], args["y"] = x, y
        (d / "action.json").write_text(json.dumps({
            "tool": tool,
            "args": args,
            "action_truth": {
                "effect": "delivered", "route": "global_input",
                "transport": "linux_wayland_virtual_pointer",
                "refusal": None},
            "ts": time.time() if ts is None else ts,
            "ms": int(time.monotonic() * 1000)}))
        return d


class RecCase(unittest.TestCase):
    """Shared plumbing: cancel.run is the FakeDriver, trace writes to a
    temp file, record.REC_DIR is a temp root, realinput stays off."""

    UP = True

    def setUp(self):
        realinput._stop_for_test()
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        t = pathlib.Path(self.td.name)
        self.trace_file = t / "trace.jsonl"
        self.driver = FakeDriver(up=self.UP)
        self._patchers = [
            mock.patch("wisp.cancel.run", side_effect=self.driver.run),
            mock.patch.object(record, "REC_DIR", t / "rec"),
            mock.patch.object(_trace, "TRACE_FILE", self.trace_file),
            mock.patch.object(_trace, "_enabled", True),
            mock.patch.object(act.realinput, "begin",
                              return_value="off"),
            mock.patch.object(act, "_record_traj"),
            mock.patch.object(platform, "_cua_live", return_value=True),
            mock.patch.object(cua_safety, "audit_default_path",
                              return_value=t / "cua.jsonl"),
            mock.patch.object(cua_safety, "kill_default_path",
                              return_value=t / "cua.kill"),
        ]
        for p in self._patchers:
            p.start()
        self.addCleanup(self._unpatch)

    def _unpatch(self):
        for p in reversed(self._patchers):
            p.stop()

    def trace_events(self, step=None):
        evs = _trace.read(path=self.trace_file, tail=10000)
        return [e for e in evs if step is None or e["step"] == step]

    def run_loop(self, replies, cfg=None, turn="t-rec1", **kw):
        _trace.set_turn(turn)
        steps = []
        with mock.patch.object(act, "_post", side_effect=replies):
            out = act.run_act_loop("do it", cfg or DRIVE,
                                   steps_out=steps, **kw)
        return out, steps

    def fake_tools(self):
        """tools.run stand-in: click/move 'dispatch' a driver turn dir
        at dispatch time, like the real writer."""
        def run(name, arg, cfg, harness=None):
            if name == "click":
                x, y = (int(v) for v in arg.split("@")[0].split(",")[:2])
                self.driver.action("click", x, y)
                return f"CLICKED({x},{y})"
            if name == "move":
                x, y = (int(v) for v in arg.split("@")[0].split(",")[:2])
                self.driver.action("move_cursor", x, y)
                return f"MOVED({x},{y})"
            if name == "screenshot":
                return "SHOT /tmp/fake.png"
            return "TYPED" if name == "type_text" else "OK"
        return run


class TestSessionLabel(RecCase):
    def test_every_call_carries_the_session_label(self):
        c = cua.Cua()
        c.click(10, 20)
        c.move_cursor(1, 2)
        c.zoom(1, 0, 0, 5, 5)
        c.verify_state(1, 2, [{"window": {"exists": True}}])
        tools_ = [t for t, _ in self.driver.argv]
        self.assertEqual(tools_, ["click", "move_cursor", "zoom",
                                  "verify_state"])
        for _, args in self.driver.argv:
            self.assertEqual(args["session"], "wisp")

    def test_pointer_cmds_cua_argv_carries_session(self):
        cmds = platform.pointer_cmds(100, 200, "cua", click=True)
        args = json.loads(cmds[0][3])
        self.assertEqual(args["session"], "wisp")
        cmds = platform.pointer_cmds(10, 20, "cua", click=False)
        self.assertEqual(json.loads(cmds[0][3])["session"], "wisp")
        self.assertEqual(cmds[0][:3],
                         ["cua-driver", "call", "move_cursor"])

    def test_registry_click_argv_carries_session(self):
        from wisp import pointer
        out = pointer.Registry(DRIVE).click(5, 6)
        self.assertTrue(out.ok)
        tool, args = self.driver.argv[-1]
        self.assertEqual(tool, "click")
        self.assertEqual(args["session"], "wisp")

    def test_system_click_argv_carries_session(self):
        # end-to-end through the toolbelt: system.click -> registry ->
        # CuaBackend -> Cua.call — the label rides the whole path
        out = tools.run("click", "5,6@logical", DRIVE)
        self.assertEqual(out, "CLICKED(5,6)")
        tool, args = self.driver.argv[-1]
        self.assertEqual(tool, "click")
        self.assertEqual(args["session"], "wisp")


class TestLifecycle(RecCase):
    def test_start_stop_wrap_the_run(self):
        replies = [_msg(calls=[_call("click", "10,20@logical")]),
                   _msg(content="done")]
        with mock.patch.object(tools, "run",
                               side_effect=self.fake_tools()):
            out, steps = self.run_loop(replies)
        self.assertTrue(out.startswith("ACTED"), out)
        tools_seen = [t for t, _ in self.driver.argv]
        self.assertEqual(tools_seen[0], "start_session")
        self.assertEqual(tools_seen[1], "start_recording")
        self.assertEqual(tools_seen[-1], "stop_recording")
        self.assertEqual(self.driver.starts, 1)
        self.assertEqual(self.driver.stops, 1)
        # output dir is rec/<turn-id> and 0700
        rec_args = dict(self.driver.argv)["start_recording"]
        d = pathlib.Path(rec_args["output_dir"])
        self.assertEqual(d.name, "t-rec1")
        self.assertEqual(d.parent.name, "rec")
        self.assertEqual(stat.S_IMODE(d.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(d.parent.stat().st_mode), 0o700)

    def test_second_turn_gets_fresh_dir_same_label(self):
        for turn in ("t-first", "t-second"):
            replies = [_msg(content="done")]
            with mock.patch.object(tools, "run",
                                   side_effect=self.fake_tools()):
                self.run_loop(replies, turn=turn)
        starts = [a for t, a in self.driver.argv
                  if t == "start_recording"]
        self.assertEqual(len(starts), 2)
        self.assertTrue(starts[0]["output_dir"].endswith("rec/t-first"))
        self.assertTrue(starts[1]["output_dir"].endswith("rec/t-second"))
        for _, a in self.driver.argv:
            self.assertEqual(a.get("session"), "wisp")

    def test_cancellation_still_stops_recording(self):
        replies = [_msg(calls=[_call("click", "10,20@logical")]),
                   _msg(content="done")]

        def run(name, arg, cfg, harness=None):
            raise cancel.Cancelled()
        with mock.patch.object(tools, "run", side_effect=run):
            out, _ = self.run_loop(replies)
        self.assertEqual(out, "INTERRUPTED (user)")
        self.assertEqual(self.driver.stops, 1)

    def test_error_still_stops_recording(self):
        replies = [_msg(calls=[_call("click", "10,20@logical")]),
                   _msg(content="done")]

        def run(name, arg, cfg, harness=None):
            raise RuntimeError("boom")
        with mock.patch.object(tools, "run", side_effect=run):
            out, steps = self.run_loop(replies)
        self.assertEqual(self.driver.stops, 1)

    def test_bound_cancelled_token_still_reaches_stop(self):
        # the turn's cancel token is tripped mid-step: stop() must run
        # unbound so stop_recording still reaches the daemon — a call
        # under the dead token would raise Cancelled before spawning
        tok = cancel.CancelToken()

        def run(name, arg, cfg, harness=None):
            self.driver.action("click", 10, 20)
            tok.cancel()
            return "CLICKED(10,20)"
        replies = [_msg(calls=[_call("click", "10,20@logical")]),
                   _msg(content="done")]
        steps = []
        _trace.set_turn("t-cancel")
        with mock.patch.object(act, "_post", side_effect=replies), \
                mock.patch.object(tools, "run", side_effect=run), \
                cancel.bind(tok):
            out = act.run_act_loop("do it", DRIVE, steps_out=steps)
        self.assertTrue(out.startswith("INTERRUPTED"), out)
        self.assertEqual(self.driver.stops, 1)


class TestAttribution(RecCase):
    def test_two_mutating_calls_attribute_distinct_dirs(self):
        replies = [_msg(calls=[_call("click", "10,20@logical")]),
                   _msg(calls=[_call("move", "30,40@logical")]),
                   _msg(calls=[_call("click", "50,60@logical")]),
                   _msg(content="done")]
        with mock.patch.object(tools, "run",
                               side_effect=self.fake_tools()):
            out, steps = self.run_loop(replies)
        self.assertTrue(out.startswith("ACTED"), out)
        mutating = [s for s in steps if s["tool"] in ("click", "move")]
        self.assertEqual(len(mutating), 3)
        self.assertTrue(mutating[0]["turn_dir"].endswith("turn-00001"))
        self.assertTrue(mutating[1]["turn_dir"].endswith("turn-00002"))
        self.assertTrue(mutating[2]["turn_dir"].endswith("turn-00003"))
        for s in mutating:
            self.assertEqual(s["action_truth"]["effect"], "delivered")
            self.assertEqual(s["route"], "global_input")
            self.assertEqual(s["transport"],
                             "linux_wayland_virtual_pointer")
            self.assertNotIn("verdict", s)
        evs = self.trace_events("record_turn")
        self.assertEqual(len(evs), 3)
        self.assertTrue(evs[1]["data"]["turn_dir"]
                        .endswith("turn-00002"))

    def test_interleaved_move_cursor_never_misattributes(self):
        # step 3 is a second click AFTER the interleaved move — newest-
        # dir matching would hand it the move's turn-00002; tool+args
        # matching must not
        replies = [_msg(calls=[_call("click", "10,20@logical")]),
                   _msg(calls=[_call("move", "30,40@logical")]),
                   _msg(calls=[_call("click", "50,60@logical")]),
                   _msg(content="done")]
        with mock.patch.object(tools, "run",
                               side_effect=self.fake_tools()):
            out, steps = self.run_loop(replies)
        mutating = [s for s in steps if s["tool"] in ("click", "move")]
        self.assertTrue(mutating[1]["turn_dir"].endswith("turn-00002"))
        d2 = pathlib.Path(mutating[1]["turn_dir"]) / "action.json"
        self.assertEqual(json.loads(d2.read_text())["tool"],
                         "move_cursor")
        self.assertTrue(mutating[2]["turn_dir"].endswith("turn-00003"))
        d3 = pathlib.Path(mutating[2]["turn_dir"]) / "action.json"
        self.assertEqual(json.loads(d3.read_text())["tool"], "click")

    def test_late_dir_is_matched_by_bounded_wait(self):
        # dir appears ~250 ms after the dispatch reply — the matcher
        # polls for it rather than giving up instantly
        def run(name, arg, cfg, harness=None):
            x, y = (int(v) for v in arg.split("@")[0].split(",")[:2])
            at = time.time() + 0.25

            def later():
                self.driver.action("click", x, y, ts=at)
            threading.Timer(0.25, later).start()
            return f"CLICKED({x},{y})"
        replies = [_msg(calls=[_call("click", "10,20@logical")]),
                   _msg(content="done")]
        with mock.patch.object(tools, "run", side_effect=run):
            out, steps = self.run_loop(replies)
        step = steps[0]
        self.assertIsNotNone(step["turn_dir"])
        self.assertTrue(step["turn_dir"].endswith("turn-00001"))

    def test_read_only_calls_get_no_turn_dir(self):
        replies = [_msg(calls=[_call("screenshot")]),
                   _msg(calls=[_call("notify", "hi")]),
                   _msg(content="done")]
        with mock.patch.object(tools, "run",
                               side_effect=self.fake_tools()):
            out, steps = self.run_loop(replies)
        self.assertEqual(len(steps), 2)
        for s in steps:
            self.assertNotIn("turn_dir", s)
            self.assertNotIn("verdict", s)

    def test_non_cua_mutating_tool_is_not_recorded(self):
        # type_text/scroll go through wtype/ydotool — no turn dir
        # exists for them; the step records the explicit seed
        replies = [_msg(calls=[_call("type_text", "hi")]),
                   _msg(calls=[_call("scroll", "down")]),
                   _msg(content="done")]
        with mock.patch.object(tools, "run",
                               side_effect=self.fake_tools()):
            out, steps = self.run_loop(replies)
        for s in steps:
            self.assertIsNone(s["turn_dir"])
            self.assertEqual(s["verdict"], "not_recorded")
            self.assertNotIn("action_truth", s)


class TestDaemonDown(RecCase):
    UP = False

    def test_daemon_down_is_graceful_record_unavailable(self):
        replies = [_msg(calls=[_call("click", "10,20@logical")]),
                   _msg(content="done")]

        def run(name, arg, cfg, harness=None):
            return "CLICKED(10,20)"
        with mock.patch.object(tools, "run", side_effect=run):
            out, steps = self.run_loop(replies)
        self.assertTrue(out.startswith("ACTED"), out)
        self.assertEqual(self.driver.starts, 0)
        self.assertEqual(self.driver.stops, 0)
        self.assertIsNone(steps[0]["turn_dir"])
        self.assertEqual(steps[0]["verdict"], "not_recorded")
        evs = self.trace_events("record_unavailable")
        self.assertTrue(evs)


class TestSweep(RecCase):
    def test_orphan_dirs_are_discarded_with_event(self):
        root = pathlib.Path(record.REC_DIR)
        for turn in ("t-old1", "t-old2"):
            d = root / turn / "turn-00001"
            d.mkdir(parents=True)
            (d / "action.json").write_text("{}")
        stray = root / "stray.txt"
        stray.write_text("x")
        dropped = record.sweep_orphans()
        self.assertEqual(sorted(dropped), ["t-old1", "t-old2"])
        # orphan directories only — a stray file isn't a turn record
        self.assertEqual([p.name for p in root.iterdir()],
                         ["stray.txt"])
        evs = [e for e in self.trace_events("record")
               if e["data"].get("state") == "orphan_discarded"]
        self.assertEqual(len(evs), 2)

    def test_sweep_on_empty_root_is_quiet(self):
        self.assertEqual(record.sweep_orphans(), [])


class TestProbe(RecCase):
    def test_probe_live_driver(self):
        with mock.patch("wisp.probes_cua.CuaProbe.check",
                        return_value={"state": "running", "ok": True}):
            r = record.probe({})
        self.assertTrue(r["ok"])
        self.assertFalse(r.get("skipped", False))
        self.assertIn("start_session",
                      [t for t, _ in self.driver.argv])

    def test_probe_absent_is_skipped_not_failed(self):
        with mock.patch("wisp.probes_cua.CuaProbe.check",
                        return_value={"state": "absent", "ok": False}):
            r = record.probe({})
        self.assertTrue(r["skipped"])

    def test_probe_down_driver_reports_not_ok(self):
        with mock.patch("wisp.probes_cua.CuaProbe.check",
                        return_value={"state": "installed_not_running",
                                      "ok": False}):
            r = record.probe({})
        self.assertFalse(r["ok"])
        self.assertFalse(r.get("skipped", True))


class TestRecorderDirect(RecCase):
    def test_begin_stop_and_match(self):
        _trace.set_turn("t-direct")
        rec = record.begin("t-direct")
        self.assertTrue(rec.active)
        d = self.driver.action("click", 7, 8)
        hit = rec.match_turn("click", 7, 8, since=time.time() - 1)
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], d)
        # a claimed dir never matches twice
        self.assertIsNone(
            rec.match_turn("click", 7, 8, since=time.time() - 1,
                           wait_s=0.2))
        rec.stop()
        self.assertEqual(self.driver.stops, 1)
        self.assertFalse(rec.active)

    def test_match_filters_tool_and_coords(self):
        rec = record.begin("t-direct2")
        self.driver.action("move_cursor", 30, 40)
        # wrong tool -> no match
        self.assertIsNone(rec.match_turn("click", 30, 40,
                                         since=time.time() - 1,
                                         wait_s=0.1))
        # wrong coords -> no match
        self.assertIsNone(rec.match_turn("move_cursor", 99, 99,
                                         since=time.time() - 1,
                                         wait_s=0.1))
        hit = rec.match_turn("move_cursor", 30, 40,
                             since=time.time() - 1, wait_s=0.1)
        self.assertIsNotNone(hit)
        rec.stop()

    def test_match_ignores_dirs_older_than_dispatch(self):
        rec = record.begin("t-direct3")
        self.driver.action("click", 7, 8, ts=time.time() - 100)
        hit = rec.match_turn("click", 7, 8, since=time.time() - 1,
                             wait_s=0.1)
        self.assertIsNone(hit)
        rec.stop()


if __name__ == "__main__":
    unittest.main()
