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
# tools whose success may change what's on screen → re-observe before
# the next pointer step
_SCREEN_CHANGING = {"click", "move", "type_text", "key", "launch",
                    "focus", "close", "workspace", "shell"}

SYSTEM = ("You are Wisp's hands on a Linux desktop (Hyprland). Complete "
          "the user's task using the provided tools — keep steps minimal "
          "and prefer safe tools. Take a screenshot first when the task "
          "needs on-screen targets; click/move take 'x,y' in that "
          "screenshot's pixels. Never click twice off the same screenshot "
          "— after anything that changes the screen (click, key, type, "
          "launch, focus, workspace, shell), re-screenshot before the "
          "next pointer action. A GUIDE result means the ghost cursor "
          "is parked there for the user to click — treat it as done, "
          "not an error, and continue or finish. CLICKED echoes the id "
          "of the element actually hit — if it is not the target you "
          "aimed at, re-aim from the image and click again rather than "
          "declaring success. For a dropdown/select, click it to focus "
          "then use key down/up and enter to choose — typing text into "
          "it does nothing. When done, reply with "
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
    if tier == "shell" or name in tools.TEXT_INPUT:
        if tools.denied(arg):
            return "REFUSED (denylisted command)"
        if tier == "shell" and \
                cfg.get("agent", {}).get("allow_shell",
                                         "false") != "true":
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
                 initial_image: str | None = None,
                 interrupted=None,
                 steps_out: list | None = None) -> str:
    """Drive the chat model through the toolbelt until it finishes or a
    bound trips. `confirm(prompt)->bool` asks the user (choice widget /
    IPC) when wired; without it mutating calls skip. `steps_out`, if a
    list, receives the run's step records for judging/replay."""
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
    hint = _train.hint_for(task, _surface(cfg))
    if hint:
        system += "\n\n" + hint
    from . import goals as _goals
    goal_txt = _goals.context_text()
    user_msg = (goal_txt + "\n\n" + task) if goal_txt else task
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
    max_steps = int(cfg.get("agents", {}).get("act_max_steps",
                                             str(MAX_STEPS)))
    # trigger-time image counts as the current observation; a mutating
    # step flips this and forces a fresh screenshot before the next
    # click/move
    screen_dirty = not initial_image

    while len(steps) < max_steps:
        if interrupted and interrupted():
            _goals.record_steps(steps)
            return "INTERRUPTED (user)"
        msg = _post(messages, cfg)
        calls = msg.get("tool_calls") or []
        if not calls and at_mode:
            parsed = _parse_action_text(msg.get("content") or "")
            if parsed is None:
                parse_misses += 1
                if parse_misses > 1:
                    _goals.record_steps(steps)
                    out = (f"STALLED (unparseable action replies): "
                           f"{_last(steps)}")
                    trajectories.record(task, _app(harness), steps, out,
                                        surface=_surface(cfg))
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
                trajectories.record(task, _app(harness), steps, out,
                                    surface=_surface(cfg))
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
                return "ASK_USER " + text[9:].strip()
            _goals.close("done")
            out = f"ACTED ({len(steps)} steps): {text or 'done'}"
            trajectories.record(task, _app(harness), steps, out,
                               surface=_surface(cfg))
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
                # soak fix: re-observe — a mutating step invalidates the
                # screen the last coordinates came from, so take a fresh
                # screenshot before any pointer call. Deterministic —
                # doesn't rely on the model remembering to look.
                if name in ("click", "move") and vision and screen_dirty:
                    shot = tools.run("screenshot", "", cfg, harness)
                    steps.append({"tool": "screenshot",
                                  "arg": "(auto re-observe)",
                                  "result": shot})
                    _publish(state, task, steps)
                    if shot.startswith("SHOT "):
                        _attach_image(messages, shot[5:].strip(), cfg)
                    screen_dirty = False
                try:
                    result = tools.run(name, arg, cfg, harness)
                except Exception as e:
                    result = f"ERROR ({e})"
            else:
                result = refused
            if name == "screenshot" and result.startswith("SHOT "):
                screen_dirty = False
            elif name in _SCREEN_CHANGING and not result.startswith(
                    ("ERROR", "SKIP", "REFUS")):
                screen_dirty = True
            steps.append({"tool": name, "arg": arg, "result": result})
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
                    and result.startswith("SHOT "):
                _attach_image(messages, result[5:].strip(), cfg)
            if errors > MAX_ERRORS:
                _goals.record_steps(steps)
                out = f"ABORTED (repeated failures): {_last(steps)}"
                trajectories.record(task, _app(harness), steps, out,
                               surface=_surface(cfg))
                return out
            if len(steps) >= max_steps:
                break
    out = f"ABORTED (max {max_steps} steps): {_last(steps)}"
    _goals.record_steps(steps)
    trajectories.record(task, _app(harness), steps, out,
                               surface=_surface(cfg))
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
        if fn in ("click", "left_double", "right_single", "tap"):
            xy = _at_coords(args)
            if xy is None:
                continue
            actions.append(("click", xy))
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


def _attach_image(messages: list, path: str, cfg: dict | None = None) -> None:
    """Feed the screenshot back as an image part on a follow-up user
    message — the model can't act on a screen it can't see. Keeps at
    most MAX_IMAGES image parts in the window (oldest dropped)."""
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
    caption = (f"current screen ({dims[0]}x{dims[1]} px — click/move "
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
