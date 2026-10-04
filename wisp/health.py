"""Endpoint health: probe, publish, act on (backend U7, KTD8).

`HealthRegistry` probes every configured *local* endpoint (Jev, each
brain-chain entry, optional Ollama/UI-TARS, a loopback STT server) with
a cheap request and a 500 ms timeout, every `[health] interval_s` while
idle, on hotkey press when the last probe is stale, and right after a
connection error. Results go out as the additive `health` field on the
StateBus and a `health_changed` event on each transition.

A probe counts any HTTP response (even 404/405) as up: the question is
"is something listening and answering", not "is the route valid".
Remote endpoints (openrouter.ai, Groq) are never probed — a probe would
spend a network round trip and tells us nothing the real call won't.

Other subsystems plug in with `register(name, fn)`; `fn` returns
`{"ok": bool, "code": str|None}` (e.g. U5's `hypr.health()`).
"""
import http.client
import threading
import time
import urllib.parse
from dataclasses import dataclass

from . import brain, config, errors_codes

_LOOPBACK = ("localhost", "127.0.0.1", "::1")


@dataclass
class Endpoint:
    name: str
    probe_url: str       # URL requested
    code: str            # error code when down (jev_down, brain_down, ...)


def _is_local(url: str) -> bool:
    return (urllib.parse.urlparse(url).hostname or "") in _LOOPBACK


def _origin(url: str) -> str:
    u = urllib.parse.urlparse(url)
    return f"{u.scheme}://{u.netloc}"


def _hcfg(cfg: dict) -> dict:
    return cfg.get("health", {})


def endpoints(cfg: dict, jev_url: str | None = None) -> list:
    """Configured local endpoints, in stable order."""
    jev_url = config.JEV_ENDPOINT if jev_url is None else jev_url
    out: list = []
    if jev_url and _is_local(jev_url):
        out.append(Endpoint("jev", _origin(jev_url) + "/", "jev_down"))
    seen = set()
    for p in brain.chain(cfg):
        base = (p.get("base_url") or "").rstrip("/")
        if not base or not _is_local(base) or p["name"] in seen:
            continue
        seen.add(p["name"])
        path = "/api/tags" if p["kind"] == "ollama" else "/models"
        out.append(Endpoint(f"brain_{p['name']}", base + path,
                            "brain_down"))
    h = _hcfg(cfg)
    if h.get("ollama") and "brain_ollama" not in {e.name for e in out}:
        out.append(Endpoint("ollama", h["ollama"].rstrip("/") + "/api/tags",
                            "brain_down"))
    if h.get("uitars"):
        out.append(Endpoint("uitars", h["uitars"].rstrip("/") + "/v1/models",
                            "ground_down"))
    stt = cfg.get("stt", {})
    if stt.get("provider") == "openai" and _is_local(stt.get("base_url", "")):
        out.append(Endpoint("stt", stt["base_url"].rstrip("/") + "/",
                            "stt_down"))
    return out


class HealthRegistry:
    def __init__(self, cfg: dict, bus=None, jev_url: str | None = None,
                 timeout: float | None = None, clock=time.monotonic):
        h = _hcfg(cfg)
        self.cfg = cfg
        self.bus = bus
        self.clock = clock
        self.interval_s = float(h.get("interval_s", "30"))
        self.press_stale_s = float(h.get("press_stale_s", "10"))
        self.timeout_s = float(h.get("timeout_ms", "500")) / 1000.0 \
            if timeout is None else timeout
        self._eps = {e.name: e for e in endpoints(cfg, jev_url)}
        self._hooks: dict = {}
        self._rows: dict = {}
        self._seen: dict = {}          # name -> clock() of last probe
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None

    # -- registration ----------------------------------------------------

    def register(self, name: str, fn) -> None:
        """Hook probe: fn() -> {"ok": bool, "code": str|None}."""
        with self._lock:
            self._hooks[name] = fn

    # -- probing ---------------------------------------------------------

    def _http_probe(self, ep: Endpoint) -> dict:
        u = urllib.parse.urlparse(ep.probe_url)
        t0 = time.monotonic()
        try:
            conn = http.client.HTTPConnection(
                u.hostname, u.port or 80, timeout=self.timeout_s)
            try:
                conn.request("GET", (u.path or "/")
                             + (f"?{u.query}" if u.query else ""))
                conn.getresponse().read(0)
            finally:
                conn.close()
        except Exception as e:
            code = "timeout" if errors_codes.is_timeout(e) else ep.code
            return {"ok": False, "code": code}
        return {"ok": True, "code": None,
                "latency_ms": round((time.monotonic() - t0) * 1000)}

    def probe(self, name: str) -> dict:
        ep = self._eps.get(name)
        if ep is not None:
            res = self._http_probe(ep)
        else:
            fn = self._hooks.get(name)
            if fn is None:
                return {}
            t0 = time.monotonic()
            try:
                res = dict(fn())
            except Exception:
                res = {"ok": False, "code": "internal"}
            res.setdefault("code", None)
            res.setdefault("latency_ms", round(
                (time.monotonic() - t0) * 1000))
        self._record(name, res)
        return self._rows.get(name, {})

    def probe_all(self) -> dict:
        names = list(self._eps) + [n for n in self._hooks
                                   if n not in self._eps]
        for n in names:
            self.probe(n)
        return self.snapshot()

    def _record(self, name: str, res: dict) -> None:
        with self._lock:
            now = self.clock()
            self._seen[name] = now
            old = self._rows.get(name)
            ok = bool(res.get("ok"))
            changed = (old is None and not ok) or \
                (old is not None and old["ok"] != ok)
            since = old["since"] if old and old["ok"] == ok \
                else _iso_now()
            self._rows[name] = {"ok": ok, "since": since,
                                "latency_ms": res.get("latency_ms"),
                                "code": None if ok else res.get("code")}
            first = old is None
            snap = self.snapshot()
        # publish on first sight or a transition only — a latency wobble
        # must not bump the state seq every 30 s
        if self.bus is not None and (first or changed):
            self.bus.publish(None, health=snap)
            if changed:
                self.bus.emit_event("health_changed", name=name, ok=ok,
                                    code=self._rows[name]["code"])

    # -- reads -----------------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            return {k: dict(v) for k, v in self._rows.items()}

    def known_down(self, name: str, max_age: float | None = None) -> bool:
        """True only when the last observation is recent AND down."""
        max_age = self.press_stale_s if max_age is None else max_age
        with self._lock:
            row = self._rows.get(name)
            if row is None or row["ok"]:
                return False
            return self.clock() - self._seen[name] <= max_age

    # -- schedule --------------------------------------------------------

    def on_press(self) -> None:
        """Hotkey press: refresh anything older than press_stale_s."""
        with self._lock:
            stale = [n for n in list(self._eps) + list(self._hooks)
                     if n not in self._seen
                     or self.clock() - self._seen[n] > self.press_stale_s]
        for n in stale:
            self.probe(n)

    def report_failure(self, name: str, code: str) -> None:
        """A real call just failed: mark down, then confirm by probing
        right away so recovery is also noticed promptly."""
        if name in self._eps or name in self._hooks:
            self._record(name, {"ok": False, "code": code})
            self.probe(name)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()

        def loop():
            while not self._stop.is_set():
                try:
                    self.probe_all()
                except Exception:
                    pass
                self._stop.wait(self.interval_s)
        self._thread = threading.Thread(target=loop, name="health",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t, self._thread = self._thread, None
        if t is not None:
            t.join(timeout=2)


def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# -- `wispd models start` helpers (never run in tests) -------------------

def units_to_start(cfg: dict, snap: dict) -> list:
    """User systemd units behind endpoints that are down, from
    `[health.units]` (endpoint name -> comma list of unit names)."""
    out: list = []
    for name, units in cfg.get("health.units", {}).items():
        if name in snap and not snap[name].get("ok"):
            for u in (x.strip() for x in units.split(",") if x.strip()):
                u = u if u.endswith(".service") else u + ".service"
                if u not in out:
                    out.append(u)
    return out


def start_command(units: list) -> list:
    return ["systemctl", "--user", "start", *units]
