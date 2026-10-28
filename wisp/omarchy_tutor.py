"""Omarchy tutor (B16): answer "how do I ... in Omarchy" from this machine.

Nothing here is a copied manual. At turn time, and only when the question
is about Omarchy, the text is built from the user's own install: the
`omarchy` command list (its `# omarchy:` metadata, through
`omarchy commands --json`), the effective key bindings (Omarchy's defaults
with the user's `bindings.lua` applied: rebinds and `hl.unbind`), the
current theme and the installed version. With no `omarchy` CLI the tutor is
absent and the prompt is unchanged.

Read-only: the only commands run are `omarchy commands --json`,
`omarchy version` and `omarchy theme current`. A package command is never
run; the text tells the model to offer it as a card the user confirms, and
to read an AUR PKGBUILD first.
"""
import json
import re
import shutil
import subprocess

from . import config

DEFAULTS_DIR = "/usr/share/omarchy/default/hypr/bindings"
BUDGET = 2200                      # chars added to one turn
READ_ONLY = (("commands", "--json"), ("version",), ("theme", "current"))

TOPIC = re.compile(
    r"\b(omarchy|theme|themes|keybind\w*|bindings?|shortcuts?|hotkeys?|"
    r"tiling|tile|split|float\w*|workspaces?|aur|pacman|package|packages|"
    r"install\w*|uninstall\w*|waybar|hyprland|font|fonts|wallpaper|"
    r"background|menu|screenshot|screen ?record\w*)\b", re.I)

BIND = re.compile(r'o\.bind\(\s*"([^"]+)"\s*,\s*(nil|"[^"]*")\s*,(.*)\)\s*$')
UNBIND = re.compile(r'hl\.unbind\(\s*"([^"]+)"\s*\)')


def available() -> bool:
    return shutil.which("omarchy") is not None


def relevant(transcript: str) -> bool:
    return bool(TOPIC.search(transcript or ""))


def _run(args: tuple, timeout: float = 4.0) -> str:
    """Output of one read-only `omarchy` call, "" on any failure."""
    if tuple(args) not in READ_ONLY:
        raise ValueError(f"not a read-only omarchy call: {args!r}")
    try:
        r = subprocess.run(["omarchy", *args], capture_output=True,
                           text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def _lua_lines(path):
    try:
        return path.read_text(errors="replace").splitlines()
    except OSError:
        return []


def effective_bindings(defaults_dir=None, user_file=None) -> dict:
    """{key combo: {label, action, user}}: Omarchy's defaults, then the
    user's bindings.lua applied in order (a later bind replaces, an unbind
    removes)."""
    import pathlib
    d = pathlib.Path(defaults_dir or DEFAULTS_DIR)
    user = pathlib.Path(user_file or config.HOME / ".config" / "hypr"
                        / "bindings.lua")
    out: dict = {}

    def apply(lines, is_user):
        for line in lines:
            s = line.strip()
            if s.startswith("--"):
                continue
            m = UNBIND.search(s)
            if m:
                out.pop(m.group(1).upper(), None)
                continue
            m = BIND.search(s)
            if m:
                label = m.group(2).strip('"') if m.group(2) != "nil" else ""
                out[m.group(1).upper()] = {
                    "label": label, "action": m.group(3).strip(),
                    "user": is_user}

    for f in sorted(d.glob("*.lua")) if d.is_dir() else []:
        apply(_lua_lines(f), False)
    apply(_lua_lines(user), True)
    return out


def pretty(combo: str) -> str:
    """"SUPER + ALT + SPACE" -> "Super+Alt+Space"."""
    return "+".join(p.strip().title() if not p.strip().startswith("CODE:")
                    else p.strip().lower()
                    for p in combo.split("+"))


def key_for(binds: dict, *needles: str, label: str = "") -> str:
    """The key now bound to an action containing every needle (or whose
    label matches), "" when none: a rebind shows up, a dropped one too."""
    hits = []
    for combo, b in binds.items():
        hay = b["action"].lower()
        if all(n.lower() in hay for n in needles) and (
                not label or label.lower() in b["label"].lower()):
            hits.append((not b["user"], combo))
    return pretty(sorted(hits)[0][1]) if hits else ""


def habits(binds: dict) -> list:
    """The three habits a new user needs, with the keys they really have."""
    lines = []
    kb = key_for(binds, "omarchy-menu-keybindings") \
        or key_for(binds, label="Keybindings")
    menu = key_for(binds, "omarchy-menu toggle apps")
    root = key_for(binds, "omarchy-menu toggle\"") \
        or key_for(binds, label="Omarchy menu")
    if kb:
        lines.append(f"{kb} opens the list of every key binding.")
    else:
        lines.append("The key binding list is not bound here; "
                     "`omarchy menu` still opens the menu.")
    if menu:
        lines.append(f"{menu} opens the apps menu.")
    if root:
        lines.append(f"{root} opens the Omarchy menu.")
    lines.append("AUR recipes are unvetted: read the PKGBUILD before any "
                 "`omarchy pkg aur install`.")
    return lines


def _commands(query: str, limit: int = 8) -> list:
    raw = _run(("commands", "--json"))
    try:
        cmds = json.loads(raw).get("commands", [])
    except (ValueError, AttributeError):
        return []
    words = {w for w in re.findall(r"[a-z]{4,}", query.lower())}
    scored = []
    for c in cmds:
        if c.get("hidden") or not c.get("name"):
            continue
        hay = f"{c.get('group', '')} {c.get('name', '')} " \
              f"{c.get('summary', '')}".lower()
        s = sum(1 for w in words if w in hay)
        if s:
            scored.append((-s, c["route"], c))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [f"{c['route']} {c.get('args', '')}".strip()
            + f": {c.get('summary', '')}" for _, _, c in scored[:limit]]


def context_for(transcript: str, defaults_dir=None, user_file=None) -> str:
    """The tutor text for this question, or "" (no CLI, off-topic)."""
    if not available() or not relevant(transcript):
        return ""
    binds = effective_bindings(defaults_dir, user_file)
    version = _run(("version",))
    theme = _run(("theme", "current"))
    lines = ["[omarchy] Read from this machine, not from a manual."]
    if version:
        lines.append(f"Installed Omarchy {version}"
                     + (f", theme {theme}." if theme else "."))
    lines += habits(binds)
    split = key_for(binds, "togglesplit")
    flt = key_for(binds, label="floating/tiling")
    if split:
        lines.append(f"{split} toggles the window split.")
    if flt:
        lines.append(f"{flt} toggles floating and tiling.")
    own = [f"{pretty(k)} {b['label']}".strip()
           for k, b in binds.items() if b["user"] and b["label"]][:8]
    if own:
        lines.append("This user's own bindings: " + "; ".join(own) + ".")
    cmds = _commands(transcript)
    if cmds:
        lines.append("Matching commands on this install:")
        lines += [f"- {c}" for c in cmds]
    lines.append("When you point, put the menu item's visible label in the "
                 "point tag. Never run a package command: offer it as a "
                 "card the user confirms.")
    return "\n".join(lines)[:BUDGET]
