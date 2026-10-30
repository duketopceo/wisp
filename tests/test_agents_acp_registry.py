"""U5: ACP process + session records in the task registry (R10, R12, R13, KTD3)."""
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import shorttmp  # noqa: E402
from wisp import agents  # noqa: E402


class AcpRegistryCase(unittest.TestCase):
    def setUp(self):
        if agents._SCOPE_RE.search(agents._proc_cgroup(os.getpid())):
            self.skipTest("test process runs inside a wisp-task scope")
        self.td = pathlib.Path(shorttmp.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.td, ignore_errors=True))
        self.tf = self.td / "tasks.jsonl"
        self.logs = self.td / "tasks"
        self.logs.mkdir()
        self.procs = []
        self.addCleanup(self._kill)

    def _kill(self):
        for p in self.procs:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
            p.wait()

    def sleeper(self):
        env = {k: v for k, v in os.environ.items() if k != "WISP_TASK_ID"}
        p = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, env=env)
        self.procs.append(p)
        return p

    def proc_rec(self, helper="scout", pid=None):
        p = pid if pid is not None else self.sleeper().pid
        return agents.record_process(f"acp-{helper}", p, tasks_file=self.tf)

    def session(self, name, proc_id, **kw):
        return agents.record_session(name, f"do {name}", proc_id,
                                     session_id=f"ses_{name}",
                                     tasks_file=self.tf, **kw)

    def status_of(self, name):
        return agents._find(name, self.tf)["status"]

    def tick(self):
        return agents.reap_tick({"agent": {"task_timeout_s": "1800"}},
                                tasks_file=self.tf, log_dir=self.logs)


class ClassifyTest(AcpRegistryCase):
    def test_pid_and_scope_inside_process_classify_as_that_process(self):
        proc = self.proc_rec()
        self.session("s1", proc["id"])
        info = agents.classify_peer({"pid": proc["pid"]}, self.tf)
        self.assertTrue(info["marked"])
        self.assertEqual(info["task_id"], "acp-scout")
        other = self.sleeper()
        info = agents.classify_peer({
            "pid": other.pid, "ppid": 1, "env": {},
            "cgroup": "0::/app.slice/wisp-task-acp-scout.scope\n"}, self.tf)
        self.assertTrue(info["marked"] and info["verified"])
        self.assertEqual(info["task_id"], "acp-scout")

    def test_session_id_env_accepted_while_process_runs_then_spoofed(self):
        proc = self.proc_rec()
        self.session("s1", proc["id"])
        other = self.sleeper()
        peer = {"pid": other.pid, "ppid": 1, "cgroup": "0::/x\n",
                "env": {"WISP_TASK_ID": "s1"}}
        info = agents.classify_peer(peer, self.tf)
        self.assertTrue(info["marked"] and info["verified"])
        self.assertFalse(info["spoofed"])
        self.assertEqual(info["task_id"], "s1")
        agents._log_line({"id": proc["id"], "name": proc["id"],
                          "status": "exited"}, self.tf)
        info = agents.classify_peer(peer, self.tf)
        self.assertTrue(info["spoofed"])
        self.assertFalse(info["verified"])

    def test_refusal_from_process_scope_counts_on_running_sessions(self):
        proc = self.proc_rec()
        self.session("s1", proc["id"])
        self.session("s2", proc["id"])
        agents._log_line({"id": "s2", "name": "s2", "status": "done"},
                         self.tf)
        agents.record_refusal(proc["id"], "task_cancel", self.tf)
        self.assertEqual(agents._find("s1", self.tf)["refused_count"], 1)
        self.assertEqual(agents._find("s1", self.tf)["refused_cmds"],
                         ["task_cancel"])
        self.assertEqual(agents._find("s2", self.tf)["refused_count"], 0)


class SessionLifecycleTest(AcpRegistryCase):
    def test_max_concurrent_counts_running_sessions(self):
        proc = self.proc_rec()
        self.session("s1", proc["id"])
        self.session("s2", proc["id"])
        out = agents.spawn("third thing", {"agent": {"max_concurrent": "2"}},
                           tasks_file=self.tf, log_dir=self.logs)
        self.assertTrue(out.startswith("SKIP (agent limit"), out)

    def test_tasks_lists_sessions_and_hides_process_records(self):
        proc = self.proc_rec()
        self.session("s1", proc["id"])
        out = agents.tasks(self.tf, self.logs)
        self.assertEqual(list(out), ["s1"])
        self.assertEqual(out["s1"]["status"], "running")
        self.assertEqual(out["s1"]["task"], "do s1")
        self.assertNotIn("acp_process", out["s1"])

    def test_dead_process_record_fails_its_running_session(self):
        proc = self.proc_rec()
        self.session("s1", proc["id"])
        self.session("s2", proc["id"])
        agents._log_line({"id": "s2", "name": "s2", "status": "done"},
                         self.tf)
        agents._log_line({"id": proc["id"], "name": proc["id"],
                          "status": "exited"}, self.tf)
        ev = self.tick()
        self.assertEqual(self.status_of("s1"), "failed")
        self.assertEqual(agents._find("s1", self.tf)["error"],
                         "process exited")
        self.assertEqual(self.status_of("s2"), "done")
        self.assertEqual([(e["name"], e["status"]) for e in ev],
                         [("s1", "failed")])

    def test_live_process_keeps_running_session(self):
        proc = self.proc_rec()
        self.session("s1", proc["id"])
        self.tick()
        self.assertEqual(self.status_of("s1"), "running")
        self.assertEqual(self.status_of(proc["id"]), "running")


class SweepTest(AcpRegistryCase):
    def test_orphan_process_killed_and_sessions_interrupted(self):
        p = self.sleeper()
        proc = self.proc_rec(pid=p.pid)
        self.session("s1", proc["id"])
        self.session("s2", proc["id"])
        with mock.patch.object(agents, "_kill_scope") as ks:
            agents.sweep_orphans(self.tf, kill_grace_s=2)
        ks.assert_called()
        p.wait(timeout=5)
        self.assertFalse(agents._alive(p.pid, proc["pstart"]))
        self.assertEqual(self.status_of("s1"), "interrupted")
        self.assertEqual(self.status_of("s2"), "interrupted")
        self.assertEqual(self.status_of(proc["id"]), "exited")

    def test_pstart_mismatch_is_not_signalled(self):
        p = self.sleeper()
        proc = self.proc_rec(pid=p.pid)
        agents._log_line({"id": proc["id"], "name": proc["id"],
                          "pstart": "999999999"}, self.tf)
        self.session("s1", proc["id"])
        with mock.patch.object(agents, "_kill_scope") as ks:
            agents.sweep_orphans(self.tf, kill_grace_s=0.2)
        ks.assert_not_called()
        self.assertIsNone(p.poll())
        self.assertEqual(self.status_of("s1"), "interrupted")


if __name__ == "__main__":
    unittest.main()
