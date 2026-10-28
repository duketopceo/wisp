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


SPEED_MIN, SPEED_MAX = 0.5, 1.5
SPEED_STEPS = (0.5, 0.75, 1.0, 1.25, 1.5)


def speed(cfg: dict) -> float:
    """[voice] speed as a multiplier, clamped to 0.5 to 1.5; 1.0 when
    unset or not a number."""
    raw = (cfg.get("voice") or {}).get("speed", "")
    try:
        v = float(raw) if str(raw).strip() else 1.0
    except (TypeError, ValueError):
        return 1.0
    if v != v:       # NaN
        return 1.0
    return min(SPEED_MAX, max(SPEED_MIN, v))


def sentence_ms(text: str, cfg: dict | None = None) -> int:
    """How long `text` takes to say, in ms: words at espeak's rate scaled
    by [voice] speed. An estimate (the pen's pace, not a timer)."""
    from . import platform
    words = len((text or "").split())
    if not words:
        return 0
    wpm = platform.ESPEAK_WPM * speed(cfg or {})
    return int(round(words / wpm * 60000))


def _argv(msg: str, cfg: dict) -> list[str] | None:
    cmd = cfg.get("voice", {}).get("cmd", "")
    rate = speed(cfg)
    if cmd:
        try:
            parts = shlex.split(cmd)
        except ValueError:
            return None
        if not parts:
            return None
        # `{rate}` receives the speed multiplier (1.0 = normal)
        parts = [p.replace("{rate}", f"{rate:g}") for p in parts]
        if "{text}" in parts:
            parts = [msg if p == "{text}" else p for p in parts]
        else:
            parts.append(msg)
        return parts
    from . import platform
    return platform.tts_argv(msg, rate)


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
_SENTENCE = re.compile(r"(.+?[.!?\u2026][\"')\]]*)\s+", re.S)
# The first thing said can end at a clause break once it is long enough to
# be worth a TTS start, so a long opening sentence need not finish first.
FIRST_CLAUSE_MIN = 28
_CLAUSE = re.compile(
    r"(.{%d,}?[,;:\u2014\u2013][\"')\]]*)\s+" % FIRST_CLAUSE_MIN, re.S)


class SentenceSpeaker:
    """Speak an answer sentence by sentence as it streams (P6).

    `feed(text)` takes the accumulated (cleaned) answer so far and queues
    every newly completed sentence; a worker speaks them in order, one
    child at a time. `finish(full, on_done)` queues the unspoken tail and
    calls `on_done()` after the last sentence has been spoken (or at once
    when voice is off). `stop()` — also called by speech.stop() and on
    cancel of the turn's token — kills the speaking child and drops the
    queue.

    Points: `feed`/`finish` also take `marks` — (offset, point) pairs whose
    offsets index the cleaned text. A mark rides with the sentence whose
    span holds its offset and `on_sentence(points)` receives it when the
    worker starts that sentence (before TTS spawns, so a failed spawn still
    fires). A mark whose sentence was already dequeued fires at once;
    `finish` fires every mark still unassigned with the tail (or at once
    when there is none). `stop()` drops queued marks.
    """

    def __init__(self, cfg: dict, token=None, on_sentence=None):
        self._cfg = cfg
        self._token = token
        self._on_sentence = on_sentence
        self._plock = threading.Lock()   # marks/items: feed vs worker
        self._items: list = []           # (span end, _Item) per sentence
        self._pending: list = []         # marks past every queued sentence
        self._seen = 0                   # marks already ingested
        self.enabled = cfg.get("voice", {}).get("enabled", "false") == "true"
        self._early_clause = cfg.get("voice", {}).get(
            "early_clause", "true") != "false"
        self.started = False
        self.sentence_ms = 0        # est. spoken time of the sentence playing
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
    def feed(self, text: str, marks=()) -> None:
        if not self.enabled or self._stopped.is_set():
            return
        self._ingest(marks)
        while True:
            m = _SENTENCE.match(text, self._consumed)
            if not m and self._early_clause and not self._items:
                m = _CLAUSE.match(text, self._consumed)
            if not m:
                return
            self._consumed = m.end()
            self._head = text[:self._consumed]
            self._enqueue(m.group(1).strip(), self._consumed)

    def finish(self, full: str, on_done=None, marks=()) -> None:
        if not self.enabled or self._stopped.is_set():
            if on_done and not self._stopped.is_set():
                on_done()
            return
        self.feed(full + " ", marks)
        tail = full[self._consumed:].strip() \
            if full.startswith(self._head) else ""
        with self._plock:
            rest, self._pending = self._pending, []
        if tail:
            self._consumed = len(full)
            self._enqueue(tail, self._consumed, rest)
        else:
            self._fire([p for _, p in rest])
        self._q.put(("done", on_done))
        self._ensure_worker()

    def _ingest(self, marks) -> None:
        """Take the marks not seen yet: one inside an already-queued
        sentence rides with it (fires at once if that sentence was
        dequeued); the rest wait for the next sentence or finish()."""
        marks = list(marks)
        late = []
        with self._plock:
            new, self._seen = marks[self._seen:], max(self._seen, len(marks))
            for off, pt in new:
                item = next((it for end, it in self._items if off <= end),
                            None) if off <= self._consumed else None
                if item is None:
                    self._pending.append((off, pt))
                elif item.dequeued:
                    late.append(pt)
                else:
                    item.points.append(pt)
        self._fire(late)

    def _fire(self, points) -> None:
        if points and self._on_sentence and not self._stopped.is_set():
            try:
                self._on_sentence(points)
            except Exception:
                # a callback bug must not kill the worker: the answer is
                # still spoken and on_done still ends the turn
                import sys
                import traceback
                traceback.print_exc(file=sys.stderr)

    def _enqueue(self, sentence: str, end: int, extra=()) -> None:
        with self._plock:
            mine = [m for m in self._pending if m[0] <= end]
            self._pending = [m for m in self._pending if m[0] > end]
            mine += extra
            item = _Item(sentence, [p for _, p in mine])
            self._items.append((end, item))
        if not sentence:
            self._fire(item.points)
            return
        self.started = True
        self._q.put(("say", item))
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
            with self._plock:
                val.dequeued = True
                points = list(val.points)
            self.sentence_ms = sentence_ms(val.sentence, self._cfg)
            self._fire(points)
            val = val.sentence
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


class _Item:
    """One queued sentence and the points that fire when it starts."""

    def __init__(self, sentence: str, points: list):
        self.sentence = sentence
        self.points = points
        self.dequeued = False


def _kill_now(proc) -> None:
    from . import cancel
    cancel._kill(proc)
