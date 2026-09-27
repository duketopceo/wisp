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
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from . import config

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
            "learn": "the user wants Dim to learn or remember how to do "
                     "something — 'learn X', 'remember this', 'add a "
                     "skill for'",
            "act": "a multi-step desktop task — do several things, or "
                   "imperative instructions like 'open X and go to "
                   "workspace 2' or 'type this into the window'",
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
    """Hyprland tooling needs its instance signature when run from a daemon."""
    env = dict(os.environ)
    if not env.get("HYPRLAND_INSTANCE_SIGNATURE"):
        rd = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        hypr = pathlib.Path(rd) / "hypr"
        if hypr.is_dir():
            env["HYPRLAND_INSTANCE_SIGNATURE"] = sorted(hypr.iterdir())[0].name
    return env


def notify(msg: str) -> None:
    subprocess.run(["notify-send", "Dim", msg], env=hypr_env())


def speak(msg: str, cfg: dict) -> None:
    if cfg.get("voice", {}).get("enabled", "false") != "true":
        return
    bin_ = shutil.which("espeak-ng") or shutil.which("espeak")
    if bin_:
        subprocess.Popen([bin_, msg], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)


def record(seconds: int, state=None) -> pathlib.Path:
    out = config.CFG_DIR / "utterance.wav"
    config.RUN_DIR.mkdir(parents=True, exist_ok=True)
    sampler = threading.Thread(target=_amplitude_sampler,
                               args=(seconds, state), daemon=True)
    sampler.start()
    rec = shutil.which("pw-record") or shutil.which("arecord")
    if rec is None:
        raise RuntimeError("no pw-record or arecord found")
    if rec.endswith("pw-record"):
        cmd = [rec, "--rate", "16000", "--channels", "1", "--format", "s16",
               "--sample-count", str(16000 * seconds), str(out)]
    else:
        cmd = [rec, "-D", "default", "-r", "16000", "-c", "1", "-f", "S16_LE",
               "-d", str(seconds), str(out)]
    # pw-record exits 1 on clean --sample-count shutdown (pipewire 1.6.x);
    # trust the output file, not the exit code.
    subprocess.run(cmd, timeout=seconds + 10, env=hypr_env())
    if not (out.exists() and out.stat().st_size > 44):
        raise RuntimeError(f"recording produced no audio: {out}")
    time.sleep(0.3)
    if state:
        state.set_level(0.0)
    else:
        config.LEVEL_FILE.write_text("0.0")
    return out


def _amplitude_sampler(seconds: int, state=None) -> None:
    """Breathing darkness: sample mic RMS, publish level for the overlay."""
    arec = shutil.which("arecord")
    if not arec:
        return

    def publish(v: float) -> None:
        if state:
            state.set_level(v)
        else:
            config.LEVEL_FILE.write_text(f"{v:.3f}")

    try:
        proc = subprocess.Popen(
            [arec, "-D", "default", "-f", "U8", "-r", "200", "-c", "1",
             "-d", str(seconds)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=hypr_env())
        while True:
            chunk = proc.stdout.read(200)
            if not chunk:
                break
            step = 20
            for i in range(0, len(chunk) - step, step):
                w = chunk[i:i + step]
                rms = sum(abs(b - 128) for b in w) / (len(w) * 128)
                publish(min(1.0, rms * 6))
        proc.wait(timeout=5)
    except Exception:
        try:
            publish(0.0)
        except Exception:
            pass


def transcribe(wav: pathlib.Path, cfg: dict) -> str:
    model = config.whisper_model(cfg)
    if not (config.WHISPER_BIN.exists() and model.exists()):
        raise RuntimeError(f"whisper.cpp missing: {config.WHISPER_BIN} / {model}")
    r = subprocess.run(
        [str(config.WHISPER_BIN), "-m", str(model), "-nt", "-f", str(wav)],
        capture_output=True, text=True, timeout=120)
    return " ".join(r.stdout.split())


def build_questions(harness: dict | None) -> dict:
    """Jev questions with the app catalog rebuilt from the local harness
    and the tool list filled from the registry."""
    from . import tools
    q = json.loads(json.dumps(JEV_QUESTIONS))
    q["tool"]["criteria"] = tools.describe()
    from . import learn
    if not harness or not harness.get("apps"):
        q["app"]["criteria"] = learn.apply_overrides(q["app"]["criteria"])
        return q
    criteria = {
        name: f"{a.get('cues', name)}"
        + (f" (frequently used: {a['seen']}x)" if a.get("seen", 0) >= 5 else "")
        for name, a in harness["apps"].items()
    }
    criteria["none"] = JEV_QUESTIONS["app"]["criteria"]["none"]
    q["app"]["criteria"] = criteria
    from . import learn
    q["app"]["criteria"] = learn.apply_overrides(q["app"]["criteria"])
    return q


def active_window() -> dict:
    if not shutil.which("hyprctl"):
        return {}
    r = subprocess.run(["hyprctl", "activewindow", "-j"],
                       capture_output=True, text=True, env=hypr_env())
    try:
        w = json.loads(r.stdout)
        return {"class": w.get("class", ""), "title": w.get("title", "")}
    except json.JSONDecodeError:
        return {}


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
            "HTTP-Referer": "https://github.com/duketopceo/dim-agent",
            "X-Title": "Dim",
        }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Jev HTTP {e.code}: {e.read().decode()[:200]}") \
            from None


def ask_chat(transcript: str, cfg: dict, session_text: str = "",
             image_b64: str | None = None) -> str:
    """Real answer via an OpenRouter chat model. Jev routes; this answers.
    image_b64 attaches a screenshot for screen-aware replies."""
    model = cfg.get("agent", {}).get("answer_model",
                                    "openai/gpt-4.1-mini")
    system = ("You are Dim, a terse desktop voice assistant on Linux. "
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
    payload = {"model": model, "messages": messages, "max_tokens": 300}
    req = urllib.request.Request(
        config.CHAT_ENDPOINT, data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {config.load_api_key()}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/duketopceo/dim-agent",
            "X-Title": "Dim",
        }, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return (data.get("choices") or [{}])[0].get("message", {}) \
        .get("content", "").strip()


def capture_screen() -> pathlib.Path | None:
    """grim composites ALL outputs to RUN_DIR/screen.png. None on fail."""
    grim = shutil.which("grim")
    if not grim:
        return None
    out = config.RUN_DIR / "screen.png"
    try:
        config.RUN_DIR.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([grim, str(out)], capture_output=True,
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
    gated = route not in ("launch", "answer") and action not in ("launch", "answer")
    if gated and risk > threshold:
        return f"BLOCKED (risk={risk:.2f} > {threshold})"

    if route == "agent":
        return agents.spawn(detail or app or "unnamed task", cfg)
    if route == "act":
        from . import act
        return act.run_act_loop(detail, cfg, state=state,
                                harness=harness, confirm=confirm)
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
        tier = tools.risk_of(tool_name)
        if tier == "shell":
            if tools.denied(detail):
                return "REFUSED (denylisted command)"
            if cfg.get("agent", {}).get("allow_shell", "false") != "true":
                return "BLOCKED (shell tool needs allow_shell=true in config)"
        if tier == "mutating" and risk > threshold:
            return f"BLOCKED (tool {tool_name!r} needs confirmation)"
        if tier == "safe" or risk <= threshold:
            return tools.run(tool_name, detail, cfg, harness)
        return f"BLOCKED (tool {tool_name!r} needs confirmation)"
    if route == "answer" or action == "answer" or app == "none":
        return "ANSWERED"
    if route == "launch" or action == "launch":
        return tools.run("launch", app, cfg, harness)
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


def run_listen(cfg: dict, state, wait_for_choice=None) -> int:
    """One push-to-talk cycle inside the daemon.

    `wait_for_choice(timeout)` -> picked label or None; injected by the
    daemon so ambiguous turns resolve via IPC/widget clicks. With no
    chooser wired, low-confidence turns cancel rather than guess.
    """
    secs = int(cfg.get("audio", {}).get("seconds", "5"))
    model = cfg.get("agent", {}).get("model", "typesafe/jev-1.13")
    t0 = time.monotonic()
    timing = {}
    try:
        state.transition("listening", transcript="", result="", answer="",
                         choices=[], points=[], error="")
        wav = record(secs, state)
        timing["record_ms"] = round((time.monotonic() - t0) * 1000)
        state.transition("transcribing")
        text = transcribe(wav, cfg)
        timing["stt_ms"] = round((time.monotonic() - t0) * 1000
                                 - timing["record_ms"])
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
        resp = ask_jev(text, model, build_questions(harness), context=context)
        timing["jev_ms"] = round((time.monotonic() - t0) * 1000
                                 - timing["record_ms"] - timing["stt_ms"])
        answers = resp.get("answers", {})
        low_conf = is_low_confidence(answers, cfg)
        corrected = None
        if low_conf:
            labels = ambiguous_choices(answers, cfg)
            if wait_for_choice:
                state.transition("awaiting_choice", choices=labels)
                picked = wait_for_choice(60)
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
        reply = ""
        if result == "ANSWERED":
            pts = []
            try:
                reply = ask_chat(text, cfg, session_text,
                                 image_b64=screen_b64(cfg, answers))
            except Exception as e:
                result = f"ANSWER_FAILED ({e})"
                reply = answer_text(text)
            if reply:
                from . import points as _points
                reply, raw = _points.extract(reply)
                if raw:
                    pts = _points.to_logical(raw, _points.monitors())
            state.transition("done", result=result, answer=reply,
                             points=pts)
            speak(reply, cfg)
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
        state.transition("error", error=str(e))
        log_decision({"ts": datetime.now(timezone.utc).isoformat(),
                      "result": f"ERROR ({e})", "timing_ms": timing})
        notify(f"error: {e}")
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        if state:
            state.set_level(0.0)
