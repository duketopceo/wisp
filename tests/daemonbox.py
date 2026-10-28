"""Run the real `wispd daemon run` in a throwaway HOME/XDG tree (B29)."""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent


class DaemonBox:
    def __init__(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="wispbox"))
        self.env = dict(os.environ)
        self.env.update({
            "HOME": str(self.tmp / "home"),
            "XDG_RUNTIME_DIR": str(self.tmp / "run"),
            "XDG_CONFIG_HOME": str(self.tmp / "config"),
            "XDG_DATA_HOME": str(self.tmp / "data"),
            "XDG_STATE_HOME": str(self.tmp / "state"),
            "XDG_CACHE_HOME": str(self.tmp / "cache"),
        })
        for k in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE",
                  "DBUS_SESSION_BUS_ADDRESS"):
            self.env.pop(k, None)
        for sub in ("home", "run", "config", "data", "state", "cache"):
            (self.tmp / sub).mkdir()
        (self.tmp / "run").chmod(0o700)
        self.sock = self.tmp / "run" / "wisp" / "wispd.sock"
        self.lock = self.tmp / "run" / "wisp" / "wispd.lock"
        self.procs = []

    def start(self, timeout=30.0) -> subprocess.Popen:
        p = subprocess.Popen(
            [sys.executable, str(ROOT / "wispd"), "daemon", "run"],
            env=self.env, cwd=str(ROOT), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)
        self.procs.append(p)
        end = time.monotonic() + timeout
        while time.monotonic() < end and not self.sock.exists():
            if p.poll() is not None:
                break
            time.sleep(0.1)
        return p

    def run_second(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ROOT / "wispd"), "daemon", "run"],
            env=self.env, cwd=str(ROOT), capture_output=True, text=True,
            timeout=60)

    def close(self):
        for p in self.procs:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
            for f in (p.stdout, p.stderr):
                if f:
                    f.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
