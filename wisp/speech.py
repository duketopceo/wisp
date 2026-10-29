"""Spoken replies (TTS) with barge-in.

speak() spawns the TTS command and tracks its pid; a new listen (or
stop) calls stop() to kill in-flight speech fast — SIGTERM, no drain.
[voice] cmd overrides the binary: whitespace/shlex-split argv, `{text}`
placeholder replaced by the message (else it's appended as last arg).

SentenceSpeaker (backend U9) starts TTS per completed sentence while the
answer is still streaming; a turn's CancelToken (or stop()) kills the
speaking child and drops the queued sentences.
"""

import os
import queue
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time

_LOCK = threading.Lock()
_NOTED: set = set()      # languages whose "no voice" note was spoken
_PROC: subprocess.Popen | None = None


def local_usable(cfg: dict) -> bool:
    """True when a local TTS command exists to speak with: the [voice]
    cmd's program, else the built-in espeak."""
    cmd = str(((cfg or {}).get("voice") or {}).get("cmd", "")).strip()
    if cmd:
        try:
            first = shlex.split(cmd)[0]
        except (ValueError, IndexError):
            return False
        return bool(shutil.which(first))
    from . import platform
    return platform.tts_binary() is not None


def voice_enabled(cfg: dict) -> bool:
    """[voice] enabled, the one reader every caller goes through. `true`
    and `false` are explicit; `auto` (the default, and an unset or blank
    value) is on when a Groq key resolves or a local voice is installed.
    Anything else is off."""
    raw = ((cfg or {}).get("voice") or {}).get("enabled", "auto")
    v = str(raw).strip().lower() or "auto"
    if v == "true":
        return True
    if v != "auto":
        return False
    from . import tts_groq
    return tts_groq.available(cfg) or local_usable(cfg)


def backend(cfg: dict) -> tuple:
    """(name, why): who speaks a one-off English line now. name is groq,
    cmd ([voice] cmd), espeak or off. The one helper speak(), the doctor
    row and the notice read; makes no network call."""
    from . import tts_groq
    if not voice_enabled(cfg):
        raw = str(((cfg or {}).get("voice") or {}).get("enabled", "auto"))
        return "off", (f"[voice] enabled = {raw.strip()}"
                       if raw.strip().lower() not in ("", "auto")
                       else "no Groq key and no local voice installed")
    local = "cmd" if str(((cfg or {}).get("voice") or {}).get(
        "cmd", "")).strip() else "espeak"
    if tts_groq.provider(cfg) != "groq":
        why = f"provider = {tts_groq.provider(cfg)}"
    elif not tts_groq.available(cfg):
        why = "no Groq key or no audio player"
    else:
        wait = tts_groq.backoff_until()
        if tts_groq._now() >= wait:
            return "groq", "Groq key resolves"
        why = f"Groq backing off until {tts_groq.fmt_time(wait)}"
    if not local_usable(cfg):
        return "off", why + "; no local voice installed"
    return local, why


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


def voice_for(cfg: dict, lang: str) -> tuple:
    """(voice, fallback) for a spoken language; English is ("", False)."""
    from . import lang as _lang
    from . import platform
    return _lang.voice(cfg, lang, platform.tts_binary())


def _argv(msg: str, cfg: dict, lang: str = "") -> list[str] | None:
    cmd = cfg.get("voice", {}).get("cmd", "")
    rate = speed(cfg)
    voice = ""
    if lang:
        voice, _fallback = voice_for(cfg, lang)
    if cmd:
        try:
            parts = shlex.split(cmd)
        except ValueError:
            return None
        if not parts:
            return None
        # `{rate}` receives the speed multiplier (1.0 = normal)
        parts = [p.replace("{rate}", f"{rate:g}") for p in parts]
        if lang:
            # `{lang}` is the language code, `{voice}` the chosen voice
            parts = [p.replace("{lang}", lang).replace(
                "{voice}", voice or lang) for p in parts]
        if "{text}" in parts:
            parts = [msg if p == "{text}" else p for p in parts]
        else:
            parts.append(msg)
        return parts
    from . import platform
    return platform.tts_argv(msg, rate, voice) if voice \
        else platform.tts_argv(msg, rate)


def speak(msg: str, cfg: dict) -> subprocess.Popen | None:
    """Spawn the TTS command; returns the proc (None if voice off or no
    binary). Caller registers on_exit to observe natural completion."""
    global _PROC
    if not msg or not voice_enabled(cfg):
        return None
    if backend(cfg)[0] == "groq":
        return _speak_groq(msg, cfg)
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


class _GroqCall:
    """What speak() returns on the Groq path: the Popen surface callers
    use (poll, wait, terminate, kill), over a SentenceSpeaker that does
    the fetching, playing and espeak fallback. Ends when the line has
    been spoken or the speaker was stopped."""

    def __init__(self, speaker):
        self._sp = speaker
        self._done = threading.Event()

    def poll(self):
        return 0 if self._done.is_set() or self._sp._stopped.is_set() \
            else None

    def wait(self, timeout=None):
        end = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            left = None if end is None else end - time.monotonic()
            if left is not None and left <= 0:
                raise subprocess.TimeoutExpired("groq-speak", timeout)
            self._done.wait(0.02 if left is None else min(0.02, left))
        return 0

    def terminate(self):
        self._sp.stop()

    kill = terminate


def _speak_groq(msg: str, cfg: dict) -> "_GroqCall":
    """Speak one line through the same path as streamed answers
    (chunks, Fetcher, player, cancel, spend cap, backoff, per-failure
    espeak fallback). Returns at once; the network is not waited on."""
    global _PROC
    sp = SentenceSpeaker(cfg)
    call = _GroqCall(sp)
    sp.finish(msg, on_done=call._done.set)
    with _LOCK:
        old, _PROC = _PROC, call
    _kill(old)
    return call


def is_speaking() -> bool:
    """True while the TTS process is running (the wake word is deaf then)."""
    with _LOCK:
        p = _PROC
    return p is not None and p.poll() is None


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

    def __init__(self, cfg: dict, token=None, on_sentence=None,
                 on_audio=None):
        self._cfg = cfg
        self._token = token
        self._on_sentence = on_sentence
        self._on_audio = on_audio        # (ms to first Groq audio)
        self._plock = threading.Lock()   # marks/items: feed vs worker
        self._items: list = []           # (span end, _Item) per sentence
        self._pending: list = []         # marks past every queued sentence
        self._seen = 0                   # marks already ingested
        self.enabled = voice_enabled(cfg)
        self._early_clause = cfg.get("voice", {}).get(
            "early_clause", "true") != "false"
        self.lang = ""              # spoken language of the answer (B23)
        self.started = False
        self.sentence_ms = 0        # est. spoken time of the sentence playing
        self.spoken: list = []
        self._consumed = 0          # chars of the cleaned text queued
        self._head = ""             # the text those chars were taken from
        self._noted = False         # the one-time "no voice" note
        self._q: queue.Queue = queue.Queue()
        self._stopped = threading.Event()
        self._worker = None
        self._proc = None
        self._lock = threading.Lock()
        self._jlock = threading.Lock()   # _order, jobs, _fetcher
        self._order: list = []           # every queued _Item, in order
        self._fetcher = None             # tts_groq.Fetcher, lazy
        self._groq_off = False           # latched: espeak for this turn
        self._t_first = 0                # ns the first sentence was queued
        self._audio_told = False
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
        if not self._t_first:
            self._t_first = time.monotonic_ns()
        with self._jlock:
            self._order.append(item)
        self._q.put(("say", item))
        self._prefetch()
        self._ensure_worker()

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker is None and not self._stopped.is_set():
                self._worker = threading.Thread(target=self._run,
                                                daemon=True)
                self._worker.start()

    # -- worker ----------------------------------------------------
    def _run(self) -> None:
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
            if self._groq_ok():
                self._prefetch()
                self._say_groq(val, points)
            else:
                self._say_local(val.sentence, points)
            val.done = True
            self._prefetch()
        self._release()

    # -- local voice (espeak or [voice] cmd) -------------------------
    def _say_local(self, text: str, points, fire: bool = True) -> None:
        """Speak `text` with the local voice. `fire` False when the
        sentence's points already fired (Groq failed mid-sentence)."""
        if fire:
            self.sentence_ms = sentence_ms(text, self._cfg)
            self._fire(points)
        say = text
        if self.lang and not self._noted:
            self._noted = True
            say = self._fallback_note() + text
        argv = _argv(say, self._cfg, self.lang)
        if argv is None:
            return
        self._play(argv, text)

    def _play(self, argv, spoken: str) -> bool:
        """Run one player/TTS child to its end, registered like every
        speaking child so is_speaking() and barge-in see it. False when
        nothing was spawned."""
        global _PROC
        if self._stopped.is_set():
            return False
        try:
            proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    start_new_session=True)
        except OSError:
            return False
        with self._lock:
            self._proc = proc
        with _LOCK:
            _PROC = proc
        if self._token is not None:
            self._token.register_pid(proc)
        if self._stopped.is_set():
            _kill_now(proc)
        self.spoken.append(spoken)
        proc.wait()
        if self._token is not None:
            self._token.unregister_pid(proc)
        with _LOCK:
            if _PROC is proc:
                _PROC = None
        with self._lock:
            self._proc = None
        return True

    # -- Groq voice --------------------------------------------------
    def _groq_ok(self) -> bool:
        """Groq speaks this sentence: not latched off for the turn, an
        English answer (Orpheus is English only), a key, a player and no
        backoff."""
        from . import tts_groq
        return not self._groq_off and not self.lang \
            and tts_groq.usable(self._cfg)

    def _prefetch(self) -> None:
        """Keep the sentence playing and the one after it fetching."""
        if self._stopped.is_set() or not self._groq_ok():
            return
        from . import tts_groq
        with self._jlock:
            if self._stopped.is_set():
                return
            prev = None
            for item in [i for i in self._order if not i.done][:2]:
                if item.job is None:
                    if self._fetcher is None:
                        self._fetcher = tts_groq.Fetcher(self._cfg)
                    item.job = _Job(item.sentence, self._fetcher,
                                    self._stopped, prev)
                    item.job.start()
                prev = item.job

    def _latch(self) -> None:
        """Groq failed: espeak for the rest of this turn, and what was
        prefetched is dropped."""
        self._groq_off = True
        with self._jlock:
            for item in self._order:
                if item.job is not None:
                    item.job.cancel()
                    item.job = None

    def _say_groq(self, item, points) -> None:
        from . import tts_groq
        job = item.job
        if job is None:               # prefetch refused (stop raced it)
            return
        fired = False
        for i, chunk in enumerate(job.chunks):
            got = job.get(self._stopped)
            if got is None:           # stopped
                return
            argv = None
            if isinstance(got, tts_groq.Audio):
                path = self._wav_file(got.data)
                argv = tts_groq.player_argv(path) if path else None
            if argv is None:          # a failure, or no player after all
                self._latch()
                rest = " ".join(job.chunks[i:])
                self._say_local(rest, points, fire=not fired)
                return
            try:
                if not fired:
                    fired = True
                    # the pen's pace: this sentence's real spoken time
                    self.sentence_ms = got.ms if len(job.chunks) == 1 \
                        else round(got.ms * len(item.sentence)
                                   / max(1, len(chunk)))
                    self._first_audio()
                    self._fire(points)
                self._play(argv, chunk)
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        if not fired:
            self._fire(points)

    @staticmethod
    def _wav_file(data: bytes) -> str:
        try:
            fd, path = tempfile.mkstemp(prefix="wisp-tts-", suffix=".wav")
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            return path
        except OSError:
            return ""

    def _first_audio(self) -> None:
        if self._audio_told or self._on_audio is None:
            return
        self._audio_told = True
        try:
            self._on_audio(round((time.monotonic_ns() - self._t_first)
                                 / 1e6))
        except Exception:   # noqa: BLE001
            pass

    def _fallback_note(self) -> str:
        """"I don't have a Spanish voice" once per language, when the
        default voice has to read it; "" otherwise."""
        from . import lang as _lang
        _voice, fallback = voice_for(self._cfg, self.lang)
        if not fallback or self.lang in _NOTED:
            return ""
        _NOTED.add(self.lang)
        return _lang.fallback_note(self.lang) + " "

    def _release(self) -> None:
        with _LOCK:
            if self in _SPEAKERS:
                _SPEAKERS.remove(self)

    def stop(self) -> None:
        """Kill the speaking child, abort any Groq request in flight and
        drop the queue and the prefetched audio. Does not block."""
        self._stopped.set()
        with self._jlock:
            fetcher = self._fetcher
            for item in self._order:
                if item.job is not None:
                    item.job.cancel()
                    item.job = None
            self._order.clear()
        if fetcher is not None:
            fetcher.close()
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
        self.done = False
        self.job = None


class _Job:
    """Fetches the WAVs for one sentence (one per chunk) on its own
    thread, in order. `get` yields each result: a tts_groq.Audio, or the
    GroqError that ended the run (nothing follows an error)."""

    def __init__(self, sentence: str, fetcher, stopped, prev=None):
        from . import tts_groq
        self.chunks = tts_groq.chunks(sentence)
        self._fetcher = fetcher
        self._stopped = stopped
        self._prev = prev          # requests go out one sentence at a time
        self._off = threading.Event()
        self.finished = threading.Event()
        self.failed = False
        self._q: queue.Queue = queue.Queue()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self) -> None:
        self._off.set()

    def _run(self) -> None:
        try:
            self._fetch_all()
        finally:
            self.finished.set()

    def _fetch_all(self) -> None:
        from . import cancel, tts_groq
        prev = self._prev
        while prev is not None and not prev.finished.wait(0.05):
            if self._off.is_set() or self._stopped.is_set():
                return
        if prev is not None and prev.failed:
            # an earlier sentence failed: do not spend on this one
            self._fail(tts_groq.GroqError("backoff", "earlier sentence failed"))
            return
        for chunk in self.chunks:
            if self._off.is_set() or self._stopped.is_set():
                return
            try:
                audio = self._fetcher.synth(chunk)
            except cancel.Cancelled:
                return
            except tts_groq.GroqError as e:
                self._fail(e)
                return
            except Exception as e:   # noqa: BLE001  never kill the turn
                self._fail(tts_groq.GroqError("net", repr(e)))
                return
            self._put(audio)

    def _fail(self, err) -> None:
        self.failed = True
        self._put(err)

    def _put(self, result) -> None:
        if not (self._off.is_set() or self._stopped.is_set()):
            self._q.put(result)

    def get(self, stopped):
        """Next result in order; None once the speaker is stopped."""
        while not stopped.is_set():
            try:
                return self._q.get(timeout=0.05)
            except queue.Empty:
                continue
        return None


def _kill_now(proc) -> None:
    from . import cancel
    cancel._kill(proc)
