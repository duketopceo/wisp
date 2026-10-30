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
