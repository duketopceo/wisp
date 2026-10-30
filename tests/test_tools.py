#!/usr/bin/env python3
"""Toolbelt + agent-manager tests — all subprocesses mocked."""
import http.server
import json
import os
import pathlib
import socket
import sys
import tempfile
import threading
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


class _CdpHandler(http.server.BaseHTTPRequestHandler):
    tabs = [
        {"type": "page", "id": "S1", "title": "Developers \u2013 Pace-HQ \u2013 Stripe",
         "url": "https://dashboard.stripe.com/test/developers"},
        {"type": "page", "id": "G1", "title": "Inbox (5) - x@gmail.com - Gmail",
         "url": "https://mail.google.com/mail/u/0/#inbox"},
        {"type": "service_worker", "id": "W1", "title": "Stripe worker",
         "url": "https://dashboard.stripe.com/sw.js"},
    ]
    activated: list = []

    def do_GET(self):
        if self.path == "/json/list":
            body = json.dumps(self.tabs).encode()
        elif self.path.startswith("/json/activate/"):
            self.activated.append(self.path.rsplit("/", 1)[1])
            body = b"Target activated"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class TestTabTool(unittest.TestCase):
    def setUp(self):
        _CdpHandler.activated = []
        self.srv = http.server.HTTPServer(("127.0.0.1", 0), _CdpHandler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.port = self.srv.server_address[1]
        self.focused = []
        for p in (mock.patch.object(tools.desktop, "CDP_PORTS",
                                    (self.port,)),
                  mock.patch.object(tools.desktop, "_focus_browser",
                                    side_effect=self.focused.append)):
            p.start()
            self.addCleanup(p.stop)

    def test_registered_safe(self):
        self.assertEqual(tools.risk_of("tab"), "safe")
        self.assertIn("tab", tools.describe())

    def test_stripe_tablet_switches_to_stripe(self):
        out = tools.run("tab", "stripe tablet", {})
        self.assertEqual(_CdpHandler.activated, ["S1"])
        self.assertTrue(out.startswith("SWITCHED tab "), out)
        self.assertIn("dashboard.stripe.com", out)
        self.assertEqual(self.focused, ["Developers \u2013 Pace-HQ \u2013 Stripe"])

    def test_gmail(self):
        out = tools.run("tab", "gmail", {})
        self.assertEqual(_CdpHandler.activated, ["G1"])
        self.assertIn("mail.google.com", out)

    def test_my_email_means_the_mail_tab_not_a_page_titled_email(self):
        extra = {"type": "page", "id": "E1",
                 "title": "Verify your email - Example",
                 "url": "https://example.com/verify"}
        with mock.patch.object(_CdpHandler, "tabs",
                               [extra] + _CdpHandler.tabs):
            tools.run("tab", "my email", {})
        self.assertEqual(_CdpHandler.activated, ["G1"])

    def test_host_query(self):
        tools.run("tab", "dashboard.stripe.com", {})
        self.assertEqual(_CdpHandler.activated, ["S1"])

    def test_no_match_skips_without_activating(self):
        out = tools.run("tab", "nonexistent thing", {})
        self.assertTrue(out.startswith("SKIP (no open tab matches "), out)
        # inactive tab titles never reach the model
        self.assertNotIn("Gmail", out)
        self.assertEqual(_CdpHandler.activated, [])

    def test_no_debug_port(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        dead = s.getsockname()[1]
        s.close()
        with mock.patch.object(tools.desktop, "CDP_PORTS", (dead,)):
            out = tools.run("tab", "stripe", {})
        self.assertEqual(out, "SKIP (no browser debug port on 127.0.0.1; "
                              "open the tab by clicking it)")


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
             mock.patch.object(tools.desktop, "_browseros_live",
                               return_value=False), \
             mock.patch("wisp.inventory.defaults", return_value={}), \
             mock.patch.object(tools.desktop, "_exec_detached") as ex:
            out = tools.desktop.launch("gmail.com", cfg)
        self.assertIn("OPENED https://gmail.com", out)
        ex.assert_called_once_with("xdg-open https://gmail.com")

    def _site_launch(self, cfg, live=False, role="firefox"):
        self._hypr_up()
        with mock.patch.object(tools.desktop.shutil, "which",
                               return_value="/usr/bin/x"), \
             mock.patch.object(tools.desktop, "_browseros_live",
                               return_value=live), \
             mock.patch("wisp.inventory.defaults",
                        return_value={"browser": role}), \
             mock.patch.object(tools.desktop, "_exec_detached") as ex:
            out = tools.desktop.launch("stripe.com", cfg)
        return out, ex

    def test_launch_site_goes_to_live_browseros_not_xdg_open(self):
        out, ex = self._site_launch({"apps": {}, "agent": {}}, live=True)
        self.assertEqual(out, "OPENED https://stripe.com -> browseros")
        ex.assert_called_once_with("browseros https://stripe.com")

    def test_launch_site_uses_the_browser_role_when_browseros_is_down(self):
        cfg = {"apps": {"firefox": "firefox"}, "agent": {}}
        out, ex = self._site_launch(cfg)
        self.assertEqual(out, "OPENED https://stripe.com -> firefox")
        ex.assert_called_once_with("firefox https://stripe.com")

    def test_launch_site_browseros_opt_out_skips_browseros(self):
        cfg = {"apps": {"firefox": "firefox"},
               "agent": {"browseros_first": "false"}}
        out, ex = self._site_launch(cfg, live=True)
        ex.assert_called_once_with("firefox https://stripe.com")

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

    def test_launch_my_email_resolves_to_mail_web_role(self):
        self._hypr_up()
        cfg = {"apps": {"browseros": "browseros"}, "agent": {}}
        with mock.patch.object(tools.desktop, "_try_switch_open_tab",
                               return_value=None):
            out, ex = self._mail_launch(cfg, role="my email")
        self.assertEqual(out, "OPENED https://mail.google.com -> browseros")
        ex.assert_called_once_with("browseros https://mail.google.com")

    def test_launch_stripe_switches_to_open_tab_when_present(self):
        self._hypr_up()
        cfg = {"apps": {"browseros": "browseros"}, "agent": {}}
        with mock.patch.object(tools.desktop, "_try_switch_open_tab",
                               return_value="SWITCHED tab 'Developers – Stripe' -> dashboard.stripe.com") as sw, \
             mock.patch.object(tools.desktop, "_web_browser",
                               return_value="browseros"), \
             mock.patch.object(tools.desktop, "_exec_detached") as ex:
            out = tools.desktop.launch("my Stripe", cfg)
        self.assertTrue(out.startswith("SWITCHED tab "), out)
        sw.assert_called_once_with("stripe", url="https://dashboard.stripe.com",
                                   browser="browseros")
        ex.assert_not_called()

    def test_launch_linear_opens_default_web_url_when_no_tab(self):
        self._hypr_up()
        cfg = {"apps": {"browseros": "browseros"}, "agent": {}}
        with mock.patch.object(tools.desktop, "_try_switch_open_tab",
                               return_value=None), \
             mock.patch.object(tools.desktop.shutil, "which",
                               return_value="/x/browseros"), \
             mock.patch.object(tools.desktop, "_browseros_live",
                               return_value=True), \
             mock.patch("wisp.inventory.defaults", return_value={}), \
             mock.patch.object(tools.desktop, "_exec_detached") as ex:
            out = tools.desktop.launch("my Linear", cfg)
        self.assertEqual(out, "OPENED https://linear.app -> browseros")
        ex.assert_called_once_with("browseros https://linear.app")

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
                                  ask=None, user_request="")

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
            # the one-shot path (codex/claude/devin); opencode runs over ACP
            with mock.patch.object(agents.shutil, "which",
                                   return_value="/usr/bin/codex"), \
                 mock.patch.object(agents.subprocess, "Popen",
                                   return_value=proc), \
                 mock.patch.object(agents, "_proc_stat",
                                   return_value=("S", "99")):
                out = agents.spawn("fix the tests in wisp",
                                   {"brain": {"agent_runtime": "codex"}},
                                   tasks_file=tf, log_dir=ld)
            self.assertIn("SPAWNED", out)
            rec = json.loads(tf.read_text().splitlines()[0])
            self.assertEqual(rec["pid"], 4242)
            self.assertIn("codex exec", rec["cmd"])

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


class MultiProfileBrowserTests(unittest.TestCase):
    """Multi-profile browser detection (Personal vs Work) for tab() and launch()."""

    def test_active_browser_profile_from_window_title(self):
        with mock.patch("wisp.platform.active_window",
                        return_value={"class": "BrowserOS", "title": "Inbox — Personal"}):
            self.assertEqual(tools.desktop.active_browser_profile(), "personal")
        with mock.patch("wisp.platform.active_window",
                        return_value={"class": "brave-browser", "title": "Linear - Work"}):
            self.assertEqual(tools.desktop.active_browser_profile(), "work")

    def test_requested_profile_overrides_active_window(self):
        with mock.patch("wisp.platform.active_window",
                        return_value={"class": "BrowserOS", "title": "YouTube — Personal"}):
            self.assertEqual(
                tools.desktop.requested_profile("check my email for work"), "work")
            self.assertEqual(
                tools.desktop.requested_profile("check my email"), "personal")

    def test_tab_prefers_matching_browser_profile(self):
        pages = [
            {"id": "p1", "type": "page",
             "title": "Inbox - kimballluke@gmail.com — Personal",
             "url": "https://mail.google.com/mail/u/0/#inbox",
             "_cdp_port": 9100},
            {"id": "p2", "type": "page",
             "title": "Inbox - luke@bartlett.com — Work",
             "url": "https://mail.google.com/mail/u/0/#inbox",
             "_cdp_port": 9101},
        ]
        activated = []
        with mock.patch.object(tools.desktop, "_cdp_pages",
                               return_value=(9100, pages)), \
             mock.patch.object(
                 tools.desktop, "_cdp_get",
                 side_effect=lambda port, path: activated.append((port, path)) or "Target activated"
             ), \
             mock.patch.object(tools.desktop, "_focus_browser", return_value=None), \
             mock.patch("wisp.platform.active_window",
                        return_value={"class": "BrowserOS", "title": "YouTube — Personal"}):
            out_work = tools.desktop.tab("email for work")
            out_personal = tools.desktop.tab("email")
        self.assertIn("Work", out_work)
        self.assertEqual(activated[0], (9101, "/json/activate/p2"))
        self.assertIn("Personal", out_personal)
        self.assertEqual(activated[1], (9100, "/json/activate/p1"))

    def test_launch_strips_profile_qualifier_and_checks_open_tabs(self):
        seen_queries = []
        with mock.patch.object(tools.desktop, "_wm_down", return_value=None), \
            mock.patch.object(
                 tools.desktop, "_try_switch_open_tab",
                 side_effect=lambda q, **kw: (seen_queries.append(q),
                                        "SWITCHED tab 'Stripe — Work' -> dashboard.stripe.com"
                                        if "work" in q.lower() else None)[1]
             ), \
             mock.patch.object(tools.desktop, "_web_browser",
                               return_value="browseros"):
            out = tools.desktop.launch("go to my Stripe for work", {"agent": {}})
        self.assertIn("SWITCHED tab 'Stripe — Work'", out)
        self.assertEqual(seen_queries, ["stripe work"])
