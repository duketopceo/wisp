---
title: Raycast teardown and Linux plan (Vicinae runtime + OpenRouter AI layer + top-extension ports)
type: feat
date: 2026-10-16
target_repo: proposed new repo `duketopceo/omarchy-ray` (name open); no existing repo owns this
---

# Raycast teardown → Linux plan on OpenRouter

## Summary

Raycast has no Linux build. Vicinae already is the Linux launcher with a
Raycast-compatible extension runtime. Building another launcher is wasted
work. The gap is Raycast's **AI layer**: Quick AI, AI Chat, AI Commands,
AI Extensions (tools), MCP servers, permissions, and screen awareness. The
plan builds that layer as Vicinae extensions on OpenRouter, and ports or
replaces the top-ten store extensions where they are macOS-bound.

Unit IDs are `R0`–`R7`. They never renumber.

## Provenance

- **documentation-based**: Raycast manual and developer docs; Raycast
  store popularity page; Vicinae docs and repository.
  - https://manual.raycast.com/ai/ai-extensions
  - https://manual.raycast.com/ai/model-context-protocol
  - https://developers.raycast.com/ai/learn-core-concepts-of-ai-extensions
  - https://developers.raycast.com/ai/provide-ai-models
  - https://www.raycast.com/store/popular
  - https://docs.vicinae.com/ , https://github.com/vicinaehq/vicinae
- **source-assisted** (available, not yet read in depth): `raycast/extensions`
  monorepo (MIT) for the top extensions. R6 reads each before porting.
- Not done: no inspection of the Raycast binary. Internal model routing
  and the "Ray-1" model are treated as opaque.

## Research Findings

### A. Raycast AI surface (documentation-based, high)

- **Quick AI**: one-off answer from root search (Tab), now chat-style with
  follow-ups, attachments and a handoff to AI Chat.
- **AI Chat**: multi-turn with persistent history, attachments, tools;
  agentic mode plans, uses extensions, writes and runs code, asks when it
  needs a decision.
- **AI Commands**: built-in and custom prompts acting on selected text or
  clipboard (improve writing, summarize, explain).
- **AI Extensions**: an extension declares `tools[]` in `package.json`;
  each tool is a typed function with a description the model reads; an
  optional `confirmation` function previews the action before it runs.
  Users `@mention` extensions in Quick AI, Chat, or root search ("Ask …").
- **MCP**: stdio and HTTP servers installed from a form; `@server` scoping;
  an "Ask <server>" root command per server.
- **Permissions** (Settings → AI → Tools): Ask, Auto (default on paid),
  Always Allow; per-call "Allow / Always allow" with "Show Command" for
  shell.
- **Built-in AI extensions**: `@screen-awareness` (front app, selection,
  window screenshot), `@terminal`, `@file-explorer`, `@selected-text`.
- **Send Element to AI**: hover an on-screen element and send it to chat.
- **Extension-provided models**: extensions can serve models; Raycast
  passes tool definitions and expects AI-SDK tool-call parts in the
  stream. Pro only.
- Models: multiple providers, BYOK for some, Ollama for local.

### B. Store popularity, top ten (documentation-based, high)

| Rank | Extension | Downloads | macOS only | Linux path |
|---|---|---|---|---|
| 1 | Kill Process | 782,504 | no | port; `/proc` or `procps` |
| 2 | Color Picker | 621,457 | no | port UI; picker via `hyprpicker` |
| 3 | Google Chrome | 575,219 | yes | replace: CDP against Chromium remote debugging |
| 4 | Google Translate | 502,115 | no | likely runs as-is |
| 5 | Spotify Player | 494,654 | no | runs via Web API; menu bar part dropped |
| 6 | Visual Studio Code | 415,828 | no | port: Linux `storage.json` paths, `code` CLI |
| 7 | Linear | 405,528 | no | likely runs as-is; also an AI extension |
| 8 | Slack | 338,181 | no | likely runs as-is |
| 9 | Brew | 297,755 | yes | replace: `pacman`/`yay`/AUR extension |
| 10 | Notion | 282,958 | no | likely runs as-is |

"Likely runs as-is" is moderate confidence; Vicinae's own compatibility
notes say support is partial and simpler extensions work best. R6 verifies
each on a real install.

### C. Vicinae (documentation-based, high)

- GPL-3.0, C++ and Qt, Linux first with Wayland focus; macOS and Windows
  builds exist. Raycast extensions run through a custom React reconciler
  and `@vicinae/api`; the Raycast store is browsable in-app; script
  commands and dmenu mode are supported.
- Built-ins: app search, clipboard history, snippets, file search, browser
  tab switcher, emoji picker, calculator, window and workspace switching,
  font browser, volume. No kill-process built-in is documented.
- Whether Vicinae exposes a Raycast-style `AI` API or `tools[]` runtime is
  **unknown**. R0 resolves this first.

### D. Verdicts

- Do not build a launcher (high). Vicinae exists, is GPL, and already
  speaks the Raycast extension format.
- The AI layer is the real gap and is cleanly separable: it is an
  extension plus a small local daemon (moderate).
- The "all OpenRouter" constraint is a feature: one key, model picker from
  the OpenRouter catalog, spend ledger. wisp's ledger pattern applies.
- Counterargument: Vicinae may ship its own AI integration soon, making a
  third-party AI extension redundant. Mitigation: the tool layer is MCP, so
  it survives a runtime change; the daemon is launcher-agnostic.

## Key Technical Decisions

- **D1.** Runtime = Vicinae. Extensions written against `@raycast/api`
  where compatible, `@vicinae/api` where needed.
- **D2.** A local daemon `rayd` (TypeScript, Node 20+) owns OpenRouter
  calls, chat history (SQLite), MCP client connections, permissions, and
  the spend ledger. The extensions are thin views over a Unix socket.
- **D3.** Tools follow Raycast's `tools[]` manifest shape so third-party
  AI extensions can be loaded by `rayd` even if Vicinae never runs them
  natively. Internally every tool is exposed as an MCP tool.
- **D4.** Permissions: Ask, Auto, Always Allow, stored per tool; shell
  tools always preview the command. Auto uses a cheap classifier call for
  read-only detection; unknown → Ask.
- **D5.** Screen awareness on Hyprland: `hyprctl activewindow`, `grim`
  window crop, `wl-paste` selection; sent as image plus text to a vision
  model. No element-level "Send Element to AI" in v1.
- **D6.** Default models: a cheap fast model for Quick AI and commands; a
  strong model for agentic chat; both user-overridable from the
  OpenRouter catalog cached daily.
- **D7.** Repo: new, proposed `omarchy-ray`, MIT for extensions, with
  `rayd/`, `extensions/ai/`, `extensions/ports/*`.

## Implementation Units

### R0. Compatibility spike
- **Goal:** facts before code: what Vicinae runs and exposes.
- **Files:** `docs/spike-vicinae.md` with a matrix.
- **Checks:** install Vicinae on Omarchy; install each top-ten extension
  from the store; record works / partial / fails with the failing API;
  grep `@vicinae/api` typings for `AI`, `tools`, `environment` fields;
  confirm Node version and extension sandboxing.
- **Verification:** matrix committed; R6 scope set from it.

### R1. `rayd` daemon and OpenRouter client
- **Goal:** one local service for models, history, ledger.
- **Files:** `rayd/src/{server,openrouter,ledger,history,config}.ts`,
  `rayd/systemd/rayd.service`, `rayd/test/*`.
- **Behavior:** streaming chat completions; model catalog cache; per-day
  and per-month caps; history in SQLite; socket API versioned.
- **Test scenarios:** stream parse; cap refusal with a typed error;
  catalog refresh; history query by chat id.
- **Verification:** `curl --unix-socket` smoke and a 100-message soak.

### R2. Quick AI and AI Chat extensions
- **Goal:** Tab-to-ask and a persistent chat view inside Vicinae.
- **Files:** `extensions/ai/src/{quick,chat}.tsx`, `extensions/ai/package.json`.
- **Behavior:** Quick AI answers inline with follow-up; "open in chat"
  handoff; chat list, archive, model picker, attachments (clipboard,
  selection, file).
- **Test scenarios:** render with a fake socket; handoff preserves
  messages; model switch mid-chat recorded.
- **Verification:** screenshots in `docs/`.

### R3. AI Commands
- **Goal:** prompt presets on selected text or clipboard.
- **Files:** `extensions/ai/src/commands/*.tsx`, `extensions/ai/prompts/*.md`,
  user prompts in `~/.config/omarchy-ray/prompts/`.
- **Behavior:** built-ins (fix grammar, improve, summarize, explain code,
  translate); output actions: paste, copy, replace selection via `wtype`.
- **Test scenarios:** prompt file parse with frontmatter; replace-selection
  path on a fake clipboard.
- **Verification:** five presets demoed.

### R4. Tool layer: AI Extensions manifest and MCP
- **Goal:** `@mention` tools from extensions and MCP servers with
  permissions.
- **Files:** `rayd/src/tools/{manifest,mcp,permissions,runner}.ts`,
  `extensions/ai/src/mentions.tsx`, `extensions/ai/src/manage-mcp.tsx`.
- **Behavior:** load `tools[]` from installed extensions; connect stdio
  and HTTP MCP servers from a form; tool calls shown live; confirmation
  preview; Ask/Auto/Always Allow per tool; "Ask <server>" command per
  server.
- **Test scenarios:** manifest validation; permission table; a denied
  call never executes; MCP reconnect after server exit.
- **Verification:** Linear MCP server and a local filesystem server work
  end to end.

### R5. Screen awareness and terminal tools
- **Goal:** `@screen` and `@terminal` built-ins.
- **Files:** `rayd/src/tools/builtin/{screen,terminal,files,selection}.ts`.
- **Behavior:** screen tool captures the active window and selection;
  terminal tool always previews and requires approval unless Always Allow;
  files tool is read-only by default.
- **Test scenarios:** capture on a fake Hyprland socket; terminal preview
  text matches executed command; denied path refused.
- **Verification:** "what does this error mean" on a terminal window.

### R6. Top-ten ports and replacements
- **Goal:** the ten most-used extensions work on Linux.
- **Files:** `extensions/ports/{kill-process,color-picker,chromium,
  vscode,pacman}/`; upstream PRs where a small Linux branch suffices.
- **Behavior per row:** see table B; prefer upstream patches that add a
  Linux platform branch over forks.
- **Test scenarios:** each extension's own tests plus a Linux fixture.
- **Verification:** matrix from R0 updated to ten green rows.

### R7. Omarchy packaging
- **Goal:** one install on Omarchy.
- **Files:** `install.sh`, AUR or script-command bundle, `omarchy-plugins`
  catalog entry, Hyprland keybind snippet.
- **Verification:** clean-VM install under 10 minutes.

## Scope Boundaries

- No launcher core, no window manager features, no theming.
- No extension-provided-model API; `rayd` is the only model provider.
- No iOS or sync.
- No Raycast account features (notes sync, focus, cloud snippets).

## Risks

- Vicinae extension API gaps block R2 views. Mitigation: R0 first; fall
  back to `@vicinae/api` native components.
- Raycast store access runs through Raycast's servers and could be
  restricted. Mitigation: vendored copies of the ten extensions.
- OpenRouter has no realtime or image-generation parity for every Raycast
  AI feature. Out of scope and stated.

## Sources

Listed under Provenance.
