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
import signal
import subprocess
import threading
import time
import urllib.request

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
    from . import platform
    cmd = platform.record_cmd(out, None)
    if cmd is None:
        raise RuntimeError(
            f"no recorder found — {platform.missing_deps_hint()}")
    stop_ev = threading.Event()
    sampler = threading.Thread(target=_amplitude_sampler,
                               args=(None, state, stop_ev), daemon=True)
    sampler.start()
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, env=_pl().hypr_env())
    return {"proc": proc, "out": out, "sampler_stop": stop_ev,
            "sampler": sampler, "t0": time.monotonic()}


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
    provider = cfg.get("stt", {}).get("provider", "local")
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
        return _transcribe_openai(wav, cfg["stt"], cfg)
    model = config.whisper_model(cfg)
    if not (config.WHISPER_BIN.exists() and model.exists()):
        raise RuntimeError(f"whisper.cpp missing: {config.WHISPER_BIN} / {model}")
    argv = [str(config.WHISPER_BIN), "-m", str(model), "-nt",
            "-f", str(wav)]
    from . import vocab
    prompt = vocab.build(cfg)
    if prompt:
        argv += ["--prompt", prompt]
    r = _cancel.run(argv, capture_output=True, text=True, timeout=120)
    return " ".join(r.stdout.split())


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
    key = config.load_env_key(stt.get("key_env", "GROQ_API_KEY"))
    if not key:
        raise RuntimeError(
            f"no {stt.get('key_env', 'GROQ_API_KEY')} in .env or environment")
    base = stt.get("base_url", "https://api.groq.com/openai/v1") \
        .rstrip("/")
    boundary = f"----wisp{int(time.monotonic() * 1000)}"
    audio = wav.read_bytes()
    body = b"\r\n".join([
        f"--{boundary}".encode(),
        b'Content-Disposition: form-data; name="model"',
        b"",
        stt.get("model", "whisper-large-v3-turbo").encode(),
        f"--{boundary}".encode(),
        b'Content-Disposition: form-data; name="prompt"',
        b"",
        _cap_prompt(vocab.build(cfg or {"stt": stt})).encode(),
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
        return " ".join(
            json.loads(resp.read()).get("text", "").split())


def active_window() -> dict:
    from . import platform
    return platform.active_window()


def capture_screen() -> pathlib.Path | None:
    """Platform screenshot → RUN_DIR/screen.png. None on fail/denied
    (macOS Screen Recording perm denial = empty PNG → caller skips)."""
    from . import platform
    out = config.RUN_DIR / "screen.png"
    cmd = platform.screenshot_cmd(out)
    if not cmd:
        return None
    try:
        config.RUN_DIR.mkdir(parents=True, exist_ok=True)
        r = _cancel.run(cmd, capture_output=True,
                        timeout=10, env=_pl().hypr_env())
        return out if r.returncode == 0 and out.exists() else None
    except Exception:
        return None


def _png_b64(png: pathlib.Path | None) -> str | None:
    if not png:
        return None
    try:
        return base64.b64encode(png.read_bytes()).decode()
    finally:
        png.unlink(missing_ok=True)


def turn_screenshot(cfg: dict, speculative=None) -> str | None:
    """The turn's screenshot (base64): the press-time speculative capture
    when it is ready and fresh, else one inline capture. None when
    screenshots are off."""
    if cfg.get("agent", {}).get("screenshots", "true") != "true":
        return None
    if speculative is not None:
        got = speculative.take("screenshot", wait=_SPEC_WAIT_S)
        if got:
            return got
    return _png_b64(_pl().capture_screen())


_SPEC_WAIT_S = 1.0


def speculative_context(cfg: dict):
    """Press-time speculation (W4): screenshot and window map, gathered
    concurrently. Not started — the daemon calls `.start()`."""
    from . import context as _context
    g = {"windows": _context.windows_map}
    if cfg.get("agent", {}).get("screenshots", "true") == "true":
        g["screenshot"] = lambda: _png_b64(_pl().capture_screen())
    return _context.Speculative(g)


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
    try:
        text = pl.transcribe(wav, cfg)
    except Exception as e:
        raise _errors.classify(e, "stt_down") from e
    token.check()
    sp.record("stt", sp.rel0)
    _trace.emit(ctx.turn, "transcribe", "stt",
                {"provider": cfg.get("stt", {}).get("provider", "local"),
                 "text": text}, sp.ms["stt"])
    state.transition("deciding", transcript=text)
    ctx.text = text
    if not text or "[BLANK" in text:
        state.transition("done", result="heard nothing")
        pl.notify("Heard nothing", **pl._toast_ctx(state, ctx.turn, cfg))
        return False
    return True


def context_stage(ctx) -> None:
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
    if cfg.get("agent", {}).get("screenshots", "true") == "true":
        with sp.timed("screenshot"):
            ctx.shot_b64 = pl.turn_screenshot(cfg, speculative)
        _trace.emit(turn, "screen_capture", "act",
                    {"captured": bool(ctx.shot_b64),
                     "speculative": bool(speculative)})
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
    ctx.session_text = session.as_text(session.tail(n_turns))
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
