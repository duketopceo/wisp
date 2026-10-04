# Wisp config reference — `~/.config/wisp/config.toml`

Flat TOML, edited live via `wispd config set <key> <value>` (no
restart) or the Settings tab in the GUI. Every key has a default.

## [hotkey]

| key | default | meaning |
|-----|---------|---------|
| `mod` | `"SUPER"` | modifier for push-to-talk |
| `key` | `"D"` | key for push-to-talk (SUPER+D) |

## [keys] — keyboard submap (Linux/Hyprland)

| key | default | meaning |
|-----|---------|---------|
| `submap` | `"true"` | register the Wisp keyboard submap while a turn acts or waits |

While a turn is `acting` or `awaiting_choice`, `wispd` registers and enters
a Hyprland submap named `wisp` and leaves it on every other status:

| state | keys |
|-------|------|
| `acting`, or waiting with no options | `Esc` stops the turn |
| `awaiting_choice`, n options | `Esc` stops, `Enter` picks option 1 (the "yes" of a confirm), `1`..`min(n,9)` pick that option |

The keys are modifier-free but exist only inside the submap, so they never
shadow a global bind or typing outside those states. Pointer backends do not
take focus, so `Esc` stays reachable while cua acts. Design notes:

- Registered at runtime through the bind registry in `wisp/hypr.py`
  (`hyprctl eval` / the request socket), never by editing `bindings.lua` or
  anything under `/usr/share/omarchy`. Nothing is written to `~/.config/hypr`.
- Every bind's description starts with `wisp:`. If a submap named `wisp`
  already holds binds without that prefix, Wisp reports the conflict in
  `wispd.log` and runs voice/mouse only; it never overwrites them.
- The daemon leaves the submap on idle, on shutdown, and at startup (clears
  what a crash left). The `Esc` bind itself also leaves the submap, so a dead
  daemon cannot strand the keyboard in it.
- `Esc` runs `wisp/fastkey.py --sock <wispd.sock> interrupt`: the same IPC
  `interrupt` command as `wispd interrupt`, without importing the daemon
  (cold `wispd interrupt` is about 120 ms; `fastkey.py` about 20 ms).
- The agent's own `key` tool steps run outside the submap so a scripted
  `Esc` cannot stop its own turn.

## [audio]

| key | default | meaning |
|-----|---------|---------|
| `seconds` | `60` | max capture per toggle press — SUPER+D starts, SUPER+D again stops; this is only the safety ceiling |
| `whisper_model` | `"ggml-small.en.bin"` | ggml model file name |

## [stt] — speech-to-text

| key | default | meaning |
|-----|---------|---------|
| `provider` | `"local"` | `local` (whisper.cpp) or `openai` (compatible audio API) |
| `base_url` | groq URL | endpoint for `openai` provider |
| `model` | `whisper-large-v3-turbo` | STT model id |
| `key_env` | `GROQ_API_KEY` | env var / `.env` key name holding the key |
| `prompt` | `""` | vocab priming (names, jargon) |

## [jev] — routing deadline and shadow decider

| key | default | meaning |
|-----|---------|---------|
| `deadline_ms` | `400` | Jev gets this long to route; past it, on an error, or on a malformed reply the heuristic router decides and the turn goes on |
| `shadow` | `""` | second decider logged to `shadow.jsonl` (`pplx`); never changes what Wisp does |

Every routed turn appends Jev vs heuristic vs final route to `route_ab.jsonl`; read it with `wispd eval route`.

## [agent] — routing + action policy

| key | default | meaning |
|-----|---------|---------|
| `model` | `typesafe/jev-1.13` | Jev decision model |
| `answer_model` | `meta-llama/llama-4-maverick` | model that writes answers (used when `brain.default` unset) |
| `session_turns` | `8` | turns of chat history kept in context |
| `screenshots` | `true` | allow screen capture for context |
| `confirm_timeout` | `120` | seconds a confirm card waits before it resolves as deny (clamped 5 to 600) |
| `risk_threshold` | `1.5` | action risk score allowed before confirmation; lower = asks more |
| `confidence_instant` | `0.95` | auto-accept cutoff |
| `confidence_ambiguous` | `0.8` | ask-choice cutoff |
| `allow_shell` | `false` | allow free-form shell tool |
| `denylist` | built-in | commands never run |
| `goal_ttl_s` | `600` | seconds an open goal accepts follow-up utterances |
| `browseros_first` | `true` | `launch("browser")` prefers BrowserOS when its MCP server (:9200) is live |
| `password_manager` | `""` | `1password` lets the agent click quick-unlock/passkey prompts (never types a master password); `off`/empty disables |

## [brain] — pluggable answer brains

| key | default | meaning |
|-----|---------|---------|
| `router` | `"jev"` | `jev` (decision API) / `chat` (straight to answer brain) / `off` (clarify) |
| `default` | `"openrouter:<answer_model>"` | `name:model` selecting a `[brain.<name>]` provider |
| `fallback` | `""` | comma-separated `name:model` chain tried after `default` (e.g. `"mlx:ornith, ollama:ornith"`) |
| `allow_paid` | `false` | allow paid fallback entries (OpenRouter, or `paid = "true"` on the section); the U10 cap hook (`brain.budget_ok`, see `[budget]`) also applies; at a cap fallbacks are skipped, the primary runs unless `[budget] gate_primary` |
| `first_token_s` | `3` | a streaming entry must emit a token within this many seconds or the chain moves on; all entries failing ends the turn `brain_down` |
| `agent_runtime` | `"opencode"` | spawned-agent runtime: `opencode`/`codex`/`claude`/`devin` |

Retries: one fast retry on connection refused/reset only; timeouts are
never retried. Once answer text has streamed, a failure ends the turn
instead of falling back.

### [brain.<name>] provider tables

| key | meaning |
|-----|---------|
| `type` | `openrouter`, `openai_compat`, or `ollama` |
| `base_url` | endpoint |
| `key_env` | env var name; may be `omaseal://service/account` |
| `paid` | `true`/`false`; defaults to true for `openrouter.ai` URLs. Paid fallback entries need `[brain] allow_paid` |
| `vision` / `tools` | capability flags — gates screenshots and tool schemas |

Built-ins: `openrouter`, `ollama`, `lmstudio`, `mlx`.

## [budget] — spend caps (W14, reconciled with 7ec4236)

| key | default | meaning |
|-----|---------|---------|
| `daily_usd` | unset = `8.00` | daily cap on paid spend; blank = no cap; `0` blocks all gated paid calls. If unset, the deprecated `[brain] daily_cap_usd` is honoured as an alias (a one-time deprecation hint is logged); `[budget] daily_usd` wins when both are set |
| `monthly_usd` | `"160.00"` | same, per calendar month (20 days x the daily default, so it is never stricter than the daily cap) |
| `gate_primary` | `"false"` | `false`: at/over a cap only paid FALLBACK entries are skipped and the primary still runs (so the agent lives). `true`: every paid entry, primary included, is refused at the cap |

Policy table:

| situation | paid fallback | paid primary |
|-----------|---------------|--------------|
| under every cap | runs | runs |
| at/over a cap | skipped | runs (`gate_primary = "true"`: skipped) |
| ledger unreadable | skipped | runs (`gate_primary = "true"`: skipped) |

Local models are recorded (tokens, cost 0) but never gated. Rows live in
`~/.local/share/wisp/usage.jsonl`, the single ledger (`brain` makes one
`ledger.note()` per call and requests OpenRouter `usage.include`). Cost is
the OpenRouter-reported `usage.cost` when present, else a built-in price
table; an unlisted paid model is priced high so it cannot look free.
Rows from the old `~/.local/share/wisp/spend.jsonl` writer
(`{ts, model, cost, prompt_tokens, completion_tokens}`) are still read
and counted as paid openrouter rows (source `spend.jsonl`); nothing
writes that file any more. The clicklab lab records per-task `cost_usd`
and tokens from the same ledger and aborts at the daily cap. Inspect
with `wispd spend`.

## [health] — endpoint probes (U7)

Local endpoints only (Jev, every brain-chain entry, optional extras, a
loopback `[stt]` server); remote ones are never probed. Any HTTP answer
counts as up. Results appear as `health` in state.json and a
`health_changed` event fires on each transition.

| key | default | meaning |
|-----|---------|---------|
| `enabled` | `true` | run the daemon's probe loop |
| `interval_s` | `30` | idle probe period |
| `press_stale_s` | `10` | on hotkey press, re-probe anything older than this |
| `timeout_ms` | `500` | per-probe timeout |
| `ollama` / `uitars` | unset | extra endpoint base URLs to watch |

`[health.units]` maps an endpoint name (`jev`, `brain_<provider>`,
`uitars`, `ollama`, `stt`) to a comma list of user systemd units.
`wispd models start` prints the `systemctl --user start ...` command for
the units behind down endpoints; `--run` executes it. `wispd doctor`
and `wispd models` show current health.

## [agents]

| key | meaning |
|-----|---------|
| `model` | model passed to the spawned runtime |
| `recall` | number of recall notes injected into context |
| `act_max_steps` | `12` | tool-call bound for the act loop |

## [mcp]

| key | default | meaning |
|-----|---------|---------|
| `enabled` | `true` | expose the `mcp_call` tool; servers are discovered by `wispd inventory` and `~/.config/wisp/mcp.json` (OAuth'd via `wispd connect`) |

## [recall] — semantic memory

| key | default | meaning |
|-----|---------|---------|
| `provider` | `"none"` | `none` (FTS5 keyword search) or `openai` (embeddings + RRF fusion) |
| `base_url` / `model` / `key_env` | openrouter | embedding endpoint + model + key env |

## [voice] — text-to-speech

| key | meaning |
|-----|---------|
| `enabled` | speak answers aloud |
| `cmd` | override TTS command; `{text}` placeholder or appended arg. Empty = platform default (espeak/say/SAPI) |

## [notify] — desktop toasts

| key | meaning |
|-----|---------|
| `enabled` | `false` turns every toast off |
| `quiet` | silent window `"22:00-07:00"` (may cross midnight); empty = never |
| `dedupe_secs` | drop an identical toast inside this window (default 60) |
| `timeout_ms` | toast expiry (default 5000) |
| `actions` | `false` never sends buttons (they are only sent when the server advertises `actions`) |

One toast per turn is updated in place (replace-id). Cancelled turns and
stale turns never toast; spoken answers do not also toast when `[voice]
enabled` is true. The server is detected at runtime (GetServerInformation
and GetCapabilities via `gdbus`); without one, `notify-send` is used (no
buttons). Not yet implemented: server do-not-disturb and fullscreen
suppression (needs W7).

## [cua] — safety layer for injected input (W9)

Applies when `[pointer] mode = "drive"` (click/move/scroll) and always to
typing and key presses. Policy order: cancel, kill switch, deny, allow,
rate limit, dry run, dispatch. Refusals read `REFUSED (...)`.

| key | default | meaning |
|-----|---------|---------|
| `timeout_ms` | `800` | per-call driver timeout; a timed-out click is never retried on another backend |
| `safety` | `true` | master switch for this layer (kill switch and audit go with it) |
| `allow` | `""` | comma list of window-class substrings; when set, any other app is refused (an unknown window fails closed) |
| `deny` | `""` | extra substrings to refuse; added to the built-in list (password managers, polkit/pinentry, keyrings, and terminals whose title shows `sudo`). Deny beats allow |
| `max_clicks_per_min` | `30` | rolling 60 s cap on click/scroll/type/key calls per window class (moves are not counted) |
| `max_per_turn` | `12` | cap on the same calls in one act run |
| `dry_run` | `false` | log what would happen and return `DRYRUN ...`; no driver, ydotool or hyprctl call. Deny, kill and rate checks still apply |
| `kill_switch` | `false` | refuse everything. The runtime file `$XDG_RUNTIME_DIR/wisp/cua.kill` does the same without a config edit (`cua_safety.kill()` / `resume()`) |
| `confirm` | `tier` | `tier` keeps the tool tiers; `always` makes click/move/scroll/type/key ask once per (tool, focused app) per session |
| `audit` | `true` | append one JSON line per call to `$XDG_STATE_HOME/wisp/cua.jsonl` |

Audit line: `ts, turn, tool, app, decision (allow|deny|dry_run|cancelled),
dry_run, result (first word only), ms`, plus `x`/`y` for coordinate
targets, `key` for named keys and chords, and `len` + `sha` (12 hex of a
per-process salted hash) for typed text. Typed text, target names,
screenshots and result text are never written.

## Latency budgets (W2)

Data, not config: `wisp/budgets.json` (p50 ceiling per path; the verdict
also needs p90 <= 1.5x). Not revised yet from live traces.

| id | path | p50 ms |
|---|---|---|
| P1 / P2 | press / release feedback | 25 / 25 |
| P3 | transcript (key up -> text); warm whisper floor 1300 | 600 |
| P4 | route (context + route) | 200 |
| P5 | first answer token | 500 |
| P6 | TTS start | 150 |
| P7 | act first step (UI-TARS grounding) | 1200 |
| P8 | agent ack | 300 |
| P9 | stop (request -> idle) | 150 |
| P10 | offline error | 1000 |
| E2E | answer, key up -> first token | 1400 |

Resources: wispd under 250 MB RSS and 3% idle CPU; cua-driver
`MemoryMax=512M`; Companion under 5% CPU at 120 Hz idle.
`wispd latency` reports real turns; `--budgets` prints this table,
`--baseline` the committed fake-backed baseline
(`docs/baselines/latency-harness.json`), `--harness` re-measures it.

## [debug]

| key | meaning |
|-----|---------|
| `trace` | write the full dev trace (`trace.jsonl` — every stage, tool call, timing; never logs keys) |

## Environment overrides

| var | effect |
|-----|--------|
| `WISP_OS` | force the OS adapter (`linux`/`macos`/`windows`) |
| `WISP_DESKTOP` | force the Linux desktop table (`hyprland`/`gnome`/`kde`/`x11`) |
| `XDG_*` | standard dir resolution for config/data/runtime |

## Command line (`wispd <group> <verb>`)

Every command takes `--help` (one-line summary plus examples) and the
global flags `--json`, `--quiet` and `--no-color`, before or after the verb.
Output is plain when stdout is not a tty or `NO_COLOR` is set. Tables use
the Ember tokens from `wisp/theme.py`.

```
daemon run|install|harness     status  stop  interrupt  trigger [start|stop]
watch [topic ...]              choice [pick] [--prompt-id ID] [--index N]
doctor  health [start [--run]]  latency [--since 24h]  spend  binds  onboard
cua status|test|log|enable|disable      notify test
task list|status|cancel|run    memory edit|write    suggest list
label report|set               context
train stats|history|bank|rebuild        review list|run|approve|reject
learn weekly|fails             skills list|import  recipes draft|approve
trace show|digest              eval route
config show|set                theme show|set|check|css
connect list|add               sync  inventory  tui  completion bash|zsh|fish
```

`cua enable` and `cua disable` only edit `[pointer] backend`; wisp never
starts or stops the cua-driver service. `cua test` only checks the binary
and connects to the driver socket (nothing is sent).

### Exit codes

| code | meaning |
|------|---------|
| 0 | ok |
| 1 | failure (the command ran and did not succeed) |
| 2 | usage error |
| 3 | daemon not running |
| 4 | unhealthy dependency (model endpoint down, cua driver unreachable, doctor MISS rows, setup incomplete) |

Errors go to stderr as `E_CODE: Sentence.` plus a `Try: ...` line. The code
set is `E_USAGE`, `E_FAILED`, `E_DAEMON_DOWN`, `E_UNHEALTHY`, `E_CUA_DOWN`,
`E_NOT_READY`, `E_BAD_CONFIG`, `E_NO_NOTIFIER`, plus one `E_<CODE>` per typed
wisp error (`E_JEV_DOWN`, `E_BRAIN_DOWN`, `E_STALE_PROMPT`, ...).

### JSON

`--json` prints one object on stdout, for success and failure alike:

```
{"ok": true,  "command": "health", "data": {...}}
{"ok": false, "command": "health", "error": {"code": "E_UNHEALTHY",
  "message": "1 of 1 local endpoints are down.", "try": "wispd health start"},
  "data": {...}}
```

`data` keys per command are declared in the registry (`wisp/cli/*.py`, the
`schema` argument) and checked by `tests/test_cli.py`. `watch` is always
NDJSON (one event per line) and `daemon run` / `tui` have no envelope.
`doctor`: `{healthy, sections:[{name, rows:[{name, value, ok}]}]}`;
`health`: `{healthy, endpoints:[{name, ok, latency_ms, code}]}`;
`latency`: `{since_h, turns, rows:[{id, label, n, p50, p90, budget_p50,
verdict}]}`; `spend`: `{today_usd, calls_today, cap_usd, paid_allowed,
source}`; `binds`: `{hotkey:{mod,key,chord}, hyprland, binds}`;
`cua status`: `{configured, backend, mode, binary, socket, live}`.

### Old names

These keep working for one release and map to the new commands:
`install`, `harness`, `subscribe`, `tasks`, `task_status`, `task_cancel`,
`agent <task>`, `memory-write`, `suggestions`, `fails`, `tele`, `models
[start [--run]]`, `label correct|incorrect [note]`, `learn`, `trace
--tail/--latency`, `train|review|skills|recipes` with no verb, `config`
with no verb, `theme [name|--check|--css]`, `connect [--list|service]`,
`daemon` with no verb. Output of the old forms is unchanged except that
errors use the new `E_CODE` format and daemon-unreachable exits 3 (was 1);
`doctor` now exits 4 (was 1) when a check fails.

### Completion

```
wispd completion bash > ~/.local/share/bash-completion/completions/wispd
wispd completion zsh  > "${fpath[1]}/_wispd"
wispd completion fish > ~/.config/fish/completions/wispd.fish
```
