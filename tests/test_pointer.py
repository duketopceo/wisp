"""Guide-cursor pointer tools: arg parsing, guide/drive modes, backend."""
import json
import unittest
from unittest import mock

from wisp.tools import system
from wisp import platform, realinput


GUIDE_CFG = {"pointer": {"mode": "guide", "backend": "auto"}}
DRIVE_CFG = {"pointer": {"mode": "drive", "backend": "auto"}}
AUTO = {"pointer": {"mode": "auto", "backend": "auto"}}


class _Iso(unittest.TestCase):
    """Isolate the module-level realinput watch — other
    suites may leave it armed/yielded; pointer dispatches must
    see _WATCH absent unless the test installs one."""

    def setUp(self):
        realinput._stop_for_test()


class PointerTest(_Iso):

    def setUp(self):
        super().setUp()
        # no live compositor here: an unreadable layout is "on screen"
        p = mock.patch("wisp.points.monitors", return_value=[])
        p.start()
        self.addCleanup(p.stop)

    def test_parse_xy_screenshot(self):
        # legacy path: raw physical px (no magick to normalize)
        with mock.patch("wisp.points.monitors",
                        return_value=[{"x": 0, "y": 0, "width": 1000,
                                       "height": 500, "scale": 2}]), \
             mock.patch("wisp.points.img_space_is_logical",
                        return_value=False):
            # 200,100 px on a 2x monitor = 100,50 logical
            self.assertEqual(system._parse_xy("200,100"), (100, 50))

    def test_parse_xy_normalized(self):
        # normalized shot: image px == logical coords 1:1
        from wisp import points as _p
        _p.SHOT_ORIGIN = (0, 0)
        with mock.patch("wisp.points.monitors",
                        return_value=[{"x": 0, "y": 0, "width": 1000,
                                       "height": 500, "scale": 2}]), \
             mock.patch("wisp.points.img_space_is_logical",
                        return_value=True):
            self.assertEqual(system._parse_xy("200,100"), (200, 100))

    def test_parse_xy_logical(self):
        self.assertEqual(system._parse_xy("123,456@logical"), (123, 456))

    def test_parse_xy_bad(self):
        self.assertIsNone(system._parse_xy("nowhere"))
        self.assertIsNone(system._parse_xy(""))

    # two monitors side by side: 2x laptop (logical 1000x500) + 1x at x=1000
    MONS = [{"x": 0, "y": 0, "width": 2000, "height": 1000, "scale": 2},
            {"x": 1000, "y": 0, "width": 1920, "height": 1080,
             "scale": 1}]

    def test_on_screen_uses_logical_rects(self):
        from wisp import points
        self.assertTrue(points.on_screen(10, 20, self.MONS))
        self.assertTrue(points.on_screen(2500, 900, self.MONS))
        # right of the 2x monitor's logical width (1000) is the 2nd one;
        # below the 2x monitor's logical height (500) at x<1000 is nothing
        self.assertFalse(points.on_screen(500, 800, self.MONS))
        self.assertFalse(points.on_screen(-50, 10, self.MONS))
        self.assertFalse(points.on_screen(5000, 10, self.MONS))

    def test_on_screen_unknown_layout_never_vetoes(self):
        from wisp import points
        self.assertTrue(points.on_screen(99999, 99999, []))

    def test_offscreen_click_is_refused_not_driven(self):
        with mock.patch("wisp.points.monitors", return_value=self.MONS), \
             mock.patch("wisp.pointer.Registry") as reg:
            out = system.click("5000,10@logical", DRIVE_CFG)
        self.assertTrue(out.startswith("FAIL (5000,10 is off every screen"),
                        out)
        self.assertIn("re-aim", out)
        reg.assert_not_called()

    def test_offscreen_move_is_refused_in_guide_mode_too(self):
        with mock.patch("wisp.points.monitors", return_value=self.MONS):
            out = system.move("500,800@logical", GUIDE_CFG)
        self.assertTrue(out.startswith("FAIL (500,800 is off every"), out)

    def test_onscreen_click_still_goes_through(self):
        with mock.patch("wisp.points.monitors", return_value=self.MONS):
            self.assertEqual(system.click("1500,300@logical", GUIDE_CFG),
                             "GUIDE(1500,300)")

    def test_guide_mode_no_spawn(self):
        with mock.patch("subprocess.run") as run:
            out = system.click("10,20@logical", GUIDE_CFG)
        self.assertEqual(out, "GUIDE(10,20)")
        run.assert_not_called()

    def test_drive_without_backend_degrades_to_guide(self):
        with mock.patch.object(platform, "pointer_backend",
                               return_value=None):
            out = system.click("10,20@logical", DRIVE_CFG)
        self.assertTrue(out.startswith("GUIDE(10,20)"))
        self.assertIn("no pointer backend", out)

    def test_drive_with_backend_clicks(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return mock.Mock(returncode=0)

        with mock.patch.object(platform, "pointer_backend",
                               return_value="ydotool"), \
             mock.patch("subprocess.run", side_effect=fake_run), \
             system.pointer_context(user_request="click at 10,20@logical"):
            # This backend-argv fixture represents a literal human request.
            out = system.click("10,20@logical", DRIVE_CFG)
        self.assertEqual(out, "CLICKED(10,20)")
        self.assertEqual(len(calls), 2)  # move + click
        self.assertIn("mousemove", calls[0])

    def test_move_guide(self):
        self.assertEqual(system.move("5,6@logical", GUIDE_CFG),
                         "MOVE-GUIDE(5,6)")

    def test_auto_mode_drives_when_backend(self):
        # auto mode should behave like drive when a backend exists
        with mock.patch.object(platform, "pointer_backend",
                               return_value="wlrctl"), \
             mock.patch("subprocess.run",
                        return_value=mock.Mock(returncode=0)) as run, \
             system.pointer_context(user_request="click at 1,2@logical"):
            out = system.click("1,2@logical", AUTO)
        self.assertEqual(out, "CLICKED(1,2)")
        self.assertGreaterEqual(run.call_count, 1)

    def test_model_coordinate_without_element_never_reaches_backend(self):
        with mock.patch.object(platform, "pointer_backend",
                               return_value="ydotool"), \
             mock.patch("wisp.grounding.target_at_point", return_value=None), \
             mock.patch("subprocess.run") as run:
            out = system.click("10,20@logical", DRIVE_CFG)
        self.assertTrue(out.startswith("REFUSED"), out)
        run.assert_not_called()

    def test_explicit_backend_missing_falls_back(self):
        cfg = {"pointer": {"mode": "drive", "backend": "ydotool"}}
        with mock.patch.object(platform, "_which", return_value=False):
            self.assertIsNone(platform.pointer_backend(cfg))

    def test_backend_none_forces_guide(self):
        cfg = {"pointer": {"mode": "drive", "backend": "none"}}
        self.assertIsNone(platform.pointer_backend(cfg))
        self.assertTrue(system.click("1,2@logical", cfg)
                        .startswith("GUIDE"))

    def test_codegraph_usage(self):
        out = system.codegraph("bogus {}")
        self.assertIn("FAIL", out)

    def test_codegraph_bad_json(self):
        # Pin the binary as present. Without this the guard returns SKIP
        # on any host lacking codebase-memory-mcp (every CI runner), so
        # the test passed only on a developer box that had it.
        with mock.patch.object(system.shutil, "which",
                               return_value="/usr/local/bin/" + system._CBM_BIN):
            out = system.codegraph("search_graph not-json")
        self.assertIn("FAIL", out)

    def test_codegraph_skips_without_the_binary(self):
        with mock.patch.object(system.shutil, "which", return_value=None):
            self.assertIn("SKIP", system.codegraph("search_graph {}"))


if __name__ == "__main__":
    unittest.main()


class CuaBackend(_Iso):
    def test_explicit_cua_without_daemon_returns_none(self):
        cfg = {"pointer": {"mode": "drive", "backend": "cua"}}
        with mock.patch.object(platform, "_cua_live", return_value=False):
            self.assertIsNone(platform.pointer_backend(cfg))

    def test_explicit_cua_with_daemon(self):
        cfg = {"pointer": {"mode": "drive", "backend": "cua"}}
        with mock.patch.object(platform, "_cua_live", return_value=True):
            self.assertEqual(platform.pointer_backend(cfg), "cua")

    def test_auto_prefers_live_cua_over_hyprcursor(self):
        with mock.patch.object(platform, "_cua_live", return_value=True), \
             mock.patch.object(platform, "_which", return_value="/x"), \
             mock.patch.object(platform, "current", return_value="linux"):
            self.assertEqual(platform.pointer_backend({}), "cua")

    def test_auto_falls_to_hyprcursor_when_daemon_down(self):
        with mock.patch.object(platform, "_cua_live", return_value=False), \
             mock.patch.object(platform, "_which",
                               return_value="/x"), \
             mock.patch.object(platform, "current", return_value="linux"):
            self.assertEqual(platform.pointer_backend({}), "hyprcursor")

    def test_cua_click_cmd_shape(self):
        cmds = platform.pointer_cmds(100, 200, "cua", click=True)
        self.assertEqual(len(cmds), 1)
        c = cmds[0]
        self.assertEqual(c[:3], ["cua-driver", "call", "click"])
        args = json.loads(c[3])
        self.assertEqual(args["x"], 100)
        self.assertEqual(args["y"], 200)
        self.assertEqual(args["scope"], "desktop")
        self.assertEqual(args["coordinate_frame"], "desktop")

    def test_cua_move_uses_move_cursor(self):
        cmds = platform.pointer_cmds(10, 20, "cua", click=False)
        self.assertEqual(cmds[0][:3],
                         ["cua-driver", "call", "move_cursor"])
        self.assertEqual(json.loads(cmds[0][3])["scope"], "desktop")
