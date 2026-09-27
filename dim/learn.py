"""Weekly learning loop: corrections -> staged criteria proposals.

Every clarify-widget pick is logged to corrections.jsonl by the pipeline.
`weekly()` aggregates a week of corrections plus low-confidence decisions
into a human-reviewable proposal; `approve()` merges approved criteria
overrides into ~/.config/dim-agent/criteria_overrides.json, which
build_questions applies on top of the catalog. Nothing auto-applies —
the loop is human-gated by design.
"""
import json
from datetime import datetime, timedelta, timezone

from . import config

OVERRIDES_FILE = config.CFG_DIR / "criteria_overrides.json"
PROPOSALS_DIR = config.DATA_DIR / "proposals"


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


def weekly(days: int = 7, corrections_file=config.CORRECTIONS,
           decisions_file=config.DECISIONS,
           out_dir=PROPOSALS_DIR) -> str | None:
    """Aggregate the last `days` of corrections into a proposal file.
    Returns the proposal path, or None when there is nothing to propose."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = []
    for rec in _read_jsonl(corrections_file):
        try:
            ts = datetime.fromisoformat(rec["ts"])
        except (KeyError, ValueError):
            continue
        if ts >= cutoff:
            recent.append(rec)
    if not recent:
        return None

    counts = {}
    for rec in recent:
        key = rec.get("picked", "")
        counts[key] = counts.get(key, 0) + 1

    iso_year, iso_week, _ = datetime.now(timezone.utc).isocalendar()
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{iso_year}-W{iso_week:02d}.md"
    lines = [
        f"# Dim learning proposal — {iso_year}-W{iso_week:02d}",
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
    out.write_text("\n".join(lines) + "\n")
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
