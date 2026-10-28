"""Speak stage: stream the answer, speak it, point at the screen and
close the turn (session tail, recall index, toast, decision log).

Fourth of the four turn stages. Public names are re-exported from
wisp.pipeline; names that tests patch as `pipeline.<name>` are resolved
through `_pl()` at call time.
"""
import json
import re
import threading
import time
from datetime import datetime, timezone

from . import config, speech


def _pl():
    """wisp.pipeline, resolved late (patch targets live there)."""
    from . import pipeline
    return pipeline


def ask_chat(transcript: str, cfg: dict, session_text: str = "",
             image_b64: str | None = None, on_delta=None,
             meta: dict | None = None, doc_text: str = "",
             scribble_hint: str = "", tutor_text: str = "") -> str:
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
            "something is or where to click, point at it with one or "
            "more tags like [POINT:x,y:label] using the screenshot's "
            "pixel coordinates. Put each tag inside the sentence that "
            "talks about it, right after the words it points at and "
            "before the sentence's final punctuation, e.g. \"Click Save "
            "[POINT:812,40:Save] to keep it.\". For a multi-step "
            "sequence, give each step its own sentence and tag, or end "
            "with [POINTS:[{\"x\":x,\"y\":y,\"label\":\"step\"}]]. "
            "To draw on the screen you may also use [RING:x,y,r] (a "
            "ring: center and radius), [ARROW:x1,y1,x2,y2] (an arrow "
            "from one spot to another) or [HL:x,y,w,h] (a highlight "
            "box: top-left corner, width and height), all in screenshot "
            "pixels, placed inside the sentence they illustrate like a "
            "point tag, at most three per answer. "
            "The tags render as an overlay and are never spoken.")
        if scribble_hint:
            system += " " + scribble_hint
    user_content = transcript
    if image_b64:
        user_content = [
            {"type": "text", "text": transcript},
            {"type": "image_url",
             "image_url": {"url": image_b64
                           if image_b64.startswith("data:")
                           else f"data:image/png;base64,{image_b64}"}},
        ]
    messages = [{"role": "system", "content": system}]
    from . import memory
    block = memory.context_block()
    if block:
        messages.append({"role": "system", "content": block})
    if session_text:
        messages.append({"role": "system",
                         "content": f"Recent conversation:\n{session_text}"})
    if doc_text:
        messages.append({"role": "system", "content": doc_text})
    if tutor_text:
        messages.append({"role": "system", "content": tutor_text})
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
    """Flip speaking → done when TTS exits (only if nothing moved on).

    Capture bus/turn at arm time: if a newer turn owns the bus by the
    time TTS exits, skip close+done so we don't clear its paper.
    """
    bus = getattr(state, "_bus", None)
    turn = getattr(state, "turn_id", None)

    def cb():
        if bus is not None and turn is not None \
                and hasattr(bus, "current_turn") \
                and bus.current_turn() != turn:
            return
        if state.status == "speaking":
            _close_paper(state, bus=bus, turn=turn)
            state.transition("done")
    return cb


def _close_paper(state, *, bus=None, turn=None) -> None:
    """Drop the live plan strip when the turn finishes (U2).

    Paper is an output surface — I/O / bus failures must not fail the
    speak path. Unexpected bugs still propagate. Sync failures from the
    note writer also land here as OSError (no durable success claimed).
    """
    try:
        from . import note as _note
        bus = bus if bus is not None else (getattr(state, "_bus", None)
                                           or state)
        if turn is None:
            turn = getattr(state, "turn_id", None)
        if turn is None and hasattr(bus, "current_turn"):
            turn = bus.current_turn()
        if bus is not None and turn is not None \
                and hasattr(bus, "current_turn") \
                and bus.current_turn() != turn:
            return
        _note.close_live(bus, turn_id=turn, state=state)
    except (ImportError, OSError, TypeError, AttributeError, ValueError,
            KeyError):
        pass


def _publish_paper(state, text: str, turn: str | None = None) -> dict | None:
    """If `text` carries paper markup, rewrite note.md + state.note.

    Uses a conversation-stable note id (not the turn id) so `wispd note`
    keeps resolving the same file across turns. Same failure policy as
    `_close_paper`: surface I/O / sync errors cannot take down the turn.
    """
    try:
        from . import note as _note
        if not _note.looks_like_paper(text):
            return None
        bus = getattr(state, "_bus", None) or state
        tid = turn
        if tid is None and hasattr(bus, "current_turn"):
            tid = bus.current_turn()
        return _note.publish_from_text(text, bus=bus, turn_id=tid,
                                       state=state)
    except (ImportError, OSError, TypeError, AttributeError, ValueError,
            KeyError):
        return None


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
        payload = _spoken_payload(result)
        if payload:
            _speak_result(ctx, payload)
        else:
            _close_paper(ctx.state)
            ctx.state.transition("done", result=result)
    return _finish(ctx)


def _spoken_payload(result: str) -> str:
    """User-facing text inside a terminal act result: the model's final
    reply for ACTED; empty for INTERRUPTED/other prefixes (already
    announced by the interrupt itself, or machine-only status)."""
    m = re.match(r"^(?:ACTED|WALKED)(?:\s*\([^)]*\))?\s*:\s*(.*)$",
                 result, re.DOTALL)
    return m.group(1).strip() if m else ""


def _speak_result(ctx, payload: str) -> None:
    """Speak a finished act result like an answer — strip point tags
    into annotations, publish `speaking`, TTS the payload."""
    from . import points as _points
    from . import trace as _trace
    pl, state, cfg, sp = _pl(), ctx.state, ctx.cfg, ctx.sp
    reply, raw = _points.extract(payload)  # drawing tags stripped, none drawn
    ctx.reply = reply
    pts = []
    if raw:
        _mons = _points.monitors()
        if _points.img_space_is_logical():
            pts = _points.canvas_to_logical(raw, _mons)
        else:
            pts = _points.to_logical(raw, _mons)
        _trace.emit(ctx.turn, "points", "act", {"points": pts})
    _publish_paper(state, _points.extract(payload)[0], ctx.turn)
    state.transition("speaking", result=ctx.result,
                     answer=reply, points=pts)
    tts_start = sp.now()
    proc = speech.speak(reply, cfg)
    if proc is not None:
        speech.on_exit(proc, pl._end_speaking(state))
    else:
        _close_paper(state)
        state.transition("done", result=ctx.result)
    sp.record("tts_start", tts_start)


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
    session.append_turn(text, route="act", reply=q, result=result,
                        app=ctx.app)
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


def _publish_points(state, pts: list, drawings: list) -> None:
    """Points+drawings publish (no status, one bus.publish so a ring
    never shows a frame before its beacon), turn-scoped like
    `_publish_delta`; plain handles (tests, standalone State) just
    transition."""
    from . import state as _state
    if isinstance(state, _state.TurnState):
        state._bus.publish(state.turn_id, points=list(pts),
                           drawings=list(drawings))
    else:
        state.transition("speaking", points=list(pts),
                         drawings=list(drawings))


def _answer(ctx) -> None:
    """Answer route: stream the brain's reply into state while speaking
    each finished sentence, then speak the tail. With voice on, each
    point is published when the sentence holding its tag starts playing;
    with voice off they all land with the `speaking` transition. Sets
    ctx.reply."""
    from . import points as _points
    from . import trace as _trace
    pl, state, cfg, sp, token = _pl(), ctx.state, ctx.cfg, ctx.sp, ctx.token
    text, result, turn = ctx.text, ctx.result, ctx.turn
    pts = []        # logical points fired so far (voice on)
    drws = []       # logical drawings fired so far (voice on)
    plock = threading.Lock()  # one lock over append + publish: no reordering
    _mons: list = []          # one monitors() lookup per turn
    _shot: list = []          # the press-time screenshot, decoded once

    def _tones(d_px):
        """Light or dark under each drawing, from the shot the model saw
        (marks are in its pixels); [] when there is no shot."""
        from . import ink as _ink
        if not _shot:
            _shot.append(_ink.open_image(getattr(ctx, "shot_b64", None)))
        return _ink.tones_for(_shot[0], d_px) if _shot[0] is not None \
            else []

    def _logical(raw):
        if not _mons:
            _mons.append(_points.monitors())
        conv = _points.canvas_to_logical \
            if _points.img_space_is_logical() else _points.to_logical
        return conv(raw, _mons[0])

    def _split(marks_px):
        """Fired marks -> (logical points, logical drawings)."""
        if not marks_px:
            return [], []
        if not _mons:
            _mons.append(_points.monitors())
        p_px = [m for m in marks_px if "kind" not in m]
        d_px = [m for m in marks_px if "kind" in m]
        d_log = (_points.drawings_to_logical(
            d_px, _mons[0], _points.img_space_is_logical())
            if d_px else [])
        tones = _tones(d_px) if d_px else []
        if len(tones) == len(d_log):          # same marks, same order
            for d, t in zip(d_log, tones):
                if t:
                    d["tone"] = t
        return (_logical(p_px) if p_px else [], d_log)

    def _fire(raw):
        # a sentence just started playing: grow the list, publish only
        # if this turn is still the live, speaking one
        with plock:
            p, d = _split(raw)
            ms = int(getattr(speaker, "sentence_ms", 0) or 0)
            if ms > 0:        # the pen's pace: this sentence's spoken time
                for one in d:
                    one["ms"] = ms
            pts.extend(p)
            drws.extend(d)
            bus = getattr(state, "_bus", None)
            if token.cancelled or (
                    bus is not None and hasattr(bus, "current_turn")
                    and bus.current_turn() != getattr(state, "turn_id",
                                                      None)) \
                    or state.status != "speaking":
                return
            _publish_points(state, pts, drws)

    ctx.speaker = speaker = speech.SentenceSpeaker(cfg, token=token,
                                                   on_sentence=_fire)

    def _delta(acc):
        # stream the answer into state.json as it arrives — the
        # cursor bubble renders it live. Rate-limited by the
        # bus (coalesced, latest wins); tags are stripped (and any
        # still-open one hidden) so the bubble never flashes them.
        sp.fire("first_token")
        if token.cancelled:
            return  # a cancelled turn publishes no more deltas
        from . import note as _note
        clean, marks = _points.extract_marked(_note.strip_image_lines(
            _points.strip_partial(acc), partial=True))
        pl._publish_delta(state, clean)
        # speak each completed sentence while the rest streams
        speaker.feed(clean, marks)

    try:
        _t = time.monotonic()
        _meta: dict = {}
        _extra = ({"doc_text": ctx.doc_text}
                  if getattr(ctx, "doc_text", "") else {})
        if getattr(ctx, "tutor_text", ""):
            _extra["tutor_text"] = ctx.tutor_text
        if getattr(ctx, "scribble_hint", ""):
            _extra["scribble_hint"] = ctx.scribble_hint
        reply = pl.ask_chat(text, cfg, ctx.session_text,
                            image_b64=ctx.shot_b64,
                            on_delta=_delta, meta=_meta, **_extra)
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
    # paper before point extraction so `::` / plan markers land in
    # note.md even when the spoken reply is the letter body only
    # (tags stripped first so a stored note never holds one)
    paper = _publish_paper(state, _points.extract(reply)[0] if reply
                           else reply, turn)
    if reply:
        # `::image[...]` lines are for the card, not the voice or bubble;
        # a refused picture is explained aloud instead
        from . import note as _note
        reply = _note.strip_image_lines(reply)
        why = _note.refusals(paper)
        if why:
            reply = (reply + " " + " ".join(why)).strip()
    ctx.reply = reply
    marks = []
    all_pts = []
    all_drws = []
    if reply:
        reply, marks = _points.extract_marked(reply)
        ctx.reply = reply
        if marks:
            with plock:
                all_pts, all_drws = _split([p for _, p in marks])
    if all_pts or all_drws:
        _trace.emit(turn, "points", "act",
                    {"points": all_pts, "drawings": all_drws})
    token.check()
    _t = time.monotonic()
    tts_start = sp.now()
    if speaker.enabled:
        # voice on: every sentence (a single-chunk reply included) goes
        # through the speaker so its points fire as it starts playing;
        # the transition publishes what has fired so far
        with plock:
            state.transition("speaking", result=result, answer=reply,
                             points=list(pts), drawings=list(drws))
        speaker.finish(reply, on_done=pl._end_speaking(state), marks=marks)
        proc = True
    else:
        state.transition("speaking", result=result, answer=reply,
                         points=all_pts, drawings=all_drws)
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
        _close_paper(state)
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
                        .get("choice", ""), reply=reply, result=result,
                        app=ctx.app)
    bgwriter.submit(_recall.index_turn, text, reply, result)
    pl.notify(result, "success", spoken=True,
              **pl._toast_ctx(state, ctx.turn, cfg))
    sp.record("done", sp.rel0)
    rec = {"ts": datetime.now(timezone.utc).isoformat(),
           "turn": ctx.turn,
           "transcript": text, "answers": answers,
           "result": result,
           "timing_ms": sp.legacy_timing(),
           "corrected": bool(answers.get("corrected_by_user"))}
    lane = getattr(ctx, "route_lane", None)
    if lane:
        rec["route_lane"] = lane
    pl.log_decision(rec)
    return 0
