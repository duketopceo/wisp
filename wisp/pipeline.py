"""Voice pipeline: record -> transcribe -> Jev -> route -> act.

Runs inside the daemon on a worker thread; every stage transitions State
so widgets see listening/deciding/awaiting_choice/done in real time.

The turn is four stages around the StateBus (W30), one module each:

    stage_capture   mic, transcribe, screen and window context
    stage_route     Jev / heuristic router, rescues, clarify prompt
    stage_execute   dispatch to tools, the act loop, agents, dictation
    stage_speak     stream + speak the answer, close the turn

This module keeps the orchestrator (run_listen, _listen_turn: cancel,
error and cleanup paths) and re-exports every public name the stages
define, so `pipeline.<name>` still resolves for callers and tests. The
stages look patchable names up through this module at call time, so
`mock.patch.object(pipeline, "ask_jev")` and friends keep working.
"""
import base64  # noqa: F401  (patch targets: pipeline.<module>)
import json  # noqa: F401
import os  # noqa: F401
import pathlib
import re  # noqa: F401
import shutil  # noqa: F401
import signal  # noqa: F401
import subprocess
import sys
import threading
import time  # noqa: F401
import urllib.error  # noqa: F401
import urllib.request  # noqa: F401
from datetime import datetime, timezone  # noqa: F401

from . import cancel as _cancel
from . import copy as _copy
from . import config, speech  # noqa: F401
from . import errors_codes as _errors
from .stage_capture import (  # noqa: F401
    _LEVEL_WINDOW, _SAMPLER_JOIN_S, _SPEC_WAIT_S, _amplitude_sampler,
    _cap_prompt, _png_b64, _record_finish, _transcribe_openai,
    active_window, capture_screen, context_stage, capture_stage,
    hypr_env, record, record_start, record_stop, screen_b64,
    speculative_context, transcribe, turn_screenshot)
from .stage_ctx import TurnCtx
from .stage_execute import (  # noqa: F401
    _DICTATE_PREFIX, dictation_text, execute, execute_stage)
from .stage_route import (  # noqa: F401
    JEV_QUESTIONS, _BENIGN_ACTIONS, _COMPLEX_LAUNCH, _LAUNCH_VERBS,
    _OPEN_VERB, _ask_prompt, _jev_is_local, _shadow_agree,
    _shadow_decision, _shadow_worker, ambiguous_choices, apply_choice,
    ask_jev, auto_pick, build_questions, complex_launch, fuzzy_app,
    is_low_confidence, route_stage)
from .stage_speak import (  # noqa: F401
    _end_speaking, _publish_delta, answer_text, ask_chat, log_decision,
    speak_stage)


def notify(msg: str, level: str = "info", **kw) -> None:
    """Toast via wisp.notify (replace-id per turn, dedupe, quiet hours,
    never blocks). kw: cfg, turn, code, key, actions, spoken, stale."""
    from . import notify as _notify
    try:
        _notify.send(msg, level=level, **kw)
    except Exception:
        pass


def _toast_ctx(state, turn, cfg) -> dict:
    """Common notify kwargs: this turn's id (replace-id) and whether a
    newer turn has begun (stale turns never toast)."""
    stale = False
    try:
        bus = getattr(state, "_bus", None)
        stale = bool(bus and turn and bus.current_turn() != turn)
    except Exception:
        pass
    return {"cfg": cfg, "turn": turn, "stale": stale}


def _open_log_action():
    def _open():
        from . import config
        subprocess.Popen(["xdg-open", str(config.DECISIONS)],
                         env=hypr_env(), stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    # TODO(W17): label from wisp/copy.py
    return ("open_log", "Open log", _open)


def _publish_error(state, exc: BaseException) -> None:
    """End a turn in `error` with a closed-set code: `error` is the
    human-safe string, `error_detail` the raw text (local only)."""
    from . import errors_codes as _ec
    err = _ec.classify(exc, "internal")
    state.transition("error", error=err.public, error_code=err.code,
                     error_detail=err.detail[:500])
    from . import report as _report
    _report.capture(err.code, exc)


def run_listen(cfg: dict, state, wait_for_choice=None,
               wav: pathlib.Path | None = None,
               interrupted=None, spans=None, turn_id=None,
               cancel=None, speculative=None) -> int:
    """One push-to-talk cycle inside the daemon.

    `cancel` is the turn's CancelToken (U9; the daemon's `interrupt`
    sets it). With only `interrupted` (a callable), a watcher bridges it
    to a token within ~20 ms. Either way a cancelled turn closes its
    sockets, kills its children and ends `idle` with
    `error_code = cancelled`.

    `wav` set → toggle mode: the daemon already captured audio between
    two presses, so skip recording. `wait_for_choice(timeout)` -> picked
    label or None; injected by the daemon so ambiguous turns resolve via
    IPC/widget clicks. With no chooser wired, low-confidence turns cancel
    rather than guess. `spans` (trace.Spans) carries the press/release
    timestamps from the daemon; absent, spans start at this call.
    `state` may be a StateBus: the turn is then `turn_id` (adopted from
    the daemon's first press) or a fresh one, and every write goes
    through the bus tagged with it. `speculative` (context.Speculative,
    started at press) supplies the screenshot and window map; the turn
    discards whatever it did not consume when it ends.
    """
    from . import bgwriter
    bgwriter.configure(cfg)
    token = cancel or _cancel.CancelToken()
    stop_watch = threading.Event()
    if interrupted is not None and cancel is None:
        def watch():
            while not stop_watch.is_set():
                if interrupted():
                    token.cancel()
                    return
                stop_watch.wait(0.02)
        threading.Thread(target=watch, daemon=True).start()
    try:
        with _cancel.bind(token):
            return _listen_turn(cfg, state, wait_for_choice, wav,
                                interrupted, spans, turn_id, token,
                                speculative)
    finally:
        stop_watch.set()
        if speculative is not None:
            speculative.cancel()


def _listen_turn(cfg, state, wait_for_choice, wav, interrupted, spans,
                 turn_id, token, speculative=None) -> int:
    secs = int(cfg.get("audio", {}).get("seconds", "60"))
    model = cfg.get("agent", {}).get("model", "typesafe/jev-1.13")
    from . import trace as _trace
    sp = spans or _trace.Spans()
    from . import state as _state
    if isinstance(state, _state.StateBus):
        turn = turn_id or state.begin_turn()
        _trace.set_turn(turn)
        state = state.turn(turn)
    else:
        turn = _trace.new_turn()
    sp.bind(turn)
    ctx = TurnCtx(cfg, state, wait_for_choice, wav, interrupted, sp, turn,
                  token, speculative, secs, model)
    _trace.emit(turn, "listen_start", "lifecycle",
                {"seconds": secs, "model": model})
    try:
        token.check()
        if not capture_stage(ctx):
            return 0
        context_stage(ctx)
        if not route_stage(ctx):
            return 0
        execute_stage(ctx)
        return speak_stage(ctx)
    except _cancel.Cancelled:
        # stop works at every stage: sockets are closed and children
        # killed by the token; kill any speech and settle on idle
        if ctx.speaker is not None:
            ctx.speaker.stop()
        speech.stop()
        _trace.emit(turn, "cancelled", "lifecycle", {"result": ctx.result})
        fields = {"error": "", "error_code": "cancelled",
                  "error_detail": "", "choices": [], "prompt_id": "",
                  "confirm": None}
        if ctx.result:
            fields["result"] = ctx.result
        state.transition("idle", **fields)
        log_decision({"ts": datetime.now(timezone.utc).isoformat(),
                      "result": "CANCELLED (user)",
                      "timing_ms": sp.legacy_timing()})
        return 0
    except Exception as e:
        if ctx.speaker is not None:
            ctx.speaker.stop()
        err = _errors.classify(e, "internal")
        _trace.emit(turn, "error", "error",
                    {"error": str(e), "error_code": err.code})
        _publish_error(state, err)
        log_decision({"ts": datetime.now(timezone.utc).isoformat(),
                      "result": f"ERROR ({e})",
                      "timing_ms": sp.legacy_timing()})
        notify(_copy.toast_text(err.code), "error", code=err.code,
               actions=[_open_log_action()],
               **_toast_ctx(state, turn, cfg))
        print(f"error: {err.code}: {e}", file=sys.stderr)
        return 1
    finally:
        sp.close()
        state.set_level(0.0)
