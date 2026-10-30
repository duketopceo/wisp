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
import pathlib
import re
import time

from . import bgwriter, cancel, cua_safety, grounding, ledger, \
    policy, realinput, tools
from . import delivery as _delivery
from . import state as _state

# Defaults; the daemon reads [agents] act_max_steps, act_max_errors,
# act_max_parse_misses, act_max_seconds and act_max_usd
# (wisp/settings_schema.py) through _limit()/_limit_f().
MAX_STEPS = 8
MAX_ERRORS = 2
MAX_PARSE_MISSES = 1
# narrated-next-step replies (no tool call) nudged back into the loop
MAX_INTENT_NUDGES = 2
# done claims contradicted by the run's last effect step, nudged back
MAX_DONE_NUDGES = 1
MAX_SECONDS = 600          # wall-clock cap for one run; 0 = off
MAX_USD = 0.0              # per-run paid-model spend cap; 0 = off
MAX_IMAGES = 3  # cap retained screenshots in the message window
# tools whose success may change what's on screen → re-observe before
# the next pointer step
_SCREEN_CHANGING = {"click", "move", "type_text", "key", "launch",
                    "focus", "tab", "close", "workspace", "shell", "fill",
                    "post_send"}

SYSTEM = ("You are Wisp's hands on a Linux desktop (Hyprland). Complete "
          "the user's task using the provided tools — keep steps minimal "
          "and prefer safe tools. Take a screenshot first when the task "
          "needs on-screen targets; click/move take 'x,y' in that "
          "screenshot's pixels or a target name (e.g. 'monitor icon in menu bar') "
          "which automatically grounds via Clef/Jev noul probabilistic centering. "
          "Call observe for a cropped frame of the focused "
          "app to inspect (control-channel when the app ships one, "
          "else a window-crop capture — inspect only, its pixels are "
          "not the click coordinate space). "
          "To switch to a browser tab that is already open, call tab "
          "'<name or site>' (include 'personal' or 'work' when the user "
          "names a profile or when the focused browser window shows "
          "Personal/Work) — do not click the tab strip or call launch; "
          "launch opens apps, it never switches tabs. "
          "Media playback (pause, play, next, previous, volume, mute) "
          "uses the media tool — never a click on a player and never a "
          "key press. "
          "Never click twice off the same screenshot "
          "— after anything that changes the screen (click, key, type, "
          "launch, focus, tab, workspace, shell), re-screenshot before the "
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
    from . import brain, trace as _trace
    t0 = time.monotonic()
    res = brain.chat(messages, cfg,
                     tools=tools.tool_schemas(cfg), timeout=60)
    raw = res["raw"]
    img = sum(len(p.get("image_url", {}).get("url", ""))
              for m in messages if isinstance(m.get("content"), list)
              for p in m["content"]
              if p.get("type") == "image_url")
    _trace.emit(_trace.current(), "llm_call", "act",
                {"brain": res.get("provider"),
                 "model": res.get("model"),
                 "fallback_from": res.get("fallback_from"),
                 "ttft_ms": res.get("ttft_ms"),
                 "latency_ms": res.get("latency_ms"),
                 "msgs": len(messages), "img_kb": img // 1024,
                 "tools_out": [_name_arg(c)[0]
                               for c in raw.get("tool_calls") or []],
                 "reply": (raw.get("content") or "")[:200]},
                ms=round((time.monotonic() - t0) * 1000))
    return raw


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
    raw = fn.get("arguments")
    arg = ""
    # providers emit arguments as a JSON string or an object — anything
    # else (a list, a bare scalar, broken JSON) leaves arg empty so the
    # call becomes a tool error instead of crashing the run
    if isinstance(raw, dict):
        arg = str(raw.get("arg", ""))
    elif isinstance(raw, str):
        try:
            parsed = json.loads(raw or "{}")
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            arg = str(parsed.get("arg", ""))
    return name, arg


def _reply(messages: list, call: dict, name: str, result: str) -> None:
    """Append a tool result: action-text calls are plain user messages,
    real tool_calls need the tool_call_id link."""
    if call.get("_at"):
        messages.append({"role": "user", "content": result})
    else:
        messages.append({"role": "tool",
                         "tool_call_id": call.get("id", name),
                         "content": result})


def run_act_loop(task: str, cfg: dict, state=None,
                 harness: dict | None = None, confirm=None,
                 initial_image: str | None = None,
                 interrupted=None,
                 steps_out: list | None = None,
                 ask=None, *, user_request: str = "", lang: str = "") -> str:
    """Drive the chat model through the toolbelt until it finishes or a
    bound trips. `confirm(prompt)->bool` asks the user (choice widget /
    IPC) when wired; without it mutating calls skip. `ask(question,
    options)->pick|None` is the in-loop conversation channel (U4 —
    `confirm.make_ask` on the same broker); without it `ask_user` calls
    resolve NO_ANSWER. `steps_out`, if a list, receives the run's step
    records for judging/replay. `user_request` is the caller's verbatim
    human instruction, not a generated task/goal or model tool payload.
    Only that trusted channel may authorize an element-free coordinate
    click; omitted context fails closed."""
    from . import brain
    at_mode = brain.action_text(cfg)
    if not brain.supports_tools(cfg) and not at_mode:
        p = brain.provider(cfg)
        return (f"SKIP (brain provider '{p['name']}' does not support "
                f"tools — set [brain.{p['name']}] tools=true or pick a "
                f"capable provider)")
    system = SYSTEM
    if lang:
        from . import lang as _lang
        rule = _lang.reply_rule(lang)
        if rule:
            system += " " + rule
    from . import trajectories, context as _ctx, action_stats as _ast
    traj_recs = trajectories._read_all()  # one parse feeds both blocks
    traj_labs = trajectories._labels()
    focus = _ctx.snapshot(cfg)
    if focus:
        system += "\n\n" + focus
        app_key = _ctx.focused_app()
        stats_blk = _ast.block_for(app_key, records=traj_recs)
        if stats_blk:
            system += "\n" + stats_blk
    prior = trajectories.context_for(task, cfg=cfg, records=traj_recs,
                                     labels=traj_labs)
    if prior:
        system += "\n\n" + prior
    from . import goals as _goals
    goal_txt = _goals.context_text()
    # a follow-up turn sees the previous turn's outcome, not just
    # the open goal — corrections already carry the failed attempt, so
    # this is the general "previous turn did X" context
    prev_txt = _prev_turn(state)
    user_msg = "\n\n".join(t for t in (goal_txt, prev_txt, task) if t)
    p = brain.provider(cfg)
    vision = p.get("vision", "false") == "true"
    if not initial_image and vision:
        # no trigger-time image (direct/IPC path) — observe before the
        # first model call so the loop never plans blind
        shot = tools.run("screenshot", "", cfg, harness)
        if shot.startswith("SHOT "):
            import pathlib as _pl
            from .tools.system import model_image
            initial_image = model_image(_pl.Path(shot[5:].strip()))
    if initial_image:
        # screen at trigger — the model sees the app, no "what app" ask.
        # Name the pixel space: models click more accurately when they
        # know the image's true dimensions.
        if initial_image.startswith("data:"):
            url = initial_image
            b64 = url.split(",", 1)[1]
        else:
            url = f"data:image/png;base64,{initial_image}"
            b64 = initial_image
        dims = _img_dims(b64)
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
                    {"type": "image_url", "image_url": {"url": url}}]
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user_msg}]
    steps = steps_out if steps_out is not None else []
    if steps_out is not None:
        steps_out.clear()
    errors = 0
    parse_misses = 0
    intent_nudges = 0
    done_nudges = 0
    # the window focused at trigger time (stage_capture records it):
    # refocusing it changes nothing on screen
    start_focus = str((getattr(state, "focus", None) or {}).get("app")
                      or "")
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
    # parked prompt cards share the run's wall-clock bound — the
    # factories read _run_deadline and cap each card's wait at it, so a
    # question can't outlast act_max_seconds
    if max_seconds > 0:
        for _fn in (confirm, ask):
            if callable(_fn):
                try:
                    _fn._run_deadline = t0 + max_seconds
                except (AttributeError, TypeError):
                    pass
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

    def _user_interrupted() -> bool:
        return bool(interrupted and interrupted()) \
            or realinput.yielded()

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

    # exclusive drive with instant takeover — while a pointer-delivery
    # op is in flight, real input (physical mouse/keys; the injectors are
    # filtered out of the watch) must win immediately, same as the user's
    # own interrupt. Mode is logged for the run's audit trail.
    watch_mode = realinput.begin(cfg)
    out = None                  # the finally's pack call reads it
    # F1: the trajectory snapshot must land AFTER _terminal_verify —
    # each exit that used to call _record_traj now just flags it, and
    # the finally snapshots the post-verify steps so trajectories and
    # pack manifests agree on the final verdicts
    want_traj = False
    try:
        from . import trace as _trace
        _trace.emit(_trace.current(), "yield_watch", "cua",
                    {"mode": watch_mode})
    except (ImportError, AttributeError, TypeError):
        pass

    guard = cua_safety.Guard(cfg, state=state,
                           interrupted=_user_interrupted)
    gate_ctx = policy.gate_ctx()   # per-run declines (U3)

    # U1: turn-scoped recording — the cua driver writes one
    # rec/<turn>/turn-NNNNN dir per dispatched action; _record_step
    # attributes each mutating cua dispatch to its dir and attaches the
    # action_truth for the verdict path. A down/absent daemon records
    # nothing and never fails the run.
    from . import record as _rec
    recorder = _rec.begin(_trace.current())

    try:
        while len(steps) < max_steps:
            why = budget_hit()
            if why:
                _goals.record_steps(steps)
                out = _budget_abort(state, task, steps, why)
                want_traj = True
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
                        want_traj = True
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
                    want_traj = True
                    return out
                calls = [{"id": f"at-{len(steps)}-{i}", "_at": True,
                          "function": {"name": n,
                                       "arguments": json.dumps({"arg": a})}}
                         for i, (n, a) in enumerate(parsed["actions"])]
            if not calls:
                text = (msg.get("content") or "").strip()
                if (intent_nudges < MAX_INTENT_NUDGES
                        and _announces_next_step(text)):
                    # 'Now I'm taking a screenshot…' with no tool call is
                    # a narrated plan, not an outcome — ending here
                    # reported ACTED after one wrong click
                    intent_nudges += 1
                    messages.append({"role": "assistant", "content": text})
                    messages.append({"role": "user",
                                     "content": _CONTINUE_NUDGE})
                    continue
                _publish(state, task, steps)
                _goals.record_steps(steps)
                if text.upper().startswith("ASK_USER:"):
                    # conversational backchannel — speak the question, keep
                    # the goal open for the next utterance
                    _state.action_add(state, "question", text[9:].strip(),
                                      status="awaiting")
                    return "ASK_USER " + text[9:].strip()
                why = _unsupported_done(task, steps, start_focus)
                if why and done_nudges < MAX_DONE_NUDGES:
                    done_nudges += 1
                    messages.append({"role": "assistant", "content": text})
                    messages.append({"role": "user", "content": (
                        f"Not confirmed: {why}. Check the latest "
                        "screenshot against the request. Continue with a "
                        "tool call, or reply with what actually "
                        "happened.")})
                    continue
                if why:
                    # unconfirmed: leave the goal open so "try again"
                    # resumes it instead of starting over
                    text = f"I could not confirm that worked \u2014 {why}."
                else:
                    _goals.close("done")
                out = f"ACTED ({len(steps)} steps): {text or 'done'}"
                want_traj = True
                return out
            messages.append(msg)
            # B11: a reply with several changing steps is shown as ONE
            # plan card, and every step then checks the screen is still
            # the one the plan was made for
            plan, plan_focus, plan_no = [], "", 0
            if callable(confirm):
                try:
                    plan, declined = policy.plan_preview(
                        [_name_arg(c) for c in calls], cfg, confirm, state,
                        minimum=_limit(cfg, "act_preview_min",
                                       policy.PREVIEW_MIN))
                except cancel.Cancelled:
                    _goals.record_steps(steps)
                    return "INTERRUPTED (user)"
                if declined:
                    _goals.record_steps(steps)
                    return declined
                plan_focus = _focus_class() if plan else ""
            plan_names = {pair for pair in plan}
            for ci, call in enumerate(calls):
                if stopped():  # no further steps once the user said stop
                    _goals.record_steps(steps)
                    return "INTERRUPTED (user)"
                name, arg = _name_arg(call)
                if (name, arg) in plan_names:
                    plan_no += 1
                    why = _stale_why(plan_focus, plan_no, len(plan))
                    if why:
                        _goals.record_steps(steps)
                        out = _budget_abort(state, task, steps, why)
                        want_traj = True
                        return out
                why = budget_hit()
                if why:
                    _goals.record_steps(steps)
                    out = _budget_abort(state, task, steps, why)
                    want_traj = True
                    return out
                if name == "ask_user":
                    # U4 conversational backchannel: the question parks on
                    # the prompt broker like a confirm card and the pick/
                    # spoken answer comes back as this call's result. No
                    # gate — it's a question, not an action.
                    try:
                        result, shown = _ask_user(state, ask, arg)
                    except cancel.Cancelled:
                        _goals.record_steps(steps)
                        return "INTERRUPTED (user)"
                    # the raw answer is model-facing only — the stream,
                    # state.json and trajectories get the redacted form
                    steps.append(
                        {"tool": name, "arg": arg, "result": shown,
                         "reply": (msg.get("content") or "")[:500]})
                    _publish(state, task, steps)
                    _reply(messages, call, name, result)
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
                # the arg actually dispatched and its wall-clock stamp —
                # the recorder attributes a step to its turn dir on
                # tool+args+ts (U1); None = never reached dispatch.
                # aim_mono is the F5 watermark: control._BEFORE snaps
                # are monotonic-stamped at aim time and a verify rung
                # only accepts one stamped after this dispatch began
                tool_arg, dispatched_at, tgt, aim_mono, dispatch_mono = \
                    arg, None, None, None, None
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
                            # resolve the point BEFORE the guard so the
                            # audit records x,y (not just len) for name
                            # targets
                            # F5: the aim window opens BEFORE grounding
                            # runs — a control before-snap taken inside
                            # _aim is stamped >= this mark; anything
                            # older belongs to a previous action
                            aim_mono = time.monotonic()
                            tool_arg, tgt, result = _aim(
                                name, arg, cfg, guard, state)
                            if result is None:
                                # the session label idles out at ~300 s
                                # — re-mint before a dispatch that went
                                # stale (parked card, slow model reply)
                                recorder.ensure()

                                def _dispatch():
                                    nonlocal dispatched_at, dispatch_mono
                                    dispatched_at = time.time()
                                    dispatch_mono = time.monotonic()
                                    from .tools.system import pointer_context
                                    with pointer_context(
                                            target=tgt,
                                            user_request=user_request):
                                        return tools.run(name, tool_arg, cfg,
                                                         harness)
                                # kill/deny/rate/dry-run/audit around
                                # dispatch
                                result = guard.run(
                                    name, tool_arg, _dispatch)
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
                # the call actually used; a gated/cached step records
                # the mode it would have used.
                d = _delivery.planned(name, cfg) \
                    if refused is not None or served_cached \
                    else guard.last_delivery
                kw = {"status": _tool_status(result), "reason": result}
                if d:
                    kw["delivery"] = d
                _state.action_set(state, aid, **kw)
                if name == "screenshot" and result.startswith("SHOT "):
                    screen_dirty = False
                    if not served_cached:
                        last_shot = result
                elif name in _SCREEN_CHANGING and not result.startswith(
                        ("ERROR", "SKIP", "REFUS", "DRYRUN", "FAIL",
                         "BLOCKED")):
                    screen_dirty = True
                    dirty_step = f"{name} {arg}".strip()[:60]
                step = {"tool": name, "arg": arg, "result": result,
                        "reply": (msg.get("content") or "")[:500]}
                if aim_mono is not None:
                    # F5: the control rung rejects pre-dispatch
                    # snapshots older than this dispatch's aim —
                    # a (turn, app) snap from an earlier action can
                    # never serve a later action's verify
                    step["aim_mono"] = aim_mono
                if name == "observe":
                    # U5: a SHOT under a turn-9NNNN dir is the pack's
                    # frame-index linkage; a shots/-resident frame is a
                    # context-less capture and links nothing
                    odir = _observe_dir(result)
                    if odir:
                        step["turn_dir"] = odir
                if d:
                    step["delivery"] = d
                _record_step(step, name, tool_arg, dispatched_at,
                             recorder, cfg, mono=dispatch_mono)
                if not step.get("turn_dir"):
                    # a recorded step's real verdict speaks below —
                    # the generic nudge is only for mutations with no
                    # evidence trail (DOM/keyboard/hypr lanes)
                    hint = _verify_hint(name, arg, result, cfg)
                    if hint:
                        result += hint
                        step["result"] = result
                # U2: the cheap-first ladder runs only when a turn dir
                # attributed (cua-dispatched + recorded). The verdict
                # lands on the step record AND the tool_result the model
                # reads — a `missed` surfaces as feedback; the loop does
                # not re-dispatch on it.
                vd = _run_verify(step, name, arg, tool_arg, tgt, cfg)
                if vd is not None:
                    step["verdict"] = vd["verdict"]
                    step["verify"] = vd
                    result += " — verify " + json.dumps(
                        vd, separators=(",", ":"), sort_keys=True)
                    step["result"] = result
                steps.append(step)
                _publish(state, task, steps)
                _publish_guide(state, name, arg, result)
                # GUIDE() is a user-handoff (guide mode / no backend), not
                # a failure — don't burn the error budget on it.
                errors = errors + 1 if result.startswith(
                    ("ERROR", "SKIP", "REFUS", "FAIL", "BLOCKED")) else 0
                _reply(messages, call, name, result)
                if name in ("screenshot", "observe") and vision \
                        and result.startswith("SHOT ") \
                        and not served_cached:
                    _attach_image(messages, result[5:].strip(), cfg,
                                  coords=name == "screenshot")
                if errors > max_errors:
                    _goals.record_steps(steps)
                    out = f"ABORTED (repeated failures): {_last(steps)}"
                    want_traj = True
                    return out
                if len(steps) >= max_steps:
                    break
        out = _budget_abort(state, task, steps, f"max {max_steps} steps")
        _goals.record_steps(steps)
        want_traj = True
        return out
    finally:
        # R3: re-verify the turn's last recorded mutation with a fresh
        # after-frame BEFORE the result speaks — the driver's after.png
        # can predate the effect rendering (the FilmCraft ~70px miss sat
        # behind exactly this gap). Skipped when the turn was cancelled.
        try:
            _terminal_verify(steps, cfg)
        except Exception:
            pass
        # F1: snapshot the trajectory AFTER the terminal re-verify so
        # a flipped verdict lands in both the trajectory and the pack
        # manifest — recording before verify persisted the stale one
        try:
            if want_traj and out is not None:
                _record_traj(task, harness, steps, out, cfg, recorder)
        except Exception:
            pass
        # stop the turn's recording on EVERY exit — normal return,
        # interrupt, error, budget abort (U1). `active` is read BEFORE
        # stop() clears it: the pack writer needs to know this turn was
        # ever recorded (a recorded-but-zero-action turn still packs a
        # transcript; an unrecorded one leaves nothing durable).
        was_recorded = recorder.started
        recorder.stop()
        # U4: fold rec/<turn>/ into the durable packs/<turn>/ —
        # manifest + frames + redaction + deny re-check + retention.
        # packs.write never raises; the belt-suspenders try keeps a
        # bug in the artifact path from escaping run teardown.
        try:
            _write_pack(recorder, task, steps, cfg, was_recorded, out)
        except Exception:
            pass
        # disarm the yield watch — armed/yielded must
        # never outlive the run they armed for (a stale
        # yield would poison the next real-pointer call)
        realinput.finish()


def _observe_dir(result: str) -> str | None:
    """SHOT <rec/<turn>/turn-9NNNN/observe.*> -> its turn dir for the
    step record (the pack's frame-index linkage); a shots/-resident
    frame is a context-less capture and links nothing."""
    if not result.startswith("SHOT "):
        return None
    parent = pathlib.Path(result[5:].strip()).parent
    from . import record
    if record._TURN_RE.match(parent.name):
        return str(parent)
    return None


def _aim(name: str, arg: str, cfg: dict, guard, state):
    """Resolve a click/move target to compositor-global coords and emit
    the W21 `cua.target` aim. Returns (tool_arg, Target|None, refusal).
    A name target is grounded (UI-TARS / a11y / vision fallback, one
    re-observe on low confidence, then refused); explicit coordinates
    pass through unchanged. DOM mode and non-pointer tools are
    untouched, and a call the guard would refuse anyway never ships a
    screenshot to a model."""
    if name not in ("click", "move") or \
            (cfg or {}).get("screen", {}).get("dom_page"):
        return arg, None, None
    from .tools import system as _sys
    if _XY_ARG.match(arg or ""):
        # Explicit model coordinates are not human provenance. Keep the
        # typed target even when no ghost-cursor overlay is listening.
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
    except (ImportError, AttributeError, OSError, RuntimeError,
            TypeError):
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
    """Map a tool-call result string onto the action lifecycle — the
    shared classifier (an INTERRUPTED at dispatch level is a cancelled
    step here too)."""
    return _state.result_status(result)


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


def _focus_class() -> str:
    """The focused window's class, "" when it can't be read."""
    try:
        from . import platform
        return str((platform.active_window() or {}).get("class") or "")
    except Exception:
        return ""


def _stale_why(plan_focus: str, step_no: int, total: int) -> str | None:
    """Why a previewed plan must stop before its next step: the focused
    window is not the one the plan was made for. None when it still is
    (or the focus can't be read)."""
    if not plan_focus:
        return None
    now = _focus_class()
    if not now or now == plan_focus:
        return None
    return (f"screen changed: focus moved from {plan_focus} to {now} "
            f"before step {step_no} of {total}")


def _budget_abort(state, task: str, steps: list, why: str) -> str:
    """Bounded abort (U4, R17): publish a `failed` stream entry with
    reason `budget` and the step list so far, then the result string."""
    _state.action_add(state, "act", f"run: {task[:60]}",
                      status="failed", reason="budget",
                      target=_last(steps)[:160])
    return f"ABORTED ({why}): {_last(steps)}"


def _prev_turn(state=None) -> str:
    """'[previous turn] user: "x" → wisp: y' — every follow-up turn gets
    the prior turn's outcome, not just labeled corrections (U4)."""
    try:
        from . import session
        focus = getattr(state, "focus", None)
        app = focus.get("app", "") if isinstance(focus, dict) else None
        last = session.tail(1, app=app)  # this app's last turn only
        txt = session.as_text(last) if last else ""
    except (ImportError, AttributeError, OSError, TypeError,
            ValueError):
        return ""
    return f"[previous turn]\n{txt[:400]}" if txt else ""


def _parse_ask(arg: str) -> tuple:
    """ask_user arg 'question | opt | opt' -> (question, [options])."""
    parts = [p.strip().strip("'\"") for p in (arg or "").split("|")]
    q = parts[0] if parts else ""
    return q, [p for p in parts[1:] if p][:6]


def _ask_user(state, ask, arg: str) -> tuple:
    """Run the model's ask_user call: the question parks on the turn's
    ask channel (`confirm.make_ask` — a `question` card on the same
    prompt broker the confirm card uses) and the pick/typed/spoken
    answer comes back as the tool result. NO_ANSWER when no channel is
    wired or the question lapsed. Returns (model-facing result, redacted
    result for the stream/step record) — a free-text answer can carry
    secrets, so it never reaches state.json or trajectories."""
    q, opts = _parse_ask(arg)
    if not q:
        return ("SKIP (ask_user needs a question)",
                "SKIP (ask_user needs a question)")
    aid = _state.action_add(state, "tool", "ask_user", target=arg,
                            status="in_flight")
    answer = ask(q, opts or None) if callable(ask) else None
    result = (f"USER ANSWERED: {answer}" if answer else
              "NO_ANSWER (no usable reply — the question lapsed or "
              "no answer channel is wired; proceed on your best "
              "judgment or report the block)")
    shown = (f"USER ANSWERED ({len(answer)} chars)" if answer else result)
    _state.action_set(state, aid, status=_tool_status(result),
                      reason=shown)
    return result, shown


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


# act-loop tool name -> the driver tool recorded in a turn dir's
# action.json (U1 — the only tools dispatched through cua today)
_CUA_TOOLS = {"click": "click", "move": "move_cursor"}

# mutating tools a step record must seed with `not_recorded` when no
# turn dir attributed — _SCREEN_CHANGING plus scroll (a wheel-axis
# injection that never dirties the "needs re-observe" flag) and
# mcp_call (an external mutation with no cua evidence — it belongs on
# the manifest's action list like every other unrecorded mutation)
_RECORD_SEED = _SCREEN_CHANGING | {"scroll", "mcp_call"}


def _record_step(step: dict, name: str, tool_arg: str, dispatched_at,
                 rec, cfg: dict | None, mono=None) -> None:
    """Recording linkage for a mutating step (U1).

    A cua-dispatched call attaches its `turn-NNNNN` dir plus the
    driver's `action_truth` (effect/route/transport) — the evidence
    the verdict path scores. Every other mutating call gets
    `turn_dir: null` + verdict seed `not_recorded` — DOM clicks, wtype/
    ydotool typing, hypr window ops never reached the cua daemon, so
    there is nothing to attribute. Read-only tools get neither field:
    the driver doesn't record them. Never raises."""
    if name not in _RECORD_SEED:
        return
    step["turn_dir"] = None
    step["verdict"] = "not_recorded"
    hit = None
    if rec is not None and rec.active and dispatched_at is not None \
            and name in _CUA_TOOLS \
            and not (cfg or {}).get("screen", {}).get("dom_page") \
            and (cfg or {}).get("pointer", {}).get("mode") in ("drive", "auto"):
        try:
            # planned backend == actual backend on the dispatch path —
            # a recorded dir exists only when the driver saw the call
            if _delivery.resolve_backend(cfg, name) == "cua":
                rec.touch()   # the dispatch itself slid the idle TTL
                from .tools import system as _sys
                xy = _sys._parse_xy(tool_arg)
                hit = rec.match_turn(_CUA_TOOLS[name],
                                     *(xy or (None, None)),
                                     since=dispatched_at,
                                     since_mono=mono)
        except Exception:
            hit = None
        if hit:
            d, action = hit
            truth = action.get("action_truth") or {}
            step["turn_dir"] = str(d)
            step["action_truth"] = truth
            step["route"] = truth.get("route")
            step["transport"] = truth.get("transport")
            step.pop("verdict", None)
    _rec_turn(name, step)


def _rec_turn(name: str, step: dict) -> None:
    """`record_turn` trace event for a mutating step — best-effort,
    never breaks a turn."""
    from . import trace as _trace
    truth = step.get("action_truth") or {}
    try:
        _trace.emit(_trace.current(), "record_turn", "rec", {
            "tool": name, "turn_dir": step.get("turn_dir"),
            "effect": truth.get("effect"),
            "route": truth.get("route"),
            "transport": truth.get("transport"),
            "verdict": step.get("verdict")})
    except Exception:
        pass


def _run_verify(step: dict, name: str, arg: str, tool_arg: str, tgt,
                cfg: dict | None) -> dict | None:
    """The U2 ladder for one step: privacy re-check, action_truth gate,
    registered rungs, VLM judge on ambiguity. Returns the verdict dict.

    None when the step wasn't recorded (no turn_dir — the U1
    `not_recorded` seed stands) or the turn is being cancelled. Never
    raises into the loop; a broken ladder degrades to `unverifiable`,
    never to `landed`."""
    if name == "observe":
        # an observe frame is model-facing evidence, not a mutation —
        # the rungs have nothing to score (U5)
        return None
    if not step.get("turn_dir"):
        return None
    try:
        from . import verify as _verify
        return _verify.verdict(step, name=name, arg=arg,
                               tool_arg=tool_arg, tgt=tgt, cfg=cfg)
    except cancel.Cancelled:
        return None
    except Exception as e:
        return {"verdict": "unverifiable", "source": "none",
                "corroborated": False,
                "evidence": str(step["turn_dir"]),
                "detail": f"verify error: {e}"[:200]}


def _terminal_verify(steps: list, cfg: dict | None) -> None:
    """R3 terminal after-frame: the turn's final mutating step that was
    recorded gets one more capture + ladder pass, so a late-rendered
    effect is scored on settled pixels. If that final mutation was never
    recorded, abstain — do not re-score an earlier step with a later
    keystroke's frame."""
    if cancel.is_cancelled():
        return
    last = next((s for s in reversed(steps)
                 if s.get("tool") in _RECORD_SEED), None)
    if last is None:
        return
    if not last.get("turn_dir") or last.get("verdict") == "not_recorded":
        return
    vd0 = last.get("verify") if isinstance(last.get("verify"), dict) \
        else {}
    if vd0.get("verdict") in ("suppressed", "refused"):
        return
    try:
        from . import verify as _verify
        vd = _verify.terminal_verdict(last, cfg=cfg)
    except cancel.Cancelled:
        return
    except Exception:
        return
    if vd is not None:
        last["verdict"] = vd["verdict"]
        last["verify"] = vd


def _record_traj(task: str, harness: dict | None, steps: list, out: str,
                 cfg: dict | None, recorder=None) -> None:
    """Hand the run's trajectory to the background writer: the step list
    is copied (the caller reuses it), and the active-window lookup, the
    rotation check and the append all happen off the turn's hot path.
    `pack` is the deterministic packs/<turn> link — the pack write runs
    later in the finally, so the ref is by name, not existence."""
    # Default act routing also handles plain questions. Empty-step replies
    # have no action path to replay and must not expand transcript storage.
    if not steps:
        return
    from . import trajectories
    snap = [dict(s) for s in steps]
    record = trajectories.record     # bound now: patches stay honoured
    pack = (f"packs/{recorder.turn}"
            if recorder is not None and recorder.started else None)

    def write():
        record(task, _app(harness), snap, out, surface=_surface(cfg),
               pack=pack)
    bgwriter.submit(write)


def _write_pack(recorder, task: str, steps: list, cfg: dict | None,
                was_recorded: bool, out) -> None:
    """Turn-end hand-off to packs.write (U4): assemble the transcript
    lines — the user utterance, any parked ask_user questions, the
    spoken result — and pass the recorder's dir/session. packs.write
    owns the artifact (manifest, frames, redaction, deny re-check,
    rec/ + retention cleanup); this wrapper is the tests' patch seam,
    mirroring _record_traj."""
    from . import packs
    now = time.time()
    transcript = []
    if task:
        transcript.append({"role": "user", "text": task})
    for s in steps:
        if s.get("tool") == "ask_user" and s.get("arg"):
            transcript.append({"ts": now, "role": "wisp",
                               "text": s["arg"]})
    if isinstance(out, str) and out.strip():
        transcript.append({"ts": now, "role": "wisp", "text": out})
    packs.write(recorder.turn, steps, cfg=cfg,
                rec_dir=recorder.dir, recorded=was_recorded,
                transcript=transcript,
                session=getattr(recorder, "session", "wisp") or "wisp")


def _app(harness: dict | None) -> str:
    """Active app class for trajectory grouping."""
    try:
        from . import platform
        return platform.active_window().get("class", "")
    except (ImportError, AttributeError, OSError, RuntimeError,
            TypeError):
        return ""


def _surface(cfg: dict | None) -> str:
    """Interaction substrate tag — keeps browser-DOM and real-desktop
    training data in separate buckets."""
    if (cfg or {}).get("screen", {}).get("dom_page"):
        return "browser-dom"
    if (cfg or {}).get("pointer", {}).get("mode") == "guide":
        return "desktop-guide"
    return "desktop"


_NEXT_STEP_RE = re.compile(
    r"\b(?:now i'?m|now i am|i'?ll|i will|let me|next,? i|i'?m going to|"
    r"i need to|taking a (?:new |fresh )?screenshot|to see if|to check if|"
    r"to verify)\b", re.I)
_CONTINUE_NUDGE = ("You described a next step but did not call a tool. "
                   "Call the tool now. If the task is already complete, "
                   "reply with one short sentence describing the outcome.")


def _same_word(a: str, b: str) -> bool:
    # app binaries drift from spoken names (spotify -> spotifast): a
    # shared 5-letter stem counts as naming the app
    return a == b or (len(a) >= 5 and len(b) >= 5 and a[:5] == b[:5])


def _unsupported_done(task: str, steps: list,
                      start_focus: str = "") -> "str | None":
    """One-line reason when a tool-less 'done' is contradicted by the
    run's last effect step, else None. Pure answers (no effect step)
    and supported claims return None."""
    from .goals import _tokens as _words
    last = next((s for s in reversed(steps)
                 if s.get("tool") in _SCREEN_CHANGING), None)
    if last is None:
        return None
    result = str(last.get("result") or "")
    # a recorded (turn_dir) step's verdict is re-checked after the loop
    # by _terminal_verify, which may flip a mid-run "missed" to
    # "landed" — only an unrecorded step's verdict is final here
    missed = (not last.get("turn_dir")
              and (last.get("verify") or {}).get("verdict") == "missed")
    if missed or "verify FAILED" in result:
        return f"the last step ({last['tool']}) failed verification"
    if last["tool"] == "tab" and result.startswith("SKIP"):
        return "the tab switch was skipped: " + result[len("SKIP"):].strip(" ()")
    if last["tool"] in ("launch", "focus") and result.startswith("FOCUSED"):
        cls = result.partition("->")[2].split(" (")[0].strip()
        from . import config as _config
        from .tools import desktop as _desktop
        task_words = _words(task)
        service_roles = {_desktop._resolve_service_role(w)
                         for w in task_words} & set(_config.WEB_DEFAULTS)
        focused = cls or result[len("FOCUSED"):].split(" (")[0].strip()
        if focused.lower() in _desktop._BROWSER_CLASSES and service_roles:
            return (f"{last['tool']} only focused a browser; the service "
                    "destination needs a tab switch or URL confirmation")
        # focusing another app is a visible change (music -> spotify);
        # only a refocus of the window already in front is a no-op
        if start_focus and start_focus.lower() != cls.lower():
            return None
        arg_words = _words(last.get("arg"))
        alias_words = {_desktop._resolve_service_role(w) for w in arg_words}
        task_words = _words(task) | {_desktop._resolve_service_role(w)
                                     for w in _words(task)}
        named = arg_words | alias_words | _words(cls)
        if not any(_same_word(a, b) for a in task_words for b in named):
            return (f"{last['tool']} only refocused "
                    f"{(last.get('arg') or cls).strip()}, which the "
                    "request did not name")
    return None


def _announces_next_step(text: str) -> bool:
    """True when a tool-less reply narrates what it will do next rather
    than reporting a finished outcome."""
    if not text or text.upper().startswith(("ASK_USER:", "DONE")):
        return False
    return bool(_NEXT_STEP_RE.search(text))


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
# see system.BLOCKED_INPUT). UI-TARS emits e.g. left_double /
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
    except (ImportError, AttributeError, TypeError, ValueError):
        pass


def _img_dims(b64: str) -> tuple | None:
    """(w,h) from a base64 PNG IHDR or JPEG SOF — no decoder needed."""
    import struct
    try:
        raw = base64.b64decode(b64[:520])
    except (ValueError, TypeError):
        return None
    if raw[:8] == b"\x89PNG\r\n\x1a\n" and raw[12:16] == b"IHDR":
        return struct.unpack(">II", raw[16:24])
    if raw[:2] == b"\xff\xd8":          # JPEG: scan segments for SOF
        i = 2
        while i + 9 < len(raw):
            if raw[i] != 0xFF:
                i += 1
                continue
            m = raw[i + 1]
            if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                     0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", raw[i + 5:i + 9])
                return w, h
            if m in (0xD8, 0xD9) or 0xD0 <= m <= 0xD7:
                i += 2
                continue
            i += 2 + struct.unpack(">H", raw[i + 2:i + 4])[0]
    return None


def _attach_image(messages: list, path: str, cfg: dict | None = None,
                  why: str = "", coords: bool = True) -> None:
    """Feed the screenshot back as an image part on a follow-up user
    message — the model can't act on a screen it can't see. Keeps at
    most MAX_IMAGES image parts in the window (oldest dropped). `why`
    prefaces the caption when a re-observe exists to VERIFY the last
    mutating step rather than to plan the next one (U4). `coords`
    marks whether the frame's pixels are the click/move space — an
    observe capture is a cropped inspect-only view, never a click
    space (U5)."""
    from .tools.system import model_image
    url = model_image(path)
    if not url:
        return
    b64 = url.split(",", 1)[1]
    dims = _img_dims(b64)
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
    caption = (f"{why} — " if why else "")
    if coords:
        caption += (f"current screen ({dims[0]}x{dims[1]} px — "
                    "click/move x,y use these pixels"
                    if dims else "current screen")
    else:
        caption += (f"observed frame ({dims[0]}x{dims[1]} px — inspect "
                    "only; click/move do NOT use these pixels"
                    if dims else "observed frame")
    if dims and coords \
            and (cfg or {}).get("screen", {}).get("dom_page"):
        els = (cfg or {})["screen"].get("dom_els") or []
        if els:
            caption += "; elements: " + "; ".join(els)
        else:
            caption += ("; elements are labeled with id and center "
                        "(x,y)")
    caption += "):" if dims else ":"
    messages.append({"role": "user", "content": [
        {"type": "text", "text": caption},
        {"type": "image_url", "image_url": {"url": url}}]})
