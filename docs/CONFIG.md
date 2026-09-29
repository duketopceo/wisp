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
| `seconds` | `5` | mic capture length per press |
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

## [brain] — pluggable answer brains

| key | default | meaning |
|-----|---------|---------|
| `router` | `"jev"` | `jev` (decision API) / `chat` (straight to answer brain) / `off` (clarify) |
| `default` | `"openrouter:<answer_model>"` | `name:model` selecting a `[brain.<name>]` provider |
| `agent_runtime` | `"opencode"` | spawned-agent runtime: `opencode`/`codex`/`claude`/`devin` |

### [brain.<name>] provider tables

| key | meaning |
|-----|---------|
| `type` | `openrouter`, `openai_compat`, or `ollama` |
| `base_url` | endpoint |
| `key_env` | env var name; may be `omaseal://service/account` |
| `vision` / `tools` | capability flags — gates screenshots and tool schemas |

Built-ins: `openrouter`, `ollama`, `lmstudio`, `mlx`.

## [agents]

| key | meaning |
|-----|---------|
| `model` | model passed to the spawned runtime |
| `recall` | number of recall notes injected into context |

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
