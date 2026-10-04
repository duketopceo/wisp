# Training Gauntlet — research synthesis + three-tier design

Date: 2026-10-02. Sources: three parallel research agents (model
landscape, eval/training harnesses, tiered architectures). Extends
`2026-10-02-training-arena-requirements.md` (shipped on
`feat/training-arena`).

## The shape: three models, one loop

```
utterance
   │
T0  JEV (typesafe/jev-1.13) — route + app + risk, ~50ms. Exists.
   │
T1  ACTOR — fast vision+tools model, ReAct loop, starts immediately.
    Does NOT enumerate options; commits per step. Per-step it emits a
    typed uncertainty tag + reversible/irreversible flag.
    Escalates when: irreversible action ∧ low confidence | tool error |
    repeated-observation loop | step-budget pressure | route doubt.
   │
T2  DECIDER — deliberative model, async (Talker-Reasoner pattern:
    Google, arXiv 2410.08328). Maintains plan/beliefs in shared state
    the Actor reads each step; takes over on escalation, best-of-N at
    decision points, replans on surprise (Plan-and-Act, ICML 2025).
   │
T3  REVIEWER — strongest cheap coding model, OFFLINE/batch. Replays
    trajectories, generates counterfactual alternatives (ECHO,
    arXiv 2510.10304), extracts workflows → skill bank (AWM, ICML 2025:
    +24.6% Mind2Web), relabels failures → future SFT pairs (AgentHER,
    +7–12pp), tunes T1→T2 escalation thresholds.
   │
T4  JUDGE — Jev verdict per run (exists): success vs ground truth,
    efficiency, waste taxonomy. T3 consumes its output; judge stays
    independent of the reviewer (critic information isolation,
    EvoSkill-GUI).
```

Key evidence: RLM-Cascade in production got −45.8% cost, 1.83× faster
p50, quality ≥ baseline at 88.8% cheap-tier draft use. The deferral
estimator is the whole game; escalations must be *typed* (interpretation
→ ask user; evidence → observe more; route → decider; state → inspect;
verify → stronger checker), not one scalar — a bigger model is the wrong
fix for an evidence gap (SAGE-Agent, ACL 2026).

Caution from "Cheap Verifiers, Large Blind Spots" (arXiv 2609.01345):
T3 must be *strong*, and never auto-distill reviewer rejections into T1
training data without validation — that path degrades then collapses.

## Model picks (OpenRouter, verify live prices)

| Tier | Primary | Backup | Price/Mtok |
|---|---|---|---|
| Actor | `google/gemini-3.1-flash-lite` | `openai/gpt-5-nano` (effort=minimal) | $0.25/$1.50 |
| Actor (free) | **local UI-TARS-1.5-7B via mlx-vlm** | `qwen/qwen3-vl-8b-instruct` local | ~$0 (electricity) |
| Decider | `gemini-3-flash-preview` thinking=low | `deepseek-r1-0528` | $0.50/$3.00 (Flex half) |
| Reviewer | `deepseek/deepseek-v3.2` | `qwen/qwen3-coder` | ~$0.21/$0.31 |
| Judge | `typesafe/jev-1.13` | — | existing |

Notes: UI-TARS-1.5-7B is a purpose-built GUI agent (OSWorld 42.5 >
OpenAI CUA 36.4), emits literal action strings — needs an arg parser
shim, not a tool-call shim; 7B fits the M1 Max comfortably = zero-cost
training iterations. gpt-5-nano must pin `reasoning_effort=minimal`.
Prompt caching halves real bills (repeated system+tool-schema).
Escalation axis = reversibility, not just confidence: irreversible
actions get T2 review at much lower uncertainty.

## Harness upgrades (from OSWorld/WebArena/WorkArena research)

Adopt in days:
1. **Oracle solver per suite task** — script the optimal sequence;
   efficiency = steps vs optimal-length, Jev judges path quality not
   step counting.
2. **Pass^k reporting** — run each seed k≥3; skills that lift pass@1
   but not pass^3 are noise (arXiv 2604.17849).
3. **First-fault-step** in the Jev verdict schema (SkillAdaptor) — the
   step where the run first went wrong is where corrections attach.
4. **Flake taxonomy** — env-flake / judge-false-negative / real-failure
   buckets; record seed+timing so flakes reproduce.
5. **Judge audit** — graders false-negative more than false-positive
   ("How Benchmarks Mis-Score CUAs"); sample-audit Jev verdicts.
6. **Cheap-model-first cascade** — whole suite on cheapest model;
   promote only failures to pricier tiers.

Adopt in weeks:
7. **OS-Genesis task synthesis** — enumerate interactive elements,
   roll out short explorations, derive tasks from reachable end-states
   (verification stays free via `__score`). Auto-generates dom-hard
   volume instead of hand-writing.
8. **AgentSynth composition** — compose easy subtasks into long-horizon
   goals (~$0.60/trajectory equivalent).
9. **Isolated critic** — T3 reviewer sees trajectory but NOT the skill
   text it produced (EvoSkill-GUI).
10. **BrowserGym wrap** — expose clicklab as an AbstractBrowserTask to
    inherit MiniWoB++/WorkArena as external validity suites.
11. **Trajectory schema stays SFT-compatible** — keeps the LoRA door
    open (worth it only if grounding errors dominate the taxonomy and
    ≥10k verified trajectories exist).

## Proposed build order

1. `--models` matrix runner in clicklab — same suite across N models,
   results bucketed by model in the bank (scaffold fixed = valid
   comparison, "Scaffold Effect" caveat).
2. Reviewer pass (`scripts/clicklab/review.py`): batch-loads judged
   runs → deepseek-v3.2 → emits counterfactual sequences + first-fault
   analysis + suggested corrections → writes into bank history /
   proposal files. Runs after each hammer, costs cents.
3. Escalation skeleton in act.py: per-step uncertainty tag in the act
   prompt + `decider` tool (escalate → T2 answers next-step guidance).
   Start failure-triggered only (ADAPT).
4. UI-TARS local provider: `brain.local` openai-compat shim + action
   parser → near-free bulk iteration.
5. Pass^k + flake buckets in arena stats/UI.
6. Then: Talker-Reasoner async decider, OS-Genesis task generator,
   BrowserGym wrap.

## Cost sketch

A 28-task core suite at ~1.5 model calls/task ≈ 42 calls. On
flash-lite ≈ $0.0004/run; 100 iterations ≈ $0.04. Reviewer batch over
100 runs ≈ $0.01. Effectively free until desktop-real-mode starts
shipping 1MP screenshots — then local UI-TARS pays for itself.
