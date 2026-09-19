#!/usr/bin/env python3
"""Build dim-agent's local Jev harness from dayflow activity data.

Mines ~/.local/share/dayflow/dayflow.db for the apps and projects the user
actually uses, resolves each to a launch command (PATH binary, ~/.local/bin
shim, or omarchy-launch-webapp for web apps), and writes

    ~/.config/dim-agent/harness.json

Local-only personalization — never committed to the repo. Re-run anytime
(`dimd harness` calls this too). dimd merges it over its built-in defaults.
"""
import json
import re
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
DAYFLOW_DB = HOME / ".local" / "share" / "dayflow" / "dayflow.db"
OUT = HOME / ".config" / "dim-agent" / "harness.json"
BINDINGS = HOME / ".config" / "hypr" / "bindings.lua"

# Canonical app name -> launch command. Web apps ride omarchy-launch-webapp.
WEB = "omarchy-launch-webapp"
KNOWN = {
    "terminal":  ("ghostty", "terminal, shell, command line, console"),
    "browser":   ("chromium", "web browser or a website"),
    "browser_new_tab": ("chromium", "a new browser tab"),
    "firefox":   ("firefox", "Firefox specifically"),
    "editor":    ("cursor", "code editor (Cursor/VS Code)"),
    "neovim":    ("ghostty -e nvim", "neovim / vim in the terminal"),
    "files":     ("nautilus", "file manager"),
    "spotify":   ("fastpotify", "music player / spotify"),
    "slack":     (f"{WEB} https://app.slack.com/client", "slack chat / work messages"),
    "discord":   (f"{WEB} https://discord.com/app", "discord chat"),
    "gmail":     (f"{WEB} https://mail.google.com", "gmail / email"),
    "google_meet": (f"{WEB} https://meet.google.com", "google meet video call"),
    "perplexity": (f"{WEB} https://perplexity.ai/", "perplexity search/AI"),
    "linear":    (f"{WEB} https://linear.app", "linear issue tracker"),
    "1password": ("1password", "password manager"),
    "obsidian":  ("obsidian", "obsidian notes"),
    "rowboat":   ("rowboat-toggle", "Rowboat AI coworker"),
    "blip":      ("blip", "blip iMessage bridge"),
    "hermes":    ("hermes", "Hermes agent"),
    "herdr":     ("herdr", "Herdr app"),
    "agentzero": ("a0", "Agent Zero / a0"),
    "opencode":  ("opencode", "opencode agent"),
    "claude":    ("claude", "Claude Code CLI"),
    "devin":     ("devin", "Devin agent CLI"),
    "codex":     ("codex", "Codex CLI"),
    "cursor_agent": ("cursor-agent", "cursor agent CLI"),
    "retroarch": ("retroarch", "retroarch games/emulator"),
    "btop":      ("ghostty -e btop", "btop system monitor"),
    "seahorse":  ("seahorse", "seahorse key/password manager"),
    "solaar":    ("solaar", "solaar logitech device manager"),
    "browseros": ("browseros", "BrowserOS agentic browser"),
    "fincept":   ("fincept-terminal", "fincept terminal finance"),
    "omwrite":   ("omwrite", "omwrite writing app"),
    "gemini":    ("gemini-toggle", "Gemini desktop overlay"),
    "dayflow":   ("dayflow", "dayflow activity journal UI"),
    "settings":  ("gnome-control-center", "system settings"),
    "activity":  ("activity-monitor", "activity monitor"),
}

# dayflow activity app names -> canonical names above.
ALIASES = {
    "terminal": "terminal", "ghostty": "terminal", "com.mitchellh.ghostty": "terminal",
    "org.omarchy.terminal": "terminal",
    "chromium": "browser", "chromium-browser": "browser", "chrome": "browser",
    "chrome-x.com__-Default": "browser", "browser": "browser",
    "firefox": "firefox",
    "cursor": "editor", "code": "editor", "vscode": "editor",
    "visual studio code": "editor", "neovim": "neovim",
    "spotify": "spotify", "fastpotify": "spotify",
    "slack": "slack", "discord": "discord", "gmail": "gmail",
    "google meet": "google_meet", "perplexity": "perplexity", "linear": "linear",
    "1password": "1password", "com.onepassword.OnePassword": "1password",
    "obsidian": "obsidian",
    "rowboat": "rowboat", "Rowboat": "rowboat", "blip": "blip",
    "hermes": "hermes", "hermes agent": "hermes", "herdr": "herdr",
    "org.omarchy.herdr": "herdr",
    "agent zero": "agentzero", "agent-zero": "agentzero", "agentzero": "agentzero",
    "a0-launcher": "agentzero", "org.omarchy.agent": "agentzero",
    "opencode": "opencode", "org.omarchy.opencode": "opencode",
    "claude": "claude", "org.omarchy.claude": "claude", "devin": "devin",
    "retroarch": "retroarch", "com.libretro.RetroArch": "retroarch",
    "emulator": "retroarch",
    "btop": "btop", "seahorse": "seahorse", "solaar": "solaar",
    "browseros": "browseros", "fincept terminal": "fincept",
    "omwrite": "omwrite", "dayflow": "dayflow",
    "omaseal": "system", "system": "settings",
    "Hermes": "hermes", "vanila": "browser", "a0": "agentzero",
}


def mine_apps(db: sqlite3.Connection) -> Counter:
    counts = Counter()
    for (acts,) in db.execute("SELECT activities FROM blocks WHERE activities != ''"):
        try:
            for a in json.loads(acts):
                name = ALIASES.get(a.get("app", "").strip())
                if name:
                    counts[name] += 1
        except Exception:
            continue
    return counts


def mine_projects(db: sqlite3.Connection) -> list:
    words = Counter()
    stop = set("""the and you for with your were this that from into using used
    after before also while then when have been over some work working testing
    debugging developing configuring managing reviewing browsing running
    checking creating searching related issues project several various update
    updates updated activity status features tools repo repos panel dashboard
    linux deployment personal homes roofs locked idle agents agent system
    projects troubleshooting auditing deploying discovery""".split())
    for (t,) in db.execute("SELECT title FROM blocks"):
        for w in re.findall(r"[A-Za-z][A-Za-z0-9_.-]{2,}", t):
            w = w.lower()
            if w not in stop:
                words[w] += 1
    return [w for w, c in words.most_common(60) if c >= 2][:25]


def binding_launch(name_pat: str):
    """Pull a launch command from bindings.lua for a matching description."""
    if not BINDINGS.exists():
        return None
    m = re.search(r'o\.bind\([^,]+,\s*"([^"]*%s[^"]*)"\s*,\s*\{\s*launch\s*=\s*"([^"]+)"' % name_pat,
                  BINDINGS.read_text(), re.I)
    return m.group(2) if m else None


def first_binary(cmd: str) -> str:
    return cmd.split()[0]


def resolvable(cmd: str) -> bool:
    b = first_binary(cmd)
    return shutil.which(b) is not None or (HOME / ".local" / "bin" / b).exists()


def main() -> int:
    apps = {}
    counts = Counter()
    if DAYFLOW_DB.exists():
        db = sqlite3.connect(f"file:{DAYFLOW_DB}?mode=ro", uri=True)
        counts = mine_apps(db)
        projects = mine_projects(db)
    else:
        projects = []
        print("warning: no dayflow db; emitting defaults only", file=sys.stderr)

    for name, (cmd, cues) in KNOWN.items():
        if not resolvable(cmd):
            continue
        entry = {"launch": cmd, "cues": cues}
        if counts.get(name):
            entry["seen"] = counts[name]  # usage frequency -> Jev prior
        apps[name] = entry

    # Web-app fallbacks for dayflow-seen names with no binary.
    for day_name, canon in ALIASES.items():
        if canon in apps or canon not in KNOWN or counts.get(canon, 0) == 0:
            continue
        cmd, cues = KNOWN[canon]
        if resolvable(cmd):
            apps[canon] = {"launch": cmd, "cues": cues, "seen": counts[canon]}

    harness = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "source": "dayflow.db activity mining + PATH/binary resolution",
        "context": (
            "Omarchy Linux (Hyprland) user. Most-used apps by activity: "
            + ", ".join(f"{n}({c}x)" for n, c in counts.most_common(12))
            + ". Active projects/topics: " + ", ".join(projects[:15]) + "."
        ),
        "apps": apps,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(harness, indent=2) + "\n")
    print(f"wrote {OUT}: {len(apps)} apps, {len(projects)} project terms")
    for n, e in sorted(apps.items()):
        print(f"  {n:16} seen={e.get('seen',0):3}  -> {e['launch']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
