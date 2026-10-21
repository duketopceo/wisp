"""Action-level learning — per-(app, tool) outcome rates aggregated
from trajectories.jsonl. Injected into the act-loop system prompt as a
'what works here' block so the planner biases toward proven actions and
away from tools that keep failing in this app.

This is the honest version of RL over actions: credit assignment over
logged steps, not weight updates.

U6: steps now carry verify-ladder verdicts, and dispatch success is no
longer scored — "CLICKED" that missed is a miss, not an ok. Buckets
(learn.step_bucket owns the mapping): landed | missed (each split into
a `*_solo` single-source variant — R2a down-weight, reported
separately) | refused | unverifiable | suppressed | not_recorded |
legacy. Rows from before verdicts existed are `legacy`: counted, but
never minted `landed`.
"""
import json
from collections import Counter

from . import config

TRAJECTORIES = config.DATA_DIR / "trajectories.jsonl"
_FAIL = ("FAIL", "ERROR", "REFUSED", "SKIPPED", "BLOCKED", "denied")
_NO_SIGNAL = ("refused", "unverifiable", "suppressed", "not_recorded")


def _load(path=None) -> list:
    p = path or TRAJECTORIES
    try:
        return [json.loads(l) for l in p.read_text().splitlines()
                if l.strip()]
    except OSError:
        return []


def stats(path=None, records: list | None = None) -> dict:
    """{app: {tool: {bucket: n}}} — verdict-bucketed step counts plus
    `legacy_ok`, the pre-verdict dispatch heuristic kept so legacy-only
    tools still render a rate."""
    from . import learn
    out = {}
    for t in (_load(path) if records is None else records):
        app = (t.get("app") or "_unknown").lower()
        for s in t.get("steps") or []:
            tool = s.get("tool", "?")
            b = learn.step_bucket(s)
            cell = out.setdefault(app, {}).setdefault(tool, Counter())
            cell[b] += 1
            if b == learn.LEGACY \
                    and not str(s.get("result", "")).startswith(_FAIL):
                cell["legacy_ok"] += 1
    return out


def block_for(app: str, path=None, records: list | None = None) -> str:
    """'[what works in godot] click 4/5, launch 3/3; suspect: shell 0/4'
    — empty string when the app is unrecorded.

    Verdicted tools score landed/(landed+missed) — solo verdicts count
    in the display but weigh SOLO_WEIGHT in the suspect test, and are
    flagged `(N solo)`. Legacy-only tools keep the old dispatch-rate
    display (they're all this store had). Steps that produced no
    outcome evidence surface under `unverified:` so a tool that keeps
    landing `not_recorded` doesn't silently read as working."""
    from . import learn
    solo_w = learn.SOLO_WEIGHT
    app = (app or "_unknown").lower()
    by_app = stats(path, records=records)
    tools = by_app.get(app) or by_app.get("_unknown")
    if not tools:
        return ""
    good, suspect, unv = [], [], []
    for tool, b in sorted(tools.items(),
                          key=lambda kv: -sum(
                              v for k, v in kv[1].items()
                              if k != "legacy_ok")):
        landed = b.get("landed", 0) + b.get("landed_solo", 0)
        missed = b.get("missed", 0) + b.get("missed_solo", 0)
        vd = landed + missed
        legacy = b.get("legacy", 0)
        nosig = sum(b.get(k, 0) for k in _NO_SIGNAL)
        if vd:
            solo = b.get("landed_solo", 0) + b.get("missed_solo", 0)
            ok_w = b.get("landed", 0) + solo_w * b.get("landed_solo", 0)
            n_w = ok_w + b.get("missed", 0) \
                + solo_w * b.get("missed_solo", 0)
            txt = f"{tool} {landed}/{vd}" \
                + (f" ({solo} solo)" if solo else "")
            (suspect if vd >= 3 and ok_w / n_w < 0.4
             else good).append(txt)
        elif legacy:
            ok = b.get("legacy_ok", 0)
            (suspect if legacy >= 3 and ok / legacy < 0.4
             else good).append(f"{tool} {ok}/{legacy}")
        if nosig:
            unv.append(f"{tool}×{nosig}")
    bits = ", ".join(good)
    if suspect:
        bits += ("; " if bits else "") + "suspect: " + ", ".join(suspect)
    if unv:
        bits += ("; " if bits else "") \
            + "unverified: " + ", ".join(unv)
    return f"[what works in {app}] {bits}"
