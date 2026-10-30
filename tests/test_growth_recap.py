"""B31 private recap: fixtures only; all network and subprocesses forbidden."""
import importlib
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "growth"
NOW = datetime(2026, 10, 30, 12, tzinfo=timezone(timedelta(hours=-6)))
ON = {"growth": {"weekly_recap": "true"}}


class GrowthRecapTest(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket", "urllib.request.urlopen", "subprocess.run"):
            blocker = patch(target, side_effect=AssertionError("recap must stay local"))
            blocker.start()
            self.addCleanup(blocker.stop)

    def test_private_recap_reports_last_complete_local_week(self):
        self.assertTrue((ROOT / "wisp" / "growth.py").exists(),
                        "private weekly recap is missing")
        growth = importlib.import_module("wisp.growth")
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            for name in ("decisions.jsonl", "usage.jsonl"):
                shutil.copyfile(FIXTURES / name, data / name)
            with patch("socket.socket", side_effect=AssertionError("no network")), \
                 patch("urllib.request.urlopen", side_effect=AssertionError("no HTTP")), \
                 patch("subprocess.run", side_effect=AssertionError("no process")):
                result = growth.weekly_recap(ON, now=NOW, data_dir=data)
            self.assertEqual(result["reason"], "ready")
            card = result["card"]
            self.assertEqual(card["week_start"], "2026-10-19")
            self.assertEqual(card["week_end"], "2026-10-25")
            self.assertEqual(card["days_used"], 5)
            self.assertEqual(card["turns"], 6)
            self.assertEqual(card["spend"]["recorded_usd"], 0.83)
            self.assertIsNone(card["spend"]["measured_usd"])
            self.assertIsNone(card["spend"]["estimated_usd"])
            self.assertEqual(card["spend"]["basis"], "source_not_recorded")
            self.assertIn("may include estimates", card["spend_note"])
            self.assertEqual(sorted(p.name for p in data.iterdir()),
                             ["decisions.jsonl", "usage.jsonl"])

    def test_off_by_default_never_reads_logs_or_creates_state(self):
        growth = importlib.import_module("wisp.growth")
        with tempfile.TemporaryDirectory() as d:
            absent = Path(d) / "not-created"
            with patch.object(Path, "read_text", side_effect=AssertionError("no log read")):
                for cfg in ({}, {"growth": {"weekly_recap": "false"}},
                            {"growth": {"weekly_recap": "yes"}}):
                    result = growth.weekly_recap(cfg, now=NOW, data_dir=absent)
                    self.assertFalse(result["enabled"])
                    self.assertEqual(result["reason"], "disabled")
                    self.assertIsNone(result["card"])
            self.assertFalse(absent.exists())

    def test_claim_is_deduplicated_by_completed_week(self):
        growth = importlib.import_module("wisp.growth")
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            for name in ("decisions.jsonl", "usage.jsonl"):
                shutil.copyfile(FIXTURES / name, data / name)
            with (data / "decisions.jsonl").open("a") as stream:
                stream.write('{"ts":"2026-10-26T09:00:00-06:00"}\n')
            first = growth.weekly_recap(ON, now=NOW, data_dir=data, claim=True)
            repeated = growth.weekly_recap(ON, now=NOW, data_dir=data, claim=True)
            self.assertEqual(first["reason"], "ready")
            self.assertEqual(repeated["reason"], "already_seen")
            self.assertIsNone(repeated["card"])
            self.assertIsNone(growth.weekly_recap(ON, now=NOW, data_dir=data)["card"])
            marker = data / "recap-weeks" / "2026-10-19.json"
            self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(marker.read_text())["week_start"], "2026-10-19")
            following = growth.weekly_recap(
                ON, now=NOW + timedelta(days=7), data_dir=data, claim=True)
            self.assertEqual(following["card"]["week_start"], "2026-10-26")
            self.assertEqual(following["card"]["turns"], 1)

    def test_missing_logs_do_not_invent_zero_spend_or_claim_delivery(self):
        growth = importlib.import_module("wisp.growth")
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            result = growth.weekly_recap(ON, now=NOW, data_dir=data, claim=True)
            self.assertEqual(result["reason"], "no_activity")
            self.assertIsNone(result["card"])
            self.assertEqual(result["logs"]["decisions"]["state"], "missing")
            self.assertFalse((data / "recap-weeks").exists())
            shutil.copyfile(FIXTURES / "decisions.jsonl", data / "decisions.jsonl")
            result = growth.weekly_recap(ON, now=NOW, data_dir=data)
            self.assertEqual(result["logs"]["usage"]["state"], "missing")
            self.assertIsNone(result["card"]["spend"]["recorded_usd"])
            self.assertIn("spend unavailable", result["card"]["summary"])

    def test_local_monday_boundaries_include_naive_ledger_timestamps(self):
        growth = importlib.import_module("wisp.growth")
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            times = [
                "2026-10-19T05:59:59+00:00",  # previous Sunday, excluded
                "2026-10-19T06:00:00+00:00",  # Monday midnight, included
                "2026-10-26T05:59:59+00:00",  # Sunday 23:59, included
                "2026-10-26T06:00:00+00:00",  # following Monday, excluded
                "2026-10-19T00:00:00",        # naive local Monday, included
            ]
            (data / "decisions.jsonl").write_text(
                "".join(json.dumps({"ts": ts}) + "\n" for ts in times))
            (data / "usage.jsonl").write_text(
                "".join(json.dumps({"ts": ts, "usd": 0.1}) + "\n" for ts in times))
            card = growth.weekly_recap(ON, now=NOW, data_dir=data)["card"]
            self.assertEqual(card["turns"], 3)
            self.assertEqual(card["days_used"], 2)
            self.assertEqual(card["spend"]["recorded_usd"], 0.3)

    def test_malformed_logs_are_explicitly_partial(self):
        growth = importlib.import_module("wisp.growth")
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            (data / "decisions.jsonl").write_text(
                '{"ts":"2026-10-20T12:00:00-06:00"}\n'
                'broken-json\n[]\n{"ts":null}\n')
            (data / "usage.jsonl").write_text(
                '{"ts":"2026-10-20T12:00:00","usd":0.5}\n'
                '{"ts":"bad-time","usd":0.5}\n'
                '{"ts":"2026-10-20T12:00:00","usd":"NaN"}\n'
                '{"ts":"2026-10-20T12:00:00"}\n')
            result = growth.weekly_recap(ON, now=NOW, data_dir=data)
            self.assertEqual(result["card"]["turns"], 1)
            self.assertEqual(result["card"]["spend"]["recorded_usd"], 0.5)
            self.assertFalse(result["card"]["spend"]["complete"])
            self.assertIn("partial", result["card"]["summary"])
            self.assertIn("partial", result["card"]["activity_note"])
            self.assertEqual(result["logs"]["decisions"],
                             {"state": "partial", "skipped": 3})
            self.assertEqual(result["logs"]["usage"],
                             {"state": "partial", "skipped": 3})

    def test_unreadable_logs_and_state_fail_without_delivering_a_card(self):
        growth = importlib.import_module("wisp.growth")
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            (data / "decisions.jsonl").write_bytes(b"\xff")
            result = growth.weekly_recap(ON, now=NOW, data_dir=data, claim=True)
            self.assertEqual(result["logs"]["decisions"]["state"], "unreadable")
            self.assertIsNone(result["card"])
            shutil.copyfile(FIXTURES / "decisions.jsonl", data / "decisions.jsonl")
            with patch("wisp.growth.os.open", side_effect=PermissionError("private-path")):
                result = growth.weekly_recap(ON, now=NOW, data_dir=data, claim=True)
            self.assertEqual(result["reason"], "state_unavailable")
            self.assertIsNone(result["card"])

    def test_cli_claim_and_off_work_without_a_daemon(self):
        from wisp import cli, config, growth

        def run(*args):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(["recap", *args, "--json"])
            self.assertEqual(code, 0, err.getvalue() or out.getvalue())
            result = json.loads(out.getvalue())["data"]
            self.assertEqual(set(result), {"enabled", "reason", "card", "logs"})
            self.assertIsInstance(result["logs"], dict)
            return result

        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            cfg_dir = data / "cfg"
            cfg_dir.mkdir()
            cfg_file = cfg_dir / "config.toml"
            cfg_file.write_text('[growth]\nweekly_recap = "true"\n')
            for name in ("decisions.jsonl", "usage.jsonl"):
                shutil.copyfile(FIXTURES / name, data / name)
            with patch.object(config, "DATA_DIR", data), \
                 patch.object(config, "CFG_DIR", cfg_dir), \
                 patch.object(config, "CFG_FILE", cfg_file), \
                 patch.object(growth, "datetime", wraps=datetime) as clock:
                clock.now.return_value = NOW
                self.assertEqual(run()["card"]["turns"], 6)
                self.assertFalse((data / "recap-weeks").exists())
                self.assertEqual(run("--claim")["card"]["turns"], 6)
                self.assertEqual(run("--claim")["reason"], "already_seen")
                self.assertIsNone(run("--off")["card"])
                self.assertIn('weekly_recap = "false"', cfg_file.read_text())
                self.assertEqual(run()["reason"], "disabled")

    def test_cli_default_off_does_not_bootstrap_config(self):
        from wisp import cli, config
        with tempfile.TemporaryDirectory() as d:
            cfg_file = Path(d) / "not-created.toml"
            with patch.object(config, "CFG_FILE", cfg_file), \
                 contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(cli.main(["recap", "--json"]), 0)
            self.assertEqual(json.loads(out.getvalue())["data"]["reason"], "disabled")
            self.assertFalse(cfg_file.exists())

    def test_legacy_ledger_costs_are_included_without_rewriting_logs(self):
        growth = importlib.import_module("wisp.growth")
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            shutil.copyfile(FIXTURES / "decisions.jsonl", data / "decisions.jsonl")
            legacy = data / "spend.jsonl"
            content = json.dumps({
                "ts": datetime(2026, 10, 20, 12, tzinfo=timezone.utc).timestamp(),
                "cost": 0.2, "model": "fixture",
            }) + "\n"
            legacy.write_text(content)
            result = growth.weekly_recap(ON, now=NOW, data_dir=data)
            self.assertEqual(result["card"]["spend"]["recorded_usd"], 0.2)
            self.assertEqual(result["logs"]["legacy_usage"]["state"], "ok")
            shutil.copyfile(FIXTURES / "usage.jsonl", data / "usage.jsonl")
            result = growth.weekly_recap(ON, now=NOW, data_dir=data)
            self.assertEqual(result["card"]["spend"]["recorded_usd"], 1.03)
            self.assertEqual(legacy.read_text(), content)

    def test_unknown_legacy_costs_are_not_silently_coerced_to_zero(self):
        from wisp import growth
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            shutil.copyfile(FIXTURES / "decisions.jsonl", data / "decisions.jsonl")
            ts = datetime(2026, 10, 20, 12, tzinfo=timezone.utc).timestamp()
            (data / "spend.jsonl").write_text(
                json.dumps({"ts": ts, "cost": "unknown"}) + "\n"
                + json.dumps({"ts": ts}) + "\n")
            result = growth.weekly_recap(ON, now=NOW, data_dir=data)
            self.assertIsNone(result["card"]["spend"]["recorded_usd"])
            self.assertEqual(result["logs"]["legacy_usage"],
                             {"state": "partial", "skipped": 2})
