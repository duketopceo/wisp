#!/usr/bin/env python3
"""Weekly self-improving router proposal — reads data/corrections.jsonl and
clusters user corrections into proposed new choice criteria.

Usage: python3 scripts/propose_criteria.py [path/to/corrections.jsonl]
Default path: $XDG_DATA_HOME/dim-agent/corrections.jsonl (~/.local/share/dim-agent/).
Output: a human-readable proposal report on stdout. NOT scheduled by cron yet
(documented workflow: run manually, review, then edit JEV_QUESTIONS in dimd).
"""
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

default_path = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "dim-agent" / "corrections.jsonl"


def load(path: Path):
    rows = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else default_path
    rows = load(path)
    if not rows:
        print(f"no decisions logged yet at {path}")
        return 0
    print(f"decisions: {len(rows)}")
    corrected = [r for r in rows if r.get("corrected")]
    print(f"user corrections: {len(corrected)}")
    blocked = [r for r in rows if (r.get("result") or "").startswith("BLOCKED")]
    print(f"risk-blocked: {len(blocked)}")

    confusion = defaultdict(Counter)
    for r in corrected:
        a = r.get("answers", {})
        picked = a.get("app", {}).get("choice")
        confusions = [
            (k, v) for k, v in a.get("app", {}).get("probabilities", {}).items() if k != picked
        ]
        if confusions:
            confusion[picked].update([k for k, _ in confusions])

    print("\nproposed criteria refinements:")
    for picked, others in confusion.items():
        for other, n in others.most_common(2):
            if n >= 2:
                print(f"  - app '{picked}' vs '{other}' confused {n}x — "
                      f"add a distinguishing criterion description in dimd JEV_QUESTIONS")
    if not confusion:
        print("  (no repeated confusion clusters — nothing to propose)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
