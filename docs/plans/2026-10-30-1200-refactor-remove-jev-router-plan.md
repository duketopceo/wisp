---
title: "refactor: Remove the Jev router (Phase 5), fixture migration first"
type: refactor
status: active
date: 2026-10-30
origin: ROADMAP.md (Next, in order, item 2) and docs/plans/2026-10-26-0031-feat-wisp-v1-roadmap-plan.md (Phase 5, Q3)
---

# refactor: Remove the Jev router (Phase 5), fixture migration first

## Goal Capsule

- **Objective:** finish Phase 5 by removing the Jev router (`router = jev`, `route.decide`, the clarify prompt, `JEV_QUESTIONS`/`build_questions`) so no decision model sits on the routing path. Turns go to the act loop, with the regex fast path (`[brain] fast_path`, #233) in front.
- **Authority:** ROADMAP "Product target" fixes the no-decision-model rule. ROADMAP item 2 fixes the order: fixture migration first, then deletion.
- **This run ships:** PR 1, the fixture and test migration (U1 to U4). PR 2, the deletion (U5), is recorded as the next PR (see KTD1).
- **Stop conditions:** a fixture whose behavior can only be reproduced by a Jev answer and has no act-loop equivalent is kept explicitly pinned to `router: jev` and handed to PR 2 for deletion; it is never silently weakened.

## Product Contract

### Problem Frame

`router` already defaults to `act`. The Jev router survives only as an opt-in value plus the code behind it, and as an implicit test pin: `tests/harness/runner.py::_pin_jev_router` forces `router = jev` on every replay fixture that scripts a `jev` endpoint (47 of the 54 turn fixtures), and about 25 test modules script Jev. Deleting the router while those pin it would break the suite wholesale, so the pin has to be retired first.

### Requirements

- R1. No replay fixture or test reaches the Jev router implicitly. After PR 1, `router: jev` appears only where a fixture or test is about Jev-only behavior, and each such place is explicit.
- R2. Every migrated fixture keeps the intent of its original assertions (tool calls, results, statuses that still apply). Expectations change only where the routing path genuinely changed (no `jev` hop, fast path in front), and each change is deliberate.
- R3. `suggest` and the grounding `jev` provider keep working untouched (Q3 is undecided). `ask_jev`, `_jev_locate`, `JEV_ENDPOINT` and the health `jev` endpoint stay.
- R4. `wispd eval` and its labelled-turn data are unchanged.
- R5. ROADMAP.md's Phase 5 entry matches what shipped in the same PR.
- R6. No live or paid calls: replay fixtures and fakes only.

### Scope Boundaries

- Deferred to PR 2: deleting `route.decide` and its helpers, `router = jev` handling in `stage_route.route_stage`, the clarify prompt (`is_low_confidence`, `ambiguous_choices`, `_ask_prompt` use for clarify, `auto_pick`/`apply_choice` if unused elsewhere), `JEV_QUESTIONS`, `build_questions`, the `jev` value in `settings_schema`/`selfknow`/`config.py` comments, `FakeJev` as a router fake, and the Jev-only fixtures and tests.
- Outside this change: the Rust daemon (`rs/wispd`, its own `router` default and `brain::ask_jev`), `suggest`, grounding `jev`, Q3 itself.

## Planning Contract

### Key Technical Decisions

- KTD1. **Two PRs, migration then deletion.** The migration touches 47 fixtures and about 25 test modules and has to be reviewed as expectation changes; the deletion is a code removal plus deleting the Jev-only tests. Folding them into one PR would bury expectation changes in a large deletion and hide the invariant R1 gives PR 2 for free (every remaining Jev reference is deletable). Rejected alternative: one PR, because the diff would not be reviewable.
- KTD2. **Retire the implicit pin, keep explicit pins.** Remove `_pin_jev_router`. Fixtures about Jev-only behavior (`jev_down`, `jev_slow`, `choose`, `stale_choice`, and any found during U2) set `"config": {"brain": {"router": "jev"}}` themselves. This makes "what still needs Jev" greppable and is exactly the PR 2 delete list.
- KTD3. **Migrate by deleting the `jev` endpoint block and re-deriving expectations from the act path under the fakes**, then reviewing each expectation diff against the fixture's description rather than regenerating blindly (R2).
- KTD4. **`ask_jev` stays in PR 1 and PR 2.** `suggest._worth_mining` calls it. ROADMAP lists `ask_jev` for removal, but Q3 is open, so it is kept and Q3 is recorded as a residual for Luke.
- KTD5. **PR 2 normalizes a stored `router = "jev"` (or any unknown value) to `act` explicitly.** Today `fixed_route` returns `None` for anything but `act`/`chat`/`off`, so `route_stage` falls to `route.decide`; once `decide` is deleted that would hit a missing function, and the fast path (gated on `router == "act"`) would be skipped. PR 2 adds the normalization in `route_stage` (or config load), removes the `decide` branch, and tests `router: "jev"` and an unknown value. Not needed in PR 1. If the Rust daemon reads the same config.toml it needs equivalent handling (follow-up).
- Assumption (pipeline mode, no human): the Rust daemon is out of scope. Its `router` default and `brain::ask_jev` are a separate parity cleanup and are recorded as a follow-up.

### Sequencing

U1 first (harness), then U2 and U3 (independent), then U4. PR 2 (U5) starts after PR 1 is merged.

## Implementation Units

### U1. Harness: retire the implicit Jev pin

- **Goal:** fixtures no longer get `router = jev` unless they ask for it. U1 is not independently green: with the pin gone, `test_turn_replay` and `harness_helpers.turn()` users fail until U2 and U3 finish. U1 to U3 land as one commit series and are verified together; during U1 verify only `tests.test_fakes` and a few hand-picked fixtures.
- **`harness_helpers.turn()`:** it always scripts a `jev` endpoint steered by its `route=` argument, which becomes a no-op under `act`. Decide in U1: drop the default Jev endpoint, keep `jev=` as the explicit opt-in (which pins `router: jev`), and for callers that passed `route=` map the intent to an act-loop brain script or the fast path, one caller group at a time in U3.
- **Files:** `tests/harness/runner.py` (remove `_pin_jev_router` and its call in the config build), `tests/harness_helpers.py` (the fixture builder's `jev` parameter: scripted Jev only when the caller passes it, and then it pins `router: jev` explicitly), `tests/harness/_child.py` (unchanged unless FakeJev wiring needs a guard).
- **Test scenarios:** a fixture with no `jev` block runs under `router = act`; a fixture with explicit `router: jev` still reaches FakeJev (`tests/test_turn_replay.py`, `tests/test_fakes.py`).
- **Verification:** `python3 -m unittest tests.test_turn_replay tests.test_fakes`.

### U2. Migrate the turn fixtures

- **Goal:** the 47 fixtures in `tests/fixtures/turns/` that carry a `jev` endpoint are each either migrated to the act router or explicitly pinned (4 known pins: `jev_down`, `jev_slow`, `choose`, `stale_choice`; so about 43 migrate). Pre-pass: grep `expect` blocks for `jev_calls` and other Jev assertions to separate unpin-only fixtures from re-derive fixtures. Under `act`, `fixed_route` also intercepts learn, walkthrough, setting and named-agent intents and the fast path takes plain questions, so `brain_calls` and `statuses` can shift even for act-style fixtures.
- **Files:** `tests/fixtures/turns/*.json`. Groups: act-style (`act*.json`, `cua_*`, `notify_*`, `budget_*`, `cancel_*`, `lang_*`, `brain_*`, `offline_all`, `stt_failure`, `answer_*`, `ask*`) lose the `jev` block and get expectations re-derived (the `deciding`-status sequence, `brain_calls`, and `result_prefix` may shift; plain questions such as `ask.json` now take the fast path). `router_act.json` / `router_act_default.json` / `fast_path_*.json` already assert `jev_calls: 0`; drop their unused `jev` blocks. Jev-only fixtures (`jev_down`, `jev_slow`, `choose`, `stale_choice`) get an explicit `router: jev` pin (KTD2) and are left for PR 2.
- **Patterns:** `tests/fixtures/turns/router_act.json` and `fast_path_launch.json` are the shape to migrate toward.
- **Test scenarios:** each migrated fixture replays green under `tests/test_turn_replay.py`; the intent in the fixture's `description` still holds.
- **Verification:** `python3 -m unittest tests.test_turn_replay`.

### U3. Migrate the Python test modules that script Jev

- **Goal:** test modules that use Jev as scaffolding for something else stop doing so. The inventory is a rule, not a list: every module matching `grep -il jev tests/test_*.py tests/harness/*.py` is triaged into migrate, explicit pin (PR 2 delete), or stays under R3 (grounding, suggest, health endpoint, `jev_ms`/`jev_down` literals, the retired jev-shim unit). The named files below are the expected migrate/pin set; the rest are expected to stay and are confirmed by triage. `tests/harness/latency.py`, `harness/fakes.py` and `harness/_child.py` are in the triage.
- **Files:** `tests/test_cancel.py`, `test_context_selection.py`, `test_act.py`, `test_ground_chain.py`, `test_bugreport.py`, `test_health.py`, `test_learn.py`, `test_ipc_stream.py`, `test_manage.py`, `test_notify.py`, `test_latency_budgets.py`, `test_scenarios.py`, `test_self_answers.py`, `test_state_reader.py`, `test_routines_wire.py`, `test_voicepick.py`, `test_onboard.py`, `test_key_missing.py`, `test_bgwriter.py`, `test_cli.py`, `test_pipeline.py`, plus `tests/stage_test.sh`. For each: if Jev is only a harness dependency, switch it to the act path or a neutral fake; if the test is about the router or the clarify prompt (`test_route.py` decide cases, `test_pipeline.py` clarify cases, `test_voicepick.py` choice cases), pin `router: jev` explicitly and mark it for PR 2 deletion. Grounding-chain tests that exercise the `jev` provider and `suggest` tests stay as they are (R3).
- **Test scenarios:** the module passes unchanged in intent; `grep -rn "router.*jev" tests` returns only the explicit PR 2 delete list.
- **Verification:** run each touched module, then the full suite.

### U4. ROADMAP and plan record

- **Files:** `ROADMAP.md` (Phase 5 entry and the "Next, in order" item 2: migration shipped, deletion next, Q3 still open and why `ask_jev` stays), this plan file.
- **Verification:** the ROADMAP text names exactly what shipped and what PR 2 deletes.

### U5. (PR 2, not this run) Delete the router

- Delete the items in Scope Boundaries "Deferred to PR 2", remove the explicit-pin fixtures and tests found in U2/U3, drop `jev` from `settings_schema` and `selfknow`, update `docs`. `ask_jev` stays while `suggest` needs it (KTD4).

## Verification Contract

| What | Command |
|---|---|
| Replay fixtures | `python3 -m unittest tests.test_turn_replay` |
| Full suite | `python3 -m unittest discover -s tests` (about 6 minutes) |

Known environmental failures on this machine, not caused by this change: `test_snap.TestRender.test_all_fixtures_match_goldens_within_tolerance` and `test_voice_polish.DeliveryPlan.test_voice_usable_checks_the_tts_program`. CI gates: unit 3.11, unit 3.13, plugin, rust.

## Definition of Done

- No `_pin_jev_router`; `grep -rn "router.*jev" tests` and `grep -rln '"jev"' tests/fixtures` list only deliberate Jev-only fixtures and tests (plus the R3 cases).
- Full suite green apart from the two known failures.
- ROADMAP Phase 5 entry updated; Q3 recorded as open for the owner.

## Risks

- A fixture's `statuses` or `brain_calls` expectation changes because the fast path or act loop behaves differently. Mitigation: KTD3, review each diff against the description.
- Hidden Jev dependencies in tests that do not mention `jev` literally (they rely on the harness pin). Mitigation: removing the pin in U1 surfaces them as failures.
