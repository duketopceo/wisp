"""Desktop tools: app launch/focus/close and Hyprland workspace ops."""
import json
import re
import shlex
import shutil
import time
import urllib.parse
import urllib.request

from .. import config
from .. import hypr


def _resolve_apps(cfg: dict, harness: dict | None) -> dict:
    """Learned apps (cfg/harness) win; every other installed app still
    resolves through the generic .desktop catalog so 'launch cadcraft'
    works before dayflow has ever seen it."""
    apps = dict(cfg.get("apps", {}))
    if harness:
        apps.update({n: a["launch"] for n, a in harness.get("apps", {}).items()
                     if a.get("launch")})
    from . import adapters
    for n, a in adapters.generic_catalog().items():
        if a.get("launch"):
            apps.setdefault(n, a["launch"])
    return apps


def _lookup(apps: dict, app: str) -> str:
    """Exact hit, else normalized ('cad craft'/'CADCraft' → cadcraft)."""
    hit = apps.get(app)
    if hit:
        return hit
    want = re.sub(r"[\s._-]+", "", app.lower())
    if not want:
        return ""
    norm = {re.sub(r"[\s._-]+", "", k.lower()): v for k, v in apps.items()}
    return norm.get(want, "")


def _wm_down() -> str | None:
    """Tool-failure string when window ops need Hyprland and its socket
    is not answering (checked by the startup/periodic probe, no fork)."""
    from .. import platform
    if platform.uses_hypr() and not hypr.available():
        return "ERROR tool_failed (hypr_unavailable)"
    return None


def _exec_detached(binname: str) -> bool:
    from .. import platform
    return platform._try(platform.launch_exec_cmds(binname))


def _on_path(binary: str) -> bool:
    """Is this command's first token launchable?

    Values are bare binaries, so a PATH probe is the right test."""
    return bool(shutil.which(binary)
                or (config.HOME / ".local" / "bin" / binary).exists())


def _browseros_live() -> bool:
    """BrowserOS MCP server reachable → the signed-in agent browser is
    running, so 'browser' should mean it rather than a cold chromium."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", 9200), timeout=0.5):
            return True
    except OSError:
        return False


# resolved apps that count as a browser for role web apps, besides
# whatever the 'browser' role maps to
_BROWSERS = ("browseros", "chromium", "google-chrome", "firefox", "brave")


def _web_browser(apps: dict, cfg: dict) -> str | None:
    """The binary that should open a URL: BrowserOS when it is live (the
    signed-in agent browser, same rule as launch('browser')), else the
    browser role's resolved app when it is installed, else None so the
    caller falls back to xdg-open."""
    if cfg.get("agent", {}).get("browseros_first", "true") == "true" \
            and shutil.which("browseros") and _browseros_live():
        return "browseros"
    from .. import inventory
    role = inventory.defaults().get("browser")
    binname = _lookup(apps, role) if role else None
    if binname and _on_path(binname.split()[0]):
        return binname
    return None


def launch(app: str, cfg: dict, harness: dict | None = None) -> str:
    # Resolve the app first: "unknown app" / "not installed" are about the
    # request and read the same with or without a window manager. The
    # Hyprland gate applies only once we are about to exec through it.
    apps = _resolve_apps(cfg, harness)
    # soak fix: "browser" prefers BrowserOS (live logins) when its MCP
    # server is up — opt out with [agent] browseros_first = "false"
    if app in ("browser", "browser_new_tab") \
            and cfg.get("agent", {}).get("browseros_first",
                                         "true") == "true" \
            and shutil.which("browseros") and _browseros_live():
        down = _wm_down()
        if down:
            return down
        _exec_detached("browseros")
        return "LAUNCHED browser -> browseros"
    binname = _lookup(apps, app)
    if not binname:
        # role words ('mail', 'files', 'editor') resolve through the
        # user's configured default handler — 'open mail' opens THEIR
        # mail app, not a guessed client
        from .. import inventory
        defaults = inventory.defaults()
        role_word = app.strip().lower()
        role = defaults.get(role_word)
        if role:
            binname = _lookup(apps, role)
            # a role served by a browser is a web app: open its URL in
            # that browser — focusing the window reads as success while
            # the inbox never opens
            url = config.web_settings(cfg).get(role_word)
            if binname and url and (role in _BROWSERS
                                    or role == defaults.get("browser")):
                down = _wm_down()
                if down:
                    return down
                if not _exec_detached(f"{binname} {shlex.quote(url)}"):
                    return f"SKIP (could not open {url} in {role})"
                return f"OPENED {url} -> {role}"
            if binname:
                app = role
        if not binname:
            # a URL/domain still opens via the default browser (webmail
            # and web apps the inventory can't know); bare nouns stay
            # SKIP so nothing arbitrary execs
            cand = app.strip()
            if re.match(r"^(https?://)?[\w][\w.-]*\.[a-zA-Z]{2,}(/\S*)?$",
                        cand) and shutil.which("xdg-open"):
                url = cand if cand.startswith(("http://", "https://")) \
                    else "https://" + cand
                down = _wm_down()
                if down:
                    return down
                # "go to <site>" navigates the user's own browser (a tab
                # in the running instance), not whatever xdg-open maps
                # the scheme to — that spawned a second app
                via = _web_browser(apps, cfg)
                if via:
                    if not _exec_detached(f"{via} {shlex.quote(url)}"):
                        return f"SKIP (could not open {url} in {via})"
                    return f"OPENED {url} -> {via}"
                _exec_detached(f"xdg-open {shlex.quote(url)}")
                return f"OPENED {url} -> default browser"
            return f"SKIP (unknown app {app!r})"
    binary = binname.split()[0]
    # already running -> 'open X' means focus it, not spawn a twin
    from .. import platform
    win = _find_window(app)
    if win:
        if platform._try([hypr.LuaCmd(hypr.focus_window(
                f"address:{win['address']}"))]):
            return (f"FOCUSED {app} -> {win.get('class', '')} "
                    "(already running)")
    if not _on_path(binary):
        # terminal: fall back to the desktop's configured default
        # (xdg-terminal-exec) — e.g. ghostty isn't packaged on Asahi
        if app == "terminal" and shutil.which("xdg-terminal-exec"):
            binname = binary = "xdg-terminal-exec"
        else:
            return f"SKIP ({app} -> {binary!r} not installed)"
    down = _wm_down()
    if down:
        return down
    _exec_detached(binname)
    return f"LAUNCHED {app} -> {binname}"


def _norm(s: str) -> str:
    return re.sub(r"[\s._:—–-]+", "", (s or "").lower())


def _find_window(name: str) -> dict | None:
    """Normalized scan of live clients — 'filmcraft' hits class
    ai.storyteller.filmcraft and title 'FilmCraft'. Returns the client."""
    from .. import platform
    if not platform.uses_hypr():
        return None
    want = _norm(name)
    if not want:
        return None
    try:
        clients = hypr.query("clients")
    except Exception:
        return None
    if not isinstance(clients, list):
        return None
    best = None
    for c in clients:
        keys = [c.get("class", ""), c.get("initialClass", ""),
                c.get("title", ""), c.get("initialTitle", "")]
        norms = [_norm(k) for k in keys]
        if want in norms:            # exact field match wins
            return c
        # substring ('film' hits filmcraft) — keep the first contender
        if best is None and any(want in n or n in want
                                for n in norms if n):
            best = c
    return best


def focus(classname: str) -> str:
    from .. import platform
    down = _wm_down()
    if down:
        return down
    cmds = platform.focus_cmds(classname)
    if not cmds:
        return (f"SKIP (focus unsupported — "
                f"{platform.missing_deps_hint()})")
    if platform._try(cmds):
        return f"FOCUSED {classname}"
    # class regex missed (case, vendor-prefixed stems like
    # ai.storyteller.filmcraft) — normalized scan, then focus by address
    hit = _find_window(classname)
    if hit and hit.get("address") and platform._try(
            [hypr.LuaCmd(hypr.focus_window(
                f"address:{hit['address']}"))]):
        return f"FOCUSED {classname} -> {hit.get('class', hit['address'])}"
    return f"SKIP (no window matching class {classname!r})"


# Loopback Chrome DevTools ports to try, in order: 9108 is Chromium's own,
# 9107 a shim answering the same /json routes, 9222 the conventional default.
CDP_PORTS = (9108, 9107, 9222)
CDP_TIMEOUT_S = 1.0
_TAB_FILLER = frozenset({"my", "the", "a", "an", "tab", "tabs", "tablet",
                         "open", "up", "switch", "to", "go", "page",
                         "website", "site"})
# spoken word -> the word a tab's title or host actually carries
# ("my email" is a Gmail tab titled "Inbox ... gmail.com" on mail.*)
_TAB_ALIAS = {"email": "mail", "emails": "mail", "inbox": "mail"}


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (s or "").lower())


def _query_words(query: str) -> list[str]:
    return [_TAB_ALIAS.get(w, w) for w in _words(query)
            if w not in _TAB_FILLER]


def _cdp_get(port: int, path: str) -> bytes:
    # 127.0.0.1 only — never a caller-supplied host
    url = f"http://127.0.0.1:{int(port)}{path}"
    with urllib.request.urlopen(url, timeout=CDP_TIMEOUT_S) as r:
        return r.read()


def _cdp_pages() -> tuple[int | None, list[dict]]:
    """(port, page targets) from the first loopback port that answers."""
    for port in CDP_PORTS:
        try:
            data = json.loads(_cdp_get(port, "/json/list"))
        except (OSError, ValueError):
            continue
        if isinstance(data, list):
            return port, [t for t in data if isinstance(t, dict)
                          and t.get("type") == "page" and t.get("id")]
    return None, []


def _tab_score(query: list[str], tab: dict) -> int:
    host = urllib.parse.urlparse(tab.get("url") or "").hostname or ""
    have = _words(tab.get("title", "")) + _words(host)
    return sum(1 for q in query if any(h.startswith(q) for h in have))


def _focus_browser(title: str) -> None:
    """Raise the Chromium window (prefer the one titled with the tab)."""
    from .. import platform
    if not platform.uses_hypr() or not hypr.available():
        return
    # Chromium retitles its window a beat after /json/activate — poll
    # briefly so a second browser window is not raised by mistake
    pick, wins = None, []
    for _ in range(4):
        try:
            clients = hypr.query("clients")
        except Exception:
            return
        wins = [c for c in clients if isinstance(c, dict)
                and c.get("class") == "chromium-browser"
                and c.get("address")]
        pick = next((c for c in wins
                     if title and title in (c.get("title") or "")), None)
        if pick or len(wins) < 2:
            break
        time.sleep(0.1)
    pick = pick or (wins[0] if wins else None)
    if pick:
        platform._try([hypr.LuaCmd(hypr.focus_window(
            f"address:{pick['address']}"))])


def tab(query: str) -> str:
    """Switch to an already-open browser tab by title or site."""
    words = _query_words(query)
    port, pages = _cdp_pages()
    if port is None:
        return ("SKIP (no browser debug port on 127.0.0.1; "
                "open the tab by clicking it)")
    best, top = None, 0
    for t in pages:                       # MRU first; strict > keeps ties
        sc = _tab_score(words, t)
        if sc > top:
            best, top = t, sc
    if best is None:
        # no tab titles here: inactive tabs are not the model's to read
        return f"SKIP (no open tab matches {query!r})"
    try:
        _cdp_get(port, "/json/activate/" + str(best["id"]))
    except OSError as e:
        return f"SKIP (could not activate tab: {e})"
    title = best.get("title", "")
    _focus_browser(title)
    host = urllib.parse.urlparse(best.get("url") or "").hostname or ""
    return f"SWITCHED tab {title!r} -> {host}"


def close(classname: str) -> str:
    from .. import platform
    down = _wm_down()
    if down:
        return down
    if platform._try(platform.close_cmds(classname)):
        return f"CLOSED {classname or 'active window'}"
    return f"SKIP (nothing closed for {classname!r})"


def workspace(n: str) -> str:
    from .. import platform
    # natural-language args: "workspace 4", "ws4", "go to 4" all mean 4
    m = re.search(r"\d+", str(n))
    if not m:
        return f"SKIP (workspace {n!r} has no number)"
    num = int(m.group())
    down = _wm_down()
    if down:
        return down
    cmds = platform.workspace_cmds(num)
    if not cmds:
        return (f"SKIP (workspace {num} unsupported — "
                f"{platform.missing_deps_hint()})")
    platform._try(cmds)
    return f"WORKSPACE {num}"


def clients() -> list:
    """Open windows, as Hyprland reports them. Hyprland-only: no other
    platform has an equivalent enumerator here, so return [] instead of
    raising on a host without Hyprland."""
    try:
        clients = hypr.query("clients")
    except hypr.HyprError:
        return []
    return clients if isinstance(clients, list) else []
