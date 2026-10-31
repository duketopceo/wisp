#!/usr/bin/env python3
"""Dev tuning mode U1: the session switch (state file, five-run counter,
`dev` IPC command, `wispd dev on|off|status`, state field, tracing)."""
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import sys
import threading
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import shorttmp  # noqa: E402
from wisp import config, devsession, ipc, state as state_mod, trace  # noqa: E402


def _load_wispd():
    loader = importlib.machinery.SourceFileLoader(
        "wispd_devsession_test", str(ROOT / "wispd"))
    spec = importlib.util.spec_from_loader("wispd_devsession_test", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


WISPD = _load_wispd()


class Base(unittest.TestCase):
    def setUp(self):
        td = shorttmp.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.dir = pathlib.Path(td.name)
        p = mock.patch.object(config, "DATA_DIR", self.dir)
        p.start()
        self.addCleanup(p.stop)


class TestSession(Base):
    def test_off_by_default(self):
        s = devsession.status()
        self.assertFalse(s["on"])
        self.assertEqual(s["runs_done"], 0)
        self.assertEqual(s["max_runs"], 5)

    def test_on_status_off_round_trip(self):
        s = devsession.turn_on()
        self.assertTrue(s["on"])
        self.assertEqual(s["runs_left"], 5)
        self.assertTrue(s["started_at"])
        self.assertTrue(devsession.is_on())
        self.assertTrue(devsession.status()["on"])
        s = devsession.turn_off()
        self.assertFalse(s["on"])
        self.assertFalse(devsession.is_on())

    def test_on_again_keeps_the_count(self):
        devsession.turn_on()
        devsession.complete_run()
        s = devsession.turn_on()
        self.assertEqual(s["runs_done"], 1)

    def test_turning_on_after_off_starts_a_fresh_count(self):
        devsession.turn_on()
        devsession.complete_run()
        devsession.turn_off()
        s = devsession.turn_on()
        self.assertEqual(s["runs_done"], 0)
        self.assertEqual(s["runs_left"], 5)

    def test_fifth_completed_run_turns_the_session_off(self):
        devsession.turn_on()
        for i in range(1, 5):
            s = devsession.complete_run()
            self.assertTrue(s["on"], i)
            self.assertEqual(s["runs_left"], 5 - i)
        s = devsession.complete_run()
        self.assertFalse(s["on"])
        self.assertEqual(s["runs_done"], 5)
        self.assertFalse(devsession.is_on())

    def test_complete_run_with_session_off_changes_nothing(self):
        s = devsession.complete_run()
        self.assertFalse(s["on"])
        self.assertEqual(s["runs_done"], 0)

    def test_file_is_written_atomically_as_json(self):
        devsession.turn_on()
        f = self.dir / "dev_session.json"
        self.assertEqual(json.loads(f.read_text())["on"], True)
        self.assertEqual(list(self.dir.glob("*.tmp")), [])

    def test_corrupt_file_reads_as_off(self):
        (self.dir / "dev_session.json").write_text("{nope")
        self.assertFalse(devsession.is_on())

    def test_never_writes_config(self):
        cfgfile = self.dir / "config.toml"
        cfgfile.write_text("[debug]\ntrace = false\n")
        with mock.patch.object(config, "CFG_FILE", cfgfile):
            devsession.turn_on()
            devsession.complete_run()
            devsession.turn_off()
        self.assertEqual(cfgfile.read_text(), "[debug]\ntrace = false\n")


class TestTracing(Base):
    def test_session_forces_trace_on_then_restores_owner_setting(self):
        with mock.patch.object(trace, "_enabled", False):
            self.assertFalse(trace._cfg_flag())
            devsession.turn_on()
            self.assertTrue(trace._cfg_flag())
            devsession.turn_off()
            self.assertFalse(trace._cfg_flag())


class TestState(Base):
    def test_state_snapshot_has_dev_field(self):
        st = state_mod.State(state_file=self.dir / "state.json",
                             write_initial=False)
        self.assertEqual(st.snapshot()["dev"], {"on": False, "runs_left": 0})

    def test_publish_dev(self):
        bus = state_mod.StateBus(state_file=self.dir / "state.json",
                                 autostart=False)
        self.addCleanup(bus.close)
        bus.publish(None, dev={"on": True, "runs_left": 5})
        self.assertEqual(bus.snapshot()["dev"],
                         {"on": True, "runs_left": 5})


class TestIpc(Base):
    def setUp(self):
        super().setUp()
        self.st = state_mod.StateBus(state_file=self.dir / "state.json",
                                     autostart=False)
        self.addCleanup(self.st.close)
        self.ctl = {"stop": threading.Event(), "busy": threading.Event(),
                    "interrupt": threading.Event(),
                    "choice_event": threading.Event(), "choice_pick": "",
                    "broker": None, "token": None, "rec": None,
                    "rec_lock": threading.Lock()}
        self.handle = WISPD._handler(
            self.st, config._default_cfg_dict(), self.ctl,
            tasks_file=self.dir / "tasks.jsonl")
        # Direct handler tests represent the local, native-attributed caller.
        # Missing peer identity intentionally cannot mutate daemon state.
        self.peer = {"pid": os.getpid(), "uid": os.getuid()}

    def test_dev_is_mutating(self):
        self.assertIn("dev", ipc.MUTATING_CMDS)
        self.assertIn("dev_run", ipc.MUTATING_CMDS)
        self.assertIn("dev_stop", ipc.MUTATING_CMDS)

    def test_on_status_off_over_ipc_and_state_publishes(self):
        r = self.handle({"cmd": "dev", "op": "on"}, self.peer)
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["dev"]["on"])
        self.assertEqual(self.st.snapshot()["dev"],
                         {"on": True, "runs_left": 5})
        r = self.handle({"cmd": "dev", "op": "status"}, self.peer)
        self.assertTrue(r["dev"]["on"])
        r = self.handle({"cmd": "dev", "op": "off"}, self.peer)
        self.assertFalse(r["dev"]["on"])
        self.assertEqual(self.st.snapshot()["dev"],
                         {"on": False, "runs_left": 0})

    def test_unknown_op_is_an_error(self):
        r = self.handle({"cmd": "dev", "op": "sideways"}, self.peer)
        self.assertFalse(r["ok"])

    def test_off_never_touches_config(self):
        cfgfile = self.dir / "config.toml"
        cfgfile.write_text("[dev]\npanel = \"false\"\n")
        with mock.patch.object(config, "CFG_FILE", cfgfile):
            self.assertTrue(self.handle(
                {"cmd": "dev", "op": "on"}, self.peer)["ok"])
            self.assertTrue(self.handle(
                {"cmd": "dev", "op": "off"}, self.peer)["ok"])
        self.assertEqual(cfgfile.read_text(), "[dev]\npanel = \"false\"\n")


if __name__ == "__main__":
    unittest.main()
