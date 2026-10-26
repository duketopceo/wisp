# Roadmap

Where wisp stands and what happens next. The plan of record is
`docs/plans/2026-10-25-1625-feat-wisp-heyclicky-linux-roadmap-plan.md`;
the top-level `ROADMAP.md` lists its phases. `docs/research/heyclicky-features.md`
and `docs/research/2026-10-25-*.md` hold the competitor and state research
it builds on.

## Shipped (current master)

- **Conversational act loop** — tools + follow-ups + goal memory;
  `router = "act"` skips the Jev decision hop (route ~480ms → ~25ms)
- **Real-app launch** — every installed `.desktop` app launchable by
  normalized spoken name (incl. all 12 `ai.storyteller.*` Craft debug
  builds); `mimeapps.list` defaults resolve role words; running apps
  focus instead of re-spawning
- **Debug spine** — `trace.jsonl`: spans per stage, `screen_capture`
  (img_kb, qa_skip), `shot_normalize`, `shot_compress`, `llm_call`
  (img_kb/tools_out/ms), `tool_call`/`tool_result`, `ground(_refused)`
- **Fast shots** — logical-px normalize + grid overlay, JPEG q85
  transport (~10x payload cut), Q&A turns skip the shot entirely
- **Safety** — risk-tier gating, denylist preempt (keyring prompts
  refused mid-drill), real-input instant takeover
- **Surface** — bar pill top-center (own spot), ghost cursor, beacons,
  ACTED replies spoken

## In flight

- **HeyClicky delta units H1–H9 (merged as #124)**: most landed as
  libraries without a production caller. The roadmap plan wires the
  walkthrough, drawing and suggestion pieces (Phase 7) and deleted the
  unused per-conversation grants and talk/deep lanes modules.

## Next — the Craft-app proving ground

The `ai.storyteller.*` suite (FilmCraft, CADCraft, DeckCraft, …) is the
training arena: local debug builds, deterministic UIs, no user data.

1. **Drill harness** — bounded tasks per app (`open → dismiss modal →
   expand bin → scrub`), each scored pass/fail by observable state, not
   vibes.
2. **Control-channel verifier** — FilmCraft already exposes a JSON-lines
   `--control` server with automation ids and `ui.screenshot`. Wire it
   as ground truth for "did the action land" — a signal HeyClicky can't
   get from outside an app. Same pattern to the other craft apps.
3. **Aim accuracy** — first live click missed by ~70px. Iterate:
   grounding two-stage (H3) + verify-by-control + trajectory replay
   until click/scroll/type are reliably good.
4. **Drawn annotations** — the #124 walkthrough overlay is the teaching
   UX gap vs HeyClicky (they draw on the real UI; we beacon).

## Then

- **CUA session auto-recovery** — detect empty `list_windows`/epoch
  mismatch, re-handshake without a manual restart
- **Per-app memory** — save learned behavior by app (`cadcraft` knows
  its shortcuts; browser knows its tabs) — H4 groundwork
- **Trajectory → training** — decisions/trajectories/trace are the
  corpus; the loop is run → score → correct → rerun, not longer soaks
- **App preference policy** — installed ≠ preferred (firefox installed
  but unused); a blocklist or preference weight so defaults always win

## Not doing

- No slow decision-model hops on the hot path — speed comes from
  skipping stages, not adding them
- No arbitrary exec on unknown nouns — unknown stays SKIP
- No blanket confirm prompts — risk tiers and boundaries, or it's a
  router not an agent
