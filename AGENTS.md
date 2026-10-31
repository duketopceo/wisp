# AGENTS.md

## Code graph index (optional accelerator)

This repo may be indexed by `codebase-memory-mcp` (CBM) on an agent's local
machine — `.codebase-memory/` is gitignored. If your harness exposes CBM
tools (`search_graph`, `trace_path`, `get_architecture`, `detect_changes`),
prefer them for structural questions — symbol lookup, caller/callee traces,
impact analysis — instead of grep/read loops. Reindex after large refactors
(`index_repository`); treat `.codebase-memory/graph.db.zst` as a local cache
artifact, never commit it.

## Installing Wisp for a user

If a user asks you to install Wisp, follow the runbook in
`docs/INSTALL.md` ("Let your coding agent do it"): run the `agent` steps,
stop and ask at every `user` step, never read key files, never run anything privileged,
and show each plan before anything is written.

## Open-source readiness (added 2026-10-31)

This repo ships open-source ready, NOT personal-config ready:
- Owner personalizations belong downstream of onboarding (written to
  ~/.config/wisp/) or behind explicit opt-in — never in shipped defaults.
- skills_seed must not contain personal paths/hostnames/plugin IDs.
- Telemetry contract: wisp-observer is opt-in only; no shipped default
  posts traces/prompts/content anywhere. TRUST.md must stay honest.
- Site: https://wisp.observer/ (live landing + one-line install → onboard).
- Readiness plan: docs/plans/2026-10-31-0300-feat-open-source-ready-plan.md
