# Wisp IPC + State Contract v2

The stable boundary between `wispd` (any implementation — Python
reference or `wispd-rs`) and UI shells (Omarchy quickshell plugin,
future tray apps). Shells MUST only depend on this document.

## Transport

- Linux: unix domain socket at
  `$XDG_RUNTIME_DIR/wisp/wispd.sock` (fallback `/tmp/wisp/`).
- Framing: one JSON object per connection, newline-terminated request
  and newline-terminated reply. Request: `{"cmd": <string>, ...}`.
- Reply envelope: `{"ok": bool, ...}`; on failure `ok=false` plus
  `{"error": <string>}`.

## Commands

| cmd | extra fields | reply | effect |
|---|---|---|---|
| `status` | — | `{ok, state}` | `state` = full state.json snapshot |
| `listen` | `phase?: start\|stop`, `t0?: int` (client wall-clock ns of the keypress; additive, optional) | see below | capture + pipeline async on idle; **mini-capture** while a turn is busy; kills in-flight TTS on a new turn (barge-in) |
| `choice` | `pick: string`, optional `prompt_id: string`, optional `index: int` | `{ok}` or `{ok:false, error}`; `{ok, result}` for `suggestion:` picks | resolves the pending choice/confirm; see Prompt ids |
| `suggestions` | — | `{ok, suggestions: [...]}` | pending routine suggestions (suggestions.jsonl backlog) |
| `task_status` | `name: string` | `{ok, result: string}` | named-agent status |
| `task_cancel` | `name: string` | `{ok, result: string}` | cancel named agent |
| `agent` | `task: string` | `{ok, result: string}` | spawn a background task via `[brain] agent_runtime`; `result` is `SPAWNED …`/`SKIP …` |
| `memory` | `arg` or `target`+`body` | `{ok, result: string}` | `arg` = tool grammar `target|op|old|new`; `target`+`body` = whole-doc `write` (GUI editor path — pipes/newlines safe) |
| `subscribe` | `topics?: ["state","health","tasks","events"]` | NOT one reply: a push stream, see Push stream | long-lived connection of newline-delimited JSON events |
| `stop` | — | `{ok}` | daemon exits, socket removed; kills in-flight TTS |
| `interrupt` | — | `{ok}` | cancels the in-flight turn only — daemon stays up; see Cancellation |
| `config` | `set: {"section.key": "val"}` (optional) | `{ok, config}` | read config; with `set`, writes config.toml preserving comments/order and live-reloads |
| `label` | `label: correct\|incorrect` | `{ok, result}` | tag the most recent decision (read by `wispd eval` and the trajectory join) |
| `dictate_correct` | `{"heard","meant"}` | `{ok, result}` or `{ok:false, error, result}` | record a personal dictation correction → `dictation.json` (U6); cleanup/compose prompts carry the table |
| `context` | — | `{ok, result}` | focused app, `[windows]` workspace map, inventory counts |
| `captures` | `turn_id?: string`, `full?: bool`, `limit?: int` | `{ok, packs}` or `{ok, manifest}` | read capture-pack list or manifest |
| `task_output` | `name: string` | `{ok, name, status, exit_code, output}` | read named-agent log output (U2) |
| `task_artifacts` | `name: string` | `{ok, name, out_dir, delivered, deliverables, artifacts}` | read named-agent output workspace + deliverable verification (U2) |
| `learn` | — | `{ok, result}` | no-op; weekly proposals were removed |
| `harness` | — | `{ok, result}` | regenerate the app harness catalog |
| unknown/malformed | — | `{ok:false, error}` | — |

### Command authorization & marked-peer boundary (U1, R2)

The daemon captures `SO_PEERCRED` (`{pid, uid}`) on every AF_UNIX connection and classifies IPC commands into two sets (**deny-by-default**):

- **Read class (`READ_CMDS`):** `status`, `task_status`, `context`, `subscribe`, `captures`, `suggestions`, `task_output`, `task_artifacts`. `captures` with `full: true` (transcript/state-dump fields) is refused for marked peers with `"reason": "gated_read"`.
- **Mutating class (`MUTATING_CMDS` + anything unlisted):** `agent`, `task_cancel`, `choice`, `config`, `memory`, `stop`, `interrupt`, `listen`, `label`, `dictate_correct`, `learn`, `harness`, and any unknown or future command not in `READ_CMDS`. `config` and `memory` are mutating as whole commands, so their get forms (`wispd config`, `wispd memory`) are refused for marked peers too: a `config` reply carries the full config, including key references.

Every process spawned via `agent_spawn` is placed in a registered task scope (`wisp-task-<id>.scope` via `systemd-run --user --scope` on systemd hosts, recorded in `tasks.jsonl` alongside `WISP_TASK_ID` and root PID/start-time). On each request `_dispatch` checks the connecting peer:

1. **Marked peer (verified against `tasks.jsonl` via cgroup scope, PID/ancestry, or `WISP_TASK_ID`):** allowed `READ_CMDS` only. Any mutating or unlisted command is refused with `{"ok": false, "error": "marked_peer_refused", "reason": "mutating_cmd"|"safety_key"|"gated_read", "cmd": <cmd>, "task_id": <id>}`, and `refused_count` is incremented on the task record in `tasks.jsonl`. `config set` on safety-lowering keys (`agent.allow_shell`, `agent.autonomy`, `agent.risk_threshold`, `cua.*`, any `budget.*` key, `agents.act_max_usd`, `pointer.mode`) refuses marked peers with `"reason": "safety_key"`.
2. **Spoofed marker (a `wisp-task-*.scope` cgroup matching no task record in `tasks.jsonl` (any status), or a `WISP_TASK_ID` not matching a running task):** refused on all commands with `{"ok": false, "error": "marked_peer_refused", "reason": "unregistered_task_id"|"unregistered_scope"}`.
3. **Unmarked same-uid peer (normal CLI, shell widgets):** all commands pass. Arbitrary unmarked local processes and direct file writes to `config.toml`/`routines.json`/`MEMORY.md` remain outside the IPC split by design.
4. **Non-systemd fallback limitation:** on hosts without a user systemd session, marking falls back to `WISP_TASK_ID` + `ppid` ancestry walk; a child that both clears its environment and reparents via double-fork/`setsid` can escape ancestry marking on those hosts (cgroup scope marking on Linux/systemd closes that escape).
5. **Local-only `connect` verb:** `wispd connect` refuses when invoked from a marked peer so OAuth granting stays human-only.

### `listen` replies (additive; #110)

When no turn owns the daemon (`busy` clear), the first press returns
`{ok:true, recording:true}` and starts capture; release runs the full
listen pipeline (`{ok:true, stopped:true}` on success). A second press
while already recording stops capture the same way. `phase: start` /
`phase: stop` mirror hold-to-talk; empty `phase` toggles.

While a turn is busy (`deciding`, `acting`, or parked on
`awaiting_choice`):

- Press (no recorder yet): `{ok:true, recording:true, mini:"choice"|"stop"}`
  — starts a short mini-capture. `mini:"choice"` when a prompt is pending;
  `"stop"` when only interruption applies.
- Press while mini-capture already open: `{ok:true, recording:true}`.
- Release after mini-capture: transcribe, then:
  - mapped choice → `{ok:true}` (same as `choice` applied);
  - unmapped choice → `{ok:true, heard:<text>, mapped:false}`;
  - spoken stop → `{ok:true, result:"interrupted", heard:<text>}`;
  - non-stop interjection with no prompt → `{ok:true, heard:<text>, mapped:false}`;
  - STT failure → `{ok:false, error:"stt_down"}`.
- Starting a full turn while the daemon is busy with a normal (non-mini)
  capture still returns `{ok:false, error:"busy"}`.

Trace (Python core, `trace.jsonl`): `choice_voice` (mapped or not),
`interrupt_voice`, `interjection_dropped`.

`config` keys are `section.key` (e.g. `agent.answer_model`); split is on
the **last** dot, so nested sections work — `brain.ollama.base_url` →
`[brain.ollama] base_url`. The daemon returns `{ok:false}` if any key
lacks a section. Shells may offer a settings page on top of this command.

The CLI also exposes verbs that run **locally** with no daemon
round-trip — they are not IPC commands and are absent from the table:
`connect` (OAuth via BrowserOS Strata), `inventory`, `recipes`,
`tele`, `fails`, `subscribe`'s client side (`wispd watch`).

## state.json (atomically rewritten, tmp+rename)

```json
{
  "status": "idle|listening|transcribing|deciding|awaiting_choice|acting|speaking|suggestion|done|error",
  "transcript": "string",
  "answer": "string",
  "result": "string",
  "choices": ["string"],
  "prompt_id": "string — id of the offered choices/confirm; \"\" when none",
  "confirm": "null, or {prompt_id, prompt, timeout_s, kind} while a confirm card waits (additive, W25; kind \"confirm\"|\"handoff\" added U3)",
  "points": [{"x": 0, "y": 0, "label": "string", "step": 1}],
  "steps": ["tool arg → result", "…"],
  "actions": [{"id": "a3", "kind": "tool", "label": "click",
               "status": "in_flight", "target": "640,360",
               "reason": "", "undo_ref": null, "delivery": "background",
               "at": "ISO-8601"}],
  "guide": {"x": 0, "y": 0, "label": "string", "mode": "guide|drive", "seq": 1},
  "focus": {"app": "string", "title": "string"},
  "note": "null, or {conv_id, path, raw, objects, plan, closed, rendered} — live paper surface (additive, gap-closure U1); when closed, plan is []",
  "goal": {"text": "string", "status": "open|done|failed"},
  "level": 0.0,
  "tasks": {"name": "running|done|failed|cancelled"},
  "error": "string — human-safe copy, never raw exception text",
  "error_code": "closed set, see below; \"\" when no error",
  "error_detail": "string — raw failure text, local only",
  "health": {"<endpoint>": {"ok": true, "since": "ISO-8601", "latency_ms": 12, "code": null}},
  "spend": {"today_usd": 0.0, "cap_usd": 8.0, "month_usd": 0.0, "monthly_cap_usd": 160.0, "blocked": false},
  "started_at": "ISO-8601",
  "turn_id": "string — turn that produced this write",
  "seq": 0,
  "updated_at": "ISO-8601",
  "contract_version": 2,
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
`key_missing` (a required API key did not resolve; `error` names it and
`wispd onboard`), `internal`. Shells render copy from the code and must treat unknown
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

Spend (additive; W14): `spend` is `{today_usd, cap_usd|null, month_usd,
monthly_cap_usd|null, blocked}` from the usage ledger (`wisp/ledger.py`),
republished after every recorded model call and on each health tick (so
the local-midnight rollover reaches shells without a call). `cap_usd` is
the daily cap, null when unset; `blocked` is true while a cap is reached
(or the ledger is unreadable): paid FALLBACK calls are refused, and the
primary too only when `[budget] gate_primary = "true"` (local models
always run). A `spend` health
row goes down with code `budget_exceeded` in the same state. `{}` on
older cores.

Prompt ids (additive; U9): every `awaiting_choice` publishes `choices`
together with a `prompt_id`, and clears both when the prompt resolves.
`choice` may carry `prompt_id` and/or `index` (1-based into `choices`;
`wispd choice [pick] [--prompt-id ID] [--index N]`). Replies:
`{ok:true}` when applied; `{ok:false, error:"stale_prompt"}` when no
prompt is pending or `prompt_id` is not the pending one (the pending
prompt keeps waiting); `{ok:false, error:"not_offered"}` for a `pick`
not in `choices`; `{ok:false, error:"bad_index"}` for an `index` out of
range. A `choice` without `prompt_id` is accepted only while a prompt is
pending (exactly one ever is) — this keeps current shells working — with
one exception: resolving the wildcard `always` pick REQUIRES the live
`prompt_id` (`{ok:false, error:"prompt_id_required"}` otherwise), so a
session-wide grant can only come from a client that saw the card. An
empty `pick` dismisses the prompt like a timeout. The core also refuses
an unoffered pick that reaches the turn by another path (trace
`choice_rejected`) and falls back to its safe auto-pick.

A `pick` beginning `suggestion:` needs no `prompt_id`: the daemon
resolves it before the broker (`suggestion:<act>` for the live card,
`suggestion:<act>:<key>` for a pending suggestions.jsonl row) and
replies `{ok:true, result}` — `result` is the daemon's own words for
the surface ack (`automating`, `OK (snoozed)`, `SKIP (suggestion
expired)`, `OK (never suggest that again)`).

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

Confirm card (additive; W25): while a confirm waits the core also
publishes `confirm = {prompt_id, prompt, timeout_s, kind}` (`null`
otherwise, cleared with `choices`). `confirm.prompt_id` equals
`prompt_id`; the card's replies use it, and a reply with any other id is
`stale_prompt`. No reply within `timeout_s` (`[agent] confirm_timeout`,
default 120, clamped 5 to 600) resolves as deny: the daemon owns the
deadline, the step result is `SKIPPED (<tool> confirmation timed out)`.
`kind` is `"confirm"` (absent on older cores), `"handoff"` (U3: a T3
step the user must do themselves — options read `… — done` / `cancel`,
the tool never runs), or `"question"` (U4: the act loop's `ask_user` —
the agent asked mid-task instead of guessing). A `confirm` card's
`choices` may carry a middle `"always"` pick (U3 session grant):
first option is still the allow pick, last is still the deny.
`detail` (additive, optional) is the body the card renders under the
ask — the thing being approved, e.g. the dictation text an
`auto_send` profile is about to send. Absent when the ask needs no
payload preview; shells should render it elided after `prompt`.

Question card (additive; U4): a `confirm` block with `kind:"question"`
means the running agent asked the user something (`prompt` is the
question text). When the model offered picks, `choices` carries them
and the usual `choice` pick/index rules apply; when it did not,
`choices` is empty and ANY non-empty `pick` resolves the card — a
typed `wispd choice "the answer"` or a free-form spoken reply resolves
it verbatim (voice answers are offered as picks when no options are
pending, and mapped onto options when they are). A free-form answer is
user-typed content — possibly a credential — so the stream and trace
record only `(answer)` / `answered (N chars)`, never the text; the
verbatim answer reaches the model only. No reply inside `timeout_s`
lapses the question (`cancelled`, reason `timeout`) and the model
receives a `NO_ANSWER` tool result rather than a stuck turn.

Action stream (additive; U2): `actions` is the unified lifecycle log —
one entry per dispatch, tool call, prompt, pick, interrupt, label and
suggestion, newest last, capped at the most recent 50. Entry shape:
`{id, kind, label, status, target, reason, undo_ref, at}` plus the
additive `delivery` (U5 — `background` | `pointer` | `guide`, `""` when
no input channel applies); prompt
entries also carry `options` (the offered picks) and `prompt_id`.
`id` is a per-boot `a<N>` counter — unique within one daemon run.
`status` is a closed set: `queued`, `in_flight`, `awaiting`, `done`,
`failed`, `cancelled` — shells must map unknown values to `done`.
`kind` is an open set (`route`, `tool`, `confirm`, `handoff`,
`clarify`, `choice`, `interrupt`, `label`, `suggestion`, `question`,
`act`, `dictation` today); render entries generically and ignore
unknown kinds' extras.
`target` is the
truncated arg (tool) or key (suggestion); `reason` is the terminal or
waiting context — a result string for tools, `denied` / `timeout` /
`interrupted` on `cancelled` prompts, `never` / `snoozed` / `expired` /
`accepted` on suggestions. `undo_ref` carries a short undo hint on
reversible (T1) tool entries (`"undo in the app"`, `"switch back"`),
else `null`.
`at` is the ISO-8601 entry-creation time. Entries mutate in place by
`id`: the whole capped list ships in each diff, so subscribers replace
it wholesale. The newest `awaiting` entry of kind `confirm` IS the
confirm card while its `prompt_id` equals the top-level `prompt_id`
(supersedes `confirm` in newer shells; `confirm` still publishes for
compatibility and supplies `timeout_s`). An `awaiting` entry whose
prompt already ended is stale — render it cancelled, don't keep the
card. The list is daemon-lifetime — it is not cleared per turn and not
persisted across restarts. `steps` still publishes the per-turn step
strings for older shells.

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

1. `{"type":"hello","ok":true,"contract_version":2,"topics":[...]}`.
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
   - `{"type":"event","name":"note_changed","data":{conv_id,path,raw,
     objects,plan,closed,rendered}}` (topic `events`; gap-closure U1):
     the conversation paper was rewritten. `objects` is the parsed `::`
     list; `plan` is the live `{now}`/`{pick}`/`{needs}` strip (`[]`
     when `closed`); `rendered` is the text form for CLI/panel. Additive
     — older clients ignore it.
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
landed; the ghost dims and returns); `delivery` string — `background`,
`pointer` or `guide`, the input channel the aim would take (`""` on
older cores; additive, U5). `{"x":null,"y":null}` clears.

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

Agent reaper (core behaviour behind the `tasks` field; U2): every 5 s the
daemon closes tasks whose process is gone, SIGTERMs tasks past
`[agent] task_timeout_s` (`timed_out`), and escalates to SIGKILL after 10 s.
Every spawn path wraps the child in an exit-code shim (`tasks/<id>.exit`)
and creates an output workspace at `tasks/<id>/out/`. At reap time:

- Exit code `0` transitions the task to `done`; non-zero exit or signal/kill
  transitions to `failed` (`exited` only for legacy unshimmed records with
  no exit-code evidence).
- Each path declared in `delivers[]` is verified on disk (regular file,
  non-empty, `mtime` within the task's run window) and recorded as
  `delivered` or `missing` in `deliverables[]`; `delivered: bool` is true
  only when the task exited `0` and every declared deliverable passed.
- Paths outside `out_dir`, symlinks escaping `out_dir`, and executable /
  `.desktop` files are flagged (`flagged: true`, `openable: false`) and
  never offered as notification `open` actions.
- `task_finished` push events and `_agent_done` notifications report facts
  (`"claims <file> — not on disk"` when `delivered: false`) and include
  `refused_count` when mutating IPC commands were blocked under U1.
- The reaper never signals a pid whose start-time differs from the one
  recorded at spawn (PID reuse). Each running to not-running transition
  publishes the new `tasks` and one `task_finished` event.

## Data files (shared by both cores, never versioned differently)

- `decisions.jsonl` — one JSON per turn: `ts`, `transcript`, `answers`,
  `result`, `timing_ms{record,stt,jev,act}`, `corrected`.
- `session.jsonl` — turns for follow-up context.
- `corrections.jsonl` — user picks on ambiguous turns.
- `tasks.jsonl` — agent registry; `tasks/<id>.log` per-agent output.
- `labels.jsonl` — human labels (`correct`/`incorrect`) keyed to the
  decision ts; joined to trajectories via the decision's transcript.
- `trajectories.jsonl` — episodic act-loop memory (task, app, steps,
  outcome); feeds `context_for()`.
- goal state — in-memory only (`wisp/goals.py`, `goal_ttl_s` TTL, lost
  on restart); not a file.
- `inventory.json` — scanned local terrain (apps, cli_tools, mcp
  servers, omarchy plugins/binds, dayflow, skills); 24h TTL.
- `MEMORY.md`, `USER.md` — curated bounded memory (frozen snapshot).
- `skills/*/SKILL.md` — self-authored skills (progressive disclosure).
- `trace.jsonl` — full-fidelity dev trace (`[debug] trace`, default on):
  one event per line `{ts, turn, step, kind, ms, data}` covering
  listen_start/record/transcribe/decision/dispatch/tool_call/
  tool_result/brain_call/answer/speak/points/ipc/error,
  choice_voice/interrupt_voice/interjection_dropped, plus `kind=span`
  events (`step` = press, release, stt, context, route, first_token,
  first_step, tts_start, done, and sub-spans screenshot/hyprctl/memory/
  goal; `ms` = duration, `data.offset_ms` from the keypress,
  `data.t0_source` client|daemon). `wispd trace show --tail N --turn
  <id> --kind <k>` on both cores; Python core adds `trace show --latency
  --since 24h` (p50/p90 per budget path). Rotates at 10 MB;
  never logs secrets.
- `recall.db` — sqlite-vec/FTS5 long-term recall.

## Versioning

Contract version = top of this file. Shells read
`state.contract_version` when present; absent ⇒ v1. Additive fields are
allowed without a bump; changed/removed semantics bump the version.
