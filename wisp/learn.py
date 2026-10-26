"""Learning helpers: the correct/incorrect label store, correction and
retry context, the fails report, and verdict-weighted trajectory evidence.

Every clarify-widget pick is logged to corrections.jsonl by the pipeline
(`record_correction`); recall re-indexes that file on rebuild.
"""
import json
from datetime import datetime, timezone

from . import config

LABELS_FILE = config.DATA_DIR / "labels.jsonl"


def label_last(label: str, note: str = "") -> str:
    """Tag the most recent decisions.jsonl turn correct/incorrect —
    the soak's intent-match metric reads labels.jsonl keyed by `ref`."""
    label = {"ok": "correct", "good": "correct",
             "bad": "incorrect"}.get(label, label)
    if label not in ("correct", "incorrect"):
        return "SKIP (label must be correct|incorrect)"
    try:
        last = ""
        with config.DECISIONS.open() as f:
            for line in f:
                if line.strip():
                    last = line
        if not last:
            return "nothing to label"
        ref = json.loads(last).get("ts", "")
    except OSError:
        return "nothing to label"
    rec = {"ts": datetime.now(timezone.utc).isoformat(),
           "ref": ref, "label": label, "note": note}
    try:
        LABELS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LABELS_FILE.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError as e:
        return f"ERROR ({e})"
    return f"labeled {label}: {ref}"


def soak_stats() -> str:
    """Per-route intent-match from labels.jsonl joined to
    decisions.jsonl on ts — the v1.0 soak metric (≥85% per route)."""
    decs = {d.get("ts"): d for d in _read_jsonl(config.DECISIONS)}
    by_ref = {}
    for lab in _read_jsonl(LABELS_FILE):
        if lab.get("ref"):
            by_ref[lab["ref"]] = lab.get("label", "")
    per_route = {}
    for ref, lab in by_ref.items():
        route = ((decs.get(ref) or {}).get("answers", {})
                 .get("route", {}) or {}).get("choice", "?")
        ok, tot = per_route.get(route, (0, 0))
        per_route[route] = (ok + (lab == "correct"), tot + 1)
    if not per_route:
        return "no labels yet — use `wispd label correct|incorrect`"
    lines, (ok_all, tot_all) = [], (0, 0)
    for route, (ok, tot) in sorted(per_route.items()):
        lines.append(f"  {route:<10} {ok}/{tot} correct "
                     f"({100 * ok / tot:.0f}%)")
        ok_all, tot_all = ok_all + ok, tot_all + tot
    lines.append(f"  {'total':<10} {ok_all}/{tot_all} "
                 f"({100 * ok_all / tot_all:.0f}%) — gate: 85%")
    return "soak intent-match:\n" + "\n".join(lines)


_CUES = ("no", "nope", "wrong", "that's wrong", "didn't work",
         "didnt work", "actually", "instead", "not that", "try again")


def _last_jsonl(path, window: int = 65536) -> dict | None:
    """Last record only — tail-read so correction_context stays O(1)
    on unbounded decision/label logs."""
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - window))
            lines = f.read().decode("utf-8", "replace").splitlines()
        if size > window:
            lines = lines[1:]  # partial first line
        for line in reversed(lines):
            line = line.strip()
            if line:
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        # nothing parsed — the last record may exceed the window;
        # fall back to the full read rather than return a stale row
        if size > window:
            recs = _read_jsonl(path)
            return recs[-1] if recs else None
    except OSError:
        pass
    return None


def _last_decision(decisions_file=config.DECISIONS) -> dict | None:
    return _last_jsonl(decisions_file)


def _last_label(labels_file=LABELS_FILE) -> dict | None:
    return _last_jsonl(labels_file)


def correction_context(text: str, cfg: dict) -> dict | None:
    """Detect a correction turn: the user labeling the last run bad and
    speaking again, or opening with a cue phrase ('no', 'didn't work',
    'instead'...). Returns {prior_task, prior_route, prior_result} to
    inject, or None."""
    if cfg.get("dev", {}).get("refine", "true") != "true":
        return None
    dec = _last_decision()
    if not dec:
        return None
    lab = _last_label()
    labeled_bad = bool(lab) and lab.get("label") == "incorrect" \
        and lab.get("ref") == dec.get("ts")
    low = (text or "").lower().strip()
    cued = any(low == c or low[:len(c) + 1].rstrip(" ,.:;!-") == c
               for c in _CUES) and len(low) > 3
    if not (labeled_bad or cued):
        return None
    return {
        "prior_task": dec.get("transcript", ""),
        "prior_route": (dec.get("answers", {}).get("route", {})
                        or {}).get("choice", "?"),
        "prior_result": dec.get("result", ""),
        "prior_ref": dec.get("ts", ""),
        "via": "label" if labeled_bad else "cue",
    }


def record_retry(prior_ref: str, result: str) -> None:
    """Join a correction turn's outcome back to the failed run — the
    fails report reads 'corrected-by-retry' as fixed or unfixed."""
    if not prior_ref:
        return
    rec = {"ts": datetime.now(timezone.utc).isoformat(),
           "ref": prior_ref, "label": "corrected-by-retry",
           "note": result[:120]}
    try:
        LABELS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LABELS_FILE.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def fails(n: int = 10, decisions_file=config.DECISIONS,
          labels_file=LABELS_FILE) -> str:
    """Recent failures and whether a correction retry fixed them."""
    decs = _read_jsonl(decisions_file)
    labs = _read_jsonl(labels_file)
    marked_bad, retries = set(), {}
    for l in labs:
        ref = l.get("ref")
        if not ref:
            continue
        if l.get("label") == "incorrect":
            marked_bad.add(ref)
        elif l.get("label") == "corrected-by-retry":
            retries[ref] = l
        elif l.get("label") == "correct":
            marked_bad.discard(ref)
    rows = []
    for d in reversed(decs):
        res = d.get("result", "")
        ref = d.get("ts", "")
        bad = ref in marked_bad or res.startswith(
            ("ABORTED", "BLOCKED", "ERROR", "CANCELLED"))
        if not bad:
            continue
        retry = retries.get(ref)
        if retry:
            note = retry.get("note", "")
            status = ("unfixed" if note.startswith(
                ("ABORTED", "BLOCKED", "ERROR", "CANCELLED", "SKIP"))
                else "fixed")
        else:
            status = "no retry"
        rows.append(f"  {ref[11:19]} {status:<9} "
                    f"{(d.get('transcript') or '')[:36]!r:<40} "
                    f"{res[:40]}")
        if len(rows) >= n:
            break
    if not rows:
        return "no failures logged"
    return "fails (recent first):\n" + "\n".join(rows)


def _read_jsonl(path) -> list:
    try:
        return [json.loads(l) for l in path.read_text().splitlines()
                if l.strip()]
    except OSError:
        return []


def record_correction(transcript: str, picked: str, answers: dict,
                      corrections_file=config.CORRECTIONS) -> None:
    try:
        corrections_file.parent.mkdir(parents=True, exist_ok=True)
        with corrections_file.open("a") as f:
            f.write(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "heard": transcript,
                "picked": picked,
                "jev_said": {
                    "app": answers.get("app", {}).get("choice"),
                    "route": answers.get("route", {}).get("choice"),
                },
            }) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------
# verdict-weighted trajectory evidence (U6 — R2a symmetric down-weight,
# R5 real-outcome scoring)
# ---------------------------------------------------------------------
#
# Every mutating act step now carries a verdict the ladder produced
# (landed|missed|refused|unverifiable|suppressed|not_recorded) plus the
# rung that minted it (verify_source) and a corroboration flag. Learning
# consumes verdicts, not dispatch success — "CLICKED" that missed must
# never read as a success. The canonical mapping lives here so every
# consumer (action_stats, trajectories, the bank fold) agrees:
#
#   landed/missed, two+ rungs or judge-confirmed -> full weight
#   landed/missed, one rung only ("_solo")       -> SOLO_WEIGHT (R2a:
#       a lone pixel diff does not prove either direction)
#   refused/unverifiable/suppressed/not_recorded -> 0 — no outcome
#       evidence; neither failure nor success
#   no verdict at all (pre-U6 rows, read-only tools) -> "legacy" — the
#       dispatch-only era; counted separately, NEVER as landed.

LEGACY = "legacy"
SOLO_WEIGHT = 0.5
_OUTCOME = ("landed", "missed")
_NO_SIGNAL = frozenset(
    {"refused", "unverifiable", "suppressed", "not_recorded"})


def _corroborated(step: dict):
    """The step's corroboration flag: persisted rows carry it flat,
    in-memory act steps carry the ladder's `verify` dict."""
    corr = step.get("corroborated")
    if corr is None:
        vd = step.get("verify")
        if isinstance(vd, dict):
            corr = vd.get("corroborated")
    return corr


def step_bucket(step: dict) -> str:
    """Canonical evidence bucket for one trajectory step:
    landed|missed split by corroboration (`_solo` = single rung),
    refused|unverifiable|suppressed|not_recorded pass through, anything
    without verdict data is `legacy`."""
    v = str(step.get("verdict") or "").strip().lower()
    if v in _OUTCOME:
        return v if _corroborated(step) is True else v + "_solo"
    if v in _NO_SIGNAL:
        return v
    return LEGACY


def terminal_evidence(steps: list) -> tuple:
    """(bucket, weight) of the LAST outcome-bearing step — the run's
    verified tail. (None, 0.0) when nothing produced a landed/missed
    verdict: the tail's truth is then unknown, NOT a failure."""
    for s in reversed(steps or []):
        b = step_bucket(s)
        if b in _OUTCOME or b.endswith("_solo"):
            return b, 1.0 if b in _OUTCOME else SOLO_WEIGHT
    return None, 0.0
