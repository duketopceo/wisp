"""Speak stage: stream the answer, speak it, point at the screen and
close the turn (session tail, recall index, toast, decision log).

Fourth of the four turn stages. Public names are re-exported from
wisp.pipeline; names that tests patch as `pipeline.<name>` are resolved
through `_pl()` at call time.
"""
import json
import re
import time
from datetime import datetime, timezone

from . import config, speech


def _pl():
    """wisp.pipeline, resolved late (patch targets live there)."""
    from . import pipeline
    return pipeline


def ask_chat(transcript: str, cfg: dict, session_text: str = "",
             image_b64: str | None = None, on_delta=None,
             meta: dict | None = None) -> str:
    """Real answer via the configured brain provider ([brain] default).
    image_b64 attaches a screenshot — dropped when the provider lacks
    vision support (U6 capability gating)."""
    from . import brain
    if image_b64 and not brain.supports_vision(cfg):
        image_b64 = None  # provider can't see it — don't attach
    system = ("You are Wisp, a terse desktop voice assistant on Linux. "
              "Answer in one or two short sentences, plain speech, no "
              "markdown.")
    from . import context as _ctx
    focus = _ctx.snapshot(cfg)
    if focus:
        system += f"\n{focus} — resolve pronouns like 'this'/'it' against the focused app."
    if image_b64:
        system += (
            " A screenshot of the user's screen is attached. Describe "
            "what is relevant to the question. When the user asks where "
            "something is or where to click, point at it: append one or "
            "more tags like [POINT:x,y:label] using the screenshot's "
            "pixel coordinates, or for a multi-step sequence "
            "[POINTS:[{\"x\":x,\"y\":y,\"label\":\"step\"}]]. Keep the "
            "spoken text free of the tags; they render as an overlay.")
    user_content = transcript
    if image_b64:
        user_content = [
            {"type": "text", "text": transcript},
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
        ]
    messages = [{"role": "system", "content": system}]
    from . import memory
    block = memory.context_block()
    if block:
        messages.append({"role": "system", "content": block})
    if session_text:
        messages.append({"role": "system",
                         "content": f"Recent conversation:\n{session_text}"})
    messages.append({"role": "user", "content": user_content})
    if on_delta is not None:
        out = brain.chat_stream(messages, cfg, on_delta=on_delta,
                                timeout=30)
    else:
        out = brain.chat(messages, cfg, timeout=30)
    if meta is not None:
        meta.update(provider=out.get("provider"),
                    fallback_from=out.get("fallback_from"))
    return out["content"].strip()


def _publish_delta(state, partial: str) -> None:
    """Streamed answer text → state, coalesced by the bus when there is
    one; plain handles (tests, standalone State) just transition."""
    from . import state as _state
    if isinstance(state, _state.TurnState):
        state._bus.publish(state.turn_id, status="speaking",
                           answer=partial, coalesce=True)
    else:
        state.transition("speaking", answer=partial)


def _end_speaking(state):
    """Flip speaking → done when TTS exits (only if nothing moved on)."""
    def cb():
        if state.status == "speaking":
            state.transition("done")
    return cb


def answer_text(transcript: str) -> str:
    """Canned reply for the answer route — Jev returns no free text."""
    low = transcript.lower()
    if "what can" in low or "help" in low or "commands" in low:
        return ('Try "open discord", "screenshot", "go to workspace 2", '
                'or "agent, research X" — I route to apps, tools, and agents.')
    return f'You said: "{transcript}". Not a desktop action I can take yet.'


def log_decision(record_dict: dict, log_file=config.DECISIONS) -> None:
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a") as f:
            f.write(json.dumps(record_dict) + "\n")
    except Exception:
        pass


def speak_stage(ctx) -> int:
    """Turn the result into speech, then close the turn. Returns the
    turn's exit code (0)."""
    result = ctx.result
    if result.startswith("ASK_USER "):
        return _ask_user(ctx)
    if result == "ANSWERED":
        _answer(ctx)
    else:
        ctx.state.transition("done", result=result)
    return _finish(ctx)


def _ask_user(ctx) -> int:
    """Spoken backchannel — ask aloud, keep the goal open; the next
    utterance resumes it (goal ttl covers the pause)."""
    from . import trace as _trace
    from . import session
    pl, state, cfg, sp = _pl(), ctx.state, ctx.cfg, ctx.sp
    result, text = ctx.result, ctx.text
    q = result[9:].strip()
    _trace.emit(ctx.turn, "ask_user", "speak", {"question": q})
    state.transition("speaking", result=result, answer=q)
    proc = speech.speak(q, cfg)
    if proc is not None:
        speech.on_exit(proc, pl._end_speaking(state))
    else:
        state.transition("done", result=result)
    session.append_turn(text, route="act", reply=q, result=result)
    pl.notify(result, "success", spoken=True,
              **pl._toast_ctx(state, ctx.turn, cfg))
    sp.record("done", sp.rel0)
    pl.log_decision({"ts": datetime.now(timezone.utc).isoformat(),
                     "turn": ctx.turn,
                     "transcript": text, "answers": ctx.answers,
                     "result": result,
                     "timing_ms": sp.legacy_timing(),
                     "corrected": False})
    return 0


def _answer(ctx) -> None:
    """Answer route: stream the brain's reply into state while speaking
    each finished sentence, then speak the tail. Sets ctx.reply."""
    from . import trace as _trace
    pl, state, cfg, sp, token = _pl(), ctx.state, ctx.cfg, ctx.sp, ctx.token
    text, result, turn = ctx.text, ctx.result, ctx.turn
    pts = []
    ctx.speaker = speaker = speech.SentenceSpeaker(cfg, token=token)

    def _delta(acc):
        # stream the answer into state.json as it arrives — the
        # cursor bubble renders it live. Rate-limited by the
        # bus (coalesced, latest wins); incomplete
        # trailing [POINT…/markdown-ish brackets hidden so the
        # bubble never flashes raw tags.
        sp.fire("first_token")
        if token.cancelled:
            return  # a cancelled turn publishes no more deltas
        partial = re.sub(r"\[[A-Za-z]*:?[^\]]*$", "", acc)
        pl._publish_delta(state, partial)
        # speak each completed sentence while the rest streams
        from . import points as _pts
        speaker.feed(_pts.extract(partial)[0])

    try:
        _t = time.monotonic()
        _meta: dict = {}
        reply = pl.ask_chat(text, cfg, ctx.session_text,
                            image_b64=ctx.shot_b64,
                            on_delta=_delta, meta=_meta)
        sp.fire("first_token")  # non-streaming brains
        _trace.emit(turn, "brain_call", "brain",
                    {"endpoint": "chat/completions",
                     "model": cfg.get("agent", {})
                     .get("answer_model", ""),
                     "provider": _meta.get("provider"),
                     "fallback_from": _meta.get("fallback_from"),
                     "reply": reply},
                    round((time.monotonic() - _t) * 1000))
    except Exception as e:
        # every brain entry failed (brain_down), or a timeout /
        # bug: the turn ends in a typed error rather than a
        # canned answer the user would mistake for a real one
        from . import errors_codes as _errors
        raise _errors.classify(e, "brain_down") from e
    ctx.reply = reply
    if reply:
        from . import points as _points
        reply, raw = _points.extract(reply)
        ctx.reply = reply
        if raw:
            _mons = _points.monitors()
            if _points.img_space_is_logical():
                pts = _points.canvas_to_logical(raw, _mons)
            else:
                pts = _points.to_logical(raw, _mons)
    if pts:
        _trace.emit(turn, "points", "act", {"points": pts})
    token.check()
    state.transition("speaking", result=result, answer=reply, points=pts)
    _t = time.monotonic()
    tts_start = sp.now()
    if speaker.started:
        # sentences already went out as they completed; queue
        # the unspoken tail and flip to done when the last ends
        speaker.finish(reply, on_done=pl._end_speaking(state))
        proc = True
    else:
        proc = speech.speak(reply, cfg)
        if proc is not None:
            speech.on_exit(proc, pl._end_speaking(state))
    sp.record("tts_start", tts_start)
    _trace.emit(turn, "speak", "tts",
                {"cmd": cfg.get("voice", {}).get("cmd", ""),
                 "spawned": proc is not None,
                 "streamed": speaker.started},
                round((time.monotonic() - _t) * 1000))
    if proc is None:
        state.transition("done")


def _finish(ctx) -> int:
    """Close a finished turn: session tail, recall (off the hot path),
    toast and the decision log line."""
    from . import session
    from . import recall as _recall
    from . import bgwriter
    pl, state, cfg, sp = _pl(), ctx.state, ctx.cfg, ctx.sp
    text, reply, result, answers = ctx.text, ctx.reply, ctx.result, ctx.answers
    session.append_turn(text, route=answers.get("route", {})
                        .get("choice", ""), reply=reply, result=result)
    bgwriter.submit(_recall.index_turn, text, reply, result)
    pl.notify(result, "success", spoken=True,
              **pl._toast_ctx(state, ctx.turn, cfg))
    sp.record("done", sp.rel0)
    pl.log_decision({"ts": datetime.now(timezone.utc).isoformat(),
                     "turn": ctx.turn,
                     "transcript": text, "answers": answers,
                     "result": result,
                     "timing_ms": sp.legacy_timing(),
                     "corrected": bool(answers.get("corrected_by_user"))})
    return 0
