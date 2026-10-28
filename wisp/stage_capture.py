"""Capture stage: microphone, transcription, screen and window context.

First of the four turn stages (capture, route, execute, speak). Public
names are re-exported from wisp.pipeline; anything a test or another
module patches as `pipeline.<name>` is looked up through `_pl()` at call
time so the patch still takes effect (see docs/PIPELINE_STAGES.md).
"""
import base64
import json
import os
import pathlib
import re
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request

from . import blank as _blank
from . import cancel as _cancel
from . import config
from . import errors_codes as _errors


def _pl():
    """wisp.pipeline, resolved late (patch targets live there)."""
    from . import pipeline
    return pipeline


def hypr_env() -> dict:
    """Session env for spawned tools when run from a (systemd) daemon —
    fills in HIS and the Wayland socket wtype/grim need."""
    env = dict(os.environ)
    uid = os.getuid() if hasattr(os, "getuid") else 1000
    rd = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    if not env.get("HYPRLAND_INSTANCE_SIGNATURE"):
        hypr = pathlib.Path(rd) / "hypr"
        if hypr.is_dir():
            env["HYPRLAND_INSTANCE_SIGNATURE"] = sorted(hypr.iterdir())[0].name
    if not env.get("WAYLAND_DISPLAY"):
        for s in sorted(pathlib.Path(rd).glob("wayland-*")):
            env["WAYLAND_DISPLAY"] = s.name
            break
    return env


def record(seconds: int, state=None) -> pathlib.Path:
    """Bounded capture for standalone `wispd listen` (no daemon to
    toggle-stop). The daemon uses record_start/record_stop instead."""
    rec = _pl().record_start(state)
    try:
        rec["proc"].wait(timeout=seconds)
        return _record_finish(rec, state)
    except subprocess.TimeoutExpired:
        return _pl().record_stop(rec, state)


def record_start(state=None) -> dict:
    """Toggle capture: spawn the recorder unbounded + the level sampler.
    Returns a handle for record_stop()."""
    out = config.CFG_DIR / "utterance.wav"
    config.RUN_DIR.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    from . import platform, voice_polish
    if platform.record_cmd(out, None) is None:
        raise RuntimeError(
            f"no recorder found — {platform.missing_deps_hint()}")
    try:
        device = voice_polish.mic_device(config.load_config())
    except Exception:
        device = ""
    stop_ev = threading.Event()
    sampler = threading.Thread(target=_amplitude_sampler,
                               args=(None, state, stop_ev), daemon=True)
    sampler.start()
    env = _pl().hypr_env()

    def _spawn(argv):
        return subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, env=env)

    # [audio] device gone (unplugged, Bluetooth asleep): record from the
    # system default instead and say so, never hang on a dead mic (B8b)
    proc, failed_over = voice_polish.spawn_recorder(
        lambda d: platform.record_cmd(out, None, d), _spawn, device=device,
        before_retry=lambda: out.unlink(missing_ok=True))
    if failed_over:
        _note_mic_failover(state, device)
    from . import stt_stream
    stt_stream.begin(out, proc)   # streams finished chunks while held
    return {"proc": proc, "out": out, "sampler_stop": stop_ev,
            "sampler": sampler, "t0": time.monotonic()}


def _note_mic_failover(state, device: str) -> None:
    """One toast; the turn goes on with the default mic."""
    from . import voice_polish
    try:
        _pl().notify(voice_polish.HINT_MIC, "info", key="mic-failover",
                     hold=False)
    except Exception:
        pass


def record_stop(rec: dict, state=None) -> pathlib.Path:
    """SIGINT the recorder (finalizes the WAV header), then validate."""
    proc = rec["proc"]
    if proc.poll() is None:
        try:
            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=3)
        except (subprocess.TimeoutExpired, ProcessLookupError):
            proc.kill()
            proc.wait(timeout=3)
    rec["sampler_stop"].set()
    return _record_finish(rec, state, settled=True)


_SAMPLER_JOIN_S = 0.25


def _record_finish(rec: dict, state=None, settled: bool = False
                   ) -> pathlib.Path:
    out = rec["out"]
    if not settled:
        # bounded path: proc already exited or timed out
        rec["sampler_stop"].set()
    # the level sampler may publish one more window after the recorder
    # stops; wait for it to exit (event-driven) instead of a fixed
    # 300 ms sleep, then zero the level. Bounded in case it is stuck.
    sampler = rec.get("sampler")
    if sampler is not None:
        sampler.join(timeout=_SAMPLER_JOIN_S)
    if state:
        state.set_level(0.0)
    else:
        config.LEVEL_FILE.write_text("0.0")
    if not (out.exists() and out.stat().st_size > 44):
        raise RuntimeError(f"recording produced no audio: {out}")
    return out


_LEVEL_WINDOW = 20


def _amplitude_sampler(seconds: int | None, state=None,
                       stop_ev=None) -> None:
    """Breathing darkness: sample mic RMS, publish level for the overlay."""
    from . import platform
    arec = platform.sampler_cmd(seconds)
    if not arec:
        return

    def publish(v: float) -> None:
        if state:
            state.set_level(v)
        else:
            config.LEVEL_FILE.write_text(f"{v:.3f}")

    proc = None
    try:
        proc = subprocess.Popen(
            arec,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=_pl().hypr_env())
        # one 100 ms window (20 samples at 200 Hz) per read: the level
        # arrives at an even 10 Hz instead of a burst once a second
        while True:
            if stop_ev is not None and stop_ev.is_set():
                break
            w = proc.stdout.read(_LEVEL_WINDOW)
            if not w:
                break
            if len(w) < _LEVEL_WINDOW:
                continue  # short tail at EOF — next read ends the loop
            rms = sum(abs(b - 128) for b in w) / (len(w) * 128)
            publish(min(1.0, rms * 6))
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)
    except Exception:
        try:
            publish(0.0)
        except Exception:
            pass
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()


def transcribe(wav: pathlib.Path, cfg: dict) -> str:
    stt = config.stt_settings(cfg)
    provider = stt["provider"]
    from . import stt_stream
    streamer = stt_stream.claim(wav)
    if streamer is not None and provider == "openai":
        text = streamer.finish()    # chunks sent while the key was held
        if text is not None:
            return text
    if provider == "wordink":
        try:
            import wordink
            return wordink.transcribe(str(wav))
        except ImportError:
            raise RuntimeError(
                "stt provider 'wordink' requested but the wordink "
                "module is not installed")
        except Exception:
            pass
    if provider == "openai":
        return _transcribe_openai(wav, stt, cfg)
    model = config.whisper_model(cfg)
    if not (config.WHISPER_BIN.exists() and model.exists()):
        raise RuntimeError(f"whisper.cpp missing: {config.WHISPER_BIN} / {model}")
    argv = [str(config.WHISPER_BIN), "-m", str(model), "-nt",
            "-f", str(wav)]
    from . import lang as _lang
    multilingual = not _lang.local_model_english_only(cfg)
    if multilingual:
        # a multilingual model: pin the language or let it detect
        argv += ["-l", _lang.base(_lang.configured(cfg)) or "auto"]
    from . import vocab
    prompt = vocab.build(cfg)
    if prompt:
        argv += ["--prompt", prompt]
    r = _cancel.run(argv, capture_output=True, text=True, timeout=120)
    heard = ""
    if multilingual:
        m = re.search(r"auto-detected language:\s*([a-z]{2,3})",
                      r.stderr or "")
        heard = m.group(1) if m else ""
    return _lang.Transcript(" ".join(r.stdout.split()), heard)


def _cap_prompt(prompt: str, limit: int = 896) -> str:
    """Groq rejects /audio/transcriptions prompts over 896 chars —
    trim at the last term boundary so vocab terms aren't clipped
    mid-word."""
    if len(prompt) <= limit:
        return prompt
    return prompt[:limit].rsplit(",", 1)[0]


def _transcribe_openai(wav: pathlib.Path, stt: dict,
                       cfg: dict | None = None) -> str:
    """OpenAI-compatible /audio/transcriptions — Groq, OpenAI, vLLM,
    Together, DeepInfra. Key comes from .env/env via stt.key_env."""
    from . import vocab
    stt = {**config.STT_DEFAULTS, **stt}
    from . import lang as _lang
    key = config.require_key(stt["key_env"])
    base = stt["base_url"].rstrip("/")
    audio = wav.read_bytes()
    prompt = _cap_prompt(vocab.build(cfg or {"stt": stt}))
    pinned = _lang.base(_lang.configured(cfg or {"stt": stt}))
    # a pinned language is sent as is; on auto the model reports what it
    # heard (verbose_json), so the answer and the voice can follow it
    extra = [("language", pinned)] if pinned \
        else [("response_format", "verbose_json")]

    def post(fields):
        boundary = f"----wisp{int(time.monotonic() * 1000)}"
        parts = []
        for name, value in [("model", stt["model"]),
                            ("prompt", prompt)] + fields:
            parts += [f"--{boundary}".encode(),
                      f'Content-Disposition: form-data; name="{name}"'
                      .encode(), b"", value.encode()]
        body = b"\r\n".join(parts + [
            f"--{boundary}".encode(),
            b'Content-Disposition: form-data; name="file"; '
            b'filename="utterance.wav"',
            b"Content-Type: audio/wav",
            b"",
            audio,
            f"--{boundary}--".encode(),
            b"",
        ])
        from . import brain as _brain
        req = urllib.request.Request(
            f"{base}/audio/transcriptions", data=body,
            headers={"Authorization": f"Bearer {key}",
                     "User-Agent": "wisp/1.0",
                     **_brain.app_headers(base),
                     "Content-Type":
                     f"multipart/form-data; boundary={boundary}"})
        with _cancel.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())

    try:
        got = post(extra)
    except urllib.error.HTTPError as e:
        if e.code != 400:
            raise
        if pinned:
            raise _lang.Refused(_lang.provider_refusal(
                _lang.configured(cfg or {"stt": stt}))) from e
        got = post([])        # a provider without verbose_json: no detection
    return _lang.Transcript(" ".join(got.get("text", "").split()),
                            "" if pinned else got.get("language", ""))


def active_window() -> dict:
    from . import platform
    return platform.active_window()


def capture_screen(window: bool = False) -> pathlib.Path | None:
    """Platform screenshot → RUN_DIR/screen.png. None on fail.
    `window=True` crops to the focused window (the blank-frame retry)."""
    from . import platform
    from . import cua_safety
    if cua_safety.capture_blocked():
        return None   # sensitive window focused: no shot (R13)
    out = config.RUN_DIR / "screen.png"
    if window:
        cmd = platform.window_screenshot_cmd(out, platform.active_geometry())
    else:
        cmd = platform.screenshot_cmd(out)
    if not cmd:
        return None
    try:
        config.RUN_DIR.mkdir(parents=True, exist_ok=True)
        r = _cancel.run(cmd, capture_output=True,
                        timeout=10, env=_pl().hypr_env())
        if r.returncode == 0 and out.exists():
            # same normalize as the screenshot tool: logical-size image
            # + coord grid, so model x,y maps 1:1 and HiDPI pixels don't
            # double-map — also ~4x smaller on the wire (raw 3456x2160
            # PNG was the biggest single payload in the first act call)
            try:
                from .tools.system import _normalize_shot
                _normalize_shot(out)
            except Exception:
                pass
            from . import redact
            if redact.apply(out, config.load_config()):
                out.unlink(missing_ok=True)   # a hidden window rides along
                return None
            return out
        return None
    except Exception:
        return None


def _png_b64(png: pathlib.Path | None) -> str | None:
    """Shot file → data URL (JPEG when magick transcodes, else PNG)."""
    if not png:
        return None
    try:
        from .tools.system import model_image
        return model_image(png)
    finally:
        png.unlink(missing_ok=True)


def _qa_needs_no_screen(text: str) -> bool:
    """Question-shaped utterance with no screen referent → the shot is
    dead payload. Referent tokens (this/that/screen/open/it...) or a
    non-question verb keep the image; over ~120 chars keeps it too
    (long asks are rarely pure trivia)."""
    t = " ".join((text or "").lower().split())
    if not t or len(t) > 120:
        return False
    _Q = ("what", "who", "when", "where", "why", "how", "which",
          "is ", "are ", "do ", "does ", "can ", "could ", "would ",
          "define ", "translate ", "spell ", "convert ")
    if not t.startswith(_Q):
        return False
    _REF = ("this", "that", "screen", "window", "open", "file",
            "folder", "here", "error", "dialog", "button", "click",
            "these", "those", " it ", "my ", " the app", "app ",
            "code", "desktop", "monitor")
    return not any(r in t for r in _REF)


def turn_screenshot(cfg: dict, speculative=None) -> str | None:
    """The turn's screenshot (base64): the press-time speculative capture
    when it is ready and fresh, else one inline capture. None when
    screenshots are off."""
    if cfg.get("agent", {}).get("screenshots", "true") != "true":
        return None
    if speculative is not None:
        got = speculative.take("screenshot", wait=_SPEC_WAIT_S)
        if got or isinstance(got, _blank.Blind):
            return got
    return _vetted_b64()


def _vetted_b64():
    """A screenshot as a data URL, checked for a blank frame (B28): the
    frame itself, or a `blank.Blind` when it came out black or empty and
    the window retry did not help, or None when nothing was captured."""
    pl = _pl()
    got = _blank.vet(pl.capture_screen(),
                     retry=lambda: pl.capture_screen(window=True),
                     trace=_trace_blank)
    if isinstance(got, _blank.Blind) or got is None:
        return got
    return _png_b64(got)


def _trace_blank(event: str, fields: dict) -> None:
    from . import trace as _trace
    _trace.emit(_trace.current(), event, "act", fields)


_SPEC_WAIT_S = 1.0


def speculative_context(cfg: dict):
    """Press-time speculation (W4): screenshot and window map, gathered
    concurrently. Not started — the daemon calls `.start()`."""
    from . import context as _context
    g = {"windows": _context.windows_map}
    from . import selection as _selection
    if _selection._enabled(cfg):
        g["selection"] = lambda: _selection.read_primary(cfg)
    if cfg.get("agent", {}).get("screenshots", "true") == "true":
        g["screenshot"] = _vetted_b64
    delays = {}
    from . import chips as _chips
    if "screenshot" in g and _chips.armed(cfg):
        # a tap (B21) is released before this and takes no screenshot
        delays["screenshot"] = _chips.TAP_MAX_S
    return _context.Speculative(g, delays=delays)


def screen_b64(cfg: dict, answers: dict) -> str | None:
    """Attach a screenshot on the answer route — the act loop already
    gets the trigger-time capture via initial_image. Skipped when
    screenshots are disabled in config."""
    if cfg.get("agent", {}).get("screenshots", "true") != "true":
        return None
    if answers.get("route", {}).get("choice") != "answer":
        return None
    png = _pl().capture_screen()
    if not png:
        return None
    try:
        return base64.b64encode(png.read_bytes()).decode()
    finally:
        png.unlink(missing_ok=True)


def capture_stage(ctx) -> bool:
    """Record (unless the daemon already did) and transcribe. False when
    nothing was heard: the turn is already finished in that case."""
    from . import trace as _trace
    pl, state, sp, token, cfg = _pl(), ctx.state, ctx.sp, ctx.token, ctx.cfg
    if ctx.wav is None:
        state.transition("listening", transcript="", result="",
                         answer="", choices=[], points=[], error="",
                         error_code="", error_detail="")
        sp.record("press", sp.t0)
        rec_start = sp.now()
        ctx.wav = pl.record(ctx.secs, state)
        sp.record("record", rec_start)
        sp.set_release()
    wav = ctx.wav
    token.check()
    rec_ms = sp.ms.get("record", 0)
    _trace.emit(ctx.turn, "record", "stt",
                {"wav": str(wav),
                 "bytes": wav.stat().st_size if wav.exists() else 0},
                rec_ms)
    state.transition("transcribing")
    sp.record("release", sp.rel0)
    from . import lang as _lang
    try:
        why = _lang.stt_refusal(cfg)
        if why:
            raise _lang.Refused(why)
        text = pl.transcribe(wav, cfg)
    except _lang.Refused as e:
        return _refuse_language(ctx, str(e))
    except Exception as e:
        raise _errors.classify(e, "stt_down") from e
    token.check()
    sp.record("stt", sp.rel0)
    _trace.emit(ctx.turn, "transcribe", "stt",
                {"provider": config.stt_settings(cfg)["provider"],
                 "text": text}, sp.ms["stt"])
    ctx.lang = _lang.resolve(cfg, getattr(text, "language", ""))
    text = str(text)
    state.transition("deciding", transcript=text)
    ctx.text = text
    if ctx.lang and not _lang.is_english(ctx.lang):
        _trace.emit(ctx.turn, "language", "stt", {"lang": ctx.lang})
    if not text or "[BLANK" in text:
        state.transition("done", result="heard nothing")
        pl.notify("Heard nothing", **pl._toast_ctx(state, ctx.turn, cfg))
        return False
    return True


def _say_and_wait(ctx, line: str) -> None:
    """Speak one sentence now and let it finish (bounded), so the answer
    that follows does not talk over it."""
    from . import speech
    try:
        proc = speech.speak(line, ctx.cfg)
        if proc is not None:
            proc.wait(timeout=8)
    except Exception:
        pass


def _refuse_language(ctx, reason: str) -> bool:
    """The speech setup cannot do the language: say why out loud and end
    the turn, never hang."""
    from . import speech
    pl = _pl()
    ctx.state.transition("done", result=reason)
    speech.speak(reason, ctx.cfg)
    pl.notify(reason, **pl._toast_ctx(ctx.state, ctx.turn, ctx.cfg))
    return False


def context_stage(ctx) -> bool:
    """Everything the router and the brain are told about this moment:
    harness catalog, focused window, trigger screenshot, goal, recent
    conversation, memory and a refinement correction if there is one."""
    from . import trace as _trace
    pl, state, sp, cfg, text = _pl(), ctx.state, ctx.sp, ctx.cfg, ctx.text
    turn, speculative = ctx.turn, ctx.speculative
    from .tools import adapters
    ctx.harness = harness = {"apps": adapters.best_catalog(),
                             "context": adapters.context()}
    with sp.timed("hyprctl"):
        win = pl.active_window()
    ctx.app = win.get("class", "") or ""
    state.transition("deciding", transcript=text,
                     focus={"app": win.get("class", ""),
                            "title": win.get("title", "")[:120]})
    context = harness.get("context", "")
    if win.get("title"):
        context += f"\nActive window: {win['class']} — {win['title']}"
    # screen-first: capture once at trigger; act loop + answer share
    # it. Clicky does the same — the model sees the app instead of
    # asking which one.
    ctx.shot_b64 = None
    ctx.blind = None
    from . import scribble as _scribble
    marks = _scribble.take()          # consumed by this turn, used or not
    if cfg.get("agent", {}).get("screenshots", "true") == "true":
        # pure Q&A doesn't need the screen — dropping the image saves
        # ~700KB of payload + the transcode on "what time is it" turns.
        # Conservative: any referent token keeps the shot.
        from . import selfknow as _selfknow
        qa_skip = (_qa_needs_no_screen(text)
                   or _selfknow.intent(text) is not None) and marks is None
        if not qa_skip:
            with sp.timed("screenshot"):
                ctx.shot_b64 = pl.turn_screenshot(cfg, speculative)
            if isinstance(ctx.shot_b64, _blank.Blind):
                ctx.blind, ctx.shot_b64 = ctx.shot_b64, None
            ctx.shot_b64, ctx.scribble_hint = _scribble.apply(
                ctx.shot_b64, marks)
            if ctx.scribble_hint:
                context += "\n" + ctx.scribble_hint
        _trace.emit(turn, "screen_capture", "act",
                    {"captured": bool(ctx.shot_b64),
                     "img_kb": len(ctx.shot_b64 or "") * 3 // 4096,
                     "qa_skip": qa_skip,
                     "scribbled": bool(ctx.scribble_hint),
                     "speculative": bool(speculative)})
    if ctx.blind is not None:
        read = _blank.window_text(win)
        _trace.emit(turn, "screen_blind", "act",
                    {"why": ctx.blind.reason, "text_chars": len(read)})
        if not read:
            # nothing to read: end honestly, no model call about content
            return _refuse_language(ctx, _blank.LINE_BLIND)
        _say_and_wait(ctx, _blank.LINE_READING)
        context += "\n" + _blank.context_note(ctx.blind.reason, read)
    wins = speculative.take("windows") if speculative else None
    if wins:
        context += "\n" + wins
    # goal memory — continuations ("it's open, just hit cmd-t") join
    # the open goal instead of starting a fresh act
    from . import goals as _goals
    with sp.timed("goal"):
        goal, joined = _goals.join_or_new(text, win.get("class", ""), cfg)
    context += "\n" + _goals.context_text()
    _trace.emit(turn, "goal", "thought",
                {"joined": joined, "goal": goal["text"][:160]})
    from . import session
    n_turns = int(cfg.get("agent", {}).get("session_turns", "8"))
    ctx.session_text = session.as_text(session.tail(n_turns, app=ctx.app))
    if ctx.session_text:
        context += f"\nRecent conversation:\n{ctx.session_text}"
    from . import memory
    with sp.timed("memory"):
        block = memory.context_block(text)
    if block:
        context += f"\n{block}"
    # refinement loop: a labeled-bad last turn or a correction cue
    # ("no", "didn't work", "instead") turns this utterance into a
    # retry — the failed attempt rides along as context for Jev and
    # the act loop
    from . import learn as _learn
    corr = _learn.correction_context(text, cfg)
    detail = text
    if corr:
        context += ("\nCorrection: the previous attempt "
                    f"('{corr['prior_task']}' → {corr['prior_route']}) "
                    f"failed: {corr['prior_result']}. The user is "
                    "correcting it — re-route, don't repeat.")
        detail = (f"[previous attempt: {corr['prior_task']!r} → "
                  f"{corr['prior_route']} failed "
                  f"({corr['prior_result'][:80]})] {text}")
        _trace.emit(turn, "correction", "thought",
                    {"via": corr["via"], "prior": corr["prior_task"]})
    ctx.corr, ctx.detail, ctx.context = corr, detail, context
    try:
        from . import docread
        ctx.doc_text = docread.context_for(text, win, cfg)
    except Exception:
        ctx.doc_text = ""            # a document read never fails a turn
    try:
        from . import selection as _selection
        prim = speculative.take("selection", wait=_SPEC_WAIT_S, ttl=600) \
            if speculative else None
        found = _selection.build(text, prim, cfg)
        ctx.selection_text, ctx.clip_image = found.text, found.image
        if found.sources:
            _trace.emit(turn, "selection", "act",
                        {"sources": list(found.sources),
                         "chars": found.chars})
    except Exception:
        ctx.selection_text = ctx.clip_image = ""   # never fails a turn
    try:
        from . import omarchy_tutor
        ctx.tutor_text = omarchy_tutor.context_for(text)
    except Exception:
        ctx.tutor_text = ""          # a tutor read never fails a turn
    if ctx.tutor_text:
        ctx.context += "\n" + ctx.tutor_text
    return True
