"""Route-decision eval — replay logged decisions through candidate
models and score intent-match. Offline: reads decisions.jsonl, calls
OpenRouter /chat/completions per candidate, prints a table. The eval
bills the orchestral lane when WISP_EVAL_KEY_ENV names it (org rule),
else the configured OpenRouter key.

Ground truth per decision: the corrected pick when a 'correct'/'incorrect'
label pair resolves one, else the route that was taken (marked 'logged').
"""
import json
import re
import time
import urllib.request

from . import config, pipeline

DECISIONS = config.DECISIONS
LABELS = config.DATA_DIR / "labels.jsonl"

CANDIDATES = [
    "qwen/qwen3-30b-a3b-instruct-2507",
    "mistralai/ministral-3b-2512",
    "google/gemma-3-4b-it",
    "ibm-granite/granite-4.0-h-micro",
    "openai/gpt-5-nano",
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
        r = subprocess.run(["omaseal", "get", "openrouter", "orchestral"],
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
