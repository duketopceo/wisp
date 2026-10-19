# Ops — running wisp on omarchy-max

## Services and ports

| Thing | Where | Notes |
|---|---|---|
| `wispd` (user) | systemd `--user` | the daemon; `systemctl --user restart wispd` |
| IPC | `$XDG_RUNTIME_DIR/wisp/wispd.sock` | AF_UNIX + SO_PEERCRED |
| Live state | `$XDG_RUNTIME_DIR/wisp/state.json` | StateBus snapshot the shell reads |
| brain (primary) | OpenRouter, `google/gemini-2.5-flash` | `[brain]` in `~/.config/wisp/config.toml` |
| llama-local | `127.0.0.1:8080` | Ornith-35B GPU brain (fallback/local mode) |
| llama-jev | `:8091` | qwen3-4b decisions |
| jev-shim | `:8931` | decisions-API emulator (`WISP_JEV_ENDPOINT`) |
| llama-uitars | `:8081` | UI-TARS-7B GUI grounding provider |
| Ollama | `:11434` | CPU models |
| cua-driver | unix socket | rust injector + `cua-hyprland` plugin |
| BrowserOS | `:9200` MCP | default browser / DOM lane |
| STT | Groq whisper turbo | `[stt]` config |

`wisp-backend local|openrouter|status` flips brain+Jev between the local
stack and OpenRouter; `wisp-backend-watch.service` auto-falls back when
the llamas go unhealthy.

## Debug spine (dev mode)

`[debug] trace = true` → `~/.local/share/wisp/trace.jsonl`, one JSONL
event per stage per turn. Events: `span` (ms + offset from keypress),
`screen_capture` (img_kb, qa_skip), `shot_normalize` (in/out dims+KB),
`shot_compress` (png→jpeg KB), `llm_call` (brain, msgs, img_kb,
tools_out, reply head, ms), `tool_call`/`tool_result`, `ground`/
`ground_refused`, `brain_fallback`, ipc, lifecycle.

```
wispd trace --tail 50              # recent events
wispd trace --turn <id>            # one full turn
wispd trace --kind tool            # tool traffic only
wispd trace --latency --since 24h  # p50/p90 per stage
```

`wispd doctor` — health check (integrations, skills, data files).

## Known failure modes → recovery

| Symptom | Cause | Fix |
|---|---|---|
| clicks refused, `list_windows` returns `[]` | cua-hyprland plugin session stale (compositor epoch mismatch after reload) | restart the cua-driver/plugin; verify `wispd cua` reports real windows |
| `Jev HTTP 502` / decisions fail | llama-* killed by systemd-oomd under memory pressure | `systemctl --user reset-failed llama-local llama-jev llama-uitars jev-shim && systemctl --user start ...`; backend-watch usually auto-falls back first |
| keyring auth prompt over windows | gnome-keyring daemon race (D-Bus vs systemd instance) | `systemctl --user reset-failed gnome-keyring-daemon{,.socket}`, kill stragglers, start `gnome-keyring-daemon` |
| dictation dead / 401s | WordInk token drift after home sync | `~/bin/wordink-rotate-token` |
| voxtype spins 100% CPU | ALSA POLLERR after USB audio disappears | `systemctl --user restart voxtype` |
| answers silent | voice disabled or espeak missing | `[voice] enabled`; check `speak` events in trace |
| act clicks land ~2x off | shot not normalized (pixel space mismatch) | confirm `shot_normalize` in trace; logical px must match caption dims |

## Verify after changes

```
python3 wispd install            # from the source checkout, not PATH wispd
systemctl --user restart wispd
.venv/bin/python -m unittest discover -s tests   # 1900+; PIL/darwin-gated skips are normal
```

QML snapshots: `scripts/ui/snap.py` (check/update); golden drift across
font stacks is expected — regenerate deliberately, never mid-change.
