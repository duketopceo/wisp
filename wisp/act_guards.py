"""Pre-dispatch guards for the act loop: file-manager keyboard routes
(U3) and the invented-path guard (U4).

A skill's `## Keyboard routes` section names the keys that cover a
file-manager intent (open a path, go up, new folder, rename). When the
task is one of those and the focused app has such a route, a vision
click is turned back once with the route spelled out, a new-folder name
is not typed until the name field is on screen, and a "done" is checked
against the window title or text first.

The path guard refuses to type a bare absolute path that is not on
disk, not in the task and not in the focused window's text or the
earlier tool results: a guessed home path. Both guards answer with a
`SKIP (...)` result so the planner re-plans instead of the run failing.
Window title and text readers are injectable for tests.
"""
import os
import re

_SECTION = "## keyboard routes"
_ALIASES = {"control": "ctrl", "return": "enter", "escape": "esc"}

# path as the whole typed argument: ~, ~/x or /x (a command that merely
# contains a path is left alone; it may create it)
_BARE_PATH = re.compile(r"^\s*(~(?:/\S*)?|/\S*)\s*$")
_TASK_PATH = re.compile(r"(?<![\w/.])(~/[^\s,;\"']+|/[A-Za-z0-9_.@+-][^\s,;\"']*"
                        r"|~(?=[\s,.;]|$))")
_NAME = re.compile(
    r"(?:called|named|name it|name)\s+[\"'`]?([\w][\w .-]*?)[\"'`]?"
    r"(?=\s+(?:in|inside|under|on|at)\b|[.,;!?]|$)", re.I)
_QUOTED = re.compile(r"[\"'`“]([^\"'`”]{1,60})[\"'`”]")


def norm_key(key: str) -> str:
    parts = [p for p in re.split(r"\s*\+\s*", str(key or "").strip()) if p]
    return "+".join(_ALIASES.get(p.lower(), p.lower()) for p in parts)


def parse_routes(text: str) -> dict:
    """intent -> {"key", "text"} from a skill's `## Keyboard routes`
    section: one `- <intent>: `<key>` ...` line per route."""
    routes, inside = {}, False
    for line in str(text or "").splitlines():
        low = line.strip().lower()
        if low.startswith("## "):
            inside = low == _SECTION
            continue
        if not inside or not line.lstrip().startswith("- "):
            continue
        label, _, rest = line.lstrip()[2:].partition(":")
        key = re.search(r"`([^`]+)`", rest)
        if label.strip() and key:
            routes[re.sub(r"\s+", "_", label.strip().lower())] = {
                "key": norm_key(key.group(1)),
                "text": f"{label.strip()}: {rest.strip()}"}
    return routes


def routes_for_window(win_class: str, skills_dir=None) -> dict:
    """The keyboard routes of the app skill matching this window class,
    {} when none matches or the skill has no routes section."""
    if not str(win_class or "").strip():
        return {}
    from . import skills
    try:
        info = skills.match_app_skill_info(win_class, skills_dir=skills_dir)
        if not info:
            return {}
        with open(info["path"], encoding="utf-8", errors="replace") as f:
            return parse_routes(f.read())
    except (OSError, KeyError, ValueError):
        return {}


def task_path(task: str) -> str:
    m = _TASK_PATH.search(str(task or ""))
    return m.group(1).rstrip(".,;") if m else ""


def intent_of(task: str) -> str:
    """Which file-manager intent the task states, "" when none."""
    t = str(task or "").lower()
    if re.search(r"\b(new|create|make|add)\b.{0,20}\b(folder|directory)\b", t):
        return "new_folder"
    if re.search(r"\brename\b", t):
        return "rename"
    if re.search(r"\b(go up|parent (folder|directory)|up (one|a) "
                 r"(level|folder|directory))\b", t):
        return "go_up"
    if task_path(t) and re.search(r"\b(open|go to|navigate|show|visit)\b", t):
        return "open_path"
    return ""


def _new_name(task: str, intent: str) -> str:
    t = str(task or "")
    if intent == "rename":
        m = re.search(r"\bto\s+[\"'`]?([\w][\w .-]*?)[\"'`]?(?=[.,;!?]|$)",
                      t, re.I)
        if m:
            return m.group(1).strip()
    m = _NAME.search(t)
    if m:
        return m.group(1).strip()
    q = _QUOTED.findall(t)
    return q[-1].strip() if q else ""


def _default_window() -> dict:
    try:
        from . import platform
        return platform.active_window() or {}
    except Exception:
        return {}


def _default_text(cfg) -> str:
    try:
        from . import window_text
        r = window_text.collect(cfg or {})
        return getattr(r, "text", "") or ""
    except Exception:
        return ""


class RunGuards:
    """One run's guard state; `pre_dispatch` is called before every tool
    dispatch and returns a SKIP line to refuse the call, else None."""

    def __init__(self, task: str, user_request: str = "", cfg=None,
                 window=None, text=None, routes=None):
        self.task = str(task or "")
        self.given = f"{self.task}\n{user_request or ''}"
        self.cfg = cfg or {}
        self._window = window or _default_window
        self._text = text or (lambda: _default_text(self.cfg))
        self._routes = routes          # injected for tests
        self.intent = intent_of(self.given)
        self.marks = {}                # intent -> route use record
        self.redirected = set()
        self.dialog_warned = False

    # -- helpers ------------------------------------------------------
    def routes(self, win: dict) -> dict:
        if self._routes is not None:
            return self._routes
        return routes_for_window(win.get("class") or win.get("app") or "")

    def _evidence(self, steps) -> str:
        done = "\n".join(str(s.get("result") or "") for s in steps or ()
                         if s.get("tool") != "screenshot")
        return f"{self._text()}\n{done}"

    # -- U4 -----------------------------------------------------------
    def invented_path(self, arg: str, steps=()) -> str | None:
        m = _BARE_PATH.match(arg or "")
        if not m:
            return None
        p = m.group(1)
        full = os.path.expanduser(p)
        if os.path.exists(full):
            return None
        for form in {p, full, p.rstrip("/"), full.rstrip("/")}:
            if form and form in self.given:
                return None
        ev = self._evidence(steps)
        if any(f and f in ev for f in (p.rstrip("/"), full.rstrip("/"))):
            return None
        return (f"SKIP (path guard: {p!r} is not on disk and is not in the "
                "task or on screen. Read the real path from the window, "
                "or ask_user. Do not guess a path.)")

    # -- U3 -----------------------------------------------------------
    def pre_dispatch(self, name: str, arg: str, steps=()) -> str | None:
        if name == "type_text":
            return (self.invented_path(arg, steps)
                    or self._dialog_ready(steps))
        if name in ("click", "move"):
            return self._click_redirect()
        if name == "key":
            self._mark_route(arg)
        return None

    def _route(self):
        win = self._window()
        routes = self.routes(win) if self.intent else {}
        return win, routes, routes.get(self.intent)

    def _click_redirect(self) -> str | None:
        # rename still needs a click to select the file first
        if self.intent in ("", "rename") or self.intent in self.redirected \
                or self.intent in self.marks:
            return None
        win, _, route = self._route()
        if route is None:
            return None
        if self.intent == "open_path" and not task_path(self.given):
            return None
        self.redirected.add(self.intent)
        return ("SKIP (keyboard route covers this: " + route["text"]
                + " Use the key tool, not a click.)")

    def _mark_route(self, arg: str) -> None:
        if not self.intent or self.intent in self.marks:
            return
        win, _, route = self._route()
        if route and norm_key(arg) == route["key"]:
            self.marks[self.intent] = {
                "title": str(win.get("title") or ""), "typed": False}

    def _dialog_ready(self, steps) -> str | None:
        mark = self.marks.get("new_folder")
        if not mark or mark["typed"]:
            return None
        title = str(self._window().get("title") or "").lower()
        blob = f"{title}\n{self._text()}".lower()
        if "folder name" in blob or "new folder" in blob:
            mark["typed"] = True
            return None
        if self.dialog_warned:
            mark["typed"] = True        # one warning, then let it through
            return None
        self.dialog_warned = True
        return ("SKIP (the new-folder name field is not on screen yet, so "
                "typed text would land in the search box. Take a screenshot "
                "to check; retry the shortcut or use the menu.)")

    def unverified_done(self, steps=()) -> str | None:
        """Why a "done" is not supported by the window, else None. Only
        a route the run actually used is checked, and only against what
        the title or window text can show."""
        win = self._window()
        title = str(win.get("title") or "")
        for intent, mark in self.marks.items():
            if intent == "go_up":
                if title and title == mark["title"]:
                    return ("the window title did not change after the "
                            "go-up shortcut")
            elif intent == "open_path":
                path = task_path(self.given)
                leaf = os.path.basename(path.rstrip("/")) if path else ""
                if path in ("~", os.path.expanduser("~")) or not leaf:
                    leaf = "home"
                if title and leaf.lower() not in title.lower() and not (
                        leaf.lower() == "home"
                        and os.path.basename(os.path.expanduser("~")).lower()
                        in title.lower()):
                    return (f"the window title {title!r} does not show "
                            f"{leaf!r} after opening the path")
            elif intent in ("new_folder", "rename"):
                new = _new_name(self.given, intent)
                if not new:
                    continue
                blob = f"{title}\n{self._text()}"
                if blob.strip() and new.lower() not in blob.lower():
                    return (f"{new!r} is not in the window title or text "
                            f"after the {intent.replace('_', ' ')} route")
        return None
