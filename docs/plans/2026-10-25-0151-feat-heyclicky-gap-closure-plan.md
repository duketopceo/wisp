---
title: "feat: Close the HeyClicky delta — paper surface, perception polish, and the Windows port"
date: 2026-10-25
type: feat
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
origin: docs/plans/2026-10-16-001-feat-heyclicky-teardown-delta-plan.md
---

# feat: Close the HeyClicky delta — paper surface, perception polish, and the Windows port

## Goal Capsule

- **Objective:** wisp covers every remaining measurable gap the HeyClicky
  teardown exposed — most visibly a live, watchable **output artifact** (the
  "paper") that shows what the agent is doing instead of only hearing it —
  while keeping wisp's stronger consent model and its real (not
  `danger-full-access`) sandboxing. Afterwards wisp is feature-superior, not
  just feature-comparable.
- **Means:** port the decoded mechanics verbatim where they are self-contained
  specs (the `note.md` `::` markup, the tuning constants, the warm-ears STT
  design, the pixel-settle numbers) and rebuild only where wisp's architecture
  differs (KTD1–KTD4).
- **Authority:** the teardown report at
  `~/heyclicky-research/heyclicky-windows-teardown.md` is the evidence source;
  its *Limits* section bounds what is proven (static analysis only — grounding
  internals and model routing stay assumptions, not facts to build on).
- **Stop conditions:** stop if a delta turns out to need live-runtime evidence
  we cannot legally/technically obtain, or if a ported mechanism regresses an
  existing route's latency or safety guarantees (the turn pipeline's
  cancel/cleanup contract is not negotiable).
- **Execution profile:** sequential unit landing on `master`-descendant
  branches per repo working agreement; the replay harness is the proof vehicle
  for everything before U11.

---

## Product Contract

### Summary

The Oct-16 H-plan built H1–H9 from docs and the MIT predecessor — it explicitly
recorded "no decompilation done." The REA teardown of the installed Windows
build (HeyClicky 1.1.3, .NET 9 / WinUI 3) now fills that gap with hard
specifications: a complete output-artifact protocol, exact tuning constants,
and several small mechanics wisp lacks. This plan closes the full remaining
delta table and, as its own phase, finishes the Windows port already in flight.

### Problem Frame

HeyClicky's UX advantage is not its agent runtime (stock Codex 0.152.1 under a
wrapper — architecturally equivalent to ori-opencode) but its **surface**: a
`note.md` file the agent rewrites in place that renders as a live card —
`tiles`, `tickets`, `letters`, `charts`, `sketches`, a plan strip that marks
`{now}`/`{pick}`/`{needs}` and vanishes on finish. Wisp answers by voice and
`[POINT]`-family tags but leaves no durable, watchable artifact of *what the
agent decided*. Secondary deltas are narrower: their walkthrough arms a
screen-diff guided target (wisp's advance is window-state only), their screen
settle is a pixel-diff heuristic, their STT socket pre-opens at trigger, and
their proactive/dictation policies ship tuned constants we have now measured.

### Requirements

- **R1.** A turn can maintain a **paper**: one `note.md` per conversation
  (under the run/state dir) that the agent rewrites in place across the turn,
  using the decoded `::` object markup (`::tiles`, `::ticket[...]`, `::ask`,
  `::question`, `:::letter`, `:::chart`, `:::sketch`) and plan markers
  (`{now}`, `{pick}`, `{needs}`).
- **R2.** The user can *watch* the paper live: the panel/pill and a CLI tail
  surface the current note content as it is patched, including the plan strip
  that clears on finish.
- **R3.** The brain's act/route prompts teach the markup with the extracted
  HeyClicky grammar text as the contract basis (adapted to wisp's tools), so a
  model produces correct markup without new training.
- **R4.** Act/walkthrough waits on **pixel settle** (image-diff calm fraction
  and timeout per KTD4) instead of relying only on title/loading-state checks.
- **R5.** Walkthrough steps can advance on **non-window visual change**
  (element-level diff fallback) so web/app steps that do not change window
  state still progress.
- **R6.** The STT session is **pre-opened at trigger** (warm ears): the
  endpoint connection is established during the listening phase so
  first-transcript latency excludes connect+handshake.
- **R7.** Mic resilience: on input device failure mid-turn, capture fails over
  to the default device without losing the turn; BT/headset capture is held
  through the spoken reply.
- **R8.** Dictation gains a **correction detector**: an immediate post-dictate
  edit that Levenshtein-matches a single word is recorded as a vocabulary
  correction (observation window per teardown).
- **R9.** Suggestion etiquette matches measured values (cap ~3/day, dwell
  windows, ambient-quiet suppression) in `suggest_policy.py`.
- **R10.** Exclusive-fullscreen foreground content (games) suppresses
  drawing/pointer overlays automatically.
- **R11.** Windows: the test suite reaches a green-with-documented-skips
  state and `wispd install` completes its registration path (elevation-aware).

### Key Decisions

- **Copy the paper protocol verbatim rather than design a wisp dialect.**
  The `::` grammar is a complete, proven spec already extracted; inventing a
  second markup would spend effort and lose compatibility with every prompt
  we crib. *(session-settled: user-approved — "build wisp better than
  heyclicky" via the research; governs R1–R3)*
- **All nine deltas, phased — not just the output surface.** The user chose
  the full delta table over a surface-only plan. *(session-settled:
  user-directed; governs R4–R9)*
- **Windows port rides as a trailing phase, not a parallel plan.**
  *(session-settled: user-directed; governs R11)*

### Success Criteria

- A replay turn (agent route) emits a `note.md` containing at least
  `::tiles`/`:::letter` and renders in the panel; `wispd note` tails it.
- Act step that used to rely on `is_loading_state` completes via pixel-settle
  in ≤ the configured cap with no hang on a title-stuck page.
- Turn replay shows STT first-byte arriving earlier with warm ears than the
  cold path (measured span, fixture-controlled).
- `python -m unittest discover -s tests` on Windows: 0 errors; every skip is
  an explicit `needs-unix`/POSIX-only gate; Linux/macOS suites unaffected.

### Scope Boundaries

- **Not built:** grounding internals (`SnappedTarget`-style element snapping)
  — unproven by static analysis; stays a research question, not planned work.
- **Not built:** their `danger-full-access` / `approval_policy = never`
  posture. Wisp's tiered risk + denylist is the stronger design; consent
  stays briefing-level-consistent with `suggest_policy`/route gates.
- **Not built:** App.Ink's full renderer (269 types, uninspected). We rebuild
  the *protocol*, not their ClearScript pipeline; wisp's overlay renders the
  `::` objects natively.
- **Not built:** server-side behavior (billing, "ears" paywall, account
  concepts) — those are their hosted layer, inapplicable.
- **Deferred to follow-up work:** model-catalog parity (their multi-provider
  routing table), Chrome-extension equivalence (already a separate H-item),
  U10 packaging items beyond install registration.

### Dependencies / Assumptions

- `~/heyclicky-research/heyclicky-windows-teardown.md` and the extracted
  prompts/constants remain available (external, not in-repo — per research
  hygiene the repo keeps only what this plan cites).
- Assumed but unverified: the `::` grammar text recovered from embedded
  prompts is complete enough to drive a renderer; a malformed-object fallback
  (render as letter text) covers gaps.
- The Windows test sweep continues on top of the in-flight env/transport
  fixes already in the working tree.

---

## Planning Contract

### Key Technical Decisions

- **KTD1 — Paper is a file, not an event.** The note lives at a known path
  (`<state>/notes/<turn-or-conv>.md`) rewritten in place by the agent's note
  ops (`note set/patch/close` tool calls mirroring their rewrite-in-place
  semantics). A watcher tail publishes `note_changed` events on the IPC bus;
  the panel renders on events rather than polling. Files give routines,
  labels, and `wispd note` a durable artifact for free.
- **KTD2 — Prompt-side contract mirrors the extracted grammar.** Brain and
  route prompts get a compressed `::` spec (objects, the `:::letter`/
  `:::chart`/`:::sketch` blocks, plan markers, the "reply is the note in
  short" rule, in-place rewrite semantics). Unknown/garbled markup degrades
  to letter text — never an error surfaced to the user mid-turn.
- **KTD3 — Warm ears = pre-open at `listening`, cancel on early exit.** The
  STT provider connection is initiated as the turn enters `listening` and is
  closed via the normal turn cleanup if the turn dies before `transcribing`
  — no new lifecycle, just an earlier start. W12's design note is the
  reference.
- **KTD4 — Steal the numbers, not the shape.** Copied constants land as
  named config defaults rather than inline literals: pixel-settle 0.5% calm /
  150 ms sample / 4 s cap, ≤3 proactive prompts/day, walkthrough 15-step /
  2-min arm / 0.03-diff tolerance, PTT 120 s (already matches), routine
  window 2 min–1 week.
- **KTD5 — Windows: degrade-by-guard, never fake the platform.** The port
  keeps Linux behavior byte-identical and makes Windows-only paths explicit
  (TCP transport, `resolve_exe`, job-object tree kill, msvcrt locking,
  USERPROFILE/PATHEXT/PYTHONUTF8 passthrough). Tests that need real unix
  semantics skip with named reasons; nothing pretends Hyprland exists.

### High-Level Technical Design

```text
trigger ──► listening ──► transcribing ──► deciding ──► acting ──► speaking ──► done
   │            │               │                                    │
   │            └─ warm STT      └─ note ops (KTD1)                   └─ fullscreen gate (R10)
   │               opens here        note.md rewritten in place        overlay suppressed
   │                                │                        │
   │                                ▼                        ▼
   │                         bus: note_changed          pixel-settle + screen-diff
   │                                │                        advance (R4, R5)
   │                                ▼
   └──────────────────────► panel/pill + `wispd note` render `::` objects (KTD2)
```

Data flow: `note.py` owns the file + parser; `stage_speak`/panel + the bus
consume `note_changed`; the brain prompt (KTD2) produces the markup. Paper is
an output surface — it never feeds back into routing decisions in this plan.

### Alternative Approaches Considered

- **Event stream instead of a note file** — publish each object on the bus
  and let the panel accumulate state. Rejected: it gives up the durable
  artifact (routines, labels, `wispd note` all read the file for free) and
  diverges from the proven rewrite-in-place semantics that keep the surface
  simple for the model. File + `note_changed` is strictly more capable.
- **Invent a wisp-native markup dialect** — a fresh `[TAG]` extension of
  `points.py`'s grammar. Rejected: re-spends design effort for zero
  compatibility gain; the decoded `::` grammar is complete, already
  prompt-tested in production, and directly copyable.
- **Rebuild their renderer (ClearScript-style JS draw engine)** — out of
  scope by construction: the plan ports the *protocol*; wisp's native
  surface renders objects it already has equivalents for, with text
  fallback for the rest.

### Assumptions

- The `::` markup list recovered statically covers the objects their
  production prompts emit; unknown tokens render as letter text.
- Pixel-settle needs only a downscaled grayscale diff — no new dependencies
  (existing screenshot path supplies frames).
- The note surface does not change IPC protocol versioning: `note_changed`
  is additive; older clients ignore it.
- Task Scheduler registration on Windows is a per-user action that may need
  elevation in some environments — the installer degrades to instructions,
  not failure.

---

## Implementation Units

### Phase A — The paper (R1–R3)

### U1. Note surface: file, parser, and IPC events

**Goal:** A `note.md` per conversation at a known path, rewritten in place,
with `note_changed` published on the bus.
**Requirements:** R1, R2.
**Dependencies:** none.
**Files:** `wisp/note.py` (new), `wisp/ipc.py` (event type), `wisp/state.py`
(path wiring), `tests/test_note.py` (new).
**Approach:**
1. `note.py` owns path resolution (`<XDG_STATE_HOME>/wisp/notes/<conv>.md`),
   the `::` markup parser (objects, `:::` blocks, plan markers), and
   write/patch/close ops callable from the agent loop.
2. Writes are whole-file rewrites (their semantics) with fsync; a watcher in
   `ipc`/state publishes `note_changed` with the new object list.
3. Parse is tolerant: unknown objects and malformed blocks degrade to
   letter-text segments; the parser never raises on agent output.
**Execution note:** build the parser against a fixture file of decoded markup
examples first — the grammar is the contract, not the storage.
**Patterns to follow:** `wisp/points.py` (tag grammar precedent), the
`StateBus` publication style in `wisp/state.py` (subscribed via
`ipc.Daemon`'s `bus=` wiring).
**Test scenarios:**
- Writing a note with `::tiles`, `:::letter`, `{now}` produces the parsed
  object list and a `note_changed` event.
- A rewrite replacing `{now}` with `{needs}` yields one event with the
  updated plan strip.
- Garbage markup (`::bogus`, unclosed `:::chart`) degrades to letter text —
  no exception, event still fires.
- Two sequential writes from one turn produce two ordered events.
**Verification:** `python -m unittest tests.test_note` green; event visible
via `wispd daemon` bus subscribe in a manual smoke.

### U2. Paper rendering: panel/pill + `wispd note`

**Goal:** Users watch the note as it is written — plan strip, tiles,
letters — plus a CLI tail.
**Requirements:** R2.
**Dependencies:** U1.
**Files:** `wisp/cli/core.py` or `wisp/cli/` new `note` command,
`wisp/stage_speak.py` (render hook), shell/panel consumer,
`tests/test_note_render.py` (new).
**Approach:**
1. `wispd note` tails the current note (subscribe to `note_changed`, print
   rendered text form; `--raw` prints the file).
2. The panel/pill renders the note's current objects: plan strip while the
   turn runs (cleared on `done`), tiles inline, letters as flowing text.
3. Renderer maps each `::` object to the existing visual surface — no
   ClearScript clone; sketch/chart objects render as their text fallback in
   v1.
**Test scenarios:**
- A turn emitting `::tiles` + a `{now}` plan strip renders both while acting
  and drops the strip at `done`.
- `wispd note` on a completed turn prints the final rendered text.
- Note with only `:::letter` renders identically to today's spoken answer.
- `wispd note --raw` prints the verbatim file.
**Verification:** replay fixture turn produces renderable note objects;
manual `wispd note` during a live turn shows updates.

### U3. Prompt-side contract: brain/route prompts teach the markup

**Goal:** The model actually emits the protocol — compressed `::` spec into
the brain system/context with wisp-tool adaptation.
**Requirements:** R3.
**Dependencies:** U1 (parser is the validity oracle).
**Files:** `wisp/brain.py` (prompt assembly), `wisp/copy.py` (contract text),
`tests/test_brain_prompt.py` or fixture-level replay expectations.
**Approach:**
1. Port the extracted grammar text as a compact spec section: objects,
   `:::` blocks, plan markers, "the reply is the note in short", rewrite-in-
   place.
2. Adapt tool names to wisp's toolbelt (their `sessions_*` equivalents map
   to wisp's agent/delivery tools); keep `danger-full-access`-style wording
   out — consent framing stays wisp's.
3. Act/agent routes get the full spec; Talk lane gets the letter-only subset
   so spoken answers stay unchanged.
**Test scenarios:**
- Brain context contains the `::` spec on agent/act routes and not on the
  Talk answer path.
- A scripted brain response emitting `::tiles` is parsed by `note.py` into
  objects (round-trip through U1's parser).
- Malformed markup from the brain produces a fallback letter, never an
  error status.
**Verification:** replay turn with markup-emitting fake brain produces a
well-formed note + rendered output.

### Phase B — perception and pacing (R4–R5)

### U4. Pixel-settle wait for act/walkthrough

**Goal:** Replace title-based loading checks with a downscaled grayscale
pixel-diff settle detector (KTD4 constants), used by act steps and
walkthrough arming.
**Requirements:** R4.
**Dependencies:** none (shares capture path with U5 but independent).
**Files:** `wisp/settle.py` or `wisp/walkthrough.py` (detector), capture
source reuse, `tests/test_settle.py` (new).
**Approach:**
1. Downscale screenshot to ~192 px width, grayscale, per-frame diff;
   "calm" when changed-fraction < 0.5% for the sample window, hard cap 4 s.
2. Replace/augment `is_loading_state` call sites with `wait_settle()` —
   title check remains as a fast-path.
**Test scenarios:**
- A static screen settles within the sample window.
- A screen changing >0.5% every frame exhausts the 4 s cap and proceeds.
- Title-loading false (stuck title) + changing pixels → settle proceeds on
  pixels, proving the title fast-path no longer blocks.
**Verification:** unit tests on scripted frame sequences; replay act turn
shows settle gating.

### U5. Walkthrough advance on non-window visual change

**Goal:** Per-step screen-diff fallback so steps that do not change window
state (web clicks, in-page changes) still advance within the 2-min arm.
**Requirements:** R5.
**Dependencies:** U4 (diff plumbing), existing `walkthrough.py`.
**Files:** `wisp/walkthrough.py`, `tests/test_walkthrough.py` (extend).
**Approach:**
1. Each step arms a guided target region (element rect when grounded, else
   full frame); advance when the region diff exceeds the 0.03 tolerance OR
   window-state changes (existing path).
2. Web clicks and non-window mutations land under the diff path; cursor-only
   drift is filtered by the tolerance.
**Test scenarios:**
- Step with no window change but >0.03 region diff advances.
- Sub-tolerance flicker (cursor blink) does not advance.
- 2-min arm expiry ends the walkthrough (existing behavior preserved).
**Verification:** scripted walkthrough fixtures in the replay harness.

### Phase C — ears and voice robustness (R6–R8)

### U6. Warm ears: pre-opened STT session

**Goal:** First-transcript latency drops by moving endpoint
connect+handshake into `listening`; session is torn down on early exit
(KTD3).
**Requirements:** R6.
**Dependencies:** none.
**Files:** `wisp/speech.py` / STT provider seam, `wisp/pipeline.py`
(listening hook), `tests/test_warm_ears.py` or replay-span assertions.
**Approach:**
1. On `listening`, open the provider session (socket for stream providers,
   or a no-op prefetch for batch endpoints) and hold the handle on the turn
   context.
2. `transcribing` consumes the warm handle; any early-cancel closes it in
   turn cleanup (existing cancel contract).
3. Provider seam gains `warm()`; OpenAI-compatible endpoints benefit
   immediately, whisper.cpp gets model-warm instead of socket-warm.
**Test scenarios:**
- Turn reaching `transcribing` reuses the warm session — provider sees no
  second connect (call log asserts).
- Turn cancelled in `listening` closes the warm handle — no leak under the
  LeakGuard.
- Cold fallback when `warm()` raises → normal path, no turn error.
**Verification:** first-token span in replay improves vs cold baseline.

### U7. Mic resilience: dead-mic failover + reply hold

**Goal:** Input device death mid-turn fails over to the default capture
device; the capture channel is held until the spoken reply finishes.
**Requirements:** R7.
**Dependencies:** U6 (session lifecycle touches the same seam).
**Files:** `wisp/realinput.py` / capture source, `wisp/speech.py`,
`tests/` additions.
**Approach:**
1. Detect zero-frames/device-removed during capture; reopen on the default
   device within the turn's remaining PTT budget (their 120 s) rather than
   failing the turn.
2. Keep the capture handle (or monitor path) alive through `speaking` —
   matches their BT-hold behavior; release at `done`.
3. Platform seam: sox/Windows capture and PipeWire paths each get the
   failover branch; unresolvable failure degrades to the existing error
   code, not a hang.
**Test scenarios:**
- Capture device drop mid-recording → capture continues from default
  device; turn completes.
- No fallback device → turn ends with the existing stt/audio error code.
- Handle released at `done` — no device held after turn.
**Verification:** scripted device-drop fixtures; manual sox test on
Windows box.

### U8. Dictation correction detector

**Goal:** Single-word post-dictate edits (Levenshtein distance ≤ threshold,
inside the observation window) are recorded as vocabulary corrections —
their observed learning loop.
**Requirements:** R8.
**Dependencies:** none.
**Files:** `wisp/vocab.py`, `wisp/dictate.py`, `tests/test_vocab.py`.
**Approach:**
1. After a dictate, watch the target field for a short window; an edit that
   changes exactly one word with edit distance ≤ 2 records
   `spoken → corrected` into the vocab layer.
2. Multi-word edits, paste, and out-of-window edits are ignored.
3. Corrections feed the existing vocab learning path — no new store.
**Test scenarios:**
- "kimbal"→"kimba" single-word swap within window is recorded.
- Two-word edit is not recorded; out-of-window edit is not recorded.
- Correction appears in subsequent dictate's vocab bias.
**Verification:** unit tests on the detector plus a vocab-bias integration
case.

### Phase D — behavior policy and small wins (R9–R10)

### U9. Proactive etiquette numbers

**Goal:** `suggest_policy.py` caps and windows match the measured values —
≤3 prompts/day, dwell windows, ambient-quiet suppression.
**Requirements:** R9.
**Dependencies:** none.
**Files:** `wisp/suggest_policy.py`, `tests/test_suggest_policy.py`.
**Approach:**
1. Land the constants as named config defaults (KTD4): daily cap, dwell
   (morning window shape), quiet suppression while a turn or fullscreen
   focus is active.
2. Keep wisp's existing approval card semantics — this is tuning, not a
   rewrite.
**Test scenarios:**
- Fourth suggestion in a day is suppressed.
- Suggestion during an active turn is deferred, not dropped.
- Morning-window prompts allowed; outside-window suppressed.
**Verification:** policy unit tests + a replay suggestion fixture.

### U10. Exclusive-fullscreen carve-out

**Goal:** Drawing/pointer overlays disable automatically when the focused
surface is exclusive-fullscreen (their `FullscreenGameNote` behavior).
**Requirements:** R10.
**Dependencies:** none.
**Files:** `wisp/pointer.py` or overlay surface, `wisp/platform.py`
(fullscreen probe), `tests/` additions.
**Approach:**
1. Platform probe for exclusive-fullscreen (Hyprland fullscreen flag,
   Windows exclusive mode best-effort, macOS fullscreen window).
2. Overlay/draw calls check the probe and no-op with a logged carve-out;
   voice/text paths unaffected.
**Test scenarios:**
- Fullscreen flag set → pointer/draw calls return carved-out result, no
  overlay emitted.
- Windowed app → normal draw.
- Carve-out is logged (audit), not silent.
**Verification:** unit tests with probed flag; manual check optional.

### Phase E — Windows port completion (R11)

### U11. Windows suite green-with-documented-skips

**Goal:** `python -m unittest discover -s tests` reaches 0 errors on
Windows, failures eliminated or converted to named skips (POSIX-only).
**Requirements:** R11.
**Dependencies:** none (builds on the in-flight working tree).
**Files:** remaining failing `tests/*.py`, plus production modules where a
real Windows bug is exposed (`wisp/*.py`, `wisp/cli/*.py`).
**Approach:**
1. Continue the sweep cluster-by-cluster using the landed patterns:
   env passthrough (`USERPROFILE`, `PATHEXT`, `PYTHONUTF8`, `SystemRoot`),
   `resolve_exe`, TCP-with-port-file fakes, `.cmd` shim binaries,
   `msvcrt` locking, job-object tree kill, `needs_unix` skips.
2. Distinguish production bugs (fix) from environment-only tests (skip
   with named reason) — no semantic test weakening.
3. Encoding: file I/O carrying non-ASCII gets explicit `encoding="utf-8"`.
**Execution note:** prefer cluster fixes (one root cause → many tests)
over per-test whack-a-mole; document each skip reason.
**Test scenarios:** this unit IS the sweep — success is the suite result,
not new test cases.
**Verification:** suite run output committed to the PR description:
0 errors, skips enumerated; Linux/macOS CI unchanged.

### U12. Windows install path completion

**Goal:** `wispd install` completes on Windows: Task Scheduler registration
with elevation-aware fallback, and dry-run honored on the Windows branch.
**Requirements:** R11.
**Dependencies:** none.
**Files:** `wispd` (install_windows path), `docs/WINDOWS.md`.
**Approach:**
1. Honor `--dry-run` on the nt branch (currently it installs regardless).
2. schtasks registration: try normal create; on access-denied print the
   exact elevated command and continue (file install already succeeded)
   instead of printing a bare failure.
3. Keep `wispd.cmd` launcher; document PowerToys/AHK hotkey binding.
**Test scenarios:**
- `--dry-run` on Windows writes nothing.
- Unprivileged schtasks failure → printed recovery command + non-zero-but-
  reported status (documented exit behavior).
- Elevated registration succeeds on a box that permits it (manual check).
**Verification:** manual install run on this box; `wispd doctor` reports
installed files.

---

## Verification Contract

- `python -m py_compile wispd wisp/*.py wisp/tools/*.py scripts/propose_criteria.py tests/*.py`
- `python -m unittest discover -s tests -v` — the repo's CI suite; on
  Windows the exit criterion of U11 is **0 errors, failures only from
  documented platform skips**.
- Replay harness is the primary behavioral proof: `python -m unittest
  tests.test_turn_replay` must stay green per unit that touches the turn
  pipeline (U1–U6).
- For timing-sensitive units (U4, U6) the proof is the measured span in a
  fixture-controlled replay, not wall-clock on a live box.
- No unit lands without its listed test file present in the diff.

## Definition of Done

- Every U's verification line passes on the developer box; Linux path
  unchanged where the unit is platform-neutral (no POSIX regressions).
- The note surface round-trips end-to-end in a replay agent turn: brain →
  markup → note file → bus → render.
- Delta table in the teardown doc is all-addressed: each row is landed,
  explicitly deferred with reason, or recorded unproven.
- Windows install: files + task (or printed elevation instructions) on a
  clean run of `wispd install`.
- No abandoned-attempt code left in the diff; teardown artifacts stay out
  of the repository.
