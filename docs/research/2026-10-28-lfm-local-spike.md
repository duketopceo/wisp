# spike/lfm-local — Liquid LFM as the local/offline lane

Test branch, not a direction: can a dense few-GB local model take over
the latency-hot, low-reasoning stages and cut cloud cost, without giving
up the verification ladder?

## What's here

- **`lfm` brain provider** (`wisp/brain.py`): `openai_compat` preset at
  `http://127.0.0.1:8082/v1`, vision on, tools off. Use it with
  `[brain] default = "lfm:lfm25-vl-1.6b"` or as a `[brain] fallback`
  entry (local entries are never paid-gated). Per-provider overrides
  live in `[brain.lfm]` like every other provider.
- **`scripts/lfm-serve`** — launcher; `install -m755 scripts/lfm-serve
  ~/.local/bin/llama-lfm`. Env: `LFM_MODEL` (HF spec or local GGUF),
  `LFM_PORT`, `LFM_CTX`, `LFM_EXTRA`.
- **`scripts/units/llama-lfm.service`** — installs with the other llama
  units only when `[local] enabled = "true"` and the launcher exists.
- **`scripts/lfm_eval.py`** — the gate evaluator: runs a jsonl of
  screen-QA / prompt fixtures through the lfm provider and (optionally)
  a paid reference provider, prints per-fixture ok/miss + ms, summary
  accuracy and p50, and PASS/FAIL gates. `tests/fixtures/lfm_gate.jsonl`
  is the starter set — grow it from `wispd eval --misses` and clicklab
  replays.
- **`tests/test_lfm_eval.py`** — provider resolution, unit gating,
  scoring, gates, offline failure path.

## Candidate models

| Model | ~Q4 size | Wisp stage to try |
|---|---|---|
| LFM2.5-VL-1.6B | ~1.1 GB + mmproj | screen QA, point candidates, note drafting |
| LFM2-VL-450M | ~350 MB | cheap screen reads, element description |
| LFM2.5-350M/230M (text) | ~250-350 MB | routing, tool calls, extraction |
| LFM2.5-Audio-1.5B | ~1.5 GB | possible local STT/answer pair |

## The loop

```
install -m755 scripts/lfm-serve ~/.local/bin/llama-lfm
llama-lfm &                                   # or: systemctl --user start llama-lfm
python scripts/lfm_eval.py tests/fixtures/lfm_gate.jsonl \
    --lfm lfm:lfm25-vl-1.6b \
    --ref openrouter:google/gemini-2.5-flash   # paid; needs key+budget
```

1. Baseline: `wispd eval` / replay harness numbers with the cloud brain.
2. Swap one lane at a time to `lfm:` (answer brain first — vision path;
   never act grounding, which keeps `control → a11y → uitars` first).
3. Grow `lfm_gate.jsonl` from real misses; each miss is a fixture.
4. Tuning path: distill cloud gold outputs from `trace.jsonl` into
   SFT/LoRA on `LFM2.5-VL-*-Base` → export GGUF → re-run the gate.
   RL (DPO on `labels.jsonl` preference pairs) only if SFT plateaus.
5. Promotion gates (defaults, tune via flags): p50 ≤ 400 ms, accuracy
   ≥ 0.5 absolute, within 0.10 of the reference provider.

## Known limits

- **License:** LFM Open License v1.0 — free under $10M/yr revenue, but
  not OSI. Stays opt-in; weights never vendored.
- **Vision res:** 512×512 native, tiled above; small UI text is the
  expected weak spot — measure, don't assume.
- **No coordinate training:** point candidates need prompt coaxing or
  fine-tune; grounding keeps its control/a11y-first chain regardless.
- **Reasoning:** sub-2B models are not act-loop brains. Realistic wins
  are latency and offline resilience on QA/route/note/dictation lanes.
