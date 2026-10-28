"""R13: no screenshot while a sensitive window is focused."""
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import cua_safety, stage_capture  # noqa: E402
from wisp.tools import system  # noqa: E402


def win(app, title=""):
    return {"app": app, "title": title}


class CaptureBlockedTest(unittest.TestCase):
    def test_password_manager_blocks(self):
        self.assertIn("denied", cua_safety.capture_blocked({}, win("1Password")))

    def test_ordinary_window_passes(self):
        self.assertEqual(cua_safety.capture_blocked({}, win("firefox")), "")

    def test_terminal_running_sudo_blocks(self):
        self.assertTrue(cua_safety.capture_blocked(
            {}, win("kitty", "sudo pacman -Syu")))

    def test_user_deny_list_applies(self):
        cfg = {"cua": {"deny": "signal"}}
        self.assertTrue(cua_safety.capture_blocked(cfg, win("Signal")))

    def test_safety_off_never_blocks(self):
        cfg = {"cua": {"safety": "false"}}
        self.assertEqual(cua_safety.capture_blocked(cfg, win("keepassxc")), "")

    def test_capture_screen_takes_no_shot_for_a_sensitive_window(self):
        with mock.patch.object(cua_safety, "_live_window",
                               return_value=win("bitwarden")), \
                mock.patch("wisp.platform.screenshot_cmd") as cmd, \
                mock.patch("wisp.config.load_config", return_value={}):
            self.assertIsNone(stage_capture.capture_screen())
        cmd.assert_not_called()

    def test_screenshot_tool_skips_for_a_sensitive_window(self):
        with mock.patch.object(cua_safety, "_live_window",
                               return_value=win("pinentry-gtk")), \
                mock.patch("wisp.platform.screenshot_cmd") as cmd:
            out = system.screenshot("", {})
        self.assertTrue(out.startswith("SKIP (screenshot skipped"), out)
        cmd.assert_not_called()


if __name__ == "__main__":
    unittest.main()
