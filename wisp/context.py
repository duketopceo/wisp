"""Focus context — what the user is looking at right now.

snapshot() → "[focus] app=godot title=… doing=…" injected into the act
loop (and answer route) so "this" / "fix it" resolve against the real
screen instead of a void. [act] context = full|minimal|off.
"""
import json
import threading
import time

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
    if mode == "full":
        from . import inventory as _inv
        env = _inv.summary(cfg)
        if env:
            out += "\n" + env
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


SPECULATIVE_TTL_S = 5.0


class Speculative:
    """Context gathered at key press, while the user is still talking
    (W4). Each gatherer runs on its own thread so the screenshot and the
    window map overlap each other and the recording; `take()` hands a
    result to the turn once, and only if it is younger than the TTL.
    `cancel()` (interrupt, phantom release, no audio) discards everything,
    including results that land afterwards. A gatherer that raises is a
    miss: the pipeline falls back to gathering inline."""

    def __init__(self, gatherers: dict, ttl: float = SPECULATIVE_TTL_S,
                 clock=time.monotonic):
        self._gatherers = dict(gatherers)
        self._ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._done = {n: threading.Event() for n in self._gatherers}
        self._res = {}
        self._cancelled = False

    @property
    def names(self) -> list:
        return list(self._gatherers)

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def start(self) -> "Speculative":
        for name, fn in self._gatherers.items():
            threading.Thread(target=self._run, args=(name, fn),
                             daemon=True, name=f"wisp-spec-{name}").start()
        return self

    def _run(self, name, fn) -> None:
        try:
            val = fn()
        except Exception:
            val = None
        with self._lock:
            if not self._cancelled and val is not None:
                self._res[name] = (val, self._clock())
        self._done[name].set()

    def take(self, name: str, wait: float = 0.0, consume: bool = True):
        """The gathered value, or None (missing, failed, stale, cancelled
        or still running past `wait` seconds)."""
        ev = self._done.get(name)
        if ev is None:
            return None
        if wait and not ev.is_set():
            ev.wait(wait)
        with self._lock:
            if self._cancelled:
                return None
            got = self._res.get(name)
            if got is None:
                return None
            val, at = got
            if self._clock() - at > self._ttl:
                del self._res[name]
                return None
            if consume:
                del self._res[name]
            return val

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            self._res.clear()
