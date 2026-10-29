#!/usr/bin/env python3
"""Learning-loop tests: correction recording, labels, retry context."""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import learn  # noqa: E402


class TestCorrections(unittest.TestCase):
    def test_record_appends_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            f = pathlib.Path(td) / "corrections.jsonl"
            learn.record_correction("open dicord", "app:discord",
                                    {"app": {"choice": "browser"}},
                                    corrections_file=f)
            rec = json.loads(f.read_text().splitlines()[0])
        self.assertEqual(rec["picked"], "app:discord")
        self.assertEqual(rec["jev_said"]["app"], "browser")


if __name__ == "__main__":
    unittest.main()


class CorrectionTest(unittest.TestCase):
    def setUp(self):
        d = pathlib.Path(tempfile.mkdtemp())
        self.decs = d / "decisions.jsonl"
        self.labs = d / "labels.jsonl"
        self.decs.write_text(json.dumps(
            {"ts": "T1", "transcript": "open mario",
             "answers": {"route": {"choice": "launch"}},
             "result": "LAUNCHED retroarch"}) + "\n")

    def _cfg(self, refine="true"):
        return {"dev": {"refine": refine}}

    def _ctx(self, text):
        with mock.patch.object(learn, "_last_decision",
                               lambda *a, **k: learn._read_jsonl(
                                   self.decs)[-1]), \
             mock.patch.object(learn, "_last_label",
                               lambda *a, **k: (learn._read_jsonl(
                                   self.labs) or [None])[-1]):
            return learn.correction_context(text, self._cfg())

    def test_cue_phrase_triggers(self):
        c = self._ctx("no, open the 64 version")
        self.assertEqual(c["via"], "cue")
        self.assertEqual(c["prior_route"], "launch")

    def test_label_channel(self):
        self.labs.write_text(json.dumps(
            {"ts": "x", "ref": "T1", "label": "incorrect"}) + "\n")
        c = self._ctx("try the n64 page")
        self.assertEqual(c["via"], "label")

    def test_normal_utterance_skips(self):
        self.assertIsNone(self._ctx("open terminal"))

    def test_refine_off(self):
        self.assertIsNone(
            learn.correction_context("no do it", {"dev": {"refine": "false"}}))

    def test_record_retry_and_fails(self):
        with mock.patch.object(learn, "LABELS_FILE", self.labs):
            learn.record_retry("T1", "ACTED (2 steps): done")
        self.assertIn("corrected-by-retry", self.labs.read_text())
        out = learn.fails(decisions_file=self.decs,
                          labels_file=self.labs)
        # T1 has no incorrect label and a non-failure result → not listed
        self.assertIn("no failures", out)

    def test_fails_fixed(self):
        self.decs.write_text(json.dumps(
            {"ts": "T1", "transcript": "open mario",
             "result": "ABORTED (max steps)"}) + "\n")
        self.labs.write_text(json.dumps(
            {"ts": "x", "ref": "T1", "label": "corrected-by-retry",
             "note": "ACTED (2 steps): opened"}) + "\n")
        out = learn.fails(decisions_file=self.decs,
                          labels_file=self.labs)
        self.assertIn("fixed", out)


class ThemeTest(unittest.TestCase):
    def test_tokens_both_themes(self):
        from wisp import theme
        for name in theme.THEMES:
            t = theme.THEMES[name]
            for k in ("canvas", "ink", "accent", "guide", "err"):
                self.assertIn(k, t)

    def test_current_falls_back(self):
        from wisp import theme
        self.assertEqual(theme.current({"ui": {"theme": "bogus"}}),
                         "dark")
        self.assertEqual(theme.current({"ui": {"theme": "light"}}),
                         "light")

    def test_emit_writes_theme_json(self):
        from wisp import theme
        d = pathlib.Path(tempfile.mkdtemp()) / "theme.json"
        with mock.patch.object(theme, "FILE", d):
            self.assertEqual(theme.emit({"ui": {"theme": "light"}}),
                             "light")
            body = json.loads(d.read_text())
        self.assertEqual(body["name"], "light")
        self.assertEqual(body["tokens"]["canvas"], "#f5f6fa")


class LabelTurnTest(unittest.TestCase):
    """U1/R9: a label names its turn and never lands on a newer,
    cancelled or errored line."""

    def setUp(self):
        d = pathlib.Path(tempfile.mkdtemp())
        self.decs = d / "decisions.jsonl"
        self.labs = d / "labels.jsonl"
        p1 = mock.patch.object(learn.config, "DECISIONS", self.decs)
        p2 = mock.patch.object(learn, "LABELS_FILE", self.labs)
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    def _decs(self, *rows):
        self.decs.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def _labels(self):
        return learn._read_jsonl(self.labs)

    def test_turn_wins_over_a_newer_line(self):
        self._decs({"ts": "T1", "turn": "a1", "result": "ANSWERED"},
                   {"ts": "T2", "turn": "b2", "result": "ACTED (1 steps)"})
        out = learn.label_last("correct", turn="a1")
        self.assertTrue(out.startswith("labeled correct"), out)
        self.assertEqual([r["ref"] for r in self._labels()], ["T1"])

    def test_no_turn_skips_a_cancelled_last_line(self):
        self._decs({"ts": "T1", "turn": "a1", "result": "ANSWERED"},
                   {"ts": "T2", "turn": "b2",
                    "result": "CANCELLED (user)"},
                   {"ts": "T3", "turn": "c3", "result": "ERROR (boom)"})
        learn.label_last("incorrect")
        self.assertEqual([r["ref"] for r in self._labels()], ["T1"])

    def test_out_names_the_turn_that_was_labelled(self):
        self._decs({"ts": "T1", "turn": "a1", "result": "ANSWERED"},
                   {"ts": "T2", "turn": "b2", "result": "ANSWERED"})
        got = {}
        learn.label_last("incorrect", out=got)
        self.assertEqual(got, {"turn": "b2"})
        got = {}
        learn.label_last("incorrect", turn="a1", out=got)
        self.assertEqual(got, {"turn": "a1"})
        got = {}
        learn.label_last("incorrect", turn="zz", out=got)
        self.assertEqual(got, {})

    def test_cancelled_turn_is_not_ratable_and_writes_nothing(self):
        self._decs({"ts": "T1", "turn": "a1", "result": "ANSWERED"},
                   {"ts": "T2", "turn": "b2",
                    "result": "CANCELLED (user)"},
                   {"ts": "T3", "turn": "c3", "result": "ERROR (x)"})
        for t in ("b2", "c3"):
            out = learn.label_last("correct", turn=t)
            self.assertEqual(learn.label_status(out), "not_ratable", out)
        self.assertFalse(self.labs.exists())

    def test_unknown_turn_is_not_found(self):
        self._decs({"ts": "T1", "turn": "a1", "result": "ANSWERED"},
                   {"ts": "T0", "result": "ANSWERED"})  # pre-turn line
        out = learn.label_last("correct", turn="zzz")
        self.assertEqual(learn.label_status(out), "not_found", out)
        self.assertFalse(self.labs.exists())

    def test_status_ok_and_empty_log(self):
        self._decs({"ts": "T1", "turn": "a1", "result": "ANSWERED"})
        self.assertEqual(learn.label_status(
            learn.label_last("correct", turn="a1")), "ok")
        self.decs.write_text("")
        self.assertEqual(learn.label_status(
            learn.label_last("correct")), "not_found")

    def test_relabel_appends_and_eval_takes_latest(self):
        self._decs({"ts": "T1", "turn": "a1", "result": "ANSWERED"},
                   {"ts": "T2", "turn": "b2", "result": "ANSWERED"})
        learn.label_last("correct", turn="a1")
        learn.label_last("incorrect", turn="a1")
        self.assertEqual(len(self._labels()), 2)
        rep = learn.eval_report(None, self.decs, self.labs)
        self.assertEqual(rep["total"]["labelled"], 1)
        self.assertEqual(rep["total"]["incorrect"], 1)
        self.assertEqual(rep["total"]["correct"], 0)

    def test_eval_tallies_turn_labels_unchanged(self):
        self._decs({"ts": "T1", "turn": "a1", "result": "ANSWERED"},
                   {"ts": "T2", "turn": "b2", "result": "ACTED (2 steps)"})
        learn.label_last("correct", turn="a1")
        learn.label_last("incorrect", turn="b2")
        rep = learn.eval_report(None, self.decs, self.labs)
        self.assertEqual((rep["total"]["labelled"],
                          rep["total"]["correct"]), (2, 1))
        self.assertEqual(set(rep["kinds"]), {"answer", "act"})


class DecisionWriterTurnTest(unittest.TestCase):
    """Every decisions.jsonl writer stamps the turn, cancelled and
    error lines included."""

    def _run(self, exc):
        from wisp import pipeline
        logged = []
        st = mock.Mock()
        cfg = {"audio": {"seconds": "0"}, "agent": {},
               "brain": {"router": "jev"}}
        with mock.patch.object(pipeline, "record",
                           return_value=pathlib.Path("/x.wav")), \
             mock.patch.object(pipeline, "transcribe", side_effect=exc), \
             mock.patch.object(pipeline, "notify"), \
             mock.patch.object(pipeline, "log_decision",
                               side_effect=logged.append):
            pipeline.run_listen(cfg, st, wav=pathlib.Path("/x.wav"))
        return logged

    def test_cancel_line_carries_turn(self):
        from wisp import cancel
        rows = self._run(cancel.Cancelled())
        self.assertEqual(len(rows), 1, rows)
        self.assertTrue(rows[0].get("turn"), rows)
        self.assertTrue(rows[0]["result"].startswith("CANCELLED"))

    def test_low_confidence_cancel_line_carries_turn(self):
        from wisp import pipeline, stage_route
        logged = []
        ctx = mock.MagicMock()
        ctx.turn, ctx.text = "T9", "open thing"
        ctx.cfg = {"brain": {"router": "jev"}}
        ctx.wait_for_choice = None
        ctx.harness = {}
        from wisp import trace
        with mock.patch.object(pipeline, "log_decision",
                               side_effect=logged.append), \
             mock.patch.object(pipeline, "notify"), \
             mock.patch.object(trace, "emit"), \
             mock.patch.object(stage_route, "fixed_route",
                               return_value=("launch", None)), \
             mock.patch.object(stage_route, "is_low_confidence",
                               return_value=True), \
             mock.patch.object(stage_route, "ambiguous_choices",
                               return_value=[]):
            self.assertFalse(stage_route.route_stage(ctx))
        self.assertEqual(len(logged), 1, logged)
        self.assertEqual(logged[0].get("turn"), "T9")
        self.assertTrue(logged[0]["result"].startswith("CANCELLED"))

    def test_error_line_carries_turn(self):
        rows = self._run(RuntimeError("boom"))
        self.assertEqual(len(rows), 1, rows)
        self.assertTrue(rows[0].get("turn"), rows)
        self.assertTrue(rows[0]["result"].startswith("ERROR"))
