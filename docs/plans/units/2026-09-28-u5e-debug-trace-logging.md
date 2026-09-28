---
plan: dim-u5e-debug-trace
created: 2026-09-28
status: ready
origin: user request 2026-09-28 — "log everything, action, thought, tool call"
issue: https://github.com/duketopceo/dim-agent/issues/23
wave: 3 (dogfooding enabler — lands before U6)
---

# U5e — full-fidelity dev trace

## Why

Dim is about to be used daily (dogfood). Every stage of a turn — record,
STT, Jev decision, route dispatch, tool call, brain call, TTS — can
misfire, and today the only evidence is the final `result` string and
`decisions.jsonl` (Jev I/O only). To let us *and Jev* parse real
misfires into repros and fixtures, we need a single ordered event
stream per turn.

## Scope

One append-only JSONL event stream, both cores, identical schema.

- File: `~/.local/state/dim-agent/trace.jsonl` (data_dir — beside
  recall.db, decisions.jsonl). Rotated at ~10 MB to `trace.1.jsonl`.
- Event: `{"ts": iso, "turn": "<id>", "step": "<name>",
  "kind": "<category>", "ms": <int|null>, "data": {...}}`
- `turn` = short id minted per `listen` cycle; IPC/control commands get
  `turn: "sys"` so the whole stream is filterable by either.
- Steps (at minimum):
  `listen_start`, `record` (wav path, bytes, ms), `transcribe`
  (provider, model, ms, text), `decision` (route, latency, payload —
  this is the "thought"), `dispatch` (route→action mapping),
  `tool_call` (name, args, ms), `tool_result` (result string, ok),
  `brain_call` (endpoint, model, ms, request+response truncated 8 KB),
  `answer`, `speak` (cmd, ms), `points`, `state` (transitions),
  `ipc` (command name + reply, `turn:"sys"`), `error` (stage, message).
- Config: `[debug] trace = true` default ON during development;
  `trace_max_mb = 10`; `trace_data_bytes = 8192` truncation.
- **Never logged**: Authorization headers, resolved key values
  (`load_env_key` output), `.env` contents. Only key *names*.
- `dimd trace` subcommand: `--tail N` (default 50), `--turn <id>`,
  `--kind <k>` — pretty-prints events; exits 0 on empty.
- Both cores emit identical schema; a parity fixture asserts field sets.

## Steps

1. `dim/trace.py`: `emit(turn, step, kind, data=None, ms=None)`,
   `new_turn()`, `enabled(cfg)` cached, rotation check on open.
2. `rs/dimd/src/trace.rs`: same API + `OnceLock` enabled flag.
3. Instrument `pipeline.rs`/`.py` at each stage boundary listed above;
   `main.rs`/`dimd` emit `ipc` per command (outside turn → "sys").
4. `dimd trace`/`dimd-rs trace` subcommand with filters.
5. GUI: none here — Logs tab in #18 reads the file.

## Tests

- Emit → parse roundtrip; schema field set identical Python/Rust
  (parity test compares emitted event keys).
- `trace=false` → file untouched.
- Rotation at max_mb; truncation at data_bytes.
- A full mocked `listen` turn produces the ordered step chain
  listen_start → record → transcribe → decision → dispatch → …
- `dimd trace --tail` output parses as JSONL.

## Risks

- Volume: TTS/brain payloads are the big ones — truncation covers it.
- Key leakage: keys never enter `data` — instrument at call sites
  *after* header construction, logging only endpoint+model+status.
- Perf: JSONL append is ~µs; rotation stat per event is fine.

## Done when

Running `dimd trace --turn <id>` after a live listen prints the full
ordered stage list with ms timings, and `dimd trace --tail` works on
both daemons.
