"""Private text never rides on a child's command line.

Other local accounts can read /proc/<pid>/cmdline while a process runs, so
an agent task and dictated text go to the child's stdin instead.
"""
import os
import pathlib
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import agents, platform  # noqa: E402
from wisp.tools import system  # noqa: E402

SECRET = "zebra-quartz-7731 private sentence"
RECORDER = (
    "import os,pathlib,sys;"
    "out=pathlib.Path(os.environ['WISP_OUT_DIR'])/'got.txt';"
    "cl=pathlib.Path('/proc/self/cmdline').read_bytes().replace(b'\\0',b' ');"
    "out.write_text(sys.stdin.read()+'\\n--\\n'+cl.decode())")


class AgentTask(unittest.TestCase):
    def setUp(self):
        self.td = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)
        self.tf = self.td / "tasks.jsonl"
        self.logs = self.td / "tasks"
        self.logs.mkdir()
        p = mock.patch.object(agents, "_pinned_state",
                              lambda: {"state": "absent"})
        p.start()
        self.addCleanup(p.stop)

    def test_the_task_reaches_the_agent_on_stdin_not_argv(self):
        with mock.patch.object(agents, "_runtime_cmd",
                               return_value=[sys.executable, "-c",
                                             RECORDER]), \
                mock.patch.object(agents, "_systemd_scope_enabled",
                                  return_value=False):
            res = agents.spawn(SECRET, {"agent": {"max_concurrent": "5"}},
                               tasks_file=self.tf, log_dir=self.logs)
        self.assertTrue(res.startswith("SPAWNED"), res)
        got = next(self.logs.rglob("got.txt"), None)
        for _ in range(100):
            got = next(self.logs.rglob("got.txt"), None)
            if got and "--" in got.read_text():
                break
            time.sleep(0.05)
        self.assertIsNotNone(got)
        stdin, _, cmdline = got.read_text().partition("\n--\n")
        self.assertEqual(stdin, SECRET)
        self.assertNotIn("zebra-quartz", cmdline)
        # the recorded command line is no different
        rec = next(iter(agents._latest(self.tf)))
        self.assertNotIn("zebra-quartz", rec["cmd"])

    def test_no_runtime_template_carries_a_prompt_placeholder(self):
        for rt, argv in agents._RUNTIMES.items():
            self.assertFalse([a for a in argv if "{" in a], rt)

    def test_each_runtime_is_told_to_read_stdin(self):
        want = {"codex": ["codex", "exec", "-"],
                "claude": ["claude", "-p"],
                "opencode": ["ori", "opencode", "run"]}
        for rt, argv in want.items():
            with mock.patch.object(agents.shutil, "which",
                                   return_value="/bin/x"):
                got = agents._runtime_cmd({"brain": {"agent_runtime": rt}},
                                          "")
            self.assertEqual(got, argv, rt)

    def test_a_model_flag_goes_before_the_stdin_marker(self):
        with mock.patch.object(agents.shutil, "which",
                               return_value="/bin/x"):
            got = agents._runtime_cmd({"brain": {"agent_runtime": "codex"}},
                                      "m/x")
        self.assertEqual(got, ["codex", "exec", "-m", "m/x", "-"])


class Dictation(unittest.TestCase):
    def test_the_typer_argv_never_holds_text(self):
        for desk in ("hyprland", "x11", "gnome"):
            with mock.patch.dict(os.environ, {"WISP_DESKTOP": desk}), \
                    mock.patch.object(platform, "_which",
                                      return_value=True):
                cmd = platform.type_text_cmd()
            self.assertEqual(cmd[-1], "-", desk)

    def test_typed_text_goes_to_the_typer_on_stdin(self):
        out = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)
        rec = out / "got.txt"
        code = (
            "import pathlib,sys;"
            "cl=pathlib.Path('/proc/self/cmdline').read_bytes()"
            ".replace(b'\\0',b' ');"
            f"pathlib.Path({str(rec)!r}).write_text("
            "sys.stdin.read()+'\\n--\\n'+cl.decode())")
        with mock.patch.object(platform, "type_text_cmd",
                               return_value=[sys.executable, "-c", code]):
            self.assertEqual(system.type_text(SECRET, {}), "TYPED")
        stdin, _, cmdline = rec.read_text().partition("\n--\n")
        self.assertEqual(stdin, SECRET)
        self.assertNotIn("zebra-quartz", cmdline)


if __name__ == "__main__":
    unittest.main()
