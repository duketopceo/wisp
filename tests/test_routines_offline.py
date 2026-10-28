"""B10: routines wait for the network, and a run missed offline does not
count toward the three-failure pause."""
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import agents, routines  # noqa: E402

ROUTE = ("Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\n"
         "{iface}\t00000000\t0100A8C0\t{flags}\t0\t0\t0\t00000000\n"
         "lo\t0000007F\t00000000\t0001\t0\t0\t0\t000000FF\n")


class Online(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = pathlib.Path(td.name)
        self.route = self.tmp / "route"
        self.net = self.tmp / "net"
        for p in (mock.patch.object(routines, "_PROC_ROUTE", self.route),
                  mock.patch.object(routines, "_SYS_NET", self.net)):
            p.start()
            self.addCleanup(p.stop)

    def nic(self, name, state):
        d = self.net / name
        d.mkdir(parents=True)
        (d / "operstate").write_text(state + "\n")

    def test_default_route_on_an_up_interface_is_online(self):
        self.route.write_text(ROUTE.format(iface="wlan0", flags="0003"))
        self.nic("wlan0", "up")
        self.assertTrue(routines.online({}))

    def test_no_default_route_is_offline(self):
        self.route.write_text("Iface\tDestination\tGateway\tFlags\n"
                              "lo\t0000007F\t00000000\t0001\n")
        self.assertFalse(routines.online({}))

    def test_a_down_interface_is_offline(self):
        self.route.write_text(ROUTE.format(iface="wlan0", flags="0003"))
        self.nic("wlan0", "down")
        self.assertFalse(routines.online({}))

    def test_a_route_that_is_not_up_is_offline(self):
        self.route.write_text(ROUTE.format(iface="wlan0", flags="0002"))
        self.nic("wlan0", "up")
        self.assertFalse(routines.online({}))

    def test_local_models_count_as_online(self):
        self.route.write_text("Iface\tDestination\n")
        self.assertTrue(routines.online({"local": {"enabled": "true"}}))

    def test_unreadable_state_does_not_block_a_routine(self):
        self.assertTrue(routines.online({}))      # no route file at all


class Waiting(unittest.TestCase):
    def test_waits_for_the_network_then_goes(self):
        seq = iter([False, False, True])
        slept = []
        ok = routines.wait_until_online(
            {}, wait_s=60, poll_s=2, sleep=slept.append,
            online_fn=lambda c: next(seq))
        self.assertTrue(ok)
        self.assertEqual(slept, [2, 2])

    def test_gives_up_after_the_bound(self):
        slept = []
        ok = routines.wait_until_online(
            {}, wait_s=6, poll_s=2, sleep=slept.append,
            online_fn=lambda c: False)
        self.assertFalse(ok)
        self.assertEqual(sum(slept), 6)

    def test_zero_wait_checks_once(self):
        slept = []
        self.assertFalse(routines.wait_until_online(
            {}, wait_s=0, sleep=slept.append, online_fn=lambda c: False))
        self.assertEqual(slept, [])

    def test_bound_comes_from_config(self):
        slept = []
        routines.wait_until_online(
            {"agents": {"routine_wait_s": "4"}}, poll_s=2,
            sleep=slept.append, online_fn=lambda c: False)
        self.assertEqual(sum(slept), 4)


class Outcomes(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = pathlib.Path(td.name)
        self.store = routines.RoutineStore(self.tmp / "r.json")
        self.store.set_opted_in(True)
        self.store.save(routines.Routine(id="digest", task="digest mail"))

    def test_offline_misses_never_pause_a_routine(self):
        for _ in range(10):
            out = routines.record_routine_outcome(
                "digest", False, store=self.store, offline=True)
        r = self.store.get("digest")
        self.assertEqual(r.consecutive_failures, 0)
        self.assertFalse(r.paused)
        self.assertEqual(r.last_status, "missed_offline")
        self.assertFalse(out["auto_paused"])

    def test_real_failures_still_pause_after_three(self):
        for _ in range(3):
            out = routines.record_routine_outcome(
                "digest", False, store=self.store)
        self.assertTrue(out["auto_paused"])

    def test_an_offline_miss_does_not_reset_the_count(self):
        routines.record_routine_outcome("digest", False, store=self.store)
        routines.record_routine_outcome("digest", False, store=self.store)
        routines.record_routine_outcome("digest", False, store=self.store,
                                        offline=True)
        self.assertEqual(self.store.get("digest").consecutive_failures, 2)

    def test_run_routine_offline_is_deferred_and_does_not_spawn(self):
        spawned = []
        with mock.patch.object(agents, "spawn",
                               lambda *a, **k: spawned.append(a) or "SPAWNED"):
            out = routines.run_routine("digest", {}, store=self.store,
                                       online_fn=lambda c: False)
        self.assertTrue(out["deferred"])
        self.assertEqual(out["error"], "offline")
        self.assertEqual(spawned, [])
        r = self.store.get("digest")
        self.assertEqual((r.consecutive_failures, r.last_status),
                         (0, "missed_offline"))

    def test_run_routine_online_spawns(self):
        with mock.patch.object(agents, "spawn", lambda *a, **k: "SPAWNED x"):
            out = routines.run_routine("digest", {}, store=self.store,
                                       online_fn=lambda c: True)
        self.assertTrue(out["ok"])

    def test_a_task_that_failed_while_offline_is_a_miss(self):
        rec = {"routine_id": "digest"}
        with mock.patch.object(routines, "online", lambda cfg=None: False):
            for _ in range(5):
                agents._record_routine_for_task(rec, "failed", False,
                                                routines_store=self.store)
        self.assertFalse(self.store.get("digest").paused)
        with mock.patch.object(routines, "online", lambda cfg=None: True):
            for _ in range(3):
                agents._record_routine_for_task(rec, "failed", False,
                                                routines_store=self.store)
        self.assertTrue(self.store.get("digest").paused)


class CliPath(unittest.TestCase):
    class Ctx:
        json = False
        cfg = {}

        def __init__(self, reply):
            self.reply, self.emitted = reply, []

        def send(self, msg):
            return self.reply

        def emit(self, data, text=None):
            self.emitted.append((data, text))
            return 0

    def run_cli(self, reply, env):
        from wisp.cli import agents as cli_agents
        ctx = self.Ctx(reply)
        waits = []
        a = mock.Mock(routine="digest", task=[])
        with mock.patch.dict("os.environ", env, clear=False), \
                mock.patch.object(routines, "wait_until_online",
                                  lambda cfg=None, **k: waits.append(1)):
            rc = cli_agents.task_run(ctx, a)
        return rc, ctx, waits

    def test_a_deferred_routine_is_not_a_failure_exit(self):
        rc, ctx, _ = self.run_cli(
            {"ok": False, "deferred": True, "result": "SKIP (no network)"},
            {})
        self.assertEqual(rc, 0)
        self.assertEqual(ctx.emitted[0][1], "SKIP (no network)")

    def test_only_a_timer_run_waits_for_the_network(self):
        ok = {"ok": True, "result": "SPAWNED x"}
        _, _, waits = self.run_cli(ok, {"INVOCATION_ID": "abc"})
        self.assertEqual(waits, [1])
        import os
        os.environ.pop("INVOCATION_ID", None)
        _, _, waits = self.run_cli(ok, {})
        self.assertEqual(waits, [])


if __name__ == "__main__":
    unittest.main()
