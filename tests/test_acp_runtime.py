"""ACP runtime integration (U9): the opencode runtime end to end against
the scripted fake agent installed as the pinned `ori` (R3, R5, R6, R7, R9,
R10, R11, R12, R14; KTD1, KTD3, KTD5, KTD13, KTD14). No live model."""
import os
import pathlib
import stat
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from fakes import acp_agent  # noqa: E402
from fakes.bins import BinDir  # noqa: E402
from wisp import (acp_runtime, agent_ask, agent_home, agent_mcp, config,  # noqa: E402
                  agents, cancel, state)

READY = {"state": "ready", "ok": True, "fix": None}
MODEL = "fake/model-a"


def until(fn, what="condition", secs=8.0):
    end = time.time() + secs
    while time.time() < end:
        if fn():
            return
        time.sleep(0.01)
    raise AssertionError(f"never: {what}")


def msg(text):
    return {"update": {"sessionUpdate": "agent_message_chunk",
                       "content": {"type": "text", "text": text}}}


def tool(tid, title, kind="read", status="pending"):
    return {"update": {"sessionUpdate": "tool_call", "toolCallId": tid,
                       "title": title, "kind": kind, "status": status}}


def tool_done(tid, status="completed"):
    return {"update": {"sessionUpdate": "tool_call_update",
                       "toolCallId": tid, "status": status}}


class Bus:
    def __init__(self):
        self.events = []

    def emit_event(self, event, **data):
        self.events.append((event, data))

    def named(self, name):
        return [d for n, d in self.events if n == name]

    def publish(self, *a, **kw):
        return True


class Case(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.dir = pathlib.Path(td.name)
        # never the real ~/.local/share/wisp; absent, as on a fresh CI host
        p = mock.patch.object(config, "DATA_DIR", self.dir / "data")
        p.start()
        self.addCleanup(p.stop)
        self.tf = self.dir / "tasks.jsonl"
        self.ld = self.dir / "tasks"
        self.work = self.dir / "work"
        self.work.mkdir()
        self.rt = self.dir / "runtime"
        self.cur = self.rt / "ori" / "current"
        self.bins = BinDir(self.cur)
        oc = self.rt / "opencode" / "current"
        oc.mkdir(parents=True)
        (oc / "opencode").write_text("#!/bin/sh\n")
        (oc / "opencode").chmod(0o755)
        self.log = acp_agent.install(self.bins, {})
        self.now = [1000.0]
        self.cfg = {"brain": {"agent_runtime": "opencode"},
                    "agent": {"max_concurrent": "3",
                              "task_timeout_s": "1800"},
                    "agents": {"acp_models": MODEL,
                               "cancel_grace_s": "0.3"}}
        self.bus = Bus()
        self.finished = []
        self.st = state.State(self.dir / "state.json", write_initial=False)
        self.broker = cancel.PromptBroker()
        self.spoken = []
        self.ask = agent_ask.AskQueue(
            self.st, self.broker, self.spoken.append,
            lambda n, **d: self.bus.emit_event(n, **d), poll=0.005)
        self.ask.start()
        self.addCleanup(self.ask.stop)
        self.mgr = self.manager(clock=lambda: self.now[0])
        acp_runtime.set_manager(self.mgr)
        self.addCleanup(acp_runtime.set_manager, None)
        self.addCleanup(self.mgr.stop)
        for p in (mock.patch.object(agents, "_RUNTIME_ROOT", self.rt),
                  mock.patch.object(agents, "_pinned_state",
                                    lambda: dict(READY)),
                  mock.patch.object(
                      agent_home, "_root",
                      lambda root=None: root or self.dir / "agents")):
            p.start()
            self.addCleanup(p.stop)

    def manager(self, **kw):
        return acp_runtime.Manager(
            self.cfg, ask=self.ask, bus=self.bus, tasks_file=self.tf,
            log_dir=self.ld, home=self.dir / "home", runtime_root=self.rt,
            on_finished=self.finished.append, wispd_path="/opt/wispd", **kw)

    # -- helpers -------------------------------------------------------

    def script(self, **s):
        s.setdefault("models", [MODEL])
        acp_agent.install(self.bins, s)

    def spawn(self, task="do the thing", **kw):
        kw.setdefault("cwd", str(self.work))
        return agents.spawn(task, self.cfg, self.tf, self.ld, **kw)

    def rec(self, name):
        return agents._find(name, self.tf)

    def status(self, name):
        r = self.rec(name)
        return r.get("status") if r else None

    def settled(self, name):
        until(lambda: self.status(name) not in (None, "running"),
              f"{name} settles")
        return self.rec(name)

    def rows(self, kind=None):
        rows = acp_agent.log_rows(self.log)
        return [r for r in rows if kind is None or r["kind"] == kind]

    def methods(self):
        return [r["msg"].get("method") for r in self.rows("recv")]

    def prompts(self):
        return [r["msg"] for r in self.rows("recv")
                if r["msg"].get("method") == "session/prompt"]

    def pick(self, label):
        until(lambda: self.st.snapshot().get("status") == "awaiting_choice",
              "ask published")
        pid = self.st.snapshot()["prompt_id"]
        self.assertTrue(self.broker.offer(pick=label, prompt_id=pid)["ok"])


class Happy(Case):
    def test_progress_answer_and_one_finished_event(self):
        self.script(prompts=[[
            msg("Looking around."),
            tool("t1", "read notes.md"),
            {"delay": 0.6},
            tool_done("t1"),
            msg("Found it. "), msg("All good.")]])
        out = self.spawn("check the notes")
        self.assertTrue(out.startswith("SPAWNED"), out)
        name = out.split()[1]
        until(lambda: agents.tasks(self.tf, self.ld).get(name, {})
              .get("line"), "line appears")
        entry = agents.tasks(self.tf, self.ld)[name]
        self.assertEqual(entry["status"], "running")
        for k in ("task", "line", "seconds", "tail"):
            self.assertIn(k, entry)
        self.assertIn("read notes.md", entry["line"])
        self.assertIn("read notes.md", (self.ld / f"{name}.log").read_text())
        rec = self.settled(name)
        self.assertEqual(rec["status"], "done")
        self.assertEqual(rec["stop_reason"], "end_turn")
        self.assertEqual(rec["answer"], "Found it. All good.")
        self.assertEqual(rec["model"], MODEL)
        self.assertEqual(rec["session_id"], "sess-1")
        # the reaper never double-reports what the manager reported
        self.assertEqual(agents.reap_tick(self.cfg, self.tf, self.ld), [])
        self.assertEqual(len(self.bus.named("task_finished")), 1)
        self.assertEqual(len(self.finished), 1)
        note = agents.build_done_notification(self.finished[0])
        self.assertIn("Found it. All good.", note["message"])
        self.assertTrue(note["delivered"])

    def test_progress_events_throttled(self):
        self.script(prompts=[[tool(f"t{i}", f"step {i}") for i in range(6)]
                             + [{"delay": 0.2}]])
        name = self.spawn().split()[1]
        self.settled(name)
        self.assertEqual(len(self.bus.named("task_progress")), 1)
        self.assertEqual(self.bus.named("task_progress")[0]["name"], name)

    def test_session_new_carries_wisp_mcp_entry_and_token_is_revoked(self):
        self.script(prompts=[[{"delay": 0.3}]])
        name = self.spawn().split()[1]
        until(lambda: "session/new" in self.methods(), "session/new")
        new = next(r["msg"] for r in self.rows("recv")
                   if r["msg"].get("method") == "session/new")
        entry = new["params"]["mcpServers"][0]
        self.assertEqual(entry["name"], "wisp")
        self.assertEqual(entry["command"], "/opt/wispd")
        self.assertEqual(entry["args"], ["agent-mcp"])
        tok = entry["env"][0]
        self.assertEqual(tok["name"], "WISP_MCP_TOKEN")
        self.assertEqual(agent_mcp.lookup(tok["value"]), name)
        self.settled(name)
        until(lambda: agent_mcp.lookup(tok["value"]) is None, "revoked")

    def test_launch_is_pinned_ori_acp_without_model_flag(self):
        self.script(prompts=[[]])
        name = self.spawn().split()[1]
        self.settled(name)
        start = self.rows("start")[0]
        self.assertEqual(start["argv"], ["opencode", "acp"])
        self.assertTrue(start["env"]["XDG_CONFIG_HOME"].startswith(
            str(self.dir / "home")))
        proc = self.rec(f"acp-{name}")
        self.assertEqual(proc["kind"], "acp_process")
        self.assertEqual(proc["scope"], f"wisp-task-acp-{name}.scope")


class Models(Case):
    def test_only_premium_offered_fails_before_prompting(self):
        self.script(models=["openrouter/x/premium"])
        name = self.spawn().split()[1]
        rec = self.settled(name)
        self.assertEqual(rec["status"], "failed")
        self.assertIn("none of the configured cheap models is available",
                      rec["error"])
        self.assertNotIn("session/prompt", self.methods())
        self.assertNotIn("session/set_config_option", self.methods())

    def test_first_offered_configured_model_is_set(self):
        self.cfg["agents"]["acp_models"] = "m/absent, m/b ,m/a"
        self.script(models=["m/a", "m/b"], prompts=[[]])
        name = self.spawn().split()[1]
        self.assertEqual(self.settled(name)["model"], "m/b")
        sets = [r["msg"]["params"] for r in self.rows("recv")
                if r["msg"].get("method") == "session/set_config_option"]
        self.assertEqual([s["value"] for s in sets], ["m/b"])


class Refusals(Case):
    def test_opencode_1x_is_refused_with_reason(self):
        v1 = {"state": "opencode_v1", "ok": False,
              "fix": "wispd install --agents (never OpenCode 1.x)"}
        with mock.patch.object(agents, "_pinned_state", lambda: v1):
            out = self.spawn()
        self.assertTrue(out.startswith("SKIP"), out)
        self.assertIn("1.x", out)
        self.assertEqual(self.rows("start"), [])

    def test_protocol_not_1_is_refused(self):
        self.script(protocolVersion=2)
        out = self.spawn()
        self.assertTrue(out.startswith("SKIP"), out)
        self.assertIn("protocol", out)
        self.assertEqual(agents._running(self.tf), [])


class Permissions(Case):
    def test_git_push_asks_and_no_sends_reject_once(self):
        self.script(prompts=[[
            {"permission": {"toolCall": {
                "toolCallId": "p1", "title": "git push origin main",
                "kind": "execute",
                "rawInput": {"command": "git push origin main"}}}},
            msg("Not pushed.")]])
        name = self.spawn().split()[1]
        until(lambda: self.spoken, "ask spoken")
        self.assertIn("git push origin main", self.spoken[0])
        self.assertTrue(agents.tasks(self.tf, self.ld)[name]["waiting"])
        self.pick("No")
        rec = self.settled(name)
        self.assertEqual(rec["status"], "done")
        outcome = self.rows("permission_outcome")[0]["outcome"]
        self.assertEqual(outcome, {"outcome": "selected",
                                   "optionId": "reject"})
        self.assertNotIn("waiting", agents.tasks(self.tf, self.ld)[name])

    def test_allow_answer_sends_allow_once(self):
        self.script(prompts=[[
            {"permission": {"toolCall": {
                "toolCallId": "p1", "title": "git push", "kind": "execute",
                "rawInput": {"command": "git push"}}}}]])
        name = self.spawn().split()[1]
        self.pick("Allow")
        self.settled(name)
        self.assertEqual(self.rows("permission_outcome")[0]["outcome"],
                         {"outcome": "selected", "optionId": "allow"})

    def test_read_in_cwd_is_allowed_without_asking(self):
        f = self.work / "notes.md"
        f.write_text("x")
        self.script(prompts=[[
            {"permission": {"toolCall": {
                "toolCallId": "p1", "title": "read notes.md",
                "kind": "read", "locations": [{"path": str(f)}],
                "rawInput": {"filePath": str(f)}}}}]])
        name = self.spawn().split()[1]
        self.settled(name)
        self.assertEqual(self.rows("permission_outcome")[0]["outcome"],
                         {"outcome": "selected", "optionId": "allow"})
        self.assertEqual(self.spoken, [])

    def test_written_test_file_makes_the_runner_ask(self):
        """Write test_payload.py, then run it: the run must not be
        auto-allowed (the agent's own code would execute unconfirmed)."""
        f = self.work / "test_payload.py"
        self.script(prompts=[[
            {"permission": {"toolCall": {
                "toolCallId": "p1", "title": "write test_payload.py",
                "kind": "edit", "locations": [{"path": str(f)}],
                "rawInput": {"filePath": str(f)}}}},
            {"permission": {"toolCall": {
                "toolCallId": "p2",
                "title": "python3 -m unittest test_payload",
                "kind": "execute",
                "rawInput": {
                    "command": "python3 -m unittest test_payload"}}}}]])
        name = self.spawn().split()[1]
        until(lambda: self.spoken, "ask spoken")
        self.assertIn("unittest test_payload", self.spoken[0])
        self.pick("No")
        self.settled(name)
        outs = [r["outcome"]["optionId"]
                for r in self.rows("permission_outcome")]
        self.assertEqual(outs, ["allow", "reject"])

    def test_refused_call_is_rejected_and_counted(self):
        self.script(prompts=[[
            {"permission": {"toolCall": {
                "toolCallId": "p1", "title": "omaseal get key",
                "kind": "execute",
                "rawInput": {"command": "omaseal get key"}}}}]])
        name = self.spawn().split()[1]
        rec = self.settled(name)
        self.assertEqual(self.rows("permission_outcome")[0]["outcome"],
                         {"outcome": "selected", "optionId": "reject"})
        self.assertEqual(self.spoken, [])
        self.assertEqual(self.rec(name)["refused_count"], 1)
        self.assertEqual(rec["status"], "done")


class Followups(Case):
    def helper(self, task="start"):
        out = self.spawn(task, agent="scout")
        self.assertTrue(out.startswith("SPAWNED"), out)
        return out.split()[1]

    def test_tell_mid_turn_queues_into_the_same_session(self):
        self.script(prompts=[[{"delay": 0.8}, msg("first done")],
                             [msg("second done")]])
        name = self.helper()
        until(lambda: self.prompts(), "first prompt sent")
        out = agents.run_named(
            agent_home.encode("tell", name="Scout", message="also do B"),
            self.cfg, self.tf, log_dir=self.ld)
        self.assertTrue(out.startswith("ACTED"), out)
        self.assertEqual(len(self.prompts()), 1)     # waits its turn
        rec = self.settled(name)
        self.assertEqual(rec["status"], "done")
        self.assertEqual(rec["answer"], "second done")
        ps = self.prompts()
        self.assertEqual(len(ps), 2)
        self.assertEqual({p["params"]["sessionId"] for p in ps}, {"sess-1"})
        self.assertEqual(ps[1]["params"]["prompt"][0]["text"], "also do B")
        self.assertEqual(self.methods().count("session/new"), 1)
        self.assertFalse((self.dir / "agents" / "scout" / "inbox.md").exists())

    def test_idle_process_is_reused_and_idles_out(self):
        self.script(prompts=[[msg("one")], [msg("two")]])
        first = self.helper()
        self.settled(first)
        self.assertEqual(len(self.rows("start")), 1)
        second = self.helper("again")
        self.assertNotEqual(first, second)
        self.settled(second)
        self.assertEqual(len(self.rows("start")), 1)    # same process
        self.assertEqual(self.methods().count("session/new"), 2)
        proc = self.rec("acp-scout")
        self.assertTrue(agents._alive(proc["pid"], proc["pstart"]))
        self.now[0] += 899
        self.mgr.sweep()
        self.assertEqual(self.status("acp-scout"), "running")
        self.now[0] += 2
        self.mgr.sweep()
        self.assertEqual(self.status("acp-scout"), "exited")
        until(lambda: not agents._alive(proc["pid"], proc["pstart"]),
              "process gone")
        third = self.helper("once more")
        self.settled(third)
        self.assertEqual(len(self.rows("start")), 2)    # fresh process


class Cancel(Case):
    def test_cancel_mid_turn_reads_cancelled(self):
        self.script(prompts=[[{"wait_cancel": True}]])
        name = self.spawn().split()[1]
        until(lambda: self.prompts(), "prompt sent")
        self.assertEqual(agents.cancel(name, self.tf), f"CANCELLED {name}")
        rec = self.settled(name)
        self.assertEqual(rec["status"], "cancelled")
        self.assertIn("session/cancel", self.methods())

    def ignore_cancel(self):
        """Install an `ori` whose prompt never ends and that ignores
        session/cancel, so the cancel grace window stays open."""
        stub = self.cur / "ori"
        opts = ("[{'id':'model','category':'model','type':'select',"
                "'currentValue':'fake/model-a',"
                "'options':[{'value':'fake/model-a'}]}]")
        stub.write_text(
            f"#!{sys.executable}\n"
            "import json, sys, time\n"
            "def send(o):\n"
            "    sys.stdout.write(json.dumps(o) + '\\n')\n"
            "    sys.stdout.flush()\n"
            f"OPTS = {opts}\n"
            "for line in sys.stdin:\n"
            "    m = json.loads(line)\n"
            "    r, me = m.get('id'), m.get('method')\n"
            "    ok = lambda res: send({'jsonrpc': '2.0', 'id': r, 'result': res})\n"
            "    if me == 'initialize':\n"
            "        ok({'protocolVersion': 1, 'agentCapabilities': {}})\n"
            "    elif me == 'session/new':\n"
            "        ok({'sessionId': 's1', 'configOptions': OPTS})\n"
            "    elif me == 'session/set_config_option':\n"
            "        ok({'configOptions': OPTS})\n"
            "    elif me == 'session/prompt':\n"
            "        time.sleep(600)\n")
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)

    def test_follow_up_during_cancel_is_not_accepted(self):
        # review: a tell in the cancel grace window was reported queued,
        # then dropped when the session ended
        self.ignore_cancel()
        name = self.spawn("start", agent="scout").split()[1]
        until(lambda: self.rec(name).get("model") == MODEL, "model set")
        time.sleep(0.2)                 # the prompt is in flight
        agents.cancel(name, self.tf)
        self.assertFalse(self.mgr.tell("scout", "also do B"))

    def test_agent_that_ignores_cancel_is_killed_after_the_grace(self):
        self.ignore_cancel()
        name = self.spawn().split()[1]
        until(lambda: self.rec(name).get("model") == MODEL, "model set")
        time.sleep(0.2)                 # the prompt is in flight
        proc = self.rec(f"acp-{name}")
        t0 = time.time()
        agents.cancel(name, self.tf)
        rec = self.settled(name)
        self.assertEqual(rec["status"], "cancelled")
        self.assertGreaterEqual(time.time() - t0, 0.25)     # grace first
        until(lambda: not agents._alive(proc["pid"], proc["pstart"]),
              "leader dead")

        def group_gone():
            try:
                os.killpg(proc["pid"], 0)
            except ProcessLookupError:
                return True
            except PermissionError:
                return False
            return False
        until(group_gone, "no stray pid in the group")

    def test_session_past_task_timeout_is_cancelled_and_timed_out(self):
        self.script(prompts=[[{"wait_cancel": True}]])
        name = self.spawn().split()[1]
        until(lambda: self.prompts(), "prompt sent")
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        agents._log_line({"id": name, "name": name, "started": old}, self.tf)
        agents.reap_tick(self.cfg, self.tf, self.ld)
        rec = self.settled(name)
        self.assertEqual(rec["status"], "timed_out")
        self.assertIn("session/cancel", self.methods())


class Failure(Case):
    def test_crash_mid_turn_fails_with_last_line_and_next_spawn_is_fresh(self):
        self.script(prompts=[[tool("t1", "step one"), {"delay": 0.2},
                              {"crash": 3}]])
        first = self.spawn("first", agent="scout").split()[1]
        rec = self.settled(first)
        self.assertEqual(rec["status"], "failed")
        self.assertIn("step one", rec["error"])
        self.assertIn("step one", (self.ld / f"{first}.log").read_text())
        until(lambda: self.status("acp-scout") == "exited", "process closed")
        self.script(prompts=[[msg("fine")]])
        second = self.spawn("second", agent="scout").split()[1]
        self.assertEqual(self.settled(second)["status"], "done")
        self.assertEqual(len(self.rows("start")), 2)

    def test_stop_reasons_map_to_failed_with_the_reason(self):
        for reason in ("max_tokens", "refusal", "max_turn_requests"):
            self.script(prompts=[[msg("partial"), {"stop": reason}]])
            name = self.spawn(f"run {reason}").split()[1]
            rec = self.settled(name)
            self.assertEqual(rec["status"], "failed")
            self.assertEqual(rec["stop_reason"], reason)
            self.assertIn(reason, rec["error"])

    def test_claimed_file_absent_is_not_delivered(self):
        self.script(prompts=[[msg("I wrote report.md for you.")]])
        name = self.spawn("write it", delivers=["report.md"]).split()[1]
        rec = self.settled(name)
        self.assertEqual(rec["status"], "done")
        self.assertFalse(rec["delivered"])
        self.assertEqual(rec["deliverables"][0]["status"], "missing")
        note = agents.build_done_notification(self.finished[0])
        self.assertIn("not on disk", note["message"])
        self.assertFalse(note["delivered"])


class Resume(Case):
    def test_restart_interrupts_and_continue_loads_the_stored_session(self):
        self.script(prompts=[[{"wait_cancel": True}]])
        name = self.spawn("long job", agent="scout").split()[1]
        until(lambda: self.prompts(), "prompt sent")
        self.mgr.stop()
        self.assertEqual(self.status(name), "interrupted")
        self.assertEqual(self.rec(name)["session_id"], "sess-1")
        self.assertEqual(self.finished, [])        # a restart is no result
        self.script(prompts=[[msg("resumed ok")]])
        m2 = self.manager()
        acp_runtime.set_manager(m2)
        self.addCleanup(m2.stop)
        out = agents.run_named(agent_home.encode("continue", name="Scout"),
                               self.cfg, self.tf, log_dir=self.ld)
        self.assertTrue(out.startswith("ACTED"), out)
        rec = self.settled(name)
        self.assertEqual(rec["status"], "done")
        self.assertEqual(rec["answer"], "resumed ok")
        load = next(r["msg"] for r in self.rows("recv")
                    if r["msg"].get("method") == "session/load")
        self.assertEqual(load["params"]["sessionId"], "sess-1")
        after = self.methods()[self.methods().index("session/load"):]
        self.assertNotIn("session/new", after)

    def test_start_sweeps_orphans_into_interrupted(self):
        agents.record_process("acp-scout", 2 ** 22 + 1, tasks_file=self.tf)
        agents.record_session("scout", "x", "acp-scout", "s9",
                              tasks_file=self.tf)
        self.mgr.start()
        self.assertEqual(self.status("scout"), "interrupted")

    def test_continue_without_load_support_says_so(self):
        agents.record_session("scout", "x", "acp-scout", "s9",
                              cwd=str(self.work), tasks_file=self.tf,
                              agent="scout")
        agents._log_line({"id": "scout", "name": "scout",
                          "status": "interrupted"}, self.tf)
        self.script(prompts=[[]])
        orig = acp_runtime.acp.AcpConnection.initialize

        def no_load(conn):
            res = orig(conn)
            conn.agent_capabilities = {}
            return res
        with mock.patch.object(acp_runtime.acp.AcpConnection,
                               "initialize", no_load):
            out = agents.run_named(
                agent_home.encode("continue", name="Scout"),
                self.cfg, self.tf, log_dir=self.ld)
        self.assertIn("can't", out)
        self.assertEqual(self.status("scout"), "interrupted")
        self.assertNotIn("session/prompt", self.methods())


class Runtime(Case):
    def test_auto_resolves_to_pinned_opencode_never_a_path_ori(self):
        decoy = BinDir(self.dir / "pathbin")
        decoy.install("ori")
        self.script(prompts=[[msg("hi")]])
        self.cfg["brain"]["agent_runtime"] = "auto"
        with mock.patch.dict(os.environ, {"PATH": str(decoy.path)}):
            self.assertEqual(agents.resolve_runtime(self.cfg), "opencode")
            self.assertEqual(agents.detect_runtimes()["opencode"],
                             str(self.cur / "ori"))
            name = self.spawn().split()[1]
            self.settled(name)
        self.assertEqual(decoy.calls(), [])
        self.assertEqual(len(self.rows("start")), 1)

    def test_path_ori_alone_does_not_count_as_installed(self):
        decoy = BinDir(self.dir / "pathbin")
        decoy.install("ori")
        self.cfg["brain"]["agent_runtime"] = "auto"
        absent = {"state": "absent", "ok": False}
        with mock.patch.dict(os.environ, {"PATH": str(decoy.path)}), \
                mock.patch.object(agents, "_pinned_state", lambda: absent):
            self.assertEqual(agents.resolve_runtime(self.cfg), "")
            self.assertNotIn("opencode", agents.detect_runtimes())
            out = self.spawn()
        self.assertTrue(out.startswith("SKIP"), out)
        self.assertEqual(decoy.calls(), [])

    def test_codex_keeps_the_one_shot_path(self):
        self.cfg["brain"]["agent_runtime"] = "codex"
        proc = mock.Mock(pid=4242)
        with mock.patch.object(agents.shutil, "which",
                               return_value="/usr/bin/codex"), \
                mock.patch.object(agents.subprocess, "Popen",
                                  return_value=proc), \
                mock.patch.object(agents, "_proc_stat",
                                  return_value=("S", "99")):
            out = self.spawn("one shot")
        self.assertIn("SPAWNED one-shot (pid 4242)", out)
        rec = self.rec("one-shot")
        self.assertEqual(rec["pid"], 4242)
        self.assertIn("codex exec", rec["cmd"])
        self.assertNotIn("kind", rec)
        self.assertEqual(self.rows("start"), [])


if __name__ == "__main__":
    unittest.main()
