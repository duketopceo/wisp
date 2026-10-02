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
