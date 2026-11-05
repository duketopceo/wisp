#!/usr/bin/env python3
"""Detect the user's effective Omarchy profile into JSON.

Reads ~/.config/hypr/*.lua and ~/.config/omarchy/ — never /usr/share/omarchy —
and emits: layout mode, effective keybinds (unbind-aware), scratchpad binds,
bar plugins, and named app-launch binds. Output feeds the omarchy-app skill
so Wisp navigates the user's real config, not stock defaults.

Usage: scripts/omarchy_profile.py [--json]  (default: human summary)
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

HYPR = Path.home() / ".config" / "hypr"
OMARCHY = Path.home() / ".config" / "omarchy"

BIND_RE = re.compile(r'o\.bind\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*(.+)')
UNBIND_RE = re.compile(r'hl\.unbind\(\s*"([^"]+)"\s*\)')
LAYOUT_RE = re.compile(r'layout\s*=\s*"(\w+)"')
SCRATCH_RE = re.compile(r'special:(\w+)')


def parse_binds() -> dict:
    """Effective bind map: o.bind adds/overrides, hl.unbind removes."""
    binds, unbound = {}, set()
    f = HYPR / "bindings.lua"
    if not f.exists():
        return {"binds": binds, "unbound": [], "error": "bindings.lua not found"}
    for line in f.read_text().splitlines():
        line = line.split("--", 1)[0].strip()
        if not line:
            continue
        if m := UNBIND_RE.search(line):
            unbound.add(m.group(1))
            binds.pop(m.group(1), None)
        elif m := BIND_RE.search(line):
            key, desc, action = m.group(1), m.group(2), m.group(3).strip()
            # keep the first bind per key (release/dup variants collapse)
            binds.setdefault(key, {"description": desc, "action": action[:200]})
    return {"binds": binds, "unbound": sorted(unbound)}


def detect_layout() -> str:
    """scrolling | dwindle | unknown — active layout mode from user config."""
    for name in ("looknfeel.lua", "hyprland.lua", "hyprland.conf"):
        f = HYPR / name
        if not f.exists():
            continue
        text = f.read_text()
        # strip comments: -- lua, # conf
        text = re.sub(r"--[^\n]*", "", text)
        text = re.sub(r"#[^\n]*", "", text)
        m = LAYOUT_RE.search(text)
        if m:
            return m.group(1)
    return "dwindle"  # hyprland default


def scratchpads() -> dict:
    """Named special workspaces + any binds that toggle them."""
    found = set()
    for f in HYPR.glob("*.lua"):
        if f.name.startswith("bindings"):
            continue
        found |= set(SCRATCH_RE.findall(f.read_text()))
    out = {}
    bd = parse_binds()["binds"]
    for sp in sorted(found):
        toggles = [k for k, v in bd.items() if sp in v.get("action", "")]
        out[sp] = {"binds": toggles}
    return out


def bar_plugins() -> list[str]:
    p = OMARCHY / "plugins"
    if not p.is_dir():
        return []
    return sorted(d.name for d in p.iterdir() if d.is_dir() or d.suffix in (".so", ".qml"))


def app_launchers() -> dict:
    """Binds that launch named apps — the 'go to my X' map."""
    out = {}
    for key, v in parse_binds()["binds"].items():
        act = v.get("action", "")
        if "launch" in act or "webapp" in act:
            out[key] = {"description": v["description"], "action": act}
    return out


def profile() -> dict:
    return {
        "layout": detect_layout(),
        "binds": parse_binds(),
        "scratchpads": scratchpads(),
        "bar_plugins": bar_plugins(),
        "app_launchers": app_launchers(),
        "omarchy_menu": (OMARCHY / "omarchy-menu.jsonc").exists(),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    p = profile()
    if a.json:
        print(json.dumps(p, indent=2))
        return 0
    print(f"layout: {p['layout']}")
    print(f"binds: {len(p['binds']['binds'])} effective, {len(p['binds']['unbound'])} unbound")
    print(f"scratchpads: {', '.join(p['scratchpads']) or 'none'}")
    print(f"bar plugins: {', '.join(p['bar_plugins']) or 'none detected'}")
    print("app launchers:")
    for k, v in sorted(p["app_launchers"].items()):
        print(f"  {k}: {v['description']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
