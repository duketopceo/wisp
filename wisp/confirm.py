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

`make_ask()` builds the matching `ask(question, options) -> pick|None`
for the act loop's `ask_user` tool (U4): `kind="question"` in the
stream and on the card, free-form picks accepted when the model
offered no options.
"""
import time

from . import cancel as _cancel
from . import state as _state

DEFAULT_TIMEOUT = 120
MIN_TIMEOUT = 5
MAX_TIMEOUT = 600
YES = "yes"
NO = "no"
ALWAYS = "always"
CANCEL = "cancel"
TIMEOUT = "timeout"
_UNSET = object()


def yes_option(prompt: str) -> str:
    return f"{prompt} — yes"


def done_option(prompt: str) -> str:
    return f"{prompt} — done"


def park_prompt(state, wait_for_choice, token, kind: str, label: str,
                options, secs: float, confirm_blob=None,
                clear_confirm: bool = True) -> tuple:
    """The shared prompt-card lifecycle: publish the awaiting stream
    entry + `awaiting_choice` (and `confirm`, when confirm_blob is
    given), park on the broker, then restore `acting` unless the turn
    was cancelled (the turn unwinds to idle itself).

    Returns (aid, pid, pick). pick is _UNSET when the waiter died
    without an answer — the awaiting row is resolved 'error' on the
    way out so no dead card is left parked. Pick resolution and
    terminal statuses stay with the caller — confirm maps yes/no/
    always, ask returns text, clarify rejects off-menu picks."""
    pid = _cancel.new_prompt_id()
    opts = list(options) if options else None
    aid = _state.action_add(state, kind, label, status="awaiting",
                            options=opts, prompt_id=pid)
    fields = {"choices": list(opts or []), "prompt_id": pid}
    if confirm_blob is not None:
        confirm_blob["prompt_id"] = pid
        fields["confirm"] = confirm_blob
    state.transition("awaiting_choice", **fields)
    pick = _UNSET
    try:
        pick = wait_for_choice(secs, prompt_id=pid, options=opts)
    finally:
        if not token.cancelled:
            clear = {"choices": [], "prompt_id": ""}
            if clear_confirm:
                clear["confirm"] = None
            state.transition("acting", **clear)
            if pick is _UNSET:
                _state.action_set(state, aid, status="cancelled",
                                  reason="error")
    return aid, pid, pick


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
        if kind == "handoff":
            options = [done_option(prompt), CANCEL]
        else:
            options = [yes_option(prompt)]
            if always:
                options.append(ALWAYS)
            options.append(NO)
        start = clock()
        aid, pid, pick = park_prompt(
            state, wait_for_choice, token, kind, prompt, options, secs,
            confirm_blob={"prompt": prompt, "timeout_s": secs,
                          "kind": kind})
        if token.cancelled:
            _state.action_set(state, aid, status="cancelled",
                              reason="interrupted")
            token.check()
        if pick == options[0]:
            confirm.last = YES
            _state.action_set(state, aid, status="done")
        elif always and pick == ALWAYS:
            confirm.last = ALWAYS
            _state.action_set(state, aid, status="done",
                              reason=ALWAYS)
        elif not pick and clock() - start >= secs:
            confirm.last = TIMEOUT
            _state.action_set(state, aid, status="cancelled",
                              reason=TIMEOUT)
            _trace.emit(turn, "confirm_timeout", "act",
                        {"prompt_id": pid, "timeout_s": secs})
        else:
            confirm.last = NO
            _state.action_set(state, aid, status="cancelled",
                              reason="denied")
        return confirm.last in (YES, ALWAYS)

    confirm.last = ""
    confirm.rich = True   # policy.ask may pass kind=/always=
    return confirm


def make_ask(state, wait_for_choice, token, turn, cfg,
             clock=time.monotonic):
    """Build `ask(question, options=None) -> pick|None` for the act
    loop's `ask_user` tool (U4): the conversational card a running
    agent raises mid-loop instead of ending the turn.

    Same broker channel as confirm, inverted shape: the prompt IS the
    payload, so the stream entry is `kind="question"` with `options`
    only when the model offered picks. With no options the broker
    accepts any pick string — a typed `wispd choice "the answer"` or a
    spoken free-form reply resolves it; with options the usual
    click/index/voice-map rules apply. The question is spoken too —
    a voice loop that asks silently isn't a conversation.

    Returns the picked/typed answer text, or None on
    timeout/dismiss/cancel (the caller turns that into a NO_ANSWER
    tool result). A cancelled turn raises `cancel.Cancelled`, like the
    confirm card.
    """
    secs = timeout_s(cfg)

    def ask(question: str, options: list | None = None) -> str | None:
        from . import trace as _trace
        opts = [str(o)[:80] for o in (options or []) if str(o).strip()][:6]
        try:
            from . import speech
            speech.speak(question, cfg)   # gated by voice.enabled
        except Exception:
            pass
        start = clock()
        aid, pid, pick = park_prompt(
            state, wait_for_choice, token, "question", question,
            opts or None, secs,
            confirm_blob={"prompt": question, "timeout_s": secs,
                          "kind": "question"})
        if token.cancelled:
            _state.action_set(state, aid, status="cancelled",
                              reason="interrupted")
            token.check()
        if pick:
            _state.action_set(state, aid, status="done",
                              reason=str(pick)[:120])
            return str(pick)
        if clock() - start >= secs:
            _trace.emit(turn, "ask_timeout", "act",
                        {"prompt_id": pid, "timeout_s": secs})
        _state.action_set(state, aid, status="cancelled",
                          reason=TIMEOUT)
        return None

    ask.rich = True
    return ask
