"""Route stage: ask Jev (or the heuristic router), rescue the decision,
clarify when unsure.

Second of the four turn stages. Public names are re-exported from
wisp.pipeline; names that tests patch as `pipeline.<name>` are resolved
through `_pl()` at call time.
"""
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from . import cancel as _cancel
from . import config
from . import state as _state


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
    q["app"]["criteria"] = criteria
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
        headers["Authorization"] = f"Bearer {config.load_api_key()}"
    req = urllib.request.Request(
        endpoint, data=json.dumps(payload).encode(), headers=headers,
        method="POST")
    for attempt in (1, 2):
        try:
            with _cancel.urlopen(req, timeout=30) as resp:
                out = json.loads(resp.read())
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
    r"pull up|show me(?!\s+(?:what|what's|whats|why|how|where|which)\b))\s+"
    r"(?:up\s+)?(?:the\s+)?(?:app\s+)?([\w .+~/-]+)",
    re.IGNORECASE)
_DEICTIC_TARGET = re.compile(r"\b(?:this|that|these|those|here)\b", re.I)


def fuzzy_app(text: str, answers: dict) -> str:
    """Pull an app name out of 'open discord' when Jev picks none.
    Matches against the probability keys Jev was choosing among —
    normalized ('day flow' matches 'dayflow'), substring then difflib."""
    m = _OPEN_VERB.search(text)
    if not m:
        return ""
    raw_target = m.group(1).strip().rstrip(".")
    if _DEICTIC_TARGET.search(raw_target):
        return ""
    want = re.sub(r"[\s._-]+", "", raw_target).lower()
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


_COMPLEX_LAUNCH = re.compile(
    r"\b(?:(on|in|to|at|for|into|and)\s+\S|this\b|that\b|these\b|those\b|here\b)",
    re.I)
_LAUNCH_VERBS = ("open", "launch", "start", "go to", "pull up",
                 "bring up", "switch to")


def complex_launch(text: str) -> bool:
    """'open discord' → False (plain launch); 'open X on the Y page',
    'open up this setting', or 'open A and B' → True (multi-step or
    on-screen deictic target, belongs in act)."""
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
    from . import confirm as _confirm
    aid, pid, pick = _confirm.park_prompt(
        state, wait_for_choice, token, kind,
        ", ".join(options) or "clarify", list(options), timeout)
    if pick and pick not in options:
        _state.action_set(state, aid, status="failed", reason="rejected")
        _trace.emit(turn, "choice_rejected", "act",
                    {"kind": kind, "pick": pick, "prompt_id": pid,
                     "offered": list(options)})
        return None
    _state.action_set(
        state, aid,
        status="done" if pick else "cancelled",
        reason=pick or ("interrupted" if token.cancelled else "timeout"))
    return pick


def fixed_route(text: str, router: str):
    """Routes decided without the Jev hop, as (choice, detail); None
    means ask route.decide. An explicit 'wisp agent ...' prefix wins,
    then router off; a voice-taught routine utterance goes to learn
    under every other router, so it still works when router = act."""
    from . import routines
    agent_m = re.match(r"^\s*wisp\s+agent[:,.\s-]+(.*)$", text,
                       re.IGNORECASE)
    if agent_m and agent_m.group(1).strip():
        # explicit agent mode — skip Jev, straight to the
        # computer-use loop with the trigger screenshot
        return "act", agent_m.group(1).strip()
    if router == "off":
        return "clarify", None
    if routines.parse_teach_intent(text) is not None:
        return "learn", text
    from . import agent_home, voice_settings, walkthrough_run
    named = agent_home.route_for(text)
    if named:
        return named
    speed = voice_settings.intent(text)
    if speed:
        return "setting", voice_settings.PREFIX + speed
    caps = voice_settings.captions_intent(text)
    if caps:
        return "setting", voice_settings.CAPTIONS_PREFIX + caps
    from . import selfknow
    own = selfknow.intent(text)
    if own:
        return "setting", selfknow.PREFIX + own     # local state, no model
    lesson = walkthrough_run.lesson_intent(text)
    if lesson:
        pre = walkthrough_run.SAVE_PREFIX if lesson[0] == "save" \
            else walkthrough_run.REPLAY_PREFIX
        return "walkthrough", pre + lesson[1]
    if walkthrough_run.resume_intent(text) and walkthrough_run.paused():
        return "walkthrough", walkthrough_run.RESUME_PREFIX
    demo = walkthrough_run.demo_intent(text)
    if demo:
        return "walkthrough", walkthrough_run.DEMO_PREFIX + demo
    goal = walkthrough_run.walk_intent(text)
    if goal:
        return "walkthrough", goal   # a spoken, pointed lesson
    if router == "act":
        return "act", None
    if router == "chat":
        return "answer", None
    return None


# words that make a question an action request in disguise ("how do I
# open X and click Y"): such turns stay with the act loop
_FAST_ACTION = re.compile(
    r"\b(?:click|open|launch|start|run|type|press|close|quit|go to|"
    r"navigate|search|find|download|play|pause|scroll|drag|fill|select|"
    r"log ?in|sign in|then|and)\b", re.I)

_FAST_MEDIA_RE = re.compile(
    r"^\s*(?:please\s+)?"
    r"(?:"
    r"(?P<pause>pause(?:\s+(?:the\s+)?(?:music|video|song|track|audio|playback|media|youtube|spotify))?)"
    r"|(?P<play>(?:resume|unpause)(?:\s+(?:the\s+)?(?:music|video|song|track|audio|playback|media|youtube|spotify))?|play\s+(?:the\s+)?(?:music|video|song|track|audio|playback|media))"
    r"|(?P<next>(?:next|skip)(?:\s+(?:the\s+)?(?:song|track|video|media))?)"
    r"|(?P<previous>(?:previous|prev)(?:\s+(?:the\s+)?(?:song|track|video|media))?)"
    r"|(?P<mute>(?:mute|unmute)(?:\s+(?:the\s+)?(?:audio|volume|sound|speaker|speakers))?)"
    r"|(?P<volume_up>volume\s+up|turn\s+(?:it\s+|the\s+volume\s+)?up|louder)"
    r"|(?P<volume_down>volume\s+down|turn\s+(?:it\s+|the\s+volume\s+)?down|quieter)"
    r")\s*[.!?]*\s*$",
    re.I,
)


def media_fast_arg(text: str) -> str | None:
    """Return canonical `tools.media` arg ('pause', 'play', 'next',
    'previous', 'mute', 'volume_up', 'volume_down') for bare media
    utterances, or None when the utterance is compound/ambiguous."""
    t = str(text or "").strip()
    if not t or " and " in t.lower() or " then " in t.lower():
        return None
    m = _FAST_MEDIA_RE.match(t)
    if not m:
        return None
    for k, v in m.groupdict().items():
        if v:
            return k
    return None


def fast_route(text: str, apps: dict | None, cfg: dict):
    """The no-model fast path in front of act: (answers, rule) for a
    bare launch of a catalogued app ("open firefox"), a bare media
    control ("pause youtube", "next track", "mute"), or a plain question
    ("what does this error mean"); None sends the turn to the act loop.

    Everything ambiguous (compound requests, unknown apps, questions that
    carry an action verb) is left to act. `[brain] fast_path = "false"`
    turns the path off."""
    if str((cfg or {}).get("brain", {}).get("fast_path",
                                            "true")).lower() == "false":
        return None
    m_arg = media_fast_arg(text)
    if m_arg:
        return ({
            "route": {"choice": "tool", "confidence": 0.99},
            "action": {"choice": "media", "confidence": 0.99},
            "tool": {"choice": "media", "confidence": 0.99},
            "app": {"choice": "none", "confidence": 0.99},
            "risk": {"score": 1.0},
            "media_arg": m_arg,
        }, "bare_media")
    from . import route as _route
    h = _route.heuristic(text, apps)
    if h["rule"] == "bare_launch":
        return _route.heuristic_answers(h), h["rule"]
    if h["rule"] in ("question_word", "question_mark") \
            and not _FAST_ACTION.search(text):
        return _route.heuristic_answers(h), h["rule"]
    return None


def route_stage(ctx) -> bool:
    """Decide the route. False when the turn ended here (low confidence
    and no pick): it is already finished."""
    from . import trace as _trace
    from . import route as _route
    pl, state, sp, cfg, text = _pl(), ctx.state, ctx.sp, ctx.cfg, ctx.text
    turn, token, model = ctx.turn, ctx.token, ctx.model
    harness, context = ctx.harness, ctx.context
    # router: act (default; every turn straight to the conversational
    # agent loop — no decision hop, the loop's brain decides
    # answer-vs-work with the trigger screenshot) | jev (decision API) |
    # chat (transcript straight to answer brain) | off (always
    # clarify via choices) — Rust parity
    sp.record("context", sp.mark_ns("stt"))
    route_start = sp.now()
    route_meta = None
    router = cfg.get("brain", {}).get("router", "act")
    fixed = fixed_route(text, router)
    fast_rule = None
    if fixed == ("act", None) and router == "act":
        fast = fast_route(text, harness.get("apps"), cfg)
        if fast:
            fixed, fast_rule = None, fast[1]
            resp = {"answers": fast[0]}
            if fast[0].get("media_arg"):
                ctx.detail = fast[0]["media_arg"]
    if fixed:
        choice, detail = fixed
        if detail:
            ctx.detail = detail
        resp = {"answers": {"route": {"choice": choice}}}
    elif fast_rule:
        ctx.route_lane = "fast_path"
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
                 **({"route_lane": "fast_path", "route_rule": fast_rule}
                    if fast_rule else {}),
                 **({"route_source": route_meta["source"],
                     "jev_status": route_meta["jev_status"],
                     "route_lane": route_meta.get("route_lane")}
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
        ctx.route_lane = route_meta.get("route_lane") or route_meta.get(
            "source")
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
                         "turn": turn, "transcript": text,
                         "answers": answers,
                         "result": result, "corrected": False})
        ctx.result = result
        return False
    ctx.answers = corrected if corrected else answers
    return True
