"""Confirm card backend (W25, Ember U15).

A risky tool step asks the user before it runs. The ask rides the same
prompt-id channel as every other prompt (#66, `cancel.PromptBroker`):

  - `state.confirm = {prompt_id, prompt, timeout_s, kind}` is published
    next to `choices` and `prompt_id`, status `awaiting_choice`; shells
    draw the card from `confirm`;
  - contract v2 (U2): the card is also an `awaiting` entry in
    `state.actions` (`kind=confirm`, carrying `options` + `prompt_id`) —
    v2 readers demote the card from the stream and transition the same
    entry on the answer. `kind=handoff` entries (U3, T3 steps) stay in
    the stream: the "needs you" row for a step the user took over;
  - a reply with another prompt id, or after the confirm ended, is refused
    by the broker (`stale_prompt`) and the confirm keeps waiting;
  - no reply inside `[agent] confirm_timeout` seconds (default 120, clamped
    5 to 600) resolves as deny. The deadline is the waiter's own, on the
    broker's clock, so it is daemon-side: no shell timer, no polling;
  - the card is cleared and the turn returns to `acting` however the
    confirm ended, except on stop (the turn unwinds to idle itself).

`make()` returns the `confirm(prompt, kind=, always=) -> bool` the act
loop calls — `.rich` marks it so policy can pass the kwargs (plain
doubles take just the prompt). `kind="handoff"` swaps the options for
done/cancel — the user does the step, wisp never runs it. `always=True`
inserts an "always" middle option: picking it grants the session the
("*", "*") key in `state.confirmed` (the same confirm-once set a
per-(tool, app) yes writes). The function carries `.last` (`yes`,
`always`, `no`, `timeout`) so the gate can say why a deny happened.
"""
import time

from . import cancel as _cancel
from . import state as _state

DEFAULT_TIMEOUT = 120
MIN_TIMEOUT = 5
MAX_TIMEOUT = 600
NO = "no"
ALWAYS = "always"
CANCEL = "cancel"
_UNSET = object()


def yes_option(prompt: str) -> str:
    return f"{prompt} — yes"


def done_option(prompt: str) -> str:
    return f"{prompt} — done"


def timeout_s(cfg) -> int:
    raw = (cfg or {}).get("agent", {}).get("confirm_timeout", DEFAULT_TIMEOUT)
    try:
        v = int(float(raw))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT
    return max(MIN_TIMEOUT, min(MAX_TIMEOUT, v))


def make(state, wait_for_choice, token, turn, cfg, clock=time.monotonic):
    """Build the confirm callable for one turn. `wait_for_choice` is the
    broker waiter, `token` the turn's CancelToken."""
    secs = timeout_s(cfg)

    def confirm(prompt: str, kind: str = "confirm",
                always: bool = False) -> bool:
        from . import trace as _trace
        pid = _cancel.new_prompt_id()
        if kind == "handoff":
            options = [done_option(prompt), CANCEL]
        else:
            options = [yes_option(prompt)]
            if always:
                options.append(ALWAYS)
            options.append(NO)
        # the card is a state in the action stream: the awaiting entry
        # goes first so a stream-driven surface never sees a card whose
        # entry doesn't exist yet
        aid = _state.action_add(state, kind, prompt,
                                status="awaiting", options=options,
                                prompt_id=pid)
        state.transition("awaiting_choice", choices=list(options),
                         prompt_id=pid,
                         confirm={"prompt_id": pid, "prompt": prompt,
                                  "timeout_s": secs, "kind": kind})
        start = clock()
        pick = _UNSET
        try:
            pick = wait_for_choice(secs, prompt_id=pid,
                                   options=list(options))
        finally:
            if not token.cancelled:
                state.transition("acting", choices=[], prompt_id="",
                                 confirm=None)
                if pick is _UNSET:
                    # the waiter died without an answer — don't leave a
                    # dead awaiting row parked in the stream
                    _state.action_set(state, aid, status="cancelled",
                                      reason="error")
        if token.cancelled:
            _state.action_set(state, aid, status="cancelled",
                              reason="interrupted")
            token.check()
        if pick == options[0]:
            confirm.last = "yes"
            _state.action_set(state, aid, status="done")
        elif always and pick == ALWAYS:
            confirm.last = "always"
            _state.action_set(state, aid, status="done",
                              reason="always")
        elif not pick and clock() - start >= secs:
            confirm.last = "timeout"
            _state.action_set(state, aid, status="cancelled",
                              reason="timeout")
            _trace.emit(turn, "confirm_timeout", "act",
                        {"prompt_id": pid, "timeout_s": secs})
        else:
            confirm.last = "no"
            _state.action_set(state, aid, status="cancelled",
                              reason="denied")
        return confirm.last in ("yes", "always")

    confirm.last = ""
    confirm.rich = True   # policy._ask may pass kind=/always=
    return confirm
