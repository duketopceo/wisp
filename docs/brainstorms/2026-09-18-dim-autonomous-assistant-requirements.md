# Product Contract — Dim: Autonomous Voice Assistant for Omarchy

**Date:** 2026-09-18
**Status:** Confirmed (ce-brainstorm synthesis accepted; "RL week by week" added at confirmation)
**Next step:** ce-plan → implementation plan

## Summary

Dim grows from a push-to-talk app launcher into a resident voice assistant daemon for Omarchy — Jev as the brain deciding between a toolbelt (app launch, `ori opencode` for code tasks, named agent spawns, window/system actions), spawnable widgets plus a center top-bar icon as its UI, and a corrections loop that improves routing week over week. Built as a generic, shippable app — fast, not perfect.

## Vision

A Hey Clicky-/Hermes-style assistant that lives on an Omarchy (Hyprland) desktop: press `Super+D`, speak, and Jev routes the request — launch an app, answer a question, spawn a persistent agent, or run a desktop tool — with the outcome visible in lightweight widgets. Voice-first, screen-aware, minimal context switching, safe autonomy. The app is generic and public-ready; Luke's dayflow data is an optional personalization source, never a dependency.

## Target Users

- Primary: Omarchy/Hyprland users who want a voice-first desktop assistant (Linux, Wayland — the underserved Clicky niche).
- Developer mode: the same person uses "Dim, agent …" to spawn `ori opencode` coding agents.

## Requirements

### R1 — Resident daemon

- `dimd` becomes a persistent daemon (systemd user service), not spawn-per-trigger.
- Holds session/conversation state, active-task state, spawned-agent state, widget state.
- `Super+D` remains the trigger: single press → listen → transcribe → decide → act/respond.
- Daemon exposes state to widgets and survives across triggers (follow-ups, task checks).

### R2 — Jev as decision brain

- Jev (OpenRouter decisions, `typesafe/jev-1.13` pin) classifies each utterance into: app launch, toolbelt action, agent spawn, question/conversation, or clarification-needed.
- Conversational utterances ("what can I say?") get answered, not forced into actions.
- Confidence gates: gate on app/target confidence primarily; `launch` executes when target confidence is high even if action confidence is moderate. Uncertain → ask via widget, never silently execute.
- Screen/context awareness: active-window + workspace context in decision state; screenshot-on-demand (explicit capture per request/task start — no continuous streaming).

### R3 — Toolbelt

- Structured tool registry instead of hard-coded launch: launch/focus/close apps, Hyprland window/workspace ops, notifications, screenshot/context capture, shell/typing (guarded), local file search, agent spawn/monitor/stop.
- Each tool declares a risk level; mutating or shell-like tools require confirmation or elevated approval mode.
- Optional plugins (not core deps): dayflow search/personalization, omaseal secrets, harness.json app catalog.

### R4 — Code & autonomous agents via ori opencode

- "Dim, agent — <task>" spawns a persistent named agent backed by `ori opencode` (all OpenRouter).
- Agents are inspectable through widgets (status, progress), checkable later by voice, and cancellable.
- `ori code --prompt` headless is the default spawn mode; interactive TUI optional.

### R5 — Widget framework + top-bar icon

- Standalone widget framework (repo-owned; gtk-layer-shell or equivalent — implementation detail for ce-plan).
- Center top-bar icon as the persistent presence surface.
- Spawnable widgets: listening/recording, transcript, decision/status, confirmation choices, agent progress, completion/error.
- Existing dim overlay becomes one widget in the framework, not the whole UI.
- Rowboat Personal bridge is deferred; the framework must not be coupled to Rowboat.

### R6 — Text-first output, optional espeak

- Assistant responses render as text widgets by default.
- Optional local `espeak` (or piper) spoken replies behind a config flag — never a hard dependency.

### R7 — Week-by-week learning loop (RL cadence)

- Corrections lane (existing `corrections.jsonl`) closes automatically: user picks a correction → recorded → applied to future decisions.
- Weekly cadence: aggregated corrections/feedback tune Jev's criteria/harness each week (evolving `propose_criteria.py` into an automated weekly improvement pass — the "RL week by week" requirement).
- Harness/catalog stays local (`~/.config/dim-agent/`), never committed.

### R8 — Generic, shippable app

- No hard dependency on dayflow, Rowboat, or Luke-specific paths.
- Dayflow mining becomes an optional plugin behind the same enrichment interface the generic path uses.
- Public repo hygiene: no secrets, no personal data, no machine-specific binds committed.

## Success Criteria

- Press `Super+D`, say "open discord" / "agent, fix the tests in dim-agent" / "what can I say?" — each routes correctly: launch / spawned `ori opencode` agent visible in a widget / conversational text answer.
- Correct-but-low-action-confidence launches (the "retro-large" failure) execute instead of cancelling.
- A named agent spawn survives the trigger, reports progress in a widget, and can be cancelled.
- Corrections made through the choice widget measurably improve next week's routing decisions.
- App runs on a fresh Omarchy install without dayflow, Rowboat, or personal config.

## Out of Scope

- Wake-word / always-on listening ("Hey Dim") — push-to-talk only this round.
- Clicky-style pixel-level GUI clicking — toolbelt covers type/window/shell actions only.
- Rowboat Personal UI integration — standalone framework now, bridge later.
- Rich TTS (ElevenLabs/piper-quality voices) — espeak optional only.
- Continuous screen streaming — explicit capture only.

## Key Decisions (from dialogue)

| Decision | Choice | Rejected | Why |
|---|---|---|---|
| UI home | Standalone widget framework now | Rowboat Personal surface | Works with Rowboat closed; bridge later |
| Code agent path | `ori opencode` | per-agent CLIs (devin/claude/codex) | All OpenRouter, one auth path |
| Daemon model | Resident daemon | spawn-per-trigger | Assistant feel: session + task + agent state |
| App catalog | Generic + optional plugins | dayflow-only mining | Public app, not Luke-specific |
| Voice out | Text-first, espeak optional | full TTS | Speed to ship; espeak is free |
| Feedback loop | Weekly RL-style cadence | manual propose_criteria run | Compounding improvement without manual steps |

## Open Questions (for ce-plan)

- Widget toolkit: extend gtk-layer-shell overlay vs. quickshell vs. other — implementation trade-off.
- Daemon↔widget IPC mechanism.
- How `ori opencode` headless output maps into widget progress updates.
- Whisper model bump (base.en → small.en) as part of this build or follow-up.
- Whether the corrections lane auto-tunes Jev criteria in-place or stages proposals for review.
