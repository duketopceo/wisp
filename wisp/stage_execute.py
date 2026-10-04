"""Execute stage: dispatch the routed turn to a tool, the act loop, an
agent or a dictation insert.

Third of the four turn stages. Public names are re-exported from
wisp.pipeline.
"""
import re


def _pl():
    """wisp.pipeline, resolved late (patch targets live there)."""
    from . import pipeline
    return pipeline


_DICTATE_PREFIX = re.compile(
    r"^\s*(please\s+)?(dictate|dictation|take dictation|type this|"
    r"type|write this down|write down)[:,.\s—-]+",
    re.IGNORECASE)


def dictation_text(text: str) -> str:
    """Strip a leading dictate command prefix; keep the rest verbatim."""
    return _DICTATE_PREFIX.sub("", text, count=1).strip() or text


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


def execute_stage(ctx) -> None:
    """Run the dispatch for this turn; sets ctx.result."""
    from . import trace as _trace
    pl, state, cfg, token = _pl(), ctx.state, ctx.cfg, ctx.token
    answers = ctx.answers
    state.transition("acting")
    confirm = None
    if ctx.wait_for_choice:
        from . import confirm as _confirm
        confirm = _confirm.make(state, ctx.wait_for_choice, token,
                                ctx.turn, cfg)
    from . import brain as _brain
    act_img = ctx.shot_b64 if ctx.shot_b64 and \
        _brain.supports_vision(cfg) else None
    result = ctx.result = pl.execute(
        answers, cfg, ctx.harness, detail=ctx.detail, state=state,
        confirm=confirm, initial_image=act_img,
        interrupted=ctx.interrupted)
    _trace.emit(ctx.turn, "dispatch", "act",
                {"route": answers.get("route", {}).get("choice"),
                 "result": result})
    if result.startswith("INTERRUPTED"):
        token.cancel()   # `interrupted()` fired before the watcher
    token.check()
    if ctx.corr:
        from . import learn as _learn
        _learn.record_retry(ctx.corr["prior_ref"], result)
