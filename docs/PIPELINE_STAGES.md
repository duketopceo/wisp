# Pipeline stages (W30)

`wisp/pipeline.py` used to hold the whole turn. It is now an orchestrator
over four stage modules, all writing through the StateBus turn handle:

| Module | Stage | Owns |
|---|---|---|
| `wisp/stage_capture.py` | capture | recorder and level sampler, transcription (local, wordink, OpenAI-compatible), trigger screenshot (checked for a black or single-colour frame by `wisp/blank.py`: one window-capture retry, then the window's accessibility text with one spoken sentence, else "I can't see that window." and no model call) and window map, `capture_stage` and `context_stage` (focus, goal, session, memory, correction) |
| `wisp/stage_route.py` | route | `fixed_route` (local routes, with a saved `router = "jev"` or unknown value read as `act`), `fast_route` (the no-model fast path), `route_stage` |
| `wisp/stage_execute.py` | execute | `execute` (risk gate and dispatch to tools, act loop, agents, dictation), `execute_stage` |
| `wisp/stage_speak.py` | speak | `ask_chat`, answer streaming, TTS, ASK_USER, `log_decision`, `speak_stage` |
| `wisp/stage_ctx.py` | shared | `TurnCtx`, the per-turn values the stages hand to each other |

`wisp/pipeline.py` keeps `run_listen`, `_listen_turn` (cancel, error and
cleanup paths), `notify`, `_publish_error`, and re-exports every public
name, so `pipeline.execute` and the rest still resolve.

Patch targets: a stage calls anything tests patch (`execute`,
`record`, `capture_screen`, `notify`, `log_decision`, `_ask_prompt`, ...)
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

## Walkthrough step kinds

Each walkthrough step carries a `kind` and an optional `radius` (logical
px), defined in `wisp/step_kinds.py` and saved in the paused, last-finished
and lesson dumps next to `why`. The planner picks the kind by one rule: if
the app will visibly react to the action, use `click` or `hover`;
otherwise use `area`, `handle`, `motion` or `voice-confirm` and ask the
user to say "continue".

| Kind | Meaning | Drawn as | Advances on |
|---|---|---|---|
| `click` | one atomic click the app will show | ring with radius | click in radius |
| `hover` | reveal something by hovering | dashed ring | pointer rest |
| `area` | a region matters, no single control | soft highlight region | settle or voice |
| `handle` | a thing to grab or drag from | small marker | settle or voice |
| `motion` | direction of a drag or swipe | arrow or curve | settle or voice |
| `voice-confirm` | not detectable (type text, set a value) | none, caption chip | "continue" |

An unknown kind falls back to `voice-confirm` (the only kind that never
claims detection) and is logged once. A step the model plans as `click`
whose label or wording is text entry is rewritten to `voice-confirm`. A
click with no radius uses `DEFAULT_CLICK_RADIUS`. Steps saved before kinds
existed read back as plain clicks.

## Latency gate

`wisp/budgets.json` holds a p50 budget per path (a path's p90 may be up to
1.5x). The replay harness (`tests/harness/latency.py`) runs fixture turns
against fake models and fails `tests.test_budgets` when a measured path goes
over its budget; on CI the budget is multiplied by 2 (`CI_SCALE`) because
shared runners are slower than a desktop. `tests.test_latency_budgets` proves
the gate by slowing one stage at a time (speech-to-text, route, first token)
and requiring that path to fail at the exact budget. A budget is never loosened to make
a change pass.

`wispd eval` prints the measured p50 and p90 of the last week of turns next to
each path's budget (the same table as `wispd latency`), and `--json` carries
the rows as `latency`.
