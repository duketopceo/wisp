---
title: Hosted Install - Plan
type: feat
date: 2026-10-26
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
---

# Hosted Install - Plan

## Goal Capsule

- **Objective:** A fresh Linux box gets a working Wisp from `wispd install` + `wispd onboard` with only hosted services: speech-to-text, brain and keys work without any local model, a missing key says what to do instead of failing a turn, and the owner can redeploy any git ref and see which commit is running.
- **Means:** Hosted STT as the shipped default (U1); a keys step in onboarding plus soft-fail on key lookup (U2); `wispd install --ref` with a recorded deployed commit (U3); a clean-box test and the hotkey false-positive fix (U4).
- **Authority:** Phase 6 of `docs/plans/2026-10-26-0031-feat-wisp-v1-roadmap-plan.md` (roadmap R1 redeploy-and-measure, R2 hosted install — not this plan's R1/R2). Tracker: Tallyline TLY-200.
- **Execution profile:** U1 → U2 → U3 → U4, serial; full Python suite green after each.
- **Stop conditions:** Stop if any change would alter `rs/` or `tests/fixtures/ipc_commands.jsonl`, or would turn a local model server back on by default.
- **Who finishes:** This run's PR (#146). Q4 settled by the owner on 2026-10-26: Groq.

---

## Product Contract

### Summary

Ship hosted speech-to-text (Groq) as the default, make onboarding collect the OpenRouter and STT keys, turn key-lookup failures into a clear spoken/notified "key missing" message, let `wispd install` deploy a named git ref and record what it deployed, prove it all on a clean HOME, and stop `wispd install` warning about its own hotkey.

### Problem Frame

Today's shipped config defaults `[stt] provider = "local"` (whisper.cpp), so a new box needs a local model before the first turn, which contradicts the hosted-only direction. Onboarding checks mic, models, cua, notifications and keybinding but never asks for an API key, and a missing key surfaces as a `RuntimeError` mid-turn (`wisp/stage_capture.py` `_transcribe_openai`). `wispd install` copies only from the checkout it is run from, and nothing records which commit is deployed — R0 on 2026-10-26 had to infer that the running daemon was an Oct 21 build. During that redeploy `install_bind` (`wispd`) warned that SUPER + D was taken; the "conflict" was the `-- Wisp push-to-talk (Super + D)` comment above wisp's own bind.

### Requirements

- R1. With no `[stt]` section in the user config, Wisp transcribes through an OpenAI-compatible hosted endpoint, Groq by default (`base_url` `https://api.groq.com/openai/v1`, `whisper-large-v3-turbo`); `provider = "local"` still selects whisper.cpp when set explicitly.
- R2. `wispd onboard` has a keys step that reports, for the brain (OpenRouter) and the configured STT provider, whether a key resolves; when one does not, it offers to store one where the configured lookup will find it — at the `omaseal://` ref in that key's lookup list when there is one and `omaseal` is on PATH, else in `~/.config/wisp/.env` — and never prints the value.
- R3. When a turn needs a key that does not resolve, the turn ends with a short user-visible message naming the missing key and `wispd onboard` (spoken/notified like other turn errors), not a traceback; a slow or failing `omaseal` lookup cannot hang a turn.
- R4. `wispd install --ref <git-ref>` installs that ref from the source repository (the checkout it last installed from, or `--repo <path>`), without touching the working tree; every install records the source repo, commit and time, and `wispd status` (or `health`) shows the deployed commit.
- R5. A clean-box test installs into an empty temporary HOME with default config and no keys, and asserts: files land, no local-model unit is installed, onboarding reports the keys step as todo, and a turn needing STT returns the R3 message.
- R6. `wispd install` does not warn about a hotkey conflict when the only matching lines are wisp's own bind or its comment marker.

### Key Decisions

- **Hosted only by default.** Governs R1, R5. (session-settled: user-directed — chosen over keeping local models on by default: the owner never uses them.)
- **Linux only.** Governs R4, R5. (session-settled: user-directed — chosen over cross-platform seams.)
- **Groq is the default STT provider.** Governs R1. (session-settled: user-directed, 2026-10-26 — chosen over another OpenAI-compatible provider: already live on this machine and cheap.) Any OpenAI-compatible endpoint stays configurable.

### Scope Boundaries

- Out: streaming STT and barge-in (Phase 7).
- Out: packaging (AUR/pip) — the install path stays `wispd install` from a checkout.
- Not built: verifying keys against the provider during onboarding (a network call per key). A key that resolves but is wrong already fails the first turn with the provider's error; revisit if that error proves unclear.
- Not built: removing whisper.cpp support — it stays as an explicit opt-in.
- Not built: a cache of omaseal misses. The short lookup timeout already bounds a turn (R3); a cache in the long-lived daemon would keep reporting a key as missing after `wispd onboard` stores it. Revisit only if timeouts show up in turn latency.

### Outstanding Questions

- Q4. Settled 2026-10-26 by the owner: Groq is the hosted STT default.

---

## Planning Contract

### Key Technical Decisions

- KTD1. **One STT-settings helper owns the defaults.** `load_config` does not merge defaults into an existing file, and `wisp/stage_capture.py` and `wisp/onboard.py` read `provider` with a hard-coded `"local"` fallback (and `cfg["stt"]` directly). A helper in `wisp/config.py` overlays the hosted defaults (`provider = "openai"`, Groq base URL and model, `key_env = "GROQ_API_KEY"`) on whatever `[stt]` keys the user set, and every reader goes through it. The schema default for `stt.provider` becomes `openai` (`shell-plugin/lib/settings_schema.js` regenerated). Configs that set `[stt]` keys keep them; the live omaseal config keeps `omaseal://groq/default,GROQ_API_KEY`.
- KTD2. **Soft-fail is a new closed-set error code.** Turn errors are the closed `CODES` set in `wisp/errors_codes.py` with copy in `wisp/copy.py`; an unknown exception becomes `internal`. Add `key_missing` (copy names the key and `wispd onboard`), raised by one required-key helper that `load_api_key`, the STT path and every turn-path OpenRouter lookup (`route.py`, `stage_route.py`, brain) use — only for providers that declare a `key_env`, so keyless local brains are unaffected. `load_env_key`'s omaseal call gets a short timeout (seconds, not 10); no miss cache (see Scope Boundaries).
- KTD3. **Ref installs export, they do not check out:** `git archive <ref>` (or a temporary worktree) of the source repo into a temp dir, then the existing `install_files` from that dir. The deploy record is a small JSON file in `~/.local/opt/wisp/` written by `install_files`.
- KTD4. **rs/ frozen.** (session-settled: user-directed — chosen over Rust parity.) No Rust or `tests/fixtures/ipc_commands.jsonl` change; if `status` gains a field it is Python-only.

---

## Implementation Units

### U1. Hosted STT default

- **Goal:** R1.
- **Requirements:** R1; KTD1.
- **Files:** `wisp/config.py` (the STT-settings helper, default config text), `wisp/stage_capture.py` (provider fallback, `cfg["stt"]`, trace field), `wisp/onboard.py` (`_whisper_ok` via the helper), `wisp/settings_schema.py`, `shell-plugin/lib/settings_schema.js` (regenerated), `docs/CONFIG.md`, `docs/INSTALL.md`, `tests/test_config.py` or the existing config test module.
- **Approach:** add the helper, route the three `[stt]` readers through it, flip the shipped default text. `_whisper_ok` already skips the whisper model for a non-local provider; it only needs the helper.
- **Test scenarios:**
  - Config dict with no `stt` key → `transcribe` takes the hosted path (no KeyError) and `_check_mic` passes without a whisper model.
  - `[stt]` with only `prompt` set → provider still `openai`, prompt kept.
  - `provider = "local"` in user config → whisper.cpp path chosen, mic check still requires the model.
- **Verification:** suite green; `gen_settings.py --check` clean.

### U2. Keys onboarding step and soft-fail

- **Goal:** R2, R3.
- **Requirements:** R2, R3; KTD2.
- **Dependencies:** U1.
- **Files:** `wisp/onboard.py` (new `keys` step and check), `wisp/config.py` (`load_env_key` timeout, required-key helper, `load_api_key`), `wisp/errors_codes.py`, `wisp/copy.py`, `shell-plugin/lib/copy.js` (regenerated), `docs/IPC_CONTRACT.md`, `wisp/stage_capture.py`, `wisp/brain.py`, `wisp/route.py`, `wisp/stage_route.py`, `tests/test_onboard.py`, `tests/test_stage_capture.py` or the nearest existing test module, CLI help goldens if `onboard` output is pinned.
- **Approach:**
  1. Keys check resolves the brain and STT `key_env` lists and reports which are missing.
  2. The run step prompts through the existing `walk` ask/out callbacks. It stores at the `omaseal://` ref in that key's lookup list when there is one and `omaseal` is on PATH; otherwise it writes `~/.config/wisp/.env`, opened with mode 0600 and forced to 0600 if it already exists, rejecting values with whitespace or newlines.
  3. Turn-path key lookups raise `key_missing` (KTD2); the existing error path renders its copy.
- **Patterns to follow:** existing `Step`/`_CHECKS`/`run_step` shape in `wisp/onboard.py`; omaseal resolution in `config.load_env_key`.
- **Test scenarios:**
  - Both keys resolve → keys step `ok`.
  - STT key missing → `todo` naming `GROQ_API_KEY`.
  - Storing without omaseal writes `.env` with 0600 and the value never appears in step output.
  - A pre-existing 0644 `.env` is 0600 after a store; a value containing a newline is refused.
  - With `key_env = "omaseal://groq/default,GROQ_API_KEY"` and a fake `omaseal`, the stored key is written at that ref and the keys step re-checks `ok`.
  - A turn with no STT key ends with `key_missing` naming `GROQ_API_KEY`, no traceback, and the daemon keeps serving.
  - A turn with no OpenRouter key ends with `key_missing` naming `OPENROUTER_API_KEY`.
  - `omaseal` hanging past the timeout → lookup falls through to env within the bound.
- **Verification:** suite green; onboarding status on this machine reports keys `ok` (read-only check).

### U3. Install from a git ref and record the deploy

- **Goal:** R4.
- **Requirements:** R4; KTD3, KTD4.
- **Dependencies:** none (can follow U2).
- **Files:** `wisp/cli/core.py` (`--ref`, `--repo` args), `wispd` (`install_files` source dir + deploy record), the `status`/`health` surface that reports versions, `docs/INSTALL.md`, `tests/test_install.py` (new) or an existing install test, CLI help goldens.
- **Approach:** resolve the repo (flag, else the recorded source), export the ref to a temp dir, install from it, write the record (repo, ref, commit, time). Running from the installed copy with `--ref` works because the repo comes from the record, not `__file__`. The first deploy of this feature still runs from a checkout (the installed copy predates `--ref`); `docs/INSTALL.md` says so.
- **Test scenarios:**
  - Install from a temp git repo at a tagged ref → files match that ref, record names its commit.
  - Uncommitted change in the source working tree is not installed with `--ref`.
  - Unknown ref → clear error, nothing written.
  - `--ref` with no record and no `--repo` → clear error naming `--repo`.
  - `wispd status` shows the recorded commit; absent record → "unknown".
- **Verification:** suite green; `wispd install --ref origin/master --dry-run` prints the plan.

### U4. Clean-box check and hotkey false positive

- **Goal:** R5, R6.
- **Requirements:** R5, R6; KTD4.
- **Dependencies:** U1, U2, U3.
- **Files:** `tests/test_clean_box.py` (new), `wispd` (`install_bind` conflict filter), `tests/test_install.py` or the existing bind test.
- **Approach:** `config.HOME` and friends are import-time constants, so the test drives `wispd` in subprocesses with a temp HOME/XDG and an explicit minimal environment (no `*_API_KEY` variables, no `omaseal` on PATH, `hyprctl`/`systemctl` stubbed), using the hermetic harness in `tests/cli_env.py`, and asserts nothing outside the temp HOME was written. The bind filter ignores lines containing `wisp-trigger` (already) and comment lines.
- **Execution note:** write the clean-box test first; it should fail on today's `master` default (`provider = "local"`).
- **Test scenarios:**
  - Clean HOME: install succeeds, no `llama-*`/`jev-shim` unit file, keys step `todo`, STT turn returns the missing-key message.
  - `bindings.lua` with only wisp's comment + bind → no warning.
  - `bindings.lua` with an unrelated `SUPER + D` bind → warning still printed.
- **Verification:** suite green.

---

## Verification Contract

| Gate | Command | Applies to |
|---|---|---|
| Python suite | `python3 -m unittest discover -s tests` | all |
| Generated settings | `python3 scripts/assets/gen_settings.py --check` | U1 |
| Parity | `git diff --quiet origin/master -- rs tests/fixtures/ipc_commands.jsonl` | all |

---

## Definition of Done

- R1–R6 covered by tests; suite and settings check green; parity untouched.
- PR body flags Q4 for the owner and notes that live configs with an explicit `[stt]` section are unchanged.
