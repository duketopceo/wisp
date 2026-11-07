"""OpenRouter region: `[brain.openrouter] region = "us" | "global"`.

One setting moves every OpenRouter call (brain, answers, sense, grounding,
fallback, recall embeddings, the eval judge) to the US endpoint. The US
endpoint serves only a subset of models, so `models_missing` compares the
configured models with `GET <base>/models` and `wispd doctor` reports the
ones the chosen region cannot serve. Agent runtimes get no OpenRouter
base URL from Wisp (their credentials are scrubbed, wisp/agents.py), so
the setting has nothing to change there.
"""
import json
import urllib.error
import urllib.request
from urllib.parse import urlparse

GLOBAL_HOST = "openrouter.ai"
US_HOST = "us.openrouter.ai"
REGIONS = ("global", "us")
DEFAULT = "global"

NOTE = ('Optional: set [brain.openrouter] region = "us" to send every '
        "OpenRouter call to the US endpoint. It serves fewer models "
        "(for example no google/gemini-*); wispd doctor lists any "
        "configured model it cannot serve.")


def region(cfg: dict | None) -> str:
    """The selected region; anything unrecognised means global."""
    raw = str(((cfg or {}).get("brain.openrouter") or {}).get("region", "")
              ).strip().lower()
    return raw if raw in REGIONS else DEFAULT


def apply(cfg: dict | None, url: str) -> str:
    """`url` with its host moved to the selected region. Only the exact
    global OpenRouter host is rewritten; other hosts (ollama, a proxy, an
    already-regional URL) pass through untouched."""
    if not url or region(cfg) != "us":
        return url
    p = urlparse(url)
    if p.hostname != GLOBAL_HOST:
        return url
    return p._replace(netloc=US_HOST + (f":{p.port}" if p.port else "")
                      ).geturl()


def base_url(cfg: dict | None) -> str:
    return apply(cfg, f"https://{GLOBAL_HOST}/api/v1")


def _spec_model(spec: str, default_name: str = "openrouter") -> str:
    """The OpenRouter model id in a `name:model` spec, "" for any other
    provider. A bare id (no provider name) is an OpenRouter model."""
    spec = (spec or "").strip()
    if not spec:
        return ""
    name, sep, model = spec.partition(":")
    if sep and "/" not in name:
        return model.strip() if name.strip() == default_name else ""
    return spec


def configured_models(cfg: dict | None) -> list[tuple[str, str]]:
    """[(setting, openrouter model id)] for every model the config sends to
    OpenRouter, in a stable order, deduplicated."""
    cfg = cfg or {}
    b, g = cfg.get("brain", {}), cfg.get("ground", {})
    a, s = cfg.get("agent", {}), cfg.get("sense", {})
    found: list[tuple[str, str]] = []
    for setting, raw in (
            ("brain.default", b.get("default")
             or "openrouter:" + str(a.get("answer_model", "")
                                    or "google/gemini-2.5-flash")),
            ("brain.fast_model", b.get("fast_model")),
            ("brain.teach_model", b.get("teach_model")),
            ("ground.vlm_brain", g.get("vlm_brain")),
            ("sense.model", s.get("model")),
            ("agent.model", a.get("model")),
            ("router.model", (cfg.get("router") or {}).get("model"))):
        m = _spec_model(str(raw or ""))
        if m:
            found.append((setting, m))
    for part in str(b.get("fallback", "") or "").split(","):
        m = _spec_model(part)
        if m:
            found.append(("brain.fallback", m))
    seen, out = set(), []
    for setting, m in found:
        if (setting, m) not in seen:
            seen.add((setting, m))
            out.append((setting, m))
    return out


def fetch_models(cfg: dict | None, key: str = "", timeout: float = 8.0,
                 opener=urllib.request.urlopen) -> set[str]:
    """Model ids served at the selected region's base URL. Raises OSError /
    ValueError on a network or parse failure (the caller reports it)."""
    req = urllib.request.Request(
        base_url(cfg) + "/models",
        headers={"Authorization": f"Bearer {key}"} if key else {})
    with opener(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    return {str(m["id"]) for m in data.get("data", []) if m.get("id")}


def models_missing(cfg: dict | None, available) -> list[tuple[str, str]]:
    """Configured OpenRouter models that `available` does not list."""
    have = set(available)
    return [(setting, m) for setting, m in configured_models(cfg)
            if m not in have]
