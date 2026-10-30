# Installing Wisp

Wisp is a resident voice assistant: a `wispd` daemon plus a
push-to-talk trigger, a shell plugin (bar mark + live pill + overlay), and a management
app.

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
agent  python3 wispd install --dry-run       # show me every file and the bind it would add
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
  GUI (`shells/`), shell plugin source
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
nothing. A yes runs that tarball's `wispd install`; it does not restart
the daemon, so apply it with `systemctl --user restart wispd`. Installing
needs a terminal to ask you.

`wispd update` never goes backwards. It compares the release with what is
installed (version numbers when you installed a release; when you
deployed a git ref, the installed commit against the release tag on
GitHub) and refuses a release that is older, the same, diverged from your
install, or that it cannot compare, before downloading anything. A
`--dry-run` still previews it and says so. `wispd update --force` installs
it anyway, and still asks for your yes.

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
3. **cua** (optional): the cua-driver probe from `wispd cua status`.
4. **notifications**: sends one test notification, only when you answer
   yes (or pass `--yes`).
5. **keybinding** (optional): checks that the keyboard submap (Esc stops,
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
