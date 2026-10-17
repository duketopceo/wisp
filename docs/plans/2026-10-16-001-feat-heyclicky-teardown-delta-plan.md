---
title: HeyClicky teardown v2 and wisp delta plan (walkthroughs, app skills, routines, grounding)
type: feat
date: 2026-10-16
depends_on: docs/plans/2026-10-09-001-feat-autonomous-agent-parity-plan.md
---

# HeyClicky teardown v2 → wisp delta plan

## Summary

The Oct 9 parity plan (U1–U8) covered the agent loop, background delivery,
autonomy tiers and dictation. PRs #116 and #118 landed the loop and the
act-router mode. This plan covers what HeyClicky does that wisp still does
not: step-by-step walkthroughs that advance on the user's real click,
draw-on-screen targets, two-stage element grounding, scheduled routines, suggestion etiquette, and a fast/deep model
split on OpenRouter, plus an app-keyed skill library (a feature HeyClicky
removed in v1.0.49; kept as wisp's own choice). It also records the architecture teardown of the MIT
predecessor so the borrowed mechanics have a source.

Unit IDs here are `H1`–`H9`. They never renumber. The Oct 9 plan keeps
`U1`–`U8`; roadmap IDs stay `W*`.

## Provenance

- **source-assisted**: `farzaa/clicky` (MIT), cloned 2026-10-16. Files cited
  by path. Source: https://github.com/farzaa/clicky
- **documentation-based**: heyclicky.com changelog and trust page.
  https://www.heyclicky.com/changelog, https://www.heyclicky.com/trust
- **in-tree**: wisp `master` at #122, read directly.
- Not done: no decompilation of the commercial HeyClicky binary. Its runtime
  prompt is already summarized in `docs/research/heyclicky-features.md`.

Confidence is marked per claim: high / moderate / low.

## Research Findings

### A. Architecture of the predecessor (source-assisted, high)

- Menu-bar-only app (`LSUIElement=true`), SwiftUI with AppKit bridging for the
  panel and a full-screen, non-activating `NSPanel` overlay that joins all
  Spaces and never steals focus (`AGENTS.md` → Key Architecture Decisions).
- Push-to-talk is a listen-only `CGEvent` tap for `ctrl+option`. The AppKit
  global monitor was dropped because modifier-only chords were unreliable.
- STT: AssemblyAI realtime streaming (`u3-rt-pro`) over one shared,
  long-lived `URLSession`; OpenAI and Apple Speech as fallbacks.
- LLM: Claude Sonnet default, Opus optional, SSE streaming through a
  Cloudflare Worker proxy. The worker exposes exactly three routes:
  `/chat`, `/tts`, `/transcribe-token` (`worker/src/index.ts:28-36`).
  API keys never ship in the app.
- TTS: ElevenLabs `eleven_flash_v2_5` through the same proxy.
- Screen capture: ScreenCaptureKit, all monitors at press time.
- Pointing protocol: the model appends `[POINT:x,y:label]` or
  `[POINT:x,y:label:screenN]` after the spoken text, or `[POINT:none]`
  (`CompanionManager.swift:568-576`). Coordinates are screenshot pixels.
- Second-stage grounding: `ElementLocationDetector.swift` calls the Computer
  Use tool with the screenshot resized to the Anthropic-recommended
  resolution whose aspect ratio is closest to the display, defaulting to
  1280×800, then clamps and scales the returned point back to display
  points and flips the Y origin (`ElementLocationDetector.swift:100-150`).
- Transient cursor mode: overlay fades in for record → response → TTS →
  pointing, then fades out.
- Analytics: PostHog, including a "response included a POINT tag" event
  (`ClickyAnalytics.swift:98`).

### B. What the commercial product added (documentation-based, moderate)

From the changelog, in order of product weight:

1. **Walkthroughs.** Spoken step, drawn target, wait for the user's click,
   detect it, advance. Up to 15 steps with a running done-log. Waits for
   slow pages; asks what the user already has; does not repeat a failed step.
2. **Draw on screen.** Target rings, arrows, highlights in a hand-drawn
   style. Highlights fade in about two seconds; drawings clear when speech
   stops. The user can also draw a region to scope a question.
3. **App skills (former feature).** HeyClicky once injected skill files for
   about 89 apps with browser-site matching, plus roughly 100 community
   skills. Its changelog (v1.0.49) says Skills were paused and removed "for
   now", so this is history, not a current competitor feature. H4 stays as
   wisp's own design choice.
4. **Named agents ("Clickys") and routines.** Persistent personas with their
   own memory, chat and file folder. Routines are scheduled runs; results
   land quietly with an unread dot; missed runs wait; pause after three
   failures; the first suggested routine asks for explicit opt-in.
5. **Suggestions.** Mined from connected apps, not screen watching. One card
   at a time; "Do it / next / Adjust"; remembers declines; morning greeting
   after 6am; holds during calls, screen share, Focus; backs off after three
   ignored days. Proactive screen tracking shipped and was removed over
   privacy (v1.0.46).
6. **Integrations via MCP** (Notion, Gmail, Linear, Slack, Google Workspace)
   and native Notes/Calendar/Reminders; multiple accounts per app.
7. **Permission model.** "Allow once / Always / Not now" per conversation,
   voice-answerable; hard stop before purchases, sends, deletes.
8. **Dictation.** About 450 ms streaming insert; auto-learned dictionary from
   corrections within 20 s; newline collapse in terminals.
9. **Memory.** `PROFILE.md` (stable) and `VOLATILE.md` (recent, decaying).
10. **Model split.** A fast lane for talk and a deep lane for agents.
11. **Trust posture.** Cloud-only processing; screenshots not stored.

### C. What wisp already has (in-tree, high)

| HeyClicky mechanic | wisp today | Gap |
|---|---|---|
| `[POINT]` tag protocol | `wisp/points.py` extracts tags and maps grim composite px → logical per monitor | none |
| Element grounding | `wisp/grounding.py` chain: a11y → OCR/template → vision-LLM fallback | no second-stage pointing call at aspect-matched resolution |
| Background delivery | `wisp/delivery.py`, `wisp/pointer.py` (cua first) | none |
| Skills | `wisp/skills.py` Hermes SKILL.md; 5 seeds | no app-keyed lookup; no site matching; tiny library |
| Named agents | `wisp/agents.py` (ori-opencode tasks) | no schedule, no quiet landing, no failure pause |
| Suggestions | `wisp/suggest.py` miner | no etiquette policy (hold, backoff, one-at-a-time, decline memory) |
| Memory | `wisp/memory.py` MEMORY.md + USER.md | no decaying volatile layer |
| Permission tiers | 4 tiers + autonomy tiers (#116) | per-conversation grant exists? verify in H7 |
| Dictation dictionary | `wisp/vocab.py` | verify correction-window learning |
| Walkthroughs | none (`rg walkthrough` = 0 hits) | whole feature |
| Draw on screen | ghost cursor only | rings/arrows/highlights, user-drawn regions |
| Fast/deep split | Jev router + brains | no explicit latency-budgeted talk lane |

### D. Verdicts

- HeyClicky's moat is polish plus a cloud key proxy, not architecture
  (high). wisp holds a single-user OpenRouter key locally; no proxy needed.
- The one mechanic worth copying exactly is the walkthrough state machine.
  It converts a pointing assistant into a tutor and is what drove adoption
  (moderate; inferred from changelog emphasis).
- Do not copy: notch UI, PostHog, ElevenLabs dependency, realtime voice API.
  OpenRouter has no realtime audio session; barge-in stays local (high).
- Counterargument to this whole plan: wisp's v1.0 gate (W34 soak, clean-box
  install) is still open. Nine more units widen the surface before the
  existing one is proven. Mitigation: H1–H3 are gated behind W34 soak
  evidence; H4–H9 can proceed in parallel because they are policy and data,
  not new interaction paths.

## Key Technical Decisions

- **D1.** Walkthrough click detection uses the Hyprland socket2 events plus
  the cua `get_window_state` diff, not a global input hook. Reason: no
  libinput root access, and a focus/element change is the signal that
  matters. Fallback: ask "done?" by voice after 20 s without a detected
  change.
- **D2.** Second-stage grounding runs only when the talk model emits
  `[POINT:none]` with a located-element intent, or when the a11y provider
  returns nothing. The call goes to a pointing-capable VLM on OpenRouter
  (Qwen3-VL class) with the screenshot resized to one of 1024×768,
  1280×800, 1366×768 by aspect match, mirroring `ElementLocationDetector`.
  Confidence that OpenRouter exposes a sufficient pointing model: moderate;
  H3 starts with a 50-target bench.
- **D3.** App skills are keyed by `activewindow.class` and, for browsers,
  by URL host from the CDP tab. Seeds live in `wisp/skills_seed/apps/`.
  Community skills reuse the existing SKILL.md frontmatter; no new format.
- **D4.** Routines are systemd user timers that invoke `wispd agents run
  <id>`; the daemon owns the quiet-landing and failure-pause policy. No
  in-process scheduler.
- **D5.** Suggestion etiquette is a pure policy function over
  (time, call/screen-share state, last three decisions, dismissal streak).
  Call state comes from PipeWire node state and Hyprland fullscreen.
- **D6.** Memory gains `VOLATILE.md` with per-line TTL (default 7 days),
  compacted by the existing memory tool. PROFILE semantics stay in USER.md.
- **D7.** Model lanes: `talk` lane budget 1.5 s to first token on a cheap
  VLM; `deep` lane on the act loop's current model. Lane choice is a Jev
  output, not a user setting.
- **D8.** License: ported prompt fragments and the resolution table cite
  `farzaa/clicky` (MIT) in-file. wisp stays AGPL-3.0-only.

## Implementation Units

### H1. Walkthrough state machine
- **Goal:** "how do I X in this app" becomes a stepwise tutor that
  advances on the user's action.
- **Files:** `wisp/walkthrough.py` (new: `Step`, `Walkthrough`, done-log,
  max 15 steps), `wisp/stage_execute.py` (route `walkthrough`),
  `wisp/hypr.py` (socket2 event subscription), `wisp/cua.py`
  (`get_window_state` diff helper), `shell-plugin/components/
  OverlayLayer.qml` (step counter chip), `wisp/copy.py` (spoken templates).
- **Behavior:** each step = spoken text + one `[POINT]`; wait for a focus
  or element-tree change; re-capture; verify the step by a cheap talk-lane
  call; append to done-log; never re-issue a step in the done-log; after
  20 s with no change ask "done, or stuck?"; load-wait when window title
  contains loading markers or the tree is empty.
- **Test scenarios:** fake Hyprland event stream drives a 3-step script;
  a failed step is not repeated; step 16 refuses with a spoken summary;
  Esc cancels and clears overlay; no-change path asks instead of looping.
- **Verification:** 10 live walkthroughs in Chromium settings and GIMP
  menus, each labeled; ≥7/10 complete without a manual nudge.

### H2. Draw-on-screen overlay
- **Goal:** rings, arrows and highlights in a hand-drawn style, timed to
  speech; user-drawn regions as question scope.
- **Files:** `shell-plugin/components/DrawLayer.qml` (new, Canvas with
  jittered strokes), `wisp/points.py` (extend tags: `[RING:x,y,r]`,
  `[ARROW:x1,y1,x2,y2]`, `[HL:x,y,w,h]`), `wisp/stage_speak.py`
  (clear-on-speech-end), `wisp/stage_capture.py` (region attach),
  `docs/IPC_CONTRACT.md`.
- **Behavior:** highlights fade after 2 s; rings/arrows persist until TTS
  ends or Esc; nothing persists across turns; a held modifier plus drag
  captures a region that is cropped and attached to the next capture.
- **Test scenarios:** tag parser round-trips all four shapes per monitor
  scale; overlay clears on speech end and on cancel; region crop matches
  logical coordinates on a 2-monitor fixture with mixed scale.
- **Verification:** screenshot goldens for each shape at 1x and 2x.

### H3. Two-stage element grounding
- **Goal:** when the talk model cannot point, a pointing VLM does.
- **Files:** `wisp/grounding.py` (new provider `vlm_point`), `wisp/brain.py`
  (resolution table and lane), `wisp/config.py` (`[grounding] point_model`),
  `tests/test_grounding_point.py`, `docs/CUA.md`.
- **Behavior:** trigger rules per D2; resize by aspect match; clamp and
  scale back; fall through to `guide` delivery when confidence is below
  threshold.
- **Test scenarios:** resolution picker chooses 1366×768 for 16:9,
  1280×800 for 16:10, 1024×768 for 4:3; off-range coordinates clamp;
  provider order unchanged when a11y hits.
- **Verification:** 50-target bench (`wisp/probes_cua.py`) across 5 apps;
  report hit-rate per provider; adopt only if `vlm_point` beats the current
  vision fallback by ≥15 points.

### H4. App-keyed skill library
- **Goal:** the right app notes are in context without the user asking.
- **Files:** `wisp/skills.py` (lookup by class/host, ranking), `wisp/
  skills_seed/apps/*/SKILL.md` (20 seeds: Hyprland, Waybar, Chromium,
  Firefox, neovim, VS Code, LibreOffice Writer/Calc, GIMP, Inkscape,
  Obsidian, Spotify, Thunderbird, Signal, Steam, Nautilus, kitty/alacritty,
  pavucontrol, Omarchy menu, 1Password), `wisp/stage_ctx.py` (inject index
  entry plus matched body), `wisp/cli/core.py` (`wispd skills match`).
- **Behavior:** at most one app skill body per turn; browser host match
  beats class match; community skills install from a directory or git URL
  into `~/.local/share/wisp/skills/`.
- **Test scenarios:** class and host matching with precedence; token
  budget respected; unknown app injects nothing; CLI prints the match.
- **Verification:** seeds reviewed for accuracy on a live Omarchy box.

### H5. Routines
- **Goal:** "check this every few hours" produces a scheduled agent run
  with quiet results.
- **Files:** `wisp/routines.py` (new: create/list/pause; writes systemd
  user timer and service units), `wisp/agents.py` (run id linkage,
  failure counter), `shell-plugin/components/AgentsTab.qml` (unread dot),
  `wisp/cli/agents.py`, `docs/CONFIG.md`.
- **Behavior:** explicit opt-in prompt on first recurrence; `Persistent=true`
  so missed runs fire once, not pile up; after 3 consecutive failures the
  timer is paused and the user is told once; results never speak unless
  asked.
- **Test scenarios:** unit files generated and validated with
  `systemd-analyze verify`; failure pause after 3; missed-run coalescing;
  opt-in refusal creates nothing.
- **Verification:** one daily routine runs for 3 days on the soak box.

### H6. Suggestion etiquette policy
- **Goal:** suggestions arrive when welcome and stop when ignored.
- **Files:** `wisp/suggest_policy.py` (new pure function), `wisp/suggest.py`
  (call policy, persist decisions and reasons), `wisp/sense.py` (call and
  screen-share detection via PipeWire and Hyprland fullscreen),
  `tests/test_suggest_policy.py`.
- **Behavior:** one card at a time; not before 6am local; hold during
  calls, screen share or fullscreen; "Adjust" opens a one-turn voice edit;
  after 3 consecutive dismissed days, pause for 7 days; decline reasons feed
  the next batch prompt.
- **Test scenarios:** table-driven policy cases (time, state, streak);
  decline reason appears in the next batch prompt; pause and resume dates.
- **Verification:** 7-day log review on the soak box shows no card during
  a recorded call.

### H7. Per-conversation permission grants
- **Goal:** match "Allow once / Always / Not now" semantics exactly.
- **Files:** `wisp/confirm.py`, `wisp/policy.py`, `wisp/voicepick.py`,
  `shell-plugin/components/ConfirmCard.qml`, `docs/CUA.md`.
- **Behavior:** first computer-use in a conversation asks once; "Always"
  persists per app class; purchases, sends, deletes and payments always
  stop regardless of grant; all three answers accepted by voice.
- **Test scenarios:** grant scoping by conversation and app class;
  hard-stop list cannot be bypassed by "Always"; voice answer maps.
- **Verification:** audit log shows one prompt per conversation in a
  5-step task.

### H8. Volatile memory layer
- **Goal:** recent context decays instead of polluting USER.md.
- **Files:** `wisp/memory.py` (VOLATILE.md with `until:` per line,
  compaction), `wisp/stage_ctx.py`, `tests/test_memory_volatile.py`.
- **Test scenarios:** expired lines drop on load; budget cap enforced;
  memory tool can promote a volatile line to MEMORY.md.
- **Verification:** 7-day soak shows VOLATILE.md stays under budget.

### H9. Talk and deep lanes on OpenRouter
- **Goal:** spoken answers start within 1.5 s; agents keep the strong model.
- **Files:** `wisp/brain.py` (lane config), `wisp/route.py` (Jev emits
  lane), `wisp/ledger.py` (per-lane spend), `wisp/budgets.json`,
  `docs/baselines/` (latency baseline, closes W2 `needs_live_baseline`).
- **Behavior:** talk lane default to a cheap vision model with streaming;
  deep lane unchanged; lane and model logged per turn; barge-in cancels
  TTS and the in-flight stream.
- **Test scenarios:** lane selection table; ledger splits by lane; cancel
  token stops both TTS and stream.
- **Verification:** 20-turn live baseline, p50 first-audio ≤1.5 s.

## Scope Boundaries

- No cloud proxy, no account system, no telemetry service.
- No macOS notch UI; macOS parity stays in the existing U7 adapter plan.
- No realtime voice API; TTS stays espeak/say or the configured provider.
- No screen-watching proactive mode. Suggestions use activity windows and
  connected sources only, matching HeyClicky's post-v1.0.46 posture.
- No new agent runtime; routines reuse `agents.py`.

## Risks

- H1 click detection may miss web clicks that change no window state.
  Mitigation: CDP `Page.frameNavigated` and DOM mutation count for
  browser targets.
- H3 depends on an OpenRouter pointing model. If the bench fails, keep the
  current chain and close H3 as "not adopted" with the numbers.
- Surface growth before the v1.0 gate. H1–H3 wait for W34 soak evidence.
- Overlay drawing on multi-scale monitors has coordinate pitfalls already
  seen in `points.py`. Goldens at both scales are mandatory.

## Sources

- farzaa/clicky (MIT): https://github.com/farzaa/clicky
- HeyClicky changelog: https://www.heyclicky.com/changelog
- HeyClicky trust page: https://www.heyclicky.com/trust
- Prior in-tree research: `docs/research/heyclicky-features.md`
- Prior plan: `docs/plans/2026-10-09-001-feat-autonomous-agent-parity-plan.md`
