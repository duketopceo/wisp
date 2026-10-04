---
status: "superseded by 2026-10-04-0100-feat-wisp-unified-plan.md"
---

# Wisp Companion UX — research-grounded UI plan

Origin: user asks for a "bleeding edge" UI where every decision is backed by
current best-practice research (Clicky/Hey-Clicky, Spotlight-style bars, agent
consoles, overlay patterns). This plan converts that research into ordered,
testable units on top of the shipped conversation/agent plumbing.

## Research synthesis (reference lock)

| Reference | Pattern worth stealing | Wisp gap |
|---|---|---|
| Hey Clicky | Answer renders **at the cursor**, not in a window; spoken + visual | Shipped in #45 (bubble at cursor) |
| Hey Clicky | Three surfaces: status chip → response overlay → pointer overlay | We have orb + points overlay; the *listening* surface (`WispOverlay.qml`) is still a centered card that reads like a dialog |
| Hey Clicky | Points are **post-hoc annotations** appended by the model, never the primary answer | Already true (`state.points`) |
| Spotlight / EnConvo SmartBar | Invocation bar lives at bottom-center of the *focused* monitor; shows context prefixes (`#app`) and streams the answer inline | `WispOverlay` is centered, not bottom-anchored; no context prefixes |
| omni-cli-overlay / agent consoles | Streaming tool-call timeline, session tabs, pause/stop | `steps` array exists but renders as raw text lines; no stop control; no session history |
| OpenClicky / approval-first UIs | Risky actions present approve/deny inline where the user is looking | Choices exist; tool-confirm state is not yet surfaced in `state.json` |
| LingxY / local-first consoles | Context inspector — what the agent sees (windows, workspaces, connectors) | Inventory + `[windows]` exist server-side, invisible in UI |

Design direction: **keep the three-surface model** — bar chip (ambient) →
cursor-adjacent bubble (answers) → fullscreen pointer overlay (points/guide) —
and make the orb card + panel the *console* (history, approvals, connectors).
Do not add a fourth surface.

## Hard invariants

- Overlay stays click-through (`mask: Region {}`) and never steals keyboard focus.
- No new always-on polling: timers run only while their surface is visible.
- QML-only changes ship with no Python deps; state.json stays the single bus.
- No Astra. BYO provider untouched.

## Implementation units

### U1 — done (PR #45)
Cursor-adjacent speech bubble, mode badge in panel header, goal line in orb card.

### U2 — Listening surface redesign (`shell-plugin/WispOverlay.qml`)
Bottom-center pill on the focused monitor (Spotlight anatomy): mic-level arc,
status word (`listening`/`thinking`/`acting`), live transcript tail, mode chip.
Replaces the centered card. Choice buttons move into the pill row.

Test scenarios:
- status `listening` → pill visible, breathing follows `level`
- `awaiting_choice` → choice chips render inside the pill, click dispatches `wispd choice`
- status → `idle`/`done`/`error` → pill closes; never eats clicks at rest

### U3 — Streaming answer into the bubble
Daemon publishes partial answer text to `state.json.answer` as chunks arrive
(`wisp/pipeline.py` answer path writes per-δ; `wisp/state.py` already atomic).
Bubble + orb card re-render on file change (existing `FileView` watch — free).

Test scenarios:
- `publish` called with partial answer → bubble shows it growing (unit: patch `state.publish`, assert file content updates mid-answer)
- TTS still speaks only the final answer, not chunks
- Non-streaming provider (no delta API) → single final write, identical UX

### U4 — Agent console polish (Now tab + orb card)
- Steps render as a timeline: numbered rows, mode-colored bullet, tool name
  emphasized, last step highlighted (Companion.qml step Column + Panel Now tab).
- STOP chip in Now tab + orb card while `busy` → `wispd task_cancel` /
  `wispd stop` (absolute path, same PATH-fix pattern as labelProc).
- `ASK_USER:` questions render as a distinct "wisp asks:" row, not plain text.

Test scenarios:
- busy → STOP visible; click runs `task_cancel`
- `steps=[...]` → one row per entry, newest emphasized
- `result` starts `ASK_USER` → question row styled, no STOP

### U5 — Context inspector (Panel tab: "Context")
New tab between Now and Agents rendering what Wisp sees:
- focused app/title (`state.focus`)
- `[windows]` map: parse `wispd` context via a `wispd context` subcommand that
  prints `context.snapshot()` output, read via `Process` on tab open
- inventory counts (apps/cli_tools/mcp/skills) from `inventory.json` via FileView

Test scenarios:
- `wispd context` returns `[focus]`/`[windows]` lines (unit test exists already for snapshot; add CLI smoke)
- tab shows workspace groups; zero windows → empty-state text
- `inventory.json` missing → "run wispd inventory" hint

### U6 — Connectors tab (Panel)
`wispd connect --list` JSON mode (`--json` flag to add) → FileView of
`~/.config/wisp/mcp.json` + service catalog. Per-service row: name, status dot
(connected/needs-auth), Connect button → spawn `wispd connect <svc>` in a
`Process` (foreground CLI polls; UI shows "authorizing…" until file changes).

Test scenarios:
- `connect --list --json` emits machine-readable rows (new unit test)
- connected service shows green dot; Connect button hidden
- connect flow: button disables while Process runs; status refreshes on mcp.json change

### U7 — Session history strip (Panel Now tab footer)
Last N (5) transcripts from `session.py` as chips; clicking a chip re-expands
goal context read-only. Requires `wispd session` read subcommand or direct
FileView of session file (prefer FileView — no daemon round-trip).

### U8 — Deploy hygiene
`wispd install` currently leaves a stale nested `shell-plugin/` copy inside the
installed plugin dir. Fix install step to sync `shell-plugin/*.qml` to the
plugin root and remove the nested copy from the tree (it is not loaded).

Test scenarios:
- after `wispd install`, plugin root `.qml` mtimes ≥ repo copies; no nested dir

## Sequencing

U2 (listening pill) and U3 (streaming) are the visible-feel wins — do first.
U4 rides the same surfaces. U5–U7 are panel tabs — independent, any order.
U8 is a one-commit fix, slot whenever touching `wispd`.

## Explicitly out of scope

- Menu-bar/macos parity (deferred lane)
- Command palette / slash commands (needs a keyboard-focus surface — conflicts
  with the never-steal-focus invariant; revisit only with a deliberate design)
- Any new surface beyond chip/bubble/pointer/console
