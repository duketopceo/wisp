---
title: "feat: Branch consolidation + local GPU actor loop"
type: feat
date: 2026-10-03
origin: docs/brainstorms/2026-10-02-training-gauntlet-research.md
status: "superseded by 2026-10-04-0100-feat-wisp-unified-plan.md"
---

# feat: Branch consolidation + local GPU actor loop

## Summary

Two scoped phases. **Phase A** lands the five divergent branches that all
forked from `aa4194a` (pre-clicklab) — including the working-tree deltas
on `feat/training-arena`. **Phase C** makes the local GPU servers
first-class actor options: a UI-TARS action-text parser for the act loop
and a model-matrix runner so the arena produces per-model
pass-rate/latency/cost comparisons instead of vibes.

## Problem Frame

Six branches now touch overlapping files (`wisp/act.py`,
`wisp/tools/system.py`, `wisp/pipeline.py`, `scripts/clicklab/`). The
remote branches (`shadow-decider`, `be-u1-spans`, `wisp-u9-u18`,
`docs/redesign-spec-plan`, `wisp-u1-theme`) were all cut from `aa4194a`
— one commit *before* clicklab merged to master — so a naive merge of
each deletes ~900 lines of arena work. Every day they sit unmerged the
rebase gets worse.

Meanwhile the local inference stack is live and wired
(`llama-local` Ornith-35B :8080, `llama-jev` qwen3-4b :8091 via
jev-shim :8931, `llama-uitars` UI-TARS-7B :8081, Ollama CPU :11434), but
the act loop cannot use UI-TARS because it emits literal action text
(`click(x,y)`) rather than OpenAI tool_calls — and we have no harness
to compare actors on equal footing.

## Requirements

From origin `docs/brainstorms/2026-10-02-training-gauntlet-research.md`
and the roadmap:

- R1: Outstanding work consolidates to master without losing clicklab /
  training-arena code; every mergeable branch gets a PR.
- R2: The act loop can drive a non-tool-call GUI model (UI-TARS) through
  the same toolbelt and safety tiers as a native tool-calling model.
- R3: `run.py` can run the same suite + seed across multiple actor
  models, recording model/provider/latency/cost per run, so the bank and
  arena page can compare them.
- R4: Local GPU servers are expressible as `[brain.*]` providers — no
  hard-coded endpoints; config, not code, selects the actor.
- R5: No claim of model quality from compile/self-report — ground-truth
  (`window.__score`) verification stays authoritative.

## Scope Boundaries

In scope: merge mechanics, UI-TARS parser, model-matrix flags, per-model
record fields, provider config docs.

Deferred to follow-up work:

- Reviewer-tier batch pass (counterfactuals, first-fault, skill
  extraction) — gauntlet v2 plan.
- Pass^k aggregation, oracle step-counts, flake taxonomy — gauntlet v2.
- Desktop-surface arena suite (real-pixel / Hyprland targets).
- Ember GUI unit implementation (lands via `wisp-u9-u18` merge; building
  new UI is out of scope here).
- Weight-level fine-tuning — explicitly out of the behavior-loop design.

## Key Technical Decisions

- **KTD1: Rebase-then-merge, telemetry first.** `be-u1-spans` merges
  first because the matrix runner needs turn spans for latency; then
  `shadow-decider` (its `test_shadow.py` is additive); then
  `wisp-u9-u18` (QML-side, fewer Python overlaps); docs branch anytime.
  Each remote branch rebases onto master, resolving the clicklab
  deletions by keeping master's versions where the branch predates the
  files.
- **KTD2: Parser shim in the act loop, not a new provider kind.**
  UI-TARS is served by llama.cpp's OpenAI-compatible endpoint — a
  `brain` provider with `tools=false`. The gap is *response format*:
  the model answers with action lines, not `tool_calls`. The act loop
  gains a text-action fallback parser (`_parse_action_text`) that runs
  only when a reply has no tool_calls and the provider is flagged
  `action_text=true` in config. The parser emits the same dispatch the
  native path uses — interactive tier, denylist, and confirmations apply
  unchanged.
- **KTD3: Model selection via CLI flag + provider presets, not config
  edits.** `run.py --models "openrouter:google/gemini-3.1-flash-lite,openai_compat:uitars"` overrides `cfg["brain"]["default"]` per run;
  `[brain.uitars]` and `[brain.llama_local]` presets ship in
  `DEFAULT_CONFIG` (commented) so the flag works out of the box.
- **KTD4: Per-model bucketing is additive.** Trajectory/clicklab records
  gain `model` + `provider` fields; `train.py` bank keys gain an
  optional model dimension (`surface|app|task|model` when a model is
  set) so hints stay per-actor rather than cross-contaminating.

## High-Level Technical Design

```mermaid
flowchart LR
    subgraph Phase A — consolidation
        WT[working tree: watchdog,<br/>dom-gate, JEV_ENDPOINT] --> TA[feat/training-arena<br/>3 commits]
        TA --> M[master]
        BE[be-u1-spans] --> M
        SD[shadow-decider] --> M
        U9[wisp-u9-u18] --> M
        DP[docs/redesign-spec-plan] --> M
    end
    subgraph Phase C — local actor
        UIT[llama-uitars :8081<br/>UI-TARS-7B] --> P[action-text<br/>parser]
        P --> AL[run_act_loop<br/>toolbelt + tiers]
        MX[--models a,b,c] --> AL
        AL --> REC[clicklab.jsonl<br/>+ model/provider/latency]
        REC --> BANK[train.py bank<br/>per-model keys]
        REC --> AR[arena page<br/>model filter]
    end
```

## Implementation Units

### U1. Land pending training-arena deltas

**Goal:** Commit the three uncommitted working-tree changes as one
focused commit and push the branch.

**Requirements:** R1

**Dependencies:** none

**Files:**
- `shell-plugin/Companion.qml` (compress watchdog — already written,
  linted, deployed)
- `scripts/clicklab/run.py` (DOM-mode skips `focus_browseros`)
- `wisp/config.py` (`WISP_JEV_ENDPOINT` env override)

**Approach:** One commit — all three changes serve "arena + companion
stability." Push `feat/training-arena` to origin; open a PR covering the
3 unpushed commits (`25ca51c`, `fabee87`, `d80b8d2`) plus this one.

**Test expectation:** none — behavior already verified live (button
commands exit-0, qmllint clean, DOM hammer runs hands-off).

**Verification:** `git log origin/master..HEAD` shows the four commits;
PR opened.

### U2. Rebase-and-merge remote branches

**Goal:** `be-u1-spans`, `shadow-decider`, `wisp-u9-u18`, and
`docs/redesign-spec-plan` land on master in dependency order without
resurrecting pre-clicklab deletions.

**Requirements:** R1

**Dependencies:** U1 (arena must be on master first — every remote
branch conflicts with it).

**Files:**
- `wisp/telemetry.py`, `wisp/trace.py`, `wispd` (be-u1-spans)
- `wisp/pipeline.py`, `wisp/config.py`, `tests/test_shadow.py`
  (shadow-decider)
- `shell-plugin/*.qml`, asset dirs (wisp-u9-u18)
- `docs/` (redesign-spec-plan)

**Approach:** For each branch: `git rebase master`. On conflicts in
`scripts/clicklab/`, `wisp/tools/system.py`, `wisp/act.py`,
`wisp/points.py` — the branch's base predates those files' current
form; keep master's version and re-apply the branch's semantic change on
top (e.g., shadow logging hooks into the *current* `run_listen`, spans
into the *current* `trace.py`). Never take the branch's deletion of
clicklab files. Order: `be-u1-spans` → `shadow-decider` →
`wisp-u9-u18` → `docs/redesign-spec-plan`. `wisp-u1-theme` is a strict
subset of `wisp-u9-u18` — close it when u9-u18 lands.

**Test scenarios:**
- After each rebase, the full pytest suite passes (the pre-existing
  `test_platform.py` macOS-env flake is the only allowed failure).
- `wispd status` still returns ok after each merge — smoke the IPC.
- shadow-decider post-merge: `test_shadow.py` passes against the
  current pipeline (its `run_listen` hooks may need re-pointing — that
  is the expected rebase work).

**Verification:** `git log origin/master..<branch>` empty for all four;
`wispd` still runs on this machine after reinstall.

### U3. UI-TARS action-text parser in the act loop

**Goal:** A provider configured `action_text=true` can drive the full
toolbelt — UI-TARS's `click(x,y)`/`type("...")`/`scroll`/`DONE` lines
dispatch through the same safety tiers as native tool_calls.

**Requirements:** R2, R5

**Dependencies:** U2 (the rebase reshapes `act.py` — parse on top of
the merged version).

**Files:**
- `wisp/act.py` — add `_parse_action_text` + fallback branch in
  `run_act_loop` when `msg` has no tool_calls and provider flag set
- `wisp/brain.py` — read `action_text` provider flag (default false)
- `wisp/config.py` — commented `[brain.uitars]` preset in
  `DEFAULT_CONFIG`
- `tests/test_act.py` — new parser + loop tests

**Approach:** UI-TARS emits a small grammar per reply:
`Action: click(x, y)`, `type("text")`, `scroll(dx, dy)`,
`hotkey("ctrl","c")`, `wait()`, `DONE`, `FAIL(reason)`. The parser maps
these onto the existing toolbelt names (`click`, `type_text`, `scroll`,
`key`) using the same arg-normalization as `_parse_xy`. Tool results are
fed back to the model as the next user message text (the "CLICKED <id>"
echo style already in the loop) instead of `tool` role messages. Loop
ends on `DONE`, step cap, or unparseable reply ×2.

**Execution note:** Implement the parser test-first against captured
UI-TARS output strings.

**Test scenarios:**
- `click(123, 456)` → dispatches `click` tool with x=123, y=456.
- `type("hello world")` → `type_text`; quoted strings with parens/commas
  parse correctly.
- `DONE` and bare `DONE` mid-text both end the loop with done status.
- Unparseable reply → counts toward the 2-strike bail; loop returns
  stalled, not crashed.
- `Action: click` with no coords → parse miss, not a bogus (0,0) click.
- Denylist still applies: `type("rm -rf /")` refuses via the interactive
  tier's text guard.
- Provider without `action_text` flag and no tool_calls → unchanged
  existing behavior (no parser involvement).
- Integration: with a stubbed brain returning a canned action transcript,
  `run_act_loop` executes 3 tool calls and returns done.

**Verification:** `llama-uitars` can complete a clicklab core task via
`run.py --dom --models openai_compat:uitars` — verified by
`window.__score`, not the model's claim.

### U4. Model-matrix runner + per-model records

**Goal:** One command runs a suite across N actor models; every record
carries model/provider/latency/cost so the arena can compare actors.

**Requirements:** R3, R5

**Dependencies:** U3 (so the local models are runnable), U2
(`be-u1-spans` provides per-turn latency; if it slips, wall-clock timing
per run suffices for v1).

**Files:**
- `scripts/clicklab/run.py` — `--models` flag, per-model run loop,
  record fields
- `wisp/train.py` — record/bank keys gain optional model dimension;
  `stats` output groups by model
- `scripts/clicklab/arena.html` + `arena.py` — model column/filter
- `tests/test_train.py` — model-keyed bank entries don't collide with
  unkeyed ones

**Approach:** `--models` is a comma list of `provider:model` strings
applied per run by setting `cfg["brain"]["default"]` before
`run_act_loop`. Each run record gains `model`, `provider`, `latency_ms`
(sum of model-call wall time, or turn-span sum when U2's spans land),
and `cost_usd` (looked up from a small `MODEL_PRICES` table for known
OpenRouter slugs; local models record `0` + `provider=local` — the
point is comparison, not invoice precision). Bank keys become
`surface|app|task|model` when the run carried a model flag; `hint_for`
falls back to the unkeyed entry so manual runs still benefit.

**Test scenarios:**
- `--models a,b` runs the suite twice, records carry `model=a` then
  `model=b`.
- Bank keys with model don't collide with unkeyed entries for the same
  `surface|app|task`.
- `stats` output shows a per-model grouping row.
- Unknown model flag → clear error listing valid `provider:model`
  format, no partial suite run.
- `hint_for` prefers the model-keyed graduated entry and falls back to
  unkeyed.

**Verification:** `--models` with two entries produces paired rows in
`clicklab.jsonl`; arena page shows a model filter with both values.

### U5. Local-provider presets and config docs

**Goal:** `[brain.uitars]`, `[brain.llama_local]`, and the jev-shim
env override are documented presets in `DEFAULT_CONFIG` and README so
the matrix flag works without hand-editing config.toml.

**Requirements:** R4

**Dependencies:** U3

**Files:**
- `wisp/config.py` — `DEFAULT_CONFIG` additions (commented blocks)
- `README.md` — local-model section: launcher → provider → `--models`
  string mapping
- `docs/INSTALL.md` — note the optional local-brain path

**Approach:** Ship commented presets matching the live systemd services:
`[brain.uitars]` base_url `http://127.0.0.1:8081`, `vision=true`,
`tools=false`, `action_text=true`; `[brain.llama_local]` base_url
`http://127.0.0.1:8080`, `vision=true`, `tools=true`. Document
`WISP_JEV_ENDPOINT` (already in code) beside it.

**Test scenarios:**
- `test_config.py`-adjacent: commented preset parses when uncommented —
  a doc-only config template test asserting the preset blocks exist and
  produce a valid provider dict when activated.

**Verification:** A fresh config.toml + uncommented preset + running
`llama-uitars` lets `run.py --dom --models openai_compat:uitars` start a
run with no other edits.

## Risks & Dependencies

- **Merge-risk (U2):** The remote branches delete files master added —
  a mechanical `ours`/`theirs` pick will lose real work. Mitigation:
  rebase each, treat clicklab-file deletions as "take master's," run the
  suite after every rebase, not just at the end.
- **UI-TARS grounding quality unknown:** The parser makes it *runnable*,
  not *good* — the matrix run (U4) is where we learn whether its DOM
  grounding beats Gemini's. Expect first-fault findings, not immediate
  graduation.
- **Ornith's 75s vision turn** makes it unviable as the hot-loop actor;
  it stays a decider/reviewer candidate. Plan assumes it is never
  offered to `--models` for the act loop without a measured reason.
- **Service uptime:** `llama-*` units are systemd-enabled but cold —
  matrix runs should health-check the port and skip with a clear
  message, not fail mid-suite.

## Deferred Implementation Notes

- Exact action-grammar edge cases (multiline `type` payloads,
  `hotkey` arg order) — resolve against live UI-TARS output during U3.
- Turn-span integration for `latency_ms` — depends on how
  `be-u1-spans` names its fields after rebase.
- Whether `cost_usd` belongs per-step or per-run — per-run is planned;
  per-step export can follow if the reviewer tier needs it.
