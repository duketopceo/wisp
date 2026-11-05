"""Key-down warm-up: pay the cold costs while the key is held.

At key-down a daemon thread (a) resolves the hosts the turn will call
(speech to text, the answer brain, hosted voice), so the first request does
not wait on DNS, and (b) wakes the audio output with a short silent clip, so
the first syllable does not pay device spin-up (a sleeping USB or Bluetooth
sink). Nothing is sent to any host and nothing is spent.

Exactly one warm-up runs per press (`begin` replaces an unclaimed one). The
key-up path `claim`s it; a cancelled press `discard`s it, which stops the
thread and the silent clip and waits for both. Any failure is swallowed:
the turn then takes the cold path, with the same result. `[voice] warm =
"false"` turns it off.
"""
from __future__ import annotations

import socket
import subprocess
import tempfile
import threading
import os
from contextlib import suppress
from urllib.parse import urlparse

SILENCE_S = 0.25        # long enough to open the sink, too short to hear
JOIN_S = 1.0            # most `discard` waits for the thread
_CURRENT: "Warm | None" = None
_LOCK = threading.Lock()


def enabled(cfg: dict) -> bool:
    return str((cfg or {}).get("voice", {}).get("warm", "true")).lower() \
        != "false"


def hosts(cfg: dict) -> list:
    """Hostnames this turn is likely to call, de-duplicated, in order."""
    from . import brain, config, tts_groq
    urls = []
    with suppress(Exception):
        urls.append(config.stt_settings(cfg)["base_url"])
    with suppress(Exception):
        urls.append(brain.provider(cfg).get("base_url"))
    with suppress(Exception):
        if tts_groq.provider(cfg) == "groq":
            urls.append(tts_groq.base_url(cfg))
    out = []
    for u in urls:
        h = urlparse(str(u or "")).hostname
        if h and h not in out:
            out.append(h)
    return out


class Warm:
    def __init__(self, cfg: dict, resolve=None, spawn=None, player=None):
        self.cfg = cfg
        self._resolve = resolve or (lambda h: socket.getaddrinfo(h, 443))
        self._spawn = spawn or (lambda argv: subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True))
        self._player = player
        self._stop = threading.Event()
        self._proc = None
        self._tmp = ""
        self._lock = threading.Lock()
        self.resolved: list = []
        self.woke = False
        self.claimed = False
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="wisp-warm")

    def start(self) -> "Warm":
        self._thread.start()
        return self

    def _run(self) -> None:
        try:
            for h in hosts(self.cfg):
                if self._stop.is_set():
                    return
                with suppress(Exception):
                    self._resolve(h)
                    self.resolved.append(h)
            if not self._stop.is_set():
                self._wake_audio()
        except Exception:    # noqa: BLE001 - warming must never raise
            pass

    def _wake_audio(self) -> None:
        from . import speech, stt_stream
        if not speech.voice_enabled(self.cfg):
            return
        argv_for = self._player
        if argv_for is None:
            from . import tts_groq
            argv_for = tts_groq.player_argv
        fd, path = tempfile.mkstemp(prefix="wisp-warm-", suffix=".wav")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(stt_stream.wav_bytes(
                    b"\0\0" * int(stt_stream.RATE * SILENCE_S)))
        except OSError:
            return
        with self._lock:
            self._tmp = path
        argv = argv_for(path)
        if argv is None or self._stop.is_set():
            return
        proc = self._spawn(argv)
        with self._lock:
            self._proc = proc
        self.woke = True
        if self._stop.is_set():
            self._release()
            return
        with suppress(Exception):
            proc.wait(timeout=2)

    def _release(self) -> None:
        with self._lock:
            proc, self._proc = self._proc, None
            tmp, self._tmp = self._tmp, ""
        if proc is not None and proc.poll() is None:
            with suppress(Exception):
                proc.kill()
                proc.wait(timeout=1)
        if tmp:
            with suppress(OSError):
                os.unlink(tmp)

    def join(self, timeout: float = JOIN_S) -> None:
        if self._thread.is_alive():
            self._thread.join(timeout)

    def close(self) -> None:
        """Stop the thread and the silent clip, wait for both."""
        self._stop.set()
        self._release()
        self.join()
        self._release()


def begin(cfg: dict, **kw) -> "Warm | None":
    """Key-down: start the one warm-up for this press."""
    global _CURRENT
    if not enabled(cfg):
        return None
    with _LOCK:
        old, _CURRENT = _CURRENT, None
    if old is not None:
        old.close()
    w = Warm(cfg, **kw)
    with _LOCK:
        _CURRENT = w
    return w.start()


def claim() -> "Warm | None":
    """Key-up: take the press's warm-up (it finishes on its own)."""
    global _CURRENT
    with _LOCK:
        w, _CURRENT = _CURRENT, None
    if w is not None:
        w.claimed = True
    return w


def discard() -> None:
    """A cancelled press: release the warm-up's thread and audio."""
    w = claim()
    if w is not None:
        w.claimed = False
        w.close()
