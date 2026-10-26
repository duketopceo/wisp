---
title: HeyClicky-for-Linux Phase 2 — agent substrate salvage plan
type: feat
date: 2026-10-26
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
parent_plan: docs/plans/2026-10-25-1625-feat-wisp-heyclicky-linux-roadmap-plan.md
phase: 2
---

# HeyClicky-for-Linux Phase 2 — agent substrate salvage plan

## Goal Capsule

- **Objective:** Land the closed PR #138 **Phase A** agent substrate (U1–U4 from `docs/plans/2026-10-25-0215-feat-clicky-clacky-delta-plan.md`) on top of Phase 1 (#139): IPC read/mutate split for spawned agents, exit-code and deliverable truth, routines that actually run, and voice-taught routine creation — satisfying roadmap **R14** without widening to organize/tour/draw (Phase 7–8).
- **Means:** Cherry-pick the four substrate commits plus review/CI fixups from `origin/feat/agent-substrate-phase-a` onto a branch based on `feat/local-models-opt-in` (KTD4 in the roadmap plan). Do **not** merge the full #138 branch (30+ commits of capture-pack overlap with master).
- **Authority:** Roadmap plan (`docs/plans/2026-10-25-1625-feat-wisp-heyclicky-linux-roadmap-plan.md`) Phase 2 row; delta plan U1–U4 for unit detail; `docs/research/2026-10-25-agent-native.md` for trust-boundary rationale.
- **Execution profile:** One implementation PR after this plan; full Python suite green; `tests/fixtures/ipc_commands.jsonl` lines unchanged (KTD5 / frozen `rs/`).
- **Stop conditions:** Stop if cherry-picks require re-introducing `wisp/lanes.py` or `wisp/conversation_grants.py` (deleted in Phase 1); stop if marked-peer authz would change an existing parity fixture response; stop if a unit needs live synthetic clicks (see omarchy-max section).
- **Who finishes:** Follow-up implementation PR; this document is planning only.

---

## Product Contract

### Summary

Phase 2 closes the agent honesty and trust gaps documented in the agent-native audit: background tasks report **truthful** outcomes, spawned runtimes cannot self-approve or mutate Wisp over IPC, and scheduled or voice-taught routines reach `RoutineStore` and systemd user timers end-to-end. HeyClicky pointing, tour, and draw layers stay Phase 7; spawn env scrub and skills export stay Phase 8.

### Problem Frame

Today (`feat/local-models-opt-in`), `wisp/routines.py` is library code with no production caller; generated systemd units reference `wispd agents run <id>`, which does not exist; `task_finished` carries status/tail only (no exit code or deliverable check); and any same-uid process can send mutating IPC (`choice`, `config set`, recursive `agent`). Phase 1 made **act** the default router and removed unused grant/lane modules — the right base, but agents remain unsafe and routines remain dead.

### Requirements (Phase 2 scope)

- **P2-R1 (delta R2):** IPC commands classify read vs mutating; spawned agent subtrees (systemd scope + registry-verified marker) get read-class only; local `connect` OAuth refuses marked peers; safety-lowering `config set` keys refuse marked peers.
- **P2-R2 (delta R1):** Reaper records exit codes; `done` requires exit 0; declared `delivers[]` verified under `tasks/<id>/out/` at reap; notifications state facts, not model claims; `task output` / `task artifacts` IPC and CLI reads.
- **P2-R3 (delta R3):** `wispd agents run <routine-id>` and `wispd task run --routine <id>` spawn with `routine_id`; daemon-down fallback + reconcile; `record_routine_outcome` on finish; unread UI in AgentsTab; 3-failure auto-pause.
- **P2-R4 (delta R4):** Voice teach path (`parse_teach_intent` + T2 confirm + first-run opt-in) wired in `stage_execute.py` without requiring Jev on the default path.

### Success Criteria

- `python3 -m unittest discover -s tests` green (baseline ~2298+ on Phase 1 branch).
- Named test files from #138 pass: `tests/test_ipc_authz.py`, `tests/test_task_delivery.py`, `tests/test_routines_wire.py`, extended `tests/test_agents_reaper.py`.
- `wispd doctor` / onboard unchanged for OpenRouter-only configs (no new mandatory local services).
- Rust parity job still passes without editing `tests/fixtures/ipc_commands.jsonl` replay lines.

### Scope Boundaries

**In scope:** Cherry-pick U1–U4 + `fabe497` review fixes; Linux-focused test hygiene (see U0); `docs/IPC_CONTRACT.md`, CLI help goldens, QML unread dot.

**Explicit non-goals (later phases):**

- Phase 3: Windows/macOS purge — drop macOS-only test scaffolding added for #138 CI where it does not protect Linux correctness.
- Phase 4–5: Training/eval purge and Jev router removal — Phase 2 does **not** assume a winning OpenRouter decider model (see #136 section).
- Phase 7: HeyClicky core (walkthrough, draw, tour, label-first snap in production voice path).
- Phase 8: Spawn env scrub, CONNECT handshake, skills export (delta U5–U7).
- Re-enabling **cua-driver** or relying on **ydotoold** on omarchy-max (owner-disabled / broken).
- Merging full #138 or rebasing capture-pack stacks.

**Considered, not in Phase 2:** Full delta-plan doc rewrite for CodeRabbit #139 comments (mostly Phase 7–8 content); `rs/wispd` parity for new IPC cmds (frozen — new cmds are Python-only until explicitly scheduled).

### Outstanding Questions

- **Q-P2-1:** Should marked peers retain read access to `captures` / `context` (screenshots), or restrict in a follow-up hardening PR? Default for Phase 2: **accept read-class as in #138**; document residual in IPC_CONTRACT (delta plan OQ8).
- **Q-P2-2:** Require `delivers` on every `agent_spawn`, or keep opt-in honesty? Default: **opt-in** (delta plan OQ9).
- **Q-P2-3:** Voice teach when transcript is ambiguous — clarify card only, no partial persist (already #138 behavior).

### Sources

- `docs/plans/2026-10-25-1625-feat-wisp-heyclicky-linux-roadmap-plan.md` — Phase 2 definition, KTD4–KTD5.
- `docs/plans/2026-10-25-0215-feat-clicky-clacky-delta-plan.md` — U1–U4 specs (paraphrased; Clacky/HeyClicky prompts not copied verbatim).
- `docs/research/2026-10-25-agent-native.md` — IPC trust evidence.
- `docs/research/2026-10-25-wisp-state.md` — pre-Phase-1 wiring audit (H5 routines dead).
- Closed PR #138 / branch `feat/agent-substrate-phase-a` — implementation reference (AGPL-3.0 wisp repo; Clacky reference is MIT, mechanics only).
- PR #139 — Phase 1 base branch.
- PR #136 — OpenRouter decider latency eval (shadow + replay + opt-in flash lane).

---

## Dependency on PR #139 (Phase 1)

Phase 2 implementation should branch from **`feat/local-models-opt-in`** (#139) and merge after #139, or stack on #139 until master absorbs Phase 1.

| Phase 2 unit | Depends on #139 change | Why |
|---|---|---|
| U1 IPC authz | Stable `wisp/ipc.py` / `wispd` dispatch; no `conversation_grants` | Grants module removed; authz is cgroup/marked-peer based |
| U2 Task truth | Default `router = act` | Background spawns and routines use act-capable config; no Jev requirement for routine CLI |
| U3 Routines wire | Linux-only roadmap, systemd timers | Units assume user systemd; Omarchy/Hyprland target |
| U4 Voice teach | `stage_execute` act-first path | Teach hook runs on transcript pattern before act loop; default router act does not block teach |
| Tests | Harness pins `router=jev` only for Jev fixtures | Phase 2 tests must not assume Jev default |
| Docs | Research docs on branch | Phase 2 cites agent-native audit already on #139 |

**#139 review state (verified 2026-10-26):** `CHANGES_REQUESTED` from **CodeRabbit** (15 actionable items, mostly **documentation** in `docs/plans/2026-10-25-0215-feat-clicky-clacky-delta-plan.md` and research files — task_finished shape, per-app context injection, organize provider boundary, pytest vs unittest wording, stale `conversation_grants` reference, etc.). **Applied on branch head `597b2a5`:** `install_units(local=False)` default, settings hint "act loop", **`local.enabled` boolean schema validation**. **Argus:** approve (one nit on act vs agent loop wording — fixed). **Cursor automation:** approve. **Codex:** review failed (usage limit, not product findings). **Owner-noted risks still open on #139:** silent upgrade when `[local]` absent; `[ground] providers = "uitars"` with local off → empty grounding chain (untraced); thin default-`act` replay coverage.

**Assumptions that #139 review could invalidate:**

- If #139 adds **`health.endpoints()` gating on `local_enabled()`** before merge, Phase 2 re-verify onboard/doctor goldens only (no substrate conflict).
- If #139 edits **`stage_execute` / routing** for act regressions, re-run U4 teach-path tests after rebase.
- If #139 restores or replaces deleted modules, drop conflicting cherry-picks.

**Re-verify after #139 merges or materially changes:**

1. `git merge-tree` / rebase cherry-picks onto new master head.
2. Full unittest suite + new Phase 2 test files.
3. `tests/test_turn_replay.py` — still pins Jev only where needed.
4. `scripts/assets/gen_settings.py --check` if IPC or schema touched.
5. Rust `parity.rs` job — no changes to existing `ipc_commands.jsonl` lines.

---

## Interaction with PR #136 (decision-model latency eval)

The repo is evaluating OpenRouter **decision** models (`perplexity/pplx-decider-v1.2`, `perplexity/pplx-decider-flash-v1.2`, `typesafe/jev-1.13`) against **`[jev] deadline_ms` (~400 ms)** via shadow + `wispd eval route --replay --decisions` (#136). Published benchmarks on synthetic data: flash **p95 ~280 ms**, v1.2 **p95 ~410 ms**; **real-data replay on owner logs pending**.

**Phase 2 must not assume:**

- That Jev or any decider remains on the default path (Phase 1 default is **act**; Phase 5 removes Jev).
- That flash decider wins the latency budget or ships enabled (`flash_decider` default **false** per `docs/CONFIG.md`).
- That voice-taught routines or routine CLI go through a decision model (they use transcript parsing + confirm broker).

**Stay behind config / explicit opt-in:**

- All decider models, flash lane, shadow providers, replay tooling — unchanged by Phase 2 except incidental merge conflict resolution in shared files (`wisp/route.py` touch in U4 is unrelated to decider selection).
- Any future "route teach intent via Jev" idea stays **off** unless added in a routing phase with fixtures.

**Proceed regardless of #136 outcome:**

- IPC authz, exit/deliverable truth, and routine wiring are **orthogonal** to which decider wins; they harden agents under **act-default** production.
- If #136 merges first, rebase Phase 2 on master and run `tests/test_evalroute_decisions.py` / route tests; if Phase 2 lands first, same with no decider dependency.

---

## omarchy-max click restoration (Linux dev box)

Owner state: **ydotoold failed**; **cua-driver disabled** and not desired for now. Phase 2 **must not** depend on synthetic clicks via ydotool or cua-driver for implementation or acceptance.

### Can build and verify without a working click backend

| Area | Work | Verification |
|---|---|---|
| U1 IPC authz | `wisp/ipc.py`, `wispd`, `wisp/mcpauth.py` | `tests/test_ipc_authz.py` — Unix socket + mocked peers; no pointer |
| U2 Task truth | `wisp/agents.py`, reaper, `_agent_done` | `tests/test_task_delivery.py`, `tests/test_agents_reaper.py` — stub spawn, temp `out/` |
| U3 Routines | CLI, `RoutineStore`, systemd unit text, QML unread | `tests/test_routines_wire.py` — stub spawn; unit file string asserts |
| U4 Voice teach | `routines.parse_teach_intent`, `teach_routine`, `stage_execute` hook | Parser/broker tests with fake confirm; no GUI click |
| Config / doctor | No new pointer backends | Existing fakes in harness (`tests/harness/runner.py` PATH fakes) |

Use **guide** pointer mode (`[pointer] backend = none` / guide) for manual smoke: voice teach + routine timer can be validated without injected clicks.

### Blocked until click backend returns

- End-to-end act turns that **require** injected clicks on omarchy-max (walkthrough advance, act quality — Phase 9).
- Live verification ladder steps that depend on cua recording for **click** mutations (Phase 1 capture/verify stack — out of Phase 2 scope).
- Manual v1 gate counting **correct pointing clicks** on real apps.

### Future click-backend decision (out of Phase 2 scope)

Document needs before re-enabling automation: choose among fixing **ydotool** stack, **hyprcursor**-only paths, or a new backend — with **explicit owner opt-in** in `[pointer] backend`; do **not** recommend re-enabling cua-driver in this plan. Phase 7 label-first snap may use **control/a11y** and overlay/guide without synthetic click for many answer-only flows.

---

## Planning Contract

### Key Technical Decisions

- **KTD-P2-1 — Cherry-pick, not merge #138** (roadmap KTD4): Take `b35bc91` (U1), `153e098` (U2), `187d896` (U3), `dd19911` (U4), `fabe497` (review), and **selective** hunks from `6fdee38` (spawn timestamp + deliverable path normalization — keep; macOS-only test branches — drop or gate for Phase 3).
- **KTD-P2-2 — Frozen Rust parity** (roadmap KTD5): New IPC commands documented in `IPC_CONTRACT.md`; do not append new lines to `ipc_commands.jsonl` unless rs parity is explicitly updated (default: no rs change).
- **KTD-P2-3 — systemd scope marking** (delta U1): Primary marked-peer detection via user scope; env/ppid fallback documented as weaker; Linux-only.
- **KTD-P2-4 — Teach path without Jev** (delta U4): Regex/intent parser on transcript in `stage_execute` before act dispatch; schedules via conservative parser + clarify card.

### Phased delivery (this PR only)

Single PR implementing U0–U4 below; no Phase B/C delta units.

---

## Implementation Units

### U0. Cherry-pick integration and Linux test hygiene

- **Goal:** Apply substrate commits onto Phase 1 base with minimal conflict surface.
- **Dependencies:** #139 branch available (merged or stacked).
- **Files:** All touched files from listed commits; expect conflicts in `tests/golden/cli_help/*`, `wisp/agents.py`, `wispd`, shell QML.
- **Approach:**
  1. `git cherry-pick b35bc91 153e098 187d896 dd19911 fabe497` (order preserved).
  2. Manually port non-macOS fixes from `6fdee38` (`agents.py` spawn ts ordering, deliverable path check) without macOS-only skip paths if Phase 3 has not run.
  3. Confirm `tests/fixtures/ipc_commands.jsonl` diff is empty.
  4. Regenerate help goldens if CLI surface changed.
- **Test scenarios:** Full suite green; rust CI job green.
- **Verification:** `python3 -m unittest discover -s tests`.

### U1. IPC read/mutate split + marked-peer refusal

- **Goal:** Spawned agent subtrees cannot mutate daemon state over IPC.
- **Requirements:** P2-R1.
- **Dependencies:** U0.
- **Files:** `wisp/ipc.py`, `wisp/agents.py` (scope spawn), `wisp/mcpauth.py`, `wispd`, `docs/IPC_CONTRACT.md`, `tests/test_ipc_authz.py`.
- **Approach:** As delta plan U1 — `READ_CMDS` vs mutating; deny-by-default; spoofed marker refusal; `connect` gated.
- **Test scenarios:** Marked vs unmarked vs spoofed peers; mutating cmd refusal; read cmd success; safety-key `config set` refusal.
- **Verification:** `tests/test_ipc_authz.py` green.

### U2. Task lifecycle truth

- **Goal:** Honest `done`/`failed` and deliverable verification.
- **Requirements:** P2-R2.
- **Dependencies:** U1.
- **Files:** `wisp/agents.py`, `wispd`, `wisp/cli/agents.py`, `docs/IPC_CONTRACT.md`, `tests/test_agents_reaper.py`, `tests/test_task_delivery.py`, help goldens for `task output` / `task artifacts`.
- **Approach:** Exit-code shim; `delivers[]` under `out_dir`; notification copy; refused IPC count in finish notice.
- **Test scenarios:** exit 0/1, missing deliverable, symlink escape, mtime window, executable guard.
- **Verification:** Named tests + reaper extensions.

### U3. Routines end-to-end

- **Goal:** Timers and CLI run routines with outcomes recorded.
- **Requirements:** P2-R3.
- **Dependencies:** U2.
- **Files:** `wisp/routines.py`, `wisp/cli/agents.py`, `wisp/cli/__init__.py`, `wispd`, `shell-plugin/components/AgentRow.qml`, `AgentsTab.qml`, `tests/test_routines_wire.py`, `tests/golden/cli_help/task_run.txt`.
- **Approach:** Implement `agents run`; `task run --routine`; daemon-down fallback; `_agent_done` → `record_routine_outcome`.
- **Test scenarios:** Daemon up/down spawn; 3 failures pause; success sets unread without toast.
- **Verification:** `tests/test_routines_wire.py`.

### U4. Voice-taught routine creation

- **Goal:** Natural language creates routines through T2 confirm.
- **Requirements:** P2-R4.
- **Dependencies:** U3.
- **Files:** `wisp/routines.py` (parser + `teach_routine`), `wisp/stage_execute.py`, `tests/test_routines_wire.py` (extended).
- **Approach:** Hook teach intent before act loop; conservative schedule parsing; first opt-in gate; ambiguous schedule → clarify, no write.
- **Test scenarios:** Valid daily/at-9am teach; ambiguous schedule; opt-in gate; non-teach utterance falls through to act (no routine write).
- **Verification:** Extended routine wire tests; no live click required.

---

## Testing Strategy

| Layer | Command / artifact | Phase 2 use |
|---|---|---|
| Unit | `tests/test_ipc_authz.py`, `tests/test_task_delivery.py`, `tests/test_routines_wire.py`, `tests/test_agents_reaper.py` | Primary gates per unit |
| Golden | `tests/golden/cli_help/task_*.txt` | Update in same diff as CLI |
| Harness | Existing fakes for cua/hyprctl/notify (`tests/harness/runner.py`) | No new live click dependency |
| Turn replay | `tests/test_turn_replay.py` | Regression only; no new Jev-default fixtures |
| Rust parity | `tests/fixtures/ipc_commands.jsonl` unchanged | CI rust job |
| Docs lint | `tests/test_docs_lint.py` | IPC_CONTRACT + CONFIG if touched |

Manual smoke (omarchy-max, optional): `wispd task run --routine <id>` with pointer in guide mode; voice teach phrase; confirm no click injector required.

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Cherry-pick conflicts with Phase 1 or #136 | U0 merge-tree first; owner resolves shared files (`wisp/agents.py`, `wisp/route.py`) |
| macOS CI edits from #138 confuse Linux-only direction | Strip macOS-only branches in U0; keep logical bugfixes from `6fdee38` |
| Marked-peer false negatives (scope escape) | Document env/ppid limitation; tests for cgroup + spoof |
| `captures` read exposes screenshots to agents | Document residual (Q-P2-1); restrict in later hardening if needed |
| Routine timers fire when daemon down | #138 fallback spawn + reconcile — test in U3 |
| Assuming decider latency test conclusions | See #136 section — no Phase 2 coupling |
| Click backend absent on omarchy-max | Unit/fake tests only; manual smoke without ydotool/cua |

---

## Rollout and Acceptance Criteria

**Rollout:** Merge Phase 2 after #139; no config migration required; existing `routines.json` empty or compatible; systemd user units regenerated on routine create.

**Acceptance:**

1. All P2-R1–R4 behaviors demonstrated by named tests.
2. Full Python unittest suite green.
3. Rust parity job green without jsonl fixture edits.
4. `docs/IPC_CONTRACT.md` documents read/mutate split and new read cmds.
5. No dependency on cua-driver/ydotool for CI or documented manual acceptance of Phase 2.

---

## Verification Contract

| Gate | Command |
|---|---|
| Phase 2 focused | `python3 -m unittest tests/test_ipc_authz.py tests/test_task_delivery.py tests/test_routines_wire.py tests/test_agents_reaper.py` |
| Full suite | `python3 -m unittest discover -s tests` |
| Settings codegen | `scripts/assets/gen_settings.py --check` (if schema touched) |
| Rust parity | CI `rust` job (local optional) |

---

## Definition of Done

- U0–U4 implemented on master (via #139 base).
- Cherry-picked authz, task truth, routine CLI, and voice teach match delta plan acceptance examples AE1–AE2 (AE3+ belong to later phases).
- #139 dependencies re-verified post-merge.
- Plan open questions Q-P2-1–Q-P2-3 either resolved in IPC_CONTRACT or explicitly deferred with owner sign-off.
