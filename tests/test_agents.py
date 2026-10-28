"""Agent registry — tasks() progress tails + finished() transitions."""
import pathlib
import tempfile
import unittest
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
                mock.patch.object(agents, "_systemd_scope_enabled",
                                  return_value=False), \
                mock.patch.object(agents, "_pstart", return_value="1"), \
                mock.patch.object(agents.subprocess, "Popen", fake_popen):
            out = agents.spawn("do it", {}, d / "t.jsonl", d / "logs")
        self.assertTrue(out.startswith("SPAWNED"), out)
        self.assertNotIn("OPENROUTER_API_KEY", seen)
        self.assertNotIn("GROQ_API_KEY", seen)
        self.assertEqual(seen["ANTHROPIC_API_KEY"], "runtime-own")
        self.assertIn("WISP_TASK_ID", seen)


if __name__ == "__main__":
    unittest.main()
