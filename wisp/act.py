"""Act route: a bounded, guarded conversational tool-call loop.

Jev decides the user wants a multi-step desktop task; this loop hands the
toolbelt to the chat model as OpenAI-style tools and lets it drive. Every
proposed call re-enters the same gates execute() uses — denylist,
allow_shell, risk tier — so the model can ask for anything but only
safe/confirmed work runs.

Bounds: MAX_STEPS tool calls total, MAX_ERRORS consecutive tool failures,
MAX_SECONDS wall-clock and (when set) act_max_usd of model spend per run
— a tripped bound publishes a `failed` stream entry with reason `budget`
and the step list so far. `ask_user` lets the model hold a conversation
mid-loop: it parks on the same prompt broker the confirm card uses and
the pick/typed/spoken answer comes back as the tool result. Every step
is published to state.json and recorded in decisions.jsonl by the
caller.
"""
import base64
import json
import re
import time
import urllib.error
import urllib.request

from . import bgwriter, cancel, config, cua_safety, grounding, ledger, \
    policy, realinput, tools
from . import delivery as _delivery
from . import state as _state

# Defaults; the daemon reads [agents] act_max_steps, act_max_errors,
# act_max_parse_misses, act_max_seconds and act_max_usd
# (wisp/settings_schema.py) through _limit()/_limit_f().
MAX_STEPS = 8
MAX_ERRORS = 2
MAX_PARSE_MISSES = 1
MAX_SECONDS = 600          # wall-clock cap for one run; 0 = off
MAX_USD = 0.0              # per-run paid-model spend cap; 0 = off
MAX_IMAGES = 3  # cap retained screenshots in the message window
# tools whose success may change what's on screen → re-observe before
# the next pointer step
_SCREEN_CHANGING = {"click", "move", "type_text", "key", "launch",
                    "focus", "close", "workspace", "shell", "fill",
                    "post_send"}

SYSTEM = ("You are Wisp's hands on a Linux desktop (Hyprland). Complete "
          "the user's task using the provided tools — keep steps minimal "
          "and prefer safe tools. Take a screenshot first when the task "
          "needs on-screen targets; click/move take 'x,y' in that "
          "screenshot's pixels or a target name (e.g. 'monitor icon in menu bar') "
          "which automatically grounds via Clef/Jev noul probabilistic centering. "
          "Never click twice off the same screenshot "
          "— after anything that changes the screen (click, key, type, "
          "launch, focus, workspace, shell), re-screenshot before the "
          "next pointer action. A GUIDE result means the ghost cursor "
          "is parked there for the user to click — treat it as done, "
          "not an error, and continue or finish. CLICKED echoes the id "
          "of the element actually hit — if it is not the target you "
          "aimed at, re-aim from the image and click again rather than "
          "declaring success. For a dropdown/select, input, or textarea "
          "with a known element id, use fill '<id> <value>' — it sets "
          "the value directly in one step; click+key navigation is the "
          "fallback, typing into a select does nothing. In DOM mode the "
          "screen caption lists element ids — click '<id>' and fill "
          "'<id> <value>' resolve elements directly, so only screenshot "
          "when your target is not in the legend. When done, reply with "
          "one short sentence describing the outcome. If a tool is "
          "refused or skipped, do not retry it; work around or report "
          "the block. A fresh screenshot after a mutating step is the "
          "verify pass: check the last action landed (target changed "
          "or gone) before planning the next step — if it clearly did "
          "not land, re-aim and retry instead of continuing. When the "
          "task needs information only the user has (a choice between "
          "real options, missing credentials, an ambiguous target), "
          "call ask_user with the question — 'question' or 'question | "
          "option | option' — the user answers by voice or click and "
          "the reply comes back as the tool result; keep going with "
          "it. (Reply 'ASK_USER: <question>' instead only when the run "
          "must END for the answer — the next turn resumes the goal.) "
          "Do not guess or stall. The screen image attached to the "
          "first message shows the desktop at trigger time — use it "
          "to find the app and targets instead of asking which app is "
          "meant.")


def _post(messages: list, cfg: dict) -> dict:
    """Chat call through the configured brain provider with toolbelt
    schemas (U6). Returns the provider message object."""
    from . import brain
    return brain.chat(messages, cfg,
                      tools=tools.tool_schemas(), timeout=60)["raw"]


def _gate(name: str, arg: str, cfg: dict, confirm,
          state=None, batch=(), ctx=None) -> str | None:
    """Returns a refusal string when the call is blocked, else None.
    All tier logic lives in wisp/policy.py (U3) — the denylist and
    allow_shell preempt there before a tier is consulted, the autonomy
    mode + [cua] confirm=always promotion apply, T2 checkpoints batch
    the reply's pending gated steps into one card, and T3 hands the
    step to the user."""
    return policy.gate(name, arg, cfg, confirm, state=state,
                       batch=batch, ctx=ctx)


def _name_arg(call: dict) -> tuple:
    """(tool name, arg) from one provider tool_call object."""
    fn = call.get("function", {})
    name = fn.get("name", "")
    try:
        arg = json.loads(fn.get("arguments") or "{}").get("arg", "")
    except json.JSONDecodeError:
        arg = ""
    return name, arg


def run_act_loop(task: str, cfg: dict, state=None,
                 harness: dict | None = None, confirm=None,
                 initial_image: str | None = None,
                 interrupted=None,
                 steps_out: list | None = None,
                 ask=None) -> str:
    """Drive the chat model through the toolbelt until it finishes or a
    bound trips. `confirm(prompt)->bool` asks the user (choice widget /
    IPC) when wired; without it mutating calls skip. `ask(question,
    options)->pick|None` is the in-loop conversation channel (U4 —
    `confirm.make_ask` on the same broker); without it `ask_user` calls
    resolve NO_ANSWER. `steps_out`, if a list, receives the run's step
    records for judging/replay."""
    from . import brain
    at_mode = brain.action_text(cfg)
    if not brain.supports_tools(cfg) and not at_mode:
        p = brain.provider(cfg)
        return (f"SKIP (brain provider '{p['name']}' does not support "
                f"tools — set [brain.{p['name']}] tools=true or pick a "
                f"capable provider)")
    system = SYSTEM
    from . import trajectories, context as _ctx, action_stats as _ast
    focus = _ctx.snapshot(cfg)
    if focus:
        system += "\n\n" + focus
        app_key = _ctx.focused_app()
        stats_blk = _ast.block_for(app_key)
        if stats_blk:
            system += "\n" + stats_blk
    prior = trajectories.context_for(task, cfg=cfg)
    if prior:
        system += "\n\n" + prior
    from . import train as _train
    hint = _train.hint_for(task, _surface(cfg),
                           model=brain.provider(cfg).get("model", ""))
    if hint:
        system += "\n\n" + hint
    from . import goals as _goals
    goal_txt = _goals.context_text()
    # U4: a follow-up turn sees the previous turn's outcome, not just
    # the open goal — corrections already carry the failed attempt, so
    # this is the general "previous turn did X" context
    prev_txt = _prev_turn()
    user_msg = "\n\n".join(t for t in (goal_txt, prev_txt, task) if t)
    p = brain.provider(cfg)
    vision = p.get("vision", "false") == "true"
    if not initial_image and vision:
        # no trigger-time image (direct/IPC path) — observe before the
        # first model call so the loop never plans blind
        shot = tools.run("screenshot", "", cfg, harness)
        if shot.startswith("SHOT "):
            import pathlib as _pl
            try:
                initial_image = base64.b64encode(
                    _pl.Path(shot[5:].strip()).read_bytes()).decode()
            except OSError:
                pass
    if initial_image:
        # screen at trigger — the model sees the app, no "what app" ask.
        # Name the pixel space: models click more accurately when they
        # know the image's true dimensions.
        dims = _png_dims(initial_image)
        cap = ""
        if dims:
            cap = (f"[screen image: {dims[0]}x{dims[1]} px — "
                   "click/move x,y use THESE pixels")
            if cfg.get("screen", {}).get("dom_page"):
                els = cfg["screen"].get("dom_els") or []
                cap += ("; elements: " + "; ".join(els) +
                        " — click the printed center" if els else
                        "; each element is labeled with its id and "
                        "center (x,y)")
            cap += "]\n\n"
        user_msg = [{"type": "text", "text": cap + user_msg},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,"
                                          f"{initial_image}"}}]
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user_msg}]
    steps = steps_out if steps_out is not None else []
    if steps_out is not None:
        steps_out.clear()
    errors = 0
    parse_misses = 0
    max_steps = _limit(cfg, "act_max_steps", MAX_STEPS)
    max_errors = _limit(cfg, "act_max_errors", MAX_ERRORS)
    max_parse_misses = _limit(cfg, "act_max_parse_misses", MAX_PARSE_MISSES)
    max_seconds = _limit_f(cfg, "act_max_seconds", MAX_SECONDS)
    max_usd = _limit_f(cfg, "act_max_usd", MAX_USD)
    t0 = time.monotonic()
    # ledger's in-process session counters cover every brain call the
    # loop makes; snapshot now and cap the run's DELTA (a stale global
    # total can't trip a fresh run)
    spend0 = ledger.session_totals().get("cost", 0.0) \
        if max_usd > 0 else 0.0
    bgwriter.configure(cfg)
    # trigger-time image counts as the current observation; a mutating
    # step flips this and forces a fresh screenshot before the next
    # click/move
    screen_dirty = not initial_image
    # last fresh screenshot result — in DOM mode a model-requested
    # observe while the screen is clean serves this instead of another
    # eval round-trip (unneeded_observe is the dominant judged waste)
    last_shot = None
    # the mutating step that dirtied the screen — the re-observe
    # caption names it so the model reads the shot as the verify pass
    dirty_step = ""

    def stopped() -> bool:
        return cancel.is_cancelled() or _user_interrupted()

    def budget_hit() -> str:
        """The tripped per-run bound as a result-string tail, "" while
        the run is inside its step/seconds/spend budget (U4)."""
        if max_seconds > 0 and time.monotonic() - t0 >= max_seconds:
            return f"budget: >{max_seconds:g}s"
        if max_usd > 0 and ledger.session_totals().get(
                "cost", 0.0) - spend0 >= max_usd:
            return f"budget: spend >${max_usd:g}"
        return ""

    # U5: exclusive drive with instant takeover — while a pointer-delivery
    # op is in flight, real input (physical mouse/keys; the injectors are
    # filtered out of the watch) must win immediately, same as the user's
    # own interrupt. Mode is logged for the run's audit trail.
    watch_mode = realinput.begin(cfg)
    try:
        from . import trace as _trace
        _trace.emit(_trace.current(), "yield_watch", "cua",
                    {"mode": watch_mode})
    except Exception:
        pass

    def _user_interrupted() -> bool:
        return bool(interrupted and interrupted()) \
            or realinput.yielded()

    guard = cua_safety.Guard(cfg, state=state,
                           interrupted=_user_interrupted)
    gate_ctx = policy.gate_ctx()   # per-run declines (U3)

    try:
        while len(steps) < max_steps:
            why = budget_hit()
            if why:
                _goals.record_steps(steps)
                out = _budget_abort(state, task, steps, why)
                _record_traj(task, harness, steps, out, cfg)
                return out
            if stopped():
                _goals.record_steps(steps)
                return "INTERRUPTED (user)"
            try:
                msg = _post(messages, cfg)
            except cancel.Cancelled:
                _goals.record_steps(steps)
                return "INTERRUPTED (user)"
            calls = msg.get("tool_calls") or []
            if not calls and at_mode:
                parsed = _parse_action_text(msg.get("content") or "")
                if parsed is None:
                    parse_misses += 1
                    if parse_misses > max_parse_misses:
                        _goals.record_steps(steps)
                        out = (f"STALLED (unparseable action replies): "
                               f"{_last(steps)}")
                        _record_traj(task, harness, steps, out, cfg)
                        return out
                    messages.append(
                        {"role": "user",
                         "content": "Reply with exactly one Action: line "
                                    "(click(x, y) | type('text') | scroll | "
                                    "hotkey('a','b')) or DONE."})
                    continue
                parse_misses = 0
                if not parsed["actions"]:
                    text = (parsed["done"] or "done").strip()
                    _publish(state, task, steps)
                    _goals.record_steps(steps)
                    _goals.close("done")
                    out = f"ACTED ({len(steps)} steps): {text}"
                    _record_traj(task, harness, steps, out, cfg)
                    return out
                calls = [{"id": f"at-{len(steps)}-{i}", "_at": True,
                          "function": {"name": n,
                                       "arguments": json.dumps({"arg": a})}}
                         for i, (n, a) in enumerate(parsed["actions"])]
            if not calls:
                text = (msg.get("content") or "").strip()
                _publish(state, task, steps)
                _goals.record_steps(steps)
                if text.upper().startswith("ASK_USER:"):
                    # conversational backchannel — speak the question, keep
                    # the goal open for the next utterance
                    _state.action_add(state, "question", text[9:].strip(),
                                      status="awaiting")
                    return "ASK_USER " + text[9:].strip()
                _goals.close("done")
                out = f"ACTED ({len(steps)} steps): {text or 'done'}"
                _record_traj(task, harness, steps, out, cfg)
                return out
            messages.append(msg)
            for ci, call in enumerate(calls):
                if stopped():  # no further steps once the user said stop
                    _goals.record_steps(steps)
                    return "INTERRUPTED (user)"
                name, arg = _name_arg(call)
                why = budget_hit()
                if why:
                    _goals.record_steps(steps)
                    out = _budget_abort(state, task, steps, why)
                    _record_traj(task, harness, steps, out, cfg)
                    return out
                if name == "ask_user":
                    # U4 conversational backchannel: the question parks on
                    # the prompt broker like a confirm card and the pick/
                    # spoken answer comes back as this call's result. No
                    # gate — it's a question, not an action.
                    try:
                        result = _ask_user(state, ask, arg)
                    except cancel.Cancelled:
                        _goals.record_steps(steps)
                        return "INTERRUPTED (user)"
                    steps.append(
                        {"tool": name, "arg": arg, "result": result,
                         "reply": (msg.get("content") or "")[:500]})
                    _publish(state, task, steps)
                    if call.get("_at"):
                        messages.append({"role": "user", "content": result})
                    else:
                        messages.append(
                            {"role": "tool",
                             "tool_call_id": call.get("id", name),
                             "content": result})
                    continue
                # lifecycle stream: queued when the model proposes the call,
                # in_flight while gates/dispatch run, terminal on the result;
                # T1 steps carry how to take them back (undo_ref)
                aid = _state.action_add(
                    state, "tool", name, target=arg,
                    undo_ref=policy.undo_ref(name, arg, cfg))
                # T2 checkpoint: _gate batches the reply's remaining gated
                # calls into ONE card (not a card per tool)
                refused = _gate(
                    name, arg, cfg, confirm, state=state,
                    batch=[_name_arg(c) for c in calls[ci + 1:]],
                    ctx=gate_ctx)
                served_cached = False
                if refused is None:
                    _state.action_set(state, aid, status="in_flight")
                    # soak fix: re-observe — a mutating step invalidates the
                    # screen the last coordinates came from, so take a fresh
                    # screenshot before any pointer call. Deterministic —
                    # doesn't rely on the model remembering to look.
                    # DOM-mode id clicks are exempt: they dispatch through
                    # getElementById + scrollIntoView, so stale legend
                    # coords can't misaim them.
                    _id_arg = name == "click" \
                        and (cfg or {}).get("screen", {}).get("dom_page") \
                        and not re.match(r"^\s*-?\d+\s*,", arg or "")
                    if (name in ("click", "move") and vision
                            and screen_dirty and not _id_arg):
                        rid = _state.action_add(
                            state, "tool", "screenshot",
                            target="(auto re-observe)", status="in_flight")
                        shot = tools.run("screenshot", "", cfg, harness)
                        _state.action_set(state, rid,
                                          status=_tool_status(shot),
                                          reason=shot)
                        steps.append({"tool": "screenshot",
                                      "arg": "(auto re-observe)",
                                      "result": shot})
                        _publish(state, task, steps)
                        if shot.startswith("SHOT "):
                            _attach_image(
                                messages, shot[5:].strip(), cfg,
                                why=f"re-observe: verify "
                                    f"'{dirty_step or 'last step'}' landed")
                            last_shot = shot
                            screen_dirty = False
                        # a failed observe leaves the screen dirty AND the
                        # cached shot ineligible — a stale DOM digest is
                        # worse than no digest
                    tgt = None
                    if (name == "screenshot" and not screen_dirty
                            and last_shot
                            and (cfg or {}).get("screen", {}).get(
                                "dom_page")):
                        # DOM observation is deterministic given unchanged
                        # state — the model already has this digest/image
                        result = last_shot + " (unchanged)"
                        served_cached = True
                    else:
                        try:
                            # W13: resolve the point BEFORE the guard so the
                            # audit records x,y (not just len) for name
                            # targets
                            tool_arg, tgt, result = _aim(
                                name, arg, cfg, guard, state)
                            if result is None:
                                # W9: kill/deny/rate/dry-run/audit around
                                # dispatch
                                result = guard.run(
                                    name, tool_arg,
                                    lambda: tools.run(name, tool_arg, cfg,
                                                      harness))
                            _aimed_done(state, name, tgt, result,
                                        guard.last_delivery)
                        except cancel.Cancelled:
                            _state.action_set(state, aid, status="cancelled",
                                              reason="interrupted")
                            grounding.emit_target(state, None)
                            _goals.record_steps(steps)
                            return "INTERRUPTED (user)"
                        except Exception as e:
                            grounding.emit_target(state, None)
                            result = f"ERROR ({e})"
                else:
                    result = refused
                # the stream entry keeps the raw result — the verify line
                # below is model-facing feedback (step record + tool
                # result), not stream copy. `delivery` records the channel
                # the call actually used (U5); a gated/cached step records
                # the mode it would have used.
                d = _delivery.planned(name, cfg) \
                    if refused is not None or served_cached \
                    else guard.last_delivery
                kw = {"status": _tool_status(result), "reason": result}
                if d:
                    kw["delivery"] = d
                _state.action_set(state, aid, **kw)
                result += _verify_hint(name, arg, result, cfg)
                if name == "screenshot" and result.startswith("SHOT "):
                    screen_dirty = False
                    if not served_cached:
                        last_shot = result
                elif name in _SCREEN_CHANGING and not result.startswith(
                        ("ERROR", "SKIP", "REFUS", "DRYRUN")):
                    screen_dirty = True
                    dirty_step = f"{name} {arg}".strip()[:60]
                step = {"tool": name, "arg": arg, "result": result,
                        "reply": (msg.get("content") or "")[:500]}
                if d:
                    step["delivery"] = d
                steps.append(step)
                _publish(state, task, steps)
                _publish_guide(state, name, arg, result)
                # GUIDE() is a user-handoff (guide mode / no backend), not
                # a failure — don't burn the error budget on it.
                errors = errors + 1 if result.startswith(("ERROR", "SKIP",
                                                          "REFUS")) else 0
                if call.get("_at"):
                    messages.append({"role": "user", "content": result})
                else:
                    messages.append({"role": "tool",
                                     "tool_call_id": call.get("id", name),
                                     "content": result})
                if name == "screenshot" and vision \
                        and result.startswith("SHOT ") \
                        and not served_cached:
                    _attach_image(messages, result[5:].strip(), cfg)
                if errors > max_errors:
                    _goals.record_steps(steps)
                    out = f"ABORTED (repeated failures): {_last(steps)}"
                    _record_traj(task, harness, steps, out, cfg)
                    return out
                if len(steps) >= max_steps:
                    break
        out = _budget_abort(state, task, steps, f"max {max_steps} steps")
        _goals.record_steps(steps)
        _record_traj(task, harness, steps, out, cfg)
        return out
    finally:
        # U5: disarm the yield watch — armed/yielded must
        # never outlive the run they armed for (a stale
        # yield would poison the next real-pointer call)
        realinput.finish()


def _aim(name: str, arg: str, cfg: dict, guard, state):
    """Resolve a click/move target to compositor-global coords and emit
    the W21 `cua.target` aim. Returns (tool_arg, Target|None, refusal).
    A name target is grounded (UI-TARS / a11y / vision fallback, one
    re-observe on low confidence, then refused); explicit coordinates
    pass through unchanged. DOM mode and non-pointer tools are untouched,
    and a call the guard would refuse anyway never ships a screenshot to
    a model."""
    if name not in ("click", "move") or \
            (cfg or {}).get("screen", {}).get("dom_page"):
        return arg, None, None
    from .tools import system as _sys
    if _XY_ARG.match(arg or ""):
        # explicit coordinates: no grounding; only convert for the ghost
        # cursor when something is listening
        if state is None or not callable(getattr(state, "emit_event",
                                                 None)):
            return arg, None, None
        xy = _sys._parse_xy(arg)
        if xy is None:
            return arg, None, None
        tgt = grounding.Target(xy[0], xy[1], "global", 1.0, "model",
                               label="")
        _announce(state, tgt, name=name, cfg=cfg)
        return arg, tgt, None
    if guard.preflight(name):
        return arg, None, None       # guard.run refuses + audits it
    try:
        tgt = grounding.ground_target(arg, cfg)
    except grounding.GroundRefused as e:
        grounding.emit_target(state, None)
        return arg, None, (f"REFUSED (could not ground {arg[:60]!r}: "
                           f"{e.reason or e.code})")
    _announce(state, tgt, name=name, cfg=cfg, label=arg[:40])
    return f"{tgt.x},{tgt.y}@logical", tgt, None


_XY_ARG = re.compile(r"^\s*-?\d+\s*,\s*-?\d+\s*(@logical)?\s*$")


def _announce(state, tgt, name: str = "", cfg: dict | None = None,
              label: str = "") -> None:
    if state is None or not callable(getattr(state, "emit_event", None)):
        return
    win = ""
    try:
        from . import platform
        w = platform.active_window() or {}
        win = w.get("title") or w.get("class") or ""
    except Exception:
        pass
    # the aim carries the delivery the call would use — a visible
    # "pointer" aim is the escalation the user sees before it lands
    grounding.emit_target(state, "aim", tgt, window=win, label=label,
                          delivery=_delivery.planned(name, cfg))


def _aimed_done(state, name: str, tgt, result: str,
                delivery: str = "") -> None:
    """After a pointer step: a landed click is `click` (ripple) then
    `done`; a guide handoff / move leaves the aim parked; anything else
    (failed, refused, dry-run) clears. Emitted after the result so a
    failed or denied click never shows a ripple."""
    if tgt is None or name not in ("click", "move"):
        return
    if name == "click" and result.startswith("CLICKED"):
        grounding.emit_target(state, "click", tgt, delivery=delivery)
        grounding.emit_target(state, "done", tgt, delivery=delivery)
    elif not result.startswith(("GUIDE", "MOVED", "MOVE-GUIDE")):
        grounding.emit_target(state, None)


def _tool_status(result: str) -> str:
    """Map a tool-call result string onto the action lifecycle: calls
    the gates turned away are `cancelled` (deny, timeout, disabled —
    the reason field says which), real failures are `failed`."""
    if result.startswith(("SKIP", "BLOCKED", "NO_ANSWER")):
        return "cancelled"
    if result.startswith(("ERROR", "REFUS", "FAIL", "ABORT", "STALL")):
        return "failed"
    return "done"


def _publish(state, task: str, steps: list) -> None:
    if state is None:
        return
    try:
        recent = [f"{s['tool']} {s['arg'][:40]} → {s['result'][:60]}"
                  for s in steps[-4:]]
        state.transition("acting",
                         result=f"act step {len(steps)}: "
                                f"{steps[-1]['tool']}" if steps else "act",
                         steps=recent)
    except Exception:
        pass


def _last(steps: list) -> str:
    return "; ".join(f"{s['tool']}→{s['result']}" for s in steps[-3:])


def _limit(cfg: dict | None, key: str, default: int) -> int:
    """An [agents] integer bound, `default` when absent or not a number."""
    raw = ((cfg or {}).get("agents") or {}).get(key)
    try:
        return int(raw) if raw not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _limit_f(cfg: dict | None, key: str, default: float) -> float:
    """An [agents] bound as a float — seconds/usd caps take fractional
    values; `default` when absent or not a number."""
    raw = ((cfg or {}).get("agents") or {}).get(key)
    try:
        return float(raw) if raw not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _budget_abort(state, task: str, steps: list, why: str) -> str:
    """Bounded abort (U4, R17): publish a `failed` stream entry with
    reason `budget` and the step list so far, then the result string."""
    _state.action_add(state, "act", f"run: {task[:60]}",
                      status="failed", reason="budget",
                      target=_last(steps)[:160])
    return f"ABORTED ({why}): {_last(steps)}"


def _prev_turn() -> str:
    """'[previous turn] user: "x" → wisp: y' — every follow-up turn gets
    the prior turn's outcome, not just labeled corrections (U4)."""
    try:
        from . import session
        last = session.tail(1)
        txt = session.as_text(last) if last else ""
    except Exception:
        return ""
    return f"[previous turn]\n{txt[:400]}" if txt else ""


def _parse_ask(arg: str) -> tuple:
    """ask_user arg 'question | opt | opt' -> (question, [options])."""
    parts = [p.strip().strip("'\"") for p in (arg or "").split("|")]
    q = parts[0] if parts else ""
    return q, [p for p in parts[1:] if p][:6]


def _ask_user(state, ask, arg: str) -> str:
    """Run the model's ask_user call: the question parks on the turn's
    ask channel (`confirm.make_ask` — a `question` card on the same
    prompt broker the confirm card uses) and the pick/typed/spoken
    answer comes back as the tool result. NO_ANSWER when no channel is
    wired or the question lapsed."""
    q, opts = _parse_ask(arg)
    aid = _state.action_add(state, "tool", "ask_user", target=arg,
                            status="in_flight")
    answer = ask(q, opts or None) if callable(ask) else None
    result = (f"USER ANSWERED: {answer}" if answer else
              "NO_ANSWER (no usable reply — the question lapsed or "
              "no answer channel is wired; proceed on your best "
              "judgment or report the block)")
    _state.action_set(state, aid, status=_tool_status(result),
                      reason=result)
    return result


def _verify_hint(name: str, arg: str, result: str, cfg: dict) -> str:
    """One-line verify feedback appended to a mutating call's result
    (U4 observe→act→verify): the model is told the screen changed and
    to check the step landed on the next observation — and a DOM
    click-by-id whose echo names a clearly different element than the
    aim reads as retryable feedback, not a silent continue. Pixel-space
    verify rides the re-observe screenshot; no second model call."""
    if not result or result.startswith(
            ("ERROR", "SKIP", "REFUS", "FAIL", "DRYRUN", "GUIDE",
             "MOVE", "NO_ANSWER", "HANDED")):
        return ""
    if name == "click" and result.startswith("CLICKED ") \
            and (cfg or {}).get("screen", {}).get("dom_page"):
        hit = result[len("CLICKED "):].strip()
        want = (arg or "").strip().strip("'\"").lower()
        if want and hit and want not in hit.lower() \
                and hit.lower() not in want:
            return (f" — verify FAILED: aimed at {want!r}, hit "
                    f"{hit[:40]!r}; re-aim and click again rather "
                    "than continuing")
    if name in _SCREEN_CHANGING:
        return (" — screen changed; verify the step landed on the "
                "next screenshot before planning the next pointer "
                "action")
    return ""


def _record_traj(task: str, harness: dict | None, steps: list, out: str,
                 cfg: dict | None) -> None:
    """Hand the run's trajectory to the background writer: the step list
    is copied (the caller reuses it), and the active-window lookup, the
    rotation check and the append all happen off the turn's hot path."""
    from . import trajectories
    snap = [dict(s) for s in steps]
    record = trajectories.record     # bound now: patches stay honoured

    def write():
        record(task, _app(harness), snap, out, surface=_surface(cfg))
    bgwriter.submit(write)


def _app(harness: dict | None) -> str:
    """Active app class for trajectory grouping."""
    try:
        from . import platform
        return platform.active_window().get("class", "")
    except Exception:
        return ""


def _surface(cfg: dict | None) -> str:
    """Interaction substrate tag — keeps browser-DOM and real-desktop
    training data in separate buckets."""
    if (cfg or {}).get("screen", {}).get("dom_page"):
        return "browser-dom"
    if (cfg or {}).get("pointer", {}).get("mode") == "guide":
        return "desktop-guide"
    return "desktop"


_GUIDE_RE = re.compile(r"(?:GUIDE|MOVE-GUIDE|CLICKED|MOVED)\((-?\d+),"
                       r"(-?\d+)\)")

# UI-TARS-style action grammar — providers flagged action_text=true.
# One action per reply; 'Action:' prefix and bare 'name(args)' both
# accepted. Returns {"actions": [(tool, arg)], "done": text|None} or
# None when nothing parses.
_AT_DONE_RE = re.compile(
    r"^(?:DONE\b:?\s*(?P<dt>.*)|"
    r"(?:Action:\s*)?finished\s*\(\s*content\s*=\s*(?P<fq>['\"])(?P<fc>.*?)"
    r"(?P=fq)\s*\)|(?:Action:\s*)?FAIL\b.*)$", re.I | re.S)
_AT_CALL_RE = re.compile(
    r"^(?:Action:\s*)?([a-z_]+)\s*\((?P<args>.*)\)\s*\.?$",
    re.I | re.S)
_AT_QUOTED_RE = re.compile(r"['\"]([^'\"]*)['\"]")
_AT_NUM_RE = re.compile(r"-?\d+")

# action-text gesture names -> the blocked tool name whose dispatch
# returns a legible refusal (desktop-scope real-pointer input is off,
# U5 — see system.BLOCKED_INPUT). UI-TARS emits e.g. left_double /
# right_single / left_click_drag; they must not silently map to click.
_AT_BLOCKED = {
    "left_double": "double_click", "right_double": "double_click",
    "double_click": "double_click", "tap_double": "double_click",
    "triple_click": "triple_click",
    "right_single": "right_click", "right_click": "right_click",
    "middle": "middle_click", "middle_click": "middle_click",
    "mouse_down": "mouse_down", "mouse_up": "mouse_up",
    "left_mouse_down": "mouse_down", "left_mouse_up": "mouse_up",
    "drag": "drag", "move_drag": "drag", "left_click_drag": "drag",
    "drag_and_drop": "drag", "swipe": "drag",
}


def _at_coords(args: str) -> str | None:
    nums = _AT_NUM_RE.findall(args)
    return f"{nums[0]},{nums[1]}" if len(nums) >= 2 else None


def _parse_action_text(text: str) -> dict | None:
    t = (text or "").strip()
    if not t:
        return None
    m = _AT_DONE_RE.match(t)
    if m:
        return {"actions": [],
                "done": (m.group("dt") or m.group("fc") or t).strip()}
    actions = []
    for line in t.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith(("thought", "observation")):
            continue
        cm = _AT_CALL_RE.match(line)
        if not cm:
            return None if not actions else {"actions": actions,
                                             "done": None}
        fn, args = cm.group(1).lower(), cm.group("args")
        if fn in ("click", "tap"):
            xy = _at_coords(args)
            if xy is None:
                continue
            actions.append(("click", xy))
        elif fn in _AT_BLOCKED:
            # gestures that would fight the user for the real pointer
            # parse to the blocked tool names — the call returns a
            # legible BLOCKED rather than silently becoming a click
            actions.append((_AT_BLOCKED[fn], fn))
        elif fn == "type":
            q = _AT_QUOTED_RE.search(args)
            if q:
                actions.append(("type_text", q.group(1)))
        elif fn == "scroll":
            d = _AT_QUOTED_RE.search(args)
            if d:
                actions.append(("scroll", d.group(1).lower()))
            else:
                nums = [int(n) for n in _AT_NUM_RE.findall(args)]
                dy = nums[-1] if nums else 0
                if dy:
                    actions.append(
                        ("scroll",
                         f"{'down' if dy > 0 else 'up'} {abs(dy)}"))
        elif fn in ("hotkey", "press", "key"):
            keys = _AT_QUOTED_RE.findall(args)
            if keys:
                actions.append(("key", "+".join(k.lower()
                                                for k in keys)))
        elif fn == "wait":
            continue  # no wait tool — free no-op
        else:
            actions.append((fn, args.strip()))  # unknown → tool error
    return {"actions": actions, "done": None} if actions else None


def _publish_guide(state, name: str, arg: str, result: str) -> None:
    """Move the overlay ghost cursor to wherever a pointer step landed
    (or was pointed). GUIDE() parks it for the user; CLICKED marks the
    injected click."""
    if state is None or name not in ("click", "move"):
        return
    m = _GUIDE_RE.search(result)
    if not m:
        return
    try:
        state.transition("acting", guide={
            "x": int(m.group(1)), "y": int(m.group(2)),
            "label": arg[:40] if arg and not _GUIDE_RE.match(arg) else "",
            "mode": "drive" if result.startswith(("CLICKED", "MOVED"))
                    else "guide",
            "seq": len(state.steps or []) + 1})
    except Exception:
        pass


def _png_dims(b64: str) -> tuple | None:
    """(w,h) from a base64 PNG's IHDR — no decoder needed."""
    import struct
    try:
        raw = base64.b64decode(b64)[:26]
        if raw[:8] == b"\x89PNG\r\n\x1a\n" and raw[12:16] == b"IHDR":
            return struct.unpack(">II", raw[16:24])
    except Exception:
        pass
    return None


def _attach_image(messages: list, path: str, cfg: dict | None = None,
                  why: str = "") -> None:
    """Feed the screenshot back as an image part on a follow-up user
    message — the model can't act on a screen it can't see. Keeps at
    most MAX_IMAGES image parts in the window (oldest dropped). `why`
    prefaces the caption when a re-observe exists to VERIFY the last
    mutating step rather than to plan the next one (U4)."""
    import pathlib
    try:
        b64 = base64.b64encode(
            pathlib.Path(path).read_bytes()).decode()
    except OSError:
        return
    dims = _png_dims(b64)
    # drop oldest image parts beyond the cap
    kept = 0
    for m in reversed(messages):
        c = m.get("content")
        if isinstance(c, list):
            imgs = [p for p in c if p.get("type") == "image_url"]
            if imgs:
                kept += 1
                if kept >= MAX_IMAGES:
                    m["content"] = [p for p in c
                                    if p.get("type") != "image_url"]
    caption = (f"{why} — " if why else "") + (
        f"current screen ({dims[0]}x{dims[1]} px — click/move "
        "x,y use these pixels" if dims else "current screen")
    if dims and (cfg or {}).get("screen", {}).get("dom_page"):
        els = (cfg or {})["screen"].get("dom_els") or []
        if els:
            caption += "; elements: " + "; ".join(els)
        else:
            caption += ("; elements are labeled with id and center "
                        "(x,y)")
    caption += "):" if dims else ":"
    messages.append({"role": "user", "content": [
        {"type": "text", "text": caption},
        {"type": "image_url",
         "image_url": {"url": f"data:image/png;base64,{b64}"}}]})
