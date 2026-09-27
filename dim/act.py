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
import json
import urllib.error
import urllib.request

from . import config, tools

MAX_STEPS = 8
MAX_ERRORS = 2

SYSTEM = ("You are Dim's hands on a Linux desktop (Hyprland). Complete "
          "the user's task using the provided tools — keep steps minimal "
          "and prefer safe tools. When done, reply with one short "
          "sentence describing the outcome. If a tool is refused or "
          "skipped, do not retry it; work around or report the block.")


def _post(payload: dict) -> dict:
    req = urllib.request.Request(
        config.CHAT_ENDPOINT, data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {config.load_api_key()}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/duketopceo/dim-agent",
            "X-Title": "Dim",
        }, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _gate(name: str, arg: str, cfg: dict, confirm) -> str | None:
    """Returns a refusal string when the call is blocked, else None."""
    tier = tools.risk_of(name)
    if tier == "shell":
        if tools.denied(arg):
            return "REFUSED (denylisted command)"
        if cfg.get("agent", {}).get("allow_shell", "false") != "true":
            return "SKIPPED (shell disabled — set allow_shell=true)"
    if tier in ("mutating", "shell"):
        if confirm is None:
            return f"SKIPPED ({name} needs user confirmation)"
        if not confirm(f"run {name}: {arg or '(no arg)'}?"):
            return f"SKIPPED ({name} declined by user)"
    return None


def run_act_loop(task: str, cfg: dict, state=None,
                 harness: dict | None = None, confirm=None) -> str:
    """Drive the chat model through the toolbelt until it finishes or a
    bound trips. `confirm(prompt)->bool` asks the user (choice widget /
    IPC) when wired; without it mutating calls skip."""
    model = cfg.get("agent", {}).get("answer_model",
                                    "meta-llama/llama-4-maverick")
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": task}]
    steps, errors = [], 0

    while len(steps) < MAX_STEPS:
        data = _post({"model": model, "messages": messages,
                      "tools": tools.tool_schemas(), "tool_choice": "auto",
                      "max_tokens": 400})
        msg = (data.get("choices") or [{}])[0].get("message", {})
        calls = msg.get("tool_calls") or []
        if not calls:
            text = (msg.get("content") or "").strip()
            _publish(state, task, steps)
            return f"ACTED ({len(steps)} steps): {text or 'done'}"
        messages.append(msg)
        for call in calls:
            fn = call.get("function", {})
            name, arg = fn.get("name", ""), ""
            try:
                arg = json.loads(fn.get("arguments") or "{}").get("arg", "")
            except json.JSONDecodeError:
                pass
            refused = _gate(name, arg, cfg, confirm)
            if refused is None:
                try:
                    result = tools.run(name, arg, cfg, harness)
                except Exception as e:
                    result = f"ERROR ({e})"
            else:
                result = refused
            steps.append({"tool": name, "arg": arg, "result": result})
            _publish(state, task, steps)
            errors = errors + 1 if result.startswith(("ERROR", "SKIP",
                                                      "REFUS")) else 0
            messages.append({"role": "tool",
                             "tool_call_id": call.get("id", name),
                             "content": result})
            if errors > MAX_ERRORS:
                return f"ABORTED (repeated failures): {_last(steps)}"
            if len(steps) >= MAX_STEPS:
                break
    return f"ABORTED (max {MAX_STEPS} steps): {_last(steps)}"


def _publish(state, task: str, steps: list) -> None:
    if state is None:
        return
    try:
        state.transition("acting",
                         result=f"act step {len(steps)}: "
                                f"{steps[-1]['tool']}" if steps else "act")
    except Exception:
        pass


def _last(steps: list) -> str:
    return "; ".join(f"{s['tool']}→{s['result']}" for s in steps[-3:])
