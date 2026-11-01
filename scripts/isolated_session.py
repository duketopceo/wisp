#!/usr/bin/env python3
"""The isolated test session: a second, invisible Hyprland instance.

    python scripts/isolated_session.py start      # launch + canary
    python scripts/isolated_session.py status     # JSON, exit 1 if down
    python scripts/isolated_session.py canary     # re-run the input canary
    python scripts/isolated_session.py smoke      # the full gate (U2)
    python scripts/isolated_session.py stop       # idempotent

The gauntlet and the click probe drive THIS instance with
`--session isolated` instead of the owner's desktop, so their input,
screenshots and windows never reach the live session (R5). Design: the
plan's KTD5 (launch environment, headless outputs, fallbacks) and KTD6
(instance-scoped input: wisp/vpointer.py + wtype, never uinput).

Launch environment (KTD5): `DISPLAY` and `WAYLAND_DISPLAY` unset,
`HYPRLAND_NO_SD_VARS=1`, `HYPRLAND_NO_SD_NOTIFY=1`, `AQ_BACKENDS=headless`
(never DRM), a private `XDG_RUNTIME_DIR`, a private D-Bus via
`dbus-run-session`, and the test-only `isolated_session/hyprland.lua`
(xwayland off). It starts only from a live Wayland session (never from a
tty, which would contend for DRM master) and refuses if the instance
signature equals the live one.

Two headless outputs are created through the instance socket and shaped
like the owner's layout: 3456x2160 at scale 2 and 3440x1440 at scale 1
(R6). `start` writes an env file (signature, wayland display, runtime
dir, bus address, the live signature it must differ from) that U3's
drivers source.

Starting and stopping never touch the owner's systemd user environment,
D-Bus session or `wispd.service` (R7): nothing here calls
`systemctl --user set-environment`, `import-environment` or
`dbus-update-activation-environment`, and `smoke` proves it by
snapshotting that state before and after.

Exit codes: 0 ok, 1 a check failed (the session is stopped when `start`
fails), 2 a precondition or usage error.

Everything that touches the system goes through `Deps`, so
tests/test_isolated_session.py drives every path with fakes. The launch
flags, the `hyprctl output create headless` flow and the marker-window
probes are verified live by `smoke` (the first live action of the plan).
"""
import argparse
import json
import os
import pathlib
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

CONFIG_LUA = HERE / "isolated_session" / "hyprland.lua"
EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2
# R6: the owner's two outputs. (width, height, scale, x, y) in layout
# coordinates; the second output sits right of the first's logical width.
OUTPUTS = (
    {"width": 3456, "height": 2160, "scale": 2, "x": 0, "y": 0},
    {"width": 3440, "height": 1440, "scale": 1, "x": 1728, "y": 0},
)
REFRESH_HZ = 60
START_TIMEOUT_S = 30.0
SOAK_S = 1800
SOAK_POLL_S = 30.0
ENV_KEYS = ("HYPRLAND_INSTANCE_SIGNATURE", "WAYLAND_DISPLAY",
            "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS",
            "WISP_ISOLATED_SESSION", "WISP_ISOLATED_STATE",
            "WISP_ISOLATED_OUTPUTS", "WISP_LIVE_SIGNATURE")
# the page the canary and smoke open: a full-window button (click ->
# title "canary-hit") above an input pinned to the top strip (typing ->
# title "typed-<value>")
MARKER_HTML = (
    "<title>canary-wait</title>"
    "<body style='margin:0'>"
    "<input id=i autofocus style='position:fixed;top:0;left:0;"
    "width:100%;height:8%' oninput=\"document.title='typed-'+this.value\">"
    "<button style='position:fixed;top:8%;left:0;width:100%;height:92%' "
    "onclick=\"document.title='canary-hit'\">x</button>")
LIVE_SERVICE = "wispd.service"


class SessionError(RuntimeError):
    """A start/check failure with a message the owner can act on."""


def default_state_dir(environ=None) -> pathlib.Path:
    e = os.environ if environ is None else environ
    base = e.get("XDG_STATE_HOME") or str(pathlib.Path.home() / ".local"
                                          / "state")
    return pathlib.Path(base) / "wisp-isolated"


# -- env file -----------------------------------------------------------------

def write_env_file(path, env: dict) -> None:
    """`KEY=value` lines, shell-quoted so `set -a; . file` works."""
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={shlex.quote(str(env[k]))}"
             for k in ENV_KEYS if k in env]
    tmp = p.with_name(p.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, p)


def load_env_file(path) -> dict:
    """Parse an env file written by `write_env_file`. Raises
    SessionError when it is missing or incomplete."""
    try:
        text = pathlib.Path(path).read_text(encoding="utf-8")
    except OSError:
        raise SessionError(f"no isolated session env file at {path}; run "
                           "scripts/isolated_session.py start") from None
    env = {}
    for line in text.splitlines():
        k, sep, v = line.partition("=")
        if sep and k in ENV_KEYS:
            parts = shlex.split(v)
            env[k] = parts[0] if parts else ""
    for k in ("HYPRLAND_INSTANCE_SIGNATURE", "WAYLAND_DISPLAY",
              "XDG_RUNTIME_DIR"):
        if not env.get(k):
            raise SessionError(f"{path} is missing {k}; run "
                               "scripts/isolated_session.py start")
    return env


# -- the launch environment ---------------------------------------------------

def launch_env(environ: dict, runtime_dir) -> dict:
    """The child environment of the instance (KTD5). Nothing of the live
    compositor survives: the display, wayland socket and signature are
    dropped, the runtime dir is private, systemd notification is off and
    the backend is pinned to headless so DRM is never opened."""
    env = dict(environ)
    for k in ("DISPLAY", "WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE",
              "HYPRLAND_CMD", "DBUS_SESSION_BUS_ADDRESS", "WAYLAND_SOCKET",
              "XDG_SESSION_ID", "NOTIFY_SOCKET"):
        env.pop(k, None)
    env.update({"XDG_RUNTIME_DIR": str(runtime_dir),
                "HYPRLAND_NO_SD_VARS": "1",
                "HYPRLAND_NO_SD_NOTIFY": "1",
                "AQ_BACKENDS": "headless",
                "XDG_SESSION_TYPE": "wayland"})
    return env


def launch_argv(runtime_dir, config=CONFIG_LUA) -> list:
    """dbus-run-session gives the instance its own bus; the shim writes
    the bus address where `start` can read it back, then execs
    Hyprland."""
    addr = str(pathlib.Path(runtime_dir) / "bus.addr")
    return ["dbus-run-session", "--", "sh", "-c",
            'printf %s "$DBUS_SESSION_BUS_ADDRESS" > "$1"; shift; '
            'exec "$@"', "sh", addr,
            "Hyprland", "--config", str(config)]


def instance_env(base: dict, state: dict) -> dict:
    """The env a tool must have to talk to the instance only: the
    instance's runtime dir, display, signature and bus; no DISPLAY."""
    env = dict(base)
    env.pop("DISPLAY", None)
    env.update({"XDG_RUNTIME_DIR": state["XDG_RUNTIME_DIR"],
                "WAYLAND_DISPLAY": state["WAYLAND_DISPLAY"],
                "HYPRLAND_INSTANCE_SIGNATURE":
                    state["HYPRLAND_INSTANCE_SIGNATURE"]})
    if state.get("DBUS_SESSION_BUS_ADDRESS"):
        env["DBUS_SESSION_BUS_ADDRESS"] = state["DBUS_SESSION_BUS_ADDRESS"]
    return env


# -- system access ------------------------------------------------------------

class Deps:
    """Everything the launcher does to the system, replaceable in tests."""

    def __init__(self, environ=None, clock=time.monotonic,
                 sleep=time.sleep):
        self.environ = dict(os.environ if environ is None else environ)
        self.clock, self.sleep = clock, sleep

    # processes
    def spawn(self, argv, env, log_path):
        log = open(log_path, "ab")
        return subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)

    def run(self, argv, env=None, timeout=15, input=None):
        try:
            return subprocess.run(argv, env=env, capture_output=True,
                                  timeout=timeout, input=input)
        except (OSError, subprocess.SubprocessError) as e:
            return subprocess.CompletedProcess(argv, 127, b"",
                                               str(e).encode())

    def pid_alive(self, pid) -> bool:
        try:
            os.kill(int(pid), 0)
        except (OSError, ValueError):
            return False
        return True

    def kill_group(self, pid, sig) -> None:
        try:
            os.killpg(os.getpgid(int(pid)), sig)
        except (OSError, ValueError):
            pass

    # filesystem
    def mkdtemp(self, parent) -> str:
        d = tempfile.mkdtemp(prefix="wisp-iso-", dir=parent)
        os.chmod(d, 0o700)
        return d

    def rmtree(self, path) -> None:
        shutil.rmtree(path, ignore_errors=True)

    def listdir(self, path) -> list:
        try:
            return sorted(os.listdir(path))
        except OSError:
            return []

    def exists(self, path) -> bool:
        return os.path.exists(path)

    def read_text(self, path) -> str:
        try:
            return pathlib.Path(path).read_text(encoding="utf-8")
        except OSError:
            return ""

    # the marker window (canary / smoke): a browser on the instance
    def spawn_marker(self, env, profile_dir):
        exe = next((b for b in ("chromium", "google-chrome-stable", "brave")
                    if shutil.which(b)), None)
        if exe is None:
            raise SessionError("no chromium-family browser for the marker "
                               "window")
        argv = [exe, f"--user-data-dir={profile_dir}", "--no-first-run",
                "--no-default-browser-check", "--ozone-platform=wayland",
                "--new-window", "--app=data:text/html," + _urlquote(
                    MARKER_HTML)]
        benv = {k: v for k, v in env.items()
                if not any(s in k for s in ("KEY", "TOKEN", "SECRET"))}
        return subprocess.Popen(argv, env=benv, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                start_new_session=True)

    def image_nonblack(self, path) -> bool:
        """True when the PNG has any non-black pixel. Raises
        SessionError when no image tool is available."""
        if shutil.which("magick"):
            r = self.run(["magick", str(path), "-format",
                          "%[fx:maxima]", "info:"])
            try:
                return float(r.stdout.decode().strip()) > 0
            except ValueError:
                raise SessionError("magick could not read the "
                                   "screenshot") from None
        raise SessionError("no image tool (magick) to check the "
                           "screenshot")

    def open_sandbox_apps(self, env, state_dir) -> list:
        """Open the gauntlet sandbox's browser and file manager against
        the instance, report [(app, ok, detail)], close them."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "gauntlet_sandbox", HERE / "gauntlet" / "sandbox.py")
        sb = importlib.util.module_from_spec(spec)
        sys.modules.setdefault("gauntlet_sandbox", sb)
        spec.loader.exec_module(sb)
        saved = dict(os.environ)
        os.environ.clear()
        os.environ.update(env)
        out = []
        box = sb.Sandbox(pathlib.Path(state_dir) / "smoke-sandbox",
                         base_env=env,
                         dbus=env.get("DBUS_SESSION_BUS_ADDRESS"))
        try:
            box.prepare()
            for app in ("browser", "files"):
                try:
                    w = box.start(app)
                    out.append((app, True, f"window {w.address}"))
                except Exception as e:                  # noqa: BLE001
                    out.append((app, False, str(e)[:120]))
        finally:
            box.close()
            os.environ.clear()
            os.environ.update(saved)
        return out


def _urlquote(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(s, safe="")


# -- session state ------------------------------------------------------------

class Session:
    """start / status / stop / canary / smoke over one state directory."""

    def __init__(self, deps=None, state_dir=None, out=print):
        self.d = deps or Deps()
        self.state_dir = pathlib.Path(
            state_dir or default_state_dir(self.d.environ))
        self.out = out

    @property
    def env_file(self) -> pathlib.Path:
        return self.state_dir / "isolated.env"

    @property
    def meta_file(self) -> pathlib.Path:
        return self.state_dir / "session.json"

    # -- live reference -----------------------------------------------------
    def _meta(self) -> dict:
        try:
            return json.loads(self.d.read_text(self.meta_file) or "{}")
        except ValueError:
            return {}

    def live_signature(self) -> str:
        """The live compositor's signature: what `start` recorded, else
        this process's own (never the instance's)."""
        return self._meta().get("live_signature") or self.d.environ.get(
            "HYPRLAND_INSTANCE_SIGNATURE", "")

    def _live_env(self) -> dict:
        m = self._meta()
        env = dict(self.d.environ)
        if m.get("live_signature"):
            env["HYPRLAND_INSTANCE_SIGNATURE"] = m["live_signature"]
        if m.get("live_runtime_dir"):
            env["XDG_RUNTIME_DIR"] = m["live_runtime_dir"]
        if m.get("live_wayland"):
            env["WAYLAND_DISPLAY"] = m["live_wayland"]
        return env

    def live_hyprctl(self, *args):
        """Read-only query against the LIVE session."""
        r = self.d.run(["hyprctl", *args], env=self._live_env())
        return r

    def live_cursor(self):
        r = self.live_hyprctl("-j", "cursorpos")
        try:
            j = json.loads(r.stdout.decode())
            return int(j["x"]), int(j["y"])
        except (ValueError, KeyError, TypeError):
            raise SessionError("cannot read the live cursor position "
                               "(hyprctl cursorpos)") from None

    def live_clients(self) -> set:
        r = self.live_hyprctl("-j", "clients")
        try:
            return {c["address"] for c in json.loads(r.stdout.decode())}
        except (ValueError, KeyError, TypeError):
            raise SessionError("cannot list the live clients") from None

    # -- instance ---------------------------------------------------------------
    def state(self) -> dict:
        """The recorded instance env (SessionError when none)."""
        return load_env_file(self.env_file)

    def _ienv(self, state=None) -> dict:
        return instance_env(self.d.environ, state or self.state())

    def hyprctl(self, state, *args, timeout=15):
        return self.d.run(["hyprctl", *args], env=self._ienv(state),
                          timeout=timeout)

    def monitors(self, state) -> list:
        r = self.hyprctl(state, "-j", "monitors", "all")
        try:
            return json.loads(r.stdout.decode())
        except ValueError:
            return []

    def clients(self, state) -> list:
        r = self.hyprctl(state, "-j", "clients")
        try:
            return json.loads(r.stdout.decode())
        except ValueError:
            return []

    def running(self) -> bool:
        pid = self._meta().get("pid")
        return bool(pid) and self.d.pid_alive(pid)

    # -- start ------------------------------------------------------------------
    def start(self) -> int:
        d, env = self.d, self.d.environ
        if self.running():
            self.out("an isolated session is already running; "
                     "`stop` it first")
            return EXIT_USAGE
        parent = env.get("WAYLAND_DISPLAY", "")
        rt = env.get("XDG_RUNTIME_DIR", "")
        wsock = parent if os.path.isabs(parent) else os.path.join(rt, parent)
        if not parent or not rt or not d.exists(wsock) \
                or env.get("XDG_SESSION_TYPE") == "tty":
            self.out("no live Wayland session to start from (a tty would "
                     "contend for DRM master); refusing")
            return EXIT_USAGE
        live_sig = env.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        if not live_sig:
            self.out("no live HYPRLAND_INSTANCE_SIGNATURE; cannot prove "
                     "the instance differs from the live session")
            return EXIT_USAGE
        self.state_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.state_dir, 0o700)
        rdir = d.mkdtemp(rt)
        meta = {"runtime_dir": rdir, "live_signature": live_sig,
                "live_runtime_dir": rt, "live_wayland": parent}
        self.meta_file.write_text(json.dumps(meta))
        try:
            self._launch(meta, rdir, live_sig)
        except SessionError as e:
            self.out(f"start failed: {e}")
            self.stop()
            return EXIT_FAIL
        state = self.state()
        self.out(f"isolated session up: {state['WAYLAND_DISPLAY']} "
                 f"(instance {state['HYPRLAND_INSTANCE_SIGNATURE']}); "
                 f"env file {self.env_file}")
        return EXIT_OK

    def _launch(self, meta, rdir, live_sig) -> None:
        d = self.d
        proc = d.spawn(launch_argv(rdir), launch_env(d.environ, rdir),
                       self.state_dir / "hyprland.log")
        meta["pid"] = proc.pid
        self.meta_file.write_text(json.dumps(meta))
        sig, disp = self._wait_socket(rdir, proc)
        if sig == live_sig:
            raise SessionError("the instance signature equals the live "
                               "one; refusing to touch it")
        if not d.exists(os.path.join(rdir, disp)):
            raise SessionError("the instance has no wayland socket")
        bus = d.read_text(os.path.join(rdir, "bus.addr")).strip()
        state = {"HYPRLAND_INSTANCE_SIGNATURE": sig,
                 "WAYLAND_DISPLAY": disp, "XDG_RUNTIME_DIR": rdir,
                 "DBUS_SESSION_BUS_ADDRESS": bus,
                 "WISP_ISOLATED_SESSION": "1",
                 "WISP_ISOLATED_STATE": str(self.state_dir),
                 "WISP_LIVE_SIGNATURE": live_sig}
        self._outputs(state)
        write_env_file(self.env_file, state)
        res = self.canary()
        if not res[0]:
            raise SessionError("canary failed: " + res[1])

    def _wait_socket(self, rdir, proc) -> tuple:
        d = self.d
        end = d.clock() + START_TIMEOUT_S
        while True:
            if hasattr(proc, "poll") and proc.poll() is not None:
                raise SessionError("Hyprland exited at startup (see "
                                   f"{self.state_dir / 'hyprland.log'})")
            sigs = d.listdir(os.path.join(rdir, "hypr"))
            wls = [n for n in d.listdir(rdir)
                   if n.startswith("wayland-") and not n.endswith(".lock")]
            ready = [s for s in sigs if d.exists(
                os.path.join(rdir, "hypr", s, ".socket.sock"))]
            if ready and wls:
                return ready[0], wls[0]
            if d.clock() > end:
                raise SessionError("Hyprland did not open its sockets in "
                                   f"{START_TIMEOUT_S:.0f}s")
            d.sleep(0.25)

    def _outputs(self, state) -> None:
        """Create the two headless outputs and shape them (R6)."""
        names = []
        for spec in OUTPUTS:
            before = {m.get("name") for m in self.monitors(state)}
            r = self.hyprctl(state, "output", "create", "headless")
            if r.returncode != 0:
                raise SessionError("hyprctl output create headless failed: "
                                   + r.stderr.decode()[:120])
            new = self._new_output(state, before)
            lua = ("hl.monitor({ output = %s, mode = %s, position = %s, "
                   "scale = %d })" % (
                       _lua(new),
                       _lua(f"{spec['width']}x{spec['height']}"
                            f"@{REFRESH_HZ}"),
                       _lua(f"{spec['x']}x{spec['y']}"), spec["scale"]))
            r = self.hyprctl(state, "eval", lua)
            if r.returncode != 0 or r.stdout.decode().strip().startswith(
                    "error"):
                raise SessionError(f"could not configure {new}: "
                                   + (r.stdout + r.stderr).decode()[:120])
            names.append(new)
        state["WISP_ISOLATED_OUTPUTS"] = ",".join(names)
        got = {m["name"]: m for m in self.monitors(state)
               if m.get("name") in names}
        for name, spec in zip(names, OUTPUTS):
            m = got.get(name) or {}
            if (m.get("width"), m.get("height"), float(
                    m.get("scale", 0))) != (spec["width"], spec["height"],
                                            float(spec["scale"])):
                raise SessionError(
                    f"{name} came up as {m.get('width')}x{m.get('height')}"
                    f"@{m.get('scale')}, wanted {spec['width']}x"
                    f"{spec['height']}@{spec['scale']}")

    def _new_output(self, state, before) -> str:
        d = self.d
        end = d.clock() + 10
        while True:
            new = [m["name"] for m in self.monitors(state)
                   if m.get("name") not in before]
            if new:
                return new[0]
            if d.clock() > end:
                raise SessionError("the new headless output never "
                                   "appeared")
            d.sleep(0.25)

    # -- stop -------------------------------------------------------------------
    def stop(self) -> int:
        """Kill the process group, remove the runtime dir and the env
        file. Safe to call twice."""
        d = self.d
        m = self._meta()
        pid = m.get("pid")
        if pid and d.pid_alive(pid):
            d.kill_group(pid, signal.SIGTERM)
            end = d.clock() + 5
            while d.pid_alive(pid) and d.clock() < end:
                d.sleep(0.1)
            if d.pid_alive(pid):
                d.kill_group(pid, signal.SIGKILL)
        if m.get("runtime_dir"):
            d.rmtree(m["runtime_dir"])
        for f in (self.env_file, self.meta_file):
            try:
                f.unlink()
            except OSError:
                pass
        self.out("isolated session stopped")
        return EXIT_OK

    # -- status -----------------------------------------------------------------
    def status(self) -> int:
        up = self.running()
        info = {"running": up}
        if up:
            try:
                st = self.state()
                info.update({k: st.get(k, "") for k in (
                    "HYPRLAND_INSTANCE_SIGNATURE", "WAYLAND_DISPLAY",
                    "XDG_RUNTIME_DIR", "WISP_ISOLATED_OUTPUTS")})
                info["pid"] = self._meta().get("pid")
            except SessionError as e:
                info["error"] = str(e)
        self.out(json.dumps(info))
        return EXIT_OK if up and "error" not in info else EXIT_FAIL

    # -- the marker window ---------------------------------------------------------
    def _marker(self, state, proc_holder):
        """Open the marker page in the instance; (client dict)."""
        d = self.d
        before = {c["address"] for c in self.clients(state)}
        prof = d.mkdtemp(state["XDG_RUNTIME_DIR"])
        proc_holder["profile"] = prof
        proc_holder["proc"] = d.spawn_marker(self._ienv(state), prof)
        end = d.clock() + 20
        while True:
            for c in self.clients(state):
                if c["address"] not in before and str(
                        c.get("title", "")).startswith(
                            ("canary-", "typed-")):
                    return c
            if d.clock() > end:
                raise SessionError("the marker window never appeared in "
                                   "the instance")
            d.sleep(0.5)

    def _marker_title(self, state, address) -> str:
        for c in self.clients(state):
            if c["address"] == address:
                return str(c.get("title", ""))
        return ""

    def _close_marker(self, holder) -> None:
        p = holder.get("proc")
        if p is not None:
            try:
                self.d.kill_group(p.pid, signal.SIGTERM)
            except Exception:                           # noqa: BLE001
                pass
        if holder.get("profile"):
            self.d.rmtree(holder["profile"])

    def _wait_title(self, state, address, want, timeout=5.0) -> str:
        d = self.d
        end = d.clock() + timeout
        while True:
            t = self._marker_title(state, address)
            if t == want or d.clock() > end:
                return t
            d.sleep(0.25)

    def _click_center(self, state, client) -> None:
        from wisp import points, vpointer
        mons = [m for m in self.monitors(state) if not m.get("disabled")]
        bx, by, bw, bh = points.logical_bbox(mons)
        at, size = client["at"], client["size"]
        cx, cy = at[0] + size[0] // 2, at[1] + size[1] // 2
        vpointer.click(cx, cy, (bw, bh), origin=(bx, by),
                       env=vpointer.isolated_env(self._ienv(state)))

    # -- canary -----------------------------------------------------------------
    def canary(self) -> tuple:
        """(ok, detail). A marker window in the instance is clicked
        through the virtual-pointer client; the window must see it, the
        live cursor must not move and no new client may appear on the
        live session."""
        try:
            state = self.state()
            cur0, cl0 = self.live_cursor(), self.live_clients()
        except SessionError as e:
            return False, str(e)
        holder = {}
        try:
            client = self._marker(state, holder)
            self._click_center(state, client)
            title = self._wait_title(state, client["address"],
                                     "canary-hit")
            cur1, cl1 = self.live_cursor(), self.live_clients()
        except Exception as e:                          # noqa: BLE001
            return False, f"{type(e).__name__}: {e}"[:200]
        finally:
            self._close_marker(holder)
        if title != "canary-hit":
            return False, ("the marker window never saw the click "
                           f"(title {title!r})")
        if cur1 != cur0:
            return False, (f"the LIVE cursor moved {cur0} -> {cur1} "
                           "during the canary")
        if cl1 - cl0:
            return False, ("a new client appeared on the LIVE session "
                           f"during the canary: {sorted(cl1 - cl0)}")
        return True, "ok"

    # -- smoke ------------------------------------------------------------------
    def snapshot_live(self) -> dict:
        """Bytes of the owner's systemd user environment and the
        `wispd.service` state: R7 says start/stop leaves them alone
        (dbus-broker mirrors systemd's environment as its activation
        environment, so this covers both)."""
        e = self._live_env()
        snap = {}
        for key, argv in (
                ("systemd-env", ["systemctl", "--user", "show-environment"]),
                ("wispd", ["systemctl", "--user", "show", LIVE_SERVICE,
                           "-p", "ActiveState", "-p", "MainPID"])):
            r = self.d.run(argv, env=e)
            snap[key] = r.stdout
        return snap

    def smoke(self, soak_s=SOAK_S) -> int:
        """The gate. Prints one line per check; exit 0 only when every
        check passed. Starts the session if none is up, and stops it
        again only if it started it."""
        results = []

        def check(name, ok, detail=""):
            results.append((name, bool(ok), detail))
            self.out(f"{'PASS' if ok else 'FAIL'} {name}"
                     + (f": {detail}" if detail and not ok else ""))
            return ok

        try:
            before = self.snapshot_live()
        except SessionError as e:
            self.out(f"FAIL live-snapshot: {e}")
            return EXIT_FAIL
        started_here = False
        if not self.running():
            started_here = True
            ok = self.start() == EXIT_OK
            check("headless-start", ok,
                  "" if ok else "see the start output above; try a "
                  "fallback mode (weston-nested, then QEMU: KTD5)")
            if not ok:
                return EXIT_FAIL
        else:
            check("headless-start", True, "already running")
        try:
            state = self.state()
            self._smoke_checks(state, check, soak_s)
            after = self.snapshot_live()
            same = before == after
            check("live-environment-unchanged", same,
                  "" if same else "the systemd user environment or "
                  f"{LIVE_SERVICE} changed: "
                  + ",".join(k for k in before if before[k] != after.get(k)))
        except SessionError as e:
            check("smoke", False, str(e))
        finally:
            if started_here:
                self.stop()
        failed = [n for n, ok, _ in results if not ok]
        self.out("smoke " + ("FAILED: " + ", ".join(failed) if failed
                             else "passed"))
        return EXIT_FAIL if failed else EXIT_OK

    def _smoke_checks(self, state, check, soak_s) -> None:
        d = self.d
        names = [n for n in state.get("WISP_ISOLATED_OUTPUTS", "").split(
            ",") if n]
        mons = {m["name"]: m for m in self.monitors(state)}
        for n, spec in zip(names, OUTPUTS):
            m = mons.get(n) or {}
            got = (m.get("width"), m.get("height"),
                   float(m.get("scale", 0)))
            want = (spec["width"], spec["height"], float(spec["scale"]))
            check(f"mode:{n}", got == want, f"got {got}, want {want}")
        if len(names) != len(OUTPUTS):
            check("outputs", False, f"expected {len(OUTPUTS)} outputs, "
                  f"have {names}")
        for n in names:
            path = os.path.join(state["XDG_RUNTIME_DIR"], f"smoke-{n}.png")
            r = d.run(["grim", "-o", n, path], env=self._ienv(state),
                      timeout=30)
            if r.returncode != 0:
                check(f"grim:{n}", False, r.stderr.decode()[:100])
                continue
            try:
                check(f"grim:{n}", d.image_nonblack(path),
                      "the screenshot is all black")
            except SessionError as e:
                check(f"grim:{n}", False, str(e))
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        ok, detail = self.canary()
        check("canary", ok, "" if ok else detail)
        self._smoke_wtype(state, check)
        try:
            apps = d.open_sandbox_apps(self._ienv(state), self.state_dir)
        except Exception as e:                          # noqa: BLE001
            apps = [("apps", False, f"{type(e).__name__}: {e}"[:120])]
        for app, ok, detail in apps:
            check(f"sandbox:{app}", ok, detail)
        self._soak(state, check, soak_s)

    def _smoke_wtype(self, state, check) -> None:
        d = self.d
        holder = {}
        try:
            cl0 = self.live_clients()
            titles0 = self._live_titles()
            client = self._marker(state, holder)
            r = d.run(["wtype", "isolated"], env=self._ienv(state))
            title = self._wait_title(state, client["address"],
                                     "typed-isolated")
            reached = r.returncode == 0 and title == "typed-isolated"
            leaked = self.live_clients() - cl0 or (
                self._live_titles() != titles0)
            check("wtype-instance-only", reached and not leaked,
                  "" if reached and not leaked else
                  f"instance title {title!r}; leaked to live: "
                  f"{bool(leaked)}")
        except Exception as e:                          # noqa: BLE001
            check("wtype-instance-only", False,
                  f"{type(e).__name__}: {e}"[:160])
        finally:
            self._close_marker(holder)

    def _live_titles(self) -> dict:
        r = self.live_hyprctl("-j", "clients")
        try:
            return {c["address"]: c.get("title", "")
                    for c in json.loads(r.stdout.decode())}
        except (ValueError, KeyError, TypeError):
            raise SessionError("cannot read the live clients") from None

    def _soak(self, state, check, soak_s) -> None:
        d = self.d
        if soak_s <= 0:
            check("soak", True, "skipped (--soak-seconds 0)")
            return
        end = d.clock() + soak_s
        bad = ""
        while d.clock() < end and not bad:
            d.sleep(min(SOAK_POLL_S, max(0.0, end - d.clock())))
            if not self.running():
                bad = "the instance process died"
                break
            names = [m.get("name") for m in self.monitors(state)]
            want = [n for n in state.get("WISP_ISOLATED_OUTPUTS",
                                         "").split(",") if n]
            if any(n not in names for n in want):
                bad = f"outputs changed: {names}"
        check("soak", not bad, bad or f"{soak_s}s")


def _lua(s) -> str:
    from wisp import hypr
    return hypr.lua_str(s)


# -- CLI ------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Start, check and stop the isolated Hyprland test "
                    "session (docs/ISOLATED_SESSION.md).")
    ap.add_argument("command", choices=("start", "status", "stop",
                                        "smoke", "canary"))
    ap.add_argument("--state-dir", default="",
                    help="where the env file and session record live "
                         "(default: $XDG_STATE_HOME/wisp-isolated)")
    ap.add_argument("--soak-seconds", type=int, default=SOAK_S,
                    help="smoke: how long the soak runs (default 1800; "
                         "0 skips it)")
    return ap


def main(argv=None, deps=None, out=print) -> int:
    args = build_parser().parse_args(argv)
    s = Session(deps, args.state_dir or None, out)
    try:
        if args.command == "start":
            return s.start()
        if args.command == "status":
            return s.status()
        if args.command == "stop":
            return s.stop()
        if args.command == "canary":
            ok, detail = s.canary()
            out(("canary ok" if ok else f"canary FAILED: {detail}"))
            return EXIT_OK if ok else EXIT_FAIL
        return s.smoke(args.soak_seconds)
    except SessionError as e:
        out(f"isolated_session: {e}")
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
