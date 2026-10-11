# Handoff — machine migration (omarchy-macbook-m1 → omarchy-max)

Written 2026-09-19 during migration off the M1 MacBook. Branch: `feat/dim-assistant`.

**Archived:** this note describes a September 2025 machine move. Several
"coming soon" items below shipped long ago (computer-use clicks, CUA
subsystem, Ember surfaces, bar pill). Keep this file for history only;
current residuals live in `docs/HANDOFF.md` and `ROADMAP.md`.

## Where things stood (2026-09-19)

The 8-unit plan (`docs/plans/2026-09-18-001-feat-dim-autonomous-assistant-plan.md`)
was fully implemented: resident `wispd` daemon + Unix-socket IPC, Jev routing
v2 (launch/tool/agent/answer/clarify), risk-tiered toolbelt, `ori opencode`
named agents, Omarchy Quickshell plugin (bar icon + dim overlay + choices),
weekly human-gated learning loop, generic install. 54/54 tests pass.

## Live state on the M1 (had to be redone on omarchy-max)

- `wispd install` + `systemctl --user enable --now wispd`
- `Super+D` bind lives in `~/.config/hypr/bindings.lua` **and** the
  machine stash `~/.local/share/machine/<host>/bindings.lua` (sync-watch
  reverts ~/.config edits not in the stash)
- Plugin enabled via `omarchy shell setPluginEnabled io.github.duketopceo.wisp`
  and already placed in the bar `center` layout in `~/.config/omarchy/shell.json`
- `whisper.cpp` at `~/src/whisper.cpp`; model `ggml-small.en.bin` must be
  downloaded (`bash models/download-ggml-model.sh small.en`) — the
  `for-tests-*.bin` files are stubs, not real models
- Secrets: `OPENROUTER_API_KEY` in `~/.config/wisp/.env`
- `harness.json` regenerates via `wispd harness` (mines dayflow if present,
  else generic .desktop/PATH catalog)

## Known issues / next tasks (as of 2026-09-19)

- **Point grounding**: the model mis-grounds raw pixel coords on large
  screenshots — pick a better-vision answer model via `[brain] default`
  or shrink the shot before prompting (accuracy knob, not a bug).
- **Streaming STT/TTS**: batch today; streaming voice: coming soon.
- **Literal computer-use clicks**: Wisp points but doesn't click —
  coming soon behind the risk gate.
- **File/PDF attach context**: coming soon.
- **GNOME Wayland window ops**: platform has no general window API —
  wm ops answer `SKIP` there by design, not a stub.
- **Windows workspaces**: virtual-desktop API needs COM — coming soon.
