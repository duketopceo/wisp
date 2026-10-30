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
    deny_tools`) and turns trajectory feedback off. The owner's router
    setting is kept, so a run measures the real routing (the regex fast
    path included);
  - a task whose route pre-screens as agent, learn, setting, walkthrough
    or dictation is skipped as `stopped` and never runs. The pre-screen
    only calls the router's pure functions.

After each task the judge (wisp.devjudge) reads the end-of-turn screen,
and drift is flagged (wisp.devreport). One JSON line per task goes to
dev_runs/<run_id>.jsonl in the data dir. `--vs key=value` runs the list
a second time on a config copy with that one override (arm `b`); both
arms count as one run. The owner's config is never written.
"""
import copy
import json
import re
import secrets
import threading
import time
from datetime import datetime, timezone

from . import config, devsession, ipc

# A run is unattended on the owner's live desktop, so it is an allow
# list: navigation, reading and media only. Every other tool, including
# any added later, is denied and the task ends as stopped.
ALLOW_TOOLS = frozenset((
    "click", "move", "scroll", "screenshot", "observe", "ground",
    "launch", "focus", "tab", "media", "workspace",
    "recall", "memory_read", "skill_list", "skill_view",
    "search_files", "task_status", "codegraph"))


def deny_tools() -> list:
    """Every registered tool a run may not call (registry minus the
    allow list), plus the browser lane, which runs outside the registry."""
    from . import tools
    return sorted((set(tools.REGISTRY) - ALLOW_TOOLS) | {"browser"})
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
    with open(path, encoding="utf-8") as f:
        for line in f:
            t = " ".join(line.split())
            if t and not t.startswith("#"):
                out.append(t[:300])
    return out


# -- safety ----------------------------------------------------------------

def parse_vs(vs: str) -> tuple:
    """`section.key=value` -> (section, key, value). One override only;
    the safety and spend settings and the run's own `[dev]` and `[traj]`
    keys cannot be overridden. Raises ValueError."""
    k, eq, v = str(vs).partition("=")
    k = k.strip()
    sec, dot, key = k.partition(".")
    if not eq or not dot or not sec or not key or "." in key \
            or not re.fullmatch(r"[A-Za-z0-9_-]+", sec) \
            or not re.fullmatch(r"[A-Za-z0-9_-]+", key):
        raise ValueError("--vs wants one section.key=value, "
                         "like brain.default=openrouter:acme/model")
    if ipc.is_safety_config_key(k) or sec in ("dev", "traj"):
        raise ValueError(f"--vs cannot change {k}")
    return sec, key, v.strip()


def run_config(cfg: dict, run_id: str, vs=None) -> dict:
    """A deep copy of `cfg` for one run, with the one `--vs` override
    applied when given. The owner's own config object is never
    changed."""
    c = copy.deepcopy(cfg)
    c.setdefault("dev", {})
    c["dev"]["run_id"] = run_id
    c["dev"]["deny_tools"] = deny_tools()
    c.setdefault("traj", {})["enabled"] = "false"
    c.setdefault("agent", {})["allow_shell"] = "false"
    if vs:
        sec, key, val = vs
        c.setdefault(sec, {})[key] = val
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
    llm = {}
    for e in evs:
        d = e.get("data") or {}
        if e.get("step") in ("brain_call", "llm_call") and not llm:
            llm = {"provider": d.get("provider") or d.get("brain"),
                   "model": d.get("model"),
                   "ttft_ms": d.get("ttft_ms"),
                   "latency_ms": d.get("latency_ms", e.get("ms"))}
        if e.get("step") == "tool_call":
            steps.append({"tool": str(d.get("name", "")),
                          "arg": str(d.get("args", ""))[:120],
                          "result": None, "ms": None})
        elif e.get("step") == "tool_result":
            full = str(d.get("result", ""))
            for s in reversed(steps):
                if s["tool"] == d.get("name") and s["result"] is None:
                    s["result"] = full[:120]
                    s["ms"] = e.get("ms")
                    if _verify_failed(full):
                        s["verify_failed"] = True     # past the 120 chars
                    break
        elif e.get("step") == "gate_stop":
            res = str(d.get("result", ""))[:120]
            stops.append(res)
            steps.append({"tool": str(d.get("tool", "")), "arg": "",
                          "result": res, "ms": None, "stopped": True})
    return steps, stops, llm


def _verify_failed(result: str) -> bool:
    return "verify FAILED" in result \
        or '"verdict":"missed"' in result.replace(" ", "")


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


def start(cfg: dict, st, ctl: dict, path, run_listen=None, judge=None,
          vs=None) -> dict:
    """Begin a run over the task file at `path`. Refused when the
    session is off, a run is going, a turn is in flight, or the list is
    unreadable or empty. `vs` ("section.key=value") runs the list twice,
    the second time with that one override."""
    global _thread
    if not devsession.is_on():
        return {"ok": False, "error": "dev_off"}
    override = None
    if vs is not None:
        try:
            override = parse_vs(vs)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
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
        total = len(goals) * (2 if override else 1)
        _summary.update({"run_id": run_id, "tasks": total, "done": 0,
                         "stopped": False, "running": True,
                         "judge_capped": False,
                         "path": str(store_path(run_id))})
        try:
            if judge is None:
                from . import devjudge
                judge = devjudge.Judge(cfg)
            _thread = threading.Thread(
                target=_run, name="dev-run", daemon=True,
                args=(cfg, st, ctl, run_id, goals, run_listen, judge,
                      override, vs))
            _thread.start()
        except Exception:
            # never leave the daemon stuck busy on a run that never ran
            ctl["busy"].clear()
            _summary["running"] = False
            raise
    return {"ok": True, "run_id": run_id, "tasks": total}


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


def _run(cfg, st, ctl, run_id, goals, run_listen, judge=None,
         override=None, vs=None) -> None:
    if run_listen is None:
        from . import pipeline
        run_listen = pipeline.run_listen
    arms = ([("a", run_config(cfg, run_id)),
             ("b", run_config(cfg, run_id, override))] if override
            else [(None, run_config(cfg, run_id))])
    out = store_path(run_id)
    try:
        from . import devreport
        apps = devreport.app_skills()
    except Exception:
        apps = set()
    done = 0
    try:
        for arm, rcfg in arms:
            for i, goal in enumerate(goals):
                if _stop.is_set() or not devsession.is_on():
                    _summary["stopped"] = True
                    return
                row = _one(rcfg, st, ctl, run_id, i, goal, run_listen,
                           judge, apps)
                if arm:
                    row["arm"], row["vs"] = arm, vs
                _append(out, row)
                done += 1
                _summary["done"] = done
                _summary["judge_capped"] = bool(
                    getattr(judge, "capped", False))
                if ctl["interrupt"].is_set():     # the owner interrupted
                    _summary["stopped"] = True
                    return
        if _stop.is_set():
            _summary["stopped"] = True
    finally:
        # a stopped run still counts: it produced a report
        devsession.complete_run()
        _summary["running"] = False
        ctl["busy"].clear()
        _publish_dev(st)


def _judge(judge, goal, steps) -> dict:
    try:
        return judge.judge(goal, steps)
    except Exception as e:
        return {"outcome": "unjudged", "reason":
                f"judge failed: {type(e).__name__}", "model": None,
                "cost_usd": 0.0}


def _drift(goal, row, apps) -> dict:
    j = (row.get("judge") or {}).get("outcome")
    eff = j if j in ("success", "stopped", "incomplete", "wrong_tries") \
        else row.get("outcome")
    try:
        from . import devreport
        return devreport.drift(goal, row.get("steps") or [], eff, apps)
    except Exception:
        return {"suspected": False}


def _one(rcfg, st, ctl, run_id, index, goal, run_listen, judge=None,
         apps=()) -> dict:
    from . import ledger
    started = _now()
    spend0 = ledger.session_totals()["cost"]
    t0 = time.monotonic()
    route, skip = prescreen(goal, rcfg)
    row = {"run_id": run_id, "index": index, "goal": goal, "turn": None,
           "route": route, "result": None, "steps": [], "outcome": None,
           "timing_ms": {}, "started": started, "ended": None,
           "judge": None, "drift": None, "cost": None}
    if skip:
        row.update(result=f"SKIP (route {route} is not run in dev mode)",
                   outcome="stopped")
        row["judge"] = {"outcome": "unjudged", "reason": "not run",
                        "model": None, "cost_usd": 0.0}
    else:
        from . import cancel, trace
        tid = st.begin_turn()
        row["turn"] = tid
        ctl["interrupt"].clear()
        token = ctl["token"] = cancel.CancelToken()
        # confirms the owner granted in their own session must not
        # carry into an unattended task
        # (empty the same set in place: st may be a proxy over the bus
        # state, so rebinding the attribute would not reach the gate)
        held = getattr(st, "confirmed", None)
        granted = set(held) if held is not None else None
        if held is not None:
            held.clear()
        try:
            run_listen(rcfg, st, wait_for_choice=None,
                       interrupted=ctl["interrupt"].is_set,
                       turn_id=tid, cancel=token, typed=goal)
        except Exception as e:
            row["error"] = f"{type(e).__name__}: {e}"[:200]
        finally:
            if held is not None:
                held.clear()
                held.update(granted)
        d = _decision(tid)
        steps, stops, llm = _trace_steps(tid)
        row["steps"] = steps
        if llm.get("model"):
            row["model"] = llm["model"]
        if llm.get("provider"):
            row["provider"] = llm["provider"]
        if d:
            row["result"] = d.get("result")
            r = ((d.get("answers") or {}).get("route") or {}).get("choice")
            row["route"] = r or route
            if isinstance(d.get("timing_ms"), dict):
                row["timing_ms"] = dict(d["timing_ms"])
        if llm.get("ttft_ms") is not None:
            row["timing_ms"]["ttft"] = llm["ttft_ms"]
        if llm.get("latency_ms") is not None:
            row["timing_ms"]["llm"] = llm["latency_ms"]
        row["outcome"] = classify(row["result"] or "", stops)
        task_usd = max(0.0, ledger.session_totals()["cost"] - spend0)
        row["judge"] = (_judge(judge, goal, steps) if judge is not None
                        else {"outcome": "unjudged", "reason": "no judge",
                              "model": None, "cost_usd": 0.0})
        row["cost"] = {"task_usd": round(task_usd, 6),
                       "judge_usd": round(float(
                           row["judge"].get("cost_usd") or 0.0), 6)}
    row["cost"] = row["cost"] or {"task_usd": 0.0, "judge_usd": 0.0}
    row["drift"] = _drift(goal, row, apps)
    row["timing_ms"]["wall"] = round((time.monotonic() - t0) * 1000)
    row["ended"] = _now()
    return row
