"""Dev tuning mode: drift flags, run reports, A/B pairs and the owner's
spot-check (U4).

Everything here is a read over the run stores in dev_runs/ (one JSON line
per task, written by wisp.devrun and filled by wisp.devjudge), joined
with the owner's labels in labels.jsonl. Nothing here changes the
owner's config. The one write is the owner's own label for a reviewed
task, and it goes through the existing turn-scoped `learn.label_last`
path: a judge label is never written to labels.jsonl, so the v1 gate
counts owner-confirmed labels only.
"""
import json
import re

from . import config, devlog, learn

OUTCOMES = ("success", "stopped", "incomplete", "wrong_tries")
_MIX = OUTCOMES + ("unjudged",)
_RANK = {"success": 3, "wrong_tries": 2, "incomplete": 1, "stopped": 0}
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
REVIEW_N = 5
RUNS_MAX = 20
_DECISION_SCAN = 6000


# -- run stores ------------------------------------------------------------

def runs_dir():
    return config.DATA_DIR / "dev_runs"


def _valid(run_id) -> bool:
    return bool(run_id) and bool(_ID_RE.match(run_id)) and ".." not in run_id


def run_ids() -> list:
    """Run ids, newest first (ids start with a timestamp)."""
    try:
        return sorted((p.stem for p in runs_dir().glob("*.jsonl")),
                      reverse=True)
    except OSError:
        return []


def read_rows(run_id: str) -> list:
    if not _valid(run_id):
        return []
    out = []
    try:
        with open(runs_dir() / f"{run_id}.jsonl", encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict):
                    out.append(d)
    except OSError:
        pass
    return out


# -- drift (KTD7) ------------------------------------------------------------

def app_skills() -> set:
    """Names that count as a saved app skill: the folder and `app_classes`
    of every skill under `apps/` (the owner's and the bundled ones), plus
    any other saved skill that declares `app_classes`."""
    from . import skills
    names: set = set()
    for f in skills._iter_skill_files():
        try:
            fm = skills._frontmatter(skills._header(f) or "")
        except OSError:
            continue
        classes = skills._list_field(fm.get("app_classes"))
        if f.parent.parent.name == "apps" or classes:
            names.add(f.parent.name.lower())
            names.update(c.lower() for c in classes if c)
    return names


def _named_apps(goal: str, apps) -> list:
    g = (goal or "").lower()
    return sorted(a for a in (apps or ())
                  if a and re.search(r"(?<![\w-])" + re.escape(a)
                                     + r"(?![\w-])", g))


def _failed_verify(s: dict) -> bool:
    r = str(s.get("result") or "")
    return bool(s.get("verify_failed")) or "verify FAILED" in r \
        or '"verdict":"missed"' in r.replace(" ", "")


def _next(steps: list, i: int):
    if i + 1 >= len(steps):
        return None
    n = steps[i + 1]
    return f"{n.get('tool', '')}: {str(n.get('arg') or '')[:60]}".strip()


def drift(goal: str, steps: list, outcome: str, apps) -> dict:
    """The narrow drift flag: the task names an app with a saved app
    skill AND a step failed verification, or the task needed wrong tries
    with a re-aimed click. Records the step, what wisp did next and
    whether the task still got there. Detection only; no skill is ever
    changed."""
    named = _named_apps(goal, apps)
    if not named:
        return {"suspected": False}
    steps = steps or []
    hit, reason = None, ""
    for i, s in enumerate(steps):
        if _failed_verify(s):
            hit, reason = i, "verify_failed"
            break
    if hit is None and outcome == "wrong_tries":
        clicks = [i for i, s in enumerate(steps) if s.get("tool") == "click"]
        if len(clicks) >= 2:
            hit, reason = clicks[0], "wrong_tries"
    if hit is None:
        return {"suspected": False}
    return {"suspected": True, "apps": named, "reason": reason,
            "step": hit, "next": _next(steps, hit),
            "recovered": outcome in ("success", "wrong_tries")}


# -- the report ---------------------------------------------------------------

def _decision_refs(turns: set) -> dict:
    """turn id -> the decision's ts (the label's `ref`)."""
    out: dict = {}
    if not turns:
        return out
    for i, raw in enumerate(devlog.tail_lines(config.DECISIONS)):
        if i > _DECISION_SCAN:
            break
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("turn") in turns \
                and d["turn"] not in out and d.get("ts"):
            out[d["turn"]] = d["ts"]
            if len(out) == len(turns):
                break
    return out


def _judged(r: dict) -> str:
    j = r.get("judge")
    o = (j or {}).get("outcome") if isinstance(j, dict) else None
    return o if o in OUTCOMES else "unjudged"


def _num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _task(r: dict, confirmed) -> dict:
    j = r.get("judge") if isinstance(r.get("judge"), dict) else {}
    c = r.get("cost") if isinstance(r.get("cost"), dict) else {}
    judged = _judged(r)
    agree = None
    if confirmed and judged != "unjudged":
        agree = (judged == "success") == (confirmed == "correct")
    return {"index": r.get("index"), "goal": r.get("goal", ""),
            "turn": r.get("turn"), "route": r.get("route"),
            "outcome": r.get("outcome"), "judged": judged,
            "reason": j.get("reason", ""), "confirmed": confirmed,
            "agrees": agree,
            "drift": r.get("drift") if isinstance(r.get("drift"), dict)
            else {"suspected": False},
            "cost_usd": round(_num(c.get("task_usd"))
                              + _num(c.get("judge_usd")), 6),
            "total_ms": (r.get("timing_ms") or {}).get("wall"),
            "ttft_ms": (r.get("timing_ms") or {}).get("ttft"),
            "model": r.get("model"),
            "provider": r.get("provider"),
            "steps": [{"tool": s.get("tool", ""), "arg": s.get("arg", ""),
                       "result": s.get("result") or ""}
                      for s in (r.get("steps") or [])
                      if isinstance(s, dict)],
            "arm": r.get("arm")}


def _summary(rows: list, tasks: list) -> dict:
    mix = {k: 0 for k in _MIX}
    conf = {"correct": 0, "incorrect": 0, "unreviewed": 0}
    stage: dict = {}
    task_usd = judge_usd = 0.0
    by_provider: dict = {}
    for r, t in zip(rows, tasks):
        mix[t["judged"]] += 1
        conf[t["confirmed"] or "unreviewed"] += 1
        c = r.get("cost") if isinstance(r.get("cost"), dict) else {}
        task_usd += _num(c.get("task_usd"))
        judge_usd += _num(c.get("judge_usd"))
        for prov, usd in (c.get("by_provider") or {}).items():
            by_provider[prov] = by_provider.get(prov, 0.0) + _num(usd)
        for k, v in (r.get("timing_ms") or {}).items():
            stage[k] = stage.get(k, 0) + (v if isinstance(v, (int, float))
                                          else 0)
    n_judged = len(rows) - mix["unjudged"]
    n_conf = conf["correct"] + conf["incorrect"]
    capped = any((r.get("judge") or {}).get("reason") == "cap"
                 for r in rows if isinstance(r.get("judge"), dict))
    starts = [r["started"] for r in rows if r.get("started")]
    ends = [r["ended"] for r in rows if r.get("ended")]
    return {"tasks": len(rows),
            "ran": sum(1 for r in rows if r.get("turn")),
            "judged_n": n_judged, "unjudged": mix["unjudged"],
            "judge_capped": capped,
            "mix": {"judged": mix, "confirmed": conf},
            "accuracy": {"judged": (mix["success"] / n_judged
                                    if n_judged else None),
                         "confirmed": (conf["correct"] / n_conf
                                       if n_conf else None)},
            "drift_count": sum(1 for t in tasks
                               if t["drift"].get("suspected")),
            "cost": {"task_usd": round(task_usd, 6),
                     "judge_usd": round(judge_usd, 6),
                     "total_usd": round(task_usd + judge_usd, 6),
                     "by_provider": {k: round(v, 6) for k, v in
                                     sorted(by_provider.items())}},
            "stage_ms": stage,
            "started": min(starts) if starts else None,
            "ended": max(ends) if ends else None}


def _pairs(tasks_a: list, tasks_b: list) -> list:
    by_b = {t["index"]: t for t in tasks_b}
    out = []
    for a in tasks_a:
        b = by_b.get(a["index"])
        if b is None:
            continue
        ra = _RANK.get(a["judged"], _RANK.get(a["outcome"], 0))
        rb = _RANK.get(b["judged"], _RANK.get(b["outcome"], 0))
        out.append({"index": a["index"], "goal": a["goal"],
                    "a": a["judged"], "b": b["judged"],
                    "a_turn": a["turn"], "b_turn": b["turn"],
                    "better": "a" if ra > rb else "b" if rb > ra else "tie"})
    return out


def _run(run_id: str, labels: dict) -> dict | None:
    rows = read_rows(run_id)
    if not rows:
        return None
    refs = _decision_refs({r["turn"] for r in rows if r.get("turn")})

    def owner(r):
        lab = labels.get(refs.get(r.get("turn")))
        return lab[0] if lab and lab[0] in ("correct", "incorrect") else None
    tasks = [_task(r, owner(r)) for r in rows]
    out = {"run_id": run_id, **_summary(rows, tasks), "rows": tasks}
    arms = sorted({r.get("arm") for r in rows if r.get("arm")})
    if arms:
        out["vs"] = next((r.get("vs") for r in rows if r.get("vs")), None)
        out["profiles"] = any(r.get("profile") for r in rows)
        out["arms"] = {}
        for arm in arms:
            idx = [i for i, r in enumerate(rows) if r.get("arm") == arm]
            out["arms"][arm] = _summary([rows[i] for i in idx],
                                        [tasks[i] for i in idx])
        if len(arms) == 2:
            # two arms pair per task; `a` and `b` are the first and
            # second arm in name order (gauntlet arms: hybrid/openrouter)
            first, second = arms
            out["pair_arms"] = {"a": first, "b": second}
            out["pairs"] = _pairs([t for t in tasks if t["arm"] == first],
                                  [t for t in tasks if t["arm"] == second])
    return out


def build(run_id=None, labels_file=None) -> dict:
    """{runs: [summary with per-task rows]}: one run by id, or the newest
    runs first. `confirmed` is the owner's label only."""
    labels = learn._latest_labels(labels_file or learn.LABELS_FILE)
    if run_id:
        ids = [run_id] if _valid(run_id) else []
    else:
        ids = run_ids()[:RUNS_MAX]
    runs = [r for r in (_run(i, labels) for i in ids) if r]
    return {"runs": runs}


def redact(out: dict) -> dict:
    """The same reply with every goal, reason and step text blanked: what
    a spawned agent peer may see (counts, outcomes, cost, timings)."""
    runs = []
    for run in out.get("runs") or []:
        rows = []
        for t in run.get("rows") or []:
            d = dict(t, goal="", reason="",
                     steps=[dict(s, arg="", result="")
                            for s in t.get("steps") or []])
            if isinstance(d.get("drift"), dict):
                d["drift"] = dict(d["drift"], next=None)
            rows.append(d)
        r = dict(run, rows=rows)
        if "pairs" in run:
            r["pairs"] = [dict(p, goal="") for p in run["pairs"]]
        runs.append(r)
    return dict(out, runs=runs)


# -- the owner's spot-check ------------------------------------------------

def pick_review(rows: list, n: int = REVIEW_N) -> list:
    """Up to `n` judged, not yet reviewed tasks, mixing failures and
    successes (a failure first, then alternating)."""
    cand = [r for r in rows if r.get("judged") in OUTCOMES
            and r.get("turn") and not r.get("confirmed")]
    ok = [r for r in cand if r["judged"] == "success"]
    bad = [r for r in cand if r["judged"] != "success"]
    out = []
    while (ok or bad) and len(out) < n:
        for pool in (bad, ok):
            if pool and len(out) < n:
                out.append(pool.pop(0))
    return out


def _label(label: str, note: str, turn: str) -> str:
    return learn.label_last(label, note, turn=turn)


def _find(run_id, turn):
    for rid in ([run_id] if run_id else run_ids()):
        for r in read_rows(rid):
            if r.get("turn") == turn:
                return r
    return None


def label_for(judged: str, action: str) -> str:
    """The owner's label for a judged outcome: confirm agrees with the
    judge, flip is the opposite."""
    label = "correct" if judged == "success" else "incorrect"
    if action == "flip":
        label = "incorrect" if label == "correct" else "correct"
    return label


def review_apply(run_id, turn: str, action: str, label_fn=None) -> dict:
    """The owner confirms or flips the judge on one task. The label is
    the owner's, written through the turn-scoped label path: confirm
    writes `correct` for a judged success and `incorrect` otherwise;
    flip writes the opposite."""
    if action not in ("confirm", "flip"):
        return {"ok": False, "error": "action must be confirm or flip"}
    r = _find(run_id, turn)
    if r is None:
        return {"ok": False, "error": f"no dev task for turn {turn}"}
    judged = _judged(r)
    if judged == "unjudged":
        return {"ok": False, "error": "that task was not judged"}
    label = label_for(judged, action)
    return _write(label, f"dev review: {action} {judged}", turn, label_fn)


def set_label(run_id, turn: str, label: str, label_fn=None) -> dict:
    """The owner's own label for a task of a dev run."""
    if label not in ("correct", "incorrect"):
        return {"ok": False, "error": "label must be correct or incorrect"}
    if _find(run_id, turn) is None:
        return {"ok": False, "error": f"no dev task for turn {turn}"}
    return _write(label, "dev review", turn, label_fn)


def _write(label, note, turn, label_fn) -> dict:
    out = (label_fn or _label)(label, note, turn)
    if isinstance(out, dict):
        ok, text = bool(out.get("ok")), str(out.get("result", ""))
    else:
        text = str(out)
        ok = not text.startswith(("SKIP", "ERROR", "nothing", "not_found",
                                  "not_ratable"))
    return {"ok": ok, "label": label, "turn": turn, "result": text}


# -- importing the owner's gauntlet labels -----------------------------------

OWNER_LABELS = ("correct", "incorrect")


def import_labels(src_dir, decisions_file=None, labels_file=None) -> dict:
    """Copy the owner's labels on gauntlet turns, and only those turns'
    decisions, from a gauntlet data directory into the owner's own data
    (R20, KTD11). Only a `correct` or `incorrect` label counts: the
    judge writes none, and the automatic `corrected-by-retry` mark is
    not the owner's word. A decision already present (same `ts`) is
    skipped, so a second run copies nothing. Returns
    {copied, present, unlabelled}."""
    import pathlib
    from . import private
    src = pathlib.Path(src_dir)
    dest_dec = pathlib.Path(decisions_file or config.DECISIONS)
    dest_lab = pathlib.Path(labels_file or learn.LABELS_FILE)
    if src.resolve() == dest_dec.parent.resolve():
        raise ValueError("that is your own data directory")
    owner: dict = {}
    for lab in learn._read_jsonl(src / "labels.jsonl"):
        ref = lab.get("ref")
        if isinstance(ref, str) and ref and lab.get("label") in OWNER_LABELS:
            owner[ref] = lab                    # the latest owner label
    have = {d.get("ts") for d in learn._read_jsonl(dest_dec)}
    copied = present = 0
    decs = learn._read_jsonl(src / "decisions.jsonl")
    seen = set()
    for d in decs:
        ts = d.get("ts")
        if ts in seen or ts not in owner:
            continue
        seen.add(ts)
        if ts in have:
            present += 1
            continue
        with private.open_append(dest_dec) as f:
            f.write(json.dumps(d, separators=(",", ":")) + "\n")
        with private.open_append(dest_lab) as f:
            f.write(json.dumps(owner[ts], separators=(",", ":")) + "\n")
        copied += 1
    return {"copied": copied, "present": present,
            "unlabelled": len({d.get("ts") for d in decs} - set(owner))}


# -- text ------------------------------------------------------------------

def _pct(x) -> str:
    return "-" if x is None else f"{round(x * 100)}%"


def render(out: dict) -> str:
    lines = []
    for r in out.get("runs") or []:
        m = r.get("mix") or {}
        j = " ".join(f"{k} {v}" for k, v in
                     (m.get("judged") or {}).items() if v)
        c = {"correct": 0, "incorrect": 0, "unreviewed": 0,
             **(m.get("confirmed") or {})}
        acc = r.get("accuracy") or {}
        cost = {"total_usd": 0.0, "judge_usd": 0.0, **(r.get("cost") or {})}
        lines.append(f"run {r['run_id']}: {r.get('tasks')} tasks"
                     + (f"  (A/B: {r['vs']})" if r.get("vs") else ""))
        lines.append(f"  judged: {j or '-'}   accuracy {_pct(acc.get('judged'))}")
        lines.append(f"  confirmed: {c['correct']} correct, "
                     f"{c['incorrect']} incorrect, {c['unreviewed']} "
                     f"unreviewed   accuracy "
                     f"{_pct(acc.get('confirmed'))}")
        lines.append(f"  drift flags: {r.get('drift_count', 0)}   cost "
                     f"${cost['total_usd']:.4f} (judge "
                     f"${cost['judge_usd']:.4f})")
        if r.get("stage_ms"):
            lines.append("  time: " + ", ".join(
                f"{k} {round(v)}ms" for k, v in r["stage_ms"].items()))
        for name, a in (r.get("arms") or {}).items():
            if name in ("a", "b") and not r.get("profiles"):
                continue
            ac = {"total_usd": 0.0, **(a.get("cost") or {})}
            prov = ", ".join(f"{k} ${v:.4f}" for k, v in
                             (ac.get("by_provider") or {}).items())
            lines.append(
                f"  arm {name}: {a.get('tasks')} tasks  judged "
                f"{_pct((a.get('accuracy') or {}).get('judged'))}  cost "
                f"${ac['total_usd']:.4f}" + (f" ({prov})" if prov else ""))
        if r.get("judge_capped"):
            lines.append(f"  judge cap reached: {r.get('unjudged')} tasks "
                         "unjudged")
        for t in r.get("rows") or []:
            tag = "".join(("D" if (t.get("drift") or {}).get("suspected")
                           else "-", "*" if t.get("confirmed") else " "))
            lines.append(f"  {str(t.get('index')):>2} "
                         f"{t.get('judged', ''):<12}{tag} "
                         f"{(t.get('arm') or ''):<2}"
                         f"{str(t.get('goal', ''))[:60]}")
        for p in r.get("pairs") or []:
            lines.append(f"  pair {p['index']}: a {p['a']} / b {p['b']}"
                         f" -> {p['better']}  {p['goal'][:50]}")
    return "\n".join(lines) if lines else "no dev runs yet"
