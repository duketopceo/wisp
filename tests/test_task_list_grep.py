#!/usr/bin/env python3
"""U5 from the outside: `wispd task list --grep` finds a past run by its
subject or by what it learned, which is R6's actual claim."""
import functools
import io
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from wisp import agents  # noqa: E402
from wisp.cli import agents as cli_agents  # noqa: E402


class _Ctx:
    def __init__(self):
        self.out = io.StringIO()

    def emit(self, payload, text):
        self.out.write(text + "\n")
        return payload, text


class TaskListGrep(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)
        self.tf = self.d / "tasks.jsonl"
        self.ld = self.d / "tasks"
        self.ld.mkdir()
        # tasks() binds its paths as defaults at definition time, so the
        # CLI's `agents.tasks()` call is pointed at this registry instead
        mock.patch.object(
            agents, "tasks",
            functools.partial(agents.tasks, self.tf, self.ld)).start()
        self.addCleanup(mock.patch.stopall)

    def rec(self, name, task, learned="", status="done"):
        (self.ld / f"{name}.log").write_text(
            f"LEARNED: {learned}\n" if learned else "")
        agents._log_line({"id": name, "name": name, "task": task,
                          "status": status, "kind": "session",
                          "ts": "2026-11-14T01:00:00+00:00",
                          "out_dir": str(self.ld / name / "out")}, self.tf)
        if learned:
            agents._log_line({"id": name, "name": name, "status": status,
                              "learned": learned,
                              "ts": "2026-11-14T02:00:00+00:00"}, self.tf)

    def run_list(self, grep=""):
        a = type("A", (), {"grep": grep, "json": False})()
        ctx = _Ctx()
        return cli_agents.task_list(ctx, a)

    def test_finds_a_run_by_its_subject(self):
        self.rec("kickoff", "find the flaky test")
        self.rec("other", "write the release notes")
        payload, text = self.run_list("flaky")
        self.assertEqual([r["name"] for r in payload["tasks"]], ["kickoff"])
        self.assertIn("find the flaky test", text)

    def test_finds_a_run_by_what_it_learned(self):
        self.rec("kickoff", "find the flaky test", "the ordering is the flake")
        self.rec("other", "write the release notes", "nothing new")
        payload, _ = self.run_list("ordering")
        self.assertEqual([r["name"] for r in payload["tasks"]], ["kickoff"])

    def test_the_learned_line_is_shown_under_the_run(self):
        self.rec("kickoff", "find the flaky test", "the ordering is the flake")
        _, text = self.run_list()
        self.assertIn("the ordering is the flake", text)

    def test_no_match_says_nothing_matched(self):
        self.rec("kickoff", "find the flaky test")
        payload, text = self.run_list("pancakes")
        self.assertEqual(payload["tasks"], [])
        self.assertIn("nothing matched", text)

    def test_no_grep_lists_every_run(self):
        self.rec("a", "first job")
        self.rec("b", "second job")
        payload, _ = self.run_list()
        self.assertEqual(len(payload["tasks"]), 2)


if __name__ == "__main__":
    unittest.main()
