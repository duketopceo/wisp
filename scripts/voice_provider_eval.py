#!/usr/bin/env python3
"""Speech provider metric harness (U13). Fakes by default; no network.

    python scripts/voice_provider_eval.py                 # fake provider
    python scripts/voice_provider_eval.py --json
    python scripts/voice_provider_eval.py --provider groq --live   # spends

Runs a provider over WAV fixtures (STT) and a few sentences (TTS) and
reports the same fields for any provider, fake or real:

    stt_ms        wall time of transcribe()          (the `stt` span)
    tts_start_ms  wall time until synth() returns audio
                  (the `tts_start` span; the real path is not streamed
                  yet, so this is first audio = whole sentence)

U11's composite (key release to first audible audio) is not on master
when this is written, so the composite is not reported; the two spans
above are the same ones U11 builds it from.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WAV_DIR = ROOT / "tests" / "fixtures" / "turns"
SENTENCES = (
    "Click the blue button in the top right.",
    "Done. Now open the File menu and choose Save.",
    "That worked.",
)


def pct(xs: list, q: float):
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 1)


def run(provider, wavs: list, sentences=SENTENCES, clock=time.monotonic,
        price: dict | None = None) -> dict:
    """One report for `provider`. `clock` returns seconds. `price` holds
    {"tts_usd_per_1k_chars", "stt_usd_per_audio_min"} (None = unknown)."""
    price = price or {}
    stt, tts, errors, audio_s, chars = [], [], 0, 0.0, 0
    if provider.caps.stt:
        for w in wavs:
            data = pathlib.Path(w).read_bytes()
            t = clock()
            try:
                provider.transcribe(data)
            except Exception:   # noqa: BLE001 - counted, not raised
                errors += 1
                continue
            stt.append((clock() - t) * 1000)
            audio_s += wav_seconds(data)
    if provider.caps.tts:
        for s in sentences:
            t = clock()
            try:
                provider.synth(s)
            except Exception:   # noqa: BLE001
                errors += 1
                continue
            tts.append((clock() - t) * 1000)
            chars += len(s)
    cost = None
    if price.get("stt_usd_per_audio_min") is not None and \
            price.get("tts_usd_per_1k_chars") is not None:
        cost = round(audio_s / 60 * price["stt_usd_per_audio_min"]
                     + chars / 1000 * price["tts_usd_per_1k_chars"], 6)
    return {"provider": provider.name,
            "stt": {"n": len(stt), "p50_ms": pct(stt, .5),
                    "p90_ms": pct(stt, .9)},
            "tts_start": {"n": len(tts), "p50_ms": pct(tts, .5),
                          "p90_ms": pct(tts, .9)},
            "audio_s": round(audio_s, 2), "chars": chars,
            "errors": errors, "cost_usd": cost}


def wav_seconds(data: bytes) -> float:
    """Duration of a 16-bit mono 16 kHz WAV from its byte size."""
    return max(0, len(data) - 44) / 32000


def render(rep: dict) -> str:
    return (f"{rep['provider']}: stt n={rep['stt']['n']} "
            f"p50={rep['stt']['p50_ms']} p90={rep['stt']['p90_ms']} ms | "
            f"tts_start n={rep['tts_start']['n']} "
            f"p50={rep['tts_start']['p50_ms']} "
            f"p90={rep['tts_start']['p90_ms']} ms | errors={rep['errors']} "
            f"cost_usd={rep['cost_usd']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="fake", choices=("fake", "groq"))
    ap.add_argument("--live", action="store_true",
                    help="required for a real provider; it spends money")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    wavs = sorted(WAV_DIR.glob("*.wav"))
    clock = time.monotonic
    if a.provider == "groq":
        if not a.live:
            print("refusing: a real provider needs --live", file=sys.stderr)
            return 2
        from wisp import config, voice_provider
        provider = voice_provider.GroqProvider(config.load_config())
        price = None            # from docs, not measured: see the note
    else:
        sys.path.insert(0, str(ROOT / "tests"))
        from fakes.voice import FakeClock, FakeProvider
        clock = FakeClock()
        provider, price = FakeProvider(clock=clock), None
    rep = run(provider, wavs, price=price, clock=clock)
    print(json.dumps(rep, indent=2) if a.json else render(rep))
    return 0 if not rep["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
