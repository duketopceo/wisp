#!/usr/bin/env python3
"""Replay one turn fixture through the real pipeline and print a timeline.

    python scripts/replay_turn.py tests/fixtures/turns/ask.json
    python scripts/replay_turn.py ask            # short name also works
    python scripts/replay_turn.py ask --json     # machine-readable

Fake model servers run on 127.0.0.1 ephemeral ports; nothing leaves
loopback and the live wispd/model services are never touched. Exit
status is non-zero when the fixture's `expect` block is not met.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from harness import runner  # noqa: E402


def main(argv: list) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    target = args[0]
    path = pathlib.Path(target)
    if not path.exists():
        path = runner.FIXTURE_DIR / (target if target.endswith(".json")
                                     else target + ".json")
    res = runner.run_turn(path)
    problems = runner.check_expectations(res)
    if "--json" in argv:
        print(json.dumps({"statuses": res.statuses, "final": res.final,
                          "spans": res.spans, "problems": problems,
                          "violations": res.violations}, indent=2))
        return 1 if problems or res.violations else 0
    print(f"fixture {res.fixture}: {path}")
    for t_ms, label in res.timeline():
        print(f"{t_ms:>7} ms  {label}")
    print(f"statuses : {' > '.join(res.statuses)}")
    print(f"transcript: {res.final.get('transcript')!r}")
    print(f"answer   : {res.final.get('answer')}")
    print(f"result   : {res.final.get('result')!r}")
    if res.final.get("error"):
        print(f"error    : {res.final['error']}")
    print(f"spans    : {res.spans}")
    if res.launch_calls:
        print(f"launches : {res.launch_calls} (stubbed)")
    if res.violations:
        print(f"NETWORK VIOLATIONS: {res.violations}")
    if res.exit_code != 0:
        print(res.stderr, file=sys.stderr)
    for p in problems:
        print(f"EXPECT FAIL: {p}")
    print("expectations: " + ("FAIL" if problems else "ok"))
    return 1 if problems or res.violations else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
