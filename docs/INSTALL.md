# Installing Wisp

Wisp is a resident voice assistant: a `wispd` daemon plus a
push-to-talk trigger, a shell plugin (bar mark + live pill + overlay), and a management
app.

## One-line verified-release bootstrap

Use a published tag, including a prerelease such as `v1.0.0-rc.3`; the
example is a candidate identifier, not a claim that this tag exists yet.
Run as your normal Linux desktop user, never with sudo. Python 3.11.4+,
`curl`, Linux x86_64 or aarch64, GitHub HTTPS access, and an **independently
installed GitHub CLI with artifact-attestation support** are required.
The bootstrap never installs its own verifier. Check `gh attestation verify
--help` for exact-identity, source-ref/source-digest, signer-digest and
hosted-runner verification flags. ([GitHub CLI verification](https://cli.github.com/manual/gh_attestation_verify))

On Omarchy/Arch, install the independent verifier from your normal terminal
with `sudo pacman -S --needed github-cli` if it is missing. This is an
explicit system-package operation, not something the bootstrap runs.
An RPC/SSH shell without `HOME` or desktop-session variables is not a live
desktop check. Run installation and interactive onboarding from your usual
desktop terminal; the bootstrap refuses an empty, relative, nonexistent or
filesystem-root `HOME` before downloading a payload.

The bootstrap is self-contained Python, not a shell script. **This
convenience download does not authenticate the bootstrap script itself.**
Use it only after independently trusting/reviewing that pinned script;
otherwise download without executing and inspect it in a separate editor.
A malicious replacement bootstrap could simply omit its own checks;
the later payload attestation cannot repair that root-entrypoint problem.
([bootstrap implementation](https://github.com/duketopceo/wisp/blob/master/scripts/bootstrap/install.py))

```sh
VERSION=v1.0.0-rc.3; f=$(mktemp) && curl -fLsS "https://raw.githubusercontent.com/duketopceo/wisp/$VERSION/scripts/bootstrap/install.py" -o "$f" && python3 "$f" --version "$VERSION"
```

For inspect-first use, stop after downloading and read the file with a
separate trusted editor before executing anything. `--inspect-source` is
only a convenience for an already-trusted script, not a safe way to inspect
untrusted Python. After establishing that trust, run:

```sh
python3 "$f" --version "$VERSION" --dry-run
python3 "$f" --version "$VERSION"              # terminal consent
# Explicit unattended consent after inspection:
python3 "$f" --version "$VERSION" --yes
```

`--dry-run` is offline: it prints the selected release endpoint, architecture
and intended actions, with no network, HOME writes or service actions.
It does not claim to have checked release availability. Unsupported hosts
exit 4. Without `--version`, only GitHub's latest non-prerelease is selected;
always pin a release candidate explicitly. `--from-plugin` preserves the
marketplace's plugin ownership. `--sha256 <hex>` supplies an independently
obtained archive checksum but **cannot bypass attestation**; no API token
or other secret is needed. `--trusted-root /independent/root.json` optionally
uses a previously provisioned GitHub/Sigstore trust root, never one shipped
with the Wisp release. Without that option, gh obtains authenticated TUF
trust material using its independently installed roots. An unavailable or
unsupported verifier, missing bundle, failed verification or unavailable
trust roots stops without extraction or payload execution—there is no
checksum-only downgrade. ([GitHub CLI verification](https://cli.github.com/manual/gh_attestation_verify),
[trusted-root provisioning](https://cli.github.com/manual/gh_attestation_trusted-root))

After consent, bootstrap fetches official GitHub release metadata and
`SHA256SUMS` (or the release asset digest) for integrity, plus the archive's
`<archive>.sigstore.json` public bundle. Before extraction, independent gh
verifies the archive bytes against keyless GitHub/Sigstore proof, the exact
`duketopceo/wisp/.github/workflows/release.yml@refs/tags/<tag>` identity,
GitHub's OIDC issuer, the expected repository, the exact tag ref and the
resolved full source/signer commit, and GitHub-hosted runners. Only then
does bootstrap validate/extract the archive and run its real installer.
([bootstrap](https://github.com/duketopceo/wisp/blob/master/scripts/bootstrap/install.py),
[GitHub CLI policy flags](https://cli.github.com/manual/gh_attestation_verify))

Extraction refuses traversal, links, devices, secrets such as `.env`,
duplicate members and excessive expanded size. Missing inputs stop before HOME
mutation. There is no sudo, model download, key entry, audio capture,
daemon start or restart. The unit installer may reload user-unit definitions,
but never enables or starts a unit. A failed first install may leave files;
it is not a filesystem transaction. See Uninstall below.

Attestations authenticate the stated build identity and artifact digest,
not that the source is safe, that repository maintainers are uncompromised,
or that voice/desktop tests passed. This implementation configures that
channel; a real Wisp release is not attested until its actual bundle exists
and verification succeeds. The separate plugin-only asset is not covered
by the native archive's attestation. The in-app updater enforces the same
native archive policy before extracting or executing a candidate; it loads
the helper from the trusted running installation, never the candidate.
([release workflow](https://github.com/duketopceo/wisp/blob/master/.github/workflows/release.yml),
[updater](https://github.com/duketopceo/wisp/blob/master/wisp/update.py))

For offline **verification** after downloading artifacts, provision the
root on an independently trusted connected machine, transport it separately,
and pass `--trusted-root`; the bootstrap itself still downloads release/tag
metadata and assets. Local-bundle verification needs no GitHub login, and
bootstrap isolates gh's config/cache and removes token environment variables.
If unavailable, stop and independently review/build a pinned source commit;
do not run an unauthenticated archive as a fallback.
([local bundles](https://cli.github.com/manual/gh_attestation_verify),
[root command](https://cli.github.com/manual/gh_attestation_trusted-root))

## Let your coding agent do it

Paste this into a coding agent (Claude Code, Codex, opencode or similar)
running in a terminal on your Omarchy machine:

```text
Install Wisp for me from https://github.com/duketopceo/wisp. If it is not
already there, clone it into ~/src/wisp. Then follow the runbook in
docs/INSTALL.md under "Let your coding agent do it", one step at a time.
Do the steps marked agent yourself and stop at every step marked user and
ask me. Never read, print or copy any key, token or .env file, and never run
anything with elevated privileges; if a step needs one, tell me what and why
and wait. Show me every plan before anything is written, and finish with the
verification turn.
```

The runbook the agent follows. `agent` steps are safe for it to run as
written; `user` steps need you (keys, microphone permission, the bind, and the
first spoken test). The dry runs write nothing.

```runbook
agent  python3 wispd doctor                  # exit 0 or 4: show me every MISS row and its fix
agent  python3 wispd install --dry-run       # exit 0 or 4; show every MISS and planned write
user   say yes to that plan, then the agent runs: python3 wispd install
user   put the model key in ~/.config/wisp/.env yourself (the agent must not read or write it)
agent  python3 wispd onboard --status        # show the first-run checklist
user   allow the microphone when asked, and confirm the Hyprland bind before it is added
agent  python3 wispd binds                   # shows the hotkey and the lines it adds
user   hold Super+D and say "what time is it", then tell the agent what you heard
agent  python3 wispd doctor                  # exit 0 or 4: report what is still missing
```

If a step fails, the agent reports the error code and the `Try:` line the
command printed and stops; it does not edit config files to get past it.
To undo everything, see Uninstall below.

## From a release tarball/zip

```sh
tar xzf wisp-linux-aarch64.tar.gz && cd wisp-linux-aarch64
python3 wispd install   # core files + service + plugin + menu entry
```

`wispd install` is idempotent. It lays down:

- `~/.local/opt/wisp/` — the Python core (`wisp/`), launcher (`wispd`),
  GUI (`shells/`), runtime assets, binary, scripts, public docs/baseline/task data,
  release metadata and plugin ownership records
- `~/.local/bin/wispd` + `wisp-trigger` on PATH
- `~/.local/share/applications/wisp.desktop` — "Wisp" in the app menu
  opens the management app; right-click actions: Listen (`wispd
  trigger`), Stop (`wispd interrupt`), Panel (the management app).
  Template: `assets/desktop/wisp.desktop`. An edited file is kept as
  `wisp.desktop.bak`; `wispd install --dry-run` previews the change.
- hicolor icons under `~/.local/share/icons/hicolor/` (16 to 512 px
  plus scalable); `update-desktop-database` and `gtk-update-icon-cache`
  run only if installed
- No tray icon: the bar mark is the status surface. A StatusNotifier
  host exists on Omarchy (quickshell owns
  `org.kde.StatusNotifierWatcher`; check with `busctl --user list |
  grep StatusNotifier`), but publishing an item needs a D-Bus
  service object, which stdlib Python and busctl cannot export, so no
  SNI item is shipped (W27).
- Omarchy plugin `io.github.duketopceo.wisp` (Linux/Omarchy)
- a service: `wispd.service` (systemd user)
- the push-to-talk bind in `~/.config/hypr/bindings.lua` (Hyprland only)

## From the Omarchy plugin marketplace

```sh
omarchy plugin add https://github.com/duketopceo/wisp-plugin.git --enable
```

That adds the bar mark, live pill and overlay only (a plugin-only mirror,
built from this repo's `shell-plugin/` by `scripts/plugin_mirror.py` on
every release; this repo stays the source of truth). The daemon comes from
a release tarball. Run its installer in `--from-plugin` mode: it prints
every file it will write and the exact lines it will add to
`~/.config/hypr/bindings.lua`, and writes nothing until you say yes
(`--yes` answers it for you; without a terminal it refuses and writes
nothing). It leaves the plugin folder to `omarchy plugin update`.

```sh
python3 wispd install --from-plugin --dry-run   # the plan, nothing written
python3 wispd install --from-plugin             # the plan, then asks
```

`wispd install --dry-run` now also lists the bind it would add. To remove
everything: `omarchy plugin remove io.github.duketopceo.wisp`, then the
Uninstall steps below.

## Updating a release install

`wispd update` checks the latest tagged release of the repo and never
installs on its own:

```sh
wispd update --dry-run   # version, digest and the files that would change
wispd update             # same, then asks; only "y" installs
```

It downloads the tarball for your architecture into a temporary
directory, checks its SHA-256 against the digest the release publishes (the
asset digest, or a `SHA256SUMS` asset), and aborts on a mismatch or when
no digest is published (pass `--sha256 <hex>` if you have one from a
source you trust). `--dry-run` deletes the download again and writes
nothing. A yes saves a backup of the managed files (below), runs that
tarball's `wispd install`, and checks every installed file against the
verified release. It does not restart the daemon unless you pass
`--restart` and say yes. Installing needs a terminal to ask you.

`wispd update` never goes backwards. It compares the release with what is
installed (version numbers when you installed a release; when you
deployed a git ref, the installed commit against the release tag on
GitHub) and refuses a release that is older, the same, diverged from your
install, or that it cannot compare, before downloading anything. A
`--dry-run` still previews it and says so. `wispd update --force` installs
it anyway, and still asks for your yes.

### The stages of an update

1. **Preflight.** The effective home directory, OS, architecture, Python
   3.11.4+, free space, systemd/session environment, optional tools and
   the current install are checked first. A `MISS` row stops
   the update or install before anything is written and says what to fix;
   a `warn` row (no systemd, no OpenCode, no Ollama, no `hyprctl`) is
   shown and never blocks. `wispd doctor` and `wispd install --dry-run`
   include the shared preflight rows. Doctor also checks runtime readiness
   and exits 4 if any of its checks are missing; that is not a clean bill
   of health or an installation-success claim. Blocked install previews exit 4 without writes,
   network or service actions; an unblocked preview exits 0.
   Real installs also report the rows. Desktop companion, audio capture,
   playback/resampling/ducking, typing, clipboard, notifications, verifier,
   repository and optional local-model/agent tools are checked on PATH;
   supported typing, playback and speech fallbacks are accepted. A found
   executable or session variable does not prove live device access.
   Missing desktop-session variables warn without blocking a headless install.
   These checks do not install packages, capture audio, inject input or start services.
2. **Preview.** The version, digest and every file that would change. It
   also calls out external plugin and unit changes.
3. **Consent.** Nothing is downloaded into the install, written or
   restarted without your yes. Nothing reads or prints a key.
4. **Verify the download.** SHA-256 against the published digest, then
   ordering (never backwards), before anything outside a temp directory
   is touched.
5. **Back up.** Managed core/runtime resources under `~/.local/opt/wisp/`
   and the exact plugin files and selected unit templates this installer
   will write are copied to `~/.local/state/wisp/update/<id>/`.
   The owner-only manifest holds relative paths, pre/post hashes,
   original permissions and whether the daemon was active.
   Config, keys, memories, user skills and documents are excluded.
6. **Apply and verify.** The installer runs, the release version is
   recorded, and every file is compared with the verified release. A
   mismatch is reported as a failure, never as success.
7. **Restart (optional).** `wispd update --restart` asks, restarts
   `wispd`, and checks that it answers.

### When an update fails

Whatever the failure (installer error, interruption, mismatch, a daemon
that does not answer), the backup and manifest stay and `wispd update`
refuses to start another update until you decide:

```sh
wispd update --rollback            # restore the saved files, on your yes
wispd update --rollback --restart  # and offer to restart the daemon
```

For plugin files and units, rollback restores only content attributable
to the update, even after interruption. A different current hash is kept
and listed, not guessed to be an incomplete copy. Newly added external
files are removed only when they still match the expected update hash.
Core files retain interrupted-apply recovery: partial core bytes are
restored from backup; after a verified update, differing core files are
kept as user edits. Symlinked paths and escapes are refused.

The plugin installer preserves unrelated additions and detects edits
against its previous `plugin-files.json` record; edited files are kept.
Marketplace mode persists across reinstall/update and never takes over a
marketplace plugin. Legacy installs without that ownership record cannot
identify pre-existing edits automatically; update backups preserve their
old bytes. Units retain changed-file `.bak-<timestamp>` copies.

Repeated rollback is safe; previously kept edits stay kept. A partial
restore says so and lists attention needed, rather than claiming success.
The recovery scope is not a filesystem snapshot: desktop entries/icons,
launchers, hotkey binds, installed agents, user config and service-manager
state are excluded. No rollback restarts services without `--restart`
and a separate yes. After a failed first install there is no update backup;
use Uninstall below.

### Offline, degraded and kept files

With no network, `wispd update` stops at the download and changes nothing;
the installed copy keeps working. Without systemd the files install and
the units are not started; start `wispd` yourself. Without OpenCode,
Ollama, a microphone permission or a keyring, install and onboarding still
finish: those steps are optional, skipped on request and never run
without a yes.

Backups accumulate under `~/.local/state/wisp/update/`. Nothing deletes
them. After an update you have verified yourself, remove old
directories there by hand if you want the space back; keep the newest
one until you are sure.

### What the download proves

A release download is checked against a publisher SHA-256 for integrity;
that checksum alone does not authenticate the publisher. Both bootstrap
and in-app update additionally require the public GitHub/Sigstore bundle,
an independently installed compatible `gh`, and exact release-workflow,
tag and source-commit verification before extraction or payload execution.
`--sha256` supplies an additional integrity check and `--force` changes
version-order consent only: neither bypasses authentication. An updater
dry run downloads/verifies in temporary storage and reports authentication
separately; missing verifier, bundle or trusted installed helper refuses
without managed writes. Old unsigned releases are source/manual-review
only. Existing legacy updater binaries do not retroactively acquire these
guards; use the authenticated bootstrap or independently reviewed source
to migrate them. Offline rollback of an owned backup requires no new
release, verifier or network. The bootstrap entry script and any manual
source checkout still require a separate initial trust decision.
([updater](https://github.com/duketopceo/wisp/blob/master/wisp/update.py),
[bootstrap](https://github.com/duketopceo/wisp/blob/master/scripts/bootstrap/install.py))

### Release checklist

Before a release is announced, record in the release notes: OS,
architecture and release id; whether an isolated first install, an update
and a rollback each ran in a temporary HOME; whether failure injection
(interrupted installer, wrong digest, daemon that does not answer) ran;
and the result of one spoken test on a real machine (hold the bind, say a
sentence, say what you heard). A check that was not run is listed as not
run. A release is not called verified on the strength of checks that were
skipped.

## Deploying a git ref

`wispd install --ref <git-ref>` installs that branch, tag or commit of
the source repo instead of the working tree (uncommitted changes are not
installed, and the checkout is not touched):

```sh
wispd install --ref origin/master --dry-run   # print the plan
wispd install --ref origin/master
wispd install --ref v1.2 --repo ~/src/wisp    # name the repo explicitly
```

The repo is `--repo`, else the one the last install came from. Every
install writes `~/.local/opt/wisp/deploy.json` (repo, ref, commit,
time); `wispd status` shows the deployed commit, or `unknown` when
there is no record. The installed copy predates `--ref` until the first
install that includes it, so run that one from a checkout
(`python3 wispd install`); after that `wispd install --ref ...` works
from anywhere.

## Secrets

`~/.config/wisp/.env`:

```
OPENROUTER_API_KEY=sk-or-...
# hosted speech-to-text (the default)
GROQ_API_KEY=gsk-...
```

Env vars take precedence over `.env` — handy for testing.

## Speech-to-text

Default is hosted: an OpenAI-compatible audio API, Groq
(`https://api.groq.com/openai/v1`, `whisper-large-v3-turbo`) unless you
change `stt.base_url`/`stt.model`; `stt.key_env` names the env var
holding the key.

Offline/private: set `stt.provider = "local"` for whisper.cpp:

```sh
sh scripts/fetch_whisper.sh      # clones + builds whisper-cli, downloads ggml-small.en
```

## Per-OS notes

- **Linux/Omarchy (Hyprland)**: fully wired — hold `SUPER+D` to talk,
  bar mark + live pill, companion overlay, hyprctl window ops.
- **Linux GNOME/KDE/X11**: planned, not yet supported. Wisp is
  Omarchy-first: it is built into Omarchy first and expands to other
  desktops later. A generic adapter exists in the code and is described
  in `docs/LINUX.md`, but it is not tested or promised, and nothing here
  should be read as support. Use Omarchy.

## First run

After `wispd install`, run the guided setup (or open the Panel, where a
first-run card shows the same steps until setup is finished):

If `~/.local/bin` is not yet on PATH, use `~/.local/bin/wispd` explicitly.
Installation does not start the daemon. When you choose, start it with
`systemctl --user start wispd` (or `~/.local/bin/wispd daemon run` in a
terminal), then do the microphone/bind test yourself. `doctor` reports
missing capabilities honestly; onboarding completion is not proof of a
successful live voice turn.

```sh
wispd onboard                    # walk the steps on a terminal
wispd onboard --status           # checklist only, exit 0
wispd onboard --step mic         # run one step
wispd onboard --undo mic         # forget one recorded step
wispd onboard --finish           # mark setup finished (hides the card)
wispd onboard --reset            # forget all progress
```

Steps, in order:

1. **mic**: a recorder (`pw-record`, `parecord` or `arecord`) and the
   whisper model (skipped when `stt.provider` is not `local`).
2. **models**: probes the local ladder over loopback only (Ornith
   `:8080`, Jev `:8091` and `:8931`, UI-TARS `:8081`, Ollama `:11434`).
   It never starts or stops a service; `wispd health start` is the
   manual way to do that.
3. **keys**: checks required provider keys; explicit key entry is private,
   never a command-line argument or copied into an agent conversation.
4. **agents** (optional): pinned ori/OpenCode install and sign-in, only
   with consent; decline it to finish core onboarding without agents.
5. **cua** (optional): the cua-driver probe from `wispd cua status`.
6. **notifications**: sends one test notification, only when you answer
   yes (or pass `--yes`).
7. **keybinding** (optional): checks that the keyboard submap (Esc stops,
   Enter confirms, number keys choose) is registered; shown as not
   available while the daemon has not registered it (Hyprland only).

Every step is skippable. A skip writes nothing and the step is offered
again next time. A step that passed is recorded in
`~/.local/share/wisp/onboard.json`, so a partly finished run resumes where
it stopped; `--undo` forgets one. Onboarding never edits `config.toml`.

## Settings

`wispd config keys` lists every setting wispd validates, with its default
and range. The same table (`wisp/settings_schema.py`) generates the
Panel settings tab (`shell-plugin/lib/settings_schema.js`, written by
`python scripts/assets/gen_settings.py`; `--check` fails when it is
stale) and the daemon's check in `wispd config set`, so a bad value gets
the same `E_BAD_CONFIG` message from the CLI, the Panel and the daemon.

## Verifying

The installed runbook is `~/.local/opt/wisp/docs/INSTALL.md`; starter tasks
and their provenance remain under `~/.local/opt/wisp/docs/`. Once you
explicitly enable dev mode and start the daemon, run the installed task
list from any working directory:

```sh
~/.local/bin/wispd dev run ~/.local/opt/wisp/docs/dev-tasks/starter.txt
```

That command invokes a live desktop run, not an installer smoke test.

```sh
wispd status          # daemon + state
wispd trigger         # run one listen cycle without the hotkey
wispd trace show --tail 20   # recent dev trace events (stages + timings)
```

## Background agents

The onboarding agents step (`wispd onboard --step agents`, optional) and
`wispd install --agents` download a pinned `ori` (Apache-2.0,
`OpenRouterLabs/ori-releases`) and OpenCode 2.x (MIT, `anomalyco/opencode`)
from their GitHub releases. Each download is checked against a SHA-256 baked
into Wisp before anything is installed; no sudo, and ori's own installer and
updater are never run. `wispd install --agents --dry-run` prints the two
URLs and writes nothing. Neither tool is bundled with Wisp.

They land in `~/.local/share/wisp/agent-runtime/<tool>/<version>/` behind a
`current` link, with OpenCode's private home and config in
`~/.local/share/wisp/agent-runtime/home/` and each named helper's folder in
`~/.local/share/wisp/agents/`. Signing in is part of the onboarding step: it
passes the OpenRouter key from your keyring (or opens ori's browser sign-in)
and never edits `config.toml`. Your own OpenCode, if you have one, is not
touched.

## Uninstall

```sh
systemctl --user disable --now wispd.service   # linux
rm -rf ~/.local/opt/wisp ~/.local/bin/wispd ~/.local/bin/wisp-trigger \
       ~/.local/share/applications/wisp.desktop \
       ~/.config/omarchy/plugins/io.github.duketopceo.wisp
# config + memory kept in ~/.config/wisp and ~/.local/share/wisp —
# remove those too for a full wipe.
rm -rf ~/.local/share/wisp/agent-runtime    # pinned ori + OpenCode (is under the data dir)
secret-tool clear service wisp account openrouter   # the stored key, if any
```
