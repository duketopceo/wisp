#!/usr/bin/env python3
"""`wispd settings` (overhaul U4): raise a running settings window over
Quickshell IPC, otherwise start one detached with the category in the
environment; refuse with pointers when there is no display. No process is
started: run, spawn, which and focus are fakes."""
import contextlib
import io
import os
import pathlib
import re
import subprocess
import unittest
from unittest import mock

from wisp import cli
from wisp.cli import settings_window as sw
from wisp.cli.registry import CliError

ROOT = pathlib.Path(__file__).resolve().parent.parent
WAYLAND = {"WAYLAND_DISPLAY": "wayland-1", "HOME": "/h"}


class Fakes:
    def __init__(self, ipc_rc=0, ipc_raises=None, qs="/usr/bin/quickshell",
                 focus_raises=None):
        self.ipc_rc, self.ipc_raises = ipc_rc, ipc_raises
        self.qs, self.focus_raises = qs, focus_raises
        self.runs, self.spawns, self.focused = [], [], []

    def run(self, argv, **kw):
        self.runs.append((argv, kw))
        if self.ipc_raises:
            raise self.ipc_raises
        return subprocess.CompletedProcess(argv, self.ipc_rc, "", "")

    def spawn(self, argv, **kw):
        self.spawns.append((argv, kw))

    def which(self, name):
        return self.qs if name == "quickshell" else None

    focus_reply = "ok"

    def focus(self, lua):
        if self.focus_raises:
            raise self.focus_raises
        self.focused.append(lua)
        return self.focus_reply

    def open(self, category="", env=WAYLAND):
        return sw.open_window(category, env=env, run=self.run,
                              spawn=self.spawn, which=self.which,
                              focus=self.focus, path=pathlib.Path("/o/s"))


class TestOpenWindow(unittest.TestCase):
    def test_no_display_refuses(self):
        f = Fakes()
        with self.assertRaises(CliError) as cm:
            f.open("budget", env={"HOME": "/h"})
        self.assertEqual(cm.exception.code, "E_NO_DISPLAY")
        self.assertEqual(f.runs, [])
        self.assertEqual(f.spawns, [])

    def test_x11_display_counts(self):
        res = Fakes().open("", env={"DISPLAY": ":0"})
        self.assertEqual(res["action"], "raised")

    def test_running_window_is_asked_over_ipc_and_focused(self):
        f = Fakes(ipc_rc=0)
        res = f.open("budget")
        self.assertEqual(f.runs[0][0], ["/usr/bin/quickshell", "ipc", "-p",
                                        "/o/s", "call", "settings", "open",
                                        "budget"])
        self.assertEqual(f.spawns, [])
        self.assertEqual(res, {"action": "raised", "category": "budget",
                               "focused": True})
        self.assertEqual(len(f.focused), 1)
        self.assertIn("title:^Wisp settings$", f.focused[0])

    def test_no_running_window_starts_one_detached(self):
        f = Fakes(ipc_rc=1)
        res = f.open("budget")
        argv, kw = f.spawns[0]
        self.assertEqual(argv, ["/usr/bin/quickshell", "-n", "-p", "/o/s"])
        self.assertTrue(kw["start_new_session"])
        self.assertEqual(kw["env"]["WISP_SETTINGS_CATEGORY"], "budget")
        self.assertEqual(kw["stdin"], subprocess.DEVNULL)
        self.assertEqual(res["action"], "started")
        self.assertEqual(f.focused, [])

    def test_ipc_timeout_or_error_starts_one(self):
        for exc in (subprocess.TimeoutExpired("qs", 3), OSError("gone")):
            with self.subTest(exc=type(exc).__name__):
                f = Fakes(ipc_raises=exc)
                self.assertEqual(f.open("voice")["action"], "started")
                self.assertEqual(len(f.spawns), 1)

    def test_no_category_drops_a_stale_env_value(self):
        f = Fakes(ipc_rc=1)
        f.open("", env=dict(WAYLAND, WISP_SETTINGS_CATEGORY="models"))
        self.assertNotIn("WISP_SETTINGS_CATEGORY", f.spawns[0][1]["env"])

    def test_focus_failure_still_reports_raised(self):
        f = Fakes(ipc_rc=0, focus_raises=RuntimeError("no hyprland"))
        res = f.open("agents")
        self.assertEqual(res["action"], "raised")
        self.assertFalse(res["focused"])

    def test_unmatched_window_warning_is_not_focus(self):
        f = Fakes(ipc_rc=0)
        f.focus_reply = "warning: no window matched"
        res = f.open("agents")
        self.assertEqual(res["action"], "raised")
        self.assertFalse(res["focused"])

    def test_no_quickshell(self):
        f = Fakes(qs=None)
        with self.assertRaises(CliError) as cm:
            f.open()
        self.assertEqual(cm.exception.code, "E_UNHEALTHY")

    def test_shell_dir_is_the_settings_config(self):
        d = sw.shell_dir()
        self.assertEqual(d, ROOT / "shells" / "settings")
        self.assertTrue((d / "shell.qml").is_file())


def run_cli(argv, env):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, env, clear=True), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv), host=None)
    return code, out.getvalue(), err.getvalue()


class TestCommand(unittest.TestCase):
    def test_no_display_exits_non_zero_with_both_pointers(self):
        code, out, err = run_cli(["settings"], {"HOME": "/h"})
        self.assertNotEqual(code, 0)
        self.assertIn("E_NO_DISPLAY", err)
        self.assertIn("wispd config", err)
        self.assertIn("wispd tui", err)

    def test_message_for_each_outcome(self):
        cases = [({"action": "started", "category": "", "focused": False},
                  "Opening the settings window."),
                 ({"action": "raised", "category": "", "focused": True},
                  "The settings window is open."),
                 ({"action": "raised", "category": "", "focused": False},
                  "already open on another workspace")]
        for res, text in cases:
            with self.subTest(res=res), \
                    mock.patch.object(sw, "open_window", return_value=res):
                code, out, _err = run_cli(["settings"], WAYLAND)
                self.assertEqual(code, 0)
                self.assertIn(text, out)

    def test_category_takes_every_page_and_category(self):
        from wisp import settings_schema as S
        for name in ("health", "tasks", "agents", "home", "binds"):
            with self.subTest(name):
                self.assertIn(name, S.SIDEBAR)
                self.assertEqual(Fakes(ipc_rc=0).open(name)["category"], name)
        # the tasks page and the agents category are different entries
        self.assertNotIn("agents", S.PAGES)
        self.assertNotIn("tasks", S.CATEGORIES)
        self.assertEqual(len(set(S.SIDEBAR)), len(S.SIDEBAR))
        # the CLI accepts a page name and hands it to the window (no
        # display or quickshell is needed for that)
        res = {"action": "started", "category": "health", "focused": False}
        with mock.patch.object(sw, "open_window", return_value=res) as ow:
            code, _out, _err = run_cli(["settings", "--category", "health"],
                                       WAYLAND)
        self.assertEqual(code, 0)
        ow.assert_called_once_with("health")

    def test_unknown_category_is_a_usage_error(self):
        code, _out, _err = run_cli(["settings", "--category", "nope"],
                                   WAYLAND)
        self.assertEqual(code, 2)

    def test_does_not_collide_with_config(self):
        from wisp.cli import registry
        cli.load_groups()
        cmds = registry.commands()
        self.assertIn("settings", cmds)
        self.assertIn("config set", cmds)


class TestShellConfig(unittest.TestCase):
    def test_settings_config_links_the_plugin_and_owns_its_shim(self):
        s, plugin = ROOT / "shells" / "settings", ROOT / "shell-plugin"
        for name, target in (("components", plugin / "components"),
                             ("lib", plugin / "lib"),
                             ("copy.js", plugin / "lib" / "copy.js"),
                             ("tokens.js", plugin / "lib" / "tokens.js"),
                             ("WispService.qml", plugin / "WispService.qml")):
            with self.subTest(name):
                self.assertTrue((s / name).exists(), name)
                self.assertEqual((s / name).resolve(), target.resolve())
        # one-surface U3: the qs.Commons shim is the window's own directory
        self.assertTrue((s / "Commons" / "qmldir").is_file())
        self.assertFalse((s / "Commons").is_symlink())

    def test_shell_reads_category_env_and_serves_ipc(self):
        src = (ROOT / "shells" / "settings" / "shell.qml").read_text()
        self.assertIn('Quickshell.env("WISP_SETTINGS_CATEGORY")', src)
        self.assertIn('target: "settings"', src)
        self.assertIn("function open(category: string)", src)
        # the CLI focuses the window by this title
        self.assertIn(f'title: "{sw.WINDOW_TITLE}"', src)
        # KTD2: the stream follows the page, on for a Status or management
        # page and off on a config category
        self.assertIn("readonly property bool streamOn: S.isPage(host.category)", src)
        self.assertIn("streamEnabled: win.streamOn", src)
        self.assertIn("onStreamOnChanged: heard = false", src)
        # no category, or an unknown one, opens Home
        self.assertIn('S.startPage(Quickshell.env("WISP_SETTINGS_CATEGORY") || "")', src)
        # the connector list asks the gateway: read once, on the first visit
        # to the Connectors page, never at window open
        start = re.search(r"Component\.onCompleted:\s*\{.*?\n  \}", src, re.S)
        self.assertIsNotNone(start)
        self.assertNotIn("loadConnectors", start.group(0))
        once = re.search(r"function readConnectorsOnce\(\).*?\n  \}", src, re.S)
        self.assertIsNotNone(once)
        self.assertIn("connectorsRead", once.group(0))
        self.assertIn('host.category !== "connectors"', once.group(0))
        self.assertIn("svc.loadConnectors()", once.group(0))
        self.assertIn("onCategoryChanged: { win.readConnectorsOnce(); win.enter(host.category); }", src)
        self.assertIn("minimumSize: Qt.size(720, 520)", src)
        self.assertNotRegex(src, r"\bTimer\s*\{")


if __name__ == "__main__":
    unittest.main()
