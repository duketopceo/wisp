# dim-agent

A Jev-powered voice computer-use agent for Omarchy (Hyprland on Asahi Linux).

Push-to-talk → PipeWire mic capture → whisper.cpp transcription → Jev decision (OpenRouter) → guarded Hyprland action, with a dim overlay while listening/acting.

## Architecture (v0.1)

```
[Right Alt + Space] ──bind──▶ dimd ──▶ pw-record 5s mic wav
                                        │
                                        ▼
                                 whisper.cpp (ggml-base.en)
                                        │
                                        ▼
                          POST openrouter.ai/api/alpha/decisions
                          model: ~typesafe/jev-latest
                          questions: app / action / risk
                                        │
                              risk ≤ 1 and action == launch
                                        ▼
                       hyprctl dispatch exec <app> + notify-send
```

## Layout

- `dimd` — daemon: watches for the hotkey trigger (spawned by the Hyprland bind), records, transcribes, decides, acts.
- `dim-overlay` — fullscreen dim overlay (see Overlay below).
- `config.toml` — user config (hotkey, apps, risk threshold), at `~/.config/dim-agent/config.toml`.
- `dim-agent.service`-free: v0.1 is bind-spawned, no systemd unit yet.

## Hotkey

**Right Alt + Space** is push-to-talk (default). Super+Space is reserved for input-method switching on this machine. Remap in `~/.config/dim-agent/config.toml`:

```toml
[hotkey]
mod = "ALT_R"   # Hyprland modmask token
key = "Space"
```

The installer writes the matching `bind = ALT_R, Space, exec, ~/.local/bin/dim-agent-trigger` line into `~/.config/hypr/hyprland.conf` (idempotent — skips if `dim-agent` bind already present). Check for conflicts first: `hyprctl binds | grep -A3 ALT_R`.

## Overlay choice (documented decision)

`eww` is not installed and pulls a GTK3 build chain; `gtk-layer-shell` IS installed (`extra/gtk-layer-shell 0.10.1-1`) along with `python-gobject`. Simplest working path: a tiny **PyGObject + gtk-layer-shell fullscreen overlay** — a native wlr-layer-shell client, no chromium kiosk hack, ~40 lines. Fallback if layer-shell fails: chromium kiosk at 40% opacity (not implemented).

## Dependencies (laptop, Arch)

- hyprctl, wpctl/pipewire, `pw-record` (pipewire-audio)
- whisper.cpp built at `~/src/whisper.cpp` (model: `ggml-base.en.bin`)
- python3.11+ (3.11.16 installed; system 3.14), `python-gobject`, `gtk-layer-shell`
- espeak-ng (testing), ffmpeg, `notify-send` (libnotify)

## Env

`~/.config/dim-agent/.env` (chmod 600):
```
OPENROUTER_API_KEY=sk-or-...
```
Never committed.

## Testing without a human voice

`tests/stage_test.sh`: espeak-ng "open terminal" → wav → whisper.cpp → transcript → Jev call → hyprctl launch. See `SLICE_TEST_RESULTS.md` for outputs.

## Status

- v0.1: vertical slice (voice → Jev → launch, guarded) ✔
- v0.2: dim overlay (gtk-layer-shell) ✔
- next: type_text / run_shell actions with explicit confirmation, streaming partials
