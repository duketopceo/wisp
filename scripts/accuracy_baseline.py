#!/usr/bin/env python3
"""Read normalized accuracy trials and print a report; never edit the input."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

_TEXT = {"type": "string", "minLength": 1}
_MANIFEST = {
    "record_type": {"const": "manifest"},
    "schema": {"const": "wisp.accuracy.trials.v1"},
    "dataset_id": _TEXT, "synthetic": {"type": "boolean"},
    "collected_on": {"type": "string", "format": "date"},
    "source_ref": _TEXT,
}
_TRIAL = {
    "record_type": {"const": "trial"}, "trial_id": _TEXT,
    "task_id": _TEXT, "kind": _TEXT,
    "outcome": {"enum": ["acted", "aborted", "not_acted"]},
    "verified": {"type": ["boolean", "null"]},
    "elapsed_ms": {"type": "number", "minimum": 0},
    "recorded_at": {"type": "string", "format": "date-time"},
}
INPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Wisp normalized accuracy JSONL record (manifest then trials)",
    "oneOf": [
        {"type": "object", "properties": fields, "required": list(fields),
         "additionalProperties": False}
        for fields in (_MANIFEST, _TRIAL)],
}


def _timestamp(value: str) -> str:
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("timestamps must have a timezone")
    return stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_record(row, fields: dict, line: int) -> None:
    """Validate the small exported record schema without extra dependencies."""
    if not isinstance(row, dict) or row.keys() != fields.keys():
        raise ValueError(f"line {line}: expected exactly {', '.join(fields)}")
    for name, spec in fields.items():
        value = row[name]
        invalid = ("const" in spec and value != spec["const"]) \
            or ("enum" in spec and value not in spec["enum"])
        kind = spec.get("type")
        if kind == "string":
            invalid |= not isinstance(value, str) or not value.strip()
        elif kind == "boolean":
            invalid |= type(value) is not bool
        elif kind == ["boolean", "null"]:
            invalid |= value is not None and type(value) is not bool
        elif kind == "number":
            invalid |= type(value) not in (int, float)
            if not invalid:
                invalid |= not math.isfinite(value) or value < 0
        if invalid:
            raise ValueError(f"line {line}: invalid {name}")
        if spec.get("format") == "date":
            date.fromisoformat(value)
        elif spec.get("format") == "date-time":
            row[name] = _timestamp(value)


def import_baseline(path: Path, imported_at: str) -> dict:
    raw = path.read_bytes()
    records = []
    for line_no, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        _validate_record(row, _MANIFEST if not records else _TRIAL, line_no)
        records.append(row)
    if len(records) < 2:
        raise ValueError("one manifest and at least one trial required")
    manifest, trials = records[0], records[1:]
    seen = set()
    for row in trials:
        if row["trial_id"] in seen:
            raise ValueError(f"duplicate trial_id: {row['trial_id']}")
        seen.add(row["trial_id"])
        if row["verified"] is True and row["outcome"] != "acted":
            raise ValueError("verified=true requires outcome=acted")
    imported_at = _timestamp(imported_at)
    kinds = []
    for kind in sorted({row["kind"] for row in trials}):
        rows = [row for row in trials if row["kind"] == kind]
        count = len(rows)
        acted = sum(row["outcome"] == "acted" for row in rows)
        aborted = sum(row["outcome"] == "aborted" for row in rows)
        verified = sum(row["verified"] is True for row in rows)
        times = sorted(row["elapsed_ms"] for row in rows)
        low, high = times[(count - 1) // 2], times[count // 2]
        # Latencies are nonnegative: this midpoint cannot overflow like
        # (low + high) / 2 when both finite values approach float limits.
        median_ms = low + (high - low) / 2
        kinds.append({
            "kind": kind, "trials": count, "acted": acted,
            "aborted": aborted, "verified": verified,
            "verified_rate": verified / count,
            "abort_rate": aborted / count,
            "median_ms": median_ms})
    timestamps = sorted((row["recorded_at"] for row in trials),
                        key=datetime.fromisoformat)
    return {"schema": "wisp.accuracy.baseline.v1",
            "synthetic": manifest["synthetic"],
            "dataset_id": manifest["dataset_id"],
            "imported_at": imported_at,
            "source": {"path": str(path.resolve()), "bytes": len(raw),
                       "schema": manifest["schema"],
                       "sha256": hashlib.sha256(raw).hexdigest(),
                       "collected_on": manifest["collected_on"],
                       "source_ref": manifest["source_ref"],
                       "first_trial_at": timestamps[0],
                       "last_trial_at": timestamps[-1]},
            "totals": {"trials": len(trials),
                       "tasks": len({row["task_id"] for row in trials})},
            "ranking_rule": "abort_rate desc, median_ms desc, kind asc",
            "ranking": [row["kind"] for row in sorted(
                kinds, key=lambda row: (-row["abort_rate"],
                                        -row["median_ms"], row["kind"]))],
            "kinds": kinds}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="?")
    parser.add_argument("--imported-at")
    parser.add_argument("--schema", action="store_true",
                        help="print JSON Schema for each input JSONL record")
    args = parser.parse_args(argv)
    if args.schema:
        print(json.dumps(INPUT_SCHEMA, indent=2, sort_keys=True))
        return 0
    if args.source is None or args.imported_at is None:
        parser.error("source and --imported-at are required for import")
    try:
        report = import_baseline(args.source, args.imported_at)
        rendered = json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
    except (OSError, ValueError, OverflowError) as error:
        parser.error(f"invalid baseline: {error}")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
