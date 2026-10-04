"""Spoken replies (TTS) with barge-in.

speak() spawns the TTS command and tracks its pid; a new listen (or
stop) calls stop() to kill in-flight speech fast — SIGTERM, no drain.
[voice] cmd overrides the binary: whitespace/shlex-split argv, `{text}`
placeholder replaced by the message (else it's appended as last arg).

SentenceSpeaker (backend U9) starts TTS per completed sentence while the
answer is still streaming; a turn's CancelToken (or stop()) kills the
speaking child and drops the queued sentences.
"""

import queue
import re
import shlex
import shutil
import subprocess
import threading

_LOCK = threading.Lock()
_PROC: subprocess.Popen | None = None


def _argv(msg: str, cfg: dict) -> list[str] | None:
    cmd = cfg.get("voice", {}).get("cmd", "")
    if cmd:
        try:
            parts = shlex.split(cmd)
        except ValueError:
            return None
        if not parts:
            return None
        if "{text}" in parts:
            parts = [msg if p == "{text}" else p for p in parts]
        else:
            parts.append(msg)
        return parts
    from . import platform
    return platform.tts_argv(msg)


def speak(msg: str, cfg: dict) -> subprocess.Popen | None:
    """Spawn the TTS command; returns the proc (None if voice off or no
    binary). Caller registers on_exit to observe natural completion."""
    global _PROC
    if not msg or cfg.get("voice", {}).get("enabled", "false") != "true":
        return None
    argv = _argv(msg, cfg)
    if argv is None:
        return None
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
    except OSError:
        return None
    with _LOCK:
        old, _PROC = _PROC, proc
    _kill(old)
    return proc


def on_exit(proc: subprocess.Popen, cb) -> None:
    """Call cb() when proc exits; also clears the tracked pid."""
    def _watch():
        global _PROC
        proc.wait()
        with _LOCK:
            if _PROC is proc:
                _PROC = None
        cb()
    threading.Thread(target=_watch, daemon=True).start()


def _kill(proc: subprocess.Popen | None) -> None:
    """SIGTERM, then reap (unreaped children leak as zombies)."""
    if proc is None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def stop() -> None:
    global _PROC
    with _LOCK:
        proc, _PROC = _PROC, None
        speakers = list(_SPEAKERS)
    for sp in speakers:
        sp.stop()
    _kill(proc)


_SPEAKERS: list = []
# a sentence ends at . ! or ? (plus closing quotes/brackets) followed by
# whitespace — "3.5" and a trailing "three." with nothing after it yet
# are not complete
_SENTENCE = re.compile(r"(.+?[.!?][\"')\]]*)\s+", re.S)


class SentenceSpeaker:
    """Speak an answer sentence by sentence as it streams (P6).

    `feed(text)` takes the accumulated (cleaned) answer so far and queues
    every newly completed sentence; a worker speaks them in order, one
    child at a time. `finish(full, on_done)` queues the unspoken tail and
    calls `on_done()` after the last sentence has been spoken (or at once
    when voice is off). `stop()` — also called by speech.stop() and on
    cancel of the turn's token — kills the speaking child and drops the
    queue.
    """

    def __init__(self, cfg: dict, token=None):
        self._cfg = cfg
        self._token = token
        self.enabled = cfg.get("voice", {}).get("enabled", "false") == "true"
        self.started = False
        self.spoken: list = []
        self._consumed = 0          # chars of the cleaned text queued
        self._head = ""             # the text those chars were taken from
        self._q: queue.Queue = queue.Queue()
        self._stopped = threading.Event()
        self._worker = None
        self._proc = None
        self._lock = threading.Lock()
        if self.enabled:
            with _LOCK:
                _SPEAKERS.append(self)
            if token is not None:
                token.register_close(self.stop)

    # -- producer side ---------------------------------------------
    def feed(self, text: str) -> None:
        if not self.enabled or self._stopped.is_set():
            return
        while True:
            m = _SENTENCE.match(text, self._consumed)
            if not m:
                return
            self._consumed = m.end()
            self._head = text[:self._consumed]
            self._enqueue(m.group(1).strip())

    def finish(self, full: str, on_done=None) -> None:
        if not self.enabled or self._stopped.is_set():
            if on_done and not self._stopped.is_set():
                on_done()
            return
        self.feed(full + " ")
        tail = full[self._consumed:].strip() \
            if full.startswith(self._head) else ""
        if tail:
            self._consumed = len(full)
            self._enqueue(tail)
        self._q.put(("done", on_done))
        self._ensure_worker()

    def _enqueue(self, sentence: str) -> None:
        if not sentence:
            return
        self.started = True
        self._q.put(("say", sentence))
        self._ensure_worker()

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker is None and not self._stopped.is_set():
                self._worker = threading.Thread(target=self._run,
                                                daemon=True)
                self._worker.start()

    # -- worker ----------------------------------------------------
    def _run(self) -> None:
        global _PROC
        while not self._stopped.is_set():
            try:
                kind, val = self._q.get(timeout=0.05)
            except queue.Empty:
                continue
            if kind == "done":
                self._release()
                if val and not self._stopped.is_set():
                    val()
                return
            argv = _argv(val, self._cfg)
            if argv is None:
                continue
            try:
                proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL,
                                        start_new_session=True)
            except OSError:
                continue
            with self._lock:
                self._proc = proc
            with _LOCK:
                _PROC = proc
            if self._token is not None:
                self._token.register_pid(proc)
            if self._stopped.is_set():
                _kill_now(proc)
            self.spoken.append(val)
            proc.wait()
            if self._token is not None:
                self._token.unregister_pid(proc)
            with _LOCK:
                if _PROC is proc:
                    _PROC = None
            with self._lock:
                self._proc = None
        self._release()

    def _release(self) -> None:
        with _LOCK:
            if self in _SPEAKERS:
                _SPEAKERS.remove(self)

    def stop(self) -> None:
        """Kill the speaking child, drop the queue. Does not block."""
        self._stopped.set()
        with self._lock:
            proc = self._proc
        if proc is not None:
            _kill_now(proc)
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass
        self._release()


def _kill_now(proc) -> None:
    from . import cancel
    cancel._kill(proc)
