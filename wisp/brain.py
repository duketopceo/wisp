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
"""
import json
import urllib.request
import urllib.error

from . import config

UA = "wisp/1.0"

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


def provider(cfg: dict) -> dict:
    """Resolve `[brain] default = "name:model"` → merged provider dict
    {name, kind, base_url, key_env, model, vision, tools}. Falls back
    to the legacy agent.answer_model on the openrouter provider."""
    brain = cfg.get("brain", {})
    default = brain.get("default", "")
    if ":" in default:
        name, model = default.split(":", 1)
    elif default:
        name, model = default, cfg.get("agent", {}) \
            .get("answer_model", "meta-llama/llama-4-maverick")
    else:
        name = "openrouter"
        model = cfg.get("agent", {}) \
            .get("answer_model", "meta-llama/llama-4-maverick")
    p = dict(_BUILTINS.get(name, _BUILTINS["openai_compat"]))
    p.update({k: v for k, v in cfg.get(f"brain.{name}", {}).items()})
    p["name"], p["model"] = name, model
    return p


def supports_vision(cfg: dict) -> bool:
    return provider(cfg).get("vision", "false") == "true"


def supports_tools(cfg: dict) -> bool:
    return provider(cfg).get("tools", "false") == "true"


def _probe(p: dict) -> None:
    """Local providers get a fast reachability check so failures are
    explicit (per U6: health probe) instead of silent OpenRouter-shaped
    errors."""
    if not p["base_url"].startswith(("http://localhost",
                                     "http://127.0.0.1")):
        return
    url = ("/api/tags" if p["kind"] == "ollama" else "/models")
    try:
        with urllib.request.urlopen(p["base_url"] + url, timeout=2):
            return
    except Exception as e:
        raise RuntimeError(
            f"brain provider '{p['name']}' unreachable at "
            f"{p['base_url']} ({e})")


def _post(url: str, headers: dict, body: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"User-Agent": UA, "Content-Type": "application/json",
                 **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def chat(messages: list, cfg: dict, tools: list | None = None,
         timeout: int = 60) -> dict:
    """Provider-agnostic chat call → normalized {"content": str,
    "raw": message} for OpenAI shape, or {"content", "raw": resp} for
    ollama. Caller owns message assembly (memory/session/screens).
    `tools` = OpenAI-style schemas; included only when the provider
    declares tools support."""
    p = provider(cfg)
    if not p["base_url"]:
        raise RuntimeError(
            f"brain provider '{p['name']}' needs brain.{p['name']}."
            "base_url")
    _probe(p)
    if p["kind"] == "ollama":
        # native /api/chat — images ride on the user message
        msgs = []
        for m in messages:
            m = dict(m)
            if isinstance(m.get("content"), list):
                text = "".join(c.get("text", "")
                               for c in m["content"]
                               if c.get("type") == "text")
                imgs = [c["image_url"]["url"].split(",", 1)[-1]
                        for c in m["content"]
                        if c.get("type") == "image_url"]
                m["content"] = text
                if imgs:
                    m["images"] = imgs
            msgs.append(m)
        body = {"model": p["model"], "messages": msgs, "stream": False}
        if tools and supports_tools(cfg):
            body["tools"] = tools
        resp = _post(f"{p['base_url'].rstrip('/')}/api/chat", {},
                     body, timeout)
        msg = resp.get("message", {})
        return {"content": msg.get("content", ""), "raw": msg}
    key = config.load_env_key(p.get("key_env", "")) \
        if p.get("key_env") else ""
    headers = {}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if p["name"] == "openrouter":
        headers["HTTP-Referer"] = \
            "https://github.com/duketopceo/wisp"
        headers["X-Title"] = "Wisp"
    body = {"model": p["model"], "messages": messages,
            "max_tokens": 600}
    if tools and supports_tools(cfg):
        body["tools"] = tools
        body["tool_choice"] = "auto"
    resp = _post(f"{p['base_url'].rstrip('/')}/chat/completions",
                 headers, body, timeout)
    msg = (resp.get("choices") or [{}])[0].get("message", {})
    return {"content": msg.get("content", ""), "raw": msg}
