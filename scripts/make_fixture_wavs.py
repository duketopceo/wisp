#!/usr/bin/env python3
"""Regenerate the synthetic WAVs under tests/fixtures/turns/.

Pure stdlib (`wave`, `math`, `struct`): short sine bursts at distinct
pitches, 16 kHz mono 16-bit. No recorded human audio. The fake whisper
server returns the fixture's scripted transcript regardless of content;
the WAVs only need to be valid audio of plausible size.
"""
import math
import pathlib
import struct
import wave

OUT = pathlib.Path(__file__).resolve().parent.parent / "tests" / \
    "fixtures" / "turns"
RATE = 16000

SPECS = {            # name -> (hz, seconds)
    "ask.wav": (440.0, 0.8),
    "act.wav": (554.4, 1.0),
    "choose.wav": (659.3, 0.6),
}


def write(path: pathlib.Path, hz: float, secs: float) -> None:
    n = int(RATE * secs)
    frames = bytearray()
    for i in range(n):
        env = min(1.0, i / 800, (n - i) / 800)  # fade in/out, no clicks
        v = int(9000 * env * math.sin(2 * math.pi * hz * i / RATE))
        frames += struct.pack("<h", v)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (hz, secs) in SPECS.items():
        write(OUT / name, hz, secs)
        print(f"wrote {OUT / name}")
