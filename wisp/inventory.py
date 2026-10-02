"""Local-context inventory — the setup passthrough.

scan() maps what Wisp can see and do on this machine and writes
inventory.json next to the other local data:

  apps      — learned app catalog (harness.json: name -> launch cmd)
  cli_tools — executables on PATH the agent can shell out to
              (~/.local/bin, ~/bin, /usr/local/bin + detected dev/agent
              runtimes)
  omarchy   — plugin names, SUPER bindings, version
  dayflow   — top-used apps, project terms, today's goals from
              dayflow.db
  skills    — installed skill names

summary() renders the compact [env] block injected into the act/answer
context so the agent knows the terrain — which browsers exist, what
CLIs it may call, what Omarchy surface it's on. Rebuilt on daemon start
when stale (>TTL_S) or via `wispd inventory`.
"""
import json
import os
import pathlib
import re
import sqlite3
import time
from collections import Counter

from . import config, skills

FILE = config.DATA_DIR / "inventory.json"
HARNESS = config.DATA_DIR / "harness.json"
DAYFLOW_DB = pathlib.Path.home() / ".local/share/dayflow/dayflow.db"
OMARCHY_PLUGINS = pathlib.Path.home() / ".config/omarchy/plugins"
BINDINGS = pathlib.Path.home() / ".config/hypr/bindings.lua"
TTL_S = 24 * 3600

_DEV_TOOLS = ("git gh glab docker podman kubectl k9s helm terraform "
              "ansible tailscale ssh rsync jq yq rg fd fzf bat eza "
              "node npm pnpm bun deno python3 pip uv cargo rustc go "
              "opencode codex claude devin gemini ollama lmstudio "
              "n8n dayflow omaseal herder herdr codebase-memory-mcp "
              "hyprctl wtype ydotool grim slurp pw-record").split()

_USER_BIN_DIRS = (".local/bin", "bin", ".cargo/bin", "go/bin",
                  ".bun/bin", ".npm-global/bin",
                  ".local/share/x86-binaries", ".lmstudio/bin",
                  ".local/share/mise/shims")

_PROJ_STOP = set("""the and you for with your were this that from into
using used after before also while then when have been over some work
working testing debugging developing configuring managing reviewing
browsing running checking creating searching related issues project
several various update updates updated activity status features tools
repo repos panel dashboard linux deployment personal locked idle agents
agent system projects troubleshooting auditing deploying discovery
""" .split())


def _cli_tools() -> dict:
    import shutil
    home = pathlib.Path.home()
    found = {}
    for d in _USER_BIN_DIRS:
        p = home / d
        if p.is_dir():
            for f in p.iterdir():
                if f.is_file() and os.access(f, os.X_OK) \
                        and "." not in f.name.lstrip("."):
                    found.setdefault(f.name, str(f))
    for t in _DEV_TOOLS:
        w = shutil.which(t)
        if w:
            found.setdefault(t, w)
    return dict(sorted(found.items()))


def _omarchy() -> dict:
    plugins = sorted(d.name for d in OMARCHY_PLUGINS.iterdir()
                     if d.is_dir()) if OMARCHY_PLUGINS.is_dir() else []
    binds = []
    try:
        for line in BINDINGS.read_text().splitlines():
            m = re.search(r'bind\w*\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"',
                          line)
            if m:
                binds.append({"key": m.group(1), "action":
                              m.group(2)[:60]})
    except OSError:
        pass
    return {"plugins": plugins, "bindings": binds}


_MCP_JSON = (".cursor/mcp.json", ".claude.json",
             ".config/devin/mcp_config.json",
             ".config/opencode/opencode.json")


def _mcp_servers() -> dict:
    """Configured MCP servers across agent harnesses — name →
    {url|command, via}. The act loop can't speak MCP natively yet, but
    knowing 'browseros'/'dayflow'/'omaseal' exist lets it pick the CLI
    or HTTP endpoint instead of inventing one."""
    home = pathlib.Path.home()
    out = {}
    for rel in _MCP_JSON:
        f = home / rel
        if not f.is_file():
            continue
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        servers = d.get("mcpServers") or d.get("mcp") or {}
        if not isinstance(servers, dict):
            continue
        for name, spec in servers.items():
            if not isinstance(spec, dict) or name in out:
                continue
            entry = {"via": rel}
            if spec.get("url"):
                entry["url"] = spec["url"]
            if spec.get("command"):
                entry["command"] = spec["command"]
            if spec.get("type"):
                entry["type"] = spec["type"]
            out[name] = entry
    codex = home / ".codex/config.toml"
    if codex.is_file():
        cur = None
        try:
            for line in codex.read_text().splitlines():
                m = re.match(r"\[mcp_servers\.([\w-]+)\]", line.strip())
                if m:
                    cur = m.group(1)
                    out.setdefault(cur, {"via": ".codex/config.toml"})
                elif cur and "=" in line and line.strip() \
                        .startswith(("command", "url")):
                    k, v = line.split("=", 1)
                    out[cur][k.strip()] = v.strip().strip('"')
                elif line.strip().startswith("["):
                    cur = None
        except OSError:
            pass
    return dict(sorted(out.items()))


def _dayflow() -> dict:
    if not DAYFLOW_DB.exists():
        return {}
    out = {}
    try:
        db = sqlite3.connect(f"file:{DAYFLOW_DB}?mode=ro", uri=True)
        try:
            apps = Counter()
            for (acts,) in db.execute(
                    "SELECT activities FROM blocks "
                    "WHERE activities != '' ORDER BY rowid DESC "
                    "LIMIT 400"):
                try:
                    for a in json.loads(acts):
                        n = a.get("app")
                        if n:
                            apps[n] += 1
                except Exception:
                    continue
            out["top_apps"] = [a for a, _ in apps.most_common(20)]
            words = Counter()
            for (t,) in db.execute(
                    "SELECT title FROM blocks ORDER BY rowid DESC "
                    "LIMIT 300"):
                for w in re.findall(r"[A-Za-z][\w.-]{2,}", t or ""):
                    wl = w.lower()
                    if wl not in _PROJ_STOP:
                        words[wl] += 1
            out["project_terms"] = [w for w, c in
                                    words.most_common(40) if c >= 2][:20]
            try:
                out["today_goals"] = [r[0] for r in db.execute(
                    "SELECT title FROM day_goals "
                    "ORDER BY rowid DESC LIMIT 5")]
            except sqlite3.Error:
                out["today_goals"] = []
        finally:
            db.close()
    except sqlite3.Error:
        return {}
    return out


def scan(cfg: dict | None = None) -> dict:
    """Full passthrough — write inventory.json and return it."""
    inv = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                      time.gmtime())}
    try:
        inv["apps"] = sorted(json.loads(HARNESS.read_text())
                             .get("apps", {}).keys())
    except (OSError, ValueError):
        inv["apps"] = []
    inv["cli_tools"] = _cli_tools()
    inv["mcp"] = _mcp_servers()
    inv["omarchy"] = _omarchy()
    inv["dayflow"] = _dayflow()
    inv["skills"] = [s.get("name", "") for s in skills.index()]
    try:
        FILE.write_text(json.dumps(inv, indent=1) + "\n")
    except OSError:
        pass
    return inv


def load() -> dict:
    try:
        return json.loads(FILE.read_text())
    except (OSError, ValueError):
        return {}


def fresh() -> bool:
    try:
        return time.time() - FILE.stat().st_mtime < TTL_S
    except OSError:
        return False


def summary(cfg: dict | None = None) -> str:
    """Compact [env] line for prompts — names only, capped so it stays
    cheap. Full detail lives in inventory.json."""
    inv = load() or (scan(cfg) if cfg else {})
    if not inv:
        return ""
    parts = []
    if inv.get("apps"):
        parts.append(f"apps({len(inv['apps'])})")
    cli = inv.get("cli_tools") or {}
    if cli:
        # notable dev/agent tools first, then other user bins
        notable = [t for t in _DEV_TOOLS if t in cli]
        rest = [t for t in cli if t not in _DEV_TOOLS]
        names = (notable + rest)[:14]
        parts.append("cli=" + ",".join(names)
                     + (f"+{len(cli) - len(names)}"
                        if len(cli) > len(names) else ""))
    mcp = list((inv.get("mcp") or {}).keys())
    if mcp:
        parts.append("mcp=" + ",".join(mcp[:10])
                     + (f"+{len(mcp) - 10}" if len(mcp) > 10 else ""))
    plugs = (inv.get("omarchy") or {}).get("plugins", [])
    if plugs:
        parts.append("omarchy_plugins=" + ",".join(
            p.split(".")[-1] for p in plugs[:8]))
    df = inv.get("dayflow") or {}
    if df.get("top_apps"):
        parts.append("most_used=" + ",".join(df["top_apps"][:6]))
    return "[env] " + " · ".join(parts) if parts else ""
