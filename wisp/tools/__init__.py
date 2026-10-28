"""Toolbelt: named tools Jev can route to, each with a risk tier and
autonomy metadata.

Risk tiers (the blast-radius vocabulary the denylist, allow_shell and
Jev's risk gate still speak):
  safe        — read-only/launch; executes immediately
  interactive — reversible desktop I/O (click, type, scroll, key,
                workspace); executes without prompting — the agent must
                act, not ask. The denylist still applies to text-bearing
                args so `type_text "rm -rf ~"` can't slip through.
  mutating    — irreversible-ish state changes (close, cancel, memory,
                skill edits, MCP calls); confirm-once per (tool, app)
  shell       — arbitrary command; always needs per-call confirmation
                and is subject to the denylist

Autonomy tiers (wisp/policy.py — when a step asks a human, U3/KTD9):
  T0 observe/navigate      — never confirms
  T1 reversible local      — runs confirm-free, renders in-flight + undo
  T2 irreversible/external — confirms at batched checkpoints
  T3 human-only            — pauses the run for a handoff ("needs you")

Risk → autonomy mapping for entries carrying no meta (dynamic skill_*
tools, callers that hand-register a bare 3-tuple):
  safe → T0 · interactive → T1 · mutating → T2 · shell → T2

Every static entry declares its meta as the fourth tuple element —
{"tier", "reversible", "external"}: the declared T-tier the policy
consults, whether a user can take the effect back, and whether it
reaches outside this machine. `memory`, `mcp_call` and `skill_manage`
declare their worst case; the policy refines per call (a `memory add`
is T1, an mcp read is T0, an OAuth/credential call is T3). The lint in
tests/test_policy.py fails when an entry lacks it.
"""
from . import desktop, mcpclient, social, system

RISK = {"safe": 0, "interactive": 1, "mutating": 2, "shell": 3}

AUTONOMY_TIERS = ("T0", "T1", "T2", "T3")

# risk tier → autonomy tier for entries with no declared meta
RISK_AUTONOMY = {"safe": "T0", "interactive": "T1",
                 "mutating": "T2", "shell": "T2"}

# hard refusals — checked before any confirmation prompt
SHELL_DENYLIST = ("rm -rf /", "rm -rf ~", "rm -rf $HOME", "mkfs",
                  "dd if=", ":(){ ", "shutdown", "reboot")

# interactive tools whose arg carries user-bound text/keystrokes —
# denylist applies so a prompt-free tier can't type destruction into a
# terminal
TEXT_INPUT = {"type_text", "key"}

REGISTRY = {
    "launch": (desktop.launch, "safe",
               "open an application — any installed app name works "
               "(see [env] apps=); a role like 'mail'/'files' opens "
               "the user's default handler (see [env] defaults=), and "
               "when that handler is a browser it opens the role's web "
               "app (see [web]); a domain/URL like 'gmail.com' opens "
               "in the browser",
               {"tier": "T0", "reversible": True, "external": False}),
    "focus": (desktop.focus, "safe", "focus a window by class",
              {"tier": "T0", "reversible": True, "external": False}),
    "tab": (desktop.tab, "safe",
            "switch to an already-open browser tab — arg: its title or "
            "site, e.g. 'stripe' or 'gmail'",
            {"tier": "T0", "reversible": True, "external": False}),
    "close": (desktop.close, "mutating",
              "close the active/matching window",
              {"tier": "T2", "reversible": False, "external": False}),
    "workspace": (desktop.workspace, "interactive",
                  "switch Hyprland workspace",
                  {"tier": "T1", "reversible": True, "external": False}),
    "notify": (system.notify_tool, "safe", "send a desktop notification",
               {"tier": "T0", "reversible": True, "external": False}),
    "screenshot": (system.screenshot, "safe",
                   "capture the screen to a file",
                   {"tier": "T0", "reversible": True, "external": False}),
    "observe": (None, "safe",
                "capture a frame of the focused app to inspect — arg: "
                "a control-channel panel name, or 'x1,y1,x2,y2' to "
                "crop a window-local region; the app's control channel "
                "when it ships one, else a window-cropped capture; "
                "the image comes back as the next observation "
                "(inspect only — its pixels are not the click "
                "coordinate space)",
                {"tier": "T0", "reversible": True,
                 "external": False}),  # wired in wisp/observe.py (U5)
    "type_text": (system.type_text, "interactive",
                  "type text into the focused window",
                  {"tier": "T1", "reversible": True, "external": False}),
    "fill": (system.fill, "interactive",
             "set a field's value directly — 'field-id value' "
             "(selects pick the matching option); dom-mode only",
             {"tier": "T1", "reversible": True, "external": False}),
    "click": (system.click, "interactive",
              "click at 'x,y' or target element e.g. 'monitor icon in menu bar' — "
              "in guide mode points the ghost cursor for the user",
              {"tier": "T1", "reversible": True, "external": False}),
    "move": (system.move, "interactive",
             "move the pointer to 'x,y' or target element",
             {"tier": "T1", "reversible": True, "external": False}),
    "ground": (system.ground, "safe",
               "locate on-screen UI element center: 'monitor icon in menu bar' -> GROUNDED(x,y)",
               {"tier": "T0", "reversible": True, "external": False}),
    "scroll": (system.scroll, "interactive",
               "scroll the view — 'down'/'up'/'down 400'/'bottom'",
               {"tier": "T1", "reversible": True, "external": False}),
    "key": (system.key, "interactive",
            "press a named key — 'enter', 'tab', 'esc', 'down', "
            "'pageup', 'pagedown', 'backspace', arrows",
            {"tier": "T1", "reversible": True, "external": False}),
    "mcp_call": (mcpclient.call, "mutating",
                 "call a tool on a configured MCP server — "
                 "'<server> <tool> <json-args>' e.g. 'browseros tabs "
                 "{\"action\":\"list\"}'. For strata-registered OAuth "
                 "services (wispd connect) the tool token is "
                 "'<category>/<action>'. Server names/URLs are in "
                 "inventory.json and the [env] context line",
                 {"tier": "T2", "reversible": False, "external": True}),
    "post": (social.post_draft, "safe",
             "preview an X post — 'post <text>'; always dry-run",
             {"tier": "T0", "reversible": True, "external": False}),
    "post_send": (social.post_open, "mutating",
                  "open X's compose window pre-filled — "
                  "'post_send <text>'; the user presses Post",
                  {"tier": "T2", "reversible": False, "external": True}),
    "codegraph": (system.codegraph, "safe",
                  "query a repo's code-graph index (CBM): "
                  "'<tool> <json-args>' e.g. 'search_graph "
                  "{\"project\":\"wisp\",\"query\":\"State\"}'",
                  {"tier": "T0", "reversible": True, "external": False}),
    "shell": (system.shell, "shell", "run a shell command",
              {"tier": "T2", "reversible": False, "external": True}),
    "search_files": (system.search_files, "safe",
                     "find files by name under ~",
                     {"tier": "T0", "reversible": True, "external": False}),
    "agent_spawn": (None, "safe", "spawn a named ori opencode agent",
                    {"tier": "T1", "reversible": True,
                     "external": False}),  # wired in wisp.agents
    "task_status": (None, "safe", "report a named agent's status",
                    {"tier": "T0", "reversible": True,
                     "external": False}),
    "task_cancel": (None, "mutating", "cancel a named agent",
                    {"tier": "T2", "reversible": False,
                     "external": False}),
    "memory": (None, "mutating", "curate long-term memory — "
               "'memory|add|new fact' or 'memory|replace|old|new' or "
               "'memory|remove|old' (target 'user' for USER.md)",
               {"tier": "T2", "reversible": False, "external": False}),
    "recall": (None, "safe", "search long-term recall — "
               "'search <query>' returns top-k indexed context",
               {"tier": "T0", "reversible": True, "external": False}),
    "skill_manage": (None, "mutating", "author a self-taught skill — "
                     "'create|name|description|body', 'edit|name||body', "
                     "'write_file|name|filename|body', 'delete|name', "
                     "'remove_file|name|filename', 'list'",
                     {"tier": "T2", "reversible": False,
                      "external": False}),
    "skill_view": (None, "safe", "read a skill's full SKILL.md by name",
                   {"tier": "T0", "reversible": True,
                    "external": False}),
    "ask_user": (None, "safe",
                 "ask the user a question mid-task and wait for the "
                 "reply — 'question text' or 'question | option | "
                 "option'; the pick or spoken answer comes back as the "
                 "tool result",
                 {"tier": "T0", "reversible": True,
                     "external": False}),  # wired in the act loop (U4)
}


# registry entries whose executor lives outside REGISTRY[0] — the
# dispatch in run() owns these names (ask_user's lives in the act
# loop, not here); tool_schemas must not drop them.
EXTERN = frozenset({"agent_spawn", "task_status", "task_cancel",
                    "memory", "recall", "skill_manage", "skill_view",
                    "ask_user", "observe"})

# loop-internal backchannels the model can call inside a run but that
# have no route-level executor — Jev must never route to them (run()
# could only answer SKIP)
LOOP_ONLY = frozenset({"ask_user"})


def get(name: str):
    return REGISTRY.get(name)


def meta_of(name: str) -> dict:
    """The declared autonomy meta for a static entry
    ({"tier","reversible","external"}); {} for dynamic entries —
    policy maps their risk tier instead."""
    entry = REGISTRY.get(name)
    if entry is not None and len(entry) > 3:
        return entry[3]
    return {}


def describe() -> dict:
    """Criteria text for Jev's tool question — routable tools only;
    LOOP_ONLY entries are advertised in tool_schemas but can't be
    dispatched as a route."""
    return {name: e[2] for name, e in REGISTRY.items()
            if name not in LOOP_ONLY}


def tool_schemas() -> list:
    """OpenAI-style tool definitions derived from the registry — one
    string arg per tool. Derived, not static, so new tools appear in the
    act loop automatically."""
    out = []
    for name, e in REGISTRY.items():
        fn, tier, desc = e[0], e[1], e[2]
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
    if name in system.BLOCKED_INPUT:
        return "safe"   # blocked gestures never inject — never gate them
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
    if name in system.BLOCKED_INPUT:
        return system.blocked_scope(name)
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
    if name == "observe":
        from .. import observe as _obs
        return _obs.observe(arg, cfg)
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
              system.scroll, system.key, system.type_text,
              system.fill):
        return fn(arg, cfg)
    if fn is mcpclient.call:
        return fn(arg, cfg)
    return fn(arg)


def denied(cmd: str) -> bool:
    c = cmd.lower()
    return any(d in c for d in SHELL_DENYLIST)
