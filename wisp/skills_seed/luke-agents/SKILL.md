---
name: luke-agents
description: The user's canonical agent constitution (luke-agents repo) — rules, quick-start digest, 113 _LUKE skills, active repos index. Read on demand when a request touches user preferences, other repos, deploy conventions, or agent-fleet rules
tier: safe
---
# luke-agents

`~/Documents/github/personal/luke-agents` is the canonical operating
manual for every Luke repo (remote: duketopceo/luke-agents, symlinked
from `~/.agents`).

Read on demand — do not hold it all in context:

- `QUICK_START.md` — 253-line digest: principles, safety invariants,
  active repos, load-on-demand index. **Start here.**
- `AGENTS.md` — the king file: precedence, non-sycophantic reasoning,
  Karpathy principles, hard rules, safety invariants.
- `_LUKE/` — ~113 personal skills (importable via
  `wispd skills import <path>`).
- `GUARDRAILS.md`, `CODE_STANDARDS.md`, `SECURITY_GUIDELINES.md`,
  `TOOLS_OPERATIONS.md` — topical depth files.
- `context/` — per-project context packs (e.g. pace-server).

High-signal facts are already injected via MEMORY.md's `## luke-agents`
block (refreshed by `wispd sync`); reach into the repo for detail.
