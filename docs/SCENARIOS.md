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
`peer_closed`, `brain_fallback_from`, `stop_within_ms` (interrupt to idle,
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
| `act_guide_mode` | guide mode | pointer.mode = guide: the click is a user hand-off (ghost cursor guide), no backend is invoked. |
| `ask` | answer | Answer route: Jev routes to answer, brain streams a reply. Characterization baseline of today's pipeline. |
| `brain_down` | brain down | Answer brain returns 500 and no fallback is configured: the turn ends in error with error_code brain_down (U7). No canned answer. |
| `brain_fallback` | brain fallback | Primary answer brain returns 500; [brain] fallback names a second fake brain which answers. Trace records fallback_from (U7). |
| `cancel_mid_act` | cancel mid-act | Act route: the fake cua-driver click hangs; the user stop lands mid-call. W9: the guard/cancel path ends the turn INTERRUPTED within 150 ms of the stop and no further step runs. |
| `cancel_mid_stream` | cancel mid-stream | Cancel fires while the answer is still streaming. U9: the stream stops promptly, the brain socket closes, no further deltas publish and the turn ends idle with error_code cancelled. |
| `choose` | choose/confirm | Low-confidence launch: pipeline offers choices, the scripted chooser picks app:discord, launch stub records it. |
| `cua_denied_app` | deny-listed app | Focused window is a password manager: the built-in deny list refuses the click, cua-driver is never called. |
| `cua_dry_run` | dry-run | [cua] dry_run on: the click is reported as DRYRUN and nothing is sent to cua-driver. |
| `cua_kill_switch` | kill switch | [cua] kill_switch on: every injected click is refused before dispatch; cua-driver sees nothing. |
| `cua_rate_limited` | rate limit hit | Per-turn click cap of 1: the first click goes through, the second is refused and never reaches cua-driver. |
| `jev_down` | Jev down | Jev answers 503 on every call. The turn ends in error with error_code jev_down, a human-safe error string and the raw text in error_detail (U7). No fallback router until U8. |
| `notify_error_toast` | notify paths | Brain down with the notify fake installed: the error turn raises an error toast. |
| `notify_quiet_hours` | notify paths | Same turn inside [notify] quiet hours: the toast is suppressed, nothing reaches notify-send. |
| `notify_success_toast` | notify paths | Answer turn with the notify fake installed: one success toast reaches notify-send. |
| `offline_all` | offline daemon | Every model endpoint is down (STT, Jev, brain): the turn ends in a clean error, nothing leaves loopback. |
| `stale_choice` | stale choice | The chooser returns a pick that was never offered (stale prompt). U9: it is rejected (choice_rejected in the trace) and the turn falls back to the safe auto-pick. |
| `stt_failure` | STT failure | Whisper answers 500: the turn ends in error before routing; Jev and the brain are never called. |

## Pending

- **budget blocked** (W14 usage ledger): the ledger and spend cap are in
  open PR #88, not on master. Add `budget_blocked.json` once the ledger
  lands, and move the tag from `PENDING` to `REQUIRED` in
  `tests/test_scenarios.py`.
- **agent spawn** (P8 agent ack): `agents.spawn` forks a process; needs an
  agent fake first.
- **quiet hours** note: `notify_quiet_hours` uses `00:00-23:59`, so the
  one minute at 23:59 each day is not quiet.

## Latency

`wispd latency --baseline` shows the fake-backed budget baseline measured
over `ask`, `act_click_cua`, `cancel_mid_act`, `brain_down` and `jev_down`
(`docs/baselines/latency-harness.json`).
