---
status: "superseded by 2026-10-04-0100-feat-wisp-unified-plan.md"
---

# Wisp roadmap — refreshed 2026-10-02

Wisp: open-source, resident desktop AI companion. Push-to-talk → screen +
voice → conversational/agentic action on the actual desktop. Linux-first
(Omarchy/Hyprland), BYO providers (OpenRouter default; Jev for routing;
Ollama/LM Studio/OpenAI-compatible for brains; Codex/Claude/Devin/etc for
background agent runtimes).

## Where we are (shipped, on master, live)

Done in the last two days:

- Conversational agent core: screen captured at trigger and fed to the
  act loop; goal memory across utterances; confirm-once per (tool, app);
  `ASK_USER:` voice backchannel; `wisp agent` explicit-agent prefix;
  clarify demoted to launch-only.
- Local observability: decisions.jsonl, trace.jsonl, trajectories,
  labels/corrections, `wispd tele`, `wispd fails`, panel tabs
  (Now/Agents/Activity/Tele/Skills), TUI sections.
- Learning loop (auditable, no weights): trajectory memory, per-app
  action stats, labeled-soak corrections, human-gated recipe skills.
- Local-context passthrough: `inventory.json` — 103 apps, 239 CLI tools
  (incl. herdr), 24 MCP servers, 33 omarchy plugins + bindings, dayflow
  top-apps/projects/goals. `[env]`/`[windows]`/`[focus]` injected per
  turn; vocab primed from all of it.
- Platform seam: Linux primary; macOS daemon+tests green (deferred
  lane — revisit after Linux v1.0).
- Process: branch-per-PR, CI matrix (unit × 3, rust × 2), Argus review
  lane live on self-hosted runner.

Known gaps, in rough priority order.

## U1 — MCP access (agent can call servers, not just know they exist)

Inventory lists 24 MCP servers but the tool registry can't call them.
Add `mcp_call` tool: `arg = "server tool_name {json args}"`. Two
transports:

- **HTTP streamable** (browseros :9200, cloudflare suite, kurultai) —
  POST JSON-RPC `tools/call`, parse SSE/JSON response.
- **stdio** (omaseal, codebase-memory-mcp, dayflow?) — subprocess,
  initialize handshake, tools/call, terminate. Keep per-call for v1;
  no persistent sessions.

Risk tier: `mutating` by default; read-mostly servers (docs, dayflow
queries) still mutating-tier in v1 — safer to over-ask once per
(server) via the confirm-once cache. Extend `_gate` key to
(`mcp_call`, server).

Acceptance: "ask browseros what tabs are open" → real MCP round-trip
traced in trace.jsonl.

## U2 — Voice-first soak fixes (the Robinhood sequence must pass)

Dogfood gate from plan -001: `"check robinhood"` → `"open it in a
browser"` → `"command t"` → `"type robinhood.com"` → `"click GDX"` —
one goal, ≤1 confirm, click lands. Current residual risks:

- Natural-language arg extraction: "workspace 4" must parse the digit,
  "command t" must hit the browser's tab shortcut (key tool, not
  shell), "type X" must type into the focused field, not launch a
  keyboard hunt.
- Browser preference: `browser` should resolve to BrowserOS when it's
  the running/default, not chromium. Use windows_map + inventory.
- Re-observation: after any step that changes the screen, screenshot
  before the next click (act loop should prefer screenshot → click
  over blind coordinates).
- Tool-tier re-review: `click`/`type_text`/`key` inside a confirmed app
  session should not re-prompt; that's already done — verify in trace.

Acceptance: the 5-utterance sequence completes end-to-end; trace shows
one goal, ≥1 re-screenshot before the final click, zero clarify cards.

## U3 — Talk mode polish (the everyday path)

Most utterances should never touch the act loop. Talk = screen +
question → spoken answer + `[POINT]` ghost cursor. Currently answer
route gets the screenshot but:

- POINT tags tested only lightly — verify cursor lands + label shows.
- Session tail should prefer *spoken-friendly* recency (answers, not
  raw tool noise).
- Follow-ups in the same app ("ok and the third column?") should reuse
  focus context without re-capturing — capture-once-per-turn already
  done; verify latency stays <3s total.

## U4 — GUI/debug surface v2

Panel exists; needs the agent-era polish:

- Now tab: goal timeline (step chips), ASK_USER pending indicator,
  mode badge (Talk/Act/Agent).
- Activity tab: per-goal grouping, not per-turn — the Robinhood run
  should render as one expanding row.
- Tele tab: confirm-cache hits, goal join rate, ASK_USER count.
- Errors readable in UI without `wispd fails`.

## U5 — Jev question slimming (finishing plan -001's U4)

`app`/`action`/`needs_screen` questions still in `build_questions` —
advisory now, but they cost tokens and produce noise (low-confidence
app answers, needs_screen the pipeline ignores). Replace with:

- `route` (act/answer/agent/dictation/learn/tool) — keep
- `goal` (short text for goal naming) — new
- `risk` — keep, only consulted on mutating/shell tiers
- `tool` — keep for tool-route picks
- `app`, `action`, `needs_screen` — delete; launch resolves the app
  via fuzzy_app/harness, the rest resolves via screen+goal.

Acceptance: Jev payload shrinks; no route regressions in the eval
corpus (`wispd eval route`).

## U6 — Recipes → skills graduation

Trajectory → proposed recipe → human approve → installed skill. The
plumbing exists (recipes approve, provenance stamps). Missing: recipe
*candidate generation* from successful multi-step goals — when a goal
closes `done` with ≥3 steps and the label is ✓, draft a SKILL.md
skeleton (goal text, app, step tools) into skills-review. Panel shows
it as a suggestion card.

## U7 — Release hygiene for open-source

- README: what it is, 60-sec install, screenshots (the plugin UI
  actually looks good now — shoot it).
- `wispd install` clean-box test on a fresh Omarchy VM or container:
  no ~/.local/share/wisp, no memory, no harness — first run does the
  full passthrough (inventory + skills seed + vocab) and works.
- LICENSE MIT already. GitHub topics, description, and a demo GIF.

## Deferred (explicitly not now)

- **macOS parity**: platform seam holds; menu-bar UI, overlay, hotkey,
  pointer = revisit after Linux v1.0. No new macOS work meanwhile —
  keep the seam honest (OS code only in platform.py/platform.rs).
- **Windows**: docs stub only.
- **Hosted/cloud anything**: Wisp stays local-first; the only network
  calls are the configured providers.
- **Weight-level RL**: never. The learning loop is trajectory stats +
  human-gated recipes — auditable, reversible.
