"""mcp_call tool — let the act loop invoke a configured MCP server.

Arg: '<server> <tool> <json-args>' e.g.
  'browseros tabs {"action":"list"}'
  'dayflow get_today {}'

Servers come from inventory.json's `mcp` section (cursor/claude/devin/
opencode/codex configs). Two transports:

- http  — POST JSON-RPC to spec.url; accepts application/json and
          text/event-stream (SSE `data:` lines) responses.
- stdio — spawn spec.command, newline-framed JSON-RPC: initialize →
          notifications/initialized → tools/call → terminate.

Risk: mutating tier, so one confirm covers (mcp_call, app) per session.
Disabled entirely with [mcp] enabled = "false".
"""
import json
import os
import select
import subprocess
import time
import urllib.request

TIMEOUT = 20
_MAX_OUT = 4000
_PROTO = "2024-11-05"
_CLIENT = {"name": "wisp", "version": "1.0"}


def _server_spec(name: str) -> dict | None:
    from .. import inventory
    spec = (inventory.load().get("mcp") or {}).get(name)
    return spec


def _rpc(method: str, params: dict | None = None,
         rid: int = 1) -> dict:
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    if rid:
        msg["id"] = rid
    return msg


def _call_http(url: str, tool: str, args: dict) -> str:
    def post(payload):
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream"},
            method="POST")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read().decode("utf-8", "replace")
        # SSE: last 'data:' line is the response payload
        if "data:" in body and not body.lstrip().startswith("{"):
            for line in reversed(body.splitlines()):
                if line.startswith("data:"):
                    body = line[5:].strip()
                    break
        return json.loads(body) if body.strip() else {}

    post(_rpc("initialize",
              {"protocolVersion": _PROTO, "capabilities": {},
               "clientInfo": _CLIENT}))
    post(_rpc("notifications/initialized", {}, rid=0))
    resp = post(_rpc("tools/call",
                     {"name": tool, "arguments": args}))
    return _extract(resp)


def _call_stdio(command: str, spec: dict, tool: str,
                args: dict) -> str:
    argv = command.split() + [str(a) for a in spec.get("args", [])]
    env = dict(os.environ)
    for k, v in (spec.get("env") or {}).items():
        env[k] = os.path.expandvars(str(v))
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL,
                            text=True, env=env)
    try:
        def send(payload):
            proc.stdin.write(json.dumps(payload) + "\n")
            proc.stdin.flush()

        def read_reply(rid, deadline):
            fd = proc.stdout.fileno()
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise RuntimeError("reply timeout")
                # select guards the actual read — a server that emits
                # nothing can't stall us past the deadline
                if not select.select([fd], [], [], remaining)[0]:
                    raise RuntimeError("reply timeout")
                line = proc.stdout.readline()
                if not line:
                    raise RuntimeError("server closed pipe")
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                if m.get("id") == rid:
                    return m

        deadline = time.time() + TIMEOUT
        send(_rpc("initialize",
                  {"protocolVersion": _PROTO, "capabilities": {},
                   "clientInfo": _CLIENT}, rid=1))
        read_reply(1, deadline)
        send(_rpc("notifications/initialized", {}, rid=0))
        send(_rpc("tools/call",
                  {"name": tool, "arguments": args}, rid=2))
        return _extract(read_reply(2, deadline))
    finally:
        proc.kill()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass


def _extract(resp: dict) -> str:
    if "error" in resp:
        e = resp["error"]
        return f"MCP_ERROR {e.get('code')}: {e.get('message', '')[:200]}"
    result = resp.get("result") or {}
    if result.get("isError"):
        parts = result.get("content") or []
        text = " ".join(c.get("text", "") for c in parts
                        if isinstance(c, dict))
        return f"TOOL_ERROR {text[:400]}"
    parts = result.get("content") or []
    if parts and all(isinstance(c, dict) and c.get("type") == "text"
                     for c in parts):
        text = "\n".join(c.get("text", "") for c in parts)
    else:
        text = json.dumps(result)[:_MAX_OUT]
    return text[:_MAX_OUT] if text else "OK (empty result)"


def call(arg: str, cfg: dict) -> str:
    """'<server> <tool> <json-args>' — one MCP round-trip."""
    if cfg.get("mcp", {}).get("enabled", "true") == "false":
        return "SKIP (mcp disabled — [mcp] enabled=false)"
    parts = arg.split(None, 2)
    if len(parts) < 2:
        return ("SKIP (mcp_call needs '<server> <tool> "
                "{json-args}' — server names in inventory.json)")
    server, tool = parts[0], parts[1]
    try:
        args = json.loads(parts[2]) if len(parts) > 2 else {}
        if not isinstance(args, dict):
            return "SKIP (mcp args must be a JSON object)"
    except json.JSONDecodeError:
        return f"SKIP (bad json args: {parts[2][:80]!r})"
    spec = _server_spec(server)
    if not spec:
        return (f"SKIP (mcp server {server!r} not in inventory — "
                "run wispd inventory to rescan)")
    try:
        if spec.get("url") or spec.get("type") == "http":
            url = spec.get("url")
            if not url:
                return f"SKIP ({server} has no url)"
            return _call_http(url, tool, args)
        if spec.get("command"):
            return _call_stdio(spec["command"], spec, tool, args)
        return f"SKIP ({server} spec has no url or command)"
    except Exception as e:
        return f"MCP_FAIL ({type(e).__name__}: {e})"
