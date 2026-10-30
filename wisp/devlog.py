"""Dev tab data: one read-only snapshot of the last turns (U4, KTD4).

`build()` tail-reads decisions.jsonl and trace.jsonl (never the whole
file), joins each turn's stage spans and latest label, and adds the
`wispd eval` tally, the share of finished turns rated, and the top
misses by calling the eval functions in `learn`. Nothing is cached:
every call recomputes. The reply is capped at MAX_BYTES.
"""
import json
import re
from datetime import datetime, timedelta, timezone

from . import config, learn, trace

DEFAULT_N, MAX_N = 20, 50
MAX_BYTES = 64 * 1024
TEXT_CHARS = 120
BLOCK = 64 * 1024
# Spans precede their decision line; stop reading the trace once events
# are this much older than the oldest wanted decision, or after this
# many bytes, whichever comes first.
TRACE_MARGIN = timedelta(minutes=10)
TRACE_MAX_BYTES = 8 * 1024 * 1024
# Spans that are aggregates, not stages of their own.
_TOTAL_SPAN = "done"
_AGGREGATE = {"done", "e2e"}
_STEPS = re.compile(r"\((\d+) steps?\)")


def tail_lines(path, stats=None, key="bytes"):
    """Yield the file's lines newest first, reading BLOCK bytes at a
    time from the end. `stats[key]` counts the bytes read."""
    try:
        f = open(path, "rb")
    except OSError:
        return
    with f:
        f.seek(0, 2)
        pos = f.tell()
        rest = b""
        while pos > 0:
            step = min(BLOCK, pos)
            pos -= step
            f.seek(pos)
            chunk = f.read(step)
            if stats is not None:
                stats[key] = stats.get(key, 0) + len(chunk)
            parts = (chunk + rest).split(b"\n")
            rest = parts[0]
            for ln in reversed(parts[1:]):
                if ln.strip():
                    yield ln
        if rest.strip():
            yield rest


def _parse(raw):
    try:
        v = json.loads(raw)
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def _clip(s, n=TEXT_CHARS):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def _ts(s):
    try:
        t = datetime.fromisoformat(str(s))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _spans(trace_file, want, oldest, stats):
    """({turn: [(step, ms), ...]}, {turn: {model, provider, ttft_ms, latency_ms}})
    in emission order for the wanted turns."""
    out = {t: [] for t in want}
    meta = {t: {} for t in want}
    floor = (oldest - TRACE_MARGIN) if oldest else None
    seen = 0
    for raw in tail_lines(trace_file, stats, "trace_bytes"):
        seen += len(raw) + 1
        ev = _parse(raw)
        if ev is None:
            continue
        if floor is not None:
            t = _ts(ev.get("ts"))
            if t is not None and t < floor:
                break
        if seen > TRACE_MAX_BYTES:
            break
        turn_id = ev.get("turn")
        if turn_id not in out:
            continue
        kind = ev.get("kind")
        if kind == "span" and isinstance(ev.get("ms"), (int, float)):
            out[turn_id].append((str(ev.get("step", "")), ev["ms"]))
        elif kind in ("brain", "act") and ev.get("step") in ("brain_call", "llm_call"):
            data = ev.get("data") or {}
            m = meta[turn_id]
            # Keep the first LLM call's TTFT/model (since we iterate newest-first, overwrite)
            if data.get("model"):
                m["model"] = data["model"]
            if data.get("provider") or data.get("brain"):
                m["provider"] = data.get("provider") or data.get("brain")
            if data.get("ttft_ms") is not None:
                m["ttft_ms"] = data["ttft_ms"]
            if data.get("latency_ms") is not None:
                m["latency_ms"] = data["latency_ms"]
    for v in out.values():
        v.reverse()          # collected newest first
    return out, meta


def _finished(d) -> bool:
    r = str(d.get("result") or "")
    return bool(r) and not r.startswith(learn._UNRATABLE)


def _turn(d, spans, lab, meta=None):
    stages, total = [], None
    seen = {}
    for name, ms in spans:
        if name == _TOTAL_SPAN:
            total = ms
        elif name not in _AGGREGATE:
            seen[name] = ms          # a repeated span: the last wins
    stages = [{"name": n, "ms": ms} for n, ms in seen.items()]
    if total is None and stages:
        total = sum(s["ms"] for s in stages)
    result = str(d.get("result") or "")
    m = _STEPS.search(result) if result.startswith("ACTED") else None
    label, note = lab if lab else ("none", "")
    route = ((d.get("answers") or {}).get("route") or {}).get("choice", "")
    meta = meta or {}
    row = {"id": str(d.get("turn") or ""), "turn": str(d.get("turn") or ""),
           "ts": d.get("ts", ""),
           "transcript": _clip(d.get("transcript")),
           "route": route if isinstance(route, str) else "",
           "kind": learn.turn_kind(result),
           "result": _clip(result), "label": label, "note": _clip(note),
           "total_ms": total, "stages": stages,
           "act_steps": int(m.group(1)) if m else None}
    if meta.get("model"):
        row["model"] = meta["model"]
    if meta.get("provider"):
        row["provider"] = meta["provider"]
    if meta.get("ttft_ms") is not None:
        row["ttft_ms"] = meta["ttft_ms"]
    elif "first_token" in seen:
        row["ttft_ms"] = seen["first_token"]
    if meta.get("latency_ms") is not None:
        row["latency_ms"] = meta["latency_ms"]
    return row


def build(cfg=None, n=None, decisions_file=None, labels_file=None,
          trace_file=None, max_bytes=MAX_BYTES, stats=None) -> dict:
    try:
        n = DEFAULT_N if n is None else int(n)
    except (TypeError, ValueError):
        n = DEFAULT_N
    n = max(1, min(MAX_N, n))
    decisions_file = decisions_file or config.DECISIONS
    labels_file = labels_file or learn.LABELS_FILE
    trace_file = trace_file or trace.TRACE_FILE

    rows = []
    for raw in tail_lines(decisions_file, stats, "decisions_bytes"):
        d = _parse(raw)
        if d is not None:
            rows.append(d)
            if len(rows) >= n:
                break
    labels = learn._latest_labels(labels_file)
    oldest = min((t for t in (_ts(d.get("ts")) for d in rows) if t),
                 default=None)
    spans, meta = _spans(trace_file, {str(d.get("turn")) for d in rows
                                      if d.get("turn")}, oldest, stats)
    turns = [_turn(d, spans.get(str(d.get("turn")), []),
                   labels.get(d.get("ts")),
                   meta.get(str(d.get("turn")))) for d in rows]

    rep = learn.eval_report(cfg or {}, decisions_file, labels_file)
    tot, g = rep["total"], rep["gate"]
    gate = {"labelled": tot["labelled"], "correct": tot["correct"],
            "rate": tot["rate"], "gate_rate": g.get("rate"),
            "min_turns": g["min_turns"], "status": g["status"],
            "needs": g["needs"], "kinds": rep["kinds"]}
    fin = rated = 0
    for d in learn._read_jsonl(decisions_file):
        if _finished(d):
            fin += 1
            rated += d.get("ts") in labels
    out = {"turns": turns, "gate": gate, "rated": rated, "finished": fin,
           "rated_share": (rated / fin) if fin else None,
           "misses": learn.eval_misses(decisions_file, labels_file),
           "truncated": False}
    while len(json.dumps(out)) > max_bytes and out["turns"]:
        out["turns"].pop()
        out["truncated"] = True
    if len(json.dumps(out)) > max_bytes:
        out["misses"] = []
    return out


def redact(out: dict) -> dict:
    """The same reply with every transcript, result text and note blanked:
    what a spawned agent peer may see (timings, labels, gate, miss counts)."""
    turns = [dict(t, transcript="", result="", note="")
             for t in out.get("turns") or []]
    # a miss's pattern is the result's first words (for dictation, what
    # the owner said), so it goes too; kind and counts stay
    misses = [dict(m, examples=[], pattern="")
              for m in out.get("misses") or []]
    return dict(out, turns=turns, misses=misses)
