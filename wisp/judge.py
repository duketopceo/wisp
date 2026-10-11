"""Jev-as-judge: a cheap structured pass grading an act run.

Separate from the planner: the act loop answers "what do I do next",
the judge answers "did it work and was it optimal". Runs through the
same OpenRouter decisions endpoint as ask_jev with its own question
set — one call per task, ~50ms class.

Honest degradation (U7): the `[clicklab] judge` key picks the judge —
"jev" (default) tries the decisions endpoint first and falls back to a
cheap brain.chat call with the same verdict schema; "brain" skips Jev;
"off" judges by the harness oracle alone. When every judge is down the
run is marked `judged: False` (`by: "none"`) — unjudged runs never
count toward recipe promotion in wisp/train.py.
"""
import json
import re

from . import config
from . import pipeline

# who owns the failure — the verdict classification wisp/train.py's
# failure buckets count (plus "none" for clean runs)
FAILURE_CLASSES = ("model", "environment", "tool", "judge")

JUDGE_QUESTIONS = {
    "success": {
        "type": "choice",
        "instructions": "Did the run accomplish the user's task? Judge "
                        "against the stated ground truth first; the "
                        "agent's own narration is NOT evidence.",
        "criteria": {
            "yes": "task verified complete",
            "partial": "progress made but the task is not fully done",
            "no": "task failed or the agent only claimed success",
        },
    },
    "efficiency": {
        "type": "score",
        "instructions": "How optimal was the action sequence? A single "
                        "correct tool call that lands IS optimal (3). "
                        "0 wasteful (wrong tools, failed retries, or "
                        "steps unrelated to the task), 1 workable but "
                        "with clear waste, 2 clean but with a minor "
                        "extra step, 3 optimal — fewest correct steps, "
                        "right tools, no re-aims.",
        "criteria": ["wasteful", "workable", "clean", "optimal"],
    },
    "failure_class": {
        "type": "choice",
        "instructions": "When the run did not succeed, who owns the "
                        "failure? model = the agent aimed or planned "
                        "wrong (bad click, wrong tool, no plan). "
                        "environment = the page, VM, driver or harness "
                        "broke — errors outside the agent's control. "
                        "tool = an action executed but had no effect "
                        "(input delivery refused or swallowed). "
                        "judge = the evidence is too thin to tell.",
        "criteria": {
            "none": "the run succeeded",
            "model": "the agent aimed or planned wrong",
            "environment": "page/driver/harness broke",
            "tool": "an executed action had no effect",
            "judge": "cannot tell from the evidence",
        },
    },
    "waste": {
        "type": "choice",
        "instructions": "If the run was not optimal, what wasted effort?",
        "criteria": {
            "none": "the run was optimal or near it",
            "extra_steps": "more steps than the task needed",
            "wrong_tool": "used a tool that could not accomplish the step",
            "re_aim": "click/move aimed at the wrong element and retried",
            "no_focus": "typed/keyed without focusing the target first",
            "unneeded_observe": "screenshots/observes that weren't needed",
            "stalled": "model narrated instead of calling tools",
        },
    },
    "first_fault": {
        "type": "score",
        "instructions": "Which numbered step was the EARLIEST wrong, "
                        "wasteful, or unnecessary action? 0 = none (the "
                        "run was clean or failed for reasons outside "
                        "the agent's actions). Score = step number.",
        # Jev caps score criteria at 10: none + steps 1-8 + "9 or later"
        "criteria": (["none"] + [f"step {i}" for i in range(1, 9)]
                     + ["step 9 or later"]),
    },
}

# score-type answers come back as numeric score → normalize to 0..1
_EFF_SCALE = [0.0, 0.34, 0.67, 1.0]
_OK = {"yes": True, "partial": None, "no": False}
_WASTES = {c for c in JUDGE_QUESTIONS["waste"]["criteria"]}

# brain-fallback prompt: one strict JSON object, same schema the Jev
# question set produces. Kept short — the fallback is the cheap call.
_BRAIN_PROMPT = """You are the run judge for a GUI agent. Reply with ONLY
one compact JSON object (no prose, no markdown):
{"success": true|false|null, "failure_class": "model"|"environment"|"tool"|"judge"|null, "efficiency": 0..1, "waste": "none|extra_steps|wrong_tool|re_aim|no_focus|unneeded_observe|stalled", "first_fault": 0-based index of the earliest wrong step or -1}
failure_class: model = agent aimed/planned wrong; environment = page/VM/driver broke; tool = action ran but had no effect; judge = evidence ambiguous."""


def verdict(task: str, steps: list, outcome: str, cfg: dict,
            verified: bool | None = None,
            evidence: dict | None = None) -> dict:
    """Grade one act run. `verified` is the harness's own ground truth
    (scoreboard check) — the judge reconciles it against the step list.
    `evidence` may add {"state": final DOM/score dump, "image": b64 png}
    — state joins the judge's evidence text; the image rides the brain
    fallback when that provider sees pixels.

    `[clicklab] judge`: "jev" (default) → Jev, brain fallback; "brain"
    → brain only; "off" → the oracle verdict alone counts."""
    mode = str(cfg.get("clicklab", {}).get("judge", "jev")).lower()
    if mode == "off":
        return _oracle(verified)
    state = _state_text(task, steps, outcome, verified, evidence)
    errs = []
    if mode != "brain":
        model = cfg.get("agent", {}).get("model", "typesafe/jev-1.13")
        try:
            return _from_answers(pipeline.ask_jev(state, model,
                                                JUDGE_QUESTIONS),
                                 len(steps), by="jev")
        except Exception as e:
            errs.append(f"jev: {e}")
    try:
        v = _brain_verdict(state, cfg, evidence, nsteps=len(steps))
        v["fallback_from"] = "jev" if errs else None
        return v
    except Exception as e:
        errs.append(f"brain: {e}")
        return _unjudged("; ".join(errs))


def _state_text(task: str, steps: list, outcome: str,
                verified: bool | None, evidence: dict | None) -> str:
    step_lines = "\n".join(
        f"  {i+1}. {s.get('tool')} {s.get('arg', '')[:60]} → "
        f"{s.get('result', '')[:60]}"
        for i, s in enumerate(steps)) or "  (no tool calls)"
    state = (
        f"Task: {task}\n"
        f"Agent steps:\n{step_lines}\n"
        f"Agent's reported outcome: {outcome[:160]}\n"
        f"Automated verifier: "
        f"{'PASS' if verified else 'FAIL' if verified is False else 'N/A'}")
    extra = str((evidence or {}).get("state") or "")
    if extra:
        state += f"\nFinal page state:\n{extra[:1500]}"
    return state


def _oracle(verified: bool | None) -> dict:
    """`judge = off`: the scoreboard verdict alone — it is still
    evidence-based, so the run counts (for or against) normally."""
    return {"success": bool(verified) if verified is not None else None,
            "efficiency": None, "first_fault": -1,
            "failure_class": None, "waste": "none",
            "by": "oracle", "judged": True, "raw": {}}


def _unjudged(note: str) -> dict:
    """Every judge failed — mark it, never count it (train._run_ok
    treats judged=False as neutral, not a pass)."""
    return {"success": None, "efficiency": None, "first_fault": -1,
            "failure_class": None, "waste": "judge_error",
            "by": "none", "judged": False, "note": note[:160],
            "raw": {}}


def _from_answers(resp: dict, nsteps: int, by: str) -> dict:
    answers = resp.get("answers") or {}
    succ = str((answers.get("success") or {}).get("choice", "")).lower()
    eff_raw = (answers.get("efficiency") or {}).get("score")
    try:
        eff = _EFF_SCALE[min(3, max(0, int(float(eff_raw))))] \
            if eff_raw is not None else None
    except (TypeError, ValueError):
        eff = None
    waste = str((answers.get("waste") or {}).get("choice", "")).lower()
    fc = str((answers.get("failure_class") or {})
             .get("choice", "")).lower()
    ff_raw = (answers.get("first_fault") or {}).get("score")
    try:
        # criteria index: 0 = none → -1; score i → 0-indexed step i-1
        ff = int(float(ff_raw)) - 1 if ff_raw is not None else -1
        ff = max(-1, min(ff, nsteps - 1))
    except (TypeError, ValueError):
        ff = -1
    return {"success": _OK.get(succ),
            "efficiency": eff,
            "first_fault": ff,
            "failure_class": fc if fc in FAILURE_CLASSES else None,
            "waste": waste if waste in _WASTES else "none",
            "by": by, "judged": True,
            "raw": answers}


def _brain_verdict(state: str, cfg: dict,
                   evidence: dict | None, nsteps: int = 0) -> dict:
    """Cheap brain.chat fallback emitting the same verdict schema."""
    from . import brain
    user = state
    img = (evidence or {}).get("image")
    if img and brain.supports_vision(cfg):
        user = [{"type": "text", "text": state},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{img}"}}]
    resp = brain.chat([{"role": "system", "content": _BRAIN_PROMPT},
                       {"role": "user", "content": user}],
                      cfg, timeout=30)
    txt = resp.get("content", "") if isinstance(resp, dict) \
        else str(resp)
    v = _parse_verdict_json(txt, nsteps)
    v["by"] = "brain"
    v["judged"] = True
    v["raw"] = {"content": txt[:400]}
    return v


_TRUE = {"true", "yes", "ok", "pass", "success"}
_FALSE = {"false", "no", "fail", "failure"}
_NULL = {"null", "none", "partial", "ambiguous", ""}


def _norm_success(v):
    if isinstance(v, bool):
        return v
    s = str(v or "").strip().lower()
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    return None


def _norm_verdict(d: dict, nsteps: int) -> dict:
    eff = d.get("efficiency")
    try:
        eff = max(0.0, min(1.0, float(eff))) \
            if eff is not None else None
    except (TypeError, ValueError):
        eff = None
    waste = str(d.get("waste") or "").lower()
    fc = str(d.get("failure_class") or "").lower()
    try:
        ff = int(float(d.get("first_fault", -1)))
        ff = max(-1, min(ff, nsteps - 1))
    except (TypeError, ValueError):
        ff = -1
    return {"success": _norm_success(d.get("success")),
            "efficiency": eff, "first_fault": ff,
            "failure_class": fc if fc in FAILURE_CLASSES else None,
            "waste": waste if waste in _WASTES else "none"}


def _parse_verdict_json(text: str, nsteps: int = 0) -> dict:
    """Strict parse of the brain judge's reply: JSON object first, then
    a regex rescue for the two load-bearing keys. Raises ValueError when
    no verdict is recoverable — the caller marks the run unjudged.
    nsteps clamps first_fault to the real step range (0 → unknown)."""
    cap = nsteps if nsteps > 0 else 10_000
    m = re.search(r"\{[^{}]*\}", text or "", re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            if "success" in d:
                return _norm_verdict(d, cap)
        except json.JSONDecodeError:
            pass
    succ = re.search(r'"?success"?\s*:\s*"?(\w+)"?', text or "")
    if not succ:
        raise ValueError(f"no verdict in reply: {(text or '')[:120]}")
    fc = re.search(
        r'"?failure_class"?\s*:\s*"?(model|environment|tool|judge)',
        text or "")
    d = {"success": succ.group(1),
         "failure_class": fc.group(1) if fc else None}
    eff = re.search(r'"?efficiency"?\s*:\s*([\d.]+)', text or "")
    if eff:
        d["efficiency"] = float(eff.group(1))
    return _norm_verdict(d, cap)


def describe(v: dict) -> str:
    """One-line verdict for logs/UI."""
    s = {True: "ok", False: "fail", None: "?"}[v.get("success")]
    e = v.get("efficiency")
    e_txt = f" eff={e:.2f}" if e is not None else ""
    ff = v.get("first_fault", -1)
    ff_txt = f" fault@{ff + 1}" if ff >= 0 else ""
    fc = v.get("failure_class")
    fc_txt = f" cls={fc}" if fc else ""
    by = v.get("by")
    by_txt = f" by={by}" if by in ("brain", "none", "oracle") else ""
    return (f"judge:{s}{e_txt} waste={v.get('waste', '?')}"
            f"{fc_txt}{ff_txt}{by_txt}")
