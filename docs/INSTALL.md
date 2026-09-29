# Installing Wisp

Wisp is a resident voice assistant: a `wispd` daemon plus a
push-to-talk trigger, a shell plugin (orb + overlay), and a management
app.

## From a release tarball/zip

```sh
tar xzf wisp-linux-aarch64.tar.gz && cd wisp-linux-aarch64
python3 wispd install          # launcher sits at archive root, next to wisp/        # core files + service + plugin + menu entry
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
