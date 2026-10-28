"""B12: the first-minute tour passes step by step against scripted turns."""
import json
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import onboard, tour  # noqa: E402


def turn(route="answer", drawings=(), points=()):
    return {"turn": "t", "route": route, "drawings": list(drawings),
            "points": list(points)}


class Judging(unittest.TestCase):
    def test_each_step_asks_for_its_own_proof(self):
        by = {s.id: s for s in tour.STEPS}
        ring = {"kind": "ring", "x": 1, "y": 2, "r": 3}
        arrow = {"kind": "arrow"}
        self.assertTrue(tour.passed(by["draw"], [turn(points=[{"x": 1}])]))
        self.assertTrue(tour.passed(by["draw"], [turn(drawings=[arrow])]))
        self.assertFalse(tour.passed(by["draw"], [turn()]))
        self.assertTrue(tour.passed(by["circle"], [turn(drawings=[ring])]))
        self.assertFalse(tour.passed(by["circle"], [turn(drawings=[arrow])]))
        self.assertTrue(tour.passed(by["ask"], [turn("answer")]))
        self.assertFalse(tour.passed(by["ask"], [turn("act")]))
        self.assertTrue(tour.passed(by["dictation"], [turn("dictation")]))
        self.assertFalse(tour.passed(by["dictation"], [turn("answer")]))

    def test_five_steps_in_the_documented_order(self):
        self.assertEqual([s.id for s in tour.STEPS],
                         ["hello", "draw", "circle", "ask", "dictation"])


class Walk(unittest.TestCase):
    def run_tour(self, script, **kw):
        """`script`: the turns that appear on poll 1, 2, ... (one list per
        poll, shared by every step; fixture voice)."""
        said, marks, logs = [], [], []
        polls = {"n": 0}

        def turns(since):
            polls["n"] += 1
            return script[min(polls["n"] - 1, len(script) - 1)]
        t = {"now": 0.0}

        def sleep(s):
            t["now"] += s
        res = tour.run(said.append, turns, marks.append, log=logs.append,
                       sleep=sleep, clock=lambda: t["now"], **kw)
        return res, said, marks, logs

    def test_a_full_tour_logs_a_pass_for_every_step(self):
        everything = [turn("answer",
                           drawings=[{"kind": "ring"}, {"kind": "arrow"}],
                           points=[{"x": 1}]),
                      turn("dictation")]
        res, said, marks, logs = self.run_tour([everything])
        self.assertEqual([r["status"] for r in res], ["passed"] * 5)
        self.assertEqual(marks, [s.id for s in tour.STEPS])
        self.assertEqual(said, [s.say for s in tour.STEPS])
        self.assertEqual(logs, [f"tour {s.id}: pass" for s in tour.STEPS])

    def test_a_step_nobody_does_is_skipped_not_marked(self):
        res, _, marks, logs = self.run_tour([[]], wait_s=3)
        self.assertEqual(marks, ["hello"])
        self.assertEqual([r["status"] for r in res],
                         ["passed"] + ["skipped"] * 4)
        self.assertIn("tour draw: skipped", logs)

    def test_recorded_steps_are_not_repeated_but_only_replays_one(self):
        res, said, marks, _ = self.run_tour(
            [[turn("answer")]], done={"hello", "draw", "circle"}, wait_s=2)
        self.assertEqual([r["status"] for r in res[:3]], ["already"] * 3)
        self.assertEqual(said, [tour._BY_ID["ask"].say,
                                tour._BY_ID["dictation"].say])
        res, said, marks, _ = self.run_tour(
            [[turn("answer")]], only="ask", done={"ask"})
        self.assertEqual([r["id"] for r in res], ["ask"])
        self.assertEqual(marks, ["ask"])


class FromLogs(unittest.TestCase):
    def test_turns_come_from_the_decision_log_and_trace(self):
        with tempfile.TemporaryDirectory() as td:
            td = pathlib.Path(td)
            dec, tr = td / "decisions.jsonl", td / "trace.jsonl"
            old = "2026-01-01T00:00:00+00:00"
            new = datetime.now(timezone.utc).isoformat()
            dec.write_text("\n".join(json.dumps(r) for r in (
                {"ts": old, "turn": "t0",
                 "answers": {"route": {"choice": "answer"}}},
                {"ts": new, "turn": "t1",
                 "answers": {"route": {"choice": "answer"}}},
                {"ts": new, "turn": "t2",
                 "answers": {"route": {"choice": "dictation"}}})) + "\nnot json\n")
            tr.write_text(json.dumps(
                {"ts": new, "turn": "t1", "step": "points", "kind": "act",
                 "ms": None, "data": {"points": [{"x": 1, "y": 2}],
                                      "drawings": [{"kind": "ring"}]}}) + "\n")
            got = tour.turns_since("2026-06-01T00:00:00", decisions=dec,
                                   trace_file=tr)
        self.assertEqual([t["turn"] for t in got], ["t1", "t2"])
        self.assertEqual(got[0]["drawings"], [{"kind": "ring"}])
        self.assertEqual(got[1]["route"], "dictation")
        self.assertEqual(got[1]["points"], [])

    def test_no_log_is_no_turns(self):
        self.assertEqual(tour.turns_since("x", decisions=pathlib.Path(
            "/nonexistent/decisions.jsonl")), [])


class Progress(unittest.TestCase):
    def test_passes_are_recorded_without_touching_the_setup_checklist(self):
        with tempfile.TemporaryDirectory() as td:
            p = onboard.Progress(pathlib.Path(td) / "onboard.json")
            self.assertEqual(p.tour, {})
            p.mark("mic")
            p.tour_mark("hello")
            self.assertEqual(list(p.tour), ["hello"])
            self.assertEqual(list(p.done), ["mic"])
            p.reset()
            self.assertEqual(p.tour, {})


class Cli(unittest.TestCase):
    def test_unknown_step_is_a_usage_error(self):
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        from cli_env import CliEnv
        with CliEnv() as env:
            code, out, err = env.run(["onboard", "--tour", "nope", "--json"])
        self.assertNotEqual(code, 0)
        self.assertIn("E_USAGE", out + err)

    def test_the_hello_step_runs_and_is_recorded(self):
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        from cli_env import CliEnv
        with CliEnv() as env:
            code, out, err = env.run(["onboard", "--tour", "hello",
                                      "--json"])
            self.assertEqual(code, 0, err)
            data = json.loads(out)["data"]
            self.assertEqual(data["steps"],
                             [{"id": "hello", "status": "passed"}])
            rec = json.loads(next(env.home.rglob("onboard.json")).read_text())
        self.assertIn("hello", rec["tour"])


if __name__ == "__main__":
    unittest.main()
