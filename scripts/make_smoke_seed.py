#!/usr/bin/env python3
"""Smoke seed generator: N synthetic examples for the pre-training smoke run."""
import json
import random
import sys
from pathlib import Path

APPS = ["browser", "terminal", "files", "vscode", "music", "settings"]
ACTIONS = ["launch", "close", "type_text", "run_shell"]


def synth(n: int) -> list[dict]:
    rows = []
    for i in range(n):
        app = random.choice(APPS)
        action = random.choice(ACTIONS) if i % 3 else "launch"
        state = {
            "utterance": f"please {action} {app}" if random.random() < 0.8 else f"{app} {action} now",
            "focused_app": random.choice(APPS),
            "hour": random.randint(0, 23),
        }
        answer = {
            "choice": app if action == "launch" else None,
            "belief": None,
            "score": 0 if action == "launch" else 1,
        }
        rows.append({"state": state, "answer": answer})
    return rows


def main(n: int) -> int:
    random.seed(7)
    out = Path("data/seed/smoke.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        for ex in synth(n):
            f.write(json.dumps(ex) + "\n")
    for line in out.read_text().splitlines():
        rec = json.loads(line)
        assert rec["answer"]["choice"] in APPS or rec["answer"]["choice"] is None
    print(f"smoke seed valid: {n} examples -> {out}")
    return 0


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    sys.exit(main(n))
