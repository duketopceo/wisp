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

from . import config, speech

JEV_QUESTIONS = {
    "route": {
        "type": "choice",
        "instructions": "What kind of request is this?",
        "criteria": {
            "launch": "open, start, or close an application",
            "tool": "a desktop/system action — window ops, workspace "
                    "switch, type text, screenshot, notify, run a command, "
                    "find files",
            "agent": "spawn a background agent for a coding, research, or "
                     "multi-step task — phrases like 'agent', 'have an "
                     "agent', 'spawn', 'delegate'",
            "learn": "the user wants Wisp to learn or remember how to do "
                     "something — 'learn X', 'remember this', 'add a "
                     "skill for'",
            "act": "a multi-step desktop task — do several things, or "
                   "imperative instructions like 'open X and go to "
                   "workspace 2' or 'type this into the window'",
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
    "action": {
        "type": "choice",
        "instructions": "What should be done?",
        "criteria": {
            "launch": "open or start it",
            "close": "close or quit it",
            "type_text": "type some text",
            "run_shell": "run a shell command",
            "answer": "respond to the user in text — questions, chat, "
                      "or anything that is not a desktop action",
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
    "needs_screen": {
        "type": "noul",
        "instructions": "Does fulfilling this request require seeing what "
                        "is on the screen — reading an error, describing a "
                        "window, referencing visible content?",
    },
}


def hypr_env() -> dict:
    """Session env for spawned tools when run from a (systemd) daemon —
    fills in HIS and the Wayland socket wtype/grim need."""
    env = dict(os.environ)
    rd = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    if not env.get("HYPRLAND_INSTANCE_SIGNATURE"):
        hypr = pathlib.Path(rd) / "hypr"
        if hypr.is_dir():
            env["HYPRLAND_INSTANCE_SIGNATURE"] = sorted(hypr.iterdir())[0].name
    if not env.get("WAYLAND_DISPLAY"):
        for s in sorted(pathlib.Path(rd).glob("wayland-*")):
            env["WAYLAND_DISPLAY"] = s.name
            break
    return env


def notify(msg: str) -> None:
    from . import platform
    cmd = platform.notify_cmd("Wisp", msg)
    if cmd:
        subprocess.run(cmd, env=hypr_env())


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
            "sampler": sampler}


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


def _record_finish(rec: dict, state=None, settled: bool = False
                   ) -> pathlib.Path:
    out = rec["out"]
    if not settled:
        # bounded path: proc already exited or timed out
        rec["sampler_stop"].set()
    time.sleep(0.3)
    if state:
        state.set_level(0.0)
    else:
        config.LEVEL_FILE.write_text("0.0")
    if not (out.exists() and out.stat().st_size > 44):
        raise RuntimeError(f"recording produced no audio: {out}")
    return out


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
        while True:
            if stop_ev is not None and stop_ev.is_set():
                break
            chunk = proc.stdout.read(200)
            if not chunk:
                break
            step = 20
            for i in range(0, len(chunk) - step, step):
                w = chunk[i:i + step]
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
    if cfg.get("stt", {}).get("provider", "local") == "openai":
        return _transcribe_openai(wav, cfg["stt"])
    model = config.whisper_model(cfg)
    if not (config.WHISPER_BIN.exists() and model.exists()):
        raise RuntimeError(f"whisper.cpp missing: {config.WHISPER_BIN} / {model}")
    r = subprocess.run(
        [str(config.WHISPER_BIN), "-m", str(model), "-nt", "-f", str(wav)],
        capture_output=True, text=True, timeout=120)
    return " ".join(r.stdout.split())


def _transcribe_openai(wav: pathlib.Path, stt: dict) -> str:
    """OpenAI-compatible /audio/transcriptions — Groq, OpenAI, vLLM,
    Together, DeepInfra. Key comes from .env/env via stt.key_env."""
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
        stt.get("prompt", "").encode(),
        f"--{boundary}".encode(),
        b'Content-Disposition: form-data; name="file"; '
        b'filename="utterance.wav"',
        b"Content-Type: audio/wav",
        b"",
        audio,
        f"--{boundary}--".encode(),
        b"",
    ])
    req = urllib.request.Request(
        f"{base}/audio/transcriptions", data=body,
        headers={"Authorization": f"Bearer {key}",
                 "User-Agent": "wisp/1.0",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
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


def ask_jev(transcript: str, model: str, questions: dict,
            context: str = "") -> dict:
    state_txt = f"{context}\n\nThe user said: \"{transcript}\"" \
        if context else f'The user said: "{transcript}"'
    payload = {"model": model, "state": state_txt, "questions": questions}
    req = urllib.request.Request(
        config.JEV_ENDPOINT, data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {config.load_api_key()}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/duketopceo/wisp",
            "X-Title": "Wisp",
        }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Jev HTTP {e.code}: {e.read().decode()[:200]}") \
            from None


def ask_chat(transcript: str, cfg: dict, session_text: str = "",
             image_b64: str | None = None) -> str:
    """Real answer via the configured brain provider ([brain] default).
    image_b64 attaches a screenshot — dropped when the provider lacks
    vision support (U6 capability gating)."""
    from . import brain
    if image_b64 and not brain.supports_vision(cfg):
        image_b64 = None  # provider can't see it — don't attach
    system = ("You are Wisp, a terse desktop voice assistant on Linux. "
              "Answer in one or two short sentences, plain speech, no "
              "markdown.")
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
    return brain.chat(messages, cfg, timeout=30)["content"].strip()


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
        r = subprocess.run(cmd, capture_output=True,
                           timeout=10, env=hypr_env())
        return out if r.returncode == 0 and out.exists() else None
    except Exception:
        return None


def screen_b64(cfg: dict, answers: dict) -> str | None:
    """Attach a screenshot when Jev flags needs_screen or the answer route
    fires — unless screenshots are disabled in config."""
    if cfg.get("agent", {}).get("screenshots", "true") != "true":
        return None
    needs = answers.get("needs_screen", {}).get("noul", 0)
    route = answers.get("route", {}).get("choice")
    if needs < 0.7 and route != "answer":
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


def _end_speaking(state):
    """Flip speaking → done when TTS exits (only if nothing moved on)."""
    def cb():
        if state.status == "speaking":
            state.transition("done")
    return cb


def execute(answers: dict, cfg: dict, harness: dict | None = None,
            detail: str = "", state=None, confirm=None) -> str:
    """Route-aware dispatch. Falls back to the legacy action-based path
    when Jev's response lacks the route question. Jev only answers typed
    questions (noul/choice/score) — free-text args come from the
    transcript via `detail`."""
    from . import agents, tools
    route = answers.get("route", {}).get("choice")
    action = answers.get("action", {}).get("choice")
    app = answers.get("app", {}).get("choice")
    risk = float(answers.get("risk", {}).get("score", 2))
    threshold = float(cfg.get("agent", {}).get("risk_threshold", "1.5"))

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
                  or tools.risk_of(tool_choice) == "safe"):
        gated = False
    if gated and risk > threshold:
        return f"BLOCKED (risk={risk:.2f} > {threshold})"

    if route == "agent":
        return agents.spawn(detail or app or "unnamed task", cfg)
    if route == "act":
        from . import act
        return act.run_act_loop(detail, cfg, state=state,
                                harness=harness, confirm=confirm)
    if route == "dictation":
        # type the spoken words; a leading dictate keyword is a command
        # prefix, not content — strip it
        return tools.run("type_text", dictation_text(detail), cfg)
    if route == "learn":
        from . import act
        prompt = ("Author a reusable skill for this request using the "
                  "skill_manage and skill_view tools. If a skill on this "
                  "topic already exists, view it and fold improvements "
                  "in with edit; otherwise create it. Keep the SKILL.md "
                  "body concise and procedural. Request: " + detail)
        return act.run_act_loop(prompt, cfg, state=state,
                                harness=harness, confirm=confirm)
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
                                    harness=harness, confirm=confirm)
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
        corrected["action"]["choice"] = value
    corrected["corrected_by_user"] = True
    return corrected


def run_listen(cfg: dict, state, wait_for_choice=None,
               wav: pathlib.Path | None = None) -> int:
    """One push-to-talk cycle inside the daemon.

    `wav` set → toggle mode: the daemon already captured audio between
    two presses, so skip recording. `wait_for_choice(timeout)` -> picked
    label or None; injected by the daemon so ambiguous turns resolve via
    IPC/widget clicks. With no chooser wired, low-confidence turns cancel
    rather than guess.
    """
    secs = int(cfg.get("audio", {}).get("seconds", "60"))
    model = cfg.get("agent", {}).get("model", "typesafe/jev-1.13")
    t0 = time.monotonic()
    timing = {}
    from . import trace as _trace
    turn = _trace.new_turn()
    _trace.emit(turn, "listen_start", "lifecycle",
                {"seconds": secs, "model": model})
    try:
        if wav is None:
            state.transition("listening", transcript="", result="",
                             answer="", choices=[], points=[], error="")
            wav = record(secs, state)
        timing["record_ms"] = round((time.monotonic() - t0) * 1000)
        _trace.emit(turn, "record", "stt",
                    {"wav": str(wav),
                     "bytes": wav.stat().st_size if wav.exists() else 0},
                    timing["record_ms"])
        state.transition("transcribing")
        text = transcribe(wav, cfg)
        timing["stt_ms"] = round((time.monotonic() - t0) * 1000
                                 - timing["record_ms"])
        _trace.emit(turn, "transcribe", "stt",
                    {"provider": cfg.get("stt", {}).get("provider", "local"),
                     "text": text}, timing["stt_ms"])
        state.transition("deciding", transcript=text)
        if not text or "[BLANK" in text:
            state.transition("done", result="heard nothing")
            notify("heard nothing")
            return 0
        from .tools import adapters
        harness = {"apps": adapters.best_catalog(),
                   "context": adapters.context()}
        win = active_window()
        context = harness.get("context", "")
        if win.get("title"):
            context += f"\nActive window: {win['class']} — {win['title']}"
        from . import session
        n_turns = int(cfg.get("agent", {}).get("session_turns", "8"))
        session_text = session.as_text(session.tail(n_turns))
        if session_text:
            context += f"\nRecent conversation:\n{session_text}"
        from . import memory
        block = memory.context_block(text)
        if block:
            context += f"\n{block}"
        # router: jev (default) | chat (transcript straight to answer
        # brain) | off (always clarify via choices) — Rust parity
        router = cfg.get("brain", {}).get("router", "jev")
        if router == "chat":
            resp = {"answers": {"route": {"choice": "answer"},
                                "needs_screen": {"noul": 1.0}}}
        elif router == "off":
            resp = {"answers": {"route": {"choice": "clarify"}}}
        else:
            resp = ask_jev(text, model, build_questions(harness),
                           context=context)
        timing["jev_ms"] = round((time.monotonic() - t0) * 1000
                                 - timing["record_ms"] - timing["stt_ms"])
        answers = resp.get("answers", {})
        _trace.emit(turn, "decision", "thought",
                    {"model": model, "answers": answers,
                     "latency_ms": resp.get("latency_ms")},
                    timing["jev_ms"])
        # transcript rescue: "open discord" with app=none shouldn't
        # clarify-prompt — the app name is right there in the words
        if answers.get("app", {}).get("choice", "none") in ("none", "", None):
            fa = fuzzy_app(text, answers)
            if fa:
                answers.setdefault("app", {})["choice"] = fa
        low_conf = is_low_confidence(answers, cfg)
        corrected = None
        if low_conf:
            labels = ambiguous_choices(answers, cfg)
            if wait_for_choice:
                state.transition("awaiting_choice", choices=labels)
                picked = wait_for_choice(60) or auto_pick(answers)
                state.transition("acting", choices=[])
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
            notify(result)
            log_decision({"ts": datetime.now(timezone.utc).isoformat(),
                          "transcript": text, "answers": answers,
                          "result": result, "corrected": False})
            return 0
        if corrected:
            answers = corrected
        state.transition("acting")
        confirm = None
        if wait_for_choice:
            def confirm(prompt: str) -> bool:
                state.transition("awaiting_choice",
                                 choices=[f"{prompt} — yes", "no"])
                pick = wait_for_choice(30)
                state.transition("acting", choices=[])
                return bool(pick) and "yes" in pick
        result = execute(answers, cfg, harness, detail=text,
                         state=state, confirm=confirm)
        _trace.emit(turn, "dispatch", "act",
                    {"route": answers.get("route", {}).get("choice"),
                     "result": result})
        reply = ""
        if result == "ANSWERED":
            pts = []
            try:
                _t = time.monotonic()
                reply = ask_chat(text, cfg, session_text,
                                 image_b64=screen_b64(cfg, answers))
                _trace.emit(turn, "brain_call", "brain",
                            {"endpoint": "chat/completions",
                             "model": cfg.get("agent", {})
                             .get("answer_model", ""),
                             "reply": reply},
                            round((time.monotonic() - _t) * 1000))
            except Exception as e:
                result = f"ANSWER_FAILED ({e})"
                reply = answer_text(text)
            if reply:
                from . import points as _points
                reply, raw = _points.extract(reply)
                if raw:
                    pts = _points.to_logical(raw, _points.monitors())
            if pts:
                _trace.emit(turn, "points", "act", {"points": pts})
            state.transition("speaking", result=result, answer=reply,
                             points=pts)
            _t = time.monotonic()
            proc = speech.speak(reply, cfg)
            _trace.emit(turn, "speak", "tts",
                        {"cmd": cfg.get("voice", {}).get("cmd", ""),
                         "spawned": proc is not None},
                        round((time.monotonic() - _t) * 1000))
            if proc is not None:
                speech.on_exit(proc, _end_speaking(state))
            else:
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
        notify(result)
        timing["act_ms"] = round((time.monotonic() - t0) * 1000)
        log_decision({"ts": datetime.now(timezone.utc).isoformat(),
                      "transcript": text, "answers": answers, "result": result,
                      "timing_ms": timing,
                      "corrected": bool(answers.get("corrected_by_user"))})
        return 0
    except Exception as e:
        _trace.emit(turn, "error", "error", {"error": str(e)})
        state.transition("error", error=str(e))
        log_decision({"ts": datetime.now(timezone.utc).isoformat(),
                      "result": f"ERROR ({e})", "timing_ms": timing})
        notify(f"error: {e}")
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        if state:
            state.set_level(0.0)
