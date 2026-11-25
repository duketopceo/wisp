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

## How surfaces are built

The Panel, the settings window and every other Wisp surface follow a few
construction rules, and each rule is a test that fails when it is broken:

- **A scene for every state, in light and dark.** Every component has a
  scene in `tests/qml/harness/scenes.json`; every settings page, category
  and Panel tab has a `SettingsHost` or `PanelBody` variant
  (`test_every_settings_page_and_panel_tab_has_a_scene`). Render goldens
  with `python scripts/ui/snap.py update --only <Scene>__<variant>`, look at
  both themes, then `snap.py check`. CI does not run the renderer, so
  `test_every_scene_has_goldens_in_both_themes` fails on a missing golden.
- **Every control has a name, and focus is visible.**
  `tests/qml/lib/tst_accessible.qml` scans each Panel tab and settings page
  with `tests/qml/harness/A11yScan.qml`: every control needs an
  `Accessible.name`, and a control that takes Tab focus must change what is
  drawn when it has focus (the kit uses `M.scale.focusRing` in `tk.accent`).
- **Words come from the copy table.** Add words to `wisp/copy.py`, run
  `scripts/assets/gen_copy.py`, and read them through `service.ui(key)`;
  status words come from the one status table (`test_copy`, `test_components`).
