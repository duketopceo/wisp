#!/usr/bin/env python3
"""Isolated runs: the real-input yield watch stays off, and compositor
queries / spawned tools never resolve the owner's live instance."""
import os
import pathlib
import sys
import tempfile
import unittest
import unittest.mock as mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import hypr, platform, realinput, stage_capture  # noqa: E402

ISO_CFG = {"dev": {"isolated_session": "true"},
           "pointer": {"mode": "drive"}}
LIVE_CFG = {"pointer": {"mode": "drive"}}


class WatchOffWhenIsolated(unittest.TestCase):
    def test_not_wanted_isolated(self):
        self.assertFalse(realinput._watch_wanted(ISO_CFG))
        self.assertFalse(realinput._drive_possible(ISO_CFG))

    def test_still_wanted_live(self):
        self.assertTrue(realinput._watch_wanted(LIVE_CFG))

    def test_begin_never_creates_watch_isolated(self):
        with mock.patch.object(realinput, "_watch") as w:
            self.assertEqual(realinput.begin(ISO_CFG), "off")
            w.assert_not_called()


class InstanceScopedEnv(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rd = pathlib.Path(self.tmp.name)
        live = self.rd / "hypr" / "LIVE"
        live.mkdir(parents=True)
        (live / ".socket.sock").touch()
        (self.rd / "wayland-0").touch()
        self.addCleanup(self.tmp.cleanup)

    def env(self, **kw):
        base = {"XDG_RUNTIME_DIR": str(self.rd), "WISP_ISOLATED_SESSION": "1"}
        base.update(kw)
        return mock.patch.dict(os.environ, base, clear=True)

    def test_sock_dir_no_live_fallback(self):
        with self.env(HYPRLAND_INSTANCE_SIGNATURE="ISO"):
            self.assertIsNone(hypr._sock_dir())

    def test_sock_dir_live_fallback_kept_when_not_isolated(self):
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.rd)},
                             clear=True):
            self.assertEqual(hypr._sock_dir().name, "LIVE")

    def test_platform_env_keeps_instance(self):
        with self.env(HYPRLAND_INSTANCE_SIGNATURE="ISO"):
            self.assertEqual(
                platform._env()["HYPRLAND_INSTANCE_SIGNATURE"], "ISO")

    def test_platform_env_does_not_guess_live(self):
        with self.env():
            self.assertNotIn("HYPRLAND_INSTANCE_SIGNATURE", platform._env())

    def test_hypr_env_passes_instance_not_live(self):
        with self.env(HYPRLAND_INSTANCE_SIGNATURE="ISO",
                      WAYLAND_DISPLAY="wayland-1"):
            e = stage_capture.hypr_env()
        self.assertEqual(e["HYPRLAND_INSTANCE_SIGNATURE"], "ISO")
        self.assertEqual(e["WAYLAND_DISPLAY"], "wayland-1")

    def test_hypr_env_does_not_guess_live(self):
        with self.env():
            e = stage_capture.hypr_env()
        self.assertNotIn("HYPRLAND_INSTANCE_SIGNATURE", e)
        self.assertNotIn("WAYLAND_DISPLAY", e)


if __name__ == "__main__":
    unittest.main()
