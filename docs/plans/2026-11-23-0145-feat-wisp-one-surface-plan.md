---
title: Wisp One Surface - Plan
type: feat
date: 2026-11-23
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
supersedes: docs/plans/2026-10-31-1754-feat-wisp-ui-overhaul-plan.md (units U6, U7, U8 only)
---

# Wisp One Surface - Plan

## Goal Capsule

- **Objective:** every place Wisp appears says the same thing about what it is doing, with the same words, marks and controls. The bar, the Panel, the settings window, the on-screen overlay, and any other shell that shows Wisp all agree. Old duplicate surfaces are gone.
- **Means:**
  - one status model and one kit on the settled theme;
  - the Panel trimmed to a scrolling Quick tab;
  - the console's views moved into the settings window, then the console retired;
  - one brand mark and icon set, with unused assets and code removed;
  - a published contract for other shells to show Wisp;
  - construction rules enforced by tests.
- **Authority:** this plan; `AGENTS.md`; the overhaul plan for units U1-U5, U9 and U10.
- **Stop conditions:**
  - a change regresses the Panel quick settings or the bar on the owner's desktop;
  - a removal deletes something a shipped surface still uses;
  - a unit needs a dependency Omarchy does not ship.
- **Execution profile:**
  - one unit per PR, in the order below;
  - verify with the offscreen snapshot harness, the QML suites and the full unit suite;
  - live checks on both monitors are owner gates recorded in each PR, not merge blockers.

---

## Product Contract

### Summary

Wisp grew surfaces one at a time, and each picked its own words and marks. The bar pill says "acting" where the Panel says "working", and transcribing reads "thinking" on the bar but "hearing you" elsewhere. Three files map status to visuals. The console window duplicates views that now belong in the settings window. The Panel's 19-field Settings tab duplicates the settings window. The brand has two marks: the orange flame on the app icon and bar, and a teal droplet in the site stills. This plan makes Wisp one product across all of them, keeps the theme that shipped on 2026-11-16, and removes what the new surfaces replace.

### Problem Frame

- **Duplicated state mapping.** Status-to-word, tone and glyph live in `lib/copy.js` (STATUS), `lib/bar.js` (`_pillState` with `ui.bar.state.*`), `lib/metrics.js` (MARK_ICON, MARK_TOKEN) and `lib/creature.js` (`stateFor`, TONE). So the bar pill and its own tooltip can name the same status differently.
- **Old surfaces.** `shells/debug` (876 lines) duplicates Home/Activity/Memory/Agents/Health/Spend/Audit/Binds, and its `svc.run(...)` calls are broken (`run` is a view model, not a function). The Panel's `SettingsTab` (340 px fixed width) duplicates the settings window.
- **The Panel does not scroll.** Its banners take height from every tab.
- **Two type systems.** The old `M.font`/`M.spacing` blocks are used in 34 and 38 component files. The new scale is used only by the settings window.
- **Dead weight:**
  - 12 icons with no reference;
  - 7 copy keys with no reference;
  - two lib functions with no caller anywhere;
  - teal droplet exports that only the site build uses.
- **No contract for other shells.** Another shell that wants to show Wisp has no published way to do it beyond reading internals.

### Requirements

- R1. One status model. For every daemon status, one table defines the word, tone, mark glyph, bar treatment and creature state. Every surface reads it, so no surface shows a different word for the same status.
- R2. One kit and one type scale. Every surface is built from the shared kit and the `M.scale` type and spacing steps. The old `M.font`/`M.spacing` blocks are removed.
- R3. The Panel scrolls when its content is taller than the card. Banners no longer take height from every tab. The Settings tab becomes a Quick tab: status summary, the quick toggles and "Open settings". The Panel header carries "Open settings" on every tab.
- R4. The settings window holds the Status pages (health, spend, audit, binds) and the management pages (home, activity, memory, agents). The console app (`shells/debug`) and its launcher entry are removed, and the launcher's main entry opens the settings window.
- R5. One brand mark: the orange flame. The teal droplet exports are retired, the site uses flame renders, and README screenshots come from the snapshot harness.
- R6. Nothing unused ships. Icons, copy keys, lib functions, components and assets with no production or test use are removed, and tests keep it that way.
- R7. A documented embed contract lets any shell show Wisp: live state and tasks from `wispd watch`, actions through CLI verbs, presence and version checks. It is stable and covered by a contract test.
- R8. Construction rules are tests:
  - every shipped surface has scenes for each of its states, in light and dark;
  - every interactive control in a scene has an accessible name;
  - surface words come only from the status table;
  - unused-asset and unused-key checks run in CI.
- R9. The settled theme stays: Wisp brand ink/paper surfaces with the Omarchy accent and ember, light and dark following Omarchy, font unchanged.

### Key Decisions

- **Unify, keep the theme.** (session-settled: user-directed, 2026-11-23. Chosen over a new visual direction and over "unify plus a new mark".) The theme shipped in #407 stays. Governs R1, R2, R9.
- **Deprecate the console app, the Panel Settings tab, duplicate status surfaces, the teal droplet stills, and anything unused.** (session-settled: user-directed.) Governs R3-R6.
- **Other shells read Wisp through its CLI, not its QML.** (session-settled: user-approved scope: "Wisp ships a small public embed contract".) Wisp components need `WispService`, `qs.Commons` tokens and `qs.Ui`, which other shells do not host. Governs R7.
- **One unit per PR; live checks are owner gates.** (session-settled: user-directed, 2026-11-16.)

### Scope Boundaries

- Not here: the TUI and CLI output units (overhaul plan U9, U10); a new palette, font or mark; new features in the bar or overlay beyond unifying them.
- Any shell that consumes the embed contract (R7) builds its own view in its own repository. This plan only publishes and tests the contract.

---

## Planning Contract

- **KTD1. One status table, with Python as the source of truth.**
  - **Source:** `wisp/status.py` (new), next to `wisp/copy.py`.
  - **Generated copy:** `shell-plugin/lib/status.js` (`.pragma library`, no colours), produced by `scripts/assets/gen_status.py` with a `--check` mode, the same pattern as `gen_copy.py`.
  - **Keys:** daemon status plus the derived states the bar computes (needs-you, stale, offline).
  - **Each entry holds:** the copy key of the main word, the copy key of the short word, tone token, mark glyph, bar pill treatment (shown or hidden, cause line) and creature state. Words are copy keys; the text lives in `wisp/copy.py`.
  - **Short words:** a short word must equal the main word or a prefix of it (for example "hearing" for "hearing you"), so the bar can never name a status differently.
  - **Replaces:** the QML consumers of `copy.js` STATUS, `bar.js` `_pillState` words and tokens, `metrics.js` MARK_ICON/MARK_TOKEN, `creature.js` `stateFor`/TONE, and the CLI's `copy.word_view` status lookups.
  - Rationale: four maps drift (see Problem Frame), and the CLI is Python. One table, generated for QML and drift-tested, can be checked against every surface.
- **KTD2. The settings window turns the daemon stream on while a Status or management page is shown.** Overhaul U4 (settings window host) turned it off because settings pages need only config. Status pages need health, spend and tasks, which the stream feeds. The window keeps the stream on while such a page is open and off otherwise, so idle settings use stays cheap.
- **KTD3. The type scale rollout is mechanical and goes surface by surface.** Every `M.font.*` and `M.spacing.*` use maps to an `M.scale` step through one documented table. Goldens are regenerated per surface, and the old blocks are deleted in the last PR. Hit targets follow `M.controlHeight`.
- **KTD4. Deprecation removes, it does not shim.**
  - `shells/debug` is deleted after its views move. `wispd install` rewrites the launcher entry, and the changelog notes the move.
  - Before deleting, `tests/test_manage.py` is retargeted to `shells/settings`.
  - Unused items are removed with their tests.
  - The flame site build switches to the orange flame mark renders.
- **KTD5. The embed contract is documented in `docs/EMBED.md` and pinned by a test.**
  - **Read path:** `wispd watch state tasks` NDJSON (versioned by `contract_version`, additive changes only); `wispd status --json`, where exit 3 means the daemon is down.
  - **Actions:** `wispd trigger [start|stop]`, `wispd interrupt`, `wispd choice <pick> [--prompt-id ID]`, `wispd settings [--category]`.
  - **Words:**
    - `wispd status --json` carries `word` and `tone` from the KTD1 table.
    - When the daemon is down it still prints JSON (`{"status": "offline", "word": ..., "tone": ...}`) with exit 3, so a host never hardcodes the offline word.
    - `wispd status --table --json` prints the whole KTD1 table resolved to text, including the derived needs-you, stale and offline states. It works with no daemon, so a host can show the same words for states it computes itself.
  - `tests/test_embed_contract.py` asserts every documented field and verb exists in the CLI registry and the IPC contract.
- **KTD6. The construction rules come from how strong desktop apps are built** (named scenes for every state, drift tests both ways, accessible names in every scene, unused checks). They are applied as tests in this repository, not as advice.

---

## Implementation Units

### U1. One status model

**Goal:** every surface reads one status table. The bar pill, tooltip, status line, overlay pill, bubble, buddy and mark agree.
**Requirements:** R1, R8.
**Dependencies:** none.
**Files:**
- `wisp/status.py` (new), `scripts/assets/gen_status.py` (new), `shell-plugin/lib/status.js` (new, generated)
- `shell-plugin/lib/bar.js`, `shell-plugin/lib/metrics.js`, `shell-plugin/lib/creature.js`, `shell-plugin/lib/buddy.js`, `shell-plugin/WispService.qml`
- `shell-plugin/components/BarPill.qml`, `Mark.qml`, `StatusLine.qml`, `Pill.qml`, `Bubble.qml`
- `wisp/copy.py` and the generated `shell-plugin/lib/copy.js`
- `tests/qml/lib/tst_status.qml` (new), `tests/qml/lib/tst_bar.qml`, `tests/qml/lib/tst_creature.qml`, `tests/test_components.py`, the snapshot goldens

**Approach:**
- Build `wisp/status.py` from today's four maps, and generate `status.js` from it. Where the maps disagree, the copy STATUS word wins, because it is the plain-language word the Panel and overlay already use. Examples: acting reads "working", awaiting_choice "your call", transcribing "hearing you".
  - The bar's short word sits in the same row and must be the main word or a prefix of it ("hearing", "your call", "working"). The old bar words "acting", "thinking" for transcribing, and "needs you" go away.
  - Error cause words (bar.js `CAUSE`) move into the table's error rows.
- Point `bar.js`, `metrics.js` (MARK_*), `creature.js` (`stateFor`, TONE) and `buddy.js` at the table. Delete the replaced maps and `metrics.creatureToken`.
- `WispService.statusWord`/`statusTone`/`wordView` derive from the table.

**Test scenarios:**
- For every status in `copy.js` STATUS, `status.py` has an entry. Every surface (bar pill, tooltip, StatusLine, overlay Pill, Bubble, Buddy) shows that entry's main or short word.
- Every short word equals its main word or is a prefix of it.
- `gen_status.py --check` fails when `status.js` is stale.
- Transcribing reads "hearing you" on the overlay and the Panel, and the bar's short form reads from the same entry.
- No QML or JS file outside `status.js` maps a status string to a word, tone or glyph. This is a static check over `shell-plugin/`.
- The bar's idle and offline states still hide the pill.

**Verification:** QML suites, `test_components`, full unit suite, snapshot goldens regenerated for the changed surfaces and reviewed in light and dark.

### U2. Panel scroll and Quick tab (absorbs overhaul U6)

**Goal:** the Panel scrolls, its banners stop taking height from every tab, and Settings becomes a Quick tab with "Open settings".
**Requirements:** R3.
**Dependencies:** U1.
**Files:**
- `shell-plugin/Panel.qml`
- `shell-plugin/components/PanelBody.qml` (new, window-free), `QuickTab.qml` (new); `SettingsTab.qml` (removed)
- `shell-plugin/components/StatusLine.qml`, `NowTab.qml`, `DevTab.qml`
- `wisp/copy.py` and the generated `shell-plugin/lib/copy.js` (new words: the Quick tab label, "Open settings", the offline note)
- `scripts/ui/snap.py` (tolerance entry), `scripts/ui/readme_media.py` (the Panel still swaps `SettingsTab__ok` for a Quick tab scene)
- Tests: `tests/qml/lib/tst_panel.qml` (new), `tests/qml/lib/tst_settings.qml`, `tests/test_components.py`, `tests/test_copy_lint.py`, `tests/test_dev_tab.py`, `tests/test_rate.py`, `tests/test_wisp_service.py` (their `Panel.qml` source assertions follow the markup into `PanelBody.qml`), `tests/qml/harness/scenes.json`, the snapshot goldens

**Approach:**
- `Panel.qml` imports `qs.Commons` and `qs.Ui` (its `KeyboardPanel` host), which `qmltestrunner` and the snapshot harness cannot load. So the header, tab row, banners and tab bodies move into a window-free `PanelBody.qml` that takes the service and the Panel's data as properties and emits its actions as signals. `Panel.qml` keeps the host and the skills, decisions, onboarding and what's-new plumbing, and sizes the card from `PanelBody`. `tst_panel.qml` and the new scenes drive `PanelBody` against `FixtureService`.
- With `SettingsTab` gone, `Panel.qml` drops what only it used: the `connectors` property, `connListProc`, `connRunProc`, `loadSettings()` and the tab-3 load hooks. On open the Panel reads config only (`service.loadConfig()`). Connectors stay in the settings window. `WispService.loadSettings()` (the cua and spend reads) stays for the console until U3 removes it.
- Wrap the tab area in `ScrollPage`, capped by `fittedContentHeight`. Tab bodies stay in a `Column` with per-tab `visible`, as today, so only the shown tab counts toward height. A `StackLayout` sizes to its tallest child, hidden ones included, so it is not used.
- What's-new, first-run and recap banners move into the Now tab's scroll area and stay dismissible.
- `QuickTab` shows:
  - a health summary: one clickable row built from `health.js` `sections(service.health)` (all ok, or how many checks are down), led by the status table word when the daemon is offline or stale. It does not embed `HealthSection`, so the Panel makes no cua or spend reads. A click opens the settings window. `health` is not a `--category` choice until U3 adds the Status pages, so in U2 the click runs `wispd settings` with no category; U3 retargets it to `--category health`.
  - every schema field marked `quick`, in schema order and grouped by schema group as the old tab was, through the overhaul plan's U3 controls (toggle, number, choice) with its U5 write path, so values are in schema format and one write runs at a time.
- Quick tab states:
  - **Offline:** the summary shows the table's offline word, with a one-line note that changes are saved to the config file and apply when Wisp starts. The fields stay enabled: `wispd config set` writes `config.toml` with no daemon, and the settings window behaves the same way.
  - **Loading:** a loading line while `configLoaded` is false.
  - **Read failed:** when `configReadError` is set, the error shows on one line with a Retry that calls `service.loadConfig()`, and the fields are disabled until a read succeeds.
  - **Failed write:** the daemon's error shows inline on the row, and the control returns to the saved value.
- Scrolling resets to the top on tab switch. PageUp, PageDown, Home and End scroll the Panel.
- The header is the `StatusLine` row with an "Open settings" chip at its right edge on every tab; the status notice elides first when the row is tight. The chip runs `wispd settings` detached, never through `runAction`, then closes the Panel.
- `DevTab` drops its 340 px width and scrolls.

**Test scenarios:**
- With content taller than the card, the Panel scrolls and the header stays fixed.
- A hidden tab does not add height: with a tall Quick tab, the Now tab's body height follows Now alone.
- The Quick tab shows every quick field, and changing one calls `configSet` once with the formatted value.
- "Open settings" runs `wispd settings` detached from every tab and closes the Panel, and the health summary opens the settings window (U3 adds `--category health`).
- Offline: the summary shows the offline word and the note, and the fields stay enabled. Read failed: the error and Retry show, and the fields are disabled. A failed write shows the error inline, and the control returns to its saved value.
- Switching tabs resets scroll to the top.
- Banners appear only on Now and can be dismissed.
- Scenes for the Panel body (each tab, offline, read failed) and the header at the narrow viewport with the offline notice showing, in light and dark.

**Verification:** QML suites, full unit suite, goldens at both viewports.

### U3. Status and management pages in the settings window; retire the console (absorbs overhaul U7)

**Goal:** the settings window holds every view the console had, and the console is removed.
**Requirements:** R4.
**Dependencies:** U1. U2 (so the Panel's "Open settings" exists before the console goes).
**Files:**
- `shells/settings/shell.qml`
- `shell-plugin/components/SettingsHost.qml`, `SettingsPage.qml`, `HealthView.qml`, `SpendView.qml`, `AuditView.qml`, `BindsView.qml`
- `shell-plugin/WispService.qml`
- `shells/debug/` (removed); `shells/settings/Commons` (becomes a real directory)
- `assets/desktop/wisp.desktop`, `wisp/desktop.py`, `wisp/tui.py` (docstring), `wisp/cli/settings_window.py` (`--category` accepts the new pages)
- `scripts/release/verify.py` (required files move to `shells/settings`)
- Tests: `tests/test_manage.py` (retargeted), `tests/test_desktop.py`, `tests/test_copy_lint.py`, `tests/test_release_packaging.py`, `tests/test_install_release_edges.py`, `tests/test_tui_render.py`, `tests/test_svc.py`, `tests/test_wisp_service.py`, `tests/test_settings_window.py`, `tests/qml/lib/tst_settingshost.qml`
- Docs: `INDEX.md`, `docs/DEV_MODE.md`, `DESIGN-v2.md`, `CHANGELOG.md`

**Approach:**
- **Sidebar order:** Home, Activity, Memory, Agents; then the settings categories; then a Status group (Health, Spend, Audit, Binds). The launcher opens Home. `wispd settings --category <page>` deep-links to any page, and the Panel health summary (which opens the window with no category in U2) switches to `--category health`. Views reflow to the page width; the console's fixed sizes do not carry over.
- **Page states.** Every Status and management page uses the shared `EmptyState` with words from copy:
  - first-event loading;
  - daemon offline (with Retry);
  - stale;
  - empty list;
  - partial or error.
- **Keyboard:** Tab and the arrow keys reach the sidebar and the page. Focus moves to the page heading on page change.
- Fix the `svc.run(...)` calls by using `runAction`.
- KTD2: the stream turns on while a Status or management page is open.
- Move `Commons` into `shells/settings`. Retarget `test_manage.py`, then delete `shells/debug`.
- The launcher's main entry opens `wispd settings`. The now-redundant Panel action is removed, and Listen, Stop and Settings stay.

**Test scenarios:**
- Each Status and management page renders from fixture data in light and dark, and in each of its states: loading, offline, stale, empty and error.
- `wispd settings --category health` opens Health. Focus lands on the page heading after a page change.
- A release tarball verifies with no `shells/debug` members, and an upgrade removes the old installed `shells/debug` directory.
- Restart and stop actions call `runAction` with the expected verbs.
- An audit page with 50 rows scrolls and keeps column alignment at 720 px.
- No file references `shells/debug` after removal except the changelog.
- The rendered desktop entry's main Exec runs `wispd settings`, and there is no Panel action.
- A repository-wide search finds no `shells/debug` reference except the changelog.
- `test_manage` parity checks pass against `shells/settings`.

**Verification:** QML suites, `test_manage`, `test_desktop`, full unit suite, goldens.

### U4. One type scale (absorbs overhaul U8; three PRs)

**Goal:** every surface uses the `M.scale` type and spacing steps, and the old blocks are removed.
**Requirements:** R2.
**Dependencies:** U2, U3 (fewer files left to move).
**Files:** `shell-plugin/lib/metrics.js`; the component files using `M.font`/`M.spacing` (bar and overlay first, then Panel tabs and cards, then the rest); `tests/qml/lib/tst_metrics.qml`; the goldens.

**Approach:**
- Write one mapping table (old step to `M.scale` step) in the first PR. Move surfaces in batches and regenerate goldens per batch.
- The last PR deletes `M.font`/`M.spacing` and adds a static check that they stay gone.

**Test scenarios:**
- No component reads `M.font.` or `M.spacing.` after the last PR.
- Text sizes follow `textScale`; hit targets do not.
- The bar pill stays within its bar height at text scale 2.

**Verification:** QML suites, goldens per batch reviewed in light and dark, full unit suite.

### U5. One mark, and nothing unused

**Goal:** the orange flame is the only mark, and no unused icon, copy key, function, component or asset ships.
**Requirements:** R5, R6, R8.
**Dependencies:** U1-U3, so removal runs after the moves. It can land alongside U4.
**Files:**
- `assets/brand/wisp-flame/`, `scripts/site/build.py`, `scripts/site/build_3d.py`, `tests/test_wisp_flame_asset.py`
- `assets/icons/src/*.svg`, `shell-plugin/lib/icons.js` (regenerated)
- `wisp/copy.py`, `shell-plugin/lib/copy.js`, `shell-plugin/lib/*.js` (dead functions)
- `assets/readme/*.png`, `README.md`
- `tests/test_unused.py` (new)

**Approach:**
- Retire `assets/brand/wisp-flame/`, the cyan 3D flame, with its render scripts, loops and stills.
- The site switches to the orange flame:
  - stills come from `assets/icons/hicolor` PNGs;
  - the animated hero loop is dropped for a static mark;
  - `FLAME_STILLS` in `scripts/site/build.py` and `BRAND` in `scripts/site/build_3d.py` are updated.
- Remove the unused icons and copy keys found by the scan (re-run it at implementation time) and the dead lib functions.
- Regenerate README screenshots from the snapshot harness (a `snap.py` export of named scenes).
- `test_unused.py` fails on an icon source, copy key or lib export with no use outside its own definition. It keeps a small, explicit allow-list for keys built by prefix.

**Test scenarios:**
- Every icon in `assets/icons/src` is referenced by name.
- Every `STRINGS` key is used by QML, JS or Python (prefix families declared).
- The site build references only existing files.
- README images match the current snapshot scenes.

**Verification:** full unit suite, the site build dry run, goldens.

### U6. Embed contract for other shells

**Goal:** any shell can show Wisp live and act on it through a documented, tested contract.
**Requirements:** R7.
**Dependencies:** U1 (status words from the table).
**Files:** `docs/EMBED.md` (new), `wisp/cli/core.py` (`word`/`tone` in `status --json` and in the watched state, offline JSON on exit 3, `--table` from `wisp/status.py`), `docs/IPC_CONTRACT.md`, `tests/test_embed_contract.py` (new), `tests/test_cli.py` goldens.

**Approach:**
- Document the read path, the actions, presence, and versioning (KTD5).
- Add the status word and tone from the KTD1 table to `wispd status --json`, and to the watched state, if they are not already there, so hosts never copy the table.
- Include a minimal worked example of a host following `wispd watch state tasks`.

**Test scenarios:**
- Every verb and field in `EMBED.md` exists in the CLI registry and the IPC contract.
- `wispd status --json` carries `word` and `tone` matching `wisp/status.py` for each status fixture.
- With the daemon down it prints the offline JSON and exits 3.
- `--table` lists every status and derived state with its text.

**Verification:** full unit suite, CLI goldens.

### U7. Construction rules as tests

**Goal:** the rules that keep the surfaces consistent are failing tests.
**Requirements:** R8.
**Dependencies:** U1. It can run any time after U1 and is tightened as units land.
**Files:**
- `tests/qml/lib/tst_accessible.qml` (new: walks each scene and checks every interactive control has an `Accessible.name`)
- `tests/test_components.py`: extend the existing `test_every_component_has_a_scene` only where it does not already cover both themes. The status-word guard lives in U1.
- `AGENTS.md` (a short "how surfaces are built" section pointing at these tests)

**Test scenarios:**
- A control with no accessible name fails the scan.
- Every interactive control in the settings window and Panel scenes shows a visible focus ring when focused.

**Verification:** QML suites, full unit suite.

---

## Phased Delivery

| PR | Unit | Delivers |
|---|---|---|
| 1 | U1 | One status model. |
| 2 | U2 | Scrolling Panel with a Quick tab. |
| 3 | U3 | Status and management pages in the settings window; console removed. |
| 4-6 | U4 | One type scale, in batches. |
| 7 | U5 | One mark; nothing unused. |
| 8 | U6 | Embed contract. |
| 9 | U7 | Construction rules as tests (may land earlier, after U1). |

---

## Verification Contract

| Gate | Check | Applies to |
|---|---|---|
| Unit suite | `python3 -m unittest discover -s tests` | all |
| QML suites | the CI qml job's modules | all |
| Snapshots | `scripts/ui/snap.py check` with 0 differences after a reviewed `update` | U1-U5, U7 |
| Live check (owner gate) | the bar, the Panel and `wispd settings` on both monitors | U1-U3 |

## Definition of Done

- R1-R9 hold.
- The overhaul plan's U6-U8 are marked superseded by this plan.
- Each PR records its owner live-check status.

## Sources

- The overhaul plan (U1-U5 shipped: #288, #410, #411, #420).
- Snapshot contact sheets of every current surface, taken at master 8663bae.
- A study of how a strong open-source desktop app structures scenes, registries, onboarding and drift tests (KTD6).
