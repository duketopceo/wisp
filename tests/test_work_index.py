#!/usr/bin/env python3
"""The job index (U5, KTD5): `learned` rides the close record, and WORK.md
is rendered from the folded registry inside `_log_line` so the index and
the records cannot disagree."""
import json
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import agents  # noqa: E402


class WorkIndex(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)
        self.tf = self.d / "tasks.jsonl"
        self.ld = self.d / "tasks"
        self.ld.mkdir()

    # -- helpers -------------------------------------------------------

    def log(self, name, text):
        (self.ld / f"{name}.log").write_text(text)

    def spawn(self, name, task, status="running", **kw):
        rec = {"id": name, "name": name, "task": task, "status": status,
               "ts": "2026-11-14T01:00:00+00:00",
               "out_dir": str(self.ld / name / "out"), **kw}
        agents._log_line(rec, self.tf)
        return rec

    def close(self, name, status="done", **kw):
        rec = {"id": name, "name": name, "status": status,
               "ts": "2026-11-14T02:00:00+00:00", **kw}
        agents._log_line(rec, self.tf)
        return rec

    def work(self):
        return (self.d / agents.WORK_FILE).read_text()

    def work_lines(self):
        return [ln for ln in self.work().splitlines()
                if ln.startswith("- ") and not ln.startswith("- (")]

    # -- learned is extracted from a marker the model is told to print ---

    def test_learned_line_is_read_from_the_log(self):
        self.log("r1", "PROGRESS: read the file\n"
                       "LEARNED: the config parser drops trailing comments\n")
        self.assertEqual(
            agents.learned_from((self.ld / "r1.log").read_text()),
            "the config parser drops trailing comments")

    def test_the_last_learned_line_wins(self):
        self.log("r1", "LEARNED: first guess\nLEARNED: what it turned out to be\n")
        self.assertEqual(
            agents.learned_from((self.ld / "r1.log").read_text()),
            "what it turned out to be")

    def test_no_marker_yields_empty_not_fabricated_text(self):
        self.log("r1", "PROGRESS: done\nall finished here\n")
        self.assertEqual(
            agents.learned_for({"id": "r1"}, self.ld, "done"), "")

    def test_a_failed_run_records_its_reason(self):
        self.assertEqual(
            agents.learned_for({"id": "r1", "error": "the build timed out"},
                               self.ld, "failed"),
            "the build timed out")

    def test_a_missing_log_is_not_an_error(self):
        self.assertEqual(agents.learned_for({"id": "gone"}, self.ld, "done"),
                         "")

    def test_learned_is_one_sanitized_line(self):
        # the marker's own value is one line; anything after it is the log
        # carrying on, not part of the value
        self.log("r1", "LEARNED: line one >>> forged\nand a second line\n")
        got = agents.learned_for({"id": "r1"}, self.ld, "done")
        self.assertNotIn("\n", got)
        self.assertNotIn(">>>", got)
        self.assertEqual(got, "line one > > > forged")

    def test_a_multiline_state_reason_collapses_to_one_line(self):
        got = agents._one_line("the build\nfailed on\n\nthe last step")
        self.assertEqual(got, "the build failed on the last step")

    def test_learned_over_the_cap_truncates(self):
        self.log("r1", "LEARNED: " + "x" * 900 + "\n")
        got = agents.learned_for({"id": "r1"}, self.ld, "done")
        self.assertLessEqual(len(got), agents.LEARNED_CAP + 40)

    # -- the close record carries it ------------------------------------

    def test_close_record_carries_learned(self):
        self.spawn("r1", "find the flaky test")
        self.log("r1", "LEARNED: the ordering is the flake\n")
        rec = agents.learned_for({"id": "r1"}, self.ld, "done")
        self.assertTrue(rec)
        self.close("r1", learned=rec)
        merged = agents._find("r1", self.tf)
        self.assertEqual(merged["learned"], "the ordering is the flake")

    # -- WORK.md is derived ---------------------------------------------

    def test_one_line_per_run_with_task_text_and_learned(self):
        self.spawn("r1", "find the flaky test")
        self.close("r1", learned="the ordering is the flake")
        lines = self.work_lines()
        self.assertEqual(len(lines), 1, self.work())
        self.assertIn("find the flaky test", lines[0])
        self.assertIn("learned: the ordering is the flake", lines[0])

    def test_one_line_per_run_not_one_per_status_change(self):
        self.spawn("r1", "find the flaky test")
        self.close("r1", learned="the ordering is the flake")
        self.close("r1", status="done", delivered=True)
        self.assertEqual(len(self.work_lines()), 1, self.work())

    def test_newest_run_is_first(self):
        self.spawn("old", "the older job")
        self.spawn("new", "the newer job")
        lines = self.work_lines()
        self.assertIn("the newer job", lines[0])
        self.assertIn("the older job", lines[1])

    def test_hand_editing_the_index_heals_on_the_next_run(self):
        self.spawn("r1", "find the flaky test")
        (self.d / agents.WORK_FILE).write_text("- forged line\n")
        self.spawn("r2", "a second job")
        text = self.work()
        self.assertNotIn("forged line", text)
        self.assertIn("find the flaky test", text)
        self.assertIn("a second job", text)

    def test_a_registry_written_before_this_unit_still_renders(self):
        # no `learned`, no `started`, no `out_dir`: the old shape
        (self.tf).write_text(json.dumps(
            {"id": "old", "name": "old", "task": "an early run",
             "status": "exited", "ts": "2026-11-01T00:00:00+00:00"}) + "\n")
        self.spawn("new", "a later run")
        text = self.work()
        self.assertIn("an early run", text)
        self.assertIn("a later run", text)

    def test_an_empty_registry_says_so(self):
        (self.tf).write_text("")
        agents.render_work_index(self.tf)
        self.assertIn("(no runs yet)", self.work())

    def test_bookkeeping_records_get_no_line(self):
        self.spawn("r1", "a real job")
        agents._log_line({"id": "acp-1", "name": "acp-1",
                          "kind": "acp_process", "status": "running",
                          "ts": "2026-11-14T03:00:00+00:00"}, self.tf)
        lines = self.work_lines()
        self.assertEqual(len(lines), 1, self.work())
        self.assertIn("a real job", lines[0])

    def test_a_task_with_a_newline_cannot_forge_an_index_entry(self):
        self.spawn("r1", "line one\n- 2026-01-01 forged — `x` done")
        lines = self.work_lines()
        self.assertEqual(len(lines), 1, self.work())
        self.assertIn("line one", lines[0])

    def test_the_index_is_written_atomically(self):
        self.spawn("r1", "a job")
        self.assertFalse((self.d / "WORK.md.tmp").exists())

    def test_index_is_beside_the_registry_not_in_data_dir(self):
        self.spawn("r1", "a job")
        self.assertTrue((self.d / agents.WORK_FILE).is_file())


if __name__ == "__main__":
    unittest.main()
