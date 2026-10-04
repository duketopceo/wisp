# Pipeline stages (W30)

`wisp/pipeline.py` used to hold the whole turn. It is now an orchestrator
over four stage modules, all writing through the StateBus turn handle:

| Module | Stage | Owns |
|---|---|---|
| `wisp/stage_capture.py` | capture | recorder and level sampler, transcription (local, wordink, OpenAI-compatible), trigger screenshot and window map, `capture_stage` and `context_stage` (focus, goal, session, memory, correction) |
| `wisp/stage_route.py` | route | `JEV_QUESTIONS`, `ask_jev`, shadow decider, rescues (`fuzzy_app`, `complex_launch`), clarify prompt, `route_stage` |
| `wisp/stage_execute.py` | execute | `execute` (risk gate and dispatch to tools, act loop, agents, dictation), `execute_stage` |
| `wisp/stage_speak.py` | speak | `ask_chat`, answer streaming, TTS, ASK_USER, `log_decision`, `speak_stage` |
| `wisp/stage_ctx.py` | shared | `TurnCtx`, the per-turn values the stages hand to each other |

`wisp/pipeline.py` keeps `run_listen`, `_listen_turn` (cancel, error and
cleanup paths), `notify`, `_publish_error`, and re-exports every public
name, so `pipeline.ask_jev`, `pipeline.execute` and the rest still resolve.

Patch targets: a stage calls anything tests patch (`ask_jev`, `execute`,
`record`, `capture_screen`, `notify`, `log_decision`, `_shadow_worker`, ...)
through `wisp.pipeline` at call time (`_pl()`), so
`mock.patch.object(pipeline, "<name>")` keeps working. Do not call such a
name directly from inside a stage module.

## Background writer

`wisp/bgwriter.py` takes trajectory (`act.py`) and recall (`index_turn`,
`index_correction`) writes off the turn: `submit` appends to a bounded
queue and returns; one daemon thread writes in order. Overflow drops the
oldest job and counts it (`bgwriter.stats()["dropped"]`). `wispd` flushes it
on shutdown and `atexit` covers the rest.

## Settings (daemon only, not in the Panel)

`[agents]` keys, declared in `wisp/settings_schema.py`:
`act_max_steps` (12), `act_max_errors` (2), `act_max_parse_misses` (1),
`writer_queue_max` (256).
