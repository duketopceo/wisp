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
| `choice` | `pick: string`, optional `prompt_id: string`, optional `index: int` | `{ok}` or `{ok:false, error}` | resolves the pending choice/confirm; see Prompt ids |
| `task_status` | `name: string` | `{ok, result: string}` | named-agent status |
| `task_cancel` | `name: string` | `{ok, result: string}` | cancel named agent |
| `agent` | `task: string` | `{ok, result: string}` | spawn a background task via `[brain] agent_runtime`; `result` is `SPAWNED …`/`SKIP …` |
| `memory` | `arg` or `target`+`body` | `{ok, result: string}` | `arg` = tool grammar `target|op|old|new`; `target`+`body` = whole-doc `write` (GUI editor path — pipes/newlines safe) |
| `subscribe` | `topics?: ["state","health","tasks","events"]` | NOT one reply: a push stream, see Push stream | long-lived connection of newline-delimited JSON events |
| `stop` | — | `{ok}` | daemon exits, socket removed; kills in-flight TTS |
| `interrupt` | — | `{ok}` | cancels the in-flight turn only — daemon stays up; see Cancellation |
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
  "prompt_id": "string — id of the offered choices/confirm; \"\" when none",
  "points": [{"x": 0, "y": 0, "label": "string", "step": 1}],
  "steps": ["tool arg → result", "…"],
  "guide": {"x": 0, "y": 0, "label": "string", "mode": "guide|drive", "seq": 1},
  "focus": {"app": "string", "title": "string"},
  "goal": {"text": "string", "status": "open|done|failed"},
  "level": 0.0,
  "tasks": {"name": "running|done|failed|cancelled"},
  "error": "string — human-safe copy, never raw exception text",
  "error_code": "closed set, see below; \"\" when no error",
  "error_detail": "string — raw failure text, local only",
  "health": {"<endpoint>": {"ok": true, "since": "ISO-8601", "latency_ms": 12, "code": null}},
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

Error codes (additive, Python core; U7): when `status` is `error`,
`error_code` is one of `jev_down`, `brain_down`, `stt_down`,
`ground_down`, `ground_failed`, `timeout`, `cancelled`, `busy`,
`stale_prompt`, `restarted`, `tool_failed`, `budget_exceeded`,
`internal`. Shells render copy from the code and must treat unknown
codes as `internal`. `error_detail` is for logs and `wispd watch`, not
for display. A turn that starts (`listening`) clears all three.

Health (additive; U7): `health` maps local endpoint names (`jev`,
`brain_<provider>`, `ollama`, `uitars`, `stt`, plus hook-registered
ones such as `hypr`) to `{ok, since, latency_ms, code}`; `latency_ms`
is from the first probe and any later transition, `code` is null while
ok. It is republished on first observation and on every ok/down
transition, each with a stream event
`{"type":"event","name":"health_changed","data":{name,ok,code}}`.
Absent or `{}` on older cores and while probing is disabled. Remote
endpoints are never probed and never listed.

Prompt ids (additive; U9): every `awaiting_choice` publishes `choices`
together with a `prompt_id`, and clears both when the prompt resolves.
`choice` may carry `prompt_id` and/or `index` (1-based into `choices`;
`wispd choice [pick] [--prompt-id ID] [--index N]`). Replies:
`{ok:true}` when applied; `{ok:false, error:"stale_prompt"}` when no
prompt is pending or `prompt_id` is not the pending one (the pending
prompt keeps waiting); `{ok:false, error:"not_offered"}` for a `pick`
not in `choices`; `{ok:false, error:"bad_index"}` for an `index` out of
range. A `choice` without `prompt_id` is accepted only while a prompt is
pending (exactly one ever is) — this keeps current shells working. An
empty `pick` dismisses the prompt like a timeout. The core also refuses
an unoffered pick that reaches the turn by another path (trace
`choice_rejected`) and falls back to its safe auto-pick.

Cancellation (additive; U9): `interrupt` cancels the current turn at
whatever stage it is in — the whisper child and tool subprocesses are
killed, Jev/STT/brain connections are closed (a late reply is never
read), the brain stream stops publishing deltas, speech is killed, and
a cancelled turn never falls back to the next brain. The turn unwinds
to `status: idle` with `error_code: "cancelled"` (`error` empty);
`result` carries `INTERRUPTED (user)` when an act step was running. A
new turn (`listening`) clears `error_code`. Speech now starts per
completed sentence while the answer streams (state still goes
`speaking` → `done` when the last sentence ends).

Confirmation gate: when a mutating/shell action needs approval, the
core transitions to `awaiting_choice` with `choices` = e.g.
["<prompt> — yes", "no"]; clients reply via `choice` (pick string, or
`index`, with the `prompt_id` they saw).
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

## Push stream (additive; W3)

`{"cmd":"subscribe","topics":[...]}` (topics optional, default all) turns
the connection into a server-to-client stream of newline-delimited JSON.
The client sends nothing further; it closes the socket to unsubscribe.
Core-only and additive: shells that keep reading `state.json` are
unaffected, and `state.json` is still written on every change.

Lines, in order:

1. `{"type":"hello","ok":true,"contract_version":1,"topics":[...]}`.
   On refusal (`unknown topic`, no bus) `{"type":"hello","ok":false,
   "error":"..."}` and the daemon closes.
2. `{"type":"snapshot","seq":N,"state":{...}}`, the full state.json
   content at subscribe time. Every connect, including a reconnect,
   starts with a fresh snapshot, so a client never replays history.
3. Then, as they happen:
   - `{"type":"state","seq":N+1,"diff":{...}}` (topic `state`): the
     changed fields plus `seq`, `updated_at`, `turn_id`. `seq` rises by
     exactly one per written snapshot: the first diff is `snapshot.seq+1`
     and a gap means the client missed data and must reconnect. Diffs
     include `heartbeat_at` (every 15 s while transcribing, deciding or
     acting) and `tasks` / `health` when those change.
   - `{"type":"event","name":"health_changed","data":{...}}` (topic
     `health`); `{"type":"event","name":"task_finished","data":{name,
     status,tail}}` (topic `tasks`; any `task_*` name belongs to it);
     other named events belong to `events`. Events do not bump `seq`.
   - `{"type":"event","name":"cua.target","data":{x,y,window,label,
     confidence,phase}}` (topic `events`; W21 reader, W13 emitter): the
     screen point a computer-use click is about to hit, so the ghost
     cursor can show it while the real pointer stays put. See
     "cua.target" below.
   - `{"type":"ping"}` after 15 s with nothing to send (all topics; a
     keep-alive, ignore it). Clients should treat 45 s of silence as a
     dead connection and reconnect.

### cua.target (ghost cursor input)

`data` fields: `x`, `y` numbers, screen pixels in the compositor's global
layout (required, finite); `window` string, the target window title or
class (may be empty); `label` string, a short element name such as
"night light" (may be empty); `confidence` number 0..1 from the grounding
model (default 1); `phase` one of `aim` (default; the ghost travels to the
point and parks), `click` (one ripple at the tip), `done` (the click
landed; the ghost dims and returns). `{"x":null,"y":null}` clears.

Reader rules (`shell-plugin/lib/state.js`, `view.cuaTarget`): the event
is applied only while `status` is `acting`, `deciding` or
`awaiting_choice`; a malformed payload is ignored and leaves the current
target; the target is dropped when the status leaves those, when
`turn_id` changes, and when the daemon goes offline. No target means the
ghost cursor renders nothing. The emitter sends at most one `aim` per
action, then `click`, then `done`; it need not repeat unchanged targets.
W13 (`wisp/act.py` via `wisp/grounding.py`) emits it for every act-loop
click/move: `aim` once the point is resolved, then `click` and `done`
when the click landed; a failed, refused or dry-run click sends the
clear. A guide-mode click or a move leaves the `aim` parked. Fixtures
also drive it (`tests/qml/harness/scenes.json`).

Topic filtering happens in the daemon: unrequested events are never
queued for that client. Ordering is the bus's write order, identical for
every subscriber.

Backpressure: each subscriber has its own bounded queue (256 events) fed
from the bus without blocking it. A subscriber that falls behind, or
whose socket stays unwritable for 5 s, is dropped: the daemon sends a
final `{"type":"event","name":"overflow"}` when it still can, then
closes. A dropped client reconnects and gets a new snapshot. A slow
subscriber never delays state.json writes or other subscribers.

`wispd watch [topic ...]` prints this stream (reconnecting forever).

Agent reaper (core behaviour behind the `tasks` field): every 5 s the
daemon closes tasks whose process is gone (`exited`), SIGTERMs tasks past
`[agent] task_timeout_s` (`timed_out`), SIGKILLs a cancelled or timed-out
process that ignored SIGTERM for 10 s, and never signals a pid whose
start-time differs from the one recorded at spawn (PID reuse). Each
running to not-running transition publishes the new `tasks` and one
`task_finished` event.

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
- goal state — in-memory only (`wisp/goals.py`, `goal_ttl_s` TTL, lost
  on restart); not a file.
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
