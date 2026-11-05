# Accuracy evidence and element-backed clicks

## Status

B3's executable click rule and a read-only normalized trial importer are
implemented. The original owner clicklab export is **not available in this
checkout**. No historical baseline, historical worst-three ranking, or
owner-labelled before/after improvement is claimed.

The historical task/trial totals in the
[B3 plan](plans/2026-10-27-feat-wisp-beat-competitors-plan.md#b3-accuracy-loop-on-the-clicklab-baseline)
describe a requested source, not data reproduced by this implementation.
The only new input fixture,
`tests/fixtures/accuracy/synthetic-trials.jsonl`, contains four explicitly
invented trials in two synthetic kinds. Its dates, task names, verification
flags, and latency values are test data, **not owner labels or measurements**.
Do not put its report in `docs/baselines/` as the historical baseline.

## Click contract

- A named target keeps its `Target` source, bounds, confidence, label, and
  window through act dispatch instead of being reduced to an untyped pair.
- Observed control/a11y bounds containing the point are element evidence.
  Control has priority over accessibility in the read-only point hit test;
  the existing configured name-grounding chain retains its order.
- A numeric model click, or a named VLM/label point without observed bounds,
  must acquire independent live element evidence before compositor backend
  injection. A VLM's confidence, requested label, or model-authored rectangle
  is not itself that evidence. A real unnamed accessibility button can
  still supply evidence through its role/id and bounds.
- This is **not an a11y-only rule**: control-backed targets and the existing
  DOM lane still work. DOM dispatch checks a live element in the same
  JavaScript operation that dispatches the event (by id or
  `elementFromPoint`). A missing DOM element never dispatches.
- A missing element yields `REFUSED`, not `CLICKED` or false completion.
  Re-observe or name an element; do not automatically retry through a
  different injection backend.
- Guide handoffs, nonmutating move/pointing, off-monitor refusal,
  sensitive-surface confirmation, kill/deny/rate/dry-run gates, and existing
  pointer backend priority remain in place. An element-free guide or move
  is not an injected mutating click.

### Trusted human-coordinate exception

`act.run_act_loop(..., user_request=verbatim_human_request)` is the explicit,
keyword-only trusted seam. The default is empty and fails closed: `task`
can be generated, so it does not authorize coordinates. The caller must
provide the original transcript/request, never a synthesized goal,
tool-call JSON, or model-provided `source="user"`.

The accepted literal request forms are `click x,y`, `click at x,y`,
`tap x,y`, or `tap at x,y`,
optionally preceded by `please`, with optional `@logical` and terminal
punctuation. Pair **and coordinate frame** must match the dispatched
argument. Negated, quoted, indirect, or compound instructions are not
exceptions. When a request falls outside this narrow form, element-backed
clicks and guide mode remain available.

The executor receives provenance through the dispatch-scoped
`system.pointer_context(target=target, user_request=request)`, not config
or model fields. The context resets even when dispatch raises; it must not
be persisted or reused for a later action.

**Integration required outside B3 ownership:** the `stage_execute._run_act`
caller must pass `user_request=detail` only when `detail` is the verbatim
human request. Scheduled routines must not authorize coordinates by
copying a generated routine/task into this parameter. Legacy injection
tests must provide genuine fake element evidence or explicitly represent
a human coordinate request; do not globally bypass the safety rule.

## Read-only baseline import

No service, model training, reinforcement learning, network access, or
live desktop action is involved. The importer reads one JSONL file and
prints JSON to stdout; it never changes the source or writes reports
automatically.

```sh
# Inspect the machine-readable JSON Schema for each JSONL record.
python scripts/accuracy_baseline.py --schema

# Deterministic example: synthetic data only, NOT a historical baseline.
python scripts/accuracy_baseline.py \
  tests/fixtures/accuracy/synthetic-trials.jsonl \
  --imported-at 2026-10-30T12:00:00Z
```

### Input schema: `wisp.accuracy.trials.v1`

Exactly one manifest comes first, followed by at least one trial.
Blank lines are ignored. Unknown/missing fields and malformed data fail
with exit status 2 and no partial report.

| Manifest field | Meaning |
| --- | --- |
| `record_type` | Exactly `manifest` |
| `schema` | Exactly `wisp.accuracy.trials.v1` |
| `dataset_id` | Nonempty source/export identity |
| `synthetic` | Required boolean, never inferred from a filename |
| `collected_on` | ISO calendar date for collection/export, not import time |
| `source_ref` | Nonempty original export/path/approved source description |

| Trial field | Meaning |
| --- | --- |
| `record_type` | Exactly `trial` |
| `trial_id` | Nonempty unique trial identity across the file |
| `task_id` | Nonempty task identity; retries are separate trials of a task |
| `kind` | Nonempty kind exactly as supplied; no invented category mapping |
| `outcome` | `acted`, `aborted`, or `not_acted` |
| `verified` | Boolean or null; true requires an acted trial |
| `elapsed_ms` | Finite nonnegative number, not a boolean |
| `recorded_at` | ISO timestamp with timezone; normalized to UTC in report |

This is a **normalized export contract**, not a guess at the missing
clicklab file's undocumented shape. When the original becomes available,
inspect its schema, document an approved mapping, and retain the original
bytes plus their SHA-256 alongside any normalized export. Do not derive
trials, kinds, dates, or labels from a prose historical summary.

### Output: `wisp.accuracy.baseline.v1`

The report includes the import timestamp, dataset identity, synthetic
flag, absolute input path, byte length, SHA-256 of the exact input bytes,
source schema/reference/collection date, actual first/last trial instants,
and total trial/task counts.

Each kind reports `trials`, `acted`, `aborted`, `verified`,
`verified_rate`, `abort_rate`, and `median_ms`. Both rate denominators are
**all trials of that kind**; null/false verification is not verified.
Median time includes all outcomes, including aborts and not-acted trials.
Kinds are preserved exactly and rows are alphabetical.

`ranking` lists **all** input kinds in descending abort-rate order,
breaking ties by descending median time, then ascending kind. It is a
ranking of that input only, never an inferred historical top three.
Trial verification is not interchangeable with the owner's
first-time-correct labels used by `wispd eval`.

## Pending data and live gates

1. Obtain the original owner export or an approved source-matched export.
   Inspect and map its actual fields without changing outcome semantics.
2. Preserve the original and normalized-export hashes, real collection
   dates, source reference, and import timestamp. Compare every per-kind
   count/rate/median against the source before accepting a historical
   `docs/baselines/accuracy-*` artifact.
3. Only then identify the actual three worst kinds and add one dedicated
   red-before/green-after replay per kind. Current synthetic safety tests
   are not substitutes for these source-ranked regressions.
4. Run the real installed candidate and collect owner-labelled turns
   with release/commit identity. Record `wispd eval` before/after, verify
   first-time-correct does not drop, and satisfy the release label-count
   and pass-rate gate. No such tally was produced by these fake tests.

Focused offline checks:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  tests.test_click_provenance tests.test_accuracy_baseline -v
```

## Teaching harness baseline (offline)

`python scripts/gauntlet.py --teach-offline` (or
`wisp.gauntlet.score_teach_cases(dir)`) scores recorded planner replies for
the first step of each teach case in `tests/fixtures/teach/`. It reads files
only: no model call, no network, and a case with no recorded reply is an
error. Captures are synthetic mock UIs drawn by
`scripts/gen_teach_fixtures.py`; the replies are **hand-authored, not real
model output**, and four of the fifteen are deliberately wrong.

A case counts as first-time-correct when the reply points inside the
expected region (plus a small slack) and carries the expected `kind`. A
reply that omits `kind` is wrong-kind, because the planner's `kind` field is
optional today. Order of checks: no-element, wrong-target, wrong-kind.

| class | cases (n=15) |
|---|---|
| first-time-correct | 0 |
| wrong-target | 2 |
| wrong-kind | 11 |
| no-element | 2 |
| target right, any kind | 11 |

The 0 is the strict rule at work: no current-planner reply names a kind.
The last row shows the pointing quality underneath. Later units add cases
through `tests/fixtures/teach/<id>/` (`case.json`, `capture.png`,
`reply.json`); `case.json` may also carry optional `ax_tree` (U7) and
`guide` (U9) fields, unused by scoring until those units land.

## Grounding model bake-off (U8)

Plan unit U8 in `docs/plans/2026-11-04-1847-feat-wisp-teaching-assistant-parity-roadmap-plan.md`.

**Status: the harness is built and tested offline. The live run was not
done, so there is no per-model accuracy or cost number yet.** The key
store was locked when the run was due (`omaseal get openrouter wisp`
returned `store locked`), so the run was skipped rather than worked
around. Live spend: $0.00. The default model is unchanged, and no model
is recommended: nothing was measured.

### What exists

`scripts/grounding_bakeoff.py` draws synthetic screens with PIL (a title
bar and 6 to 10 labelled buttons on six canvas shapes: 16:9, 16:10, 4:3,
ultrawide and two portraits), so most cases force a letterbox pad. Each
case is sent the way production sends it (`Shot.letterboxed`, the
`_VLM_POINT_PROMPT` text) and the reply goes through
`grounding.parse_vlm_reply`, the same parser `_vlm_locate` uses. A hit is
a point inside the target button's rectangle in source pixels. A reply
with no point, a point outside the image or one inside the padding is a
miss.

- **Split.** A pool of 120 case ids is partitioned once by
  `sha256(seed:id)` into a tuning set and a held-out set (40 percent).
  Same seed, same split; the sets cannot overlap (tested). Case content
  does not depend on the split seed. Only held-out cases are scored.
- **Modes.** `direct` (one call, pixel coordinates) and `labels` (the
  same prompt plus the visible control labels, standing in for an
  accessibility tree). Describe-then-point (two calls per case) is not
  implemented; it doubles the cost per case and should wait for a
  direct-mode winner.
- **Spend cap.** A hard cap in dollars. The loop is case-major so a
  partial table stays balanced, reads the cost from OpenRouter's
  `usage.cost` on every reply, and stops before the call whose worst case
  (the largest cost seen so far, or a $0.01 reserve before any) could
  cross the cap. It prints the table so far with `n` per row and exits 3.
- **Round trip.** Tests cover `Letterbox` conversion for landscape,
  ultrawide, portrait and exact-aspect captures, the repo's recorded
  `tests/fixtures/images` PNGs, and an oracle provider that answers in
  sent-image coordinates and must score 100 percent on every canvas.
- Offline tests use fake providers only, with the network patched to fail.

### Candidates and prices (from the OpenRouter models list, read 2026-11-05)

Open-weight vision models only. Prices are USD per million tokens
(prompt / completion); not measured, and they change.

| model | prompt | completion |
|---|---|---|
| `qwen/qwen3-vl-8b-instruct` | 0.25 | 0.75 |
| `qwen/qwen3-vl-30b-a3b-instruct` | 0.15 | 0.60 |
| `qwen/qwen3-vl-235b-a22b-instruct` | 0.21 | 1.90 |
| `qwen/qwen2.5-vl-72b-instruct` | 0.80 | 1.00 |
| `bytedance/ui-tars-1.5-7b` | 0.10 | 0.20 |
| `google/gemma-4-31b-it` | 0.20 | 0.40 |
| `meta-llama/llama-4-maverick` | 0.35 | 1.00 |

The shipped default, `google/gemini-2.5-flash` ($0.30 / $2.50), is not
open-weight, so it is outside this run by the owner's rule. Whether it
would win is unmeasured here.

### Run it (owner)

```sh
export OPENROUTER_API_KEY=...   # from your key store; never paste it
python scripts/grounding_bakeoff.py --live --cap 0.80 --cases 24 \
  --models qwen/qwen3-vl-8b-instruct,qwen/qwen3-vl-30b-a3b-instruct,qwen/qwen3-vl-235b-a22b-instruct,qwen/qwen2.5-vl-72b-instruct,bytedance/ui-tars-1.5-7b,google/gemma-4-31b-it,meta-llama/llama-4-maverick
```

24 cases, 7 models and 2 modes is 336 calls. Each call is one image of
about 1,000 tokens in and under 64 tokens out, so the cost should be
well under the cap (an estimate from the table above, not a measurement).
Paste the printed table here with the date and the seed.

### How to read the result

Synthetic cases are a weak signal: flat, high-contrast, English-only
buttons with no real application chrome, no icons-only controls and no
clutter. They can screen out a model that cannot do pixel pointing at
all, and they exercise the letterbox math. They cannot establish that one
model is better than another on real screens, and a few points of
difference over 24 cases is noise. A change of the default model needs
the owner's approval and a result on labelled real turns; this table
alone is not that.
