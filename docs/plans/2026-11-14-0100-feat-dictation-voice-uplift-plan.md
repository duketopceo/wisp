---
title: "feat: Dictation uplift and voice quality — screen-aware compose and talk-back voice"
type: feat
date: 2026-11-14
depends_on: docs/plans/2026-11-08-1749-feat-wisp-companion-core-plan.md
roadmap_area: 3+4
---

# Dictation uplift and voice quality

## Goal Capsule

- **Objective:** Wisp matches HeyClicky on dictation's two headline behaviors — plain streaming dictation with correction learning, and screen-aware compose — and replaces the talk-back voice the roadmap calls "not good enough".
- **Means:** Extend the existing `wisp/dictate.py` (cleanup/compose modes, terminal guard, `dictation.json` corrections, wordink→type→paste) and `wisp/speech.py` (barge-in TTS). No new daemon, no new surfaces.
- **Authority:** HeyClicky changelog (sonar-verified 2026-11-14): plain dictation streams at ~450 ms via Fn+Control hold, double-tap Fn+Control hands-free, correction within ~20 s auto-adds to dictionary, text streams in (typing-style insertion). Screen-aware mode uses the current app to draft actual text. Voice count 30, 130+ languages.
- **Stop conditions:** Stop if screen-aware compose needs raw screenshots where a11y text suffices (privacy regression), or if the new voice provider needs a local server (OpenRouter-only engine is fixed decision 1 in ROADMAP).

## Requirements

- **R1 (plain dictation parity).** Streaming insert with first-token budget ~450 ms; double-tap hands-free; correction within 20 s saved to `dictation.json`; terminal newline collapse for every mode.
- **R2 (screen-aware compose).** From focused-window a11y text + `VoiceInk` style memory, draft finished text in the user's voice; per-app `[dictation.profiles.*]` style still applies; typed-not-pasted insertion preferred.
- **R3 (voice).** New hosted talk-back provider selectable via config; `voicepick.py` language mapping preserved; spoken errors still work when provider is down (`NSSpeechSynthesizer`-equivalent fallback or status error).
- **R4 (barge-in, already shipped).** Keep `speech.py` kill-on-new-listen; add no regressions on streaming TTS start latency.

## Units

| ID | Work | Files | Test |
|---|---|---|---|
| U1 | Correction-window enforcement: verify/add 20 s window to `_maybe_correction` + IPC `dictate_correct` path; surface "saved to dictionary" confirmation | `wisp/dictate.py` | `tests/test_dictate.py`: correction at 19 s saved, at 21 s ignored |
| U2 | Screen-aware compose: compose mode reads focused-window text (reuse `context.py` a11y capture, never full screenshot where a11y present) + draft in user voice | `wisp/dictate.py`, `wisp/context.py` | `tests/test_dictate.py`: compose uses window text, drafts email-reply shape, never inserts raw transcript |
| U3 | Voice provider: hosted talk-back candidate (ElevenLabs-class or OpenRouter TTS) behind `[voice]` config; A/B scored on `wispd eval` talk turns | `wisp/speech.py`, `wisp/config.py`, `docs/TRUST.md` | Live: 10 eval turns scored; `test_trust.py` still true |

## Non-goals

- No local/STT server changes; no bootstrap/signed releases; no Event-driven routine logic (Area 5 plan).

## Risks

- Screen-aware compose invites prompt injection from window text — apply the 2026-11-13 framing plan's untrusted-content rule when it lands; until then fence interpolated window text as data.
- Voice cost: measure per-minute against Groq STT budget before defaulting.
