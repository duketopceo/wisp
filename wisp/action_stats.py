"""Action-level learning — per-(app, tool) success rates aggregated
from trajectories.jsonl. Injected into the act-loop system prompt as a
'what works here' block so the planner biases toward proven actions and
away from tools that keep failing in this app.

This is the honest version of RL over actions: credit assignment over
logged steps, not weight updates.
"""
import json
from collections import Counter

from . import config

TRAJECTORIES = config.DATA_DIR / "trajectories.jsonl"
_FAIL = ("FAIL", "ERROR", "REFUSED", "SKIPPED", "BLOCKED", "denied")


def _load(path=None) -> list:
    p = path or TRAJECTORIES
    try:
        return [json.loads(l) for l in p.read_text().splitlines()
                if l.strip()]
    except OSError:
        return []


def stats(path=None) -> dict:
    """{app: {tool: [ok, n]}}"""
    out = {}
    for t in _load(path):
        app = (t.get("app") or "_unknown").lower()
        for s in t.get("steps") or []:
            tool = s.get("tool", "?")
            ok = not str(s.get("result", "")).startswith(_FAIL)
            out.setdefault(app, {}).setdefault(tool, [0, 0])
            out[app][tool][0] += ok
            out[app][tool][1] += 1
    return out


def block_for(app: str, path=None) -> str:
    """'[what works in godot] click 4/5, launch 3/3; suspect: shell 0/4'
    — empty string when the app is unrecorded."""
    app = (app or "_unknown").lower()
    tools = stats(path).get(app) or stats(path).get("_unknown")
    if not tools:
        return ""
    good, suspect = [], []
    for tool, (ok, n) in sorted(tools.items(), key=lambda kv: -kv[1][1]):
        if n >= 3 and ok / n < 0.4:
            suspect.append(f"{tool} {ok}/{n}")
        else:
            good.append(f"{tool} {ok}/{n}")
    bits = ", ".join(good)
    if suspect:
        bits += ("; " if bits else "") + "suspect: " + ", ".join(suspect)
    return f"[what works in {app}] {bits}"
