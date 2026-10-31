---
title: Verified Install and Update
type: feat
date: 2026-10-29
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
---

# Verified Install and Update

## Goal Capsule

- **Objective:** A person can install or update Wisp with clear progress, know what works, and recover safely if a change fails.
- **Means:** Extend the existing installer, updater, doctor and onboarding into a staged, consent-based workflow with explicit verification and recovery.
- **Authority:** User request for an Omarchy-like verified update experience and a simple first install, including onboarding.
- **Stop conditions:** Stop before overwriting or deleting user data, changing OS settings without approval, deploying an unverifiable release, or claiming recovery where it cannot be demonstrated.
- **Finish:** Implementation and independent verification in a later work session; no deployment or merge implied by this plan.

## Product Contract

### Problem Frame

An install should be as reassuring as an update pipeline: inspect, explain, protect, apply and verify. Wisp already has useful pieces, but they are not yet one verified transaction. `docs/INSTALL.md` documents `doctor`, an install dry run and onboarding; `wisp/update.py` checks release ordering and SHA-256 and asks before installation. The documented update does not restart the daemon. A successful file copy alone does not prove the user's assistant works.

### Requirements

- **R1:** Provide a documented one-line entry point to a versioned, integrity-verified release bootstrap and retain the existing agent-friendly runbook. No blindly executed unverified downloaded payload; explain the bootstrap's trust root and its own integrity limitations.
- **R2:** Preflight OS, architecture, available space, required dependencies, current installation, permissions and relevant optional capabilities; clearly distinguish blocking failures from optional degradation.
- **R3:** Preview writes, service actions, downloads, size, existing user modifications and permissions. Require explicit consent before changes, network downloads, paid provider checks and privileged actions. Never read or display secret values.
- **R4:** Preserve config, keys, memories, skills, user documents and unrelated services. Before an update, protect managed installation files and service state sufficiently for tested recovery. Report the exact scope: a managed-file backup is not a filesystem snapshot.
- **R5:** Execute stages visibly, with meaningful status and failure messages; make reruns safe. Verify installed version, service/IPC and available local prerequisites. Treat microphone permission and a spoken turn as user-confirmed checks; never report unperformed checks as passed.
- **R6:** On failure, preserve evidence and offer a tested restoration path. If recovery is incomplete, stop and explain the remaining manual steps; do not imply that external state or user data was rolled back.
- **R7:** Identify cleanup candidates only after verification. Preview paths and sizes; never delete user data or old installations without specific user confirmation.
- **R8:** Guide OpenRouter, speech and optional OpenCode setup through existing onboarding, using supported secure credential mechanisms. Missing or incompatible optional components must not block basic installation. Do not force a provider or download model weights.
- **R9:** Treat local LFM as an opt-in experiment until matched real-task tests demonstrate a suitable accuracy, latency, resource and safety bar. Compare local and cloud on identical fixtures; distinguish the screen-description lane from the reasoning/agent lane and do not promote based on the small synthetic trial.
- **R10:** Release readiness includes isolated install, interrupted update, restoration and onboarding tests, plus a representative machine smoke test. Report unavailable checks rather than silently passing them.

### Scope Boundaries

- Initial target is the Linux/Omarchy deployment supported by the current runbook; other OSes are later work.
- This is a plan, not permission to run an installer, obtain credentials, restart services, call paid models, or remove files.
- OpenCode is a potential agent integration, not an assumed installed dependency or established default runtime.

## Planning Contract

### Key Technical Decisions

- **KTD1:** Extend existing `wisp/update.py`, installer and `wisp/onboard.py`; retain one source of truth for checks rather than a second installer.
- **KTD2:** Use a recoverable transaction over Wisp-owned managed files, not a presumed system-wide snapshot. Record staged inputs, pre-change manifest and service state before mutation. Never restore over independently changed user data.
- **KTD3:** A bootstrap retrieves a pinned release with a documented independent integrity mechanism; if authenticity cannot be established, stop and direct the user to the manual verified install. An HTTPS download and checksum from the same endpoint alone do not authenticate a compromised publisher.
- **KTD4:** Local inference and OpenCode remain separately detectable, consented optional components. Record evidence and promotion criteria before changing defaults.

### High-Level Technical Design

`bootstrap -> preflight -> preview/consent -> stage + verify -> protect -> apply -> health checks -> success or recovery -> optional cleanup`

On a first install with no previous deployment, recovery removes only newly created managed artifacts after consent and otherwise reports manual cleanup. On update, restore the previous managed version only when the backup is complete and ownership is established.

### Dependencies and Risks

- Existing `wispd install` implementation and `wisp/svc.py` may modify plugin, launcher, desktop entry and bind files beyond the core directory. Inventory every managed path and establish per-path ownership before implementing rollback.
- Release signing, publication and bootstrap hosting must be available before claiming an authenticated one-line channel. Select a signing mechanism during implementation and document key rotation; do not silently weaken the integrity gate.
- App data may change during update: avoid copying secrets into logs or a broadly readable backup, and never restore mutable memories to an older state.
- Architecture guidelines consulted locally; shared architecture-memory service was unavailable. No new service or database is proposed.

## Implementation Units

### U1. Preflight and transaction inventory

**Files:** `wisp/update.py`, `wisp/svc.py`, installer entry point `wispd`, `docs/INSTALL.md`, `tests/test_install.py`, `tests/test_update.py`.

Map current writes, side effects and service ownership. Add structured preflight results and an accurate no-write preview shared by install and update. Include supported platform detection, disk headroom and optional capability checks.

**Tests:** clean HOME, existing customized files, insufficient space, unsupported architecture, absent systemd, and dry run with no writes or service actions. Existing update ordering and digest refusals remain intact.

### U2. Staging, recovery and post-update verification

**Files:** `wisp/update.py`, `wisp/deploy.py`, `wisp/svc.py`, `wispd`, `tests/test_update.py`, `tests/test_install.py`.

Stage and verify releases before mutation. Protect Wisp-managed paths and capture pre-update service state; preserve user content. Make apply, verification, restoration and interrupted-run recovery explicit, bounded and idempotent. Require approval before any restart, destructive cleanup or rollback that overwrites changed files.

**Tests:** digest mismatch before mutation; interrupted staging and apply; service/IPC failure; restoration success and failure; changed user config remains intact; repeated recovery; no deletion of unowned files; accurate installed-version reporting.

### U3. Bootstrap and onboarding

**Files:** `docs/INSTALL.md`, release/packaging configuration discovered during implementation, `wisp/onboard.py`, `tests/test_onboard.py`, `tests/test_install.py`.

Design and ship the minimal bootstrap only after KTD3's release trust prerequisite is met. Connect it to the existing consent-based install and onboarding. Detect OpenCode and local inference without installing or enabling either automatically. Secret handling uses existing supported keyring flows and never logs values; an interactive user handles permissions and voice verification.

**Tests:** first install with no keys, user declines each optional step, unavailable OpenCode or keyring, missing microphone permission, disconnected network, retry and verified-artifact failure. Assert no paid calls or model downloads without consent.

### U4. Local model promotion gate

**Files:** `scripts/lfm_eval.py`, `tests/fixtures/lfm_gate.jsonl`, `tests/test_lfm_eval.py`, `docs/research/2026-10-28-lfm-local-spike.md`.

Extend evaluation with privacy-safe, consented realistic fixtures and identical local/cloud task inputs. Predeclare objective outcomes, latency percentiles, failure categories, cost and hardware environment. Include screen understanding and synthesis separately, repeated runs and a held-out set; report confidence and limitations. Establish thresholds with the owner before any default change.

**Tests:** scoring and missing-answer handling; fixture provenance; equivalent inputs across providers; p50/p90 and per-lane aggregation; unavailable provider; no credentials in output. Actual cloud calls require explicit spending approval and the designated evaluation credential.

### U5. Operator experience and release gate

**Files:** `docs/INSTALL.md`, `docs/ROADMAP.md`, `tests/test_install.py`, `tests/test_update.py`, applicable CLI help golden fixtures.

Document each stage, confirmations, failure recovery, offline and degraded operation, and retention boundaries. Add release checklist evidence for isolated first install and update, recovery failure injection and an interactive voice smoke test. Record skipped checks and manual follow-up.

**Tests:** end-to-end temporary HOME without real user data; no consent causes no writes; malformed archives and interrupted updates; no cleanup before verification or user approval; failures displayed without secrets.

## Verification Contract

- Run targeted `tests/test_install.py`, `tests/test_update.py`, `tests/test_onboard.py`, `tests/test_lfm_eval.py`, and relevant service tests in isolated temporary homes.
- Verify user-facing CLI examples and goldens; exercise recovery failure injection before any real deployment.
- For release evidence, record OS, architecture, release identifier, checks performed and skipped, and the outcome of the user-confirmed voice test.
- Local-model results must not be described as production-ready until the agreed gate passes on real tasks.

## Definition of Done

R1-R10 have corresponding tests and honest operator-facing results; release trust and recovery are demonstrated; optional components do not silently change defaults; existing user data remains intact. Any unavailable or manual validation is explicitly recorded.
