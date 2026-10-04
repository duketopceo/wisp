"""Fake Hyprland: request socket + ``.socket2`` event stream.

Layout matches the real compositor: ``<runtime_dir>/hypr/<sig>/
.socket.sock`` (one request per connection, reply then close) and
``.socket2.sock`` (event lines ``name>>data\\n``). Promoted from
test_hypr.py's FakeHypr and extended; ``test_hypr`` re-exports it.

Reply resolution, in order: ``handler(request)`` if given (None return
= hang), else script ``replies[request]`` (non-str values are
JSON-encoded; ``None`` = hang), else the recorded live probe
(tests/fixtures/hypr_probe.json) for queries, else ``"ok"`` for evals
and dispatches.

script keys: replies {request: reply}, hang [requests], events [lines
sent to every event client on connect], hold_events (keep clients open
so ``emit`` can push more).

``with FakeHypr()`` (legacy test mode) patches os.environ and resets
wisp.hypr; ``start()/stop()`` do neither (the replay runner passes the
env to the child process instead).
"""
import json
import os
import pathlib
import socket
import threading
import time
from unittest import mock

import shorttmp  # tests/ is on sys.path (unittest discover -s tests)

FIXTURE = json.loads((pathlib.Path(__file__).resolve().parent.parent
                      / "fixtures" / "hypr_probe.json").read_text())


def ok_handler(r):
    """Fixture JSON for queries, 'ok' for every eval."""
    return FIXTURE[r] if r.startswith("j/") and r in FIXTURE else "ok"


class FakeHypr:
    """Unix-socket fake. handler(request) -> reply str, or None to hang."""

    def __init__(self, handler=None, runtime_dir=None, bins=None,
                 script: dict | None = None, sig: str = "SIG1"):
        self.script = dict(script or {})
        self.td = None
        if runtime_dir is None:
            self.td = shorttmp.TemporaryDirectory()
            runtime_dir = self.td.name
        self.runtime_dir = pathlib.Path(runtime_dir)
        self.sig = sig
        self.dir = self.runtime_dir / "hypr" / sig
        self.dir.mkdir(parents=True)
        # no handler and no script = legacy test_hypr default (probe
        # fixture, "unknown request" otherwise); a script (even {}) =
        # scripted replies with ok for evals.
        self.handler = handler or (
            self._scripted if script is not None
            else (lambda r: FIXTURE.get(r, "unknown request")))
        self.requests: list = []
        self.event_chunks: list = []   # bytes written to each client
        for ev in self.script.get("events", []):
            self.event_chunks.append((ev + "\n").encode())
        self.hold_events = bool(self.script.get("hold_events"))
        self.event_clients: list = []
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.srv = self._listen(".socket.sock")
        self.srv2 = self._listen(".socket2.sock")
        self.threads: list = []
        self.bins = bins
        if bins is not None:
            bins.install("hyprctl", {})
        self._env = mock.patch.dict(os.environ, self.env())

    def env(self) -> dict:
        return {"XDG_RUNTIME_DIR": str(self.runtime_dir),
                "HYPRLAND_INSTANCE_SIGNATURE": self.sig}

    def _scripted(self, r):
        reps = self.script.get("replies", {})
        if r in self.script.get("hang", ()):
            return None
        if r in reps:
            v = reps[r]
            return None if v is None else (
                v if isinstance(v, str) else json.dumps(v))
        return ok_handler(r)

    def _listen(self, name):
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(self.dir / name))
        s.listen(8)
        s.settimeout(0.05)
        return s

    # -- lifecycle -------------------------------------------------
    def start(self):
        if not self.threads:
            self.threads = [
                threading.Thread(target=self._serve, daemon=True),
                threading.Thread(target=self._serve2, daemon=True)]
            for t in self.threads:
                t.start()
        return self

    def stop(self):
        self._stop.set()
        for c in list(self.event_clients):
            try:
                c.close()
            except OSError:
                pass
        for t in self.threads:
            t.join(timeout=2)
        for s in (self.srv, self.srv2):
            s.close()
        if self.td is not None:
            self.td.cleanup()

    def _serve(self):
        while not self._stop.is_set():
            try:
                c, _ = self.srv.accept()
            except (socket.timeout, OSError):
                continue
            threading.Thread(target=self._one, args=(c,),
                             daemon=True).start()

    def _one(self, c):
        c.settimeout(2)
        try:
            req = c.recv(65536).decode()
            self.requests.append(req)
            rep = self.handler(req)
            if rep is None:
                self._stop.wait(2)
            else:
                data = rep.encode()
                # force multi-chunk delivery to exercise reassembly
                for i in range(0, len(data), 4096):
                    c.sendall(data[i:i + 4096])
                    time.sleep(0.001)
        except OSError:
            pass
        finally:
            c.close()

    def _serve2(self):
        while not self._stop.is_set():
            try:
                c, _ = self.srv2.accept()
            except (socket.timeout, OSError):
                continue
            try:
                for chunk in self.event_chunks:
                    c.sendall(chunk)
                    time.sleep(0.01)
            except OSError:
                c.close()
                continue
            if self.hold_events:
                with self._lock:
                    self.event_clients.append(c)
            else:
                c.close()

    # -- events ----------------------------------------------------
    def emit(self, line: str) -> None:
        """Push one event line to every held client (hold_events)."""
        data = (line.rstrip("\n") + "\n").encode()
        with self._lock:
            clients = list(self.event_clients)
        for c in clients:
            try:
                c.sendall(data)
            except OSError:
                pass

    def wait_event_clients(self, n: int, timeout: float = 3.0) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if len(self.event_clients) >= n:
                return True
            time.sleep(0.01)
        return False

    def evals(self) -> list:
        return [r for r in self.requests if r.startswith("eval")]

    def __enter__(self):
        from wisp import hypr
        self._env.start()
        hypr.reset()
        return self.start()

    def __exit__(self, *a):
        from wisp import hypr
        self._env.stop()
        self.stop()
        hypr.reset()
