# Installing Wisp

Wisp is a resident voice assistant: a `wispd` daemon plus a
push-to-talk trigger, a shell plugin (orb + overlay), and a management
app.

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
  opens the management app
- Omarchy plugin `io.github.duketopceo.wisp` (Linux/Omarchy)
- a service: `wispd.service` (systemd user, Linux),
  `ai.wisp.wispd` launchd plist (macOS), Task Scheduler `Wisp` (Windows)
- the push-to-talk bind in `~/.config/hypr/bindings.lua` (Hyprland only)

## Secrets

`~/.config/wisp/.env`:

```
OPENROUTER_API_KEY=sk-or-...
GROQ_API_KEY=gsk-...        # only if stt.provider = "openai"
```

Env vars take precedence over `.env` — handy for testing.

## Speech-to-text

Default is local whisper.cpp (free, private):

```sh
sh scripts/fetch_whisper.sh      # clones + builds whisper-cli, downloads ggml-small.en
```

Faster/cloud: set `stt.provider = "openai"`, `stt.base_url` to Groq
(`https://api.groq.com/openai/v1`) or any OpenAI-compatible audio API,
`stt.key_env` to the env var name holding the key.

## Per-OS notes

- **Linux/Omarchy (Hyprland)**: fully wired — `SUPER+D` talks, orb in
  the bar, overlay, hyprctl window ops.
- **Linux GNOME/KDE/X11**: runs via the desktop adapter; window ops
  degrade where the platform has no API (documented in
  `docs/LINUX.md`). Bind `wispd listen` through your DE's shortcut
  settings.
- **macOS**: `wispd install` writes the launchd plist; bind `wispd
  listen` via SKHD/Raycast. Grant Screen Recording + Accessibility.
  See `docs/MACOS.md`.
- **Windows**: `wispd install` registers the logon task; bind via a
  hotkey tool to `wispd.exe listen`. See `docs/WINDOWS.md`.

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
5. **keybinding** (optional): needs the W24 keyboard submap; shown as not
   available until that lands.

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
wispd trace --tail    # the dev trace — every turn's stages + timings
```

## Uninstall

```sh
systemctl --user disable --now wispd.service   # linux
rm -rf ~/.local/opt/wisp ~/.local/bin/wispd ~/.local/bin/wisp-trigger \
       ~/.local/share/applications/wisp.desktop \
       ~/.config/omarchy/plugins/io.github.duketopceo.wisp
# config + memory kept in ~/.config/wisp and ~/.local/share/wisp —
# remove those too for a full wipe.
```
