---
plan: dim-u6-brain-providers
created: 2026-09-27
status: ready
origin: docs/plans/2026-09-26-001-feat-dim-companion-crossplatform-plan.md#U6
issue: https://github.com/duketopceo/dim-agent/issues/13
wave: 3
---

# U6 — Brain provider trait + registry (Rust)

## Scope

One `Brain` trait so users power Dim however they want: OpenRouter
default, any OpenAI-compatible endpoint (Ollama, LM Studio, vLLM,
corporate gateways), MLX, plus a native Ollama path.

## Steps

1. **Trait**: `trait Brain { chat(messages, opts) -> Result<String>;
   supports_vision(); supports_tools(); }`
2. **Providers**: `openrouter` (current client), `openai_compat`
   (base_url+model+optional key — covers Ollama/LM Studio/vLLM),
   `mlx` (mlx-lm server endpoint + health probe), `ollama` native
   `/api/chat` (richer than the compat shim).
3. **Config**: `[brain] default = "openrouter:meta-llama/llama-4-maverick"`,
   named provider sections, `router = "jev"|"chat"|"off"`,
   `agent_runtime = "opencode"|"codex"|"claude"|"devin"` + PATH probe;
   missing runtime → explicit error state.
4. **Router modes**: `jev` (current), `chat` (transcript+screenshot
   straight to the answer brain), `off` (always clarify→choice).
5. **Python parity shim**: same config keys honored in `dim/config.py`
   so both cores read one file.

## Tests

- Provider string parsing, vision/tool capability gating (screenshot
  attached only when supported).
- Router `off` → choice flow without a Jev call.
- Agent runtime probe against stub PATH entries.

## Risks

- Provider quirks (Ollama tool-call format vs OpenAI) — keep per-
  provider payload builders small and tested with recorded responses.

## Done when

`[brain] default = "ollama:llama3.1"` + `router = "chat"` answers
locally with zero OpenRouter calls.
