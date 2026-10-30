# ACP launch spike: pinned ori + OpenCode 2.x under a private home

Date: 2026-10-28. Binaries: ori `0.16.1+91f9f29` (`ori-linux-arm64`) and OpenCode `v2.2.0` (`opencode-linux-arm64.tar.gz`). Both were downloaded from the pinned release tags, and their SHA-256 matched the release `SHA256SUMS`. Host: aarch64 Arch Linux ARM. The user's own OpenCode 2.1.4 background service was running at the time.

No `session/prompt` was ever sent, so no model was called. Only `initialize`, `session/new`, `session/set_config_option`, `ori auth --json` and OpenCode's `debug` subcommands were used. Credentials were never printed; only `authenticated` and the source label were read.

This answers the checks U4 of `docs/plans/2026-10-28-2249-feat-wisp-acp-agents-plan.md` lists.

## Results

| Check | Result |
|---|---|
| `ori auth --json` under the private `XDG_*` env, `HOME` kept | Exit 0, `data.authenticated: true`. Its `source` label said `environment` / `OPENROUTER_API_KEY` even though that env had no such variable, so the label is not a reliable signal. Only `authenticated` is (the probe was fixed to read it). |
| The global config comes from the private `XDG_CONFIG_HOME` | Yes. `opencode debug paths` lists every dir under the private home. The `wisp` agent from the private `opencode.json` is the session's default mode, and none of the user's commands or agents appear. |
| `ori opencode acp` without `--standalone` touches the shared service | No. `~/.local/state/opencode/service.json` mtime was unchanged, and the session's DB was created under the private `XDG_DATA_HOME`. The `debug config`/`debug agents` CLI commands without `--standalone` did try to start a private service on the same fixed port, and failed. ACP does not use that path. |
| `ori opencode acp --standalone` | Broken for ACP: non-protocol text on stdout fails JSON-RPC framing. Wisp launches without `--standalone`. |
| Project `opencode.json` and `.opencode/command/*.md` in cwd | **Loaded by default**: the project agent appeared as a mode and the project command in `available_commands_update`. With `OPENCODE_DISABLE_PROJECT_CONFIG=1` neither loads. Wisp sets it, plus `OPENCODE_DISABLE_CLAUDE_CODE=1` (keeps `~/.claude` skills out) and `OPENCODE_DISABLE_AUTOUPDATE=1`. |
| Model option in `session/new` | `category: "model"`, 360+ ids. The default `currentValue` varied between runs (`openrouter/openai/gpt-6.1-terra`, `openrouter/particle-ai/particle-1`), so the default is never safe to rely on. `openrouter/deepseek/deepseek-v4-flash` is offered, and `session/set_config_option` to it returned that as the current value. Other cheap ids seen: `openrouter/deepseek/deepseek-v4.1-flash`, `openrouter/google/gemini-3.5-flash-lite`, `openrouter/z-ai/glm-5.3-flashx`. |
| Wisp's generated `opencode.json` (U4) | Accepted, no config errors. The effective `wisp` permissions are OpenCode's base rules followed by Wisp's. Last match wins, so every action asks, `wisp_*` MCP tools are allowed and `*.env` reads are denied. |
| Agent capabilities | `protocolVersion: 1`, `loadSession`, `mcpCapabilities {http: true, sse: false}` (stdio is mandatory in ACP), image and embedded context, session resume/fork/list/close/delete. |

## Not checked live

Whether OpenCode sends `session/request_permission` for every `ask`-ruled action can only be seen by running a prompt, which spends model tokens. The client side is pinned by the fake-agent tests. The effective rule list above makes `ask` the outcome for every action except Wisp's MCP tools and `.env` reads. `wispd doctor` reports that this check was not run live.

## Leftovers

The spike left no processes running. The scratch homes live only in the session scratchpad.
