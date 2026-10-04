# Wisp IPC + State Contract v1

The stable boundary between `wispd` (any implementation — Python
reference or `wispd-rs`) and UI shells (Omarchy quickshell plugin,
future tray apps). Shells MUST only depend on this document.

## Transport

- Linux: unix domain socket at
  `$XDG_RUNTIME_DIR/wisp/wispd.sock` (fallback `/tmp/wisp/`).
- macOS: unix domain socket at `$TMPDIR/wisp/wispd.sock`.
- Windows: TCP loopback — daemon binds `127.0.0.1:<ephemeral>` and
  writes the port to `%TEMP%\wisp\wispd.sock` as a plain text
  file; clients read the port then connect. Identical framing.
- Framing: one JSON object per connection, newline-terminated request
  and newline-terminated reply. Request: `{"cmd": <string>, ...}`.
- Reply envelope: `{"ok": bool, ...}`; on failure `ok=false` plus
  `{"error": <string>}`.

## Commands

| cmd | extra fields | reply | effect |
|---|---|---|---|
| `status` | — | `{ok, state}` | `state` = full state.json snapshot |
| `listen` | `phase?: start\|stop`, `t0?: int` (client wall-clock ns of the keypress; additive, optional) | `{ok}` or `{ok:false,error:"busy"}` | starts a listen cycle async; kills in-flight TTS (barge-in) |
| `choice` | `pick: string` | `{ok}` | resolves a pending choice/confirm |
| `task_status` | `name: string` | `{ok, result: string}` | named-agent status |
| `task_cancel` | `name: string` | `{ok, result: string}` | cancel named agent |
| `agent` | `task: string` | `{ok, result: string}` | spawn a background task via `[brain] agent_runtime`; `result` is `SPAWNED …`/`SKIP …` |
| `memory` | `arg` or `target`+`body` | `{ok, result: string}` | `arg` = tool grammar `target|op|old|new`; `target`+`body` = whole-doc `write` (GUI editor path — pipes/newlines safe) |
| `stop` | — | `{ok}` | daemon exits, socket removed; kills in-flight TTS |
| `interrupt` | — | `{ok}` | cancels the in-flight turn only — daemon stays up |
| `config` | `set: {"section.key": "val"}` (optional) | `{ok, config}` | read config; with `set`, writes config.toml preserving comments/order and live-reloads |
| `label` | `label: correct\|incorrect` | `{ok, result}` | tag the most recent decision (soak intent-match + trajectory join) |
| `context` | — | `{ok, result}` | focused app, `[windows]` workspace map, inventory counts |
| `inventory` | — | `{ok, result}` | rescan local terrain → `inventory.json` |
| `connect` | `service` or `list` | `{ok, result, json?}` | OAuth connector flow via BrowserOS Strata; `list` returns the catalog (add `--json` for machine-readable) |
| `recipes` | `approve <name>` optional | `{ok, result}` | list draft recipe-* proposals; `approve` installs as a skill |
| `tele` / `fails` | — | `{ok, result}` | decision telemetry / recent failures |
| `learn` | — | `{ok, result}` | weekly learning proposals (human-gated) |
| `harness` | — | `{ok, result}` | regenerate the app harness catalog |
| unknown/malformed | — | `{ok:false, error}` | — |

`config` keys are `section.key` (e.g. `agent.answer_model`); split is on
the **last** dot, so nested sections work — `brain.ollama.base_url` →
`[brain.ollama] base_url`. The daemon returns `{ok:false}` if any key
lacks a section. Shells may offer a settings page on top of this command.

## state.json (atomically rewritten, tmp+rename)

```json
{
  "status": "idle|listening|transcribing|deciding|awaiting_choice|acting|speaking|done|error",
  "transcript": "string",
  "answer": "string",
  "result": "string",
  "choices": ["string"],
  "points": [{"x": 0, "y": 0, "label": "string", "step": 1}],
  "steps": ["tool arg → result", "…"],
  "guide": {"x": 0, "y": 0, "label": "string", "mode": "guide|drive", "seq": 1},
  "focus": {"app": "string", "title": "string"},
  "goal": {"text": "string", "status": "open|done|failed"},
  "level": 0.0,
  "tasks": {"name": "running|done|failed|cancelled"},
  "error": "string",
  "started_at": "ISO-8601",
  "turn_id": "string — turn that produced this write",
  "seq": 0,
  "updated_at": "ISO-8601",
  "contract_version": 1,
  "heartbeat_at": "ISO-8601|null — refreshed every 15 s while transcribing/deciding/acting"
}
```

Single publisher (Python core): one `StateBus` owns every write. `seq`
increases by one per written snapshot; a write from a turn that is no
longer current is dropped; `level` is rate-limited to ~12 writes/s.
Shells still just read the file — all of these fields are additive.

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
- `labels.jsonl` — human labels (`correct`/`incorrect`) keyed to the
  decision ts; joined to trajectories via the decision's transcript.
- `trajectories.jsonl` — episodic act-loop memory (task, app, steps,
  outcome); feeds `context_for()` and `propose_recipes()`.
- `goals.json` — open/closed goal state for cross-utterance continuity.
- `inventory.json` — scanned local terrain (apps, cli_tools, mcp
  servers, omarchy plugins/binds, dayflow, skills); 24h TTL.
- `MEMORY.md`, `USER.md` — curated bounded memory (frozen snapshot).
- `skills/*/SKILL.md` — self-authored skills (progressive disclosure).
- `trace.jsonl` — full-fidelity dev trace (`[debug] trace`, default on):
  one event per line `{ts, turn, step, kind, ms, data}` covering
  listen_start/record/transcribe/decision/dispatch/tool_call/
  tool_result/brain_call/answer/speak/points/ipc/error, plus `kind=span`
  events (`step` = press, release, stt, context, route, first_token,
  first_step, tts_start, done, and sub-spans screenshot/hyprctl/memory/
  goal; `ms` = duration, `data.offset_ms` from the keypress,
  `data.t0_source` client|daemon). `wispd trace`
  `--tail N --turn <id> --kind <k>` on both cores; Python core adds
  `--latency [--since 24h]` (p50/p90 per budget path). Rotates at 10 MB;
  never logs secrets.
- `recall.db` — sqlite-vec/FTS5 long-term recall.

## Versioning

Contract version = top of this file. Shells read
`state.contract_version` when present; absent ⇒ v1. Additive fields are
allowed without a bump; changed/removed semantics bump the version.
