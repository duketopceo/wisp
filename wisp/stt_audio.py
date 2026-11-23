"""PCM helpers for speech-to-text: tail trim and tail energy.

Trailing silence after the user stops talking makes whisper models invent
credits and outros ("The End", "Thanks for watching"). Trimming the clip
and measuring how quiet the tail was supports a conservative post-filter
without touching real utterances that end on those words.
"""
from __future__ import annotations

import array
import math
import struct
import sys
import tempfile
import wave
from pathlib import Path

from . import stt_stream

RATE = stt_stream.RATE
SAMPLE_BYTES = stt_stream.SAMPLE_BYTES
FRAME_S = 0.02
MIN_TAIL_KEEP_S = 0.15
MAX_TAIL_TRIM_S = 12.0
SPEECH_RMS = 120.0
QUIET_RMS = 45.0


def _read_pcm(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise wave.Error("expected 16-bit mono WAV")
        rate = w.getframerate()
        pcm = w.readframes(w.getnframes())
    if rate != RATE and pcm:
        # resample is out of scope; callers use the recorder's native rate
        pass
    return pcm, rate


def _rms_frame(pcm: bytes, at: int, frame_bytes: int) -> float:
    chunk = pcm[at:at + frame_bytes]
    n = len(chunk) // SAMPLE_BYTES
    if not n:
        return 0.0
    a = array.array("h")
    a.frombytes(chunk[: n * SAMPLE_BYTES])
    if sys.byteorder != "little":
        a.byteswap()
    return math.sqrt(sum(x * x for x in a) / n)


def tail_stats(pcm: bytes, rate: int = RATE) -> dict:
    """Energy after the last speech frame and overall clip length."""
    frame = max(SAMPLE_BYTES, int(rate * FRAME_S) * SAMPLE_BYTES)
    last_speech = 0
    for at in range(0, len(pcm) - frame + 1, frame):
        if _rms_frame(pcm, at, frame) >= SPEECH_RMS:
            last_speech = at + frame
    tail = pcm[last_speech:] if last_speech else pcm
    tail_s = len(tail) / float(rate * SAMPLE_BYTES) if rate else 0.0
    tail_rms = _rms_frame(tail, 0, len(tail) // SAMPLE_BYTES * SAMPLE_BYTES) \
        if tail else 0.0
    return {"last_speech_end": last_speech, "tail_bytes": len(tail),
            "tail_s": round(tail_s, 3),
            "tail_rms": round(tail_rms, 1),
            "tail_quiet": tail_rms <= QUIET_RMS and tail_s >= 0.25}


def trim_trailing_silence(path: Path, *, min_keep_s: float = MIN_TAIL_KEEP_S
                          ) -> tuple[Path, dict]:
    """Return `(wav_path, meta)` — a trimmed copy when worth it, else the
    original path. `meta` always includes tail_stats fields."""
    try:
        pcm, rate = _read_pcm(path)
    except (OSError, wave.Error):
        return path, {"trimmed": False, "reason": "unreadable"}
    if not pcm:
        return path, {"trimmed": False, "reason": "empty"}
    stats = tail_stats(pcm, rate)
    keep = stats["last_speech_end"] + int(min_keep_s * rate * SAMPLE_BYTES)
    keep = min(len(pcm), keep)
    trimmed_s = (len(pcm) - keep) / float(rate * SAMPLE_BYTES)
    if trimmed_s < 0.2 or trimmed_s > MAX_TAIL_TRIM_S:
        return path, {**stats, "trimmed": False,
                      "trimmed_s": round(trimmed_s, 3)}
    out_pcm = pcm[:keep]
    fd, tmp = tempfile.mkstemp(prefix="wisp-stt-", suffix=".wav")
    try:
        with open(fd, "wb") as f:
            f.write(stt_stream.wav_bytes(out_pcm))
        return Path(tmp), {**stats, "trimmed": True,
                           "trimmed_s": round(trimmed_s, 3),
                           "out": tmp}
    except OSError:
        return path, {**stats, "trimmed": False, "reason": "write_failed"}


def tail_stats_file(path: Path) -> dict:
    try:
        pcm, rate = _read_pcm(path)
        return tail_stats(pcm, rate)
    except (OSError, wave.Error):
        return {}


def prepare_for_stt(path: Path) -> tuple[Path, dict, Path | None]:
    """Trim when helpful; always return tail energy stats for filtering."""
    out, meta = trim_trailing_silence(path)
    if "tail_rms" not in meta:
        meta.update(tail_stats_file(out))
    tmp = out if out != path else None
    return out, meta, tmp