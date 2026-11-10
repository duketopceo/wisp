"""`wispd dev runs|review --data-dir DIR` reads a gauntlet's data
directory directly: the daemon on the socket serves its own data, so a
gauntlet run must never be looked up through it."""
import json
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from cli_env import CliEnv  # noqa: E402


def seed(d: pathlib.Path):
    (d / "dev_runs").mkdir(parents=True)
    row = {"run_id": "g1", "index": 0, "goal": "open the folder",
           "turn": "tg1", "route": "act",
           "result": "ACTED (1 steps): ok", "steps": [],
           "outcome": "success",
           "timing_ms": {"route": 1, "act": 2, "wall": 3},
           "judge": {"outcome": "success", "reason": "looks done",
                     "model": "m", "cost_usd": 0.0},
           "cost": {"task_usd": 0.0, "judge_usd": 0.0}}
    (d / "dev_runs" / "g1.jsonl").write_text(json.dumps(row) + "\n")
    (d / "decisions.jsonl").write_text(json.dumps(
        {"ts": "ts1", "turn": "tg1", "transcript": "open the folder",
         "result": "ACTED (1 steps): ok"}) + "\n")


class TestDataDir(unittest.TestCase):
    def test_review_reads_the_directory_not_the_daemon(self):
        with CliEnv(daemon=True) as env:   # daemon answers: no runs
            gdata = env.home / "g" / "data" / "wisp"
            seed(gdata)
            code, out, err = env.run(
                ["dev", "review", "--json", "--data-dir", str(gdata), "g1"])
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["data"]["run_id"], "g1")
            self.assertEqual(env.ipc, [])          # never asked the daemon

    def test_without_the_flag_the_daemon_answers(self):
        with CliEnv(daemon=True) as env:
            code, out, err = env.run(["dev", "review", "g1"])
            self.assertNotEqual(code, 0)
            self.assertIn("No dev run", out + err)
            self.assertEqual([c["cmd"] for c in env.ipc], ["dev_runs"])

    def test_runs_reads_the_directory(self):
        with CliEnv(daemon=True) as env:
            gdata = env.home / "g" / "data" / "wisp"
            seed(gdata)
            code, out, err = env.run(
                ["dev", "runs", "--json", "--data-dir", str(gdata)])
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["data"]["runs"][0]["run_id"], "g1")
            self.assertEqual(env.ipc, [])

    def test_set_writes_the_label_into_that_directory(self):
        with CliEnv(daemon=True) as env:
            gdata = env.home / "g" / "data" / "wisp"
            seed(gdata)
            code, out, err = env.run(
                ["dev", "review", "--set", "tg1", "correct", "--json",
                 "--data-dir", str(gdata), "g1"])
            self.assertEqual(code, 0, err)
            lab = json.loads((gdata / "labels.jsonl").read_text())
            self.assertEqual((lab["ref"], lab["label"]), ("ts1", "correct"))
            self.assertEqual(env.ipc, [])
            self.assertFalse((env.data / "labels.jsonl").exists())

    def test_a_missing_directory_is_a_usage_error(self):
        with CliEnv() as env:
            code, out, err = env.run(
                ["dev", "runs", "--data-dir", str(env.home / "nope")])
            self.assertNotEqual(code, 0)
            self.assertIn("No data directory", out + err)


if __name__ == "__main__":
    unittest.main()
