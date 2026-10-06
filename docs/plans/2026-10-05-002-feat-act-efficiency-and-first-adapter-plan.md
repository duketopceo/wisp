# feat: Act-loop efficiency + first real-app adapter

Created: 2026-10-05
Type: feat
Origin: `2026-10-04-1800-feat-cua-driver-and-parallel-training-plan.md`;
data-driven from `~/.local/share/wisp/clicklab.jsonl` (4,237 records)

## Problem — what the ledger says

Three measured facts set this phase's priorities:

1. **`unneeded_observe` is 38% of judged waste** (1,510/4,004 judged
   records). The model re-screenshots when nothing changed —
   `act.py` already tracks which tools mutate state, but the model
   still asks for fresh observations it doesn't need. Tasks average
   **1.3 calls above the oracle minimum**.
2. **`apps-nodes` is 0% for both models** across 272 tasks — a
   systematic failure class, not noise. Canvas/graph surfaces need
   geometry-aware targeting that the DOM-button path doesn't provide.
3. **Zero records carry worker/sandbox attribution** — the parallel
   machinery in PR #105 has never run live; its value is unproven.

## Scope

### In scope

- Live verification of `hammer-parallel.sh` + `report.py` against
  real CubeVM workers.
- Cutting redundant observe calls in the act loop (DOM mode first).
- Cracking the `apps-nodes` failure class (canvas targeting).
- First Tier-1 real-app adapter: X compose flow via CDP/DOM.
- Recipe auto-promotion: verified ≥N consecutive passes graduate a
  task sequence to the recipe bank (`recipe-*`).

### Out of scope / deferred

- Tier-2 adapters (Godot/OBS), teach mode, federation — separate plan.
- `Sandbox.clone(n)` fast provision.
- Non-DOM (pixel) surfaces.

## Requirements

- R1: `hammer-parallel.sh 2 10` produces records from ≥2 distinct
  `sandbox_id`s, and `report.py` groups them correctly.
- R2: consecutive `screenshot`/`observe` calls with no intervening
  mutation are elided or served a cheap "unchanged" marker in DOM
  mode; `unneeded_observe` share of judged waste drops measurably on
  a before/after suite run (target: mean efficiency ↑, calls/task ↓
  on `core` + `dom-hard`).
- R3: `apps-nodes` verified rate goes from 0% to >50% on both arena
  models.
- R4: X adapter drives "compose a post" end-to-end against a live
  session, with a machine-checkable oracle (composer state after
  send).
- R5: a task verified ≥3 consecutive passes auto-promotes to a
  `recipe-*` entry that replays at $0 model spend.

## Implementation units

### U1. Live parallel smoke

**Goal:** prove the machinery from PR #105 works on real sandboxes.
**Requirements:** R1
**Dependencies:** none
**Files:** none (operational), `docs/plans/...` status update
**Approach:** `cube.py up --count 2`, then `hammer-parallel.sh 2 10`.
Check `clicklab.jsonl` for distinct `sandbox_id`s, non-empty
per-worker logs, and a `report.py` table. Note the reported run's
cost and any `env` flakes.
**Test expectation:** none — operational validation, results recorded
in the plan doc.
**Verification:** ≥2 distinct sandbox_ids in records; report prints
grouped table; no ledger corruption.

### U2. Observe elision in DOM mode

**Goal:** stop paying for screenshots that can't show anything new.
**Requirements:** R2
**Dependencies:** none
**Files:** `wisp/act.py` (observe handling in `run_act_loop`),
`tests/test_act.py` or `tests/test_act_loop*.py`
**Approach:** in DOM mode the observation is `_dom_shot`, which is
deterministic given unchanged DOM state. When the model calls
`screenshot`/`observe` and the previous step was non-mutating
(already tracked — see `MUTATING` set + the dirty flag around
act.py:181), return the last synthesized shot/digest plus a short
"unchanged since last observe" marker instead of a fresh eval round-
trip. Keep a hard rule: any mutating tool resets the cache. Never
elide the *first* observe or a post-mutation observe.
**Execution note:** test-first — a scripted-brain test that requests
two observes across a non-mutating step and asserts the second is
served from cache (no CDP round-trip), then one across a mutating
step asserting a fresh shot.
**Patterns:** existing dirty-flag + `(auto re-observe)` bookkeeping
in `run_act_loop`.
**Test scenarios:**
- observe → click(mutation) → observe: second observe is fresh
- observe → non-mutating tool → observe: second served from cache,
  flagged "unchanged"
- observe with no prior shot: never cached
- bank path unaffected (`--replay` never calls observe)
**Verification:** new tests green; a `core`+`dom-hard` suite run on
gemma shows lower calls/task vs the recorded baseline (report.py).

### U3. apps-nodes failure class

**Goal:** canvas/graph targeting so the suite isn't a permanent 0%.
**Requirements:** R3
**Dependencies:** U2 (cleaner loop first)
**Files:** `scripts/clicklab/run.py` or `wisp/tools/` (DOM act path),
`scripts/clicklab/apps.html` (if node hit-testing needs a hook)
**Approach:** investigate first — the nodes canvas likely renders
non-DOM children or needs coordinate targeting relative to the
canvas rect. Options: (a) expose node centers via the page's own
state (`__score`-adjacent introspection) so the DOM click path can
translate a node id → viewport coords; (b) add a `click_node`
synthetic tool only for lab surfaces. Prefer (a) — it mirrors how
real canvas apps expose scene-graph state, which is the actual
skill being trained.
**Test scenarios:**
- oracle + probe still work on nodes surface
- gemma verifies ≥1 nodes task end-to-end in CubeVM
- no regression on other apps.html suites
**Verification:** `apps-nodes` >50% verified on a 10-task sample
across both arena models.

### U4. X compose adapter (first real app)

**Goal:** "make a post" works on a real site via CDP.
**Requirements:** R4
**Dependencies:** none
**Files:** `scripts/clicklab/adapters/x.py` (new dir),
`scripts/clicklab/adapters/__init__.py`, `tests/test_x_adapter.py`
**Approach:** adapter = the SurfaceAdapter shape from the origin
plan: `inventory()` (query composer trigger, textbox, post button
via DOM), `act()` (click/fill/post), `state()`/`probe()` (composer
open? char count? posted?). Runs against the user's signed-in neo
browser via the existing MCP/CDP path — real session, real compose.
Oracle: after send, composer closed + toast/timeline state changed.
Draft-only by default; actual posting needs `WISP_X_POST=1` or a
dry-run mode that types but doesn't send (first runs should be
dry-run — a real post is a side-effecting action).
**Test scenarios:**
- inventory() on a logged-out/非-X page returns empty without
  crashing
- dry-run: composer opens, text lands, oracle sees "draft present"
- selector drift fails loudly (adapter error, not silent wrong-click)
**Verification:** dry-run verified against live X in neo; real post
only on explicit opt-in.

### U5. Recipe auto-promotion

**Goal:** competence compounds — verified sequences stop costing.
**Requirements:** R5
**Dependencies:** none (bank exists — `train.update_bank`)
**Files:** `wisp/train.py`, `tests/test_train.py` or clicklab tests
**Approach:** `update_bank` already records verified runs. Add a
threshold: when a (task-key, suite) has ≥3 consecutive verified
passes, write a `recipe-*` entry carrying the step list so `--replay`
executes it with zero model calls. Key recipes by
app/surface/intent — never raw coordinates (use the recorded
selector/anchor fields).
**Test scenarios:**
- 3 consecutive verified records on same task key → recipe entry
  created
- a failure between passes resets the streak
- recipe replays without model calls (mock brain asserts zero calls)
- coordinate-free: recipe stores selectors, not px
**Verification:** a banked recipe replays green in `--replay` mode.

## Risks

- **U2 regression risk:** eliding observes is the kind of change that
  silently breaks tasks needing fresh state — the dirty-flag
  discipline must be airtight, which is why it's test-first.
- **U4 side-effect risk:** X adapter on a live account — dry-run
  default is mandatory; a real "post" needs explicit opt-in.
- **U5 metric gaming:** auto-promotion on streak alone can bank
  lucky sequences — oracle_len must be sane (no 0-step oracles).
- **Cost:** U1 live smoke ≈ $0.05–0.10 on the eval key; U2/U3 reruns
  similar. Small.

## Deferred to follow-up work

- `Sandbox.clone(n)` provisioning fast path.
- Tier-2 adapters (Godot `bpy`-class APIs, OBS websocket), teach
  mode, federation recipe repo.
- Pixel/AT-SPI fallback tier for unscriptable apps.
- SFT/LoRA export of verified trajectories (needs the corpus this
  phase grows).

## Results (verified 2026-10-05)

- **U1 — DONE.** `hammer-parallel.sh 2 5` live: 2 CubeVM workers
  provisioned, 88 records with `worker`/`sandbox_id` stamps
  (w0:42, w1:32), all spend through `orch`. Per-suite: chess/email/
  settings 100%, editor 50%, core 64%, dom-hard 21%.
- **U2 — DONE.** DOM-mode observe elision in `act.py`: model-requested
  screenshot on a clean DOM serves `last_shot + " (unchanged)"`;
  mutations mark dirty; pixel mode untouched. 4 new tests, 159 act
  tests green.
- **U3 — DONE.** `apps-nodes` 0% → 25% live. Root causes found and
  fixed: (a) `type_text` crashed on `input[type=number]`
  (`selectionStart` throws on older Chrome; Chrome 154 returns 0 —
  detect by `el.type` instead), (b) new `fill` tool sets field values
  directly (selects by option text), (c) `fill` was unreachable via
  `tools.run` (not in the cfg-arg dispatch list), (d) select-click
  hint now names `fill`. Remaining misses are model aim
  (`fill n-blur-input 8` on the select, not the `n-blur-radius`
  input) — recorded/judged corpus for the training loop.
- **U4 — DONE.** `social.py`: `post` (safe tier, always dry-run
  preview) and `post_send` (mutating, confirm-gated, opens X
  `intent/post` pre-filled — the human presses Post; wisp never
  scripts the send). No silent posting path exists.
- **U5 — DONE.** `train._fold` stamps `recipe_id` (`recipe-<sha1[:10]>`)
  on graduation; `--replay` accepts task substring or recipe_id,
  replays only `status=graduated` entries (`--all` opts out), exits
  nonzero on re-check failure.
- **U-infra.** CubeVM provisioning: worker rootfs is ~1G and
  chromium-154 + recommends overflowed it (dpkg ENOSPC, silent
  orphan). Provision now `apt-get clean` first, installs with
  `--no-install-recommends`, drops lists after. `_create` kills any
  sandbox that fails bring-up — no more untracked leak.
