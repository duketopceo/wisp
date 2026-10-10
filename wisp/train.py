"""Training arena — behavior-loop improvement over logged runs.

Reads every judged run (clicklab results + act trajectories), buckets
them by surface/app, tracks streaks, and maintains the skill bank:
task patterns that auto-graduate once proven (streak>=3, mean
efficiency>=0.9) and demote when they regress. No weight training —
this is credit assignment and recipe distillation over logs.

U7 additions: `verdicts.jsonl` mirrors the judge pass per run;
`buckets.json` is the rolling failure-bucket summary (by failure
class x task skill x surface) the adaptive clicklab loop reads to
aim the next task at the model's weakest skill.
"""
import hashlib
import json
import re
from datetime import datetime, timezone

from . import config

RESULTS = config.DATA_DIR / "clicklab.jsonl"
TRAJECTORIES = config.DATA_DIR / "trajectories.jsonl"
BANK_FILE = config.DATA_DIR / "skillbank.json"
VERDICTS = config.DATA_DIR / "verdicts.jsonl"
BUCKETS_FILE = config.DATA_DIR / "buckets.json"
BUCKET_WINDOW = 500      # rolling window of recent runs buckets read

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


def _run_ok(rec: dict) -> bool | None:
    """Ground truth wins; Jev reconciles. Tri-state (U7):

      True   a verified success the streak may count
      False  a failure — resets the streak, demotes graduates
      None   unjudged (every judge was down) — NEUTRAL: never counts
             toward promotion, but thin evidence doesn't break a
             streak either
    """
    if rec.get("verified") is False:
        return False
    j = rec.get("judge") or {}
    if j.get("judged") is False or j.get("by") == "none":
        return None
    if j.get("success") is False:
        return False
    return bool(rec.get("verified"))


def promote_after(cfg: dict | None = None) -> int:
    """Verified-success streak a recipe needs to graduate
    ([clicklab] promote_after; default GRAD_STREAK)."""
    raw = (cfg or {}).get("clicklab", {}).get("promote_after")
    try:
        return max(1, int(raw)) if raw else GRAD_STREAK
    except (TypeError, ValueError):
        return GRAD_STREAK


def update_bank(rec: dict, path=None, cfg: dict | None = None) -> dict:
    """Fold one judged run into the skill bank. Returns the entry."""
    bank = load_bank(path)
    k = _key(rec)
    e = _fold(bank.get(k), rec, promote_after(cfg))
    bank[k] = e
    save_bank(bank, path)
    return e


def replay_all(path=None, cfg: dict | None = None) -> dict:
    """Rebuild the bank from clicklab.jsonl — idempotent."""
    bank = {}
    need = promote_after(cfg)
    p = path or BANK_FILE
    for rec in _load_jsonl(RESULTS):
        bank[_key(rec)] = _fold(bank.get(_key(rec)), rec, need)
    save_bank(bank, p)
    return bank


# tools that never mutate verifiable page state — a screenshot or a
# hover can't be what an oracle checks
PASSIVE_TOOLS = frozenset({"screenshot", "move"})
NO_EFFECT = ("SKIP", "ERROR", "FAIL", "REFUS", "DRYRUN", "STALLED",
             "INTERRUPTED", "ASK_USER")


def distill_steps(steps: list) -> list:
    """Minimal re-executable sequence — drop passive observes/moves and
    steps that returned no effect. A trajectory can pass reliably and
    still be twice the necessary length; this is the shrink."""
    out = []
    for s in steps or []:
        if s.get("tool") in PASSIVE_TOOLS:
            continue
        if (s.get("result") or "").startswith(NO_EFFECT):
            continue
        out.append({"tool": s["tool"], "arg": s.get("arg", "")})
    return out


def distill_candidates(bank: dict, needed: int = GRAD_STREAK) -> list:
    """Candidates that pass reliably but wastefully: streak>=needed
    yet sub-floor efficiency, and a banked trajectory that actually
    shrinks under distillation. These are 'reliable, optimize it' —
    not 'learn it'."""
    out = []
    for e in bank.values():
        if e.get("status") != "candidate" \
                or e.get("streak", 0) < needed or not e.get("check"):
            continue
        if len(distill_steps(e.get("steps"))) < len(e.get("steps") or []):
            out.append(e)
    return out


def promote(e: dict, steps: list) -> dict:
    """Graduate a distilled entry after its minimal sequence re-verified
    on a fresh seed. The re-verified shorter path IS the efficiency
    proof — no judged run needed."""
    e["status"] = "graduated"
    e["optimized"] = True
    e["orig_steps"] = len(e.get("steps") or [])
    e["steps"] = steps[:24]
    e["graduated_at"] = datetime.now(timezone.utc).isoformat()
    e.setdefault("recipe_id",
                 "recipe-" + hashlib.sha1(
                     (e.get("key") or "").encode()).hexdigest()[:10])
    return e


def _fold(e: dict | None, rec: dict, needed: int = GRAD_STREAK) -> dict:
    """Fold one judged run into an entry — pure, no file I/O.
    Graduation judges the current streak's efficiency window (a past
    failure shouldn't make re-graduation impossible); demotion uses the
    same window plus any verified failure. An unjudged run (`ok` None)
    is recorded but moves nothing — no streak bump, no break, no demote."""
    j = rec.get("judge") or {}
    e = e or {"key": _key(rec), "task": rec.get("task"),
              "surface": rec.get("surface"),
              "app": rec.get("app") or "",
              "model": rec.get("model") or "",
              "streak": 0, "streak_eff": [], "runs": 0, "verified": 0,
              "eff_sum": 0.0,
              "status": "candidate", "steps": [], "history": []}
    ok = _run_ok(rec)
    eff = rec.get("efficiency")
    if not isinstance(eff, (int, float)):
        eff = j.get("efficiency")
    e["runs"] += 1
    if isinstance(eff, (int, float)):
        e["eff_sum"] += eff
    if ok is True:
        e["streak"] += 1
        e["verified"] = e.get("verified", 0) + 1
        if isinstance(eff, (int, float)):
            e["streak_eff"].append(eff)
    elif ok is False:
        e["streak"] = 0
        e["streak_eff"] = []
    e["history"].append({"ts": rec.get("ts"), "ok": ok,
                         "eff": eff,
                         "cls": j.get("failure_class"),
                         "waste": j.get("waste")})
    e["history"] = e["history"][-50:]
    prev = e["status"]
    win = e["streak_eff"]
    win_mean = sum(win) / len(win) if len(win) >= needed else 0.0
    if e["status"] == "graduated" and (
            ok is False
            or (ok is True and win and win_mean < DEMOTE_EFFICIENCY)):
        e["status"] = "demoted"
        e["demoted_at"] = datetime.now(timezone.utc).isoformat()
    elif e["status"] != "graduated" and e["streak"] >= needed \
            and win_mean >= GRAD_EFFICIENCY:
        e["status"] = "graduated"
        e["graduated_at"] = \
            datetime.now(timezone.utc).isoformat()
        # promoted entries get a stable recipe id for replay/lookup
        e.setdefault("recipe_id",
                     "recipe-" + hashlib.sha1(
                         e["key"].encode()).hexdigest()[:10])
    e["changed"] = e["status"] != prev
    if ok and rec.get("steps"):
        e["steps"] = rec["steps"][:24]
    if rec.get("check"):
        e["check"] = rec["check"]
    if rec.get("suite"):
        # distillation routes candidates to the page their suite ran on
        e["suite"] = rec["suite"]
    return e


def stats() -> dict:
    """Arena roll-up: per-surface/per-model pass rates + efficiency,
    pass^k reliability, waste + flake histograms, bank status."""
    recs = _load_jsonl(RESULTS)
    surfaces: dict = {}
    models: dict = {}
    reliability: dict = {}
    flakes: dict = {}
    unjudged = 0
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
        if (r.get("judge") or {}).get("judged") is False:
            unjudged += 1
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
            "waste": waste, "bank": bank_status, "unjudged": unjudged}


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


# ---------------------------------------------------------------------
# verdict stream + failure buckets
# ---------------------------------------------------------------------

def record_verdict(rec: dict, path=None) -> None:
    """Mirror a run's verdict onto verdicts.jsonl — the judge stream
    beside trajectories, kept slim so it stays greppable at volume."""
    j = rec.get("judge") or {}
    line = {"ts": rec.get("ts") or datetime.now(timezone.utc).isoformat(),
            "task": rec.get("task"), "surface": rec.get("surface"),
            "suite": rec.get("suite"), "model": rec.get("model"),
            "verified": rec.get("verified"),
            "judge": {"success": j.get("success"),
                      "failure_class": j.get("failure_class"),
                      "efficiency": j.get("efficiency"),
                      "first_fault": j.get("first_fault"),
                      "waste": j.get("waste"),
                      "by": j.get("by"), "judged": j.get("judged")}}
    try:
        p = path or VERDICTS
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(json.dumps(line) + "\n")
    except OSError:
        pass


def is_failure(rec: dict) -> bool:
    """A run that failed for real — oracle FAIL or judge dissent.
    Unjudged runs are not failures (they're no evidence either way)."""
    if rec.get("verified") is False:
        return True
    return (rec.get("judge") or {}).get("success") is False


_FLAKE_CLASS = {"env": "environment", "timing": "environment",
                "judge_fn": "judge", "model": "model"}


def failure_class(rec: dict) -> str | None:
    """Who owns a failure: model | environment | tool | judge.
    The judge's own classification wins; the local flake heuristic is
    the fallback so buckets fill even when the judge couldn't classify."""
    j = rec.get("judge") or {}
    c = j.get("failure_class")
    if c in ("model", "environment", "tool", "judge"):
        return c
    if not is_failure(rec):
        return None
    fk = rec.get("flake") or classify_flake(rec)
    return _FLAKE_CLASS.get(fk, "model")


# leading-verb classifier — the FIRST action word is the skill the task
# actually exercises ('scroll the list then click ECHO' is a scroll
# task; the trailing click is routine)
_SKILLS = [
    ("scroll", r"\bscroll"),
    ("type",   r"\btype\b|\bwrite\b"),
    ("fill",   r"\bfill\b|\bset\b.{0,30}\bto\b"),
    ("select", r"\bselect\b|\bdropdown\b"),
    ("drag",   r"\bdrag\b|\bconnect\b|\bmove\b.{0,40}\bto\b"),
    ("key",    r"\bpress\b.{0,20}\b(key|button)\b|\bhotkey\b"),
    ("open",   r"\bopen\b|\blaunch\b"),
    ("click",  r"\bclick\b|\btick\b|\bcheck\b|\btap\b"),
]


def task_skill(task: str) -> str:
    """Which skill a task exercises: click | scroll | type | fill |
    select | drag | key | open. Position-ordered — earliest verb wins."""
    t = (task or "").lower()
    best, pos = "click", len(t) + 1
    for skill, pat in _SKILLS:
        m = re.search(pat, t)
        if m and m.start() < pos:
            best, pos = skill, m.start()
    return best


_TOOL_SKILL = {"click": "click", "move": "click", "double_click":
               "click", "scroll": "scroll", "type": "type",
               "fill": "fill", "key": "key", "hotkey": "key",
               "press": "key", "select": "select", "drag": "drag"}


def fail_skill(rec: dict) -> str:
    """The skill a failed run actually exercised: the first-fault
    step's tool when the judge named one, else the task's leading verb."""
    j = rec.get("judge") or {}
    ff = j.get("first_fault", -1)
    steps = rec.get("steps") or []
    if isinstance(ff, int) and 0 <= ff < len(steps):
        sk = _TOOL_SKILL.get(str(steps[ff].get("tool") or ""))
        if sk:
            return sk
    return task_skill(rec.get("task") or "")


def compute_buckets(recs: list) -> dict:
    """Rolling failure-bucket summary over the given records: counts by
    failure class, by task skill, by surface — plus cells
    ('class|skill|surface') and the hottest one (`top`). Pure."""
    b = {"runs": len(recs), "fails": 0, "unjudged": 0,
         "by_class": {}, "by_skill": {}, "by_surface": {}, "cells": {}}
    for rec in recs:
        j = rec.get("judge") or {}
        if j.get("judged") is False or j.get("by") == "none":
            b["unjudged"] += 1
        if not is_failure(rec):
            continue
        cls = failure_class(rec) or "model"
        skill = fail_skill(rec)
        surf = rec.get("surface") or "unknown"
        b["fails"] += 1
        for dim, k in ((b["by_class"], cls), (b["by_skill"], skill),
                       (b["by_surface"], surf)):
            dim[k] = dim.get(k, 0) + 1
        cell = f"{cls}|{skill}|{surf}"
        b["cells"][cell] = b["cells"].get(cell, 0) + 1
    top = max(b["cells"].items(), key=lambda kv: (kv[1], kv[0]),
              default=None)
    b["top"] = top[0] if top else None
    return b


def rebuild_buckets(path=None, records=None) -> dict:
    """Recompute buckets.json from the rolling tail of clicklab.jsonl
    (BUCKET_WINDOW runs). Returns the summary it wrote."""
    recs = records if records is not None else _load_jsonl(RESULTS)
    b = compute_buckets(recs[-BUCKET_WINDOW:])
    b["updated"] = datetime.now(timezone.utc).isoformat()
    p = path or BUCKETS_FILE
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(b, indent=1, sort_keys=True))
    except OSError:
        pass
    return b


def load_buckets(path=None) -> dict:
    try:
        return json.loads((path or BUCKETS_FILE).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
