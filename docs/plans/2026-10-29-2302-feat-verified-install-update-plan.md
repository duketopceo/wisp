---
title: Verified Install and Update
type: feat
date: 2026-10-29
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
deepened: 2026-10-30
---

# Verified Install and Update

**Status (2026-10-31):** U1, U2, U3 and U5 merged in #256; first-run readiness validation in #264. Deferred as listed in this plan: the signed one-line bootstrap (needs an independently distributed key), U4, first-install recovery, plugin/units/desktop/bind rollback and R7 cleanup tooling.

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

Grounding (verified against master 47d1066, after PR #241): `wisp/update.py` already verifies SHA-256 (asset digest, `SHA256SUMS` or `--sha256`), refuses non-newer releases, extracts to a temp tree and shells out to `wispd install` from that tree, which does not restart the daemon. `wispd install` (`install_files` in `wispd`) mirrors `wisp/`, `shells/`, `wispd`, the shell plugin, desktop files and units, then writes `deploy.json`. A release-tarball install records `ref=None, commit=unknown`, so `installed_version()` reads `unknown` after an update; U2 fixes that. `wisp/onboard.py` already owns the first-run checklist including the agents step (#241). `wispd doctor` prints rows; `wisp/svc.py` owns units and `doctor_rows`. Pinned-download precedent: `wisp/agent_install.py` and `scripts/cua/`.

Scope of this plan's first delivery: U1, U2, U3 (docs, trust statement and onboarding guarantees) and U5. The one-line bootstrap script (R1, KTD3 prerequisite) and U4 (R9) are deferred; see Deferred to Follow-Up Work.

### Deferred to Follow-Up Work

- **Bootstrap script (R1).** Blocked by KTD3: releases publish only a same-endpoint digest, with no independent signing key. This delivery documents the trust root and its limit in `docs/INSTALL.md`; it ships no `curl | sh`.
- **U4 local-model promotion gate (R9).** Its files (`scripts/lfm_eval.py`, `tests/fixtures/lfm_gate.jsonl`, the LFM spike doc) exist only in open PR #239 and thresholds need the owner. No default changes here.
- **First-install recovery (R6, first install branch).** Removing newly created managed artifacts needs a created-file manifest in `wispd install`; this delivery keeps the documented Uninstall steps and states that limit.
- **R7 cleanup tooling.** This delivery builds no cleanup candidate listing; U5 documents the retained update backups under `~/.local/state/wisp/update/` and how to remove them by hand. Nothing is deleted automatically.
- **Recovery of the shell plugin directory, unit files, desktop entry and Hyprland bind.** Not captured by the update backup; the report names them as outside rollback scope.

### U1. Preflight and shared preview

**Goal:** One structured preflight used by `install --dry-run`, `update` and `doctor`.

**Files:** new `wisp/preflight.py`, `wispd` (`install_files` dry run and a pre-write gate), `wisp/update.py` (`describe`), `wisp/cli/core.py`, `docs/INSTALL.md`, `tests/test_preflight.py` (new), `tests/test_install.py`, `tests/test_update.py`.

**Approach:** `preflight.run(home, opt, ...)` returns rows `{id, level: block|degraded|ok, detail, fix}` for OS (Linux only), architecture (x86_64/aarch64), Python version, free space under `home` against a stated headroom, systemd user availability (degraded: files install, units not started), optional capabilities (hyprctl, pw-record, wtype, grim, opencode, ollama/llama endpoint) as degraded and never block, current installation (version, deploy record, customized desktop file) and the writes the install would make. Injectable seams (`machine`, `disk_free`, `which`, `systemd`) keep tests offline. A `block` row stops a real install or update before any write with a `Try:` line; `--dry-run` prints rows and the write list and exits 0 or 4 like doctor. Never reads `.env` or key values.

**Test scenarios:** clean HOME lists every would-be write and writes nothing; insufficient space and unsupported architecture block with a fix line; absent systemd degrades without blocking; edited `wisp.desktop` reported as an existing user modification; optional tools missing never block; dry run starts no service and makes no network call; existing update ordering and digest refusal tests still pass.

### U2. Staging, protected apply, verification and rollback

**Goal:** `wispd update` becomes a recoverable transaction over Wisp-managed files in the opt dir.

**Files:** `wisp/update.py`, `wisp/cli/core.py` (flags `--restart`, `--rollback`), `wisp/deploy.py`, `tests/test_update.py`, `tests/test_install.py`, golden `tests/golden/cli_help/daemon_update.txt`.

**Approach:** Per KTD2. Stage and verify as today. Before apply, write a backup under `~/.local/state/wisp/update/<id>/` (owner-only mode) holding copies of the opt-dir managed files (the set `install_files` writes under the opt dir: `wisp/`, `shells/`, `wispd`, `build_harness.py`, `CHANGELOG.md`, `deploy.json`; this list is authoritative and the Grounding paragraph's mirror list is read as the same set) and an atomic `manifest.json`: from/to versions, per-path sha256 before and after, whether `wispd.service` was active, and a `phase` (`staged`, `applying`, `applied`, `verified`, `restored`, `restore-incomplete`). Config, keys, memories, skills and documents are not in scope and never read. After `install_fn`, record the release tag in `deploy.json` (fixes `unknown` after tarball installs) and verify that every staged file matches the install and the recorded version equals the tag. A restart happens only with `--restart` and a yes; if the daemon was active, verify IPC answers afterwards and report the result. `--rollback` restores the last manifest after a yes: outside an interrupted apply, a file is restored only when its current hash equals the expected post-update hash (unchanged since the update), and a file that differs is left and listed; a file the update added is removed only when its hash matches the staged hash. Backup, restore and added-file removal act only on regular files whose resolved path is inside the opt dir, never follow symlinks, store manifest paths relative and reject absolute or `..` paths; anything else is skipped and listed. The state tree is created 0700 and backup files and `manifest.json` (and its temp file) 0600. Expected post-update hashes come from the staged tree and are recorded before apply (`deploy.json` is hashed after its tag write); `__pycache__` is excluded everywhere. Rollback classifies each path against three hashes by phase: in `applying`, a file matching neither the pre-update nor the expected post-update hash is an interrupted-apply leftover and is restored from backup; in `applied` or `verified`, a file differing from the expected post-update hash is a user edit and is left and listed. `update.py` imports every module needed for verification and rollback before calling `install_fn`, and IPC verification runs in a fresh subprocess of the installed `wispd`. `--restart` prints the same plugin/unit scope warning before asking. Files under managed dirs that are not in the manifest (bytecode caches, runtime files) are unmanaged: left alone and not listed as user edits. After restoring, `--rollback` offers a restart (with a yes) when the manifest says the service was active, then verifies IPC and reports that as the outcome. The update preview warns when the staged tree changes the shell plugin, units or desktop files, because rollback does not cover them and a restore can leave old core code with new plugin files. For this delivery R4/R6 "managed files" means the opt-dir set above. Rerunning is idempotent; a manifest in `applying` is offered for rollback on the next `wispd update`. The report states plainly that this is a managed-file backup, not a filesystem snapshot, and that external state and user data were not rolled back.

**Test scenarios:** digest mismatch leaves opt dir and state dir untouched; installer failure mid-apply leaves manifest `applying` and rollback restores originals; verification mismatch reports failure and does not claim success; daemon not restarted without `--restart`; IPC failure after restart reports rollback available; user-edited managed file is skipped by rollback and listed; update-added file with changed content is kept; rollback twice is a no-op; unowned files under opt dir and sibling config files are never deleted; installed version reads the tag after update; backup tree modes are 0700/0600; symlinked managed path and tampered manifest path are skipped and listed; extra runtime file in `wisp/` survives rollback unlisted; rollback after a failed post-restart IPC check offers restart and reports the verified result.

### U3. Trust statement and onboarding guarantees

**Goal:** Honest install trust documentation and tests that onboarding degrades gracefully.

**Files:** `docs/INSTALL.md`, `wisp/onboard.py` (only if a test exposes a gap), `tests/test_onboard.py`, `tests/test_install.py`.

**Approach:** Document the release trust root (GitHub release over HTTPS, digest from the same publisher, `--sha256` from an independent source) and that it does not defend against a compromised publisher. Reuse the existing onboarding agents step and keyring flow; assert that declining or lacking OpenCode, keyring, microphone or network leaves the install usable, that no download or paid call happens without consent, and that failures never echo secrets.

**Test scenarios:** no keys at first run; each optional step declined; OpenCode absent; keyring unavailable; no network; retry after failure; no secret value in any output.

### U5. Operator documentation and release gate

**Goal:** Operators can follow each stage and know what a release must prove.

**Files:** `docs/INSTALL.md`, `docs/ROADMAP.md`, `tests/test_install.py`, `tests/test_update.py`, `tests/golden/cli_help/daemon_update.txt`, `tests/golden/cli_help/daemon_install.txt`.

**Approach:** Document stages, consents, failure recovery, offline and degraded operation and retention limits. Add a release checklist (isolated first install and update, failure injection, interactive voice smoke test; record OS, arch, release id, checks run and skipped). Docs must pass docs, copy and trust lint tests; regenerate goldens with `WISP_UPDATE_GOLDEN=1`.

**Test scenarios:** end-to-end update in a temporary HOME with no real user data; no consent causes no writes; malformed archive refused; no cleanup before verification; error text carries no secrets.

## Verification Contract

- Run targeted `tests/test_install.py`, `tests/test_update.py`, `tests/test_onboard.py`, `tests/test_preflight.py`, and relevant service tests in isolated temporary homes.
- Verify user-facing CLI examples and goldens; exercise recovery failure injection before any real deployment.
- For release evidence, record OS, architecture, release identifier, checks performed and skipped, and the outcome of the user-confirmed voice test.
- Local-model work (U4) is deferred; no local-model default changes and no readiness claim here.

## Definition of Done

R2-R8 and R10 have corresponding tests and honest operator-facing results for the delivered units (R6 for the update path only; R1 satisfied by the documented trust statement, not a bootstrap script; R7 by documentation); R9, the bootstrap script and first-install recovery are tracked under Deferred to Follow-Up Work and are not part of done; update recovery is demonstrated by failure injection in temporary homes; optional components do not silently change defaults; existing user data remains intact. Any unavailable or manual validation is explicitly recorded.
