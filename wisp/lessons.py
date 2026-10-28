"""Saved walkthrough lessons (B12): keep a finished walkthrough and play it
back later without asking a model again.

A lesson is the walkthrough's goal and steps (spoken line, on-screen label,
the model's fallback point), one JSON file per lesson in the data dir's
`lessons/` folder. Replay re-speaks and re-points every step through the
same runner; nothing here talks to a model.
"""
import json
import os
import re
import time

from . import config

MAX_LESSONS = 200


def _dir():
    return config.DATA_DIR / "lessons"


def slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return s[:60]


def save(title: str, dump: dict, root=None) -> str | None:
    """Store `dump` (a walkthrough dump: goal + steps) as a lesson.
    Returns its slug, None when there is nothing to save. The same title
    replaces the older lesson."""
    root = root or _dir()
    steps = [{"text": s["text"], "label": s.get("label") or "",
              "point": s.get("point")}
             for s in (dump or {}).get("steps", []) if s.get("text")]
    title = (title or dump.get("goal") or "").strip()
    name = slug(title)
    if not steps or not name:
        return None
    rec = {"title": title, "goal": dump.get("goal") or title,
           "steps": steps, "saved": time.time()}
    try:
        root.mkdir(parents=True, exist_ok=True)
        tmp = root / (name + ".tmp")
        tmp.write_text(json.dumps(rec))
        os.replace(tmp, root / (name + ".json"))
        _prune(root)
    except OSError:
        return None
    return name


def _prune(root) -> None:
    files = sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime)
    for p in files[:-MAX_LESSONS]:
        try:
            p.unlink()
        except OSError:
            pass


def all_lessons(root=None) -> list:
    """Every lesson, newest first."""
    root = root or _dir()
    out = []
    try:
        files = list(root.glob("*.json"))
    except OSError:
        return []
    for p in files:
        try:
            rec = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict) and rec.get("steps"):
            out.append(rec)
    return sorted(out, key=lambda r: r.get("saved") or 0, reverse=True)


def _words(text: str) -> set:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def find(query: str = "", root=None) -> dict | None:
    """The lesson a spoken name points at: exact title, else the most word
    overlap with its title or goal, else (no query) the newest."""
    lessons = all_lessons(root)
    if not lessons:
        return None
    q = (query or "").strip()
    if not q:
        return lessons[0]
    for rec in lessons:
        if slug(rec["title"]) == slug(q):
            return rec
    want = _words(q) - {"the", "a", "an", "lesson", "walkthrough", "my"}
    best, best_n = None, 0
    for rec in lessons:
        n = len(want & (_words(rec["title"]) | _words(rec.get("goal"))))
        if n > best_n:
            best, best_n = rec, n
    return best
