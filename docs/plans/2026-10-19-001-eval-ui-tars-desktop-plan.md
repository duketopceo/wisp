---
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan user-directed
external_source: ByteDance/UI-TARS-desktop @ 3ac2cb8d946d78d5ff92ad17b318eaafa18c178c (github.com/bytedance/UI-TARS-desktop) — Apache-2.0, TypeScript/Electron; ~39k★ as of 2026-10-09
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

1. **Platform gate:** Target is **aarch64 Asahi Linux** (Wayland preferred; X11 acceptable) with an **Electron build target** that matches that OS (not macOS arm64 binaries). First record whether upstream documents or ships a Linux desktop build for this target — treat **unsupported target** (no Linux desktop in README/CI) separately from **supported-but-failed** (build or runtime error). Only attempt build/run when supported; otherwise use the code-read fallback (still valid — the loop is what we're taking).
2. **Extract the loop:** screenshot → grounding call → action schema → execute → verify. Document their action space (click/type/scroll primitives, coordinate conventions) vs wisp's.
3. **Identify the borrowable pieces concretely:** prompt templates, action parser, retry/recovery on failed GUI actions, grounding-model call format.
4. **Decision note** `docs/decisions/ui-tars-desktop-eval.md`: per-component adopt/borrow/skip, plus the **pinned revision** (`3ac2cb8…` or the SHA actually checked out if re-pinned at eval time).

### Acceptance examples

- A written comparison of action schemas (theirs vs wisp's) with a concrete recommendation.
- **Endpoint compatibility gate** (before any GUI task counts as success): against the pinned revision, with grounding pointed at `http://127.0.0.1:8081`, verify request shape (chat/completions-style), model id, multimodal image payload, response parsing, coordinate mapping (`px` vs normalized), handling of malformed model output, and transport failure — aligned with wisp's `uitars` provider contract in `docs/CUA.md`. Record pass/fail per check; adapter mismatch is not an eval conclusion.
- **Action-space checks** (code-read minimum; live when the harness runs): deterministic cases with expected outcomes for **click**, **type**, **scroll**, **execute/verify**, and one **deliberate failed action** (expected retry or abort per their loop). The primary live oracle below exercises click; the others are documented from code or run in the fixture when live.
- **Live run hygiene:** disposable VM or user, block all outbound traffic except `127.0.0.1:8081`, disable telemetry and report/UTIO upload in upstream settings, no cloud or premium-provider fallback — evaluation stays local and inexpensive by default.

## Repo Touchpoints

- `docs/decisions/ui-tars-desktop-eval.md` (new)

## Test Scenarios

1. **Platform:** aarch64 Asahi run, or documented **unsupported-target** vs **build/runtime failure** blocker.
2. **Endpoint redirect:** Point their grounding call at `http://127.0.0.1:8081` only; complete the compatibility gate in Acceptance before GUI tasks.
3. **Primary deterministic GUI oracle** (when live): fixture = minimal Electron window or upstream test harness with a labeled button **"EvalTarget"**; postcondition = harness reports click on that control (DOM or accessibility state); allowed actions = open app → single left-click on EvalTarget; **≤5** agent steps, **≤120 s** wall clock; evidence = screenshot + parsed action log saved under `docs/decisions/ui-tars-desktop-eval.md` attachments or cited paths. Fail closed if postcondition unmet (distinguish harness error vs coordinate mismatch vs success).

## Risks / Honest Notes

- Active upstream project (Apache-2.0); Linux desktop support is not established in their README — expect code-read as the likely path on Asahi.
- Don't let scope creep turn this into "build wisp into a desktop agent" — the plan is borrow-the-loop.
