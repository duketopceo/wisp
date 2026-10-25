"""U3 + U4: Routines end-to-end wiring (CLI target, daemon-down fallback,
reap outcome recording, unread state, and voice-taught routines)."""
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from cli_env import CliEnv  # noqa: E402
from wisp import agents, routines  # noqa: E402


class RoutinesWireU3Test(unittest.TestCase):
    def setUp(self):
        self.td = pathlib.Path(tempfile.mkdtemp())
        self.store_path = self.td / "routines.json"
        self.store = routines.RoutineStore(self.store_path)
        self.tf = self.td / "tasks.jsonl"
        self.logs = self.td / "tasks"
        self.logs.mkdir()
        self.cfg = {"agent": {"task_timeout_s": "1800", "max_concurrent": "5"}}

    def test_cli_agents_run_with_daemon_up_sends_routine_id(self):
        with CliEnv(daemon=True) as env:
            code, out, err = env.run(["agents", "run", "inbox-digest"])
            self.assertEqual(code, 0, err)
            self.assertIn("SPAWNED", out)
            self.assertEqual(
                env.ipc,
                [{"cmd": "agent", "routine_id": "inbox-digest"}])

    def test_cli_agents_run_daemon_down_fallback_spawns_and_reconciles(self):
        with CliEnv(daemon=False) as env:
            env.shim("ori", "exit 0")
            r_store = routines.RoutineStore(env.data / "routines.json")
            r_store.create(
                routines.Routine(
                    id="inbox-digest",
                    name="Inbox Digest",
                    task="summarize unread messages",
                    schedule="daily",
                ),
                opt_in=True,
            )
            code, out, err = env.run(["agents", "run", "inbox-digest"])
            self.assertEqual(code, 0, (out, err))
            self.assertIn("SPAWNED inbox-digest", out)

            tf = env.data / "tasks.jsonl"
            rec = agents._find("inbox-digest", tf)
            self.assertIsNotNone(rec)
            self.assertEqual(rec["routine_id"], "inbox-digest")
            self.assertEqual(rec["spawned_by"], "routine:inbox-digest")

            # Wait for shim to write .exit, then reconcile as on daemon start
            import time
            deadline = time.monotonic() + 5.0
            while agents._alive(rec["pid"], rec.get("pstart", "")) \
                    and time.monotonic() < deadline:
                time.sleep(0.05)

            notified = []
            done = agents.reconcile_routines(
                self.cfg,
                tasks_file=tf,
                log_dir=env.data / "tasks",
                routines_store=r_store,
                on_finished=lambda t: agents.notify_done(
                    t, notify_fn=notified.append),
            )
            self.assertEqual(len(done), 1)
            self.assertEqual(done[0]["status"], "done")
            self.assertTrue(done[0]["unread"])
            self.assertEqual(notified, [])  # quiet completion -> no toast
            updated = r_store.get("inbox-digest")
            self.assertTrue(updated.unread)
            self.assertEqual(updated.last_status, "ok")

    def test_three_consecutive_failures_auto_pauses_and_notifies_once(self):
        self.store.create(
            routines.Routine(
                id="flaky-sync",
                name="Flaky Sync",
                task="sync notes",
                schedule="hourly",
            ),
            opt_in=True,
        )
        notifications = []

        for run_no in (1, 2, 3, 4):
            # Force run even after pause on run 4 to verify no 2nd notification
            if run_no == 4:
                r = self.store.get("flaky-sync")
                r.enabled = True
                r.paused = False
                self.store.save(r)
            out_dir = self.logs / f"flaky-sync-{run_no}" / "out"
            out_dir.mkdir(parents=True, exist_ok=True)
            tname = f"flaky-sync-{run_no}"
            agents._exit_file(self.logs, tname).write_text("1\n")
            agents._log_line({
                "id": tname,
                "name": tname,
                "task": "sync notes",
                "pid": 999999,
                "pstart": "1",
                "status": "running",
                "routine_id": "flaky-sync",
                "spawned_by": "routine:flaky-sync",
                "out_dir": str(out_dir),
                "shimmed": True,
                "ts": "2026-10-25T10:00:00+00:00",
            }, self.tf)

            done = agents.reap_tick(
                self.cfg, tasks_file=self.tf, log_dir=self.logs,
                routines_store=self.store)
            self.assertEqual(len(done), 1)
            agents.notify_done(done[0], notify_fn=notifications.append)

        r_final = self.store.get("flaky-sync")
        self.assertTrue(r_final.paused)
        self.assertFalse(r_final.enabled)
        self.assertEqual(len(notifications), 1)
        self.assertIn("flaky-sync", notifications[0])
        self.assertIn("paused", notifications[0])

    def test_routine_success_sets_unread_in_tasks_and_never_speaks(self):
        self.store.create(
            routines.Routine(
                id="daily-brief",
                name="Daily Brief",
                task="prepare daily brief",
                schedule="daily",
            ),
            opt_in=True,
        )
        out_dir = self.logs / "daily-brief" / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        agents._exit_file(self.logs, "daily-brief").write_text("0\n")
        agents._log_line({
            "id": "daily-brief",
            "name": "daily-brief",
            "task": "prepare daily brief",
            "pid": 999999,
            "pstart": "1",
            "status": "running",
            "routine_id": "daily-brief",
            "spawned_by": "routine:daily-brief",
            "out_dir": str(out_dir),
            "shimmed": True,
            "ts": "2026-10-25T10:00:00+00:00",
        }, self.tf)

        notifications = []
        done = agents.reap_tick(
            self.cfg, tasks_file=self.tf, log_dir=self.logs,
            routines_store=self.store)
        self.assertEqual(len(done), 1)
        info = agents.notify_done(done[0], notify_fn=notifications.append)
        self.assertFalse(info["notified"])
        self.assertEqual(notifications, [])
        self.assertFalse(done[0]["routine_outcome"]["speak"])

        snap = agents.tasks(self.tf, self.logs)
        self.assertTrue(snap["daily-brief"]["unread"])
        self.assertEqual(snap["daily-brief"]["routine_id"], "daily-brief")


if __name__ == "__main__":
    unittest.main()
