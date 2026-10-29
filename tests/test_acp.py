"""ACP client core (wisp/acp.py) against the scripted fake agent."""
import pathlib
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, ".")
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from fakes import acp_agent  # noqa: E402
from fakes.bins import BinDir  # noqa: E402
from wisp import acp  # noqa: E402


def _wait(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


class AcpCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.bins = BinDir(self._tmp.name)
        self.conns = []
        self.baseline = threading.active_count()

    def connect(self, script, **kw):
        log = acp_agent.install(self.bins, script)
        self.log = log
        conn = acp.AcpConnection(
            [str(self.bins.path / "ori"), "opencode", "acp", "--extra"],
            cwd=self._tmp.name, **kw)
        self.conns.append(conn)
        self.addCleanup(conn.close)
        return conn

    def started(self):
        rows = [r for r in acp_agent.log_rows(self.log)
                if r["kind"] == "start"]
        return rows[0]


class Handshake(AcpCase):
    def test_initialize_protocol_1(self):
        c = self.connect({})
        res = c.initialize()
        self.assertEqual(res["protocolVersion"], 1)
        self.assertIn("agentCapabilities", res)
        self.assertEqual(self.started()["argv"],
                         ["opencode", "acp", "--extra"])

    def test_version_2_raises(self):
        c = self.connect({"protocolVersion": 2})
        with self.assertRaises(acp.AcpVersionError):
            c.initialize()

    def test_session_and_model_option(self):
        c = self.connect({"models": ["m/a", "m/b"]})
        c.initialize()
        s = c.new_session("/tmp", [])
        self.assertEqual(s["sessionId"], "sess-1")
        opts = c.set_config_option(s["sessionId"], "model", "m/b")
        self.assertEqual(opts["configOptions"][0]["currentValue"], "m/b")


class Prompting(AcpCase):
    def test_ordered_updates_and_end_turn(self):
        c_updates = []
        steps = [
            {"update": {"sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": "a"}}},
            {"update": {"sessionUpdate": "tool_call", "toolCallId": "t1"}},
            {"update": {"sessionUpdate": "tool_call_update",
                        "toolCallId": "t1", "status": "completed"}},
            {"update": {"sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": "b"}}},
        ]
        c = self.connect({"prompt": steps},
                         on_update=lambda sid, u: c_updates.append(
                             (sid, u["sessionUpdate"])))
        c.initialize()
        sid = c.new_session("/tmp", [])["sessionId"]
        h = c.prompt(sid, "hi")
        self.assertEqual(h.wait(5), "end_turn")
        self.assertEqual([u for _, u in c_updates],
                         ["agent_message_chunk", "tool_call",
                          "tool_call_update", "agent_message_chunk"])
        self.assertEqual({s for s, _ in c_updates}, {sid})

    def test_permission_answered_later(self):
        got = []
        c = self.connect(
            {"prompt": [{"permission": {"toolCall": {"toolCallId": "t"}}}]},
            on_permission=lambda sid, tc, opts, reply: got.append(
                (tc, opts, reply)))
        c.initialize()
        sid = c.new_session("/tmp", [])["sessionId"]
        h = c.prompt(sid, "go")
        self.assertTrue(_wait(lambda: got))
        self.assertFalse(h._fut.done.is_set())
        tc, opts, reply = got[0]
        self.assertEqual(tc["toolCallId"], "t")
        reply("allow")
        self.assertEqual(h.wait(5), "end_turn")
        outs = [r["outcome"] for r in acp_agent.log_rows(self.log)
                if r["kind"] == "permission_outcome"]
        self.assertEqual(outs, [{"outcome": "selected",
                                 "optionId": "allow"}])

    def test_cancel_answers_pending_permission_cancelled(self):
        got = []
        c = self.connect(
            {"prompt": [{"permission": {"toolCall": {}}}]},
            on_permission=lambda sid, tc, opts, reply: got.append(reply))
        c.initialize()
        sid = c.new_session("/tmp", [])["sessionId"]
        h = c.prompt(sid, "go")
        self.assertTrue(_wait(lambda: got))
        c.cancel(sid)
        self.assertEqual(h.wait(5), "cancelled")
        rows = acp_agent.log_rows(self.log)
        self.assertTrue(any(r.get("msg", {}).get("method")
                            == "session/cancel" for r in rows))
        outs = [r["outcome"] for r in rows
                if r["kind"] == "permission_outcome"]
        self.assertEqual(outs, [{"outcome": "cancelled"}])


class Transport(AcpCase):
    def test_stderr_flood_does_not_block(self):
        c = self.connect({"stderr_bytes": 2 * 1024 * 1024,
                          "prompt": [{"stderr": 2 * 1024 * 1024}]})
        c.initialize()
        sid = c.new_session("/tmp", [])["sessionId"]
        self.assertEqual(c.prompt(sid, "x").wait(15), "end_turn")

    def test_exit_mid_turn_raises_closed(self):
        c = self.connect({"prompt": [{"crash": 3}]})
        c.initialize()
        sid = c.new_session("/tmp", [])["sessionId"]
        with self.assertRaises(acp.AcpClosed):
            c.prompt(sid, "x").wait(5)
        self.assertTrue(c.dead)

    def test_oversized_line_is_framing_error(self):
        c = self.connect({"prompt": [{"huge_line": 20 * 1024 * 1024}]})
        c.initialize()
        sid = c.new_session("/tmp", [])["sessionId"]
        with self.assertRaises(acp.AcpFramingError):
            c.prompt(sid, "x").wait(15)

    def test_close_leaves_no_threads(self):
        c = self.connect({})
        c.initialize()
        c.close()
        self.assertTrue(_wait(
            lambda: threading.active_count() <= self.baseline))


if __name__ == "__main__":
    unittest.main()
