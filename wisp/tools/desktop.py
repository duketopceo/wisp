"""Desktop tools: app launch/focus/close and Hyprland workspace ops."""
import json
import pathlib
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

_LEADING_VERB = re.compile(
    r"^(?:go\s+to|open(?:\s+up)?|check|switch\s+to|show(?:\s+me)?|visit|navigate\s+to)\s+",
    re.I,
)
_LEADING_POSSESSIVE = re.compile(r"^(?:my|the|our|a|an)\s+", re.I)
_PROFILE_QUALIFIER = re.compile(
    r"(?:\b(?:for|on|in)\s+(?:my\s+)?(?:work|personal)(?:\s+(?:profile|account|browser))?\b"
    r"|^(?:work|personal)\s+"
    r"|\s+(?:work|personal)$)",
    re.I,
)

# Natural spoken names for web services and role aliases. When the user
# says "check my email", "go to my Stripe", or "go to Linear", launch()
# resolves the alias to a web role; if a matching tab is already open in
# the browser, it switches to that tab instead of spawning a duplicate.
_SERVICE_ALIASES = {
    "email": "mail",
    "emails": "mail",
    "inbox": "mail",
    "gmail": "mail",
    "webmail": "mail",
    "stripe": "stripe",
    "stripedashboard": "stripe",
    "linear": "linear",
    "linearapp": "linear",
    "github": "github",
    "notion": "notion",
    "slack": "slack",
}


def _clean_target(raw: str) -> str:
    s = _LEADING_VERB.sub("", (raw or "").strip()).strip()
    return _LEADING_POSSESSIVE.sub("", s).strip()


def _resolve_service_role(raw: str) -> str:
    cleaned = _clean_target(raw).lower()
    stripped = _LEADING_POSSESSIVE.sub("", _PROFILE_QUALIFIER.sub(" ", cleaned).strip()).strip()
    target = stripped or cleaned
    compact = re.sub(r"[\s._-]+", "", target)
    return _SERVICE_ALIASES.get(target) or _SERVICE_ALIASES.get(compact) or target


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
    # Catalog names can start with an article or a launch verb ("The Game",
    # "Open Board"). Prefer the complete name before interpreting its words.
    raw_app = (app or "").strip()
    binname = _lookup(apps, raw_app)
    if not binname:
        raw_app = _LEADING_VERB.sub("", raw_app).strip()
        binname = _lookup(apps, raw_app)
    app = raw_app if binname else (_clean_target(app) or app)
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
    binname = binname or _lookup(apps, app)
    if not binname:
        # role words ('mail', 'files', 'editor') and service aliases
        # ('email', 'stripe', 'linear') resolve through the user's
        # configured default handler or [web] settings.
        from .. import inventory
        defaults = inventory.defaults()
        role_word = _resolve_service_role(app)
        prof_hint = requested_profile(app)
        tab_query = f"{role_word} {prof_hint}".strip() if prof_hint else role_word
        role = defaults.get(role_word)
        web_urls = config.web_settings(cfg)
        url = web_urls.get(role_word)
        if role:
            binname = _lookup(apps, role)
            # a role served by a browser is a web app: switch to an
            # already-open tab when possible, otherwise open its URL in
            # that browser — focusing the window alone never opens the inbox
            if binname and url and (role in _BROWSERS
                                    or role == defaults.get("browser")):
                down = _wm_down()
                if down:
                    return down
                switched = _try_switch_open_tab(tab_query, url=url,
                                                browser=binname)
                if switched:
                    return switched
                if not _exec_detached(f"{binname} {shlex.quote(url)}"):
                    return f"SKIP (could not open {url} in {role})"
                return f"OPENED {url} -> {role}"
            if binname:
                app = role
        elif url:
            down = _wm_down()
            if down:
                return down
            via = _web_browser(apps, cfg)
            switched = _try_switch_open_tab(tab_query, url=url,
                                            browser=via or "")
            if switched:
                return switched
            if via:
                if not _exec_detached(f"{via} {shlex.quote(url)}"):
                    return f"SKIP (could not open {url} in {via})"
                return f"OPENED {url} -> {via}"
            if shutil.which("xdg-open"):
                if not _exec_detached(f"xdg-open {shlex.quote(url)}"):
                    return f"SKIP (could not open {url} in default browser)"
                return f"OPENED {url} -> default browser"
            return f"SKIP (no browser to open {url})"
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
                if not _exec_detached(f"xdg-open {shlex.quote(url)}"):
                    return f"SKIP (could not open {url} in default browser)"
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
# Also discover profile instances on 9100 and 9223 without changing the
# existing ports' precedence.
CDP_PORTS = (9108, 9107, 9222, 9100, 9223)
CDP_TIMEOUT_S = 1.0
_PROC_ROOT = pathlib.Path("/proc")
_TAB_FILLER = frozenset({"my", "the", "a", "an", "tab", "tabs", "tablet",
                         "open", "up", "switch", "to", "go", "page",
                         "website", "site", "for", "on", "in", "profile",
                         "account"})
_PROFILE_HINTS = ("personal", "work")
# spoken word -> the word a tab's title or host actually carries
# ("my email" is a Gmail tab titled "Inbox ... gmail.com" on mail.*)
_TAB_ALIAS = {"email": "mail", "emails": "mail", "inbox": "mail"}
_BROWSER_CLASSES = frozenset({
    "chromium-browser", "chromium", "browseros", "google-chrome",
    "firefox", "brave", "brave-browser",
})


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (s or "").lower())


def _extract_profile(text: str) -> str:
    low = (text or "").lower()
    for p in _PROFILE_HINTS:
        if re.search(rf"\b{p}\b", low):
            return p
    return ""


def active_browser_profile() -> str:
    """Return 'personal' or 'work' when the focused window (or single matching
    browser client) indicates a browser profile, else ''."""
    from .. import platform
    try:
        win = platform.active_window() or {}
    except Exception:
        win = {}
    prof = _extract_profile(win.get("title", ""))
    if prof:
        return prof
    return ""


def requested_profile(query: str) -> str:
    """Explicit profile in `query` ('for work', 'on personal') wins;
    otherwise fall back to the currently focused browser profile."""
    explicit = _extract_profile(query)
    if explicit:
        return explicit
    return active_browser_profile()


def _query_words(query: str) -> list[str]:
    raw = [_TAB_ALIAS.get(w, w) for w in _words(query)
           if w not in _TAB_FILLER]
    without_prof = [w for w in raw if w not in _PROFILE_HINTS]
    return without_prof or raw


def _cdp_get(port: int, path: str) -> bytes:
    # 127.0.0.1 only — never a caller-supplied host
    url = f"http://127.0.0.1:{int(port)}{path}"
    with urllib.request.urlopen(url, timeout=CDP_TIMEOUT_S) as r:
        return r.read()


def _cdp_pages() -> tuple[int | None, list[dict]]:
    """(first_port, page targets) across responding loopback CDP ports.
    Each target carries `_cdp_port` so multi-profile browser instances on
    different ports can be activated on their own port."""
    first_port: int | None = None
    pages: list[dict] = []
    for port in CDP_PORTS:
        try:
            data = json.loads(_cdp_get(port, "/json/list"))
        except (OSError, ValueError):
            continue
        if isinstance(data, list):
            if first_port is None:
                first_port = port
            for t in data:
                if isinstance(t, dict) and t.get("type") == "page" and t.get("id"):
                    item = dict(t)
                    item["_cdp_port"] = port
                    pages.append(item)
    return first_port, pages


def _tab_score(query: list[str], tab: dict, profile: str = "") -> int:
    host = urllib.parse.urlparse(tab.get("url") or "").hostname or ""
    title = tab.get("title", "")
    have = _words(title) + _words(host)
    base = sum(1 for q in query if any(h.startswith(q) for h in have))
    if base > 0 and profile:
        tab_prof = _extract_profile(title) or _extract_profile(str(tab.get("profile", "")))
        if tab_prof != profile:
            return 0
        base += 1
    return base


def _focus_browser(title: str, profile: str = "", browser: str = "") -> None:
    """Raise the browser window (prefer the one matching `title` and `profile`)."""
    from .. import platform
    if not platform.uses_hypr() or not hypr.available():
        return
    # Browsers retitle their window a beat after /json/activate — poll
    # briefly so a second browser window (e.g. Personal vs Work) is not
    # raised by mistake.
    pick, wins = None, []
    prof = (profile or "").lower()
    classes = _BROWSER_CLASSES
    if browser:
        binary = pathlib.Path(shlex.split(browser)[0]).name.lower()
        classes = {"chromium": {"chromium", "chromium-browser"},
                   "brave": {"brave", "brave-browser"}}.get(binary, {binary})
    for _ in range(4):
        try:
            clients = hypr.query("clients")
        except Exception:
            return
        wins = [c for c in clients if isinstance(c, dict)
                and (c.get("class") or "").lower() in classes
                and (not prof or prof in (c.get("title") or "").lower())
                and c.get("address")]
        if title and prof:
            pick = next((c for c in wins
                         if title in (c.get("title") or "")
                         and prof in (c.get("title") or "").lower()), None)
        if not pick and title:
            pick = next((c for c in wins
                         if title in (c.get("title") or "")), None)
        if not pick and prof:
            pick = next((c for c in wins
                         if prof in (c.get("title") or "").lower()), None)
        if pick or len(wins) < 2:
            break
        time.sleep(0.1)
    pick = pick or (wins[0] if wins else None)
    if pick:
        platform._try([hypr.LuaCmd(hypr.focus_window(
            f"address:{pick['address']}"))])


def _cdp_owner_matches(port: int, browser: str) -> bool:
    """Prove a loopback endpoint belongs to the selected executable.

    Port conventions and /json/version product names are not ownership
    evidence. If procfs is absent/inaccessible or ownership is ambiguous,
    skip reuse and launch the configured browser command instead.
    """
    def profile_args(args: list[str]) -> dict:
        values = {}
        it = iter(args)
        for arg in it:
            key, sep, value = arg.partition("=")
            if key in ("--profile-directory", "--user-data-dir",
                       "--profile", "-profile", "-P"):
                values[key] = value if sep else next(it, "")
            elif key in ("--guest", "--incognito", "--private-window"):
                values[key] = True
        return values

    try:
        command = shlex.split(browser)
        selected = shutil.which(command[0]) if command else None
        if not selected:
            return False
        selected_exe = pathlib.Path(selected).resolve()
        inodes = set()
        for name in ("tcp", "tcp6"):
            try:
                rows = (_PROC_ROOT / "net" / name).read_text().splitlines()[1:]
            except OSError:
                continue
            for row in rows:
                fields = row.split()
                if (len(fields) > 9 and fields[3] == "0A"
                        and int(fields[1].rsplit(":", 1)[1], 16) == port):
                    inodes.add(f"socket:[{fields[9]}]")
        if len(inodes) != 1:
            return False
        owners = []
        for process in _PROC_ROOT.glob("[0-9]*"):
            try:
                if not any(str(fd.readlink()) in inodes
                           for fd in (process / "fd").iterdir()):
                    continue
                owners.append(process)
            except OSError:
                continue
        if len(owners) != 1 or (owners[0] / "exe").resolve() != selected_exe:
            return False
        actual = (owners[0] / "cmdline").read_bytes().decode().split("\0")
        wanted_profiles = profile_args(command[1:])
        actual_profiles = profile_args(actual[1:])
        for mode in ("--guest", "--incognito", "--private-window"):
            if bool(wanted_profiles.get(mode)) != bool(actual_profiles.get(mode)):
                return False
        # An extra identity selector is not neutral: Work inside a custom
        # data directory is not Work inside the configured/default store.
        # With no selectors on either side, ordinary default reuse remains
        # valid; do not guess equivalence for unrequested explicit stores.
        return actual_profiles == wanted_profiles
    except (OSError, ValueError):
        return False


def _try_switch_open_tab(query: str, *, url: str = "",
                         browser: str = "") -> str | None:
    """If an open browser tab already matches `query`, activate and focus it."""
    words = _query_words(query)
    if not words:
        return None
    if not browser:
        return None
    prof = requested_profile(query)
    port, pages = _cdp_pages()
    if port is None or not pages:
        return None
    best, top = None, 0
    owners = {}
    for t in pages:
        if url:
            expected_host = urllib.parse.urlparse(url).hostname
            if (not expected_host or
                    urllib.parse.urlparse(t.get("url") or "").hostname
                    != expected_host):
                continue
        target_port = int(t.get("_cdp_port") or port)
        if target_port not in owners:
            owners[target_port] = _cdp_owner_matches(target_port, browser)
        if not owners[target_port]:
            continue
        sc = _tab_score(words, t, profile=prof)
        if sc > top:
            best, top = t, sc
    if best is None:
        return None
    target_port = int(best.get("_cdp_port") or port)
    try:
        _cdp_get(target_port, "/json/activate/" + str(best["id"]))
    except OSError:
        return None
    title = best.get("title", "")
    _focus_browser(title, profile=prof, browser=browser)
    host = urllib.parse.urlparse(best.get("url") or "").hostname or ""
    return f"SWITCHED tab {title!r} -> {host}"


def tab(query: str) -> str:
    """Switch to an already-open browser tab by title or site."""
    words = _query_words(query)
    prof = requested_profile(query)
    port, pages = _cdp_pages()
    if port is None:
        return ("SKIP (no browser debug port on 127.0.0.1; "
                "open the tab by clicking it)")
    best, top = None, 0
    for t in pages:                       # MRU first; strict > keeps ties
        sc = _tab_score(words, t, profile=prof)
        if sc > top:
            best, top = t, sc
    if best is None:
        # no tab titles here: inactive tabs are not the model's to read
        return f"SKIP (no open tab matches {query!r})"
    target_port = int(best.get("_cdp_port") or port)
    try:
        _cdp_get(target_port, "/json/activate/" + str(best["id"]))
    except OSError as e:
        return f"SKIP (could not activate tab: {e})"
    title = best.get("title", "")
    if prof:
        _focus_browser(title, profile=prof)
    else:
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
