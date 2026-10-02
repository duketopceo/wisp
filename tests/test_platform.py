"""Platform seam tests — adapters exercised via WISP_OS override.
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
    def test_detect_override(self):
        with _with_os("macos"):
            self.assertEqual(platform.current(), "macos")
        with _with_os("linux"):
            self.assertEqual(platform.current(), "linux")

    def test_macos_dirs(self):
        with _with_os("macos"):
            cfg, data, rt = platform.dirs()
            self.assertIn("Application Support/wisp", str(cfg))
            self.assertIn("Application Support/wisp", str(data))
            self.assertTrue(str(rt).endswith("wisp"))

    def test_linux_dirs_unchanged(self):
        with _with_os("linux"), \
                mock.patch.dict(os.environ, {},
                                clear=False):
            cfg, data, rt = platform.dirs()
            self.assertTrue(str(cfg).endswith(".config/wisp"))
            self.assertTrue(str(data).endswith(
                ".local/share/wisp"))

    def test_linux_cmds(self):
        with _with_os("macos"), _with_os("linux"):
            with mock.patch.object(platform, "_which",
                                   return_value=True):
                rec = platform.record_cmd(Path("/t/u.wav"), 5)
                self.assertEqual(rec[0], "pw-record")
                self.assertIn("16000", rec)
                shot = platform.screenshot_cmd(Path("/t/s.png"))
                self.assertEqual(shot[0], "grim")
                self.assertEqual(
                    platform.type_text_cmd("hi")[0], "wtype")
                self.assertEqual(platform.tts_binary(), "espeak-ng")

    def test_macos_cmds(self):
        with _with_os("macos"):
            with mock.patch.object(platform, "_which",
                                   return_value=True):
                self.assertEqual(
                    platform.screenshot_cmd(Path("/t/s.png"))[0],
                    "screencapture")
                self.assertEqual(
                    platform.record_cmd(Path("/t/u.wav"), 5)[0],
                    "afrecord")
                self.assertEqual(
                    platform.type_text_cmd("hi")[0], "osascript")
                self.assertEqual(platform.tts_binary(), "say")
                self.assertEqual(
                    platform.notify_cmd("a", "b")[0], "osascript")
                self.assertEqual(platform.sampler_cmd(5)[0], "sox")
                self.assertEqual(
                    platform.focus_cmds("Firefox")[0],
                    ["open", "-a", "Firefox"])
                self.assertEqual(
                    platform.close_cmds("")[0][0], "osascript")
                self.assertEqual(
                    platform.workspace_cmds(3)[0][0], "osascript")
                self.assertEqual(platform.workspace_cmds(10), [])
                self.assertEqual(
                    platform.launch_exec_cmds("foot")[0],
                    ["sh", "-c", "foot"])

    def test_missing_tools_graceful(self):
        with _with_os("macos"):
            with mock.patch.object(platform, "_which",
                                   return_value=False):
                self.assertIsNone(
                    platform.record_cmd(Path("/t/u.wav"), 5))
                self.assertIsNone(
                    platform.screenshot_cmd(Path("/t/s.png")))
                self.assertIsNone(platform.tts_binary())
                self.assertIsNone(platform.sampler_cmd(5))

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
        with _with_os("macos"):
            with mock.patch.object(platform, "_which",
                                   return_value=True):
                rec = platform.record_cmd(Path("/t/u.wav"), None)
                self.assertEqual(rec[0], "afrecord")
                self.assertNotIn("-d", rec)
                smp = platform.sampler_cmd(None)
                self.assertNotIn("trim", smp)

    def test_windows_cmds(self):
        with _with_os("windows"):
            with mock.patch.object(platform, "_which",
                                   return_value=True):
                self.assertEqual(
                    platform.record_cmd(Path("/t/u.wav"), 5)[0],
                    "sox")
                self.assertEqual(
                    platform.screenshot_cmd(Path("/t/s.png"))[0],
                    "powershell")
                self.assertEqual(
                    platform.type_text_cmd("hi")[0], "powershell")
                self.assertEqual(
                    platform.tts_argv("hi")[0], "powershell")
                self.assertEqual(
                    platform.notify_cmd("a", "b")[0], "powershell")
                self.assertEqual(
                    platform.focus_cmds("Notepad")[0][0],
                    "powershell")
                self.assertEqual(
                    platform.close_cmds("")[0][0], "powershell")
                self.assertEqual(
                    platform.launch_exec_cmds("app.exe")[0],
                    ["cmd", "/c", "start", "", "/b", "app.exe"])
                # virtual desktops unsupported via shell — graceful []
                self.assertEqual(platform.workspace_cmds(2), [])

    def test_windows_missing_tools(self):
        with _with_os("windows"):
            with mock.patch.object(platform, "_which",
                                   return_value=False):
                self.assertIsNone(
                    platform.record_cmd(Path("/t/u.wav"), 5))
                self.assertIsNone(platform.tts_argv("hi"))
                self.assertEqual(platform.focus_cmds("x"), [])
                self.assertIn("powershell",
                              platform.missing_deps_hint())

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
                    platform.type_text_cmd("hi")[0], typer)
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

    def test_sendkeys_escape(self):
        self.assertEqual(platform._sendkeys_escape("a+b{c}"),
                         "a{+}b{{}c{}}")

    def test_wm_ok_verdict(self):
        p = mock.Mock()
        p.stdout, p.returncode = "ok: focus", 0
        with _with_os("linux"):
            self.assertTrue(platform.wm_ok(p))
        p.stdout, p.returncode = "", 1
        with _with_os("linux"):
            self.assertFalse(platform.wm_ok(p))
        with _with_os("macos"):
            self.assertFalse(platform.wm_ok(p))
        p.returncode = 0
        with _with_os("macos"):
            self.assertTrue(platform.wm_ok(p))
        p.returncode = 1
        with _with_os("windows"):
            self.assertFalse(platform.wm_ok(p))

    def test_osascript_escaping(self):
        with _with_os("macos"):
            with mock.patch.object(platform, "_which",
                                   return_value=True):
                cmd = platform.type_text_cmd('say "hi" \\ ok')
                script = cmd[-1]
                self.assertIn('\\"hi\\"', script)
                self.assertIn('\\\\', script)


class TestDefaultApps(unittest.TestCase):
    """The default [apps] map must match the host. These are the names
    Jev resolves "open the terminal" against, so a Linux name on macOS
    turns every such request into a SKIP."""

    def test_macos_defaults(self):
        with _with_os("macos"):
            apps = config._default_apps()
        # values must be launch commands whose first token is on PATH —
        # a bare "Terminal" fails desktop.launch()'s which() probe.
        self.assertEqual(apps["terminal"], "open -a 'Terminal'")
        self.assertEqual(apps["files"], "open -a 'Finder'")
        self.assertEqual(apps["settings"], "open -a 'System Settings'")
        for value in apps.values():
            self.assertTrue(value.startswith("open -a "), value)
        self.assertNotIn("gnome", " ".join(apps.values()))
        self.assertNotIn("nautilus", " ".join(apps.values()))

    def test_macos_defaults_are_which_able(self):
        import shutil
        with _with_os("macos"):
            apps = config._default_apps()
        for name, value in apps.items():
            self.assertIsNotNone(shutil.which(value.split()[0]),
                                 f"{name} -> {value}")

    def test_linux_defaults_unchanged(self):
        with _with_os("linux"):
            apps = config._default_apps()
        self.assertEqual(apps["terminal"], "ghostty")
        self.assertEqual(apps["files"], "nautilus")

    def test_toml_renders_apps_section(self):
        with _with_os("macos"):
            txt = config._apps_toml()
        self.assertTrue(txt.startswith("[apps]\n"))
        self.assertIn("terminal = \"open -a 'Terminal'\"", txt)
        # the rest of the default config no longer carries a stale block
        self.assertNotIn("[apps]", config.DEFAULT_CONFIG)

    def test_value_survives_toml_round_trip(self):
        """load_config() does v.strip('"'), which eats an inner closing
        quote — a double-quoted app name would come back truncated."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "config.toml"
            with _with_os("macos"), \
                 mock.patch.object(config, "CFG_FILE", f), \
                 mock.patch.object(config, "CFG_DIR", Path(td)):
                cfg = config.load_config()
            self.assertEqual(cfg["apps"]["settings"],
                             "open -a 'System Settings'")


class TestClientsOffLinux(unittest.TestCase):
    """clients() is Hyprland-only. It used to shell hyprctl unguarded, so
    on macOS it raised FileNotFoundError instead of reporting no windows."""

    def test_empty_on_macos(self):
        with _with_os("macos"):
            self.assertEqual(desktop.clients(), [])

    def test_empty_on_windows(self):
        with _with_os("windows"):
            self.assertEqual(desktop.clients(), [])

    def test_hyprctl_still_called_on_linux(self):
        with _with_os("linux"), \
             mock.patch.object(desktop.subprocess, "run") as run:
            run.return_value = mock.Mock(stdout="[{\"class\": \"a\"}]")
            self.assertEqual(desktop.clients(), [{"class": "a"}])
        self.assertEqual(run.call_args[0][0][0], "hyprctl")


if __name__ == "__main__":
    unittest.main()
