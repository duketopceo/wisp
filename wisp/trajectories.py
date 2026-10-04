"""Episodic act-loop memory — trajectories recorded, retrieved, distilled.

Every act run appends {ts, task, app, steps, outcome} to
trajectories.jsonl (rotated like activity.jsonl). At act start,
similar prior runs (token-overlap + app match, top-k) are injected
into the system prompt: successful paths as hints, failed/corrected
runs as explicit wrong-branch cautions — "avoid X; the working path
was Y". Turn labels (labels.jsonl ✓/✗) join by ts ref to mark a
trajectory corrected.

Distillation: a task with ≥1 failed run followed by a success is a
learned workflow — `propose_recipes()` drafts a recipe-* skill into
proposals/; `wispd recipes approve` installs it (human-gated, same
contract as learn.py criteria proposals).
"""
import json
import re
from datetime import datetime, timezone

from . import config

FILE = config.DATA_DIR / "trajectories.jsonl"
MAX_BYTES = 2 * 1024 * 1024

_WORDS = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set:
    return set(_WORDS.findall((text or "").lower()))


def record(task: str, app: str, steps: list, outcome: str,
           ref: str = "", surface: str = "") -> None:
    """Append one act-run trajectory. Rotates FILE at MAX_BYTES.
    `surface` tags the interaction substrate (browser-dom, desktop) so
    per-surface training stats and skills stay separate."""
    rec = {"ts": datetime.now(timezone.utc).isoformat(),
           "task": task, "app": app, "surface": surface,
           "steps": [{"tool": s.get("tool"), "arg": s.get("arg", "")[:80],
                      "result": s.get("result", "")[:80]}
                     for s in steps],
           "outcome": outcome[:200], "ref": ref}
    try:
        FILE.parent.mkdir(parents=True, exist_ok=True)
        if FILE.exists() and FILE.stat().st_size > MAX_BYTES:
            FILE.replace(FILE.with_suffix(".jsonl.1"))
        with FILE.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def _read_all(path=None) -> list:
    path = path or FILE
    try:
        return [json.loads(l) for l in path.read_text().splitlines()
                if l.strip()]
    except OSError:
        return []


def _labels() -> dict:
    """lookup keys → 'correct'|'incorrect' (last label wins per ref).

    Labels key on the *decision* ts; trajectories have their own ts,
    so the ts join never matches in production. Bridge: resolve each
    label's ref → its decisions.jsonl transcript, and also emit
    'task:<transcript>' keys — an act turn's trajectory `task` is the
    same text."""
    from . import learn
    out = {}
    labs = [l for l in learn._read_jsonl(learn.LABELS_FILE)
            if l.get("ref")]
    if not labs:
        return out
    # ref ts → transcript, from decisions.jsonl
    from . import config as _c
    transcripts = {}
    try:
        for line in _c.DECISIONS.read_text().splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            if d.get("ts") and d.get("transcript"):
                transcripts[d["ts"]] = d["transcript"]
    except (OSError, ValueError):
        pass
    for lab in labs:
        ref = lab["ref"]
        out[ref] = lab.get("label", "")
        if ref in transcripts:
            out["task:" + transcripts[ref]] = lab.get("label", "")
    return out


def similar(task: str, app: str = "", k: int = 3,
            labels: dict | None = None, records: list | None = None) -> list:
    """Top-k prior trajectories for this task, scored by token overlap
    + app match. Each returned record gains `failed`/`corrected`."""
    recs = _read_all() if records is None else records
    labs = _labels() if labels is None else labels
    toks = _tokens(task)
    if not toks:
        return []
    scored = []
    for r in recs:
        overlap = len(toks & _tokens(r.get("task", "")))
        score = overlap + (1 if app and r.get("app") == app else 0)
        if score <= 0:
            continue
        r = dict(r)
        out = r.get("outcome", "")
        r["failed"] = out.startswith(("ABORTED", "SKIP", "ERROR"))
        lab = (labs.get(r.get("ts")) or labs.get(r.get("ref") or "")
               or labs.get("task:" + r.get("task", ""), ""))
        r["corrected"] = lab == "incorrect"
        scored.append((score, r))
    scored.sort(key=lambda s: -s[0])
    return [r for _, r in scored[:k]]


def _fmt_steps(steps: list, limit: int = 8) -> str:
    return " → ".join(f"{s.get('tool')} {s.get('arg', '')[:24]}".rstrip()
                      for s in steps[:limit])


def context_for(task: str, app: str = "", cfg: dict | None = None) -> str:
    """Episodic context block for the act system prompt, or ''."""
    if (cfg or {}).get("traj", {}).get("enabled", "true") != "true":
        return ""
    k = int((cfg or {}).get("traj", {}).get("max_inject", "3"))
    priors = similar(task, app, k=k)
    if not priors:
        return ""
    lines = ["Prior attempts at this or similar tasks:"]
    for r in priors:
        steps = _fmt_steps(r.get("steps", []))
        if r["failed"] or r["corrected"]:
            lines.append(
                f"- FAILED run ({r['outcome'][:60]}): {steps or 'no steps'}"
                " — do not repeat this branch")
        else:
            lines.append(f"- prior success: {steps or 'no steps'}")
    return "\n".join(lines)


def _task_key(rec: dict) -> tuple:
    return (rec.get("app", ""), frozenset(_tokens(rec.get("task", ""))))


def _related(a: frozenset, b: frozenset) -> bool:
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= 0.5


def propose_recipes(out_dir=None) -> list:
    """Draft recipe-* skills for tasks with failure(s) then a success.
    Returns proposal file paths. Never installs — approve via wispd."""
    from . import learn
    out_dir = out_dir or learn.PROPOSALS_DIR
    recs = _read_all()
    labs = _labels()
    drafted = []
    def _lab(rec):
        return (labs.get(rec.get("ts")) or labs.get(rec.get("ref") or "")
                or labs.get("task:" + rec.get("task", ""), ""))

    for i, r in enumerate(recs):
        if r.get("outcome", "").startswith(("ABORTED", "SKIP", "ERROR")):
            continue
        if _lab(r) == "incorrect":
            continue  # user says it failed even if it reported ACTED
        key = _task_key(r)
        prior_bad = [p for p in recs[:i]
                     if p.get("app") == key[0]
                     and _related(_task_key(p)[1], key[1])
                     and (p.get("outcome", "").startswith(
                          ("ABORTED", "SKIP", "ERROR"))
                          or _lab(p) == "incorrect")]
        # graduation: a labeled-correct multi-step success drafts even
        # with no prior failures — the user confirmed the workflow
        verified = (_lab(r) == "correct"
                    and len(r.get("steps", [])) >= 3)
        if not prior_bad and not verified:
            continue
        slug = re.sub(r"[^a-z0-9]+", "-",
                      (r.get("app") or "task") + "-" +
                      "-".join(sorted(key[1])[:4]))[:48].strip("-")
        name = f"recipe-{slug}"
        path = out_dir / f"{name}.md"
        steps = "\n".join(
            f"{n}. `{s.get('tool')} {s.get('arg','')}`"
            for n, s in enumerate(r.get("steps", []), 1))
        bad = "\n".join(f"- {p.get('outcome','')[:60]}: "
                        f"{_fmt_steps(p.get('steps', []), 4)}"
                        for p in prior_bad[-3:])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"---\nname: {name}\ndescription: verified workflow for "
            f"'{r.get('task','')}' on {r.get('app','?')}\ntier: safe\n"
            f"provenance: distilled-from {r.get('ts','')} app="
            f"{r.get('app','?')} priors={len(prior_bad)}\n"
            f"---\n\n# Recipe: {r.get('task','')}\n\n"
            + (f"Verified sequence (after {len(prior_bad)} failed "
               f"attempt(s)):\n\n{steps}\n\n## Wrong branches to avoid\n\n"
               f"{bad}\n" if prior_bad else
               "Verified sequence (user-labeled correct):\n\n"
               f"{steps}\n"))
        drafted.append(str(path))
    return drafted
