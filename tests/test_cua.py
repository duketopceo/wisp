"""Typed cua-driver client (W8): argv-only CLI wrapper, timeouts,
typed errors mapped to U7 codes, cancel. Uses the W5 FakeCua (daemon
socket + `cua-driver call` shim); never touches the real daemon."""
import json
import os
import pathlib
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import fakes  # noqa: E402

from wisp import cancel, cua, errors_codes  # noqa: E402


class Env:
    def __init__(self, script=None):
        self.td = tempfile.TemporaryDirectory()
        t = pathlib.Path(self.td.name)
        self.bins = fakes.BinDir(t / "bin")
        self.cua = fakes.FakeCua(t, self.bins, script or {})
        self.env = mock.patch.dict(os.environ, {
            "HOME": self.td.name, "PATH": str(self.bins.path)})

    def __enter__(self):
        self.cua.start()
        self.env.start()
        return self

    def __exit__(self, *a):
        self.env.stop()
        self.cua.stop()
        self.td.cleanup()


class TestCall(unittest.TestCase):
    def test_click_sends_desktop_frame_json_argv(self):
        with Env() as e:
            r = cua.Cua().click(100, 200)
            self.assertEqual(r["ok"], True)
            self.assertEqual(e.cua.calls[0]["tool"], "click")
            self.assertEqual(e.cua.calls[0]["args"], {
                "x": 100, "y": 200, "coordinate_frame": "desktop",
                "scope": "desktop"})

    def test_move_cursor_args(self):
        with Env() as e:
            cua.Cua().move_cursor(5, 6)
            self.assertEqual(e.cua.calls[0]["tool"], "move_cursor")
            self.assertEqual(e.cua.calls[0]["args"],
                             {"x": 5, "y": 6, "scope": "desktop"})

    def test_argv_only_no_shell_injection(self):
        # a hostile string is one JSON argv element, never shell text
        with Env() as e:
            evil = "a'; touch pwned; echo '"
            cua.Cua().call("get_window_state", {"title": evil})
            argv = e.bins.calls("cua-driver")[0]["argv"]
            self.assertEqual(argv[:2], ["call", "get_window_state"])
            self.assertEqual(json.loads(argv[2]), {"title": evil})
            self.assertEqual(len(argv), 3)
            self.assertFalse(pathlib.Path("pwned").exists())

    def test_non_integer_coordinates_rejected_before_spawn(self):
        with Env() as e:
            with self.assertRaises(ValueError):
                cua.Cua().click("1;rm -rf", 2)
            self.assertEqual(e.cua.calls, [])

    def test_tool_name_must_be_plain(self):
        with Env():
            with self.assertRaises(ValueError):
                cua.Cua().call("click; ls", {})
            with self.assertRaises(ValueError):
                cua.Cua().call("--socket", {})

    def test_window_helpers(self):
        with Env(script={"tools": {"default": {"result": {"windows": []}}}}) \
                as e:
            c = cua.Cua()
            c.list_windows()
            c.window_state(844, 6123)
            self.assertEqual(e.cua.tools(),
                             ["list_windows", "get_window_state"])
            self.assertEqual(e.cua.calls[1]["args"],
                             {"pid": 844, "window_id": 6123})


class TestErrors(unittest.TestCase):
    def test_down_stale_socket(self):
        with Env({"mode": "stale"}):
            with self.assertRaises(cua.CuaError) as cm:
                cua.Cua().click(1, 2)
        self.assertEqual(cm.exception.cua_code, "E_CUA_DOWN")
        self.assertEqual(cm.exception.code, "tool_failed")

    def test_down_binary_missing(self):
        with Env({"mode": "absent"}):
            with self.assertRaises(cua.CuaError) as cm:
                cua.Cua().click(1, 2)
        self.assertEqual(cm.exception.cua_code, "E_CUA_DOWN")

    def test_refused(self):
        with Env({"tools": {"default": {"ok": False,
                                        "error": "E_CUA_REFUSED"}}}):
            with self.assertRaises(cua.CuaError) as cm:
                cua.Cua().click(1, 2)
        self.assertEqual(cm.exception.cua_code, "E_CUA_REFUSED")
        self.assertEqual(cm.exception.code, "tool_failed")
        self.assertIsInstance(cm.exception, errors_codes.WispError)

    def test_other_tool_error_is_refused(self):
        with Env({"tools": {"default": {"ok": False,
                                        "error": "no such window"}}}):
            with self.assertRaises(cua.CuaError) as cm:
                cua.Cua().click(1, 2)
        self.assertEqual(cm.exception.cua_code, "E_CUA_REFUSED")

    def test_timeout_maps_to_timeout_code(self):
        with Env({"tools": {"default": {"hang": True}}}):
            t0 = time.monotonic()
            with self.assertRaises(cua.CuaError) as cm:
                cua.Cua(timeout_s=0.3).click(1, 2)
            self.assertLess(time.monotonic() - t0, 3)
        self.assertEqual(cm.exception.cua_code, "E_CUA_TIMEOUT")
        self.assertEqual(cm.exception.code, "timeout")

    def test_default_click_timeout_is_800ms(self):
        self.assertEqual(cua.Cua().timeout_s, 0.8)

    def test_malformed_json_strict(self):
        done = mock.Mock(returncode=0, stdout=b"<<not json>>", stderr=b"")
        with mock.patch("wisp.cancel.run", return_value=done):
            with self.assertRaises(cua.CuaError) as cm:
                cua.Cua().call("get_window_state", {})
        self.assertEqual(cm.exception.cua_code, "E_CUA_PROTOCOL")
        self.assertEqual(cm.exception.code, "tool_failed")

    def test_malformed_json_lenient_for_actions(self):
        # click/move trust the exit code: the real driver may print text
        done = mock.Mock(returncode=0, stdout=b"clicked", stderr=b"")
        with mock.patch("wisp.cancel.run", return_value=done):
            self.assertEqual(cua.Cua().click(1, 2), {})

    def test_stdout_text_error_on_nonzero(self):
        done = mock.Mock(returncode=1, stdout=b"",
                         stderr=b"Cua Driver daemon is not running.")
        with mock.patch("wisp.cancel.run", return_value=done):
            with self.assertRaises(cua.CuaError) as cm:
                cua.Cua().click(1, 2)
        self.assertEqual(cm.exception.cua_code, "E_CUA_DOWN")


class TestCancel(unittest.TestCase):
    def test_pre_cancelled_token_makes_no_call(self):
        with Env() as e:
            tok = cancel.CancelToken()
            tok.cancel()
            with cancel.bind(tok):
                with self.assertRaises(cancel.Cancelled):
                    cua.Cua().click(1, 2)
            self.assertEqual(e.cua.calls, [])

    def test_cancel_mid_call_is_not_a_timeout(self):
        with Env({"tools": {"default": {"hang": True}}}):
            tok = cancel.CancelToken()
            threading.Timer(0.3, tok.cancel).start()
            t0 = time.monotonic()
            with cancel.bind(tok):
                with self.assertRaises(cancel.Cancelled):
                    cua.Cua(timeout_s=10).click(1, 2)
            self.assertLess(time.monotonic() - t0, 3)


class TestAvailable(unittest.TestCase):
    def test_available_needs_binary_and_socket(self):
        with Env():
            self.assertTrue(cua.Cua().available())
        with Env({"mode": "absent"}):
            self.assertFalse(cua.Cua().available())

    def test_stale_socket_counts_as_available_but_down(self):
        # same contract as platform._cua_live: file presence only
        with Env({"mode": "stale"}):
            self.assertTrue(cua.Cua().available())


if __name__ == "__main__":
    unittest.main()
