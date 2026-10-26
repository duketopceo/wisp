# Installing Wisp

Wisp is a resident voice assistant: a `wispd` daemon plus a
push-to-talk trigger, a shell plugin (bar mark + live pill + overlay), and a management
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

## Secrets

`~/.config/wisp/.env`:

```
OPENROUTER_API_KEY=sk-or-...
GROQ_API_KEY=gsk-...        # hosted speech-to-text (the default)
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
- **Linux GNOME/KDE/X11**: runs via the desktop adapter; window ops
  degrade where the platform has no API (documented in
  `docs/LINUX.md`). Bind `wispd trigger` through your DE's shortcut
  settings.

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

## Uninstall

```sh
systemctl --user disable --now wispd.service   # linux
rm -rf ~/.local/opt/wisp ~/.local/bin/wispd ~/.local/bin/wisp-trigger \
       ~/.local/share/applications/wisp.desktop \
       ~/.config/omarchy/plugins/io.github.duketopceo.wisp
# config + memory kept in ~/.config/wisp and ~/.local/share/wisp —
# remove those too for a full wipe.
```
