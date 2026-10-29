"""Routing: Jev accelerates, a heuristic router never lets a turn wait
(backend U8, KTD3).

`decide()` computes the heuristic route first (a few microseconds), then
asks Jev under a deadline (`[jev] deadline_ms`, default 400). Jev timing
out, erroring, or answering nonsense yields the heuristic route and the
turn continues; a late Jev reply is discarded. The only time the
heuristic overrides a good Jev answer is a bare single-clause launch of
an app that exists in the catalog ("open firefox"), so a compound
request ("open firefox and go to github") keeps Jev's act route.
"""
import re
import threading
import time

DEFAULT_DEADLINE_MS = 400
ROUTES = ("launch", "tool", "agent", "learn", "act", "dictation",
          "answer", "clarify")

_RISK = {"launch": 0, "answer": 0, "dictation": 0, "clarify": 0,
         "tool": 1, "agent": 1, "learn": 1, "act": 2}

# -- heuristic ----------------------------------------------------------

_POLITE = re.compile(
    r"^(?:(?:hey|ok|okay)\s+)?(?:wisp[,:]?\s+)?"
    r"(?:(?:can|could|would|will)\s+you\s+)?(?:please\s+)?", re.I)
_DICTATE = re.compile(
    r"^(?:dictate|dictation|take dictation|type this|write this down|"
    r"write down)\b", re.I)
_AGENT = re.compile(
    r"^(?:have an agent|spawn (?:an? )?agent|delegate\b|agent[:,])", re.I)
_LEARN = re.compile(
    r"^(?:learn (?:how|to|that)\b|remember (?:this|how|that)\b|"
    r"add a skill\b|save (?:this )?as (?:my |a )?.{0,40}?\broutine\b|"
    r"create a routine\b)", re.I)
_WH = re.compile(
    r"^(?:what|what's|whats|who|whom|whose|when|where|why|how|which|"
    r"is|are|am|was|were|do|does|did|should|tell me|explain|define|"
    r"summari[sz]e|describe|give me)\b", re.I)
_SCREENSHOT = re.compile(r"\bscreenshot\b", re.I)
_WORKSPACE = re.compile(
    r"^(?:go to|switch to|move to|jump to)\s+workspace\s+\d+\b", re.I)
_LAUNCH = re.compile(
    r"^(?:open|launch|start|run|pull up|bring up|switch to|focus)\s+"
    r"(?P<rest>.+)$", re.I)
_ACT = re.compile(
    r"^(?:click|scroll|go to|navigate|search(?: for)?|find|type|press|"
    r"select|fill|close|quit|drag|play|pause|download|log ?in|sign in|"
    r"open)\b|\b(?:and then|then)\b", re.I)
_FILLER = re.compile(r"\b(?:the|app|application|up)\b", re.I)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _catalog_app(rest: str, apps: dict) -> str:
    want = _norm(_FILLER.sub(" ", rest))
    if not want:
        return ""
    for name in apps or {}:
        if _norm(name) == want:
            return name
    return ""


def _is_compound(rest: str) -> bool:
    return bool(re.search(r"\b(?:on|in|to|at|for|into|and|then|with)\s+\S",
                          rest, re.I))


def heuristic(text: str, apps: dict | None = None) -> dict:
    """Deterministic route from the transcript and the app catalog.
    -> {route, rule, app, tool, bare_launch}. Never raises."""
    t0 = time.perf_counter()
    out = _heuristic(text or "", apps or {})
    out["ms"] = round((time.perf_counter() - t0) * 1000, 2)
    return out


def _result(route, rule, app="", tool="", bare=False):
    return {"route": route, "rule": rule, "app": app, "tool": tool,
            "bare_launch": bare}


def _heuristic(text: str, apps: dict) -> dict:
    t = text.strip().rstrip(".!")
    t = _POLITE.sub("", t).strip()
    if not t or t.startswith("[") or not re.search(r"\w", t):
        return _result("clarify", "empty")
    if _DICTATE.match(t):
        return _result("dictation", "dictate_verb")
    if _AGENT.match(t):
        return _result("agent", "agent_verb")
    if _LEARN.match(t):
        return _result("learn", "learn_verb")
    if _WH.match(t):
        return _result("answer", "question_word")
    if _WORKSPACE.match(t):
        return _result("tool", "workspace", tool="workspace")
    if _SCREENSHOT.search(t):
        return _result("tool", "screenshot", tool="screenshot")
    m = _LAUNCH.match(t)
    if m:
        rest = m.group("rest")
        app = _catalog_app(rest, apps)
        if app and not _is_compound(rest):
            return _result("launch", "bare_launch", app=app, bare=True)
        return _result("act", "launch_compound" if app else "launch_unknown")
    if _ACT.search(t):
        return _result("act", "act_verb")
    if t.endswith("?"):
        return _result("answer", "question_mark")
    return _result("answer", "default_answer")


def heuristic_answers(h: dict) -> dict:
    """Jev-shaped `answers` so the rest of the pipeline cannot tell."""
    conf = 0.95 if h["bare_launch"] else 0.7
    ans = {"route": {"choice": h["route"], "confidence": conf},
           "app": {"choice": h["app"] or "none", "confidence": conf},
           "risk": {"score": _RISK.get(h["route"], 2)}}
    if h["tool"]:
        ans["tool"] = {"choice": h["tool"]}
    return ans


# -- Jev under a deadline ----------------------------------------------

def deadline_ms(cfg: dict | None) -> int:
    try:
        v = int(((cfg or {}).get("jev") or {}).get("deadline_ms",
                                                   DEFAULT_DEADLINE_MS))
        return v if v > 0 else DEFAULT_DEADLINE_MS
    except (TypeError, ValueError):
        return DEFAULT_DEADLINE_MS


def jev_route(resp) -> str | None:
    """The route a Jev reply picked, or None when the reply is not a
    usable decision. A legacy reply with only an `action` choice is
    accepted (the pipeline still dispatches it)."""
    ans = resp.get("answers") if isinstance(resp, dict) else None
    if not isinstance(ans, dict):
        return None
    r = ans.get("route")
    choice = r.get("choice") if isinstance(r, dict) else None
    if choice in ROUTES:
        return choice
    a = ans.get("action")
    if isinstance(a, dict) and a.get("choice") and not choice:
        return str(a["choice"])
    return None


def _effective(resp: dict, route: str) -> str:
    """Jev saying route=tool with tool=launch is a launch."""
    tool = ((resp.get("answers") or {}).get("tool") or {}).get("choice")
    return "launch" if route == "tool" and tool == "launch" else route


def _ask(box: dict, done: threading.Event, args: tuple) -> None:
    from . import pipeline
    t0 = time.monotonic()
    try:
        box["resp"] = pipeline.ask_jev(*args[:4], cfg=args[4])
    except BaseException as e:                        # noqa: BLE001
        box["err"] = e
    box["ms"] = round((time.monotonic() - t0) * 1000)
    done.set()


def _finish_from_jev(resp, meta, h):
    """Shared tail: bare-launch override or keep Jev's answer."""
    jr = meta["jev_route"]
    eff = _effective(resp, jr)
    meta["agree"] = eff == h["route"]
    if h["bare_launch"] and eff != "launch":
        meta["override"] = True
        meta["source"] = "heuristic"
        meta["route_lane"] = "heuristic"
        return {"answers": heuristic_answers(h),
                "latency_ms": resp.get("latency_ms", 0)}, meta
    meta["source"] = "jev"
    meta["route_lane"] = "jev"
    return resp, meta


def decide(text: str, model: str, questions: dict, context: str,
           cfg: dict, apps: dict | None = None, spans=None):
    """-> (resp, meta). `resp` is a Jev-shaped {"answers": ...}; `meta`
    carries what the A/B log and trace need. Blocks at most the
    deadline (plus the heuristic's microseconds)."""
    from . import errors_codes as _ec
    dl = deadline_ms(cfg)
    t_start = time.monotonic()
    h = heuristic(text, apps)
    if spans is not None:
        spans.record("route_heuristic", spans.now() - int(h["ms"] * 1e6))
    meta = {"deadline_ms": dl, "jev_ms": None, "jev_route": None,
            "jev_code": None, "heuristic": h, "override": False,
            "agree": None, "route_lane": None}

    box: dict = {}
    done = threading.Event()
    threading.Thread(target=_ask, daemon=True, name="jev-ask",
                     args=(box, done, (text, model, questions, context,
                                       cfg))).start()
    remaining = max(dl / 1000 - (time.monotonic() - t_start), 0)
    finished = done.wait(remaining)
    jev_ms = box.get("ms") if finished else round(
        (time.monotonic() - t_start) * 1000)
    meta["jev_ms"] = jev_ms
    resp = box.get("resp")
    if not finished:
        meta["jev_status"] = "timeout"
    elif "err" in box:
        e = box["err"]
        from . import cancel as _cancel
        if isinstance(e, _cancel.Cancelled):
            raise e
        meta["jev_status"] = "error"
        meta["jev_code"] = _ec.classify(e, "jev_down").code
    elif jev_route(resp) is None:
        meta["jev_status"] = "malformed"
    else:
        meta["jev_status"] = "ok"
    if spans is not None:
        spans.record("route_jev", spans.now() - int(jev_ms * 1e6),
                     status=meta.get("jev_status"))
    if meta.get("jev_status") != "ok":
        meta["source"] = "heuristic"
        meta["route_lane"] = "heuristic"
        return {"answers": heuristic_answers(h), "latency_ms": 0}, meta
    meta["jev_route"] = jev_route(resp)
    return _finish_from_jev(resp, meta, h)
