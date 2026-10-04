"""Reviewer tier — an async batch pass over failed or inefficient
trajectories that produces human-gated proposals.

The reviewer is a slower, decider-class model reading step logs (text,
not pixels). Its output is NEVER auto-applied: proposals land in
review_proposals.jsonl; `wispd review` lists them; `wispd review
approve N` copies a skill/counterfactual into the bank as `candidate`
(still must earn `graduated` on streak + efficiency like any pattern).
Per the Cheap Verifiers warning in the gauntlet research — rejected
reviewer output distills nothing back into the actor.

Reviewer provider: `[brain] reviewer = "name:model"` picks a configured
provider; absent that, the brain default is used.
"""
import json
import re
import time

from . import brain, config, train

PROPOSALS = config.DATA_DIR / "review_proposals.jsonl"

_EFF_FLOOR = 0.67  # runs below this are worth a second look

_PROMPT = """You are reviewing a GUI-agent trajectory that underperformed.
Read the steps and the verdict, then propose corrections.

TASK: {task}
VERIFIED RESULT: {verified}
AGENT VERDICT: {verdict}
JUDGE: waste={waste} first_fault_step={first_fault} efficiency={eff}
FLAKE CLASS: {flake}

STEPS (numbered):
{steps}

Reply with ONLY a JSON object, no prose:
{{"first_fault": <0-indexed step number or -1>,
  "why": "<one sentence: what went wrong>",
  "counterfactual": [<the step sequence that SHOULD have run, same
     shape as steps>],
  "skill": {{"name": "<short slug>", "when": "<one-line trigger
     condition>", "steps": [<minimal reusable steps>]}} | null,
  "confidence": <0.0-1.0>}}"""


def _reviewer_cfg(cfg: dict) -> dict:
    """`[brain] reviewer = "name:model"` overrides the provider for
    this pass only — falls back to the brain default."""
    rev = (cfg.get("brain") or {}).get("reviewer", "")
    if not rev:
        return cfg
    c = dict(cfg)
    c["brain"] = {**(cfg.get("brain") or {}), "default": rev}
    return c


def _candidates(limit: int) -> list:
    """Recent records worth a second look: verified failures, genuine
    model-flake fails, or inefficient passes."""
    recs = [r for r in train._load_jsonl(train.RESULTS)
            if r.get("verified") is False
            or r.get("flake") == "model"
            or (isinstance(r.get("efficiency"), (int, float))
                and r["efficiency"] < _EFF_FLOOR)]
    return recs[-limit:]


def _extract_json(text: str) -> dict | None:
    """Pull the first {...} object out of a chatty reply."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _fmt_steps(steps: list) -> str:
    return "\n".join(
        f"{i}. {s.get('tool')}({s.get('arg', '')}) → {s.get('result')}"
        for i, s in enumerate(steps)) or "(no steps)"


def run(cfg: dict, limit: int = 10) -> dict:
    """Batch-review recent underperforming records. Returns
    {reviewed, proposed, skipped, notes[]}. Never raises on a single
    bad record — the batch continues."""
    recs = _candidates(limit)
    rcfg = _reviewer_cfg(cfg)
    out = {"reviewed": 0, "proposed": 0, "skipped": 0, "notes": []}
    PROPOSALS.parent.mkdir(parents=True, exist_ok=True)
    with PROPOSALS.open("a") as f:
        for rec in recs:
            out["reviewed"] += 1
            j = rec.get("judge") or {}
            prompt = _PROMPT.format(
                task=rec.get("task"),
                verified="PASS" if rec.get("verified") else "FAIL",
                verdict=str(rec.get("verdict"))[:300],
                waste=j.get("waste", "?"),
                first_fault=j.get("first_fault", -1),
                eff=(f"{rec['efficiency']:.2f}"
                     if isinstance(rec.get("efficiency"), (int, float))
                     else "?"),
                flake=rec.get("flake", "?"),
                steps=_fmt_steps(rec.get("steps") or []))
            try:
                resp = brain.chat([{"role": "user", "content": prompt}],
                                  rcfg, timeout=120)
            except Exception as e:
                out["skipped"] += 1
                out["notes"].append(
                    f"reviewer call failed: {str(e)[:80]}")
                continue
            prop = _extract_json(resp.get("content", ""))
            if not isinstance(prop, dict):
                out["skipped"] += 1
                out["notes"].append(
                    f"malformed reply for '{rec.get('task', '')[:40]}'")
                continue
            prop.update({"ts": time.time(), "task": rec.get("task"),
                         "model": rec.get("model") or "",
                         "surface": rec.get("surface") or "unknown",
                         "status": "staged"})
            f.write(json.dumps(prop) + "\n")
            out["proposed"] += 1
    return out


def _proposals() -> list:
    return train._load_jsonl(PROPOSALS)


def list_text() -> str:
    props = _proposals()
    staged = [p for p in props if p.get("status") == "staged"]
    if not staged:
        return "nothing staged — run `wispd review run` after a batch"
    lines = []
    for i, p in enumerate(staged, 1):
        cf = len(p.get("counterfactual") or [])
        sk = (p.get("skill") or {}).get("name", "-")
        conf = p.get("confidence")
        c = f" conf={conf:.2f}" if isinstance(conf, (int, float)) else ""
        lines.append(f"{i}. [{p.get('model') or '?'}] "
                     f"{str(p.get('task'))[:46]}\n"
                     f"   why: {str(p.get('why'))[:72]}\n"
                     f"   counterfactual: {cf} steps · skill: {sk}{c}")
    return "\n".join(lines)


def approve(n: int) -> str:
    """Copy proposal N's counterfactual (or skill steps) into the bank
    as a `candidate` — never graduated; it earns that on real runs."""
    staged = [p for p in _proposals() if p.get("status") == "staged"]
    if not 1 <= n <= len(staged):
        return f"no staged proposal #{n} ({len(staged)} staged)"
    p = staged[n - 1]
    steps = p.get("counterfactual") or (p.get("skill") or {}).get("steps")
    if not steps:
        return f"proposal #{n} has no steps to promote"
    key = "|".join([p.get("surface") or "unknown", "_",
                    (p.get("task") or "").strip().lower(),
                    p.get("model") or ""])
    bank = train.load_bank()
    bank[key] = {"key": key, "task": p.get("task"),
                 "surface": p.get("surface") or "unknown", "app": "",
                 "model": p.get("model") or "",
                 "streak": 0, "streak_eff": [], "runs": 0,
                 "eff_sum": 0.0, "status": "candidate",
                 "steps": steps[:24], "history": [],
                 "source": "reviewer"}
    train.save_bank(bank)
    # mark the proposal approved in-place
    props, seen = _proposals(), 0
    for i, q in enumerate(props):
        if q.get("status") == "staged":
            seen += 1
            if seen == n:
                props[i]["status"] = "approved"
    PROPOSALS.write_text("".join(json.dumps(q) + "\n" for q in props))
    return f"approved #{n} → bank candidate '{key}'"


def reject(n: int) -> str:
    staged = [p for p in _proposals() if p.get("status") == "staged"]
    if not 1 <= n <= len(staged):
        return f"no staged proposal #{n} ({len(staged)} staged)"
    props, seen = _proposals(), 0
    for i, q in enumerate(props):
        if q.get("status") == "staged":
            seen += 1
            if seen == n:
                props[i]["status"] = "rejected"
    PROPOSALS.write_text("".join(json.dumps(q) + "\n" for q in props))
    return f"rejected #{n} — nothing distilled"
