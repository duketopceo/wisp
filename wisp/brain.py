"""Brain providers — pluggable chat backends (issue #13, U6).

`[brain] default = "provider:model"` selects the answer brain; each
`[brain.<provider>]` section declares base_url/key_env/vision/tools.
Kinds:
- openrouter / openai_compat: POST {base}/chat/completions (Ollama's
  OpenAI shim, LM Studio, vLLM, corporate gateways — optional key)
- ollama: native POST {base}/api/chat (images on the message itself)
- mlx: mlx-lm server — openai_compat wire shape + /v1/models probe

Jev routing stays on the OpenRouter decisions endpoint regardless of
brain — that's the router, not the answer provider.

Fallback chain (backend U7): `[brain] fallback = "name:model, ..."`
lists entries tried in order after `default`. A paid entry (OpenRouter,
or `paid = "true"` on its section) is skipped unless
`[brain] allow_paid = "true"` and `budget_ok()` (U10 hook). Each call
gets ONE fast retry on connection refused/reset only (never a timeout —
that would double the wait); streaming entries must produce a first
token within `[brain] first_token_s` (default 3) or the chain moves on.
Once tokens have reached the caller a failure ends the turn rather than
falling back (a second answer would be spliced onto the first). When
every entry fails the turn ends `brain_down`.
"""
import json
import pathlib
import time
import urllib.request
import urllib.error

from . import cancel, config, errors_codes

# set by the daemon: a health.HealthRegistry; entries it knows are down
# are skipped without a connection attempt
HEALTH = None

UA = "wisp/1.0"
APP_URL = "https://github.com/duketopceo/wisp"
APP_TITLE = "Wisp"


def app_headers(url: str) -> dict:
    """OpenRouter attribution headers — every call to openrouter.ai
    must carry the app name (HTTP-Referer + X-Title) so usage/limits
    report correctly."""
    return {"HTTP-Referer": APP_URL, "X-Title": APP_TITLE} \
        if "openrouter.ai" in (url or "") else {}

_BUILTINS = {
    "openrouter": {"kind": "openai_compat",
                   "base_url": "https://openrouter.ai/api/v1",
                   "key_env": "OPENROUTER_API_KEY",
                   "vision": "true", "tools": "true"},
    "ollama": {"kind": "ollama",
               "base_url": "http://localhost:11434",
               "key_env": "", "vision": "false", "tools": "false"},
    "openai_compat": {"kind": "openai_compat", "base_url": "",
                      "key_env": "", "vision": "false",
                      "tools": "false"},
    "mlx": {"kind": "openai_compat",
            "base_url": "http://localhost:8080/v1",
            "key_env": "", "vision": "false", "tools": "false"},
}


def _make(cfg: dict, name: str, model: str) -> dict:
    p = dict(_BUILTINS.get(name, _BUILTINS["openai_compat"]))
    p.update({k: v for k, v in cfg.get(f"brain.{name}", {}).items()})
    p["name"], p["model"] = name, model
    if "paid" in p:
        p["paid"] = str(p["paid"]).lower() == "true"
    else:
        p["paid"] = "openrouter.ai" in (p.get("base_url") or "")
    return p


def _split(cfg: dict, spec: str) -> tuple:
    if ":" in spec:
        name, model = spec.split(":", 1)
        return name.strip(), model.strip()
    return spec.strip(), cfg.get("agent", {}) \
        .get("answer_model", "meta-llama/llama-4-maverick")


def provider(cfg: dict) -> dict:
    """Resolve `[brain] default = "name:model"` → merged provider dict
    {name, kind, base_url, key_env, model, vision, tools, paid}. Falls
    back to the legacy agent.answer_model on the openrouter provider."""
    default = cfg.get("brain", {}).get("default", "")
    name, model = _split(cfg, default or "openrouter")
    return _make(cfg, name, model)


def chain(cfg: dict) -> list:
    """Primary provider followed by `[brain] fallback` entries."""
    out = [provider(cfg)]
    for spec in cfg.get("brain", {}).get("fallback", "").split(","):
        if spec.strip():
            out.append(_make(cfg, *_split(cfg, spec)))
    return out


_SPEND_LOG = pathlib.Path.home() / ".local/share/wisp/spend.jsonl"
_USAGE = {"cost": 0.0, "prompt_tokens": 0, "completion_tokens": 0,
          "calls": 0}


def reset_usage() -> None:
    for k in _USAGE:
        _USAGE[k] = 0


def usage_totals() -> dict:
    return dict(_USAGE)


def _track_usage(resp: dict, model: str = "") -> None:
    u = resp.get("usage") or {}
    cost = u.get("cost")
    _USAGE["calls"] += 1
    _USAGE["prompt_tokens"] += int(u.get("prompt_tokens") or 0)
    _USAGE["completion_tokens"] += int(u.get("completion_tokens") or 0)
    if cost is None:
        return
    _USAGE["cost"] += float(cost)
    try:
        _SPEND_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_SPEND_LOG, "a") as f:
            f.write(json.dumps({"ts": time.time(), "model": model,
                                "cost": float(cost),
                                "prompt_tokens": u.get("prompt_tokens"),
                                "completion_tokens":
                                    u.get("completion_tokens")}) + "\n")
    except OSError:
        pass


def spend_today() -> float:
    """Sum of today's recorded spend (USD) across all callers in this
    process + earlier runs — the local ledger behind budget_ok()."""
    day = time.strftime("%Y-%m-%d")
    total = 0.0
    try:
        with open(_SPEND_LOG) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if time.strftime("%Y-%m-%d",
                                 time.localtime(r.get("ts", 0))) == day:
                    total += float(r.get("cost") or 0)
    except OSError:
        pass
    return total


def budget_ok() -> bool:
    """False once today's recorded spend passes [brain] daily_cap_usd
    (default $8). Applies to paid fallback entries; the primary model
    is always allowed so the agent never dies outright."""
    try:
        cap = float(cfg_default_cap())
    except (TypeError, ValueError):
        cap = 8.0
    return spend_today() < cap


def cfg_default_cap():
    try:
        return config.load_config().get("brain", {}) \
            .get("daily_cap_usd", 8.0)
    except Exception:
        return 8.0


def supports_vision(cfg: dict) -> bool:
    return provider(cfg).get("vision", "false") == "true"


def supports_tools(cfg: dict) -> bool:
    return provider(cfg).get("tools", "false") == "true"


def _tools_ok(p: dict) -> bool:
    return p.get("tools", "false") == "true"


def action_text(cfg: dict) -> bool:
    """Provider speaks literal action text (UI-TARS: 'Action:
    click(x,y)') instead of OpenAI tool_calls — the act loop parses
    replies into the same dispatch."""
    return provider(cfg).get("action_text", "false") == "true"


def _first_token_s(cfg: dict) -> float:
    try:
        return float(cfg.get("brain", {}).get("first_token_s", "3"))
    except ValueError:
        return 3.0


def _post(url: str, headers: dict, body: dict, timeout: float = 60) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"User-Agent": UA, "Content-Type": "application/json",
                 **headers}, method="POST")
    with cancel.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _headers(p: dict) -> dict:
    key = config.load_env_key(p.get("key_env", "")) \
        if p.get("key_env") else ""
    headers = {}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    headers.update(app_headers(p["base_url"]))
    return headers


def _ollama_msgs(messages: list) -> list:
    msgs = []
    for m in messages:
        m = dict(m)
        if isinstance(m.get("content"), list):
            text = "".join(c.get("text", "") for c in m["content"]
                           if c.get("type") == "text")
            imgs = [c["image_url"]["url"].split(",", 1)[-1]
                    for c in m["content"] if c.get("type") == "image_url"]
            m["content"] = text
            if imgs:
                m["images"] = imgs
        msgs.append(m)
    return msgs


def _chat_one(p: dict, messages: list, tools, timeout) -> dict:
    base = p["base_url"].rstrip("/")
    if p["kind"] == "ollama":
        body = {"model": p["model"], "messages": _ollama_msgs(messages),
                "stream": False}
        if tools and _tools_ok(p):
            body["tools"] = tools
        resp = _post(f"{base}/api/chat", {}, body, timeout)
        msg = resp.get("message", {})
        return {"content": msg.get("content", ""), "raw": msg}
    body = {"model": p["model"], "messages": messages, "max_tokens": 600,
            "usage": {"include": True}}
    if tools and _tools_ok(p):
        body["tools"] = tools
        body["tool_choice"] = "auto"
    resp = _post(f"{base}/chat/completions", _headers(p), body, timeout)
    _track_usage(resp, p["model"])
    msg = (resp.get("choices") or [{}])[0].get("message", {})
    return {"content": msg.get("content", ""), "raw": msg}


def _relax(r, timeout) -> None:
    """After the first token the per-read socket timeout goes from the
    first-token deadline back to the normal call timeout."""
    try:
        r.fp.raw._sock.settimeout(timeout)
    except Exception:
        pass


def _stream_one(p: dict, messages: list, on_delta, timeout,
                first_token_s: float) -> dict:
    base = p["base_url"].rstrip("/")
    ollama = p["kind"] == "ollama"
    if ollama:
        body = {"model": p["model"], "messages": _ollama_msgs(messages),
                "stream": True}
        url, headers = f"{base}/api/chat", {}
    else:
        body = {"model": p["model"], "messages": messages,
                "max_tokens": 600, "stream": True,
                "usage": {"include": True}}
        url, headers = f"{base}/chat/completions", _headers(p)
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"User-Agent": UA, "Content-Type": "application/json",
                 **headers}, method="POST")
    t0 = time.monotonic()
    acc, msg, usage = "", {}, None
    try:
        with cancel.urlopen(req, timeout=first_token_s) as r:
            for raw in r:
                cancel.check()
                line = raw.decode("utf-8", "replace").strip()
                if ollama:
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    piece = (chunk.get("message") or {}).get("content") \
                        or ""
                    done = bool(chunk.get("done"))
                else:
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    usage = chunk.get("usage") or usage
                    choice = (chunk.get("choices") or [{}])[0]
                    piece = (choice.get("delta") or {}).get("content") \
                        or ""
                    if choice.get("message"):
                        msg = choice["message"]
                    done = False
                if piece:
                    if not acc:
                        _relax(r, timeout)
                    acc += piece
                    if on_delta:
                        on_delta(acc)
                elif not acc and time.monotonic() - t0 > first_token_s:
                    raise TimeoutError(
                        f"no first token within {first_token_s:g}s")
                if done:
                    break
        cancel.check()  # a closed socket ends the loop like EOF
    except Exception as e:
        if cancel.is_cancelled():
            raise cancel.Cancelled() from e
        if acc:  # the caller already saw text: never splice a 2nd answer
            err = errors_codes.classify(e, "brain_down")
            err.committed = True
            raise err from e
        raise
    if usage and not ollama:
        _track_usage({"usage": usage}, p["model"])
    return {"content": acc, "raw": msg or {"content": acc}}


def _describe(p: dict, e: Exception) -> str:
    if errors_codes.is_connection_failure(e):
        return (f"brain provider '{p['name']}' unreachable at "
                f"{p['base_url']} ({e})")
    if errors_codes.is_timeout(e):
        return f"brain provider '{p['name']}' timed out ({e})"
    return f"brain provider '{p['name']}' failed ({e})"


def _attempt(p: dict, fn):
    """Call fn(p); one fast retry on connection refused/reset only."""
    try:
        return fn(p)
    except Exception as e:
        if cancel.is_cancelled():
            raise cancel.Cancelled() from e
        if getattr(e, "committed", False) \
                or not errors_codes.is_connection_failure(e):
            raise
        time.sleep(0.05)
        return fn(p)


def _run_chain(cfg: dict, fn, tools=None) -> dict:
    from . import trace
    allow_paid = cfg.get("brain", {}).get("allow_paid", "false") == "true"
    failures: list = []
    first_failed = None
    for i, p in enumerate(chain(cfg)):
        cancel.check()  # a cancelled turn never moves to the next brain
        if not p["base_url"]:
            failures.append(f"brain provider '{p['name']}' needs "
                            f"brain.{p['name']}.base_url")
        elif i and p["paid"] and not (allow_paid and budget_ok()):
            failures.append(f"{p['name']}: paid entry skipped")
            continue
        elif i and tools and not _tools_ok(p):
            failures.append(f"{p['name']}: no tool support, skipped")
            continue
        elif HEALTH is not None and HEALTH.known_down(
                f"brain_{p['name']}"):
            failures.append(f"{p['name']}: known down, skipped")
        else:
            try:
                res = _attempt(p, fn)
            except Exception as e:
                if getattr(e, "committed", False) \
                        or isinstance(e, cancel.Cancelled):
                    raise
                failures.append(_describe(p, e))
                if HEALTH is not None:
                    HEALTH.report_failure(f"brain_{p['name']}",
                                          "brain_down")
            else:
                res["provider"] = p["name"]
                res["fallback_from"] = first_failed
                if first_failed:
                    trace.emit(trace.current(), "brain_fallback", "brain",
                               {"fallback_from": first_failed,
                                "to": p["name"], "model": p["model"],
                                "tried": failures[-3:]})
                return res
        if first_failed is None:
            first_failed = p["name"]
    raise errors_codes.WispError("brain_down", "; ".join(failures))


def chat(messages: list, cfg: dict, tools: list | None = None,
         timeout: float = 60) -> dict:
    """Provider-agnostic chat call through the fallback chain →
    {"content", "raw", "provider", "fallback_from"}. Caller owns message
    assembly (memory/session/screens). `tools` = OpenAI-style schemas;
    included only for providers that declare tools support."""
    return _run_chain(
        cfg, lambda p: _chat_one(p, messages, tools, timeout), tools)


def chat_stream(messages: list, cfg: dict, on_delta=None,
                timeout: float = 60) -> dict:
    """Streaming chat through the fallback chain. `on_delta(accumulated
    _text)` fires per chunk. OpenAI-compatible providers stream SSE;
    ollama streams NDJSON from /api/chat. The first token must arrive
    within `[brain] first_token_s` (default 3) or the next entry is
    tried."""
    ft = min(_first_token_s(cfg), timeout)
    return _run_chain(
        cfg, lambda p: _stream_one(p, messages, on_delta, timeout, ft))
