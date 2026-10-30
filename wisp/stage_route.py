"""Local fast paths plus conversational dispatch; no decision-model hop.

Second of the four turn stages. Public names are re-exported from
wisp.pipeline.
"""
import re

def fixed_route(text: str, router: str):
    """Routes decided locally, as (choice, detail).
    An explicit 'wisp agent ...' prefix wins,
    then router off; a voice-taught routine utterance goes to learn
    under every other router, so it still works when router = act."""
    # Saved `router=jev` and unknown old values are compatibility inputs,
    # never permission to resurrect the retired decision endpoint.
    router = router if router in ("act", "chat", "off") else "act"
    from . import routines
    agent_m = re.match(r"^\s*wisp\s+agent[:,.\s-]+(.*)$", text,
                       re.IGNORECASE)
    if agent_m and agent_m.group(1).strip():
        # explicit agent mode — straight to the
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
    r"navigate|search|find|download|play|pause|resume|unpause|skip|"
    r"mute|unmute|turn\s+(?:it\s+|(?:the\s+)?volume\s+)?(?:up|down)|"
    r"scroll|drag|fill|select|"
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
    """Route locally; ambiguous work stays in the conversational act loop."""
    from . import trace as _trace
    sp, cfg, text = ctx.sp, ctx.cfg, ctx.text
    turn, token = ctx.turn, ctx.token
    harness = ctx.harness or {}
    sp.record("context", sp.mark_ns("stt"))
    route_start = sp.now()
    router = cfg.get("brain", {}).get("router", "act")
    router = router if router in ("act", "chat", "off") else "act"
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
        ctx.route_lane = router
    else:
        ctx.route_lane = "fast_path"
    token.check()
    sp.record("route", route_start)
    sp.arm("first_token", sp.mark_ns("route"))
    sp.arm("first_step", sp.mark_ns("route"))
    answers = resp.get("answers", {})
    _trace.emit(turn, "decision", "thought",
                {"answers": answers,
                 **({"route_lane": "fast_path", "route_rule": fast_rule}
                    if fast_rule else {"route_lane": ctx.route_lane})},
                sp.ms["context"] + sp.ms["route"])
    ctx.answers = answers
    return True
