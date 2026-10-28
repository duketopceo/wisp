"""Streaming speech-to-text while the hotkey is held (Phase 7 / R8).

The recorder writes a growing 16 kHz mono s16 WAV. While the key is held,
a worker cuts finished chunks from that file at a quiet moment, so a cut
lands between words, and transcribes each one as its own request. On
release only the audio after the last cut still needs transcribing, and
the texts are joined in order. Short utterances never reach the first
cut and take the ordinary single-request path.

Any failure (a chunk request fails, the header is not a plain PCM WAV,
the worker is late) makes `finish` return None and the caller transcribes
the whole file, so streaming can only save time, never lose speech.
Hosted providers only: the local whisper.cpp path is untouched.
"""
from __future__ import annotations

import array
import math
import os
import pathlib
import struct
import sys
import tempfile
import threading
import time

RATE = 16000
SAMPLE_BYTES = 2
BPS = RATE * SAMPLE_BYTES          # bytes of audio per second
CHUNK_S = 6.0                      # earliest cut, seconds into a chunk
SEARCH_S = 2.0                     # look this far past it for a quiet spot
FRAME_S = 0.1                      # energy window for choosing the cut
MIN_RMS = 60.0                     # quieter than this is treated as silence
MIN_TAIL_S = 0.3                   # a shorter remainder is not worth a call
JOIN_S = 25.0                      # most `finish` waits for the worker

_STREAMS: dict[str, "Streamer"] = {}


def data_offset(head: bytes) -> int | None:
    """Offset of the PCM in a canonical 16 kHz mono s16 WAV, or None."""
    if len(head) < 44 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        return None
    pos = 12
    fmt_ok = False
    while pos + 8 <= len(head):
        cid, size = head[pos:pos + 4], struct.unpack("<I", head[pos + 4:pos + 8])[0]
        if cid == b"fmt " and pos + 24 <= len(head):
            tag, ch, rate = struct.unpack("<HHI", head[pos + 8:pos + 16])
            bits = struct.unpack("<H", head[pos + 22:pos + 24])[0]
            fmt_ok = (tag == 1 and ch == 1 and rate == RATE and bits == 16)
        elif cid == b"data":
            return pos + 8 if fmt_ok else None
        pos += 8 + size + (size & 1)
    return None


def wav_bytes(pcm: bytes) -> bytes:
    n = len(pcm)
    return (b"RIFF" + struct.pack("<I", 36 + n) + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 1, 1, RATE, BPS, SAMPLE_BYTES, 16)
            + b"data" + struct.pack("<I", n) + pcm)


def _rms(pcm: bytes) -> float:
    n = len(pcm) // SAMPLE_BYTES
    if not n:
        return 0.0
    a = array.array("h")
    a.frombytes(pcm[:n * SAMPLE_BYTES])
    if sys.byteorder != "little":
        a.byteswap()
    return math.sqrt(sum(x * x for x in a) / n)


def quiet_cut(pcm: bytes, lo_s: float, hi_s: float) -> int:
    """Byte offset (frame aligned) of the quietest FRAME_S window whose
    centre lies between `lo_s` and `hi_s` seconds into `pcm`."""
    frame = int(RATE * FRAME_S) * SAMPLE_BYTES
    best, best_at = None, int(lo_s * BPS) // 2 * 2
    start = int(lo_s * BPS) // frame * frame
    end = min(int(hi_s * BPS), len(pcm) - frame)
    for at in range(start, max(end, start) + 1, frame):
        e = _rms(pcm[at:at + frame])
        if best is None or e < best:
            best, best_at = e, at + frame // 2
    return best_at // 2 * 2


class Streamer:
    """Watch one recording and transcribe its finished chunks."""

    def __init__(self, path, proc=None, transcribe_fn=None,
                 chunk_s: float = CHUNK_S, tick_s: float = 0.4,
                 journal=None):
        self.path = pathlib.Path(path)
        self.proc = proc                  # the recorder; ends the watch
        self._fn = transcribe_fn
        self.chunk_s = chunk_s
        self.tick_s = tick_s
        self.texts: list[str] = []        # transcripts of the cut chunks
        self.cut = 0                      # PCM bytes already transcribed
        self.journal = journal            # dictate_history.Journal or None
        self.failed = False
        self.enabled = True
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "Streamer":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    # -- worker ----------------------------------------------------
    def _transcribe(self, pcm: bytes) -> str:
        if _rms(pcm) < MIN_RMS:
            return ""                      # silence: nothing to say
        fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="wisp-chunk-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(wav_bytes(pcm))
            return self._fn(pathlib.Path(tmp)) or ""
        finally:
            pathlib.Path(tmp).unlink(missing_ok=True)

    def _setup(self) -> int | None:
        if self._fn is None:
            from . import config, stage_capture
            cfg = config.load_config()
            stt = config.stt_settings(cfg)
            on = str(stt.get("streaming", "true")).strip().lower()
            if stt["provider"] != "openai" or on in ("false", "0", "no", "off"):
                return None
            self._fn = lambda p: stage_capture._transcribe_openai(p, stt, cfg)
        for _ in range(50):                # wait for the header to land
            try:
                off = data_offset(self.path.read_bytes()[:4096])
            except OSError:
                off = None
            if off is not None:
                return off
            if self._stopped():
                return None
            time.sleep(0.05)
        return None

    def _stopped(self) -> bool:
        return self._stop.is_set() or (self.proc is not None
                                       and self.proc.poll() is not None)

    def _run(self) -> None:
        try:
            off = self._setup()
            if off is None:
                self.enabled = False
                return
            need = int((self.chunk_s + SEARCH_S) * BPS)
            while not self._stopped():
                time.sleep(self.tick_s)
                try:
                    with self.path.open("rb") as f:
                        f.seek(off + self.cut)
                        pcm = f.read(need)
                except OSError:
                    continue
                if len(pcm) < need:
                    continue
                at = quiet_cut(pcm, self.chunk_s - 1.0,
                               self.chunk_s + SEARCH_S - 0.5)
                self.texts.append(self._transcribe(pcm[:at]))
                self.cut += at
                if self.journal is not None:
                    self.journal.add(self.texts[-1])   # survives a kill
        except Exception:
            self.failed = True

    # -- consumer --------------------------------------------------
    def finish(self) -> str | None:
        """Transcript of the whole recording, or None when the caller
        should transcribe the file itself. Call after the recorder has
        exited and finalized the WAV."""
        try:
            return self._finish()
        finally:
            if self.journal is not None:
                self.journal.done()        # the text now lives in the turn

    def _finish(self) -> str | None:
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=JOIN_S)
            if t.is_alive():
                return None
        if self.failed or not self.enabled or not self.texts:
            return None                    # nothing streamed: ordinary path
        try:
            data = self.path.read_bytes()
        except OSError:
            return None
        off = data_offset(data[:4096])
        if off is None:
            return None
        tail = data[off + self.cut:]
        tail = tail[:len(tail) // SAMPLE_BYTES * SAMPLE_BYTES]
        parts = list(self.texts)
        if len(tail) >= int(MIN_TAIL_S * BPS):
            try:
                parts.append(self._transcribe(tail))
            except Exception:
                return None
        return " ".join(" ".join(p for p in parts if p).split())


def begin(path, proc) -> "Streamer":
    """Start watching a recording; replaces any earlier unclaimed watch."""
    _STREAMS.clear()
    journal = None
    try:
        from . import config, dictate_history
        journal = dictate_history.Journal(config.load_config())
        journal.start()        # an earlier interrupted session is kept
    except Exception:
        journal = None
    s = Streamer(path, proc, journal=journal).start()
    _STREAMS[str(path)] = s
    return s


def claim(path) -> "Streamer | None":
    return _STREAMS.pop(str(path), None)
