# Open-source readiness fixes — wisp

Goal: repo ships **open-source ready**, not "personal config ready."
Owner personalizations live downstream of onboarding or under advanced;
nothing of Luke's machine is a shipped default.

## P0 — leaks out of the box (blocks release)

1. **Seed skills with personal paths** — `skills_seed/omarchy-bridge/SKILL.md`
   references `~/Documents/github/personal/omarchy-plugins`,
   `io.github.duketopceo.*` plugin IDs, host `omarchy-max`,
   `~/.agents/skills/omarchy`. `skills_seed/luke-agents/` ships personal
   agent rules. Fix: move both out of the seed set into a user-level/
   generated layer (onboarding writes `~/.config/wisp/` content), or gate
   behind an explicit "import my config" opt-in.
2. **Plugin namespace** — `io.github.duketopceo.wisp` is the installed
   plugin ID everywhere (shell-plugin, install, omarchy plugins dir).
   Decide before launch: keep (it's the published ID) or rename to a
   neutral org. At minimum, don't *document* it as personal.
3. **Domain/docs coherence** — README/docs should point at
   `wisp.observer` install path; confirm docs/INSTALL.md bootstrap URL
   matches the live site (install.py + version flag verified on site).

## P1 — telemetry contract (code it now, not later)

4. **wisp-observer is opt-in only.** No telemetry endpoint in any shipped
   default. Self-hosted ingest is documented for the owner only; a user's
   daemon must never post traces, prompts, or content without explicit
   consent + a visible toggle. `docs/TRUST.md` already enumerates hosts —
   keep wisp-observer out of the default trust surface or marked opt-in.
5. **Silent-posts audit** — one pass over `telemetry.py`, `trace.py`,
   `report.py`, `observe.py`, `idle.py` to confirm nothing uploads
   diagnostics without consent. Document the answer in TRUST.md.

## P2 — legal/compliance before public launch

6. Third-party license attribution page (llama.cpp, ollama,
   faster-whisper, whisper weights, Quickshell, QML deps).
7. Provider ToS passthrough text for BYOK (OpenRouter, Groq, Perplexity).
8. Privacy policy page on wisp.observer if it collects anything (even
   waitlist email); the install bootstrap itself should not collect data.
9. Trademark phrasing review — "works with" only, no endorsement claims.
10. AI-behavior disclaimer (acts/clicks/types; verify before approving).
11. Refund/payment points deferred — no payments yet.

## P3 — polish

12. Visual snapshot + test_act failures triaged separately from this work.
13. `cargo fmt` crate-wide diff left as follow-up (not folded into these).
