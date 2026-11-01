"""The stdlib zwlr_virtual_pointer_v1 client, against a fake socket."""
import os
import pathlib
import struct
import time
import unittest

import shorttmp  # tests/ is on sys.path (unittest discover -s tests)

from fakes.wayland import FakeWayland, GLOBALS
from wisp import vpointer

BTN_LEFT = 0x110


class VPointerWire(unittest.TestCase):
    def setUp(self):
        td = shorttmp.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.dir = pathlib.Path(td.name)
        self.path = str(self.dir / "wl-test")

    def server(self, **kw):
        s = FakeWayland(self.path, **kw).start()
        self.addCleanup(s.stop)
        return s

    def test_click_sends_the_expected_wire_messages(self):
        s = self.server()
        vpointer.click(100, 200, (1728, 1080), path=self.path)
        reqs = s.requests
        names = [(o, r) for o, r, _a in reqs]
        # registry bind of seat + manager, then the pointer is created
        self.assertEqual(names[0], ("wl_display", "get_registry"))
        binds = [a for o, r, a in reqs if r == "bind"]
        self.assertEqual([b[0] for b in binds],
                         ["wl_seat", "zwlr_virtual_pointer_manager_v1"])
        create = [a for o, r, a in reqs if r == "create_virtual_pointer"]
        self.assertEqual(len(create), 1)
        self.assertEqual(create[0][0], "wl_seat")
        vp = [(r, a) for o, r, a in reqs
              if o == "zwlr_virtual_pointer_v1"]
        kinds = [r for r, _ in vp]
        self.assertEqual(kinds[:6], ["motion_absolute", "frame", "button",
                                     "frame", "button", "frame"])
        ma = vp[0][1]
        self.assertEqual(ma[1:], (100, 200, 1728, 1080))
        self.assertEqual(vp[2][1][1:], (BTN_LEFT, 1))     # pressed
        self.assertEqual(vp[4][1][1:], (BTN_LEFT, 0))     # released

    def test_origin_offsets_the_absolute_point(self):
        s = self.server()
        vpointer.move(3500, 100, (6896, 2160), origin=(0, 0),
                      path=self.path)
        vpointer.move(10, 10, (500, 400), origin=(-100, -50),
                      path=self.path)
        ma = [a for o, r, a in s.requests if r == "motion_absolute"]
        self.assertEqual(ma[0][1:], (3500, 100, 6896, 2160))
        self.assertEqual(ma[1][1:], (110, 60, 500, 400))

    def test_scroll_emits_axis_events_with_wheel_source(self):
        s = self.server()
        vpointer.scroll(dy=120, path=self.path)
        vp = [(r, a) for o, r, a in s.requests
              if o == "zwlr_virtual_pointer_v1"]
        axes = [a for r, a in vp if r == "axis_discrete"]
        self.assertEqual(len(axes), 2)                    # 120px, 60/step
        self.assertTrue(all(a[1] == vpointer.AXIS_VERTICAL for a in axes))
        self.assertTrue(all(a[2] == 60 * 256 for a in axes))   # 24.8 fixed
        self.assertIn("axis_source", [r for r, _ in vp])

    def test_scroll_up_is_negative(self):
        s = self.server()
        vpointer.scroll(dy=-30, path=self.path)
        a = [a for o, r, a in s.requests if r == "axis_discrete"]
        self.assertEqual(a[0][2], -30 * 256)

    def test_missing_manager_is_a_clear_error(self):
        self.server(globals_=GLOBALS[:1])
        with self.assertRaises(vpointer.VPointerError) as cm:
            vpointer.click(1, 1, (10, 10), path=self.path)
        self.assertIn("zwlr_virtual_pointer_manager_v1", str(cm.exception))

    def test_protocol_error_surfaces(self):
        self.server(error_on=("zwlr_virtual_pointer_manager_v1",
                              "create_virtual_pointer"))
        with self.assertRaises(vpointer.VPointerError) as cm:
            vpointer.click(1, 1, (10, 10), path=self.path)
        self.assertIn("protocol error", str(cm.exception))

    def test_no_socket_is_an_error_not_a_hang(self):
        with self.assertRaises(vpointer.VPointerError):
            vpointer.click(1, 1, (10, 10), path=str(self.dir / "absent"))

    def test_socket_path_resolution(self):
        self.assertEqual(
            vpointer.socket_path({"WAYLAND_DISPLAY": "wayland-9",
                                  "XDG_RUNTIME_DIR": "/run/x"}),
            "/run/x/wayland-9")
        self.assertEqual(
            vpointer.socket_path({"WAYLAND_DISPLAY": "/a/b"}), "/a/b")
        with self.assertRaises(vpointer.VPointerError):
            vpointer.socket_path({})

    def test_pointer_is_destroyed_on_close(self):
        s = self.server()
        vpointer.move(1, 1, (10, 10), path=self.path)
        for _ in range(50):
            if any(r == "destroy" for _o, r, _a in s.requests):
                break
            time.sleep(0.02)
        self.assertIn("destroy", [r for _o, r, _a in s.requests])


class IsolatedEnv(unittest.TestCase):
    def test_env_drops_display_and_requires_the_instance_socket(self):
        env = vpointer.isolated_env({"DISPLAY": ":0",
                                     "WAYLAND_DISPLAY": "wayland-77",
                                     "XDG_RUNTIME_DIR": "/run/iso"})
        self.assertNotIn("DISPLAY", env)
        self.assertEqual(env["WAYLAND_DISPLAY"], "wayland-77")

    def test_missing_wayland_display_is_refused_not_guessed(self):
        with self.assertRaises(vpointer.UinputRefused):
            vpointer.isolated_env({"XDG_RUNTIME_DIR": "/run/iso"})

    def test_is_isolated(self):
        self.assertTrue(vpointer.is_isolated(
            {"dev": {"isolated_session": "true"}}))
        self.assertFalse(vpointer.is_isolated({"dev": {}}))
        self.assertFalse(vpointer.is_isolated(None))


if __name__ == "__main__":
    unittest.main()
