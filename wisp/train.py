"""Training arena — behavior-loop improvement over logged runs.

Reads every judged run (clicklab results + act trajectories), buckets
them by surface/app, tracks streaks, and maintains the skill bank:
task patterns that auto-graduate once proven (streak>=3, mean
efficiency>=0.9) and demote when they regress. No weight training —
this is credit assignment and recipe distillation over logs.
"""
import json
from datetime import datetime, timezone

from . import config

RESULTS = config.DATA_DIR / "clicklab.jsonl"
TRAJECTORIES = config.DATA_DIR / "trajectories.jsonl"
BANK_FILE = config.DATA_DIR / "skillbank.json"

GRAD_STREAK = 3          # consecutive verified+judge-ok runs
GRAD_EFFICIENCY = 0.9    # mean efficiency floor
DEMOTE_EFFICIENCY = 0.5  # a graduated pattern scoring below this drops


def _load_jsonl(path) -> list:
    try:
        return [json.loads(l) for l in path.read_text().splitlines()
                if l.strip()]
    except OSError:
        return []


def load_bank(path=None) -> dict:
    """{key: entry} — key = surface|app|task."""
    try:
        return json.loads((path or BANK_FILE).read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_bank(bank: dict, path=None) -> None:
    p = path or BANK_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(bank, indent=1, sort_keys=True))


def _key(rec: dict) -> str:
    parts = [rec.get("surface") or "unknown",
             (rec.get("app") or "").lower() or "_",
             (rec.get("task") or "").strip().lower()]
    if rec.get("model"):
        parts.append(str(rec["model"]))
    return "|".join(parts)


_ENV_HINTS = ("mcp", "browseros", "unreachable", "connection",
              "timeout", "timed out", "screenshot", "grim", "no page",
              "refused")
_STALL_HINTS = ("abort", "stall", "max ", "interrupt", "timeout")


def classify_flake(rec: dict) -> str:
    """Label a run's failure mode: env flake, judge false negative,
    timing flake, genuine model failure, or none. Pure heuristics —
    honest about not being a second judge."""
    j = rec.get("judge") or {}
    steps = rec.get("steps") or []
    if rec.get("verified") is True and j.get("success") is False:
        return "judge_fn"
    if rec.get("verified") is not False:
        return "none"
    results = [str(s.get("result") or "").lower() for s in steps]
    if steps and all(r.startswith("error") for r in results):
        return "env"
    if any(h in r for r in results for h in _ENV_HINTS):
        return "env"
    v = str(rec.get("verdict") or "").lower()
    if len(steps) <= 2 and any(h in v for h in _STALL_HINTS):
        return "timing"
    return "model"


def _run_ok(rec: dict) -> bool:
    """Ground truth wins; Jev reconciles. A run counts toward a streak
    only when the verifier passed and the judge didn't dissent."""
    j = rec.get("judge") or {}
    if rec.get("verified") is False:
        return False
    if j.get("success") is False:
        return False
    return bool(rec.get("verified"))


def update_bank(rec: dict, path=None) -> dict:
    """Fold one judged run into the skill bank. Returns the entry."""
    bank = load_bank(path)
    k = _key(rec)
    e = _fold(bank.get(k), rec)
    bank[k] = e
    save_bank(bank, path)
    return e


def replay_all(path=None) -> dict:
    """Rebuild the bank from clicklab.jsonl + trajectories — idempotent."""
    bank = {}
    p = path or BANK_FILE
    for rec in _load_jsonl(RESULTS):
        bank[_key(rec)] = _fold(bank.get(_key(rec)), rec)
    save_bank(bank, p)
    return bank


def _fold(e: dict | None, rec: dict) -> dict:
    """Fold one judged run into an entry — pure, no file I/O.
    Graduation judges the current streak's efficiency window (a past
    failure shouldn't make re-graduation impossible); demotion uses the
    same window plus any verified failure."""
    j = rec.get("judge") or {}
    e = e or {"key": _key(rec), "task": rec.get("task"),
              "surface": rec.get("surface"),
              "app": rec.get("app") or "",
              "model": rec.get("model") or "",
              "streak": 0, "streak_eff": [], "runs": 0,
              "eff_sum": 0.0,
              "status": "candidate", "steps": [], "history": []}
    ok = _run_ok(rec)
    eff = rec.get("efficiency")
    if not isinstance(eff, (int, float)):
        eff = j.get("efficiency")
    e["runs"] += 1
    if isinstance(eff, (int, float)):
        e["eff_sum"] += eff
    if ok:
        e["streak"] += 1
        if isinstance(eff, (int, float)):
            e["streak_eff"].append(eff)
    else:
        e["streak"] = 0
        e["streak_eff"] = []
    e["history"].append({"ts": rec.get("ts"), "ok": ok,
                         "eff": eff,
                         "waste": j.get("waste")})
    e["history"] = e["history"][-50:]
    prev = e["status"]
    win = e["streak_eff"]
    win_mean = sum(win) / len(win) if len(win) >= GRAD_STREAK else 0.0
    if e["status"] == "graduated" and (
            not ok or (win and win_mean < DEMOTE_EFFICIENCY)):
        e["status"] = "demoted"
        e["demoted_at"] = datetime.now(timezone.utc).isoformat()
    elif e["status"] != "graduated" and e["streak"] >= GRAD_STREAK \
            and win_mean >= GRAD_EFFICIENCY:
        e["status"] = "graduated"
        e["graduated_at"] = \
            datetime.now(timezone.utc).isoformat()
    e["changed"] = e["status"] != prev
    if ok and rec.get("steps"):
        e["steps"] = rec["steps"][:24]
    if rec.get("check"):
        e["check"] = rec["check"]
    return e


def stats() -> dict:
    """Arena roll-up: per-surface/per-model pass rates + efficiency,
    pass^k reliability, waste + flake histograms, bank status."""
    recs = _load_jsonl(RESULTS)
    surfaces: dict = {}
    models: dict = {}
    reliability: dict = {}
    flakes: dict = {}
    waste = {}
    for r in recs:
        surf = r.get("surface") or "unknown"
        b = surfaces.setdefault(surf, {"runs": 0, "verified": 0,
                                       "eff_sum": 0.0, "eff_n": 0})
        b["runs"] += 1
        b["verified"] += bool(r.get("verified"))
        e = r.get("efficiency")
        if not isinstance(e, (int, float)):
            e = (r.get("judge") or {}).get("efficiency")
        if isinstance(e, (int, float)):
            b["eff_sum"] += e
            b["eff_n"] += 1
        w = (r.get("judge") or {}).get("waste")
        if w and w != "none":
            waste[w] = waste.get(w, 0) + 1
        mdl = r.get("model")
        if mdl:
            mb = models.setdefault(mdl, {"runs": 0, "verified": 0,
                                         "ms_sum": 0})
            mb["runs"] += 1
            mb["verified"] += bool(r.get("verified"))
            mb["ms_sum"] += r.get("ms") or 0
        rk = "|".join([r.get("surface") or "?",
                       (r.get("task") or "").strip().lower(),
                       r.get("model") or ""])
        rb = reliability.setdefault(rk, {"task": r.get("task") or "",
                                         "surface":
                                         r.get("surface") or "?",
                                         "model": r.get("model") or "",
                                         "runs": 0, "verified": 0})
        rb["runs"] += 1
        rb["verified"] += bool(r.get("verified"))
        fk = r.get("flake") or classify_flake(r)
        if fk != "none":
            flakes[fk] = flakes.get(fk, 0) + 1
    bank = load_bank()
    bank_status = {}
    for e in bank.values():
        bank_status[e["status"]] = bank_status.get(e["status"], 0) + 1
    return {"runs": len(recs),
            "reliability": [
                {"task": v["task"], "surface": v["surface"],
                 "model": v["model"], "runs": v["runs"],
                 "pass": v["verified"],
                 "pass_rate": round(v["verified"] / v["runs"], 3)}
                for v in sorted(reliability.values(),
                                key=lambda x: (x["verified"] / x["runs"],
                                               -x["runs"]))
                if v["runs"] >= 2],
            "flakes": flakes,
            "models": {k: {"runs": v["runs"], "pass": v["verified"],
                           "avg_ms": round(v["ms_sum"] / v["runs"])
                           if v["runs"] else None}
                       for k, v in models.items()},
            "surfaces": {
                k: {"runs": v["runs"], "pass": v["verified"],
                    "efficiency": round(v["eff_sum"] / v["eff_n"], 3)
                    if v["eff_n"] else None}
                for k, v in surfaces.items()},
            "waste": waste, "bank": bank_status}


def stats_text() -> str:
    s = stats()
    lines = [f"runs: {s['runs']}"]
    for surf, v in sorted(s["surfaces"].items()):
        eff = f" eff={v['efficiency']}" if v["efficiency"] is not None \
            else ""
        lines.append(f"  {surf}: {v['pass']}/{v['runs']} verified{eff}")
    if s["waste"]:
        lines.append("waste: " + ", ".join(
            f"{k}×{v}" for k, v in sorted(s["waste"].items(),
                                          key=lambda kv: -kv[1])))
    if s["bank"]:
        lines.append("bank: " + ", ".join(
            f"{k}={v}" for k, v in sorted(s["bank"].items())))
    return "\n".join(lines)


def history_text(limit: int = 30) -> str:
    recs = _load_jsonl(RESULTS)[-limit:]
    lines = []
    for r in recs:
        j = r.get("judge") or {}
        ok = "PASS" if r.get("verified") else "FAIL"
        eff = j.get("efficiency")
        e = f" eff={eff:.2f}" if isinstance(e, (int, float)) else ""
        w = j.get("waste")
        lines.append(f"{ok} {r.get('surface', '?'):<11} "
                     f"{r.get('task', '')[:52]}{e}"
                     + (f" waste={w}" if w and w != "none" else ""))
    return "\n".join(lines) or "no runs yet"


def hint_for(task: str, surface: str, app: str = "",
             model: str = "") -> str:
    """Proven-sequence hint for the act system prompt — only graduated
    patterns on this surface. Prefers the model-keyed entry when
    `model` is set, falls back to unkeyed. Returns '' when nothing
    applies."""
    bank = load_bank()
    t = (task or "").strip().lower()
    best = None
    for e in bank.values():
        if e.get("status") != "graduated":
            continue
        if (e.get("task") or "").strip().lower() != t:
            continue
        if surface and e.get("surface") != surface:
            continue
        keyed = bool(model) and e.get("model") == model
        if model and e.get("model") and not keyed:
            continue  # another model's pattern — don't contaminate
        if best is None or (keyed and not best[0]):
            best = (keyed, e)
    if not best:
        return ""
    e = best[1]
    steps = " → ".join(f"{s['tool']}({s.get('arg','')})"
                       for s in e.get("steps") or [])
    if not steps:
        return ""
    return (f"[proven sequence — graduated {e['streak']}-run "
            f"streak] {steps}\n(verify each result; re-aim if "
            f"the layout moved)")


def bank_text() -> str:
    bank = load_bank()
    if not bank:
        return "skill bank empty — run the arena first"
    lines = []
    order = {"graduated": 0, "candidate": 1, "demoted": 2}
    for e in sorted(bank.values(),
                    key=lambda x: (order.get(x["status"], 9),
                                   -x["streak"])):
        eff = e["eff_sum"] / e["runs"] if e["runs"] else 0
        lines.append(f"{e['status']:<10} {e['surface']}/{e['app'] or '-'}"
                     f" streak={e['streak']} eff={eff:.2f} "
                     f"{e['task'][:48]}")
    return "\n".join(lines)
