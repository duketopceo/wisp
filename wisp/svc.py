"""Service hygiene (W29, backend U16): unit templates, sd_notify
watchdog, and the service rows `wispd doctor` prints.

Templates live in `scripts/units/*.service`. `install_units` copies them
into `~/.config/systemd/user/`, backs up any differing unit first, and
only ever runs `systemctl --user daemon-reload` — it never enables,
starts or restarts anything. `wisp-backend-watch` stays external; this
module reads systemd state only.

Stdlib only; every systemd interaction degrades to a no-op when the
tool or `$NOTIFY_SOCKET` is absent.
"""
import configparser
import os
import pathlib
import shutil
import socket
import subprocess
import threading
import time

UNIT_NAMES = ["llama-local", "llama-jev", "llama-uitars", "jev-shim",
              "wispd"]
LLAMA = ["llama-local", "llama-jev", "llama-uitars", "jev-shim"]
ALWAYS_INSTALL = {"wispd"}     # program is placed by install_files itself
SPIN_LINES = 50                # POLLERR lines/min (journal cap is ~200)
SPIN_CPU = 80.0                # % for a cpal_alsa thread


def units_src() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent / "scripts" \
        / "units"


def render(name: str, home=None) -> str:
    """Template text. Units use %h, so no per-user substitution."""
    return (units_src() / f"{name}.service").read_text()


# -- lint ---------------------------------------------------------------

def lint_unit(text: str, name: str = "") -> list:
    """Problems with a unit file; [] when clean."""
    cp = configparser.ConfigParser(strict=True, interpolation=None,
                                   delimiters=("=",))
    cp.optionxform = str
    try:
        cp.read_string(text)
    except configparser.Error as e:
        return [f"parse error: {str(e).splitlines()[0]}"]
    p = []
    for sec in ("Unit", "Service", "Install"):
        if sec not in cp:
            p.append(f"missing [{sec}]")
    if p:
        return p
    u, s = cp["Unit"], cp["Service"]
    for sec, key in (("Unit", "Description"), ("Service", "ExecStart"),
                     ("Service", "Restart"), ("Service", "RestartSec"),
                     ("Install", "WantedBy")):
        if key not in cp[sec]:
            p.append(f"missing {key}")
    if "StartLimitIntervalSec" not in u or "StartLimitBurst" not in u:
        p.append("missing StartLimitIntervalSec/StartLimitBurst")
    if s.get("Slice") == "app.slice":
        p.append("Slice=app.slice is oomd-killable (use session.slice)")
    if "WatchdogSec" in s and s.get("Type") != "notify":
        p.append("WatchdogSec needs Type=notify")
    if name in LLAMA and s.get("Slice") != "session.slice" \
            and s.get("ManagedOOMPreference") != "omit":
        p.append("Slice=session.slice or ManagedOOMPreference=omit "
                 "required")
    return p


# -- install ------------------------------------------------------------

def _needed_paths(text: str, home) -> list:
    for line in text.splitlines():
        if line.startswith("ExecStart="):
            toks = line.split("=", 1)[1].split()
            return [t.replace("%h", str(home)) for t in toks
                    if t.startswith(("/", "%h")) and "python" not in t]
    return []


def install_units(home, dry_run: bool = False, names=None,
                  now=None) -> list:
    """Install the templates under `home`. Returns one dict per unit:
    {name, path, action: new|unchanged|update|skip, backup, reason}.
    An `update` first copies the old file to `<unit>.bak-<stamp>`.
    Dry-run computes the same plan and writes nothing."""
    home = pathlib.Path(home)
    udir = home / ".config" / "systemd" / "user"
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    acts, wrote = [], False
    for n in names or UNIT_NAMES:
        text = render(n, home)
        dst = udir / f"{n}.service"
        a = {"name": n, "path": str(dst), "action": "new",
             "backup": None, "reason": ""}
        acts.append(a)
        missing = [] if n in ALWAYS_INSTALL else \
            [x for x in _needed_paths(text, home)
             if not pathlib.Path(x).exists()]
        if missing:
            a["action"], a["reason"] = "skip", f"{missing[0]} not found"
            continue
        if dst.exists():
            if dst.read_text() == text:
                a["action"] = "unchanged"
                continue
            a["action"] = "update"
            a["backup"] = str(dst.with_name(dst.name + f".bak-{stamp}"))
        if dry_run:
            continue
        udir.mkdir(parents=True, exist_ok=True)
        if a["backup"]:
            shutil.copy2(dst, a["backup"])
        dst.write_text(text)
        wrote = True
    if wrote and shutil.which("systemctl"):
        subprocess.run(["systemctl", "--user", "daemon-reload"],
                       capture_output=True)
    return acts


def describe(acts: list, dry_run: bool = False) -> str:
    verb = {"new": "install", "update": "replace", "unchanged": "ok",
            "skip": "skip"}
    out = []
    for a in acts:
        line = f"{'would ' if dry_run and a['action'] in ('new', 'update') else ''}" \
               f"{verb[a['action']]} {a['path']}"
        if a["backup"]:
            line += f" (backup {a['backup']})"
        if a["reason"]:
            line += f" ({a['reason']})"
        out.append(line)
    return "\n".join(out)


# -- sd_notify ----------------------------------------------------------

def notify(msg: str, environ=None) -> bool:
    """sd_notify over $NOTIFY_SOCKET. False (no-op) when unset or the
    send fails; never raises."""
    env = os.environ if environ is None else environ
    path = env.get("NOTIFY_SOCKET")
    if not path:
        return False
    if path.startswith("@"):
        path = "\0" + path[1:]
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            s.sendto(msg.encode(), path)
        finally:
            s.close()
        return True
    except OSError:
        return False


def watchdog_interval(environ=None):
    """Seconds between WATCHDOG=1 pings: a third of WATCHDOG_USEC (well
    under the half systemd recommends), or None when no watchdog."""
    env = os.environ if environ is None else environ
    try:
        usec = int(env.get("WATCHDOG_USEC", ""))
    except ValueError:
        return None
    pid = env.get("WATCHDOG_PID")
    if usec <= 0 or (pid and pid.isdigit() and int(pid) != os.getpid()):
        return None
    return usec / 3_000_000


class Watchdog(threading.Thread):
    """Pings WATCHDOG=1 while `alive()` is true; a false/raising check
    withholds the ping so systemd restarts a wedged daemon. No-op when
    systemd armed no watchdog."""

    def __init__(self, stop: threading.Event, alive, environ=None):
        super().__init__(name="watchdog", daemon=True)
        self._stop_evt, self._alive = stop, alive
        self._env = os.environ if environ is None else environ
        self._every = watchdog_interval(self._env)

    def run(self):
        if self._every is None:
            return
        while not self._stop_evt.wait(self._every):
            try:
                ok = bool(self._alive())
            except Exception:
                ok = False
            if ok:
                notify("WATCHDOG=1", self._env)


# -- doctor -------------------------------------------------------------

def _run(argv: list, timeout: float = 5.0):
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           timeout=timeout)
        return r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return None


def _show(unit: str) -> dict:
    out = _run(["systemctl", "--user", "show", "-p",
                "LoadState,ActiveState,SubState,Result,UnitFileState,"
                "Slice,ManagedOOMPreference,NRestarts", f"{unit}.service"])
    props = {}
    for line in (out or "").splitlines():
        k, _, v = line.partition("=")
        props[k] = v
    return props


def _unit_row(name: str, p: dict):
    """(ok, text) for a loaded unit's properties."""
    active, sub = p.get("ActiveState", "?"), p.get("SubState", "?")
    sl, pref = p.get("Slice", "?"), p.get("ManagedOOMPreference", "none")
    info = f"{active}/{sub}, {sl}, oomd={pref}"
    if p.get("NRestarts") not in (None, "", "0"):
        info += f", restarts={p['NRestarts']}"
    exposed = sl == "app.slice" and pref != "omit"
    res, enabled = p.get("Result", ""), p.get("UnitFileState", "")
    notes, ok = [], True
    if res == "oom-kill":
        notes.append("killed by systemd-oomd")
    if res == "start-limit-hit":
        notes.append(f"start limit hit: systemctl --user reset-failed "
                     f"{name} && systemctl --user start {name}")
    if active != "active" and enabled == "enabled":
        ok = False
        if not notes:
            notes.append("enabled but dead: systemctl --user start "
                         f"{name}")
    elif active == "failed":
        ok = False
    if res == "oom-kill":
        ok = False
    if exposed:
        notes.append("oomd can kill this: run wispd install --units")
        if name in ("llama-local", "llama-jev", "llama-uitars"):
            ok = False
    return ok, info + ("; " + "; ".join(notes) if notes else "")


def voxtype_row():
    """{"name", "value", "ok"}: POLLERR journal flood or a hot cpal_alsa
    thread means the upstream voxtype spin bug."""
    out = _run(["journalctl", "--user", "-u", "voxtype", "--since",
                "-1min", "--no-pager", "-q", "-o", "cat"], 10)
    n = sum("POLLERR" in l for l in (out or "").splitlines())
    ps = _run(["ps", "-eLo", "pcpu=,comm="]) or ""
    hot = 0.0
    for line in ps.splitlines():
        cpu, _, comm = line.strip().partition(" ")
        if comm.strip().startswith("cpal_alsa"):
            try:
                hot = max(hot, float(cpu))
            except ValueError:
                pass
    fix = "systemctl --user restart voxtype"
    if n >= SPIN_LINES or hot >= SPIN_CPU:
        why = (f"alsa::poll() POLLERR x{n} in 1 min" if n >= SPIN_LINES
               else f"cpal_alsa thread at {hot:.0f}% CPU")
        return {"name": "voxtype alsa", "ok": False,
                "value": f"POLLERR spin ({why}); fix: {fix}"}
    return {"name": "voxtype alsa", "ok": True,
            "value": f"no POLLERR spin ({n} lines/min)"}


def doctor_rows() -> list:
    """Rows for the `services` doctor section; [] without systemctl."""
    if not shutil.which("systemctl"):
        return []
    rows = []
    for n in LLAMA:
        p = _show(n)
        if not p or p.get("LoadState") in (None, "", "not-found"):
            continue
        ok, text = _unit_row(n, p)
        rows.append({"name": n, "value": text, "ok": ok})
    rows.append(voxtype_row())
    return rows
