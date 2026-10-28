"""B29: idle cost is a number CI watches.

`wispd health idle` samples the running daemon (CPU over a short window,
resident memory) against the `idle_cpu_pct` and `idle_rss_mb` rows of
wisp/budgets.json. The smoke starts the real daemon in a throwaway tree,
lets it settle, and requires it to be inside the budget; a spin-loop
holding the daemon's lock must fail the same check.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from daemonbox import DaemonBox  # noqa: E402
from wisp import idle, telemetry  # noqa: E402

SETTLE_S = 2.0


def wispd(box, *args):
    p = subprocess.run([sys.executable, str(ROOT / "wispd"), *args],
                       env=box.env, cwd=str(ROOT), capture_output=True,
                       text=True, timeout=60)
    return p


class Budgets(unittest.TestCase):
    def test_idle_rows_exist_and_are_not_loosened(self):
        r = telemetry.load_budgets()["resources"]
        self.assertEqual(r["idle_cpu_pct"], 3)
        self.assertEqual(r["idle_rss_mb"], 250)
        # the older rows say the same thing and must keep agreeing
        self.assertEqual(r["idle_cpu_pct"], r["wispd_idle_cpu_pct"])
        self.assertEqual(r["idle_rss_mb"], r["wispd_rss_mb"])
        self.assertEqual(r["always_on_polling_loops"], 0)

    def test_breaches_say_which_budget_in_plain_words(self):
        b = {"cpu_pct": 3.0, "rss_mb": 250.0}
        self.assertEqual(idle.breaches(
            {"cpu_pct": 1.0, "rss_mb": 40.0}, b), [])
        self.assertEqual(idle.breaches(
            {"cpu_pct": 3.0, "rss_mb": 250.0}, b), [])     # at the line: ok
        over = idle.breaches({"cpu_pct": 60.0, "rss_mb": 300.0}, b)
        self.assertEqual(len(over), 2)
        self.assertIn("CPU", over[0])
        self.assertIn("memory", over[1])


class Sampling(unittest.TestCase):
    def test_stat_parsing_survives_spaces_and_parens_in_the_name(self):
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "7").mkdir()
        (d / "7" / "stat").write_text(
            "7 (my (odd) name) S 1 7 7 0 -1 0 0 0 0 0 40 2 0 0 20 0 1 0 "
            "100 1000 10\n")
        (d / "7" / "status").write_text("Name:\tx\nVmRSS:\t  20480 kB\n")
        self.assertEqual(idle.cpu_ticks(7, d), 42)
        self.assertEqual(idle.rss_mb(7, d), 20.0)

    def test_cpu_percent_is_ticks_over_wall_time(self):
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "9").mkdir()
        (d / "9" / "status").write_text("VmRSS:\t 1024 kB\n")
        ticks = iter([100, 150])

        def stat():
            (d / "9" / "stat").write_text(
                "9 (x) S " + "0 " * 10 + f"{next(ticks)} 0 " + "0 " * 8)
        stat()
        clock = iter([0.0, 2.0])

        def sleep(_s):
            stat()
        s = idle.sample(9, 2, proc=d, clock=lambda: next(clock),
                        sleep=sleep, hz=100)
        self.assertEqual(s["cpu_pct"], 25.0)        # 50 ticks / 2 s / 100 Hz
        self.assertEqual(s["rss_mb"], 1.0)

    def test_an_unreadable_process_is_none(self):
        self.assertIsNone(idle.sample(2 ** 22 + 12345, 0.01))

    def test_a_spin_loop_is_over_budget_and_a_sleeper_is_not(self):
        spin = subprocess.Popen([sys.executable, "-c", "while True: pass"])
        nap = subprocess.Popen([sys.executable, "-c",
                                "import time; time.sleep(30)"])
        self.addCleanup(lambda: [p.kill() or p.wait() for p in (spin, nap)])
        time.sleep(0.3)
        hot = idle.sample(spin.pid, 1.0)
        cold = idle.sample(nap.pid, 1.0)
        self.assertGreater(hot["cpu_pct"], 50)
        self.assertTrue(any("CPU" in m for m in idle.breaches(hot)))
        self.assertEqual(idle.breaches(cold), [])


class RealDaemonIdle(unittest.TestCase):
    def test_the_idle_daemon_is_inside_the_budget(self):
        box = DaemonBox()
        self.addCleanup(box.close)
        d = box.start()
        self.assertIsNone(d.poll(), "daemon did not start")
        time.sleep(SETTLE_S)
        p = wispd(box, "health", "idle", "--seconds", "3", "--json")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        data = json.loads(p.stdout)["data"]
        self.assertEqual(data["pid"], d.pid)
        self.assertTrue(data["ok"], data)
        self.assertLessEqual(data["cpu_pct"], data["budget_cpu_pct"])
        self.assertLessEqual(data["rss_mb"], data["budget_rss_mb"])

    def test_the_check_fails_when_a_spin_loop_holds_the_daemon_lock(self):
        box = DaemonBox()
        self.addCleanup(box.close)
        (box.tmp / "run" / "wisp").mkdir(parents=True)
        code = ("import sys, pathlib; sys.path.insert(0, %r);"
                "from wisp import instance;"
                "instance.acquire(pathlib.Path(%r));"
                "print('held', flush=True)\n"
                "while True: pass" % (str(ROOT), str(box.lock)))
        spin = subprocess.Popen([sys.executable, "-c", code],
                                stdout=subprocess.PIPE, text=True,
                                env=box.env)
        self.addCleanup(lambda: (spin.kill(), spin.wait(), spin.stdout.close()))
        self.assertEqual(spin.stdout.readline().strip(), "held")
        p = wispd(box, "health", "idle", "--seconds", "1", "--json")
        self.assertEqual(p.returncode, 4, p.stdout + p.stderr)   # unhealthy
        self.assertIn("idle CPU", p.stderr + p.stdout)

    def test_no_daemon_is_reported_as_down(self):
        box = DaemonBox()
        self.addCleanup(box.close)
        p = wispd(box, "health", "idle", "--seconds", "1")
        self.assertEqual(p.returncode, 3, p.stdout + p.stderr)

    def test_a_bad_window_is_a_usage_error(self):
        box = DaemonBox()
        self.addCleanup(box.close)
        p = wispd(box, "health", "idle", "--seconds", "0")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
