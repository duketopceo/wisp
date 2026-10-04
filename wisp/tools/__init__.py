"""Toolbelt: named tools Jev can route to, each with a risk tier.

Tiers:
  safe        — read-only/launch; executes immediately
  interactive — reversible desktop I/O (click, type, scroll, key,
                workspace); executes without prompting — the agent must
                act, not ask. The denylist still applies to text-bearing
                args so `type_text "rm -rf ~"` can't slip through.
  mutating    — irreversible-ish state changes (close, cancel, memory,
                skill edits, MCP calls); confirm-once per (tool, app)
  shell       — arbitrary command; always needs per-call confirmation
                and is subject to the denylist
"""
from . import desktop, mcpclient, system

RISK = {"safe": 0, "interactive": 1, "mutating": 2, "shell": 3}

# hard refusals — checked before any confirmation prompt
SHELL_DENYLIST = ("rm -rf /", "rm -rf ~", "rm -rf $HOME", "mkfs",
                  "dd if=", ":(){ ", "shutdown", "reboot")

# interactive tools whose arg carries user-bound text/keystrokes —
# denylist applies so a prompt-free tier can't type destruction into a
# terminal
TEXT_INPUT = {"type_text", "key"}

REGISTRY = {
    "launch": (desktop.launch, "safe", "open an application"),
    "focus": (desktop.focus, "safe", "focus a window by class"),
    "close": (desktop.close, "mutating", "close the active/matching window"),
    "workspace": (desktop.workspace, "interactive", "switch Hyprland workspace"),
    "notify": (system.notify_tool, "safe", "send a desktop notification"),
    "screenshot": (system.screenshot, "safe", "capture the screen to a file"),
    "type_text": (system.type_text, "interactive", "type text into the focused window"),
    "click": (system.click, "interactive",
              "click at 'x,y' or target element e.g. 'monitor icon in menu bar' — "
              "in guide mode points the ghost cursor for the user"),
    "move": (system.move, "interactive",
             "move the pointer to 'x,y' or target element"),
    "ground": (system.ground, "safe",
               "locate on-screen UI element center: 'monitor icon in menu bar' -> GROUNDED(x,y)"),
    "scroll": (system.scroll, "interactive",
               "scroll the view — 'down'/'up'/'down 400'/'bottom'"),
    "key": (system.key, "interactive",
            "press a named key — 'enter', 'tab', 'esc', 'down', "
            "'pageup', 'pagedown', 'backspace', arrows"),
    "mcp_call": (mcpclient.call, "mutating",
                 "call a tool on a configured MCP server — "
                 "'<server> <tool> <json-args>' e.g. 'browseros tabs "
                 "{\"action\":\"list\"}'. For strata-registered OAuth "
                 "services (wispd connect) the tool token is "
                 "'<category>/<action>'. Server names/URLs are in "
                 "inventory.json and the [env] context line"),
>>>>>>> origin/master
    "codegraph": (system.codegraph, "safe",
                  "query a repo's code-graph index (CBM): "
                  "'<tool> <json-args>' e.g. 'search_graph "
                  "{\"project\":\"wisp\",\"query\":\"State\"}'"),
    "shell": (system.shell, "shell", "run a shell command"),
    "search_files": (system.search_files, "safe", "find files by name under ~"),
    "agent_spawn": (None, "safe", "spawn a named ori opencode agent"),  # wired in wisp.agents
    "task_status": (None, "safe", "report a named agent's status"),
    "task_cancel": (None, "mutating", "cancel a named agent"),
    "memory": (None, "mutating", "curate long-term memory — "
               "'memory|add|new fact' or 'memory|replace|old|new' or "
               "'memory|remove|old' (target 'user' for USER.md)"),
    "recall": (None, "safe", "search long-term recall — "
               "'search <query>' returns top-k indexed context"),
    "skill_manage": (None, "mutating", "author a self-taught skill — "
                     "'create|name|description|body', 'edit|name||body', "
                     "'write_file|name|filename|body', 'delete|name', "
                     "'remove_file|name|filename', 'list'"),
    "skill_view": (None, "safe", "read a skill's full SKILL.md by name"),
}


# registry entries whose executor lives outside REGISTRY[0] — the
# dispatch in run() owns these names; tool_schemas must not drop them.
EXTERN = frozenset({"agent_spawn", "task_status", "task_cancel",
                    "memory", "recall", "skill_manage", "skill_view"})


def get(name: str):
    return REGISTRY.get(name)


def describe() -> dict:
    """Criteria text for Jev's tool question."""
    return {name: desc for name, (_, _, desc) in REGISTRY.items()}


def tool_schemas() -> list:
    """OpenAI-style tool definitions derived from the registry — one
    string arg per tool. Derived, not static, so new tools appear in the
    act loop automatically."""
    out = []
    for name, (fn, tier, desc) in REGISTRY.items():
        if fn is None and name not in EXTERN:
            continue
        out.append({
            "type": "function",
            "function": {
                "name": name,
                "description": f"[{tier}] {desc}",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "arg": {"type": "string",
                                "description": "the argument or payload "
                                               "for this tool"}
                    },
                    "required": [],
                },
            },
        })
    return out


def risk_of(name: str) -> str:
    if name.startswith("skill_"):
        from .. import skills
        return skills.tier_of(name)  # dynamic — skills can appear mid-session
    entry = REGISTRY.get(name)
    return entry[1] if entry else "shell"


def run(name: str, arg: str, cfg: dict, harness: dict | None = None) -> str:
    """Execute a tool by name. Confirm-gating happens in the pipeline
    before run() is called — this is the bare executor."""
    import time as _time
    from .. import trace as _trace
    _t = _time.monotonic()
    _trace.emit(_trace.current(), "tool_call", "tool",
                {"name": name, "args": arg})
    _out = _run_inner(name, arg, cfg, harness)
    _trace.emit(_trace.current(), "tool_result", "tool",
                {"name": name, "result": _out},
                round((_time.monotonic() - _t) * 1000))
    return _out


def _run_inner(name: str, arg: str, cfg: dict,
               harness: dict | None = None) -> str:
    from .. import agents
    if name == "agent_spawn":
        return agents.spawn(arg, cfg)
    if name == "task_status":
        return agents.status(arg)
    if name == "task_cancel":
        return agents.cancel(arg)
    if name == "memory":
        from .. import memory
        return memory.run(arg)
    if name == "recall":
        from .. import recall
        return recall.run(arg)
    if name == "skill_manage":
        from .. import skills
        return skills.run_manage(arg)
    if name == "skill_view":
        from .. import skills
        return skills.run_view(arg)
    if name.startswith("skill_"):
        from .. import skills
        out = skills.run_tool(name, arg)
        return out if out is not None \
            else f"SKIP (tool {name!r} unavailable)"
    entry = REGISTRY.get(name)
    if entry is None or entry[0] is None:
        return f"SKIP (tool {name!r} unavailable)"
    fn = entry[0]
    if fn is desktop.launch:
        return fn(arg, cfg, harness)
    if fn in (system.click, system.move, system.screenshot,
              system.scroll, system.key, system.type_text):
        return fn(arg, cfg)
    if fn is mcpclient.call:
        return fn(arg, cfg)
    return fn(arg)


def denied(cmd: str) -> bool:
    c = cmd.lower()
    return any(d in c for d in SHELL_DENYLIST)
