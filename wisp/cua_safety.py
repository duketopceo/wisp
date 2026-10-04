"""CUA safety layer (W9): the gate every injected pointer/keyboard call
passes through between the act loop and the pointer registry.

Policy order (first match wins), evaluated per call by `Guard.run`:

  1. cancel     turn cancelled / interrupted        -> raises Cancelled
  2. kill       `[cua] kill_switch` or the kill file -> REFUSED
  3. deny       built-in + `[cua] deny` app/title    -> REFUSED
  4. allow      `[cua] allow` set, app not on it     -> REFUSED (fail closed)
  5. rate       per-window rolling 60 s cap, then per-turn cap -> REFUSED
  6. dry run    `[cua] dry_run` -> "DRYRUN ..." (nothing is invoked)
  7. dispatch   the caller's runner, exactly once; a failed click is
                never retried here (W1 rule); cancel is re-checked after

Confirmation tiers stay in act._gate (confirm-once per (tool, app));
`effective_tier` is the only mapping: `[cua] confirm = "always"` promotes
the interactive input tools to the mutating tier.

Audit: one JSON line per call in `$XDG_STATE_HOME/wisp/cua.jsonl`. Typed
text is never written: only its length and a salted hash (per-process
salt, so repeats correlate within a run but cannot be dictionary-
reversed). Click targets that are not coordinates (names) are never
written either. Audit failures never break an action.
"""
import collections
import hashlib
import json
import os
import pathlib
import re
import threading
import time

from . import cancel, config

# input tools this layer gates. move is gated (kill/deny/dry-run) but not
# counted: it is idempotent and never changes state.
POINTER = ("click", "move", "scroll")
KEYBOARD = ("type_text", "key")
GUARDED = POINTER + KEYBOARD
COUNTED = ("click", "scroll", "type_text", "key")

WINDOW_S = 60.0
DEFAULT_MAX_PER_MIN = 30
DEFAULT_MAX_PER_TURN = 12

# substring match on the focused window class, lowercase
BUILTIN_DENY_APPS = (
    "1password", "bitwarden", "keepassxc", "keepass", "enpass", "lastpass",
    "seahorse", "gnome-keyring", "pinentry", "polkit", "policykit",
    "hyprpolkitagent", "omaseal", "kwalletmanager", "gcr-prompter")
TERMINALS = ("ghostty", "kitty", "alacritty", "foot", "wezterm", "konsole",
             "gnome-terminal", "xterm", "terminator", "tilix", "st-256color")
_NAMED_KEYS = {"enter", "return", "tab", "esc", "escape", "space", "up",
               "down", "left", "right", "home", "end", "pageup", "pagedown",
               "backspace", "delete"}
_XY = re.compile(r"^\s*(-?\d+)\s*,\s*(-?\d+)")
_VERB = re.compile(r"^[A-Za-z][A-Za-z_-]{0,15}")
_SALT = os.urandom(8)


def _truthy(v, default=False) -> bool:
    if v is None or v == "":
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _num(v, default: int) -> int:
    try:
        return max(0, int(float(v)))
    except (TypeError, ValueError):
        return default


def _csv(v) -> list:
    return [s.strip().lower() for s in str(v or "").split(",") if s.strip()]


def settings(cfg: dict | None) -> dict:
    c = (cfg or {}).get("cua", {}) or {}
    return {
        "safety": _truthy(c.get("safety"), True),
        "allow": _csv(c.get("allow")),
        "deny": _csv(c.get("deny")),
        "deny_builtin": _truthy(c.get("deny_builtin"), True),
        "per_min": _num(c.get("max_clicks_per_min"), DEFAULT_MAX_PER_MIN),
        "per_turn": _num(c.get("max_per_turn"), DEFAULT_MAX_PER_TURN),
        "dry_run": _truthy(c.get("dry_run")),
        "kill": _truthy(c.get("kill_switch")),
        "audit": _truthy(c.get("audit"), True),
        "confirm": str(c.get("confirm", "tier")).strip().lower(),
    }


def effective_tier(name: str, cfg: dict | None) -> str:
    """Confirm tier for a tool: the registry tier, except that
    `[cua] confirm = "always"` promotes interactive input tools to
    mutating (so act._gate asks once per (tool, app))."""
    from . import tools
    tier = tools.risk_of(name)
    if tier == "interactive" and name in GUARDED \
            and settings(cfg)["confirm"] == "always":
        return "mutating"
    return tier


def audit_default_path() -> pathlib.Path:
    base = os.environ.get("XDG_STATE_HOME") \
        or str(pathlib.Path.home() / ".local" / "state")
    return pathlib.Path(base) / "wisp" / "cua.jsonl"


def kill_default_path() -> pathlib.Path:
    return pathlib.Path(config.RUN_DIR) / "cua.kill"


def kill(path=None) -> None:
    """Arm the kill switch (all guarded calls refused until resume)."""
    p = pathlib.Path(path) if path else kill_default_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("")


def resume(path=None) -> None:
    p = pathlib.Path(path) if path else kill_default_path()
    p.unlink(missing_ok=True)


class Limiter:
    """Rolling-window call counter per key; clock injectable."""

    def __init__(self, clock=time.monotonic, window_s: float = WINDOW_S):
        self.clock, self.window_s = clock, window_s
        self._hits = collections.defaultdict(collections.deque)
        self._lock = threading.Lock()

    def _prune(self, key) -> collections.deque:
        q = self._hits[key]
        cutoff = self.clock() - self.window_s
        while q and q[0] <= cutoff:
            q.popleft()
        return q

    def count(self, key) -> int:
        with self._lock:
            return len(self._prune(key))

    def record(self, key) -> None:
        with self._lock:
            self._prune(key).append(self.clock())


_LIMITER = Limiter()


def _live_window(state=None) -> dict:
    try:
        from . import platform
        w = platform.active_window() or {}
    except Exception:
        w = {}
    app = (w.get("class") or w.get("app") or "").lower()
    title = w.get("title") or ""
    if not app and state is not None:
        f = getattr(state, "focus", None)
        if isinstance(f, dict):
            app = (f.get("app") or "").lower()
            title = title or f.get("title", "")
    return {"app": app, "title": title}


class Guard:
    """One per act-loop run: holds the per-turn count; the rolling
    per-window counts live in the (shared) limiter."""

    def __init__(self, cfg: dict | None, state=None, window=None,
                 interrupted=None, clock=time.monotonic, limiter=None,
                 audit_path=None, kill_path=None, turn: str | None = None):
        self.s = settings(cfg)
        self.cfg = cfg or {}
        self.pointer_mode = (self.cfg.get("pointer", {}) or {}).get(
            "mode", "guide")
        self.state = state
        self._window = window or (lambda: _live_window(state))
        self.interrupted = interrupted
        self.clock = clock
        self.limiter = limiter or _LIMITER
        self.audit_path = pathlib.Path(audit_path) if audit_path \
            else audit_default_path()
        self.kill_path = pathlib.Path(kill_path) if kill_path \
            else kill_default_path()
        self.turn = turn or _turn_id()
        self.turn_count = 0

    # -- scope ---------------------------------------------------------
    def applies(self, name: str) -> bool:
        if not self.s["safety"] or name not in GUARDED:
            return False
        if name in POINTER and self.pointer_mode != "drive":
            return False   # guide mode only moves the ghost cursor
        return True

    # -- policy --------------------------------------------------------
    def _killed(self) -> bool:
        return self.s["kill"] or self.kill_path.exists()

    def _denied(self, app: str, title: str) -> str:
        names = list(self.s["deny"])
        if self.s["deny_builtin"]:
            names += BUILTIN_DENY_APPS
        hay = app.lower()
        for n in names:
            if n and n in hay:
                return f"app {app or '?'} is denied"
        if self.s["deny_builtin"] and any(t in hay for t in TERMINALS) \
                and "sudo" in (title or "").lower():
            return "terminal running sudo is denied"
        return ""

    def check(self, name: str, app: str, title: str) -> str:
        """Refusal reason, or '' when allowed (rate counted separately
        so a refused call never consumes budget)."""
        if self._killed():
            return "cua kill switch is on"
        why = self._denied(app, title)
        if why:
            return why
        if self.s["allow"] and not any(a in app for a in self.s["allow"]
                                       if a):
            return f"app {app or '?'} is not on the cua allow list"
        if name in COUNTED:
            if self.s["per_min"] and \
                    self.limiter.count(app or "?") >= self.s["per_min"]:
                return (f"rate limit: {self.s['per_min']} input calls "
                        f"per minute in {app or 'this window'}")
            if self.s["per_turn"] and self.turn_count >= self.s["per_turn"]:
                return f"rate limit: {self.s['per_turn']} input calls per turn"
        return ""

    # -- the single entry point ----------------------------------------
    def run(self, name: str, arg: str, runner) -> str:
        if not self.applies(name):
            return runner()
        self._stopped()
        w = self._window() or {}
        app, title = (w.get("app") or "").lower(), w.get("title") or ""
        t0 = time.monotonic()
        why = self.check(name, app, title)
        if why:
            self._audit(name, arg, app, "deny", f"REFUSED ({why})", t0)
            return f"REFUSED ({why})"
        if name in COUNTED:
            self.limiter.record(app or "?")
            self.turn_count += 1
        if self.s["dry_run"]:
            msg = f"DRYRUN would {name} {_describe(name, arg)}"
            self._audit(name, arg, app, "dry_run", msg, t0)
            return msg
        try:
            result = runner()
        except cancel.Cancelled:
            self._audit(name, arg, app, "cancelled", "CANCELLED", t0)
            raise
        self._audit(name, arg, app, "allow", result, t0)
        self._stopped()   # a stop that landed mid-call ends the turn now
        return result

    def _stopped(self) -> None:
        cancel.check()
        if self.interrupted and self.interrupted():
            raise cancel.Cancelled()

    # -- audit ---------------------------------------------------------
    def _audit(self, name, arg, app, decision, result, t0) -> None:
        if not self.s["audit"]:
            return
        rec = {"ts": round(time.time(), 3), "turn": self.turn, "tool": name,
               "app": app, "decision": decision,
               "dry_run": self.s["dry_run"],
               "result": _verb(result),
               "ms": int((time.monotonic() - t0) * 1000)}
        arg = arg or ""
        m = _XY.match(arg)
        if name in ("click", "move", "scroll") and m:
            rec["x"], rec["y"] = int(m.group(1)), int(m.group(2))
        elif name == "key" and ("+" in arg or arg.lower() in _NAMED_KEYS):
            rec["key"] = arg.lower()[:32]
        elif name in KEYBOARD or (name in POINTER and arg and not m):
            rec["len"] = len(arg)
            if name in KEYBOARD:
                rec["sha"] = hashlib.sha256(
                    _SALT + arg.encode("utf-8", "replace")).hexdigest()[:12]
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.audit_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, separators=(",", ":")) + "\n")
        except OSError:
            pass


def _verb(result) -> str:
    m = _VERB.match(str(result or ""))
    return m.group(0).upper() if m else "?"


def _describe(name: str, arg: str) -> str:
    m = _XY.match(arg or "")
    if name in POINTER and m:
        return f"at {m.group(1)},{m.group(2)}"
    if name in KEYBOARD:
        return f"({len(arg or '')} chars)"
    return ""


def _turn_id() -> str:
    try:
        from . import trace
        t = trace.current()
        if t:
            return str(t)
    except Exception:
        pass
    return f"act-{int(time.time())}"
