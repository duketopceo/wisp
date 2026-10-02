"""Focus/windows/password-manager context injection."""
import sys
import unittest
from unittest import mock

sys.path.insert(0, ".")
from wisp import context  # noqa: E402


def _client(cls, title, wsid, wsname=""):
    return {"class": cls, "title": title,
            "workspace": {"id": wsid, "name": wsname}}


class WindowsMap(unittest.TestCase):
    def _clients(self):
        return [
            _client("BrowserOS", "Robinhood — Work", 1),
            _client("BrowserOS", "YouTube — Personal", 2),
            _client("com.onepassword.OnePassword", "1Password", -97,
                    "special:scratchpad"),
        ]

    def test_groups_by_workspace(self):
        with mock.patch("wisp.tools.desktop.clients",
                        return_value=self._clients()):
            out = context.windows_map()
        self.assertIn("ws1=BrowserOS:Robinhood — Work", out)
        self.assertIn("ws2=BrowserOS:YouTube — Personal", out)

    def test_special_workspaces_use_name(self):
        with mock.patch("wisp.tools.desktop.clients",
                        return_value=self._clients()):
            out = context.windows_map()
        self.assertIn("special:scratchpad", out)
        self.assertNotIn("ws-97", out)

    def test_empty_when_no_clients(self):
        with mock.patch("wisp.tools.desktop.clients", return_value=[]):
            self.assertEqual(context.windows_map(), "")

    def test_tolerates_enumerator_failure(self):
        with mock.patch("wisp.tools.desktop.clients",
                        side_effect=RuntimeError("no hyprctl")):
            self.assertEqual(context.windows_map(), "")


class PasswordManager(unittest.TestCase):
    def _snap(self, pm):
        cfg = {"act": {"context": "minimal"},
               "agent": {"password_manager": pm}}
        with mock.patch("wisp.platform.active_window",
                        return_value={"class": "firefox", "title": "x"}):
            return context.snapshot(cfg)

    def test_1password_allows_prompt_clicks(self):
        out = self._snap("1password")
        self.assertIn("1password", out)
        self.assertIn("never type or guess a password", out)

    def test_other_value_disallows(self):
        out = self._snap("off")
        self.assertIn("do NOT interact", out)

    def test_absent_adds_nothing(self):
        out = self._snap("")
        self.assertNotIn("password_manager", out)


class WindowsInSnapshot(unittest.TestCase):
    def test_full_mode_includes_windows(self):
        cfg = {"act": {"context": "full"}, "agent": {}}
        with mock.patch("wisp.platform.active_window",
                        return_value={"class": "godot", "title": "t"}), \
             mock.patch("wisp.tools.desktop.clients",
                        return_value=[_client("godot", "proj", 4)]):
            out = context.snapshot(cfg)
        self.assertIn("[windows]", out)
        self.assertIn("ws4=godot:proj", out)


if __name__ == "__main__":
    unittest.main()
