#!/usr/bin/env python3
"""Toolbelt + agent-manager tests — all subprocesses mocked."""
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import agents, hypr, pipeline, tools  # noqa: E402


class TestRegistry(unittest.TestCase):
    def test_all_registered_tools_describable(self):
        desc = tools.describe()
        for name in tools.REGISTRY:
            if name in tools.LOOP_ONLY:
                # loop-internal tools (ask_user) are advertised to the
                # model in tool_schemas but must not be route targets —
                # Jev can't dispatch them, only the act loop can
                self.assertNotIn(name, desc)
                continue
            self.assertIn(name, desc)

    def test_unknown_tool_skips(self):
        self.assertIn("unavailable", tools.run("nope", "", {}))

    def test_risk_tiers(self):
        self.assertEqual(tools.risk_of("launch"), "safe")
        self.assertEqual(tools.risk_of("close"), "mutating")
        self.assertEqual(tools.risk_of("shell"), "shell")
        self.assertEqual(tools.risk_of("nonexistent"), "shell")

    def test_denylist(self):
        self.assertTrue(tools.denied("rm -rf /home"))
        self.assertTrue(tools.denied("sudo mkfs.ext4 /dev/sda"))
        self.assertFalse(tools.denied("ls -la"))


class TestToolExec(unittest.TestCase):
    def _hypr_up(self):
        """Pin a Hyprland host with a live socket: launch execs through
        Hyprland, and CI runners have none. _find_window is stubbed off
        — launch tests exercise the exec path, not live clients."""
        for p in (mock.patch.dict(os.environ, {"WISP_OS": "linux",
                                               "WISP_DESKTOP": "hyprland"}),
                  mock.patch.object(hypr, "available", return_value=True),
                  mock.patch.object(tools.desktop, "_find_window",
                                    return_value=None)):
            p.start()
            self.addCleanup(p.stop)

    def test_workspace_parses_number(self):
        with mock.patch.dict(os.environ, {"WISP_OS": "linux",
                                          "WISP_DESKTOP": "hyprland"}), \
             mock.patch.object(hypr, "available", return_value=True), \
             mock.patch.object(hypr, "run_lua", return_value=True) as ev:
            self.assertEqual(tools.run("workspace", "3", {}), "WORKSPACE 3")
        ev.assert_called_once_with(hypr.focus_workspace(3))

    def test_workspace_rejects_non_number(self):
        self.assertIn("SKIP", tools.run("workspace", "abc", {}))

    def test_workspace_parses_natural_language(self):
        # soak fix: "workspace 4" / "ws4" must extract the digit
        with mock.patch.dict(os.environ, {"WISP_OS": "linux",
                                          "WISP_DESKTOP": "hyprland"}), \
             mock.patch.object(hypr, "available", return_value=True), \
             mock.patch.object(hypr, "run_lua", return_value=True):
            for arg in ("workspace 4", "ws4", "go to 4"):
                self.assertEqual(tools.run("workspace", arg, {}),
                                 "WORKSPACE 4")

    def test_browser_prefers_browseros_when_live(self):
        self._hypr_up()
        # soak fix: 'browser' means the signed-in BrowserOS when its
        # MCP server is up — chromium is the fallback, not the default
        cfg = {"apps": {"browser": "chromium"}, "agent": {}}
        with mock.patch.object(tools.desktop.shutil, "which",
                               return_value="/x/browseros"), \
             mock.patch.object(tools.desktop, "_browseros_live",
                               return_value=True), \
             mock.patch.object(tools.desktop, "_exec_detached") as ex:
            out = tools.desktop.launch("browser", cfg)
        self.assertIn("browseros", out)
        ex.assert_called_once_with("browseros")

    def test_browser_falls_back_to_chromium(self):
        self._hypr_up()
        cfg = {"apps": {"browser": "chromium"}, "agent": {}}
        with mock.patch.object(tools.desktop.shutil, "which",
                               return_value="/x/browseros"), \
             mock.patch.object(tools.desktop, "_browseros_live",
                               return_value=False), \
             mock.patch.object(tools.desktop, "_exec_detached") as ex:
            out = tools.desktop.launch("browser", cfg)
        self.assertIn("chromium", out)
        ex.assert_called_once_with("chromium")

    def test_browseros_first_opt_out(self):
        self._hypr_up()
        cfg = {"apps": {"browser": "chromium"},
               "agent": {"browseros_first": "false"}}
        with mock.patch.object(tools.desktop.shutil, "which",
                               return_value="/x/browseros"), \
             mock.patch.object(tools.desktop, "_browseros_live",
                               return_value=True), \
             mock.patch.object(tools.desktop, "_exec_detached") as ex:
            out = tools.desktop.launch("browser", cfg)
        self.assertIn("chromium", out)
        ex.assert_called_once_with("chromium")

    def test_launch_domain_opens_in_browser(self):
        self._hypr_up()
        cfg = {"apps": {}, "agent": {}}
        with mock.patch.object(tools.desktop.shutil, "which",
                               return_value="/usr/bin/xdg-open"), \
             mock.patch.object(tools.desktop, "_exec_detached") as ex:
            out = tools.desktop.launch("gmail.com", cfg)
        self.assertIn("OPENED https://gmail.com", out)
        ex.assert_called_once_with("xdg-open https://gmail.com")

    def _mail_launch(self, cfg, role_app="browseros", win=None,
                     role="mail"):
        """launch(role) with the owner's mimeapps shape: the role
        resolves to role_app; the browser role resolves to browseros."""
        defaults = {"mail": role_app, "calendar": role_app,
                    "browser": "browseros"}
        with mock.patch("wisp.inventory.defaults",
                        return_value=defaults), \
             mock.patch.object(tools.desktop, "_find_window",
                               return_value=win), \
             mock.patch.object(tools.desktop.shutil, "which",
                               return_value="/x/bin"), \
             mock.patch("wisp.platform._try", return_value=True), \
             mock.patch.object(tools.desktop, "_exec_detached") as ex:
            out = tools.desktop.launch(role, cfg)
        return out, ex

    def test_launch_mail_in_browser_opens_webmail(self):
        self._hypr_up()
        cfg = {"apps": {"browseros": "browseros"}, "agent": {}}
        win = {"address": "0xabc", "class": "BrowserOS"}
        out, ex = self._mail_launch(cfg, win=win)
        self.assertEqual(
            out, "OPENED https://mail.google.com -> browseros")
        ex.assert_called_once_with("browseros https://mail.google.com")

    def test_launch_mail_in_browser_failed_exec_is_not_opened(self):
        self._hypr_up()
        cfg = {"apps": {"browseros": "browseros"}, "agent": {}}
        defaults = {"mail": "browseros", "browser": "browseros"}
        with mock.patch("wisp.inventory.defaults", return_value=defaults), \
             mock.patch.object(tools.desktop, "_find_window",
                               return_value=None), \
             mock.patch.object(tools.desktop.shutil, "which",
                               return_value="/x/bin"), \
             mock.patch("wisp.platform._try", return_value=True), \
             mock.patch.object(tools.desktop, "_exec_detached",
                               return_value=False):
            out = tools.desktop.launch("mail", cfg)
        self.assertTrue(out.startswith("SKIP"), out)
        self.assertIn("https://mail.google.com", out)

    def test_launch_mail_in_browser_without_window(self):
        self._hypr_up()
        cfg = {"apps": {"browseros": "browseros"}, "agent": {}}
        out, ex = self._mail_launch(cfg)
        self.assertEqual(
            out, "OPENED https://mail.google.com -> browseros")
        ex.assert_called_once_with("browseros https://mail.google.com")

    def test_launch_mail_web_url_from_config(self):
        self._hypr_up()
        cfg = {"apps": {"browseros": "browseros"}, "agent": {},
               "web": {"mail": "https://outlook.office.com/mail"}}
        out, ex = self._mail_launch(cfg)
        self.assertEqual(
            out, "OPENED https://outlook.office.com/mail -> browseros")
        ex.assert_called_once_with(
            "browseros https://outlook.office.com/mail")

    def test_launch_mail_empty_web_value_uses_default(self):
        self._hypr_up()
        cfg = {"apps": {"browseros": "browseros"}, "agent": {},
               "web": {"mail": ""}}
        out, ex = self._mail_launch(cfg)
        ex.assert_called_once_with("browseros https://mail.google.com")

    def test_launch_calendar_in_browser_opens_web_calendar(self):
        self._hypr_up()
        cfg = {"apps": {"browseros": "browseros"}, "agent": {}}
        out, ex = self._mail_launch(cfg, role="calendar")
        self.assertEqual(
            out, "OPENED https://calendar.google.com -> browseros")
        ex.assert_called_once_with(
            "browseros https://calendar.google.com")

    def test_launch_mail_native_client_unchanged(self):
        self._hypr_up()
        cfg = {"apps": {"thunderbird": "thunderbird"}, "agent": {}}
        out, ex = self._mail_launch(cfg, role_app="thunderbird")
        self.assertEqual(out, "LAUNCHED thunderbird -> thunderbird")
        ex.assert_called_once_with("thunderbird")

    def test_launch_mail_native_client_running_focuses(self):
        self._hypr_up()
        cfg = {"apps": {"thunderbird": "thunderbird"}, "agent": {}}
        win = {"address": "0xdef", "class": "thunderbird"}
        out, ex = self._mail_launch(cfg, role_app="thunderbird", win=win)
        self.assertIn("FOCUSED thunderbird", out)
        ex.assert_not_called()

    def test_launch_unknown_noun_still_skips(self):
        self._hypr_up()
        cfg = {"apps": {}, "agent": {}}
        with mock.patch.object(tools.desktop.shutil, "which",
                               return_value="/usr/bin/xdg-open"), \
             mock.patch.object(tools.desktop, "_exec_detached") as ex:
            out = tools.desktop.launch("thunderbird", cfg)
        self.assertIn("SKIP (unknown app 'thunderbird')", out)
        ex.assert_not_called()

    def test_launch_running_app_focuses_instead(self):
        self._hypr_up()
        cfg = {"apps": {"foot": "foot"}, "agent": {}}
        win = {"address": "0xabc", "class": "foot", "title": "zsh"}
        with mock.patch.object(tools.desktop, "_find_window",
                               return_value=win), \
             mock.patch("wisp.platform._try",
                        return_value=True) as tr, \
             mock.patch.object(tools.desktop, "_exec_detached") as ex:
            out = tools.desktop.launch("foot", cfg)
        self.assertIn("FOCUSED foot", out)
        self.assertIn("already running", out)
        ex.assert_not_called()

    def test_notify_runs(self):
        with mock.patch.object(tools.system, "notify") as n:
            self.assertEqual(tools.run("notify", "hi", {}), "NOTIFIED")
            n.assert_called_once_with("hi")

    def test_shell_bounded_output(self):
        out = tools.system.shell("echo hello")
        self.assertIn("rc=0", out)
        self.assertIn("hello", out)


class TestRouteDispatch(unittest.TestCase):
    def answers(self, route, tool="", detail="", action="", app="",
                risk=1.0):
        return {"route": {"choice": route},
                "tool": {"choice": tool},
                "action": {"choice": action},
                "app": {"choice": app},
                "risk": {"score": risk}}

    def test_tool_route_dispatches(self):
        with mock.patch.object(tools, "run",
                               return_value="WORKSPACE 3") as r:
            out = pipeline.execute(
                self.answers("tool", tool="workspace"),
                {"agent": {"risk_threshold": "1.5"}}, detail="3")
        self.assertEqual(out, "WORKSPACE 3")
        r.assert_called_once_with("workspace", "3", mock.ANY, None)

    def test_agent_route_spawns(self):
        with mock.patch.object(agents, "spawn",
                               return_value="SPAWNED x") as s:
            out = pipeline.execute(
                self.answers("agent"),
                {"agent": {"risk_threshold": "1.5"}}, detail="fix tests")
        self.assertEqual(out, "SPAWNED x")
        s.assert_called_once_with("fix tests", mock.ANY)

    def test_answer_route(self):
        out = pipeline.execute(
            self.answers("answer"),
            {"agent": {"risk_threshold": "1.5"}},
            detail="you can say open discord")
        self.assertEqual(out, "ANSWERED")

    def test_shell_tool_blocked_by_default(self):
        out = pipeline.execute(
            self.answers("tool", tool="shell"),
            {"agent": {"risk_threshold": "1.5"}}, detail="ls -la")
        self.assertIn("allow_shell", out)

    def test_shell_tool_goes_through_act_loop(self):
        # Jev can't produce free-text args — verbatim transcript as a
        # shell command is the "sh -c <your sentence>" bug. Shell via
        # the tool route defers to the act loop, which composes a real
        # argv (and applies the denylist on the composed command).
        with mock.patch("wisp.act.run_act_loop",
                        return_value="ACTED x") as a:
            out = pipeline.execute(
                self.answers("tool", tool="shell"),
                {"agent": {"risk_threshold": "1.5",
                           "allow_shell": "true"}},
                detail="rm -rf /")
        self.assertEqual(out, "ACTED x")
        a.assert_called_once_with("rm -rf /", mock.ANY, state=None,
                                  harness=None, confirm=None,
                                  initial_image=None, interrupted=None,
                                  ask=None)

    def test_risk_blocks_before_route(self):
        out = pipeline.execute(
            self.answers("tool", tool="shell", risk=2.5),
            {"agent": {"risk_threshold": "1.5"}}, detail="ls")
        self.assertTrue(out.startswith("BLOCKED"))

    def test_legacy_launch_still_works(self):
        with mock.patch.object(tools, "run",
                               return_value="LAUNCHED") as r:
            out = pipeline.execute(
                {"action": {"choice": "launch"},
                 "app": {"choice": "terminal"},
                 "risk": {"score": 1.0}},
                {"agent": {"risk_threshold": "1.5"}})
        self.assertEqual(out, "LAUNCHED")
        r.assert_called_once_with("launch", "terminal", mock.ANY, None)


class TestAgents(unittest.TestCase):
    def test_spawn_writes_record(self):
        with tempfile.TemporaryDirectory() as td:
            tf = pathlib.Path(td) / "tasks.jsonl"
            ld = pathlib.Path(td) / "logs"
            proc = mock.Mock(pid=4242)
            with mock.patch.object(agents.shutil, "which",
                                   return_value="/usr/bin/ori"), \
                 mock.patch.object(agents.subprocess, "Popen",
                                   return_value=proc), \
                 mock.patch.object(agents, "_proc_stat",
                                   return_value=("S", "99")):
                out = agents.spawn("fix the tests in wisp", {},
                                   tasks_file=tf, log_dir=ld)
            self.assertIn("SPAWNED", out)
            rec = json.loads(tf.read_text().splitlines()[0])
            self.assertEqual(rec["pid"], 4242)
            self.assertIn("ori opencode", rec["cmd"])

    def test_spawn_missing_ori(self):
        # a missing configured runtime is an explicit error naming it
        with mock.patch.object(agents.shutil, "which", return_value=None):
            out = agents.spawn("task", {})
        self.assertIn("not on PATH", out)
        self.assertIn("opencode", out)

    def test_duplicate_names_get_suffix(self):
        with tempfile.TemporaryDirectory() as td:
            tf = pathlib.Path(td) / "tasks.jsonl"
            tf.write_text(json.dumps({"id": "fix-x", "name": "fix-x",
                                      "pid": 1}) + "\n")
            proc = mock.Mock(pid=99)
            with mock.patch.object(agents.shutil, "which",
                                   return_value="/usr/bin/ori"), \
                 mock.patch.object(agents.subprocess, "Popen",
                                   return_value=proc), \
                 mock.patch.object(agents, "_proc_stat",
                                   return_value=("S", "99")):
                agents.spawn("fix-x", {}, tasks_file=tf,
                             log_dir=pathlib.Path(td))
            recs = [json.loads(l) for l in tf.read_text().splitlines()]
            self.assertEqual(recs[-1]["name"], "fix-x-2")

    def test_status_unknown_task(self):
        with tempfile.TemporaryDirectory() as td:
            out = agents.status("ghost",
                                tasks_file=pathlib.Path(td) / "t.jsonl")
        self.assertIn("no task", out)

    def test_cancel_not_running(self):
        with tempfile.TemporaryDirectory() as td:
            tf = pathlib.Path(td) / "t.jsonl"
            tf.write_text(json.dumps({"id": "x", "name": "x",
                                      "pid": 999999999}) + "\n")
            out = agents.cancel("x", tasks_file=tf)
        self.assertIn("not running", out)


if __name__ == "__main__":
    unittest.main()


class WebConfigTemplateTest(unittest.TestCase):
    """The shipped template's [web] block must not swallow [stt] keys."""

    def test_template_keeps_stt_prompt_in_stt(self):
        import tempfile
        from wisp import config
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "config.toml"
            p.write_text(config.DEFAULT_CONFIG, encoding="utf-8")
            with mock.patch.object(config, "CFG_FILE", p):
                cfg = config.load_config()
        self.assertIn("prompt", cfg["stt"])
        self.assertEqual(set(cfg["web"]), {"mail", "calendar"})
