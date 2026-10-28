---
title: "feat: Beat every competitor — wisp competitive teardown and unit plan"
date: 2026-10-27
type: feat
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
origin: docs/plans/2026-10-26-0031-feat-wisp-v1-roadmap-plan.md
---

# feat: Beat every competitor — wisp competitive teardown and unit plan

## Goal Capsule

- **Objective:** Make wisp, the push-to-talk voice companion for Hyprland/Omarchy
  (hosted models only), clearly better than HeyClicky (public and commercial),
  Clacky, and the Windows and Linux Clicky-family apps, on the things a user
  feels: how fast it answers, how well it points and draws, whether it teaches
  step by step, and whether its background agents can be trusted.
- **Means:** One evidence-backed feature matrix, a short list of gaps that the
  existing parity plans do not already cover, and prioritized units (`B1`–`B14`)
  that each name files, acceptance criteria and a proof.
- **Authority:** This plan adds to, and never replaces, the four parity plans
  (see *What the older plans already cover*). Where it overlaps the v1 roadmap
  (`2026-10-26-0031`), the roadmap's order wins: v1 gate first, then these units.
- **Stop conditions:** Stop a unit if it needs a vendor runtime, a local model
  server, a wisp-held credential inside a spawned agent, or copying competitor
  prompt text or source that is not MIT-licensed (see *Provenance and limits*).
- **Who finishes:** Implementation runs under `ce-work`, one PR per unit. The
  owner merges. Nothing here edits `ROADMAP.md` or Phase 7–9 code; units that
  touch those areas say so and wait for them.

---

## Product Contract

### Summary

Wisp already matches HeyClicky's core loop on Linux: hold a key, speak, get a
spoken answer with a cursor buddy that flies to the target, rings, arrows and
highlights timed to the sentence, a paper `note.md`, honest background agents,
routines and a spend-capped hosted-only stack. What it lacks is mostly
*surface and proof*: the hand-drawn, speech-paced drawing and 2D/3D cards that
HeyClicky 1.1.1 shipped on 2026-10-23, a walkthrough that actually runs, a
watchable agent lane in the user's own browser, and the measured accuracy the
v1 gate asks for (32% right first time today, 60% required).

The plan's thesis: **do not out-feature a funded team on cards and 3D. Be the
companion that is faster to answer, shows its work, never lies about what it
did, costs only the model bill, and is yours to read and change.**

### Competitor roster (who is who)

| Short name | What it is | Source of facts |
|---|---|---|
| **HeyClicky public (OSS)** | `farzaa/clicky`, MIT, macOS Swift app plus a Cloudflare worker key proxy. The predecessor the commercial app grew from. | Source read (prior plans, 2026-10-16 REA ledger) |
| **HeyClicky commercial ("private/pro")** | Closed-source macOS and Windows app by Humansongs (Free, Pro $20, Max $100). v1.1.1 (2026-10-23) added drawing in 2D/3D, "HeyClicky drive", Chrome extension, notch Home, routines by voice, Windows. | Changelog, trust page, reviews, and a static look at the installed 1.1.1 bundle (see Provenance) |
| **Clacky** | `Raynan00/clacky` v0.2.0, MIT, Windows PyQt6 companion on Claude Computer Use, vendored from clicky-windows | Source read (`docs/research/2026-10-25-clacky-teardown.md`) plus Luke's port notes |
| **The Windows equivalent** | Three answers. (1) **HeyClicky for Windows** 1.1.1–1.1.3 (official, 2026-10-23/24, signed self-updating installer). (2) **Clacky**, the open-source Windows companion. (3) **clicky-windows** (`Bitshank-2338`, MIT, Python/PyQt6, 1.6 preview of 2026-10-26 adds "Sketch" and "Drive"). The most direct commercial rival to wisp on Windows is (1); the code a competitor could be cloned from is (2) and (3). | Changelog, source read of clicky-windows at `6c6216b` |
| **Linux rivals** | **Peeky** (`danielbusnz/Peeky`, Rust/Tauri, Hyprland first, MIT), **clicky-desktop** (`tornikegomareli`, Rust/Raylib, Hyprland window rules), **ClickyX** (`unn-Known1`, Tauri, Linux .deb/AppImage/Flatpak), **Flicky** (Electron), **clawbar** (Hyprland + waybar voice agent in Docker). Wisp is not alone on Hyprland any more. | Source read of Peeky and ClickyX; READMEs for the rest |

### Provenance and limits (reverse-engineering method)

Method follows the REA skill's discipline: every claim carries an evidence class
and the plan separates **observed**, **inferred** and **unknown**.

- `source` — open-source code read in this run: clicky-windows `6c6216b`,
  Peeky `5950340`, ClickyX `988568a`, Clacky 0.2.0 (earlier teardown).
- `doc` — vendor changelog (`heyclicky.com/changelog` through v1.1.3), trust
  page, reviews dated 2026-10-24/25.
- `bundle-static` — the shipped HeyClicky 1.1.1 macOS bundle, inspected
  read-only on the owner's machine: `Info.plist`, bundled resource files
  (skills, draw engine JS, browser-extension manifest and skill, the background
  worker instruction file), helper names, linked frameworks, endpoint names.
  Nothing was run, nothing decompiled, no function-level disassembly done.
- **Observed vs inferred.** What a resource file *says* is observed. What the
  closed binary *does* with it is inferred and marked so. Runtime behaviour of
  the commercial app (latency, model routing, grounding accuracy) is **unknown**
  and not planned against.
- **Not copied.** This plan describes mechanics in our own words. It does not
  reproduce HeyClicky prompts, code or assets. Embedded analytics, auth and
  crash-report credentials found in the bundle were not recorded anywhere.
- **REA tooling.** The REA MCP server was not connected in this run, so no
  Evidence IDs exist for the bundle findings. If an REA ledger entry is wanted,
  re-run the bundle through `analyze-javascript-application` on the draw-engine
  JS and `open_binary` on the helper, then attach the IDs to rows tagged
  `bundle-static` below.

### Requirements

- **R1.** A single matrix states, for each competitor, which wisp capabilities
  are *have*, *missing*, *partial* or *better*, with evidence class per row.
- **R2.** Every unit below is new work, or a precisely scoped change to
  existing work. Nothing re-plans a unit that an older plan owns.
- **R3.** The top gaps are ranked by user-felt impact on the v1 promise
  (speak, see, point, teach, delegate), not by competitor headline count.
- **R4.** Each unit has acceptance criteria a reviewer can run, and says what
  it must not touch.
- **R5.** The plan states plainly what makes wisp better, and which of those
  claims a unit must keep true.

### What the older plans already cover (do not re-plan)

| Older plan | Owns |
|---|---|
| `2026-10-25-0151` heyclicky-gap-closure | Paper `::` markup (U1–U3, partly landed as `wisp/note.py`), pixel-settle, walkthrough advance on visual change, warm STT socket, dead-mic failover, dictation correction detector, suggestion etiquette numbers, fullscreen carve-out. Windows units are obsolete after Linux-only. |
| `2026-10-25-0215` clicky-clacky-delta | IPC authz (landed #141), honest task outcomes (landed), routines (landed), voice-taught routines, `organize` with undo (dropped from v1), element-snap pointing, tour mode, per-app memory, needs-connect handshake, skills export, streaming STT, safe sentence split. |
| `2026-10-26-2149` clacky-cursor-buddy | The buddy cursor (landed #148/#149). |
| `2026-10-25-1625` heyclicky-linux-roadmap | Phases 1–9; superseded for unshipped phases by the v1 roadmap. |
| `2026-10-26-0031` v1 roadmap | Redeploy, hosted install (landed #146), act quality, Phase 7 surfaces (points timed to speech #150 and draw rings #152 landed; walkthrough, per-app history, sensitive-window skip, streaming STT, barge-in in flight), Phase 5 router fast path, Phase 8 env scrub. |

Everything in the *New findings* section is absent from those plans.

---

## Feature matrix

Legend: **have** = on `master` and reachable from a turn; **partial** = code or
a thin version exists; **missing** = nothing; **better** = wisp is ahead and the
row says why. Evidence class in brackets. Wisp state is `master` at `066481c`
(2026-10-27) read directly.

### Voice and conversation

| Capability | HeyClicky commercial | Clacky | clicky-windows 1.6 | Peeky / Linux rivals | Wisp today | Verdict |
|---|---|---|---|---|---|---|
| Hold-to-talk, screenshot at press | yes [doc] | yes [source] | yes [source] | yes [source] | have (Super+D via Hyprland submap, press-time speculative capture) | have |
| Answer start latency after release | "a couple of seconds" claimed [doc]; realtime voice model names in the main binary [bundle-static strings] | streaming STT (Deepgram) + gapless sentence TTS [source] | optional Deepgram streaming partials [source] | Peeky ~1.2 s release-to-action with own keys, on-device intent router [source README] | batch Groq STT, sentence TTS; 32% first-time-correct, no measured latency gate in CI | **missing** (B1, B2) |
| Streaming STT while key held | main binary names Deepgram and Apple speech APIs [bundle-static strings]; which one serves a turn is inferred | yes [source] | Deepgram only [source] | Peeky streams [source] | no (roadmap R8, in flight) | missing, owned by Phase 7 |
| Barge-in (talk over it) | yes [doc] | yes (50 ms kill) [source] | Esc only [source] | Peeky has `barge_in.rs` [source] | TTS barge-in exists (`speech.py`) | have |
| Per-app conversation memory | 40 messages, plus "remembers the page you just left" [doc] | 20 per app [source] | 20 per app [source] | Peeky SQLite FTS5 log [source] | partial (`app_key` in act/control only) | missing, Phase 7 |
| Captions while speaking | setting [doc] | no | sentence-timed captions [source] | no | answer bubble beside cursor | partial (B8) |
| Voice speed 0.5–1.5x | yes [doc] | no | yes [source] | some | not exposed | missing (B8) |
| Mic failover, Bluetooth pre-roll, muted speaker keeps answer on clipboard | yes [doc, changelog 1.0.49] | sleep/wake watchdog [source] | native-rate fallback [source] | no | planned (gap-closure U6/U7), not landed | missing, reconfirm (B8) |
| Dictation with screen-aware compose, terminal newline guard, learn corrections in ~20 s | yes [doc] | no | basic dictation [source] | no | have: `dictate.py`, vocab learning, terminal newline guard | have |
| Whole-document reading (PDF/file, not just visible) | yes [doc 1.0.47, plist folder prompts] | doc drag-drop [source] | PDF/DOCX/XLSX/OCR [source] | no | missing | missing (B9) |

### Pointing, drawing, teaching

| Capability | HeyClicky commercial | Clacky | clicky-windows 1.6 | Linux rivals | Wisp today | Verdict |
|---|---|---|---|---|---|---|
| Cursor buddy that flies in an arc and labels the target | yes [doc] | yes (source of wisp's buddy) | yes | clicky-desktop, Flicky | have (#148) | have |
| Points timed to the sentence | yes (inferred) | single-stream tour [source] | no | no | have (#150) | have |
| Snap to real UI element, not model pixels | grounding internals unknown | UIA first, model fallback [source] | UIA, OCR, 2-stage grid [source] | ClickyX reads windows through xdotool and xprop [source] | have chain `control, a11y, uitars, jev`; accuracy unproven | partial (B3) |
| Draw rings, arrows, highlights, cleared when speech ends | yes, hand-drawn look [doc 1.0.40] | whiteboard tags [source] | arrow/circle/underline/label [source] | ClickyX rectangles/scribbles [source] | have (#152) plain shapes | have, look **missing** (B4) |
| Hand-drawn pen, pen-reveal paced to speech, pills, numbered badges, dashed regions, auto light/dark ink | yes: draw engine 1.6, "pieces" for graph/timeline/sticky/receipt/clipping/photo/spotlight/target/hover, live part editing, worker sandbox with time limit [bundle-static] | no | "Sketch" JSON scene: chart, graph, cube, sphere, buttons, save/replay, PNG export [source] | no | missing | **missing** (B4) |
| Explanation cards with real photos | yes [doc 1.1.1, bundle-static photo helper] | no | no | no | `note.md` text tiles, no images | missing (B5) |
| 3D model you can drag and click a part to ask about it | yes (three.js bundled) [bundle-static, doc] | no | wireframe cube/sphere [source] | ClickyX Tripo3D + GLB viewer [source] | missing | missing, deliberately last (B13) |
| Guided walkthrough: speak step, point, detect the click, advance, 15-step cap, done-log | yes [doc] | tour, no click detect [source] | "say next" [source] | Peeky idea doc only [source] | module exists, **not wired** | **missing** (B6; Phase 7 owns wiring) |
| App skills so guidance is right in each app | 89 apps in 1.0.28, then "Skills paused" in 1.0.49 [doc]; bundled integration skill files remain [bundle-static] | SKILL.md + progressive disclosure [source] | per-app knowledge base [source] | ClickyX 64 skills | 15 seeds, matcher exists in `wisp/skills.py`, call sites unconfirmed | partial (B6) |
| Scribble or circle on screen to ask about it | yes (1.0.25, 1.0.33) [doc] | no | no | no | missing | **missing** (B7) |
| Saved lessons, replay with narration, spaced review | "Lessons" named in draw engine [bundle-static] | SM-2 journal [source] | MP4 + transcript + journal [source] | no | missing | missing (B12) |
| Demonstration mode (ghost walks real steps, never clicks) | partial (walkthrough) | no | no | Peeky idea [source] | guide mode points without clicking | partial, folds into B6 |

### Agents, computer use, browser

| Capability | HeyClicky commercial | Clacky | clicky-windows 1.6 | Linux rivals | Wisp today | Verdict |
|---|---|---|---|---|---|---|
| Background agent with live card, files, stop/retry | yes, cards hang from the notch [doc] | hermes over ACP [source] | local answer jobs only [source] | ClickyX Codex sidecar HUD [source] | have: `agents.py`, truthful outcomes, bar pill, Agents tab | have |
| Truthful "done" (exit code and delivered files checked) | worker rule: never claim what did not happen [bundle-static instruction text] | `LINK:` evidence filter [source] | n/a | no | have, stronger: filesystem evidence, IPC authz (#141) | **better** |
| Persistent named agents with own memory, folder, notes file, voice follow-up from the card | yes ("Clickys") [doc, bundle-static AGENTS.md convention] | no | no | no | missing; tasks are one-shot | missing (B10) |
| Agent progress lines at milestones, first sentence of result read aloud | yes [bundle-static] | spoken summary [source] | no | no | partial | missing (B10) |
| Routines by voice, pause after 3 failures, quiet unread result, run only when online | yes [doc] | learn routine [source] | 15 min/hourly/daily [source] | ClickyX cron | have: routines, 3-failure pause, voice-taught | have; "wait for network and wake" missing (B10) |
| Consent: allow once / always / not now, by voice, per conversation | yes [doc] | 4-tier risk [source] | review-a-plan card [source] | Peeky shows move first | have: tier policy, confirm broker, voice choice | have |
| Take back control on any human input | yes: move mouse, talk, or Esc [doc 1.1.1] | Esc | mouse movement stops next action, held keys released [source] | Peeky own cursor | have: real-input takeover (`realinput.py`) | have |
| Previewed multi-action plan with screen-staleness check | no (asks, then drives) | no | yes: up to 20 bounded actions, coordinates tied to captured display, expired screen rejected [source] | no | confirm card per tool tier, no plan preview | missing (B11) |
| Agent works in the user's own signed-in Chrome, own tab group, `keep` rules, batched steps, proof screenshot, never types passwords | yes: MV3 extension with `debugger`, `tabGroups`, native messaging [bundle-static manifest and browser skill] | no | Browser Link: paired loopback extension, snapshot-epoch refs, refuses password fields [source] | Peeky/ClickyX via CUA | partial: CDP client for sandboxed Chromium (`cdpx.py`), BrowserOS connect; no watchable lane in the user's browser | **missing** (B14) |
| Structured connectors first, pixels last, multi-account labels | yes [doc 1.0.53] | Composio/MCP [source] | MCP over HTTP, reviewed calls [source] | ClickyX MCP | MCP client, no account labels | partial (B14) |
| Works while user keeps typing, never moves the real pointer | yes (background driver) [doc] | no | no | Peeky separate cursor | cua-driver background mode | partial |

### Trust, cost, distribution

| Capability | HeyClicky commercial | Clacky | clicky-windows | Linux rivals | Wisp today | Verdict |
|---|---|---|---|---|---|---|
| Source available, auditable, no telemetry | closed; analytics and crash SDKs bundled [bundle-static frameworks and plist keys, trust page names two third parties] | MIT | MIT | MIT | AGPL, no analytics, local audit log, trace kinds | **better** |
| Cost model | Free 25/25 messages, Pro $20 (150 agent msgs), Max $100 [doc] | BYO keys | BYO keys or fully local | Peeky hosted proxy + Pro tier, or BYO | BYO OpenRouter + Groq, spend caps and Spend view | **better** for heavy use |
| Privacy: screenshots only on press, never stored | yes [trust page] | yes | Privacy Guard on sensitive titles; redacts every visible sensitive window and recordings [source] | Peeky on-device router | partial: sensitive-window skip in flight (foreground only) | partial (B9) |
| Honest eval gate | none public | none | tests only | Peeky has tool-routing eval harness [source] | `wispd eval`, v1 gate | **better** once it passes |
| Self-update with verified checksum | Sparkle on Mac, signed self-updating Windows installer [doc, plist update feed] | none | GitHub digest verified, user-confirmed [source] | Peeky `upgrade.rs` | `wispd install --ref`, no `update` verb | missing (B9) |
| Platform | macOS, Windows | Windows | Windows | Linux/Hyprland, macOS | Hyprland/Omarchy only, QML inside the shell | have (focus) |

---

## UX and UI notes

Observed from the 1.1.x changelog, bundled assets and the open-source apps. Each
note is a rule wisp can adopt in its own words and theme tokens.

1. **Every mark is one ink.** HeyClicky draws every mark on the real screen in
   the user's cursor colour with a soft glow, names things in solid pills of that
   colour, numbers steps with badges, and frames regions with a dashed tinted
   box. Paper-like stickies and receipts are only for an explanation card on
   calm space, never to name something on the real screen. Wisp should adopt
   "one ink, two surfaces": *screen marks* versus *cards*. [bundle-static]
2. **Ink contrast is computed.** The host asks "white or dark here?" for text
   written straight on the screen, from the pixels under it. Wisp can sample the
   press-time screenshot for this. [bundle-static]
3. **Drawings are paced to speech.** Strokes after a spoken line are released
   while that line is spoken and spread across it; finishing early draws the rest
   at once while the voice carries on. Highlights fade in ~2 s; drawings clear
   when speech ends: "nothing stays on your screen". Wisp has clear-on-speech-end
   but draws instantly. [bundle-static, doc]
4. **Calm colours for questions.** Ask cards use a calm blue, not the agent's
   own colour, so a question does not read as an error. [doc 1.0.53] Wisp's
   `needsYou` token should be checked against this.
5. **Agents are small windows with a plan.** Running work shows its plan, then
   its result, as a card that can be answered by holding the voice key over it.
   [doc 1.0.53, 1.1.1] Wisp's Now tab holds this today; the bar pill is the
   always-visible part.
6. **Say who finished, and be quiet on calls.** Done is announced out loud and
   beside the cursor except on calls, screen share or Do Not Disturb. [doc]
   Wisp's `suggest_policy` already has the hold rule for suggestions; extend the
   same gate to done announcements.
7. **First two minutes are hands-on.** Say hello, watch it draw, circle
   something and ask, draft a reply by voice, try dictation. [doc 1.0.40] Wisp's
   `wispd onboard` checks plumbing but never shows the product.
8. **Answers carry no filler.** Fewer greetings, no narrating lookups, "talk
   slower" and "you talk too much" as spoken settings that stick. [doc 1.0.45,
   1.0.52]
9. **Hide the settings maze.** The commercial app removed model pickers on purpose ("just a chat and a
   hold-to-talk pill"). Wisp's Settings tab should stay a handful of switches
   and keep model choice in `config.toml`.
10. **Linux overlay discipline.** The Rust rivals ask users to add Hyprland
    window rules to make their overlay float, pin and not take focus. Wisp's
    layer-shell overlay needs none; keep that true and say so on the install
    page.

---

## What makes wisp clearly better (claims each unit must keep true)

1. **It tells the truth about what it did.** Exit code plus delivered files plus
   a recorded verdict, and the v1 eval. No competitor publishes this.
2. **It is native to Hyprland.** Layer-shell overlay that sits over fullscreen,
   Hyprland submap hotkey, `hyprctl` cursor and window state, Wayland-safe
   input. The Linux rivals are ports or need window rules; the commercial app
   has no Linux build.
3. **You own it.** Source, audit log, trace, and no telemetry. HeyClicky bundles
   analytics and crash reporting SDKs and runs "nothing locally".
4. **You pay the model bill and see it.** Spend caps and a Spend view versus
   message-metered plans.
5. **Safety is a design, not a prompt.** Tiered risk, deny-list, IPC authz,
   spawned agents with a scrubbed environment, real-input takeover. The
   commercial agent runs on a general coding runtime with broad permissions
   (inferred from its bundled runtime and instructions).
6. **Measured, not claimed.** `wispd eval` and a labelled gate. The units below
   add a latency gate so "fast" is a number.

If any unit weakens one of these six, it is rejected.

---

## New findings (not in any older plan)

| # | Finding | Evidence | Why it matters |
|---|---|---|---|
| N1 | HeyClicky's drawing is a *program* the model writes, run in a sandboxed worker with a time limit, producing hand-drawn SVG; pieces include graph, timeline, sticky, receipt, clipping, photo, spotlight, target, hover; strokes are paced to speech and a drawing can be edited live by part id | bundle-static (engine 1.6 header, pieces file) | This, not the agent runtime, is why its answers look magical. |
| N2 | 3D answers use a bundled three.js scene and clicking a part asks about it. The main binary also names a single `mac_step` tool for app-window actions, Accessibility (AX) APIs and ScreenCaptureKit | bundle-static, doc | Competitors cannot match it without a renderer; ClickyX uses a paid 3D API. |
| N3 | Background worker contract: working folder is the agent's home with an `AGENTS.md` identity and dated notes; `output/` holds only deliverables, `tmp/` scratch; one bundled question set instead of invented facts; progress lines at milestones; final message leads with the result and its first sentence may be read aloud | bundle-static (worker instruction file) | Concrete rules wisp's agents can adopt today. |
| N4 | Browser lane = MV3 extension in the user's own Chrome with `debugger`, `tabGroups`, native messaging; the agent works in a tab group beside the user's tab, batches up to 20 steps, takes proof screenshots, never types passwords | bundle-static (manifest and browser skill) | A *watchable* lane is the trust feature wisp lacks. clicky-windows built an original version in a week. |
| N5 | Drive plan preview with screen-staleness rejection (clicky-windows) | source | Cheap trust gain for multi-action act turns. |
| N6 | Privacy Guard redacts **every** visible sensitive-titled window, and recordings, not only the focused one | source | Wisp's sensitive-window skip checks the focused window only. |
| N7 | Peeky: on-device intent router (ONNX), release-to-action ~1.2 s, per-stage latency benches, behaviour dials in one file | source | The bar for "fast" on Linux. Wisp has budgets in `wisp/budgets.json` but no CI latency gate. |
| N8 | HeyClicky pulled proactive agents (privacy) and paused suggestions in 1.1.1 | doc | Wisp's suggestions must stay opt-in and read-only. |
| N9 | Windows 1.1.2 fixes show the real pain: comma-decimal locales, GPU-less 3D, focus returned to the app behind after a drive | doc | Wisp analogues: locale-safe parsing, software fallback for any shader, focus return after drive. |
| N10 | Clicklab data on the owner's machine: 4,435 synthetic click trials over 62 tasks, 3,779 acted and 656 aborted, 64% verified, median 6.0 s per trial | file stats from the removed training stack | A ready baseline for B3 (accuracy) and B2 (latency); not a product claim. |

---

## Top gaps in plain words (ranked)

1. It is not fast enough to feel instant, and nothing measures it in CI.
2. Pointing and clicking are right only 3 times in 10 in the labelled data.
3. The step-by-step teacher exists as code but is not turned on.
4. Drawings are plain shapes; HeyClicky's are hand-drawn and paced to speech.
5. You cannot scribble on the screen to say "this one".
6. Agents are one-shot jobs, not named helpers with memory you can talk back to.
7. No watchable lane in your own browser.
8. It only reads what is on screen, not the whole PDF or file.
9. Answers cannot carry a picture or a 3D part.
10. No first-minute tour that shows what it can do, and no saved lessons.

---

## Planning Contract

### Key Technical Decisions

- **KTD1 — Latency is a gate, not a goal.** Add a replay-harness latency check
  for each stage in `wisp/budgets.json` that fails CI on regression, before any
  new feature adds a hop.
- **KTD2 — Drawing is a data format, rendered natively.** Marks stay a small
  declarative list the QML overlay renders; the model never emits executable
  code. This keeps the sandbox problem (N1) out of wisp and matches clicky-windows'
  rule that model output is never executed.
- **KTD3 — Speech is the clock.** Any animated mark takes its start and duration
  from the sentence it belongs to (already how points work, #150), so drawing
  pace and voice cannot drift.
- **KTD4 — A browser lane uses the user's own browser and the user's yes.** One
  Chromium extension, paired explicitly to a loopback socket, own tab group, no
  password or code fields, no run without a user action that connected it. Wisp
  keeps CDP for sandboxed browsers.
- **KTD5 — Spawned agents keep the scrubbed environment (Phase 8) and gain a
  folder contract.** A per-agent home with `AGENTS.md`, `output/`, `tmp/`;
  deliverables verified on disk (already true) before the first sentence is
  spoken.
- **KTD6 — New units extend files owned by Phase 7–9 only after those land.**
  Units marked `after P7`/`after P9` rebase on those PRs.

### Phased Delivery

| Order | Unit | Delivers | Size | Depends on |
|---|---|---|---|---|
| 1 | B1 | Latency gate in CI from the replay harness | S | — |
| 2 | B2 | Fast first sentence: speculative answer start and warm paths | M | B1, P7 streaming STT |
| 3 | B3 | Accuracy loop: clicklab baseline replay and the three top fixes | M | P9 |
| 4 | B6 | Walkthrough turned on, with app skills and demonstration mode | M | P7 |
| 5 | B4 | Hand-drawn ink and speech-paced reveal | M | #152 |
| 6 | B7 | Scribble to ask | M | B4 |
| 7 | B10 | Named agents, progress lines, spoken first sentence | M | #141 |
| 8 | B11 | Plan preview and stale-screen guard for multi-action drives | S | — |
| 9 | B9 | Whole-document reading, redact all sensitive windows, `wispd update` | M | P7 sensitive-skip |
| 10 | B14 | Watchable browser lane | L | KTD4 |
| 11 | B8 | Voice polish: speed, captions, failover, quiet-on-calls | S | P7 |
| 12 | B5 | Photo and image cards | M | B4 |
| 13 | B12 | Lessons, replay, and first-minute tour | M | B6 |
| 14 | B13 | 3D parts (optional) | L | B5 |

---

## Implementation Units

IDs `B1`–`B14` never renumber. "Files" lists the expected touch points, not a
promise. "Must not touch" keeps this plan out of the other worker's lane.

### B1. Latency gate from the replay harness

**Goal:** "Fast" becomes a number in CI.
**Requirements:** R4, KTD1. **Dependencies:** none.
**Files:** `tests/test_turn_replay.py`, `wisp/budgets.json`, `tests/test_latency_budgets.py` (new), `docs/PIPELINE_STAGES.md`.
**Approach:** Compute per-stage spans from replay traces (stt, route, first_token, tts_start, stop) against `budgets.json` p50 with its p90 factor; fail on regression beyond a stated margin. Keep live-only spans (press, release) out.
**Acceptance criteria:**
- A deliberately slowed fixture stage fails the new test; the unmodified suite passes.
- `wispd eval` prints the measured p50 and p90 for each measured span next to its budget.
- No budget in `budgets.json` is loosened by this unit.
**Verification:** `python3 -m unittest tests.test_latency_budgets tests.test_turn_replay`.
**Must not touch:** `ROADMAP.md`.

### B2. First sentence sooner

**Goal:** Median release-to-first-spoken-word ≤ 1.8 s with hosted keys (Peeky reports ~1.2 s to action, HeyClicky "a couple of seconds").
**Requirements:** R3, KTD1. **Dependencies:** B1, Phase 7 streaming STT.
**Files:** `wisp/stage_capture.py`, `wisp/stage_route.py`, `wisp/speech.py`, `wisp/stage_speak.py`, `tests/test_turn_replay.py`.
**Approach:** (1) Start the answer model call from the streaming-STT final partial as soon as it arrives, not after the whole transcript pass. (2) Keep TTS connection warm during `listening` (gap-closure KTD3, if not landed). (3) Pre-baked ack clip only for routes the heuristic marks slow, and only after B1 shows the span. (4) Split sentences only on `[.!?…]` plus whitespace (clacky-delta R9) if not yet true.
**Acceptance criteria:**
- Replay trace for a chat turn shows first TTS audio ≥ 300 ms earlier than the pre-change trace on the same fixture.
- No second connect to the STT or TTS endpoint in the call log for one turn.
- A cancelled turn in `listening` leaves no open connection (LeakGuard).
- The owner's live `wispd eval` p50 for "key up to first audio" is recorded in the PR description before and after.
**Must not touch:** act-loop code; Phase 9 owns it.

### B3. Accuracy loop on the clicklab baseline

**Goal:** Turn the 32% first-time-correct figure into a tracked climb to the 60% gate.
**Requirements:** R3. **Dependencies:** Phase 9.
**Files:** `wisp/learn.py`, `wisp/grounding.py`, `tests/fixtures/turns/`, `docs/baselines/`.
**Approach:** Import the owner's `clicklab.jsonl` summary (62 tasks, 4,435 trials) as a read-only baseline in `docs/baselines/`; rank task kinds by abort rate and median time; add one replay fixture per top failure kind; make label-first snap prefer the control/a11y lane over model pixels (clacky-delta U8) and refuse model-chosen mutating clicks that resolve to no element unless the user dictated coordinates.
**Acceptance criteria:**
- A baseline file lists, per task kind: trials, acted, aborted, verified rate, median ms; numbers match the source file.
- Each of the three worst kinds has a replay fixture that failed before the fix and passes after.
- `wispd eval` first-time-correct rate on labelled turns does not drop; the PR states the new tally.
**Must not touch:** any file Phase 9's open PR changes, until that PR merges.

### B4. Hand-drawn ink, paced to speech

**Goal:** Marks look drawn by a person, appear as the sentence is spoken, and read on any background.
**Requirements:** R3, KTD2, KTD3. **Dependencies:** #152.
**Files:** `shell-plugin/components/DrawLayer.qml`, `shell-plugin/lib/` (new `ink.js`), `wisp/points.py`, `wisp/stage_speak.py`, `tests/qml/`.
**Approach:** Stroke wobble with a tapered pen and a soft glow in the buddy's ink colour; pen-reveal duration derived from the sentence's spoken duration (KTD3) with a `finish now` path when speech ends early; one ink for marks, solid pills for names, numbered badges for steps, dashed tinted frame for a region; text-on-screen colour chosen from luminance under it, sampled from the press-time screenshot. Reduced-motion setting draws instantly. Marks stay declarative (KTD2); an unknown mark kind is dropped, never executed.
**Acceptance criteria:**
- Golden snapshot for each mark kind in dark and light themes (`scripts/ui/snap.py`).
- A three-mark answer reveals mark 2 no earlier than its sentence's start time in the replay trace; `finish now` completes all marks within one frame budget.
- White text on a dark region and dark text on a light region in the luminance fixture.
- Reduced motion produces zero animation frames.
- `test_tokens_only` and `test_components` still pass; no hard-coded hex values.
**Must not touch:** `Buddy.qml` motion constants.

### B5. Photo and image cards

**Goal:** An answer can carry a picture the user can see next to the cursor.
**Requirements:** R3. **Dependencies:** B4.
**Files:** `wisp/note.py`, `shell-plugin/components/` (new `Card.qml`), `wisp/tools/` (image fetch with allow-list).
**Approach:** Extend the `::` paper grammar with an image object; fetch through a bounded, allow-listed fetcher that stores a local copy and records source URL; render in a card on calm screen space, never over the thing being named.
**Acceptance criteria:**
- A replay turn emitting an image object produces a card with the local file and a visible source line.
- A non-allow-listed host is refused with a spoken reason, never fetched.
- Card placement avoids the target rectangle in a fixture with a point on the left half.
**Must not touch:** voice path.

### B6. Walkthrough on, with skills and demonstration mode

**Goal:** "How do I do X in this app" becomes a spoken, pointed, click-detected, resumable lesson.
**Requirements:** R3. **Dependencies:** Phase 7 (owns wiring `walkthrough.py`, label-first snap).
**Files:** `wisp/walkthrough.py`, `wisp/skills.py`, `wisp/skills_seed/apps/`, `wisp/stage_route.py`.
**Approach:** After Phase 7 wires the step machine: call the app-skill matcher before the first step and put the skill text in the prompt; add a `demonstrate` mode (point and narrate, never click; Peeky's idea); on "continue" after a manual step, keep goal and done-log; ask what the user already has before step one (HeyClicky 1.0.53 rule); never repeat a step that just failed.
**Acceptance criteria:**
- Replay: three-step lesson advances on a window-state change, repeats nothing, stops at step 15.
- Fixture with a loading page waits, then continues.
- `demonstrate` mode emits points and speech but zero input events (audit log shows none).
- With a seeded skill for the focused app, the prompt contains its text; without one it does not.
**Must not touch:** anything Phase 7's open PR changes before it lands.

### B7. Scribble to ask

**Goal:** Hold the talk key, drag on the screen to circle the thing, and say "what is this".
**Requirements:** R3. **Dependencies:** B4.
**Files:** `shell-plugin/Companion.qml`, `shell-plugin/components/` (new `ScribbleLayer.qml`), `wisp/stage_capture.py`.
**Approach:** While status is `listening`, an input region on the overlay captures pointer drag; the strokes are composited into the press-time screenshot sent to the model (as a flagged image) and cleared when the turn ends. The layer exists only during `listening`, so no persistent surface sits over user content.
**Acceptance criteria:**
- Strokes drawn during `listening` appear in the screenshot passed to the brain fixture; none after `speaking`.
- With no drag, behaviour is identical to today (golden unchanged).
- Click-through is restored within one frame of leaving `listening`.
**Must not touch:** IPC contract fields (reuse existing state).

### B8. Voice polish

**Goal:** Close the small voice gaps competitors list in their changelogs.
**Requirements:** R3. **Dependencies:** Phase 7.
**Files:** `wisp/speech.py`, `wisp/stage_capture.py`, `wisp/suggest_policy.py`, `shell-plugin/lib/settings_schema.js`, `wisp/settings_schema.py`.
**Approach:** Voice speed 0.5–1.5x; captions toggle; fail over to the default mic on device loss and say so; hold the capture channel through a Bluetooth reply; if the speaker is muted keep the answer on the clipboard and say so on the bubble; hold done announcements on calls or screen share (reuse `suggest_policy` gate); "talk slower" and "stop announcing yourself" as spoken settings.
**Acceptance criteria:**
- Speed 1.5x shortens a fixed fixture utterance by ≥ 25% and 0.5x lengthens it by ≥ 50% (TTS command receives the rate).
- Dead-mic fixture finishes the turn on the default device or ends with the existing audio error code, never a hang.
- Muted-speaker fixture sets the clipboard and shows the bubble hint.
- A voice command changes a setting only through the existing `config` IPC and appears in the audit log.

### B9. Documents, whole-screen privacy, and update

**Goal:** Answer about the whole file; redact every sensitive window; update safely.
**Requirements:** R3. **Dependencies:** Phase 7 sensitive-window skip lands first.
**Files:** `wisp/stage_capture.py`, `wisp/context.py`, `wisp/tools/` (document reader), `wispd` (`update` verb), `docs/INSTALL.md`.
**Approach:** (1) Read the focused document's file when its path is knowable (window title or open-files probe), bounded size, PDF/DOCX/XLSX text with OCR fallback; refuse paths in protected folders. (2) Extend sensitive-window handling from "focused only" to "any visible window whose title matches", blanking those regions in the screenshot (clicky-windows rule). (3) `wispd update` fetches a tagged release, verifies SHA-256, shows the diff summary and waits for the user's yes; never auto-installs.
**Acceptance criteria:**
- A fixture PDF of 40 pages answers a question about page 30 that is not visible on screen.
- A fixture with a banking-titled window behind the focused one produces a screenshot with that region blanked; focused-only behaviour is a strict subset.
- `wispd update --dry-run` prints version, digest and the files that would change and writes nothing; a wrong digest aborts.
- The docs lint passes (`python3 -m unittest tests.test_docs_lint`).

### B10. Named agents with a folder, progress and a spoken result

**Goal:** Background work feels like a helper you know, not a job number.
**Requirements:** R3, KTD5. **Dependencies:** #141, Phase 8.
**Files:** `wisp/agents.py`, `wisp/routines.py`, `shell-plugin/components/AgentRow.qml`, `RunCard.qml`, `wisp/stage_route.py`.
**Approach:** A named agent has a folder (`AGENTS.md` identity, dated notes, `output/`, `tmp/`); the spawn prompt gets the contract (ask once with bundled questions, progress line at milestones, first sentence of result is the spoken summary, say "drafted" for drafts); "tell <name> …" and "what's running" route by name; the Agents tab card accepts a spoken follow-up while hovered; routines wait for network and for wake before running and a run missed while offline does not count toward the three-failure pause.
**Acceptance criteria:**
- Spawning "make me a research helper called Scout" creates the folder with `AGENTS.md`; a second run reads its notes.
- A finished agent whose `delivers` file is missing announces failure, not done (existing test stays green).
- "Tell Scout …" routes to Scout and does not create a second agent.
- A routine due while offline runs once after reconnect and the failure counter is unchanged.
- No credential appears in the agent environment (Phase 8 test stays green).

### B11. Plan preview and stale-screen guard

**Goal:** A multi-action act turn shows the whole plan once and refuses to run on a screen that has changed.
**Requirements:** R3. **Dependencies:** none.
**Files:** `wisp/act.py`, `wisp/confirm.py`, `wisp/cua_safety.py`, `tests/test_act.py`.
**Approach:** When the model proposes ≥ 3 mutating steps, show them as one card (bounded to 20), run on yes; before each step compare the capture hash and focused window with the plan's; a mismatch re-plans rather than clicking stale coordinates.
**Acceptance criteria:**
- A 4-step fixture produces exactly one confirm card listing four lines.
- Changing the focused window between steps aborts with a spoken reason and zero further input events.
- Single-step turns behave exactly as today (existing confirm tests unchanged).

### B14. Watchable browser lane

**Goal:** Browser work happens in the user's own Chromium, in a tab group beside theirs, and the user can watch and stop it.
**Requirements:** R3, KTD4. **Dependencies:** none; large, ships behind `[browser] lane = "extension"` default off.
**Files:** `shell-plugin/` or new `browser-extension/` (MV3), `wisp/tools/browser.py` (new), `wisp/cua_safety.py`, `docs/`.
**Approach:** Original MV3 extension (no vendor code) with `tabs`, `tabGroups`, `scripting`; explicit pairing to a loopback-only socket with a one-time code; a per-task tab group; snapshot with element refs valid for one snapshot epoch; batched steps (≤ 20) with `wait_for`; proof screenshot saved to the agent's `output/`; refuse password, one-time-code and card fields; toolbar stop ends the lane for the turn.
**Acceptance criteria:**
- Without pairing, every call fails with a clear setup message and does nothing.
- A fixture page with a password field is read but never filled.
- A ref from an old snapshot epoch is rejected.
- Stopping from the toolbar ends the task within 1 s and the tab group closes unless a tab was kept.
- The extension requests only the permissions listed above (manifest test).

### B12. Lessons and the first minute

**Goal:** A lesson can be saved, replayed, and a new user sees the product work in two minutes.
**Requirements:** R3. **Dependencies:** B6.
**Files:** `wisp/walkthrough.py`, `wisp/memory.py`, `wisp/onboard.py`, `shell-plugin/lib/onboard.js`.
**Approach:** Save a finished walkthrough as a lesson (title, steps, spoken lines); "replay that lesson" re-speaks and re-points without calling the model; `wispd onboard --tour` runs five spoken steps: hello, watch it draw, circle something, ask about the screen, try dictation; replayable from Settings.
**Acceptance criteria:**
- A saved lesson replays with zero model calls (call log asserts).
- The tour completes against the fixture voice with each step logging its pass.
- Docs lint passes; `wispd` commands named in docs exist.

### B13. 3D parts (optional, last)

**Goal:** For "what is this, a real thing" answers, a small 3D model whose parts can be clicked to ask about.
**Requirements:** R3. **Dependencies:** B5.
**Files:** `shell-plugin/` (Qt Quick 3D or a bundled glTF viewer), `wisp/note.py`.
**Approach:** Only after B1–B12 and only if the owner asks: glTF from an allow-listed source, software-render fallback (N9), click a part to ask. Not started unless the owner overrides the order.
**Acceptance criteria:** a model renders on a machine without GPU acceleration; clicking a named part sends one question with the part name; the overlay is click-through again when closed.

---

## Verification Contract

| Gate | Command | Applies to |
|---|---|---|
| Compile | `python3 -m py_compile wispd wisp/*.py wisp/tools/*.py tests/*.py` | all |
| Unit suite | `python3 -m unittest discover -s tests` with no API keys in the environment | all |
| Docs lint | `python3 -m unittest tests.test_docs_lint` | B1, B9, B12 |
| QML goldens | `python3 scripts/ui/snap.py` then `tests/test_snap.py` | B4, B5, B7 |
| Replay | `python3 -m unittest tests.test_turn_replay` | B1, B2, B6, B8 |
| Eval | `wispd eval` tally recorded in the PR body | B2, B3 |

## Definition of Done

- Each landed unit passes its acceptance criteria and every gate it lists.
- Each of the six *better* claims still holds (checked in review).
- The matrix rows a unit closes are updated in the unit's PR, with the evidence class kept.
- No unit adds telemetry, a local model server, or competitor text or code.
- The v1 gate (`wispd eval` at the owner's rate over 50 labelled turns) is met before B10 onward ship.

## Sources

- HeyClicky changelog v1.0.10–v1.1.3: `https://www.heyclicky.com/changelog`; trust page `https://www.heyclicky.com/trust`; reviews of 2026-10-24/25 (GetQuids, Creators Toolbox, rahmanbuilds).
- HeyClicky 1.1.1 macOS bundle, read-only static inspection by the owner's machine (Info.plist, resource files, helper and framework names).
- `Raynan00/clacky` v0.2.0 and `docs/research/2026-10-25-clacky-teardown.md`; owner's port notes `2026-10-26-port-research.md`.
- `Bitshank-2338/clicky-windows` `6c6216b` (`RELEASE-NOTES-1.6.md`, `drive.py`, `drawing.py`, `response_blocks.py`).
- `danielbusnz/Peeky` `5950340`, `unn-Known1/clickyX` `988568a`, `tornikegomareli/clicky-desktop`, `pango07/flicky`, `stevenvo780/clawbar` READMEs.
- `jasonkneen/openclicky` README and AGENTS.md (macOS only, not a Windows or Linux rival).
- In-repo: `docs/plans/2026-10-25-0151`, `2026-10-25-0215`, `2026-10-25-1625`, `2026-10-26-0031`, `2026-10-26-2149`; `docs/research/heyclicky-features.md`; `wisp/budgets.json`.
