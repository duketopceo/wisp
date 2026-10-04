"""Fake cua-driver: daemon on a unix socket + the ``cua-driver call`` CLI.

wisp finds cua through ``platform._cua_live()`` (``cua-driver`` on PATH
AND ``~/.cache/cua-driver/cua-driver.sock`` exists) and drives it with
``cua-driver call <tool> '<json>'`` (``platform.pointer_cmds``). The CLI
shim (bins/_shim.py) connects to this daemon, so the call really crosses
the socket and is recorded here.

Wire format (fake only): one JSON line ``{"tool","args"}`` in, one JSON
line ``{"ok","result"|"error"}`` out.

script keys:
  mode   "live" (default) daemon listening + CLI installed
         "stale" socket file exists, nobody listening, CLI installed
                 (``_cua_live()`` is True but every call fails E_CUA_DOWN)
         "absent" no socket, no CLI (cua-driver not installed)
  tools  {tool: {ok, result, error, latency_ms, hang}}; ``default`` key
         applies to every other tool
"""
import json
import os
import pathlib
import socket
import threading
import time


class FakeCua:
    def __init__(self, home, bins, script: dict | None = None):
        self.script = dict(script or {})
        self.mode = self.script.get("mode", "live")
        self.bins = bins
        self.sock_path = pathlib.Path(home) / ".cache" / "cua-driver" \
            / "cua-driver.sock"
        self.calls: list = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._srv = None
        self._thread = None
        self._conns: list = []

    # -- lifecycle -------------------------------------------------
    def start(self):
        if self.mode == "absent":
            return self
        self.bins.install("cua-driver", {})
        self.sock_path.parent.mkdir(parents=True, exist_ok=True)
        srv = socket.socket(socket.AF_UNIX)
        srv.bind(str(self.sock_path))
        if self.mode == "stale":
            srv.close()  # file stays behind, nobody accepts
            return self
        srv.listen(16)
        srv.settimeout(0.05)
        self._srv = srv
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        for c in list(self._conns):
            try:
                c.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=5)
        if self._srv:
            self._srv.close()
        self.sock_path.unlink(missing_ok=True)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    # -- serving ---------------------------------------------------
    def _serve(self):
        while not self._stop.is_set():
            try:
                c, _ = self._srv.accept()
            except (socket.timeout, OSError):
                continue
            self._conns.append(c)
            threading.Thread(target=self._one, args=(c,),
                             daemon=True).start()

    def _one(self, c):
        try:
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = c.recv(65536)
                if not chunk:
                    return
                buf += chunk
            req = json.loads(buf)
            tool, args = req.get("tool", ""), req.get("args", {})
            with self._lock:
                self.calls.append({"tool": tool, "args": args,
                                   "t": time.monotonic()})
            rule = self._rule(tool)
            if rule.get("latency_ms"):
                self._stop.wait(rule["latency_ms"] / 1000.0)
            if rule.get("hang"):
                self._stop.wait(30)
                return
            if rule.get("ok", True):
                rep = {"ok": True, "result": rule.get(
                    "result", {"tool": tool})}
            else:
                rep = {"ok": False,
                       "error": rule.get("error", "E_CUA_FAILED")}
            c.sendall((json.dumps(rep) + "\n").encode())
        except (OSError, ValueError):
            pass
        finally:
            try:
                c.close()
            except OSError:
                pass

    def _rule(self, tool: str) -> dict:
        tools = self.script.get("tools", {})
        return tools.get(tool, tools.get("default", {}))

    # -- inspection ------------------------------------------------
    def tools(self) -> list:
        return [c["tool"] for c in self.calls]

    def calls_for(self, tool: str) -> list:
        return [c for c in self.calls if c["tool"] == tool]
