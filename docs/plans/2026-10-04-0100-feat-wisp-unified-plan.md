---
title: "Wisp unified plan: stack landing, CUA, desktop surfaces, Ember, backend"
type: feat
status: active
date: 2026-10-04
supersedes:
  - docs/plans/2026-10-02-2315-feat-wisp-ember-redesign-plan.md   (on PR #56; IDs Ember U1-U20)
  - docs/plans/2026-10-03-1455-feat-wisp-backend-core-plan.md     (on PR #56; IDs backend U1-U16)
  - docs/plans/2026-10-03-001-feat-consolidate-and-local-actor-plan.md (on PR #60; remaining items only)
  - docs/plans/2026-10-02-002-feat-wisp-roadmap-plan.md, ...-003-feat-wisp-companion-ux-plan.md (UX content folded in)
---

# Wisp unified plan

One plan. The Ember redesign and backend-core plans (PR #56) keep their detailed
unit text as design reference; this document owns IDs, order, dependencies and
status from here on. Units use a new namespace, **W1..W34**, with a crosswalk at
the end. Detail that already exists in the #56 plans is referenced, not copied.

## Status as of 2026-10-04 (evening)

Verified against `master` (`835b5ba`): merge commits and files present, not PR
titles. Master now contains #55-#66, #67, #68, and the second landing: #78
(`integrate/wisp-land`: W3, W8, W17, W18, W19, W20 and the W5 fakes that had
merged only into intermediate branches), #79 (W9), #80 (W21), #81 (W10) and #77
(Decision Agent grounding, WordInk STT, hotkey collision check; by the user).
Only #82 is open.

| Unit | Status | Evidence |
|---|---|---|
| W1 | done (landing); supersession front matter not applied | #68 merged the stack; INDEX pointer present; old plans carry no `superseded` front matter yet |
| W2 | todo | `latency` command and `latency_report` exist; baseline not recorded, budget table not revised |
| W3 | done | #70 via #78 (`ipc.py` subscribe, `test_ipc_stream.py`, `test_agents_reaper.py`) |
| W4 | todo | fixed `time.sleep(0.3)` still in `pipeline.py` |
| W5 | done | #72 merged to master (fakes under `tests/fakes`) |
| W6 | todo | no `tests/scenarios` |
| W7 | done | #62 via #68 (`wisp/hypr.py`, `wispd binds`); `keys.py` belongs to W24 |
| W8 | done | #73 via #78 (`pointer.py`, `cua.py`) |
| W9 | done | #79 (`cua_safety.py`) |
| W10 | done | #81 (`probes_cua.py`, `scripts/cua/`) |
| W11 | todo (partial) | shadow decider #55 merged; heuristic router absent |
| W12 | todo | no `wisp/stt.py`; open question 3 (STT engine) still with the user |
| W13 | todo | #77 merged and overlaps `act.py` and grounding (WordInk STT, Decision Agent); `wisp/ground.py` per this unit not present; reconcile with #77 before starting |
| W14 | todo | no ledger |
| W15 | todo | no batch lane |
| W16 | todo | no error reporting module |
| W17 | done | #71 via #78 (`copy.py`, `shell-plugin/lib`, copy lint) |
| W18 | done | #69 via #78 (`notify.py`) |
| W19 | done | #74 via #78 (`wisp/cli/` registry, `--json`) |
| W20 | done | #75 via #78 (snapshot harness, `shell-plugin/components`) |
| W21 | in progress | #80 merged (components, creature, ghost cursor); W21b `Companion.qml` host rewire in progress, monolith still present |
| W22 | todo | waits on W14 |
| W23 | in review | #82, stacked on `feat/wisp-w21-companion` (that base merged via #80; retarget to master) |
| W24-W34 | todo | no code on master |

Open questions still with the user: STT engine, alias period, Rust core,
premium handoff.

## 0. Constraints carried into every unit

- Cheap and local by default: brain `mlx:ornith` (:8080), Jev qwen3-4b (:8091),
  UI-TARS (:8081), Ollama (:11434), OpenRouter only as fallback or batch. No
  Anthropic or premium default anywhere in code, config or tests. Eval spend
  goes through `orch` (omaseal `openrouter/orchestral`), never `openrouter/default`.
- Tests never spend money and never touch the live daemon, Hyprland, audio or
  systemd. They use the W5 replay harness fakes, temp `WISP_HOME`/`XDG_*` dirs,
  and stub `hyprctl`, `cua-driver`, `notify-send`, `systemctl` via a PATH shim.
- Hand-authored assets only (SVG, QML shapes, shader code, synthesised earcons).
  No AI image generation.
- UI copy: no emoji, no em dashes, sentence case, plain verbs. Copy lives in one
  generated table (W17) so a lint test can enforce it.
- Config keys are added only in `wisp/config.py`, serialised through one PR at a
  time (see section 8 collision rules). Python is the reference core; Rust
  parity is frozen at W31 and only follows the frozen contract.
- Do not edit `/usr/share/omarchy/`. Machine specifics (hypr binds, units) are
  written into the repo as templates and installed to `~/.config/` by
  `wispd install`; the stash-canonical files are not touched by repo code.

## 1. State of wisp (2026-10-04)

**On master (`aa4194a`)**: Python reference daemon (`wisp/`, about 10k lines) plus
Rust parity core (`rs/wispd`). Pipeline: PipeWire capture, whisper.cpp,
Jev route (`launch | tool | agent | act | dictate | answer | clarify`), Talk with
`[POINT]` cursor, guarded act loop (`act.py`, 8 steps, 2 consecutive errors),
agent runtimes, `mcp_call`, goals, recall (sqlite-vec + RRF), skills/recipes,
sense + suggestion miner, trace/telemetry. Surfaces: quickshell plugin
(`shell-plugin/`: `Companion.qml` 975 lines, `Panel.qml` 827, `BarWidget.qml`,
`WispService.qml`), management app (`shells/debug/shell.qml`, 781 lines),
`wispd tui`. v0.9 released, soak gate at 0 of 50 labelled runs per route.

**Open PRs (all OPEN, base master; the stack is physically linear)**

| PR | Branch | Content | Notes |
|---|---|---|---|
| #55 | feat/shadow-decider | log a second model's route answers per turn; Jev endpoint override | small; shares 5 base commits with #60 |
| #60 | feat/training-arena | clicklab harness, Jev judge, skill bank, interactive tier, UI-TARS action-text provider, oracle efficiency, reviewer pass | 36 files, base of the act work |
| #61 | fix/log-and-learn-drift | stacked on #60: log date-stamp and rotate; `weekly()` legacy-row fix; **cua-driver pointer backend** (`wisp/platform.py` `_cua_live`, `pointer_cmds`) | only the last 2 commits are new after #60 |
| #59 | feat/wisp-be-u1-spans | turn spans, latency report | backend U1 |
| #63 | feat/wisp-be-u14-replay | turn-replay harness, fake model servers, `scripts/replay_turn.py` | backend U14 |
| #64 | feat/wisp-be-u2-statebus | StateBus single publisher (contains U1+U14 via merge) | backend U2 |
| #65 | feat/wisp-be-u7-health | `wisp/health.py`, `errors_codes.py`, brain fallback chain | backend U7 |
| #66 | feat/wisp-be-u9-cancel | cancellable turns, prompt ids, sentence TTS | backend U9 |
| #62 | feat/wisp-be-u5-hypr-socket | Hyprland socket layer, bind registry | backend U5; single commit off master |
| #57 | feat/wisp-u1-theme | Ember U1 token adapter, U2 QML tokens/motion/copy, U6 icon set | Ember foundations |
| #58 | feat/wisp-u9-u18 | stacked on #57: app icon + desktop entry (U9), management app + TUI on tokens (U18) | |
| #56 | docs/redesign-spec-plan | Ember spec, Ember plan, backend plan | docs only |

**Stale or duplicated**
- 13 plans under `docs/plans/` on master plus 4 more on #56/#60. The dim-era plans
  (2026-09-18 to 09-26), `units/*` (U2-U10 dim) and the three Oct-02 plans are
  shipped or absorbed. They are marked superseded in W1 and left in place.
- Two state writers: `wisp/state.py` atomic file plus ad hoc `dlog`/`trace`/`notify`
  calls in `pipeline.py`. #64 fixes the writer; the readers (Panel, Companion,
  BarWidget, debug shell, TUI) each parse `state.json` separately until W17.
- `Companion.qml` (975) and `Panel.qml` (827) are monoliths that Ember U4 splits.
- `wispd` is a hand-rolled `sys.argv` if-chain (888 lines, about 25 commands, no
  common `--json`, no `--help`, inconsistent exit codes).
- Pointer logic is in `wisp/platform.py` (`pointer_backend`, `pointer_cmds`) with
  the cua path bolted on by string checks.
- Rust parity core lags: no spans, health, bus, cancel or cua. Contract freeze (W31)
  decides what it must follow.

**Pain points (from logs, traces, tests, machine notes)**
- Latency: key to transcript 2.75 s p50 (p90 4.2 s) with warm-less whisper; fixed
  300 ms release sleep; route 348 ms includes screenshot and hyprctl; TTS off so
  spoken latency unmeasured.
- Failure visibility: Jev 502 (llama services killed by oomd, see machine notes)
  surfaces as a hang or generic "error: ..." notification. #65 adds typed codes;
  no surface renders them yet.
- Notifications: single `notify(msg)` in `pipeline.py` shelling `notify-send`
  with title "Wisp". No dedupe, no replace-id, no actions, no quiet hours, no
  level. No mako or swaync is on PATH on this machine; Omarchy 4 shell owns
  `org.freedesktop.Notifications`, so detect via D-Bus rather than assuming.
- Pointer: ydotool absolute move mismatches scale-2 outputs; hyprcursor steals the
  real cursor. cua fixes both but is verified manually only, has no safety layer,
  no health entry, no fake for tests and no install path in the repo.
- voxtype ALSA POLLERR spin and gnome-keyring races are host issues but wisp should
  detect "dictation daemon spinning" in `wispd doctor`.
- Tests: 386 of 387 pass on Linux; one macOS-only failure pre-exists on master. No
  UI tests exist until Ember U5 (snapshot harness).

## 2. CUA as a first-class subsystem

**What cua-driver gives.** A local daemon (`cua-driver serve`, socket
`~/.cache/cua-driver/cua-driver.sock`, Wayland backend enabled by
`CUA_DRIVER_RS_ENABLE_WAYLAND=1`) with a `call <tool> <json>` CLI. On Hyprland it
uses the `cua-hyprland` plugin plus an inject socket to create a wlroots virtual
pointer: clicks land at compositor-exact desktop coordinates without moving the
user's cursor and without stealing focus. Verified by hand on Hyprland 0.56.2
aarch64; user unit `cua-driver.service` already exists on this machine (outside
the repo). Today wisp uses two tools only: `click` and `move_cursor`.

**Position in the loop.**
```
act.py step -> grounding (W13: UI-TARS or vision LLM) -> (x, y, frame)
            -> safety gate (W9) -> pointer backend registry (W8)
                 cua | hyprcursor | ydotool | wlrctl | guide-only
            -> ghost cursor event on the bus (shows target; real cursor stays put)
            -> re-observe (existing soak-gate fix) -> next step
```
Order stays `cua > hyprcursor > ydotool > wlrctl`, overridable by `[pointer]
backend`. A failed cua call falls to the next backend only for idempotent
`move`; a failed `click` does not silently retry on another backend (double-click
risk): it reports `E_POINTER` and lets the act loop re-observe.

**Safety (W9).** Reuse the existing tiers and confirm-once-per-(tool, app).
Added: per-app allowlist and denylist (`[cua] allow`, `deny`; default deny for
password managers, polkit/auth dialogs, terminals running sudo), hard rate limit
(`[cua] max_clicks_per_min`, default 30; per-turn cap 12), kill switch (Esc
submap and `wispd stop` cancel the turn via W4/#66 CancelToken and send a cua
"release" if the driver supports it; otherwise the limit is enforced
client-side before each call), dry-run (`[cua] dry_run`, logs the call it would
make), and an append-only audit line per call in `cua.jsonl` (tool, coords, app,
turn id, result, ms; no screenshots, no text typed). Typed text is never logged.

**Health (W10).** `CuaProbe` registered in `wisp/health.py` (#65): socket exists,
`cua-driver call` ping within 300 ms, plugin loaded (`hyprctl plugin list`
through the W7 socket layer, not a subprocess), driver version vs a pinned min.
States feed the same fallback logic: unhealthy cua means the backend registry
skips it and `wispd doctor` prints one line with the fix command. Shown in the
Panel Health tab (W22) and the bar mark tooltip.

**Packaging (W10).** `scripts/cua/install.sh` (idempotent, no sudo): fetch the
pinned release kit, build `cua-hyprland` against the installed Hyprland headers
(`hyprpm`-style, outputs under `~/.local/share/cua-driver/`), write
`~/.config/systemd/user/cua-driver.service` from `scripts/cua/cua-driver.service`
(same content as the machine unit above, plus `Slice=session.slice` and
`MemoryMax=512M`), and register the plugin via the hypr Lua bind registry (W7),
never by editing stash-canonical files. `wispd install` calls it behind `--cua`.
Pinned version and checksum live in `scripts/cua/PIN`; upgrade is a one-line diff.

**Tests (W5, W8).** A fake `cua-driver` executable (`tests/fakes/cua-driver`) and
a fake unix socket server record calls, return canned JSON, and can simulate
slow, dead, version-skew and error replies. Pointer unit tests assert argv;
replay scenarios (W6) assert end to end: ground, gate, click, re-observe, audit
line, cancel mid-click. No test calls the real driver.

**Open capability questions (resolve in W8 spike, 1 hour, read-only):** does the
driver expose window-scoped clicks, scroll, key/type, and a window-tree
(accessibility) tool? If yes, W13 grounding can prefer the tree over pixels
(cheaper, more accurate); if no, the plan is unchanged.

## 3. Phases

```
P0  Land the stack      W1                              (no new code)
P1  Foundations         W2 W3 W4 W5 W6 W7 W8 W17 W18   (parallel groups, section 8)
P2  Core logic          W9 W10 W11 W12 W13 W14 W15 W16
P3  Surfaces            W19..W28
P4  Hardening           W29 W30 W31 W32 W33
P5  Release             W34
```

## 4. Merge order for the open stack (W1)

1. **#60** training arena (base of act work; other PRs carry its shared commits).
2. **#61** after rebase it is 2 commits: log rotation and cua pointer. Review
   against W8 before merge; the cua code is moved, not rewritten, by W8.
3. **#55** shadow decider (rebases to 3 commits).
4. **#59** spans, then **#63** harness, **#64** StateBus, **#65** health,
   **#66** cancel, in that order. Each is already contained in the next, so after
   each merge the following PR shrinks; run the full suite at each step.
5. **#62** hypr socket and bind registry (touches `config.py`, `platform.py`;
   after #66 to avoid rebase churn).
6. **#57** Ember foundations, then **#58** (app icon, debug app, TUI).
7. **#56** docs last, with this plan; W1 adds `superseded` front matter and the
   INDEX pointer in the same merge.
Rule: no feature unit (W2 onward) merges until #59 and #63 are in, because every
later test and latency claim depends on spans and the harness.

## 5. Units: backend core and CUA

Test layers: **unit** (pure Python), **harness** (W5 replay with fakes),
**contract** (`tests/test_contract.py`, IPC fixtures), **snapshot** (W20 QML
snapshots), **manual** (single human check on this machine, listed, never in CI).
Every unit's verification includes `python -m unittest discover -s tests` green
and no network access (CI sets `WISP_OFFLINE=1`; harness fails on unexpected
sockets).

### W1. Stack landing and plan supersession (P0)
- Goal: merge per section 4; mark old plans superseded; add INDEX pointer.
- Files: `INDEX.md`, `ROADMAP.md` (status line), front matter of old plans.
- Deps: none. Test: full suite after each merge; replay harness on #63 merge.
- Verify: `git log --oneline origin/master` shows the order; `wispd tele`
  latency report runs; baseline numbers pasted into W2's PR.
- Layers: unit, harness.

### W2. Baseline and budget table (P1)
- Goal: run #59 latency report on real traces; revise the budget table once
  (section 7) before later units are judged. Add `wispd latency --json`.
- Files: `wisp/telemetry.py`, `docs/CONFIG.md` (numbers only).
- Deps: W1. Tests: report on fixture spans; empty trace; corrupt line skipped.
- Verify: report prints p50/p90 for P1-P10 rows. Layers: unit.

### W3. Push stream, subscribers, agent reaper (backend U3)
- Goal: replace file-poll readers with a unix-socket subscribe (`{"cmd":"subscribe"}`)
  that emits StateBus events; agent reaper closes dead tasks.
- Files: `wisp/ipc.py`, `wisp/state.py`, `wisp/agents.py`, `docs/IPC_CONTRACT.md`.
- Deps: #64 (W1). Tests: two subscribers, slow subscriber dropped, reconnect
  replays last state, reaper kills orphaned pid (PID-reuse pinned).
- Verify: harness turn shows ordered events; `state.json` still written for
  legacy readers. Layers: unit, harness, contract.

### W4. Fast trigger and speculative context (backend U4)
- Goal: press publishes `listening` in 25 ms; release publishes `transcribing`
  without the fixed 300 ms sleep; screenshot and window map captured
  speculatively at press.
- Files: `wispd` (`cmd_trigger`), `wisp/pipeline.py`, `wisp/context.py`.
- Deps: W3, #64. Tests: release with and without audio, double press, stale
  speculative context discarded after 5 s. Verify: spans show P1 and P2 budgets.
- Layers: unit, harness.

### W5. Replay harness: CUA, Hyprland and notify fakes (extends #63)
- Goal: fakes for `cua-driver` (CLI plus socket), `hyprctl`/hypr socket,
  `notify-send`/D-Bus notification server, `systemctl --user`, UI-TARS and Jev.
- Files: `tests/fakes/`, `scripts/replay_turn.py`, `tests/harness_helpers.py`.
- Deps: #63. Tests: each fake has a self-test; harness refuses real `PATH` binaries.
- Verify: `python -m unittest tests.test_replay` offline. Layers: harness.

### W6. Scenario corpus
- Goal: scenarios shared by all units: answer, act-click via cua, cancel mid-act,
  Jev down, cua down, quiet hours, confirm, agent spawn. Fixture wavs exist
  (`scripts/make_fixture_wavs.py`).
- Files: `tests/scenarios/*.jsonl`. Deps: W5. Verify: corpus runs under 20 s.
- Layers: harness.

### W7. Hyprland socket and bind registry integration (backend U5)
- Goal: land #62 usage: one `wisp/hypr.py` for window queries, plugin list,
  keyword/eval, and bind registration for the Wisp submap (`keys.py` in W24).
- Files: `wisp/hypr.py`, `wisp/platform.py`, `wisp/keys.py`. Deps: #62.
- Tests: socket absent, malformed reply, bind collision reported not clobbered.
- Verify: `wispd doctor` lists binds and detects conflicts. Layers: unit, harness.

### W8. Pointer backend registry and CUA client
- Goal: `wisp/pointer.py` with a `Backend` protocol (`probe()`, `move`, `click`,
  `scroll`, `cancel`); backends `cua`, `hyprcursor`, `ydotool`, `wlrctl`, `guide`;
  `wisp/cua.py` wraps `cua-driver call` with timeout (800 ms click), JSON
  parsing, typed errors (`E_CUA_DOWN`, `E_CUA_TIMEOUT`, `E_CUA_REFUSED`). Move
  code out of `platform.py` (keep thin shims for the Rust parity tests). Includes
  the one-hour capability spike (section 2) recorded in `docs/LINUX.md`.
- Files: `wisp/pointer.py`, `wisp/cua.py`, `wisp/platform.py`, `wisp/config.py`
  (`[pointer]`, `[cua]`), `tests/test_pointer.py`, `tests/test_cua.py`.
- Deps: #61 merged, W5. Tests: auto order with each subset live; click failure
  does not fall through; timeout; malformed JSON; scale-2 coordinates pass
  through unchanged in `desktop` frame; guide fallback when none.
- Verify: unit and harness green; manual: one click on a scratch window via cua
  while another window keeps focus. Layers: unit, harness, manual.

### W9. CUA safety layer
- Goal: allow/deny lists, rate limits, kill switch, dry-run, audit log, confirm
  tier mapping (section 2).
- Files: `wisp/cua_safety.py`, `wisp/act.py`, `wisp/config.py`, `docs/CONFIG.md`.
- Deps: W8, #66. Tests: denied app, rate limit window rollover, cancel between
  calls, dry-run emits no subprocess, audit line has no typed text, confirm-once
  per (tool, app) preserved. Verify: scenario "cancel mid-act" ends in 150 ms of
  the stop request (P9). Layers: unit, harness.

### W10. CUA health, doctor and packaging
- Goal: `CuaProbe` in HealthRegistry, doctor lines, install script and unit
  template, PIN file.
- Files: `wisp/health.py` (probe only, in a new `wisp/probes_cua.py` to avoid
  colliding with #65 follow-ups), `scripts/cua/{install.sh,cua-driver.service,PIN}`,
  `wispd` (`install --cua`, `doctor`). Deps: W8, #65.
- Tests: installer under a fake HOME with stub `systemctl`/`hyprctl` (asserts
  files written, idempotent second run, refuses on checksum mismatch); probe
  states table. Verify: `install.sh --dry-run` prints plan. Layers: unit, harness.

### W11. Jev accelerator, shadow decider, heuristic router (backend U8)
- Goal: Jev with 400 ms deadline then heuristic route; shadow decider (#55)
  promoted to an A/B log read by `wispd eval route`.
- Files: `wisp/brain.py`, `wisp/pipeline.py`, `wisp/evalroute.py`.
- Deps: #55, #65. Tests: deadline expiry, Jev 502, heuristic coverage of
  launch/dictate/answer, shadow disagreement logged. Verify: P4 budget on spans.
- Layers: unit, harness.

### W12. Warm STT server (backend U6)
- Goal: pick by benchmark between warm whisper.cpp server and Parakeet; cancellable
  client; fixture-wav benchmark script (offline, local only).
- Files: `wisp/stt.py`, `scripts/bench_stt.py`, `wisp/pipeline.py`, unit
  `~/.config/systemd/user` template under `scripts/units/` (W29 installs).
- Deps: #66, W4. Tests: server down falls back to cold CLI; cancel mid-request;
  fixture transcripts WER under threshold. Verify: P3 budget (600 ms or 1.3 s floor).
- Layers: unit, harness, manual (benchmark on hardware).

### W13. UI-TARS grounding adapter (backend U12)
- Goal: `wisp/ground.py`: screenshot to coords for `click` targets, UI-TARS first,
  vision LLM fallback, optional window-tree path if W8 spike says cua exposes it;
  returns `(x, y, frame, confidence)`; low confidence triggers re-observe.
- Files: `wisp/ground.py`, `wisp/act.py`, `wisp/points.py`, `scripts/clicklab/arena.py`
  (suite entry only). Deps: W8, #60.
- Tests: coordinate frame conversion at scale 2 and 1, malformed model output,
  low confidence path, clicklab suite comparison offline against recorded outputs.
- Verify: P7 budget 1.2 s; clicklab pass^k not lower than current provider.
- Layers: unit, harness, manual (arena run on local model only).

### W14. Usage ledger and spend caps (backend U10)
- Goal: ledger of tokens and cost per provider; daily and monthly caps; caps
  block premium calls and OpenRouter fallback before they happen; surfaces
  show spend. Local calls recorded as zero cost.
- Files: `wisp/ledger.py`, `wisp/brain.py`, `wisp/config.py`. Deps: W11, W12.
- Tests: cap hit, cap reset at midnight local, unknown model priced at max,
  concurrent writers. Layers: unit, harness.

### W15. Batch lane (backend U11)
- Goal: OpenRouter Batch for offline work only (recipe proposals, learn weekly,
  judge runs); never on the live path; cheap-model allowlist.
- Files: `wisp/batch.py`, `wisp/learn.py`, `wisp/judge.py`. Deps: W14.
- Tests: fake batch server, partial failure, resubmit idempotent, cap respected.
- Layers: unit, harness.

### W16. GlitchTip error reporting (backend U13)
- Goal: typed errors (`errors_codes.py`) reported with scrubbed context (no
  transcripts, no screenshots, no paths with usernames), opt-in, rate limited.
- Files: `wisp/report.py`, `wisp/errors_codes.py`. Deps: #65.
- Tests: scrubber table, offline queue, disabled by default, no call in tests.
- Layers: unit.

## 6. Units: desktop surfaces

Surface principle: every surface renders from the same event stream (W3) through
one reader and one token set (W17). No surface parses `state.json` itself.

### W17. Shared UI core: state reader, tokens, copy (Ember U2 remainder, U3)
- Goal: one `WispStateReader.qml` singleton (subscribe socket with file fallback);
  tokens and generated copy table (`wisp/copy.py` to `copy.js`) including error
  code messages and the no-emoji, no-em-dash lint.
- Files: `shell-plugin/WispService.qml`, `shell-plugin/lib/*`, `wisp/copy.py`,
  `tests/test_copy.py`. Deps: #57, W3.
- Tests: reader reconnect, stale snapshot flagged after 5 s, copy lint on every
  string. Verify: BarWidget, Panel, Companion read through the singleton.
- Layers: unit, snapshot.

### W18. Notifications (new; replaces `notify()` in `pipeline.py`)
- Goal: `wisp/notify.py` with levels `info | success | attention | error`, one
  channel for the daemon and one API for tools; detect server via
  `org.freedesktop.Notifications.GetServerInformation` (mako, swaync, Omarchy
  shell, other) and capabilities (`actions`, `body-markup`); replace-id per
  turn so a turn updates one toast instead of stacking; dedupe key plus 60 s
  suppression window; quiet hours (`[notify] quiet = "22:00-07:00"`, also
  silent when `dnd` is set in the notification server or a fullscreen window is
  focused via W7); actions as buttons where supported (Confirm, Cancel, Open
  panel, Undo) wired to `wispd choice`/`stop`; fallback to `notify-send` without
  actions; messages come from the W17 copy table; errors map from typed codes
  with a "Fix" action running the doctor remedy. Spoken answers never also toast
  unless the user has TTS off.
- Files: `wisp/notify.py`, `wisp/platform.py` (`notify_cmd` stays for macOS and
  Windows), `wisp/pipeline.py`, `wisp/tools/system.py`, `wisp/config.py`.
- Deps: W5, W17. Tests: fake D-Bus server with and without actions capability,
  dedupe window, quiet hours across midnight, replace-id, action callback,
  server absent, body escaping. Verify: scenario "Jev down" yields one error
  toast with one action. Layers: unit, harness, manual (one real toast).

### W19. CLI rebuild (new)
- Goal: replace the `sys.argv` chain with a command registry (argparse
  subparsers): `wispd <group> <verb>`; `--help` everywhere with one-line
  summaries and examples; global `--json`, `--quiet`, `--no-color`; consistent
  exit codes (0 ok, 1 failure, 2 usage, 3 daemon not running, 4 unhealthy
  dependency); errors print `E_CODE: sentence` with a "Try:" line from the
  copy table; table output through one formatter (tokens from `theme.py`, plain
  when not a tty). Existing commands keep their names as aliases for one release.
  New or promoted: `doctor`, `health`, `cua status|test|log|enable|disable`,
  `notify test`, `latency`, `spend`, `binds`, `onboard`, `completion bash|zsh|fish`.
- Files: `wispd` (shrinks to entry), `wisp/cli/` (new package: `registry.py`,
  one module per group), `tests/test_cli.py`, `docs/CONFIG.md`.
- Deps: W3 (so commands share the client). Tests: every command has `--help`
  golden, JSON schema per command, exit code table, alias parity with old
  syntax (golden transcripts), daemon-down behaviour. Verify: `wispd --help`
  under 60 lines; shell completion loads. Layers: unit, contract.

### W20. Ember snapshot harness (Ember U5) and component split (U4)
- Goal: window-free components under `shell-plugin/components/`, `wispd replay`
  drives fixture states into a headless `qs` offscreen render for PNG diffs.
- Files: `shell-plugin/components/*.qml`, `scripts/ui/snap.py`, `tests/qml/`.
- Deps: #57, W17. Tests: each state fixture renders; diff tolerance table; harness
  never opens a Wayland window (offscreen platform, skipped if `qs` missing).
- Layers: snapshot.

### W21. Companion: creature, corner, pill, bubble, ghost cursor (Ember U7, U11, U12, U13)
- Goal: creature shader with 13 states; corner creature with on-demand console;
  listening pill and cursor bubble; fork-free ghost cursor and beacons; ghost
  cursor driven by W13 target events (so CUA clicks show where they will land
  while the real cursor stays).
- Files: `assets/shaders/`, `shell-plugin/components/{WispCreature,Corner,Console,Pill,Bubble,GhostCursor,Beacon}.qml`.
- Deps: W20, W3, W13 (cursor targets only). Tests: snapshot per state, motion
  reduced setting, 120 Hz and scale 2 fixtures. Layers: snapshot, manual.

### W22. Panel four tabs and Health tab (Ember U17)
- Goal: Panel reduced to Now, Agents, Memory, Settings from today's seven tabs;
  Health section inside Settings shows endpoints, cua, STT, spend, last errors
  from the registry (W10, W14); settings editor writes through `wispd config set`.
- Files: `shell-plugin/Panel.qml`. Deps: W20, W10, W14. Layers: snapshot.

### W23. Bar mark and bar plugin (Ember U10)
- Goal: single mark glyph with states; tooltip with health and spend; click
  toggles listen, middle click stop, right click opens Panel; no polling.
- Files: `shell-plugin/BarWidget.qml`, `shell-plugin/manifest.json`.
- Deps: #57 icons, W17. Tests: `test_plugin_manifest.py`, snapshot. Layers: snapshot.

### W24. Keyboard submap and Esc stop (Ember U14)
- Goal: `wisp/keys.py` registers submap through W7 registry: Esc stops, Enter
  confirms, number keys choose; collision report; works while cua acts (since
  clicks do not take focus, Esc stays reachable).
- Files: `wisp/keys.py`, `wispd`. Deps: W7, W9, #66. Tests: registry fake, conflict,
  submap exit on idle. Layers: unit, harness, manual.

### W25. Confirm card and error/offline/stale UX (Ember U15, U16)
- Goal: confirm card uses #66 prompt ids; typed errors, offline and stale states
  rendered from copy table in Companion, bar and notifications consistently.
- Files: `wisp/state.py`, `wisp/copy.py`, components. Deps: W21, W18, #66.
- Tests: prompt id mismatch ignored, timeout auto-cancels, every error code has a
  rendering in each surface (table test). Layers: unit, snapshot, harness.

### W26. Management app and TUI (Ember U18 follow-through)
- Goal: after #58, bring `shells/debug/shell.qml` and `wisp/tui.py` onto the W17
  reader; add Health, Spend, Audit (cua.jsonl), Binds views; TUI parity via the
  same JSON as `wispd health --json`.
- Files: `shells/debug/shell.qml`, `wisp/tui.py`. Deps: #58, W19, W22. Layers: snapshot, unit.

### W27. Tray, launcher and desktop entries (Ember U9 follow-through)
- Goal: `wisp.desktop` (launcher "Wisp"), actions "Listen", "Stop", "Panel";
  no tray icon unless the Omarchy shell exposes a StatusNotifier host, in which
  case a SNI item mirrors the bar mark. Icon theme install under
  `~/.local/share/icons/hicolor`.
- Files: `assets/desktop/`, `wispd install`. Deps: #58. Tests: desktop-file-validate
  (skipped if absent), install into temp HOME. Layers: unit.

### W28. Onboarding, first run and settings
- Goal: `wispd onboard` and a first-run card: checks mic, models (local ladder:
  Ornith, Jev, UI-TARS, Ollama), optional cua, notifications, keybinding; each
  step reversible and skippable; settings schema (`wisp/settings_schema.py`)
  generates both CLI `config` help and the Panel settings UI so they cannot drift.
- Files: `wisp/onboard.py`, `wisp/settings_schema.py`, `shell-plugin/Panel.qml`
  (settings section), `docs/INSTALL.md`. Deps: W19, W22, W10, W18.
- Tests: fresh temp HOME flow, partial completion resume, nothing written on
  skip. Layers: unit, harness, snapshot.

## 7. Units: hardening and polish

Latency budget (from backend plan, to be revised once by W2): press 25 ms,
release 25 ms, transcript 600 ms (Parakeet) or 1.3 s (warm whisper), route 200 ms,
first answer token 500 ms, TTS start 150 ms, act first step 1.2 s with UI-TARS,
agent ack 300 ms, stop 150 ms, offline error 1 s. End to end answer path p50
at most 1.4 s versus about 3.5 s today. Memory and CPU budgets: wispd under
250 MB RSS and 3% idle CPU; cua-driver `MemoryMax=512M`; Companion under 5%
CPU at 120 Hz idle (animations pause when idle); no always-on polling loops.

### W29. Service hygiene, oomd protection, watchdog (backend U16)
- Goal: move `llama-*.service` into `session.slice` (or set
  `ManagedOOMPreference=omit`) so oomd cannot pick them; `StartLimit` relaxed with
  `RestartSec` backoff; wispd `WatchdogSec` with sd_notify; `wispd doctor` flags
  voxtype POLLERR spin (journal rate or `cpal_alsa` CPU) and recommends the
  restart; unit templates under `scripts/units/` installed by `wispd install`.
  `wisp-backend-watch` stays external; wisp only reads its fallback state.
- Files: `scripts/units/*.service`, `wisp/health.py`, `wispd install`.
- Deps: #65, W10. Tests: unit-file lint, doctor against fake `systemctl`/`journalctl`.
- Verify: manual `systemd-analyze --user verify`. Layers: unit, manual.

### W30. Logic cleanup behind the surfaces
- Goal: split `pipeline.py` (918 lines) into capture, route, execute, speak stages
  around the bus; delete dead `notify`/`dlog` call sites; `act.py` step budget and
  error counters configurable; trajectories and recall writes off the hot path.
- Files: `wisp/pipeline.py`, `wisp/act.py`, `wisp/recall.py`. Deps: W3, W4, W11.
- Tests: existing 386 plus replay goldens unchanged (behaviour-preserving).
- Verify: spans show no regression versus W2 baseline. Layers: unit, harness.

### W31. Contract conformance and Rust freeze (backend U15)
- Goal: `docs/IPC_CONTRACT.md` versioned; Python and Rust both pass
  `tests/fixtures/ipc_commands.jsonl`; Rust gets only the frozen subset (state,
  trigger, stop, subscribe); new Python-only features are marked `py-only`.
- Files: `docs/IPC_CONTRACT.md`, `tests/test_contract.py`, `rs/wispd/tests/parity.rs`.
- Deps: W3, W19. Layers: contract.

### W32. Training arena restyle and eval hygiene (Ember U19)
- Goal: arena page on tokens; evals run through `orch`; arena model matrix limited
  to local models plus at most one cheap hosted model (Grok 4.7 class ceiling).
- Files: `scripts/clicklab/arena.html`, `arena.py`. Deps: #60, #57. Layers: manual.

### W33. Docs, README media and QA pass (Ember U20)
- Goal: README and docs reflect shipped state; screenshots and short capture made
  from real runs (screen recording, no generated imagery); CUA doc page
  (`docs/CUA.md`); close superseded plans.
- Files: `README.md`, `docs/`, `assets/readme/`. Deps: W21, W25, W22. Layers: manual.

### W34. v1.0 gate
- Goal: soak gate (50 labelled runs per route, 50 percent intent match), fresh-box
  install under 10 minutes on a clean Omarchy VM using `wispd onboard`, learning
  loop exercised twice, tag `v1.0.0`.
- Deps: all of the above. Verify: checklist in `ROADMAP.md`. Layers: manual.

## 8. Sequencing, parallelism and file collisions

Dependency spine: W1 > (W2, W5) > W3 > (W4, W17, W19) > W20 > W21/W22/W23 > W25.
CUA spine: W5 > W8 > W9/W10/W13 > W21 (ghost) and W24.

Parallel groups (no shared files, safe in separate worktrees):

| Group | Units | Why safe |
|---|---|---|
| A (after W1) | W2, W5, W7 | `telemetry.py` / `tests/fakes` / `hypr.py` |
| B (after W5) | W8, W3, W17 | `pointer.py+cua.py` / `ipc.py+state.py` / `shell-plugin/lib+copy.py` |
| C | W10, W9, W13 | `probes_cua.py+scripts/cua` / `cua_safety.py` / `ground.py`; W9 and W13 both touch `act.py`, so W9 lands first |
| D | W18, W19, W20 | `notify.py` / `wisp/cli/` / `shell-plugin/components` |
| E | W12, W14, W16 | `stt.py` / `ledger.py` / `report.py` |
Collision rules: `wisp/config.py` and `docs/CONFIG.md` are single-writer, one
open PR at a time (W8, W9, W11, W12, W14, W18 queue in that order, each rebases
on the last). `wisp/pipeline.py` is touched by W4, W11, W18, W30: land in that
order, and W30 is last by design. `shell-plugin/Companion.qml` is touched only
by W20 (split) then W21/W25 on the new components. `wispd` is touched by W19
(rewrite): freeze other `wispd` edits (W10 `install --cua`, W24, W27, W28) until
W19's registry lands, then they add modules under `wisp/cli/`.

## 9. New things to consider (not committed scope)

Ranked by value for cost; each needs a go from the user before it becomes a unit.
1. **Window-tree grounding through cua** (if the W8 spike says the driver exposes
   it): cheaper and more reliable than pixels; reduces UI-TARS load and RAM.
2. **Undo for actions**: action journal from `cua.jsonl` plus per-tool inverse
   (reopen window, restore workspace); notification "Undo" action from W18.
3. **Scheduled and event triggers** (when a build finishes, at 9:00): reuse
   agents registry and notify; no new daemon.
4. **Secrets-aware safety**: detect password fields and omaseal prompts, refuse
   cua clicks and typing there; pairs with W9 deny list.
5. **Per-app recipes from trajectories** promoted to cua macros with dry-run
   preview in the confirm card (extends existing recipe graduation).
6. **Local model residency manager**: wisp asks `wisp-backend-watch` to unload
   brain when the batch lane or a build needs RAM; closes the oomd loop at the
   source.
7. **Multi-monitor awareness** (eDP-1 off in clamshell, Odyssey scale 1):
   coordinates and ghost cursor per monitor; cheap once W7 exposes monitors.
8. **Handoff to Claude Code or Codex agents** as an explicit opt-in route with
   spend cap; default stays local. (User-gated per spend policy.)

## 10. Crosswalk

| Old ID | New ID | Status |
|---|---|---|
| Ember U1, U2, U6 | #57, then W17 (copy and reader remainder) | done (#57, #71) |
| Ember U3 | W17 | done (#71) |
| Ember U4, U5 | W20 | done (#75); Companion/Panel split continues in W21b |
| Ember U7, U11, U12, U13 | W21 | in progress (#80 merged, W21b open) |
| Ember U8 earcons | W21 (assets sub-task; synthesised, hand-authored) | planned |
| Ember U9, U18 | #58, then W26, W27 | #58 done; W26, W27 planned |
| Ember U10 | W23 | in review (#82) |
| Ember U14 | W24 | planned |
| Ember U15, U16 | W25 | planned |
| Ember U17 | W22 | planned |
| Ember U19 | W32 | planned |
| Ember U20 | W33 | planned |
| Backend U1 | #59, W2 | #59 done; W2 todo |
| Backend U2 | #64 | done (#64) |
| Backend U3 | W3 | done (#70) |
| Backend U4 | W4 | planned |
| Backend U5 | #62, W7 | done (#62) |
| Backend U6 | W12 | planned |
| Backend U7 | #65 (+W10, W29 probes) | #65, W10 done; W29 planned |
| Backend U8 | W11 (+#55) | #55 done; W11 todo |
| Backend U9 | #66 | done (#66) |
| Backend U10, U11 | W14, W15 | planned |
| Backend U12 | W13 | planned |
| Backend U13 | W16 | planned |
| Backend U14 | #63, W5, W6 | #63, W5 done; W6 todo |
| Backend U15 | W31 | planned |
| Backend U16 | W29 | planned |
| cua pointer backend (#61) | W8 to W10 | done (#61, #73, #79, #81) |
| New this plan | W1, W9, W18, W19, W28, W30, W34 | W1 (landing), W9, W18, W19 done; rest planned |

## 11. Open questions

1. Does cua-driver expose window-scoped clicks, key/type and a window tree? (W8 spike.)
2. Which notification server owns D-Bus on this machine (Omarchy shell versus
   mako/swaync)? W18 detects it; confirm actions render in the actual server.
3. Warm whisper or Parakeet for STT (W12 benchmark decides).
4. Keep CLI aliases for one release or drop immediately (W19)?
5. Should the Rust core keep parity for subscribe and cua, or freeze at the
   minimal subset (W31)?
6. Is a premium handoff route (item 8 above) wanted at all?
