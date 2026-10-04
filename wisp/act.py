"""Act route: a bounded, guarded tool-call loop.

Jev decides the user wants a multi-step desktop task; this loop hands the
toolbelt to the chat model as OpenAI-style tools and lets it drive. Every
proposed call re-enters the same gates execute() uses — denylist,
allow_shell, risk tier — so the model can ask for anything but only
safe/confirmed work runs.

Bounds: MAX_STEPS tool calls total, MAX_ERRORS consecutive tool failures,
then ABORTED. Every step is published to state.json (the companion orb
shows progress) and recorded in decisions.jsonl by the caller.
"""
import base64
import json
import re
import urllib.error
import urllib.request

from . import config, tools

MAX_STEPS = 8  # default; [agents] act_max_steps overrides
MAX_ERRORS = 2
MAX_IMAGES = 3  # cap retained screenshots in the message window

SYSTEM = ("You are Wisp's hands on a Linux desktop (Hyprland). Complete "
          "the user's task using the provided tools — keep steps minimal "
          "and prefer safe tools. Take a screenshot first when the task "
          "needs on-screen targets; click/move take 'x,y' in that "
          "screenshot's pixels or a target name (e.g. 'monitor icon in menu bar') "
          "which automatically grounds via Clef/Jev noul probabilistic centering. "
          "A GUIDE result means the ghost cursor "
          "is parked there for the user to click — treat it as done, "
          "not an error, and continue or finish. When done, reply with "
          "one short sentence describing the outcome. If a tool is "
          "refused or skipped, do not retry it; work around or report "
          "the block. If the task cannot proceed without information "
          "only the user has (a choice between real options, missing "
          "credentials), reply 'ASK_USER: <one short question>' — do "
          "not guess or stall. The screen image attached to the first "
          "message shows the desktop at trigger time — use it to find "
          "the app and targets instead of asking which app is meant.")


def _post(messages: list, cfg: dict) -> dict:
    """Chat call through the configured brain provider with toolbelt
    schemas (U6). Returns the provider message object."""
    from . import brain
    return brain.chat(messages, cfg,
                      tools=tools.tool_schemas(), timeout=60)["raw"]


def _gate(name: str, arg: str, cfg: dict, confirm,
          state=None) -> str | None:
    """Returns a refusal string when the call is blocked, else None."""
    tier = tools.risk_of(name)
    if tier == "shell":
        if tools.denied(arg):
            return "REFUSED (denylisted command)"
        if cfg.get("agent", {}).get("allow_shell", "false") != "true":
            return "SKIPPED (shell disabled — set allow_shell=true)"
    if tier in ("mutating", "shell"):
        # confirm-once: a yes for (tool, focused-app) holds for the
        # session — one "yes" shouldn't gate every step of one goal
        key = None
        confirmed = getattr(state, "confirmed", None)
        if state is not None and isinstance(confirmed, set):
            focus = getattr(state, "focus", None)
            app = focus.get("app", "") if isinstance(focus, dict) else ""
            key = (name, app)
            if key in confirmed:
                return None
        if confirm is None:
            return f"SKIPPED ({name} needs user confirmation)"
        if not confirm(f"run {name}: {arg or '(no arg)'}?"):
            return f"SKIPPED ({name} declined by user)"
        if key is not None:
            state.confirmed.add(key)
    return None


def run_act_loop(task: str, cfg: dict, state=None,
                 harness: dict | None = None, confirm=None,
                 initial_image: str | None = None) -> str:
    """Drive the chat model through the toolbelt until it finishes or a
    bound trips. `confirm(prompt)->bool` asks the user (choice widget /
    IPC) when wired; without it mutating calls skip."""
    from . import brain
    if not brain.supports_tools(cfg):
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
    from . import goals as _goals
    goal_txt = _goals.context_text()
    user_msg = (goal_txt + "\n\n" + task) if goal_txt else task
    if initial_image:
        # screen at trigger — the model sees the app, no "what app" ask
        user_msg = [{"type": "text", "text": user_msg},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,"
                                          f"{initial_image}"}}]
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user_msg}]
    steps, errors = [], 0
    max_steps = int(cfg.get("agents", {}).get("act_max_steps",
                                             str(MAX_STEPS)))
    p = brain.provider(cfg)
    vision = p.get("vision", "false") == "true"

    while len(steps) < max_steps:
        msg = _post(messages, cfg)
        calls = msg.get("tool_calls") or []
        if not calls:
            text = (msg.get("content") or "").strip()
            _publish(state, task, steps)
            _goals.record_steps(steps)
            if text.upper().startswith("ASK_USER:"):
                # conversational backchannel — speak the question, keep
                # the goal open for the next utterance
                return "ASK_USER " + text[9:].strip()
            _goals.close("done")
            out = f"ACTED ({len(steps)} steps): {text or 'done'}"
            trajectories.record(task, _app(harness), steps, out)
            return out
        messages.append(msg)
        for call in calls:
            fn = call.get("function", {})
            name, arg = fn.get("name", ""), ""
            try:
                arg = json.loads(fn.get("arguments") or "{}").get("arg", "")
            except json.JSONDecodeError:
                pass
            refused = _gate(name, arg, cfg, confirm, state=state)
            if refused is None:
                try:
                    result = tools.run(name, arg, cfg, harness)
                except Exception as e:
                    result = f"ERROR ({e})"
            else:
                result = refused
            steps.append({"tool": name, "arg": arg, "result": result})
            _publish(state, task, steps)
            _publish_guide(state, name, arg, result)
            # GUIDE() is a user-handoff (guide mode / no backend), not
            # a failure — don't burn the error budget on it.
            errors = errors + 1 if result.startswith(("ERROR", "SKIP",
                                                      "REFUS")) else 0
            messages.append({"role": "tool",
                             "tool_call_id": call.get("id", name),
                             "content": result})
            if name == "screenshot" and vision \
                    and result.startswith("SHOT "):
                _attach_image(messages, result[5:].strip())
            if errors > MAX_ERRORS:
                _goals.record_steps(steps)
                out = f"ABORTED (repeated failures): {_last(steps)}"
                trajectories.record(task, _app(harness), steps, out)
                return out
            if len(steps) >= max_steps:
                break
    out = f"ABORTED (max {max_steps} steps): {_last(steps)}"
    _goals.record_steps(steps)
    trajectories.record(task, _app(harness), steps, out)
    return out


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


def _app(harness: dict | None) -> str:
    """Active app class for trajectory grouping."""
    try:
        from . import platform
        return platform.active_window().get("class", "")
    except Exception:
        return ""


_GUIDE_RE = re.compile(r"(?:GUIDE|MOVE-GUIDE|CLICKED|MOVED)\((-?\d+),"
                       r"(-?\d+)\)")


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


def _attach_image(messages: list, path: str) -> None:
    """Feed the screenshot back as an image part on a follow-up user
    message — the model can't act on a screen it can't see. Keeps at
    most MAX_IMAGES image parts in the window (oldest dropped)."""
    import pathlib
    try:
        b64 = base64.b64encode(
            pathlib.Path(path).read_bytes()).decode()
    except OSError:
        return
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
    messages.append({"role": "user", "content": [
        {"type": "text", "text": "current screen:"},
        {"type": "image_url",
         "image_url": {"url": f"data:image/png;base64,{b64}"}}]})
