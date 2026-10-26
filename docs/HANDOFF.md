# Handoff — current (2026-10-11)

Short checklist for someone picking up Wisp on a live Omarchy box or
continuing toward the v1.0 gate in `ROADMAP.md`. The September 2025
M1→max migration note is archived at
`docs/archive/HANDOFF-2026-09-19-migration.md`.

## Shipped since that migration (do not re-open as "coming soon")

- Resident `wispd`, IPC contract v1, push stream, `wispd <group> <verb>` CLI.
- Computer use: pointer backends, cua-driver, safety policy, grounding chain
  (`docs/CUA.md`).
- Ember surfaces: bar mark + **in-bar live pill** (replaced the corner orb and
  on-demand console, PR #109), companion overlay (listening pill, answer
  bubble, ghost cursor), four-tab Panel, confirm card, keyboard submap.
- Pipeline split: `wisp/stage_{capture,route,execute,speak}.py` (W30).
- Act tools: DOM `click`/`fill` by element id (#107), label-grounded legend +
  recipe distillation (#108), voice answers to pending prompts and spoken
  interrupt (#110).

## Machine setup (still manual)

- `python3 wispd install` then `systemctl --user enable --now wispd`
- Hold `Super+D` bind from install (or `wispd trigger start` / `stop`)
- Plugin `io.github.duketopceo.wisp` enabled in Omarchy shell layout
- Local whisper.cpp model + optional loopback brains (`wispd health`)
- Secrets in `~/.config/wisp/.env` (never committed)

## Verify on a fresh session

```sh
wispd doctor
wispd status --json
wispd trigger          # one full talk cycle without the hotkey
wispd trace show --tail 5
python3 -m unittest discover -s tests -q
```

## Genuinely open (see ROADMAP for evidence gates)

- v1.0 soak: ≥50 labelled runs per route, fresh-box install ≤10 min,
  learning loop exercised twice.
- Warm/streaming STT (W12), contract-freeze housekeeping (W31).
- Platform residuals: GNOME/KDE window ops degrade by design;
  streaming TTS remains sentence-chunked batch.
- Grounding accuracy is a model/config knob, not a missing feature.
