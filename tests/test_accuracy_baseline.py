"""Read-only importer contracts; all input trials are explicitly synthetic."""
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "accuracy_baseline.py"
FIXTURE = ROOT / "tests" / "fixtures" / "accuracy" / "synthetic-trials.jsonl"
IMPORTED_AT = "2026-10-30T12:00:00Z"


def run_import(path=FIXTURE, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(path), "--imported-at",
         IMPORTED_AT, *args], capture_output=True, text=True, cwd=ROOT)


class AccuracyBaseline(unittest.TestCase):
    def test_per_kind_metrics_match_only_supplied_synthetic_rows(self):
        before = FIXTURE.read_bytes()
        result = run_import()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["synthetic"], True)
        rows = {row["kind"]: row for row in report["kinds"]}
        self.assertEqual(rows["synthetic-menu"], {
            "kind": "synthetic-menu", "trials": 2, "acted": 1,
            "aborted": 1, "verified": 1, "verified_rate": 0.5,
            "abort_rate": 0.5, "median_ms": 600.0})
        self.assertEqual(rows["synthetic-field"], {
            "kind": "synthetic-field", "trials": 2, "acted": 1,
            "aborted": 0, "verified": 1, "verified_rate": 0.5,
            "abort_rate": 0.0, "median_ms": 150.0})
        self.assertEqual(report["source"]["sha256"],
                         hashlib.sha256(before).hexdigest())
        self.assertEqual(FIXTURE.read_bytes(), before)

    def test_report_records_dates_and_source_identity(self):
        result = run_import()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report.get("schema"), "wisp.accuracy.baseline.v1")
        self.assertEqual(report["imported_at"], IMPORTED_AT)
        self.assertEqual(report["dataset_id"], "synthetic-import-test")
        self.assertEqual(report["source"]["path"], str(FIXTURE.resolve()))
        self.assertEqual(report["source"]["bytes"], len(FIXTURE.read_bytes()))
        self.assertEqual(report["source"]["collected_on"], "2026-10-01")
        self.assertIn("NOT owner clicklab", report["source"]["source_ref"])
        self.assertEqual(report["source"]["first_trial_at"], "2026-10-01T10:00:00Z")
        self.assertEqual(report["source"]["last_trial_at"], "2026-10-01T10:03:00Z")
        self.assertEqual(report["totals"], {"trials": 4, "tasks": 2})

    def test_worst_kind_ranking_uses_abort_rate_then_median_then_name(self):
        records = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
        for index, (kind, elapsed) in enumerate((
                ("synthetic-z-fast", 200), ("synthetic-b-slow", 900),
                ("synthetic-a-slow", 900)), start=5):
            records.append({**records[1], "trial_id": f"synthetic-{index}",
                            "kind": kind, "elapsed_ms": elapsed})
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / "synthetic-ranking.jsonl"
            source.write_text("".join(json.dumps(r) + "\n" for r in records))
            result = run_import(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report.get("ranking"), [
            "synthetic-a-slow", "synthetic-b-slow", "synthetic-z-fast",
            "synthetic-menu", "synthetic-field"])
        self.assertEqual(report["ranking_rule"],
                         "abort_rate desc, median_ms desc, kind asc")
        self.assertNotIn("top_three_historical", report)

    def test_machine_readable_input_schema_is_available_without_data(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--schema"],
                                capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        schema = json.loads(result.stdout)
        manifest, trial = schema["oneOf"]
        self.assertEqual(manifest["properties"]["schema"]["const"],
                         "wisp.accuracy.trials.v1")
        self.assertIn("synthetic", manifest["required"])
        self.assertIn("recorded_at", trial["required"])
        self.assertEqual(trial["properties"]["outcome"]["enum"],
                         ["acted", "aborted", "not_acted"])
        self.assertFalse(trial["additionalProperties"])

    def test_invalid_schema_never_emits_a_partial_baseline(self):
        original = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
        cases = {
            "missing provenance": [{k: v for k, v in original[0].items()
                                    if k != "source_ref"}, *original[1:]],
            "unmarked synthetic": [{**original[0], "synthetic": "true"},
                                  *original[1:]],
            "unknown format": [{**original[0], "schema": "clicklab-unknown"},
                               *original[1:]],
            "negative latency": [original[0], {**original[1], "elapsed_ms": -1}],
            "boolean latency": [original[0], {**original[1], "elapsed_ms": True}],
            "nonfinite latency": [original[0], {**original[1], "elapsed_ms": float("nan")}],
            "overflow latency": [original[0], {**original[1], "elapsed_ms": 10**400}],
            "unknown outcome": [original[0], {**original[1], "outcome": "success"}],
            "unknown label": [original[0], {**original[1], "verified": "yes"}],
            "contradictory verification": [
                original[0], {**original[1], "verified": True}],
            "extra field": [original[0], {**original[1], "owner_label": "good"}],
            "duplicate trial": [*original, original[1]],
            "missing date": [original[0], {**original[1], "recorded_at": ""}],
            "naive date": [original[0], {**original[1],
                                       "recorded_at": "2026-10-01T10:00:00"}],
            "invalid collection date": [
                {**original[0], "collected_on": "2026-99-99"}, *original[1:]],
            "no trials": [original[0]],
            "second manifest": [*original, original[0]],
            "nonobject row": [original[0], []],
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / "invalid-synthetic.jsonl"
            for name, records in cases.items():
                with self.subTest(name=name):
                    source.write_text("".join(json.dumps(r) + "\n" for r in records))
                    before = source.read_bytes()
                    result = run_import(source)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertEqual(result.stdout, "")
                    self.assertIn("invalid baseline", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertEqual(source.read_bytes(), before)

    def test_time_range_uses_instants_not_timestamp_string_sorting(self):
        records = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
        records[1]["recorded_at"] = "2026-10-01T10:00:00.5Z"
        records[2]["recorded_at"] = "2026-10-01T12:00:00+02:00"
        records = records[:3]
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / "synthetic-timezones.jsonl"
            source.write_text("".join(json.dumps(r) + "\n" for r in records))
            result = run_import(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        provenance = json.loads(result.stdout)["source"]
        self.assertEqual(provenance["first_trial_at"], "2026-10-01T10:00:00Z")
        self.assertEqual(provenance["last_trial_at"], "2026-10-01T10:00:00.500000Z")

    def test_large_finite_pair_has_finite_median_without_traceback(self):
        # Exact reproduced overflow: statistics.median([1e308,1e308]).
        records = [json.loads(line) for line in FIXTURE.read_text().splitlines()][:3]
        for row in records[1:]:
            row["elapsed_ms"] = 1e308
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / "synthetic-finite-overflow.jsonl"
            source.write_text("".join(json.dumps(r) + "\n" for r in records))
            result = run_import(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout, parse_constant=lambda value:
                            self.fail(f"nonfinite JSON value: {value}"))
        self.assertEqual(report["kinds"][0]["median_ms"], 1e308)
