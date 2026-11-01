"""The gauntlet sandbox (U6, KTD12, R15-R17).

Three Omarchy default apps run as the driver's own child processes, each
with a throwaway HOME under the gauntlet directory and a scrubbed
environment (no API keys, no D-Bus session address, nothing of the
owner's home): a browser with a throwaway profile, a file manager on a
temporary directory and a terminal running the restricted shell
(`rsh`, beside this file). The driver finds each app's window by the
process it spawned (a new compositor client whose pid is in that
process's tree), moves it to a dedicated workspace and hands the window
addresses to the daemon, which allows typing into those and nothing else.

Everything that touches the system is injected (spawn, the compositor's
client list, window moves, kill, clock), so tests use fakes. The default
`move` Lua call and the per-app command lines are checked live in U8.
"""
import json
import os
import pathlib
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
RSH = HERE / "rsh"
# two dedicated workspaces for window-control cases
SANDBOX_WS = (91, 92)
# what a sandbox app may inherit: the display, never a secret
ENV_KEEP = ("PATH", "LANG", "LC_ALL", "TERM", "XDG_RUNTIME_DIR",
            "WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE")
_SECRET = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|"
                     r"AUTH|SESSION_BUS)", re.I)
BROWSERS = ("chromium", "google-chrome-stable", "brave", "firefox")
FILE_MANAGERS = ("nautilus", "thunar", "pcmanfm", "dolphin")
# terminal -> the flag that introduces the command to run
TERMINALS = {"alacritty": ["-e"], "ghostty": ["-e"], "kitty": [],
             "foot": [], "xterm": ["-e"]}
APPS = ("browser", "files", "terminal")


class SandboxError(RuntimeError):
    pass


def scrubbed_env(home, base=None) -> dict:
    """The environment a sandbox app gets: the display variables, a HOME
    and XDG dirs under `home`, and nothing else. Never an API key and
    never the session bus (a file manager would otherwise hand its
    window to the owner's already-running instance)."""
    base = os.environ if base is None else base
    home = pathlib.Path(home)
    env = {k: base[k] for k in ENV_KEEP if k in base and not _SECRET.search(k)}
    # without an address, libdbus falls back to $XDG_RUNTIME_DIR/bus,
    # the owner's own session; point it at nothing
    env.update({"DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent",
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_DATA_HOME": str(home / ".local" / "share"),
                "XDG_CACHE_HOME": str(home / ".cache"),
                "XDG_STATE_HOME": str(home / ".local" / "state")})
    return env


def free_port() -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def descendants(pid: int, proc="/proc") -> set:
    """`pid` and every process below it, read from /proc."""
    kids: dict = {}
    try:
        names = os.listdir(proc)
    except OSError:
        return {pid}
    for n in names:
        if not n.isdigit():
            continue
        try:
            stat = pathlib.Path(proc, n, "stat").read_text()
            ppid = int(stat.rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        kids.setdefault(ppid, []).append(int(n))
    out, todo = set(), [pid]
    while todo:
        p = todo.pop()
        if p not in out:
            out.add(p)
            todo.extend(kids.get(p, ()))
    return out


def hypr_clients() -> list:
    from wisp import hypr
    try:
        c = hypr.query("clients")
    except hypr.HyprError:
        return []
    return c if isinstance(c, list) else []


def hypr_move(address: str, workspace: int) -> None:
    """Move a window to a workspace without following it."""
    from wisp import hypr
    hypr.eval_lua("hl.dispatch(hl.dsp.window.move({workspace = %d, "
                  "window = %s}))" % (int(workspace),
                                      hypr.lua_str("address:" + address)))


def hypr_focused() -> str:
    from wisp import hypr
    w = hypr.query("activewindow")
    return str(w.get("address") or "") if isinstance(w, dict) else ""


class Window:
    def __init__(self, app, address, pid, proc, port=None):
        self.app, self.address, self.pid = app, address, pid
        self.proc, self.port = proc, port
        self.cls = ""                   # the window class, for skill matching
        self.start_geometry: dict = {}

    def __repr__(self):
        return f"Window({self.app}, {self.address})"


class Sandbox:
    """One gauntlet attempt's apps. `prepare` wipes the workspace and the
    throwaway homes, `start` opens an app, `close` ends every process
    this sandbox spawned (and only those)."""

    def __init__(self, root, *, spawn=subprocess.Popen, clients=hypr_clients,
                 move=hypr_move, focused=hypr_focused, which=shutil.which,
                 killpg=os.killpg, sleep=time.sleep, clock=time.monotonic,
                 base_env=None, port=free_port, tree=descendants,
                 fetch=None, window_timeout=15.0):
        self.root = pathlib.Path(root)
        self.workspace = self.root / "workspace"
        self.spawn, self.clients, self.move = spawn, clients, move
        self.focused, self.which, self.killpg = focused, which, killpg
        self.sleep, self.clock = sleep, clock
        self.base_env = base_env
        self.port, self.tree = port, tree
        self.fetch = fetch or _fetch_json
        self.window_timeout = window_timeout
        self.windows: dict = {}
        self._procs: list = []

    # -- setup ------------------------------------------------------------

    def home(self, app: str) -> pathlib.Path:
        return self.root / "home" / app

    def prepare(self, setup=None) -> None:
        """Fresh workspace and homes. `setup`: {files: {name: text},
        dirs: [name]} created under the workspace."""
        self.close()
        for p in (self.workspace, self.root / "home"):
            shutil.rmtree(p, ignore_errors=True)
        self.workspace.mkdir(parents=True)
        (self.root / "rsh.log").write_text("")
        setup = setup or {}
        for d in setup.get("dirs") or ():
            self.workspace_path(d).mkdir(parents=True, exist_ok=True)
        for name, text in (setup.get("files") or {}).items():
            f = self.workspace_path(name)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(str(text).replace("{workspace}",
                                           str(self.workspace)))

    def workspace_path(self, rel: str) -> pathlib.Path:
        """A path inside the workspace; anything that escapes it is a
        SandboxError."""
        p = (self.workspace / str(rel)).resolve()
        base = self.workspace.resolve()
        if p != base and base not in p.parents:
            raise SandboxError(f"path leaves the sandbox: {rel!r}")
        return p

    # -- apps -------------------------------------------------------------

    def command(self, app: str, setup=None, port=None) -> list:
        setup = setup or {}
        if app == "browser":
            url = str(setup.get("url") or "about:blank").replace(
                "{workspace}", str(self.workspace))
            exe = next((b for b in BROWSERS if self.which(b)), None)
            if exe is None:
                raise SandboxError("no browser found")
            prof = self.home("browser")
            if exe == "firefox":
                return [self.which(exe), "--no-remote", "--profile",
                        str(prof), url]
            return [self.which(exe), f"--user-data-dir={prof}",
                    "--no-first-run", "--no-default-browser-check",
                    "--disable-sync", f"--remote-debugging-port={port}",
                    "--new-window", url]
        if app == "files":
            exe = next((b for b in FILE_MANAGERS if self.which(b)), None)
            if exe is None:
                raise SandboxError("no file manager found")
            return [self.which(exe), *(["--new-window"] if exe == "nautilus"
                                       else []), str(self.workspace)]
        if app == "terminal":
            exe = next((t for t in TERMINALS if self.which(t)), None)
            if exe is None:
                raise SandboxError("no terminal found")
            return [self.which(exe), *TERMINALS[exe], sys.executable,
                    str(RSH)]
        raise SandboxError(f"unknown sandbox app {app!r}")

    def start(self, app: str, setup=None, workspace: int = SANDBOX_WS[0]):
        """Open `app`, find its window by the process just spawned, move
        it to the sandbox workspace and return the Window."""
        home = self.home(app)
        home.mkdir(parents=True, exist_ok=True)
        port = self.port() if app == "browser" else None
        argv = self.command(app, setup, port)
        env = scrubbed_env(home, self.base_env)
        if app == "terminal":
            env["GAUNTLET_ROOT"] = str(self.workspace)
        before = {c.get("address") for c in self.clients()}
        proc = self.spawn(argv, env=env, cwd=str(self.workspace),
                          stdin=subprocess.DEVNULL,
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, start_new_session=True)
        self._procs.append(proc)
        deadline = self.clock() + self.window_timeout
        while True:
            mine = self.tree(proc.pid)
            for c in self.clients():
                if c.get("address") not in before and c.get("pid") in mine:
                    win = Window(app, str(c["address"]), proc.pid, proc, port)
                    win.cls = str(c.get("class") or "")
                    break
            else:
                win = None
            if win:
                break
            if self.clock() >= deadline:
                self.close()
                raise SandboxError(f"no window for {app}")
            self.sleep(0.25)
        try:
            self.move(win.address, workspace)
        except Exception:
            pass            # best effort; the check reads the real state
        win.start_geometry = self.geometry(win)
        self.windows[app] = win
        return win

    def addresses(self) -> list:
        return [w.address for w in self.windows.values()]

    def close(self) -> None:
        """End every process this sandbox spawned, nothing else."""
        for p in self._procs:
            try:
                self.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                try:
                    p.terminate()
                except Exception:
                    pass
        for p in self._procs:
            try:
                p.wait(timeout=3)
            except Exception:
                try:
                    self.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except Exception:
                    pass
        self._procs, self.windows = [], {}

    # -- reading state ----------------------------------------------------

    def client(self, win: Window) -> dict:
        for c in self.clients():
            if c.get("address") == win.address:
                return c
        return {}

    def geometry(self, win: Window) -> dict:
        c = self.client(win)
        return {"at": list(c.get("at") or ()),
                "size": list(c.get("size") or ())}

    def titles(self, app=None) -> list:
        wins = [self.windows[app]] if app in self.windows else (
            [] if app else list(self.windows.values()))
        return [str(self.client(w).get("title") or "") for w in wins]

    def urls(self, win: Window) -> list:
        if not win.port:
            return []
        data = self.fetch(f"http://127.0.0.1:{win.port}/json")
        return [str(p.get("url") or "") for p in data
                if isinstance(p, dict) and p.get("type") == "page"]


def _fetch_json(url: str):
    # loopback only: the sandbox browser's own debugging port
    if not url.startswith("http://127.0.0.1:"):
        raise SandboxError("only loopback")
    with urllib.request.urlopen(url, timeout=3) as r:
        return json.loads(r.read().decode())


# -- the deterministic checks ----------------------------------------------

def evaluate(check: dict, box: Sandbox):
    """(passed, detail) for one case check, or (None, detail) when the
    case has no deterministic check and the judge decides. Never
    raises: a check that cannot be read is a failed check."""
    kind = (check or {}).get("type", "judge")
    try:
        if kind == "judge":
            return None, "judge fallback"
        if kind == "title_regex":
            titles = box.titles(check.get("app"))
            ok = any(re.search(check["pattern"], t, re.I) for t in titles)
            return ok, {"titles": titles, "pattern": check["pattern"]}
        if kind == "file_exists":
            have = box.workspace_path(check["path"]).exists()
            gone = True
            if check.get("absent"):
                gone = not box.workspace_path(check["absent"]).exists()
            return have and gone, {"path": check["path"], "exists": have,
                                   "absent_ok": gone}
        if kind == "url_host":
            win = box.windows.get(check.get("app", "browser"))
            urls = box.urls(win) if win else []
            hosts = [re.sub(r"^[a-z]+://([^/:]*).*$", r"\1", u)
                     for u in urls]
            want = check["host"].lower()
            ok = any(h.lower() == want or h.lower().endswith("." + want)
                     for h in hosts)
            return ok, {"urls": urls, "host": want}
        if kind == "rsh_log":
            log = (box.root / "rsh.log").read_text()
            rows = [ln.split("\t", 1) for ln in log.splitlines()]
            verdict = check.get("verdict", "ok")
            ok = any(v == verdict and re.search(check["pattern"], c)
                     for v, c in (r for r in rows if len(r) == 2))
            return ok, {"pattern": check["pattern"], "verdict": verdict,
                        "lines": len(rows)}
        if kind == "window_workspace":
            win = box.windows[check["app"]]
            want = SANDBOX_WS[int(check["workspace"]) - 1]
            got = (box.client(win).get("workspace") or {}).get("id")
            return got == want, {"workspace": got, "want": want}
        if kind == "geometry_changed":
            win = box.windows[check["app"]]
            key = "size" if check.get("what") == "size" else "at"
            now = box.geometry(win)[key]
            return (bool(now) and now != win.start_geometry.get(key),
                    {"before": win.start_geometry.get(key), "now": now})
        if kind == "window_focused":
            win = box.windows[check["app"]]
            return box.focused() == win.address, {"want": win.address}
    except (KeyError, OSError, ValueError, SandboxError, TypeError,
            IndexError, re.error) as e:
        return False, {"error": f"{type(e).__name__}: {e}"[:160]}
    return False, {"error": f"unknown check {kind!r}"}
