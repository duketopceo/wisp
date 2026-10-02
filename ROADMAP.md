# Wisp Roadmap

State: **v0.9 released — soak in progress.**
Last updated: 2026-09-30.

Progress on the v1.0 gates:

- ✅ U10 merged (PR #31); release CI verified — `v0.9.0` published all
  five platform archives; linux-aarch64 artifact runs the live daemon.
- ✅ Visible surface: bar glyph, companion orb, app menu, GUI — verified.
- ✅ Run labeling landed: `wispd label correct|incorrect` + orb ✓/✗ →
  `labels.jsonl`; `wispd label` prints the per-route intent-match report.
- 🔄 Soak: label every run; fix top failure mode weekly; re-measure.
  Current: 0/1 labeled (0%) — gate needs ≥50 labeled runs per route.
- ⬜ Fresh-box install ≤10 min on a clean Omarchy VM.
- ⬜ Learning loop exercised twice (`wispd learn` → approve → clarify
  rate drops).
- ⬜ Tag `v1.0.0` once the soak gates pass.

Shipped beyond the v1.0 gates (post-roadmap work, live on master):

- ✅ Proactive companion (2026-09-30): sense collector reads dayflow +
  hyprctl window deltas into `activity.jsonl`; Jev-gated suggestion
  miner → orb "an idea" cards (automate / not now / never, approval-only);
  `agent_runtime=auto` probing + `wispd doctor`; seeded `dayflow-bridge`
  + `self-checkup` skills; GUI Activity tab; `wispd tui`; task caps,
  timeout reaper, PID-reuse pinning, daily model-call budget.
- ✅ Dual-OS (2026-10-01): macOS is now a supported second platform with
  Linux still primary — host-independent suite, `/Applications` app
  catalog (118 apps), per-OS `[apps]` defaults in **both** the Python and
  Rust config layers, a launchd agent that carries a real `PATH` (without
  it brew's `sox` was invisible), and CI running on `macos-latest`
  alongside `ubuntu-latest` so a Linux-only assumption fails the build.
  `docs/MACOS.md` records what is verified and what is not.
- 📋 Planned (2026-09-30): guide cursor (ring + peel-off ghost),
  `click` pointer tool with guide-mode fallback, vision-fed act loop,
  episodic trajectory memory → human-gated recipe skills —
  `docs/plans/2026-09-30-002-feat-wisp-guide-cursor-recipes-plan.md`.

## Where it is

- Pipeline shipped: `Super+D` → PipeWire capture → whisper.cpp (`ggml-small.en`) → Jev routing (`launch | tool | agent | answer | clarify`) → risk-tiered toolbelt / `ori opencode` agents → Omarchy bar widgets.
- Units U1–U9 merged: resident daemon, spoken answers (U4), dictation + orb states (U5), semantic recall via sqlite-vec + RRF (U5c), dev trace `trace.jsonl` (U5e), pluggable brain providers — OpenRouter / openai-compat / Ollama / MLX (U6), macOS adapter (U7), Windows adapter (U8), generic-Linux adapter (U9).
- U10 merged (PR #31); release CI verified end-to-end.
- Session memory, weekly human-gated learning loop (`wispd learn`), and answer-route with optional screenshot context all work in code.

**The honest gap:** verified pieces now exist (release binary runs the
daemon, sense collector is recording, labeling is wired), but labeled
volume is 1 run. Reliability is still unmeasured — v1.0 remains a
verification milestone, not a feature milestone.

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
  macOS is now CI-verified and installable from source
  (`docs/MACOS.md`); the remaining gap is the menu-bar surface and a
  signed/notarized bundle.
- Multi-profile (household) support.
- Local-first everything: STT, routing (Ollama), and answers offline by
  default; cloud models as opt-in accelerators.

## Cut list

Anything not required for the soak is cut from v1.0. Wake word, new tools,
and adapter polish wait. The only metric that ships v1.0 is the labeled
success rate.
