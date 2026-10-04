"""Pointer backend registry (W8): auto order with every live subset,
explicit pin, move falls through / click never retried, cancel,
coordinate pass-through, guide fallback. All fakes (W5)."""
import itertools
import os
import pathlib
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

from wisp import cancel, platform, pointer  # noqa: E402
from wisp.tools import system  # noqa: E402

DRIVE = {"pointer": {"mode": "drive", "backend": "auto"}}


def pin(name):
    return {"pointer": {"mode": "drive", "backend": name}}


class Rig:
    """live: subset of {cua, hyprctl, ydotool, wlrctl} present on PATH."""

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
            "HOME": self.td.name, "PATH": str(self.bins.path),
            "WISP_OS": "linux",
            "WISP_DESKTOP": "hyprland" if hypr else "x11"})

    def shell(self):
        return self.log.read_text().splitlines() if self.log.exists() \
            else []

    def evals(self):
        return [r for r in self.hypr.requests if "cursor.move" in r] \
            if self.hypr else []

    def __enter__(self):
        if self.hypr:
            self.hypr.__enter__()
        self.cua.start()
        self.env.start()
        return self

    def __exit__(self, *a):
        self.env.stop()
        self.cua.stop()
        if self.hypr:
            self.hypr.__exit__(*a)
        self.td.cleanup()


def expected_auto(live):
    if "cua" in live:
        return "cua"
    if "hyprctl" in live and "ydotool" in live:
        return "hyprcursor"
    for b in ("ydotool", "wlrctl"):
        if b in live:
            return b
    return None


class TestAutoOrder(unittest.TestCase):
    def test_every_subset(self):
        names = ("cua", "hyprctl", "ydotool", "wlrctl")
        for r in range(len(names) + 1):
            for live in itertools.combinations(names, r):
                with self.subTest(live=live), Rig(live, hypr=False):
                    reg = pointer.Registry(DRIVE)
                    b = reg.select()
                    self.assertEqual(b.name if b else None,
                                     expected_auto(set(live)))
                    # platform shim agrees (Rust parity tests use it)
                    self.assertEqual(platform.pointer_backend(DRIVE),
                                     expected_auto(set(live)))

    def test_registry_lists_backends_in_auto_order(self):
        self.assertEqual(pointer.Registry({}).names(),
                         ["cua", "hyprcursor", "ydotool", "wlrctl",
                          "guide"])

    def test_non_linux_is_none(self):
        with Rig():
            with mock.patch.dict(os.environ, {"WISP_OS": "macos"}):
                self.assertIsNone(pointer.Registry(DRIVE).select())

    def test_backend_none_pin(self):
        with Rig():
            self.assertIsNone(pointer.Registry(pin("none")).select())

    def test_unknown_pin_means_auto(self):
        with Rig():
            self.assertEqual(pointer.Registry(pin("bogus")).select().name,
                             "cua")


class TestPin(unittest.TestCase):
    def test_pin_wins_over_live_cua(self):
        with Rig():
            self.assertEqual(
                pointer.Registry(pin("wlrctl")).select().name, "wlrctl")
            self.assertEqual(
                pointer.Registry(pin("ydotool")).select().name, "ydotool")
            self.assertEqual(
                pointer.Registry(pin("hyprcursor")).select().name,
                "hyprcursor")

    def test_pin_to_unavailable_does_not_fall_through(self):
        with Rig(("ydotool",)):
            self.assertIsNone(pointer.Registry(pin("cua")).select())
            self.assertIsNone(pointer.Registry(pin("wlrctl")).select())

    def test_hyprcursor_needs_both_tools(self):
        with Rig(("hyprctl",)):
            self.assertIsNone(pointer.Registry(pin("hyprcursor")).select())

    def test_exclude_ignores_pin_and_walks_auto_order(self):
        with Rig():
            r = pointer.Registry(pin("cua"))
            self.assertEqual(r.select(exclude=("cua",)).name, "hyprcursor")
            self.assertEqual(
                r.select(exclude=("cua", "hyprcursor")).name, "ydotool")
        with Rig(("cua", "wlrctl")):
            self.assertEqual(
                pointer.Registry(DRIVE).select(exclude=("cua",)).name,
                "wlrctl")
        with Rig(("cua",)):
            self.assertIsNone(
                pointer.Registry(DRIVE).select(exclude=("cua",)))

    def test_pin_honoured_for_actions(self):
        with Rig() as r:
            out = pointer.Registry(pin("ydotool")).click(5, 6)
            self.assertTrue(out.ok)
            self.assertEqual(out.backend, "ydotool")
            self.assertEqual(r.cua.calls, [])


class TestCuaConfig(unittest.TestCase):
    def test_timeout_from_cfg_clamped(self):
        def t(v):
            return pointer.Registry({"cua": {"timeout_ms": v}}) \
                .get("cua").client.timeout_s
        self.assertEqual(t("1500"), 1.5)
        self.assertEqual(t("junk"), 0.8)
        self.assertEqual(t("5"), 0.1)
        self.assertEqual(t("999999"), 10.0)
        self.assertEqual(pointer.Registry({}).get("cua").client.timeout_s,
                         0.8)

    def test_default_config_has_cua_section(self):
        from wisp import config
        self.assertEqual(config._default_cfg_dict()["cua"]["timeout_ms"],
                         "800")
        self.assertIn("[cua]", config.DEFAULT_CONFIG)


class TestMetadata(unittest.TestCase):
    def test_capabilities_and_space(self):
        reg = pointer.Registry({})
        cua = reg.get("cua")
        self.assertIn("background", cua.capabilities)
        self.assertIn("no_focus_steal", cua.capabilities)
        self.assertEqual(cua.coordinate_space, "desktop")
        for n in ("hyprcursor", "ydotool", "wlrctl"):
            self.assertNotIn("no_focus_steal", reg.get(n).capabilities)
            self.assertEqual(reg.get(n).coordinate_space, "logical")
        self.assertFalse(reg.get("guide").drives)

    def test_health_shape(self):
        with Rig(("cua",)):
            h = pointer.Registry({}).get("cua").health()
            self.assertTrue(h["ok"])
            self.assertEqual(h["name"], "cua")
        with Rig(("ydotool",)):
            h = pointer.Registry({}).get("cua").health()
            self.assertFalse(h["ok"])
            self.assertTrue(h["detail"])


class TestMoveFallthrough(unittest.TestCase):
    CUA_FAIL = {"tools": {"default": {"ok": False,
                                      "error": "E_CUA_REFUSED"}}}

    def test_failed_cua_move_falls_to_hypr_eval(self):
        with Rig(cua_script=self.CUA_FAIL) as r:
            out = pointer.Registry(DRIVE).move(5, 6)
            self.assertTrue(out.ok)
            self.assertEqual(out.backend, "hypr")
            self.assertEqual(len(r.evals()), 1)
            self.assertEqual(len(r.cua.calls), 1)

    def test_failed_cua_move_off_hypr_uses_next_backend(self):
        with Rig(cua_script=self.CUA_FAIL, hypr=False) as r:
            out = pointer.Registry(DRIVE).move(5, 6)
            self.assertTrue(out.ok)
            self.assertEqual(out.backend, "hyprcursor")  # auto order
        with Rig(("cua", "ydotool"), cua_script=self.CUA_FAIL,
                 hypr=False) as r:
            out = pointer.Registry(DRIVE).move(5, 6)
            self.assertEqual(out.backend, "ydotool")
            self.assertEqual(len(r.shell()), 1)  # mousemove only

    def test_all_fail_reports_failure(self):
        with Rig(("cua",), cua_script=self.CUA_FAIL, hypr=False):
            out = pointer.Registry(DRIVE).move(5, 6)
            self.assertFalse(out.ok)

    def test_non_cua_move_uses_hypr_eval_on_hyprland(self):
        with Rig(("ydotool",)) as r:
            out = pointer.Registry(DRIVE).move(5, 6)
            self.assertTrue(out.ok)
            self.assertEqual(len(r.evals()), 1)
            self.assertEqual(r.shell(), [])

    def test_live_cua_move_never_touches_hypr(self):
        with Rig() as r:
            self.assertTrue(pointer.Registry(DRIVE).move(5, 6).ok)
            self.assertEqual(r.evals(), [])
            self.assertEqual(r.cua.tools(), ["move_cursor"])


class TestClickNoRetry(unittest.TestCase):
    def test_failed_cua_click_not_retried(self):
        with Rig(cua_script=TestMoveFallthrough.CUA_FAIL) as r:
            out = pointer.Registry(DRIVE).click(5, 6)
            self.assertFalse(out.ok)
            self.assertEqual(out.backend, "cua")
            self.assertEqual(len(r.cua.calls), 1)
            self.assertEqual(r.shell(), [])
            self.assertEqual(r.evals(), [])

    def test_timeout_click_not_retried(self):
        with Rig(cua_script={"tools": {"default": {"hang": True}}}) as r:
            reg = pointer.Registry(DRIVE)
            reg.get("cua").client.timeout_s = 0.3
            out = reg.click(5, 6)
            self.assertFalse(out.ok)
            self.assertEqual(r.shell(), [])

    def test_cua_down_click_not_retried_when_socket_stale(self):
        # stale socket: _cua_live true, daemon dead -> E_CUA_DOWN
        td = tempfile.TemporaryDirectory()
        t = pathlib.Path(td.name)
        bins = fakes.BinDir(t / "bin")
        cua = fakes.FakeCua(t, bins, {"mode": "stale"})
        ydo = bins.path / "ydotool"
        log = t / "log"
        ydo.write_text(f'#!/bin/sh\necho y >> "{log}"\n')
        ydo.chmod(0o755)
        with mock.patch.dict(os.environ, {
                "HOME": td.name, "PATH": str(bins.path),
                "WISP_OS": "linux", "WISP_DESKTOP": "x11"}):
            cua.start()
            try:
                out = pointer.Registry(DRIVE).click(1, 2)
            finally:
                cua.stop()
        td.cleanup()
        self.assertFalse(out.ok)
        self.assertEqual(out.backend, "cua")
        self.assertFalse(log.exists())

    def test_non_cua_click_runs_move_then_click(self):
        with Rig(("ydotool",)) as r:
            out = pointer.Registry(DRIVE).click(5, 6)
            self.assertTrue(out.ok)
            self.assertEqual(len(r.shell()), 2)
            self.assertIn("mousemove", r.shell()[0])


class TestCancel(unittest.TestCase):
    def test_cancelled_token_raises_and_calls_nothing(self):
        with Rig() as r:
            tok = cancel.CancelToken()
            tok.cancel()
            with cancel.bind(tok):
                with self.assertRaises(cancel.Cancelled):
                    pointer.Registry(DRIVE).click(1, 2)
                with self.assertRaises(cancel.Cancelled):
                    pointer.Registry(DRIVE).move(1, 2)
            self.assertEqual(r.cua.calls, [])
            self.assertEqual(r.shell(), [])

    def test_cancel_mid_move_does_not_fall_through(self):
        with Rig(cua_script={"tools": {"default": {"hang": True}}}) as r:
            tok = cancel.CancelToken()
            threading.Timer(0.3, tok.cancel).start()
            t0 = time.monotonic()
            reg = pointer.Registry(DRIVE)
            reg.get("cua").client.timeout_s = 10
            with cancel.bind(tok):
                with self.assertRaises(cancel.Cancelled):
                    reg.move(1, 2)
            self.assertLess(time.monotonic() - t0, 3)
            self.assertEqual(r.evals(), [])
            self.assertEqual(r.shell(), [])


class TestCoordinates(unittest.TestCase):
    def test_scale2_coordinates_pass_through_unchanged(self):
        # logical == desktop frame: registry never rescales
        with Rig() as r:
            pointer.Registry(DRIVE).click(1728, 1080)
            a = r.cua.calls[0]["args"]
            self.assertEqual((a["x"], a["y"]), (1728, 1080))
            self.assertEqual(a["coordinate_frame"], "desktop")
        with Rig(("ydotool",), hypr=False) as r:
            pointer.Registry(DRIVE).click(1728, 1080)
            self.assertIn("-x 1728 -y 1080", r.shell()[0])


class TestGuideFallback(unittest.TestCase):
    def test_no_backend_degrades_to_guide(self):
        with Rig((), hypr=False):
            self.assertIsNone(pointer.Registry(DRIVE).select())
            out = system.click("10,20@logical", DRIVE_MODE)
            self.assertEqual(out, "GUIDE(10,20) (no pointer backend)")
            out = system.move("10,20@logical", DRIVE_MODE)
            self.assertEqual(out, "MOVE-GUIDE(10,20) (no pointer backend)")

    def test_guide_backend_never_drives(self):
        g = pointer.Registry({}).get("guide")
        self.assertTrue(g.available())
        self.assertFalse(g.click(1, 2))


DRIVE_MODE = {"pointer": {"mode": "drive", "backend": "auto"}}


class TestShims(unittest.TestCase):
    def test_pointer_cmds_unchanged(self):
        import json
        c = platform.pointer_cmds(100, 200, "cua", click=True)[0]
        self.assertEqual(c[:3], ["cua-driver", "call", "click"])
        self.assertEqual(json.loads(c[3]), {
            "x": 100, "y": 200, "coordinate_frame": "desktop",
            "scope": "desktop"})
        self.assertEqual(platform.pointer_cmds(1, 2, "wlrctl", True),
                         [["wlrctl", "pointer", "move", "1", "2"],
                          ["wlrctl", "pointer", "click", "left"]])
        self.assertEqual(platform.pointer_cmds(1, 2, "bogus"), [])


if __name__ == "__main__":
    unittest.main()
