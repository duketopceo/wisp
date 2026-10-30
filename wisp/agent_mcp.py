"""MCP stdio bridge and tool allowlist for background agents (U8, R13).

OpenCode launches `wispd agent-mcp` as its one MCP server. The bridge
answers `initialize`, `tools/list` and `tools/call` on newline-framed
JSON-RPC (the server side of tools/mcpclient.py) and forwards each call
to the daemon as `agent_tool {token, name, args}`. The daemon is the
authority: `handle()` checks the session token, that the peer is the
marked process of that session, and the allowlist. The allowlist is the
boundary, not the token's secrecy (KTD10, KTD11).

Tokens are 32 random bytes, urlsafe, held in memory only, minted per
session and revoked when it ends. They are never logged.
"""
import json
import secrets
import threading
import time

from . import agents, config

PROTO = "2024-11-05"
_SERVER = {"name": "wisp", "version": "1.0"}

_MEMORY_TOOLS = frozenset({"recall", "memory_read"})
_TASK_TOOLS = frozenset({"task_status", "task_output", "task_artifacts"})
_NAME_SCHEMA = {"type": "object", "properties": {"name": {
    "type": "string", "description": "your own task name (optional)"}}}

# name -> (description, inputSchema); order is the tools/list order
ALLOWLIST = {
    "recall": ("Search Wisp's long-term recall for context.",
               {"type": "object", "properties": {"query": {
                   "type": "string"}}, "required": ["query"]}),
    "memory_read": ("Read the user's USER.md and MEMORY.md (read-only).",
                    {"type": "object", "properties": {}}),
    "skill_list": ("List Wisp skills with their descriptions.",
                   {"type": "object", "properties": {}}),
    "skill_view": ("Read one skill's full SKILL.md by name.",
                   {"type": "object", "properties": {"name": {
                       "type": "string"}}, "required": ["name"]}),
    "task_status": ("Report your own task's status.", _NAME_SCHEMA),
    "task_output": ("Read your own task's log output.", _NAME_SCHEMA),
    "task_artifacts": ("List your own task's output files.", _NAME_SCHEMA),
    "ask_user": ("Ask the user a question and wait for the answer. "
                 "Without choices they answer in free speech.",
                 {"type": "object", "properties": {
                     "question": {"type": "string"},
                     "choices": {"type": "array",
                                 "items": {"type": "string"}}},
                  "required": ["question"]}),
}

# -- token registry ----------------------------------------------------

_TOKENS: dict = {}
_TLOCK = threading.Lock()
_PENDING: set = set()       # helpers with an ask_user in flight


def is_asking(names) -> bool:
    """True while any of `names` has an ask_user in flight."""
    with _TLOCK:
        return bool(set(names) & _PENDING)


def mint(session: str) -> str:
    tok = secrets.token_urlsafe(32)
    with _TLOCK:
        _TOKENS[tok] = str(session)
    return tok


def revoke(token: str) -> None:
    with _TLOCK:
        _TOKENS.pop(token, None)


def lookup(token) -> str | None:
    with _TLOCK:
        return _TOKENS.get(token) if isinstance(token, str) else None


# -- cfg ---------------------------------------------------------------

def _agents_cfg(cfg) -> dict:
    return (cfg or {}).get("agents") or {}


def memory_enabled(cfg) -> bool:
    v = _agents_cfg(cfg).get("mcp_memory", True)
    return str(v).strip().lower() not in ("false", "0", "no", "off")


def ask_timeout_s(cfg) -> float:
    try:
        return max(1.0, float(_agents_cfg(cfg).get("ask_timeout_s", 120)))
    except (TypeError, ValueError):
        return 120.0


def tool_defs(cfg) -> list:
    """The MCP `tools/list` payload: the allowlist, minus the memory
    tools when [agents] mcp_memory is off."""
    mem = memory_enabled(cfg)
    return [{"name": n, "description": d, "inputSchema": s}
            for n, (d, s) in ALLOWLIST.items()
            if mem or n not in _MEMORY_TOOLS]


# -- daemon side -------------------------------------------------------

def _refuse(sess: str, name: str, reason: str, tf) -> dict:
    agents.record_refusal(sess, name, tasks_file=tf)
    return {"ok": False, "error": "tool_refused", "reason": reason,
            "name": name}


def handle(cmd: dict, peer: dict | None, cfg: dict, ask_queue=None,
           tasks_file=None, clock=None) -> dict:
    """The `agent_tool` IPC command. Token first, then peer, then name."""
    tf = tasks_file if tasks_file is not None else config.TASKS_FILE
    sess = lookup(cmd.get("token"))
    if sess is None:
        return {"ok": False, "error": "bad_token"}
    rec = agents._find(sess, tf)
    info = agents.classify_peer(peer, tasks_file=tf)
    if (rec is None or rec.get("kind") != "session"
            or not info.get("marked") or info.get("spoofed")
            or info.get("task_id") not in (rec["id"],
                                           rec.get("acp_process"))):
        return {"ok": False, "error": "not_marked_peer"}
    name = str(cmd.get("name") or "")
    args = cmd.get("args")
    args = args if isinstance(args, dict) else {}
    if name not in ALLOWLIST:
        return _refuse(sess, name, "not_allowlisted", tf)
    if name in _MEMORY_TOOLS and not memory_enabled(cfg):
        return _refuse(sess, name, "memory_off", tf)
    helper = rec["name"]
    if name in _TASK_TOOLS:
        want = str(args.get("name") or helper).strip().lower()
        if want not in (helper.lower(), rec["id"].lower()):
            return _refuse(sess, name, "other_helper", tf)
        if name == "task_status":
            return {"ok": True, "result": agents.status(helper, tf)}
        fn = agents.output if name == "task_output" else agents.artifacts
        return {"ok": True, "result": json.dumps(fn(helper, tf))}
    if name == "ask_user":
        return _ask(helper, args, cfg, ask_queue, clock or time.monotonic)
    from . import tools
    if name == "recall":
        arg = str(args.get("query") or "")
    elif name == "skill_view":
        arg = str(args.get("name") or "")
    else:
        arg = ""
    return {"ok": True, "result": tools.run(name, arg, cfg)}


def _ask(helper: str, args: dict, cfg: dict, queue, clock) -> dict:
    question = str(args.get("question") or "").strip()
    if not question:
        return {"ok": False, "error": "empty_question"}
    if queue is None:
        return {"ok": False, "error": "ask_unavailable"}
    raw = args.get("choices")
    choices = [str(c) for c in raw] if isinstance(raw, list) else []
    with _TLOCK:
        if helper in _PENDING:
            return {"ok": False, "error": "ask_pending"}
        _PENDING.add(helper)
    try:
        secs = ask_timeout_s(cfg)
        done, box = threading.Event(), []

        def on_answer(pick):
            box.append(pick)
            done.set()
        queue.submit(helper, "question", question, choices,
                     clock() + secs, on_answer)
        done.wait(secs + 5)     # the queue ends every ask at its deadline
    finally:
        with _TLOCK:
            _PENDING.discard(helper)
    return {"ok": True, "result": (box[0] if box and box[0] else "no answer")}


# -- bridge side -------------------------------------------------------

def _reply(rid, result=None, error=None) -> dict:
    msg = {"jsonrpc": "2.0", "id": rid}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    return msg


def _call(send, token, params) -> dict:
    cmd = {"cmd": "agent_tool", "token": token,
           "name": str(params.get("name") or ""),
           "args": params.get("arguments") or {}}
    try:
        out = send(cmd)
    except (OSError, ValueError):
        return {"error": {"code": -32000, "message": "wisp unavailable"}}
    if out.get("ok"):
        return {"result": {"content": [
            {"type": "text", "text": str(out.get("result", ""))}]}}
    why = out.get("reason") or out.get("error") or "refused"
    return {"error": {"code": -32001, "message": f"refused: {why}"}}


def serve(inp, out, send, token: str, cfg: dict) -> None:
    """Run the stdio loop until `inp` ends. `send(cmd) -> reply` is the
    daemon socket call."""
    for line in inp:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if not isinstance(msg, dict) or "id" not in msg:
            continue            # notifications get no reply
        rid, method = msg["id"], msg.get("method")
        params = msg.get("params") or {}
        if method == "initialize":
            r = _reply(rid, {"protocolVersion": params.get(
                "protocolVersion") or PROTO,
                "capabilities": {"tools": {}}, "serverInfo": _SERVER})
        elif method == "ping":
            r = _reply(rid, {})
        elif method == "tools/list":
            r = _reply(rid, {"tools": tool_defs(cfg)})
        elif method == "tools/call":
            r = _reply(rid, **_call(send, token, params))
        else:
            r = _reply(rid, error={"code": -32601,
                                   "message": f"no method {method}"})
        out.write(json.dumps(r) + "\n")
        out.flush()
