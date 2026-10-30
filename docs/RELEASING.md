# Releasing Wisp

## Supported release targets

The full-app assets are **Linux x86_64** and **Linux aarch64**, built and Rust-tested on native Ubuntu 24.04 runners; the Omarchy shell plugin is a separate asset. There are no native macOS or Windows app packages in this workflow. The Python launcher remains `wispd`; `bin/wispd-rs` is an additional Rust core, not a replacement for the Python application's installer or voice pipeline. ([release workflow](https://github.com/duketopceo/wisp/blob/master/.github/workflows/release.yml), [launcher](https://github.com/duketopceo/wisp/blob/master/wispd))

## Release assets and inventory

Each release publishes these four assets; the filenames for the two app archives stay stable because the updater selects them by architecture. ([workflow](https://github.com/duketopceo/wisp/blob/master/.github/workflows/release.yml), [updater asset selection](https://github.com/duketopceo/wisp/blob/master/wisp/update.py))

```text
wisp-linux-x86_64.tar.gz
wisp-linux-aarch64.tar.gz
wisp-plugin-vMAJOR.MINOR.PATCH.tar.gz
SHA256SUMS
```

The app archive has one top-level directory, `wisp-linux-<architecture>/`, with the following payload. Debug-shell links to the plugin are materialized as regular files so extraction and installation do not depend on source-tree symlinks. ([packager](https://github.com/duketopceo/wisp/blob/master/scripts/release/build.py))

| Path | Purpose |
| --- | --- |
| `wispd`, `wisp/` | Real Python CLI and application; all modules, `budgets.json`, bundled skills and app-specific skill seeds |
| `bin/wispd-rs` | ELF64 Rust core for the selected Linux architecture |
| `shell-plugin/`, `shells/` | Omarchy plugin, debug shell, JavaScript, QML and precompiled shader |
| `browser-extension/` | Optional Chromium extension sources; manually load from the retained extracted release folder |
| `assets/` | Desktop-entry template, hicolor icons, asset licenses, shaders and image resources |
| `scripts/units/` | All systemd user-unit templates |
| `scripts/cua/` | Optional CUA driver's pinned metadata, installer and unit; no driver download is bundled or run |
| `scripts/bootstrap/` | Inspectable, standard-library release bootstrap; no bootstrap executes during packaging |
| `scripts/build_harness.py`, `scripts/fetch_whisper.sh` | Personalization builder and opt-in local-speech setup |
| `docs/`, `README.md`, `CHANGELOG.md`, `LICENSE`, `THIRD_PARTY_NOTICES.md`, `pyproject.toml` | Operator documentation, release history, licenses and source project metadata |
| `release.json` | Release tag, full source commit, Linux target and source commit timestamp |
| `payload.json` | Exact per-file SHA-256, byte size and normalized mode for every payload file except the inventory itself |

The inventory is generated from the staged payload, not maintained as an incomplete hand-written list. Files or directories named `node_modules`, `build`, `dist`, `target`, `.env`, `.env.*`, virtual environments and caches are excluded at every depth; bytecode and `.git` are excluded too. External or cyclic resource links are refused. The ELF header must match the selected architecture, and an output folder inside a packaged source tree is refused. ([packager](https://github.com/duketopceo/wisp/blob/master/scripts/release/build.py), [regression tests](https://github.com/duketopceo/wisp/blob/master/tests/test_release_packaging.py))

## Integrity and reproducibility

`SHA256SUMS` contains sorted, basename-only hashes for all three downloadable archives. The updater can consume this file when GitHub's release-asset digest is unavailable. These are **unsigned checksums**, not proof of an independently authenticated publisher: downloading an archive and its checksum from the same GitHub repository does not protect against a compromised publisher. No signing key or signature is claimed. Compare a digest obtained through a separate trusted channel when that assurance is required. ([checksum generation](https://github.com/duketopceo/wisp/blob/master/scripts/release/build.py), [updater digest handling](https://github.com/duketopceo/wisp/blob/master/wisp/update.py), [install trust model](https://github.com/duketopceo/wisp/blob/master/docs/INSTALL.md))

Packaging normalizes gzip headers, archive order, file modes, owner/group and timestamps to `SOURCE_DATE_EPOCH` from the source commit. With identical source contents, binary bytes, release metadata and packaging Python/zlib, repeated packaging produces identical archives. This is not a claim of bit-identical Rust binaries across arbitrary hosts: runner images, native libraries and system packages can still change. ([packager](https://github.com/duketopceo/wisp/blob/master/scripts/release/build.py))

The workflow pins action commits, Python 3.11.17 and Rust 1.99.1 and uses the checked-in Cargo lockfile with `--locked`; it does not update dependencies during release. Those interpreter/compiler versions match the existing successful CI run rather than introducing a toolchain upgrade. ([workflow](https://github.com/duketopceo/wisp/blob/master/.github/workflows/release.yml), [successful CI run](https://github.com/duketopceo/wisp/actions/runs/41114133191))

## Local verification before tagging

Run the focused regression tests without starting a desktop session:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s tests -p test_release_packaging.py -v
```

Build the Rust core using the same pinned compiler on the matching Linux architecture, then package it into a new output directory. Replace `v1.2.3` with the intended release tag; these commands create local files only, not a tag or release.

```sh
VERSION=v1.2.3
RUST_TARGET=x86_64-unknown-linux-gnu
BUNDLE_TARGET=linux-x86_64
# On aarch64 use aarch64-unknown-linux-gnu and linux-aarch64 instead.
COMMIT="$(git rev-parse HEAD)"
EPOCH="$(git show -s --format=%ct HEAD)"

cargo +1.99.1 build --locked --release --manifest-path rs/wispd/Cargo.toml \
  --target "$RUST_TARGET"
cargo +1.99.1 test --locked --manifest-path rs/wispd/Cargo.toml \
  --target "$RUST_TARGET"

python3 scripts/release/build.py bundle --source . \
  --binary "rs/wispd/target/$RUST_TARGET/release/wispd" \
  --target "$BUNDLE_TARGET" --version "$VERSION" --commit "$COMMIT" \
  --epoch "$EPOCH" --out build/release-check
ASSET="build/release-check/wisp-$BUNDLE_TARGET.tar.gz"
SHA="$(sha256sum "$ASSET" | cut -d' ' -f1)"
python3 scripts/release/verify.py --archive "$ASSET" --sha256 "$SHA" \
  --version "$VERSION" --commit "$COMMIT" --target "$BUNDLE_TARGET"
```

The verifier checks the archive checksum, refuses traversal/links/duplicate members, checks required resources and the exact inventory, and invokes the extracted real `wispd install --dry-run` in an isolated temporary HOME. It then runs the real installer **only into that disposable HOME**, compares installed runtime bytes, release records, launcher, plugin, desktop entry and daemon unit, and discards the temporary tree. It clears the inherited environment and user import paths, supplies an empty configuration, denies Python-audited child processes and sockets, denies all writes during the preview, and confines installer writes to the temporary HOME. This is a trusted-code regression guard, **not a security sandbox for arbitrary hostile Python**; no user-device installer or real host service runs. The Rust binary is never executed by this check. ([verifier](https://github.com/duketopceo/wisp/blob/master/scripts/release/verify.py), [negative tests](https://github.com/duketopceo/wisp/blob/master/tests/test_release_packaging.py))

The JSON result says explicitly that desktop/voice smoke was not run. A passing package check does **not** establish microphone permissions, live IPC, compositor integration, model access, optional driver health or successful service startup. Those remain representative-machine release checks. ([verifier report](https://github.com/duketopceo/wisp/blob/master/scripts/release/verify.py))

## Publish through GitHub Actions

1. Have the caller review and integrate the complete change set; run application tests and the focused release tests.
2. Require the actual isolated-install verification to pass; an archive inventory or install preview alone is insufficient.
3. Choose an unused `vMAJOR.MINOR.PATCH` tag, or a prerelease such as `v1.2.3-rc.1`; review the changelog and source commit.
4. With explicit release authorization, create and push that tag, or dispatch the release workflow against an existing tag:

   ```sh
   gh workflow run release.yml --ref master -f tag=v1.2.3
   ```

5. Inspect both native build jobs, the plugin validation and the per-architecture JSON verification artifacts.
6. Complete the user-confirmed Linux desktop/voice smoke and record performed/skipped checks.

The workflow requires both architecture archives and the plugin, writes and locally verifies `SHA256SUMS`, creates a draft release, downloads the uploaded assets, rechecks their hashes and only then publishes. Prerelease tags are marked as prereleases. An existing release is refused rather than silently overwritten; if publication fails, inspect the remaining draft before deciding how to recover. ([workflow](https://github.com/duketopceo/wisp/blob/master/.github/workflows/release.yml))

The workflow does not certify a live voice interaction automatically; do not present its release publication as proof of the manual smoke check. ([workflow](https://github.com/duketopceo/wisp/blob/master/.github/workflows/release.yml), [verifier](https://github.com/duketopceo/wisp/blob/master/scripts/release/verify.py))

## Download, preview and reinstall on Linux

Run these only on the intended Linux machine, after reviewing the release and choosing its version:

```sh
test "$(uname -s)" = Linux || exit 1
VERSION=v1.2.3
case "$(uname -m)" in
  x86_64|amd64) TARGET=linux-x86_64 ;;
  aarch64|arm64) TARGET=linux-aarch64 ;;
  *) echo "Unsupported Linux architecture" >&2; exit 1 ;;
esac
ASSET="wisp-$TARGET.tar.gz"
mkdir "wisp-download-$VERSION"
cd "wisp-download-$VERSION"
gh release download "$VERSION" --repo duketopceo/wisp \
  --pattern "$ASSET" --pattern SHA256SUMS
sha256sum --ignore-missing --check SHA256SUMS
mkdir unpack
tar -xzf "$ASSET" -C unpack
cd "unpack/wisp-$TARGET"
python3 wispd install --dry-run
# Review every listed path before applying:
python3 wispd install
```

The installer writes user-scope files, not system packages, and does not restart the daemon. Retain the extracted release folder for optional setup and inspection. Existing plugin installation, hotkey edits and desktop files are distinct managed surfaces; inspect the preview before reinstalling. ([installer](https://github.com/duketopceo/wisp/blob/master/wispd), [install CLI](https://github.com/duketopceo/wisp/blob/master/wisp/cli/core.py))

For an existing installation, prefer the verified transactional updater; it checks release ordering and asks before applying. Use `--force` only after inspecting why the normal version-order guard refused the release. ([updater](https://github.com/duketopceo/wisp/blob/master/wisp/update.py))

```sh
wispd update --dry-run
wispd update
# Only if a restart is intended, with separate confirmation:
wispd update --restart
# Inspect and confirm a managed-file restore if needed:
wispd update --rollback
```

Update rollback is a managed-file backup, not a filesystem snapshot. Its recovery includes attributable plugin files and installed systemd unit templates, while keeping subsequent user edits; desktop entries, icons, launchers, hotkeys, service-manager state and user data are not rolled back. Inspect the updater's scope warning and kept-file report for the particular transaction. ([updater transaction scope](https://github.com/duketopceo/wisp/blob/master/wisp/update.py))

## Installed resource and version contract

The installer retains archive runtime resources under `~/.local/opt/wisp`: core modules, shells, assets, binary, units, CUA/bootstrap resources, harness/speech scripts, baseline data and release/inventory metadata. It installs an executable `~/.local/bin/wispd` launcher, and fresh archive installations consume the validated release tag and source commit from `release.json` when recording `deploy.json`. The updater's managed-file inventory includes these retained resources for verification and backup. ([installer](https://github.com/duketopceo/wisp/blob/master/wispd), [deploy records](https://github.com/duketopceo/wisp/blob/master/wisp/deploy.py), [updater](https://github.com/duketopceo/wisp/blob/master/wisp/update.py))

The installed CUA probe looks for `scripts/cua/PIN`, unit rendering looks for `scripts/units`, and telemetry reads `docs/baselines/latency-harness.json`; an archive-only preview cannot prove those paths survived installation. The release verifier's actual temporary-home installation deliberately fails on missing runtime resources or incorrect deploy metadata, blocking publication rather than accepting a preview alone. ([CUA probe](https://github.com/duketopceo/wisp/blob/master/wisp/probes_cua.py), [unit renderer](https://github.com/duketopceo/wisp/blob/master/wisp/svc.py), [telemetry](https://github.com/duketopceo/wisp/blob/master/wisp/telemetry.py), [release verifier](https://github.com/duketopceo/wisp/blob/master/scripts/release/verify.py))

For a committed-source reinstall instead of a release archive:

```sh
git checkout --detach v1.2.3
python3 wispd install --ref v1.2.3 --repo "$PWD" --dry-run
python3 wispd install --ref v1.2.3 --repo "$PWD"
```

`--ref` exports the committed tree and records that source ref and commit instead of installing local uncommitted edits. ([ref export](https://github.com/duketopceo/wisp/blob/master/wisp/deploy.py), [install ref handler](https://github.com/duketopceo/wisp/blob/master/wisp/cli/core.py))
