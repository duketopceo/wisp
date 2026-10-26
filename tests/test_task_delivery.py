"""U2: Task lifecycle truth — exit codes, deliverable verification, and
`task output` / `task artifacts` reads (R1, R13, KTD3)."""
import json
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import agents  # noqa: E402


def _iso(sec_offset: float = 0.0) -> str:
    return (datetime.now(timezone.utc)
            + timedelta(seconds=sec_offset)).isoformat()


class TaskDeliveryTest(unittest.TestCase):
    def setUp(self):
        self.td = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(
            self.td, ignore_errors=True))
        self.tf = self.td / "tasks.jsonl"
        self.logs = self.td / "tasks"
        self.logs.mkdir()
        self.cfg = {"agent": {"task_timeout_s": "1800", "max_concurrent": "5"}}

    def _write_rec(self, name: str, *, exit_code: int | None = 0,
                   delivers: list[str] | None = None,
                   started: str | None = None,
                   shimmed: bool = True,
                   refused_count: int = 0) -> pathlib.Path:
        out_dir = self.logs / name / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        if exit_code is not None:
            agents._exit_file(self.logs, name).write_text(f"{exit_code}\n")
        rec = {
            "id": name,
            "name": name,
            "task": f"run {name}",
            "pid": 999999,
            "pstart": "1",
            "status": "running",
            "exit_code": None,
            "delivers": list(delivers or []),
            "spawned_by": "user",
            "depth": 0,
            "out_dir": str(out_dir),
            "shimmed": shimmed,
            "refused_count": refused_count,
            "ts": started or _iso(-5.0),
        }
        agents._log_line(rec, self.tf)
        return out_dir

    def test_exit_zero_with_present_deliverable_marks_delivered_and_names_file(self):
        out_dir = self._write_rec("sum-ok", exit_code=0,
                                  delivers=["out/summary.md"])
        target = out_dir / "summary.md"
        target.write_text("# Summary\nAll good.\n")

        ev = agents.reap_tick(self.cfg, tasks_file=self.tf, log_dir=self.logs)
        self.assertEqual(len(ev), 1)
        t = ev[0]
        self.assertEqual(t["status"], "done")
        self.assertEqual(t["exit_code"], 0)
        self.assertTrue(t["delivered"])
        self.assertEqual(t["deliverables"][0]["status"], "delivered")
        self.assertTrue(t["deliverables"][0]["openable"])

        notif = agents.build_done_notification(t)
        self.assertIn("done", notif["message"])
        self.assertIn("summary.md", notif["message"])
        self.assertEqual(notif["open_actions"], [str(target.resolve())])

    def test_exit_zero_with_missing_deliverable_reports_not_on_disk(self):
        self._write_rec("sum-miss", exit_code=0,
                        delivers=["out/summary.md"])

        ev = agents.reap_tick(self.cfg, tasks_file=self.tf, log_dir=self.logs)
        self.assertEqual(len(ev), 1)
        t = ev[0]
        self.assertEqual(t["status"], "done")
        self.assertEqual(t["exit_code"], 0)
        self.assertFalse(t["delivered"])
        self.assertEqual(t["deliverables"][0]["status"], "missing")
        self.assertEqual(t["deliverables"][0]["reason"], "not_found")

        notif = agents.build_done_notification(t)
        self.assertIn("claims summary.md — not on disk", notif["message"])
        self.assertNotIn("done", notif["message"])
        self.assertEqual(notif["open_actions"], [])

    def test_sigkill_and_exit_one_report_failed(self):
        # Exit 1 via status shim
        self._write_rec("exit1", exit_code=1, delivers=[])
        # SIGKILL: shimmed process dies without writing .exit
        self._write_rec("sigkill", exit_code=None, delivers=[], shimmed=True)

        ev = {e["name"]: e for e in agents.reap_tick(
            self.cfg, tasks_file=self.tf, log_dir=self.logs)}
        self.assertEqual(ev["exit1"]["status"], "failed")
        self.assertEqual(ev["exit1"]["exit_code"], 1)
        self.assertFalse(ev["exit1"]["delivered"])

        self.assertEqual(ev["sigkill"]["status"], "failed")
        self.assertEqual(ev["sigkill"]["exit_code"], -int(signal.SIGKILL))
        self.assertFalse(ev["sigkill"]["delivered"])

    def test_outside_out_dir_symlink_and_executable_flagged_and_never_opened(self):
        outside = self.td / "outside.txt"
        outside.write_text("outside content\n")

        out_dir = self._write_rec(
            "escape-task", exit_code=0,
            delivers=[
                str(outside),
                "link.txt",
                "evil.desktop",
                "run.sh",
            ],
        )
        (out_dir / "link.txt").symlink_to(outside)
        (out_dir / "evil.desktop").write_text("[Desktop Entry]\nExec=evil\n")
        sh = out_dir / "run.sh"
        sh.write_text("#!/bin/sh\necho hi\n")
        sh.chmod(0o755)

        ev = agents.reap_tick(self.cfg, tasks_file=self.tf, log_dir=self.logs)
        t = ev[0]
        by_name = {d["name"]: d for d in t["deliverables"]}

        self.assertTrue(by_name["outside.txt"]["flagged"])
        self.assertEqual(by_name["outside.txt"]["flag_reason"], "outside_out_dir")
        self.assertFalse(by_name["outside.txt"]["openable"])

        self.assertTrue(by_name["link.txt"]["flagged"])
        self.assertEqual(by_name["link.txt"]["flag_reason"], "symlink_escape")
        self.assertFalse(by_name["link.txt"]["openable"])

        self.assertTrue(by_name["evil.desktop"]["flagged"])
        self.assertEqual(by_name["evil.desktop"]["flag_reason"], "executable")
        self.assertFalse(by_name["evil.desktop"]["openable"])

        self.assertTrue(by_name["run.sh"]["flagged"])
        self.assertEqual(by_name["run.sh"]["flag_reason"], "executable")
        self.assertFalse(by_name["run.sh"]["openable"])

        notif = agents.build_done_notification(t)
        self.assertEqual(notif["open_actions"], [])

    def test_pre_existing_file_with_older_mtime_is_rejected_as_missing(self):
        out_dir = self._write_rec("stale-file", exit_code=0,
                                  delivers=["report.md"],
                                  started=_iso(0.0))
        f = out_dir / "report.md"
        f.write_text("old report from before run\n")
        past = time.time() - 3600
        os.utime(f, (past, past))

        ev = agents.reap_tick(self.cfg, tasks_file=self.tf, log_dir=self.logs)
        t = ev[0]
        self.assertFalse(t["delivered"])
        self.assertEqual(t["deliverables"][0]["status"], "missing")
        self.assertEqual(t["deliverables"][0]["reason"], "stale_mtime")

    def test_refused_command_count_included_in_done_notification(self):
        out_dir = self._write_rec("noisy-agent", exit_code=0,
                                  delivers=["notes.txt"],
                                  refused_count=3)
        (out_dir / "notes.txt").write_text("notes\n")
        ev = agents.reap_tick(self.cfg, tasks_file=self.tf, log_dir=self.logs)
        notif = agents.build_done_notification(ev[0])
        self.assertIn("3 commands refused (mutation blocked)", notif["message"])

    def test_task_output_and_artifacts_reads(self):
        out_dir = self._write_rec("read-me", exit_code=0,
                                  delivers=["result.json"])
        (self.logs / "read-me.log").write_text("step 1\nall done\n")
        (out_dir / "result.json").write_text('{"ok": true}\n')
        agents.reap_tick(self.cfg, tasks_file=self.tf, log_dir=self.logs)

        out = agents.output("read-me", tasks_file=self.tf, log_dir=self.logs)
        self.assertTrue(out["ok"])
        self.assertEqual(out["status"], "done")
        self.assertEqual(out["exit_code"], 0)
        self.assertIn("all done", out["output"])

        art = agents.artifacts("read-me", tasks_file=self.tf, log_dir=self.logs)
        self.assertTrue(art["ok"])
        self.assertTrue(art["delivered"])
        self.assertEqual(len(art["artifacts"]), 1)
        self.assertEqual(art["artifacts"][0]["name"], "result.json")
        self.assertTrue(art["artifacts"][0]["openable"])

    def test_real_spawn_with_exit_shim_records_exit_code_and_workspace(self):
        # End-to-end spawn using a real python runtime replacement
        with mock.patch.object(
            agents, "_runtime_cmd",
            return_value=[
                sys.executable, "-c",
                "import os,pathlib;"
                "p=pathlib.Path(os.environ['WISP_OUT_DIR'])/'done.txt';"
                "p.write_text('hello\\n')",
            ],
        ):
            res = agents.spawn(
                "write done file", self.cfg,
                tasks_file=self.tf, log_dir=self.logs,
                delivers=["out/done.txt"])
        self.assertTrue(res.startswith("SPAWNED"), res)
        rec = agents._find("write-done-file", self.tf)
        self.assertIsNotNone(rec)
        # Wait for the shimmed subprocess to finish
        deadline = time.monotonic() + 5.0
        while agents._alive(rec["pid"], rec.get("pstart", "")) \
                and time.monotonic() < deadline:
            time.sleep(0.05)

        ev = agents.reap_tick(self.cfg, tasks_file=self.tf, log_dir=self.logs)
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["status"], "done")
        self.assertEqual(ev[0]["exit_code"], 0)
        self.assertTrue(ev[0]["delivered"])

    def test_symlinked_parent_dir_and_slow_pstart_preserve_delivery_truth(self):
        # Simulate macOS /var -> /private/var (symlinked parent root) and a
        # slow _pstart(pid) that finishes after the child writes its output.
        real_root = self.td / "private_var"
        real_root.mkdir()
        sym_root = self.td / "var"
        sym_root.symlink_to(real_root)
        sym_logs = sym_root / "tasks"
        sym_logs.mkdir()
        sym_tf = sym_root / "tasks.jsonl"

        orig_pstart = agents._pstart

        def slow_pstart(pid: int) -> str:
            time.sleep(0.15)
            return orig_pstart(pid)

        with mock.patch.object(agents, "_pstart", side_effect=slow_pstart), \
             mock.patch.object(
                 agents, "_runtime_cmd",
                 return_value=[
                     sys.executable, "-c",
                     "import os,pathlib;"
                     "p=pathlib.Path(os.environ['WISP_OUT_DIR'])/'fast.txt';"
                     "p.write_text('ok\\n')",
                 ]):
            res = agents.spawn(
                "fast macos child", self.cfg,
                tasks_file=sym_tf, log_dir=sym_logs,
                delivers=["out/fast.txt"])
        self.assertTrue(res.startswith("SPAWNED"), res)
        rec = agents._find("fast-macos-child", sym_tf)
        deadline = time.monotonic() + 5.0
        while agents._alive(rec["pid"], rec.get("pstart", "")) \
                and time.monotonic() < deadline:
            time.sleep(0.05)

        ev = agents.reap_tick(self.cfg, tasks_file=sym_tf, log_dir=sym_logs)
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["status"], "done")
        self.assertTrue(ev[0]["delivered"])
        self.assertTrue(ev[0]["deliverables"][0]["openable"])
        self.assertFalse(ev[0]["deliverables"][0]["flagged"])

    def test_exit_code_cache_is_consumed_on_every_reap_path(self):
        self._write_rec("shim-done", exit_code=0)
        agents._EXIT_CODES[999999] = 7
        self.addCleanup(agents._EXIT_CODES.pop, 999999, None)
        rec = agents._find("shim-done", self.tf)
        # .exit file wins, but the stale cache entry must not survive it
        self.assertEqual(agents._resolve_exit_code(rec, self.logs), 0)
        self.assertNotIn(999999, agents._EXIT_CODES)

    def test_exit_code_cache_not_consumed_when_pid_reused(self):
        self._write_rec("reused", exit_code=None, shimmed=False)
        agents._EXIT_CODES[999999] = 7
        self.addCleanup(agents._EXIT_CODES.pop, 999999, None)
        rec = agents._find("reused", self.tf)
        self.assertIsNone(
            agents._resolve_exit_code(rec, self.logs, pid_reused=True))
        self.assertEqual(agents._EXIT_CODES.get(999999), 7)

    def test_timed_out_routine_run_records_outcome_while_daemon_runs(self):
        from wisp import routines
        store = routines.RoutineStore(self.td / "routines.json")
        store.create(routines.Routine(
            id="hung", name="Hung", task="t", schedule="hourly"),
            opt_in=True)
        for run_no in (1, 2, 3):
            tname = f"hung-{run_no}"
            (self.logs / tname / "out").mkdir(parents=True, exist_ok=True)
            agents._log_line({
                "id": tname, "name": tname, "task": "t", "pid": 999999,
                "pstart": "1", "status": "running", "routine_id": "hung",
                "shimmed": True, "ts": _iso(-5.0),
                "out_dir": str(self.logs / tname / "out"),
            }, self.tf)
            # as _reap_expired / cancel leave it: closed, never recorded
            agents._log_line({"id": tname, "name": tname,
                              "status": "timed_out", "ts": _iso(-1.0)},
                             self.tf)
            agents.reap_tick(self.cfg, tasks_file=self.tf,
                             log_dir=self.logs, routines_store=store)
            # idempotent: a second pass must not double-count
            agents.reap_tick(self.cfg, tasks_file=self.tf,
                             log_dir=self.logs, routines_store=store)
        r = store.get("hung")
        self.assertTrue(r.paused)
        self.assertEqual(r.consecutive_failures, 3)


if __name__ == "__main__":
    unittest.main()
