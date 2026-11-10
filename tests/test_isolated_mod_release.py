"""Isolated wtype calls release all modifiers first; live path unchanged."""
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from wisp.tools import system  # noqa: E402

REL = ["-m", "logo", "-m", "ctrl", "-m", "alt", "-m", "shift"]


class Run:
    def __init__(self):
        self.argv = None

    def __call__(self, argv, **kw):
        self.argv = argv
        return mock.Mock(returncode=0)


class ModRelease(unittest.TestCase):
    def test_isolated_key_releases_first(self):
        run = Run()
        with mock.patch("wisp.platform._which", return_value="/usr/bin/wtype"), \
                mock.patch.object(system._vp, "isolated_env",
                                  return_value={}), \
                mock.patch.object(system._cancel, "run", run):
            self.assertEqual(system._iso_key("enter"), "KEY")
        self.assertEqual(run.argv, ["wtype", *REL, "-k", "Return"])

    def test_isolated_type_releases_first(self):
        run = Run()
        cfg = {}
        with mock.patch.object(system._vp, "is_isolated", return_value=True), \
                mock.patch.object(system._vp, "isolated_env",
                                  return_value={}), \
                mock.patch("wisp.platform.type_text_cmd",
                           return_value=["wtype", "-"]), \
                mock.patch.object(system._cancel, "run", run), \
                mock.patch("wisp.gauntlet.keystroke_guard",
                           return_value=None):
            self.assertEqual(system.type_text("ls", cfg), "TYPED")
        self.assertEqual(run.argv, ["wtype", *REL, "-"])

    def test_live_path_unchanged(self):
        run = Run()
        with mock.patch.object(system._vp, "is_isolated", return_value=False), \
                mock.patch.object(system, "hypr_env", return_value={}), \
                mock.patch("wisp.platform.type_text_cmd",
                           return_value=["wtype", "-"]), \
                mock.patch.object(system._cancel, "run", run), \
                mock.patch("wisp.gauntlet.keystroke_guard",
                           return_value=None):
            system.type_text("ls", {})
        self.assertEqual(run.argv, ["wtype", "-"])
        self.assertEqual(system._wtype_argv("enter"),
                         ["wtype", "-k", "Return"])


if __name__ == "__main__":
    unittest.main()
