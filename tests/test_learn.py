#!/usr/bin/env python3
"""Learning-loop tests: correction recording, weekly proposals, overrides."""
import json
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from dim import learn  # noqa: E402


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
