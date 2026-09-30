---
name: dayflow-bridge
description: Query the local dayflow work journal — timelines, blocks, insights, agent sessions — for context and pattern questions
tool: dayflow.sh
tier: safe
---
# dayflow-bridge

Wisp's bridge to the local dayflow work journal
(`~/.local/share/dayflow/dayflow.db`, CLI on PATH as `dayflow`).
Dayflow already captures and summarizes screen activity — never
re-observe the screen when a journal query answers the question.

Run via the `skill_dayflow-bridge` tool with an arg like
`today`, `timeline 2026-09-30`, `status`, `insights week`,
`agents`, `search <term>`. All subcommands are read-only `--json`
queries; the wrapper refuses anything else.

Use it for:
- "what was I doing / what did I work on" → `today` or `timeline`
- repeated-workflow questions → `insights week` (app/category mix)
- "recap my agent sessions" → `agents`
- "find when I worked on X" → `search X`

Full CLI has more (`dayflow briefing`, `dayflow day <d> --grid`);
if a needed query isn't allowlisted, say so rather than shelling out.
