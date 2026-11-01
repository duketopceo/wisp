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
