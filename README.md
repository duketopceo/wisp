# Dim

Dim, open spotify. — a Jev-powered voice computer-use agent for Omarchy
(Hyprland on Asahi Linux). Push-to-talk, the room dims, Dim hears, decides,
and acts.

Push-to-talk → PipeWire mic capture → whisper.cpp transcription → Jev decision (OpenRouter) → guarded Hyprland action, with a dim overlay while listening/acting.

## Features

- **v0.1 vertical slice**: Right Alt + Space → 5s mic capture → whisper.cpp →
  Jev (`openrouter.ai/api/alpha/decisions`, model `~typesafe/jev-latest`) →
  guarded launch (`hyprctl dispatch exec`) + notify-send.
- **Breathing darkness**: overlay opacity modulates with live mic amplitude
  during capture; silence restores full brightness.
- **Confidence-gated UI**: Jev confidence ≥ 0.95 executes instantly; < 0.8
  shows the ambiguous choices as clickable buttons in the overlay.
- **Decision log + corrections lane**: every decision is appended to
  `~/.local/share/dim-agent/corrections.jsonl` (XDG data dir);
  `scripts/propose_criteria.py` (manual, weekly,
  NOT cron-scheduled yet) clusters corrections into proposed new choice
  criteria. Review the proposal, then edit `JEV_QUESTIONS` in `dimd`.

## Architecture

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

**Right Option (Alt_R) + Space** is push-to-talk (default). Super+Space is reserved for input-method switching on this machine. Remap in `~/.config/dim-agent/config.toml`:

```toml
[hotkey]
mod = "ALT_R"   # keysym — parsed as a multi-key bind, not a modmask
key = "Space"
```

`dimd install` copies `dimd` + `dim-overlay` to `~/.local/opt/dim-agent/`, writes the `~/.local/bin/dim-agent-trigger` shim, and appends a Lua bind to `~/.config/hypr/bindings.lua` (idempotent):

```lua
o.bind("Alt_R + SPACE", "Dim push-to-talk", { launch = "~/.local/bin/dim-agent-trigger" })
```

Omarchy configures Hyprland in **Lua** — `hyprland.conf` is not sourced, and `dimd install` strips any legacy `bind =` line it wrote there. Because `Alt_R` resolves to a keysym, the bind is a multi-key chord: it fires on the *right* Option only. Note that a generic `ALT + SPACE` bind elsewhere still matches either alt — scope such binds to `Alt_L` (this machine keeps `Alt_L + Space` for voxtype dictation). Check conflicts first: `omarchy menu keybindings --print | grep SPACE`.

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
