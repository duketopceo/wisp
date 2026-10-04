#!/usr/bin/env python3
"""Learning-loop tests: correction recording, weekly proposals, overrides."""
import json
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import learn  # noqa: E402


def corr(picked="app:retroarch", heard="let's play retro-large",
         days_ago=0):
    return {
        "ts": (datetime.now(timezone.utc)
               - timedelta(days=days_ago)).isoformat(),
        "heard": heard,
        "picked": picked,
        "jev_said": {"app": "retroarch", "route": "launch"},
    }


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


class TestWeekly(unittest.TestCase):
    def test_proposal_from_recent_corrections(self):
        with tempfile.TemporaryDirectory() as td:
            cf = pathlib.Path(td) / "corrections.jsonl"
            cf.write_text("\n".join(json.dumps(c) for c in [
                corr(), corr(heard="fire up retroarch"), corr(days_ago=3)
            ]) + "\n")
            out = learn.weekly(corrections_file=cf,
                               decisions_file=pathlib.Path(td) / "d.jsonl",
                               out_dir=pathlib.Path(td) / "prop")
            self.assertIsNotNone(out)
            body = pathlib.Path(out).read_text()
        self.assertIn("3 corrections", body)
        self.assertIn("retro-large", body)
        self.assertIn("retroarch` chosen 3x", body)

    def test_legacy_dump_rows_ignored(self):
        # pre-record_correction rows were decision dumps ({transcript,
        # answers, result, corrected}) — they carry no user pick
        with tempfile.TemporaryDirectory() as td:
            cf = pathlib.Path(td) / "corrections.jsonl"
            legacy = {"ts": corr()["ts"], "transcript": "open spotify",
                      "answers": {"app": {"choice": "music"}},
                      "result": "LAUNCHED", "corrected": True}
            cf.write_text(json.dumps(legacy) + "\n"
                          + json.dumps(corr()) + "\n")
            out = learn.weekly(corrections_file=cf,
                               decisions_file=pathlib.Path(td) / "d.jsonl",
                               out_dir=pathlib.Path(td) / "prop")
            body = pathlib.Path(out).read_text()
        self.assertIn("1 corrections", body)
        self.assertNotIn("open spotify", body)

    def test_empty_week_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            cf = pathlib.Path(td) / "corrections.jsonl"
            cf.write_text(json.dumps(corr(days_ago=30)) + "\n")
            out = learn.weekly(corrections_file=cf,
                               decisions_file=pathlib.Path(td) / "d.jsonl",
                               out_dir=pathlib.Path(td) / "prop")
        self.assertIsNone(out)

    def test_missing_log_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            out = learn.weekly(corrections_file=pathlib.Path(td) / "c.jsonl",
                               decisions_file=pathlib.Path(td) / "d.jsonl",
                               out_dir=pathlib.Path(td) / "prop")
        self.assertIsNone(out)


class TestOverrides(unittest.TestCase):
    def test_approve_and_apply(self):
        with tempfile.TemporaryDirectory() as td:
            ov = pathlib.Path(td) / "overrides.json"
            learn.approve({"app": {"retroarch": "retro games, retroarch"}},
                          path=ov)
            merged = learn.apply_overrides({"retroarch": "games"},
                                           path=ov)
        self.assertIn("user-corrected", merged["retroarch"])
        self.assertIn("games", merged["retroarch"])

    def test_override_adds_new_app(self):
        with tempfile.TemporaryDirectory() as td:
            ov = pathlib.Path(td) / "overrides.json"
            learn.approve({"app": {"mycmd": "my custom tool"}}, path=ov)
            merged = learn.apply_overrides({}, path=ov)
        self.assertIn("mycmd", merged)


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
