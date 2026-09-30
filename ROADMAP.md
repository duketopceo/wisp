# Wisp Roadmap

State: **v0.x — feature-complete on paper, unproven in fact.**
Last updated: 2026-09-29.

## Where it is

- Pipeline shipped: `Super+D` → PipeWire capture → whisper.cpp (`ggml-small.en`) → Jev routing (`launch | tool | agent | answer | clarify`) → risk-tiered toolbelt / `ori opencode` agents → Omarchy bar widgets.
- Units U1–U9 merged: resident daemon, spoken answers (U4), dictation + orb states (U5), semantic recall via sqlite-vec + RRF (U5c), dev trace `trace.jsonl` (U5e), pluggable brain providers — OpenRouter / openai-compat / Ollama / MLX (U6), macOS adapter (U7), Windows adapter (U8), generic-Linux adapter (U9).
- U10 (release CI, install/config docs, whisper bootstrap) is open in #31, mergeable.
- Session memory, weekly human-gated learning loop (`wispd learn`), and answer-route with optional screenshot context all work in code.

**The honest gap:** no verified end-to-end run exists. Real-world use so far has
been sporadic, and the assistant rarely completes its loop. Reliability is
unknown because it has never been measured. v1.0 exists to fix exactly this —
it is a verification milestone, not a feature milestone.

## v1.0 — "it actually works on my machine"

Definition of done — all required, no substitutes:

1. **U10 merged** and release CI green: binaries for Linux x86_64/aarch64,
   macOS, Windows, published as a tagged release.
2. **A two-week soak with measured success.** Every trigger logged to
   `trace.jsonl` with route + outcome; each run human-labeled correct or
   incorrect. Gate: **≥ 85% intent-match per route** (launch / tool /
   agent / answer) over ≥ 50 labeled runs per route.
3. **Failure budget:** no more than 1 in 20 triggers ends in silence, a wrong
   action, or a daemon crash.
4. **Visible surface, always:** ✦ status glyph live in the Omarchy bar,
   companion orb on screen while listening, `Wisp` in the app menu, and
   the management GUI openable from both — verified after a fresh login,
   not just when launched by hand.
5. **Fresh-box install ≤ 10 minutes** on a clean Omarchy VM, following only
   `docs/INSTALL.md`.
6. **Learning loop exercised twice:** `wispd learn` proposal → human
   approval → measurable clarify-rate drop after each cycle.
7. Tag `v1.0.0` with release notes; marketplace verify request for the
   Omarchy plugin listing.

Order of work: visibility first (landed: real `BarWidget` + `Panel.qml`
popup replacing the wrong-shaped `Panel` root — widget rendered nothing
before) → add run-labeling to trace (small: `wispd label` or a panel
button) → use Wisp daily for two weeks and label every run → fix the top
failure mode each week (expect STT accuracy and Jev routing confidence
first) → re-measure.

## v1.x — depth

- Wake word ("Wisp", openWakeWord) alongside `Super+D`; VAD endpointing
  on top of the toggle capture (landed) so silence auto-stops the mic.
- Whisper upgrade path: `faster-whisper` small → medium on GPU boxes;
  multi-language STT.
- Promote the optional adapters to first-class: dayflow activity mining as
  context, omaseal as the secrets source.
- GUI depth: graphs tab, editable memory, agent task spawn/cancel from the
  panel (exists in the management app unit — polish it).
- Agent lane: named persistent agents that announce progress unprompted.

## v2.0 — the resident OS assistant

- macOS and Windows adapters at v1.0-parity with the Linux surface.
- Multi-profile (household) support.
- Local-first everything: STT, routing (Ollama), and answers offline by
  default; cloud models as opt-in accelerators.

## Cut list

Anything not required for the soak is cut from v1.0. Wake word, new tools,
and adapter polish wait. The only metric that ships v1.0 is the labeled
success rate.
