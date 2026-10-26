---
title: Agent Substrate Salvage - Plan
type: feat
date: 2026-10-25
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
---

# Agent Substrate Salvage - Plan

## Goal Capsule

- **Objective:** Background agents and routines on master behave truthfully and safely. A spawned agent cannot change Wisp's state over IPC, a task reports failure when its process failed or its promised files are missing, and scheduled and voice-taught routines actually run.
- **Means:** Cherry-pick the agent-substrate commits from closed PR #138 onto a fresh branch from `origin/master` (KTD1), excluding everything else on that branch.
- **Authority:** Phase 2 of `docs/plans/2026-10-25-1625-feat-wisp-heyclicky-linux-roadmap-plan.md` (on PR #139); the substrate's own design is `docs/plans/2026-10-25-0215-feat-clicky-clacky-delta-plan.md` units U1–U4 (also on PR #139).
- **Execution profile:** One unit, implemented on branch `feat/agent-substrate-salvage`; the full Python suite and the Rust parity job must pass.
- **Stop conditions:** Stop and report if a commit cannot be applied without rewriting its behavior, or if the parity fixture would need changing.
- **Who finishes:** This run's PR.

---

## Product Contract

### Summary

Bring the four substrate units from #138 to master, with their review fixes and the cross-platform test hardening, as one PR.

### Problem Frame

PR #138 was closed unmerged while its base work (#133) landed as a squash, so the substrate exists only on a 30-commit branch that mostly duplicates master. Master today lets any spawned agent send mutating IPC commands, marks tasks done on process exit without checking output, and has routines with no execution path.

### Requirements

- R1. Mutating IPC commands from a process registered as a running task are refused (`marked_peer_refused`); read commands still work.
- R2. A task's outcome reflects its exit code and the presence of the deliverables it declared.
- R3. Routines execute from the CLI and from schedules, record outcomes, and pause after repeated failure.
- R4. A routine can be created by voice through the T2 confirm broker.

### Key Decisions

- **Salvage by cherry-pick, not merge.** Governs R1–R4. (session-settled: user-approved — chosen over merging the closed #138 branch: its 30 commits mostly duplicate #133 after squash.)
- **`rs/` stays frozen; `tests/fixtures/ipc_commands.jsonl` stays byte-identical to master.** (session-settled: user-directed — chosen over keeping Rust parity or deleting `rs/`.)
- **Linux only.** The macOS-portability commit is kept whole: its source change fixes deliverable checks through symlinked paths on Linux too, and its test edits (a short temp dir for AF_UNIX socket paths, a gate on SO_PEERCRED-only assertions) are harmless test robustness that Phase 3 can strip with the rest of the macOS seams. (session-settled: user-directed — chosen over keeping cross-platform seams.)

### Scope Boundaries

- Out: the capture-pack merge on #138 (`d6654c9`, already on master as #133) and the research-doc commit `72c0419` (on PR #139).
- Out: env scrub, deferred auth, organize, skills export — Phase 8.

---

## Planning Contract

### Key Technical Decisions

- KTD1. **Apply `b35bc91`, `153e098`, `187d896`, `dd19911`, `fabe497`, `6fdee38` in that order with `git cherry-pick -x`.** A `merge-tree` dry run against `origin/master` (`0a4856a`) applied all six without textual conflict. Keep each as its own commit so the history maps to delta-plan units U1–U4. Instantiates the cherry-pick Key Decision (R1–R4).
- KTD2. **Fix semantic drift in follow-up commits, not by editing the picked ones.** Help goldens, the `wispd` help line budget, and docs lint may fail because master gained `wispd note` (#135) after #138 branched; repair them in one `fix:` commit on top.

### Assumptions

- The Rust parity job replays the fixture against the frozen Rust daemon in `rs/wispd`, so the Python authz split cannot affect it while `rs/` and the fixture are unchanged; none of the six commits touch either. Authz behavior is covered by `tests/test_ipc_authz.py`, and `tests/test_contract.py` covers the Python side of the fixture.
- Overlap with PR #139 is limited to `wispd` (different hunks: IPC dispatch vs `install_files`); whichever merges second rebases cleanly.

---

## Implementation Units

### U1. Cherry-pick the agent substrate onto master

- **Goal:** Land R1–R4 on a branch from `origin/master`.
- **Requirements:** R1, R2, R3, R4; KTD1, KTD2.
- **Dependencies:** none.
- **Files:** `wisp/ipc.py`, `wisp/agents.py`, `wisp/mcpauth.py`, `wisp/routines.py`, `wisp/route.py`, `wisp/stage_execute.py`, `wisp/cli/__init__.py`, `wisp/cli/agents.py`, `wispd`, `shell-plugin/components/AgentRow.qml`, `shell-plugin/components/AgentsTab.qml`, `docs/IPC_CONTRACT.md`, `tests/test_ipc_authz.py`, `tests/test_task_delivery.py`, `tests/test_agents_reaper.py`, `tests/test_routines_wire.py`, `tests/golden/cli_help/task_artifacts.txt`, `tests/golden/cli_help/task_output.txt`, `tests/golden/cli_help/task_run.txt`.
- **Approach:**
  1. Cherry-pick the six commits in KTD1 order with `-x`.
  2. Run the full suite; repair any golden, help-budget or docs-lint drift against master in one follow-up commit (KTD2).
  3. Confirm `tests/fixtures/ipc_commands.jsonl` is unchanged.
- **Execution note:** The commits carry their own tests; this unit's proof is the full suite on the integrated tree, not new tests.
- **Test scenarios:** Test expectation: none new — the picked commits bring `tests/test_ipc_authz.py`, `tests/test_task_delivery.py`, `tests/test_agents_reaper.py` and `tests/test_routines_wire.py`, which cover R1–R4.
- **Verification:** `python3 -m unittest discover -s tests` passes; `scripts/assets/gen_settings.py --check` passes; the parity fixture is byte-identical to master.

---

## Verification Contract

| Gate | Command | Applies to |
|---|---|---|
| Python suite | `python3 -m unittest discover -s tests` | U1 |
| Generated settings | `python3 scripts/assets/gen_settings.py --check` | U1 |
| Rust parity | CI `rust` job | U1 |

---

## Definition of Done

- All six commits are on the branch, with any drift repair in one follow-up commit.
- The full suite passes and the parity fixture is unchanged.
- Nothing from `d6654c9` or `72c0419` is on the branch.
