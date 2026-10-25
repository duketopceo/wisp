"""Route-decision eval — replay logged decisions through candidate
models and score intent-match. Offline: reads decisions.jsonl, calls
OpenRouter /chat/completions per candidate, prints a table. The eval
bills the orchestral lane when WISP_EVAL_KEY_ENV names it (org rule),
else the configured OpenRouter key.

Ground truth per decision: the corrected pick when a 'correct'/'incorrect'
label pair resolves one, else the route that was taken (marked 'logged').

With ``--replay --decisions``, replays through OpenRouter
``/api/alpha/decisions`` (same shape as runtime Jev) and reports
agreement with logged routes, label-resolved accuracy, and optional
joint clarify/risky answers. Transcripts appear only in ``--out`` JSON.
"""
import json
import pathlib
import re
import statistics as st
import time
import urllib.request

from . import config, pipeline

DECISIONS = config.DECISIONS
LABELS = config.DATA_DIR / "labels.jsonl"
DECISIONS_ENDPOINT = config.JEV_ENDPOINT

CANDIDATES = [
    "qwen/qwen3-30b-a3b-instruct-2507",
    "mistralai/ministral-3b-2512",
    "google/gemma-3-4b-it",
    "ibm-granite/granite-4.0-h-micro",
    "openai/gpt-5-nano",
]

DECISION_MODELS = [
    "perplexity/pplx-decider-v1.2",
    "perplexity/pplx-decider-flash-v1.2",
    "typesafe/jev-1.13",
]


def _jev_baseline() -> str:
    """Jev's historical accuracy from human labels — replaying it would
    be circular (its answers are already the logged routes)."""
    labels = _load_jsonl(LABELS)
    good = sum(1 for l in labels if l.get("label") == "correct")
    bad = sum(1 for l in labels if l.get("label") == "incorrect")
    if not good + bad:
        return "jev (historical): no labels yet"
    return (f"jev (historical): {good}/{good + bad} labeled correct "
            f"({100 * good / (good + bad):.0f}%)")

_ROUTES = list(pipeline.JEV_QUESTIONS["route"]["criteria"])


def _joint_questions() -> dict:
    rq = pipeline.JEV_QUESTIONS["route"]
    return {
        "route": rq,
        "is_risky": {
            "type": "choice",
            "instructions": "Could carrying out this request destroy data, "
                            "spend money, send something to someone, or "
                            "otherwise be hard to undo?",
            "criteria": {
                "yes": "risky or irreversible",
                "no": "safe and reversible",
            },
        },
        "needs_clarify": {
            "type": "choice",
            "instructions": "Is the request too vague or incomplete to act "
                            "on without asking the user?",
            "criteria": {
                "yes": "too vague, must ask",
                "no": "clear enough to act",
            },
        },
    }


def _load_jsonl(path) -> list:
    try:
        return [json.loads(l) for l in path.read_text().splitlines()
                if l.strip()]
    except OSError:
        return []


def _cases() -> list:
    """[{transcript, expected, source}] — source 'labeled' when human
    truth exists, else 'logged' (what Jev picked)."""
    labels = _load_jsonl(LABELS)
    truth = {}
    for l in labels:
        ref, lab = l.get("ref"), l.get("label")
        if lab == "correct" and ref:
            truth[ref] = None          # logged route is truth
        elif lab == "incorrect" and ref:
            truth[ref] = "incorrect"   # logged route is *wrong*
    corrs = {c.get("ts"): c for c in
             _load_jsonl(config.CORRECTIONS)}
    cases = []
    for d in _load_jsonl(DECISIONS):
        tr = (d.get("transcript") or "").strip()
        if not tr or tr == "[BLANK_AUDIO]":
            continue
        route = (d.get("answers", {}).get("route") or {}).get("choice")
        if route not in _ROUTES:
            continue
        ref = d.get("ts")
        mark = truth.get(ref)
        if mark == "incorrect":
            continue  # logged route is known-wrong; no truth to score
        cases.append({"transcript": tr, "expected": route,
                      "source": "labeled" if ref in truth else "logged"})
    return cases


def _prompt(transcript: str) -> list:
    crit = pipeline.JEV_QUESTIONS["route"]["criteria"]
    opts = "\n".join(f"- {k}: {v}" for k, v in crit.items())
    return [{"role": "user", "content":
             f'The user said: "{transcript}"\n\n'
             "Pick exactly one route. Reply with the route name only.\n"
             f"{opts}"}]


def _call(model: str, messages: list, key: str) -> str:
    body = {"model": model, "messages": messages,
            "temperature": 0, "max_tokens": 12}
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "HTTP-Referer": "https://github.com/duketopceo/wisp",
                 "X-Title": "Wisp route eval"},
        method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        r = json.loads(resp.read())
    return (r["choices"][0]["message"]["content"] or "").strip().lower()


def _eval_key() -> str:
    """Eval spend bills the orchestral key (org rule) — resolve via
    omaseal, fall back to the configured OpenRouter key."""
    import subprocess
    try:
        from . import platform as _platform
        r = subprocess.run([_platform.resolve_exe("omaseal"), "get",
                            "openrouter", "orchestral"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except OSError:
        pass
    return config.load_api_key()


def run(cfg: dict, models: list | None = None, limit: int = 0) -> str:
    models = models or CANDIDATES
    cases = _cases()
    if limit:
        cases = cases[-limit:]
    if not cases:
        return "no logged decisions to replay"
    key = _eval_key()
    rows, per_route = {}, {}
    for model in models:
        ok = lat = 0
        for c in cases:
            t0 = time.time()
            try:
                got = _call(model, _prompt(c["transcript"]), key)
            except Exception as e:
                got = f"ERR {e}"
            lat += time.time() - t0
            # accept the route name anywhere in a short reply — chatty
            # models prepend filler; wrong-but-present routes still miss
            toks = re.findall(r"[a-z]+", got) if got else []
            match = c["expected"] in toks and not got.startswith("ERR")
            ok += match
            per_route.setdefault(model, {}).setdefault(
                c["expected"], [0, 0])
            per_route[model][c["expected"]][0] += match
            per_route[model][c["expected"]][1] += 1
        n = len(cases)
        rows[model] = (ok, n, lat / n if n else 0)
    out = [f"route eval — {len(cases)} cases "
           f"({sum(1 for c in cases if c['source'] == 'labeled')} labeled)"]
    for m, (ok, n, avg) in rows.items():
        out.append(f"  {m:45s} {ok}/{n}  ({100*ok/n:.0f}%)  "
                   f"{avg*1000:.0f}ms avg")
    best = max(rows.items(), key=lambda kv: kv[1][0])[0]
    out.append(f"per-route ({best}):")
    for r, (ok, n) in sorted(per_route.get(best, {}).items()):
        out.append(f"  {r:12s} {ok}/{n}")
    out.append(_jev_baseline())
    return "\n".join(out)


# -- decisions-endpoint replay -----------------------------------------


def _pct(vals: list, q: float):
    if not vals:
        return None
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(round(q * (len(vals) - 1))))]


def _label_state(labels: list) -> dict:
    """Latest label per decision ref (file order wins)."""
    by_ref: dict = {}
    for row in labels:
        ref = row.get("ref")
        if ref:
            by_ref[ref] = row.get("label")
    return by_ref


def _replay_rows(limit: int = 0, decisions_path=None) -> list:
    path = decisions_path or DECISIONS
    rows = []
    for d in _load_jsonl(path):
        tr = (d.get("transcript") or "").strip()
        if not tr or tr == "[BLANK_AUDIO]":
            continue
        logged = (d.get("answers", {}).get("route") or {}).get("choice")
        if logged not in _ROUTES:
            continue
        rows.append({
            "ts": d.get("ts"),
            "turn": d.get("turn"),
            "transcript": tr,
            "logged_route": logged,
        })
    if limit:
        rows = rows[-limit:]
    return rows


def _call_decisions(model: str, transcript: str, questions: dict,
                    key: str) -> dict:
    """One decisions call; raises on HTTP failure."""
    state = f'The user said: "{transcript}"'
    body = {"model": model, "state": state, "questions": questions}
    req = urllib.request.Request(
        DECISIONS_ENDPOINT,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "HTTP-Referer": "https://github.com/duketopceo/wisp",
                 "X-Title": "Wisp route eval"},
        method="POST")
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as resp:
        out = json.loads(resp.read())
    out["_latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out


def run_decisions(cfg: dict, models: list | None = None, limit: int = 0,
                  joint: bool = True, out_path: str | None = None,
                  decisions_path=None,
                  labels_path=None) -> str:
    """Replay logged turns through decision models; return a text report."""
    models = models or DECISION_MODELS
    dpath = decisions_path or DECISIONS
    lpath = labels_path or LABELS
    rows = _replay_rows(limit, dpath)
    if not rows:
        return "no replayable decisions (need transcript + logged route)"
    key = _eval_key()
    label_by_ref = _label_state(_load_jsonl(lpath))
    questions = _joint_questions() if joint else {
        "route": pipeline.JEV_QUESTIONS["route"]}

    detail = []
    per_model = {m: {"agree": 0, "n": 0, "lat": [], "cost": [],
                     "conf_agree": [], "conf_disagree": [],
                     "per_route": {}, "clarify_yes": 0, "clarify_n": 0}
                 for m in models}

    for row in rows:
        case = {"ts": row["ts"], "logged_route": row["logged_route"],
                "label": label_by_ref.get(row["ts"]), "models": {}}
        for model in models:
            rec = {"error": None}
            pick = None
            conf = None
            try:
                resp = _call_decisions(model, row["transcript"], questions,
                                       key)
                ans = resp.get("answers") or {}
                pick = (ans.get("route") or {}).get("choice")
                conf = (ans.get("route") or {}).get("confidence")
                rec.update({
                    "route": pick,
                    "confidence": conf,
                    "latency_ms": resp.get("_latency_ms"),
                    "cost": (resp.get("usage") or {}).get("cost"),
                    "needs_clarify": (ans.get("needs_clarify") or {})
                    .get("choice"),
                })
            except Exception as e:                          # noqa: BLE001
                rec["error"] = str(e)[:200]
                pick = None
            case["models"][model] = rec
            pm = per_model[model]
            pm["n"] += 1
            if rec.get("latency_ms") is not None:
                pm["lat"].append(rec["latency_ms"])
            if rec.get("cost") is not None:
                pm["cost"].append(float(rec["cost"]))
            if pick in _ROUTES:
                agree = pick == row["logged_route"]
                if agree:
                    pm["agree"] += 1
                pr = pm["per_route"].setdefault(row["logged_route"],
                                                [0, 0])
                pr[1] += 1
                pr[0] += int(agree)
                if conf is not None:
                    (pm["conf_agree"] if agree else pm["conf_disagree"]
                     ).append(float(conf))
            nc = rec.get("needs_clarify")
            if nc in ("yes", "no"):
                pm["clarify_n"] += 1
                pm["clarify_yes"] += int(nc == "yes")
        if out_path:
            case["transcript"] = row["transcript"]
        detail.append(case)

    lines = [f"decisions replay — {len(rows)} cases, "
             f"{len(models)} model(s), "
             f"{'joint' if joint else 'route-only'} questions"]
    lines.append("(agreement vs logged route — not a 40-item benchmark)")
    lines.append("")
    lines.append("(a) logged-route agreement:")
    for m in models:
        pm = per_model[m]
        n, ok = pm["n"], pm["agree"]
        lat = pm["lat"]
        c1k = (st.mean(pm["cost"]) * 1000) if pm["cost"] else None
        ca = pm["conf_agree"]
        cd = pm["conf_disagree"]
        lines.append(f"  {m}")
        if n:
            lines.append(
                f"    agree {ok}/{n} ({100 * ok / n:.0f}%)")
        else:
            lines.append("    agree 0/0")
        if n:
            lines.append(
                f"    conf mean agree={st.mean(ca):.2f}"
                if ca else "    conf mean agree=—")
            lines.append(
                f"    conf mean disagree={st.mean(cd):.2f}"
                if cd else "    conf mean disagree=—")
            lines.append(
                f"    latency p50={_pct(lat, .5)} p95={_pct(lat, .95)} ms")
            if c1k is not None:
                lines.append(f"    cost ${c1k:.4f}/1k replays")
        if joint and pm["clarify_n"]:
            lines.append(
                f"    needs_clarify=yes on {pm['clarify_yes']}/"
                f"{pm['clarify_n']} cases")
        for route, (a, t) in sorted(pm["per_route"].items()):
            lines.append(f"      {route:12s} {a}/{t}")

    labeled = {"correct": 0, "incorrect": 0, "corrected-by-retry": 0,
               "other": 0}
    correct_refs = []
    review = []
    for row in rows:
        lab = label_by_ref.get(row["ts"])
        if lab in labeled:
            labeled[lab] += 1
        elif lab:
            labeled["other"] += 1
        if lab == "correct":
            correct_refs.append(row)
        elif lab in ("incorrect", "corrected-by-retry"):
            review.append(row)

    lines.append("")
    lines.append("(b) labels (latest per ref):")
    lines.append(f"  correct={labeled['correct']} "
                 f"incorrect={labeled['incorrect']} "
                 f"corrected-by-retry={labeled['corrected-by-retry']} "
                 f"other={labeled['other']}")
    detail_by_ts = {d["ts"]: d for d in detail}
    if correct_refs:
        lines.append("  accuracy vs logged route (label=correct only):")
        for m in models:
            ok = sum(1 for r in correct_refs
                     if detail_by_ts[r["ts"]]["models"][m].get("route")
                     == r["logged_route"])
            lines.append(f"    {m}: {ok}/{len(correct_refs)}")
    if review:
        lines.append(f"  human review ({len(review)} cases, refs only; "
                     f"use --out for transcripts):")
        for r in review:
            ts = r["ts"]
            d = detail_by_ts[ts]
            picks = ", ".join(
                f"{m}={d['models'][m].get('route') or 'ERR'}"
                for m in models)
            note = next((l.get("note") for l in _load_jsonl(lpath)
                         if l.get("ref") == ts and l.get("label")
                         == label_by_ref.get(ts)), "")
            lines.append(f"    {ts} logged={r['logged_route']} "
                         f"[{label_by_ref.get(ts)}] {picks}"
                         + (f" note={note[:60]}" if note else ""))

    if out_path:
        payload = {
            "cases": len(rows),
            "models": models,
            "joint": joint,
            "per_model_summary": {
                m: {
                    "agree": per_model[m]["agree"],
                    "n": per_model[m]["n"],
                    "latency_p50": _pct(per_model[m]["lat"], .5),
                    "latency_p95": _pct(per_model[m]["lat"], .95),
                }
                for m in models
            },
            "label_counts": labeled,
            "detail": detail,
        }
        path = pathlib.Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=1) + "\n")
        lines.append("")
        lines.append(f"wrote {path}")

    return "\n".join(lines)
