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
import pathlib
import re
from datetime import datetime, timezone

from . import config

FILE = config.DATA_DIR / "trajectories.jsonl"
MAX_BYTES = 2 * 1024 * 1024

_WORDS = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set:
    return set(_WORDS.findall((text or "").lower()))


def _step_out(s: dict, pack=None) -> dict:
    """The persisted form of one step — tool/arg/result plus the U6
    verdict fields (R5) when the step carries them: `verdict`,
    `verify_source` (the rung that minted it), `corroborated`,
    `turn_dir`, `pack`. In-memory steps get source/corroboration from
    the ladder's `verify` dict; old rows and read-only steps simply
    have none of these keys."""
    out = {"tool": s.get("tool"), "arg": s.get("arg", "")[:80],
           "result": s.get("result", "")[:80]}
    vd = s.get("verify")
    vd = vd if isinstance(vd, dict) else {}
    if s.get("verdict") is not None:
        out["verdict"] = str(s["verdict"])[:24]
    src = s.get("verify_source") or vd.get("source")
    if src:
        out["verify_source"] = str(src)[:24]
    corr = s.get("corroborated")
    if corr is None:
        corr = vd.get("corroborated")
    if corr is not None:
        out["corroborated"] = bool(corr)
    if "turn_dir" in s:          # explicit null persists — the step
        td = s.get("turn_dir")   # was recording-eligible
        # F15: persist the evidence dir NAME, never the absolute rec/
        # path — a trajectory is durable training data and a host path
        # would leak the machine's $HOME layout
        out["turn_dir"] = pathlib.Path(str(td)).name if td else None
    p = s.get("pack") or pack
    if p:
        out["pack"] = pathlib.Path(str(p)).name
    return out


def record(task: str, app: str, steps: list, outcome: str,
           ref: str = "", surface: str = "", pack=None) -> None:
    """Append one act-run trajectory. Rotates FILE at MAX_BYTES.
    `surface` tags the interaction substrate (browser-dom, desktop) so
    per-surface training stats and skills stay separate. `pack` is the
    turn's capture-pack dir when U4 wrote one — stamped onto each step
    that doesn't already name its own."""
    rec = {"ts": datetime.now(timezone.utc).isoformat(),
           "task": task, "app": app, "surface": surface,
           "steps": [_step_out(s, pack=pack) for s in steps],
           "outcome": outcome[:200], "ref": ref}
    if pack:
        rec["pack"] = pathlib.Path(str(pack)).name   # F15: name only
    try:
        FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            size = FILE.stat().st_size
        except OSError:
            size = 0
        if size > MAX_BYTES:
            FILE.replace(FILE.with_suffix(".jsonl.1"))
        with FILE.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def _read_all(path=None) -> list:
    from . import learn
    return learn._read_jsonl(path or FILE)


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
        r["outcome_failed"] = out.startswith(("ABORTED", "SKIP", "ERROR"))
        # U6: the step verdicts outrank the outcome string — a run that
        # reported ACTED but whose last action corroborated-missed is a
        # failed branch (the FilmCraft ~70px miss); a single-source
        # terminal miss only makes it suspect (R2a down-weight).
        # not_recorded/legacy tails say nothing — outcome still governs.
        tb, _w = _terminal(r)
        r["verified_miss"] = tb == "missed"
        r["suspect_miss"] = tb == "missed_solo"
        r["failed"] = r["outcome_failed"] or r["verified_miss"]
        lab = (labs.get(r.get("ts")) or labs.get(r.get("ref") or "")
               or labs.get("task:" + r.get("task", ""), ""))
        r["corrected"] = lab == "incorrect"
        scored.append((score, r))
    scored.sort(key=lambda s: -s[0])
    return [r for _, r in scored[:k]]


def _terminal(rec: dict) -> tuple:
    """(bucket, weight) of the run's last outcome-bearing verdict —
    learn.terminal_evidence, shared policy."""
    from . import learn
    return learn.terminal_evidence(rec.get("steps") or [])


def _fmt_steps(steps: list, limit: int = 8) -> str:
    return " → ".join(f"{s.get('tool')} {s.get('arg', '')[:24]}".rstrip()
                      for s in steps[:limit])


def context_for(task: str, app: str = "", cfg: dict | None = None,
                records: list | None = None,
                labels: dict | None = None) -> str:
    """Episodic context block for the act system prompt, or ''."""
    if (cfg or {}).get("traj", {}).get("enabled", "true") != "true":
        return ""
    k = int((cfg or {}).get("traj", {}).get("max_inject", "3"))
    priors = similar(task, app, k=k, records=records, labels=labels)
    if not priors:
        return ""
    lines = ["Prior attempts at this or similar tasks:"]
    for r in priors:
        steps = _fmt_steps(r.get("steps", []))
        if r["failed"] or r["corrected"]:
            why = r['outcome'][:60]
            if r.get("verified_miss") and not r.get("outcome_failed"):
                why = f"reported {why} but last action verified missed"
            lines.append(
                f"- FAILED run ({why}): {steps or 'no steps'}"
                " — do not repeat this branch")
        elif r.get("suspect_miss"):
            lines.append(
                f"- prior success: {steps or 'no steps'} — caution:"
                " final action missed (single-source, unverified)")
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
        # a corroborated terminal miss is label-grade failure evidence
        # even under an ACTED outcome — never distill it as a success.
        # (single-source misses and not_recorded tails stay eligible:
        # weak/absent evidence, not a failure.)
        if _terminal(r)[0] == "missed":
            continue
        key = _task_key(r)
        prior_bad = [p for p in recs[:i]
                     if p.get("app") == key[0]
                     and _related(_task_key(p)[1], key[1])
                     and (p.get("outcome", "").startswith(
                          ("ABORTED", "SKIP", "ERROR"))
                          or _lab(p) == "incorrect"
                          or (_lab(p) != "correct"
                              and _terminal(p)[0] == "missed"))]
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
