---
title: Portable Wisp Credentials - Plan
type: feat
date: 2026-10-30
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
---

# Portable Wisp Credentials - Plan

## Goal Capsule

- **Objective:** Wisp users can configure and use their own provider credentials safely without installing a particular secret manager.
- **Means:** Use a shared credential-source contract for Wisp-owned calls, with optional platform keyring and OmaSeal support (KTD1).
- **Authority:** User-confirmed scope and repository safety requirements take precedence over implementation preferences.
- **Execution profile:** One reviewable change unless an implementation dependency requires splitting it; do not commit or deploy without user authorization.
- **Stop conditions:** Stop before changing live credentials, external accounts, installed configuration, or services without explicit permission; never disclose secret values.
- **Owner:** A later implementation session completes and verifies the work; this document does not implement it.

## Product Contract

### Summary

Make credential onboarding and resolution portable across installations and consistent across Wisp-owned OpenRouter paths. Preserve existing configurations and isolate the user's own local setup from shipped defaults.

### Problem Frame

Users should not need the author's keyring or credentials to run an open-source application. Today the Python brain and recall paths use configurable sources, but some decision and grounding paths use a hard-coded environment lookup; Rust's source parsing also differs. This can split one installation across different keys and makes consent, spending controls, and trace attribution unreliable.

### Requirements

- R1. Users provide their own credentials; no personal account, API key, spending cap, or OmaSeal installation is a product dependency.
- R2. Existing environment-variable and existing `.env` configurations keep working without automatic secret migration or deletion.
- R3. Wisp-owned interactive brain, hosted decision/router, grounding, shadow decisions and OpenRouter-backed recall use an explicit, predictable source selection; a configured dedicated source must not silently use a different account.
- R4. Allow supported desktop Secret Service, optional OmaSeal, and environment sources; onboarding describes the chosen storage and works without either keyring. Do not present plaintext `.env` as equivalent to a keyring.
- R5. Provider-specific credentials remain independent: never send an OpenRouter key to a non-OpenRouter provider or local endpoint. Explicit custom provider credentials remain authoritative.
- R6. Python and Rust implementations have documented, tested compatibility for supported source syntax and precedence, or an explicitly documented capability gap blocks claiming parity.
- R7. Missing, locked, denied, invalid, or unavailable credentials produce actionable, secret-free errors; no interactive prompt from an unattended daemon.
- R8. Keys never enter logs, traces, prompts, spawned background agents, command-line arguments, committed fixtures, or error messages; preserve user consent and local-first defaults.
- R9. Existing users may retain their current configuration; any new-key creation, credential migration, live config update, restart, or deletion is explicit and reversible where possible.

### Scope Boundaries

OpenCode manages its own authentication; do not inject Wisp credentials into its environment. Cloudflare/OpenRouter trace ingestion, model selection, billing management, and user data collection are separate follow-up work. This plan does not authorize altering the local Wisp setup or the new personal key.

## Planning Contract

### Key Technical Decisions

- KTD1. Extend the existing configuration and resolver, not a new mandatory credential service. Define one Wisp-owned OpenRouter source selection with explicit per-provider overrides; map all hosted call sites to it while preserving deliberately configured alternatives.
- KTD2. Preserve historical `OPENROUTER_API_KEY` lookup as the compatibility default only when no source is explicitly configured. Explicit source lists are ordered contracts; no implicit fallback to a shared account.
- KTD3. Never forward a token to a local/custom endpoint merely because the default source exists. Validate provider and endpoint association at each request boundary; local services need an explicit separate credential.
- KTD4. Onboarding prefers a usable system keyring where supported, offers OmaSeal when present, and supports env-based setups. Any existing 0600 `.env` storage remains a clearly disclosed compatibility option; never quietly copy or erase credentials.
- KTD5. Implement parity with tests for each shipped runtime, including ordered sources and unavailable managers. Document a runtime-specific unsupported feature rather than silently interpreting it differently.

### Evidence and Constraints

- `wisp/config.py` implements Python `load_env_key`, ordered comma-separated sources and `load_api_key`; `wisp/brain.py` and `wisp/recall.py` use configured key sources.
- `wisp/stage_route.py`, `wisp/route.py`, and `wisp/grounding.py` contain hard-coded OpenRouter lookups; the shadow provider has a separate configured source. Audit all callers and endpoint configurations rather than assuming this list is exhaustive.
- `wisp/onboard.py` currently supports OmaSeal or a private `.env` fallback; inspect the installed release and current branch independently before implementing Secret Service behavior.
- `rs/wispd/src/config.rs` supports an OmaSeal reference or a single environment name, not Python's ordered-list semantics. Audit Rust call sites and supported runtime scope.
- `docs/TRUST.md` describes sensitive screenshots, transcripts and local traces. The previous local change points the brain and recall at a personal OmaSeal key; route/grounding and OpenCode were not verified switched.
- Architectural guidance: avoid unnecessary services and keep secrets out of logs. Prior Kurultai decisions were not checked in this planning session.

## Implementation Units

### U1. Define and implement the credential contract

- **Goal:** Consistent and backward-compatible source selection (R1-R3, R5-R7).
- **Files:** `wisp/config.py`, `wisp/brain.py`, `rs/wispd/src/config.rs`, `rs/wispd/src/brain.rs`, relevant configuration tests.
- **Approach:** Inventory shipped configurations and every hosted provider caller. Define source precedence and explicit overrides, preserve legacy no-config behavior, and implement safe resolution in each supported runtime. Never infer that a custom endpoint is OpenRouter from an arbitrary URL.
- **Test scenarios:** Legacy env-only install; explicit OmaSeal source absent while a different env key exists; ordered configured fallback; blank or denied secret; separate custom provider; source parity on Python and Rust.
- **Verification:** Mock credential stores and HTTP boundaries; assert actual selected test sentinel without printing it. Document any unsupported runtime combination.

### U2. Unify Wisp-owned hosted call sites

- **Goal:** Use the correct configured source on each hosted request without leaking it elsewhere (R3, R5, R8).
- **Files:** `wisp/stage_route.py`, `wisp/route.py`, `wisp/grounding.py`, `wisp/recall.py`, corresponding Rust paths and tests identified by audit.
- **Approach:** Pass configuration through decision, grounding, shadow and recall paths as appropriate; use provider-specific sources. Preserve local/no-auth and fallback behavior without attaching cloud credentials to local or untrusted endpoints. Keep OpenCode isolated.
- **Test scenarios:** Capture fake HTTP request headers for each lane; check dedicated versus overridden credentials, disabled/absent optional lanes, and a local/custom endpoint that must never receive an OpenRouter key. Ensure test sentinels do not appear in logs or errors.
- **Verification:** Run focused route, grounding, recall, brain and log-hygiene suites in both runtimes where applicable.

### U3. Portable onboarding and safe compatibility

- **Goal:** Make supported storage choices understandable and usable on fresh and existing installs (R1, R2, R4, R7, R9).
- **Files:** `wisp/onboard.py`, `wisp/config.py`, `docs/INSTALL.md`, `docs/CONFIG.md`, `docs/TRUST.md`, onboarding tests; Rust onboarding only if that runtime owns it.
- **Approach:** Detect a working platform keyring rather than executable presence alone; provide noninteractive environment instructions and opt-in OmaSeal where available. Preserve the existing `.env` path with explicit disclosure and permissions. Test read-back without showing credentials. Offer changes rather than auto-migrating or overwriting existing data.
- **Test scenarios:** Fresh Linux with Secret Service; no keyring and no OmaSeal; locked/unavailable keyring; input cancellation; previously configured env and `.env`; restart guidance; existing key preserved after failed setup.
- **Verification:** Automated isolated HOME/keyring mocks plus an explicitly reported manual smoke test on a machine without OmaSeal; no live paid call required.

### U4. Cross-runtime release checks

- **Goal:** Prevent credential leakage or accidental cross-account regressions (R2, R6-R9).
- **Files:** Existing tests and documentation; add narrowly scoped contract tests as needed.
- **Approach:** Cover end-to-end caller-to-HTTP behavior, source ordering, secret redaction, and subprocess environment isolation. Update trust documentation to describe actual storage and data flows. Identify unsupported platform/runtime behavior instead of claiming it works.
- **Test scenarios:** Different sentinel keys in each source; explicit missing source with stale env key; denied keyring; provider URL changes; environment isolation in agent subprocesses; backward-compatible existing configuration.
- **Verification:** Focused Python suites and Rust tests, followed by the project's applicable CI gates. A real provider smoke test requires a separate consent and spend ceiling.

## Verification Contract

- Run applicable targeted suites, including `python -m unittest discover -s tests` (or the same named `test_*.py` files individually), after checking actual test names and project environment; add new contract tests for every audited call path.
- Run `cargo test` for the Rust daemon from its actual crate root; exercise source parsing parity and indicate any unavailable platform checks.
- Validate onboarding with a fresh temporary home and no OmaSeal on PATH, and check old env/.env behavior using dummy values only.
- Verify logs, traces, exception messages, process arguments and child environments contain no secret sentinels. Never use real personal credentials in fixtures.
- Report automated, manual, skipped and paid checks separately. No live credential migration, remote calls or daemon restart is implied by a passing unit test.

## Definition of Done

- All Wisp-owned OpenRouter paths honor the selected credential contract and do not leak credentials to other endpoints.
- Fresh installs work without OmaSeal, existing configurations remain usable, and keyring failures are clear and non-destructive.
- Python and Rust parity is verified or remaining gaps are explicitly release-blocking.
- Documentation reflects actual behavior; tests and manual gaps are reported honestly; abandoned experiments are removed. No deployment, user-key rotation or telemetry collection occurs as a side effect of completing the plan.
