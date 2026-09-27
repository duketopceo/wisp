# Handoff — machine migration (omarchy-macbook-m1 → <host>)

Written 2026-09-19 during migration off the M1 MacBook. Branch: `feat/dim-assistant`.

## Where things stand

The 8-unit plan (`docs/plans/2026-09-18-001-feat-dim-autonomous-assistant-plan.md`)
is fully implemented: resident `dimd` daemon + Unix-socket IPC, Jev routing
v2 (launch/tool/agent/answer/clarify), risk-tiered toolbelt, `ori opencode`
named agents, Omarchy Quickshell plugin (bar icon + dim overlay + choices),
weekly human-gated learning loop, generic install. 54/54 tests pass.

## Live state on the M1 (must be redone on <host>)

- `dimd install` + `systemctl --user enable --now dimd`
- `Super+D` bind lives in `~/.config/hypr/bindings.lua` **and** the
  machine stash `~/.local/share/machine/<host>/bindings.lua` (sync-watch
  reverts ~/.config edits not in the stash)
- Plugin enabled via `omarchy shell setPluginEnabled io.github.duketopceo.dim`
  and already placed in the bar `center` layout in `~/.config/omarchy/shell.json`
- `whisper.cpp` at `~/src/whisper.cpp`; model `ggml-small.en.bin` must be
  downloaded (`bash models/download-ggml-model.sh small.en`) — the
  `for-tests-*.bin` files are stubs, not real models
- Secrets: `OPENROUTER_API_KEY` in `~/.config/dim-agent/.env`
- `harness.json` regenerates via `dimd harness` (mines dayflow if present,
  else generic .desktop/PATH catalog)

## Known issues / next tasks

1. **End-to-end voice test still pending.** Every stage verified separately
   (record → whisper small.en → Jev 200 → dispatch), but no confirmed
   real Super+D run on the new machine yet.
2. **Jev cannot emit free text** — API types are only `noul` (yes/no prob),
   `choice`, `score`. Tool/agent args come from the transcript; `answer`
   route uses canned `answer_text()`. Real generated answers need a second
   OpenRouter chat model in the loop — not implemented.
3. **QML plugin loads warning-free** after `Style.*` token fixes
   (`Style.font.title/body/bodySmall`, `Style.spacing.*`). Overlay context
   has no `Style` — uses literals.
4. Legacy GTK `dim-overlay` still in repo as fallback — delete once plugin
   is proven live.
5. `needs_screen` context not wired; screenshot exists as a tool only.
6. Branch `feat/dim-assistant` never merged — decide push/PR/merge on
   the new machine.

## v0.1-usable update (2026-09-25)

- Route set grew: `launch | tool | agent | act | answer | clarify`.
  `act` = `dim/act.py` bounded tool-call loop (<=8 steps, >2 consecutive
  failures aborts): chat model drives `tools.tool_schemas()` (derived
  from the registry), every call re-passes denylist/allow_shell/confirm
  gates — mutating calls surface as a yes/no choice via the existing IPC
  choice path, skipped when no chooser wired.
- Answer/agent default: `meta-llama/llama-4-maverick` (open-weights
  flash). No GPT-6 Astra anywhere — forbidden by user.
- `decisions.jsonl` records now carry `timing_ms`:
  record/stt/jev/act — latency is measurable per stage.
- All failures write `state.json` status=error + log to decisions.jsonl;
  UI surfaces it.
- Shell plugin overlay is now `Companion.qml` — persistent bottom-right
  orb (idle/listening/thinking/acting/error colors, breathes while
  listening), click expands a card with transcript/answer/choices.
  `DimOverlay.qml` kept in repo but no longer the entry point.
- 83/83 tests pass; daemon + plugin synced and live on <host>
  (summon returned ok, no QML errors).

### Verified live
- Jev routes "open discord and then go to workspace two" -> act (conf 1)

### Still needs a real voice run (Super+D)
- act route end-to-end with spoken phrase
- yes/no confirm flow on a mutating tool call
- orb error state on a deliberately failing route
