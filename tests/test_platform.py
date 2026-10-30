"""Platform seam tests — Linux adapters.
No subprocess is spawned; we assert argv shape + graceful None."""
import os
import unittest
from pathlib import Path
from unittest import mock

from wisp import config, platform
from wisp.tools import desktop


def _with_os(os_name):
    return mock.patch.dict(os.environ, {"WISP_OS": os_name})


class TestPlatform(unittest.TestCase):
    def test_current_is_linux(self):
        self.assertEqual(platform.current(), "linux")

    def test_linux_dirs_unchanged(self):
        with _with_os("linux"), \
                mock.patch.dict(os.environ, {},
                                clear=False):
            cfg, data, rt = platform.dirs()
            self.assertTrue(cfg.as_posix().endswith(".config/wisp"))
            self.assertTrue(data.as_posix().endswith(
                ".local/share/wisp"))

    def test_linux_cmds(self):
        with _with_os("linux"):
            with mock.patch.object(platform, "_which",
                                   return_value=True):
                rec = platform.record_cmd(Path("/t/u.wav"), 5)
                self.assertEqual(rec[0], "pw-record")
                self.assertIn("16000", rec)
                shot = platform.screenshot_cmd(Path("/t/s.png"))
                self.assertEqual(shot[0], "grim")
                self.assertEqual(
                    platform.type_text_cmd()[0], "wtype")
                self.assertEqual(platform.tts_binary(), "espeak-ng")

    def test_toggle_cmds_omit_duration(self):
        # seconds=None → open-ended capture for mic toggle; the
        # recorder must carry NO duration flag (stopped by SIGINT).
        with _with_os("linux"):
            with mock.patch.object(platform, "_which",
                                   return_value=True):
                rec = platform.record_cmd(Path("/t/u.wav"), None)
                self.assertEqual(rec[0], "pw-record")
                self.assertNotIn("--sample-count", rec)
                rec2 = platform.record_cmd(Path("/t/u.wav"), 30)
                self.assertIn("--sample-count", rec2)

    def test_desktop_matrix(self):
        """Adapter selection per linux desktop — PATH fully faked."""
        cases = [
            ("hyprland", "grim", "wtype"),
            ("gnome", "gnome-screenshot", "ydotool"),
            ("kde", "spectacle", "ydotool"),
            ("x11", "maim", "xdotool"),
        ]
        for dt, shot, typer in cases:
            with _with_os("linux"),                     mock.patch.dict(os.environ,
                                    {"WISP_DESKTOP": dt}),                     mock.patch.object(platform, "_which",
                                      return_value=True):
                self.assertEqual(
                    platform.screenshot_cmd(Path("/t/s.png"))[0], shot)
                self.assertEqual(
                    platform.type_text_cmd()[0], typer)
                self.assertEqual(platform.current(), "linux")

    def test_desktop_fallback_order(self):
        """Hyprland missing grim → falls through to next screenshotter."""
        def which(b):
            return b != "grim"
        with _with_os("linux"),                 mock.patch.dict(os.environ,
                                {"WISP_DESKTOP": "hyprland"}),                 mock.patch.object(platform, "_which", which):
            self.assertEqual(
                platform.screenshot_cmd(Path("/t/s.png"))[0],
                "gnome-screenshot")

    def test_kde_wm_and_gnome_degrade(self):
        with _with_os("linux"),                 mock.patch.dict(os.environ,
                                {"WISP_DESKTOP": "kde"}),                 mock.patch.object(platform, "_which",
                                  return_value=True):
            self.assertEqual(
                platform.workspace_cmds(2)[0][0], "qdbus")
            self.assertEqual(
                platform.launch_exec_cmds("foot")[0][0], "setsid")
        with _with_os("linux"),                 mock.patch.dict(os.environ,
                                {"WISP_DESKTOP": "gnome"}),                 mock.patch.object(platform, "_which",
                                  return_value=True):
            self.assertEqual(platform.focus_cmds("x"), [])
            self.assertEqual(platform.workspace_cmds(1), [])
            self.assertFalse(platform.supports_hotkey_install())

    def test_wm_ok_verdict(self):
        p = mock.Mock()
        p.stdout, p.returncode = "ok: focus", 0
        with _with_os("linux"):
            self.assertTrue(platform.wm_ok(p))
        p.stdout, p.returncode = "", 1
        with _with_os("linux"):
            self.assertFalse(platform.wm_ok(p))



class TestDefaultApps(unittest.TestCase):
    """The default [apps] map must match the host. These are the names
    Jev resolves "open the terminal" against, so a Linux name on macOS
    turns every such request into a SKIP."""

    def test_linux_defaults_unchanged(self):
        with _with_os("linux"):
            apps = config._default_apps()
        self.assertEqual(apps["terminal"], "ghostty")
        self.assertEqual(apps["files"], "nautilus")

    def test_toml_renders_apps_section(self):
        txt = config._apps_toml()
        self.assertTrue(txt.startswith("[apps]\n"))
        self.assertIn('terminal = "ghostty"', txt)
        # the rest of the default config no longer carries a stale block
        self.assertNotIn("[apps]", config.DEFAULT_CONFIG)



class TestClients(unittest.TestCase):
    """clients() is Hyprland-only and queries the socket."""

    def test_linux_queries_hypr_socket_not_hyprctl(self):
        with _with_os("linux"), \
             mock.patch.object(desktop.hypr, "query",
                               return_value=[{"class": "a"}]) as q, \
             mock.patch("subprocess.run") as run:
            self.assertEqual(desktop.clients(), [{"class": "a"}])
        q.assert_called_once_with("clients")
        run.assert_not_called()

    def test_empty_when_hypr_down(self):
        with _with_os("linux"), \
             mock.patch.object(desktop.hypr, "query",
                               side_effect=desktop.hypr.HyprError(
                                   "unavailable")):
            self.assertEqual(desktop.clients(), [])


if __name__ == "__main__":
    unittest.main()


class TestLoadEnvKey(unittest.TestCase):
    """key_env may be a comma list of sources tried in order —
    omaseal:// refs and env/.env names — so keyring users and plain
    installs resolve the same secret."""

    def test_env_direct(self):
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "k1"}):
            self.assertEqual(config.load_env_key("GROQ_API_KEY"), "k1")

    def test_list_falls_through_dead_omaseal(self):
        def dead(cmd, **_):
            return mock.Mock(returncode=1, stdout="")
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "k2"}), \
                mock.patch("subprocess.run", side_effect=dead):
            self.assertEqual(config.load_env_key(
                "omaseal://groq/default,GROQ_API_KEY"), "k2")

    def test_list_omaseal_wins_when_alive(self):
        def ok(cmd, **_):
            return mock.Mock(returncode=0, stdout="ring-key\n")
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "env-key"}), \
                mock.patch("subprocess.run", side_effect=ok):
            self.assertEqual(config.load_env_key(
                "omaseal://groq/default,GROQ_API_KEY"), "ring-key")

    def test_omaseal_binary_absent_falls_through(self):
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "k3"}), \
                mock.patch("subprocess.run",
                           side_effect=FileNotFoundError):
            self.assertEqual(config.load_env_key(
                "omaseal://groq/default,GROQ_API_KEY"), "k3")

    def test_dotenv_fallback(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            envf = Path(td) / ".env"
            envf.write_text("GROQ_API_KEY=from-file\n")
            with mock.patch.dict(os.environ, {}, clear=True), \
                    mock.patch.object(config, "ENV_FILE", envf):
                self.assertEqual(config.load_env_key("GROQ_API_KEY"),
                                 "from-file")

    def test_all_miss_returns_empty(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(config, "ENV_FILE",
                                  Path("/nonexistent/.env")):
            self.assertEqual(config.load_env_key("NOPE_API_KEY"), "")
