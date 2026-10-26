---
title: Linux-Only Purge - Plan
type: refactor
date: 2026-10-25
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
---

# Linux-Only Purge - Plan

## Goal Capsule

- **Objective:** Wisp's code, tests, CI and docs describe and exercise one platform, Linux (Hyprland/Omarchy), so every change costs one implementation and one CI run instead of three.
- **Means:** Delete the Windows and macOS branches and the TCP IPC transport, keep `wisp.platform.current()` as a constant `"linux"` shim (KTD1), and drop macOS/Windows CI and release targets.
- **Authority:** Phase 3 of `docs/plans/2026-10-25-1625-feat-wisp-heyclicky-linux-roadmap-plan.md` (on PR #139).
- **Execution profile:** Three disjoint units, implemented in parallel; the full Python suite and the Linux CI jobs must pass.
- **Stop conditions:** Stop if a removal changes Linux behavior (any Linux test changes its expectation rather than losing a non-Linux case), or if `rs/` or `tests/fixtures/ipc_commands.jsonl` would change.
- **Who finishes:** This run's PR.

---

## Product Contract

### Summary

Remove every Windows- and macOS-only code path, test, CI job, release target and doc, leaving Linux behavior unchanged.

### Problem Frame

Wisp carries per-OS branches in `wisp/platform.py` and a dozen callers, Windows job-object handling in `wisp/cancel.py`, a TCP IPC transport that exists only for Windows, macOS/Windows default-app tables, a Windows install branch in `wispd`, and macOS/Windows CI and release targets. macOS CI alone produced most of the flaky reruns on PRs #139 and #141.

### Requirements

- R1. No production code path branches on Windows or macOS; Linux behavior is unchanged.
- R2. The IPC transport is the Unix socket only.
- R3. CI runs Linux only; release builds Linux archives only.
- R4. Docs describe Linux only; `docs/MACOS.md` and `docs/WINDOWS.md` are gone and nothing links to them.

### Key Decisions

- **Linux only.** Governs R1–R4. (session-settled: user-directed — chosen over "Linux first, keep seams": seams cost upkeep for platforms nobody runs.)
- **`rs/` frozen; `tests/fixtures/ipc_commands.jsonl` byte-identical.** (session-settled: user-directed — chosen over keeping Rust parity or deleting `rs/`.) The Rust CI job keeps running on Linux only.

### Scope Boundaries

- Out: the Rust crate's own platform code (frozen).
- Out: `tests/shorttmp.py` — open PR #141's tests import it; it is harmless on Linux.
- Out: dated plans and research docs (historical record).

---

## Planning Contract

### Key Technical Decisions

- KTD1. **Keep `wisp.platform.current()` returning `"linux"`.** `config.py` and other modules call it at import time and many tests patch it; deleting it would churn every caller for no behavior change. Delete every non-Linux branch around it, and the `WISP_OS` override if only tests use it to select non-Linux paths.
- KTD2. **Delete non-Linux test cases, never rewrite Linux expectations.** A test that only exercises a Windows/macOS branch is deleted; a test that exercises both keeps its Linux assertions unchanged.
- KTD3. **Expect rebase conflicts with #139/#141.** This branch starts from `origin/master`; `wispd`, `wisp/ipc.py`, `wisp/config.py` and `wisp/agents.py` also change there. Whichever merges second rebases; no stacking.

---

## Implementation Units

### U1. Platform layer and its callers

- **Goal:** `wisp/platform.py` and its callers carry Linux code only.
- **Requirements:** R1; KTD1, KTD2.
- **Files:** `wisp/platform.py`, `wisp/agents.py`, `wisp/cua.py`, `wisp/notify.py`, `wisp/pointer.py`, `wisp/skills.py`, `wisp/tools/adapters.py`, `wisp/tools/desktop.py`, any other `wisp/` module with a `darwin`/`win32`/`macos`/`windows` branch, `tests/test_platform.py`, `tests/test_adapters.py`, other tests that only cover removed branches.
- **Approach:** Remove each non-Linux branch and helper (PowerShell/osascript/SendKeys, `.app` catalogs), keep the Linux path verbatim, keep `current()` per KTD1.
- **Test scenarios:** Test expectation: none new — Linux tests must pass unchanged; deleted tests are only those that exercise removed branches.
- **Verification:** `grep -rniE 'win32|darwin|osascript|powershell|\bmacos\b|\bwindows\b'` over `wisp/` and `wispd` finds no live code path (comments describing history excepted); suite green.

### U2. Process, IPC, install and config

- **Goal:** Remove Windows job objects, the TCP IPC transport, the Windows install branch and non-Linux default apps.
- **Requirements:** R1, R2; KTD2.
- **Files:** `wisp/cancel.py`, `wisp/ipc.py`, `wispd`, `wisp/config.py`, `tests/test_ipc_tcp.py`, `tests/test_cancel.py` (Windows cases only), `docs/CONFIG.md` / `docs/IPC_CONTRACT.md` where they document the removed pieces.
- **Approach:** Unix-socket-only IPC; `_DEFAULT_APPS` keeps the Linux table; drop the Windows `install_files` branch and Windows job-object/taskkill code.
- **Test scenarios:** Test expectation: none new — the Unix-socket IPC, cancel and install tests stay unchanged and green.
- **Verification:** Suite green; `tests/fixtures/ipc_commands.jsonl` and `rs/` byte-identical to master.

### U3. CI, release and docs

- **Goal:** CI and releases are Linux-only; docs describe Linux only.
- **Requirements:** R3, R4.
- **Files:** `.github/workflows/test.yml`, `.github/workflows/release.yml`, `docs/MACOS.md` (delete), `docs/WINDOWS.md` (delete), `docs/INSTALL.md`, `README.md`, `INDEX.md`, `docs/ARCHITECTURE.md`, other top-level docs that link the deleted files.
- **Approach:** Drop the macOS entries from the unit and rust job matrices and the macOS/Windows release targets and staging steps; remove doc sections and links for the deleted platforms.
- **Test scenarios:** Test expectation: none — CI config and docs; the docs lint test covers dangling references.
- **Verification:** Docs lint passes; workflow YAML parses; CI on the PR runs Linux jobs only.

---

## Verification Contract

| Gate | Command | Applies to |
|---|---|---|
| Python suite | `python3 -m unittest discover -s tests` | U1–U3 |
| Docs lint | included in the suite | U3 |
| Parity | `git diff --quiet origin/master -- rs tests/fixtures/ipc_commands.jsonl` | all |
| CI | Linux unit + rust jobs on the PR | U3 |

---

## Definition of Done

- No non-Linux code path remains in `wisp/` or `wispd`; Linux tests pass unchanged.
- CI and release are Linux-only; the two platform docs are deleted with no dangling links.
- `rs/` and the parity fixture are unchanged.
