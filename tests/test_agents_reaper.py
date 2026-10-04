"""Agent reaper (W3): closes dead tasks, enforces timeouts, never
signals a recycled pid, escalates a stuck SIGTERM."""
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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import agents  # noqa: E402


def iso(sec_ago=0):
    return (datetime.now(timezone.utc)
            - timedelta(seconds=sec_ago)).isoformat()


class ReaperCase(unittest.TestCase):
    def setUp(self):
        self.td = pathlib.Path(tempfile.mkdtemp())
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
            if p.stdout:
                p.stdout.close()

    def spawn_real(self, script="import time; time.sleep(60)"):
        p = subprocess.Popen([sys.executable, "-c", script],
                             start_new_session=True,
                             stdout=subprocess.DEVNULL)
        self.procs.append(p)
        return p

    def write(self, *recs):
        self.tf.write_text("".join(json.dumps(r) + "\n" for r in recs))

    def rec(self, name="t1", pid=1, pstart="", status="running", ts=None):
        return {"id": name, "name": name, "task": "do " + name, "pid": pid,
                "pstart": pstart, "status": status, "ts": ts or iso()}

    def tick(self, cfg=None, **kw):
        return agents.reap_tick(cfg or {"agent": {"task_timeout_s": "1800"}},
                                tasks_file=self.tf, log_dir=self.logs, **kw)

    def statuses(self):
        return {k: v["status"]
                for k, v in agents.tasks(self.tf, self.logs).items()}


class ReaperTest(ReaperCase):
    def test_dead_task_is_closed_and_reported_finished(self):
        p = self.spawn_real("pass")
        p.wait()
        self.write(self.rec(pid=p.pid, pstart="123"))
        ev = self.tick()
        self.assertEqual(self.statuses(), {"t1": "exited"})
        self.assertEqual([(e["name"], e["status"]) for e in ev],
                         [("t1", "exited")])
        # idempotent: a closed task is not reported again
        self.assertEqual(self.tick(), [])

    def test_live_task_untouched(self):
        p = self.spawn_real()
        self.write(self.rec(pid=p.pid, pstart=agents._pstart(p.pid)))
        self.assertEqual(self.tick(), [])
        self.assertEqual(self.statuses(), {"t1": "running"})
        self.assertIsNone(p.poll())

    def test_recycled_pid_never_signalled_and_task_closed(self):
        """Record says pid X with start-time S; X is alive but belongs to
        someone else (start-time differs). It must be closed as lost and
        the stranger left alone, even when the timeout has long passed."""
        stranger = self.spawn_real()
        self.write(self.rec(pid=stranger.pid, pstart="999999999",
                            ts=iso(99999)))
        with mock.patch.object(agents.os, "killpg") as kg, \
                mock.patch.object(agents.os, "kill") as k:
            ev = self.tick()
        kg.assert_not_called()
        for c in k.call_args_list:
            self.assertEqual(c.args[1], 0)  # liveness probes only
        self.assertIsNone(stranger.poll())
        self.assertEqual(self.statuses(), {"t1": "exited"})
        self.assertEqual(ev[0]["status"], "exited")

    def test_timeout_kills_matching_pid(self):
        p = self.spawn_real()
        self.write(self.rec(pid=p.pid, pstart=agents._pstart(p.pid),
                            ts=iso(500)))
        ev = self.tick({"agent": {"task_timeout_s": "60"}})
        self.assertEqual(ev[0]["status"], "timed_out")
        p.wait(timeout=5)
        self.assertEqual(self.statuses(), {"t1": "timed_out"})

    def test_sigterm_ignorer_escalates_to_sigkill_after_grace(self):
        script = ("import signal,time;"
                  "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
                  "print('r',flush=True);time.sleep(60)")
        p = subprocess.Popen([sys.executable, "-c", script],
                             start_new_session=True,
                             stdout=subprocess.PIPE)
        self.procs.append(p)
        p.stdout.readline()  # handler installed
        self.write(self.rec(pid=p.pid, pstart=agents._pstart(p.pid),
                            ts=iso(500)))
        cfg = {"agent": {"task_timeout_s": "60"}}
        self.tick(cfg, kill_grace_s=30)
        time.sleep(0.2)
        self.assertIsNone(p.poll())          # SIGTERM ignored
        self.tick(cfg, kill_grace_s=30)      # inside grace: still alive
        self.assertIsNone(p.poll())
        self.tick(cfg, kill_grace_s=0)       # grace over: SIGKILL
        p.wait(timeout=5)
        self.assertEqual(p.returncode, -signal.SIGKILL)

    def test_cancelled_then_dead_is_not_reported_twice(self):
        p = self.spawn_real("pass")
        p.wait()
        self.write(self.rec(pid=p.pid, pstart="1"),
                   {"id": "t1", "name": "t1", "status": "cancelled",
                    "ts": iso()})
        self.assertEqual(self.tick(), [])
        self.assertEqual(self.statuses(), {"t1": "cancelled"})

    def test_tasks_keep_task_text_after_terminal_record(self):
        self.write(self.rec(pid=0),
                   {"id": "t1", "name": "t1", "status": "cancelled",
                    "ts": iso()})
        self.assertEqual(agents.tasks(self.tf, self.logs)["t1"]["task"],
                         "do t1")


class ReaperThreadTest(ReaperCase):
    def test_thread_publishes_tasks_and_events_then_stops(self):
        p = self.spawn_real("pass")
        p.wait()
        self.write(self.rec(pid=p.pid, pstart="1"))
        bus = mock.Mock()
        seen = []
        stop = __import__("threading").Event()
        th = agents.start_reaper(
            {"agent": {"task_timeout_s": "1800"}}, bus, stop,
            interval_s=0.05, tasks_file=self.tf, log_dir=self.logs,
            on_finished=seen.append)
        end = time.monotonic() + 3
        while not seen and time.monotonic() < end:
            time.sleep(0.02)
        stop.set()
        th.join(2)
        self.assertFalse(th.is_alive())
        self.assertEqual(seen[0]["name"], "t1")
        names = [c.args[0] for c in bus.emit_event.call_args_list]
        self.assertIn("task_finished", names)
        self.assertTrue(any("tasks" in c.kwargs
                            for c in bus.publish.call_args_list))


if __name__ == "__main__":
    unittest.main()
