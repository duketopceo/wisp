"""Learning helpers: the correct/incorrect label store, correction and
retry context, the fails report, and verdict-weighted trajectory evidence.

Every clarify-widget pick is logged to corrections.jsonl by the pipeline
(`record_correction`); recall re-indexes that file on rebuild.
"""
import json
import math
from datetime import datetime, timezone

from . import config

LABELS_FILE = config.DATA_DIR / "labels.jsonl"


_UNRATABLE = ("CANCELLED", "ERROR")


def label_status(result: str) -> str:
    """Typed reply for a `label_last` result string: ok | not_found |
    not_ratable. Refusals (SKIP/ERROR write failures) carry none."""
    r = str(result or "")
    if r.startswith("labeled "):
        return "ok"
    if r.startswith("not_ratable"):
        return "not_ratable"
    if r.startswith(("not_found", "nothing to label")):
        return "not_found"
    return ""


def label_last(label: str, note: str = "", lang: str = "",
               turn: str = "") -> str:
    """Tag a decisions.jsonl turn correct/incorrect — `wispd eval` reads
    labels.jsonl keyed by `ref`. With `turn`, that turn's line; without
    it, the most recent finished line (cancelled and error lines are
    skipped). A cancelled or errored turn is not_ratable."""
    label = {"ok": "correct", "good": "correct",
             "bad": "incorrect"}.get(label, label)
    if label not in ("correct", "incorrect"):
        return "SKIP (label must be correct|incorrect)"
    turn = str(turn or "").strip()
    rows = _read_jsonl(config.DECISIONS)
    if turn:
        hit = next((d for d in reversed(rows)
                    if d.get("turn") == turn), None)
        if hit is None:
            return f"not_found: no turn {turn}"
        if str(hit.get("result", "")).startswith(_UNRATABLE):
            return f"not_ratable: turn {turn} did not finish"
    else:
        hit = next((d for d in reversed(rows)
                    if not str(d.get("result", "")).startswith(
                        _UNRATABLE)), None)
        if hit is None:
            return "nothing to label"
    ref = hit.get("ts", "")
    rec = {"ts": datetime.now(timezone.utc).isoformat(),
           "ref": ref, "label": label, "note": note}
    if lang:
        from . import lang as _lang
        rec["lang"] = _lang.parse(lang) or str(lang)
    try:
        LABELS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LABELS_FILE.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError as e:
        return f"ERROR ({e})"
    return f"labeled {label}: {ref}"


# Result-string prefix -> turn kind. These are exactly the prefixes the
# dispatch emits: ANSWERED (stage_execute answer route), ACTED (act loop),
# LAUNCHED (tools/desktop launch), DICTATED / INSERTED / TYPED
# (dictate.run's insert paths), SPAWNED (agents.spawn). Anything else
# (BLOCKED, SKIP, ERROR, ABORTED, CANCELLED, INTERRUPTED, tool results
# like SHOT/CLOSED/FOCUSED, or an unknown/missing decision) is "other".
# Keyed on the result, never the router, so it works under any router.
_KIND_PREFIXES = (
    ("ANSWERED", "answer"), ("ACTED", "act"), ("LAUNCHED", "launch"),
    ("DICTATED", "dictate"), ("INSERTED", "dictate"),
    ("TYPED", "dictate"), ("CORRECTED", "dictate"), ("SPAWNED", "agent"),
)
KINDS = ("answer", "act", "launch", "dictate", "agent", "other")


def turn_kind(result: str) -> str:
    """Map a decisions.jsonl `result` string to a turn kind (see the
    prefix table above)."""
    if not isinstance(result, str):
        return "other"
    for prefix, kind in _KIND_PREFIXES:
        if result.startswith(prefix):
            return kind
    return "other"


def _tally(rows: dict, kind: str, label: str) -> None:
    r = rows.setdefault(kind, {"labelled": 0, "correct": 0,
                               "incorrect": 0, "corrected": 0})
    r["labelled"] += 1
    if label == "correct":
        r["correct"] += 1
    elif label == "corrected-by-retry":
        r["corrected"] += 1
    else:
        r["incorrect"] += 1


def _rate(r: dict):
    return r["correct"] / r["labelled"] if r["labelled"] else None


def eval_report(cfg: dict | None = None, decisions_file=None,
                labels_file=None) -> dict:
    """End-to-end outcome eval: labels.jsonl joined to decisions.jsonl
    on `ref` == decision `ts`. A turn's outcome is its latest label
    (correct | incorrect | corrected-by-retry; the last counts as not
    right first time). Returns per-kind and total counts plus the gate
    state from `[eval] gate_rate` / `gate_min_turns`."""
    decs = {d.get("ts"): d for d in _read_jsonl(
        decisions_file or config.DECISIONS)}
    latest, spoken = {}, {}
    for lab in _read_jsonl(labels_file or LABELS_FILE):
        ref, label = lab.get("ref"), lab.get("label", "")
        if ref and isinstance(ref, str) and isinstance(label, str):
            latest[ref] = label
            if lab.get("lang"):
                spoken[ref] = str(lab["lang"])
    rows, total = {}, {"labelled": 0, "correct": 0, "incorrect": 0,
                       "corrected": 0}
    langs = {}
    for ref, label in latest.items():
        dec = decs.get(ref) or {}
        kind = turn_kind(dec.get("result", ""))
        _tally(rows, kind, label)
        # the turn's language: a `lang` on the label, else the one the
        # decision recorded, else English (B23)
        _tally(langs, spoken.get(ref) or dec.get("lang") or "en", label)
    if set(langs) <= {"en"}:
        langs = {}
    for r in rows.values():
        for k in ("labelled", "correct", "incorrect", "corrected"):
            total[k] += r[k]
    for r in rows.values():
        r["rate"] = _rate(r)
    total["rate"] = _rate(total)
    for r in langs.values():
        r["rate"] = _rate(r)
    kinds = {k: rows[k] for k in KINDS if k in rows}

    ecfg = (cfg or {}).get("eval", {}) or {}
    try:
        min_turns = max(1, int(ecfg.get("gate_min_turns", 50)))
    except (TypeError, ValueError):
        min_turns = 50
    rawv = ecfg.get("gate_rate", "")
    raw = "" if rawv is None else str(rawv).strip()
    gate_rate, invalid = None, False
    if raw:
        try:
            if isinstance(rawv, bool):
                raise ValueError(raw)
            gate_rate = (float(raw[:-1]) / 100 if raw.endswith("%")
                         else float(raw))
            if not (math.isfinite(gate_rate) and 0 <= gate_rate <= 1):
                raise ValueError(raw)
        except ValueError:
            gate_rate, invalid = None, True
    gate = {"rate": gate_rate, "min_turns": min_turns,
            "status": "unset", "needs": 0}
    if invalid:
        gate["status"] = "invalid"
        gate["value"] = raw
    elif gate_rate is not None:
        gate["needs"] = max(0, min_turns - total["labelled"])
        ok = gate["needs"] == 0 and (total["rate"] or 0) >= gate_rate
        gate["status"] = "PASS" if ok else "FAIL"
    return {"kinds": kinds, "total": total, "gate": gate,
            "langs": dict(sorted(langs.items()))}


def _latest_labels(labels_file=None) -> dict:
    latest = {}
    for lab in _read_jsonl(labels_file or LABELS_FILE):
        ref, label = lab.get("ref"), lab.get("label", "")
        if ref and isinstance(ref, str) and isinstance(label, str):
            latest[ref] = (label, lab.get("note", ""))
    return latest


def _pattern(result: str) -> str:
    """A turn's failure pattern: the result's leading words with
    numbers collapsed, so "ACTED (3 steps): ..." and "ACTED (7 steps):
    ..." group together."""
    import re
    head = re.sub(r"\d+", "N", str(result or "").strip())
    return " ".join(head.split()[:4]) or "(empty)"


def eval_misses(decisions_file=None, labels_file=None,
                top: int = 10) -> list:
    """Phase 9: the labelled turns that were not right first time,
    grouped by turn kind and result pattern, biggest group first. Each
    group carries up to three example transcripts, so the top act
    failures are re-ranked from data rather than from memory."""
    decs = {d.get("ts"): d for d in _read_jsonl(
        decisions_file or config.DECISIONS)}
    groups = {}
    for ref, (label, note) in _latest_labels(labels_file).items():
        if label == "correct":
            continue
        d = decs.get(ref) or {}
        key = (turn_kind(d.get("result", "")), _pattern(d.get("result", "")))
        g = groups.setdefault(key, {"kind": key[0], "pattern": key[1],
                                    "count": 0, "retried": 0,
                                    "examples": []})
        g["count"] += 1
        g["retried"] += label == "corrected-by-retry"
        t = (d.get("transcript") or "").strip()
        if t and len(g["examples"]) < 3:
            g["examples"].append(t[:60])
    ranked = sorted(groups.values(),
                    key=lambda g: (-g["count"], g["kind"], g["pattern"]))
    return ranked[:max(1, int(top))]


def eval_unlabelled(decisions_file=None, labels_file=None,
                    limit: int = 20) -> list:
    """Recent turns with no label yet, newest first: what to label
    next to reach the gate's turn count. Turns the eval ignores (an
    empty result) are skipped."""
    labelled = set(_latest_labels(labels_file))
    rows = []
    for d in reversed(_read_jsonl(decisions_file or config.DECISIONS)):
        ref = d.get("ts")
        if not ref or ref in labelled or not d.get("result"):
            continue
        rows.append({"ref": ref, "kind": turn_kind(d["result"]),
                     "transcript": (d.get("transcript") or "")[:60],
                     "result": str(d["result"])[:60]})
        if len(rows) >= max(1, int(limit)):
            break
    return rows


def misses_text(rows: list) -> str:
    if not rows:
        return "no misses: every labelled turn was right first time"
    lines = ["top misses (not right first time):"]
    for g in rows:
        ex = "; ".join(repr(e) for e in g["examples"])
        lines.append(f"  {g['count']:>3}x {g['kind']:<7} {g['pattern']}"
                     + (f"  e.g. {ex}" if ex else ""))
    return "\n".join(lines)


def unlabelled_text(rows: list) -> str:
    if not rows:
        return "every logged turn is labelled"
    lines = ["unlabelled turns (newest first):"]
    for r in rows:
        lines.append(f"  {r['ref'][11:19]} {r['kind']:<7} "
                     f"{r['transcript']!r:<40} {r['result']}")
    return "\n".join(lines)


def eval_text(rep: dict) -> str:
    """Render eval_report for the terminal."""
    if not rep["total"]["labelled"]:
        return "no labels yet — use `wispd label set correct|incorrect`"

    def row(name, r):
        pct = "-" if r["rate"] is None else f"{100 * r['rate']:.0f}%"
        return (f"  {name:<8} {r['labelled']:>5} {r['correct']:>8} "
                f"{r['incorrect']:>9} {r['corrected']:>9} {pct:>6}")
    lines = ["end-to-end eval (latest label per turn):",
             f"  {'kind':<8} {'turns':>5} {'correct':>8} "
             f"{'incorrect':>9} {'retried':>9} {'rate':>6}"]
    lines += [row(k, r) for k, r in rep["kinds"].items()]
    lines.append(row("total", rep["total"]))
    if rep.get("langs"):
        lines.append("by language (first time correct):")
        lines += [row(k, r) for k, r in rep["langs"].items()]
    g = rep["gate"]
    if g["status"] == "invalid":
        lines.append(f"gate invalid: [eval] gate_rate {g['value']!r} is not "
                     "a number in 0..1 or a percentage like '60%'")
    elif g["status"] == "unset":
        lines.append("gate not set — set [eval] gate_rate to enable")
    else:
        msg = (f"gate {g['status']}: needs {100 * g['rate']:.0f}% over "
               f"{g['min_turns']}+ turns")
        if g["needs"]:
            msg += f" — needs {g['needs']} more labelled turns"
        lines.append(msg)
    return "\n".join(lines)


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
        lines = path.read_text(encoding="utf-8",
                               errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for l in lines:
        if not l.strip():
            continue
        try:
            v = json.loads(l)
        except ValueError:
            continue
        if isinstance(v, dict):
            out.append(v)
    return out


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
