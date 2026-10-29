---
name: codebase-graph
description: Query the wisp codebase's indexed code graph (symbols, callers, architecture) via codebase-memory MCP instead of grep-looping
tier: safe
asks: Where is this function called from; What does the turn pipeline look like; Show me the architecture of wispd
provenance: authored
---
# codebase-graph

The wisp repo is indexed by `codebase-memory-mcp` (project
`home-lukekimball-Documents-github-personal-wisp`, persisted at
`.codebase-memory/graph.db.zst`). Prefer the graph over rg/read loops
for structural questions.

## When to use

- "Where does X get called / what calls X" → `trace_path`
- "Find the function/class that does Y" → `search_graph` (BM25 or
  `semantic_query`)
- "How does the daemon / pipeline / module fit together" →
  `get_architecture`
- "Show the code for symbol Z" → `get_code_snippet` or
  `get_file_outline`
- Multi-hop / aggregate questions → `query_graph` (Cypher)
- Stale-index check after edits → `detect_changes` — it needs a
  `base_branch` arg (e.g. `master`); bare call errors with
  "base_branch or HEAD is not a commit". Then re-run
  `index_repository` (moderate) if coverage drifted
- Literal string/regex hunts → `search_code` or plain `rg` still wins

## Tool cheat-sheet

| Tool | Use | Key args |
|---|---|---|
| `search_graph` | find symbols | `project`, `query`/`semantic_query`, `label`, `file_pattern` |
| `trace_path` | callers/callees/data flow | `function_name`, `direction`, `depth`, `mode` (calls/data_flow/cross_service) |
| `get_architecture` | module overview | `project`, `aspects` — valid: `all`, `overview`, `structure`, `dependencies`, `routes`, `languages`, `packages`, `entry_points`, `hotspots`, `boundaries`, `layers`, `file_tree`, `clusters`, `cycles` |
| `get_code_snippet` | read a symbol's code | `project`, `qn` or `file`+`lines` |
| `get_file_outline` | file's symbol map | `project`, `file` |
| `query_graph` | custom Cypher | `query`, `project`, `graph=code|missed` |
| `index_status` / `check_index_coverage` | freshness | `project` |
| `index_repository` | re-index | `repo_path`, `mode=moderate`, `persistence=true` |
| `manage_adr` | persist decisions | `mode` |

## Workflow

1. `search_graph` to locate the symbol (get `qn`/file/lines).
2. `trace_path` for who calls it / what it calls.
3. `get_code_snippet` to read it — only then fall back to `rg` for
   things the graph doesn't model (comments, fixtures, config).
4. After large refactors: `detect_changes`; re-index if it flags drift
   (the graph is a cache, never gospel — verify hits against source).

## Verify before done

- Answer structural claims with graph rows you actually fetched
  (qn/file/lines), not memory. A stale index shows up in
  `check_index_coverage` — say so rather than guessing.

## Gotchas

- `docs/`, `scripts/`, `.venv/` are excluded from the index — ask
  graph questions about `wisp/` and `shell-plugin/` code only.
- 23 files parsed partially (mostly `shell-plugin/lib/*.js`) — if a
  lookup comes up empty there, confirm with `rg` before reporting
  "not found".
- Project name is long; pass it verbatim or the tools 404 the project.
