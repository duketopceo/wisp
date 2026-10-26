#!/usr/bin/env python3
"""U2: `wispd eval` — outcome eval over hand labels keyed by turn kind."""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import learn  # noqa: E402


class EvalBase(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.decs = pathlib.Path(td.name) / "decisions.jsonl"
        self.labs = pathlib.Path(td.name) / "labels.jsonl"
        self.decs.write_text("")
        self.labs.write_text("")

    def dec(self, ref, result):
        with self.decs.open("a") as f:
            f.write(json.dumps({"ts": ref, "result": result}) + "\n")

    def lab(self, ref, label):
        with self.labs.open("a") as f:
            f.write(json.dumps({"ts": "x", "ref": ref, "label": label,
                                "note": ""}) + "\n")

    def bulk(self, n, ok):
        for i in range(n):
            ref = f"B{i}"
            self.dec(ref, "ANSWERED")
            self.lab(ref, "correct" if i < ok else "incorrect")

    def report(self, eval_cfg=None):
        cfg = {"eval": eval_cfg} if eval_cfg is not None else {}
        return learn.eval_report(cfg, decisions_file=self.decs,
                                 labels_file=self.labs)


class TestEvalCounts(EvalBase):
    def test_answer_and_act_kinds(self):
        self.dec("A1", "ANSWERED")
        self.dec("A2", "ANSWERED")
        self.dec("C1", "ACTED (2 steps): done")
        self.lab("A1", "correct")
        self.lab("A2", "incorrect")
        self.lab("C1", "correct")
        r = self.report()
        a = r["kinds"]["answer"]
        self.assertEqual((a["labelled"], a["correct"], a["incorrect"],
                          a["corrected"]), (2, 1, 1, 0))
        self.assertAlmostEqual(a["rate"], 0.5)
        c = r["kinds"]["act"]
        self.assertEqual((c["labelled"], c["correct"]), (1, 1))
        self.assertAlmostEqual(c["rate"], 1.0)
        self.assertEqual(r["total"]["labelled"], 3)
        self.assertAlmostEqual(r["total"]["rate"], 2 / 3)

    def test_latest_label_wins(self):
        self.dec("T1", "ACTED (1 steps): x")
        self.lab("T1", "incorrect")
        self.lab("T1", "corrected-by-retry")
        r = self.report()
        k = r["kinds"]["act"]
        self.assertEqual((k["labelled"], k["correct"], k["incorrect"],
                          k["corrected"]), (1, 0, 0, 1))
        self.assertEqual(r["total"]["labelled"], 1)

    def test_orphan_label_is_other(self):
        self.lab("GONE", "correct")
        r = self.report()
        self.assertEqual(r["kinds"]["other"]["labelled"], 1)

    def test_kind_mapping(self):
        for res, kind in [("ANSWERED", "answer"), ("ACTED (3)", "act"),
                          ("LAUNCHED foo -> foo", "launch"),
                          ("DICTATED", "dictate"), ("INSERTED (paste)",
                                                    "dictate"),
                          ("SPAWNED x (pid 1)", "agent"),
                          ("BLOCKED (x)", "other"), ("", "other")]:
            self.assertEqual(learn.turn_kind(res), kind, res)


class TestEvalGate(EvalBase):
    def test_pass(self):
        self.bulk(50, 35)
        g = self.report({"gate_rate": "0.6", "gate_min_turns": "50"})["gate"]
        self.assertEqual(g["status"], "PASS")

    def test_fail_rate(self):
        self.bulk(50, 25)
        g = self.report({"gate_rate": "0.6"})["gate"]
        self.assertEqual(g["status"], "FAIL")

    def test_fail_too_few(self):
        self.bulk(10, 10)
        r = self.report({"gate_rate": "0.6", "gate_min_turns": "50"})
        self.assertEqual(r["gate"]["status"], "FAIL")
        self.assertEqual(r["gate"]["needs"], 40)
        self.assertIn("needs 40 more labelled turns", learn.eval_text(r))

    def test_unset(self):
        self.bulk(60, 60)
        r = self.report()
        self.assertEqual(r["gate"]["status"], "unset")
        txt = learn.eval_text(r)
        self.assertIn("gate not set", txt)
        self.assertNotIn("PASS", txt)
        self.assertNotIn("FAIL", txt)
        self.assertEqual(self.report({"gate_rate": ""})["gate"]["status"],
                         "unset")

    def test_no_labels(self):
        self.assertIn("no labels yet", learn.eval_text(self.report()))


class TestEvalCli(EvalBase):
    def run_cli(self, *argv):
        import io
        from contextlib import redirect_stdout
        from wisp import cli
        buf = io.StringIO()
        with mock.patch.object(learn, "LABELS_FILE", self.labs), \
                mock.patch("wisp.config.DECISIONS", self.decs), \
                mock.patch("wisp.config.load_config",
                           return_value={"eval": {"gate_rate": "0.5"}}), \
                redirect_stdout(buf):
            code = cli.main(list(argv), host=None)
        return code, buf.getvalue()

    def test_json_matches(self):
        self.bulk(4, 3)
        code, out = self.run_cli("eval", "--json")
        self.assertEqual(code, 0)
        d = json.loads(out)
        d = d.get("data", d)
        self.assertEqual(d["total"]["labelled"], 4)
        self.assertAlmostEqual(d["total"]["rate"], 0.75)
        self.assertEqual(d["gate"]["status"], "FAIL")

    def test_text_exit_zero_on_fail(self):
        self.bulk(4, 3)
        code, out = self.run_cli("eval")
        self.assertEqual(code, 0)
        self.assertIn("answer", out)


if __name__ == "__main__":
    unittest.main()
