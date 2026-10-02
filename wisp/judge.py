"""Jev-as-judge: a cheap structured pass grading an act run.

Separate from the planner: the act loop answers "what do I do next",
the judge answers "did it work and was it optimal". Runs through the
same OpenRouter decisions endpoint as ask_jev with its own question
set — one call per task, ~50ms class.
"""
import json

from . import config
from . import pipeline

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
}

# score-type answers come back as numeric score → normalize to 0..1
_EFF_SCALE = [0.0, 0.34, 0.67, 1.0]
_OK = {"yes": True, "partial": None, "no": False}


def verdict(task: str, steps: list, outcome: str, cfg: dict,
            verified: bool | None = None) -> dict:
    """Grade one act run. `verified` is the harness's own ground truth
    (scoreboard check) — Jev reconciles it against the step list."""
    model = cfg.get("agent", {}).get("model", "typesafe/jev-1.13")
    step_lines = "\n".join(
        f"  {i+1}. {s.get('tool')} {s.get('arg', '')[:60]} → "
        f"{s.get('result', '')[:60]}"
        for i, s in enumerate(steps)) or "  (no tool calls)"
    state = (
        f"Task: {task}\n"
        f"Agent steps:\n{step_lines}\n"
        f"Agent's reported outcome: {outcome[:160]}\n"
        f"Automated verifier: "
        f"{'PASS' if verified else 'FAIL' if verified is False else 'N/A'}"
    )
    try:
        resp = pipeline.ask_jev(state, model, JUDGE_QUESTIONS)
    except Exception as e:
        return {"success": None, "efficiency": None,
                "waste": "judge_error", "note": str(e)[:120]}
    answers = resp.get("answers") or {}
    succ = str((answers.get("success") or {}).get("choice", "")).lower()
    eff_raw = (answers.get("efficiency") or {}).get("score")
    try:
        eff = _EFF_SCALE[min(3, max(0, int(float(eff_raw))))] \
            if eff_raw is not None else None
    except (TypeError, ValueError):
        eff = None
    waste = str((answers.get("waste") or {}).get("choice", "")).lower()
    return {"success": _OK.get(succ),
            "efficiency": eff,
            "waste": waste if waste in
            {c for c in JUDGE_QUESTIONS["waste"]["criteria"]}
            else "none",
            "raw": answers}


def describe(v: dict) -> str:
    """One-line verdict for logs/UI."""
    s = {True: "ok", False: "fail", None: "?"}[v.get("success")]
    e = v.get("efficiency")
    e_txt = f" eff={e:.2f}" if e is not None else ""
    return f"judge:{s}{e_txt} waste={v.get('waste', '?')}"


def load_json(raw: str) -> dict:
    """Defensive parse for tests/CLI."""
    return json.loads(raw)
