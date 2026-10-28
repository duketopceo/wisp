"""Optional local wake word (B33). Off by default.

`[wakeword] enabled = "true"` makes the daemon listen to the microphone
for the phrase (`[wakeword] phrase`, default "hey wisp"). What that means,
exactly, is `plan()`: audio is read on this machine, only stretches that
sound like speech are transcribed, and the transcription is done by the
local whisper.cpp binary, never by the cloud provider set under [stt]. The
audio is dropped after each check and never written to a log. Until the
phrase is heard nothing leaves the machine, and no screenshot is taken:
the screenshot belongs to the turn the phrase starts.

Guards:
  - it refuses to turn on over open speakers: it needs headphones or a
    PipeWire echo-cancel device (`wispd install --echo-cancel`);
  - it is deaf while wisp speaks and for ECHO_TAIL_S after;
  - the mic-open state is published as `mic` on the state stream, which
    the bar shows for as long as the listener runs;
  - `wispd config set wakeword.enabled false` (or Esc interrupt) is the
    hard off.
"""
import array
import io
import math
import re
import subprocess
import threading
import time
import wave
from collections import deque

RATE = 16000
CHUNK_BYTES = 3200            # 100 ms of 16 kHz mono s16
SILENCE_CHUNKS = 6            # 0.6 s of quiet closes an utterance
MIN_VOICED_CHUNKS = 3         # under 0.3 s is a click, not a word
MAX_CHUNKS = 35               # a wake phrase is short: 3.5 s at most
PREROLL_CHUNKS = 3
RMS_THRESHOLD = 600           # s16 RMS that counts as speech
ECHO_TAIL_S = 1.5
DEFAULT_PHRASE = "hey wisp"


def enabled(cfg) -> bool:
    v = ((cfg or {}).get("wakeword", {}) or {}).get("enabled", "false")
    return str(v).strip().lower() == "true"


def phrase(cfg) -> str:
    p = ((cfg or {}).get("wakeword", {}) or {}).get("phrase", "")
    return str(p).strip().lower() or DEFAULT_PHRASE


def plan(cfg=None) -> str:
    """What turning it on means, in the words the owner reads first."""
    return (
        f'Wake word "{phrase(cfg)}" listens to your microphone for as long '
        "as it is on.\n"
        "  - Audio stays on this machine. Stretches that sound like speech "
        "are checked by the local whisper.cpp model, nothing else, and "
        "dropped right after. Nothing is saved.\n"
        "  - Until the phrase is heard, nothing is sent anywhere and no "
        "screenshot is taken.\n"
        "  - After the phrase, that turn works like a held key: your words "
        "go to the speech provider you chose under [stt].\n"
        "  - The bar shows an open-mic mark the whole time. "
        "`wispd config set wakeword.enabled false` turns it off.\n"
        "  - It needs headphones or echo cancel so wisp does not hear "
        "itself: `wispd install --echo-cancel`.\n"
        "Holding the key to talk is unchanged and stays the default.")


def normalize(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", str(text).lower()).split())


def matches(text: str, wake: str) -> bool:
    t, w = normalize(text), normalize(wake)
    return bool(w) and (t == w or t.startswith(w + " ") or t.endswith(" " + w)
                        or f" {w} " in f" {t} ")


# --- speakers or headphones ------------------------------------------------

def _run(argv) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True,
                              timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def output_kind(runner=_run) -> str:
    """"echo-cancel" | "headphones" | "open" (open speakers or unknown)."""
    if "echo-cancel" in runner(["pactl", "list", "modules", "short"]):
        return "echo-cancel"
    sinks = runner(["pactl", "list", "sinks"])
    default = (runner(["pactl", "get-default-sink"]) or "").strip()
    for block in re.split(r"\n(?=Sink #)", sinks):
        if default and f"Name: {default}" not in block:
            continue
        if re.search(r"Active Port:.*(headphone|headset)", block, re.I) or \
                re.search(r'device\.form_factor = "(headphone|headset|'
                          r'hands-free)"', block):
            return "headphones"
    return "open"


def can_enable(cfg=None, runner=_run):
    """-> (ok, reason). Refuses over open speakers without echo cancel."""
    kind = output_kind(runner)
    if kind == "open":
        return False, ("your sound is coming out of open speakers, so wisp "
                       "would hear itself. Plug in headphones or run "
                       "`wispd install --echo-cancel`, then try again.")
    return True, kind


# --- the detector ----------------------------------------------------------

def rms(pcm: bytes) -> float:
    a = array.array("h")
    a.frombytes(pcm[:len(pcm) - len(pcm) % 2])
    if not a:
        return 0.0
    return math.sqrt(sum(s * s for s in a) / len(a))


def wav_bytes(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return buf.getvalue()


class Detector:
    """Feed 100 ms chunks; `feed` returns True when an utterance that ends
    in or contains the phrase just closed. `transcribe(pcm)->str` is the
    local model; `speaking()->bool` is wisp's own voice."""

    def __init__(self, transcribe, speaking, wake, clock=time.monotonic,
                 threshold: float = RMS_THRESHOLD):
        self.transcribe, self.speaking = transcribe, speaking
        self.wake, self.clock, self.threshold = wake, clock, threshold
        self._quiet_until = 0.0
        self.checked = 0           # utterances sent to the local model
        self._reset()

    def _reset(self):
        self._pre = deque(maxlen=PREROLL_CHUNKS)
        self._buf = bytearray()
        self._voiced = 0
        self._silent = 0

    def feed(self, pcm: bytes) -> bool:
        now = self.clock()
        if self.speaking():
            self._quiet_until = now + ECHO_TAIL_S
        if now < self._quiet_until:
            self._reset()          # wisp's own voice is never examined
            return False
        loud = rms(pcm) >= self.threshold
        if not self._buf:
            if not loud:
                self._pre.append(pcm)
                return False
            for c in self._pre:
                self._buf += c
            self._pre.clear()
        self._buf += pcm
        if loud:
            self._voiced += 1
            self._silent = 0
        else:
            self._silent += 1
        done = self._silent >= SILENCE_CHUNKS or \
            len(self._buf) >= MAX_CHUNKS * CHUNK_BYTES
        if not done:
            return False
        audio, voiced = bytes(self._buf), self._voiced
        self._reset()
        if voiced < MIN_VOICED_CHUNKS:
            return False
        self.checked += 1
        try:
            heard = self.transcribe(audio)
        except Exception:
            return False
        return matches(heard, self.wake)


def local_transcribe(cfg):
    """A transcribe(pcm) that only ever runs the local whisper.cpp binary
    (never the provider under [stt]) and keeps no file afterwards."""
    from . import config

    def go(pcm: bytes) -> str:
        model = config.whisper_model(cfg)
        if not (config.WHISPER_BIN.exists() and model.exists()):
            return ""
        import os
        import tempfile
        fd, name = tempfile.mkstemp(suffix=".wav", dir=str(config.RUN_DIR))
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(wav_bytes(pcm))
            r = subprocess.run([str(config.WHISPER_BIN), "-m", str(model),
                                "-nt", "-f", name], capture_output=True,
                               text=True, timeout=30)
            return " ".join((r.stdout or "").split())
        except (OSError, subprocess.SubprocessError):
            return ""
        finally:
            try:
                os.unlink(name)
            except OSError:
                pass
    return go


# --- the listener the daemon runs --------------------------------------------

class Listener:
    """Reads the mic, runs the detector, and on the phrase starts a turn the
    same way the held key does, then stops it after the user goes quiet."""

    END_SILENCE_CHUNKS = 12     # 1.2 s of quiet ends the turn
    NO_SPEECH_CHUNKS = 60       # 6 s with no words: give up
    MAX_TURN_CHUNKS = 300       # 30 s hard cap

    def __init__(self, cfg, send, publish, open_stream, speaking,
                 transcribe=None, log=print):
        self.cfg, self.send, self.publish = cfg, send, publish
        self.open_stream, self.log = open_stream, log
        self.det = Detector(transcribe or local_transcribe(cfg), speaking,
                            phrase(cfg))
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _turn(self, stream):
        """After the phrase: record like a held key until it goes quiet."""
        self.send("start")
        quiet = heard = n = 0
        while not self._stop.is_set() and n < self.MAX_TURN_CHUNKS:
            chunk = stream.read(CHUNK_BYTES)
            if not chunk:
                break
            n += 1
            if rms(chunk) >= self.det.threshold:
                heard, quiet = heard + 1, 0
            else:
                quiet += 1
            if (heard and quiet >= self.END_SILENCE_CHUNKS) or \
                    (not heard and quiet >= self.NO_SPEECH_CHUNKS):
                break
        self.send("stop")

    def run(self):
        self.publish("open")
        stream = None
        try:
            stream = self.open_stream()
            while not self._stop.is_set() and enabled(self.cfg):
                chunk = stream.read(CHUNK_BYTES)
                if not chunk:
                    break
                if self.det.feed(chunk):
                    self.log("wakeword: heard the phrase")
                    self._turn(stream)
                    self.det._reset()
        finally:
            self.publish("")
            if stream is not None and hasattr(stream, "close"):
                stream.close()


def stream_cmd():
    from . import platform
    return platform.stream_cmd()


class ProcStream:
    """The mic as a raw 16 kHz mono s16 pipe from the system recorder."""

    def __init__(self, argv):
        self.proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL,
                                     stdin=subprocess.DEVNULL)

    def read(self, n):
        return self.proc.stdout.read(n)

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=2)
        except Exception:
            self.proc.kill()


def supervise(cfg, publish, send, speaking, log=print, poll_s: float = 1.0,
              stop=None, can=can_enable, open_stream=None,
              transcribe=None, retry_s: float = 15.0):
    """Daemon thread body: start the listener while `[wakeword] enabled` is
    true and stop it when it is not. Re-checks the output device before each
    start, so unplugging headphones does not leave an open mic over speakers
    for longer than one restart. Returns when `stop` is set."""
    stop = stop or threading.Event()
    listener, next_try, said = None, 0.0, ""
    while not stop.is_set():
        alive = listener is not None and listener._thread.is_alive()
        if enabled(cfg) and not alive and time.monotonic() >= next_try:
            ok, why = can(cfg)
            if not ok:
                if why != said:
                    log(f"wakeword: not starting: {why}")
                said = why
                next_try = time.monotonic() + retry_s
            else:
                argv = stream_cmd() if open_stream is None else True
                if not argv:
                    log("wakeword: no recorder found")
                    next_try = time.monotonic() + retry_s
                else:
                    opener = open_stream or (lambda: ProcStream(stream_cmd()))
                    listener = Listener(cfg, send, publish, opener, speaking,
                                        transcribe=transcribe, log=log)
                    listener.start()
                    said = ""
        elif not enabled(cfg) and listener is not None:
            listener.stop()
            listener = None
        stop.wait(poll_s)
    if listener is not None:
        listener.stop()
