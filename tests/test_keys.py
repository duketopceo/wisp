"""W24: keyboard submap and Esc stop.

The submap is generated Lua (golden files under tests/golden/keys/) sent
through the W7 registry in wisp/hypr.py; a fake Hyprland records what the
compositor would receive. Nothing here touches a live session."""
import json
import pathlib
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from fakes.hypr import FakeHypr  # noqa: E402
from wisp import cancel, config, hypr, ipc, keys, state as state_mod  # noqa: E402

GOLDEN = HERE / "golden" / "keys"
RUNNER = ["/usr/bin/python3", "/opt/wisp/wisp/fastkey.py",
          "--sock", "/run/user/1000/wisp/wispd.sock"]


def golden(name):
    return (GOLDEN / name).read_text()


def binds_handler(extra=()):
    def h(r):
        if r == "j/binds":
            return json.dumps([
                {"modmask": 64, "submap": "", "key": "D",
                 "description": "Display"}, *extra])
        return "ok"
    return h


class TestGeneration(unittest.TestCase):
    def test_modes(self):
        self.assertEqual(keys.mode_for("idle", 0), "")
        self.assertEqual(keys.mode_for("listening", 0), "")
        self.assertEqual(keys.mode_for("transcribing", 0), "")
        self.assertEqual(keys.mode_for("acting", 0), "stop")
        self.assertEqual(keys.mode_for("speaking", 0), "")
        self.assertEqual(keys.mode_for("awaiting_choice", 3), "choose:3")
        self.assertEqual(keys.mode_for("awaiting_choice", 20), "choose:9")
        self.assertEqual(keys.mode_for("awaiting_choice", 0), "stop")

    def test_stop_submap_golden(self):
        lua = hypr.define_submap_lua("wisp", keys.entries("stop", RUNNER))
        self.assertEqual(lua, golden("stop.lua"))

    def test_choose_submap_golden(self):
        lua = hypr.define_submap_lua("wisp",
                                     keys.entries("choose:3", RUNNER))
        self.assertEqual(lua, golden("choose3.lua"))

    def test_enter_leave_golden(self):
        self.assertEqual(hypr.enter_submap_lua("wisp"), golden("enter.lua"))
        self.assertEqual(hypr.leave_submap_lua(), golden("leave.lua"))

    def test_single_line_and_hostile_values_stay_in_literals(self):
        lua = hypr.define_submap_lua(
            "wisp", [hypr.SubmapBind("escape", ['x"); os.exit() --'])])
        self.assertNotIn("\n", lua)
        self.assertIn('x\\"); os.exit() --', lua)

    def test_bad_key_and_name_rejected(self):
        with self.assertRaises(ValueError):
            hypr.define_submap_lua("wisp", [hypr.SubmapBind('a")', ["x"])])
        with self.assertRaises(ValueError):
            hypr.define_submap_lua('w"', [hypr.SubmapBind("escape", ["x"])])

    def test_no_modifier_free_chords_only_inside_the_submap(self):
        # KTD6: never a bare key in the global map. Every generated bind
        # lives inside define_submap(...)
        lua = hypr.define_submap_lua("wisp", keys.entries("choose:9", RUNNER))
        self.assertTrue(lua.startswith('hl.define_submap("wisp", function()'))
        self.assertEqual(lua.count("hl.define_submap("), 1)
        self.assertEqual(lua.count("hl.bind("), 11)  # esc, return, 1..9


class TestRegistry(unittest.TestCase):
    def setUp(self):
        hypr.reset_binds()
        self.addCleanup(hypr.reset_binds)

    def test_conflict_with_foreign_wisp_submap_is_reported_not_clobbered(self):
        foreign = {"modmask": 0, "submap": "wisp", "key": "escape",
                   "description": "my own thing"}
        with FakeHypr(binds_handler([foreign])) as f, \
             mock.patch("atexit.register"):
            with self.assertRaises(hypr.HyprError) as cm:
                hypr.define_submap("wisp", keys.entries("stop", RUNNER))
        self.assertEqual(cm.exception.code, "bind_clash")
        self.assertEqual([e for e in f.evals() if "define_submap" in e], [])

    def test_own_stale_binds_are_not_a_conflict(self):
        own = {"modmask": 0, "submap": "wisp", "key": "escape",
               "description": "wisp:sub:wisp:escape"}
        with FakeHypr(binds_handler([own])) as f, \
             mock.patch("atexit.register"):
            h = hypr.define_submap("wisp", keys.entries("stop", RUNNER))
        self.assertTrue(h.startswith("wisp:"))
        self.assertEqual(len([e for e in f.evals() if "define_submap" in e]),
                         1)

    def test_other_submaps_are_ignored(self):
        other = {"modmask": 0, "submap": "resize", "key": "escape",
                 "description": "resize exit"}
        with FakeHypr(binds_handler([other])), mock.patch("atexit.register"):
            hypr.define_submap("wisp", keys.entries("stop", RUNNER))

    def test_shutdown_leaves_the_submap(self):
        with FakeHypr(binds_handler()) as f, mock.patch("atexit.register"):
            h = hypr.define_submap("wisp", keys.entries("stop", RUNNER))
            hypr.enter_submap(h)
            hypr.shutdown()
        self.assertEqual(f.evals()[-1], "eval " + golden("leave.lua"))
        self.assertEqual(hypr.active_submaps(), {})


class TestKeysController(unittest.TestCase):
    def setUp(self):
        hypr.reset_binds()
        self.addCleanup(hypr.reset_binds)
        self.logs = []
        self.f = FakeHypr(binds_handler())
        self.f.__enter__()
        self.addCleanup(self.f.__exit__)
        p = mock.patch("atexit.register")
        p.start()
        self.addCleanup(p.stop)
        self.k = keys.Keys(runner=RUNNER, log=self.logs.append)

    def evals(self):
        return [e[5:] for e in self.f.evals()]

    def test_start_clears_a_stale_submap_once(self):
        self.k.start()
        self.assertEqual(self.evals(), [golden("leave.lua")])

    def test_entering_awaiting_choice_registers_and_enters(self):
        self.k.sync("awaiting_choice", 3)
        ev = self.evals()
        self.assertEqual(ev, [golden("choose3.lua"), golden("enter.lua")])

    def test_same_state_twice_is_one_registration(self):
        self.k.sync("awaiting_choice", 3)
        self.k.sync("awaiting_choice", 3)
        self.assertEqual(len(self.evals()), 2)

    def test_acting_is_stop_only(self):
        self.k.sync("acting", 0)
        self.assertEqual(self.evals(),
                         [golden("stop.lua"), golden("enter.lua")])

    def test_choice_to_acting_redefines_stop_only(self):
        self.k.sync("awaiting_choice", 3)
        n = len(self.evals())
        self.k.sync("acting", 0)
        ev = self.evals()[n:]
        self.assertEqual(ev, [golden("leave.lua"), golden("stop.lua"),
                              golden("enter.lua")])

    def test_exit_on_idle_and_not_twice(self):
        self.k.sync("acting", 0)
        n = len(self.evals())
        self.k.sync("idle", 0)
        self.assertEqual(self.evals()[n:], [golden("leave.lua")])
        self.k.sync("idle", 0)
        self.k.sync("done", 0)
        self.assertEqual(len(self.evals()), n + 1)
        self.assertFalse(self.k.active)

    def test_non_binding_states_never_touch_hyprland(self):
        for s in ("listening", "transcribing", "deciding", "speaking",
                  "idle", "done", "error"):
            self.k.sync(s, 0)
        self.assertEqual(self.evals(), [])

    def test_conflict_is_reported_and_turn_goes_on(self):
        self.f.handler = binds_handler([{
            "modmask": 0, "submap": "wisp", "key": "escape",
            "description": "someone else"}])
        self.k.sync("acting", 0)
        self.assertFalse(self.k.active)
        self.assertEqual(self.k.conflicts[0]["key"], "escape")
        self.assertTrue(any("conflict" in m for m in self.logs))
        self.assertEqual([e for e in self.evals() if "define_submap" in e], [])

    def test_eval_failure_is_logged_not_raised(self):
        self.f.handler = lambda r: ("error: no" if r.startswith("eval")
                                    else binds_handler()(r))
        self.k.sync("acting", 0)
        self.assertFalse(self.k.active)
        self.assertTrue(any("submap" in m for m in self.logs))

    def test_suspended_leaves_for_a_key_step_then_returns(self):
        self.k.sync("acting", 0)
        n = len(self.evals())
        with self.k.suspended():
            self.assertFalse(self.k.active)
            self.assertEqual(self.evals()[n:], [golden("leave.lua")])
        self.assertTrue(self.k.active)
        self.assertEqual(self.evals()[-1], golden("enter.lua"))

    def test_suspended_when_idle_is_a_noop(self):
        with self.k.suspended():
            pass
        self.assertEqual(self.evals(), [])

    def test_stop_leaves(self):
        self.k.sync("acting", 0)
        self.k.stop()
        self.assertEqual(self.evals()[-1], golden("leave.lua"))

    def test_bus_driven(self):
        td = tempfile.mkdtemp()
        bus = state_mod.StateBus(state_file=pathlib.Path(td) / "s.json")
        self.addCleanup(bus.close)
        th = self.k.attach(bus)
        self.addCleanup(self.k.detach)
        bus.transition("acting")
        self._until(lambda: self.k.active)
        bus.transition("idle")
        self._until(lambda: not self.k.active)
        self.assertEqual(self.evals()[-1], golden("leave.lua"))

    def _until(self, fn, timeout=2.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end and not fn():
            time.sleep(0.005)
        self.assertTrue(fn())


class TestKeySuspendHook(unittest.TestCase):
    def test_key_tool_step_runs_inside_suspended(self):
        from wisp.tools import system
        seen = []

        class K:
            def suspended(self):
                import contextlib

                @contextlib.contextmanager
                def cm():
                    seen.append("leave")
                    yield
                    seen.append("enter")
                return cm()
        with mock.patch.object(keys, "ACTIVE", K()), \
             mock.patch.object(system._cancel, "run",
                               side_effect=lambda *a, **k: seen.append("run")
                               or mock.Mock(returncode=0)):
            self.assertEqual(system.key("esc"), "KEY")
        self.assertEqual(seen, ["leave", "run", "enter"])


class TestEscStopsWithinBudget(unittest.TestCase):
    """Harness: the exact command the Esc bind runs, executed as a real
    process against a real daemon handler, cancels the in-flight turn
    inside the W9 stop budget (150 ms) measured key to cancelled."""

    BUDGET_S = 0.150

    def setUp(self):
        hypr.reset_binds()
        self.addCleanup(hypr.reset_binds)
        self.td = pathlib.Path(tempfile.mkdtemp(prefix="wk-"))
        self.sock = self.td / "w.sock"

    def esc_argv(self, k):
        with FakeHypr(binds_handler()) as f, mock.patch("atexit.register"):
            k.sync("acting", 0)
            define = [e for e in f.evals() if "define_submap" in e][0]
        m = re.search(r'hl\.bind\("escape".*?exec_cmd\("((?:[^"\\]|\\.)*)"\)',
                      define)
        self.assertIsNotNone(m, define)
        return shlex.split(m.group(1).replace('\\"', '"'))

    def test_esc_cancels_the_turn_within_150ms(self):
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader(
            "wispd_keys", str(ROOT / "wispd"))
        spec = importlib.util.spec_from_loader("wispd_keys", loader)
        w = importlib.util.module_from_spec(spec)
        loader.exec_module(w)
        bus = state_mod.StateBus(state_file=self.td / "state.json")
        self.addCleanup(bus.close)
        ctl = {"stop": threading.Event(), "busy": threading.Event(),
               "interrupt": threading.Event(), "rec": None,
               "rec_lock": threading.Lock(),
               "choice_event": threading.Event(), "choice_pick": ""}
        token = cancel.CancelToken()
        ctl["token"] = token
        # an in-flight child the cancel path must kill (a cua call)
        child = subprocess.Popen(["sleep", "30"])
        self.addCleanup(child.kill)
        token.register_pid(child)
        bus.transition("acting")
        srv = ipc.Daemon(w._handler(bus, {}, ctl), sock_file=self.sock)
        srv.start()
        self.addCleanup(srv.stop)
        k = keys.Keys(runner=keys.runner_for(self.sock))
        argv = self.esc_argv(k)
        self.assertTrue(argv[-1] == "interrupt", argv)
        t = time.monotonic()
        r = subprocess.run(argv, capture_output=True, timeout=5)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(token.wait(1.0))
        took = time.monotonic() - t
        self.assertLess(took, self.BUDGET_S,
                        f"Esc to cancelled took {took * 1000:.0f} ms")
        deadline = time.monotonic() + 1
        while child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertIsNotNone(child.poll())
        self.assertTrue(ctl["interrupt"].is_set())

    def test_fastkey_choice_sends_index(self):
        got = []
        srv = ipc.Daemon(lambda c: got.append(c) or {"ok": True},
                         sock_file=self.sock)
        srv.start()
        self.addCleanup(srv.stop)
        argv = keys.runner_for(self.sock) + ["choice", "2"]
        r = subprocess.run(argv, capture_output=True, timeout=5)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(got, [{"cmd": "choice", "pick": "", "index": 2}])

    def test_fastkey_exits_nonzero_without_a_daemon(self):
        r = subprocess.run(keys.runner_for(self.td / "none.sock")
                           + ["interrupt"], capture_output=True, timeout=5)
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
