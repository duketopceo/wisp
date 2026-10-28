"""A deep brain through the user's own coding-agent CLI (B34 option B).
Off by default, and not live until the owner turns it on.

`[brain] default = "cli:claude"` (or `cli:codex`, or put it in `fallback`)
answers a turn by running that CLI once, non-interactively, the way the user
would in a terminal. Rules, each one tested:

  - sign-in stays in that CLI. Wisp never opens, reads or copies its
    credential files and never sees a token;
  - Wisp's own keys are scrubbed from the child's environment;
  - the CLI is the user's unmodified binary, found on PATH. No CLI, or
    `[clibrain] enabled` off, gives the existing missing-key error;
  - text only: no screenshot is handed to it;
  - one call per turn with a hard timeout. Nothing runs in a loop.

Provider terms (read 2026-10-28, see docs/COSTS.md): Claude Code allows the
user's own subscription only through Anthropic's own binary, not through
tokens a third party collects (so Wisp must never touch them); `codex exec`
is the documented non-interactive entry point and signs in through
`codex login`. Subscription limits assume ordinary individual use.
"""
import os
import shutil

from . import errors_codes

# argv to run, with the prompt on stdin (never in the process list)
CLIS = {
    "claude": ["claude", "-p"],
    "codex": ["codex", "exec", "--skip-git-repo-check", "-"],
}
TIMEOUT_S = 120


def enabled(cfg) -> bool:
    v = ((cfg or {}).get("clibrain", {}) or {}).get("enabled", "false")
    return str(v).strip().lower() == "true"


def _missing(why: str, name: str):
    return errors_codes.WispError(
        "key_missing", why, f"{name} is missing, run wispd onboard")


def prompt_of(messages: list) -> str:
    """Flatten a chat to plain text. Image parts are dropped."""
    parts = []
    for m in messages:
        c = (m or {}).get("content")
        if isinstance(c, list):
            c = "\n".join(str(p.get("text", "")) for p in c
                          if isinstance(p, dict) and p.get("type") == "text")
        parts.append(f"[{(m or {}).get('role', 'user')}]\n{c or ''}")
    return "\n\n".join(parts)


def chat(p: dict, messages: list, cfg: dict | None = None, runner=None,
         which=None) -> dict:
    """The brain call for provider `cli:<name>`."""
    from . import agents, config
    cfg = cfg if cfg is not None else config.load_config()
    on = p["enabled"] if "enabled" in p else enabled(cfg)
    name = str(p.get("model") or "").strip().lower()
    if name not in CLIS:
        raise _missing(f"unknown CLI {name!r} (use {', '.join(CLIS)})",
                       f"cli:{name}")
    if not on:
        raise _missing("[clibrain] enabled is off", f"{name} CLI")
    argv = list(CLIS[name])
    if not (which or shutil.which)(argv[0]):
        raise _missing(f"no {argv[0]} CLI on PATH", f"{name} CLI")
    env = agents.scrub_env(dict(os.environ), cfg)
    if runner is None:
        from . import cancel
        runner = cancel.run
    r = runner(argv, input=prompt_of(messages), capture_output=True,
               text=True, timeout=TIMEOUT_S, env=env)
    out = (getattr(r, "stdout", "") or "").strip()
    if getattr(r, "returncode", 1) != 0 or not out:
        raise errors_codes.WispError(
            "brain_down", f"{name} CLI exited {getattr(r, 'returncode', '?')}",
            "the coding-agent CLI did not answer")
    return {"content": out, "raw": {"content": out},
            "usage": {"in": len(prompt_of(messages)) // 4,
                      "out": len(out) // 4, "cost": 0.0}}
