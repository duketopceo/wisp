"""Isolated wtype calls release all modifiers first; live path unchanged."""
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from wisp import hypr  # noqa: E402
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

    def test_isolated_chord_goes_through_hyprland(self):
        # wtype's one-level keymap cannot deliver Shift+letter chords GTK
        # recognises (Nautilus ctrl+shift+n opened search instead of New
        # Folder in the isolated session); Hyprland's send_key_state uses
        # the compositor's real keymap. Press, then release.
        run = Run()
        lua = []
        with mock.patch("wisp.platform._which", return_value="/usr/bin/wtype"), \
                mock.patch.object(system._vp, "isolated_env",
                                  return_value={}), \
                mock.patch.object(system._cancel, "run", run), \
                mock.patch.object(hypr, "run_lua",
                                  side_effect=lambda c: lua.append(c) or True):
            self.assertEqual(system._iso_key("ctrl+shift+n"), "KEY")
        self.assertIsNone(run.argv)            # wtype not used
        self.assertEqual(lua, [hypr.send_key_state("CTRL SHIFT", "N", "down"),
                               hypr.send_key_state("CTRL SHIFT", "N", "up")])

    def test_isolated_chord_falls_back_to_wtype(self):
        run = Run()
        with mock.patch("wisp.platform._which", return_value="/usr/bin/wtype"), \
                mock.patch.object(system._vp, "isolated_env",
                                  return_value={}), \
                mock.patch.object(system._cancel, "run", run), \
                mock.patch.object(hypr, "run_lua", return_value=False):
            self.assertEqual(system._iso_key("ctrl+l"), "KEY")
        self.assertEqual(run.argv, ["wtype", *REL, "-M", "ctrl", "-k", "l",
                                    "-m", "ctrl"])

    def test_named_keys_map_to_hyprland_names(self):
        self.assertEqual(system._hypr_chord("ctrl+shift+t"), ("CTRL SHIFT", "T"))
        self.assertEqual(system._hypr_chord("alt+up"), ("ALT", "Up"))
        self.assertEqual(system._hypr_chord("ctrl+f5"), ("CTRL", "F5"))
        self.assertIsNone(system._hypr_chord("enter"))      # not a chord
        self.assertIsNone(system._hypr_chord("hyper+x"))    # unknown mod

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
