# Gauntlet live results, 2026-11-01

Tested commit: origin/master 4612657 plus the fixes on `test/live-gauntlet`
(both `scripts/gauntlet.py` and `scripts/click_probe.py` import `wisp` from
the worktree, not the installed wispd build). Machine: M1 Max, Hyprland
0.56.2, only eDP-1 live (DP-3 not connected, so no second-monitor probe).
Evidence lives under `~/.local/share/wisp-gauntlet/runs/<run id>/`.

## Click probe (eDP-1, 9 targets, `--profile` of each arm)

The first three baselines were invalid and are not counted (see fixes):
the page sat off-screen in workspace 1's scrolling layout, and the user's
own config still enabled the `jev` provider.

| config | grounding model | grounded | hits | median miss | max miss |
|---|---|---|---|---|---|
| openrouter | google/gemini-2.5-flash | 2/9 | 0 | 193 px | 297 px |
| hybrid | ollama qwen2.5vl:3b-q8_0 | 0/9 | 0 | n/a | n/a |

Hybrid refusals were `not_found` or `low_confidence vlm 0.00`, about 60 s per
target on CPU. OpenRouter refusals were `not_found`. Grounded points were
consistently 90-300 px off, so the click path is the weak link with both
cheap models. The probe's ledger delta read $0.00 (the eval-key spend is not
visible to `ledger.totals()`), so probe spend is unmeasured, estimated under
$0.05 (about 30 cheap vision calls); the spend file records it as 0.

## Gauntlet (cap $10, spent $0.267 in total)

Arms: hybrid and openrouter both use `meta-llama/llama-4-maverick` as the
reasoning brain (grounding differs). Full run `gauntlet-20261101-200501`.

| arm | tuning | held-out | skill wins | spend |
|---|---|---|---|---|
| hybrid | 0/13 | 2/7 (files-go-up, windows-resize) | 0 | $0.0966 |
| openrouter | 0/13 | 2/7 (same two) | 0 (one skill saved, create-new-folder, no improvement) | $0.0870 |
| openrouter-gemini (experiment, tuning only, run 203847) | 1/13 (windows-focus-files) | not run | 0 | $0.0838 |

Spend by provider: openrouter $0.239 task calls, eval-key judge $0.026
(orcheval). No local spend. Held-out cases were run once and not tuned on.
The two held-out passes are the cases whose check is easiest to satisfy.
Plan gate (60% held-out) is not met by either arm.

## Failure classes, ranked

1. **Brain emits no usable tool call (llama-4-maverick via OpenRouter).**
   Of 257 act-loop LLM calls in the full run, 152 were text-only replies
   and 21 were empty (no content, no tool_calls); only 84 carried a tool
   call. A direct request with the act tool schema returned
   `content: null, tool_calls: null` three times out of three, and in
   another sample the model wrote `[key(arg=ctrl+l), ...]` as prose. Result
   strings like `ACTED (0 steps): done` or "already completed" follow.
   Evidence: `gauntlet-20261101-200501/evidence/browser-open-page-*`,
   `files-open-folder-*`; trace in `data/wisp/trace.jsonl`
   (`llm_call` rows with `tools_out: []`). Swapping the brain to
   gemini-2.5-flash fixes this class (tool calls appear in every case of
   run 203847) but exposes class 2.
2. **Click grounding refused: "no element at model-chosen coordinates".**
   Top class for the tool-capable brain: browser-follow-link,
   files-open-nested, files-rename, menu-open-close, files-open-folder.
   Matches the probe (0 hits, 90-300 px misses). Evidence:
   `gauntlet-20261101-203847/evidence/*-openrouter-gemini-1.json`.
3. **Keyboard input is dead: `ydotoold` is not running** (the unit is
   disabled per the machine notes). `key` steps report
   `SKIP (ydotool key failed)`, `SKIP (unknown chord 'ctrl+,')` or an
   empty arg; `ydotool key` fails with a missing `.ydotool_socket`.
   This blocks every keyboard-first case (address bar, settings, terminal
   typing: `type_text -> SKIP (nothing to type)`). I did not start the
   service; it is the owner's call.
4. **Policy refusals the cases do not expect:** shell tools disabled in dev
   runs (`SKIPPED (shell disabled)`, `REFUSED (dev run denies shell)`) and
   `super and alt chords` refused (windows-move-workspace). Cases that need
   these cannot pass as written.
5. **`stopped: cancelled (user)`** on 4 cases in run 203847 and 1 in the
   full run. Could be real owner input during the run or a stray key event;
   not established.

## Unverified items from the plan

- Window move on Lua: `hl.dsp.window.move({workspace=N, window=...})` works,
  but it FOLLOWS the window (the owner's active workspace ended on 91 after
  a run). The sandbox comment says "without following". Fixed by restoring
  the owner's workspace at the end of the run; the follow is also what
  makes the screenshots show the sandbox windows, so it was left alone.
- Per-app launch: chromium, nautilus and foot windows were found and moved
  on every case. Sandbox apps without a session bus opened windows fine.
- wispd.service: active before and after every run (checked after each).
- Second monitor, run-2 skill reuse with a working click or key path, and
  the openrouter arm with a tool-capable brain on held-out cases are not
  measured. DP-3 was absent.

## Fixes (branch test/live-gauntlet)

- `click_probe.py`: parks the probe page on empty workspace 93 and restores
  the owner's workspace on close (workspace 1 uses the scrolling layout, so
  "fullscreen" put the page at x=-847 behind another window and every
  earlier miss was meaningless); waits 1.5 s before the fullscreen check;
  prints grounding refusal reasons; opens the page with
  `--disable-extensions`. Use `--profile docs/dev-tasks/profiles/<arm>.toml`
  so the probe grounds with the same provider list as the arm (without it
  the `jev` provider refused 0.47-0.49 confidence results).
- `gauntlet/sandbox.py`: sandbox browser gets `--disable-extensions`; the
  owner's policy force-installs a 1Password extension that opens a welcome
  tab in every fresh profile and took the focus (visible in the pilot
  screenshot).
- `gauntlet.py`: records the owner's active workspace and restores it in
  the cleanup path before the service restart.
- `docs/dev-tasks/profiles/openrouter-gemini.toml`: experiment arm with a
  tool-capable brain. Tests added in `tests/test_gauntlet_driver.py`.

## Next

1. Decide ydotoold for gauntlet runs (class 3) and rerun the keyboard cases.
2. Pick a tool-reliable brain for the openrouter arm (class 1) and re-score
   both arms; then work class 2 (grounding offsets) with the probe as the
   offline-reproducible metric.
3. Review turns: `wispd dev review gauntlet-20261101-200501` then
   `wispd dev import-labels` (commands are in each run's report.md).

---

# Second run: isolated (hidden, nested) Hyprland session, 2026-11-01

Branch `test/hidden-gauntlet` (PR #295 plus master, #298, #297, #291), run
while the owner kept using the laptop. Everything ran in the isolated
session (`isolated_session.py start`, nested-hidden, canary passed on the
first try). `wispd.service` was `active` at every check (before, during and
after probe and gauntlet); the run never stopped or restarted it. Models:
act brain `openrouter:google/gemini-2.5-flash` on both arms; openrouter arm
`vlm_brain = openrouter:meta-llama/llama-4-maverick`; hybrid arm
`ollama:qwen2.5vl:3b-q8_0` with the 60 s grounding timeout. Maverick is a
grounding model only: a peer probe saw it return 0 of 3 tool calls as a
brain, so it is never a brain or fallback.

## Click probe (isolated session, 9 targets per output)

Both outputs are headless (HEADLESS-1 3456x2160 at scale 2, HEADLESS-2
3440x1440 at scale 1). A hit is a click within the button's radius. No
refusals on any row (18 of 18 grounded per config). The model column of every
row matched the vision model in the config.

| config | model (row label) | output | hits | median miss px | max miss px |
|---|---|---|---|---|---|
| hybrid | ollama:qwen2.5vl:3b-q8_0 | HEADLESS-1 | 7/9 | 31.1 | 144.7 |
| hybrid | ollama:qwen2.5vl:3b-q8_0 | HEADLESS-2 | 6/9 | 34.5 | 374.4 |
| openrouter | openrouter:meta-llama/llama-4-maverick | HEADLESS-1 | 4/9 | 49.1 | 230.7 |
| openrouter | openrouter:meta-llama/llama-4-maverick | HEADLESS-2 | 6/9 | 58.0 | 115.9 |

Rows: the JSONL files were
written to the scratch dir (`probe-hybrid.jsonl`, `probe-openrouter.jsonl`).
The probe reported `spent_usd: 0.0` for the OpenRouter config, so probe
spend is not metered into the spend file (see failure class 6).

## Gauntlet scores

Run A (`gauntlet-20261101-235322`, full battery, 20 cases) had a driver
defect that zeroed every terminal case (fix 3). The four terminal cases were
rerun after the fix (run B, `gauntlet-20261102-012052`); the combined score
below takes terminal cases from run B and everything else from run A. An
earlier first attempt (`gauntlet-20261101-224826`, 0% on both arms) died of
fixes 1 and 2 and is not scored.

| arm | tuning | held-out | held-out gate (60%) | skill-reuse wins |
|---|---|---|---|---|
| hybrid | 8/13 (62%) | 2/7 (29%) | not met | 1 |
| openrouter | 4/13 (31%) | 4/7 (57%) | not met (3 points short) | 3 |

Run A alone: hybrid 6/13 tuning, 2/7 held-out; openrouter 4/13, 3/7. Run B
alone (terminal cases): hybrid 2/3 tuning, 0/1 held-out; openrouter 0/3,
1/1. No tuning was done against held-out cases; no fix below reads a
held-out case.

Skill-reuse wins (run 2 passed where run 1 failed, with the learned skill
reused): openrouter `browser-search-site`, `browser-address-bar`,
`files-open-folder`; hybrid `browser-address-bar`. Terminal skills were never
reused (class 5).

## Spend

Spend file total $0.731 of the $10 cap (it held $0.267 before this run).
This run: $0.464. By provider: openrouter (act brain and VLM) $0.428,
orcheval (judge) $0.036. Per run: first attempt $0.167, run A $0.258,
run B $0.039. Click-probe cost is not in the file.

## Failure classes, ranked

Evidence is under `~/.local/share/wisp-gauntlet/runs/<run>/evidence/`.

1. **Model acted and did not finish (about 11 case-arms, run A).** Wisp
   failure. Typed `pwd` without Enter (`terminal-where-am-i-openrouter-1`),
   typed a path then clicked the wrong row (`files-open-nested-openrouter-1`),
   clicked the search box twice and never submitted
   (`browser-search-site-openrouter-1`). Gemini 2.5 flash stops early; the
   judge note on each is in the evidence file.
2. **Dev-run policy denies the tool the model picked (4 case-arms).** The
   model reaches for `shell` or `close`, the sandboxed dev run refuses
   (`files-rename-openrouter-1`, `terminal-list-files-openrouter-1`,
   `terminal-where-am-i-openrouter-1` in run B, `browser-settings-page`).
   Wisp tool selection under a restricted policy, not a driver bug.
3. **Missing key and chord mappings (wisp).** `key F2` and `key ctrl+,` return
   `SKIP (unknown key/chord)` (`files-rename-hybrid-1`,
   `browser-settings-page-hybrid-1` in the first attempt). `_KEYCODES` has no
   function keys and `_chord` has no punctuation.
4. **Grounding `not_found` and off-target clicks on the small VLM (hybrid).**
   `files-open-nested`, `files-rename` (first attempt: `could not ground 'Home
   button': not_found`). The probe shows the same arm 6 to 7 of 9 with
   misses up to 374 px.
5. **Skill not reused on terminal cases (6 case-arms).** Learn turn saved a
   skill; run 2 did not use it.
6. **Metering gap.** Probe spend is not appended to the spend file, so the cap
   does not see probe cost.
7. **Environment and case defects, not model failures** (peer-confirmed, case
   files left untouched): `menu-open-close` and `menu-launcher-close` (the
   isolated `hyprland.lua` has no Omarchy menu or launcher; the click is
   `SKIPPED (click needs user confirmation)`), and `windows-move-workspace`
   (needs a super/alt chord that preempt refuses; its goal says workspace 92
   while its check says 2).

## Fixes (branch test/hidden-gauntlet)

1. **`type_text` interrupted every turn in the isolated session.** wtype's
   keymap matched the instance's `wisp` submap Esc bind, so each typed string
   fired `wispd interrupt` (one per stale duplicate bind) and the turn ended
   `CANCELLED (user)` 45 ms later. Reproduced in the instance with a
   throwaway submap. `type_text` now runs inside `keys.suspended()` for
   isolated runs, as `key` already did. Test:
   `test_type_text_steps_the_wisp_submap_aside`.
2. **Every model-coordinate click was refused in the isolated session.**
   `grounding.target_at_point` needs the control and a11y providers, and the
   isolated session has neither, so it always returned None
   (`REFUSED (no element at model-chosen coordinates)`). The hit test is now
   skipped for isolated runs. The earlier tests mocked `target_at_point` and
   hid this. Test: `test_model_coordinates_click_without_an_element_hit_test`.
3. **rsh log never reached the driver.** The sandbox terminal set
   `GAUNTLET_ROOT` to the workspace, so rsh logged inside the workspace while
   the `rsh_log` check read the file beside it; every terminal case saw 0
   lines. The sandbox now passes `GAUNTLET_LOG`. Tests added in
   `tests/test_gauntlet_driver.py`.
4. The driver now writes `driver-error.txt` with the traceback. The first
   attempt ended with `BlockingIOError` after the cases and the cause was not
   recoverable; it did not recur in runs A and B.

Known and not fixed: the instance accumulates duplicate `wisp` submap Esc
binds (62 after one run), so one Esc spawns many interrupts. Also
`tests/test_snap.py::test_all_fixtures_match_goldens_within_tolerance`
fails in the full suite on this machine; it renders fixtures and does not
touch these files.

## Final state

`isolated_session.py stop` was run; the live `hyprctl clients -j` has no
`aquamarine` window and `hyprctl instances` lists only the live instance.

---

# Third run: live desktop (eDP-1), 2026-11-01

Branch `test/hidden-gauntlet` (PR #300, head f4be4de plus the fix below). Run
on the owner's real Hyprland session with his consent; only eDP-1 live
(3456x2160, scale 2). ydotoold, ollama and wispd were active at start. The
gauntlet stopped `wispd.service` and restarted it (active after the full run
and after the rerun). The owner's workspace (1) was restored after each probe
and after the gauntlet; submap `default` at the end. Act brain
`openrouter:google/gemini-2.5-flash` on both arms.

## Click probe (live, eDP-1, 9 targets)

| config | grounding model | grounded | hits | median miss | max miss |
|---|---|---|---|---|---|
| hybrid (`--profile hybrid.toml`) | ollama qwen2.5vl:3b-q8_0 | 9/9 | 7/9 | 27.3 px | 165.1 px |
| openrouter (`--profile openrouter.toml`) | meta-llama/llama-4-maverick | 9/9 | 5/9 | 30.5 px | 297.2 px |
| hybrid, no profile (invalid, kept for the record) | same | 2/9 | 2 | 14.9 px | 23.8 px |

The no-profile hybrid run used the owner's own provider list and got
`not_found` on 7 of 9 targets; the `--profile` runs match the arms. Rows in
`~/Downloads/claude/probe-live-{hybrid,openrouter}.jsonl`. Probe spend is
still not metered (reports $0.00).

## Gauntlet (full run `gauntlet-20261102-015708`, 20 cases)

| arm | tuning | held-out | skill wins | spend |
|---|---|---|---|---|
| hybrid | 2/13 | 3/7 | 1 | $0.1122 |
| openrouter | 0/13 | 2/7 | 1 | $0.1377 |

Rerun of the three browser tuning cases after the fix below
(`gauntlet-20261102-023806`, tuning only, no held-out case rerun): hybrid 2/3
(open-page, settings-page pass; search-site fails on click grounding),
openrouter 3/3. Folding these in, tuning is about hybrid 4/13 and openrouter
3/13 (browser-open-page, browser-search-site, browser-settings-page replace
the cancelled results); held-out is unchanged.

Comparison against the isolated run (hybrid 8/13 tuning, 2/7 held-out;
openrouter 4/13, 4/7): live is worse on tuning for both arms and flat or worse
on held-out (hybrid 3/7 vs 2/7, openrouter 2/7 vs 4/7). The live-only causes
are classes 1, 3 and 4 below. The held-out gate (60%) is not met by either arm.

## Spend

This run: $0.2499 (full) + $0.0558 (rerun) = $0.3057. Cumulative spend file:
$1.0367 of the $10 cap. All paid calls through `orch` (eval key).

## Failure classes (evidence under `~/.local/share/wisp-gauntlet/runs/gauntlet-20261102-015708/evidence/`)

1. **`type_text` interrupted every turn on the live desktop (wisp bug,
   fixed).** `browser-open-page-{hybrid,openrouter}-1`,
   `browser-search-site-openrouter-1`, `browser-settings-page-openrouter-1`
   ended `CANCELLED (user)` right after `type_text`: wtype's keymap hits the
   Wisp submap Esc bind, the same defect the isolated run fixed, but the
   fix was gated to isolated runs. Now always inside `keys.suspended()`.
2. **Dev-run policy refuses the tool (case defect/env, not model).** `shell`
   denied (`terminal-*`: 5 case-arms) and `default_click`/`default_focus`
   skipped with "shell disabled" (`files-open-folder`, `files-rename`,
   `windows-move-workspace`: 4). The model picks the tool; the dev policy
   forbids it.
3. **Model-coordinate clicks refused on live: "no element at model-chosen
   coordinates".** `files-open-nested-hybrid-1`,
   `browser-search-site-hybrid-1` (also in the rerun), `files-open-folder`.
   The live hit test needs control/a11y elements; the sandbox apps do not
   expose them, so VLM coordinates are refused even where the probe hits.
4. **Menu cases are not possible as written.** `menu-open-close` on both arms:
   `SKIPPED (click needs user confirmation)`; the click policy blocks the
   action. `menu-launcher-close` fails on both arms.
5. **Model stops early or acts and misses the check** (terminal-list-files,
   windows-focus-files, files-new-folder, terminal-count-lines, aborts at max
   steps on `files-open-nested`, `files-rename`).

Env/case defect, recorded and not edited: `windows-move-workspace` cannot
pass (the super chord is refused; goal says workspace 92, check wants 2; the
window ended on 91).

## Fix (branch test/hidden-gauntlet)

`wisp/tools/system.py`: `type_text` runs inside `keys.suspended()` for live
runs too. Test: `test_type_text_steps_the_wisp_submap_aside_live` in
`tests/test_isolated_input.py`. Full suite: 4435 tests, one failure, the
known `test_snap` fixture render mismatch (unrelated).

## Final state

`wispd.service` active, owner on workspace 1, submap `default`, only eDP-1.
