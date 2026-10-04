"""Voice pipeline: record -> transcribe -> Jev -> route -> act.

Runs inside the daemon on a worker thread; every stage transitions State
so widgets see listening/deciding/awaiting_choice/done in real time.
U2 replaces the flat app/action questions with the route schema; the
confidence policy here already implements gate-on-target (launch executes
when app confidence is high even if action confidence is low).
"""
import base64
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from . import cancel as _cancel
from . import copy as _copy
from . import config, speech
from . import errors_codes as _errors

JEV_QUESTIONS = {
    "route": {
        "type": "choice",
        "instructions": "What kind of request is this?",
        "criteria": {
            "launch": "open, start, or close an application and "
                      "nothing else — if the request also says what to "
                      "do inside it (a page, a click, 'and then'), "
                      "that is 'act' instead",
            "tool": "a desktop/system action — window ops, workspace "
                    "switch, type text, screenshot, notify, run a command, "
                    "find files",
            "agent": "spawn a background agent for a coding, research, or "
                     "multi-step task — phrases like 'agent', 'have an "
                     "agent', 'spawn', 'delegate'",
            "learn": "the user wants Wisp to learn or remember how to do "
                     "something — 'learn X', 'remember this', 'add a "
                     "skill for'",
            "act": "a multi-step or in-app desktop task — do something "
                   "on screen or inside an app: 'open X on the Y page', "
                   "'go to', 'find', 'click', 'and then', any sequence "
                   "of actions — computer use",
            "dictation": "the user wants to dictate — type the words "
                         "they speak into the focused app — 'dictate', "
                         "'type this', 'take dictation', 'write this "
                         "down'",
            "answer": "the user is asking a question or chatting — "
                      "respond in text, no desktop action",
            "clarify": "the request is too ambiguous to act on",
        },
    },
    "app": {
        "type": "choice",
        "instructions": "Which application is the user asking about? "
                        "Choose 'none' if the user is asking a question, "
                        "chatting, or not requesting an app.",
        "criteria": {
            "none": "no application — the user is asking a question, "
                    "chatting, or the request is unclear",
            "browser": "user wants a web browser or a website",
            "terminal": "user wants a terminal or shell",
            "files": "user wants a file manager",
            "vscode": "user wants the code editor",
            "music": "user wants a music player",
            "settings": "user wants system settings",
            "browser_new_tab": "user wants a new browser tab",
        },
    },
    "risk": {
        "type": "score",
        "instructions": "0 read-only launch, 2 mutating",
        "criteria": ["read-only", "navigational", "mutating"],
    },
    "tool": {
        "type": "choice",
        "instructions": "Which tool should run? Only relevant when the "
                        "route is 'tool'.",
        "criteria": {},  # filled from the registry in build_questions
    },
}


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


def record(seconds: int, state=None) -> pathlib.Path:
    """Bounded capture for standalone `wispd listen` (no daemon to
    toggle-stop). The daemon uses record_start/record_stop instead."""
    rec = record_start(state)
    try:
        rec["proc"].wait(timeout=seconds)
        return _record_finish(rec, state)
    except subprocess.TimeoutExpired:
        return record_stop(rec, state)


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
                            stderr=subprocess.DEVNULL, env=hypr_env())
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
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=hypr_env())
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


def build_questions(harness: dict | None) -> dict:
    """Jev questions with the app catalog rebuilt from the local harness
    and the tool list filled from the registry."""
    from . import tools
    q = json.loads(json.dumps(JEV_QUESTIONS))
    q["tool"]["criteria"] = tools.describe()
    from . import learn
    # harness apps augment the defaults (terminal/files/...), never
    # replace them — otherwise "open the terminal" has no candidate
    criteria = dict(q["app"]["criteria"])
    if harness and harness.get("apps"):
        criteria.update({
            name: f"{a.get('cues', name)}"
            + (f" (frequently used: {a['seen']}x)"
               if a.get("seen", 0) >= 5 else "")
            for name, a in harness["apps"].items()
        })
    q["app"]["criteria"] = learn.apply_overrides(criteria)
    return q


def active_window() -> dict:
    from . import platform
    return platform.active_window()


def _jev_is_local(url: str) -> bool:
    import urllib.parse
    return (urllib.parse.urlparse(url).hostname or "") in \
        ("localhost", "127.0.0.1", "::1")


def ask_jev(transcript: str, model: str, questions: dict,
            context: str = "", cfg: dict | None = None) -> dict:
    """Jev decisions call. A loopback endpoint (jev-shim) needs no
    OPENROUTER_API_KEY; a remote one does. Failures raise WispError:
    refused/reset (after one fast retry), HTTP errors and unparseable
    replies are `jev_down`, a timeout is `timeout` (never retried)."""
    from . import errors_codes as _ec
    state_txt = f"{context}\n\nThe user said: \"{transcript}\"" \
        if context else f'The user said: "{transcript}"'
    payload = {"model": model, "state": state_txt, "questions": questions}
    headers = {"Content-Type": "application/json",
               "HTTP-Referer": "https://github.com/duketopceo/wisp",
               "X-Title": "Wisp"}
    endpoint = config.JEV_ENDPOINT
    if _jev_is_local(endpoint):
        key = config.load_env_key("OPENROUTER_API_KEY")
        if key:
            headers["Authorization"] = f"Bearer {key}"
    else:
        try:
            headers["Authorization"] = f"Bearer {config.load_api_key()}"
        except RuntimeError as e:
            raise _ec.WispError("jev_down", str(e)) from None
    req = urllib.request.Request(
        endpoint, data=json.dumps(payload).encode(), headers=headers,
        method="POST")
    for attempt in (1, 2):
        try:
            with _cancel.urlopen(req, timeout=30) as resp:
                out = json.loads(resp.read())
            _shadow_decision(transcript, state_txt, questions, cfg, out,
                             model)
            return out
        except urllib.error.HTTPError as e:
            raise _ec.WispError(
                "jev_down",
                f"Jev HTTP {e.code}: {e.read().decode()[:200]}") from None
        except Exception as e:
            if attempt == 1 and _ec.is_connection_failure(e):
                time.sleep(0.05)
                continue
            raise _ec.classify(e, "jev_down") from None


def _publish_error(state, exc: BaseException) -> None:
    """End a turn in `error` with a closed-set code: `error` is the
    human-safe string, `error_detail` the raw text (local only)."""
    from . import errors_codes as _ec
    err = _ec.classify(exc, "internal")
    state.transition("error", error=err.public, error_code=err.code,
                     error_detail=err.detail[:500])
    from . import report as _report
    _report.capture(err.code, exc)


def _shadow_decision(transcript: str, state_txt: str, questions: dict,
                     cfg: dict | None, primary: dict, model: str) -> None:
    """Answer the same questions with a second decider, in the background.

    Fire-and-forget on purpose: a turn must never wait on a shadow, and a
    shadow failing must never look like a turn failing. Its only output is
    an appended comparison record in shadow.jsonl, which exists so the two
    models can be scored against human labels instead of against each
    other.

    The trace turn id is stamped here rather than in the worker: trace ids
    live in a thread-local, and the worker runs on its own daemon thread
    where that local is unset. `log_decision` writes the same id, which is
    the only reliable way to pair a shadow record with the decision a
    human later labels — joining on transcript+timestamp mis-pairs a
    repeated utterance.
    """
    name = str(((cfg or {}).get("jev") or {}).get("shadow") or "").strip()
    spec = config.SHADOW_PROVIDERS.get(name)
    if not spec:
        return
    key = config.load_env_key(spec["key_env"])
    if not key:
        return                      # no key -> nothing to compare against
    from . import trace as _trace
    threading.Thread(
        target=_shadow_worker,
        args=(name, spec, key, transcript, state_txt, questions, primary,
              model, _trace.current()), daemon=True).start()


def _shadow_worker(name: str, spec: dict, key: str, transcript: str,
                   state_txt: str, questions: dict, primary: dict,
                   primary_model: str, turn: str) -> None:
    try:
        body = json.dumps({"model": spec["model"], "state": state_txt,
                           "questions": questions}).encode()
        req = urllib.request.Request(
            spec["endpoint"], data=body,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json",
                     "User-Agent": "wisp/1.0"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            shadow = json.loads(resp.read())
    except Exception:                                   # noqa: BLE001
        return                      # best-effort by definition

    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "turn": turn,
        "transcript": transcript,
        "primary": {"provider": "jev", "model": primary_model,
                    "answers": (primary or {}).get("answers", {})},
        "shadow": {"provider": name, "model": spec["model"],
                   "answers": (shadow or {}).get("answers", {}),
                   "input_tokens":
                       ((shadow or {}).get("usage") or {}).get("input_tokens")},
        "agree": _shadow_agree(primary, shadow),
    }
    try:
        config.SHADOW.parent.mkdir(parents=True, exist_ok=True)
        with config.SHADOW.open("a") as f:
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")
    except OSError:
        pass


def _shadow_agree(primary: dict, shadow: dict) -> dict:
    """Per-question agreement between two deciders.

    choice compares the picked option. noul is a probability, not a label,
    so it agrees when the two land within 0.2 — the same call at any sane
    threshold. score compares the rounded expected level, since 1.78 and
    1.82 are the same answer.
    """
    out = {}
    pa = (primary or {}).get("answers") or {}
    sa = (shadow or {}).get("answers") or {}
    for name in sorted(set(pa) | set(sa)):
        p, s = pa.get(name) or {}, sa.get(name) or {}
        # A question one side never answered is unmeasured, not a
        # disagreement — conflating the two would score an omission as a
        # wrong route and quietly deflate the agreement rate.
        if "choice" in p and "choice" in s:
            pv, sv = p.get("choice"), s.get("choice")
        elif "noul" in p and "noul" in s:
            pv, sv = p.get("noul"), s.get("noul")
        elif "score" in p and "score" in s:
            try:
                out[name] = round(float(p["score"])) == round(float(s["score"]))
            except (TypeError, ValueError):
                out[name] = None
            continue
        else:
            out[name] = None
            continue
        if isinstance(pv, float) and isinstance(sv, float):
            out[name] = abs(pv - sv) <= 0.2
        else:
            out[name] = pv == sv
    return out


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
                        timeout=10, env=hypr_env())
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
    return _png_b64(capture_screen())


_SPEC_WAIT_S = 1.0


def speculative_context(cfg: dict):
    """Press-time speculation (W4): screenshot and window map, gathered
    concurrently. Not started — the daemon calls `.start()`."""
    from . import context as _context
    g = {"windows": _context.windows_map}
    if cfg.get("agent", {}).get("screenshots", "true") == "true":
        g["screenshot"] = lambda: _png_b64(capture_screen())
    return _context.Speculative(g)


def screen_b64(cfg: dict, answers: dict) -> str | None:
    """Attach a screenshot on the answer route — the act loop already
    gets the trigger-time capture via initial_image. Skipped when
    screenshots are disabled in config."""
    if cfg.get("agent", {}).get("screenshots", "true") != "true":
        return None
    if answers.get("route", {}).get("choice") != "answer":
        return None
    png = capture_screen()
    if not png:
        return None
    try:
        return base64.b64encode(png.read_bytes()).decode()
    finally:
        png.unlink(missing_ok=True)


def is_low_confidence(answers: dict, cfg: dict) -> bool:
    """Gate on app/target confidence — action confidence no longer kills
    correct launches (the 'retro-large' bug). Launch is a whitelisted
    action: high app confidence + acceptable risk executes regardless of
    how Jev scored the action question."""
    app_conf = answers.get("app", {}).get("confidence", 1)
    thresh = float(cfg.get("agent", {}).get("confidence_ambiguous", "0.8"))
    return app_conf < thresh


_DICTATE_PREFIX = re.compile(
    r"^\s*(please\s+)?(dictate|dictation|take dictation|type this|"
    r"type|write this down|write down)[:,.\s—-]+",
    re.IGNORECASE)


def dictation_text(text: str) -> str:
    """Strip a leading dictate command prefix; keep the rest verbatim."""
    return _DICTATE_PREFIX.sub("", text, count=1).strip() or text


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


def execute(answers: dict, cfg: dict, harness: dict | None = None,
            detail: str = "", state=None, confirm=None,
            initial_image: str | None = None, interrupted=None) -> str:
    """Route-aware dispatch. Falls back to the legacy action-based path
    when Jev's response lacks the route question. Jev only answers typed
    questions (noul/choice/score) — free-text args come from the
    transcript via `detail`. `initial_image` is the trigger-time
    screenshot (b64) handed to the act loop so the model sees the app
    instead of asking which one."""
    from . import agents, tools
    route = answers.get("route", {}).get("choice")
    action = answers.get("action", {}).get("choice")
    app = answers.get("app", {}).get("choice")
    risk = float(answers.get("risk", {}).get("score", 2))
    threshold = float(cfg.get("agent", {}).get("risk_threshold", "9"))

    # Risk gate applies to mutating work — a plain app launch or a text
    # answer is never blocked on risk (Jev's score band for launches
    # straddles the navigational/mutating line: "open discord" ~1.6).
    # dictation is self-confirming — the transcript is the user's own
    # instruction, so it skips the risk gate like launch/answer. Same for
    # a safe-tier tool pick even when the route guess was off.
    tool_choice = answers.get("tool", {}).get("choice", "")
    gated = route not in ("launch", "answer", "dictation") and \
        action not in ("launch", "answer")
    if gated and (tool_choice in ("launch", "answer")
                  or tools.risk_of(tool_choice)
                  in ("safe", "interactive")):
        gated = False
    if gated and risk > threshold:
        return f"BLOCKED (risk={risk:.2f} > {threshold})"

    if route == "agent":
        return agents.spawn(detail or app or "unnamed task", cfg)
    if route == "act":
        from . import act
        return act.run_act_loop(detail, cfg, state=state,
                                harness=harness, confirm=confirm,
                                initial_image=initial_image,
                                interrupted=interrupted)
    if route == "dictation":
        # type the spoken words; a leading dictate keyword is a command
        # prefix, not content — strip it. A correction prefix
        # ('[previous attempt: ...]') is metadata, never dictated.
        body = re.sub(r"^\[previous attempt:[^\]]*\]\s*", "", detail)
        text_to_paste = dictation_text(body)
        try:
            import wordink
            inserter = wordink.TextInserter()
            if inserter.insert_text(text_to_paste):
                return f"DICTATED: {text_to_paste}"
        except Exception:
            pass
        return tools.run("type_text", text_to_paste, cfg)
    if route == "learn":
        from . import act
        prompt = ("Author a reusable skill for this request using the "
                  "skill_manage and skill_view tools. If a skill on this "
                  "topic already exists, view it and fold improvements "
                  "in with edit; otherwise create it. Keep the SKILL.md "
                  "body concise and procedural. Request: " + detail)
        return act.run_act_loop(prompt, cfg, state=state,
                                harness=harness, confirm=confirm,
                                initial_image=initial_image,
                                interrupted=interrupted)
    if route == "tool":
        tool_name = answers.get("tool", {}).get("choice", "")
        if tool_name == "launch":
            # launch takes the resolved app name, not the transcript
            if not app or app == "none":
                return "SKIP (launch but no app identified)"
            return tools.run("launch", app, cfg, harness)
        tier = tools.risk_of(tool_name)
        if tier == "shell":
            if cfg.get("agent", {}).get("allow_shell", "false") != "true":
                return "BLOCKED (shell tool needs allow_shell=true in config)"
            # Jev returns no free-text args — `detail` is the raw
            # transcript, and executing it verbatim turns every
            # misroute into `sh -c "<your sentence>"`. The act loop's
            # model composes a real argv from the request instead.
            from . import act
            return act.run_act_loop(detail, cfg, state=state,
                                    harness=harness, confirm=confirm,
                                    initial_image=initial_image,
                                    interrupted=interrupted)
        if tier == "mutating" and risk > threshold:
            return f"BLOCKED (tool {tool_name!r} needs confirmation)"
        if tier == "safe" or risk <= threshold:
            return tools.run(tool_name, detail, cfg, harness)
        return f"BLOCKED (tool {tool_name!r} needs confirmation)"
    if route == "launch" or action == "launch":
        if not app or app == "none":
            return "SKIP (launch route but no app identified)"
        return tools.run("launch", app, cfg, harness)
    if route == "answer" or action == "answer" or app == "none":
        return "ANSWERED"
    if action in tools.REGISTRY:
        return tools.run(action, detail, cfg, harness)
    return f"SKIP (route={route!r} action={action!r} unhandled)"


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


def ambiguous_choices(answers: dict, cfg: dict) -> list:
    """Choice labels for the clarify widget: top app/action candidates."""
    app_probs = sorted(answers.get("app", {}).get("probabilities", {}).items(),
                       key=lambda kv: -kv[1])[:3]
    act_probs = sorted(answers.get("action", {}).get("probabilities", {}).items(),
                       key=lambda kv: -kv[1])[:3]
    return [f"app:{k}" for k, _ in app_probs] \
        + [f"action:{k}" for k, _ in act_probs]


_OPEN_VERB = re.compile(
    r"(?:open|launch|start|close|quit|focus|switch to|run|bring up|"
    r"pull up|show me)\s+(?:the\s+)?(?:app\s+)?([\w .+~/-]+)",
    re.IGNORECASE)


def fuzzy_app(text: str, answers: dict) -> str:
    """Pull an app name out of 'open discord' when Jev picks none.
    Matches against the probability keys Jev was choosing among —
    normalized ('day flow' matches 'dayflow'), substring then difflib."""
    m = _OPEN_VERB.search(text)
    if not m:
        return ""
    want = re.sub(r"[\s._-]+", "", m.group(1).strip().rstrip(".")).lower()
    if not want:
        return ""
    keys = [k for k in answers.get("app", {}).get("probabilities", {})
            if k != "none"]
    norm = {re.sub(r"[\s._-]+", "", k).lower(): k for k in keys}
    if want in norm:
        return norm[want]
    for nk, k in norm.items():  # "discord canary" -> discord
        if nk in want or want in nk:
            return k
    import difflib
    close = difflib.get_close_matches(want, list(norm), n=1, cutoff=0.6)
    return norm[close[0]] if close else ""


_BENIGN_ACTIONS = ("launch", "answer")


_COMPLEX_LAUNCH = re.compile(r"\b(on|in|to|at|for|into|and)\s+\S", re.I)
_LAUNCH_VERBS = ("open", "launch", "start", "go to", "pull up",
                 "bring up", "switch to")


def complex_launch(text: str) -> bool:
    """'open discord' → False (plain launch); 'open X on the Y page'
    or 'open A and B' → True (multi-step, belongs in act)."""
    lower = text.lower()
    if not any(v in lower for v in _LAUNCH_VERBS):
        return False
    return bool(_COMPLEX_LAUNCH.search(lower))


def auto_pick(answers: dict) -> str:
    """Timeout fallback for clarify prompts: pick Jev's own top candidate
    — but only along the safe axis. App picks resolve which app; action
    picks are only auto-taken when they're launch/answer, never
    run_shell/type_text. Anything else stays cancelled."""
    probs = answers.get("app", {}).get("probabilities", {})
    acts = answers.get("action", {}).get("probabilities", {})
    top_act = max(acts.items(), key=lambda kv: kv[1])[0] if acts else ""
    top_app = max(probs.items(), key=lambda kv: kv[1])[0] if probs else ""
    if top_act in _BENIGN_ACTIONS and top_app and top_app != "none":
        return f"app:{top_app}"
    if top_act in _BENIGN_ACTIONS:
        return f"action:{top_act}"
    if top_app and top_app != "none":
        return f"app:{top_app}"
    return ""


def apply_choice(answers: dict, picked: str) -> dict:
    """User picked a clarify option — rewrite the decision accordingly."""
    kind, _, value = picked.partition(":")
    corrected = json.loads(json.dumps(answers))
    if kind == "app":
        corrected["app"]["choice"] = value
    else:
        corrected.setdefault("action", {})["choice"] = value
    corrected["corrected_by_user"] = True
    return corrected


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


def _ask_prompt(state, wait_for_choice, token, options: list,
                timeout: float, turn: str, kind: str):
    """Publish a prompt with a fresh prompt_id, wait for the answer and
    return the pick — or None when none came, the turn was cancelled or
    the pick was not one of the offered options (`choice_rejected`)."""
    from . import trace as _trace
    pid = _cancel.new_prompt_id()
    state.transition("awaiting_choice", choices=list(options),
                     prompt_id=pid)
    try:
        pick = wait_for_choice(timeout, prompt_id=pid,
                               options=list(options))
    finally:
        if not token.cancelled:
            state.transition("acting", choices=[], prompt_id="")
    if pick and pick not in options:
        _trace.emit(turn, "choice_rejected", "act",
                    {"kind": kind, "pick": pick, "prompt_id": pid,
                     "offered": list(options)})
        return None
    return pick


def _listen_turn(cfg, state, wait_for_choice, wav, interrupted, spans,
                 turn_id, token, speculative=None) -> int:
    secs = int(cfg.get("audio", {}).get("seconds", "60"))
    model = cfg.get("agent", {}).get("model", "typesafe/jev-1.13")
    result = ""
    speaker = None
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
    _trace.emit(turn, "listen_start", "lifecycle",
                {"seconds": secs, "model": model})
    try:
        token.check()
        if wav is None:
            state.transition("listening", transcript="", result="",
                             answer="", choices=[], points=[], error="",
                             error_code="", error_detail="")
            sp.record("press", sp.t0)
            rec_start = sp.now()
            wav = record(secs, state)
            sp.record("record", rec_start)
            sp.set_release()
        token.check()
        rec_ms = sp.ms.get("record", 0)
        _trace.emit(turn, "record", "stt",
                    {"wav": str(wav),
                     "bytes": wav.stat().st_size if wav.exists() else 0},
                    rec_ms)
        state.transition("transcribing")
        sp.record("release", sp.rel0)
        try:
            text = transcribe(wav, cfg)
        except Exception as e:
            raise _errors.classify(e, "stt_down") from e
        token.check()
        sp.record("stt", sp.rel0)
        _trace.emit(turn, "transcribe", "stt",
                    {"provider": cfg.get("stt", {}).get("provider", "local"),
                     "text": text}, sp.ms["stt"])
        state.transition("deciding", transcript=text)
        if not text or "[BLANK" in text:
            state.transition("done", result="heard nothing")
            notify("Heard nothing", **_toast_ctx(state, turn, cfg))
            return 0
        from .tools import adapters
        harness = {"apps": adapters.best_catalog(),
                   "context": adapters.context()}
        with sp.timed("hyprctl"):
            win = active_window()
        if state:
            state.transition("deciding", transcript=text,
                             focus={"app": win.get("class", ""),
                                    "title": win.get("title", "")[:120]})
        context = harness.get("context", "")
        if win.get("title"):
            context += f"\nActive window: {win['class']} — {win['title']}"
        # screen-first: capture once at trigger; act loop + answer share
        # it. Clicky does the same — the model sees the app instead of
        # asking which one.
        shot_b64 = None
        if cfg.get("agent", {}).get("screenshots", "true") == "true":
            with sp.timed("screenshot"):
                shot_b64 = turn_screenshot(cfg, speculative)
            _trace.emit(turn, "screen_capture", "act",
                        {"captured": bool(shot_b64),
                         "speculative": bool(speculative)})
        wins = speculative.take("windows") if speculative else None
        if wins:
            context += "\n" + wins
        # goal memory — continuations ("it's open, just hit cmd-t") join
        # the open goal instead of starting a fresh act
        from . import goals as _goals
        with sp.timed("goal"):
            goal, joined = _goals.join_or_new(text, win.get("class", ""),
                                              cfg)
        context += "\n" + _goals.context_text()
        _trace.emit(turn, "goal", "thought",
                    {"joined": joined, "goal": goal["text"][:160]})
        from . import session
        n_turns = int(cfg.get("agent", {}).get("session_turns", "8"))
        session_text = session.as_text(session.tail(n_turns))
        if session_text:
            context += f"\nRecent conversation:\n{session_text}"
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
        # router: jev (default) | chat (transcript straight to answer
        # brain) | off (always clarify via choices) — Rust parity
        sp.record("context", sp.mark_ns("stt"))
        route_start = sp.now()
        route_meta = None
        router = cfg.get("brain", {}).get("router", "jev")
        agent_m = re.match(r"^\s*wisp\s+agent[:,.\s-]+(.*)$", text,
                           re.IGNORECASE)
        if agent_m and agent_m.group(1).strip():
            # explicit agent mode — skip Jev, straight to the
            # computer-use loop with the trigger screenshot
            detail = agent_m.group(1).strip()
            resp = {"answers": {"route": {"choice": "act"}}}
        elif router == "chat":
            resp = {"answers": {"route": {"choice": "answer"}}}
        elif router == "off":
            resp = {"answers": {"route": {"choice": "clarify"}}}
        else:
            from . import route as _route
            resp, route_meta = _route.decide(
                text, model, build_questions(harness), context, cfg,
                harness.get("apps"), spans=sp)
        token.check()
        sp.record("route", route_start)
        sp.arm("first_token", sp.mark_ns("route"))
        sp.arm("first_step", sp.mark_ns("route"))
        answers = resp.get("answers", {})
        _trace.emit(turn, "decision", "thought",
                    {"model": model, "answers": answers,
                     "latency_ms": resp.get("latency_ms"),
                     **({"route_source": route_meta["source"],
                         "jev_status": route_meta["jev_status"]}
                        if route_meta else {})},
                    sp.ms["context"] + sp.ms["route"])
        # transcript rescue: "open discord" with app=none shouldn't
        # clarify-prompt — the app name is right there in the words
        if answers.get("app", {}).get("choice", "none") in ("none", "", None):
            fa = fuzzy_app(text, answers)
            if fa:
                answers.setdefault("app", {})["choice"] = fa
        # complex-launch rescue: "open X" is launch, but "open X on the
        # Y page / and Z" is computer use — Jev over-picks launch on the
        # 'open' keyword and silently drops the rest of the request
        if answers.get("route", {}).get("choice") == "launch" \
                and complex_launch(text):
            answers["route"]["choice"] = "act"
        if route_meta:
            _route.log_ab(route_meta, text, turn,
                          answers.get("route", {}).get("choice"))
        # clarify only gates routes that truly need a named target —
        # launch has no other way to resolve the app. act/agent resolve
        # the target from the screen + goal instead of asking.
        needs_app = answers.get("route", {}).get("choice") == "launch"
        low_conf = needs_app and is_low_confidence(answers, cfg)
        corrected = None
        if low_conf:
            labels = ambiguous_choices(answers, cfg)
            if wait_for_choice:
                picked = _ask_prompt(state, wait_for_choice, token,
                                     labels, 60, turn, "clarify") \
                    or auto_pick(answers)
                token.check()
                if picked:
                    corrected = apply_choice(answers, picked)
                    from . import learn, recall as _recall
                    learn.record_correction(text, picked, answers)
                    try:
                        _recall.index_correction(
                            {"heard": text, "picked": picked})
                    except Exception:
                        pass
        if low_conf and not corrected:
            result = "CANCELLED (low confidence, no pick made)"
            state.transition("done", result=result)
            notify(result, "attention", **_toast_ctx(state, turn, cfg))
            log_decision({"ts": datetime.now(timezone.utc).isoformat(),
                          "transcript": text, "answers": answers,
                          "result": result, "corrected": False})
            return 0
        if corrected:
            answers = corrected
        state.transition("acting")
        confirm = None
        if wait_for_choice:
            from . import confirm as _confirm
            confirm = _confirm.make(state, wait_for_choice, token, turn, cfg)
        from . import brain as _brain
        act_img = shot_b64 if shot_b64 and \
            _brain.supports_vision(cfg) else None
        result = execute(answers, cfg, harness, detail=detail,
                         state=state, confirm=confirm,
                         initial_image=act_img, interrupted=interrupted)
        _trace.emit(turn, "dispatch", "act",
                    {"route": answers.get("route", {}).get("choice"),
                     "result": result})
        if result.startswith("INTERRUPTED"):
            token.cancel()   # `interrupted()` fired before the watcher
        token.check()
        if corr:
            _learn.record_retry(corr["prior_ref"], result)
        reply = ""
        if result.startswith("ASK_USER "):
            # spoken backchannel — ask aloud, keep the goal open; the
            # next utterance resumes it (goal ttl covers the pause)
            q = result[9:].strip()
            _trace.emit(turn, "ask_user", "speak", {"question": q})
            state.transition("speaking", result=result, answer=q)
            proc = speech.speak(q, cfg)
            if proc is not None:
                speech.on_exit(proc, _end_speaking(state))
            else:
                state.transition("done", result=result)
            session.append_turn(text, route="act", reply=q,
                                result=result)
            notify(result, "success", spoken=True,
                   **_toast_ctx(state, turn, cfg))
            sp.record("done", sp.rel0)
            log_decision({"ts": datetime.now(timezone.utc).isoformat(),
                          "turn": turn,
                          "transcript": text, "answers": answers,
                          "result": result,
                          "timing_ms": sp.legacy_timing(),
                          "corrected": False})
            return 0
        if result == "ANSWERED":
            pts = []
            speaker = speech.SentenceSpeaker(cfg, token=token)

            def _delta(acc):
                # stream the answer into state.json as it arrives — the
                # cursor bubble renders it live. Rate-limited by the
                # bus (coalesced, latest wins); incomplete
                # trailing [POINT…/markdown-ish brackets hidden so the
                # bubble never flashes raw tags.
                sp.fire("first_token")
                if state is None or token.cancelled:
                    return  # a cancelled turn publishes no more deltas
                partial = re.sub(r"\[[A-Za-z]*:?[^\]]*$", "", acc)
                _publish_delta(state, partial)
                # speak each completed sentence while the rest streams
                from . import points as _pts
                speaker.feed(_pts.extract(partial)[0])

            try:
                _t = time.monotonic()
                _meta: dict = {}
                reply = ask_chat(text, cfg, session_text,
                                 image_b64=shot_b64,
                                 on_delta=_delta if state else None,
                                 meta=_meta)
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
                raise _errors.classify(e, "brain_down") from e
            if reply:
                from . import points as _points
                reply, raw = _points.extract(reply)
                if raw:
                    _mons = _points.monitors()
                    if _points.img_space_is_logical():
                        pts = _points.canvas_to_logical(raw, _mons)
                    else:
                        pts = _points.to_logical(raw, _mons)
            if pts:
                _trace.emit(turn, "points", "act", {"points": pts})
            token.check()
            state.transition("speaking", result=result, answer=reply,
                             points=pts)
            _t = time.monotonic()
            tts_start = sp.now()
            if speaker.started:
                # sentences already went out as they completed; queue
                # the unspoken tail and flip to done when the last ends
                speaker.finish(reply, on_done=_end_speaking(state))
                proc = True
            else:
                proc = speech.speak(reply, cfg)
                if proc is not None:
                    speech.on_exit(proc, _end_speaking(state))
            sp.record("tts_start", tts_start)
            _trace.emit(turn, "speak", "tts",
                        {"cmd": cfg.get("voice", {}).get("cmd", ""),
                         "spawned": proc is not None,
                         "streamed": speaker.started},
                        round((time.monotonic() - _t) * 1000))
            if proc is None:
                state.transition("done")
        else:
            state.transition("done", result=result)
        session.append_turn(text, route=answers.get("route", {})
                            .get("choice", ""), reply=reply, result=result)
        try:
            from . import recall as _recall
            _recall.index_turn(text, reply, result)
        except Exception:
            pass
        notify(result, "success", spoken=True,
               **_toast_ctx(state, turn, cfg))
        sp.record("done", sp.rel0)
        log_decision({"ts": datetime.now(timezone.utc).isoformat(),
                      "turn": turn,
                      "transcript": text, "answers": answers, "result": result,
                      "timing_ms": sp.legacy_timing(),
                      "corrected": bool(answers.get("corrected_by_user"))})
        return 0
    except _cancel.Cancelled:
        # stop works at every stage: sockets are closed and children
        # killed by the token; kill any speech and settle on idle
        if speaker is not None:
            speaker.stop()
        speech.stop()
        _trace.emit(turn, "cancelled", "lifecycle", {"result": result})
        fields = {"error": "", "error_code": "cancelled",
                  "error_detail": "", "choices": [], "prompt_id": "",
                  "confirm": None}
        if result:
            fields["result"] = result
        state.transition("idle", **fields)
        log_decision({"ts": datetime.now(timezone.utc).isoformat(),
                      "result": "CANCELLED (user)",
                      "timing_ms": sp.legacy_timing()})
        return 0
    except Exception as e:
        if speaker is not None:
            speaker.stop()
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
        if state:
            state.set_level(0.0)
