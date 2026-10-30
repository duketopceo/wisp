---
title: "feat: Unify Wisp Voice-Act-Cursor Runtime, Drop Jev Latency, and Align Desktop Execution (HeyClicky Parity)"
type: feat
status: active
date: 2026-10-30
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
---

# Unify Wisp Voice-Act-Cursor Runtime, Drop Jev Latency, and Align Desktop Execution

## Overview

Wisp (`duketopceo/wisp`) already contains a 7-stage voice-to-desktop pipeline (`capture -> transcribe -> context -> route -> execute -> speak -> judge`), an `act` loop (`wisp/act.py`), a grounding cascade (`wisp/grounding.py`), a policy engine (`wisp/policy.py`), and a Quickshell companion (`shell-plugin/`). However, end-to-end execution currently breaks down across six seams when compared against HeyClicky (`duketopceo/clicky`) and Clacky:

1. **Grounding Latency & Dead Jev Endpoint**: When `control` and `a11y` miss on web canvases or custom UI, `grounding._jev` slices the screenshot into 40 PNG patches and POSTs them to `https://openrouter.ai/api/alpha/decisions` (`typesafe/jev-1.13`). Meanwhile, `pick_pointing_resolution()` (`1024x768`, `1280x800`, `1366x768`) and `scale_point_from_resolution()` were implemented in `wisp/grounding.py` (lines 146–199) for HeyClicky parity, but **no provider in `wisp/grounding.py` ever calls them**. Furthermore, `suggest._worth_mining()` still calls `pipeline.ask_jev` unconditionally even when `[brain] router = "act"`.
2. **Pointer Execution Stall (`auto` Mode Ignored)**: Even though `wisp/config.py` and `tests/test_pointer.py` specify `auto = drive when a backend exists, guide otherwise`, `wisp/tools/system.py` (`_pointer`), `wisp/delivery.py` (`planned`), `wisp/cua_safety.py` (`Guard.applies`), and `wisp/realinput.py` (`begin`) only check `mode == "drive"`. As a result, `pointer.mode = "auto"` never injects real clicks.
3. **Utterance & Routing Misalignment**:
   - `"check my email"`, `"check my Stripe"`, and `"debug this"` fall through `route.heuristic` to `default_answer` because `check`, `inspect`, `review`, `debug`, and `fix` are missing from `_ACT`.
   - `"open up this setting"` is hijacked by `stage_route.fuzzy_app` (`"settings"` substring match in `"thissetting"`) and launches the OS Settings app instead of clicking the on-screen setting.
   - `"show me what's wrong here"` is matched by `_OPEN_VERB` (`show me`) as an app launch instead of an on-screen visual question.
   - Background OpenCode spawns (`"debug this in the background"`, `"have opencode fix this"`) start in `out_dir` instead of inferring the active project working directory from the focused window/terminal/editor.
4. **Web Services & Tab-First Navigation (`email`, `Stripe`, `Linear`)**:
   - `config.WEB_DEFAULTS` only defines `mail` and `calendar`. Spoken requests like `"check my email"`, `"go to my Stripe"`, or `"go to my Linear"` fail to resolve `"my email"`, `"my stripe"`, or `"my linear"` to existing browser tabs or default web URLs (`dashboard.stripe.com`, `linear.app`, `github.com`, `notion.so`, `slack.com`).
   - `act._unsupported_done()` rejects `launch` calls when the focused browser window class (`chromium`) does not match the spoken service word (`stripe` or `email`).
5. **Sensitive Surface Policy (Stripe Read-Through vs. Mutation Gate)**:
   - On financial/billing surfaces like Stripe (`dashboard.stripe.com`), Wisp must **not** go blind (`capture_blocked` is reserved for password managers/polkit/sudo). Instead, Wisp must freely observe, read balances/webhooks/errors, move the guide cursor, and switch tabs (`T0`/`T1`), while promoting mutating actions (`click`, `type_text`, `key`, `fill`) to `T2` confirmation and refusing raw live secret keys (`sk_live_`, `rk_live_`, `whsec_`).
6. **UI/UX & Voice-Cursor Cohesion**:
   - `stage_capture.py` sleeps `0.25s` before every press-time screenshot even when `ask_chips` are not armed, and `buddy.js` waits `0.30s` (`ENTRY_DELAY_S`) before showing the cursor buddy.
   - `companion.js` hides the bottom pill during `deciding` and `acting` (`PILL_STATUSES = ["listening", "transcribing", "awaiting_choice"]`), creating dead visual air between hotkey release and the first spoken/acted output.

## Problem Frame

Khan needs Wisp to act immediately and reliably on natural voice commands:
- *"Check my email"* -> switches to an open Gmail/mail tab or opens mail immediately.
- *"Go to my Stripe"* -> switches to an open Stripe tab or opens `https://dashboard.stripe.com`, treats Stripe as a sensitive surface (read/inspect/point freely; confirm before clicking or typing mutations; block live secret key injection).
- *"Go to my Linear"* -> switches to an open Linear tab or opens `https://linear.app`.
- *"Open up this setting"* -> grounds the on-screen setting via fast control/a11y/VLM pointing and clicks it (instead of launching the OS Settings binary).
- *"Tell me what this does"* / *"Tell me what's wrong here"* / *"Show me what's wrong here"* -> routes to screen-grounded `answer` with `[POINT:x,y:label]` cursor choreography.
- *"Debug this"* / *"Have OpenCode debug this in the background"* -> routes to `act` or spawns OpenCode in the active project repo directory.

## Requirements Trace

- **R1 (Drop Jev Bottleneck & Wire Aspect-Matched VLM Pointing)**: Wire `pick_pointing_resolution()` and `scale_point_from_resolution()` into a single-image VLM pointing path (`_vlm`) in `wisp/grounding.py` so fallback grounding uses one aspect-matched vision call via `brain.chat` instead of 40 PNG crops to Jev alpha, while preserving all existing `test_ground_chain.py` contract tests. Gate `suggest._worth_mining()` so it skips `ask_jev` unless `brain.router == "jev"`.
- **R2 (Real Click Execution in `auto` / `act` Mode)**: Make `pointer.mode = "auto"` resolve and drive the detected pointer backend (`cua`, `ydotool`, `wlrctl`) across `wisp/tools/system.py`, `wisp/delivery.py`, `wisp/cua_safety.py`, `wisp/realinput.py`, and `wisp/act.py`, and upgrade unconfigured default pointer mode in live `stage_execute._run_act` turns when a backend is available.
- **R3 (Deictic UI Actions, Screen Questions & Background OpenCode Routing)**: Prevent `stage_route.fuzzy_app` and `route._catalog_app` from hijacking deictic phrases (`this`, `that`, `these`, `those`, `here`, e.g. `"open up this setting"`). Route `"check ..."`, `"inspect ..."`, `"debug ..."`, `"fix ..."` to `act` (or `agent` when background/OpenCode is named). Route `"show me what's wrong here"` to `answer`. Infer repo `cwd` in `agents.spawn()` when not explicitly provided.
- **R4 (Web Services & Tab-First Resolution for Email, Stripe, Linear, GitHub, Notion, Slack)**: Normalize spoken possessive/service aliases (`"my email"`, `"my stripe"`, `"my linear"`), check open CDP browser tabs first (`SWITCHED tab ...`), fall back to opening the service URL (`WEB_DEFAULTS`), and teach `act._unsupported_done` that switching/opening a service in a browser satisfies a service navigation task.
- **R5 (Sensitive Surface Policy for Stripe & Financial Apps)**: Add `BUILTIN_SENSITIVE_SURFACES` and `cua_safety.sensitive_surface()`. Keep screen capture and read/navigation tools (`screenshot`, `observe`, `ground`, `move`, `scroll`, `tab`, `launch`, `focus`) unblocked on Stripe, promote mutating input tools (`click`, `type_text`, `key`, `fill`) to `T2` confirmation on sensitive surfaces, and preempt typing live secret keys (`sk_live_`, `rk_live_`, `whsec_`).
- **R6 (Low-Latency Capture & Continuous Companion Feedback)**: Only sleep before press-time capture when `ask_chips` are actually armed, tighten `ENTRY_DELAY_S` in `shell-plugin/lib/buddy.js`, and keep the status pill visible during `deciding` and `acting` in `shell-plugin/lib/companion.js` when no bubble or confirm card is up.

## Scope Boundaries

- Preserve all existing CLI, config schema (`wisp/settings_schema.py`), and test suite invariants (`3,525` existing unit tests).
- Do not break `tests/test_ground_chain.py`, `tests/test_settings_schema.py`, `tests/test_delivery.py`, `tests/test_pointer.py`, or `tests/test_policy.py`.

## Implementation Units

- [x] **Unit 1 (U1): Aspect-Matched VLM Grounding & Jev De-bottlenecking**
  - **Goal**: Replace 40-crop Jev alpha fallback latency with single-shot aspect-matched VLM pointing (`pick_pointing_resolution` + `scale_point_from_resolution`) and bypass `ask_jev` in `suggest.py` when `brain.router != "jev"`.
  - **Requirements**: R1
  - **Files**:
    - `wisp/grounding.py`
    - `wisp/suggest.py`
    - `tests/test_heyclicky_delta.py`
  - **Verification**: `python3 -m unittest tests/test_ground_chain.py tests/test_heyclicky_delta.py tests/test_suggest.py`

- [x] **Unit 2 (U2): Pointer Execution Alignment (`auto` Mode Drives Backend)**
  - **Goal**: Ensure `pointer.mode = "auto"` drives real clicks when a pointer backend exists, and ensure live `act` turns with default config auto-drive when a backend is available.
  - **Requirements**: R2
  - **Files**:
    - `wisp/tools/system.py`
    - `wisp/delivery.py`
    - `wisp/cua_safety.py`
    - `wisp/realinput.py`
    - `wisp/act.py`
    - `wisp/stage_execute.py`
    - `tests/test_pointer.py`
    - `tests/test_delivery.py`
  - **Verification**: `python3 -m unittest tests/test_pointer.py tests/test_pointer_precedence.py tests/test_delivery.py tests/test_act.py`

- [x] **Unit 3 (U3): Utterance Routing, Deictic Disambiguation & Background OpenCode CWD**
  - **Goal**: Fix routing for `"check my email"`, `"go to my Stripe"`, `"go to my Linear"`, `"open up this setting"`, `"tell me what this does"`, `"tell me what's wrong here"`, `"show me what's wrong here"`, and `"debug this"` / `"have opencode debug this"`, plus active repo `cwd` inference for spawned coding agents.
  - **Requirements**: R3
  - **Files**:
    - `wisp/route.py`
    - `wisp/stage_route.py`
    - `wisp/agents.py`
    - `tests/test_route.py`
    - `tests/test_stage_route.py`
    - `tests/test_agents.py`
  - **Verification**: `python3 -m unittest tests/test_route.py tests/test_stage_route.py tests/test_agents.py`

- [x] **Unit 4 (U4): Web Services (`email`, `Stripe`, `Linear`) & Tab-First Navigation**
  - **Goal**: Resolve spoken service aliases (`email`, `stripe`, `linear`, `github`, `notion`, `slack`) in `desktop.launch` and `desktop.tab`, switch to an open browser tab first when CDP is available, open the service URL otherwise, and recognize service navigation in `act._unsupported_done`.
  - **Requirements**: R4
  - **Files**:
    - `wisp/config.py`
    - `wisp/tools/desktop.py`
    - `wisp/act.py`
    - `tests/test_desktop_tools.py`
    - `tests/test_act.py`
  - **Verification**: `python3 -m unittest tests/test_desktop_tools.py tests/test_act.py`

- [x] **Unit 5 (U5): Sensitive Surface Policy (Stripe Read-Through + Mutation Gate)**
  - **Goal**: Detect sensitive financial/billing surfaces (`stripe`, `dashboard.stripe.com`, `billing`, `checkout`, `plaid`, `mercury`, `brex`, `robinhood`, `coinbase`) in `cua_safety.py`, allow screen capture and read/point/navigation (`T0`/`T1`), promote mutations (`click`, `type_text`, `key`, `fill`) to `T2` confirmation in `policy.py`, and refuse live secret key injection (`sk_live_`, `rk_live_`, `whsec_`).
  - **Requirements**: R5
  - **Files**:
    - `wisp/cua_safety.py`
    - `wisp/policy.py`
    - `tests/test_cua_safety.py`
    - `tests/test_policy.py`
  - **Verification**: `python3 -m unittest tests/test_cua_safety.py tests/test_policy.py`

- [x] **Unit 6 (U6): Low-Latency Capture & Companion Visual Continuity**
  - **Goal**: Skip unnecessary pre-capture sleep in `stage_capture.py` when `ask_chips` are not armed, tighten `ENTRY_DELAY_S` in `shell-plugin/lib/buddy.js`, and include `deciding` and `acting` in `PILL_STATUSES` in `shell-plugin/lib/companion.js`.
  - **Requirements**: R6
  - **Files**:
    - `wisp/stage_capture.py`
    - `shell-plugin/lib/buddy.js`
    - `shell-plugin/lib/companion.js`
    - `tests/qml/lib/tst_pill.qml`
  - **Verification**: `python3 -m unittest tests/test_qml_lib.py tests/test_components.py tests/test_pipeline.py`
