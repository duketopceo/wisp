# Wisp config reference — `~/.config/wisp/config.toml`

Flat TOML, edited live via `wispd config set <key> <value>` (no
restart) or the Settings tab in the GUI. Every key has a default.

## [hotkey]

| key | default | meaning |
|-----|---------|---------|
| `mod` | `"SUPER"` | modifier for push-to-talk |
| `key` | `"D"` | key for push-to-talk (SUPER+D) |

`wispd install` also writes a second bind, `mod + ALT + key` (Super+Alt+D
by default; `mod + CTRL + key` when `mod` already holds ALT, since Omarchy owns
Super+Shift+D): it rates the last finished answer wrong and opens the panel's
Now tab with a one-line note.

## [keys] — keyboard submap (Linux/Hyprland)

| key | default | meaning |
|-----|---------|---------|
| `submap` | `"true"` | register the Wisp keyboard submap while a turn acts or waits |

### Voice answers during a parked or running turn (#110)

While `ctl["busy"]` is set (a turn is deciding, acting, or parked on
`awaiting_choice`), a normal `listen` does **not** start a new turn. Hold
`Super+D` (or send `listen` with `phase: start`, then release with
`phase: stop` / a second toggle):

- With a pending prompt: the daemon records a **mini-capture** tagged
  `mini: choice`, transcribes it, and maps speech to an option via
  `wisp/voicepick.py` (yes/no, ordinals, label overlap). Mapped picks
  call the same `choice` broker as a chip click; unmapped speech leaves
  the card up and TTS says "didn't catch that".
- With no pending prompt but a turn in flight: `mini: stop` — spoken
  stop / wait / never mind / cancel sets `interrupt` like `wispd interrupt`.

The running turn keeps its status surface; mini-capture never calls
`begin_turn`. See `docs/IPC_CONTRACT.md` for reply shapes and trace events.

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
| `seconds` | `60` | max capture per press — hold `Super+D` (release to send) or `wispd trigger start` then `stop`; bare `wispd trigger` toggles; this is only the safety ceiling |
| `whisper_model` | `"ggml-small.en.bin"` | ggml model file name |
| `device` | empty | the mic to record from, a `pw-record --target` name or an `arecord -D` device. Empty records from the system default. When the named mic is gone (the recorder exits inside about 0.35 s), the turn records from the default mic instead and one toast says so (a call does not hold that toast). Under PipeWire the named mic is recorded with `node.dont-fallback`, so a missing one fails instead of silently using the default. It tries once; if the default fails too, the turn ends with the usual "recording produced no audio" error, never a hang |

## [browser] — watchable browser lane

| key | default | meaning |
|-----|---------|---------|
| `lane` | `"off"` | `"extension"` lets the `browser` tool work in your own Chromium through the paired Wisp extension, in a tab group beside your tabs. Off, the tool is not offered to the model and a call does nothing |
| `port` | `47315` | loopback port the extension polls (1024 to 65535) |

Setup, the rules it keeps and Stop: `docs/BROWSER_LANE.md`.

## [stt] — speech-to-text

| key | default | meaning |
|-----|---------|---------|
| `provider` | `"openai"` | `openai` (compatible audio API, hosted Groq by default) or `local` (whisper.cpp) |
| `base_url` | groq URL | endpoint for `openai` provider |
| `model` | `whisper-large-v3-turbo` | STT model id |
| `key_env` | `GROQ_API_KEY` | env var / `.env` key name holding the key |
| `prompt` | `""` | vocab priming (names, jargon) |
| `language` | `auto` | the language you speak. `auto`: the hosted model detects it and the answer and the spoken voice follow it. Or pin one (`es`, `de`, `fr`, `ja`, `pt-BR`, ...). English changes nothing. The local `small.en` model is English only: with `provider = "local"` and a `.en` model a non-English language is refused out loud, not guessed. Dictation is typed in the language you spoke and never translated |
| `streaming` | `true` | with the `openai` provider, send finished chunks of a long utterance while the key is held, so only the last part is left to transcribe on release; any failure falls back to one request for the whole recording |

## [web] — role web apps

| key | default | meaning |
|-----|---------|---------|
| `mail` | `"https://mail.google.com"` | URL `launch mail` opens when the default mail handler is a browser; a native client (Thunderbird, Geary) is launched as usual |
| `calendar` | `"https://calendar.google.com"` | same, for the `calendar` role |

An absent or empty key uses the default, so a config file without a `[web]` section works unchanged. Values cannot contain `#`: the config parser treats it as a comment.

## [jev] — routing deadline

| key | default | meaning |
|-----|---------|---------|
| `deadline_ms` | `400` | Jev gets this long to route; past it, on an error, or on a malformed reply the heuristic router decides and the turn goes on |


## [agent] — routing + action policy

| key | default | meaning |
|-----|---------|---------|
| `model` | `typesafe/jev-1.13` | Jev decision model |
| `answer_model` | `meta-llama/llama-4-maverick` | model that writes answers (used when `brain.default` unset) |
| `session_turns` | `8` | turns of chat history kept in context |
| `screenshots` | `true` | allow screen capture for context |
| `confirm_timeout` | `120` | seconds a confirm card waits before it resolves as deny (clamped 5 to 600) |
| `risk_threshold` | `9` | numeric risk gate; Jev scores run about 0 to 2, so the default only blocks extreme risk. Real protection is the denylist, `allow_shell` and the confirm tier |
| `confidence_instant` | `0.95` | auto-accept cutoff |
| `confidence_ambiguous` | `0.8` | ask-choice cutoff |
| `allow_shell` | `false` | allow free-form shell tool (commands also pass a built-in denylist that is not configurable) |
| `autonomy` | `"autonomous"` | act-loop confirm policy (wisp/policy.py): `autonomous` runs reversible (T1) steps free and batch-confirms irreversible (T2) ones; `guided` confirms T1 steps too; `always_ask` confirms every tool call. Human-only (T3) steps hand off under every mode |
| `max_concurrent` | `3` | most background agent tasks at once |
| `task_timeout_s` | `1800` | lifetime of one background task |
| `goal_ttl_s` | `600` | seconds an open goal accepts follow-up utterances |
| `browseros_first` | `true` | `launch("browser")` prefers BrowserOS when its MCP server (:9200) is live |
| `password_manager` | `""` | `1password` lets the agent click quick-unlock/passkey prompts (never types a master password); `off`/empty disables |

## [brain] — pluggable answer brains

| key | default | meaning |
|-----|---------|---------|
| `router` | `"act"` | `act` (default: every turn straight to the agent loop — the loop's brain decides answer-vs-work; no decision hop) / `jev` (decision API) / `chat` (straight to answer brain) / `off` (clarify) |
| `fast_path` | `"true"` | Under `router = act`, a bare launch of a catalogued app ("open firefox") or a plain question ("what does this error mean") skips the act loop and goes straight to the launch or answer handler, with no model hop. Compound requests, unknown apps and questions that carry an action verb still go to act. `"false"` sends every turn to act |
| `default` | `"openrouter:<answer_model>"` | `name:model` selecting a `[brain.<name>]` provider |
| `fallback` | `""` | comma-separated `name:model` chain tried after `default` (e.g. `"mlx:ornith, ollama:ornith"`) |
| `allow_paid` | `false` | allow paid fallback entries (OpenRouter, or `paid = "true"` on the section); the U10 cap hook (`brain.budget_ok`, see `[budget]`) also applies; at a cap fallbacks are skipped, the primary runs unless `[budget] gate_primary` |
| `first_token_s` | `3` | a streaming entry must emit a token within this many seconds or the chain moves on; all entries failing ends the turn `brain_down` |
| `agent_runtime` | `"auto"` | spawned-agent runtime: `auto`/`opencode`/`codex`/`claude`/`devin`. `auto` uses the pinned OpenCode (installed by `wispd install --agents`) when it is ready, else the first of `codex`, `claude`, `devin` found on `PATH`. Only `opencode` runs as a live ACP session (progress, questions, follow-ups, cancel); the others are one-shot CLI runs |

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
writes that file any more. Inspect
with `wispd spend`.

## [local] — local model servers (opt-in)

| key | default | meaning |
|-----|---------|---------|
| `enabled` | `false` | allow local model servers (llama.cpp Ornith, UI-TARS, jev-shim, ollama). Off: `wispd onboard` skips the local ladder, `[ground] providers` drops `uitars`, and `wispd install --units` skips the llama/jev-shim units. OpenRouter stays the brain either way |

## [trial] — capped first-run brain (off, not live)

| key | default | meaning |
|-----|---------|---------|
| `enabled` | `false` | allow `trial:<model>` as a brain. Needs `url` too; never on in a shipped build |
| `url` | `""` | the trial proxy's https address (a loopback address may use http). The install sends a random per-install token, text only, never a screenshot or a provider key. See [COSTS.md](COSTS.md) |

## [clibrain] — answer through your own coding-agent CLI (off)

| key | default | meaning |
|-----|---------|---------|
| `enabled` | `false` | allow `cli:claude` or `cli:codex` as a brain. Wisp runs the CLI once per turn with the text of the turn on stdin and never reads its credentials. See [COSTS.md](COSTS.md) |
## [handsfree] — double-tap to keep listening (opt-in)

| key | default | meaning |
|-----|---------|---------|
| `enabled` | `false` | tap the talk key twice and the second tap keeps listening after release; the next tap sends. Off: hold-to-talk is unchanged. See [PRIVACY.md](PRIVACY.md) |

## [wakeword] — local wake word (opt-in)

| key | default | meaning |
|-----|---------|---------|
| `enabled` | `false` | listen for the phrase with the local whisper.cpp model; nothing is sent and no screenshot is taken until it is heard. Refused over open speakers (headphones or `wispd install --echo-cancel`). The bar shows an open-mic mark while it runs |
| `phrase` | `"hey wisp"` | what to listen for |

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
| `act_max_steps` | tool-call bound for the act loop (default 12) |
| `act_max_errors` | consecutive tool errors before the act loop gives up (0 to 20) (default 2) |
| `act_max_parse_misses` | unparseable model steps tolerated before the act loop stops (0 to 10) (default 1) |
| `act_max_seconds` | wall-clock bound for one act run; the abort publishes a `failed` action entry with reason `budget` (0 disables, default 600) |
| `act_max_usd` | per-run cap on model spend added during the run (0 disables, default 0) |
| `act_preview_min` | steps that change something in one model reply before Wisp shows the whole plan as one card and runs it on yes (0 disables, default 3). While a plan runs, each step first checks the focused window is still the one the plan was made for and stops with a spoken reason if not |
| `routine_wait_s` | seconds a scheduled routine waits for a network connection (for example right after the machine wakes) before giving up; a run missed while offline never counts toward the three-failure pause (0 skips the wait, default 120) |
| `writer_queue_max` | background writer queue for trajectory and recall writes; oldest dropped and counted when full (default 256) |
| `acp_models` | comma list of OpenRouter models for background OpenCode agents, cheapest/fastest first (default `openrouter/particle-ai/particle-1,openrouter/deepseek/deepseek-v4-flash,openrouter/deepseek/deepseek-v4.1-flash,openrouter/google/gemini-3.5-flash-lite`). `particle-ai/particle-1` is Particle AI's post-trained DeepSeek V4.1 Flash agentic model. A session runs on the first one the agent runtime offers; if none is offered the task fails instead of falling back to another model. No reasoning effort is requested |
| `acp_idle_s` | seconds a named helper's agent process may sit idle before it exits; the next request starts a fresh one (default 900) |
| `ask_timeout_s` | seconds an agent's question or permission ask waits for your answer; a permission then counts as refused, a question as unanswered (default 120) |
| `cancel_grace_s` | seconds a cancel waits for the agent to stop on its own before its process is killed (default 10) |
| `mcp_memory` | `true` lets agents read `USER.md` and `MEMORY.md` over the read-only bridge; those reads go to OpenRouter-routed models. `false` removes the memory tools from the list (default `true`) |

Background agents authenticate to OpenRouter through ori. The key Wisp hands
it comes from the `[brain.openrouter] key_env` list, tried in order:
`keyring://wisp/openrouter` (the desktop Secret Service, the default first
entry), `omaseal://svc/acct` (still works), then a plain env var such as
`OPENROUTER_API_KEY` from your environment or `~/.config/wisp/.env`.
`wispd onboard --step agents` stores a key in the keyring when you give it one.

## [mcp]

| key | default | meaning |
|-----|---------|---------|
| `enabled` | `true` | expose the `mcp_call` tool; servers are discovered by `wispd inventory` and `~/.config/wisp/mcp.json` (OAuth'd via `wispd connect`) |

## [recall] — semantic memory

| key | default | meaning |
|-----|---------|---------|
| `provider` | `"none"` | `none` (FTS5 keyword search) or `openai` (embeddings + RRF fusion) |
| `base_url` / `model` / `key_env` | openrouter | embedding endpoint + model + key env |

## [dictation] — LLM-aware dictation (U6)

| key | default | meaning |
|-----|---------|---------|
| `mode` | `"cleanup"` | what `dictate` does: `raw` verbatim, `cleanup` fixes grammar/spelling without changing your words, `compose` turns the ramble into finished text for the focused app's genre |
| `terminal_classes` | `""` | extra window classes that count as terminals for the newline guard (comma list; built-ins: foot, alacritty, kitty, ghostty, wezterm) |
| `model` | `""` | `provider:model` override for the cleanup/compose pass; empty = the `[brain]` chain |
| `history` | `"true"` | keep every finished dictation in `~/.local/share/wisp/dictation-history.jsonl` (mode 0600) so a failed insert loses nothing. Never sent anywhere and never put in a prompt. `"false"` keeps nothing |
| `history_max` | `"100"` | most entries kept |
| `history_days` | `"7"` | oldest entry kept, in days |

Dictated words are never lost: if an insert fails the text stays in the
history and the answer says so; `wispd dictate retry [N] [--delay S]`
inserts it again at the focused cursor, `wispd dictate copy [N]` copies it,
`wispd dictate history` lists them and `wispd dictate clear` wipes them. A
long recording writes each transcribed chunk to `dictation-session.jsonl`
as it goes, so a crash or kill keeps what was said (the next start moves it
into the history). Cleanup never adds words that were not spoken (a reply
with new words is dropped and your words are inserted as spoken), and a tap
or cough with nothing said inserts nothing.

Per-app profiles (VoiceInk Power Mode, thin): a `[dictation.profiles.
<pattern>]` section matched `*pattern*` against the focused window
class, longest match winning — `mode`, `style` (a free-text style hint
folded into the rewrite prompt) and `auto_send` (`true` asks before
pressing Return after the insert). Spoken overrides: `dictate raw ...`
skips the rewrite for that call; "write an email ..." intent words
trigger compose. Into a terminal-class window every mode collapses
newlines unless a confirmed send is armed. Personal corrections live in
`~/.local/share/wisp/dictation.json` — `wispd dictate correct` records
one, `wispd dictate list` shows them.

## [voice] — text-to-speech

| key | meaning |
|-----|---------|
| `enabled` | `"auto"` (default): speak answers when a Groq key resolves and an audio player exists; with no key it stays off, even if espeak is installed. Espeak (or `cmd`) is the fallback while voice is on. `"true"` always speaks (espeak or `cmd` when there is no key), `"false"` never does. Speech, desktop toasts (no toast for a spoken answer) and captions all read this one setting |
| `provider` | `"groq"` (default): speak with Groq Orpheus when a key resolves, a player (`pw-play`, else `paplay`, else `aplay`) is installed and the answer is English; `cmd`/espeak speaks whenever Groq cannot. `"espeak"`: never ask Groq. Same key as speech-to-text: `[stt] key_env` when `[stt] base_url` is Groq, else `omaseal://groq/default,GROQ_API_KEY` |
| `tts_model` | Groq model, default `canopylabs/orpheus-v1-english` (a preview model; the id is configurable for when it changes). Not in the settings table: edit `config.toml` |
| `tts_voice` | Orpheus voice: `autumn`, `diana`, `hannah` (default), `austin`, `daniel`, `troy` |
| `tts_base_url` | Groq API base, default `https://api.groq.com/openai/v1`. Not in the settings table |
| `cmd` | override TTS command. The message is written to its stdin, never put on the command line, so other local accounts cannot read it; a `{text}` token is dropped. Empty = built-in espeak |
| `speed` | speaking speed multiplier, 0.5 to 1.5 (default 1; steps 0.5, 0.75, 1, 1.25, 1.5). The built-in espeak voice gets `-s <wpm>`; a custom `cmd` gets the multiplier wherever it writes `{rate}`. Say "talk slower", "talk faster" or "talk at normal speed" to change it by voice (logged in the audit log as a `config` entry) |
| `lang_voices` | per-language voices, `"es=es-mx,de=de"`. Empty: the built-in espeak voice named for the language when it exists, else the default voice, and Wisp says so once. A custom `cmd` may use `{lang}` (the code, like `pt-BR`) or `{voice}` |
| `early_clause` | `"true"` (default): while an answer streams, start speaking at the first clause break (`, ; : —`) once 28 characters are ready instead of waiting for the full stop. `"false"` waits for sentence ends |
| `captions` | `"true"` (default): the answer text shows in the bubble while it is spoken. `"false"` hides it while the voice plays. The text shows anyway when voice is off, when no TTS program is installed, or when speech does not start. A muted speaker always shows it. Say "turn off captions" or "turn on captions" to change it (audited like any `config` change) |

### Groq talk-back

Each sentence goes to Groq as one request of at most 200 characters (a longer sentence splits at clause breaks, then spaces), the next sentence is fetched while the current one plays, and points and drawings start when that sentence's audio starts, timed from the WAV's real length. One voice per answer: if Groq fails (any error, a spend cap, no player), the rest of that answer is spoken by espeak or `cmd`; the next answer tries Groq again. Two failures wait first: a rate limit (429) waits out `retry-after`, and a terms error (the model's terms are accepted once per Groq org at `https://console.groq.com/playground?model=canopylabs%2Forpheus-v1-english`) waits an hour and then tries by itself. The last failure class and the wait end are kept in `voice_groq.json` in the data dir. Muted speakers and a non-English answer never reach Groq.

Groq speech is paid: each request writes a `usage.jsonl` row at $22 per million characters, counts toward `[budget]` and is refused at the daily cap (espeak speaks instead). The free Groq tier allows about 100 speech requests a day, so a long answer can switch to espeak partway.

When the default speaker is muted or at 0% (read with `wpctl`, else `pactl`), Wisp does not speak the answer: it copies it to the clipboard with `wl-copy` and the bubble ends with "Speaker is muted, so I copied the answer to your clipboard." Without `wl-copy` the bubble says it could not speak the answer. Nothing is probed while `[voice] enabled` is false.

## [quiet] — calls and screen shares

| key | default | meaning |
|-----|---------|---------|
| `on_calls` | `"true"` | hold announcements nobody asked for (a finished background agent, a routine) while a call or screen share is on. Calls and shares are read from the open windows (`hyprctl clients`: Zoom, Teams, Webex, Meet and huddle windows, "is sharing your screen" titles). Held toasts go out when it ends, checked every 20 s, at most 20 kept. Errors and the toast for a turn you started are never held. Uses the same gate as suggestion cards (`suggest_policy`) |

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
| `deny_titles` | `""` | substrings of a window **title** (for example `bank, paypal`) that are never captured or driven. A visible window with a matching title, or a denied app, is painted black in every screenshot even when it is not the focused window; if it can't be blanked the screenshot is skipped |
| `max_clicks_per_min` | `30` | rolling 60 s cap on click/scroll/type/key calls per window class (moves are not counted) |
| `max_per_turn` | `12` | cap on the same calls in one act run |
| `dry_run` | `false` | log what would happen and return `DRYRUN ...`; no driver, ydotool or hyprctl call. Deny, kill and rate checks still apply |
| `kill_switch` | `false` | refuse everything. The runtime file `$XDG_RUNTIME_DIR/wisp/cua.kill` does the same without a config edit (`cua_safety.kill()` / `resume()`) |
| `delivery` | `auto` | input delivery policy (`wisp/delivery.py`, U5): `auto` uses each op's natural channel — background where the backend offers one (cua click/scroll, type, key), real pointer otherwise; `background` refuses to silently drive the real pointer and guides instead; `pointer` prefers a real-pointer backend for clicks even when cua is up. An explicit `[pointer] backend` pin outranks the policy |
| `confirm` | `tier` | `tier` keeps the tool tiers; `always` makes click/move/scroll/type/key ask once per (tool, focused app) per session |
| `audit` | `true` | append one JSON line per call to `$XDG_STATE_HOME/wisp/cua.jsonl` |

Audit line: `ts, turn, tool, app, decision (allow|deny|dry_run|cancelled),
dry_run, result (first word only), delivery, ms`, plus `x`/`y` for coordinate
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
| P6 | TTS start (espeak or `[voice] cmd`) | 150 |
| P6G | TTS start, Groq (first sentence handed over -> first audio) | 1500 |
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

## [pointer] and [ground]: how clicks happen and where they land

| key | default | meaning |
|-----|---------|---------|
| `[pointer] mode` | `guide` | `guide`: Wisp points with the ghost cursor, you click. `drive`: inject real input through the backend. `auto`: drive when a backend exists, guide otherwise |
| `[pointer] backend` | `auto` | `auto`, `cua`, `hyprcursor`, `ydotool`, `wlrctl` or `none`. A named backend is used alone; if it is unavailable Wisp guides |
| `[ground] providers` | `control,a11y,uitars,jev` | grounding chain order: app control channel, cua accessibility tree, local UI-TARS, vision fallback. `uitars` is dropped unless `[local] enabled = true` |
| `[ground] min_confidence` | `0.5` | candidates below this are re-observed once, then refused |
| `[ground] budget_ms` | `1200` | shared budget for the fast providers |
| `[ground] fallback_timeout_ms` | `5000` | timeout for the vision fallback |
| `[ground] uitars_url` | `http://127.0.0.1:8081` | UI-TARS endpoint (also `[health] uitars`); loopback only |
| `[ground] uitars_coords` | `px` | `px` or `rel1000`, how UI-TARS writes coordinates |
| `[ground] a11y_frame` | `global` | `global` or `window`, the frame of accessibility element boxes |

The whole path is in `docs/CUA.md`.

## [control]: per-app control channels (U3)

Apps exposing a JSON-lines control channel get ground-truth grounding
(`ui.elements` automation ids) and a corroborating verify rung
(`ui.inspect`/`ui.elements` before-after diffs). FilmCraft is built in
at `127.0.0.1:9876` — launch it with `--control 9876`. Channels are
loopback-only; channel-reported rects are validated against live
compositor window bounds, never trusted alone.

Add an app either as a scalar or a table:

```toml
[control]
myapp = "127.0.0.1:9877"     # host:port — loopback only

[control.myapp]
port = "9877"                # host defaults to 127.0.0.1
match = "myapp,My App"       # window class/title patterns; default: the app key
```

| key | default | meaning |
|-----|---------|---------|
| `[control] <app>` | — | `host:port` scalar for app `<app>` |
| `[control.<app>] port` | — | control port for app `<app>` |
| `[control.<app>] host` | `127.0.0.1` | channel host (loopback only) |
| `[control.<app>] match` | app key | class/title patterns that select this app's channel |
| `[control] connect_timeout_s` | `0.4` | connect deadline |
| `[control] read_timeout_s` | `3.5` | read deadline per call |
| `[control] rect_slack_px` | `8` | tolerance when validating channel rects against compositor bounds |
| `[control] element_cap` | `1024` | max elements accepted from one `ui.elements` reply |

## [report]: opt-in error reporting (W16)

| key | default | meaning |
|-----|---------|---------|
| `dsn` | `""` | GlitchTip (Sentry-compatible) DSN, or `omaseal://service/account`. Empty means off |
| `per_code_per_hour` | `3` | reports per error code per hour |
| `global_per_hour` | `20` | reports per hour in total |
| `dedupe_secs` | `300` | identical reports inside this window are dropped |
| `queue_max` | `50` | offline queue length |

Only typed error codes and a scrubbed context are sent. Transcripts,
screenshots, typed text, keys, environment values and home paths never are.

## [sense]: activity sense and suggestions

Off by default. Local sources only (Hyprland window changes, the dayflow journal).

| key | default | meaning |
|-----|---------|---------|
| `enabled` | `false` | turn the collector on |
| `interval_s` | `300` | seconds between samples |
| `window_h` | `3` | hours of activity the miner reads |
| `dayflow` | `true` | also read `dayflow today --json` |
| `dayflow_every` | `4` | read dayflow every Nth sample |
| `mine_every_s` | `2700` | how often suggestions are mined |
| `max_calls_per_day` | `48` | cap on mining model calls |
| `model` | `openrouter:google/gemini-2.5-flash` | `provider:model` for mining; a local one costs nothing |

## [traj], [dev], [eval], [ui] and [apps]

| key | default | meaning |
|-----|---------|---------|
| `[traj] enabled` | `true` | record act-loop runs and inject similar past runs as context |
| `[traj] max_inject` | `3` | most prior runs injected |
| `[dev] refine` | `true` | a labelled-bad turn or a correction ("no", "instead") retries with the failed attempt as context |
| `[dev] panel` | `false` | when `true` the panel gains a fifth tab, Dev (v1 gate, recent turns with per-stage time, top misses); local-only. It reads `wispd dev turns --json` once when the tab opens and when you press refresh, never on a timer |
| `[dev] judge_model` | `google/gemini-2.5-flash` | vision model that judges each task of a `wispd dev run` at its end, on the eval key (`omaseal://openrouter/orchestral`, never the default key) |
| `[dev] judge_cap_usd` | `1.00` | most a single run may spend on judging; the rest of the run is marked unjudged and the report says so (0 judges nothing; blank or invalid uses 1.00) |
| `[eval] gate_rate` | `60%` | first-time-correct fraction (0 to 1, or a percentage) `wispd eval` must reach for PASS; the v1 bar is 60%; unset prints "gate not set" and no PASS or FAIL |
| `[eval] gate_min_turns` | `50` | labelled turns required before the gate can pass; fewer is FAIL with "needs N more labelled turns" |
| `[ui] theme` | `dark` | `dark` or `light`; `wispd theme <name>` swaps live |
| `[apps]` | per OS | name to launch command map Jev resolves "open the terminal" against (`browser`, `terminal`, `files`, `vscode`, `music`, `settings`, `browser_new_tab`) |

## [packs] — capture-pack retention (U4)

Every recorded act turn is folded into `~/.local/share/wisp/packs/<turn>/`
(`manifest.json`, frame PNGs, `contact.png`, mode `0700`; `wispd captures`
serves them over IPC). The transient `rec/<turn>/` intermediates are
deleted at pack-write.

| key | default | meaning |
|-----|---------|---------|
| `keep` | `200` | newest packs retained (0 disables the count bound) |
| `keep_days` | `30` | days a pack is kept (0 disables the age bound) |
| `shots_keep` | `100` | newest files kept under `shots/` — the pack writer owns that pruning (0 disables) |
| `shots_keep_days` | `30` | days a `shots/` screenshot is kept (0 disables) |

Both bounds apply together; pruning runs after each pack write and at
daemon start.

## [verify] — action-verdict ladder (U2)

Every recorded act action earns a verdict (`landed`/`missed`/
`refused`/`suppressed`/`unverifiable`/`not_recorded`). The cheap
rungs vote first — a masked pixel diff of the driver's before/after
frames at the predicted region, plus the app's control-channel diff
when it ships one (see [control]); disagreement or mutual abstention
escalates to a VLM judge.

| key | default | meaning |
|-----|---------|---------|
| `vlm` | (empty) | `provider:model` endpoint for the judge; empty uses the primary brain |
| `judge_timeout_s` | `20` | seconds the judge may take before the step lands unverifiable |
| `pixel_landed_min` | `0.02` | changed-fraction threshold for a `landed` vote |
| `pixel_missed_max` | `0.001` | changed-fraction ceiling for a `missed` vote (between the two: abstain) |
| `pixel_eps` | `16` | per-channel pixel difference counted as a change |
| `region_px` | `96` | side of the square pixel region diffed around a click point |
| `frame_wait_s` | `0.5` | bound on waiting for the driver's before/after frames |

## [selection] — what you selected, copied or pointed at

"What does this mean" can use the exact words you highlighted, the image
you copied, or the file whose path you selected, instead of a guess from
the screenshot. The Wayland primary selection is read once when you press
the key; the clipboard is read only when your question says "this",
"that", "copied", "clipboard" or "selected". Nothing is read between
presses, and the text is passed to the answer model only (never the router
or the act loop) as quoted data it must not obey, with control and
invisible characters removed and the size capped at 4000 characters. A
selected file path goes through the `[docs]` reader and its protected
folder rule. A selection is sent only when the question points at it.

| key | default | meaning |
|-----|---------|---------|
| `enabled` | `true` | set `false` to never read the selection or clipboard |
| `clipboard` | `true` | set `false` to read the selection only |

## [docs] — answer about the whole document

When you ask about a document ("what does page 30 say", "summarize this
paper") and the focused window shows a PDF, DOCX, XLSX, TXT or MD file,
Wisp reads the file locally and gives the answer model the pages your
question names or matches (about 6000 characters). Files over 40 MB and
files in protected folders (`~/.ssh`, `~/.config`, keyrings, browser
profiles, system directories) are never read. Scanned PDFs use OCR when
`tesseract` is installed.

| key | default | meaning |
|-----|---------|---------|
| `enabled` | `true` | set `false` to never read the focused file |

## [chips] — what can I ask here?

A quick tap of the talk key with no speech shows up to three asks that fit
the focused app, beside the bottom of the screen, for a few seconds. Saying
one runs it like any other turn. Chips appear only on a tap, never unprompted,
only during the first `days` days from the first tap, and no screenshot is
taken for the tap. Each app skill lists its asks in an `asks:` line of its
`SKILL.md`, separated by `;`.

| key | default | meaning |
|-----|---------|---------|
| `enabled` | `true` | set `false` to never show chips |
| `days` | `7` | chips are offered for this many days from the first tap |

## [images] — pictures in answers

An answer may carry one picture, a `::image[url=...,alt=...]` line on the
paper. Wisp fetches it only from an allow-listed host over https and shows
it in a small card on calm screen space (clear of every mark and the
answer bubble) with its source address underneath. A picture from any
other host is not fetched; Wisp says so out loud. Redirects are checked
against the same list, hosts that resolve to private or loopback
addresses are refused, and the file must really be a PNG, JPEG, GIF or
WebP. Copies are kept in `<data dir>/images/`.

| key | default | meaning |
|-----|---------|---------|
| `allow` | `""` | comma list of hosts (each also matches its subdomains); empty keeps the built-in default, `upload.wikimedia.org` |
| `max_kb` | `4096` | largest picture to download, in KB |
| `timeout_s` | `8` | give up on a slow fetch after this many seconds |

## [models] — 3D parts in answers

An answer may carry one small 3D model, a `::model[url=...,alt=...]` line
on the paper pointing at a glTF or GLB file. Wisp fetches it only from an
allow-listed host over https (same rules as `[images]`: redirects checked,
private addresses refused, size and time capped), reads the named parts
and their bounding boxes (never the mesh data, and a file that points at
other files is refused) and shows them as a small turnable card. Click a
part and Wisp asks one question that names it, as a normal turn
(`wispd ask "..."`). The card takes the pointer only while it is on
screen; it is click-through again when the answer goes. Parts are kept in
`<data dir>/models/`.

| key | default | meaning |
|-----|---------|---------|
| `allow` | `""` | comma list of hosts (each also matches its subdomains); empty keeps the built-in default, `raw.githubusercontent.com` |
| `max_kb` | `4096` | largest model file to download, in KB |
| `timeout_s` | `8` | give up on a slow fetch after this many seconds |

## [debug]

| key | meaning |
|-----|---------|
| `trace` | write the full dev trace (`trace.jsonl` — every stage, tool call, timing; never logs keys) |

## Environment overrides

| var | effect |
|-----|--------|
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
cua status|test|log|kill|resume|enable|disable   notify test
task list|status|cancel|run    memory edit|write    suggest list
label set                     context  ask TEXT
learn fails  eval [--json]      skills list|import
trace show|digest              captures [turn] [--full]
config show|set|keys           theme show|set|check|css
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
--tail/--latency`, `skills` with no verb, `config`
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
