#!/usr/bin/env python3
"""U8: MCP stdio bridge, allowlist and session tokens (R13, KTD10, KTD11)."""
import importlib.machinery
import importlib.util
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import threading
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import shorttmp  # noqa: E402
from wisp import agent_mcp, agents, config, state as state_mod  # noqa: E402
from wisp import tools  # noqa: E402


def _load_wispd():
    loader = importlib.machinery.SourceFileLoader(
        "wispd_u8_test", str(ROOT / "wispd"))
    spec = importlib.util.spec_from_loader("wispd_u8_test", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


WISPD = _load_wispd()

ALLOW = ["recall", "memory_read", "skill_list", "skill_view",
         "task_status", "task_output", "task_artifacts", "ask_user"]


class FakeAsk:
    """Stands in for the U7 queue: answers (or not) synchronously."""

    def __init__(self, answer="blue"):
        self.answer = answer
        self.calls = []

    def submit(self, helper, kind, text, choices, deadline, on_answer):
        self.calls.append((helper, kind, text, choices, deadline))
        on_answer(self.answer)


class McpBase(unittest.TestCase):
    def setUp(self):
        if agents._SCOPE_RE.search(agents._proc_cgroup(os.getpid())):
            self.skipTest("test process runs inside a wisp-task scope")
        self.td = pathlib.Path(shorttmp.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.td, ignore_errors=True))
        self.tf = self.td / "tasks.jsonl"
        self.st = state_mod.StateBus()
        self.addCleanup(self.st.close)
        self.cfg = config._default_cfg_dict()
        self.ask = FakeAsk()
        self.ctl = {"stop": threading.Event(), "busy": threading.Event(),
                    "interrupt": threading.Event(),
                    "choice_event": threading.Event(), "choice_pick": "",
                    "broker": None, "token": None, "rec": None,
                    "rec_lock": threading.Lock(), "agent_ask": self.ask}
        self.handle = WISPD._handler(self.st, self.cfg, self.ctl,
                                     tasks_file=self.tf)
        self.procs = []
        self.addCleanup(self._cleanup)
        self.proc = self._sleeper()
        agents.record_process("acp-1", self.proc.pid, tasks_file=self.tf)
        agents.record_session("scout", "t", "acp-1", tasks_file=self.tf)
        agents.record_session("rex", "t", "acp-1", tasks_file=self.tf)
        self.peer = {"pid": self.proc.pid, "uid": os.getuid()}
        self.token = agent_mcp.mint("scout")
        self.addCleanup(agent_mcp.revoke, self.token)

    def _sleeper(self):
        p = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={k: v for k, v in os.environ.items()
                 if k != "WISP_TASK_ID"})
        self.procs.append(p)
        return p

    def _cleanup(self):
        for p in self.procs:
            p.kill()
            p.wait(timeout=2)

    def call(self, name, args=None, token="", peer=None):
        return self.handle(
            {"cmd": "agent_tool", "token": token or self.token,
             "name": name, "args": args or {}},
            peer or self.peer)

    def refused(self, sess="scout"):
        return agents._find(sess, self.tf).get("refused_count", 0)


class ToolsTest(McpBase):
    def test_tools_list_is_exactly_the_allowlist(self):
        names = [t["name"] for t in agent_mcp.tool_defs(self.cfg)]
        self.assertEqual(sorted(names), sorted(ALLOW))
        for t in agent_mcp.tool_defs(self.cfg):
            self.assertEqual(t["inputSchema"]["type"], "object")

    def test_mcp_memory_false_withholds_memory_tools(self):
        cfg = {"agents": {"mcp_memory": "false"}}
        names = [t["name"] for t in agent_mcp.tool_defs(cfg)]
        self.assertNotIn("recall", names)
        self.assertNotIn("memory_read", names)
        self.assertIn("skill_list", names)
        self.cfg["agents"] = dict(self.cfg.get("agents") or {},
                                  mcp_memory="false")
        r = self.call("recall", {"query": "x"})
        self.assertFalse(r["ok"])
        self.assertEqual(self.refused(), 1)

    def test_recall_from_marked_peer_returns_results(self):
        with mock.patch("wisp.recall.run", return_value="HIT one") as run:
            r = self.call("recall", {"query": "dogs"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["result"], "HIT one")
        run.assert_called_once_with("dogs")
        self.assertEqual(self.refused(), 0)

    def test_registry_readers_exist_and_are_t0(self):
        for n in ("memory_read", "skill_list"):
            self.assertEqual(tools.meta_of(n)["tier"], "T0")

    def test_every_allowlisted_registry_tool_is_t0(self):
        for n in ALLOW:
            meta = tools.meta_of(n)
            if meta:
                self.assertEqual(meta["tier"], "T0", n)
        self.assertEqual(sorted(agent_mcp.ALLOWLIST), sorted(ALLOW))

    def test_other_tools_are_refused_and_counted(self):
        names = ["memory", "skill_manage", "agent_spawn", "task_cancel",
                 "choice", "config", "shell", "mcp_call", "click",
                 "type_text"]
        for i, n in enumerate(names, 1):
            with self.subTest(tool=n):
                r = self.call(n, {})
                self.assertFalse(r["ok"], r)
                self.assertEqual(r["error"], "tool_refused")
                self.assertEqual(self.refused(), i)


class TokenTest(McpBase):
    def test_bad_tokens_are_rejected(self):
        other = agent_mcp.mint("rex")
        self.addCleanup(agent_mcp.revoke, other)
        gone = agent_mcp.mint("scout")
        agent_mcp.revoke(gone)
        for tok in ("nope", gone, ""):
            with self.subTest(token=tok):
                r = self.handle({"cmd": "agent_tool", "token": tok,
                                 "name": "recall", "args": {}}, self.peer)
                self.assertFalse(r["ok"])
                self.assertEqual(r["error"], "bad_token")
        # another session's token still maps to that session only
        self.assertEqual(agent_mcp.lookup(other), "rex")
        self.assertEqual(agent_mcp.lookup(self.token), "scout")

    def test_valid_token_from_unmarked_process_is_rejected(self):
        stranger = self._sleeper()
        r = self.call("recall", {"query": "x"},
                      peer={"pid": stranger.pid, "uid": os.getuid()})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], "not_marked_peer")

    def test_marked_peer_still_refused_config_over_socket(self):
        r = self.handle({"cmd": "config",
                         "set": {"agent.allow_shell": "true"}}, self.peer)
        self.assertEqual(r["error"], "marked_peer_refused")
        self.assertEqual(r["reason"], "safety_key")

    def test_marked_peer_other_ipc_cmds_stay_refused(self):
        r = self.handle({"cmd": "task_cancel", "name": "x"}, self.peer)
        self.assertEqual(r["error"], "marked_peer_refused")


class TaskScopeTest(McpBase):
    def test_own_task_reads_pass(self):
        with mock.patch("wisp.agents.output",
                        return_value={"ok": True, "output": "log"}) as o:
            r = self.call("task_output", {})
        self.assertTrue(r["ok"], r)
        self.assertEqual(o.call_args.args[0], "scout")
        with mock.patch("wisp.agents.status", return_value="TASK scout"):
            r = self.call("task_status", {"name": "Scout"})
        self.assertTrue(r["ok"], r)

    def test_other_helpers_task_is_refused(self):
        r = self.call("task_output", {"name": "rex"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], "tool_refused")
        self.assertEqual(r["reason"], "other_helper")
        self.assertEqual(self.refused(), 1)


class AskTest(McpBase):
    def test_ask_user_returns_the_answer(self):
        r = self.call("ask_user", {"question": "color?",
                                   "choices": ["red", "blue"]})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["result"], "blue")
        helper, kind, text, choices, _dl = self.ask.calls[0]
        self.assertEqual((helper, kind, text, choices),
                         ("scout", "question", "color?", ["red", "blue"]))

    def test_ask_user_no_answer_on_timeout(self):
        self.ask.answer = None
        r = self.call("ask_user", {"question": "color?"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["result"], "no answer")

    def test_ask_timeout_comes_from_cfg(self):
        self.cfg["agents"] = dict(self.cfg.get("agents") or {},
                                  ask_timeout_s="30")
        with mock.patch("time.monotonic", return_value=500.0):
            self.call("ask_user", {"question": "q"})
        self.assertEqual(self.ask.calls[0][4], 530.0)

    def test_one_pending_ask_per_helper(self):
        class Hold(FakeAsk):
            def submit(s, *a):
                s.calls.append(a)
                s.cb = a[-1]
        hold = Hold()
        self.ctl["agent_ask"] = hold
        t = threading.Thread(target=self.call, args=("ask_user",
                             {"question": "one"}), daemon=True)
        t.start()
        for _ in range(400):
            if hold.calls:
                break
            threading.Event().wait(0.005)
        r = self.call("ask_user", {"question": "two"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], "ask_pending")
        hold.cb("done")
        t.join(2)
        self.ctl["agent_ask"] = self.ask
        self.assertTrue(self.call("ask_user", {"question": "3"})["ok"])


class BridgeTest(McpBase):
    def _run(self, msgs, send=None):
        out = io.StringIO()
        inp = io.StringIO("".join(json.dumps(m) + "\n" for m in msgs))
        agent_mcp.serve(inp, out, send or (lambda c: self.handle(c, self.peer)),
                        self.token, self.cfg)
        return [json.loads(l) for l in out.getvalue().splitlines()]

    def test_handshake_list_and_call(self):
        with mock.patch("wisp.recall.run", return_value="HIT"):
            rs = self._run([
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2024-11-05"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                 "params": {"name": "recall",
                            "arguments": {"query": "q"}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                 "params": {"name": "shell", "arguments": {}}},
            ])
        self.assertEqual([r["id"] for r in rs], [1, 2, 3, 4])
        self.assertIn("tools", rs[0]["result"]["capabilities"])
        self.assertEqual(sorted(t["name"] for t in rs[1]["result"]["tools"]),
                         sorted(ALLOW))
        self.assertEqual(rs[2]["result"]["content"][0]["text"], "HIT")
        self.assertIn("error", rs[3])
        self.assertEqual(self.refused(), 1)

    def test_token_rides_the_ipc_command_not_the_replies(self):
        seen = []

        def send(c):
            seen.append(c)
            return {"ok": True, "result": "x"}
        rs = self._run([{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                         "params": {"name": "recall",
                                    "arguments": {}}}], send)
        self.assertEqual(seen[0]["cmd"], "agent_tool")
        self.assertEqual(seen[0]["token"], self.token)
        self.assertNotIn(self.token, json.dumps(rs))


if __name__ == "__main__":
    unittest.main()
