"""CubeVM worker lifecycle + parallel hammer helpers (no real API)."""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
CL = ROOT / "scripts" / "clicklab"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(CL))

import cube  # noqa: E402
import report  # noqa: E402
import run  # noqa: E402
from wisp import ledger  # noqa: E402


class CubeStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, "cube-worker.json")
        self._state = mock.patch.object(cube, "STATE", self.state)
        self._state.start()

    def tearDown(self):
        self._state.stop()
        self.tmp.cleanup()

    def test_legacy_state_migrates(self):
        with open(self.state, "w") as f:
            json.dump({"sandbox_id": "s1", "ip": "10.0.0.2"}, f)
        ws = cube._workers()
        self.assertEqual(len(ws), 1)
        self.assertEqual(ws[0]["sandbox_id"], "s1")

    def test_workers_round_trip(self):
        ws = [{"sandbox_id": f"s{i}", "ip": f"10.0.0.{i}"}
              for i in range(3)]
        cube._save_workers(ws)
        self.assertEqual(len(cube._workers()), 3)
        # reload survives a fresh read
        self.assertEqual(cube._workers()[2]["ip"], "10.0.0.2")

    def test_down_kills_every_worker(self):
        ws = [{"sandbox_id": f"s{i}", "ip": f"10.0.0.{i}"}
              for i in range(3)]
        cube._save_workers(ws)
        calls = []
        with mock.patch.object(cube, "_req",
                               side_effect=lambda m, p, b: calls.append(p)
                               or {}):
            cube.down()
        self.assertEqual(sorted(calls),
                         ["/sandboxes/s0", "/sandboxes/s1",
                          "/sandboxes/s2"])
        self.assertEqual(cube._workers(), [])

    def test_down_kill_fallback(self):
        cube._save_workers([{"sandbox_id": "s9", "ip": "1.2.3.4"}])
        calls = []

        def req(m, p, b):
            calls.append((m, p))
            if m == "DELETE":
                raise OSError("gone")
            return {}

        with mock.patch.object(cube, "_req", side_effect=req):
            cube.down()
        self.assertIn(("POST", "/sandboxes/s9/kill"), calls)

    def test_up_reuses_alive_recreates_dead(self):
        cube._save_workers([
            {"sandbox_id": "good", "ip": "10.0.0.1"},
            {"sandbox_id": "dead", "ip": "10.0.0.2"}])
        created = []

        def alive(w):
            return w["sandbox_id"] == "good"

        def create():
            created.append(1)
            return {"sandbox_id": "new", "ip": "10.0.0.9",
                    "cdp_port": 9223}

        with mock.patch.object(cube, "_alive", side_effect=alive), \
                mock.patch.object(cube, "provision", return_value=9223), \
                mock.patch.object(cube, "_create", side_effect=create):
            ws = cube.up(2)
        self.assertEqual(len(ws), 2)
        self.assertEqual(len(created), 1)
        self.assertEqual({w["sandbox_id"] for w in ws},
                         {"good", "new"})

    def test_up_keeps_extra_live_workers_tracked(self):
        cube._save_workers([
            {"sandbox_id": "a", "ip": "10.0.0.1"},
            {"sandbox_id": "b", "ip": "10.0.0.2"},
            {"sandbox_id": "c", "ip": "10.0.0.3"}])
        with mock.patch.object(cube, "_alive", return_value=True), \
                mock.patch.object(cube, "provision", return_value=9223):
            ws = cube.up(1)
        self.assertEqual(len(ws), 1)
        # shrinking the request must not untrack live sandboxes
        self.assertEqual(len(cube._workers()), 3)


class WorkerStampTest(unittest.TestCase):
    def test_stamp_sets_both_fields(self):
        recs = [{"task": "t", "verified": True},
                {"task": "u", "verified": False}]
        run._stamp(recs, "3", "sbx-1")
        for r in recs:
            self.assertEqual(r["worker"], 3)
            self.assertEqual(r["sandbox_id"], "sbx-1")

    def test_stamp_noop_without_flags(self):
        recs = [{"task": "t"}]
        run._stamp(recs, "", None)
        self.assertEqual(recs, [{"task": "t"}])


class ParallelLedgerTest(unittest.TestCase):
    def test_two_writers_no_corruption(self):
        """Two processes appending ledger rows produce only whole,
        parseable lines — the write path is O_APPEND + flock + a
        single os.write."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        path = os.path.join(tmp, "usage.jsonl")
        script = (
            "import sys; sys.path.insert(0, %r);"
            "from wisp import ledger;"
            "p = sys.argv[1];"
            "import pathlib;"
            "[ledger.record(provider='x', model='m', tokens_in=1,"
            " tokens_out=1, usd=0.0, paid=False,"
            " path=pathlib.Path(p))"
            " for _ in range(100)]") % str(ROOT)
        procs = [subprocess.Popen([sys.executable, "-c", script, path])
                 for _ in range(2)]
        for p in procs:
            p.wait(timeout=60)
            self.assertEqual(p.returncode, 0)
        lines = open(path).read().splitlines()
        self.assertEqual(len(lines), 200)
        for l in lines:
            self.assertEqual(json.loads(l)["model"], "m")


class ReportTest(unittest.TestCase):
    def _write(self, records):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl",
                                          delete=False)
        for r in records:
            tmp.write(json.dumps(r) + "\n")
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        return tmp.name

    def test_grouping_and_calls_per_verified(self):
        path = self._write([
            {"model": "m1", "suite": "s", "verified": True,
             "cost_usd": 0.01, "ts": 100.0},
            {"model": "m1", "suite": "s", "verified": False,
             "cost_usd": 0.02, "ts": 100.0},
            {"model": "m1", "suite": "s", "verified": True,
             "cost_usd": 0.01, "ts": 100.0},
            {"model": "m2", "suite": "s", "verified": False,
             "cost_usd": 0.5, "ts": 100.0},
        ])
        recs = [json.loads(l) for l in open(path)]
        rows = report.render(report.summarize(recs))
        m1 = next(r for r in rows if r["model"] == "m1")
        self.assertEqual(m1["tasks"], 3)
        self.assertEqual(m1["verified"], 2)
        self.assertAlmostEqual(m1["cost_usd"], 0.04)
        self.assertAlmostEqual(m1["calls_per_verified"], 1.5)
        m2 = next(r for r in rows if r["model"] == "m2")
        self.assertIsNone(m2["calls_per_verified"])

    def test_since_parses_iso_and_unix(self):
        self.assertEqual(report._since("200"), 200.0)
        self.assertGreater(report._since("2026-10-05T00:00:00"), 0)


if __name__ == "__main__":
    unittest.main()
