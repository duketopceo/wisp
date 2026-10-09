"""mcpauth — alias mapping, status parsing, register file, strata route."""
import json
import sys
import unittest
from unittest import mock

sys.path.insert(0, ".")
from wisp import mcpauth  # noqa: E402
from wisp.tools import mcpclient  # noqa: E402


class Aliases(unittest.TestCase):
    def test_canonical(self):
        self.assertEqual(mcpauth._canonical("github"), ("GitHub", "github"))
        self.assertEqual(mcpauth._canonical("google calendar"),
                         ("Google Calendar", "google calendar"))
        self.assertEqual(mcpauth._canonical("cal"),
                         ("Google Calendar", "google calendar"))
        self.assertIsNone(mcpauth._canonical("aol"))

    def test_status_connected(self):
        with mock.patch.object(mcpclient, "_call_http",
                               return_value="GitHub: connected"), \
             mock.patch.object(mcpauth, "_browseros_url",
                               return_value="http://x/mcp"):
            st = mcpauth.status("github", {})
        self.assertTrue(st["connected"])

    def test_status_auth_url(self):
        with mock.patch.object(mcpclient, "_call_http",
                               return_value="Not connected. Authorize: "
                                            "https://auth.example/x"), \
             mock.patch.object(mcpauth, "_browseros_url",
                               return_value="http://x/mcp"):
            st = mcpauth.status("slack", {})
        self.assertFalse(st["connected"])
        self.assertEqual(st["auth_url"], "https://auth.example/x")


class Register(unittest.TestCase):
    def test_register_writes_entry(self, ):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "mcp.json"
            with mock.patch.object(mcpauth, "WISP_MCP", p):
                mcpauth.register("GitHub")
                mcpauth.register("google calendar")
            data = json.loads(p.read_text())
        self.assertEqual(data["mcpServers"]["github"],
                         {"via": "strata", "service": "github"})
        self.assertEqual(data["mcpServers"]["google-calendar"]["service"],
                         "google calendar")

    def test_list_connectors_json_marks_registered(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "mcp.json"
            p.write_text(json.dumps({"mcpServers": {
                "github": {"via": "strata", "service": "github"}}}))
            with mock.patch.object(mcpauth, "WISP_MCP", p):
                rows = mcpauth.list_connectors_json({})
        gh = next(r for r in rows if r["name"] == "GitHub")
        self.assertTrue(gh["connected"])
        slack = next(r for r in rows if r["name"] == "Slack")
        self.assertFalse(slack["connected"])
        # names unique + sorted
        names = [r["name"] for r in rows]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(names, sorted(names, key=str.lower))


class OpenAuthUrl(unittest.TestCase):
    """OAuth URL opens in a personal browser — never xdg-open/chooser/
    agent browser — and never dies silently."""
    URL = "https://auth.example/x?token=redacted"

    def _run(self, *, which, hyprctl=None, env_browser="", popen=None):
        """which: dict name->path|None. hyprctl: fake clients JSON or None
        (hyprctl absent). popen: collects Popen argv."""
        import subprocess as _sp
        pops = []
        runs = []

        def fake_which(b):
            return which.get(b)

        def fake_popen(argv, **kw):
            pops.append(argv)
            return mock.Mock()

        def fake_run(argv, **kw):
            runs.append(argv)
            if isinstance(argv, list) and argv[:2] == ["hyprctl", "clients"]:
                return mock.Mock(stdout=json.dumps(hyprctl or []))
            if isinstance(argv, list) and argv[:2] == ["hyprctl", "activewindow"]:
                return mock.Mock(stdout="{}")
            return mock.Mock(stdout="")

        import os
        with mock.patch.dict(os.environ, {"BROWSER": env_browser}), \
             mock.patch("shutil.which", side_effect=fake_which), \
             mock.patch("subprocess.Popen", side_effect=fake_popen), \
             mock.patch("subprocess.run", side_effect=fake_run):
            out = mcpauth._open_auth_url(self.URL)
        return out, pops, runs

    def test_running_browser_wins(self):
        # chromium running (class chromium-browser) + xdg-open present:
        # must pick chromium directly, never the chooser/xdg path.
        out, pops, _ = self._run(
            which={"hyprctl": "/x/hyprctl", "chromium": "/x/chromium",
                   "xdg-open": "/x/xdg-open", "firefox": "/x/firefox"},
            hyprctl=[{"class": "chromium-browser"},
                     {"class": "browseros-neo"},
                     {"class": "foot"}])
        self.assertEqual(out, "browser")
        self.assertEqual(pops, [["chromium", self.URL]])

    def test_focused_browser_preferred_over_first_installed(self):
        out, pops, _ = self._run(
            which={"hyprctl": "/x/hyprctl", "firefox": "/x/firefox",
                   "chromium": "/x/chromium"},
            hyprctl=[{"class": "firefox"}, {"class": "chromium"}])
        # focused first: activewindow returns {} so order is client order;
        # firefox is a client and sorts before the not-running default list
        self.assertEqual(out, "browser")
        self.assertEqual(pops[0][0], "firefox")

    def test_browseros_running_alone_falls_to_installed_personal(self):
        out, pops, _ = self._run(
            which={"hyprctl": "/x/hyprctl", "chromium": "/x/chromium",
                   "browseros": "/x/browseros"},
            hyprctl=[{"class": "browseros-neo"}])
        self.assertEqual(out, "browser")
        self.assertEqual(pops, [["chromium", self.URL]])

    def test_browser_env_override(self):
        out, pops, _ = self._run(
            which={"hyprctl": "/x/hyprctl", "firefox": "/x/firefox"},
            hyprctl=[], env_browser="firefox")
        self.assertEqual(out, "browser")
        self.assertEqual(pops, [["firefox", self.URL]])

    def test_browser_env_chooser_rejected(self):
        out, pops, _ = self._run(
            which={"hyprctl": "/x/hyprctl", "firefox": "/x/firefox"},
            hyprctl=[], env_browser="junction")
        self.assertEqual(out, "browser")
        self.assertEqual(pops, [["firefox", self.URL]])

    def test_no_browser_copies_url(self):
        out, pops, runs = self._run(
            which={"wl-copy": "/x/wl-copy"}, hyprctl=None)
        self.assertEqual(out, "clipboard")
        self.assertEqual(pops, [])
        self.assertTrue(any(r == ["wl-copy"] for r in runs))

    def test_nothing_available_fails_loud(self):
        out, pops, runs = self._run(which={}, hyprctl=None)
        self.assertEqual(out, "failed")
        self.assertEqual(pops, [])

    def test_never_calls_xdg_open(self):
        out, pops, runs = self._run(
            which={"xdg-open": "/x/xdg-open", "open": "/x/open"},
            hyprctl=None)
        self.assertEqual(out, "failed")
        for call in pops + runs:
            self.assertNotIn("xdg-open", call)
            self.assertNotIn("open", call[0])


class StrataRoute(unittest.TestCase):
    def test_strata_dispatch_to_execute_action(self):
        spec = {"via": "strata", "service": "github"}
        inv = {"mcp": {"github": spec,
                       "browseros": {"url": "http://bos/mcp"}}}
        with mock.patch.object(mcpclient, "_server_spec",
                               return_value=spec), \
             mock.patch("wisp.inventory.load", return_value=inv), \
             mock.patch.object(mcpclient, "_call_http",
                               return_value="done") as h:
            out = mcpclient.call(
                'github issues/list {"body": {"repo": "x"}}',
                {"mcp": {}})
        self.assertEqual(out, "done")
        payload = h.call_args.args[2]
        self.assertEqual(h.call_args.args[1], "execute_action")
        self.assertEqual(payload["server_name"], "github")
        self.assertEqual(payload["category_name"], "issues")
        self.assertEqual(payload["action_name"], "list")
        self.assertEqual(json.loads(payload["body_schema"]),
                         {"repo": "x"})


if __name__ == "__main__":
    unittest.main()
