"""Arena eval hygiene (W32): which models the training arena may run,
and the gate that keeps hosted spend on the dedicated eval key.

Matrix policy
  - local providers (ollama, lmstudio, mlx, llama_local, uitars) are
    free and always allowed.
  - at most ONE hosted model per matrix, and only from HOSTED_PRICES:
    prices in USD per million tokens (input, output) at or under the
    ceiling (Grok 4.7 class, 1.60 / 4.80).
  - premium families (anthropic, claude, opus, sonnet, fable, o-series,
    gpt-4/5, ...) are rejected by name even if someone adds a price.
  - an unknown hosted model is rejected: it has no known price.

Orch gate
  `orch` (~/bin/orch) only exports the dedicated eval key and execs the
  command; it sets no marker. So the arena sets its own: `--via-orch`
  re-execs `orch python3 arena.py ...` with WISP_ARENA_ORCH=1 in the
  environment, and hosted specs are refused unless that marker is set.
  Local-only matrices never need orch.
"""
import os
import shutil

CEILING_IN, CEILING_OUT = 1.60, 4.80
MAX_HOSTED = 1
ORCH_MARKER = "WISP_ARENA_ORCH"

LOCAL_PROVIDERS = ("ollama", "lmstudio", "mlx", "llama_local", "uitars")

# provider:model -> (usd per Mtok in, usd per Mtok out)
HOSTED_PRICES = {
    "openrouter:x-ai/grok-4.7": (1.60, 4.80),
    "openrouter:google/gemini-2.5-flash": (0.30, 2.50),
    "openrouter:meta-llama/llama-4-maverick": (0.15, 0.60),
}

PREMIUM = ("anthropic", "claude", "opus", "sonnet", "fable", "haiku",
           "gpt-4", "gpt-5", "o1", "o3", "o4", "gemini-2.5-pro",
           "gemini-3-pro")


class PolicyError(ValueError):
    pass


def parse(spec: str) -> tuple:
    if ":" not in spec:
        raise PolicyError(f"bad model spec '{spec}', want provider:model")
    prov, model = spec.split(":", 1)
    if not prov.strip() or not model.strip():
        raise PolicyError(f"bad model spec '{spec}', want provider:model")
    return prov.strip().lower(), model.strip()


def is_local(spec: str) -> bool:
    return parse(spec)[0] in LOCAL_PROVIDERS


def classify(spec: str) -> str:
    """'local' or 'hosted'; raises PolicyError for a hosted spec the
    policy does not allow (premium, unpriced, over the ceiling)."""
    prov, model = parse(spec)
    if prov in LOCAL_PROVIDERS:
        return "local"
    low = spec.lower()
    for bad in PREMIUM:
        if bad in low:
            raise PolicyError(f"'{spec}' is a premium model, not "
                              "allowed in the arena")
    price = HOSTED_PRICES.get(f"{prov}:{model}")
    if price is None:
        raise PolicyError(f"'{spec}' has no known price, so it is not "
                          "on the arena hosted list")
    if price[0] > CEILING_IN or price[1] > CEILING_OUT:
        raise PolicyError(f"'{spec}' costs {price[0]}/{price[1]} per "
                          f"Mtok, over the {CEILING_IN}/{CEILING_OUT} "
                          "ceiling")
    return "hosted"


def validate_matrix(specs) -> list:
    """Return the hosted specs after checking the whole matrix."""
    specs = [s for s in specs if s and s.strip()]
    if not specs:
        raise PolicyError("empty model matrix")
    hosted = [s for s in specs if classify(s) == "hosted"]
    if len(set(hosted)) > MAX_HOSTED:
        raise PolicyError(f"{len(set(hosted))} hosted models in the "
                          f"matrix, at most {MAX_HOSTED} allowed")
    return hosted


def via_orch(env=None) -> bool:
    return (os.environ if env is None else env).get(ORCH_MARKER) == "1"


def gate(specs, env=None) -> list:
    """Full check: matrix policy, then refuse hosted specs unless the
    run came through orch. Returns the hosted specs."""
    hosted = validate_matrix(specs)
    if hosted and not via_orch(env):
        raise PolicyError(
            f"hosted model {hosted[0]} needs the orch wrapper so spend "
            "bills the eval key: rerun with --via-orch")
    return hosted


def orch_argv(argv, orch_path=None) -> list:
    """argv for the re-exec: orch python3 <argv...>. Raises when orch is
    not installed; there is no fallback to a bare run."""
    orch = orch_path or shutil.which("orch")
    if not orch:
        raise PolicyError("orch not found on PATH, cannot run hosted "
                          "models")
    return [orch] + list(argv)
