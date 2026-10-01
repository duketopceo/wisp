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
    return "[focus] " + " ".join(parts) if parts else ""
