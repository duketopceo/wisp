"""Routing: Jev accelerates, a heuristic router never lets a turn wait
(backend U8, KTD3).

`decide()` computes the heuristic route first (a few microseconds), then
asks Jev under a deadline (`[jev] deadline_ms`, default 400). Jev timing
out, erroring, or answering nonsense yields the heuristic route and the
turn continues; a late Jev reply is discarded. The only time the
heuristic overrides a good Jev answer is a bare single-clause launch of
an app that exists in the catalog ("open firefox"), so a compound
request ("open firefox and go to github") keeps Jev's act route.

Every routed turn appends one record to route_ab.jsonl (Jev vs heuristic
vs final, latencies, agreement) for `wispd eval route`.
"""
import json
import re
import threading
import time
from datetime import datetime, timezone

from . import config

DEFAULT_DEADLINE_MS = 400
DEFAULT_FLASH_DEADLINE_MS = 220
DEFAULT_FLASH_CONFIDENCE = 0.7
DEFAULT_FLASH_MODEL = "perplexity/pplx-decider-flash-v1.2"
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


def _jev_cfg(cfg: dict | None) -> dict:
    return (cfg or {}).get("jev") or {}


def flash_enabled(cfg: dict | None) -> bool:
    return str(_jev_cfg(cfg).get("flash_decider", "")).lower() in \
        ("true", "1", "yes")


def flash_confidence_threshold(cfg: dict | None) -> float:
    try:
        return float(_jev_cfg(cfg).get("flash_confidence",
                                       DEFAULT_FLASH_CONFIDENCE))
    except (TypeError, ValueError):
        return DEFAULT_FLASH_CONFIDENCE


def flash_model(cfg: dict | None) -> str:
    return str(_jev_cfg(cfg).get("flash_model") or DEFAULT_FLASH_MODEL)


def flash_deadline_ms(cfg: dict | None, total_ms: int) -> int:
    """Sub-budget for the flash lane; the remainder is left for Jev.

    Default 220 ms: flash p50 is ~240 ms so many turns accept early; the
    ~180 ms left gives Jev a median shot before the 400 ms wall."""
    try:
        fb = int(_jev_cfg(cfg).get("flash_deadline_ms",
                                    DEFAULT_FLASH_DEADLINE_MS))
    except (TypeError, ValueError):
        fb = DEFAULT_FLASH_DEADLINE_MS
    fb = max(50, fb)
    return min(fb, max(total_ms - 80, 50))


def _decisions_call(text: str, model: str, questions: dict, context: str,
                    cfg: dict | None, timeout: float) -> dict:
    """One OpenRouter /alpha/decisions call (injectable via tests)."""
    state_txt = f"{context}\n\nThe user said: \"{text}\"" \
        if context else f'The user said: "{text}"'
    payload = {"model": model, "state": state_txt, "questions": questions}
    headers = {"Content-Type": "application/json",
               "HTTP-Referer": "https://github.com/duketopceo/wisp",
               "X-Title": "Wisp"}
    endpoint = config.JEV_ENDPOINT
    from . import stage_route as _sr
    if _sr._jev_is_local(endpoint):
        key = config.load_env_key("OPENROUTER_API_KEY")
        if key:
            headers["Authorization"] = f"Bearer {key}"
    else:
        headers["Authorization"] = f"Bearer {config.load_api_key()}"
    req = urllib.request.Request(
        endpoint, data=json.dumps(payload).encode(), headers=headers,
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _try_flash_lane(text: str, context: str, cfg: dict,
                    budget_s: float) -> dict:
    """-> {ok, status, ms, route?, resp?, confidence?}. Never raises."""
    from . import pipeline
    t0 = time.monotonic()
    out = {"ok": False, "status": "skipped", "ms": 0}
    if budget_s <= 0:
        out["status"] = "no_budget"
        return out
    q = {"route": pipeline.JEV_QUESTIONS["route"]}
    try:
        resp = _decisions_call(text, flash_model(cfg), q, context, cfg,
                                 budget_s)
        out["ms"] = round((time.monotonic() - t0) * 1000)
        route = jev_route(resp)
        if route is None:
            out["status"] = "malformed"
            return out
        conf = float(((resp.get("answers") or {}).get("route") or {})
                     .get("confidence") or 0)
        out["route"] = route
        out["confidence"] = conf
        out["resp"] = resp
        if conf < flash_confidence_threshold(cfg):
            out["status"] = "low_confidence"
            return out
        out["ok"] = True
        out["status"] = "ok"
        return out
    except Exception as e:                            # noqa: BLE001
        from . import cancel as _cancel
        if isinstance(e, _cancel.Cancelled):
            raise
        out["ms"] = round((time.monotonic() - t0) * 1000)
        out["status"] = "error"
        return out


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
            "agree": None, "flash_ms": None, "flash_status": None,
            "route_lane": None}

    if flash_enabled(cfg):
        fb_ms = flash_deadline_ms(cfg, dl)
        flash = _try_flash_lane(text, context, cfg, fb_ms / 1000)
        meta["flash_ms"] = flash.get("ms")
        meta["flash_status"] = flash.get("status")
        if flash.get("ok"):
            resp = flash["resp"]
            meta["jev_route"] = flash["route"]
            meta["jev_status"] = "ok"
            meta["agree"] = flash["route"] == h["route"]
            if h["bare_launch"] and flash["route"] != "launch":
                meta["override"] = True
                meta["source"] = "heuristic"
                meta["route_lane"] = "heuristic"
                return {"answers": heuristic_answers(h),
                        "latency_ms": 0}, meta
            meta["source"] = "flash"
            meta["route_lane"] = "flash"
            if spans is not None:
                spans.record("route_flash", spans.now()
                             - int(flash["ms"] * 1e6), status="ok")
            return resp, meta
        if spans is not None and flash.get("ms"):
            spans.record("route_flash", spans.now()
                         - int(flash["ms"] * 1e6),
                         status=flash.get("status"))

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


# -- A/B log ------------------------------------------------------------

def log_ab(meta: dict, text: str, turn: str, final_route: str) -> None:
    """Append one comparison record. Best-effort: logging never fails a
    turn."""
    try:
        h = meta.get("heuristic") or {}
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "turn": turn, "transcript": text,
            "deadline_ms": meta.get("deadline_ms"),
            "jev": {"route": meta.get("jev_route"),
                    "status": meta.get("jev_status", "unknown"),
                    "ms": meta.get("jev_ms"),
                    "code": meta.get("jev_code")},
            "heuristic": {"route": h.get("route"), "rule": h.get("rule"),
                          "app": h.get("app") or None,
                          "ms": h.get("ms")},
            "final": {"route": final_route,
                      "source": meta.get("source", "heuristic")},
            "agree": meta.get("agree"),
            "override": bool(meta.get("override")),
        }
        config.ROUTE_AB.parent.mkdir(parents=True, exist_ok=True)
        with config.ROUTE_AB.open("a") as f:
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")
    except Exception:                                  # noqa: BLE001
        pass


def load_ab(limit: int = 0, path=None) -> list:
    path = path or config.ROUTE_AB
    rows = []
    try:
        for line in path.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        return []
    return rows[-limit:] if limit else rows


def _pct(vals: list, q: float):
    if not vals:
        return None
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(round(q * (len(vals) - 1))))]


def ab_report(rows: list, show: int = 10) -> dict:
    """Summarise route A/B records (what `wispd eval route` prints)."""
    jev = [r.get("jev") or {} for r in rows]
    answered = [r for r in rows if (r.get("jev") or {}).get("route")]
    agreed = [r for r in answered if r.get("agree")]
    status: dict = {}
    for j in jev:
        s = j.get("status", "unknown")
        status[s] = status.get(s, 0) + 1
    src: dict = {}
    for r in rows:
        s = (r.get("final") or {}).get("source", "unknown")
        src[s] = src.get(s, 0) + 1
    ok_ms = [j["ms"] for j in jev if j.get("status") == "ok"
             and isinstance(j.get("ms"), (int, float))]
    h_ms = [(r.get("heuristic") or {}).get("ms") for r in rows]
    h_ms = [m for m in h_ms if isinstance(m, (int, float))]
    dis = [{"ts": r.get("ts"), "turn": r.get("turn"),
            "transcript": r.get("transcript"),
            "jev": r["jev"]["route"],
            "heuristic": (r.get("heuristic") or {}).get("route"),
            "final": (r.get("final") or {}).get("route")}
           for r in answered if r.get("agree") is False]
    n = len(answered)
    return {
        "turns": len(rows), "jev_answered": n, "agreed": len(agreed),
        "agreement": (len(agreed) / n) if n else None,
        "overrides": sum(1 for r in rows if r.get("override")),
        "jev_status": status, "final_source": src,
        "jev_ms": {"p50": _pct(ok_ms, .5), "p90": _pct(ok_ms, .9)},
        "heuristic_ms": {"p50": _pct(h_ms, .5), "p90": _pct(h_ms, .9)},
        "disagreements": dis[-show:],
    }


def ab_text(rep: dict) -> str:
    if not rep["turns"]:
        return "no routed turns logged yet (route_ab.jsonl is empty)"
    n = rep["jev_answered"]
    lines = [f"route A/B, {rep['turns']} turns",
             "  jev status: " + ", ".join(
                 f"{k} {v}" for k, v in sorted(rep["jev_status"].items())),
             "  final from: " + ", ".join(
                 f"{k} {v}" for k, v in sorted(rep["final_source"].items()))]
    ag = "-" if rep["agreement"] is None else f"{rep['agreement']:.0%}"
    lines.append(f"  agree: {rep['agreed']}/{n} ({ag}), "
                 f"{rep['overrides']} heuristic overrides")

    def ms(d):
        return "-" if d["p50"] is None else f"p50 {d['p50']} p90 {d['p90']}"
    lines.append(f"  jev ms: {ms(rep['jev_ms'])}; "
                 f"heuristic ms: {ms(rep['heuristic_ms'])}")
    if rep["disagreements"]:
        lines.append("disagreements (jev -> heuristic, final):")
        for d in rep["disagreements"]:
            lines.append(f"  {d['jev']} -> {d['heuristic']}, {d['final']}"
                         f"  \"{(d['transcript'] or '')[:50]}\"")
    return "\n".join(lines)
