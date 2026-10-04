"""mcp_call tool — arg parsing, server lookup, both transports."""
import io
import json
import sys
import unittest
from unittest import mock

sys.path.insert(0, ".")
from wisp.tools import mcpclient  # noqa: E402


class ArgParsing(unittest.TestCase):
    def test_needs_server_and_tool(self):
        out = mcpclient.call("browseros", {"mcp": {}})
        self.assertTrue(out.startswith("SKIP"))

    def test_bad_json_args_skipped(self):
        out = mcpclient.call("browseros tabs {oops", {"mcp": {}})
        self.assertTrue(out.startswith("SKIP"))

    def test_disabled_by_config(self):
        out = mcpclient.call(
            'browseros tabs {}', {"mcp": {"enabled": "false"}})
        self.assertIn("mcp disabled", out)

    def test_unknown_server_skipped(self):
        with mock.patch.object(mcpclient, "_server_spec",
                               return_value=None):
            out = mcpclient.call("nope tool {}", {"mcp": {}})
        self.assertIn("not in inventory", out)


class HttpTransport(unittest.TestCase):
    def _resp(self, payload):
        r = mock.Mock()
        r.read.return_value = json.dumps(payload).encode()
        r.__enter__ = lambda s: s
        r.__exit__ = mock.Mock(return_value=False)
        return r

    def test_extracts_text_content(self):
        reply = {"jsonrpc": "2.0", "id": 1, "result": {
            "content": [{"type": "text", "text": "3 tabs"}]}}
        with mock.patch("urllib.request.urlopen",
                        return_value=self._resp(reply)):
            out = mcpclient._call_http("http://x/mcp", "tabs", {})
        self.assertEqual(out, "3 tabs")

    def test_sse_framing(self):
        body = b'event: message\ndata: {"jsonrpc":"2.0","id":2,' \
               b'"result":{"content":[{"type":"text","text":"ok"}]}}\n'
        r = mock.Mock()
        r.read.return_value = body
        r.__enter__ = lambda s: s
        r.__exit__ = mock.Mock(return_value=False)
        with mock.patch("urllib.request.urlopen", return_value=r):
            out = mcpclient._call_http("http://x/mcp", "tabs", {})
        self.assertEqual(out, "ok")

    def test_rpc_error_reported(self):
        reply = {"jsonrpc": "2.0", "id": 1,
                 "error": {"code": -32601, "message": "no such tool"}}
        with mock.patch("urllib.request.urlopen",
                        return_value=self._resp(reply)):
            out = mcpclient._call_http("http://x/mcp", "nope", {})
        self.assertTrue(out.startswith("MCP_ERROR"))


class StdioTransport(unittest.TestCase):
    def test_handshake_and_call(self):
        responses = [
            {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {}}},
            {"jsonrpc": "2.0", "id": 2, "result": {
                "content": [{"type": "text", "text": "done"}]}},
        ]
        lines = io.StringIO(
            "\n".join(json.dumps(r) for r in responses) + "\n")
        proc = mock.Mock()
        proc.stdout = lines
        proc.stdout.fileno = mock.Mock(return_value=0)
        proc.stdin = mock.Mock()
        with mock.patch("subprocess.Popen", return_value=proc), \
             mock.patch("wisp.tools.mcpclient.select.select",
                        return_value=([0], [], [])):
            out = mcpclient._call_stdio("fakeserver", {}, "t", {})
        self.assertEqual(out, "done")
        sent = [c.args[0] for c in proc.stdin.write.call_args_list]
        methods = [json.loads(s)["method"] for s in sent]
        self.assertEqual(methods, ["initialize",
                                   "notifications/initialized",
                                   "tools/call"])

    def test_silent_server_times_out(self):
        # the blocking-readline bug: a server that never writes must
        # not stall past the deadline — select guards the read
        proc = mock.Mock()
        proc.stdout = io.StringIO("")
        proc.stdout.fileno = mock.Mock(return_value=0)
        proc.stdin = mock.Mock()
        with mock.patch("subprocess.Popen", return_value=proc), \
             mock.patch("wisp.tools.mcpclient.select.select",
                        return_value=([], [], [])):
            with self.assertRaisesRegex(RuntimeError, "reply timeout"):
                mcpclient._call_stdio("fakeserver", {}, "t", {})


class EndToEnd(unittest.TestCase):
    def test_dispatch_prefers_url(self):
        spec = {"url": "http://x/mcp", "command": "ignored"}
        with mock.patch.object(mcpclient, "_server_spec",
                               return_value=spec), \
             mock.patch.object(mcpclient, "_call_http",
                               return_value="via http") as h:
            out = mcpclient.call('srv t {"a": 1}', {"mcp": {}})
        self.assertEqual(out, "via http")
        h.assert_called_once_with("http://x/mcp", "t", {"a": 1})

    def test_dispatch_stdio(self):
        spec = {"command": "mycmd --flag"}
        with mock.patch.object(mcpclient, "_server_spec",
                               return_value=spec), \
             mock.patch.object(mcpclient, "_call_stdio",
                               return_value="via stdio") as s:
            out = mcpclient.call("srv t {}", {"mcp": {}})
        self.assertEqual(out, "via stdio")
        s.assert_called_once_with("mycmd --flag", spec, "t", {})


if __name__ == "__main__":
    unittest.main()
