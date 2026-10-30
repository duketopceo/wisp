"""Dev tuning mode: the task-list runner (U2).

One run is one pass over a plain text task list (one task per line, `#`
comments, blank lines skipped). A run lives in a daemon thread, one at a
time, and drives each task as an ordinary typed turn through
`pipeline.run_listen` with no confirmation channel and a per-run copy of
the config (KTD2-KTD4):

  - `wait_for_choice=None`: every confirm, ask and handoff gate answers
    "no" at once, so a step that needs the owner ends as `stopped`;
  - the copy denies text entry, key presses, shell, external calls,
    posting and closing windows (policy.preempted reads `[dev]
    deny_tools`), turns trajectory feedback off and forces the act
    router so a task is pre-screened and never routed through a model;
  - a task whose route pre-screens as agent, learn, setting, walkthrough
    or dictation is skipped as `stopped` and never runs.

One JSON line per task goes to dev_runs/<run_id>.jsonl in the data dir.
`judge`, `drift` and `cost` are left null for the later units. The
owner's config is never written.
"""
import copy
import json
import secrets
import threading
import time
from datetime import datetime, timezone

from . import config, devsession

DENY_TOOLS = ("type_text", "key", "shell", "mcp_call", "post_send",
              "close", "fill", "browser")
OUTCOMES = ("success", "stopped", "incomplete")   # `wrong tries`: U3
# routes a run will drive; anything else is skipped as `stopped`
_RUNNABLE = ("act", "answer", "launch", "tool")
_TRACE_MAX_BYTES = 2 * 1024 * 1024
_STOP_MARKS = ("needs user confirmation", "declined by user",
               "no handoff channel", "handoff timed out",
               "confirmation timed out", "dev run denies")
_OK_PREFIXES = ("ACTED", "LAUNCHED", "ANSWERED")
_STOP_PREFIXES = ("SKIP", "REFUSED", "BLOCKED", "CANCELLED")

_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop = threading.Event()
_summary: dict = {}


# -- task list -------------------------------------------------------------

def read_tasks(path) -> list:
    """The goals in a task file: one per line, `#` comments and blank
    lines dropped, whitespace collapsed, 300 chars at most (the `ask`
    cap)."""
    out = []
    for line in open(path, encoding="utf-8"):
        t = " ".join(line.split())
        if t and not t.startswith("#"):
            out.append(t[:300])
    return out


# -- safety ----------------------------------------------------------------

def run_config(cfg: dict, run_id: str) -> dict:
    """A deep copy of `cfg` for one run. The owner's own config object
    is never changed."""
    c = copy.deepcopy(cfg)
    c.setdefault("dev", {})
    c["dev"]["run_id"] = run_id
    c["dev"]["deny_tools"] = list(DENY_TOOLS)
    c.setdefault("traj", {})["enabled"] = "false"
    c.setdefault("agent", {})["allow_shell"] = "false"
    c.setdefault("brain", {})["router"] = "act"
    return c


def prescreen(text: str, cfg: dict) -> tuple:
    """(route, skip): classify a task without running it. Read-only
    calls into the router's own pure functions."""
    from . import route as _route
    from . import stage_route
    try:
        fixed = stage_route.fixed_route(text, "act")
    except Exception:
        fixed = None
    if fixed and fixed[0] != "act":
        return fixed[0], True
    if fixed and fixed[1]:
        return "act", False            # an explicit "wisp agent ..." prefix
    apps = None
    try:
        apps = (config.load_harness() or {}).get("apps")
    except Exception:
        pass
    fast = None
    try:
        fast = stage_route.fast_route(text, apps, cfg)
    except Exception:
        pass
    if fast:
        choice = (fast[0].get("route") or {}).get("choice") or "answer"
        return choice, choice not in _RUNNABLE
    try:
        h = _route.heuristic(text, apps)
    except Exception:
        return "act", False
    if h.get("route") in ("agent", "learn", "dictation"):
        return h["route"], True
    return "act", False


# -- reading back what a turn did -------------------------------------------

def _decision(turn_id: str) -> dict | None:
    from . import devlog
    for i, raw in enumerate(devlog.tail_lines(config.DECISIONS)):
        if i > 400:
            break
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("turn") == turn_id:
            return d
    return None


def _trace_steps(turn_id: str) -> tuple:
    """(steps, stops) for one turn from the trace, oldest first. A stop
    is a policy gate refusal (needs confirmation, denied, no handoff)."""
    from . import devlog, trace
    stats: dict = {}
    evs = []
    for raw in devlog.tail_lines(trace.TRACE_FILE, stats):
        if stats.get("bytes", 0) > _TRACE_MAX_BYTES:
            break
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get("turn") == turn_id:
            evs.append(e)
    evs.reverse()
    steps, stops = [], []
    for e in evs:
        d = e.get("data") or {}
        if e.get("step") == "tool_call":
            steps.append({"tool": str(d.get("name", "")),
                          "arg": str(d.get("args", ""))[:120],
                          "result": None, "ms": None})
        elif e.get("step") == "tool_result":
            for s in reversed(steps):
                if s["tool"] == d.get("name") and s["result"] is None:
                    s["result"] = str(d.get("result", ""))[:120]
                    s["ms"] = e.get("ms")
                    break
        elif e.get("step") == "gate_stop":
            res = str(d.get("result", ""))[:120]
            stops.append(res)
            steps.append({"tool": str(d.get("tool", "")), "arg": "",
                          "result": res, "ms": None, "stopped": True})
    return steps, stops


def classify(result: str, stops: list) -> str:
    """The outcome before judging: success, stopped or incomplete."""
    if stops or any(m in (result or "") for m in _STOP_MARKS):
        return "stopped"
    r = (result or "").strip()
    if r.startswith(_STOP_PREFIXES):
        return "stopped"
    if r.startswith(_OK_PREFIXES):
        return "success"
    return "incomplete"     # budget, interrupt, stalled, error, nothing


# -- the run ---------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append(path, row: dict) -> None:
    from . import private
    with private.open_append(path) as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")


def store_path(run_id: str):
    return config.DATA_DIR / "dev_runs" / f"{run_id}.jsonl"


def start(cfg: dict, st, ctl: dict, path, run_listen=None) -> dict:
    """Begin a run over the task file at `path`. Refused when the
    session is off, a run is going, a turn is in flight, or the list is
    unreadable or empty."""
    global _thread
    if not devsession.is_on():
        return {"ok": False, "error": "dev_off"}
    try:
        goals = read_tasks(path)
    except OSError as e:
        return {"ok": False, "error": f"cannot read task list: {e.strerror}"}
    if not goals:
        return {"ok": False, "error": "no tasks in the list"}
    with _lock:
        if _thread is not None and _thread.is_alive():
            return {"ok": False, "error": "busy"}
        with ctl["rec_lock"]:
            if ctl["rec"] is not None or ctl["busy"].is_set():
                return {"ok": False, "error": "busy"}
            ctl["busy"].set()
        run_id = (datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                  + "-" + secrets.token_hex(2))
        _stop.clear()
        _summary.clear()
        _summary.update({"run_id": run_id, "tasks": len(goals), "done": 0,
                         "stopped": False, "running": True,
                         "path": str(store_path(run_id))})
        _thread = threading.Thread(
            target=_run, name="dev-run", daemon=True,
            args=(cfg, st, ctl, run_id, goals, run_listen))
        _thread.start()
    return {"ok": True, "run_id": run_id, "tasks": len(goals)}


def stop() -> dict:
    """Finish the task in flight, then end the run."""
    with _lock:
        alive = _thread is not None and _thread.is_alive()
    if not alive:
        return {"ok": False, "error": "not_running"}
    _stop.set()
    return {"ok": True, "stopping": True}


def wait(timeout: float | None = None) -> bool:
    t = _thread
    if t is not None:
        t.join(timeout)
        return not t.is_alive()
    return True


def last_summary() -> dict:
    return dict(_summary)


def reset() -> None:
    """Test hook: end any run and forget it."""
    global _thread
    _stop.set()
    wait(5)
    _thread = None
    _summary.clear()
    _stop.clear()


def _publish_dev(st) -> None:
    try:
        st.publish(None, dev=devsession.state_field())
    except Exception:
        pass


def _run(cfg, st, ctl, run_id, goals, run_listen) -> None:
    if run_listen is None:
        from . import pipeline
        run_listen = pipeline.run_listen
    rcfg = run_config(cfg, run_id)
    out = store_path(run_id)
    try:
        for i, goal in enumerate(goals):
            if _stop.is_set():
                _summary["stopped"] = True
                break
            row = _one(rcfg, st, ctl, run_id, i, goal, run_listen)
            _append(out, row)
            _summary["done"] = i + 1
            if ctl["interrupt"].is_set():     # the owner interrupted
                _summary["stopped"] = True
                break
        else:
            if _stop.is_set():
                _summary["stopped"] = True
    finally:
        # a stopped run still counts: it produced a report
        devsession.complete_run()
        _summary["running"] = False
        ctl["busy"].clear()
        _publish_dev(st)


def _one(rcfg, st, ctl, run_id, index, goal, run_listen) -> dict:
    started = _now()
    t0 = time.monotonic()
    route, skip = prescreen(goal, rcfg)
    row = {"run_id": run_id, "index": index, "goal": goal, "turn": None,
           "route": route, "result": None, "steps": [], "outcome": None,
           "timing_ms": {}, "started": started, "ended": None,
           "judge": None, "drift": None, "cost": None}
    if skip:
        row.update(result=f"SKIP (route {route} is not run in dev mode)",
                   outcome="stopped")
    else:
        from . import cancel, trace
        tid = st.begin_turn()
        row["turn"] = tid
        ctl["interrupt"].clear()
        token = ctl["token"] = cancel.CancelToken()
        try:
            run_listen(rcfg, st, wait_for_choice=None,
                       interrupted=ctl["interrupt"].is_set,
                       turn_id=tid, cancel=token, typed=goal)
        except Exception as e:
            row["error"] = f"{type(e).__name__}: {e}"[:200]
        d = _decision(tid)
        steps, stops = _trace_steps(tid)
        row["steps"] = steps
        if d:
            row["result"] = d.get("result")
            r = ((d.get("answers") or {}).get("route") or {}).get("choice")
            row["route"] = r or route
            if isinstance(d.get("timing_ms"), dict):
                row["timing_ms"] = dict(d["timing_ms"])
        row["outcome"] = classify(row["result"] or "", stops)
    row["timing_ms"]["wall"] = round((time.monotonic() - t0) * 1000)
    row["ended"] = _now()
    return row
