---
plan: dim-u10-packaging-release
created: 2026-09-27
status: in-progress
origin: docs/plans/2026-09-26-001-feat-dim-companion-crossplatform-plan.md#U10
issue: https://github.com/duketopceo/wisp/issues/17
wave: 5
---

# U10 — Packaging + release (v1.0.0)

## Scope

Wisp ships as a real app on all three OSes.

## Steps

1. **Packaging**: `cargo-dist` or `cargo-packager` —
   `.pkg` (macOS, signed + notarized), `.msi` + winget (Windows),
   `.deb` + AUR PKGBUILD + AppImage (Linux).
2. **Service registration**: `wispd install` per-OS —
   launchd plist (mac), systemd user unit (linux, exists), Task
   Scheduler entry (win).
3. **Whisper bundling**: document/ship whisper.cpp binary +
   `ggml-tiny` model path per OS; first-run download option.
4. **License**: Apache-2.0 (settled) — add `LICENSE` (closes #2).
5. **Docs**: install guide, config reference, brain provider table,
   security model (tiers, denylist, allow_shell, screenshot privacy),
   `AGENTS.md`/`CLAUDE.md` contributor notes refresh.
6. **Cutover**: Python `dim/` moves to `legacy/` (or is clearly marked
   reference); `wispd-rs` becomes the shipped `wispd`.
7. **Tag `v1.0.0`**, GitHub release with artifacts.

## Tests

- CI produces artifacts for all three targets (release workflow).
- Clean-VM install + `wispd install` + hotkey smoke per OS (manual
  checklist).

## Risks

- Notarization/signing accounts needed — infra cost, not code.
- sqlite-vec `.so` bundling inside each artifact (depends on U5c
  embeddings if landed by then).

## Done when

v1.0.0 artifacts install and run on all three OSes from a fresh
machine profile.
