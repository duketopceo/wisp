"""Suggestion miner — turn the activity window into "automate this?"
cards.

Pipeline per tick: read the recent activity window → cheap Jev gate
("is there a repeated workflow here?") → one batch call to the
configured `[sense] model` (defaults to a cheap remote, or a local
Gemma-class model via ollama/mlx) → dedup against never-list and prior
suggestions → surface the top pick on state.json so the orb/GUI can
ask. Nothing ever auto-executes: approval routes through the act loop,
"never" persists forever.

Guardrails (S6): `max_calls_per_day` caps paid calls, a failed tick is
logged and dropped, malformed model output is discarded.
"""
import hashlib
import json
import threading
import time
from datetime import datetime, timezone

from . import config, sense

SUGGESTIONS_FILE = config.DATA_DIR / "suggestions.jsonl"
NEVER_FILE = config.CFG_DIR / "never.json"
_BUDGET_FILE = config.DATA_DIR / "sense_budget.json"

_MINE_Q = {
    "mine": {
        "type": "choice",
        "instructions": "Does this activity window show a repeated "
                        "workflow worth offering to automate?",
        "criteria": {
            "yes": "the same multi-app or multi-step sequence repeats, "
                   "or one action recurs at a predictable time",
            "no": "sparse, idle, or one-off activity — nothing a "
                  "shortcut would help",
        },
    },
}

_PROMPT = """You are reviewing a privacy-first activity journal (window/app
names and summarized work blocks, no content). Find ONE workflow the
user repeats that a desktop assistant could automate or shortcut.

Reply with ONLY a JSON object, no prose:
{"suggestions": [{"title": "short title", "evidence": "what repeats",
"routine": "imperative instruction for a computer-use agent, e.g.
'open discord then go to workspace 2'", "confidence": 0.0-1.0}]}

Return {"suggestions": []} when nothing clearly repeats. Never suggest
anything destructive, credential-related, or that sends messages.

Activity window:
"""


def _load_json(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _never() -> set:
    return set(_load_json(NEVER_FILE, []))


def suppress(key: str) -> None:
    never = sorted(_never() | {key})
    try:
        NEVER_FILE.write_text(json.dumps(never, indent=2))
    except OSError:
        pass


def _key(s: dict) -> str:
    return hashlib.sha256(
        (s.get("title", "") + s.get("routine", "")).encode()
    ).hexdigest()[:16]


def _existing_keys() -> set:
    keys = set()
    try:
        for line in SUGGESTIONS_FILE.read_text().splitlines():
            try:
                keys.add(json.loads(line).get("key", ""))
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return keys


def _budget_ok(cfg: dict) -> bool:
    """max_calls_per_day ceiling — resets at local midnight."""
    cap = int(cfg.get("sense", {}).get("max_calls_per_day", "48"))
    today = datetime.now().strftime("%Y-%m-%d")
    b = _load_json(_BUDGET_FILE, {})
    if b.get("day") != today:
        b = {"day": today, "calls": 0}
    if b.get("calls", 0) >= cap:
        return False
    b["calls"] = b.get("calls", 0) + 1
    try:
        _BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
        _BUDGET_FILE.write_text(json.dumps(b))
    except OSError:
        pass
    return True


def _sense_cfg(cfg: dict) -> dict:
    """cfg copy with the brain pointed at [sense] model."""
    model = cfg.get("sense", {}).get(
        "model", "openrouter:google/gemini-2.5-flash")
    out = dict(cfg)
    out["brain"] = dict(cfg.get("brain", {}), default=model)
    return out


def _worth_mining(window: list, cfg: dict, log) -> bool:
    """Jev gate first (cheap, typed); on router failure fall back to a
    dumb event-count threshold so mining still works offline."""
    if len(window) < 4:
        return False
    summary = "\n".join(
        f"- {r.get('window', {}).get('app', '?')}: "
        f"{r.get('window', {}).get('title', '')[:60]}"
        + (" [dayflow blocks: "
           + "; ".join(b.get("title", "") for b in r["dayflow"]) + "]"
           if r.get("dayflow") else "")
        for r in window[-60:])
    try:
        from . import pipeline
        answers = pipeline.ask_jev(
            "activity window for pattern mining", "typesafe/jev-1.13",
            _MINE_Q, context=summary)
        return answers.get("mine", {}).get("choice") == "yes"
    except Exception as e:
        log(f"suggest: jev gate failed ({e}) — count fallback")
        return len(window) >= 8


def mine(cfg: dict, state=None, log=None) -> list:
    """One mining pass → new suggestions (also publishes the top one to
    state for the orb card). Empty list = nothing worth asking."""
    log = log or (lambda m: None)
    window = sense.read_window(
        hours=float(cfg.get("sense", {}).get("window_h", "3")))
    if not _worth_mining(window, cfg, log):
        return []
    if not _budget_ok(cfg):
        log("suggest: daily call budget exhausted")
        return []
    from . import brain
    body = "\n".join(json.dumps(r) for r in window[-200:])
    try:
        text = brain.chat(
            [{"role": "user", "content": _PROMPT + body}],
            _sense_cfg(cfg), timeout=60)["content"]
    except Exception as e:
        log(f"suggest: model call failed: {e}")
        return []
    try:
        start = text.index("{")
        data = json.loads(text[start:text.rindex("}") + 1])
        found = data.get("suggestions") or []
    except (ValueError, json.JSONDecodeError):
        log("suggest: malformed model output discarded")
        return []
    never, existing = _never(), _existing_keys()
    new = []
    for s in found[:3]:
        if not isinstance(s, dict) or not s.get("routine"):
            continue
        k = _key(s)
        if k in never or k in existing:
            continue
        s["key"], s["status"] = k, "new"
        s["ts"] = datetime.now(timezone.utc).isoformat()
        new.append(s)
    for s in new:
        try:
            SUGGESTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with SUGGESTIONS_FILE.open("a") as f:
                f.write(json.dumps(s) + "\n")
        except OSError:
            pass
    if new and state is not None:
        top = new[0]
        try:
            state.transition(
                "suggestion",
                suggestion={"key": top["key"], "title": top.get("title", ""),
                            "evidence": top.get("evidence", "")},
                choices=["suggestion:automate", "suggestion:not now",
                         "suggestion:never"],
                result=f"suggestion: {top.get('title', '')}")
        except Exception:
            pass
    return new


def resolve_pick(pick: str, cfg: dict, state=None, log=None) -> str:
    """User answered a suggestion card. Pick is
    'suggestion:<act>' (current card) or 'suggestion:<act>:<key>'
    (a specific pending suggestion from the GUI/TUI list)."""
    log = log or (lambda m: None)
    parts = pick.split(":")
    kind = parts[1].strip() if len(parts) > 1 else ""
    sugg = getattr(state, "suggestion", None) or {}
    key = parts[2].strip() if len(parts) > 2 else sugg.get("key", "")
    if kind == "never":
        if key:
            suppress(key)
        return "OK (never suggest that again)"
    if kind == "automate":
        rec = _find_suggestion(key)
        if not rec:
            return "SKIP (suggestion expired)"
        _mark(key, "accepted")
        return ("RUN " + rec["routine"])  # caller runs the act loop
    _mark(key, "snoozed")
    return "OK (snoozed)"


def _find_suggestion(key: str) -> dict | None:
    try:
        for line in reversed(SUGGESTIONS_FILE.read_text().splitlines()):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("key") == key:
                return rec
    except OSError:
        pass
    return None


def _mark(key: str, status: str) -> None:
    try:
        with SUGGESTIONS_FILE.open("a") as f:
            f.write(json.dumps({"key": key, "status": status,
                                "ts": datetime.now(timezone.utc)
                                .isoformat()}) + "\n")
    except OSError:
        pass


def pending(path=SUGGESTIONS_FILE) -> list:
    """Latest-status suggestions for GUI/TUI surfaces."""
    latest = {}
    try:
        for line in path.read_text().splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            k = rec.get("key", "")
            if not k:
                continue
            latest[k] = {**latest.get(k, {}), **rec}
    except OSError:
        pass
    return list(latest.values())


def run(cfg: dict, stop: threading.Event, state=None, log=None) -> None:
    """Daemon thread: mine every [sense] mine_every_s (default 45min).
    Single-flight, failure-swallowing, budget-capped via mine()."""
    log = log or (lambda m: None)
    every = int(cfg.get("sense", {}).get("mine_every_s", "2700"))
    while not stop.wait(max(300, every)):
        if state is not None and getattr(state, "status", "") \
                in ("listening", "transcribing", "deciding",
                    "acting", "awaiting_choice", "speaking"):
            continue  # don't pop a card mid-turn
        try:
            new = mine(cfg, state=state, log=log)
            if new:
                log(f"suggest: {len(new)} new suggestion(s) — "
                    f"top: {new[0].get('title', '')!r}")
        except Exception as e:
            log(f"suggest error: {e}")
    log("suggest: stopped")
