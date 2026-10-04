"""Confirm card backend (W25, Ember U15).

A risky tool step asks the user before it runs. The ask rides the same
prompt-id channel as every other prompt (#66, `cancel.PromptBroker`):

  - `state.confirm = {prompt_id, prompt, timeout_s}` is published next to
    `choices` (`["<prompt> — yes", "no"]`) and `prompt_id`, status
    `awaiting_choice`; shells draw the card from `confirm`;
  - a reply with another prompt id, or after the confirm ended, is refused
    by the broker (`stale_prompt`) and the confirm keeps waiting;
  - no reply inside `[agent] confirm_timeout` seconds (default 120, clamped
    5 to 600) resolves as deny. The deadline is the waiter's own, on the
    broker's clock, so it is daemon-side: no shell timer, no polling;
  - the card is cleared and the turn returns to `acting` however the
    confirm ended, except on stop (the turn unwinds to idle itself).

`make()` returns the `confirm(prompt) -> bool` the act loop calls. The
function carries `.last` (`yes`, `no`, `timeout`) so the act gate can say
why a deny happened.
"""
import time

from . import cancel as _cancel

DEFAULT_TIMEOUT = 120
MIN_TIMEOUT = 5
MAX_TIMEOUT = 600
NO = "no"


def yes_option(prompt: str) -> str:
    return f"{prompt} — yes"


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

    def confirm(prompt: str) -> bool:
        from . import trace as _trace
        pid = _cancel.new_prompt_id()
        options = [yes_option(prompt), NO]
        state.transition("awaiting_choice", choices=list(options),
                         prompt_id=pid,
                         confirm={"prompt_id": pid, "prompt": prompt,
                                  "timeout_s": secs})
        start = clock()
        try:
            pick = wait_for_choice(secs, prompt_id=pid,
                                   options=list(options))
        finally:
            if not token.cancelled:
                state.transition("acting", choices=[], prompt_id="",
                                 confirm=None)
        token.check()
        if pick == options[0]:
            confirm.last = "yes"
        elif not pick and clock() - start >= secs:
            confirm.last = "timeout"
            _trace.emit(turn, "confirm_timeout", "act",
                        {"prompt_id": pid, "timeout_s": secs})
        else:
            confirm.last = "no"
        return confirm.last == "yes"

    confirm.last = ""
    return confirm
