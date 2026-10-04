"""Weekly learning loop: corrections -> staged criteria proposals.

Every clarify-widget pick is logged to corrections.jsonl by the pipeline.
`weekly()` aggregates a week of corrections plus low-confidence decisions
into a human-reviewable proposal; `approve()` merges approved criteria
overrides into ~/.config/wisp/criteria_overrides.json, which
build_questions applies on top of the catalog. Nothing auto-applies —
the loop is human-gated by design.
"""
import json
from datetime import datetime, timedelta, timezone

from . import config

OVERRIDES_FILE = config.CFG_DIR / "criteria_overrides.json"
PROPOSALS_DIR = config.DATA_DIR / "proposals"
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


def _last_decision(decisions_file=config.DECISIONS) -> dict | None:
    recs = _read_jsonl(decisions_file)
    return recs[-1] if recs else None


def _last_label(labels_file=LABELS_FILE) -> dict | None:
    recs = _read_jsonl(labels_file)
    return recs[-1] if recs else None


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


def load_overrides(path=OVERRIDES_FILE) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


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


def recent(days: int = 7, corrections_file=config.CORRECTIONS) -> list:
    """Corrections from the last `days` that carry a pick."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for rec in _read_jsonl(corrections_file):
        try:
            ts = datetime.fromisoformat(rec["ts"])
        except (KeyError, ValueError):
            continue
        if ts >= cutoff and rec.get("picked"):
            out.append(rec)
    return out


def weekly(days: int = 7, corrections_file=config.CORRECTIONS,
           decisions_file=config.DECISIONS,
           out_dir=PROPOSALS_DIR) -> str | None:
    """Aggregate the last `days` of corrections into a proposal file.
    Returns the proposal path, or None when there is nothing to propose."""
    recent_recs = recent(days, corrections_file)
    if not recent_recs:
        return None
    return _write_weekly(recent_recs, days, out_dir)


def _write_weekly(recent, days, out_dir):
    counts = {}
    for rec in recent:
        key = rec["picked"]
        counts[key] = counts.get(key, 0) + 1

    iso_year, iso_week, _ = datetime.now(timezone.utc).isocalendar()
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{iso_year}-W{iso_week:02d}.md"
    lines = [
        f"# Wisp learning proposal — {iso_year}-W{iso_week:02d}",
        "",
        f"{len(recent)} corrections in the last {days} days.",
        "",
        "## Picks",
        "",
    ]
    for rec in recent:
        lines.append(
            f"- heard {rec.get('heard')!r} → picked `{rec.get('picked')}`"
            f" (jev said app={rec.get('jev_said', {}).get('app')})")
    lines += ["", "## Suggested criteria emphasis", ""]
    for pick, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        kind, _, value = pick.partition(":")
        lines.append(
            f"- `{value}` chosen {n}x — strengthen its criteria text or "
            f"add the heard phrases as cues (approve to apply)")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(out)


def approve(overrides: dict, path=OVERRIDES_FILE) -> None:
    """Merge human-approved criteria overrides (never auto-applied)."""
    cur = load_overrides(path)
    cur.setdefault("app", {}).update(overrides.get("app", {}))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cur, indent=2))


def apply_overrides(criteria: dict, path=OVERRIDES_FILE) -> dict:
    """build_questions hook: overlay approved criteria text onto a catalog."""
    o = load_overrides(path).get("app", {})
    merged = dict(criteria)
    for name, cue in o.items():
        if name in merged:
            merged[name] = f"{merged[name]} | user-corrected: {cue}"
        else:
            merged[name] = f"user-corrected: {cue}"
    return merged
