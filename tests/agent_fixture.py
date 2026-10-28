#!/usr/bin/env python3
"""A stand-in coding agent for the install runbook (B20).

Reads the ```runbook block of docs/INSTALL.md and does what the prompt tells
a real agent to do: run every `agent` step, stop at every `user` step. All
`wispd` calls run with a throwaway HOME and runtime dir, from a copy-free
checkout, so nothing on the real machine is touched. Prints one line per step
and exits 0 only when every agent step exited with an expected code.

    python3 tests/agent_fixture.py [--list]
"""
import os
import pathlib
import re
import shlex
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
INSTALL = ROOT / "docs" / "INSTALL.md"
STEP = re.compile(r"^(agent|user)\s+(.*?)\s*(?:#\s*(.*))?$")


def runbook(text=None):
    text = text if text is not None else INSTALL.read_text("utf-8")
    m = re.search(r"```runbook\n(.*?)```", text, re.S)
    if not m:
        raise SystemExit("no runbook block in docs/INSTALL.md")
    steps = []
    for ln in m.group(1).splitlines():
        if not ln.strip():
            continue
        s = STEP.match(ln.strip())
        if not s:
            raise SystemExit(f"bad runbook line: {ln!r}")
        who, cmd, note = s.group(1), s.group(2), s.group(3) or ""
        ok = [int(x) for x in re.findall(r"exit (\d+)(?: or (\d+))?", note)
              for x in x if x] or [0]
        steps.append({"who": who, "cmd": cmd, "note": note, "ok": ok})
    return steps


def main(argv) -> int:
    steps = runbook()
    if "--list" in argv:
        for s in steps:
            print(f"{s['who']:5} {s['cmd']}")
        return 0
    bad = 0
    with tempfile.TemporaryDirectory() as td:
        home = pathlib.Path(td)
        (home / "run").mkdir()
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(home), "XDG_RUNTIME_DIR": str(home / "run"),
               "LANG": "C.UTF-8", "NO_COLOR": "1"}
        for s in steps:
            if s["who"] == "user":
                print(f"STOP  ask the user: {s['cmd']}")
                continue
            argv_ = shlex.split(s["cmd"])
            r = subprocess.run([sys.executable] + argv_[1:], cwd=ROOT,
                               env=env, capture_output=True, text=True,
                               timeout=120) if argv_[0] == "python3" else None
            if r is None:
                print(f"FAIL  not a python3 wispd step: {s['cmd']}")
                bad += 1
                continue
            good = r.returncode in s["ok"]
            print(f"{'ok  ' if good else 'FAIL'}  exit {r.returncode}  "
                  f"{s['cmd']}")
            bad += 0 if good else 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
