# Next tasks

The heaviest open work, in the order to take it. Written for whoever picks
this up next; each item says where to look and how to prove it is done. The
roadmap is `ROADMAP.md`; the terminal plan is
`docs/plans/2026-10-31-001-feat-terminal-output-and-tui-plan.md`.

Run the suite the way CI does: `python -m unittest discover -s tests -v`
(about five and a half minutes; targeted runs with `-p 'test_x.py'`).
`python -m unittest tests.test_bootstrap` fails on an import path; use
`discover`.

## Release blockers

1. **Installable release candidate.** Verify real extracted archives and
   recovery, then publish a versioned Linux release with one install line.
   Files: `scripts/release/build.py`, `scripts/release/verify.py`,
   `scripts/bootstrap/install.py`, `.github/workflows/release.yml`,
   `docs/RELEASING.md`, `docs/INSTALL.md`. Test:
   `tests/test_release_packaging.py`, `test_release_attestation.py`,
   `test_bootstrap.py`, `test_install.py`, `test_install_release_edges.py`.
   Then do a fresh extract on a clean box and keep the receipt. Publish the
   homepage and bootstrap only after DNS, HTTPS and an install-command
   receipt exist (`wisp.observer` is not verified).
2. **Clean-box onboarding and doctor.** `wispd onboard` and `wispd doctor`
   must pass on a clean Omarchy box with hosted keys only (v1.0 gate).
   Files: `wisp/onboard.py`, `wisp/preflight.py`, `wisp/cli/diagnose.py`.
   Test: `tests/test_onboard.py`, `tests/test_preflight.py`,
   `tests/test_cli_doctor_view.py` once the terminal PRs land. Real check:
   run both on a fresh user account and paste the output into the PR.
3. **Owner-labelled accuracy gate.** `wispd eval` must pass `[eval]
   gate_rate` (60%) over at least 50 labelled turns; the last tally was 23
   turns at 30%. Files: `wisp/learn.py`, `wisp/cli/learning.py`, `wispd dev review`,
   `scripts/accuracy_baseline.py`. Test: `scripts/release/test_eval.py`,
   `test_accuracy_baseline.py`. This needs real runs with the feedback
   controls, not fixtures.
4. **Refresh `ROADMAP.md`.** The section "In PR #259, not yet shipped" is
   stale: #259 is merged (`f80f1ab`). Move it to Shipped, keep the caveats
   about live checks. Test: `tests/test_docs_lint.py` and a read-through.
5. **Real-device checks still marked pending.** Compositor, microphone,
   pointer and overlay behavior, and the `buddy.js` 0.30 s entry delay (needs a
   real capture before changing screenshot-clearance timing). Files:
   `shell-plugin/lib/companion.js`, `shell-plugin/lib/buddy.js`. Test:
   `tests/qml/` snapshots plus a recorded session on Omarchy.

## Terminal output and TUI (from the plan)

The plan's units were built as local branches and bundles (not pushed) in
the box at `/workspace/wisp-tui-artifacts/` (bundles, per-branch patches and
PR bodies). U1, U2 and the onboarding and installer PRs are the first to
push. The rest, in dependency order:

6. **U3, status/config views and empty states.** Branch `feat/tui-u3-views`.
   Files: `wisp/cli/views.py`, `wisp/cli/core.py`, `wisp/cli/settings.py`,
   `wisp/cli/learning.py`. Test: `tests/test_cli_views.py`; goldens in
   `tests/golden/output/`; the transcript goldens
   (`tests/golden/cli_transcripts.json`) must not change.
7. **U4, help wrapping, banner, `--version`.** Branch
   `feat/tui-u4-help-banner`. Files: `wisp/cli/__init__.py`,
   `wisp/cli/registry.py`, `wisp/settings_schema.py`. Test:
   `tests/test_cli_help_banner.py`, `tests/test_cli.py`,
   `tests/test_cua_health.py`; regenerate help goldens with
   `WISP_UPDATE_GOLDEN=1` at `COLUMNS=80`.
8. **U6/U7, TUI layout engine and views.** Branch `feat/tui-u7-layout`.
   Files: `wisp/tui_layout.py`, `wisp/tui.py`. The model builders in `tui.py`
   are pinned by `tests/test_manage.py`; only the draw layer changes. Test:
   `tests/test_tui_layout.py`, `tests/test_tui_render.py`; check by hand in a
   real terminal at 60, 100 and 200 columns (a pty smoke run was done).
9. **U8, audit log view.** Branch `feat/tui-u8-audit` (stacked on U7).
   Files: `wisp/tui.py`, `wisp/tui_layout.py`. Test: `tests/test_tui_audit.py`.
   Open: a separate decisions-log view was left out because it would add a
   sixth view and break the 1-5 keys and the QML parity.
10. **U9, style doc, VHS tapes, guard.** Branch `feat/tui-u9-docs-guard`
    (apply after the others merge, as a patch on `master`). Files:
    `docs/design/TERMINAL.md`, `docs/media/tui/*.tape`,
    `scripts/ui/tui_capture.sh`, `tests/test_cli_output_guard.py`. Test:
    `tests/test_cli_output_guard.py`; recording the tapes needs VHS and was
    not done.

Note on state: the full suite passed on U1, U2, U3, U4, the onboarding
branch (`feat/tui-u5-onboard`) and the installer branch
(`feat/tui-u6-installer`). The TUI branches (U7, U8) and the guard branch (U9)
were run with targeted tests only.

## Trials and tests

11. **Owner trial runs.** After install, run a varied set of real tasks
    across apps, label them with the feedback controls, then `wispd eval` and
    `wispd dev review`. Run `wispd dev run` only in an explicitly approved
    session; a judge result is not an owner label. Files: `docs/DEV_MODE.md`,
    `docs/dev-tasks/starter.txt`. Test: `tests/test_devrun.py`,
    `test_devjudge.py`, `test_devreport.py`, `test_devsession.py`.
12. **Accuracy loop.** Rank real misses, keep reproducible failing tasks,
    improve grounding and routing, retest on held-out tasks. Files:
    `wisp/grounding.py`, `wisp/route.py`, `scripts/skill_distill.py`.
    Test: `scripts/release/test_grounding_release_feedback.py`,
    `tests/test_route.py`. Do not count synthetic fixtures as improvement.

## Branch status

- `docs/dev-tuning-mode`: **already in `master`.** Every file it adds is in
  `master` (the work landed through #259 and #260), and `master` has later
  changes to `wisp/devrun.py` and `wisp/devreport.py` that the branch lacks.
  It is not needed. Safe to delete when you choose to; nothing here deletes it.
- `fix/wisp-install-readiness-preflight`: **already in `master`.** Its three
  commits are not ancestors of `master`, but `#264` carried the same change:
  every file it touches is identical to `master`. Not needed. Safe to delete
  when you choose to.
