"""Opt-in error reporting to GlitchTip (Sentry-compatible), W16.

Off unless `[report] dsn` is set (a plain DSN or an `omaseal://svc/acct`
ref). Only typed error codes are reported, with a scrubbed context: no
transcripts, screenshots, typed text, env values, tokens or home paths.
Sending is stdlib-only, on a background thread, rate limited, deduped,
and queued offline in a bounded JSONL. Nothing here raises into the
pipeline.
"""
import hashlib
import json
import os
import pathlib
import platform as _platform
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from . import config

QUEUE_FILE = config.DATA_DIR / "report_queue.jsonl"
QUEUE_MAX = 50
PER_CODE_BURST = 3        # token bucket capacity per code
PER_CODE_REFILL = 3       # tokens regained per hour
GLOBAL_PER_HOUR = 20
DEDUPE_SECS = 300
TIMEOUT = 3

# keys whose values are never sent, at any depth
DROP_KEYS = frozenset((
    "transcript", "text", "typed", "typed_text", "screenshot", "screenshots",
    "image", "images", "frame", "audio", "wav", "prompt", "message",
    "messages", "content", "reply", "answer", "env", "environ", "stdin",
    "clipboard", "body", "detail", "error_detail"))
SECRET_KEY = re.compile(
    r"(key|token|secret|passw|dsn|auth|cookie|credential)", re.I)
_TOKEN_RES = (
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{8,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{8,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{8,}"),
    re.compile(r"\bAKIA[0-9A-Z]{12,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=\-]{6,}"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password)=\S+"),
    re.compile(r"data:[a-z]+/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=]+"),
    re.compile(r"[A-Za-z0-9+/]{200,}={0,2}"),
)


def _home_res():
    out = []
    home = os.path.expanduser("~")
    if home and home not in ("/", "~"):
        out.append(re.compile(re.escape(home.rstrip("/"))))
    out.append(re.compile(r"/(?:home|Users)/[^/\s\"':]+"))
    return out


def scrub_text(s: str) -> str:
    s = str(s)
    for r in _home_res():
        s = r.sub("~", s)
    for name, val in os.environ.items():
        if len(val) >= 8 and SECRET_KEY.search(name):
            s = s.replace(val, "[redacted]")
    for r in _TOKEN_RES:
        s = r.sub("[redacted]", s)
    return s[:500]


def scrub(obj, _key: str = "", _depth: int = 0):
    """Recursively scrub JSON-able context. Unknown types become their
    type name, never their repr."""
    if _depth > 6:
        return "[deep]"
    k = _key.lower()
    if k in DROP_KEYS or SECRET_KEY.search(k):
        return "[redacted]"
    if isinstance(obj, dict):
        return {str(a): scrub(b, str(a), _depth + 1)
                for a, b in list(obj.items())[:40]}
    if isinstance(obj, (list, tuple)):
        return [scrub(b, _key, _depth + 1) for b in list(obj)[:40]]
    if isinstance(obj, (bool, int, float)) or obj is None:
        return obj
    if isinstance(obj, (bytes, bytearray)):
        return "[blob]"
    if isinstance(obj, str):
        return scrub_text(obj)
    return type(obj).__name__


# -- DSN ------------------------------------------------------------------

def parse_dsn(dsn: str):
    """-> (envelope_url, public_key, host) or None."""
    try:
        u = urllib.parse.urlsplit(dsn.strip())
        if u.scheme not in ("http", "https") or not u.username \
                or not u.hostname:
            return None
        parts = u.path.strip("/").split("/")
        project = parts[-1]
        if not project:
            return None
        prefix = "/".join(parts[:-1])
        netloc = u.hostname + (f":{u.port}" if u.port else "")
        url = (f"{u.scheme}://{netloc}/"
               f"{prefix + '/' if prefix else ''}api/{project}/envelope/")
        return url, u.username, u.hostname
    except ValueError:
        return None


def resolve_dsn(cfg: dict) -> str:
    raw = (cfg.get("report", {}) or {}).get("dsn", "").strip()
    if raw.startswith("omaseal://"):
        return config.load_env_key(raw)
    return raw


def _num(cfg, key, default):
    try:
        return int((cfg.get("report") or {}).get(key, default))
    except (TypeError, ValueError):
        return default


# -- reporter -------------------------------------------------------------

class Reporter:
    def __init__(self, cfg: dict | None = None, queue_file=None,
                 clock=time.time, sync: bool = False):
        cfg = cfg if cfg is not None else {}
        self._clock = clock
        self._sync = sync
        self.queue_file = pathlib.Path(queue_file or QUEUE_FILE)
        self.queue_max = _num(cfg, "queue_max", QUEUE_MAX)
        self.per_code = _num(cfg, "per_code_per_hour", PER_CODE_REFILL)
        self.burst = max(self.per_code, 1)
        self.global_cap = _num(cfg, "global_per_hour", GLOBAL_PER_HOUR)
        self.dedupe = _num(cfg, "dedupe_secs", DEDUPE_SECS)
        self._lock = threading.Lock()
        self._buckets = {}     # code -> (tokens, ts)
        self._sent = []        # global timestamps in the last hour
        self._seen = {}        # (code, fp) -> ts
        self._parsed = None
        try:
            self._parsed = parse_dsn(resolve_dsn(cfg))
        except Exception:
            self._parsed = None

    @property
    def enabled(self) -> bool:
        return self._parsed is not None

    def queue_depth(self) -> int:
        try:
            return sum(1 for l in self.queue_file.read_text().splitlines()
                       if l.strip())
        except OSError:
            return 0

    # -- policy
    def _allow(self, code: str, fp: str) -> bool:
        now = self._clock()
        with self._lock:
            self._seen = {k: t for k, t in self._seen.items()
                          if now - t < self.dedupe}
            if (code, fp) in self._seen:
                return False
            self._sent = [t for t in self._sent if now - t < 3600]
            if len(self._sent) >= self.global_cap:
                return False
            tokens, ts = self._buckets.get(code, (self.burst, now))
            tokens = min(self.burst, tokens
                         + (now - ts) * self.per_code / 3600.0)
            if tokens < 1:
                self._buckets[code] = (tokens, now)
                return False
            self._buckets[code] = (tokens - 1, now)
            self._seen[(code, fp)] = now
            self._sent.append(now)
            return True

    # -- event
    def build_event(self, code: str, exc=None, context=None) -> dict:
        etype = type(exc).__name__ if exc is not None else code
        ev = {
            "event_id": uuid.uuid4().hex,
            "timestamp": self._clock(),
            "platform": "python",
            "level": "error",
            "logger": "wisp",
            "message": f"wisp error: {code}",
            "fingerprint": [code, etype],
            "tags": {"error_code": code, "exc_type": etype},
            "contexts": {"runtime": {
                "name": "python", "version": _platform.python_version()},
                "os": {"name": _platform.system()}},
            "extra": scrub(context or {}),
        }
        return ev

    def capture(self, code: str, exc=None, context=None) -> bool:
        """Queue-or-send one error. True when accepted. Never raises."""
        try:
            if not self.enabled:
                return False
            from . import errors_codes as _ec
            if code not in _ec.CODES:
                code = "internal"
            fp = type(exc).__name__ if exc is not None else ""
            if not self._allow(code, fp):
                return False
            ev = self.build_event(code, exc, context)
            if self._sync:
                self._deliver(ev)
            else:
                threading.Thread(target=self._deliver, args=(ev,),
                                 daemon=True, name="wisp-report").start()
            return True
        except Exception:
            return False

    # -- transport
    def envelope(self, ev: dict) -> bytes:
        head = {"event_id": ev["event_id"],
                "sent_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                         time.gmtime(self._clock()))}
        body = json.dumps(ev, separators=(",", ":"))
        return "\n".join((json.dumps(head), json.dumps({"type": "event"}),
                          body)).encode()

    def _post(self, ev: dict) -> bool:
        url, key, _host = self._parsed
        req = urllib.request.Request(
            url, data=self.envelope(ev), method="POST", headers={
                "Content-Type": "application/x-sentry-envelope",
                "X-Sentry-Auth": (f"Sentry sentry_version=7, "
                                  f"sentry_client=wisp/1, "
                                  f"sentry_key={key}")})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return 200 <= r.status < 300
        except urllib.error.HTTPError as e:
            e.close()
            return False
        except Exception:
            return False

    def _deliver(self, ev: dict) -> None:
        try:
            if self._post(ev):
                self.flush()
            else:
                self._enqueue(ev)
        except Exception:
            pass

    def _enqueue(self, ev: dict) -> None:
        with self._lock:
            try:
                lines = [l for l in
                         self.queue_file.read_text().splitlines()
                         if l.strip()]
            except OSError:
                lines = []
            lines.append(json.dumps(ev, separators=(",", ":")))
            lines = lines[-self.queue_max:]   # drop oldest
            self.queue_file.parent.mkdir(parents=True, exist_ok=True)
            self.queue_file.write_text("\n".join(lines) + "\n")

    def flush(self, limit: int = 10) -> int:
        """Send queued events (oldest first); stop at first failure."""
        sent = 0
        with self._lock:
            try:
                lines = [l for l in
                         self.queue_file.read_text().splitlines()
                         if l.strip()]
            except OSError:
                return 0
        rest = list(lines)
        for l in lines[:limit]:
            try:
                ev = json.loads(l)
            except ValueError:
                rest.remove(l)
                continue
            if not self._post(ev):
                break
            rest.remove(l)
            sent += 1
        with self._lock:
            try:
                self.queue_file.write_text(
                    "".join(r + "\n" for r in rest))
            except OSError:
                pass
        return sent


# -- module-level entry point ----------------------------------------------

_reporter = None
_rlock = threading.Lock()


def get(cfg: dict | None = None) -> Reporter:
    global _reporter
    with _rlock:
        if _reporter is None:
            if cfg is None:
                try:
                    cfg = config.load_config()
                except Exception:
                    cfg = {}
            _reporter = Reporter(cfg)
        return _reporter


def reset() -> None:
    global _reporter
    with _rlock:
        _reporter = None


def capture(code: str, exc=None, context=None) -> bool:
    """Called from the pipeline when a turn ends in error. No-op and no
    network unless `[report] dsn` is configured."""
    try:
        return get().capture(code, exc, context)
    except Exception:
        return False


def status(cfg: dict) -> tuple:
    """(on: bool, queue_depth: int) for doctor. Never resolves omaseal
    refs: a ref or plain DSN string present counts as configured."""
    raw = (cfg.get("report", {}) or {}).get("dsn", "").strip()
    if not raw:
        return False, 0
    return True, Reporter({"report": {"dsn": "x"}}).queue_depth()
