# Wisp Shipping Completion

Status: branch implementation under final verification, not a released v1.
Date: 2026-10-30. The canonical delivery order and release gates remain
in [ROADMAP.md](../../ROADMAP.md).

## Scope and authorization

The owner authorized native review, testing and PR work after the original
LFG tail could not resolve its required helpers. The subsequent full-release
request supersedes that earlier PR-only limit. This receipt records what
has actually been verified, not a claim that publication has finished.

The later owner request expands this scope to an installable Linux release
candidate, one-line installation, onboarding, recovery and the public site.
Owner-labelled runs follow installation; they are not prerequisites for
publishing a clearly labelled candidate. The stable-v1 gate is unchanged.
The five proposed DNS records still require their separate confirmation.
No vault unlock, Tallyline post or real desktop task is included.

The work is attached to [Wisp PR #259](https://github.com/duketopceo/wisp/pull/259).
The safety follow-up from [PR #260](https://github.com/duketopceo/wisp/pull/260)
was cherry-picked as `d2a9285`; this is not a merge of either PR.

## Review corrections

- **Sensitive actions:** mutations check the current surface, not only
  turn-start focus. Unknown or sensitive live surfaces require confirmation,
  including stateless policy callers.
- **IPC:** unattributed callers are refused before dispatch. The experimental
  TCP seam is not an authenticated Windows control interface.
- **Capture ownership:** deterministic regressions exercise ducking,
  startup rollback, interruption, empty audio, and one-shot restoration.
  Daemon cancellation and stream-discard cleanup are covered by the expanded
  91-test focused receipt, including busy, phantom and watchdog release paths.
- **Pointer defaults:** unconfigured act turns use a temporary `auto`
  overlay only with an available backend. Explicit modes and the caller's
  configuration remain unchanged. Persisted legacy `guide` cannot safely
  be distinguished from deliberate preference and is preserved.
- **Browser navigation:** Notion has an explicit fallback; discovery includes
  ports 9100 and 9223 without removing existing ports.
- **Timing truth:** complete-response calls report TTFT unavailable, not
  total latency disguised as TTFT. Streaming first-content timing remains
  measured; total latency includes an empty-response retry.
- **Injected keys:** a failed compositor submap-leave acknowledgement
  refuses injection and preserves active state. Failed suspension does not
  leave the controller's suspension count incremented.
- **Documentation:** trust inventory explanations, inline-span extraction,
  platform readiness, historical labels, domain status and roadmap claims
  are aligned with inspected source.
- **Click provenance:** model-supplied numeric clicks require element
  evidence. Human coordinate exceptions receive the original transcript,
  not correction-decorated task text. The actual point must be inside the
  focused window; an oversized control rectangle is not sufficient.
- **Router off:** an explicit Explain, Act or Dictate choice is required.
  Missing, invalid or cancelled choices do not enter act or execute tools.
  Unattended development runs skip this interactive route.
- **Language and privacy:** act receives the requested reply language while
  the English prompt remains unchanged. Empty-step answers return before
  trajectory queueing; real-action trajectory snapshots retain their
  existing behavior. This does not solve broader action-history consent
  or redaction.
- **Workspace inference:** complete title paths retain spaces rather than
  accepting an existing truncated prefix. Explicit configured directories
  take precedence. Browser titles cannot select an agent workspace.

The native manual review is limited and is not a completed formal
multi-reviewer CE pipeline. Its original seven findings were independently
reported; focused red/green regressions were used to validate the fixes.
The bounded final source-freeze recheck resolved MR3/MR4 with no additional
actionable findings retained. It did not execute full suites or approve
publication independently.

## Website behavior and build

The optional enhanced build lives in `site-3d/`. It does not replace the
independent no-script `site/` contract or its 300 KiB ceiling.

- **Illustration:** a real Three.js scene uses the repository glyph and
  companion imagery. Email, work-profile, sensitive-action and media
  examples share a deterministic state model with semantic DOM feedback.
- **Safety explanation:** sensitive mutation waits for explicit approval;
  read/navigation and secret-refusal boundaries are stated separately.
  Media sends a toggle illustration and does not assert a paused state.
- **Controls:** cancel, reset, manual motion pause and keyboard approval
  work without a microphone, account, model call or real desktop action.
  Reset and replacement invalidate older turn timers.
- **Lifecycle:** one animation loop pauses offscreen/when hidden. Reduced
  motion, absent WebGL, module failure, draw failure and context loss use
  static content. Failed rendering disposes the enhanced scene.
  No-JavaScript HTML retains product and installation information.
- **Assets:** Three.js 0.170.0 and Outfit are vendored with MIT/OFL notices
  and provenance. No third-party runtime asset requests are required.
- **Installation:** only the repository command is copied. Presets set
  defaults; they do not supply credentials or downloaded models, and a
  local preset alone does not establish zero egress.
- **Output:** an explicit allowlist, missing/import validation and
  deterministic SHA-256/byte inventory protect a separate `build/site-3d/`.
  Source and ancestor output paths are refused.

Local build commands:

```sh
python3 scripts/site/build.py --out build/site
python3 scripts/site/build_3d.py
python3 scripts/gen_trust.py --check
```

## Browser coverage

Chromium 147.0.7727.15 with Playwright 1.59.0 rendered actual WebGL.
The normal Chromium gate requires a canvas and a completed render frame;
an unintended static fallback cannot satisfy the enhanced gate.

- **Viewport matrix:** 1440×900 desktop, 1440×540 short desktop,
  390×844 phone and 320×740 narrow phone.
- **Task flows:** email, work, media toggle, sensitive wait/approval,
  keyboard focus restoration, cancellation, rapid replacement and reset.
- **Access:** visible focus, manual pause/resume, reduced motion initially
  and after preference changes, and expanded mobile confirmation content.
- **Failure paths:** disabled JavaScript, unavailable WebGL, aborted scene
  module, context loss, denied clipboard and manual-copy guidance.
- **Assets and layout:** loaded Outfit, seven distinct DOM type sizes,
  no horizontal overflow, no uncaught page errors and no external requests.
- **Hosting:** local subpath and fresh-context private-preview root checks
  cover interaction, install copy, phone layout and end-to-end scrolling.

The first Impeccable detection reported a skip-link hover contrast warning.
The hover rule now keeps dark text on the light skip-link background.
Supplemental visual review found no blocking defect in the supplied
desktop/mobile captures; no approved raster comparison or formal full
Impeccable receipt is claimed.

Local WebKit could not install because this sandbox OS is unsupported by
Playwright 1.59.0. CI pins the enhanced job to `ubuntu-24.04`, installs
Chromium and WebKit, and records engine-specific coverage rather than
calling a fallback a successful enhanced render.

The hosted gate passes actual WebGL rendering on Chromium 147.0.7727.15
and WebKit 26.4, with scenarios, cancellation, approval and fallbacks passing
and zero external requests or page errors. This is hosted coverage, not
a claim that local WebKit installed. ([enhanced CI job](https://github.com/duketopceo/wisp/actions/runs/41130287443/job/124319132519))

## Verification ledger

Final integrated regression, source-freeze review and PR CI results are
pending. Earlier diagnostic failures are retained as evidence, not
misrepresented as the final result.

The first integrated run observed a keyboard acknowledgement race and a
CPU-contention-sensitive idle-budget failure. The keyboard race has
dedicated regressions; the idle-budget check passed in isolation without
changing its assertion. Browser processes must be closed before the final
local full suite to avoid artificial renderer contention.

The first broad run after the release-scope expansion executed 3,903 tests
with 47 failures, 55 errors and 21 skips. It is a red integration receipt,
not a release pass. Repairs cover stale removed-router mocks, attributable
IPC callers, explicit live-window/element evidence and answer-lane fixtures.
A later run reached 3,985 tests with two stale browser/image fixtures
remaining. After those fixture repairs, the focused 104-test rerun passed.
The final broad rerun passed: **3,985 tests in 404.577 seconds,
21 skipped**, on Python 3.14.8. Hosted Python 3.11/3.13 checks remain a
separate merge gate; local success is not a hosted-CI receipt.

The latest parent integration slice passes 118 tests. It includes router-off
selection, trusted request forwarding, schema/default alignment, the known
Vault deny fixture, documentation lint and Pages/bootstrap contracts.

Rollback unit restoration now performs a checked daemon reload before a
separately consented restart. Reload failure blocks restart and preserves
the truthful distinction between restored disk files and failed runtime
activation. Missing or declined restart consent performs no manager
actions. The updated rollback suite passes 71 tests, with manager runners
stubbed; the install/bootstrap integration slice passes 79 tests.

Release packaging passes 15 checks, including installation from an actual
extracted archive into a guarded disposable HOME. Local ELF test fixtures
are synthetic; they are not native Rust execution. The release workflow
builds and tests the Rust binary on native Linux x86_64 and aarch64 runners.

An isolated Qt/PySide6 6.10.0 environment passes 280 focused QML tests,
33 component checks including qmllint, and nine native recap/NowTab probes.
All 21 DrawLayer snapshots remain pixel-exact. Fifteen new recap images
pass repeated pixel checks. Only six explicitly approved Companion
goldens were updated for the intended continuous activity pill.

StepRow, RunCard and the existing NowTab cases retain historical golden
differences. Current and clean-master renders are pixel-identical in the
bounded comparison, including the two tested Qt versions; no existing
NowTab goldens or thresholds were changed to hide them. This isolated
harness is not real Hyprland/Omarchy or a release-install desktop pass.

## Installation and learning handoff

The candidate payload includes runtime docs/tasks, desktop and unit templates,
release metadata and a user-scoped launcher. Bootstrap and in-app update
require independent GitHub CLI/Sigstore verification before extraction or
candidate execution. Verification binds native archives to the repository,
release workflow, exact tag, source commit and hosted runner; missing or
failed verification cannot downgrade to checksums. Public checksums remain
integrity checks, not a trust root. The downloaded bootstrap script itself
still needs independent source trust/review; later payload checks cannot
authenticate a malicious replacement script.

Explicit prerelease selection, preflight and consent are supported.
Plugin ownership and external unit restoration are included in recovery.
Archive install tests use stub service-manager commands; they do not
prove that a real desktop daemon was started.

Legacy decision routing is retired; optional structured grounding remains.
The private weekly recap is off by default. Public growth snapshots are
source-checkout maintenance tools, not a Tallyline integration or outreach
campaign. Missing traffic and spend provenance remain unknown.

After installation, the owner runs onboarding and real tasks across apps,
labels outcomes, and records corrections. Baseline import/ranking is ready,
but unavailable historical clicklab data and live success metrics are not
invented. Improving skills and measured held-out success precedes any
claim that model reinforcement learning has been performed.

## Remaining release gates

- **Real Omarchy:** clean-box install, onboard/doctor, microphone/media
  behavior, capture/cancellation, profile targeting, cursor injection,
  QML feedback, and permission/policy behavior on the actual desktop.
- **Owner-labelled evaluation:** at least 50 labelled turns and the
  configured 60% gate. Judge output is not an owner label; historical
  7/23 or quoted 7/26 snapshots are not current verification.
- **R6 timing:** `buddy.js` still uses its 0.30-second entry delay.
  Reducing it needs a real screenshot-clearance and overlay check.
- **Production hosting:** the owner approved all five launch DNS records.
  Four DNS-only apex A records are saved and publicly resolving; the
  `www` CNAME remains pending because its dashboard dropdown failed and
  API authentication still fails after reconnection. GitHub Pages is
  configured for `wisp.observer`; deployment, certificate and HTTPS checks
  remain separate gates. The bootstrap publication path is `/install.py`,
  not `.sh`; a public command must target a real authenticated release.
  ([Public apex DNS](https://dns.google/resolve?name=wisp.observer&type=A),
  [public www DNS](https://dns.google/resolve?name=www.wisp.observer&type=CNAME))
- **Native ports:** authenticated IPC, companion integration, packaging,
  signing and hardware validation remain work, not supported releases.

No measured model-latency, live task-success, FPS, or production-release
claim is derived from the website demonstration or deterministic tests.
