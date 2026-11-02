"""Hermetic test environment: the suite never touches the real user's state.

`install()` runs before any test module imports `wisp` (the path constants in
wisp/config.py and wisp/platform.py are fixed at import time), and for the
whole run it:

- points HOME and every XDG dir (including XDG_RUNTIME_DIR) at one temp dir,
  so errors.jsonl, wispd.log, labels, suggestions and the wispd socket all
  resolve inside it, never into the real ~/.local/share/wisp or
  $XDG_RUNTIME_DIR/wisp;
- points DBUS_SESSION_BUS_ADDRESS at a path that does not exist, so nothing
  can reach org.freedesktop.Notifications;
- puts a stub `notify-send` first on PATH that only logs its arguments to
  <tmp>/notify.log, so a notification can never reach the desktop.

It is loaded by tests/__init__.py (package-style runs) and by
tests/test_00_hermetic.py (`unittest discover -s tests` imports test modules in
sorted order, so that one runs first). Helpers import it too, so a single
module run (`python -m unittest test_x` from tests/) is covered as well.
"""
import atexit
import os
import pwd
import shutil
import stat
import sys
import tempfile

_MARK = "WISP_TEST_HERMETIC_ROOT"

_XDG = {
    "XDG_DATA_HOME": ".local/share",
    "XDG_STATE_HOME": ".local/state",
    "XDG_CONFIG_HOME": ".config",
    "XDG_CACHE_HOME": ".cache",
}


def real_home() -> str:
    """The invoking user's actual home (the account database, not $HOME)."""
    try:
        return pwd.getpwuid(os.getuid()).pw_dir
    except (KeyError, AttributeError):
        return ""


def real_runtime_dir() -> str:
    return f"/run/user/{os.getuid()}" if hasattr(os, "getuid") else ""


def root() -> str:
    """The temp root for this run ("" before install())."""
    return os.environ.get(_MARK, "")


def notify_log() -> str:
    return os.path.join(root(), "notify.log") if root() else ""


def install() -> str:
    """Idempotent. Returns the temp root."""
    if os.environ.get(_MARK):
        return os.environ[_MARK]
    # short, so unix socket paths under it stay below the 108-byte limit
    base = "/tmp" if os.path.isdir("/tmp") else None
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="wt-", dir=base))
    os.chmod(tmp, 0o700)
    atexit.register(shutil.rmtree, tmp, True)

    for k in ("HYPRLAND_INSTANCE_SIGNATURE", "WAYLAND_DISPLAY", "DISPLAY"):
        os.environ.pop(k, None)

    # not named "home": report/demo scrubbers rewrite any "/home/<x>" path
    home = os.path.join(tmp, "u")
    os.makedirs(home)
    os.environ["HOME"] = home
    for var, rel in _XDG.items():
        d = os.path.join(home, rel)
        os.makedirs(d, exist_ok=True)
        os.environ[var] = d
    rt = os.path.join(tmp, "run")
    os.makedirs(rt, mode=0o700)
    os.chmod(rt, 0o700)  # XDG_RUNTIME_DIR must be 0700
    os.environ["XDG_RUNTIME_DIR"] = rt

    # a bus that cannot exist: gdbus/dbus clients fail fast instead of
    # reaching the real notification server
    os.environ["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=" + os.path.join(
        tmp, "no-such-bus")

    # stub notify-send, logging its argv; first on PATH
    if os.name == "posix":
        bindir = os.path.join(tmp, "bin")
        os.makedirs(bindir)
        stub = os.path.join(bindir, "notify-send")
        with open(stub, "w") as f:
            f.write('#!/bin/sh\nprintf "%s\\n" "$*" >> '
                    f'"{os.path.join(tmp, "notify.log")}"\n')
        os.chmod(stub, os.stat(stub).st_mode | stat.S_IXUSR)
        os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")

    os.environ[_MARK] = tmp
    return tmp


install()
