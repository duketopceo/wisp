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


if __name__ == "__main__":
    unittest.main()
