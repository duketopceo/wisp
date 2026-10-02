"""Focus context — what the user is looking at right now.

snapshot() → "[focus] app=godot title=… doing=…" injected into the act
loop (and answer route) so "this" / "fix it" resolve against the real
screen instead of a void. [act] context = full|minimal|off.
"""
import json

from . import config, platform, skills

ACTIVITY = config.DATA_DIR / "activity.jsonl"


def _last_dayflow() -> str:
    try:
        for line in reversed(
                ACTIVITY.read_text().splitlines()[-30:]):
            rec = json.loads(line)
            blocks = rec.get("dayflow") or []
            if blocks:
                return blocks[0].get("title", "")
    except (OSError, ValueError, IndexError):
        pass
    return ""


def app_skills(app: str, limit: int = 3) -> list:
    """Skills whose name/description mentions the focused app — pinned
    regardless of the transcript keyword score."""
    app = (app or "").lower()
    if not app:
        return []
    return [s["name"] for s in skills.index()
            if app in (s["name"] + " " + s["description"]).lower()
            ][:limit]


def focused_app() -> str:
    win = platform.active_window() or {}
    return (win.get("class") or win.get("app") or "").lower()


def windows_map() -> str:
    """'ws1:BrowserOS — Personal · ws4:Godot' — every open window per
    workspace, so 'the browser' resolves by title when several are up
    and 'what's on workspace N' is answerable without a tool call."""
    try:
        from . import tools as _tools
        clients = _tools.desktop.clients()
    except Exception:
        return ""
    if not clients:
        return ""
    per_ws = {}
    for c in clients:
        w = c.get("workspace") or {}
        wsid = w.get("id", 0)
        ws = str(wsid) if wsid and wsid > 0 else \
            (w.get("name") or "scratch")
        cls = c.get("class") or c.get("initialClass") or "?"
        title = (c.get("title") or "")[:40]
        per_ws.setdefault(ws, []).append(f"{cls}:{title}" if title
                                        else cls)
    return "[windows] " + " · ".join(
        f"ws{ws}={'+'.join(v)}" for ws, v in sorted(per_ws.items()))


def snapshot(cfg: dict) -> str:
    mode = cfg.get("act", {}).get("context", "full")
    if mode == "off":
        return ""
    win = platform.active_window() or {}
    app = win.get("class") or win.get("app") or ""
    title = win.get("title") or ""
    parts = []
    if app:
        parts.append(f"app={app}")
    if title and mode == "full":
        parts.append(f"title={title[:80]!r}")
    if mode == "full":
        doing = _last_dayflow()
        if doing:
            parts.append(f"doing={doing!r}")
        matched = app_skills(app)
        if matched:
            parts.append(f"skills={','.join(matched)}")
    out = ""
    if parts:
        out = "[focus] " + " ".join(parts)
    wins = windows_map() if mode == "full" else ""
    if wins:
        out = (out + "\n" + wins).strip() or wins
    pm = cfg.get("agent", {}).get("password_manager", "")
    if pm == "1password":
        out += ("\n[prefs] password_manager=1password — a 1Password "
                "unlock/passkey prompt may appear mid-task; you may "
                "interact with it (click Unlock / the passkey prompt) "
                "but never type or guess a password — if it needs the "
                "master password, ASK_USER.")
    elif pm:
        out += (f"\n[prefs] password_manager={pm} — do NOT interact "
                "with password-manager prompts; ASK_USER instead.")
    return out
