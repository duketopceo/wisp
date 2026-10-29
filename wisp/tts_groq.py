"""Groq Orpheus talk-back (U6).

One WAV per chunk of at most 200 characters from Groq's
`/audio/speech`; SentenceSpeaker (speech.py) owns sentence order, point
timing and playback, and uses this module for the network half:

- `chunks(text)`: split on clause breaks, then words, to <= 200 chars;
- `Fetcher`: one speaker's HTTP client. It owns a CancelToken, so
  `close()` shuts every open socket even after the turn's own token is
  gone (the worker thread outlives the turn's `cancel.bind`);
- backoffs and the last error class, process-wide: a 429 waits out
  `retry-after`, a terms error waits an hour and then re-probes by
  itself. `last_error()` is the record the doctor row and the one-time
  notice (U7) read.

Every request is gated by the paid/cap check before it goes out and
writes one `usage.jsonl` row priced per character.
"""
import http.client
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import namedtuple
from urllib.parse import urlparse

from . import cancel, config, ledger, platform

DEFAULT_MODEL = "canopylabs/orpheus-v1-english"
DEFAULT_VOICE = "hannah"
VOICES = ("autumn", "diana", "hannah", "austin", "daniel", "troy")
DEFAULT_BASE = "https://api.groq.com/openai/v1"
GROQ_KEY_REF = "omaseal://groq/default,GROQ_API_KEY"
MAX_CHARS = 200            # Orpheus rejects longer input
TERMS_BACKOFF_S = 3600     # re-probe an hour after a terms error
RATE_DEFAULT_S = 60        # a 429 without retry-after
RATE_MAX_S = 86400
TIMEOUT_S = 30
MAX_BYTES = 8 * 1024 * 1024
KEY_TTL_HIT_S = 600
KEY_TTL_MISS_S = 30

Audio = namedtuple("Audio", "data ms")


class GroqError(Exception):
    """kind: terms | rate_limit | auth | http | net | bad_audio | budget |
    nokey | backoff. `retry_after` is seconds (rate_limit)."""

    def __init__(self, kind: str, detail: str = "", retry_after: float = 0):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail
        self.retry_after = retry_after


# -- process state ----------------------------------------------------

_LOCK = threading.Lock()
_KEYS: dict = {}           # ref -> (value, expires monotonic)
_UNTIL = 0.0               # no Groq request before this wall time
_LAST: dict | None = None  # last error record, see last_error()
_LOADED = False


def _now() -> float:
    return time.time()


def reset() -> None:
    """Forget the key cache, backoff and last error (tests, and a fresh
    start after the user fixes the cause)."""
    global _UNTIL, _LAST, _LOADED
    with _LOCK:
        _KEYS.clear()
        _UNTIL, _LAST, _LOADED = 0.0, None, False


def _state_path():
    return config.DATA_DIR / "voice_groq.json"


def _read_state() -> dict | None:
    try:
        rec = json.loads(_state_path().read_text())
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) and rec.get("class") else None


def _write_state(rec: dict) -> None:
    """Persist the record so another process (`wispd doctor`) can read
    it. Daemon only: library code run from tests never writes it."""
    if not ledger.ACTIVE:
        return
    path = _state_path()
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(rec))
        os.replace(tmp, path)
    except OSError:
        pass


def _load() -> None:
    global _UNTIL, _LAST, _LOADED
    with _LOCK:
        if _LOADED:
            return
        _LOADED = True
        rec = _read_state() if _LAST is None else None
        if rec:
            _LAST = rec
            _UNTIL = max(_UNTIL, float(rec.get("until") or 0))


def last_error() -> dict | None:
    """{"class", "ts", "until", "detail"} of the latest Groq failure
    (class: terms | rate_limit | auth | http | net | bad_audio); None
    when there has been none. `until` is the wall time Groq is retried
    (0 when it is retried at once)."""
    global _LAST
    _load()
    with _LOCK:
        if _LAST is None:
            _LAST = _read_state()
        return dict(_LAST) if _LAST else None


def backoff_until() -> float:
    """Wall time before which no request is made (0 = none)."""
    _load()
    return _UNTIL


def _trip(err: GroqError) -> None:
    """Record a failure; a rate limit or terms error also starts a
    process-wide backoff."""
    global _UNTIL, _LAST
    now = _now()
    until = 0.0
    if err.kind == "terms":
        until = now + TERMS_BACKOFF_S
    elif err.kind == "rate_limit":
        wait = err.retry_after or RATE_DEFAULT_S
        until = now + min(float(wait), RATE_MAX_S)
    rec = {"class": err.kind, "ts": now, "until": until,
           "detail": err.detail[:300]}
    with _LOCK:
        _LAST = rec
        if until:
            _UNTIL = max(_UNTIL, until)
    _write_state(rec)


# -- settings and key -------------------------------------------------

def _voice_cfg(cfg) -> dict:
    return (cfg or {}).get("voice") or {}


def provider(cfg) -> str:
    return str(_voice_cfg(cfg).get("provider", "groq")).strip().lower() \
        or "groq"


def model(cfg) -> str:
    return str(_voice_cfg(cfg).get("tts_model", "")).strip() or DEFAULT_MODEL


def voice(cfg) -> str:
    return str(_voice_cfg(cfg).get("tts_voice", "")).strip() \
        or DEFAULT_VOICE


def base_url(cfg) -> str:
    return (str(_voice_cfg(cfg).get("tts_base_url", "")).strip()
            or DEFAULT_BASE).rstrip("/")


def _key_ref(cfg) -> str:
    """Where the Groq key lives: the STT key_env when STT talks to Groq
    (one key for both directions), else the default Groq reference. A
    key for some other STT host is never sent to Groq."""
    stt = (cfg or {}).get("stt") or {}
    host = urlparse(str(config.stt_settings(cfg)["base_url"])).hostname or ""
    if stt.get("key_env") and host.split(".")[-2:] == ["groq", "com"]:
        return str(stt["key_env"])
    return GROQ_KEY_REF


def key(cfg) -> str:
    """The Groq key, "" when none resolves. Cached: resolving shells out
    to omaseal (3 s worst case), so never once per sentence."""
    ref = _key_ref(cfg)
    now = time.monotonic()
    with _LOCK:
        hit = _KEYS.get(ref)
        if hit and hit[1] > now:
            return hit[0]
    value = config.load_env_key(ref)
    with _LOCK:
        _KEYS[ref] = (value, now + (KEY_TTL_HIT_S if value
                                    else KEY_TTL_MISS_S))
    return value


def player_argv(path: str) -> list | None:
    """argv that plays the WAV at `path`, None when no player exists."""
    pre = platform.audio_player()
    return pre + [path] if pre else None


def available(cfg) -> bool:
    """Groq is the configured voice and could speak: a key resolves and a
    player is installed. Ignores any backoff."""
    return provider(cfg) == "groq" and bool(key(cfg)) \
        and player_argv("x") is not None


def usable(cfg) -> bool:
    """available() and not inside a rate-limit or terms backoff."""
    return available(cfg) and _now() >= backoff_until()


# -- text and audio ---------------------------------------------------

_CLAUSE = re.compile(r"(?<=[,;:—–])\s+")


def _words(part: str, limit: int) -> list:
    """`part` as pieces of at most `limit` chars, cut at spaces (a word
    longer than the limit is cut hard)."""
    out, cur = [], ""
    for w in part.split():
        while len(w) > limit:
            if cur:
                out.append(cur)
                cur = ""
            out.append(w[:limit])
            w = w[limit:]
        if cur and len(cur) + 1 + len(w) > limit:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    if cur:
        out.append(cur)
    return out


def chunks(text: str, limit: int = MAX_CHARS) -> list:
    """`text` as chunks of at most `limit` characters. Text that fits is
    one chunk; longer text breaks after a comma, semicolon, colon or dash
    where it can and at a space where it cannot, packing greedily."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return [text] if text else []
    pieces = []
    for clause in _CLAUSE.split(text):
        pieces += _words(clause, limit)
    out, cur = [], ""
    for p in pieces:
        if cur and len(cur) + 1 + len(p) <= limit:
            cur = f"{cur} {p}"
        else:
            if cur:
                out.append(cur)
            cur = p
    if cur:
        out.append(cur)
    return out


def wav_ms(data: bytes) -> int:
    """Real duration of a WAV in ms from its header. A data size that is
    0 or runs past the bytes received (a streamed placeholder) is
    replaced by the bytes actually there. ValueError when it is not a
    WAV with audio."""
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a WAV")
    rate = ch = bits = 0
    i = 12
    while i + 8 <= len(data):
        cid = data[i:i + 4]
        size = int.from_bytes(data[i + 4:i + 8], "little")
        body = i + 8
        if cid == b"fmt " and body + 16 <= len(data):
            ch = int.from_bytes(data[body + 2:body + 4], "little")
            rate = int.from_bytes(data[body + 4:body + 8], "little")
            bits = int.from_bytes(data[body + 14:body + 16], "little")
        elif cid == b"data":
            avail = len(data) - body
            if size == 0 or size > avail:
                size = avail
            if not (rate and ch and bits) or size <= 0:
                raise ValueError("no audio")
            return round(size * 8 * 1000 / (rate * ch * bits))
        i = body + size + (size & 1)
    raise ValueError("no data chunk")


# -- the request ------------------------------------------------------

def classify(status: int, headers, body: bytes) -> GroqError:
    """A failed response as a GroqError. Shapes recorded live
    2026-10-28 (tests/fixtures/groq_tts_terms_400.json)."""
    try:
        err = (json.loads(body.decode("utf-8", "replace")) or {}).get(
            "error") or {}
    except (ValueError, AttributeError):
        err = {}
    if not isinstance(err, dict):
        err = {}
    msg = str(err.get("message", ""))
    code = str(err.get("code", ""))
    if status == 400 and (code == "model_terms_required"
                          or "requires terms acceptance" in msg):
        return GroqError("terms", msg or "model terms not accepted")
    if status == 429:
        raw = None
        try:
            raw = headers.get("retry-after") or headers.get("Retry-After")
        except AttributeError:
            pass
        try:
            wait = float(raw)
        except (TypeError, ValueError):
            wait = 0.0
        return GroqError("rate_limit", msg or "rate limited",
                         wait if wait > 0 else RATE_DEFAULT_S)
    if status in (401, 403):
        return GroqError("auth", msg or f"HTTP {status}")
    return GroqError("http", msg or f"HTTP {status}")


def _open(req, timeout, token):
    """The one network seam (tests replace it). The response's socket is
    closed when `token` is cancelled."""
    return cancel.urlopen_with(token, req, timeout=timeout)


class Fetcher:
    """One speaker's Groq client. Owns a CancelToken and every open
    response, so `close()` aborts a request in flight from any thread."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.token = cancel.CancelToken()
        self._resps: set = set()
        self._lock = threading.Lock()

    def synth(self, text: str) -> Audio:
        """WAV for `text` (<= 200 chars). Raises cancel.Cancelled when
        closed, GroqError otherwise. The backoff and the spend cap are
        checked before anything is sent."""
        self.token.check()
        cfg = self.cfg
        if not available(cfg):
            raise GroqError("nokey", "no Groq key or no player")
        if _now() < backoff_until():
            raise GroqError("backoff", "waiting out a Groq backoff")
        if not ledger.paid_allowed(cfg):
            raise GroqError("budget", "daily spend cap reached")
        body = json.dumps({"model": model(cfg), "input": text,
                           "voice": voice(cfg),
                           "response_format": "wav"}).encode()
        req = urllib.request.Request(
            base_url(cfg) + "/audio/speech", data=body, method="POST",
            headers={"Authorization": "Bearer " + key(cfg),
                     "Content-Type": "application/json",
                     "User-Agent": "wisp/1.0"})
        resp = None
        try:
            try:
                resp = _open(req, TIMEOUT_S, self.token)
                with self._lock:
                    self._resps.add(resp)
                data = resp.read(MAX_BYTES + 1)
            except urllib.error.HTTPError as e:
                if self.token.cancelled:
                    raise cancel.Cancelled() from e
                try:
                    detail = e.read(4096)
                except Exception:   # noqa: BLE001
                    detail = b""
                e.close()
                err = classify(e.code, e.headers, detail)
                _trip(err)
                raise err from None
            except cancel.Cancelled:
                raise
            except (urllib.error.URLError, OSError,
                    http.client.HTTPException) as e:
                if self.token.cancelled:
                    raise cancel.Cancelled() from e
                err = GroqError("net", str(e))
                _trip(err)
                raise err from None
        finally:
            if resp is not None:
                with self._lock:
                    self._resps.discard(resp)
                try:
                    resp.close()
                except Exception:   # noqa: BLE001
                    pass
        self.token.check()
        try:
            if len(data) > MAX_BYTES:
                raise ValueError("response too large")
            ms = wav_ms(data)
        except ValueError as e:
            err = GroqError("bad_audio", str(e))
            _trip(err)
            raise err from None
        ledger.note_chars("groq", model(cfg), len(text))
        return Audio(data, ms)

    def close(self) -> None:
        """Abort every request in flight and close every response."""
        self.token.cancel()
        with self._lock:
            resps, self._resps = list(self._resps), set()
        for r in resps:
            try:
                r.close()
            except Exception:   # noqa: BLE001
                pass
