"""The suite never sees the live desktop or the real user runtime dir."""
import os
import unittest

import wisp  # noqa: F401  (the import is what isolates the env)
from wisp import hypr


class DesktopIsolation(unittest.TestCase):
    def test_no_live_hyprland_signature(self):
        self.assertNotIn("HYPRLAND_INSTANCE_SIGNATURE", os.environ)
        self.assertNotIn("WAYLAND_DISPLAY", os.environ)

    def test_runtime_dir_is_not_the_real_one(self):
        rt = os.environ.get("XDG_RUNTIME_DIR", "")
        self.assertTrue(rt)
        self.assertNotEqual(os.path.realpath(rt),
                            os.path.realpath(f"/run/user/{os.getuid()}"))

    def test_hypr_finds_no_socket(self):
        self.assertIsNone(hypr._sock_dir())


if __name__ == "__main__":
    unittest.main()
