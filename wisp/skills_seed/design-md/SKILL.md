---
name: design-md
description: Reference brand/design-token specs (colors, typography, motion) from the local awesome-design-md catalog — use when theming or restyling wisp surfaces
tier: safe
---
# design-md

The user's fork of VoltAgent/awesome-design-md lives at
`~/Documents/github/personal/awesome-design-md/design-md/<brand>/DESIGN.md`
(~74 authored specs: YAML frontmatter with `colors`, `typography`,
`elevation`, `motion` tokens).

Use when: asked to restyle, re-theme, or evaluate Wisp's surfaces, or
when a task benefits from a named brand's palette/type conventions.

- Read a spec file directly (they're plain markdown + frontmatter).
- Wisp's own spec is the repo-root `DESIGN.md`; runtime tokens come from
  `~/.local/share/wisp/theme.json` via `wisp/theme.py` — dark and light
  are hand-paired, never inverted.
- To change the live theme: `wispd theme dark|light`.
