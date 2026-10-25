# Clicky (farzaa/clicky) — Teardown Verification vs HEAD

Verified against `main` @ `a80fa80721a8aebe51a170a7780705024ebc6e46` ("Update README.md", 2026-04-27 — confirmed current tip via GitHub). Shallow clone at `/tmp/clicky-src`.

## Claim-by-claim verdicts

**1. Menu-bar-only + non-activating overlay — CONFIRMED with one drift.**
- `LSUIElement` = true: `leanring-buddy/Info.plist:5-6`. Entry point is menu-bar only (`leanring-buddy/leanring_buddyApp.swift:14-26`, empty `Settings` scene).
- **Drift**: the full-screen overlay is a borderless `NSWindow` subclass, **not** an `NSPanel` — `OverlayWindow.swift:14` (`class OverlayWindow: NSWindow`), `.borderless` (19), `.screenSaver` level (27), `ignoresMouseEvents` (28), `collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary]` (29), `canBecomeKey/Main = false` (46-52). The `NSPanel` is the menu-bar dropdown (`KeyablePanel`, `MenuBarPanelManager.swift:23`, `.nonactivatingPanel` at 157, `.canJoinAllSpaces` at 169). Functional claim holds; class type was wrong.
- One overlay window **per screen** (`OverlayWindow.swift:783-807`); buddy renders only on the cursor's screen (`buddyIsVisibleOnThisScreen`, 395-407).

**2. PTT via listen-only CGEvent tap on ctrl+option — CONFIRMED, nuance on "chords dropped".**
- `CGEvent.tapCreate(tap: .cgSessionEventTap, place: .headInsertEventTap, options: .listenOnly, ...)` — `GlobalPushToTalkShortcutMonitor.swift:57-63`; monitors `.flagsChanged/.keyDown/.keyUp` (37-40); re-enables tap on `tapDisabledByTimeout/UserInput` (104-108).
- `BuddyDictationManager.swift:95`: `currentShortcutOption = .controlOption`, matched modifier-only via `.flagsChanged` (157-177).
- Nuance: the enum defines **5** shortcut options incl. two modifier+space chords (`BuddyDictationManager.swift:17-22`, space path 179-198). Chord support wasn't removed — ctrl+option modifier-only is just the hardcoded default.

**3. STT: AssemblyAI `u3-rt-pro` over shared URLSession; fallbacks — CONFIRMED with config caveat.**
- `u3-rt-pro` + `pcm_s16le`/`16000`/`format_turns`/`keyterms_prompt`: `AssemblyAIStreamingTranscriptionProvider.swift:447-466`; ws `wss://streaming.assemblyai.com/v3/ws` (111).
- One long-lived `URLSession` owned by the provider, shared across sessions: `AssemblyAIStreamingTranscriptionProvider.swift:30-34` (comment documents the socket-pool corruption rationale).
- Temp token via Worker `POST /transcribe-token` (22, 61-84); 480s TTL (`worker/src/index.ts:84`).
- Fallback chain: `BuddyTranscriptionProvider.swift:39-99` driven by `VoiceTranscriptionProvider=assemblyai` (`Info.plist:11-12`). **Caveat**: OpenAI provider needs `OpenAIAPIKey` in the bundle plist (`OpenAIAudioTranscriptionProvider.swift:20,27-33`) which is absent -> in stock builds the only live fallback is Apple Speech. OpenAI calls `api.openai.com` directly (66), **not** the Worker, and buffers-then-uploads WAV (no streaming; `finalTranscriptFallbackDelaySeconds=8.0`, 60).

**4. Claude Sonnet default / Opus optional, SSE via Worker with exactly 3 routes — CONFIRMED.**
- Default `claude-sonnet-4-6`: `CompanionManager.swift:111`, `ClaudeAPI.swift:17`; Opus option `claude-opus-4-6`: `CompanionPanelView.swift:610-611`; persisted via UserDefaults (`CompanionManager.swift:113-117`).
- SSE: `"stream": true` (`ClaudeAPI.swift:145`), `byteStream.lines` parsing `content_block_delta`/`text_delta` (183-208).
- Worker routes exactly `/chat`, `/tts`, `/transcribe-token`: `worker/src/index.ts:28-38`, POST-only (23-25). Header comment (7-10) is stale — lists only two routes.

**5. ElevenLabs `eleven_flash_v2_5` via same proxy — CONFIRMED, with a streaming claim that's false.**
- `model_id: eleven_flash_v2_5`, stability 0.5 / similarity 0.75: `ElevenLabsTTSClient.swift:41-45`; proxied `POST /tts` -> `api.elevenlabs.io/v1/text-to-speech/{voiceId}` (`worker/src/index.ts:109-124`).
- **Drift**: file header claims streaming playback, but `session.data(for:)` (50) buffers the **entire** MP3 before `AVAudioPlayer.play()` (65-67). TTS latency = full generation; not streamed.

**6. ScreenCaptureKit all-monitors — CONFIRMED, timing drifted.**
- `CompanionScreenCaptureUtility.swift:30-131`: `SCShareableContent` (31), per-display `SCContentFilter` + `SCScreenshotManager.captureImage` (81-97), cursor screen sorted first (61-68), own app's windows excluded (42-45), max dim 1280px, JPEG 0.8 (84-100), "primary focus" labels (104-111).
- **Drift**: capture happens inside `sendTranscriptToClaudeWithScreenshot` (`CompanionManager.swift:596`) — i.e., at **release/after transcript finalization**, not at press time. The screenshot reflects the screen at end of utterance.

**7. `[POINT:x,y:label(:screenN)]` / `[POINT:none]` in screenshot-pixel space — CONFIRMED.**
- Prompt spec: `CompanionManager.swift:566-576` (coords = labeled image pixels, top-left origin, `:screenN` for other screens). Teardown's ~568-576 line cite ~= correct for the prompt; parser is at 784-823 (regex 786), mapping at 648-679.
- Map: clamp to screenshot space (660-661) -> scale pixels->display points (664-665) -> flip Y top-left->bottom-left (668) -> +displayFrame origin -> global AppKit (671-674). `screenN` indexes `screenCaptures` (cursor-sorted), fallback = cursor screen (640-646).
- Triggers flight via `detectedElementScreenLocation` -> `BlueCursorView.onChange` (`OverlayWindow.swift:371-386`).

**8. Two-stage grounding via ElementLocationDetector — DRIFTED: present but dead code.**
- File exists and matches description: aspect-matched CU resolutions 1024x768/1280x800/1366x768 with 1280x800 default (`ElementLocationDetector.swift:32-36,125-145`), clamp+scale+Y-flip at 103-118 (teardown's ~100-150 ~= right).
- **But**: `ElementLocationDetector` / `detectElementLocation` have **zero call sites** — never instantiated (verified by grep). The live pipeline is single-stage: the chat model emits `[POINT]` inline and `CompanionManager` scales it. The detector also calls `api.anthropic.com` **directly** with a raw `apiKey` (40,158) using the `computer_20251124` tool + `computer-use-2025-11-24` beta (163,183) — bypasses the Worker, and no key source exists in-tree. The "two-stage" pipeline is dormant, not live.

**9. Transient cursor mode — CONFIRMED as code, but unreachable in shipped UI.**
- Show on press when cursor disabled: `CompanionManager.swift:484-489`; hide after TTS-done + pointing-done + 1s: 732-756; 0.4s fade: `OverlayWindow.swift:819-835`.
- **Nuance**: the "Show Clicky" toggle is commented out of the panel (`CompanionPanelView.swift:52-59`), so `isClickyCursorEnabled` stays default-true -> transient path is dormant unless toggled via UserDefaults.

**10. PostHog incl. "POINT tag" event — CONFIRMED.**
- `ClickyAnalytics.swift:16-22` (hardcoded project key `phc_xcQP...` at 18 — shipped). `element_pointed` = the "response included a POINT tag" event (100-104). 13 events total; `user_message_sent`/`ai_response_received` include **full transcript/response text** (85-87,93-95). Email -> `identify` + FormSpark POST (`CompanionManager.swift:153-172`).

**11. Skills (~89 apps + ~100 community) — ABSENT.**
- No skill files, directories, loaders, app-matching, or browser-site registry anywhere in the tree (glob + grep clean). Skills exist only in the commercial product; the open-source tree has **no** skill mechanism. Teardown's caveat resolved: absent.

**12. Walkthroughs / draw-on-screen / routines — ABSENT.**
- No step-guide/walkthrough mode, no annotation/draw overlay, no routine recording. Zero synthetic input: no `CGEventPost`/`AXPress`/event synthesis anywhere — pointing is **visual only** (fly + bubble; user clicks). Verified via grep for event-synthesis/AX-press APIs: only `NSSpeechSynthesizer` matched.

## What the teardown missed (adoptable mechanics)

- **Barge-in**: new PTT press cancels `currentResponseTask` and stops TTS mid-sentence (`CompanionManager.swift:494-497`, `587-588`). Simple task-cancel model; also cancels the not-yet-started dictation task on quick release (513-535 — fixes stuck-overlay race).
- **Context windowing**: `conversationHistory` capped at last 10 exchanges, `[POINT]` tags stripped before storage (`CompanionManager.swift:684-694`); history is text-only — screenshots are never retained in context (115-118 of ClaudeAPI builds only the current turn's images).
- **STT end-of-utterance protocol**: key-up -> `requestFinalTranscript()` -> AssemblyAI `ForceEndpoint` (`AssemblyAI...Provider.swift:198-206`); 1.4s explicit-final grace (113,349-365); session-level fallback 2.8s (115), manager default 2.4s (`BuddyDictationManager.swift:219,491-511`); turn stitching by `turn_order` preferring formatted turns (273-347); WS error mid-finalize -> deliver best partial (392-408).
- **Voice-native error surface**: on API/TTS failure it *speaks* "I'm all out of credits..." via `NSSpeechSynthesizer` — works even with ElevenLabs down (`CompanionManager.swift:761-766`). Textual errors surface via `lastErrorMessage` + `currentPermissionProblem` (`BuddyDictationManager.swift:236-237`) and deep-link the right Settings pane (834-848).
- **Permission machinery**: 1.5s polling (`CompanionManager.swift:415-420`); system-prompt-once-then-Settings pattern (`WindowPositionManager.swift:39-61,113-130`); dedupe concurrent mic requests + 1s post-grant cooldown trusting cached status (`BuddyDictationManager.swift:763-788`); `CGPreflightScreenCaptureAccess` false-negative workaround via persisted "previously confirmed" flag (`WindowPositionManager.swift:91-103`); screen-content grant triggered by a dummy 320x240 capture then persisted (`CompanionManager.swift:358-396`).
- **Coordinate tricks**: label images with their pixel dims so the model's coordinate space is self-describing (`CompanionManager.swift:600-606`); `SCDisplay`->`NSScreen` reconciliation via `NSScreenNumber` (`CompanionScreenCaptureUtility.swift:47-58`); Retina-safe resize via `NSBitmapImageRep` not `lockFocus` (`ElementLocationDetector.swift:270-322` — worth salvaging even though caller is dead).
- **No rate limiting / retries**: nothing throttles PTT beyond `isDictationInProgress` (`CompanionManager.swift:476`); single-attempt calls — failure goes straight to the voice fallback.
- **UX/animation recipes**: 60 Hz `Timer` cursor-follow + quadratic-bezier flight with tangent-rotation and scale pulse (`OverlayWindow.swift:411-443,495-568`); pointing bubble with variable-speed char streaming + 3s hold + fly-back cancelable by >100px mouse move only on return (420-430, 570-648); waveform = RMSx10.2 boost, 0.72 decay, 44-sample history @70 ms (`BuddyDictationManager.swift:687-734`); cursor-rect bridging for native pointer/i-beam over SwiftUI (`DesignSystem.swift:764-818`); TLS-warmup HEAD + non-ephemeral session for TLS tickets (`ClaudeAPI.swift:21-37,66-96`); STT keyterms vocabulary (`BuddyDictationManager.swift:652-685`); PCM16 converter + WAV builder (`BuddyAudioConversionSupport.swift`).
- **AX write path**: `shrinkOverlappingFocusedWindow` reads/resizes the frontmost app's focused window via `AXUIElementCopyAttributeValue`/`AXUIElementSetAttributeValue` (`WindowPositionManager.swift:188-251`) — vestigial, but a working AX position/size read-write example.
- **Onboarding demo pattern**: Mux HLS video inside the overlay + 40 s `addBoundaryTimeObserver` fires a real pointing demo with a tighter "center-20-80%" POINT prompt (`CompanionManager.swift:829-880,950-1025`).
- **Misc**: auto-registers as login item via `SMAppService.mainApp` (`leanring_buddyApp.swift:63-73`); Sparkle dep wired but `startSparkleUpdater()` commented out (53) and `SUFeedURL` still points at the old `julianjear/makesomething-mac-app` repo (`Info.plist:8`).
- **Dead/stale code inventory**: `ElementLocationDetector` (unused), `CompanionResponseOverlay{,Manager}` (superseded — comment `CompanionManager.swift:68-69`), `OpenAIAPI` (no callers), `enter.mp3`/`eshop.mp3` assets, `speechToTextProviderRow`/`showClickyCursorToggleRow`/`updateContextualKeyterms` unused, `pinMainWindowToRight`/`shrinkOverlappingFocusedWindow` vestiges. `leanring-buddy/AGENTS.md` documents three files (`FloatingSessionButton.swift`, `ContentView.swift`, `ScreenshotManager.swift`) that **do not exist** — stale doc.
- **Security note for porters**: hardcoded PostHog key (`ClickyAnalytics.swift:18`) + full transcript/response bodies to analytics; Mux stream URL and FormSpark endpoint shipped.
