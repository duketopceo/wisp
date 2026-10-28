---
title: "feat: Beat every competitor — wisp competitive teardown and unit plan"
date: 2026-10-27
updated: 2026-10-28
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
  existing parity plans do not already cover, and prioritized units (`B1`–`B34`; `B15`–`B34` added 2026-10-28)
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
| **Omarchy-native voice plugins** | **omarchy-voice** (213 stars), **Jarvis**, **omavoice**, **O.M.A.**, **omarchy-hermes-companion**: voice assistants shipped as Omarchy 4 shell plugins and installed with `omarchy plugin add`. They live in the marketplace wisp must also be listed in. Details in *Second scrub*. | README and repo metadata read 2026-10-28 |
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

### Second scrub (2026-10-28): Omarchy-native rivals, growth and distribution

Status note: since this plan was written, `master` (`09bb4c6`) has landed B1
(#164), B2's first-clause speedup (#167, with streaming STT #162), B4 (#177),
B6 (#163, #165, #166), B8 voice speed (#172), B9 (#171, #173, #174), B10
(#170, #175), B11 (#168) and B12 (#169). B3, B5, B7, B13 and B14 are not on
`master`. The older rows above are not re-audited here; the rows below are new.

#### Omarchy-native voice rivals (not in the roster above)

Omarchy 4 ("Quattro") put its whole shell in Quickshell and added a plugin
marketplace. Five voice assistants already ship there. Wisp's plugin is the same
kind of thing, so these are the nearest rivals and the place wisp must also be.

| Rival | What it is | Strength to respect | Where wisp is ahead |
|---|---|---|---|
| **omarchy-voice** (`wombatoperator`, MIT, 213 stars) | OpenAI speech plus local tools behind a policy gate; moves windows, reads pages and terminals with OCR, durable tasks, camera inspection [README] | Most stars; clear "what leaves your machine" warning | Points and draws on the real screen, teaches step by step, publishes an accuracy gate (rivals' READMEs show none, inferred) |
| **Jarvis** (`Atzingen/hey-jarvis`, MIT, 23 stars) | Wake word ("hey jarvis"), barge-in, English and Brazilian Portuguese, Codex/Claude on the machine with per-command consent, system-wide dictation, bar panel, install from the bar icon [README] | Wake word, bilingual, one-click install from the bar | Screen context, pointing, honest task outcomes |
| **omavoice** (`baranskyi`, MIT, 8 stars) | Realtime voice with a Codex/Claude "brain" behind it; the README claims about 1.6 cents a minute against about 20 for pure realtime, and keeps all networking and audio out of QML [README, claim not verified] | Cost split, a clean plugin boundary | Screen-aware, no vendor realtime lock |
| **O.M.A.** (`komagata/oma`, MIT, 6 stars) | Voice assistant with a theme-coloured low-poly face, memory, desktop tools, and an installation runbook written for a coding agent [README] | Agent-installable runbook, strong brand | Teaching, drawing, verification |
| **omarchy-hermes-companion** (`PSthelyBlog`, MIT, 7 stars) | Always-on Hermes agent that watches the focused monitor and speaks up [README] | Proactive | Wisp watches only on press (the trust line the commercial app also drew) |

Evidence class for every row: `source` (public GitHub README and repo metadata
read 2026-10-28). Behaviour was not run.

#### Voice, trust and onboarding rows added

| Capability | HeyClicky commercial | Rivals | Wisp today (`09bb4c6`) | Verdict |
|---|---|---|---|---|
| Languages | Voice in 70+ languages, dictation 50+, added because signups came from 100+ countries [doc 1.0.26, 1.0.37] | Jarvis English and Brazilian Portuguese [source]; farzaa/clicky issue #7 asks for non-English [source] | Hosted STT model is multilingual, but replies, vocabulary priming and the voice are English; local default is `small.en` | **missing** (B23) |
| Wake word and hands-free | "Always On" with echo cancel, headphones only; double-tap hands-free dictation [doc 1.0.26, 1.0.31, 1.0.37] | Jarvis wake word, O.M.A. optional voice wake [source] | Hold-to-talk only | missing, owner decision (B33) |
| Never lose dictated words | Sessions over 10 min saved, interruptions keep what was said, local transcript backup [doc 1.0.47]; farzaa/clicky issue #125 asks for local history [source] | no | Clipboard restore after paste exists; no history, no retry of a failed insert | missing (B24) |
| Selection, clipboard image or file as context | Drag files in, paste files and images [doc 1.0.49] | no | Whole-document reading for the focused window only (B9); no selection or clipboard context | missing (B22) |
| Knows what to ask | Suggestions (now paused) and a hands-on tour [doc]; a user says they "forget it's there" and are "not sure what to ask" [Reddit r/macapps] | no | First-minute tour (B12); nothing per app | missing (B21) |
| What's new after an update, credited changelog | Card after update; every fix credits the reporter and gives counts [doc 1.0.48+] | no | Releases only | missing (B26) |
| Bug report that carries logs | In-app, logs attached [doc 1.0.23] | no | Opt-in typed-error reporting (`report.py`); no user-reviewed bundle | partial (B26) |
| Second copy refuses to start | Yes, after answers played two or three times [doc 1.0.53] | no | systemd unit only; no guard for a manual second `wispd` | missing (B29) |
| Idle CPU budget | 36-45% idle CPU incidents fixed, 3-5% target [doc 1.0.47, 1.0.49] | no | Latency budgets only | missing (B29) |
| Blank capture handled | Window screenshots that came out blank fixed more than once; a user could not use it in Premiere Pro because capture was blocked [doc, Reddit] | no | Not detected | missing (B28) |
| Answers about itself | Tells the truth about its models, settings and plan use [doc 1.0.24, 1.0.52] | no | Settings by voice (B8); no model, spend or version answers | partial (B30) |
| Share a setup with a friend | Shared skill pages, team-shared skills [doc 1.0.44, 1.0.52]; an outside prototype exists because people want it (`share-a-clicky`) [source] | no | Local lessons and helpers (B10, B12); no export | missing (B27) |
| Interview-seeded onboarding | Four questions then three made-for-you Clickys; first tasks end in different ways [doc 1.0.49, 1.0.52] | no | Tour only | missing (B32) |
| Trust page | Names its two analytics and crash vendors and says nothing runs locally [doc trust page] | no | Claims are in README prose | **better** once generated from code (B25) |
| Teaches the OS itself | no | none cover Omarchy's own bindings, menu and themes | `omarchy-bridge` and `hyprland` seed skills only | **missing, uncontested** (B16) |
| Installable from the platform's own channel | Mac DMG, signed Windows installer [doc] | Jarvis and O.M.A. document `omarchy plugin add <git-url> --enable` [source] | `wispd install` from a clone; manifest lives in `shell-plugin/`, not the repo root | **missing** (B15) |

#### Growth and distribution tactics (what actually worked, and the wisp answer)

| Tactic | Evidence | Wisp answer |
|---|---|---|
| A rough, scripted demo posted weekly beats one polished launch; judge by downloads and day-five retention, not views [YC podcast summary, biggo] | The first demo got nearly 3M views, about 7,000 downloads (under 1% of views) and about 100 people still using it five days later | B17 demo kit; B31 measures what matters |
| Channel mix: Instagram about 70% of traffic, YouTube the best converter (about 20% of viewers downloaded), X the worst (under 1%) [same] | Same source | B17 (record once, cut per channel); posting is the owner's call |
| Targeted niche videos, tiny reach, real leads (about 4,000 views each, about 50 agency leads) [same] | Same source | B17, B18: target Omarchy users, not "everyone" |
| Talked to each of the roughly 100 retained users one by one [same] | Same source | B31 (owner-approved outreach only) |
| The open-source repo as the funnel: MIT, 7,796 stars, 1,556 forks; README opens with a prompt you paste into a coding agent that installs everything [farzaa/clicky, read 2026-10-28] | 91 open issues; top asks are Windows, Linux, bring-your-own key, non-English | B20 runbook and prompt; B23, B34 |
| A public changelog with credited reporters and real counts, plus a card in the app after an update [changelog] | Every release since 1.0.47 | B26 |
| Pricing: about $9 a month at launch, now Free (25 talk, 25 agent messages), Pro $20 (150), Max $100 (1,000); yearly 20% off; students 50% off the first month; referral link gives a friend 25% off and the inviter 25% cash for 12 months [doc, newsletter] | $1,000 MRR six days after launch (secondary source) | Wisp is free and AGPL. No paid tier is proposed. Decisions are listed under *Needs the owner's OK* |
| Landing copy feedback: lead with the literal job, the "buddy" is flavour [farzaa/clicky issue #62] | One issue, no replies | B19 |
| First-run is a growth surface (a well-known newsletter author called it his favourite onboarding) [site testimonials] | HeyClicky home page | B12 landed; B21 and B32 extend it |
| A community the user can reach from Settings (WhatsApp group), feature-request link, bug report with logs [changelog 1.0.27, 1.0.23] | Linked in the app | B26, B31 |
| Peeky: a hosted free trial, "enter your email for more free access", or bring your own keys; a paste-into-Claude-Code install [README] | getpeeky.ai | B20, B34 |
| OpenClicky (Windows): sign in with a ChatGPT account instead of API keys [README] | OAuth/PKCE, tokens in the OS credential store | B34 option |
| Omarchy's own channel: 500+ marketplace plugins by 2026-08-19, 100,000 installs in a week by 2026-08-28, a plugin competition, Omarchy Rangers and meetups, an Omarchy Store desktop app [Omarchy news, marketplace repo] | Verified-listing flow with an automated security baseline | **B15, B18, B16** |

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

11. **Nobody should have to guess what to ask.** A user wrote that they "forget
    it's there" and are "not sure what to ask". A tap with no speech should
    offer three asks that fit the focused app. [Reddit r/macapps, 2026-05-05]
    (B21)
12. **Lead with the literal job.** "An AI teacher on your computer that sees,
    talks and points" before the buddy framing. [farzaa/clicky issue #62] (B19)
13. **Say why, in plain words.** The commercial app replaced "plz restart me"
    with a message saying the provider was blocked in the user's region or
    network. Wisp's typed error codes should each have a one-line spoken cause.
    [doc 1.0.48] (B26, B30)
14. **Anything that repeats asks first.** A suggested routine says it repeats and
    waits for "yes, keep it going". [doc 1.0.53] (B32)
15. **A second copy must not exist.** Two running copies answered two or three
    times at once. [doc 1.0.53] (B29)

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
| N11 | Omarchy 4 has a plugin marketplace: 500+ plugins by 2026-08-19, 100,000 Omarchy installs in one week by 2026-08-28, a plugin competition, Rangers, meetups, an Omarchy Store app. A listing is a public GitHub repo with a root `manifest.json`, README, license and a unique id, then a submission issue and an automated security baseline. `omarchy plugin add <git-url> --enable` installs. Approval is "not a security review" | web: Omarchy news, plugins.omarchy.org publish guide, marketplace repo | The biggest distribution channel wisp has, and wisp's manifest is under `shell-plugin/`, not at a repo root (B15). |
| N12 | Five voice assistants already ship as Omarchy plugins; omarchy-voice leads with 213 stars. Their READMEs describe desktop control and conversation, not pointing, drawing or step-by-step teaching | source | Wisp's gap is presence, not capability (B15, B16, B18). |
| N13 | HeyClicky's founder: the first demo had nearly 3M views, about 7,000 downloads and about 100 people still using it at day five; Instagram about 70% of traffic, YouTube about 20% download rate, X under 1%; targeted niche videos produced about 50 leads from about 4,000 views each | web: YC podcast summary (biggo), arenamag, newsletter | Measure downloads and day-five use, not views (B17, B31). |
| N14 | `farzaa/clicky` on 2026-10-28: 7,796 stars, 1,556 forks, 91 open issues; top asks Windows, Linux, bring-your-own key, non-English, local dictation history, a security pass on logs, own knowledge base, clearer positioning | source | A demand list wisp can answer item by item (B20, B23, B24, B25, B19). |
| N15 | Users' stated reasons for quitting or doubting HeyClicky: forgot it was there, not sure what to ask, slow, blocked in Premiere Pro, a following cursor felt like surveillance | web: Reddit r/macapps and r/heyclicky_ | Three of these are product units (B21, B28, B25). |
| N16 | HeyClicky added 70+ voice languages because signups came from 100+ countries; dictation 50+ | doc 1.0.26, 1.0.37 | Wisp's hosted STT is multilingual, the rest of the turn is not (B23). |
| N17 | Dictation reliability detail: sessions over 10 min dropped silently, interruptions discarded words, paste raced the clipboard restore; fixed with chunked saves, kept words and a local transcript backup | doc 1.0.47, 1.0.48 | B24. |
| N18 | Resource and duplicate-instance incidents: idle CPU up to 45% for 1,600+ users, then a 3-5% target; a second running copy answered two or three times | doc 1.0.47, 1.0.49, 1.0.53 | B29. |
| N19 | Changelog style: every fix credits the reporter and gives counts ("117 users hit the Bluetooth cutout last month"), in-app card after an update, bug reports attach logs | doc 1.0.23, 1.0.48 | A trust and loyalty loop that costs words, not code (B26). |
| N20 | Pricing and plan facts: about $9 a month at launch (secondary source), now Free (25 talk, 25 agent), Pro $20 (150 agent), Max $100 (1,000), yearly 20% off, students 50% off month one, referral 25% off for the friend and 25% cash to the inviter for 12 months, team plans by hand | doc pricing page, changelog 1.0.44, 1.0.52 | Recorded as context; no paid tier is proposed. |
| N21 | Sharing is wanted: HeyClicky has shared skill pages and team-shared skills, and an unrelated developer built `share-a-clicky` because new users start from a guess | doc, source | B27. |
| N22 | Plugin boundary rule from a rival's README: no networking and no audio inside QML because the plugin shares the shell process | source (omavoice) | Wisp's QML already talks to the daemon only; B15 adds a test. |
| N23 | HeyClicky's trust page names its analytics and crash vendors, says screenshots are not stored and nothing runs after quitting, and says it has no SOC 2 or ISO 27001 | doc trust page | A generated, tested wisp trust page is a stronger answer (B25). |

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
11. Not installable from Omarchy's own plugin channel, where five rival voice
    assistants already are.
12. No video, no landing page, no changelog people read: nothing a stranger can
    see before installing.
13. English only after the speech step; no selection or clipboard context; no
    local dictation history.
14. A new user does not know what to ask, and a blocked screen is not noticed.

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

### Phased delivery, second scrub (2026-10-28)

The v1 gate still comes first. These units are independent of B3, B5, B7, B13
and B14 and can run beside them; order is by distribution leverage, then
retention, then trust, then the units that need a decision.

| Order | Unit | Delivers | Size | Tracker | Owner's OK |
|---|---|---|---|---|---|
| 1 | B15 | Omarchy marketplace listing and one-line install | M | TLY-310 | yes |
| 2 | B16 | Omarchy tutor pack read from the user's own machine | M | TLY-311 | no |
| 3 | B17 | Demo kit: scripted clips and README hero | M | TLY-312 | yes |
| 4 | B18 | Omarchy ecosystem outreach pack (drafts only) | S | TLY-313 | yes |
| 5 | B19 | Landing page with the literal promise and a real cost card | S | TLY-314 | yes |
| 6 | B20 | Agent-installable runbook and one-paste prompt | S | TLY-315 | no |
| 7 | B21 | What can I ask here? Context chips for new users | S | TLY-316 | no |
| 8 | B22 | Selection, clipboard and file as context | S | TLY-317 | no |
| 9 | B23 | Multilingual turns | M | TLY-318 | no |
| 10 | B24 | Dictation safety net | S | TLY-319 | no |
| 11 | B25 | Trust page generated from code and a log hygiene gate | S | TLY-320 | no |
| 12 | B26 | What's new card, credited changelog and wispd bugreport | S | TLY-321 | no |
| 13 | B27 | Share a lesson, skill or helper safely | M | TLY-322 | no |
| 14 | B28 | Blank or protected capture detection | S | TLY-323 | no |
| 15 | B29 | One instance and an idle resource gate | S | TLY-324 | no |
| 16 | B30 | Wisp knows itself | S | TLY-325 | no |
| 17 | B31 | Growth scoreboard from public signals and a retention loop | S | TLY-326 | yes |
| 18 | B32 | Starter pack from four questions | S | TLY-327 | no |
| 19 | B33 | Hands-free mode and optional local wake word | M | TLY-328 | yes |
| 20 | B34 | Lower the key barrier: capped trial or CLI-backed deep brain | L | TLY-329 | yes |

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

## Implementation Units: second scrub (B15–B34)

Added 2026-10-28 from a scrub of heyclicky.com (home, pricing, trust, careers,
changelog v1.0–v1.1.3), `farzaa/clicky` (README, issues, history),
HeyClicky-named forks, clones and Omarchy-native voice plugins. IDs `B15`–`B34`
never renumber. Order is priority. Every unit extends the six "better" claims; a
unit that weakens one is rejected. Units marked **OK** contain a step that
spends money, posts, or changes a promise to users; the code part is built, the
external step waits for the owner (see *Needs the owner's OK*).

### B15. Omarchy marketplace listing and one-line install

**Goal:** `omarchy plugin add <wisp git url> --enable` gives a working bar widget and overlay, and wisp is listed in the Omarchy Plugin Marketplace. **OK** to submit.
**Requirements:** R3. **Dependencies:** none. **Tracker:** TLY-310.
**Files:** `shell-plugin/manifest.json`, a generated plugin-only mirror (new `scripts/plugin_mirror.py`, `.github/workflows/release.yml`), `docs/INSTALL.md`, `README.md`, `wispd` (`install --from-plugin`).
**Approach:** The marketplace wants one plugin per public repo with `manifest.json`, a README with install and removal, a license, an optional `preview.png`, and a globally unique id outside `omarchy.*` (the current id `io.github.duketopceo.wisp` qualifies). The manifest lives under `shell-plugin/`, so publish a release-built mirror repo (plugin files only, same id, preview image from the README renders) and keep this repo the source of truth. The bar widget shows an Install button that runs `wispd install` after printing every file it will touch, including the bind it adds to `bindings.lua`, and asks first (the listing checklist forbids overwriting user configuration without consent). Keep QML free of networking and audio (the plugin shares the shell process). Bump the manifest version to the release tag.
**Acceptance criteria:**
- CI runs `omarchy plugin validate` and `qmllint` against the mirror and fails on error (skipped with a clear message when the `omarchy` CLI is absent).
- Install from the mirror on a clean HOME fixture adds no bind until the Install button's confirm is accepted (test asserts `bindings.lua` unchanged before).
- A manifest test asserts id, kinds and entry points match the files; no entry point is outside the plugin folder.
- README states removal: `omarchy plugin remove io.github.duketopceo.wisp` plus `wispd uninstall`.
**Must not touch:** any QML behaviour; this unit only packages. **Stop:** do not open the marketplace submission issue without the owner's yes. The exact issue body is drafted in B18.

### B16. Omarchy tutor pack read from the user's own machine

**Goal:** "How do I change the theme / split a window / install an AUR app / see every binding" gets a spoken, pointed answer that is right for the installed Omarchy version. Nobody else teaches Omarchy itself.
**Requirements:** R3. **Dependencies:** none (extends B6 skills). **Tracker:** TLY-311.
**Files:** `wisp/skills_seed/omarchy/` (new), `wisp/skills.py`, `wisp/context.py`, `tests/test_omarchy_skills.py`.
**Approach:** Build the skill text at turn time from the user's own install, not a copied manual: the `omarchy` command list with its `# omarchy:` metadata headers, the user's `bindings.lua`, the current theme name, and the installed version. Teach the three habits a new user needs: Super+K keybindings, Super+Alt+Space menu, and "AUR recipes are unvetted, read the PKGBUILD first" before any `omarchy pkg aur install`. Point at the real menu item with label-first snapping. Never run a package command; offer it as a card the user confirms.
**Acceptance criteria:**
- With a fixture `omarchy` command tree and `bindings.lua`, the skill text names a rebound key from the fixture and not the default.
- A question about installing from the AUR produces the PKGBUILD-review line and no install call (audit log shows none).
- With no `omarchy` CLI present the skill is absent and the prompt is unchanged (golden).
- No Omarchy manual text is copied into the repo (test greps the seed for the manual's headings).

### B17. Demo kit: scripted clips and README hero

**Goal:** README and release pages carry real video, recorded from real turns, in a repeatable way. **OK** to post anywhere.
**Requirements:** R3. **Dependencies:** none. **Tracker:** TLY-312.
**Files:** `scripts/demo/` (new: `record.py`, `scripts/*.md`), `README.md`, `docs/MEDIA.md`, `scripts/ui/readme_media.py`.
**Approach:** The README says live recordings are "still to do". Write five 30-60 s scripts: draw-and-teach in a real app, circle-and-ask, dictate a reply, a background helper that finishes and says so, "what's my day cost". A harness starts `wf-recorder` and the mic, runs a scripted turn list against the real daemon, and writes MP4 plus a GIF poster and a one-line caption. Rough and honest beats polished (HeyClicky's founder posted a ten-minute recording and kept posting weekly). One recording, cut for each channel; channels differ in conversion (see growth table), so keep per-channel caption files but never post.
**Acceptance criteria:**
- `python3 scripts/demo/record.py --dry-run <script>` prints the planned keys, speech and capture commands and records nothing.
- Each script has a `proof` line the harness checks in the decision log (a demo that did not do what it claims fails).
- README embeds the hero as a repo asset under a size cap; `tests/test_readme_media.py` stays green.
- No secret, token or home path is visible: the harness runs the sensitive-window blanker (B9) and a path redactor over every frame list.

### B18. Omarchy ecosystem outreach pack (drafts only)

**Goal:** Everything needed to show up where Omarchy users already look, ready for the owner to send. **OK** for every send.
**Requirements:** R3. **Dependencies:** B15, B17. **Tracker:** TLY-313.
**Files:** `docs/outreach/omarchy.md` (new).
**Approach:** Draft, do not send: the marketplace submission issue body (repo URL, category `Productivity`, tags `ai`, `hyprland`, `education`), a short post for the Omarchy community (what it does in one sentence, the one-line install, the honest limits), an application note for the plugin competition and Rangers if open, a meetup lightning-talk outline, and a reply template for the existing voice-plugin threads that is generous, not a pitch. Record the facts each draft relies on with links.
**Acceptance criteria:**
- Every claim in a draft links to a repo file, test or measured number; no superlatives without a source.
- A docs test fails if a draft names a feature not on `master` (kept in a list the test reads).
- Nothing in the repo contains a webhook, token or send script for these channels.

### B19. Landing page with the literal promise and a real cost card

**Goal:** One page that says "Wisp is a voice teacher and doer for Omarchy that points at your screen" in the first screen, then the demo, one-line install, honest limits, and what a day costs. **OK** for hosting and any domain.
**Requirements:** R3. **Dependencies:** B17. **Tracker:** TLY-314.
**Files:** `site/` (new, static HTML and CSS, no framework, no third-party scripts), `.github/workflows/pages.yml`, `docs/COSTS.md`.
**Approach:** A farzaa/clicky issue found the "buddy" framing read before the job and asked for the literal line first. Lead with the job, keep the buddy as flavour. The cost card comes from the owner's own `wispd eval` and spend ledger (median per turn, per day for the owner's usage), stated as one person's numbers, with the model bill as the only cost. Include the comparison table from this plan with sources. No analytics, no trackers; link to the trust page (B25).
**Acceptance criteria:**
- The first screen contains the one-sentence job and the install line (test greps the built page).
- A test fails if the page loads any third-party host (a no-third-party-request check on the built HTML).
- Every number on the cost card names its source file and date.
- Lighthouse-style size budget: page under 300 KB with the hero poster.

### B20. Agent-installable runbook and one-paste prompt

**Goal:** A user pastes one prompt into their coding agent and wisp is installed, verified and explained. The original HeyClicky repo grew on this; O.M.A. ships the same.
**Requirements:** R3. **Dependencies:** none. **Tracker:** TLY-315.
**Files:** `docs/INSTALL.md`, `AGENTS.md`, `README.md`, `tests/test_docs_lint.py`.
**Approach:** Add a "Let your coding agent do it" section: a single prompt block, then a runbook the agent follows (`wispd doctor`, `wispd install --dry-run`, show the plan, ask before editing `bindings.lua`, `wispd onboard`, a verification turn). The runbook must say which steps need the user (keys, microphone permission, the first spoken test) and never ask the agent to read key files.
**Acceptance criteria:**
- Docs lint fails if the runbook names a `wispd` verb or flag that does not exist.
- The prompt contains no key, path outside `$HOME`, or `sudo`.
- A fixture "agent" script executes every runnable step in dry-run on a clean HOME and exits 0.

### B21. What can I ask here? Context chips for new users

**Goal:** A new user taps the talk key without speaking and sees three asks that fit the app in front of them, so "I forget it's there" and "I don't know what to ask" stop being reasons to quit.
**Requirements:** R3. **Dependencies:** B6 skills. **Tracker:** TLY-316.
**Files:** `wisp/skills.py`, `wisp/stage_capture.py`, `shell-plugin/Companion.qml`, `shell-plugin/components/` (new `AskChips.qml`), `wisp/settings_schema.py`.
**Approach:** Each app skill gets an `asks:` list (three short asks). A key tap shorter than the speech threshold, with no audio, shows chips beside the buddy for the focused app (or three generic ones); saying one runs it. The first week only, and only on a tap, never unprompted. A setting turns the chips off. No screenshot is taken for a tap with no speech.
**Acceptance criteria:**
- A tap with no audio shows chips for a fixture app and takes no screenshot (capture call count is zero).
- Saying a chip's text runs that ask through the normal route (replay fixture).
- Chips never appear without a tap; the setting off hides them.
- Golden snapshot in dark and light themes; reduced motion shows them without animation.

### B22. Selection, clipboard image and file as context

**Goal:** "What does this mean" uses the exact text the user selected, or the image they copied, or the file they just pointed at, with no OCR guess.
**Requirements:** R3. **Dependencies:** B9 document reader. **Tracker:** TLY-317.
**Files:** `wisp/context.py`, `wisp/stage_capture.py`, `wisp/docread.py`, `tests/test_context_selection.py`.
**Approach:** On key press read the Wayland primary selection (`wl-paste --primary`) and, only when the question says "this/that/copied/selected", the clipboard text or image; send selected text as quoted context with its length, and a clipboard image as an attachment. A file path in the clipboard or selection goes to the B9 reader with its protected-folder rule. Strip control characters, cap size, and mark the block as untrusted data so it cannot give instructions. Nothing is read between presses.
**Acceptance criteria:**
- Fixture selection "ERR_CONNECTION_RESET" reaches the prompt as a quoted block and is the first thing the answer cites.
- With no selection the prompt is byte-identical to today (golden).
- Selection text that says "ignore previous instructions" is delivered inside the data block and does not change routing (replay fixture).
- No clipboard or selection read happens when the daemon is idle (call log asserts zero).

### B23. Multilingual turns

**Goal:** Ask in Spanish, get a spoken Spanish answer; dictate in German. HeyClicky added 70+ languages because users came from 100+ countries.
**Requirements:** R3. **Dependencies:** none. **Tracker:** TLY-318.
**Files:** `wisp/stage_capture.py`, `wisp/vocab.py`, `wisp/speech.py`, `wisp/dictate.py`, `wisp/config.py`, `docs/CONFIG.md`, `tests/fixtures/turns/lang/`.
**Approach:** Keep the hosted multilingual STT model, pass the detected or configured language through, and put one rule in the answer prompt: reply in the user's language unless asked otherwise. Choose a TTS voice per language when the provider offers one; fall back to the default voice and say so once. Vocabulary priming is per language. The local `small.en` default stays English-only and the config says so. Dictation inserts in the spoken language and never translates.
**Acceptance criteria:**
- Five fixtures (es, de, pt-BR, ja, fr): the transcript keeps the language, the answer prompt carries the reply rule, and the TTS call gets the matching voice or the stated fallback.
- English behaviour is byte-identical (golden).
- A language the STT provider cannot return ends with a spoken reason, not a hang.
- `wispd eval` accepts a `lang` field on labelled turns and reports per-language first-time-correct.

### B24. Dictation safety net

**Goal:** Dictated words are never lost to a failed insert, a call, or a long ramble.
**Requirements:** R3. **Dependencies:** none. **Tracker:** TLY-319.
**Files:** `wisp/dictate.py`, `wisp/bgwriter.py`, `wispd` (`dictate --history`), `shell-plugin/Panel.qml`, `tests/test_dictate.py`.
**Approach:** Append every finished dictation to a local, size- and age-bounded history (default 100 entries, 7 days; off switch; wiped by one command). On a failed or uncertain insert keep the text, say so, and offer "copy it" and "try again". Save sessions longer than ten minutes in chunks so an interruption keeps what was said. Add faithful-cleanup fixtures: cleanup never adds words that were not spoken. History never leaves the machine and never enters a prompt.
**Acceptance criteria:**
- A fixture where the insert tool fails leaves the text in history and the clipboard untouched; "try again" inserts it.
- A 12-minute scripted session killed at minute 11 keeps at least the first 10 minutes.
- Cleanup fixtures with a near-silent tap insert nothing.
- The history file mode is 0600 and the retention bound is enforced (test).

### B25. Trust page generated from code, and a log hygiene gate

**Goal:** "What leaves your machine" is a generated, tested page, not README prose. HeyClicky's trust page names its two outside vendors and nothing else; wisp can show every host.
**Requirements:** R5. **Dependencies:** none. **Tracker:** TLY-320.
**Files:** `docs/TRUST.md` (generated), `scripts/gen_trust.py`, `tests/test_trust.py`, `tests/test_log_hygiene.py`.
**Approach:** Scan the code and `config` defaults for every outbound host and the payload class it gets (audio, screenshot, text, none), who holds the key, retention the user controls, and what is never sent (keys, home paths, clipboard unless asked). The test regenerates the page and fails on diff, and fails when a new host appears with no entry. A second test drives a turn with sentinel secrets and transcripts and asserts none appears in any log, trace or error report (an open issue on the original repo reported transcripts and token fragments in logs).
**Acceptance criteria:**
- Adding a hard-coded URL for a new host makes `tests.test_trust` fail with the host name.
- Sentinel `sk-test-SENTINEL` and a sentinel transcript are absent from `trace.jsonl`, `decisions.jsonl`, the error report queue and stderr after a replay turn (debug logging off).
- With debug logging on, keys are still masked.
- The page links from the README and the landing page (B19).

### B26. What's new card, credited changelog and `wispd bugreport`

**Goal:** Users see what changed, reporters get credit, and a bug report carries what a maintainer needs without the user pasting logs by hand.
**Requirements:** R3. **Dependencies:** B9 update. **Tracker:** TLY-321.
**Files:** `CHANGELOG.md` (new), `wisp/update.py`, `wispd` (`bugreport`, `whatsnew`), `shell-plugin/Panel.qml`, `wisp/redact.py`.
**Approach:** After `wispd update` records a new version, the Panel shows a one-time card with the three headline lines and a link. The changelog format is "what changed for you" lines with the reporter's handle when they agree, and a count only when it comes from a real source. `wispd bugreport` writes one markdown file: version, deployed commit, `wispd health`, the last N typed errors, trace kinds (not content), config with values masked, and a blank "what happened" section. The user reads it, then opens a GitHub issue themselves. Nothing is sent.
**Acceptance criteria:**
- Sentinel secrets, transcripts, window titles and home paths are absent from a generated report (test).
- `wispd bugreport --dry-run` prints the file list and size and writes nothing.
- The what's-new card shows once per version and not on first install.
- Docs lint passes; the CHANGELOG has the last five releases.

### B27. Share a lesson, skill or helper safely

**Goal:** One file or link turns a good setup into someone else's starting point. This is the community loop HeyClicky's shared skill pages and an outside prototype both point at.
**Requirements:** R3, R5. **Dependencies:** B10, B12. **Tracker:** TLY-322.
**Files:** `wisp/lessons.py`, `wisp/skills.py`, `wisp/agent_home.py`, `wispd` (`export`, `import`), `tests/test_share.py`.
**Approach:** `wispd export lesson|skill|helper <name>` writes one JSON or markdown bundle with a content hash and no secrets, no paths, no memory. `wispd import <file|url>` shows the whole text, the permissions it asks for, and the hash, then waits for a yes; imported text is treated as untrusted (it cannot add tools, change confirm policy, or run on import). A helper's schedule is imported paused.
**Acceptance criteria:**
- Export of a fixture helper contains no home path, key, or memory text (test).
- Import without a yes writes nothing; a bundle that tries to widen tool tier is rejected with the reason.
- Importing the same bundle twice changes nothing the second time (idempotent, hash match).
- A routine in the bundle arrives paused and says so.

### B28. Blank or protected capture detection

**Goal:** When a screenshot is black, empty or blocked, wisp says so and recovers instead of answering blind.
**Requirements:** R3, claim 1. **Dependencies:** none. **Tracker:** TLY-323.
**Files:** `wisp/stage_capture.py`, `wisp/context.py`, `tests/test_capture_blank.py`.
**Approach:** After capture, test for an all-black or single-colour frame (cheap histogram). On a blank frame retry once with window capture, then fall back to accessibility text for the focused window, and tell the user in one sentence what happened ("that window blocks screenshots; I'm reading its text instead"). Never claim to see what it did not.
**Acceptance criteria:**
- A black fixture frame triggers the retry and then the fallback; the spoken line names the cause.
- A normal dark theme frame is not flagged (fixture with a real dark UI).
- With no fallback available the turn ends with an honest "I can't see that window" and no model call about its content.

### B29. One instance and an idle resource gate

**Goal:** A second `wispd` never starts, and idle cost is a number CI watches.
**Requirements:** R4. **Dependencies:** B1. **Tracker:** TLY-324.
**Files:** `wispd`, `wisp/health.py`, `tests/test_single_instance.py`, `tests/test_idle_budget.py`, `wisp/budgets.json`.
**Approach:** Take an exclusive lock on the runtime socket at start; a second start prints which pid holds it and exits non-zero. Add `idle_cpu_pct` and `idle_rss_mb` to `budgets.json`, measure over a short idle window in `wispd health` and in a CI smoke with the overlay offscreen, and fail on regression beyond a stated margin.
**Acceptance criteria:**
- Starting a second daemon exits non-zero and does not touch the first's socket (test).
- No answer is spoken twice when the second start is attempted mid-turn (replay).
- The idle test fails when a spin-loop fixture is injected and passes on `master`.
- No budget is loosened.

### B30. Wisp knows itself

**Goal:** "What model are you", "what did I spend today", "what version is this", "copy that", "say that again", "what went wrong" are answered from local state, truthfully.
**Requirements:** R3, claim 1 and 4. **Dependencies:** B8. **Tracker:** TLY-325.
**Files:** `wisp/stage_route.py`, `wisp/ledger.py`, `wisp/health.py`, `wisp/copy.py`, `tests/test_self_answers.py`.
**Approach:** A small deterministic route before the model: model names come from config and the last turn's trace, spend from the ledger (today and this week), version and deployed commit from `deploy.py`, "copy that" puts the last answer on the clipboard, "say that again" replays it, "what went wrong" reads the last typed error in plain words. No model call for these.
**Acceptance criteria:**
- Each phrase resolves with zero brain calls (call log) and the numbers match the ledger fixture.
- "What model are you" names the configured models and never a hidden one.
- Phrases inside a longer question ("explain what version control is") are not captured.

### B31. Growth scoreboard from public signals, and a retention loop

**Goal:** Know whether wisp is succeeding the way the HeyClicky founder measures it (downloads and day-five use), without telemetry. **OK** for any outreach or new community channel.
**Requirements:** R5. **Dependencies:** none. **Tracker:** TLY-326.
**Files:** `scripts/growth_snapshot.py` (new), tallyline roadmap panel, `wisp/telemetry.py` (local digest only), `docs/GROWTH.md`.
**Approach:** Daily snapshot of public numbers through the GitHub API: stars, forks, release asset downloads, issue and discussion counts, traffic (clones, views) when the token allows. Locally, an opt-in weekly recap card ("you used wisp 5 days, 42 turns, $0.83") built from the existing local digest and shown only to the user, never sent. A plan, not an action: a one-page guide for the owner on talking to the first 100 daily users (HeyClicky's founder did this one by one) and where to ask (GitHub Discussions first).
**Acceptance criteria:**
- The snapshot script runs offline against a fixture and writes a dated JSON; it prints no token.
- The recap card shows only local numbers and has an off switch; a test asserts no network call in its code path.
- Nothing posts, emails or opens a community channel.

### B32. Starter pack from four questions

**Goal:** After the tour, four spoken questions seed the profile and offer three starter helpers or routines that ask before they repeat.
**Requirements:** R3. **Dependencies:** B10, B12. **Tracker:** TLY-327.
**Files:** `wisp/tour.py`, `wisp/memory.py`, `wisp/routines.py`, `wisp/agent_home.py`, `tests/test_starter_pack.py`.
**Approach:** Ask what they do, what apps they live in, what annoys them, how they like answers; write the profile memory; propose three starters that finish in different ways (a thing to use, a straight answer, work done in an app). A starter that repeats says "this will repeat, keep it going?" and waits for yes (HeyClicky's rule). Skippable by voice; replayable.
**Acceptance criteria:**
- A scripted interview writes the profile and offers exactly three starters with different outcome kinds.
- A routine starter is not scheduled until the yes (scheduler state asserted).
- "Skip" at any point ends cleanly and offers it again next run.

### B33. Hands-free mode and optional local wake word

**Goal:** Opt-in hands-free dictation by double-tap, and an opt-in local wake word, with echo cancel so wisp does not hear itself. **OK**: this changes the claim "it only hears you when you hold the key".
**Requirements:** R3. **Dependencies:** B8. **Tracker:** TLY-328.
**Files:** `wisp/fastkey.py`, `wisp/stage_capture.py`, `wisp/speech.py`, `wispd` (`install --echo-cancel`), `docs/PRIVACY.md`.
**Approach:** Hands-free toggles on a double-tap of the hold key (one tap starts, the next stops). The wake word runs a small local detector, listening only while enabled, with a visible mic state in the bar at all times and a hard off in one keypress. It is off by default, refuses to enable on open speakers without echo cancel, and never takes a screenshot until the wake word fires. Jarvis, O.M.A. and the commercial "Always On" mode all ship it, so the demand is real; the owner decides whether the trust line moves.
**Acceptance criteria:**
- Default config has the wake word off; enabling it prints exactly what is listened to and where audio goes (nowhere outside the machine until it fires).
- With the detector enabled, a recording of wisp's own TTS does not trigger it (fixture).
- The bar shows the mic-open state while the detector runs (snapshot).
- Hold-to-talk behaviour is byte-identical with both off.

### B34. Lower the key barrier: capped trial or CLI-backed deep brain

**Goal:** A first run with no keys. Two options, both gated on the owner. **OK** for either.
**Requirements:** R3, claim 4. **Dependencies:** B25. **Tracker:** TLY-329.
**Files:** `wisp/brain.py`, `wisp/keys.py`, `wisp/onboard.py`, `docs/COSTS.md`.
**Approach:** *Option A, capped hosted trial:* a proxy the owner runs, a per-install token, a hard daily and total cap, rate limits, and a clear "this is a trial, add your own keys to continue" line. It costs money and invites abuse. Peeky offers this (email gate for more free use). *Option B, subscription-backed deep brain:* let the user's own coding-agent CLI (already installed on Omarchy, which ships several as default agents) answer deep turns the way O.M.A.-style plugins split a fast voice from a slower agent brain; sign-in stays in that CLI and wisp never reads its credentials. This depends on each provider's terms for non-interactive use, so it needs a read of those terms first. Neither option may weaken Phase 8's scrubbed environment.
**Acceptance criteria:**
- Not started until the owner picks a path. When started: Option A has a cap test that refuses the (N+1)th call and a test that the token reveals no real key; Option B has a test that no credential file is read and that a missing CLI produces the existing missing-key message.
- Either option leaves the key-based path unchanged (golden).

### Needs the owner's OK (second scrub)

| Item | Why it needs OK | Unit |
|---|---|---|
| Submit wisp to the Omarchy Plugin Marketplace (opens an issue on `omacom/omarchy-plugin-marketplace`) | Public post under the owner's name; a listing is not a security review but is a public claim | B15, B18 |
| Post demo clips on X, Instagram, YouTube, TikTok | Public posting; channel choice is the owner's. The measured order from HeyClicky is Instagram for reach, YouTube for conversion, X for neither | B17 |
| Enter the Omarchy plugin competition, apply to Rangers, speak at a meetup, reply on existing voice-plugin threads | Outreach to other people and projects | B18 |
| Host a landing page and buy any domain | Spends money or publishes under a new name; GitHub Pages is free | B19 |
| Open GitHub Discussions or any chat community; talk to early users one by one | Opens a channel that people will expect the owner to answer | B31 |
| Wake word and hands-free | Changes a user-facing privacy promise | B33 |
| A hosted trial proxy | Ongoing cost and abuse risk | B34 A |
| Using a coding-agent CLI subscription as the deep brain | Depends on provider terms; touches a credential boundary | B34 B |
| Any paid tier, referral payouts, student pricing | Wisp is free and AGPL; HeyClicky's pricing is recorded as context only, nothing is proposed | none |

---

## Verification Contract

| Gate | Command | Applies to |
|---|---|---|
| Compile | `python3 -m py_compile wispd wisp/*.py wisp/tools/*.py tests/*.py` | all |
| Unit suite | `python3 -m unittest discover -s tests` with no API keys in the environment | all |
| Docs lint | `python3 -m unittest tests.test_docs_lint` | B1, B9, B12, B15, B17, B18, B20, B25, B26 |
| QML goldens | `python3 scripts/ui/snap.py` then `tests/test_snap.py` | B4, B5, B7 |
| Replay | `python3 -m unittest tests.test_turn_replay` | B1, B2, B6, B8, B21, B22, B23, B30 |
| Eval | `wispd eval` tally recorded in the PR body | B2, B3 |

## Definition of Done

- Each landed unit passes its acceptance criteria and every gate it lists.
- Each of the six *better* claims still holds (checked in review).
- The matrix rows a unit closes are updated in the unit's PR, with the evidence class kept.
- No unit adds telemetry, a local model server, or competitor text or code.
- A unit marked **OK** ships its code and drafts but performs no external step (post, submit, email, spend) until the owner says yes in this tracker.
- The v1 gate (`wispd eval` at the owner's rate over 50 labelled turns) is met before B10 onward ship.

## Sources

- HeyClicky changelog v1.0.10–v1.1.3: `https://www.heyclicky.com/changelog`; trust page `https://www.heyclicky.com/trust`; reviews of 2026-10-24/25 (GetQuids, Creators Toolbox, rahmanbuilds).
- HeyClicky 1.1.1 macOS bundle, read-only static inspection by the owner's machine (Info.plist, resource files, helper and framework names).
- `Raynan00/clacky` v0.2.0 and `docs/research/2026-10-25-clacky-teardown.md`; owner's port notes `2026-10-26-port-research.md`.
- `Bitshank-2338/clicky-windows` `6c6216b` (`RELEASE-NOTES-1.6.md`, `drive.py`, `drawing.py`, `response_blocks.py`).
- `danielbusnz/Peeky` `5950340`, `unn-Known1/clickyX` `988568a`, `tornikegomareli/clicky-desktop`, `pango07/flicky`, `stevenvo780/clawbar` READMEs.
- `jasonkneen/openclicky` README and AGENTS.md (macOS only, not a Windows or Linux rival).
- In-repo: `docs/plans/2026-10-25-0151`, `2026-10-25-0215`, `2026-10-25-1625`, `2026-10-26-0031`, `2026-10-26-2149`; `docs/research/heyclicky-features.md`; `wisp/budgets.json`.

- Second scrub (2026-10-28): `https://www.heyclicky.com/` (home, pricing, FAQ, trust, careers, changelog v1.0 to v1.1.3); `farzaa/clicky` README, issues #7, #13, #19, #21, #26, #27, #44, #59, #62, #63, #83, #125 and repo metadata; `shahmerrkhan/heyclicky-linux`, `syedahmad0786/OpenClicky`, `Mohit-Malviya-AI-PM/share-a-clicky`, `heyclicky/clicky-releases-windows`, `danielbusnz-lgtm/Aegis` (Peeky) READMEs.
- HeyClicky growth: YC Startup Podcast summary `https://finance.biggo.com/news/5ebe255e36934bf1`; interview transcript `https://exa.ai/library/podcast/704cv1ktbwq/episode/8wdvsg280l1`; `https://arenamag.com/articles/a-time-for-tinkerers`; `https://www.donotchurn.com/p/ai-buddy-that-lives-next-to-your`; Reddit `r/macapps/comments/1t45qs6`, `r/macapps/comments/1srzk5a`, `r/heyclicky_/comments/1wn2if0`.
- Omarchy: news `https://tryomarchy.org/site/news`; releases `https://omarchylinux.org/releases/` and v4.0.3 notes; `https://plugins.omarchy.org/publish.html` and `/develop.html`; `https://github.com/omacom/omarchy-plugin-marketplace` and its `SUBMISSION.md`; `omarchy plugin add` reference `https://omarchylinux.org/reference/commands/omarchy-plugin-add/`.
- Omarchy voice plugins: `wombatoperator/omarchy-voice`, `Atzingen/hey-jarvis`, `baranskyi/omavoice`, `komagata/oma`, `PSthelyBlog/omarchy-hermes-companion` (READMEs only; nothing was run).
- Not recorded: no key, token or credential seen in any source was copied into this repository.
