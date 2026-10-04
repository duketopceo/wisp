"""Route stage: ask Jev (or the heuristic router), rescue the decision,
clarify when unsure.

Second of the four turn stages. Public names are re-exported from
wisp.pipeline; names that tests patch as `pipeline.<name>` are resolved
through `_pl()` at call time.
"""
import json
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from . import cancel as _cancel
from . import config


def _pl():
    """wisp.pipeline, resolved late (patch targets live there)."""
    from . import pipeline
    return pipeline


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


def build_questions(harness: dict | None) -> dict:
    """Jev questions with the app catalog rebuilt from the local harness
    and the tool list filled from the registry."""
    from . import tools
    q = json.loads(json.dumps(_pl().JEV_QUESTIONS))
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
            _pl()._shadow_decision(transcript, state_txt, questions, cfg,
                                   out, model)
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
        target=_pl()._shadow_worker,
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
        "agree": _pl()._shadow_agree(primary, shadow),
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


def is_low_confidence(answers: dict, cfg: dict) -> bool:
    """Gate on app/target confidence — action confidence no longer kills
    correct launches (the 'retro-large' bug). Launch is a whitelisted
    action: high app confidence + acceptable risk executes regardless of
    how Jev scored the action question."""
    app_conf = answers.get("app", {}).get("confidence", 1)
    thresh = float(cfg.get("agent", {}).get("confidence_ambiguous", "0.8"))
    return app_conf < thresh


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


def route_stage(ctx) -> bool:
    """Decide the route. False when the turn ended here (low confidence
    and no pick): it is already finished."""
    from . import trace as _trace
    from . import route as _route
    pl, state, sp, cfg, text = _pl(), ctx.state, ctx.sp, ctx.cfg, ctx.text
    turn, token, model = ctx.turn, ctx.token, ctx.model
    harness, context = ctx.harness, ctx.context
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
        ctx.detail = agent_m.group(1).strip()
        resp = {"answers": {"route": {"choice": "act"}}}
    elif router == "chat":
        resp = {"answers": {"route": {"choice": "answer"}}}
    elif router == "off":
        resp = {"answers": {"route": {"choice": "clarify"}}}
    else:
        resp, route_meta = _route.decide(
            text, model, pl.build_questions(harness), context, cfg,
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
        if ctx.wait_for_choice:
            picked = _ask_prompt(state, ctx.wait_for_choice, token,
                                 labels, 60, turn, "clarify") \
                or auto_pick(answers)
            token.check()
            if picked:
                corrected = apply_choice(answers, picked)
                from . import learn, recall as _recall
                learn.record_correction(text, picked, answers)
                from . import bgwriter
                bgwriter.submit(_recall.index_correction,
                                {"heard": text, "picked": picked})
    if low_conf and not corrected:
        result = "CANCELLED (low confidence, no pick made)"
        state.transition("done", result=result)
        pl.notify(result, "attention", **pl._toast_ctx(state, turn, cfg))
        pl.log_decision({"ts": datetime.now(timezone.utc).isoformat(),
                         "transcript": text, "answers": answers,
                         "result": result, "corrected": False})
        ctx.result = result
        return False
    ctx.answers = corrected if corrected else answers
    return True
