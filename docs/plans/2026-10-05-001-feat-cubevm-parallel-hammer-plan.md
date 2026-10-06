# feat: Parallel CubeVM training workers + arena cost correction

Created: 2026-10-05
Type: feat
Origin: continuation of `2026-10-04-1800-feat-cua-driver-and-parallel-training-plan.md` (Track B)

## Problem

Two verified facts from the last sessions:

1. **Cost shape is wrong.** The brain's paid fallback is
   `gemini-2.5-flash` ($0.30/$2.50 per Mtok) which handled ~46% of
   ledger calls at 2.3x gemma's per-call cost while scoring worse
   (89% vs 96% on core). Gemma isn't in `HOSTED_PRICES` at all, so the
   cheap/good model can't be arena-specified.
2. **Training runs serial.** `cube.py` provisions one sandbox and
   `hammer.sh` runs one suite at a time. The user wants many parallel
   CubeVM workers. `run.py --cdp` + `cdpx.py` proved the transport —
   what's missing is N-way orchestration.

## Scope

### In scope

- Correct the spend shape: priced list gains gemma; paid fallback
  moves to the cheapest adequate hosted model.
- `cube.py` multi-sandbox lifecycle (N workers, tracked, killable).
- `hammer-parallel.sh`: N CubeVM workers × suite×model matrix, each
  an isolated chromium+run.py loop, results in the shared JSONL,
  per-worker logs, shared daily-cap check before each task.
- A compact run report at the end (counts, pass rate, spend per
  model×suite) — the existing ledger already carries per-task cost.

### Out of scope / deferred

- Tier-1 site adapters (X/YouTube/Linear), Tier-2 app adapters
  (Godot/OBS), recipe auto-promotion, federation plumbing — separate
  plan; they build on recipes, not on worker count.
- `Sandbox.clone(n)` fast-provision — create+provision serially in v1;
  clone is the follow-up optimization if provisioning dominates.
- Pixel-mode training, cua-bench adoption (per origin plan).

## Requirements

- R1: every hosted model specifiable in the arena has a price entry;
  gemma-4-31b-it is usable as a `--models` spec under `orch`.
- R2: wisp's paid fallback costs ≤ $0.60/Mtok out (maverick) or is
  removed; the primary stays gemma.
- R3: `hammer-parallel.sh N` runs N independent CubeVM workers; each
  worker's tab/page state is isolated by sandbox, not by pid-claims.
- R4: the shared daily cap (`[budget] daily_usd`) is honored by every
  worker — each checks `spend_today()` before starting a task; ledger
  appends from N processes must not corrupt the file.
- R5: a per-worker sandbox failure (dead CDP, expired sandbox) fails
  that worker's current task and re-ups — it does not kill the run.
- R6: at end of run, stdout prints per-model×suite verified counts and
  total spend; `clicklab.jsonl` records carry a `worker`/`sandbox_id`
  field for attribution.

## Implementation units

### U1. Arena price correction + fallback swap

**Goal:** gemma becomes a first-class arena model; the paid fallback
stops burning flash rates on every gemma hiccup.
**Requirements:** R1, R2
**Dependencies:** none
**Files:** `scripts/clicklab/arena_policy.py`,
`tests/test_arena_policy.py` (create if absent), user config
`~/.config/wisp/config.toml` (fallback line — not repo code; note in
report)
**Approach:** add `"openrouter:google/gemma-4-31b-it"` to
`HOSTED_PRICES` at its real price (~$0.07/$0.27 per Mtok — verify
against OpenRouter at implementation time; use the model's
`usage.cost` ledger values as ground truth, not memory). Swap the
config fallback to `openrouter:meta-llama/llama-4-maverick` — the
already-priced $0.15/$0.60 entry. Do not touch `answer_model` (vision
route needs a vision-capable model; maverick's vision support must be
verified or flash stays on the answer route only).
**Patterns:** existing `HOSTED_PRICES` entries; `classify()` tests.
**Test scenarios:**
- `classify("openrouter:google/gemma-4-31b-it")` → `"hosted"`
- matrix with gemma + a local spec passes `validate_matrix`
- gemma at a price over the ceiling would be rejected — pin the
  ceiling-check behavior with a synthetic over-ceiling entry
- premium-name rejection still fires (existing tests keep passing)
**Verification:** unit tests green; `run.py --models
openrouter:google/gemma-4-31b-it` under orch passes the gate.

### U2. cube.py multi-worker lifecycle

**Goal:** `cube.py` manages N sandboxes, not one.
**Requirements:** R3, R5
**Dependencies:** none
**Files:** `scripts/clicklab/cube.py`,
`tests/test_cube.py` (new)
**Approach:** state file becomes a list —
`{"workers": [{sandbox_id, ip, cdp_port, created}]}` — with
`up --count N`, `down [--all]`, `status` printing all. Provisioning is
idempotent per sandbox (already true). `run` keeps meaning
"one sandbox": `run --worker i` or default worker 0. Reuse check pings
envd per worker; dead entries are recreated lazily on `up`.
**Test scenarios:**
- state round-trip with 3 workers serializes/deserializes
- `down --all` issues kill per sandbox_id and clears state
- stale worker (envd unreachable) is detected and replaced on `up`
- mock `_req`/`exec_guest`/`sandbox_ip` seams; no real API calls in
  tests
**Verification:** `cube.py up --count 2` returns two `ip:port`
endpoints (verified once live), each `curl /json/version`-able.

### U3. hammer-parallel.sh + worker runner

**Goal:** N CubeVM workers loop the suite×model matrix concurrently.
**Requirements:** R3, R4, R5, R6
**Dependencies:** U1, U2
**Files:** `scripts/clicklab/hammer-parallel.sh` (new),
`scripts/clicklab/cube.py` (worker subcommand if needed),
`scripts/clicklab/run.py` (worker/sandbox attribution fields)
**Approach:**
- `hammer-parallel.sh N MINUTES`: `orch` wrapper exports the eval key
  + `WISP_ARENA_ORCH=1` once at the top; children inherit.
- Per worker `i`: `cube.py up --count N` once up front (parallel
  creation acceptable — provision is ~90s), then spawn
  `run.py --cdp <ip>:9223` loops rotating suites×models×seeds.
  Round-robin the suite list so workers don't collide on the same
  suite needlessly (they can't corrupt each other — each has its own
  chromium — but spread buys coverage).
- Per-worker log: `training-logs/par-<ts>-w<i>.log`.
- `run.py` gains `--worker <id>` which writes `worker` + `sandbox_id`
  into each record (read from `cube-worker.json` via the CDP flag,
  or pass `--sandbox-id` through the shell).
- Daily cap: `brain.spend_today()` check already in run.py's task
  loop — confirm it reads the ledger fresh each iteration (it does);
  add a test that a mocked over-cap ledger aborts the suite early.
- Ledger append safety: `spend.jsonl` writes are small single-line
  appends — POSIX `O_APPEND` writes are atomic for <4KB; verify the
  writer uses `open("a")` and single `write()`; if it writes
  multi-part, switch to a single-line dump.
**Test scenarios:**
- ledger: two processes append 100 lines each, file parses to exactly
  200 valid JSON lines
- `run.py --worker 3 --sandbox-id fake` record carries both fields
- worker-level CDP failure marks the task `env` flake and continues
  (existing fault-classification path)
**Verification:** `hammer-parallel.sh 2 5` for 5 minutes produces
records from ≥2 distinct `sandbox_id`s in `clicklab.jsonl`, both
worker logs non-empty, spend lines ≤ cap.

### U4. Run report

**Goal:** end-of-run summary without hand-rolled jq.
**Requirements:** R6
**Dependencies:** U3
**Files:** `scripts/clicklab/report.py` (new, small) or a `--report`
flag in `hammer-parallel.sh`
**Approach:** read `clicklab.jsonl` since a `--since` ts (or the
run's start), group by `model×suite`, emit verified-rate + total
`cost_usd` + calls-per-verified-task. Table to stdout; JSON to
`training-logs/report-<ts>.json`.
**Test scenarios:**
- fixture jsonl → expected groupings and sums
- empty window → "no records" line, exit 0
**Verification:** report output matches a manual ledger count for a
known window.

## Risks

- **Shared cap races:** N workers each check spend before a task —
  worst case N×task-cost overshoot before the ledger updates. Accept
  (cap is a guardrail, not a precision instrument); note in report.
- **Chromium install ~90s×N serial:** acceptable v1; `clone(n)` is the
  documented fast-follow if it dominates.
- **OpenRouter rate limits under N×concurrency:** gemma free-tier
  429s already trigger fallback; with maverick as fallback the blast
  radius is cheap. Watch `env` flake count in the report.
- **`orch` env propagation:** workers must run under it or the gate
  refuses hosted specs — the script fails loudly at first task, which
  is the designed failure.

## Deferred to follow-up work

- `Sandbox.clone(n)` provisioning fast path.
- `--replay`-based regression lane per worker (banked recipes replay
  at $0 — run alongside model tasks).
- Tier-1/Tier-2 adapters, recipe promotion, federation (separate plan).
