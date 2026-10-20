---
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan user-directed
external_source: ByteDance/UI-TARS-desktop (github.com/bytedance/UI-TARS-desktop) — 39k★, Apache-2.0, TypeScript/Electron, pushed 2026-10-09
---

# UI-TARS-desktop eval — reference stack for the model we already serve

## Goal Capsule

Evaluate ByteDance's UI-TARS-desktop (the reference GUI-agent stack) against wisp's UI-TARS-7B endpoint on :8081 — decide what to adopt (grounding loop, prompt scaffolding, action schema) vs what stays out (the Electron shell). Likely outcome: pull components, not the app.

## Product Contract

### Why eval, not adopt

wisp already serves `llama-uitars` :8081 (UI-TARS-7B for GUI grounding) — we have the model, not the product. UI-TARS-desktop is the product: Electron app + operator loop + action executor + multimodal pipeline. The Electron shell doesn't fit wisp's daemon model; the *internals* (grounding loop, screen→action schema, prompt scaffolding, error-recovery on GUI actions) are the valuable parts.

### Scope boundaries

- **In:** run it (or read it deeply if aarch64 Electron is a problem), extract the grounding/action loop, compare against wisp's current UI-TARS usage, write a components-to-borrow list.
- **Out:** shipping the Electron app; adopting its orchestration layer wholesale; connecting it to production workflows.

### Requirements

1. Platform gate: Electron on aarch64 Asahi — verify it builds/runs at all. If not, the eval degrades to code-read (still valid — the loop is what we're taking).
2. Extract the loop: screenshot → grounding call → action schema → execute → verify. Document their action space (click/type/scroll primitives, coordinate conventions) vs wisp's.
3. Identify the borrowable pieces concretely: prompt templates, action parser, retry/recovery on failed GUI actions, grounding-model call format.
4. Decision note `docs/decisions/ui-tars-desktop-eval.md`: per-component adopt/borrow/skip.

### Acceptance examples

- A written comparison of action schemas (theirs vs wisp's) with a concrete recommendation.
- If it runs: one end-to-end GUI task driven by our :8081 endpoint inside their harness.

## Repo Touchpoints

- `docs/decisions/ui-tars-desktop-eval.md` (new)

## Test Scenarios

1. aarch64 run or documented blocker.
2. Point their grounding call at our local :8081 instead of their default endpoint.
3. One deterministic GUI task (open X, click Y) passes or fails visibly.

## Risks / Honest Notes

- 39k★ / 4k forks / pushed this month — real project, not vaporware. But Electron-on-Asahi is a genuine question mark; a code-read eval is the fallback and probably sufficient since we want components, not the shell.
- Don't let scope creep turn this into "build wisp into a desktop agent" — the plan is borrow-the-loop.
