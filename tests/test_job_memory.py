"""Per-job memory (§2 of the Clicky transfer): one small file per run
that the model writes and re-reads every step — MEMORY.md stays global
(who the user is), this is what one piece of work must not forget."""

import pathlib
import tempfile
import unittest
from unittest import mock

from wisp import job_memory as jm, tools


class JobMemoryTest(unittest.TestCase):
    def setUp(self):
        self.out = pathlib.Path(tempfile.mkdtemp()) / "run-1" / "out"
        self.out.mkdir(parents=True)

    def test_write_then_read_round_trips(self):
        self.assertTrue(jm.write(self.out, "goal: the invoice fix"))
        self.assertEqual(jm.read(self.out), "goal: the invoice fix")

    def test_absent_file_reads_none(self):
        self.assertIsNone(jm.read(self.out))

    def test_empty_write_is_refused_and_keeps_the_old(self):
        jm.write(self.out, "goal: x")
        self.assertFalse(jm.write(self.out, "   "))
        self.assertEqual(jm.read(self.out), "goal: x")

    def test_overlong_text_is_capped(self):
        body = "r" * (jm.MEMORY_MAX_CHARS + 100)
        self.assertTrue(jm.write(self.out, body))
        self.assertEqual(len(jm.read(self.out)), jm.MEMORY_MAX_CHARS)

    def test_write_replaces_whole_no_merging(self):
        jm.write(self.out, "goal: a\nrule: b")
        jm.write(self.out, "goal: c")
        self.assertEqual(jm.read(self.out), "goal: c")

    def test_job_dir_is_the_task_dir_not_data_dir(self):
        self.assertEqual(jm.job_dir(self.out), self.out.parent)
        # a named agent's output/ behaves the same
        agent_out = self.out.parent.parent / "agents" / "scout" / "output"
        self.assertEqual(jm.job_dir(agent_out), agent_out.parent)

    def test_reminder_shapes_the_message(self):
        self.assertIsNone(jm.reminder(self.out))
        jm.write(self.out, "goal: a")
        rem = jm.reminder(self.out)
        self.assertIn("memory_save", rem)
        self.assertIn("goal: a", rem)

    def test_memory_save_tool_routes_through_wisp_out_dir(self):
        with mock.patch.dict("os.environ", {"WISP_OUT_DIR": str(self.out)}):
            out = tools.run("memory_save", "goal: the lidar fix", {})
            self.assertIn("OK", out)
            self.assertEqual(jm.read(self.out), "goal: the lidar fix")

    def test_memory_save_without_a_job_folder_fails(self):
        env = {k: v for k, v in __import__("os").environ.items()
               if k != "WISP_OUT_DIR"}
        with mock.patch.dict("os.environ", env, clear=True):
            self.assertIn("FAIL", tools.run("memory_save", "goal: x", {}))

    def test_memory_save_refuses_an_empty_file(self):
        with mock.patch.dict("os.environ", {"WISP_OUT_DIR": str(self.out)}):
            self.assertIn("FAIL", tools.run("memory_save", "  ", {}))


class ActLoopSpliceTest(unittest.TestCase):
    """The reminder rides immediately before every model call, read
    from disk at injection time — a save mid-run is visible on the very
    next step, and nothing in the stored history can summarise it."""

    def setUp(self):
        self.out = pathlib.Path(tempfile.mkdtemp()) / "run-1" / "out"
        self.out.mkdir(parents=True)

    def _run_loop(self, fake_post):
        from wisp import act
        from wisp import brain as brain_mod
        cfg = {"brain": {"provider": "fake", "name": "fake",
                         "tools": "true", "model": "m"}}
        with mock.patch.object(act, "_post", fake_post), \
             mock.patch.object(brain_mod, "provider",
                               return_value={"name": "fake", "model": "m",
                                             "vision": "false",
                                             "tools": "true"}), \
             mock.patch.dict("os.environ", {"WISP_OUT_DIR": str(self.out)}):
            return act.run_act_loop("do the thing", cfg, out_dir=str(self.out))

    def test_saved_memory_is_seen_on_the_next_step(self):
        import json
        from wisp import act
        save_call = {"id": "c1", "function": {
            "name": "memory_save",
            "arguments": json.dumps({"arg": "goal: the lidar fix"})}}
        seen: list = []

        def fake_post(messages, cfg):
            seen.append([m.get("content") for m in messages])
            if len(seen) == 1:
                # the loop itself dispatches this through the tool path
                # (env-patched WISP_OUT_DIR), so the file really writes
                return {"content": "", "tool_calls": [save_call]}
            # a plain text reply with no tool call ends the run
            return {"content": "done: the fix landed", "tool_calls": []}

        self._run_loop(fake_post)
        # step 2's injected messages carry the memory as a fresh user message
        second = seen[1]
        self.assertTrue(any("goal: the lidar fix" in (c or "")
                            for c in second))


if __name__ == "__main__":
    unittest.main()
