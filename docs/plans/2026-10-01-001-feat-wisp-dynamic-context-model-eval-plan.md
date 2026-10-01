# feat: Dynamic context priming + router model eval + Argus PR gate

## Summary

Three follow-ups from live dogfooding: (1) the whisper vocabulary prompt
is a static string — it should be built from what Wisp *knows* (learned
apps, skills, recent windows, user vocab) and rebuilt on a timer;
(2) `typesafe/jev` is the decision router by habit, not by measurement —
run an offline bake-off against the logged decision corpus before
committing to it; (3) Argus exists (`duketopceo/Argus`, vision-E2E PR
reviewer) but isn't wired to this repo — add the workflow + self-hosted
runner so PRs get a real gate, which only matters once work moves back
to branch-per-change.

## Problem Frame

The static `stt.prompt` string fixed the "Omarchy → Amache" miss, but it
rot: the vocabulary that matters next week (a new plugin, a new project,
a new contact) isn't in it. Wisp already *possesses* the vocabulary —
`harness.json` learned apps, `~/.local/share/wisp/skills/*/SKILL.md`
names, omarchy plugin IDs, recent window titles from `activity.jsonl`,
`MEMORY.md`/`USER.md` terms. Whisper's `--prompt` is a conditioning
string, not a list — feeding it *this machine's* nouns is strictly more
accurate than a hand-maintained string, and it's free (no extra call).

On routing: Jev was chosen as "cheap structured decisions" and has never
been evaluated against alternatives. OpenRouter now lists several
candidates in the same price band or cheaper (measured 2026-10-01):
`qwen3-30b-a3b-instruct` ($0.048/$0.193), `granite-4.0-h-micro`
($0.017/$0.112), `ministral-3b-2512` ($0.10 flat), `gemma-3-4b`
($0.05/$0.10), `gpt-5-nano` ($0.05/$0.40). We have ~90 labeled/real
decisions on disk — enough signal to say which model actually routes
Luke's voice correctly. Pick by eval, not blog posts.

## Requirements

- **R1** `stt.prompt` is generated, not static: build a priming string
  from learned apps + skill names + omarchy plugin names + recent
  window-title terms + MEMORY/USER vocab, capped ~200 tokens, rebuilt
  on daemon start and every N hours. `[stt] prompt` config becomes
  *extra* terms appended to the generated base.
- **R2** A `wispd eval route` command replays decisions.jsonl (plus
  labeled corrections as adversarial cases) through candidate models
  and prints intent-match per model + per-route confusion. No daemon
  behavior changes from the eval itself — it prints a table.
- **R3** The router model is chosen by eval result, written to
  `[agent] model`; Jev stays default until the eval says otherwise.
- **R4** Argus wired to this repo: `.github/workflows/argus.yml`
  targeting a self-hosted `argus-reviewer` runner, OPENROUTER key from
  repo secrets (`orchestral-eval-v3` lane per org rule — eval spend
  bills `openrouter/orchestral`, never `default`).
- **R5** Work moves to branch-per-change once Argus gates PRs —
  master's PR-required rule is already enforced server-side (pushes
  are bypassing, not satisfying it).

## Design / Approach

### U1 — Dynamic vocab priming (`wisp/vocab.py` + pipeline)

`vocab.build(cfg) -> str`:

- `harness.json` app names (learned, real usage)
- `skills/*/SKILL.md` names + descriptions' first words
- `~/.config/omarchy/plugins/` directory names (the duketopceo
  namespace = user's own plugins)
- last ~20 distinct window titles from `activity.jsonl`, normalized
  (split CamelCase, drop generic "Mozilla Firefox")
- proper nouns from `MEMORY.md`/`USER.md` (capitalized terms,
  code-spans)
- `[stt] prompt` config appended verbatim (user's manual additions win)
- dedup, cap ~60 terms / ~200 tokens, newline-joined

`transcribe()` calls `vocab.build()` when `[stt] vocab_dynamic != "false"`;
result cached in state.json and refreshed on a `vocab_ttl_s = 3600`
timer — no per-turn rebuild. Whisper gets the merged prompt.

### U2 — Route eval harness (`wisp/evalroute.py` + `wispd eval route`)

- Load `decisions.jsonl`; for each record reconstruct the Jev question
  (transcript → route choice) and ask each candidate model the same
  multiple-choice question Jev was asked.
- Score: did candidate pick the same route? For records carrying a
  `correct` label, the picked route is ground truth; for `incorrect`,
  the corrected pick (from corrections.jsonl) is truth.
- Candidates (config list, default):
  `typesafe/jev-router`, `qwen/qwen3-30b-a3b-instruct-2507`,
  `mistralai/ministral-3b-2512`, `google/gemma-3-4b-it`,
  `ibm-granite/granite-4.0-h-micro`
- Print: intent-match % per model overall + per route, mean latency,
  est. cost per 1k decisions. Bills to `orchestral-eval-v3` via the
  `orch` wrapper — this is eval spend.
- Also compare against the zero-model baseline: app-name regex +
  `learn.apply_overrides` cues, no model call at all. If the heuristic
  beats every model on Luke's actual commands, the honest answer is to
  route common cases locally and reserve the model for ambiguity.

### U3 — Argus gate

- `.github/workflows/argus.yml` from `npx argus-reviewer init` shape:
  `pull_request` trigger, `runs-on: [self-hosted, linux, x64,
  argus-reviewer]` per Argus AGENTS.md (x64 — register on a different
  host or x64-emulated; Asahi is aarch64, so the runner likely lands on
  the Dell or a cloud box — call out in PR).
- `OPENROUTER_API_KEY` repo secret = `orchestral` key.
- Record 1-2 smoke flows against the debug GUI (`wispd gui` serves a
  local page — argus drives Playwright against it).
- **Gate is advisory first**: `continue-on-error` while the flow
  calibrates, hard gate after a week of not-flaky runs.

### U4 — Branch discipline

Flip the working convention: features on `feat/*` branches → PR →
Argus review → merge. Keeps master's enforced rule honest and gives
Argus diffs to review.

## Acceptance criteria

- `wispd eval route` prints a scored table over real decisions; the
  chosen router's intent-match is printed and ≥ Jev baseline.
- Recording audio after a vocab rebuild shows project nouns in the
  whisper prompt (visible in trace.jsonl `transcribe` span).
- `wispd install && systemctl --user restart wispd` — *both* steps —
  verified live (the stale-opt bug taught us restart ≠ deploy).
- Argus workflow present; one PR opened with an Argus comment posted
  (advisory mode).
- Test suite passes; new tests cover vocab.build, eval scoring, and
  the cache TTL.

## Risks / mitigations

- **Eval cost**: ~90 decisions × 5 models × ~300 tokens ≈ pennies. The
  `orch` wrapper enforces the eval key.
- **Vocab prompt drift**: whisper prompt length is capped by
  `n_text_ctx/2` — the 200-token cap keeps us far under.
- **x64 runner**: Asahi box is aarch64; Argus runner needs x64 (or a
  container). If no x64 host is available, U3 lands the workflow but
  stays disabled — flagged in PR, not silently queued.

## Out of scope

- No model fine-tuning.
- No live A/B routing (eval is offline replay only).
- Argus on other repos — wisp first.
