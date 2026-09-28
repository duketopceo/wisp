# Dim IPC + State Contract v1

The stable boundary between `dimd` (any implementation — Python
reference or `dimd-rs`) and UI shells (Omarchy quickshell plugin,
future tray apps). Shells MUST only depend on this document.

## Transport

- Linux/macOS: unix domain socket at
  `$XDG_RUNTIME_DIR/dim-agent/dimd.sock` (fallback `/tmp/dim-agent/`).
- Windows (future): named pipe `\\.\pipe\dim-agent`, same framing.
- Framing: one JSON object per connection, newline-terminated request
  and newline-terminated reply. Request: `{"cmd": <string>, ...}`.
- Reply envelope: `{"ok": bool, ...}`; on failure `ok=false` plus
  `{"error": <string>}`.

## Commands

| cmd | extra fields | reply | effect |
|---|---|---|---|
| `status` | — | `{ok, state}` | `state` = full state.json snapshot |
| `listen` | — | `{ok}` or `{ok:false,error:"busy"}` | starts a listen cycle async; kills in-flight TTS (barge-in) |
| `choice` | `pick: string` | `{ok}` | resolves a pending choice/confirm |
| `task_status` | `name: string` | `{ok, result: string}` | named-agent status |
| `task_cancel` | `name: string` | `{ok, result: string}` | cancel named agent |
| `stop` | — | `{ok}` | daemon exits, socket removed; kills in-flight TTS |
| `config` | `set: {"section.key": "val"}` (optional) | `{ok, config}` | read config; with `set`, writes config.toml preserving comments/order and live-reloads |
| `learn` | — | `{ok, result}` | weekly learning proposals (human-gated) |
| `harness` | — | `{ok, result}` | regenerate the app harness catalog |
| unknown/malformed | — | `{ok:false, error}` | — |

`config` keys are `section.key` (e.g. `agent.answer_model`); the daemon
returns `{ok:false}` if any key lacks a section. Shells may offer a
settings page on top of this command.

## state.json (atomically rewritten, tmp+rename)

```json
{
  "status": "idle|listening|transcribing|deciding|awaiting_choice|acting|speaking|done|error",
  "transcript": "string",
  "answer": "string",
  "result": "string",
  "choices": ["string"],
  "points": [{"x": 0, "y": 0, "label": "string", "step": 1}],
  "level": 0.0,
  "tasks": {"name": "running|done|failed|cancelled"},
  "error": "string",
  "started_at": "ISO-8601"
}
```

Confirmation gate: when a mutating/shell action needs approval, the
core transitions to `awaiting_choice` with `choices` = e.g.
["<prompt> — yes", "no"]; clients reply via `choice` (pick string).
Both cores use this same mechanism — neither may block holding a
client's request socket open for the answer.

Result/result-text fields (`result`, `error`, task statuses, `harness`
and `learn` output) are human-readable free text — parity asserts the
envelope (`ok` bool + field presence), not message wording.

Status vocabulary is closed; shells must treat unknown statuses as
`idle`-equivalent rather than failing. `points` may be absent/empty on
older cores — default `[]`. Point fields: `x`,`y` are Hyprland logical
coordinates (already normalized from screenshot pixels via monitor
scale); `label` and `step` are optional strings/ints. The model emits
them as `[POINT:x,y:label]` / `[POINTS:[{x,y,label}]]` tags in
screenshot-pixel coords; the core strips tags from the displayed/
spoken answer and publishes the normalized list.

## Data files (shared by both cores, never versioned differently)

- `decisions.jsonl` — one JSON per turn: `ts`, `transcript`, `answers`,
  `result`, `timing_ms{record,stt,jev,act}`, `corrected`.
- `session.jsonl` — turns for follow-up context.
- `corrections.jsonl` — user picks on ambiguous turns.
- `tasks.jsonl` — agent registry; `tasks/<id>.log` per-agent output.
- `MEMORY.md`, `USER.md` — curated bounded memory (frozen snapshot).
- `skills/*/SKILL.md` — self-authored skills (progressive disclosure).
- `trace.jsonl` — full-fidelity dev trace (`[debug] trace`, default on):
  one event per line `{ts, turn, step, kind, ms, data}` covering
  listen_start/record/transcribe/decision/dispatch/tool_call/
  tool_result/brain_call/answer/speak/points/ipc/error. `dimd trace`
  `--tail N --turn <id> --kind <k>` on both cores. Rotates at 10 MB;
  never logs secrets.
- `recall.db` — sqlite-vec/FTS5 long-term recall.

## Versioning

Contract version = top of this file. Shells read
`state.contract_version` when present; absent ⇒ v1. Additive fields are
allowed without a bump; changed/removed semantics bump the version.
