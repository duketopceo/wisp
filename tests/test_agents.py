"""Agent registry — tasks() progress tails + finished() transitions."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from wisp import agents


class AgentsTest(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.tasks_file = self.dir / "tasks.jsonl"
        self.logs = self.dir / "tasks"
        self.logs.mkdir()
        self.addCleanup(mock.patch.stopall)

    def _rec(self, name="build", pid=999999, status="running"):
        return {"id": "x1", "name": name, "pid": pid, "status": status,
                "task": "do the thing", "ts": "2026-01-01T00:00:00+00:00",
                "pstart": "1"}

    def test_tasks_includes_log_tail(self):
        (self.logs / "x1.log").write_text("step 1\nstep 2 done\n")
        self.tasks_file.write_text(
            __import__("json").dumps(self._rec()) + "\n")
        with mock.patch.object(agents, "_alive", return_value=True):
            out = agents.tasks(self.tasks_file, self.logs)
        self.assertEqual(out["build"]["status"], "running")
        self.assertEqual(out["build"]["tail"], "step 2 done")

    def test_finished_transition(self):
        prev = {"build": {"status": "running"},
                "other": {"status": "exited"}}
        cur = {"build": {"status": "exited", "tail": "ok"},
               "other": {"status": "exited"}}
        done = agents.finished(prev, cur)
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0]["name"], "build")
        # still-running and already-exited don't refire
        self.assertEqual(agents.finished(cur, cur), [])


class AcpSessionTest(unittest.TestCase):
    """The registry side of an ACP session (U9): live line/seconds, the
    answer in the notification, no signal to an ACP process, runtime
    detection from the pinned install."""

    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.tf = self.dir / "tasks.jsonl"
        self.logs = self.dir / "tasks"
        self.logs.mkdir()
        self.addCleanup(mock.patch.stopall)

    def test_running_session_entry_has_line_and_seconds(self):
        started = (datetime.now(timezone.utc)
                   - timedelta(seconds=90)).isoformat()
        agents._log_line({"id": "p", "name": "p", "kind": "acp_process",
                          "pid": os.getpid(), "status": "running",
                          "pstart": agents._pstart(os.getpid()),
                          "ts": started}, self.tf)
        agents._log_line({"id": "s", "name": "s", "kind": "session",
                          "acp_process": "p", "status": "running",
                          "task": "t", "ts": started}, self.tf)
        (self.logs / "s.log").write_text("read: a.py [completed]\n")
        e = agents.tasks(self.tf, self.logs)["s"]
        self.assertEqual(e["line"], "read: a.py [completed]")
        self.assertGreaterEqual(e["seconds"], 90)
        self.assertEqual(e["tail"], e["line"])
        self.assertNotIn("p", agents.tasks(self.tf, self.logs))

    def test_expiry_never_signals_an_acp_process(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        sleeper = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True)
        self.addCleanup(sleeper.wait)
        self.addCleanup(sleeper.kill)
        agents.record_process("acp-x", sleeper.pid, tasks_file=self.tf)
        agents._log_line({"id": "acp-x", "name": "acp-x", "started": old},
                         self.tf)
        agents.record_session("x", "t", "acp-x", tasks_file=self.tf)
        agents._log_line({"id": "x", "name": "x", "started": old}, self.tf)
        # no manager running: the session is left alone too
        self.assertEqual(agents._reap_expired(
            {"agent": {"task_timeout_s": "60"}}, self.tf), [])
        self.assertIsNone(sleeper.poll())

    def test_notification_speaks_the_answer_for_a_done_task(self):
        note = agents.build_done_notification(
            {"name": "scout", "status": "done", "tail": "tool: x [completed]",
             "answer": "Sorted the inbox.\nThree need you."})
        self.assertIn("Sorted the inbox. Three need you.", note["message"])
        self.assertNotIn("tool: x", note["message"])
        failed = agents.build_done_notification(
            {"name": "scout", "status": "failed", "tail": "boom",
             "answer": "partial text"})
        self.assertIn("boom", failed["message"])

    def test_opencode_counts_only_from_the_pinned_install(self):
        cfg = {"brain": {"agent_runtime": "auto"}}
        which = lambda b: "/usr/bin/" + b if b == "ori" else None  # noqa: E731
        with mock.patch.object(agents.shutil, "which", side_effect=which), \
                mock.patch.object(agents, "_pinned_state",
                                  return_value={"state": "absent"}):
            self.assertEqual(agents.resolve_runtime(cfg), "")
            self.assertEqual(agents.detect_runtimes(), {})
        with mock.patch.object(agents.shutil, "which", return_value=None), \
                mock.patch.object(agents, "_pinned_state",
                                  return_value={"state": "installed"}):
            self.assertEqual(agents.resolve_runtime(cfg), "opencode")
        with mock.patch.object(agents.shutil, "which", return_value=None), \
                mock.patch.object(agents, "_pinned_state",
                                  return_value={"state": "opencode_v1"}):
            self.assertEqual(agents.resolve_runtime(cfg), "")


class ScrubEnvTest(unittest.TestCase):
    """R11: spawned agents do not inherit Wisp-held credentials."""

    def setUp(self):
        self.env_file = pathlib.Path(tempfile.mkdtemp()) / ".env"
        p = mock.patch.object(agents.config, "ENV_FILE", self.env_file)
        p.start()
        self.addCleanup(p.stop)

    ENV = {"PATH": "/usr/bin", "HOME": "/home/x",
           "OPENROUTER_API_KEY": "sk-or", "GROQ_API_KEY": "gq",
           "ANTHROPIC_API_KEY": "runtime-own", "CUSTOM_STT": "c"}

    def test_drops_builtin_and_configured_key_envs(self):
        cfg = {"stt": {"key_env": "omaseal://groq/default,CUSTOM_STT"}}
        out = agents.scrub_env(self.ENV, cfg)
        self.assertEqual(sorted(out), ["ANTHROPIC_API_KEY", "HOME", "PATH"])

    def test_drops_names_in_env_file(self):
        self.env_file.write_text("# keys\nexport ANTHROPIC_API_KEY=x\n")
        out = agents.scrub_env(self.ENV, {})
        self.assertNotIn("ANTHROPIC_API_KEY", out)
        self.assertIn("CUSTOM_STT", out)

    def test_env_pass_allows_a_name(self):
        out = agents.scrub_env(
            self.ENV, {"agents": {"env_pass": "GROQ_API_KEY, X"}})
        self.assertEqual(out["GROQ_API_KEY"], "gq")
        self.assertNotIn("OPENROUTER_API_KEY", out)

    def test_spawn_child_env_is_scrubbed(self):
        d = pathlib.Path(tempfile.mkdtemp())
        seen = {}

        class P:
            pid = 4242

        def fake_popen(cmd, **kw):
            seen.update(kw["env"])
            return P()

        with mock.patch.dict(agents.os.environ, self.ENV, clear=True), \
                mock.patch.object(agents, "_runtime_cmd",
                                  return_value=["agent", "run"]), \
                mock.patch.object(agents, "_pinned_state",
                                  return_value={"state": "absent"}), \
                mock.patch.object(agents, "_systemd_scope_enabled",
                                  return_value=False), \
                mock.patch.object(agents, "_pstart", return_value="1"), \
                mock.patch.object(agents, "_PROCS", []), \
                mock.patch.object(agents.subprocess, "Popen", fake_popen):
            out = agents.spawn("do it", {}, d / "t.jsonl", d / "logs")
        self.assertTrue(out.startswith("SPAWNED"), out)
        self.assertNotIn("OPENROUTER_API_KEY", seen)
        self.assertNotIn("GROQ_API_KEY", seen)
        self.assertEqual(seen["ANTHROPIC_API_KEY"], "runtime-own")
        self.assertIn("WISP_TASK_ID", seen)


if __name__ == "__main__":
    unittest.main()
