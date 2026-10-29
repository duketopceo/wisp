"""The private OpenCode home Wisp launches its ACP agents in (U4).

OpenCode reads its global config, sessions and credentials from the XDG
dirs, so pointing all four at a Wisp-owned home keeps the user's own
commands, plugins, agents and `auth.json` out of the session (KTD1,
KTD4). HOME stays the user's, so ori still finds its sign-in in ~/.ori.
Project config in the session's cwd is switched off with
OPENCODE_DISABLE_PROJECT_CONFIG; the launch spike
(docs/research/2026-10-28-acp-launch-spike.md) showed it loads otherwise.

The model is never written here or passed as `--model`: the session
picks it from `[agents] acp_models` (KTD5), so OpenCode's own default
(often a premium model) can never be used silently.
"""
import json
import os
import pathlib

from . import agent_home, agent_pins, agents, config, note


def home_dir(home=None) -> pathlib.Path:
    return pathlib.Path(home or (config.DATA_DIR / "agent-runtime" / "home"))


# Ordered, last match wins (OpenCode 2 permissions). Everything asks, so
# every action reaches Wisp's policy (agent_policy) as an ACP
# `session/request_permission`; the policy then allows, asks the user or
# refuses. Only Wisp's own read-only MCP tools skip the round trip, and
# .env reads are denied outright.
PERMISSIONS = (
    {"action": "*", "resource": "*", "effect": "ask"},
    {"action": "wisp_*", "resource": "*", "effect": "allow"},
    {"action": "read", "resource": "*.env", "effect": "deny"},
)


def build_config(cfg: dict) -> dict:
    # written once, used for days: the agent fills in the date itself
    system = agent_home.CONTRACT.format(today="<today, YYYY-MM-DD>")
    return {
        "default_agent": "wisp",
        "agents": {
            "wisp": {
                "description": "Wisp background worker",
                "mode": "primary",
                "system": system,
                "permissions": [dict(r) for r in PERMISSIONS],
            },
        },
    }


def write_config(cfg: dict, home=None) -> pathlib.Path:
    """Write `<home>/config/opencode/opencode.json` (0600). Idempotent."""
    path = home_dir(home) / "config" / "opencode" / "opencode.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    note._atomic_write_text(path, json.dumps(build_config(cfg), indent=2) + "\n")
    return path


def launch(cfg: dict, base_env: dict, home=None, runtime_root=None) -> tuple:
    """-> (argv, env) for the helper's `ori opencode acp` process."""
    h = home_dir(home)
    paths = agent_pins.runtime_paths(runtime_root)
    env = agents.scrub_env(dict(base_env), cfg)
    env.pop("OPENCODE_CONFIG_CONTENT", None)  # ori writes its own
    env.update({
        "XDG_CONFIG_HOME": str(h / "config"),
        "XDG_DATA_HOME": str(h / "data"),
        "XDG_STATE_HOME": str(h / "state"),
        "XDG_CACHE_HOME": str(h / "cache"),
        "ORI_NO_UPDATE_CHECK": "1",
        "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
        "OPENCODE_DISABLE_CLAUDE_CODE": "1",
        "OPENCODE_DISABLE_AUTOUPDATE": "1",
        # ori finds OpenCode on PATH and reads its --version at launch
        "PATH": os.pathsep.join(
            [str(paths["opencode"].parent)]
            + [p for p in str(base_env.get("PATH", "")).split(os.pathsep) if p]),
    })
    return [str(paths["ori"]), "opencode", "acp"], env
