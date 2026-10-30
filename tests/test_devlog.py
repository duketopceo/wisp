#!/usr/bin/env python3
"""U4: `devlog` read-only IPC command and `wispd dev turns` verb. Tail-reads
decisions.jsonl and trace.jsonl, joins stages and labels, reuses
`wispd eval`'s tally and misses."""
import io
import json
import pathlib
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from wisp import devlog, ipc  # noqa: E402

NOW = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)


def ts(i):
    return (NOW + timedelta(seconds=i * 30)).isoformat()


class Base(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        d = pathlib.Path(td.name)
        self.decs, self.labs, self.trace = (
            d / "decisions.jsonl", d / "labels.jsonl", d / "trace.jsonl")
        for p in (self.decs, self.labs, self.trace):
            p.write_text("")

    def dec(self, i, result="ANSWERED: hi", transcript="what time is it",
            spans=(), route="answer"):
        rec = {"ts": ts(i), "turn": f"t{i}", "transcript": transcript,
               "answers": {"route": {"choice": route}}, "result": result}
        with self.decs.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        with self.trace.open("a") as f:
            for name, ms in spans:
                f.write(json.dumps({"ts": ts(i), "turn": f"t{i}",
                                    "step": name, "kind": "span",
                                    "ms": ms, "data": {}}) + "\n")

    def lab(self, i, label, note=""):
        with self.labs.open("a") as f:
            f.write(json.dumps({"ts": "x", "ref": ts(i), "label": label,
                                "note": note}) + "\n")

    def build(self, n=20, cfg=None, **kw):
        return devlog.build(cfg or {}, n=n, decisions_file=self.decs,
                            labels_file=self.labs, trace_file=self.trace,
                            **kw)


class TestTurns(Base):
    def test_newest_first_and_default_n(self):
        for i in range(30):
            self.dec(i)
        r = self.build(n=None)
        self.assertEqual(len(r["turns"]), 20)
        self.assertEqual([t["turn"] for t in r["turns"][:3]],
                         ["t29", "t28", "t27"])

    def test_n_clamped_to_max(self):
        for i in range(60):
            self.dec(i)
        self.assertEqual(len(self.build(n=500)["turns"]), 50)
        self.assertEqual(len(self.build(n=0)["turns"]), 1)

    def test_stages_in_order_and_add_up(self):
        self.dec(1, spans=[("stt", 400), ("route", 150),
                           ("first_token", 300), ("done", 850)])
        t = self.build()["turns"][0]
        self.assertEqual([s["name"] for s in t["stages"]],
                         ["stt", "route", "first_token"])
        self.assertEqual(sum(s["ms"] for s in t["stages"]), t["total_ms"])
        self.assertEqual(t["total_ms"], 850)
        self.assertEqual(t["route"], "answer")
        self.assertEqual(t["id"], "t1")

    def test_no_spans_gives_empty_stages(self):
        self.dec(1)
        t = self.build()["turns"][0]
        self.assertEqual(t["stages"], [])
        self.assertIsNone(t["total_ms"])

    def test_missing_files_are_not_errors(self):
        self.decs.unlink()
        self.trace.unlink()
        r = self.build()
        self.assertEqual(r["turns"], [])
        self.assertIsNone(r["rated_share"])

    def test_transcript_and_result_truncated(self):
        self.dec(1, transcript="x" * 500, result="ANSWERED " + "y" * 500)
        t = self.build()["turns"][0]
        self.assertLessEqual(len(t["transcript"]), 120)
        self.assertLessEqual(len(t["result"]), 120)

    def test_act_steps(self):
        self.dec(1, result="ACTED (3 steps): opened it", route="act")
        self.dec(2)
        t = {x["id"]: x for x in self.build()["turns"]}
        self.assertEqual(t["t1"]["act_steps"], 3)
        self.assertIsNone(t["t2"]["act_steps"])

    def test_reply_is_capped_and_marked(self):
        for i in range(50):
            self.dec(i, transcript="w" * 400, spans=[
                (f"s{k}", 5) for k in range(40)])
        r = self.build(n=50, max_bytes=8000)
        self.assertLessEqual(len(json.dumps(r)), 8000)
        self.assertTrue(r["truncated"])
        self.assertEqual(r["turns"][0]["id"], "t49")


class TestLabels(Base):
    def test_latest_label_wins(self):
        self.dec(1)
        self.lab(1, "correct")
        self.lab(1, "incorrect", "wrong app")
        t = self.build()["turns"][0]
        self.assertEqual(t["label"], "incorrect")
        self.assertEqual(t["note"], "wrong app")

    def test_unlabelled_is_none(self):
        self.dec(1)
        t = self.build()["turns"][0]
        self.assertEqual(t["label"], "none")
        self.assertEqual(t["note"], "")

    def test_rated_share_counts_finished_turns_only(self):
        self.dec(1)
        self.dec(2)
        self.dec(3)
        self.dec(4, result="CANCELLED (user)")
        self.dec(5, result="ERROR (boom)")
        self.lab(1, "correct")
        self.lab(2, "incorrect")
        r = self.build()
        self.assertEqual(r["rated"], 2)
        self.assertEqual(r["finished"], 3)
        self.assertAlmostEqual(r["rated_share"], 2 / 3)

    def test_gate_and_misses_reuse_eval(self):
        from wisp import learn
        for i in range(4):
            self.dec(i)
            self.lab(i, "correct" if i < 3 else "incorrect")
        cfg = {"eval": {"gate_rate": "60%", "gate_min_turns": 5}}
        r = self.build(cfg=cfg)
        rep = learn.eval_report(cfg, self.decs, self.labs)
        g = r["gate"]
        self.assertEqual(g["labelled"], 4)
        self.assertEqual(g["correct"], 3)
        self.assertEqual(g["rate"], rep["total"]["rate"])
        self.assertEqual(g["gate_rate"], 0.6)
        self.assertEqual(g["min_turns"], 5)
        self.assertEqual(g["kinds"], rep["kinds"])
        self.assertEqual(r["misses"],
                         learn.eval_misses(self.decs, self.labs))


class TestBigTrace(Base):
    def test_50mb_trace_reads_only_the_tail(self):
        # old filler first (stale ts), then three real turns at the end
        old = json.dumps({"ts": "2020-01-01T00:00:00+00:00", "turn": "old",
                          "step": "stt", "kind": "span", "ms": 1,
                          "data": {"pad": "z" * 200}}) + "\n"
        block = old * 5000
        with self.trace.open("w") as f:
            for _ in range(int(50_000_000 / len(block)) + 1):
                f.write(block)
        self.assertGreater(self.trace.stat().st_size, 50_000_000)
        for i in range(3):
            self.dec(i, spans=[("stt", 100 + i), ("done", 100 + i)])
        stats = {}
        t0 = time.monotonic()
        r = self.build(n=3, stats=stats)
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertLess(stats["trace_bytes"], 10_000_000)
        self.assertEqual([x["stages"][0]["ms"] for x in r["turns"]],
                         [102, 101, 100])


class TestIpc(Base):
    def test_devlog_is_a_read_command(self):
        self.assertIn("devlog", ipc.READ_CMDS)
        self.assertNotIn("devlog", ipc.MUTATING_CMDS)
        self.assertEqual(ipc.classify_cmd("devlog"), "read")


class TestCli(unittest.TestCase):
    def test_dev_turns_prints_json(self):
        from cli_env import CliEnv
        with CliEnv(daemon=True) as env:
            code, out, err = env.run(["dev", "turns", "--json"])
            self.assertEqual(code, 0, err)
            body = json.loads(out)
            self.assertTrue(body["ok"])
            self.assertIn("turns", body["data"])
            self.assertEqual(env.ipc[-1]["cmd"], "devlog")

    def test_dev_turns_n_is_sent(self):
        from cli_env import CliEnv
        with CliEnv(daemon=True) as env:
            env.run(["dev", "turns", "--json", "-n", "7"])
            self.assertEqual(env.ipc[-1].get("n"), 7)


if __name__ == "__main__":
    unittest.main()
