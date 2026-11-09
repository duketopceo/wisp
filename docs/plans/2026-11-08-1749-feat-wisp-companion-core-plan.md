---
title: Wisp companion core - see the window, answer, point and teach - Plan
type: feat
date: 2026-11-08
status: active (draft PR #349 open)
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
execution: code
---

# Wisp companion core - see the window, answer, point and teach - Plan

## Goal Capsule

- **Objective:** Someone using Wisp on Linux can hold a key or double-tap Control, ask about whatever window they are in, and get a spoken answer from a small, quiet companion that reads the window's text, points and draws by hand on the right monitor, and teaches multi-step tasks in the apps people actually use. This plan covers the companion core only; dictation, voice, agents, connectors, memory, home screen, engine, hygiene and the paid bundle are separate areas (see How This Work Fits Together).
- **Product authority:** this Product Contract, then `ROADMAP.md`. The window-text work in `docs/plans/2026-11-08-1607-feat-wisp-linux-companion-rescope-plan.md` (U5, U6) is absorbed here; its other units belong to other areas.
- **Open blockers:** none.

## Product Contract

### Summary

Bring Wisp's companion up to and past HeyClicky on Linux: a double-Control typed composer, a leaner cursor buddy, hand-drawn pointing and ink, answers grounded in the focused window's text on every monitor, a tested circle-to-ask, walkthroughs that combine HeyClicky's step tracking with Wisp's, and app skills grown from 17 to about 89.

### Problem Frame

Wisp already ships the companion's parts: push-to-talk with spoken answers, a cursor buddy with state words, rings, arrows, highlights and scribbles, circle-to-ask, a 15-step walkthrough tutor, and 17 app skills. Against HeyClicky it falls short in four places a user notices: answers ignore the window's own text, everything assumes one monitor, the buddy and ink look busier than HeyClicky's lean companion, and walkthroughs only cover 17 apps. Circle-to-ask has no end-to-end test, so it can break unnoticed.

### Requirements

**Asking**

- R1. Double-tapping Control opens a typed composer next to the companion; a typed question is answered the same way as a spoken one.
- R2. Holding the talk key still asks by voice; both entry points share one conversation.

**Seeing the window**

- R3. Answers use the focused window's own text when the app exposes it, then OCR of that window, then its screenshot.
- R4. On setups with several monitors, the companion, its answers and its pointing follow the monitor holding the focused window.
- R5. Circling something on screen and asking about it answers about the circled region, verified by an end-to-end test.

**Companion and ink**

- R6. The cursor buddy is a small, lean companion in HeyClicky's spirit with Wisp's own look: fewer elements, calm motion, short state labels.
- R7. Pointing and drawing (rings, arrows, highlights, callouts) look hand-drawn, appear while the answer is spoken, and clear when it ends.

**Teaching**

- R8. Walkthroughs track up to 15 steps, notice when the user did the step (click or visible change), never repeat a finished step, and wait for slow pages, combining HeyClicky's tracking with Wisp's label-first snapping and lessons.
- R9. App skills grow from 17 to about 89: popular Linux desktop apps and top web apps first, then apps from HeyClicky's list where they fit Linux or are easy to add.

### Key Decisions

- **Lean toward HeyClicky's interaction, keep Wisp's look.** Placement and behavior follow HeyClicky; visual style stays Wisp's own. Governs R1, R6, R7. (session-settled: user-directed — chosen over copying HeyClicky's look or keeping Wisp's current busier buddy: "where, not how it looks")
- **Double-Control for typing.** Governs R1. (session-settled: user-directed — chosen over a menu or a separate hotkey: matches HeyClicky's typed composer)
- **Combine walkthroughs.** Governs R8. (session-settled: user-directed — chosen over replacing Wisp's walkthroughs with HeyClicky's or keeping only Wisp's)
- **App skills reach about 89, Linux and web first.** Governs R9. (session-settled: user-directed — chosen over mirroring HeyClicky's macOS list or starting with creative tools: Linux top apps and web apps, then HeyClicky's list where it fits or is easy)
- **Live diagrams stay a stretch goal.** (session-settled: user-directed — chosen over building them in this area)

### Key Flows

- F1. **Ask about a page.** The user looks at a long web article, double-taps Control, types "what's the main argument here?", and hears a two-sentence answer while a hand-drawn underline marks the key paragraph.
- F2. **Teach me.** In a photo editor the user asks "how do I remove the background?"; Wisp points at each control in turn, notices each click, skips steps already done, and finishes with a short summary.
- F3. **Circle and ask.** The user circles a chart on their second monitor and asks "what does this spike mean?"; the answer is about that chart, and the ring appears on that monitor.

### Acceptance Examples

- AE1. A web page whose body text is exposed is answered from its text; with that text hidden, the same question is answered from OCR or the screenshot.
- AE2. With two monitors and the focused window on the second, the buddy and all ink appear on the second monitor.
- AE3. A walkthrough that the user starts halfway through does not ask them to redo finished steps.
- AE4. The circle-to-ask test fails if the answer ignores the circled region.

### Success Criteria

- Generic answer-and-point gauntlet cases (web page, PDF, terminal, two-monitor) pass at a rate the plan sets as its gate.
- About 89 app skills ship, each with at least one recorded walkthrough test.
- The circle-to-ask end-to-end test runs in CI.

### Scope Boundaries

- Not in this area: dictation, the talk-back voice, agents, connectors, memory, the home screen, the engine and SDK work, the personal-info scrub, the paid bundle.
- Not in this plan: live diagrams (stretch), other Linux desktops beyond Hyprland, macOS.

### Outstanding Questions

- Q1 (Deferred to Planning): the exact pass-rate gate for the generic gauntlet cases.
- Q2 (Deferred to Planning): how walkthroughs detect "the user did the step" when no click is observable (focus change, visible text change).

<!-- ce-section: work-relationships -->
### How This Work Fits Together

This plan covers the companion core. The broader breakdown below is the current understanding, not a committed roadmap.

- Dictation (screen-aware compose, fully HeyClicky-like) — Shares the window-text reader from R3; can proceed after it.
- Voice (new talk-back voice) — Can proceed independently of this plan; every spoken answer here benefits.
- Agents (named literary agents with faces, cards with files and Retry, routines and the suggested feed, fail-closed permissions) — Depends on the window-text reader for handoff; still to decide: event model details.
- Connectors (built-in catalog plus custom MCP) — Enables agents; still to decide: the connector provider.
- Memory (full memory system) — Can proceed independently; still to decide: the backend.
- Home screen (notch placement, Omarchy plugin, full notch integration for the maintainer's setup) — Shares the companion's look from R6.
- Engine (first-party OpenRouter SDK, optional Ollama, coding runtimes on top, macOS next) — Can proceed independently.
- Hygiene (personal-info scrub, generic defaults) — Planned in `docs/plans/2026-11-08-1607-feat-wisp-linux-companion-rescope-plan.md` (U2-U4); blocks public releases.
- Paid bundle (optional Wisp proxy key) — Still to decide: design and timing.

### Sources

- `docs/research/heyclicky-features.md`; HeyClicky official videos reviewed 2026-11-08.
- `wisp/walkthrough.py` (15-step tutor), `wisp/skills_seed/apps/` (17 app skills), `ROADMAP.md`.

Product Contract preservation: Product Contract unchanged; Q2 is resolved by KTD6.

## Planning Contract

### Key Technical Decisions

- KTD1. **Double-Control from a press/release pair of non-consuming binds.** `wisp/hypr.py` gains support for a lone-modifier bind with Hyprland's release and non-consuming flags, so Control keeps working everywhere. A press bind and a release bind on Control send `tap-down` and `tap-up` through a new light `tap` command in `wisp/fastkey.py` (no heavy client start). A tap is a press held under 250 ms; two taps within 350 ms open the composer. Because a Control chord such as Control+C is not observable from binds, the hold limit is the chord filter. Timing reuses `wisp/handsfree.py`'s pure `Tracker`, and the detector ignores taps while the talk key is held. If the binds cannot be installed, a configurable chord opens the composer instead. Implements R1.
- KTD2. **One window-text collector, prefetched and untrusted.** New `wisp/window_text.py` extends the AT-SPI reader in `wisp/elementtree.py` (`AtspiTree`, which today collects labels only) with Text-interface reads for text-bearing roles within node and time caps; its `UNAVAILABLE` and `UNBOUND` states map to source `none`. The cua driver's tree (`wisp/blank.py` `window_text`) is a second text source when that driver is installed. Then OCR of the focused-window crop when `tesseract` is installed, then the screenshot. Browsers expose page text only when their accessibility support is on, so web pages often take the OCR or screenshot path. It is prefetched in `context.Speculative` at key press (text 300 ms, OCR 700 ms; a late result is `none`), passed to prompts as quoted reference data, and never logged to stderr. Implements R3. (From the rescope plan's KTD1 and KTD2.)
- KTD3. **The focused window picks the monitor; capture stays whole-canvas.** `wisp/platform.py` `active_window()` and `active_geometry()` also return the focused window's monitor. The screenshot stays one canvas across all monitors; the focused monitor becomes the default target when the model omits a `:screenN` label, and the per-screen overlays in `shell-plugin/Companion.qml` show the buddy and ink there. Implements R4.
- KTD4. **Lean buddy by subtraction.** Keep `Buddy.qml` and the state machine; remove decoration and cap motion; state labels come from `shell-plugin/lib/copy.js`. Implements R6.
- KTD5. **Hand-drawn ink is drawn in the shell, seeded by the daemon.** Stroke jitter lives in `shell-plugin/components/DrawLayer.qml` and the shared `shell-plugin/lib/ink.js`, seeded per stroke by a value the daemon sends, so tests and replays render identically. `wisp/ink.py` keeps its contrast job and its parity test with `ink.js`. Strokes appear when the sentence that names them starts playing (the existing point-timing hook in `wisp/stage_speak.py`) and clear when speech ends. Implements R7.
- KTD6. **Walkthroughs add two completion signals to what exists.** `wisp/walkthrough.py` already has the 15-step cap, the done log with `refused_already_done`, load waits and step advancement on window-state changes; `wisp/click_watch.py` already watches clicks. The delta: feed `observe()` a click inside the target rectangle (from `click_watch`) and a window-text change near the target (from the U2 collector), and route a halfway start through the existing already-started question in `wisp/walkthrough_run.py`. This resolves Q2. Implements R8.
- KTD7. **App skills keep the existing format, with web hosts.** New skills follow `wisp/skills_seed/apps/<app>/SKILL.md`: desktop apps match by `app_classes`, web apps by `url_hosts` (supported by `skills.match_app_skill`). Each skill ships one teach case in `tests/fixtures/teach/` (a capture, a planner reply and the expected region), scored by the existing teach-case scorer in `wisp/gauntlet.py`. Cases are recorded with the existing teach capture flow. Implements R9.

### Assumptions

- Hyprland can bind a release action on Control alone without stealing Control from other shortcuts; if not, the composer falls back to a configurable chord.
- The QML overlay can be placed per monitor through the existing shell plugin.

### Sequencing

U1 (composer) and U2 (collector) start in parallel. U3 needs U2. U4 (multi-monitor) and U5 (circle-to-ask test) can start any time; U5 should land early so later ink and monitor work cannot break it. U6 and U7 (buddy and ink) follow U4. U8 (walkthroughs) follows U2. U9 (app skills) runs in batches alongside, gated by U8's fixtures. U10 (gauntlet cases) last.

## Implementation Units

### Unit Index

| U-ID | Title | Files touched | Depends on |
|---|---|---|---|
| U1 | Double-Control typed composer | `wisp/composer.py`, `wisp/hypr.py`, `wisp/fastkey.py`, `wispd`, `shell-plugin/components/Composer.qml`, `tests/test_composer.py`, `tests/test_hypr.py` | none |
| U2 | Window-text collector | `wisp/window_text.py`, `wisp/context.py`, `tests/test_window_text.py` | none |
| U3 | Answers from window text | `wisp/stage_capture.py`, `wisp/context.py`, `tests/test_window_answer.py` | U2 |
| U4 | Follow the focused monitor | `wisp/platform.py`, `wisp/points.py`, `shell-plugin/Companion.qml`, `tests/test_monitor_follow.py` | none |
| U5 | Circle-to-ask end-to-end test | `tests/test_scribble_e2e.py`, `tests/fixtures/scribble/` | none |
| U6 | Lean cursor buddy | `shell-plugin/components/Buddy.qml`, `shell-plugin/lib/buddy.js`, `shell-plugin/lib/copy.js`, `tests/test_buddy.py` | U4 |
| U7 | Hand-drawn ink | `shell-plugin/components/DrawLayer.qml`, `shell-plugin/lib/ink.js`, `wisp/stage_speak.py`, `tests/test_ink.py` | U4 |
| U8 | Walkthroughs complete on evidence | `wisp/walkthrough.py`, `wisp/walkthrough_run.py`, `wisp/click_watch.py`, `tests/test_walkthrough_run.py` | U2 |
| U9 | App skills to about 89 | `wisp/skills_seed/apps/`, `docs/research/app-skill-targets.md`, `tests/test_teaching_guides.py`, `tests/test_skill_provenance.py`, `tests/fixtures/teach/` | U8 |
| U10 | Companion gauntlet cases | `docs/dev-tasks/gauntlet.jsonl`, `wisp/gauntlet.py`, `tests/test_gauntlet_mode.py` | U3, U4 |

### U1. Double-Control typed composer

- **Goal:** double-tapping Control opens a typed composer beside the companion.
- **Requirements:** R1, R2; KTD1.
- **Files:** `wisp/composer.py` (tap detector on `handsfree.Tracker` timing), `wisp/hypr.py` (lone-modifier, release and non-consuming binds), `wisp/fastkey.py` (`tap` command), `wispd` (IPC handler), `shell-plugin/components/Composer.qml`, `tests/test_composer.py`, `tests/test_hypr.py`.
- **Approach:** as KTD1; submitting runs the same path as `wispd ask` and joins the current conversation.
- **Test scenarios:**
  - Two taps (each held 80 ms) 200 ms apart open the composer.
  - Two taps 500 ms apart do not.
  - A Control press held 400 ms (as in a chord) does not count as a tap.
  - Taps while the talk key is held are ignored.
  - `hypr` emits a release, non-consuming bind for a lone Control and still rejects a malformed chord.
  - `fastkey` builds a `tap` command; an unknown command still errors.
  - When the binds cannot be installed, the configured fallback chord opens the composer.
  - A typed question reaches the same answer path and conversation as a spoken one.
- **Verification:** unit tests; QML job for the composer's open and submit states.

### U2. Window-text collector

- **Goal:** one time-boxed reader of the focused window's text.
- **Requirements:** R3; KTD2.
- **Files:** `wisp/window_text.py`, `wisp/context.py`, `tests/test_window_text.py`.
- **Approach:** as KTD2; returns text, source (`atspi`, `ocr`, `none`) and elapsed time.
- **Execution note:** test-first on fixture trees and images.
- **Test scenarios:**
  - A fixture tree with a document role yields capped, de-duplicated text, source `atspi`.
  - A tree with only buttons yields no AT-SPI text.
  - `UNAVAILABLE` (no accessibility bindings) and `UNBOUND` (no single active frame) yield `none`.
  - With the cua tree present and AT-SPI empty, the cua text is used.
  - An empty tree plus a fixture image and a fake OCR yields source `ocr`.
  - A sensitive window yields `none`.
  - A missing OCR binary yields `none` without error.
  - A read past its time budget yields `none`.
  - The prefetched result is reused within its TTL.
- **Verification:** unit tests, hermetic.

### U3. Answers from window text

- **Goal:** answer turns use the window's text.
- **Requirements:** R3; KTD2.
- **Files:** `wisp/stage_capture.py` (`context_stage`), `wisp/context.py` (`snapshot`), `tests/test_window_answer.py`.
- **Approach:** add the prefetched text as a bounded quoted block after the focused-window and document blocks; keep the screenshot for vision models.
- **Test scenarios:**
  - A turn with window text includes the quoted block in the model request (AE1).
  - Source `none` omits the block and still sends the screenshot (AE1).
  - The block truncates at its cap.
  - Window text containing instructions stays inside the quoted block.
  - `tests/test_log_hygiene.py` passes with sentinel words in the window text.
- **Verification:** unit and replay fixtures.

### U4. Follow the focused monitor

- **Goal:** the companion, answers and ink appear on the monitor holding the focused window.
- **Requirements:** R4; KTD3.
- **Files:** `wisp/platform.py`, `wisp/points.py`, `shell-plugin/Companion.qml`, `tests/test_monitor_follow.py`.
- **Approach:** a delta over the existing `:screenN` labels and per-screen overlays: `active_window()` and `active_geometry()` return the monitor; a point with no `:screenN` label targets the focused monitor; the buddy shows on that monitor's overlay.
- **Test scenarios:**
  - With two fake monitors and the focused window on the second, an unlabelled point lands on the second monitor (AE2).
  - An explicit `:screen1` label still wins over the focused monitor.
  - A window spanning both monitors uses the one holding its center.
  - A single monitor behaves exactly as today.
  - Scaled monitors convert coordinates correctly on the shared canvas.
- **Verification:** unit tests; QML job for overlay placement.

### U5. Circle-to-ask end-to-end test

- **Goal:** circling something and asking is covered end to end.
- **Requirements:** R5.
- **Files:** `tests/test_scribble_e2e.py`, `tests/fixtures/scribble/`.
- **Approach:** drive a synthetic stroke through the existing path (`wisp/scribble.py` draws strokes into the full screenshot in pink and adds a text hint with the strokes' bounding box) with a fixture screenshot and a fake brain, in the style of `tests/test_scribble.py`.
- **Test scenarios:**
  - The image sent with the question has pink stroke pixels inside the stroke's bounding box (AE4).
  - The text hint's bounding box matches the stroke (AE4).
  - The stroke is consumed once; the next question carries no stroke.
  - A stale stroke document is ignored.
  - The answer's point resolves inside the circled bounding box.
  - The test fails if the stroke or hint is dropped from the request (AE4).
- **Verification:** runs in the unit job.

### U6. Lean cursor buddy

- **Goal:** a smaller, calmer companion with short state labels.
- **Requirements:** R6; KTD4.
- **Files:** `shell-plugin/components/Buddy.qml`, `shell-plugin/lib/buddy.js`, `shell-plugin/lib/copy.js`, `tests/test_buddy.py` (QML-backed).
- **Approach:** remove decoration, cap motion, keep the state machine and labels.
- **Test scenarios:**
  - Every daemon state maps to one short label.
  - Reduced-motion mode disables movement animation.
  - The buddy never takes keyboard focus.
- **Verification:** QML job; owner visual check on the desktop.

### U7. Hand-drawn ink

- **Goal:** pointing and drawing look hand-drawn and follow the speech.
- **Requirements:** R7; KTD5.
- **Files:** `shell-plugin/components/DrawLayer.qml`, `shell-plugin/lib/ink.js`, `wisp/stage_speak.py` (seed and timing), `tests/test_ink.py`, QML lib tests.
- **Approach:** as KTD5.
- **Test scenarios:**
  - The same seed renders the same stroke path in `ink.js`.
  - A stroke appears when its sentence starts playing.
  - All strokes clear when the answer ends or is interrupted.
  - Contrast rules in `wisp/ink.py` still hold on dark and light backgrounds.
- **Verification:** unit and QML jobs.

### U8. Walkthroughs complete on evidence

- **Goal:** walkthroughs notice what the user did and never repeat finished steps.
- **Requirements:** R8; KTD6.
- **Files:** `wisp/walkthrough.py` (`observe`), `wisp/walkthrough_run.py`, `wisp/click_watch.py`, `tests/test_walkthrough_run.py`.
- **Approach:** as KTD6; existing contracts in `tests/test_walkthrough_run.py` stay green.
- **Test scenarios:**
  - A click inside the target rectangle marks the step done.
  - A click outside it does not.
  - A window-text change near the target with no click marks it done.
  - A user who starts halfway is asked the already-started question and not asked to redo finished steps (AE3).
  - Existing load-wait, done-log and 15-step-cap tests still pass.
- **Verification:** unit tests.

### U9. App skills to about 89

- **Goal:** about 89 app skills, Linux top apps and web apps first.
- **Requirements:** R9; KTD7.
- **Files:** `wisp/skills_seed/apps/` (new skill folders), `docs/research/app-skill-targets.md` (ranked target list: Linux desktop apps, top web apps, then HeyClicky's list where it fits Linux or is easy), `tests/test_teaching_guides.py`, `tests/test_skill_provenance.py`, `tests/fixtures/teach/`.
- **Approach:** as KTD7; land skills in batches of about ten, each with frontmatter, teaching notes within the existing character cap, and one teach case.
- **Test scenarios:**
  - Every skill parses with only the allowed frontmatter keys and has `asks` and `provenance`.
  - Desktop skills have `app_classes`; web skills have `url_hosts`.
  - No two skills claim the same app class or the same host.
  - Every skill has a teach case that the teach-case scorer marks correct with its recorded planner reply.
  - The skill count reaches the target in `docs/research/app-skill-targets.md`.
- **Verification:** unit tests per batch.

### U10. Companion gauntlet cases

- **Goal:** the companion is measured on generic tasks.
- **Requirements:** Success Criteria.
- **Files:** `docs/dev-tasks/gauntlet.jsonl`, `wisp/gauntlet.py`, `tests/test_gauntlet_mode.py`.
- **Approach:** the gauntlet scores teach cases today, so answer-and-point cases are a new scoring path: answer-contains and point-in-region checks for a public web page, a PDF, a terminal and a two-monitor layout. Set the pass-rate gate (Q1) from a first owner-run baseline.
- **Test scenarios:**
  - The new case kinds parse and score from recorded replies.
  - A two-monitor case fails if the point lands on the wrong monitor.
- **Verification:** hermetic suite; the live run is owner-run and capped.

## Verification Contract

| Gate | Command or evidence | Applies to |
|---|---|---|
| Compile | `python -m py_compile wispd wisp/*.py wisp/tools/*.py tests/*.py` | all |
| Unit | `python -m unittest discover -s tests -v` | all |
| QML | the CI `qml` job | U1, U4, U6, U7 |
| Docs lint | `tests/test_docs_lint.py` | U9 |
| Live checks | owner on a real desktop: composer, buddy, ink, two monitors | U1, U4, U6, U7 |
| Live gauntlet | owner-run, capped, isolated session | U10 |

## Definition of Done

- Every unit's test scenarios exist as tests and pass; no live desktop, network or audio in the suite.
- The circle-to-ask end-to-end test runs in CI.
- About 89 app skills ship, each with a passing walkthrough fixture.
- The owner's live checks pass for the composer, buddy, ink and two monitors.
- Abandoned experiments and dead code are removed from each unit's diff.
