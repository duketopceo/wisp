"""Turn runner for the replay harness (backend U14).

``run_turn(fixture)`` starts the fake model servers on loopback
ephemeral ports, then runs the REAL ``wisp.pipeline.run_listen`` for one
turn in a child process whose HOME and XDG dirs are a temp tree, with a
fixture WAV standing in for the recorder. It returns the observed state
events, trace events and timing spans. Nothing is written to the real
state/config dirs and the live wispd daemon is never contacted.

Why a child process rather than in-process: ``wisp.config``/``session``/
``trace`` bind their paths at import time, so isolating them reliably
means setting the environment before the first import. The child also
installs the loopback-only ``NetworkGuard`` below.

Events come from a ``StateBus`` subscription in the child (U2): every
write once, in ``seq`` order, with the diff applied onto the subscribe
snapshot. The child also audits that nothing but the bus wrote
``state.json`` (``TurnResult.bus``). The runner never writes state.
"""
import ipaddress
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "turns"

sys.path.insert(0, str(HERE.parent))
from harness import fakes  # noqa: E402


class NetworkViolation(OSError):
    """Raised when code under test tries to leave loopback."""


class NetworkGuard:
    """Fail-closed socket guard: only loopback TCP/UDP and AF_UNIX are
    allowed. Every refused attempt is recorded in ``violations``."""

    def __init__(self):
        self.violations: list = []
        self._saved: dict = {}

    @staticmethod
    def _host_ok(host) -> bool:
        if isinstance(host, bytes):
            host = host.decode(errors="replace")
        if host in (None, "", "localhost"):
            return True
        try:
            return ipaddress.ip_address(host.split("%")[0]).is_loopback
        except ValueError:
            return False

    def _check(self, what: str, host) -> None:
        if not self._host_ok(host):
            self.violations.append(f"{what} {host}")
            raise NetworkViolation(
                f"replay harness blocked non-loopback {what}: {host}")

    def install(self) -> None:
        guard = self
        orig_connect = socket.socket.connect
        orig_connect_ex = socket.socket.connect_ex
        orig_gai = socket.getaddrinfo
        orig_ghbn = socket.gethostbyname
        self._saved = {"connect": orig_connect,
                       "connect_ex": orig_connect_ex,
                       "getaddrinfo": orig_gai,
                       "gethostbyname": orig_ghbn}

        def connect(sock, address):
            if sock.family != socket.AF_UNIX:
                guard._check("connect", address[0])
            return orig_connect(sock, address)

        def connect_ex(sock, address):
            if sock.family != socket.AF_UNIX:
                guard._check("connect", address[0])
            return orig_connect_ex(sock, address)

        def getaddrinfo(host, *a, **kw):
            guard._check("resolve", host)
            return orig_gai(host, *a, **kw)

        def gethostbyname(host):
            guard._check("resolve", host)
            return orig_ghbn(host)

        socket.socket.connect = connect
        socket.socket.connect_ex = connect_ex
        socket.getaddrinfo = getaddrinfo
        socket.gethostbyname = gethostbyname

    def uninstall(self) -> None:
        if not self._saved:
            return
        socket.socket.connect = self._saved["connect"]
        socket.socket.connect_ex = self._saved["connect_ex"]
        socket.getaddrinfo = self._saved["getaddrinfo"]
        socket.gethostbyname = self._saved["gethostbyname"]
        self._saved = {}


# -- fixtures ------------------------------------------------------

def load_fixture(path) -> dict:
    p = pathlib.Path(path)
    if not p.is_absolute() and not p.exists():
        p = FIXTURE_DIR / p
    fx = json.loads(p.read_text())
    fx["_dir"] = str(p.parent)
    return fx


def dedupe(seq: list) -> list:
    out: list = []
    for s in seq:
        if not out or out[-1] != s:
            out.append(s)
    return out


@dataclass
class TurnResult:
    fixture: str = ""
    exit_code: int = 0
    stderr: str = ""
    events: list = field(default_factory=list)   # state transitions
    trace: list = field(default_factory=list)    # wisp trace events
    bus: dict = field(default_factory=dict)      # StateBus writer audit (U2)
    final: dict = field(default_factory=dict)    # last snapshot
    calls: dict = field(default_factory=dict)    # fake name -> [call]
    spans: dict = field(default_factory=dict)    # ms timings
    violations: list = field(default_factory=list)
    launch_calls: list = field(default_factory=list)
    notifications: list = field(default_factory=list)
    interrupt_fired: bool = False
    interrupt_t_ms: int = 0
    peer_closed: dict = field(default_factory=dict)  # fake -> bool
    tempdir: str = ""
    endpoint_urls: dict = field(default_factory=dict)
    expect: dict = field(default_factory=dict)

    @property
    def statuses(self) -> list:
        return dedupe([e["status"] for e in self.events])

    def chat_calls(self, name: str = "brain") -> list:
        """Completion requests only (reachability probes excluded)."""
        return [c for c in self.calls.get(name, [])
                if c["path"].rstrip("/").endswith("/chat/completions")]

    def trace_events(self, step: str) -> list:
        return [dict(e.get("data", {}), ms=e.get("ms"))
                for e in self.trace if e.get("step") == step]

    def timeline(self) -> list:
        """(t_ms, label) rows merging state events, fake-server calls
        and trace spans, sorted by time — for replay_turn.py."""
        rows = []
        for e in self.events:
            rows.append((e["t_ms"], f"state  {e['status']}"
                         + (f"  answer={e['answer']!r}"
                            if e.get("answer") else "")))
        for name, calls in self.calls.items():
            for c in calls:
                rows.append((c["t_ms"], f"fake   {name} "
                             f"{c['method']} {c['path']}"))
        return sorted(rows, key=lambda r: r[0])


def check_expectations(res: TurnResult) -> list:
    """Compare a result with the fixture's ``expect`` block; returns a
    list of human-readable mismatches (empty = pass)."""
    ex, bad = res.expect, []

    def want(key, got):
        if key in ex and ex[key] != got:
            bad.append(f"{key}: expected {ex[key]!r}, got {got!r}")

    want("statuses", res.statuses)
    if "error_detail_contains" in ex and ex["error_detail_contains"] \
            not in str(res.final.get("error_detail", "")):
        bad.append(f"error_detail_contains {ex['error_detail_contains']!r}"
                   f" not in {res.final.get('error_detail')!r}")
    want("answer", res.final.get("answer"))
    want("transcript", res.final.get("transcript"))
    want("launch_calls", res.launch_calls)
    want("error_code", res.final.get("error_code"))
    if "brain_fallback_from" in ex:
        got = [e.get("fallback_from")
               for e in res.trace_events("brain_call")]
        want_ = ex["brain_fallback_from"]
        if got != [want_]:
            bad.append(f"brain_fallback_from: expected {[want_]!r}, "
                       f"got {got!r}")
    if "peer_closed" in ex:
        for name in ex["peer_closed"]:
            if not res.peer_closed.get(name):
                bad.append(f"peer_closed: {name} never saw the client "
                           "hang up")
    want("tool_calls", [t["name"] for t in res.trace_events("tool_call")])
    if "brain_calls" in ex:
        want("brain_calls", len(res.chat_calls()))
    if "result_prefix" in ex and not str(
            res.final.get("result", "")).startswith(ex["result_prefix"]):
        bad.append(f"result_prefix {ex['result_prefix']!r} not in "
                   f"{res.final.get('result')!r}")
    if "error_contains" in ex and ex["error_contains"] not in str(
            res.final.get("error", "")):
        bad.append(f"error_contains {ex['error_contains']!r} not in "
                   f"{res.final.get('error')!r}")
    return bad


# -- running -------------------------------------------------------

def _build_fakes(fx: dict) -> dict:
    eps = fx.get("endpoints", {})
    live = {}
    for name in ("jev", "brain", "whisper"):
        live[name] = fakes.KINDS[name](dict(eps.get(name, {})))
    for name in ("brain2", "uitars", "openrouter_batch"):
        if name in eps:
            live[name] = fakes.KINDS[name](dict(eps[name]))
    return live


def run_turn(fixture, timeout: float = 60.0) -> TurnResult:
    fx = fixture if isinstance(fixture, dict) else load_fixture(fixture)
    base = pathlib.Path(fx.get("_dir", FIXTURE_DIR))
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="wisp-replay-"))
    live = _build_fakes(fx)
    res = TurnResult(fixture=fx.get("name", ""), tempdir=str(tmp),
                     expect=fx.get("expect", {}))
    try:
        for s in live.values():
            s.start()
        res.endpoint_urls = {k: s.url for k, s in live.items()}
        urls = dict(res.endpoint_urls)
        if fx.get("brain_base_url_override"):
            urls["brain_base"] = fx["brain_base_url_override"]
        else:
            urls["brain_base"] = urls["brain"] + "/v1"
        if "brain2" in urls:
            urls["brain2_base"] = urls["brain2"] + "/v1"
        spec = {
            "tmp": str(tmp),
            "wav": str(base / fx["audio"]),
            "urls": urls,
            "config": fx.get("config", {}),
            "chooser": fx.get("chooser"),
            "interrupt_after_ms": fx.get("interrupt_after_ms"),
            "result": str(tmp / "result.json"),
        }
        spec_path = tmp / "spec.json"
        spec_path.write_text(json.dumps(spec))
        home = tmp / "home"
        home.mkdir()
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(tmp / "config"),
            "XDG_DATA_HOME": str(tmp / "data"),
            "XDG_STATE_HOME": str(tmp / "state"),
            "XDG_RUNTIME_DIR": str(tmp / "run"),
            "TMPDIR": str(tmp),
            "WISP_OS": "linux",
            "WISP_FAKE_STT_KEY": "fake-stt-key",
            "OPENROUTER_API_KEY": "fake-openrouter-key",
            "PYTHONPATH": str(ROOT),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        (tmp / "run").mkdir()
        proc = subprocess.run(
            [sys.executable, str(HERE / "_child.py"), str(spec_path)],
            env=env, capture_output=True, text=True, timeout=timeout,
            cwd=str(tmp))
        res.exit_code, res.stderr = proc.returncode, proc.stderr
        out = {}
        rp = pathlib.Path(spec["result"])
        if rp.exists():
            out = json.loads(rp.read_text())
        res.events = out.get("events", [])
        res.trace = out.get("trace", [])
        res.bus = out.get("bus", {})
        res.final = out.get("final", {})
        res.violations = out.get("violations", [])
        res.launch_calls = out.get("launch_calls", [])
        res.notifications = out.get("notifications", [])
        res.interrupt_fired = out.get("interrupt_fired", False)
        res.interrupt_t_ms = round((out.get("interrupt_t", 0) - out.get("t0", 0)) * 1000)
        t0 = out.get("t0", 0.0)
        for e in res.events:
            e["t_ms"] = round((e["t"] - t0) * 1000)
        res.calls = {}
        for name, s in live.items():
            res.calls[name] = [
                {"path": c["path"], "method": c["method"],
                 "body": c["body"], "t": c["t"],
                 "t_ms": round((c["t"] - t0) * 1000)}
                for c in s.calls]
        res.peer_closed = {n: s.peer_closed for n, s in live.items()}
        res.spans = _spans(res)
        return res
    finally:
        for s in live.values():
            s.stop()
        shutil.rmtree(tmp, ignore_errors=True)


def _spans(res: TurnResult) -> dict:
    """Timing spans derived from observed events (ms).

    first_token_ms: brain chat request arriving at the fake -> first
    state event carrying streamed answer text. U1 adds a first-class
    ``first_token`` trace span; this one is measured from outside so it
    is independent of it.
    """
    spans = {}
    brain = res.chat_calls()
    if brain:
        t_req = brain[0]["t"]
        for e in res.events:
            if e["status"] == "speaking" and e.get("answer"):
                spans["first_token_ms"] = round((e["t"] - t_req) * 1000)
                break
    if res.events:
        spans["turn_ms"] = res.events[-1]["t_ms"] - res.events[0]["t_ms"]
    return spans

