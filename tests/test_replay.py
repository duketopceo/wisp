#!/usr/bin/env python3
"""W5: replay harness with CUA, Hyprland, notify and systemctl fakes.

A fixture's ``fakes`` block selects which fakes a turn gets; the turn's
PATH is only the fake bin dir. Also covers fixture-relative path
resolution and the leak guard. Offline: loopback + temp dirs only."""
import copy
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import fakes  # noqa: E402
import harness_helpers as hh  # noqa: E402
from harness import runner  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "turns"


class CuaTurnTest(unittest.TestCase):
    def test_click_goes_through_cua_and_is_recorded(self):
        res = runner.run_turn(FIXTURES / "act_click_cua.json")
        self.assertEqual(res.exit_code, 0, res.stderr)
        self.assertEqual(runner.check_expectations(res), [])
        self.assertEqual(res.violations, [])
        calls = res.fake_calls["cua"]
        self.assertEqual([c["tool"] for c in calls],
                         ["start_session", "start_recording",
                          "list_windows", "list_windows", "get_window_state", "click",
                          "stop_recording"])
        click = next(c for c in calls if c["tool"] == "click")
        self.assertEqual(sum(c["tool"] == "click" for c in calls), 1)
        self.assertEqual((click["args"]["x"], click["args"]["y"]),
                         (10, 20))

    def test_element_free_model_point_stays_refused(self):
        fx = hh.load("act_click_cua")
        # Remove only the explicitly declared window/element evidence.
        # No fallback metadata is invented by the fake or the harness.
        fx["fakes"]["cua"] = {}
        res = runner.run_turn(fx)
        self.assertFalse(any(c["tool"] == "click"
                             for c in res.fake_calls["cua"]))
        self.assertIn("REFUSED (no element", "\n".join(res.final["steps"]))
        self.assertEqual(res.violations, [])

    def test_cua_stale_click_fails_without_retry(self):
        res = runner.run_turn(FIXTURES / "act_click_cua_down.json")
        self.assertEqual(res.exit_code, 0, res.stderr)
        self.assertEqual(runner.check_expectations(res), [])
        self.assertEqual(res.fake_calls["cua"], [])

    def test_refusal_is_scriptable(self):
        fx = hh.load("act_click_cua")
        fx["fakes"]["cua"]["tools"]["click"] = {
            "ok": False, "error": "E_CUA_REFUSED"}
        fx["expect"]["result_prefix"] = "ACTED"
        res = runner.run_turn(fx)
        self.assertEqual(res.exit_code, 0, res.stderr)
        self.assertEqual([c["tool"] for c in res.fake_calls["cua"]],
                         ["start_session", "start_recording",
                          "list_windows", "list_windows", "get_window_state", "click",
                          "stop_recording"])
        # the tool result the brain saw on its next call
        self.assertIn("SKIP (click failed via cua)",
                      json.dumps(res.chat_calls()[1]["body"]))



class HostInputTest(unittest.TestCase):
    """A replayed turn runs the real act loop, whose takeover check reads
    realinput's process-wide watch. That watch must never sense the
    host's keyboard, mouse or cursor: a person using the desktop during a
    local run would abort the turn with INTERRUPTED (user)."""

    def test_replay_ignores_host_input(self):
        from unittest import mock
        from wisp import realinput
        from harness import _child
        host_r, host_w = os.pipe()          # stands in for /dev/input
        self.addCleanup(os.close, host_w)
        cursor = iter(range(0, 10**6, 50))  # a mouse that keeps moving
        realinput._stop_for_test()
        self.addCleanup(realinput._stop_for_test)
        violations = []
        with mock.patch.object(realinput, "real_devices",
                               lambda *a, **k: [host_r]), \
                mock.patch.object(realinput, "_hypr_cursor_pos",
                                  lambda: (next(cursor), 0)), \
                mock.patch.object(realinput, "_create",
                                  realinput._create):
            _child.hermetic_realinput(violations)
            realinput.begin({"pointer": {"mode": "drive"}})
            realinput.arm()                  # a dispatch is in flight
            for _ in range(5):
                os.write(host_w, b"key")
                time.sleep(0.05)
            self.assertFalse(realinput.yielded(),
                             "host input reached the replay's watch")
            realinput.check()                # must not raise Cancelled
        self.assertEqual(violations, [])

    def test_seam_flags_any_host_input_read(self):
        from unittest import mock
        from wisp import realinput
        from harness import _child
        violations = []
        with mock.patch.object(realinput, "real_devices", lambda *a: []), \
                mock.patch.object(realinput, "_hypr_cursor_pos",
                                  lambda: None), \
                mock.patch.object(realinput, "_create", realinput._create):
            _child.hermetic_realinput(violations)
            self.assertEqual(realinput.real_devices(), [])
            self.assertIsNone(realinput._hypr_cursor_pos())
        self.assertEqual(len(violations), 2, violations)

    def test_drive_fixture_turn_reads_no_host_input(self):
        fx = hh.load("act_click_cua")
        self.assertIn(fx["config"]["pointer"]["mode"], ("drive", "auto"))
        res = runner.run_turn(fx)
        self.assertEqual(res.violations, [])
        self.assertTrue(res.final["result"].startswith("ACTED"),
                        res.final["result"])


class NotifyTurnTest(unittest.TestCase):
    def test_real_notify_path_hits_fake_send(self):
        res = runner.run_turn(FIXTURES / "act_click_cua.json")
        n = res.fake_calls["notify"]
        self.assertTrue(n, "pipeline.notify should reach notify-send")
        self.assertEqual(n[-1]["title"], "Wisp")
        self.assertTrue(n[-1]["body"].startswith("ACTED"))

    def test_seam_stub_when_not_declared(self):
        res = runner.run_turn(FIXTURES / "ask.json")
        self.assertNotIn("notify", res.fake_calls)
        self.assertTrue(res.notifications)


class HyprTurnTest(unittest.TestCase):
    def test_hypr_requests_recorded_and_active_window_real(self):
        fx = hh.load("act_click_cua")
        fx["fakes"]["hypr"] = {"replies": {"j/activewindow": {
            "class": "firefox", "title": "t", "address": "0x1",
            "workspace": {"id": 1, "name": "1"}}}}
        res = runner.run_turn(fx)
        self.assertEqual(res.exit_code, 0, res.stderr)
        self.assertTrue(res.fake_calls["hypr"])
        self.assertIn("j/activewindow", res.fake_calls["hypr"])


class SystemctlTurnDeclTest(unittest.TestCase):
    def test_declared_systemctl_is_on_path_and_recorded(self):
        fx = hh.load("ask")
        fx["fakes"] = {"systemctl": {"units": {
            "llama-local.service": "inactive"}}}
        res = runner.run_turn(fx)
        self.assertEqual(res.exit_code, 0, res.stderr)
        self.assertEqual(res.fake_calls["systemctl"], [])


class StrictPathTest(unittest.TestCase):
    def test_turn_path_is_only_the_fake_bin_dir(self):
        fx = hh.load("ask")
        fx["fakes"] = {"notify": {}}
        seen = hh.probe_child_env(fx)
        self.assertEqual(len(seen["PATH"].split(os.pathsep)), 1)
        self.assertTrue(seen["PATH"].endswith("fakebin"))
        self.assertEqual(seen["which_ls"], None)
        self.assertTrue(seen["which_notify"])
        self.assertIsNone(seen["which_cua"])

    def test_unknown_fake_is_rejected(self):
        fx = hh.load("ask")
        fx["fakes"] = {"dbus": {}}
        with self.assertRaises(ValueError):
            runner.run_turn(fx)

    def test_declared_fakes_never_leave_tempdir(self):
        res = runner.run_turn(FIXTURES / "act_click_cua.json")
        self.assertEqual(res.violations, [])
        self.assertTrue(res.tempdir)
        self.assertFalse(os.path.exists(res.tempdir))


class PathFixTest(unittest.TestCase):
    def test_relative_fixture_path_and_relative_wav(self):
        rel = os.path.relpath(FIXTURES / "ask.json", ROOT)
        old = os.getcwd()
        os.chdir(ROOT)
        try:
            res = runner.run_turn(rel)
        finally:
            os.chdir(old)
        self.assertEqual(res.exit_code, 0, res.stderr)
        self.assertEqual(runner.check_expectations(res), [])

    def test_fixture_relative_wav_from_other_cwd(self):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            fx = json.loads((FIXTURES / "ask.json").read_text())
            fx["audio"] = "wavs/ask.wav"
            (d / "wavs").mkdir()
            (d / "wavs" / "ask.wav").write_bytes(
                (FIXTURES / "ask.wav").read_bytes())
            (d / "fx.json").write_text(json.dumps(fx))
            old = os.getcwd()
            os.chdir(d)
            try:
                res = runner.run_turn("fx.json")
            finally:
                os.chdir(old)
            self.assertEqual(res.exit_code, 0, res.stderr)
            self.assertEqual(runner.check_expectations(res), [])

    def test_missing_wav_is_a_clear_error(self):
        fx = hh.load("ask")
        fx["audio"] = "nope.wav"
        with self.assertRaises(FileNotFoundError):
            runner.run_turn(fx)

    def test_cli_accepts_relative_path(self):
        r = subprocess.run(
            [sys.executable, "scripts/replay_turn.py",
             "tests/fixtures/turns/ask.json"], cwd=ROOT,
            capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_jsonl_scenarios_load_with_fixture_relative_audio(self):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            fx = json.loads((FIXTURES / "ask.json").read_text())
            fx["audio"] = "ask.wav"
            (d / "ask.wav").write_bytes((FIXTURES / "ask.wav").read_bytes())
            a, b = dict(fx, name="one"), dict(fx, name="two")
            (d / "s.jsonl").write_text(json.dumps(a) + "\n\n"
                                       + json.dumps(b) + "\n")
            rows = runner.load_fixtures(d / "s.jsonl")
            self.assertEqual([r["name"] for r in rows], ["one", "two"])
            res = runner.run_turn(rows[1])
            self.assertEqual(res.exit_code, 0, res.stderr)


class AllFixturesTest(unittest.TestCase):
    def test_every_fixture_meets_expectations(self):
        for p in sorted(FIXTURES.glob("*.json")):
            with self.subTest(fixture=p.name):
                res = runner.run_turn(p)
                self.assertEqual(res.exit_code, 0, res.stderr)
                self.assertEqual(runner.check_expectations(res), [])
                self.assertEqual(res.violations, [])


if __name__ == "__main__":
    unittest.main()
