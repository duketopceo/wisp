# Scenario corpus (W6)

Turn fixtures under `tests/fixtures/turns/*.json`. Each one is a complete
turn for the replay harness: a fixture WAV, scripted fake models (Jev,
brain, whisper), optional fakes for `cua-driver`, Hyprland, `notify-send`,
and an `expect` block the harness checks. Nothing here touches a live
model, network, `hyprctl` or `cua-driver`.

```
python scripts/replay_turn.py <name>        # one fixture, with timeline
python scripts/replay_turn.py <name> --json
python -m unittest tests.test_scenarios     # whole corpus, under 20 s
```

`expect` keys (see `tests/harness/runner.py`): `statuses`, `answer`,
`transcript`, `result_prefix`, `error_code`, `error_contains`,
`error_detail_contains`, `tool_calls`, `brain_calls`, `jev_calls`,
`cua_calls`, `steps_contain` (one substring per act step, in order),
`notify_count`, `notify_bodies`, `launch_calls`, `hypr_requests_contain`,
`peer_closed`, `groq_tts_calls` (requests the fake Groq speech endpoint saw), top-level `notify_now` (fixed clock for quiet hours), `brain_fallback_from`, `stop_within_ms` (interrupt to idle,
the P9 budget). `tests/test_scenarios.py` requires every fixture to carry a
`description`, a `scenario` tag and a non-empty `expect`, and requires this
table to list every fixture.

| Fixture | Scenario | What it checks |
|---|---|---|
| `act` | act via tools | Act route: the brain makes two tool steps (recall, safe and local) then finishes. |
| `act_click_cua` | act click via cua | Act route: click through the fake cua-driver (daemon socket + CLI); notify and Hyprland fakes on PATH. |
| `act_click_cua_down` | cua down | cua socket file exists but the daemon is dead: the click fails and is not retried elsewhere. |
| `act_confirm_no` | choose/confirm | [cua] confirm = always: the chooser answers no, the click is declined and cua-driver is never called. |
| `act_confirm_yes` | choose/confirm | [cua] confirm = always: the click asks first; the scripted chooser answers yes and cua-driver is called once. |
| `act_false_done` | act done claim contradicted by its own step | Act route, live miss 2026-10-28 (t2e469f9a): 'open up my stripe tablet' makes launch(foot), which only refocuses an already-running terminal. The model claims 'opened'; the done-claim guard nudges once, the model repeats the claim, and the turn ends with an honest 'could not confirm' instead of the false success. |
| `act_false_done_recovers` | act done claim nudged into a real step | Act route: same unsupported done claim after launch(foot), but the nudge makes the model call tab(stripe). The later done is checked against that tab step and reported normally. |
| `act_guide_mode` | guide mode | pointer.mode = guide: the click is a user hand-off (ghost cursor guide), no backend is invoked. |
| `act_go_to_site` | go to a site in the browser | Act route: 'go to stripe.com' makes one launch(stripe.com) step. The launch stub returns the OPENED line the real launch gives when a site opens in the user's browser (tests/test_tools.py proves that); the turn ends ACTED, never a second app spawned through xdg-open. |
| `act_media_pause` | pause media natively | Act route, live miss 2026-10-30 (t6549f8d2): 'pause youtube' makes one media(pause) step through Omarchy's native media control; no tab switch and no click on a player. The media stub returns the MEDIA line the real tool gives (tests/test_media_tool.py proves that); the turn ends ACTED. |
| `act_open_mail` | open mail in browser | Act route: 'open my email' makes one launch(mail) step. The launch stub returns the OPENED line the real launch gives when mail resolves to a browser (tests/test_tools.py proves that); the turn ends ACTED, never a focused-window success. |
| `act_switch_tab` | switch to an open browser tab | Act route: 'open up my stripe tab' makes one tab step (switch to the already-open browser tab); launch is never called. The tab stub returns the SWITCHED line the real tool gives (tests/test_tools.py proves that). |
| `answer_draw_timed` | drawings timed to speech | Answer route with voice on and a fake TTS that takes 300 ms per sentence: the brain streams two sentences, the first with a [RING], the second with a [POINT] and an [ARROW]. `drawings` grows 1 then 2 while speaking (the second only after the first sentence has played), `points` arrives with the second; no tag reaches the answer and both lists are empty at done. |
| `answer_groq_voice` | groq talk-back timed to audio | Answer route with Groq talk-back: a fake `/audio/speech` returns a 400 ms then a 300 ms WAV and a fake player sleeps each WAV's real length. The brain streams two sentences, each with its own [POINT] tag; one request per sentence, `points` grows 1 then 2 and the second point arrives only after the first WAV's real duration (>= 350 ms). |
| `answer_points_timed` | points timed to speech | Answer route with voice on and a fake TTS that takes 300 ms per sentence: the brain streams two sentences, each with its own [POINT] tag. `points` grows 1 then 2 while speaking, the second point arriving only after the first sentence has played; no event carries both early. |
| `ask` | answer | Answer route: Jev routes to answer, brain streams a reply. Characterization baseline of today's pipeline. |
| `fast_path_answer` | fast path plain question | Default router: 'what does this error mean' is a plain question, so the fast path sends it to the answer handler in one brain call. No Jev call and no act loop (the result is ANSWERED, not ACTED). |
| `fast_path_compound_stays_in_act` | compound request skips the fast path | Default router: 'open firefox and go to github' is compound, so it is not a fast-path launch. It enters the act loop (ACTED), where the brain makes the launch step. |
| `fast_path_launch` | fast path launch | Default router: 'open firefox' is a bare launch of a catalogued app, so the regex fast path launches it directly. No Jev call and no brain call (the act loop never starts). |
| `lang_unsupported` | multilingual | [stt] language names a language the speech service cannot transcribe: the turn ends at once with a spoken reason, no brain call (B23). |
| `lang_voice_fallback` | multilingual | Spanish heard but the custom voice command takes no {lang}: the default voice is used and the fallback is recorded (B23). |
| `lang_fr` | multilingual | French pinned (B23). |
| `lang_ja` | multilingual | Japanese heard by auto detection (B23). |
| `lang_pt_br` | multilingual | Brazilian Portuguese pinned in [stt] language (B23). |
| `lang_de` | multilingual | German heard by auto detection (B23). |
| `lang_es` | multilingual | Spanish heard by auto detection: transcript kept, reply rule in the answer prompt, Spanish voice (B23). |
| `ask_chip` | answer from an ask chip | Saying an ask chip's text (the kitty skill's first ask) runs as a normal answer turn: same route, same stages, one brain call. |
| `ask_selection` | answer with the selection | Answer route with a press-time selection: it reaches the brain as a quoted data block (B22). |
| `ask_selection_injected` | selection is data | A selection that tries to give orders is delivered as data and routing is unchanged (B22). |
| `brain_down` | brain down | Answer brain returns 500 and no fallback is configured: the turn ends in error with error_code brain_down (U7). No canned answer. |
| `brain_fallback` | brain fallback | Primary answer brain returns 500; [brain] fallback names a second fake brain which answers. Trace records fallback_from (U7). |
| `budget_blocked` | budget blocked | W14: `[budget] daily_usd = 0` with `gate_primary = true` and a paid primary brain. The cap gates the primary too: no request is made and the turn ends in error with error_code budget_exceeded. |
| `budget_fallback_skipped` | budget blocked | W14 reconciled policy: at the cap a paid FALLBACK is skipped but the primary still runs. The free primary returns 500, the paid fallback is refused before any request, the turn ends brain_down naming the skipped entry. |
| `cancel_mid_act` | cancel mid-act | Act route: the fake cua-driver click hangs; the user stop lands mid-call. W9: the guard/cancel path ends the turn INTERRUPTED within 150 ms of the stop and no further step runs. |
| `cancel_mid_stream` | cancel mid-stream | Cancel fires while the answer is still streaming. U9: the stream stops promptly, the brain socket closes, no further deltas publish and the turn ends idle with error_code cancelled. |
| `choose` | choose/confirm | Low-confidence launch: pipeline offers choices, the scripted chooser picks app:discord, launch stub records it. |
| `cua_denied_app` | deny-listed app | Focused window is a password manager: the built-in deny list refuses the click, cua-driver is never called. |
| `cua_dry_run` | dry-run | [cua] dry_run on: the click is reported as DRYRUN and nothing is sent to cua-driver. |
| `cua_kill_switch` | kill switch | [cua] kill_switch on: every injected click is refused before dispatch; cua-driver sees nothing. |
| `cua_rate_limited` | rate limit hit | Per-turn click cap of 1: the first click goes through, the second is refused and never reaches cua-driver. |
| `jev_down` | Jev down | Jev answers 503 on every call. The heuristic router takes over (W11): a bare launch of a catalog app still launches and the turn ends done, never in error. The error-path copy for a genuine outage lives in `brain_down`. |
| `jev_slow` | Jev slow | Jev replies after 2 s, past the 400 ms deadline: the heuristic routes the turn, the late reply is discarded and the brain streams the answer (W11). |
| `notify_error_toast` | notify paths | Brain down with the notify fake installed: the error turn raises an error toast. |
| `notify_outside_quiet` | notify paths | Control for notify_quiet_hours: same 22:00-07:00 window, fixed clock 12:00 is outside it, so the toast is sent. |
| `notify_quiet_hours` | notify paths | Same turn inside [notify] quiet hours (22:00-07:00, fixed clock 23:30 via notify_now): the toast is suppressed, nothing reaches notify-send. |
| `notify_success_toast` | notify paths | Answer turn with the notify fake installed: one success toast reaches notify-send. |
| `offline_all` | offline daemon | Every model endpoint is down (STT, Jev, brain): the turn ends in a clean error, nothing leaves loopback. |
| `router_act` | act router | `[brain] router = act`: every turn enters the conversational act loop directly — zero Jev calls (jev_calls = 0), the act brain answers or acts. |
| `router_act_default` | default router | no `[brain] router` configured: the default routes straight to the act loop — zero Jev calls (jev_calls = 0). |
| `stale_choice` | stale choice | The chooser returns a pick that was never offered (stale prompt). U9: it is rejected (choice_rejected in the trace) and the turn falls back to the safe auto-pick. |
| `stt_failure` | STT failure | Whisper answers 500: the turn ends in error before routing; Jev and the brain are never called. |

## Pending

- **agent spawn** (P8 agent ack): `agents.spawn` forks a process; needs an
  agent fake first.

## Latency

`wispd latency --baseline` shows the fake-backed budget baseline measured
over `ask`, `act_click_cua`, `cancel_mid_act`, `brain_down` and `jev_down`
(`docs/baselines/latency-harness.json`).
