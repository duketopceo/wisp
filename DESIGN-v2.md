# Wisp DESIGN v2: research, audit, and redesign spec

Status: research + spec only. Nothing here is implemented. Supersedes the
token block in `DESIGN.md` (v1, kept as-is for history) once approved.
Written 2026-10-02 against `feat/training-arena` (working tree includes
uncommitted `Companion.qml` compress-watchdog changes) and `master`.

Method: refero-design (research first, reference lock, decision ledger,
anti-averaging gate) + design-taste-frontend (audit-first redesign
protocol, AI-tell bans). No Refero MCP was available, so research used the
bundled craft references, the local `awesome-design-md` corpus, the
installed Omarchy shell kit (`/usr/share/omarchy/shell/{Commons,Ui}`), a
live `grim` capture of the running companion, and a web reference sweep
(URLs in section 4).

---

## 1. Product read

**What it is.** A resident voice companion for Omarchy/Hyprland.
`Super+D` opens the mic; whisper.cpp transcribes; Jev routes the
utterance (launch, tool, agent, act, dictate, answer, clarify); Wisp
answers aloud with a cursor-adjacent bubble, points with a ghost cursor,
drives the desktop step by step, or spawns a background coding agent.
State flows one way: `wispd` writes `$XDG_RUNTIME_DIR/wisp/state.json`,
QML surfaces read it.

**Who uses it.** One power user (the author) on an M1 Max running
Asahi, Hyprland, a 3440x1440 ultrawide plus a 2x laptop panel, who
switches Omarchy themes often (current: Vantablack, 8 user themes, 22
stock). Keyboard-first and voice-first. Lives in terminals. Secondary
audience: Omarchy users installing the plugin from GitHub, who will judge
it in the first 10 seconds by whether it looks like part of their desktop.

**Job to be done.** "Let me ask or delegate without leaving what I'm
looking at, show me what you're doing while you do it, and get out of
the way when you're done."

**Design read (one line).** An Omarchy-native, theme-adaptive instrument
with exactly one living thing in it: a small light that listens, thinks,
and leads your eye. Dials: `DESIGN_VARIANCE 5`, `MOTION_INTENSITY 6`
(concentrated in the creature only; chrome stays at 3), `VISUAL_DENSITY
4` for overlays, 6 for the panel.

**Mode.** Redesign, overhaul of visuals, preserve IA and invariants
(three-surface model, click-through overlays, never steal focus, no new
always-on polling, `state.json` as the single bus). These are from
`docs/plans/2026-10-02-003-feat-wisp-companion-ux-plan.md` and stay.

---

## 2. Current-state audit

### 2.1 Stack

| Layer | Tech | Files |
|---|---|---|
| Shell plugin | Quickshell (quickshell-git 0.3.0) QML inside `omarchy-shell`, Qt 6.11, imports `qs.Commons` / `qs.Ui` | `shell-plugin/{manifest.json,BarWidget.qml,Panel.qml,Companion.qml,WispService.qml}` |
| Install target | Plugin copied (not symlinked) to `~/.config/omarchy/plugins/io.github.duketopceo.wisp/` | - |
| Management app | Standalone Quickshell `FloatingWindow`, hardcoded `#16161e` | `shells/debug/shell.qml` (781 lines) |
| TUI | stdlib curses | `wisp/tui.py` |
| Web | Static HTML served by `arena.py`; training fixture page | `scripts/clicklab/arena.html`, `scripts/clicklab/index.html` |
| Theme | Python emits `~/.local/share/wisp/theme.json` (two Tokyo Night palettes); only `Companion.qml` reads it | `wisp/theme.py`, `DESIGN.md` |
| Speech out | TTS argv via `platform.tts_argv` (no amplitude signal) | `wisp/speech.py`, `wisp/platform.py` |
| GPU | Apple AGX via Mesa (GL 4.6), `qsb` shader baker present (`/usr/lib/qt6/bin/qsb`), `qt6-multimedia` and `qt6-svg` installed, no Lottie | - |

### 2.2 Surface inventory and verdicts

| # | Surface | Where | What it does now | Verdict |
|---|---|---|---|---|
| S1 | Bar glyph | `BarWidget.qml` | `WidgetButton` with text `"✦"`, tinted by state; 2px busy strip; 6px pulsing urgent dot; tooltip dumps raw status | **Redo** |
| S2 | Companion orb | `Companion.qml` `orbWin` | 44px filled circle bottom-right on `WlrLayer.Overlay`, glyph `◉`/`♪`, scale-breathes 1.0-1.15 at 0.7 Hz while busy; two `Canvas` "Jupiter rings" spin | **Redo** (becomes the creature) |
| S3 | Orb card | `Companion.qml` expanded card | 340px card: header "Wisp — status", goal, italic transcript, mono step log, stop, answer, result, error, choice buttons, ✓ good / ✗ wrong / collapse / "Super+D to talk" | **Redo** (shrinks to "console") |
| S4 | Listening pill | `Companion.qml` `pillWin` | bottom-center pill, 3 level bars, status word, transcript tail, choice chips | **Redo** |
| S5 | Cursor bubble | `Companion.qml` `bubble` | answer at cursor+24px, 420x150 max, 7 lines then elide, hides after 9s | **Redo** (keep placement) |
| S6 | Cursor ring | `Companion.qml` `ring` | 44px guide-colored ring locked to real pointer while busy, polled by spawning `hyprctl cursorpos` every 90ms | **Redo** (cost + meaning) |
| S7 | Ghost cursor | `Companion.qml` `ghost` | Canvas-drawn arrow in `guide` color, pulses 1.0-1.12 forever, label chip "click: X", 250ms OutCubic glide | **Redo** (signature moment) |
| S8 | Point markers | `Companion.qml` `ptsHost` | 28px rings with index numbers, infinite pulse, label chips, 8s auto-hide | **Redo** |
| S9 | Panel | `Panel.qml` | `KeyboardPanel` 560px, 7 text tabs (Now, Agents, Activity, Tele, Skills, Context, Connect), almost all `Text` rows | **Restructure + restyle** |
| S10 | Management app | `shells/debug/shell.qml` | separate window, own hardcoded palette | **Restyle on shared tokens** (P2) |
| S11 | TUI | `wisp/tui.py` | curses dashboard, headers like `WISP TUI` | **Light pass** (P2) |
| S12 | Training arena | `scripts/clicklab/arena.html` | 3-column card dashboard, Tokyo Night CSS vars, violet `h1 b` | **Restyle on generated tokens** (P1) |
| S13 | Clicklab fixture | `scripts/clicklab/index.html` | click-target test page | **Keep geometry frozen** (it is a training fixture; restyle would invalidate suites). Token swap only, if at all |
| S14 | Desktop entry | `wispd` install writes `Icon=audio-input-microphone` | stock icon | **Missing** (needs app icon) |
| S15 | README / repo | `README.md` | text only, no image, no GIF, no social preview | **Missing visuals** |
| S16 | CLI output | `wispd` | plain prints | Keep; adopt copy rules only |

Live evidence: `hyprctl layers` shows `wisp-companion` at 3348,1348
92x92 on HDMI-A-1. A `grim` crop shows the idle orb as a navy
Tokyo Night disc (`#3b4261` at 0.9) with a `◉` glyph, sitting on top of a
Brave dialog, on a Vantablack desktop whose accent is orange `#e58a4b`
and whose Hyprland rounding is 0. The orb looks like a foreign app.

### 2.3 Findings (ranked)

1. **Two color systems, and the visible one ignores Omarchy.**
   `BarWidget.qml`/`Panel.qml` use `qs.Commons` `Color.accent/urgent/foreground`
   (theme-correct). `Companion.qml` (orb, card, pill, bubble, ghost,
   markers: the surfaces people actually see) uses hardcoded Tokyo Night hex
   + `theme.json`. On Vantablack you get an orange bar and a navy/violet
   companion. `BarWidget` also references `Color.tertiary`, which does not
   exist in `Color.qml` (falls back to accent by luck).
2. **Shape and type ignore the shell kit.** Companion hardcodes radius
   12/6, pixel sizes 9-18, and the Qt default sans (no `font.family`).
   Omarchy exposes `Style.cornerRadius` (Hyprland rounding, 0 here),
   `Style.font.*` (scales with `omarchy display text size`),
   `Style.spacing.*`, and the monospace alias (JetBrainsMono Nerd Font).
   Panel uses them; Companion does not. A user who sets text size 14
   gets a bigger panel and the same tiny bubble.
3. **The same information is shown three times, inconsistently.**
   While busy, transcript appears in the pill, the auto-expanded card, and
   (after) the panel. Choices render in the pill (raw `app:discord`
   strings) and in the card (humanized via `pickLabel`) at the same time:
   two click targets, two labels for one decision. Status words differ by
   surface (`awaiting_choice` raw in panel header and tooltip, "needs you"
   in card, "which one?" in pill). The uncommitted compress watchdog
   (120s/180s forced collapse) is a symptom: the card has no clear job
   so it lingers.
4. **State color semantics conflict across surfaces.** `awaiting_choice`
   is green `ok` on the orb and red `urgent` in the bar. `acting` is green
   on the orb and accent in the bar. Error and "needs you" share red in
   the bar. Panel's "agent" mode badge is `urgent` red with hardcoded
   `#fff` text. Red currently means four things.
5. **Zero custom assets; every icon is a Unicode stand-in.** `✦ ◉ ♪ › ■
   ✓ ✗ “ ” ⚙ ·`, a Canvas-drawn arrow, Canvas arcs, stock
   `audio-input-microphone` app icon, no sounds, no README imagery. Glyph
   rendering depends on font fallback (the `✦` in the bar is not
   distinguishable at 13px in the live capture).
6. **Motion is uniform and never rests.** Ghost cursor, point markers and
   the attention dot pulse with `Animation.Infinite`. Orb breathes at
   ~0.7 Hz with 15% scale while busy. Two `Canvas` rings spin (Canvas is
   CPU-rasterized; `RotationAnimator` is fine, the repaint is not). No
   reduced-motion path. Omarchy kit motion is 60-160ms OutCubic; Wisp
   uses 60-1600ms with no tokens.
7. **Performance traps.** Four independent `state.json` readers
   (`BarWidget`, `Companion`, `WispService` which nothing binds, and
   Panel via host) each run a FileView watch plus a 500ms reload timer.
   Cursor tracking spawns a `hyprctl` process every 90ms (11 forks/s)
   whenever busy or the bubble is visible.
8. **Accessibility gaps.** Card hint "Super+D to talk" uses `faint`
   `#565f89` on `#1a1b26` = **2.76:1** (fails 4.5:1). Idle orb fill
   `#3b4261` on black = **2.14:1** (fails 3:1 non-text). Button hover sets
   text to `canvas` on `guide`; the flat-variant path leaves `ink` on
   `guide` (light-on-light). Choices are mouse-or-voice only (no keyboard
   path, by the no-focus invariant). State is carried by hue alone in
   most places.
9. **Copy reads like a debugger.** "suggestion: {json}", "local only —
   decisions.jsonl + trace.jsonl", "avg ms: route=812, ...",
   "SKIP (launch route but no app identified)" shown verbatim, "Wisp —
   status" with em-dashes, tabs named "Tele".
10. **Corner placement fights content.** The orb lives on
    `WlrLayer.Overlay` with `ExclusionMode.Ignore`, covering the
    bottom-right of whatever window is there (in the capture: a dialog's
    primary button area), including over fullscreen video.

### 2.4 UX flows and friction

| Flow | Today | Friction |
|---|---|---|
| Ask (talk) | Super+D, pill appears, card auto-expands, answer streams into card and cursor bubble, speech plays, card auto-hides 15s | Answer in two places; bubble truncates at 7 lines with no "more"; card covers corner content |
| Act (drive desktop) | pill + card step log + ring on real cursor + ghost cursor glides 250ms to targets | Ring and ghost both use `guide` color, so "you" and "Wisp" pointers are hard to tell apart; no Esc-to-stop discoverable; step log is raw tool names |
| Choose | chips in pill and buttons in card | duplicated, mismatched labels, mouse-only |
| Confirm risky tool | spoken yes/no; not surfaced visually (per UX plan gap) | invisible approval state |
| Label (✓/✗) | always-visible buttons on card and panel | permanent nag; no undo; no acknowledgment |
| Agents | Panel tab, text rows `name [status]` | no progress, no open-log affordance |
| Connect | Panel tab, dot + name + "connect" link | ok; dot is the only decoration that earns it |
| Theme switch | `omarchy theme set` recolors bar/panel only; companion needs `wispd theme` | companion never follows Omarchy |

---

## 3. Asset inventory

### 3.1 Existing (all of it)

| Asset | Path | Kind | Verdict |
|---|---|---|---|
| Bar glyph `✦` | `BarWidget.qml:135`, `Panel.qml:253` | Unicode text | Redo: custom 16px vector mark |
| Orb glyphs `◉` `♪` | `Companion.qml:775` | Unicode | Remove: the creature replaces them |
| Step marker `›`, stop `■`, ✓ ✗, `⚙`, `·` | Companion/Panel | Unicode | Redo: icon set |
| Ghost cursor arrow | `Companion.qml:418-441` Canvas path | Code-drawn raster | Redo: custom vector cursor |
| Busy rings | `Companion.qml:686-727` Canvas arcs | Code-drawn raster | Remove: creature shader carries "thinking" |
| Card spinner | `Companion.qml:831-850` Canvas arc | Code-drawn raster | Remove |
| Palettes | `wisp/theme.py`, `DESIGN.md`, `arena.html` `:root`, `index.html`, `shells/debug/shell.qml` | 5 copies of Tokyo Night hex | Redo: one adapter from Omarchy `colors.toml` |
| App icon | `wispd` installer `Icon=audio-input-microphone` | stock | Missing |
| Sounds | none | - | Missing |
| Fonts | none shipped (inherits) | - | Keep inheriting (correct for Omarchy) |
| README visuals | none | - | Missing |
| Favicon / social preview | none | - | Missing |

### 3.2 New custom assets (creative briefs)

All assets are original, owned, MIT/CC0 in-repo under `assets/`
(new dir). No stock packs, no icon fonts, no emoji.

**A1. The Wisp (character).** The product's only organic element.
- *Concept:* a will-o'-the-wisp: "foolish fire," a light that drifts
  ahead and leads travellers. Not a face, not a mascot with eyes. A
  teardrop-shaped core of light with a soft corona and a short trailing
  wick that shows direction of travel and attention. Personality comes
  from anticipation (dip before rise), follow-through (wick lags the
  core), and tempo, the way Jibo's single eye and Alexa's ring carry
  emotion without a face.
- *Parameters, not clips* (Rive/Duolingo lesson): `energy` 0-1, `heat`
  (hue offset along the theme's warm axis), `cohesion` 0-1 (tight core vs
  frayed edge), `gaze` (angle of the wick), `level` (mic RMS or TTS
  envelope), `flicker` seed. Every state below is a target vector for
  these; transitions blend via springs, never cut.
- *Production:* one GLSL fragment shader baked with `qsb` into
  `assets/shaders/wisp.frag.qsb`, rendered by a single `ShaderEffect`
  (64x64 logical at rest, 96x96 max) driven by `UniformAnimator`s.
  Fallback: 12-frame PNG sprite sheets per state at 1x/2x, generated by
  rendering the same shader offline (headless `qml` + `grabToImage`), so
  shader and fallback cannot drift. Design pass first as a still-frame
  sheet (Figma or Blender emission sphere) before code.
- *Size floor:* must read at 16px (bar), 28px (pill), 64px (corner),
  and 128px+ (README, app icon).

**A2. Mark and wordmark.** Static silhouette of the Wisp (teardrop +
wick, one fill, no gradient) as the logo glyph; wordmark "wisp" set in
the user's monospace at weight 500, lowercase, tracking +2%. SVG,
single-path, `currentColor`.

**A3. Bar glyph set (16px canvas, `Style.bar.iconCanvas`).** Seven
states drawn on a 16px grid: `idle` (outline mark), `listening` (filled
mark + 3 rising ticks), `thinking` (filled mark, wick curled), `acting`
(mark with arrow-tip wick), `needs-you` (mark + corner notch), `error`
(mark with broken wick), `offline` (dashed outline). Delivered as SVG path
data in a QML JS module and rendered with `Shape { ShapePath { PathSvg } }`
so they recolor from tokens and stay crisp at any scale. No PNG.

**A4. UI icon set (24 icons).** mic, mic-off, stop, check, cross, undo,
pin, unpin, collapse, expand, talk, act, agent, point, guide, connect,
link-broken, eye (context), skill, history, gauge (telemetry), settings,
warning, external. Grid 16px, 1.5px stroke, square caps and mitred joins
(matches terminal/Vantablack squareness; round caps only on the Wisp
mark itself). Same `PathSvg` delivery as A3. Drawn by hand, checked
against Tabler/Phosphor metrics only for optical size parity, not copied.

**A5. Ghost cursor.** Must never be mistaken for the user's pointer.
Shape: the standard arrow silhouette, truncated at the tail and replaced
with the Wisp wick (so it reads as "the light holding a pointer"),
filled with the creature color, 1.5px `background` keyline for contrast
on any wallpaper. Companion parts: click ripple (single expanding ring,
220ms, no loop), breadcrumb dots for the last 3 actions (fade over 2s),
"parked" state for guide mode (wick points at the target, gentle 1
cycle settle, then still). SVG path + QML.

**A6. Point beacon.** Replaces numbered rings. A short vertical light
"stake" with index in the monospace caption size, lands with one spring
overshoot, then holds still. Label in a square-cornered chip that follows
`Style.cornerRadius`.

**A7. App icon.** The Wisp silhouette in glowing state on a
`darker_background` tile, rendered from A1 at 1024 and hand-hinted at
16/24/32/48 (separate small-size drawings, not downscales). Ship
`assets/icons/hicolor/{16..512}/apps/wisp.png` + `scalable/wisp.svg`;
installer writes `Icon=wisp`. Variant set: dark tile and light tile.

**A8. Motion sheets.** One storyboard PNG per state transition (idle to
listening, listening to thinking, thinking to speaking, thinking to
acting, acting to parked guide, any to error, error to idle) with frame
timings, plus a single reference video (`assets/motion/wisp-states.webm`,
recorded with `wf-recorder` from a QML test harness) that is the visual
spec for QA.

**A9. Earcons (5).** Designed, not sourced. 48kHz 16-bit WAV, each
under 250ms, peak -6 dBFS, perceived around -20 LUFS so they sit under
TTS. Built from one shared timbre (soft sine + short noise breath,
matching "small fire"):
- `mic-open`: two rising notes (a fifth), 160ms. Required.
- `mic-close`: same two notes falling, 140ms. Required, paired with open.
- `needs-you`: single mid note with slow attack, 220ms. Default on.
- `done`: single soft high note, 120ms. Default off.
- `error`: low minor second, 200ms. Default on.
Production: synthesize in SuperCollider or `sox synth` (scripted, so
they are reproducible and editable in-repo under `assets/sound/src/`),
then master by ear. Played with QtMultimedia `SoundEffect` (preloaded,
low latency). Ghost-click ticks are explicitly not shipped (noise).

**A10. README and repo imagery.** (a) Hero: a real 6-8s screen capture
(WebM + GIF fallback) of Super+D, pill, Wisp flare, answer bubble, ghost
cursor leading to a target, on two different Omarchy themes side by side.
(b) A state contact sheet (A8 stills). (c) GitHub social preview 1280x640
using the A7 icon and wordmark. No div-built fake UI, no mockups.

**A11. Arena favicon + tokens.** 32px favicon from A7; arena CSS custom
properties generated from the same Omarchy adapter (section 6.1).

---

## 4. Research and reference lock

### 4.1 References studied

| Reference | URL | Transferable move |
|---|---|---|
| Clicky (farzaa) | https://github.com/farzaa/clicky | Pointing tags live inside the reply text (`[POINT:x,y:label]`), so speech and pointing stay in sync; click-through overlay panels; three plain states |
| Apple Intelligence Siri glow | https://9to5mac.com/2024/11/03/new-apple-intelligence-siri-looks-different-works-the-same/ | Light originates where you invoked it and reacts to voice amplitude |
| ChatGPT Advanced Voice orb | https://techcrunch.com/2024/09/24/openai-rolls-out-advanced-voice-mode-with-more-voices-and-a-new-look | One soft blob carries all voice states by scale/turbulence, no chrome |
| Microsoft Copilot Mico | https://www.fastcompany.com/91427839/microsoft-mico-copilot-ai-assistant | Avatar can be turned off; modes via small accessories, not new characters |
| Wispr Flow bar | https://docs.wisprflow.ai/articles/5096240724-navigating-the-wispr-flow-app-desktop-ios-and-android | Persistent slim pill; expands on hotkey; freezes bars while processing |
| Superwhisper mini | https://superwhisper.com/docs/get-started/interface-rec-window | Waveform + dot only; controls revealed on hover |
| Raycast Quick AI | https://manual.raycast.com/ai/ai-commands | One keystroke escalates inline answer to full thread |
| Operator / computer-use UIs | https://blog.kowatek.com/2025/01/24/meet-openais-operator-an-ai-agent-that-navigates-the-web-for-you/ | Visible moving cursor + per-action trail |
| Clippy / Lumiere | https://erichorvitz.com/lumiere.htm | Interrupt only above expected-value threshold; otherwise change ambient state |
| Duolingo + Rive | https://rive.app/blog/duolingo-s-ai-powered-video-call-brings-lily-to-life | Blendable parameters instead of discrete clips |
| Rive state machines | https://rive.app/docs/editor/state-machine/states | One view-model drives all visuals; blend states |
| Google Assistant identity | https://design.google/library/evolving-google-identity | Explicit "didn't understand" and "confirmed" states; one shared easing set |
| Alexa light ring | https://developer.amazon.com/en-US/alexa/branding/alexa-guidelines/brand-guidelines/light-ring | Closed state grammar; hue = identity, tempo = urgency, direction = attention |
| Jibo | https://journal.animationstudies.org/article/id/103/ | Single abstract light carries emotion via anticipation and follow-through |
| Desktop Goose | https://samperson.itch.io/desktop-goose | Universal escape key whenever something else moves "your" pointer |
| Will-o'-the-wisp | https://en.wikipedia.org/wiki/Will-o%27-the-wisp | Core metaphor: a light that leads ahead of the traveller |
| caelestia shell | https://ossinsight.io/analyze/caelestia-dots/shell | Panels morph out of their origin rather than popping |
| end-4 dots-hyprland | https://github.com/end-4/dots-hyprland | AI sidebar inside a Quickshell shell is viable; token-derived color |
| Noctalia | https://github.com/noctalia-dev/noctalia-shell | "Quiet by design" baseline |
| DankMaterialShell | https://github.com/AvengeMedia/DankMaterialShell | Heavy logic in a backend daemon, thin QML |
| Omarchy theming | https://learn.omacom.io/2/the-omarchy-manual/92/making-your-own-theme | One `colors.toml` feeds every app; light mode flag |
| Qt Quick performance | https://doc.qt.io/qt-6/qtquick-performance.html | Animators on render thread; avoid layers/Canvas/clip; `visible:false` over `opacity:0` |
| Layer-shell focus | https://quickshell.org/docs/v0.2.1/types/Quickshell.Wayland/WlrKeyboardFocus | `None` for overlays; separate surface for anything that takes focus |
| M3 Expressive motion | https://raw.githubusercontent.com/material-components/material-components-android/master/docs/theming/Motion.md | Spatial springs (damping 0.9) vs effects springs (damping 1.0) as tokens |
| Apple HIG motion + reduced motion | https://developer.apple.com/design/human-interface-guidelines/motion | Avoid large ~0.2 Hz oscillation, spin, zoom; reduced motion = fade/color |
| Alexa AVS earcons | https://developer.amazon.com/docs/alexa-voice-service/functional-requirements.html | Paired start/end-of-listening sounds, every turn |
| Material sound | https://m2.material.io/design/sound/applying-sound-to-ui.html | Earcon vs hero sound hierarchy; silence as negative space |
| WCAG 1.4.11 | https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html | 3:1 for state indicators; never hue alone |
| Local corpus | `~/Documents/github/personal/awesome-design-md/design-md/{raycast,elevenlabs,warp}` | Raycast: near-black canvas, hairline borders, chrome-as-product; ElevenLabs: voice brand restraint |

### 4.2 Directions considered (and rejected)

- **"Glass assistant"** (frosted translucent cards, gradient glow, rounded
  20px). Rejected: fights Omarchy's flat, often square, often pure-black
  themes; blur is expensive on Asahi; this is the 2024 AI-overlay average.
- **"Mascot"** (Clippy/Mico style face, eyes, accessories). Rejected for
  default: the user wants an instrument, and a face makes every error
  feel personal. Kept as a P2 opt-in accessory layer only.
- **Keep Tokyo Night as Wisp's brand palette.** Rejected: on 21 of 22
  themes it is a foreign object; its violet `accentAlt` is the #1 AI
  tell.

### 4.3 Chosen direction: "Ember in the terminal"

All chrome is Omarchy chrome: theme colors, Hyprland rounding, the
user's monospace font, hairline keylines, flat fills, no blur. Inside
that disciplined frame lives one luminous, organic, round thing: the
Wisp. It is the only element allowed to glow, move continuously, or be
round when the theme is square. It does not sit in a box. It leads.

**The memorable detail:** the Wisp is the ghost cursor. When Wisp acts or
points, the light leaves its corner, travels ahead of your eye to the
target (wick trailing), and becomes the pointer there; when done it
drifts home. The folklore ("a light that leads travellers") becomes the
product's core affordance. Two separate visuals (orb + ghost arrow) become
one continuous character.

### 4.4 Reference lock

```text
Primary reference/direction:
  Omarchy shell kit (qs.Commons Color/Style + qs.Ui) for ALL chrome,
  with the Alexa light-ring state grammar for the creature.
Preserve:
  1. Every chrome color resolves from the active Omarchy theme (colors.toml / shell.toml).
  2. Chrome radius = Style.cornerRadius (Hyprland rounding); 0 stays 0.
  3. Type = Style.font.family (monospace alias) at Style.font.* sizes.
  4. Flat surfaces + 1px keylines (popups.border / hyprland.active-border); no blur, no drop shadows.
  5. Creature states: hue = identity, tempo = urgency, cohesion/gaze = attention. Never hue alone.
Borrow only:
  - Clicky: answer at cursor, pointing embedded in speech, click-through overlays.
  - M3 Expressive spring values as motion tokens.
Role rules:
  - Creature color (ember) is for the Wisp, the ghost cursor, and the mic-level meter ONLY.
    Never a button fill, tab fill, or border.
  - `urgent` means "needs you or failed" ONLY. Not "agent mode", not "acting".
  - Glow exists only on the creature. No glow on chrome.
Media strategy:
  Code-native shader for the creature (qsb-baked), hand-drawn vector icons via PathSvg,
  real screen recordings for README. No fake screenshots.
Reject:
  Tokyo Night hex, violet accents, glass/blur cards, rounded-12 everywhere,
  infinite pulsing, Unicode-as-icons, em-dashes in UI copy, spinner rings.
Token commitments: see section 5.
```

### 4.5 Decision ledger

| Decision | Source | Role rule | Why |
|---|---|---|---|
| Chrome colors from Omarchy theme | Omarchy theming docs; finding 1 | Theme owns chrome | 22+ themes; Wisp must look installed, not pasted |
| Radius follows `Style.cornerRadius` | `Commons/Style.qml`; finding 2 | Chrome only | Vantablack is square; rounded-12 broke it |
| Creature is the only round/glowing thing | Alexa ring, ChatGPT orb | Glow = creature only | One focal point; contrast between living light and flat chrome is the identity |
| Wisp becomes the ghost cursor | Will-o'-the-wisp folklore; Clicky; Operator | Ember = creature + ghost | Unifies two visuals; makes "Wisp's pointer" unmistakable vs yours |
| Hue/tempo/shape triple-encoding | Alexa ring; WCAG 1.4.11 | Never hue alone | Color-blind safe; works on themes with weak accents |
| One surface per job | Clicky three-surface; finding 3 | No duplicated content | Removes triple transcript and double chips |
| Springs as motion tokens | M3 Expressive | spatial vs effects | Physical feel for travel; no bounce on color |
| No infinite pulses | Apple HIG; Lumiere | attention decays | Calm when ignored; respect focus |
| Paired mic earcons | Alexa AVS | required pair | Mic state must be audible when eyes are elsewhere |
| PathSvg icon delivery | Qt perf docs | recolorable vectors | Crisp at 2x, no image recolor passes |
| Single ShaderEffect creature | Qt perf docs | one small shader | Cheap on AGX; animators on render thread |
| Panel tabs regrouped to 4 | Limitless timeline; finding 9 | user language | 7 dev-named tabs read like a debugger |

### 4.6 Anti-slop gate (pre-checked)

- Accent is the theme's own, never a default indigo/violet. Pass.
- Cards only where interaction lives (bubble with actions, panel). The
  pill is a strip, not a card; overlay labels are chips. Pass.
- No emoji or Unicode stand-ins as icons. Pass (A3/A4).
- Dark is not forced: light themes (5 stock) get a designed variant. Pass.
- No decorative status dots: the only dots are connector status (semantic)
  and breadcrumbs (semantic). Pass.
- No em-dashes in UI copy. Copy rules in section 5.9. Pass.

---

## 5. Design system spec

### 5.1 Color tokens (mapped to Omarchy)

Source of truth at runtime:
- `qs.Commons Color.{foreground,background,accent,urgent,muted}` (live,
  pushed by Omarchy on theme switch).
- `~/.local/state/omarchy/current/theme/colors.toml` read by one Wisp
  `FileView` (watched) for the ANSI keys the singleton does not expose:
  `green yellow orange cyan blue magenta red selection
  lighter_background darker_background dark_foreground mode`.
- `shell.toml` via `Color.popups.*` / `Color.shellValues["hyprland.active-border"]`.

| Wisp token | Maps to | Role | Fallback |
|---|---|---|---|
| `canvas` | `Color.popups.background` | bubble, pill, console, panel fill | `background` |
| `raised` | `lighter_background` | chip fill, hovered row | `Util.alpha(foreground, 0.06)` |
| `keyline` | `Util.alpha(foreground, Style.normalBorderAlpha)` | 1px chrome borders | - |
| `keylineStrong` | `Color.popups.border` (active-border) | focused/attached surface edge | `accent` |
| `ink` | `Color.foreground` | primary text | - |
| `inkMuted` | `Color.muted` | secondary text; must hit 4.5:1 on canvas (computed check, else `light_foreground`/mix toward ink) | mix(ink, canvas, .35) |
| `accent` | `Color.accent` | selection, focused tab underline, primary action text | - |
| `ember` | **derived** (5.2) | the Wisp, ghost cursor, mic meter | `accent` |
| `emberHalo` | `background` or `foreground` at 0.6, picked for 3:1 vs wallpaper luminance class | keyline around creature/ghost | - |
| `needsYou` | `yellow` | awaiting choice / confirm | `urgent` |
| `fail` | `Color.urgent` (`red`) | error only | - |
| `ok` | `green` | success acknowledgment (brief) | `accent` |
| `selection` | `selection` | text selection, selected chip | `Util.alpha(accent, .35)` |

Mode: `mode = "light"` switches the creature shader from additive glow to
"ink-in-water" (darker core, multiply corona) so it stays visible on
white. Light is designed, not inverted (keeps v1 KTD4).

### 5.2 Ember derivation (theme-adaptive creature color)

1. Start from `accent`.
2. If accent chroma (OKLCH C) < 0.05 (e.g. `white` theme accent
   `#6e6e6e`, monochrome themes), use `orange`, then `yellow`, then
   `accent` as is.
3. If the chosen color is within deltaE 10 of `urgent` (e.g. themes
   whose accent is red), rotate to `orange`/`yellow` so a calm Wisp never
   reads as an error.
4. Clamp OKLCH L to 0.70-0.85 on dark, 0.45-0.60 on light.
5. Core = ember at L+0.1, corona = ember at alpha falloff, wick = ember at
   L-0.1.
Computed once per theme change in QML JS (pure function, unit-testable
via `qmltestrunner` or mirrored in Python for `wispd theme --check`).
On Vantablack this yields the theme's own orange `#e58a4b`. On Tokyo
Night it yields its blue. That is the point: Wisp takes the theme's fire.

`wisp/theme.py` palettes become the fallback used only when no Omarchy
theme is found (generic Linux, macOS), and also emit `theme.css` for the
arena (section 6.12).

### 5.3 Typography

| Token | Omarchy source | Use |
|---|---|---|
| `type.answer` | `Style.font.subtitle` (13) | bubble answer text, max 60ch per line |
| `type.body` | `Style.font.body` (12) | console, panel rows |
| `type.label` | `Style.font.bodySmall` (11) | chips, choice labels |
| `type.caption` | `Style.font.caption` (10) | timestamps, step meta, beacon index |
| `type.title` | `Style.font.title` (14), weight 600 | panel header |

Family: `Style.font.family` everywhere (monospace alias, currently
JetBrainsMono Nerd Font). Heard transcript is **not** italic (italic mono
reads poorly); it is `inkMuted` with a leading mic icon. Line-height 1.35
for answers. Tabular figures for timings. No ALL CAPS except
`caption` labels with +6% tracking.

### 5.4 Spacing, size, radius

- Spacing: `Style.spacing.*` only (`xs 3, sm 4, md 6, lg 8, xl 10, xxl
  12, huge 18, panelPadding 18, popupPadding 14`). No raw pixels.
- Radius: `chrome = Style.cornerRadius`; `chip = min(Style.cornerRadius,
  4)`; pill = `Style.cornerRadius === 0 ? 0 : height/2`. The Wisp and
  beacons are always round (role exception, documented).
- Sizes: Wisp rest 28px (corner), 40px listening, 20px when riding the
  pill, 14px bar mark; ghost cursor 22px tall; hit targets >= 28px
  (`Style.spacing.controlHeight`).

### 5.5 Motion tokens

Springs (Qt `SpringAnimation` approximations of M3 Expressive values;
tune by eye against A8 reference video):

| Token | M3 source | Qt SpringAnimation | Use |
|---|---|---|---|
| `spatialFast` | stiffness 1400, damping 0.9 | spring 6.0, damping 0.45 | ghost click hop, chip press |
| `spatialDefault` | 700 / 0.9 | spring 4.0, damping 0.35 | Wisp travel to target, panel morph |
| `spatialSlow` | 300 / 0.9 | spring 2.5, damping 0.3 | Wisp drifting home |
| `effectsFast/Default/Slow` | 3800/1600/800, damping 1.0 | `NumberAnimation` 90 / 160 / 280ms `OutCubic` | opacity, color, uniforms |

Durations: `instant 90`, `quick 140` (= Omarchy kit), `state 220`,
`travel 320-520` (distance-scaled: 320 + 0.25ms/px, cap 520).
Enter = OutCubic, exit = InCubic, ~70% of enter duration.

Creature states (target parameter vectors):

| State | energy | cohesion | tempo | gaze | Notes |
|---|---|---|---|---|---|
| `offline` | 0.05 | 0.3 | none | down | desaturated, dashed halo; static |
| `idle` | 0.25 | 0.9 | flicker only, aperiodic, < 3% luminance | toward screen center | no scale breathing at all |
| `listening` | 0.6 + level | 0.7 | driven by mic RMS (30 Hz max) | toward user (down) | anticipation dip 80ms on wake; mic-open earcon |
| `transcribing` | 0.5 | 0.8 | level freezes then decays 300ms | - | Wispr "frozen bars" |
| `thinking` (`deciding`) | 0.55 | 0.5 | internal swirl 1.4s period, small amplitude | wick curls | no spinner, no rotation of the whole |
| `speaking` | 0.5 + envelope | 0.85 | syllable-rate pulses from TTS envelope (or synthetic 4-6 Hz if unavailable) | toward bubble | |
| `acting` | 0.7 | 0.9 | travel springs | toward target | Wisp leaves the corner and becomes the ghost cursor |
| `awaiting_choice` | 0.65 | 1.0 | one beckon (anticipation + overshoot, 600ms) then still; repeat at most twice, 8s apart | toward choices | `needsYou` ring; earcon |
| `suggestion` | 0.4 | 0.9 | single slow brighten 900ms, then still | toward bar | no sound; Lumiere threshold applies |
| `confirmed` (new, transient) | spike 0.9 to 0.4 | 1.0 | 260ms | - | after a choice or ✓ label |
| `didnt_understand` (new) | 0.4 | 0.4 | small horizontal "shake" 2 cycles, 300ms | - | from `SKIP` / `clarify` results |
| `error` | 0.2 | 0.2 (frayed) | gutter: dims over 400ms | down | `fail` halo, earcon; returns to idle after 6s |
| `done` | settle to idle over 600ms | - | - | - | optional `done` earcon |

Rules: no `Animation.Infinite` on chrome. Only the creature runs a
continuous loop, and only while a state needs it (listening, thinking,
speaking). Idle flicker is shader-noise based, aperiodic, never near 0.2
Hz at visible amplitude.

**Reduced motion.** New `[ui] motion = "full" | "reduced" | "off"`,
default inherits `hyprctl getoption animations:enabled` (false maps to
`reduced`). Reduced: creature changes brightness/hue only, travel becomes
a 140ms cross-fade (Wisp fades at corner, ghost fades in at target), no
beckon, no shake. Off: static mark per state.

### 5.6 Iconography

Rules for A3/A4: 16px grid, 1.5px stroke at 1x (scale with
`Style.font.icon` / 14), square caps, mitred joins, 1px optical inset,
`currentColor` via `ShapePath.strokeColor`. One weight, no duotone. The
Wisp mark is the only rounded-cap glyph. Icon and label always paired
in chips (icon alone only in the bar, with tooltip).

### 5.7 Elevation and effects

None on chrome. Separation is by `canvas` vs desktop plus 1px `keyline`.
Bubble and console use `keylineStrong` (active border) when they are
"attached" to the current turn, `keyline` otherwise. Opacity: overlays
are opaque at `popups.background-alpha` (theme decides translucency;
Vantablack says 1.0). The creature's corona is the only soft edge on
screen.

### 5.8 Component inventory and states

| Component | States | Notes |
|---|---|---|
| `WispCreature` (ShaderEffect) | all of 5.5 | one instance, reparented between corner, pill, cursor |
| `BarMark` | idle, listening, thinking, acting, needs-you, error, offline | PathSvg; 2px underline strip only while busy (keep, recolor ember) |
| `Chip` | normal, hover, pressed, selected, disabled, keyed (shows `1`/`2`/`3` hint) | uses `Style.normalFill/hoverFill/...`; humanized label always (`pickLabel` moves to the shared service) |
| `ActionButton` | normal, hover, pressed, busy, disabled | text + icon; `accent` text; never filled with ember |
| `StopControl` | visible only while busy; hover turns `fail` | icon + "stop" + `Esc` hint |
| `LabelPrompt` (was ✓/✗) | hidden, offered, chosen (shows "noted", undo for 5s) | offered once per finished turn, inside the bubble footer, auto-dismisses |
| `StepRow` | pending, running, done, failed, needs-confirm | icon per tool family + humanized verb ("Clicked 'Settings'"); raw tool name in tooltip |
| `Transcript` | live, final | mic icon + `inkMuted`, never italic |
| `Answer` | streaming (caret = ember block), final, truncated ("more" opens console) | |
| `Beacon` | landing, holding, fading | A6 |
| `GhostCursor` | traveling, clicking (ripple), parked (guide), returning | A5; carries the creature |
| `ConfirmCard` (new) | pending, approved, denied | inline at cursor for risky tools; `needsYou` keyline; keys `y`/`n` via submap |
| `PanelTab` | normal, hover, selected (accent underline, no fill) | 4 tabs |
| `AgentRow` | queued, running (ember tick), done, failed, cancelled | elapsed time, last log line, "open log" |
| `ConnectorRow` | connected (semantic dot, `ok`), disconnected, authorizing | |
| `EmptyState` | per tab | one sentence + one command, no illustration |

### 5.9 Copy rules

Lowercase status words, human verbs, no protocol strings, no em-dashes,
max one middle-dot per line.
- Status vocabulary (single map, shared): idle "ready", listening
  "listening", transcribing "hearing you", deciding "thinking", acting
  "working", speaking "speaking", awaiting_choice "your call",
  suggestion "idea", error "that failed", offline "offline", done
  (shows the answer, no word).
- Result prefixes are translated: `SKIP (launch route but no app
  identified)` becomes "didn't catch which app" + `didnt_understand`
  state. `BLOCKED` becomes "blocked: <reason>".
- Header "Wisp - working" never; header is the mark + status word.

---

## 6. Surface-by-surface plan

Structure first: one data layer.
**P0-0 `WispState.qml` singleton** (in plugin, `pragma Singleton` via
`qmldir`): the only `state.json` reader (FileView watch; 500ms fallback
reload only while not idle), the only `colors.toml` reader, the token
object (5.1-5.5), the status-word map, `pickLabel`, and the process
launchers (`choice`, `label`, `interrupt`, `trigger`). Bar, Companion,
Panel bind to it. Delete `WispService.qml` (unbound) after migration.
Replace `hyprctl cursorpos` forks with Quickshell's Hyprland IPC event
stream if it exposes pointer position; otherwise one long-lived
`socat`-style reader of Hyprland's socket2, or keep polling but only
while the bubble or ghost is visible and at 30 Hz via a single
persistent process.

### 6.1 Bar mark (S1)
- P0: `BarMark` PathSvg in `BarIconButton`/`OpticalGlyph` slot sizes;
  color `ink` idle, `ember` busy, `needsYou`, `fail`; tooltip uses status
  map and one line of context. Left click: panel. Right click: talk.
  Middle click: stop (new).
- Ceiling: a 14px live mini-Wisp (same shader, 10 fps cap) in the bar
  when the corner Wisp is hidden (fullscreen or user-hidden).

### 6.2 Corner Wisp (S2) and console (S3)
- P0: replace orb with `WispCreature` at 28px, no backing disc, no
  glyph. Move window to `WlrLayer.Top` (not Overlay) so fullscreen apps
  cover it; hide automatically when the focused window is fullscreen.
  Margin = `Style.gapsOut`. Click: open console. Hover: reveal "talk"
  and "hide" mini actions (Superwhisper).
- P0: the expanded card becomes the **console** and only opens on user
  click or for `awaiting_choice`/confirm. It no longer auto-expands for
  every busy state (the pill owns live progress). This retires the need
  for the compress watchdog; keep the watchdog as a safety net until
  shipped.
- Console content order: status line, goal, step timeline (StepRow), stop.
  Answer is not duplicated here unless the bubble was dismissed.
- Ceiling: console morphs out of the Wisp (caelestia): the creature
  stretches into the card's top edge and becomes its live status line.

### 6.3 Listening pill (S4)
- P0: one-row strip, `chrome` radius rules, `canvas` fill, keyline in
  ember at `0.35 + level*0.4` (keep this good idea). Contents: riding
  Wisp (20px), status word, transcript tail. Choices **only** here
  while the user is in the flow, humanized, with keyed hints `1 2 3`.
- P0: bind `Super+1..3` and `Esc` in a Hyprland submap entered only
  while `awaiting_choice` (via `bindings.lua` in the stash, sent by
  `wispd`), giving a keyboard path without stealing focus.
- Ceiling: Wispr-style edge docking (bottom, left, right; vertical on
  sides) and origin-aware entrance (pill grows from the bar mark if
  invoked by click, from the bottom edge if by hotkey; Siri lesson).

### 6.4 Cursor bubble (S5)
- P0: tokens, `type.answer`, max 60ch, grows to 12 lines then "more"
  chip opens the console with the full answer. Streaming caret in ember.
  Footer (after finish): `LabelPrompt` (check/cross icons), "copy",
  "pin". Dwell: 9s + 40ms per word, paused while hovered.
- P0: placement avoids covering the cursor's hot area and flips
  left/above at screen edges (current clamp keeps it on screen but can
  sit under the pointer).
- Ceiling: bubble tail points to the Wisp when the Wisp is riding the
  cursor; `[POINT]` tags in the answer render as inline beacons linked
  by a hairline to their on-screen target on hover.

### 6.5 Cursor ring (S6)
- P0: remove the ring around the user's own pointer. It used the same
  color as the ghost and blurred "mine vs Wisp's." Replace with the Wisp
  riding at an offset (+18, +18) from the real cursor while listening or
  thinking: presence near the eyes, never on the hotspot.
- Ceiling: rider follows with `spatialDefault` lag (wick shows motion).

### 6.6 Ghost cursor (S7), the signature moment
- P0: A5 ghost replaces the Canvas arrow. On each act step the Wisp
  travels from its current position to the target (`travel` duration,
  curved path, wick trailing), lands, ripple on click, breadcrumb kept.
  Guide mode: parks with label chip "click Settings" and stays still
  (no infinite pulse). `Esc` (submap while acting) stops and returns
  control; hint shown in the pill.
- Ceiling: multi-monitor travel across outputs (one overlay per screen,
  hand-off at the edge), and the "lead" behavior: in guide mode the Wisp
  drifts slightly ahead toward the target as the user's pointer
  approaches, like the folklore.

### 6.7 Point beacons (S8)
- P0: A6 beacons, land once, hold still, fade after 8s or on next turn.
- Ceiling: beacons connect in sequence with a faint dotted path when
  order matters (multi-step instructions).

### 6.8 Confirm (new, inside existing surfaces)
- P0 (needs daemon field `state.confirm = {tool, app, summary, risk}`):
  `ConfirmCard` renders in the bubble position with `needsYou` keyline,
  "Allow once / Allow for this app / Deny", keys `y`/`a`/`n` in the
  submap. Not a fourth surface: it is the bubble in a different mode.

### 6.9 Panel (S9)
- P1 IA: 7 tabs become 4 tabs (labels unchanged in data, regrouped in UI):
  - **Now**: current turn (mirrors console), recent turns as a day
    timeline (Limitless), label prompt for last turn.
  - **Agents**: AgentRow list with elapsed, last line, open log, cancel.
  - **Wiring**: Context ("what wisp sees"), Connectors, Skills
    (searchable, 20 shown).
  - **Stats** (was Tele + Activity): turns, success rate, per-route
    median latency as numbers with tiny inline bars (no filled tracks),
    decision log below.
- P1 style: tabs with accent underline (no filled pill), PanelSectionHeader
  and PanelSeparator from `qs.Ui`, monospace tables for timings, no raw
  JSON, no file names in copy.
- Ceiling: panel opens as a morph from the bar mark; "Ask" text field at
  top (separate focusable surface, so the no-focus invariant holds for
  overlays).

### 6.10 Management app (S10)
- P2: import the same `WispState` tokens (it runs outside omarchy-shell,
  so it reads `colors.toml`/`shell.toml` directly with the same adapter).
  Kill `#16161e`.

### 6.11 TUI (S11) and CLI (S16)
- P2: header "wisp" + status word; curses color pairs from ANSI 0-15 so
  the terminal theme (already Omarchy-generated) colors it. Status map
  shared via `wisp/status_words.py` (one source for Python and, emitted
  into `theme.json`, for QML).

### 6.12 Training arena (S12) and clicklab (S13)
- P1 arena: `wispd theme --css` emits `theme.css` from the Omarchy
  adapter; arena drops its hex block, violet `h1 b`, dashed row borders,
  and 3-equal-column card grid in favor of a 2-zone layout (left: live
  run feed as the dominant column; right: skill bank + stats) with
  hairline separators. Monospace numerals. A7 favicon.
- Clicklab `index.html`: freeze. It is a geometry fixture for suites in
  `suites.json`. Any visual change must not move targets; prefer none.

### 6.13 Repo surfaces (S14, S15)
- P1: A7 icon installed to hicolor; `Icon=wisp`. README hero recording,
  contact sheet, social preview (A10).

### 6.14 Priority summary

| P | Item | Pragmatic first pass | Supreme ceiling |
|---|---|---|---|
| P0 | `WispState` singleton + Omarchy token adapter + ember derivation | single reader, tokens, status map | live theme-switch transition (ember cross-fades over 400ms) |
| P0 | Theme-correct chrome on all overlays | Style/Color everywhere, radius rules | per-theme QA screenshots in CI across 5 themes |
| P0 | De-duplicate surfaces (console on demand, choices in pill only) | behavior change | origin-aware morphs |
| P0 | Creature v1 | shader with 6 states (idle, listening, thinking, speaking, needs-you, error) | full 13-state vector set + TTS envelope |
| P0 | Icon set A3/A4 + ghost A5 | PathSvg | animated icon transitions |
| P0 | Mic earcons pair | open/close only | full A9 set + per-theme timbre tint |
| P0 | Keyboard path (submap: 1-3, y/a/n, Esc) | via `wispd` | discoverable hint chips everywhere |
| P0 | Contrast fixes | computed `inkMuted`, halo ring | automatic 3:1 halo by sampling wallpaper luminance |
| P1 | Wisp-as-ghost-cursor travel | single monitor | multi-monitor hand-off + lead behavior |
| P1 | Panel IA (4 tabs) + restyle | | panel morph + Ask field |
| P1 | Confirm card | needs daemon field | |
| P1 | Arena restyle, app icon, README media | | |
| P2 | Management app, TUI, light-mode creature polish, opt-in accessories (Mico lesson: e.g. tiny headphones while dictating) | | |

---

## 7. Accessibility

- Contrast: text >= 4.5:1 against `canvas` (computed at theme load; if
  `muted` fails, `inkMuted` mixes toward `ink` until it passes). Current
  failures to fix: `faint` 2.76:1, idle orb 2.14:1. Non-text indicators
  (Wisp, ghost, beacons, chip borders that carry state) >= 3:1 via the
  `emberHalo` keyline.
- Never hue alone: every state also differs in tempo/shape (5.5), icon
  (A3), and word (5.9).
- Focus: overlays stay `WlrKeyboardFocus.None` and click-through except
  the pill's chips and bubble actions. Keyboard parity through a
  Hyprland submap that exists only while Wisp is waiting or acting.
  Universal `Esc` while acting (Desktop Goose rule).
- Motion: section 5.5 reduced/off modes; no flashing above 3 Hz at high
  contrast; idle never oscillates near 0.2 Hz at visible amplitude.
- Sound: earcons never the only signal; master toggle and per-earcon
  toggles in `[ui.sound]`; respect PipeWire mute/DND (Omarchy
  notifications DND state, if readable).
- Screen readers: Quickshell overlays expose little to AT-SPI; spoken TTS
  is the accessible channel. Keep answers available as text in the
  console for copy.
- Text scale: all sizes from `Style.font.*`, so `omarchy display text
  size` scales Wisp.
- Privacy honesty: a visible "mic open" state on every surface that is
  showing (bar, pill, creature) plus the earcon.

## 8. Performance budgets (QML on Asahi AGX)

| Budget | Target |
|---|---|
| Idle CPU (omarchy-shell attributable to Wisp) | < 0.3% of one core; no timers firing faster than 2s while idle |
| Idle GPU | creature redraw <= 10 fps at idle (flicker), 0 fps if `motion=off` |
| Active | creature 60 fps only while listening/thinking/speaking/traveling; one `ShaderEffect`, fragment shader <= ~40 ALU ops, 96x96 px max |
| Layers | no `layer.enabled`, no `MultiEffect` blur, no `clip`, no `Canvas` anywhere |
| Animations | Animators (`UniformAnimator`, `OpacityAnimator`, `XAnimator`) on render thread for all continuous motion |
| Hidden surfaces | `visible: false` (not opacity 0); windows unmapped when idle except corner Wisp |
| Process spawns | zero per-frame forks; cursor tracking via event stream or one persistent reader |
| state.json | one reader; reload fallback 500ms only when not idle |
| Memory | < 15 MB added to omarchy-shell RSS |
| Earcons | preloaded `SoundEffect`, latency < 50ms |
| Theme switch | recolor within one frame of Omarchy's IPC push |

Verification: `QSG_RENDER_TIMING=1` on a dev shell instance, `perf top`
on omarchy-shell during a scripted turn, and `pidstat` idle sampling;
add a `wispd selfcheck --ui` that reports timer counts from the plugin
via a debug IPC call.

## 9. Open questions

1. **Creature default placement:** corner (current) or riding near the
   cursor always? Spec assumes corner at rest + rides only during turns.
2. **TTS envelope:** can `speech.py` expose amplitude (pipe TTS PCM
   through PipeWire with a level tap) or should speaking use a synthetic
   syllable rhythm?
3. **Confirm state:** willing to add `state.confirm` to the IPC contract
   (`docs/IPC_CONTRACT.md` says the status vocabulary is closed)? Also
   `didnt_understand` and `confirmed` would be derived client-side from
   `result` unless the daemon adds them.
4. **Hyprland submap ownership:** bindings live in the stash-canonical
   `bindings.lua` (sync-watch reverts edits). OK for `wispd install` to
   add a sourced `wisp-binds.lua` there, or should Wisp use
   `hyprctl eval` to register binds at runtime?
5. **Light themes:** is a designed light creature worth P0, or is
   P2 acceptable given 5 of 22 stock themes are light?
6. **Earcons default:** mic open/close on by default? (Recommended yes.)
7. **Mascot accessories (P2):** wanted at all, or keep strictly abstract?
8. **Capture exclusion:** should overlays be hidden from screenshots and
   recordings by default (Cluely lesson), given Wisp itself takes
   screenshots at trigger time (it should never see its own overlay)?
9. **Plugin install:** switch to symlink install so the live plugin and
   repo cannot drift (currently a copy)?
10. **Production of A1/A7/A9:** hand-design in-house (Blender/Figma +
    SuperCollider) vs commission an illustrator/sound designer for the
    creature stills and earcons, with shader/code done in-repo.
