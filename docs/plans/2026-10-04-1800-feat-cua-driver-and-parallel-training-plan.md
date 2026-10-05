---
title: "CUA driver full wiring + parallel training scale-out (local + CubeVM)"
type: feat
status: draft
date: 2026-10-04
supersedes: []
---

# CUA driver full wiring + parallel training scale-out

Two tracks planned together because they converge: the cua-driver work
determines *which surfaces* Wisp can act on, and the parallel-training work
determines *how fast* we generate data to train on those surfaces. The
research swarm is Track A's phase zero — the user explicitly asked for many
research agents before implementation commits.

Decisions locked with the user: **$10/day shared spend cap** (already set in
`~/.config/wisp/config.toml` as `[brain] daily_cap_usd = 10`), **both local
and CubeVM parallelism**, **DOM-mode only inside VMs** (no display server
needed — headless chromium + evaluate).

## Verified foundation (do not re-spike)

From the live investigation on omarchy-max (luke-agents `_LUKE/cua/SKILL.md`,
commit `31f00b8`):

- `cua-driver` 0.33.1 aarch64 binary at `~/.local/share/cua-driver/`, owned by
  `cua-driver.service` (user unit, enabled, running with
  `CUA_DRIVER_RS_ENABLE_WAYLAND=1` — required or everything falls back to
  broken X11 paths).
- `cua-hyprland-plugin.so` built from the release build-kit against exact
  Hyprland 0.56.2, loaded into the live compositor (`hyprctl "cua:status"` →
  `transport: ready`); `plugin.cua.enabled = true` in the stash
  `~/.local/share/machine/lukekimball/hyprland.lua` + autostart `hyprctl
  plugin load`. Both survive reload and sync-watch.
- Verified end-to-end: `list_windows` → 8 real windows with bounds/pids,
  `get_desktop_state` → live screencopy capture, background `click`/`move`
  (virtual pointer, no focus steal) → delivered through the Wisp toolbelt
  (`platform.py` `cua` pointer backend, auto order `cua → hyprcursor →
  ydotool → wlrctl`).
- `wisp/cua.py` typed client exists (131 lines): `call()`, `click`,
  `move_cursor`, `list_windows`, `window_state` — the rest of the 60+ tool
  surface is unwired.
- W9/W10 landed: `wisp/cua_safety.py` (deny/allow, rate limits, kill switch,
  audit) and `wisp/probes_cua.py` + `scripts/cua/` (doctor/health).
- Training: clicklab runs on **browseros-neo** (:9211) since `8ad788b` —
  streamable-HTTP session-id echo + `com.browseros.neo/session` caching in
  `mcpclient.py`, `open_lab` closes stale `:8797` tabs and atexit-closes its
  own. Cost watcher live (`7ec4236`): `~/.local/share/wisp/spend.jsonl` +
  per-task `cost_usd`/`tokens` + `budget_ok()` gate + runner abort at cap.
- CubeSandbox API live at `127.0.0.1:3000` (`/health` → `{"status":"ok",
  "sandboxes":0}`, auth required — bearer/X-API-Key). Repo at
  `~/src/cubesandbox` ships a `browser-sandbox` example (browser template in
  a MicroVM), `ubuntu-desktop`, `mini-rl-training`, and `cube-bench`.

## Research swarm results (all 6 landed 2026-10-04)

Docs live in `docs/research/`. Verdicts that reshape the units below:

- **R1 (`cua-tool-catalog.md`)**: 62 tools, full matrix. **element_tokens are
  dead on Wayland** (`degraded: accessibility_window_identity_unproven`,
  zero tokens, zero frames) → A2 shrinks to pointer cleanup, no semantic
  clicks. Observation is excellent. `get_accessibility_tree` is X11-only
  (`windows:[]`); `list_windows` has no focused flag → the `_a11y`
  grounding path is double-dead. Session labels must be passed for
  snapshot context (`zoom` needs it). `move_cursor` `scope:"desktop"`
  moves the REAL pointer — `scope:"window"` is the overlay move.
- **R2 (`cua-sessions-cursor.md`)**: agent cursor is a real layer-shell
  surface, verified pixel-level — **A4 is GO**. Caveat: cannot be excluded
  from Wayland captures (toggle `set_agent_cursor_enabled` off around
  observation if it pollutes). Session API documented; ~300s idle TTL.
- **R3 (`cua-browser-tools.md`)**: **not viable** for clicklab — no
  Runtime.evaluate primitive, refs carry no geometry. Verdict: keep neo;
  if a non-neo transport is needed use raw CDP WebSocket (which is exactly
  what B4 should use in-VM anyway).
- **R4 (`cua-recording-verify.md`)**: **GO** — session-scoped recording
  persists across one-shot calls (fits our transport), turn-dirs carry
  action.json delivery-truth + before/after PNGs + evidence; wf-recorder
  video works; `verify_state` predicates live. Caveat: only cua-dispatched
  actions are captured — wire it to the desktop/cua path, not neo clicks.
- **R5 (`cua-bench-eval.md`)**: adopt selectively + mine tasks —
  `cua-bench-basic` (13 tasks/68 variants, arm64 images verified) is the
  pixel-surface arena DOM can't be; `libs/cua-s1` is a worked SFT→RL
  recipe. Deferred to a later pixel-mode round.
- **R6 (`cube-parallel-arena.md`)**: **GO, one repair** —
  `cube-sandbox-cube-proxy.service` crash-loops (tailscaled holds :443;
  fix `CUBE_PROXY_HTTPS_PORT=11443` in `.one-click.env` or bypass via tap
  IPs `10.100.0.0/18` → envd `:49983` + chromium `:9222`). Ready arm64
  `code-interpreter` template exists; browser image is amd64-only → custom
  arm64 image or runtime-install + `create_snapshot()` + `Sandbox.clone`
  fan-out. ~8–12 sandboxes on free RAM. Egress to OpenRouter works
  (optional L7 header injection so the key never enters the VM).

## Track A — CUA driver: research swarm, then wire

### A0 — Research swarm (6 agents, parallel, read-only) — **DONE**

Each unit = one background research agent producing a markdown doc under
`docs/research/` plus a "wire-up verdict": which wisp file each finding
belongs to. Agents are read-only; they may run `cua-driver call`,
`describe <tool>`, and `doctor` against the live daemon but must not change
Wisp code, Hyprland config, or the daemon's config.

- **R1 — Tool catalog deep dive** → `docs/research/cua-tool-catalog.md`.
  For every tool in `cua-driver list-tools` (~94): `describe` schema,
  required args, Wayland support (native vs XWayland-only vs broken),
  session requirement. Output: support matrix + top-10 highest-value tools
  for Wisp's act loop.
- **R2 — Sessions, lifecycle, agent cursor** → `docs/research/cua-sessions-
  cursor.md`. `start_session`/`end_session`, `set_agent_cursor_theme/
  motion/enabled`, `parallel_mouse_drag` (MPX), `get_agent_cursor_state`.
  Question: can the Companion's ghost cursor be the driver's own agent
  cursor (real rendered cursor, not an overlay)? Test: create session,
  enable cursor, move it, screenshot.
- **R3 — `browser_*` toolchain** → `docs/research/cua-browser-tools.md`.
  `browser_prepare`/`browser_click`/`browser_type`/`browser_navigate`/
  `browser_dialog`/`browser_set_input_files`: what browser + binding they
  need (CDP? extension?), whether they work against the neo browser or only
  cua-prepared browsers, ref model vs our element-id legend. Verdict: could
  these replace neo evaluate in clicklab?
- **R4 — Recording, replay, verification** → `docs/research/cua-recording-
  verify.md`. `start_recording`/`stop_recording`/`get_recording_state`,
  `replay_trajectory`, `verify_state` (bounded predicates on a window),
  `parse_visual_regions`, `zoom`. Question: does recording capture
  screenshots+actions as trajectory data we can feed `train.update_bank`?
  Test: record a 3-click sequence, inspect the on-disk turn folders.
- **R5 — cua-bench / RL environments** → `docs/research/cua-bench-eval.md`.
  Does trycua ship runnable desktop-surface evals we could host in a VM?
  Read their repo docs (fetch trycua/cua GitHub), enumerate envs, license
  (MIT), and aarch64 feasibility.
- **R6 — CubeVM parallel arena feasibility** → `docs/research/cube-parallel-
  arena.md`. Read `~/src/cubesandbox`: browser-sandbox example end-to-end,
  how to mint an API token (docs/deploy), SDK python surface (`sdk/python`),
  template build flow (`CubeTemplateCenter`, `create-from-image`), resource
  limits on this host (64GB, how many MicroVMs realistic), network egress to
  OpenRouter (CubeEgress policies), and whether the `browser-sandbox`
  template is prebuilt or must be built on aarch64. Deliverable: exact
  `Sandbox.create(...)` recipe or a clear blocker list.

Done condition: six docs, each ending in a ranked wire-up list. No code
changes.

### A1 — cua typed client completion (`wisp/cua.py`)

Extend the `Client` class to cover the vetted tool set (from R1/R4): `click`
by `element_token`, `double_click`, `right_click`, `drag`, `type_text`,
`press_key`, `scroll`, `set_value`, `get_desktop_state`, `zoom`,
`verify_state`, `launch_app`, `list_apps`, session lifecycle
(`start_session`/`end_session`), recording (`start_recording`/
`stop_recording`/`replay_trajectory`). Keep the existing `call()` escape
hatch; typed wrappers only where the arg shape is non-obvious.

Files: `wisp/cua.py`, `tests/test_cua.py` (extend existing — see current
fake patterns in `tests/fakes/`).

Test scenarios: each wrapper serializes correct JSON; strict/non-strict
parse paths; timeout passthrough; element_token calls carry the token, not
coords.

### A2 — Pointer correctness cleanup (`wisp/pointer.py`) — rescoped by R1

~~Semantic/element-token clicks~~ — **dead on Wayland** (R1: zero tokens,
zero frames, `accessibility_window_identity_unproven`). Pixel coords are
the only rung. What this unit becomes:

- `move_cursor` calls use `scope:"window"` (overlay move) not `desktop`
  (real-pointer move) — wisp currently moves the user's cursor (R1/R2).
- Pass a stable session label on every `Client.call` — snapshot context
  (`zoom`, recording linkage) is lost without it (R1 §sessions).
- Wire scroll + drag + button capabilities with `delivery_mode`
  escalation (Wayland background delivery is refused → foreground/dm
  path documented in R1's wire-up section).

Files: `wisp/pointer.py`, `wisp/tools/system.py` (click arg parsing),
`tests/test_pointer.py`.

Test scenarios: token click calls driver with token (no coords); coordinate
args still take the pixel path; missing token → clean SKIP not crash;
registry ordering.

### A3 — Desktop-state screenshots (`wisp/tools/system.py`)

`get_desktop_state` (+ `zoom` for regions) as the desktop-scope screenshot
backend when `cua` is the active pointer — replaces `grim`. Returns JPEG in
the desktop coordinate frame; must verify the coordinate frame matches the
pixel coordinates the model emits (R1 documents the frame; mismatch = off-
by-scale bugs, watch for the eDP-1 @2x scale).

Files: `wisp/tools/system.py`, `tests/test_tools.py`.

Test scenarios: shot returns path + dims; scale factor applied; falls back
to grim when cua unavailable.

### A4 — Agent cursor = ghost cursor (Companion UI bridge)

If R2 confirms the driver's cursor renders on Wayland: Companion's ghost-
cursor visual becomes `start_session` + `set_agent_cursor_*` + `move_cursor`
instead of a shell overlay. If it doesn't render, R2's doc records why and
this unit is dropped — do not build the fallback overlay in this unit.

Files: `wisp/cua.py` (session wrappers from A1), whatever `wisp/ui/` module
owns ghost cursor (W21 — check `shell-plugin/components`), tests per that
module's harness.

### A5 — Trajectory recording in clicklab

If R4 confirms recording is usable: `run.py` wraps each task in
`start_recording`/`stop_recording`, stores the turn-folder path on the
record, and `--replay` can drive `replay_trajectory` as a deterministic
regression check (currently replay re-invokes tools itself — driver replay
is stronger because it re-executes real input). Only valuable for desktop-
scope runs; DOM runs already capture everything in `steps`.

Files: `scripts/clicklab/run.py`, `wisp/cua.py`, test in whatever the
clicklab suite file is named.

### A6 — browser_* eval (deferred decision)

R3 decides: if cua's browser tools can bind the neo browser or a local
chromium with refs comparable to our legend, prototype behind a flag
(`--backend=cua`) in one suite. Otherwise skip — neo evaluate already works.

## Track B — Parallel training scale-out

### B1 — Parallel-safe clicklab (prerequisite bug, local)

`open_lab` currently closes **every** `:8797` tab — two concurrent runs
would kill each other's pages. Fix before any parallelism: maintain a live
registry `~/.local/share/wisp/clicklab-live/<pid>.json` `{pid, page_id}` —
`open_lab` only closes tabs not claimed by a live registry entry, registers
itself, atexit removes entry + closes own page (already does the close).
`serve()` already tolerates a bound port (`None` return); shared serving is
fine since all runs serve the same directory.

Files: `scripts/clicklab/run.py`, plus a test around the registry logic
(extract to a function so it's unit-testable without a browser).

Test scenarios: two registries → neither closes the other's tab; stale pid
entry (dead process) → reclaimed; single-run behavior unchanged.

### B2 — `hammer-parallel.sh` (local scale)

New script next to `scripts/clicklab/hammer.sh`: launches N concurrent
`run.py` workers (N=4 default, arg), each with its own suite×model×seed
slice, each logging to `training-logs/par-<ts>-<worker>.log`. Workers share
the neo browser (evaluate calls are per-page — safe) and the spend ledger
(cap is global — deliberate). Add `--workers` flag plumbed through; stagger
start by ~5s each to avoid open_lab races against the same tab list.

Constraint to verify in implementation: neo MCP throughput under 4–8
concurrent evaluate/click streams — if the server serializes, the win is
small; measure per-run wall time at N=1 vs N=4 before scaling to 8.

### B3 — Aggregation + per-model/suite report

`clicklab.jsonl` is append-only and already process-safe (line writes), so
parallel writers are fine. Add `wispd train report` (or a
`scripts/clicklab/report.py`): rolls up pass-rate, efficiency, cost, p50
latency per model × suite over a time window — the sitrep table generated
by hand today. Read-only; output markdown table.

Files: `scripts/clicklab/report.py` or a `wisp/cli/` command (W19 registry
— follow that pattern), `tests/test_cli_*.py` golden update if it lands in
cli.

### B4 — CubeVM arena (`scripts/clicklab/cube/`)

DOM-mode runs inside sandboxes — zero local browser/CPU contention:

- Template: build from the `browser-sandbox` example image (R6 verifies it
  builds on aarch64; if not, `ubuntu-desktop` or a chromium-alpine rootfs).
- In-sandbox runner: a trimmed `run.py` path that talks CDP directly to
  headless chromium inside the VM instead of neo (evaluate is the only
  browser primitive DOM mode needs — element list, click dispatch, key
  events, `__score` read). New flag `--backend=cdp` keeps the sandbox path
  out of neo entirely.
- Orchestrator `cube-hammer.sh`: `Sandbox.create` × M, scp/git-clone the
  repo (or bake into template), run suites in parallel, each sandbox writes
  its own jsonl; pull results back and append to `clicklab.jsonl` (or write
  a merged `cube-<ts>.jsonl` and merge offline — decide in implementation).
- Spend: same OpenRouter key — the ledger is per-machine. Sandboxes need
  the key passed via env (`OPENROUTER_API_KEY` in create payload or env
  file, never baked into the template) and `daily_cap_usd` respected via a
  shared cap check — simplest honest approach: give each sandbox its own
  sub-cap (`$10/M`) since the ledger isn't shared across machines.

Dependencies: R6 must produce the working `Sandbox.create` recipe +
auth; B1–B3 should land first so local parallelism absorbs the gap if R6
blocks.

## Sequencing

```
R1..R6 (parallel swarm, ~1 session)
   ├─ A1 (needs R1)  → A2, A3 (need A1)  → A4 (needs R2), A5 (needs R4)
   └─ B1 (independent, do FIRST — it's small) → B2 → B3
      B4 needs R6 + B2/B3 patterns
```

B1 is the only hard blocker for any parallelism and is ~1 unit of work —
land it immediately, before the research swarm even finishes.

## Risks and honest caveats

- **AT-SPI on Wayland is the A2 unknown.** If tokens only work on XWayland
  apps, A2 shrinks to "XWayland scope only" — still useful for Electron/Qt
  apps, not universal. R1 must answer this before A2 starts.
- **Agent cursor may not render on wlroots.** Hyprland isn't GNOME/KWin —
  the driver's cursor layer is compositor-dependent. A4 self-deletes if R2
  says no; don't let it become an overlay rabbit hole.
- **Parallel hammering multiplies spend.** $10/day ÷ 8 workers = fast drain
  when tasks are cheap but voluminous; the cap is global and the ledger is
  local-only — CubeVM workers each need their own sub-cap (B4). Cost per
  verified pass is the number to watch in B3's report, not raw spend.
- **neo MCP throughput** is unmeasured under concurrency — B2 must measure
  N=1 vs N=4 wall time before claiming the parallelism win.
- **CubeVM aarch64 support unverified.** The browser-sandbox example exists
  but whether its template/image builds on Asahi ARM64 is exactly what R6
  answers. If blocked, B4 pauses and local parallelism (B2) carries the
  load.
- **Recording adds disk write per task** — fine at local rates, watch at
  parallel rates.

## Out of scope (deferred)

- macOS/Windows cua-driver paths — Linux-only for now.
- Pixel-mode training inside VMs (user chose DOM-only for this round).
- `cua-bench` adoption — R5 reports; adoption is a separate plan if viable.
- Replacing neo as wispd's default browser path — A6 is an eval, not a
  migration.
