---
name: graphify
description: Index or re-index a repository into codebase-memory's code graph and report coverage honestly
tier: safe
asks: Index this repo; Refresh the code graph; Check if the index is stale
provenance: authored
---
# graphify

Index a repo into `codebase-memory-mcp` so `codebase-graph`-style
queries work. each repo's index lives at
`.codebase-memory/graph.db.zst` (project slug derived
from the repo path).

## Workflow

1. `list_projects` / `index_status` — does an index already exist?
2. `index_repository` with `repo_path`, `mode: moderate`,
   `persistence: true`. Modes: `full` = all+semantic (slow),
   `moderate` = filtered+semantic (default), `fast` = filtered only,
   `cross-repo-intelligence` = link services.
3. Read the result: `nodes`/`edges` vs `expected_*`,
   `not_indexed_files_count` (gitignore/skip-list — mostly fine),
   `parse_partial_count` (files with missing constructs — name them
   when they matter), `logfile` path for the full gap list.
4. `check_index_coverage` if the count looks thin for the repo size.

## Verify before done

- Report node/edge counts and partial-parse files — never say
  "fully indexed" when `parse_partial_count` > 0.
- `graph=missed` in `query_graph` shows the coverage-gap file tree;
  absence is not proof of completeness.

## Gotchas

- Re-index after large refactors; `detect_changes` tells you if it's
  needed — it requires a `base_branch` arg (bare call errors).
  `list_projects` names the project the long way; pass it verbatim.
- Persisted db is a cache artifact — committing it is optional and
  mostly useful for teammates; regenerating is cheap.
- The index excludes `docs/`, `scripts/`, `.venv/`, `tests/` paths per
  repo config — don't promise graph coverage there.
