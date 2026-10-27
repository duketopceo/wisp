---
title: Open Mail When the Mail Handler Is a Browser - Plan
type: fix
date: 2026-10-26
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
---

# Open Mail When the Mail Handler Is a Browser - Plan

## Goal Capsule

- **Objective:** "Open my email" opens the owner's inbox. Today wisp focuses the already-running browser and reports "mail client focused", so the request fails silently. This is the top act failure in the labels: 3 of 9 failed act turns, and the owner hit it again on 2026-10-26.
- **Means:** When a role resolves to a browser, `launch` navigates that browser to the role's web app (mail defaults to Gmail) instead of focusing the window (U1). The roadmap records Q4 as settled (U2).
- **Authority:** Phase 9 of `docs/plans/2026-10-26-0031-feat-wisp-v1-roadmap-plan.md` (roadmap R3, R4). Tracker: Tallyline TLY-201.
- **Execution profile:** U1, then U2. Full Python suite green with no API keys in the environment.
- **Stop conditions:** Stop if the change would alter `rs/` or `tests/fixtures/ipc_commands.jsonl`.
- **Who finishes:** This run's PR.

---

## Product Contract

### Summary

On this machine `~/.config/mimeapps.list` maps `x-scheme-handler/mailto` to `browseros.desktop`, so `inventory.defaults()` resolves the `mail` role to BrowserOS. `wisp/tools/desktop.py` `launch()` then finds the BrowserOS window and returns `FOCUSED browseros (already running)`. The model reads that as success. The inbox is a Gmail tab, which wisp never opens.

### Requirements

- R1. When a role (`mail`, `calendar`) resolves to a web browser, `launch` opens that role's web URL in that browser and returns `OPENED <url> -> <browser>`. It does not focus the window and report success.
- R2. The role's web URL comes from config: `[web] mail` and `[web] calendar`. When a key is absent or empty, `mail` defaults to `https://mail.google.com` and `calendar` to `https://calendar.google.com`. That holds for existing config files without a `[web]` section.
- R3. A role that resolves to a native client (Thunderbird, Geary) behaves exactly as today: launch it, or focus it when it is already running.
- R4. The `launch` tool description says that a role served by the browser opens its web app, so the model stops inventing a separate tool for it.
- R5. The roadmap plan records Q4 as settled: Groq is the hosted STT default (owner, 2026-10-26, shipped in #146).

### Key Decisions

- **Gmail is the mail web app.** Governs R2. (session-settled: user-directed — chosen over Outlook/M365 and Hey.com, 2026-10-26.)
- **Groq is the hosted STT default.** Governs R5. (session-settled: user-directed — chosen over another OpenAI-compatible provider, 2026-10-26.)

### Scope Boundaries

- Out: the wrong-coordinate click pattern (4 labelled turns). Every one predates the 2026-10-25 verification ladder in `wisp/verify.py`. A labelled click turn after 10-25 is needed before planning a fix.
- Out: a bare URL opening through `xdg-open` rather than BrowserOS (1 turn). The data does not show what the owner rejected.
- Out: replacing the UI with Clacky's companion (owner direction, 2026-10-26). It gets its own plan.
- Not built: detecting which webmail is signed in inside the browser. Config is enough, and the owner named Gmail. Which Google account appears depends on the BrowserOS profile that is active; the live check in the Definition of Done covers it.
- Not built: a switch that turns the web-app behavior off. It would bring back the false "mail client focused" success this plan removes. A different webmail is set by overriding the URL.

---

## Planning Contract

### Key Technical Decisions

- KTD1. **A browser is recognized by its role mapping.** A resolved app counts as a browser when it equals the `browser` role's resolved app from `inventory.defaults()`, or is one of the known browser names (`browseros`, `chromium`, `google-chrome`, `firefox`, `brave`). No new detection layer.
- KTD3. **Defaults live in code.** `load_config` never merges defaults into an existing file, and the owner's config has no `[web]` section. A `WEB_DEFAULTS` dict and a `web_settings(cfg)` helper in `wisp/config.py` overlay the user's non-empty `[web]` values, mirroring `STT_DEFAULTS` and `stt_settings`. The config template documents the keys.
- KTD2. **Open in that browser, not `xdg-open`.** The browser binary is run with the URL as its argument. Chromium-family browsers, BrowserOS included, open it as a tab in the running instance, which matches the behavior of the existing `browser` branch.

---

## Implementation Units

### U1. Role web apps when the handler is a browser

- **Goal:** R1–R4.
- **Requirements:** R1, R2, R3, R4; KTD1, KTD2.
- **Files:** `wisp/tools/desktop.py` (`launch`), `wisp/tools/__init__.py` (the `launch` description), `wisp/config.py` (`WEB_DEFAULTS`, `web_settings`, `[web]` in the config template), `wisp/settings_schema.py` and regenerated `shell-plugin/lib/settings_schema.js` if `[web]` keys are schema fields, `docs/CONFIG.md` (including that `[web]` URLs cannot contain `#`, which the config parser treats as a comment), `tests/test_desktop.py`, `tests/fixtures/turns/act_open_mail.json` (required: roadmap R4 asks for one replay fixture per fixed pattern).
- **Approach:**
  1. After role resolution in `launch`, check whether the resolved app is a browser (KTD1) and `web_settings(cfg)` has a URL for the role (KTD3). If both hold, exec `<browser> <url>` behind the same `_wm_down` gate and return `OPENED <url> -> <browser>`.
  2. Leave every other path unchanged.
  3. Update the tool description.
- **Execution note:** Write the `tests/test_desktop.py` case first. It should fail today with `FOCUSED browseros`.
- **Patterns to follow:** the existing `browser`/BrowserOS branch and the URL branch in `launch`. Existing role tests in `tests/test_desktop.py` patch `inventory.defaults` and `_find_window`.
- **Test scenarios:**
  - `mail` resolves to `browseros` and a BrowserOS window is running → execs `browseros https://mail.google.com` and returns `OPENED https://mail.google.com -> browseros`, never FOCUSED.
  - Same, with no BrowserOS window running → still opens the URL in BrowserOS.
  - No `web` section in cfg at all → still opens `https://mail.google.com` (the owner's real config).
  - `[web] mail = "https://outlook.office.com/mail"` → opens that URL.
  - `mail` resolves to `thunderbird` → launches or focuses Thunderbird as today, with no URL.
  - `calendar` resolves to the browser → opens `https://calendar.google.com`.
- **Verification:** suite green with keys unset; `gen_settings --check` clean.

### U2. Record Q4 as settled in the roadmap

- **Goal:** R5.
- **Requirements:** R5.
- **Files:** `docs/plans/2026-10-26-0031-feat-wisp-v1-roadmap-plan.md`.
- **Approach:** Rewrite Q4 in place as settled (Groq, owner, 2026-10-26, #146).
- **Test scenarios:** Test expectation: none -- documentation only; `test_docs_lint` covers formatting.
- **Verification:** docs lint passes.

---

## Verification Contract

| Gate | Command | Applies to |
|---|---|---|
| Python suite (keyless, as CI) | `env -u OPENROUTER_API_KEY -u GROQ_API_KEY HOME=$(mktemp -d) python3 -m unittest discover -s tests` | U1, U2 |
| Generated settings | `python3 scripts/assets/gen_settings.py --check` | U1 |
| Parity | `git diff --quiet origin/master -- rs tests/fixtures/ipc_commands.jsonl` | all |

---

## Definition of Done

- R1–R4 are covered by unit tests and the `act_open_mail` replay fixture.
- Live check after deploy: "open my email" on this machine opens Gmail in BrowserOS, in the owner's signed-in account.
- The roadmap shows Q4 settled.
- Suite green without keys; parity untouched.
