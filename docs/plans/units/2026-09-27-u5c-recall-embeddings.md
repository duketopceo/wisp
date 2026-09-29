---
plan: dim-u5c-recall-embeddings
created: 2026-09-27
status: ready
origin: docs/plans/2026-09-26-001-feat-dim-companion-crossplatform-plan.md#U5c
issue: https://github.com/duketopceo/wisp/issues/11
wave: 2.5
---

# U5c remainder — vector embeddings for recall.db

## Scope

FTS5 lexical recall shipped. This unit adds sqlite-vec embeddings behind
a provider config so recall finds semantically-related context, with
FTS5 staying the zero-key fallback.

## Steps

1. **Schema**: `vec0` virtual table `vec_items` beside `recall_fts`;
   `embedding_model` config (`[recall] provider = openrouter|none`,
   `model = ...`); `none` keeps today's behavior exactly.
2. **Embed on index**: `index_turn`/`index_correction` embed when a
   provider is configured; failures degrade to FTS-only, never lose the
   write.
3. **Search merge**: top-k = RRF over vec ANN + FTS5 ranks (pure-python
   merge, small k). Python impl, then Rust parity (rusqlite + sqlite-vec
   loadable, or `sqlite-vec` crate).
4. **Config docs**: provider table entry + offline note.

## Tests

- Embedding hit outranks lexical-only distractor on a paraphrase query.
- `provider=none` → identical results to today.
- Embedding API failure → FTS result still returned.

## Risks

- OpenRouter embeddings latency on every write — embed async (queue
  thread) if it stalls turns.
- sqlite-vec availability on all three OSes — bundle `.so` in U10
  packaging.

## Done when

A paraphrase of a past turn surfaces it in `recall` top-k.
