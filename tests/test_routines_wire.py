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
from wisp import agents, route, routines, stage_execute  # noqa: E402


class RoutinesWireU3Test(unittest.TestCase):
    def setUp(self):
        self.td = pathlib.Path(tempfile.mkdtemp())
        self.store_path = self.td / "routines.json"
        self.store = routines.RoutineStore(self.store_path)
        self.tf = self.td / "tasks.jsonl"
        self.logs = self.td / "tasks"
        self.logs.mkdir()
        self.cfg = {"agent": {"task_timeout_s": "1800", "max_concurrent": "5"}}
        p = mock.patch.object(routines, "online", lambda cfg=None: True)
        p.start()
        self.addCleanup(p.stop)

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
            env.shim("codex", "exit 0")  # a one-shot runtime: opencode needs the daemon
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


class VoiceTaughtRoutinesU4Test(unittest.TestCase):
    def setUp(self):
        self.td = pathlib.Path(tempfile.mkdtemp())
        self.store_path = self.td / "routines.json"
        self.store = routines.RoutineStore(self.store_path)
        self.unit_dir = self.td / "systemd"
        self.cfg = {"agent": {"risk_threshold": "9"}}

    def test_teach_intent_with_explicit_schedule_confirms_and_creates_units(self):
        # Pre-grant opt-in so we isolate the T2 creation confirm card
        self.store.set_opted_in(True)
        cards = []

        def confirm(prompt, detail="", **kw):
            cards.append((prompt, detail, kw))
            return True

        confirm.rich = True
        out = routines.teach_routine(
            "Save this as my morning standup routine every day at 9am to summarize open PRs",
            self.cfg,
            store=self.store,
            confirm=confirm,
            unit_dir=self.unit_dir,
        )
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["status"], "created")
        self.assertEqual(len(cards), 1)
        prompt, detail, _ = cards[0]
        self.assertIn("morning standup", prompt)
        self.assertIn("*-*-* 09:00:00", prompt)
        self.assertIn("summarize open PRs", prompt)
        self.assertIn("Routine: morning standup", detail)
        self.assertIn("Schedule: *-*-* 09:00:00", detail)
        self.assertIn("Task: summarize open PRs", detail)

        saved = self.store.get("morning-standup")
        self.assertIsNotNone(saved)
        self.assertEqual(saved.schedule, "*-*-* 09:00:00")
        self.assertEqual(saved.task, "summarize open PRs")
        self.assertTrue((self.unit_dir / "wisp-routine-morning-standup.service").is_file())
        self.assertTrue((self.unit_dir / "wisp-routine-morning-standup.timer").is_file())

        # Colon time ('9:30am') must not split the task on ':30am'
        parsed_colon = routines.parse_teach_intent(
            "Save this as my triage routine every day at 9:30am to triage issues")
        self.assertEqual(parsed_colon["schedule"], "*-*-* 09:30:00")
        self.assertEqual(parsed_colon["task"], "triage issues")

    def test_first_ever_routine_fires_opt_in_gate_before_create(self):
        self.assertFalse(self.store.has_opted_in())
        prompts = []

        # 1) Decline at the first-run opt-in gate -> nothing persisted
        res_declined = routines.teach_routine(
            "Save this as my inbox check routine every hour to check unread mail",
            self.cfg,
            store=self.store,
            confirm=lambda p, **kw: (prompts.append(p), False)[1],
            unit_dir=self.unit_dir,
        )
        self.assertFalse(res_declined["ok"])
        self.assertEqual(res_declined["status"], "opt_in_declined")
        self.assertEqual(len(prompts), 1)
        self.assertIn("Allow scheduled routine", prompts[0])
        self.assertEqual(self.store.list(), [])
        self.assertFalse(self.store.has_opted_in())

        # 2) Approve opt-in gate + approve T2 creation card -> routine created
        prompts.clear()
        res_ok = routines.teach_routine(
            "Save this as my inbox check routine every hour to check unread mail",
            self.cfg,
            store=self.store,
            confirm=lambda p, **kw: (prompts.append(p), True)[1],
            unit_dir=self.unit_dir,
        )
        self.assertTrue(res_ok["ok"])
        self.assertEqual(len(prompts), 2)
        self.assertIn("Allow scheduled routine", prompts[0])
        self.assertIn("Create routine 'inbox check' (hourly): check unread mail?", prompts[1])
        self.assertTrue(self.store.has_opted_in())
        self.assertIsNotNone(self.store.get("inbox-check"))

    def test_ambiguous_schedule_triggers_clarification_and_persists_nothing(self):
        self.store.set_opted_in(True)
        asked = []

        out = routines.teach_routine(
            "Save this as my cleanup routine sometime around afternoon to archive logs",
            self.cfg,
            store=self.store,
            confirm=lambda p, **kw: True,
            ask=lambda q: (asked.append(q), None)[1],
            unit_dir=self.unit_dir,
        )
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], "clarification_needed")
        self.assertEqual(len(asked), 1)
        self.assertIn("cleanup", asked[0])
        self.assertEqual(self.store.list(), [])
        self.assertFalse(self.unit_dir.exists())

    def test_route_and_stage_execute_wire_teach_intent_to_routine_store(self):
        h = route.heuristic("Save this as my pr digest routine every hour to check PRs")
        self.assertEqual(h["route"], "learn")

        self.store.set_opted_in(True)
        with mock.patch.object(routines, "DEFAULT_ROUTINES_FILE", self.store_path), \
             mock.patch.object(routines.config, "HOME", self.td):
            res = stage_execute.execute(
                {"route": {"choice": "learn"}, "risk": {"score": 1}},
                self.cfg,
                detail="Save this as my pr digest routine every hour to check PRs",
                confirm=lambda p, **kw: True,
            )
        self.assertIn("CREATED routine pr-digest", res)
        self.assertIsNotNone(self.store.get("pr-digest"))

    def test_teach_intent_routes_to_learn_without_jev_under_every_router(self):
        from wisp import stage_route
        teach = "Save this as my pr digest routine every hour to check PRs"
        for router in ("act", "jev", "chat"):
            self.assertEqual(stage_route.fixed_route(teach, router),
                             ("learn", teach), router)
        self.assertEqual(stage_route.fixed_route(teach, "off"),
                         ("clarify", None))

    def test_fixed_route_keeps_explicit_routes_and_retires_jev(self):
        from wisp import stage_route
        self.assertEqual(stage_route.fixed_route("open firefox", "act"),
                         ("act", None))
        self.assertEqual(stage_route.fixed_route("what is this", "chat"),
                         ("answer", None))
        self.assertEqual(stage_route.fixed_route("open firefox", "jev"),
                         ("act", None))
        self.assertEqual(
            stage_route.fixed_route("wisp agent: tidy downloads", "jev"),
            ("act", "tidy downloads"))


class RoutineUnitActivationTest(unittest.TestCase):
    def setUp(self):
        self.td = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(
            self.td, ignore_errors=True))
        self.units = self.td / "units"
        self.bindir = self.td / "bin"
        self.bindir.mkdir()
        self.calls = self.td / "calls.txt"
        self.routine = routines.Routine(
            id="nightly", name="Nightly", task="t", schedule="daily")

    def _stub_systemctl(self, rc: int = 0):
        sc = self.bindir / "systemctl"
        sc.write_text(f'#!/bin/sh\necho "$@" >> {self.calls}\nexit {rc}\n')
        sc.chmod(0o755)

    def test_install_reloads_and_enables_timer(self):
        self._stub_systemctl()
        with mock.patch.dict("os.environ", {"PATH": str(self.bindir)}):
            units = routines.install_systemd_units(
                self.routine, unit_dir=self.units, activate=True)
        self.assertTrue(units["scheduled"], units)
        calls = self.calls.read_text().splitlines()
        self.assertEqual(calls[0], "--user daemon-reload")
        self.assertEqual(
            calls[1], "--user enable --now wisp-routine-nightly.timer")

    def test_install_reports_unscheduled_without_systemctl(self):
        with mock.patch.dict("os.environ", {"PATH": str(self.bindir)}):
            units = routines.install_systemd_units(
                self.routine, unit_dir=self.units, activate=True)
        self.assertFalse(units["scheduled"])
        self.assertIn("systemctl", units["schedule_error"])

    def test_teach_routine_reports_created_but_unscheduled(self):
        store = routines.RoutineStore(self.td / "routines.json")
        store.set_opted_in(True)
        with mock.patch.dict("os.environ", {"PATH": str(self.bindir)}):
            out = routines.teach_routine(
                "Save this as my nightly routine every day at 9am to sync",
                {}, store=store, confirm=lambda *a, **k: True,
                unit_dir=self.units, activate_units=True)
        self.assertEqual(out["status"], "created_unscheduled", out)
        self.assertIn("NOT SCHEDULED", out["result"])
        self.assertIsNotNone(store.get("nightly"))


if __name__ == "__main__":
    unittest.main()
