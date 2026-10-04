"""Pointer backend precedence with cua live vs dead (W1 integration).

Rules under test: cua (live daemon socket) wins for clicks and moves and
never touches Hyprland's cursor; a failed cua move falls to the Hyprland
socket eval; a failed cua click is NOT retried elsewhere; cua dead ->
move-only uses the socket eval, clicks use ydotool. All fakes: a stub
`cua-driver`/`ydotool` on PATH logging argv, a loopback unix socket
standing in for the cua daemon, and test_hypr's FakeHypr."""
import os
import pathlib
import socket
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_hypr import FakeHypr, ok_handler  # noqa: E402

from wisp import platform  # noqa: E402
from wisp.tools import system  # noqa: E402

CFG = {"pointer": {"mode": "drive", "backend": "auto"}}


class Rig:
    def __init__(self, cua_live: bool, cua_exit: int = 0):
        self.td = tempfile.TemporaryDirectory()
        t = pathlib.Path(self.td.name)
        self.bin = t / "bin"
        self.bin.mkdir()
        self.log = t / "calls.log"
        for name, code in (("cua-driver", cua_exit), ("ydotool", 0)):
            p = self.bin / name
            p.write_text(f'#!/bin/sh\necho "{name} $*" >> "{self.log}"\n'
                         f'exit {code}\n')
            p.chmod(p.stat().st_mode | stat.S_IXUSR)
        self.srv = None
        if cua_live:
            d = t / ".cache" / "cua-driver"
            d.mkdir(parents=True)
            self.srv = socket.socket(socket.AF_UNIX)
            self.srv.bind(str(d / "cua-driver.sock"))
        self.hypr = FakeHypr(ok_handler)
        self.env = mock.patch.dict(os.environ, {
            "HOME": self.td.name, "PATH": str(self.bin), "WISP_OS": "linux",
            "WISP_DESKTOP": "hyprland"})

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() \
            else []

    def cursor_evals(self):
        return [r for r in self.hypr.requests if "cursor.move" in r]

    def __enter__(self):
        self.hypr.__enter__()
        self.env.start()
        return self

    def __exit__(self, *a):
        self.env.stop()
        self.hypr.__exit__(*a)
        if self.srv:
            self.srv.close()
        self.td.cleanup()


class TestPrecedence(unittest.TestCase):
    def test_backend_selection(self):
        with Rig(True):
            self.assertEqual(platform.pointer_backend(CFG), "cua")
        with Rig(False):
            self.assertEqual(platform.pointer_backend(CFG), "ydotool")

    def test_cua_live_click_uses_cua_only(self):
        with Rig(True) as r:
            self.assertEqual(system.click("10,20@logical", CFG),
                             "CLICKED(10,20)")
            self.assertEqual(len(r.calls()), 1)
            self.assertTrue(r.calls()[0].startswith("cua-driver call click"))

    def test_cua_live_move_does_not_use_hypr_eval(self):
        with Rig(True) as r:
            self.assertEqual(system.move("5,6@logical", CFG), "MOVED(5,6)")
            self.assertTrue(r.calls()[0].startswith(
                "cua-driver call move_cursor"))
            self.assertEqual(r.cursor_evals(), [])

    def test_cua_dead_move_uses_hypr_eval(self):
        with Rig(False) as r:
            self.assertEqual(system.move("5,6@logical", CFG), "MOVED(5,6)")
            self.assertEqual(len(r.cursor_evals()), 1)
            self.assertEqual(r.calls(), [])

    def test_cua_dead_click_uses_ydotool(self):
        with Rig(False) as r:
            self.assertEqual(system.click("5,6@logical", CFG),
                             "CLICKED(5,6)")
            self.assertTrue(all(c.startswith("ydotool") for c in r.calls()))
            self.assertEqual(len(r.calls()), 2)  # move + click

    def test_failed_cua_move_falls_to_hypr_eval(self):
        with Rig(True, cua_exit=1) as r:
            self.assertEqual(system.move("5,6@logical", CFG), "MOVED(5,6)")
            self.assertEqual(len(r.cursor_evals()), 1)

    def test_failed_cua_click_is_not_retried(self):
        with Rig(True, cua_exit=1) as r:
            out = system.click("5,6@logical", CFG)
            self.assertEqual(out, "SKIP (click failed via cua)")
            self.assertEqual(len(r.calls()), 1)  # cua only, no ydotool
            self.assertEqual(r.cursor_evals(), [])


if __name__ == "__main__":
    unittest.main()


class TestHyprHealthRegistry(unittest.TestCase):
    """wispd registers hypr health on the U7 HealthRegistry."""

    def _wispd(self):
        import importlib.machinery
        import importlib.util
        path = str(pathlib.Path(__file__).resolve().parent.parent / "wispd")
        loader = importlib.machinery.SourceFileLoader("wispd_h", path)
        spec = importlib.util.spec_from_loader("wispd_h", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        return mod

    def test_registered_hook_reports_up_and_down(self):
        from wisp import health, hypr
        w = self._wispd()
        reg = health.HealthRegistry({}, jev_url="")
        reg.register("hypr", w._hypr_health)
        with Rig(False):
            hypr.reset()
            self.assertTrue(reg.probe("hypr")["ok"])
        with mock.patch.dict(os.environ, {"WISP_OS": "linux",
                                          "WISP_DESKTOP": "hyprland",
                                          "XDG_RUNTIME_DIR": "/nonexistent"}):
            hypr.reset()
            row = reg.probe("hypr")
            self.assertFalse(row["ok"])
            self.assertEqual(row["code"], "hypr_unavailable")
        hypr.reset()
