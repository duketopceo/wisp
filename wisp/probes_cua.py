"""cua-driver health probe (W10).

`CuaProbe.check()` classifies the driver into one state; `register()`
plugs it into the HealthRegistry as the `cua` hook. Read only: it looks
for the binary, stats and connects to the socket (nothing is sent), and
runs `cua-driver --version` at most once per binary file.

State table, first match wins:

  absent                 no cua-driver on PATH           not ok  cua_absent
  installed_not_running  binary, no socket file          not ok  cua_down
  socket_unresponsive    socket file, connect refused    not ok  cua_unresponsive
  version_mismatch       running version != PIN          not ok  cua_version
  kill_switch_on         running, kill switch armed      ok (intentional)
  dry_run                running, `[cua] dry_run`        ok (intentional)
  running                everything fine                 ok

Driver faults outrank the safety modes: a kill switch on a dead driver
still reads as a dead driver. Kill switch and dry-run are deliberate
operator choices, so they stay `ok` and only change the label.
"""
import os
import pathlib
import re
import shutil
import socket
import subprocess

from . import cua_safety

REPO = pathlib.Path(__file__).resolve().parent.parent
PIN_FILE = REPO / "scripts" / "cua" / "PIN"

STATES = ("absent", "installed_not_running", "socket_unresponsive",
          "version_mismatch", "kill_switch_on", "dry_run", "running")
_CODES = {"absent": "cua_absent", "installed_not_running": "cua_down",
          "socket_unresponsive": "cua_unresponsive",
          "version_mismatch": "cua_version"}
_FIX = {
    "absent": "scripts/cua/install.sh (or wispd install --cua)",
    "installed_not_running": "systemctl --user start cua-driver.service",
    "socket_unresponsive": "systemctl --user restart cua-driver.service",
    "version_mismatch": "scripts/cua/install.sh (reinstall the pinned "
                        "version)",
    "kill_switch_on": "wispd cua resume",
}
_VER = re.compile(r"\d+\.\d+\.\d+(?:[-+.\w]*)?")


def read_pin(path=None) -> str | None:
    """CUA_VERSION from scripts/cua/PIN (WISP_CUA_PIN overrides the path);
    None when the file is not shipped next to this install."""
    p = pathlib.Path(path or os.environ.get("WISP_CUA_PIN") or PIN_FILE)
    try:
        for line in p.read_text().splitlines():
            if line.startswith("CUA_VERSION="):
                return line.split("=", 1)[1].strip() or None
    except OSError:
        pass
    return None


def default_socket() -> pathlib.Path:
    return pathlib.Path(os.path.expanduser(
        "~/.cache/cua-driver/cua-driver.sock"))


def _connect(path) -> bool:
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(0.5)
    try:
        s.connect(str(path))     # connect only; nothing is sent
        return True
    except OSError:
        return False
    finally:
        s.close()


def _version(binary) -> str | None:
    try:
        r = subprocess.run([str(binary), "--version"], capture_output=True,
                           text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (r.stdout or r.stderr or "").strip() or None


def parse_version(text) -> str | None:
    m = _VER.search(text or "")
    return m.group(0) if m else None


class CuaProbe:
    def __init__(self, cfg: dict | None = None, pin="__default__",
                 which=shutil.which, socket_path=None, kill_path=None,
                 version_fn=_version, connect_fn=_connect):
        self.cfg = cfg or {}
        self.pin = read_pin() if pin == "__default__" else pin
        self._which = which
        self.socket = pathlib.Path(socket_path) if socket_path \
            else default_socket()
        self.kill_path = pathlib.Path(kill_path) if kill_path \
            else cua_safety.kill_default_path()
        self._version_fn = version_fn
        self._connect = connect_fn
        self._vcache: dict = {}    # (binary, mtime) -> version

    def _binary(self):
        try:
            return self._which("cua-driver") or None
        except Exception:
            return None

    def _installed_version(self, binary, run: bool) -> str | None:
        try:
            key = (str(binary), os.stat(binary).st_mtime_ns)
        except OSError:
            key = (str(binary), None)
        if key not in self._vcache:
            if not run:
                return None
            try:
                self._vcache[key] = parse_version(self._version_fn(binary))
            except Exception:
                self._vcache[key] = None
        return self._vcache[key]

    def check(self, version: bool = True) -> dict:
        """-> {state, ok, code, fix, binary, socket, version, pin, kill,
        dry_run}. Never raises. `version=False` skips running the binary
        (a cached version is still used)."""
        s = cua_safety.settings(self.cfg)
        kill = bool(s["kill"] or self.kill_path.exists())
        out = {"state": "absent", "ok": False, "code": None, "fix": None,
               "binary": None, "socket": str(self.socket),
               "version": None, "pin": self.pin, "kill": kill,
               "dry_run": bool(s["dry_run"])}
        binary = self._binary()
        if not binary:
            state = "absent"
        else:
            out["binary"] = str(binary)
            if not self.socket.exists():
                state = "installed_not_running"
            elif not self._connect(self.socket):
                state = "socket_unresponsive"
            else:
                state = "running"
            if state == "running":
                out["version"] = self._installed_version(binary, version)
                if self.pin and out["version"] \
                        and out["version"] != self.pin:
                    state = "version_mismatch"
                elif kill:
                    state = "kill_switch_on"
                elif s["dry_run"]:
                    state = "dry_run"
            else:
                out["version"] = self._installed_version(binary, False)
        out["state"] = state
        out["ok"] = state in ("running", "dry_run", "kill_switch_on")
        out["code"] = _CODES.get(state)
        out["fix"] = _FIX.get(state)
        return out

    def hook(self) -> dict:
        """HealthRegistry hook: {"ok", "code", + detail fields}."""
        try:
            r = self.check()
        except Exception:
            return {"ok": False, "code": "internal"}
        return {"ok": r["ok"], "code": r["code"], "state": r["state"]}

    __call__ = hook


def register(registry, cfg: dict, probe: CuaProbe | None = None,
             force: bool = False) -> CuaProbe | None:
    """Register `cua` with a HealthRegistry. Skipped (None) when cua is
    neither installed nor the selected pointer backend, so machines
    without it never show a permanently red row."""
    probe = probe or CuaProbe(cfg)
    wanted = (cfg or {}).get("pointer", {}).get("backend") == "cua"
    if not (force or wanted or probe._binary()):
        return None
    registry.register("cua", probe)
    return probe
