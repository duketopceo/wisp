# Wisp config reference — `~/.config/wisp/config.toml`

Flat TOML, edited live via `wispd config set <key> <value>` (no
restart) or the Settings tab in the GUI. Every key has a default.

## [hotkey]

| key | default | meaning |
|-----|---------|---------|
| `mod` | `"SUPER"` | modifier for push-to-talk |
| `key` | `"D"` | key for push-to-talk (SUPER+D) |

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

## [agent] — routing + action policy

| key | default | meaning |
|-----|---------|---------|
| `model` | `typesafe/jev-1.13` | Jev decision model |
| `answer_model` | `meta-llama/llama-4-maverick` | model that writes answers (used when `brain.default` unset) |
| `session_turns` | `8` | turns of chat history kept in context |
| `screenshots` | `true` | allow screen capture for context |
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
| `allow_paid` | `false` | allow paid fallback entries (OpenRouter, or `paid = "true"` on the section); the U10 daily cap hook (`brain.budget_ok`) also applies |
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
