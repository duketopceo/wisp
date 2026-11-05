# Voice provider evaluation (U13)

Date: 2026-11-05. Plan unit: U13 in
`docs/plans/2026-11-04-1847-feat-wisp-teaching-assistant-parity-roadmap-plan.md`.
Live spend for this note: $0.00. Every number below is **from docs, not
measured** unless it says otherwise. Nothing here was called live.

## Decision

1. **No second speech provider is added.** Groq stays the only active
   provider (Whisper `whisper-large-v3-turbo` in, Orpheus
   `canopylabs/orpheus-v1-english` out).
2. **A provider-agnostic seam ships, off by default**
   (`wisp/voice_provider.py`, `[voice] alt_provider`, empty by default).
   No alternative is registered in the tree, so any value falls back to
   Groq. Adding one later is a registration plus a flag, not a rewrite.
3. **The Gemini speech path is not worth adding on its own.** The
   evaluation changed the question: OpenRouter now serves dedicated speech
   endpoints, including the same model families Wisp uses today. See the
   open question.

## What OpenRouter can serve today (from docs, not measured)

Sources, read 2026-11-05: `openrouter.ai/docs/guides/overview/multimodal/stt.md`,
`.../tts.md`, and the Models API with `?output_modalities=transcription`
and `?output_modalities=speech`.

- **Audio in (STT):** `POST /api/v1/audio/transcriptions`, JSON with base64
  audio or an OpenAI-style multipart upload (25 MB cap). Dedicated models
  include `openai/whisper-large-v3-turbo` and `openai/whisper-large-v3`
  (the model Wisp uses on Groq, open weights), `nvidia/parakeet-tdt-0.6b-v3`,
  `qwen/qwen3-asr-0.6b` and `-1.7b`, `elevenlabs/scribe-v2`, and
  `google/gemini-3.5-transcribe`. Chat models with audio input
  (Gemini, Voxtral, `openai/gpt-audio`) also exist but are priced as
  chat tokens and are not a drop-in for transcription.
- **Audio out (TTS):** `POST /api/v1/audio/speech`, raw byte stream,
  `response_format` is `mp3` or `pcm` only (no `wav`; Wisp's player path
  expects WAV, so a PCM-to-WAV wrap is needed). Models include
  `canopylabs/orpheus-3b-0.1-ft` (the Orpheus family Wisp uses on Groq),
  `hexgrad/kokoro-82m`, `elevenlabs/eleven-v4-turbo`,
  `google/gemini-3.8-flash-lite-tts` and others. Voice names are
  per-provider, so Wisp's `hannah` voice would need a mapping.
- Not documented in what was read: time to first audio byte, whether the
  stream starts before synthesis finishes for each model, and rate limits.
  These need a live run.

## Cost (from docs, not measured)

Prices are the Models API `pricing.prompt` values. Units are inferred, not
stated: per second of audio for STT (`whisper-1` reads $0.006/min, which
matches OpenAI's list price) and per character for TTS.

| role | model | OpenRouter price |
|---|---|---|
| STT | `openai/whisper-large-v3-turbo` | $0.012 per audio hour |
| STT | `nvidia/parakeet-tdt-0.6b-v3` | $0.06 per audio hour |
| STT | `elevenlabs/scribe-v2` | $0.22 per audio hour |
| TTS | `hexgrad/kokoro-82m` | $0.62 per 1M chars |
| TTS | `canopylabs/orpheus-3b-0.1-ft` | $7 per 1M chars |
| TTS | `elevenlabs/eleven-v4-turbo` | $40 per 1M chars |

Groq's own prices were not re-read for this note, so no saving or loss
against the current provider is claimed. Compare against the owner's
`usage.jsonl` (`wispd spend`) before deciding.

## Latency: not measured

The harness (`scripts/voice_provider_eval.py`) is built and tested against
a fake provider on the synthetic WAVs in `tests/fixtures/turns/`. It
reports, for any provider: `stt` p50/p90 (the existing `stt` span),
`tts_start` p50/p90 (the existing `tts_start` span; the shipped path is not
streamed, so this is the whole sentence), audio seconds, characters,
errors and cost when prices are supplied. U11's composite metric
(`feat/latency-first-voice-u11`) was not on `origin` when this was written,
so the composite is not reported; U11 builds it from the same two spans.
The fake's numbers are scripted and prove only that the fields line up.
A real comparison needs `--provider ... --live`, which spends money and
was not run.

## Open question for the owner

The OpenRouter-only rule covers models; speech is served by Groq today.
OpenRouter now offers the same model families (Whisper large-v3-turbo,
Orpheus) on its own endpoints. Should speech move to OpenRouter behind
`[voice] alt_provider`, so Wisp needs one key instead of two?

- If yes: a follow-up PR registers an `openrouter` provider on the seam
  (STT via `/audio/transcriptions`, TTS via `/audio/speech` plus a PCM
  wrap), then a capped live comparison on real latency and price. The
  seam's key and capability fallback means a missing key keeps Groq.
- If no: nothing changes; the seam stays inert.

This is a decision, not a measurement. No behavior changed in this PR.
