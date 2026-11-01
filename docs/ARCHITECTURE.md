# Architecture

Wisp is a resident desktop companion: push-to-talk (or typed IPC) → a
staged pipeline in `wispd` → a guarded tool/act loop → spoken + on-screen
feedback. Everything below is the current tree, not aspirational.

## Turn anatomy

```mermaid
flowchart TD
    HK[hotkey SUPER+D / wisp-trigger] -->|t0 wall-clock ns| IPC
    IPC["wispd : AF_UNIX $XDG_RUNTIME_DIR/wisp/wispd.sock"] --> PIPE

    subgraph PIPE[turn pipeline — wisp/pipeline.py + stage_*]
        REC["record<br/>pw-record → wav"] --> STT["transcribe<br/>stt: groq whisper / local"]
        STT --> CAP["capture<br/>trigger screenshot:<br/>grim → normalize to logical px<br/>+ 100px grid → JPEG q85"]
        CAP --> CTX["context<br/>active window · apps=<br/>defaults= (mimeapps)<br/>goal memory · session"]
        CTX --> ROUTE["route<br/>router=act: fast path or straight to loop<br/>(no decision-model hop)"]
        ROUTE --> ACT["act loop — wisp/act.py<br/>conversational tool calls,<br/>max_steps/errors/seconds/usd bounds"]
        ACT --> SPK["speak<br/>TTS answer + ACTED replies<br/>[POINT] tags → beacons"]
    end

    subgraph TOOLS[toolbelt — wisp/tools/]
        DESK["desktop: launch/focus/workspace<br/>(focus-first on running apps,<br/>normalized class/title match)"]
        SYS["system: click/type/key/screenshot<br/>notify/shell/file ops"]
        GND["grounding chain<br/>a11y → ui-tars :8081 → jev vision"]
        SYS --> GND
        CUA["cua-driver (rust) + cua-hyprland<br/>plugin — window-local inject,<br/>never seizes real cursor"]
        SYS --> CUA
    end
    ACT --> TOOLS

    subgraph GATE[policy — wisp/policy.py + cua_safety.py]
        TIERS["risk tiers T0 read / T1 reversible<br/>T2 checkpoint-batch / T3 hands-off"]
        DENY["denylist + allow_shell preempt"]
        CONFIRM["confirm card (bar pill)<br/>voice pick / click / typed"]
        TIERS --> CONFIRM
    end
    TOOLS --> GATE

    subgraph BRAIN[brain chain — wisp/brain.py]
        OR["OpenRouter<br/>gemini-2.5-flash"] -.->|fallback| LOCAL["local<br/>llama-local :8080 ornith-35B"]
        OLL["ollama :11434"]
    end
    ACT --> BRAIN

    subgraph SURFACE[shell plugin — Quickshell QML]
        PILL["bar pill, top-center<br/>(fixed spot, not pointer-follow)"]
        GHOST["cursor buddy + point beacons<br/>wisp-points"]
    end
    PIPE --> SURFACE
```

## Data spine — `~/.local/share/wisp/`

| File | What |
|---|---|
| `trace.jsonl` | debug spine — every stage event per turn: `screen_capture`/`shot_normalize`/`shot_compress`/`llm_call`/`tool_call`/`tool_result`/`ground(_refused)`/spans. `wispd trace --turn <id>` |
| `decisions.jsonl` | one row per turn: route, ms timings, result |
| `trajectories.jsonl` | act-loop step sequences (training data) |
| `usage.jsonl` | model spend ledger (also legacy `spend.jsonl`) |
| `activity.jsonl` | dayflow harness feed (app focus history) |
| `inventory.json` | installed-app catalog + `defaults` from mimeapps |
| `labels.jsonl` | route-intent corrections (right/wrong on decisions) |
| `corrections.jsonl` | dictate "I meant X" pairs |
| `session.jsonl` | conversational session turns |
| `tasks.jsonl` + `tasks/` | background agent runs |
| `recall.db`, `MEMORY.md` | memory + recall store |
| `wispd.log` | daemon operational log |
| `state.json` (RUN_DIR) | live StateBus snapshot the shell renders |

## Key invariants

- **Screenshot pixel space is logical.** `_normalize_shot` resizes to the
  compositor's logical canvas and overlays a labeled grid; clicks map
  1:1 via `points.to_logical` (SHOT_ORIGIN tracks single-output offsets).
  Model transport is JPEG q85; disk stays PNG.
- **The model never asks "which app".** `apps=` + `defaults=` are in the
  env line; `launch` resolves installed apps by normalized name, focuses
  running ones, opens domains in the configured browser.
- **Grounding degrades, never guesses silently.** Chain refuses with
  reasons (`low_confidence`, `all_down`, `not_found`) and each outcome is
  traced.
- **Safety is boundary-based.** Denylist preempts tiers; T2 batches into
  one confirm card; the loop drops user input instantly
  (`realinput` watch) — never fights the human for the cursor.

See `docs/PIPELINE_STAGES.md` for the per-stage contract and
`docs/CUA.md` for the computer-use driver detail.
