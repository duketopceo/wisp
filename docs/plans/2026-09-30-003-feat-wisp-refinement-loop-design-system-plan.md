# feat: Refinement loop (openly correctable dev mode) + Wisp DESIGN.md theming

## Summary

Two coupled asks: (1) a **refinement loop** — when Wisp does the wrong
thing, the user can just *say so* ("no, it didn't work — open X
instead") and the next turn retries with the failure as context, logs
it, measures whether the correction fixed it, and banks the learning;
(2) a **Wisp DESIGN.md** authored against the VoltAgent
`awesome-design-md` conventions (repo already forked + cloned locally),
with light/dark token themes actually wired into the QML surfaces.

## Problem Frame

The correctness loop is currently *passive*: `wispd label incorrect`
marks a turn bad, but nothing happens with that signal — the next
utterance starts cold, and the user has to re-explain everything. What
the user described is an interactive repair loop: fail → user corrects
in-band → Wisp retries with the failure in context → both attempts are
logged and the pair is measured (did the correction converge?). This is
the same episodic mechanism as trajectories (prior plan) but triggered
by *user feedback*, not by schedule.

On the design side, all QML surfaces hardcode one dark palette
(`#1a1b26`/`#7aa2f7`/…). There is no theme layer, no light theme, and
no authored design document — despite 74 reference DESIGN.md specs
already on disk in the user's `awesome-design-md` fork.

## Requirements

- **R1** Labeling a turn incorrect (or a correction cue in the next
  utterance — "no", "that's wrong", "it didn't work", "actually")
  carries the failed turn into the retry: transcript, route, steps,
  result all injected as prior-attempt context.
- **R2** Correction turns are themselves measured: when a correction
  succeeds, the pair (fail → fixed) is recorded so `wispd label` /
  `wispd fails` can report convergence ("fixed on retry" vs "still
  broken").
- **R3** Everything is logged: corrections join `corrections.jsonl`,
  `labels.jsonl`, `trajectories.jsonl`, `trace.jsonl` — no new
  invisible state.
- **R4** `[dev]` section: `refine = true` gates the correction-context
  injection (default true — it only fires when there's something to
  correct).
- **R5** A root `DESIGN.md` authored in awesome-design-md format
  (YAML frontmatter: `colors`, `typography`, `elevation`, `motion`)
  covering a Wisp dark theme *and* light theme.
- **R6** QML surfaces read palette tokens from one place — a theme
  object bound to `~/.config/wisp/theme.json` (or built-in defaults) —
  so DESIGN.md is the spec, not decoration. `[ui] theme =
  "dark"|"light"` selects; dark stays the default.
- **R7** Suggestion cards, ghost cursor, point markers, bar glyph, and
  the debug GUI all theme consistently.

## Key Technical Decisions

- **KTD1 — Correction detection is two-channel.** Channel A: the
  `label incorrect` signal already exists — if the *most recent*
  decision was labeled incorrect, the next utterance is treated as a
  correction automatically (no cue parsing needed). Channel B: lexical
  cue phrases catch corrections the user never labeled. Either channel
  injects the prior turn; a correction is also recorded so `learn` can
  mine it.
- **KTD2 — The retry is the act loop, not a new route.** Corrections
  prepend context; Jev re-routes fresh. This keeps "no do X instead"
  able to change *route* (was answer → should have been act).
- **KTD3 — Theme source of truth is DESIGN.md; runtime artifact is
  theme.json.** DESIGN.md is human-authored prose+tokens; a small
  `wisp/theme.py` emits `theme.json` tokens the QML FileView already
  knows how to watch (same pattern as state.json). No YAML parsing in
  QML.
- **KTD4 — Light theme is designed, not inverted.** Tokens are
  hand-paired per the awesome-design-md convention (ink/canvas/surface
  naming), not programmatically inverted — that produces mud.
- **KTD5 — awesome-design-md stays a reference repo, not a runtime
  dep.** Optionally surface it as a `design-md` skill (read-only
  queries against the catalog) later; not in this plan's critical path.

## Scope Boundaries

In scope: correction-context injection + measurement, `wispd fails`,
DESIGN.md + theme.json plumbing + QML token binding for Companion.qml,
BarWidget.qml, Panel.qml, debug shell.

Out of scope: porting the design system to the Rust core's surfaces;
restyling non-wisp Omarchy chrome; shipping a light theme to the GUI
debug shell's existing stylesheet if it fights the token model (the
debug app is a dev tool — dark-only is acceptable there; document it).

## Implementation Units

### U1. Correction context injection

**Goal:** "no, it didn't work — do X" retries with the failure in
context.

**Requirements:** R1, R4

**Dependencies:** none.

**Files:**
- `wisp/pipeline.py` — detect correction turns, prepend prior-turn block
- `wisp/config.py` — `[dev] refine = true`
- `tests/test_pipeline.py` (or extend existing)

**Approach:** before Jev routing, check two signals: (a) the most
recent `labels.jsonl` entry labels the previous decision `incorrect`;
(b) the transcript opens with a correction cue (`no`, `wrong`,
`didn't work`, `actually`, `instead` — small explicit set, not a regex
farm). On match, build `prior = {transcript, route, steps, result}`
from the last `decisions.jsonl` + `trajectories.jsonl` record and
prepend it to the Jev state + act system context: "The previous
attempt <route> failed: <result>. The user is correcting it." The turn
is then routed fresh — corrections can change route.

**Test scenarios:**
- incorrect label on last turn + new utterance → Jev payload contains
  the prior result
- cue phrase alone (no label) triggers the same injection
- normal utterance after a correct/no label → no injection
- `[dev] refine = false` disables both channels

**Verification:** label a turn ✗, say "no, open discord" → the retry
reaches the right route without re-asking.

### U2. Correction measurement + `wispd fails`

**Goal:** the fail→fix pair is measurable.

**Requirements:** R2, R3

**Dependencies:** U1.

**Files:**
- `wisp/learn.py` — `fails()` report + correction-pair join
- `wispd` — `wispd fails` CLI
- `tests/test_learn.py`

**Approach:** when a correction turn completes, write a
`labels.jsonl` entry `{ref: <prior-ts>, label: "corrected-by-retry",
result: <new outcome>}` — joins the failed turn to its fix.
`wispd fails` lists the last N incorrect/aborted turns with their
retry outcome: `fixed` / `unfixed` / `no retry`. Extends `soak_stats`
with a correction-convergence line.

**Test scenarios:**
- fail → corrected retry → `fails` reports `fixed`
- fail with no retry → `unfixed`
- soak report includes the convergence count

**Verification:** label a real run bad, correct it, `wispd fails`
shows the pair.

### U3. DESIGN.md + theme token plumbing

**Goal:** one authored spec drives all surfaces, light + dark.

**Requirements:** R5, R6, R7

**Dependencies:** none (parallel with U1/U2).

**Files:**
- `DESIGN.md` — new, awesome-design-md format
- `wisp/theme.py` — token model + `theme.json` writer
- `wisp/config.py` — `[ui] theme = "dark"`
- `wispd` — `wispd theme [dark|light]` (writes theme.json, live-swap)
- `tests/test_theme.py`

**Approach:** author DESIGN.md with Wisp's voice (quiet instrument,
not a mascot) — ink/canvas/surface/accent/warn tokens for both themes,
typography ramp matching the existing pixel sizes, motion notes
(ring pulse, ghost peel duration). `theme.py` holds the same tokens as
data (single source in Python; DESIGN.md is the doc), writes
`~/.local/share/wisp/theme.json`. This keeps QML dependency-free —
no YAML parse.

**Test scenarios:**
- theme.json emits all required token keys for both themes
- `[ui] theme=light` selects the light palette
- unknown theme name falls back to dark

**Verification:** `wispd theme light` rewrites theme.json; orb/bar
pick it up on the next state poll.

### U4. QML token binding

**Goal:** the surfaces actually read the theme.

**Requirements:** R6, R7

**Dependencies:** U3.

**Files:**
- `shell-plugin/Companion.qml`
- `shell-plugin/BarWidget.qml`
- `shell-plugin/Panel.qml`
- `shells/debug/shell.qml` (minimal — token palette at top only)

**Approach:** a `FileView` on `theme.json` (same watch pattern as
state.json) exposing a `theme` property object; every hardcoded hex
literal binds to `theme.x`. Ghost cursor, ring, and point-marker
colors come from `accent`/`accentAlt` tokens so they're part of the
theme, not bolted on.

**Test scenarios:**
- QML loads clean after the swap (quickshell journal has no errors)
- flipping theme.json repaints the orb color without a shell restart

**Verification:** `wispd theme light` → orb + card visibly restyle.

### U5. design-md reference skill

**Goal:** the fork's catalog is queryable from the act loop.

**Requirements:** (supports KTD5 — cheap, optional)

**Dependencies:** none.

**Files:**
- `wisp/skills_seed/design-md/SKILL.md` — read-only skill pointing at
  the local clone's catalog conventions
- `wisp/skills_seed/` registration (bundled seed list)

**Approach:** a documentation skill teaching the model the repo path +
token vocabulary — *"when theming, read
~/Documents/github/personal/awesome-design-md/design-md/<brand>/DESIGN.md
for reference conventions."* No code; it rides the existing seed
mechanism.

**Test scenarios:**
- seed installs `design-md` on `wispd install`/`doctor`
- `wispd skills` lists it

**Verification:** `wispd skills` shows design-md after a fresh seed.

## Risks and Dependencies

- **Correction cues can false-positive** ("no" as a literal answer).
  Mitigation: cue channel only fires when a *plausible* prior turn
  exists (recent, has an outcome) and the transcript continues past
  the cue word. Logged either way, so false positives are visible.
- **Theme plumbing across 4 QML files** is mechanical but tedious —
  risk is an overlooked hardcoded color, not architecture.
- **Light theme contrast on overlays** (translucent panels over bright
  wallpapers) needs real tokens — it's why the theme is authored, not
  inverted.

## Deferred to Follow-Up Work

- `voltagent` upstream agent-framework repo is *not* forked — defer
  any fork/integration decision; awesome-design-md already covers the
  design half of the ask.
- Applying the token model to the Rust surfaces.
- Auto-theme from Omarchy system preference (no reliable signal on
  Hyprland today).
- Wiring correction convergence into `ce-optimize`-style loop metrics.
