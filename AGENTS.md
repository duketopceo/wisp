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
