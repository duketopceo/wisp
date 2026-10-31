"""Autonomy tier policy (plan U3, KTD9): the confirm gate consults
policy(tier, session_mode) instead of per-tool bolt-ons.

Tools declare a T0–T3 tier in `tools.REGISTRY` meta; calls that vary by
argument refine it here (`memory add` is T1, an mcp read is T0, an
OAuth/credential-shaped mcp call is T3). `agent.autonomy` picks the
session mode:

  autonomous (default) — T1 runs free, T2 confirms at batched
                         checkpoints, T3 hands off. Matches the
                         pre-policy gate shape.
  guided               — conservative: T1 confirms too.
  always_ask           — every call confirms.

Session grants ride `state.confirmed`, the existing confirm-once set:
a yes writes (tool, focused-app) as before; an "always" pick writes the
("*", "*") wildcard — approve every gated call this session. T3 is
never grantable: the wildcard and every mode still hand off.

`gate()` returns a refusal/result string or None (run it). Hard
preempts come first — the SHELL_DENYLIST on shell + text-bearing args
and the allow_shell check refuse before a tier is consulted.
`[cua] confirm = "always"` keeps promoting T1 input tools to T2 through
cua_safety.effective_tier.
"""
import json
import re

from . import confirm as _confirm
from . import cua_safety, tools

MODES = ("autonomous", "guided", "always_ask")
ALWAYS_GRANT = ("*", "*")


def mode_of(cfg: dict | None) -> str:
    """The session autonomy mode from `[agent] autonomy`."""
    v = str((cfg or {}).get("agent", {}).get("autonomy") or "")
    return v.strip().lower() if v.strip().lower() in MODES \
        else "autonomous"


SENSITIVE_MUTATING = ("click", "type_text", "key", "fill")


def tier_of(name: str, arg: str = "", cfg: dict | None = None,
            state=None) -> str:
    """The call's autonomy tier: the declared meta, refined by arg, then
    the [cua] confirm=always promotion (T1 input -> T2) and sensitive-surface
    promotion (T1 mutating input on Stripe/financial surfaces -> T2)."""
    return _call_tier(name, arg, cfg, state)[0]


def _call_tier(name: str, arg: str, cfg: dict | None,
               state=None) -> tuple[str, str]:
    # Probe once per call, including stateless callers and confirm=always.
    surface = (cua_safety.sensitive_surface(cfg, state=state)
               if name in SENSITIVE_MUTATING else "")
    t = declared_tier(name)
    t = _refine(name, arg or "", t)
    if t == "T1" and name in cua_safety.GUARDED \
            and cua_safety.settings(cfg)["confirm"] == "always":
        t = "T2"
    if t == "T1" and surface:
        t = "T2"
    return t, surface


def declared_tier(name: str) -> str:
    """Declared meta tier, else the risk-tier mapping (dynamic skill_*
    tools, bare 3-tuple registrations, unknown names -> shell -> T2)."""
    meta = tools.meta_of(name)
    if meta:
        return meta["tier"]
    return tools.RISK_AUTONOMY.get(tools.risk_of(name), "T2")


def decide(name: str, arg: str, cfg: dict | None, state=None) -> str:
    """"run" | "confirm" | "handoff" — what the gate does with a call."""
    return _decision(tier_of(name, arg, cfg, state=state), cfg)


def _decision(t: str, cfg: dict | None) -> str:
    if t == "T3":
        return "handoff"
    mode = mode_of(cfg)
    if mode == "always_ask" or t == "T2":
        return "confirm"
    if t == "T1" and mode == "guided":
        return "confirm"
    return "run"


def preempted(name: str, arg: str, cfg: dict | None) -> str | None:
    """Hard preempts before policy: denylist on shell + text-bearing
    args, live secret keys, and shell needs allow_shell."""
    if name in ((cfg or {}).get("dev", {}).get("deny_tools") or ()):
        return f"REFUSED (dev run denies {name})"
    tier = cua_safety.effective_tier(name, cfg)
    # every tool that enters text refuses a live secret key, `fill` too
    if (tier == "shell" or name in tools.TEXT_INPUT or name == "fill") \
            and cua_safety.SENSITIVE_SECRET_RE.search(str(arg or "")):
        return "REFUSED (live secret key in input)"
    if tier == "shell" or name in tools.TEXT_INPUT:
        if tools.denied(arg):
            return "REFUSED (denylisted command)"
        if tier == "shell" and \
                (cfg or {}).get("agent", {}).get(
                    "allow_shell", "false") != "true":
            return "SKIPPED (shell disabled — set allow_shell=true)"
    return None


def gate_ctx() -> dict:
    """Per-run gate memory: (tool, app) keys the user declined this run,
    so a no isn't re-asked when the model retries."""
    return {"declined": set()}


def gate(name: str, arg: str, cfg: dict, confirm,
         state=None, batch=(), ctx=None) -> str | None:
    """The act loop's gate: a refusal/result string when the call is
    blocked or handed off, else None. `batch` is the reply's remaining
    (name, arg) calls so one checkpoint card covers every gated step
    still queued — not a card per tool.

    In a dev-mode run (`[dev] run_id` set on the run's config copy) a
    refusal is also traced as `gate_stop`, which is how the runner
    records the task as stopped."""
    out = _gate(name, arg, cfg, confirm, state, batch, ctx)
    if out is not None and (cfg or {}).get("dev", {}).get("run_id") \
            and str(out).startswith(("SKIPPED (", "REFUSED (")):
        from . import trace
        trace.emit(trace.current(), "gate_stop", "policy",
                   {"tool": name, "result": str(out)[:200]})
    return out


def _gate(name: str, arg: str, cfg: dict, confirm,
          state=None, batch=(), ctx=None) -> str | None:
    hit = preempted(name, arg, cfg)
    if hit:
        return hit
    tier, surface = _call_tier(name, arg, cfg, state)
    decision = _decision(tier, cfg)
    if decision == "run":
        return None
    app = _focus_app(state)
    confirmed = getattr(state, "confirmed", None)
    grants = confirmed if isinstance(confirmed, set) else frozenset()
    # an unattended dev run never inherits the owner's session grants:
    # every step that would ask ends as needing confirmation
    if (cfg or {}).get("dev", {}).get("run_id"):
        grants = frozenset()
    # A sensitive (or unidentified) surface needs consent for THIS action,
    # not a turn-start app grant, wildcard, plan preview or batched tail.
    if surface:
        grants = frozenset()
        batch = ()
    if decision == "handoff":
        if ctx is not None and (name, app) in ctx["declined"]:
            return f"SKIPPED ({name} declined by user)"
        out = _handoff(name, arg, confirm)
        if ctx is not None and out.endswith("declined by user)"):
            ctx["declined"].add((name, app))
        return out
    if (name, app) in grants or ALWAYS_GRANT in grants:
        return None
    if ctx is not None and (name, app) in ctx["declined"]:
        return f"SKIPPED ({name} declined by user)"
    if confirm is None:
        return f"SKIPPED ({name} needs user confirmation)"
    items = [(name, arg)] + [
        (n, a) for n, a in batch
        if (n, app) not in grants
        and (ctx is None or (n, app) not in ctx["declined"])
        and preempted(n, a, cfg) is None
        and decide(n, a, cfg, state=state) == "confirm"]
    # the card consents only to the steps it names — drop from the tail
    # until every remaining item fits; overflow calls keep their own
    # checkpoint when the loop reaches them
    while len(items) > 1 and len(checkpoint_prompt(items)) > 220:
        items.pop()
    ok, last = ask(confirm, checkpoint_prompt(items))
    if ok:
        if isinstance(confirmed, set) and not surface:
            if last == _confirm.ALWAYS:
                confirmed.add(ALWAYS_GRANT)
            else:
                for n, _a in items:
                    confirmed.add((n, app))
        return None
    if ctx is not None:
        ctx["declined"].update((n, app) for n, _a in items)
    if last == _confirm.TIMEOUT:
        return f"SKIPPED ({name} confirmation timed out)"
    return f"SKIPPED ({name} declined by user)"


PREVIEW_MIN = 3        # mutating steps in one reply that earn a plan card
PREVIEW_LINES = 20     # the card lists at most this many steps


def plan_steps(calls, cfg: dict | None) -> list:
    """The (name, arg) calls of one reply that change something: T1 and
    T2 steps the hard preempts would not already refuse."""
    out = []
    for n, a in calls:
        if tier_of(n, a, cfg) in ("T1", "T2") and preempted(n, a, cfg) is None:
            out.append((n, a))
    return out


def plan_prompt(steps: list) -> str:
    """One line per step, numbered, bounded to PREVIEW_LINES."""
    lines = [f"{i}. {n} {a}".strip()[:90]
             for i, (n, a) in enumerate(steps[:PREVIEW_LINES], 1)]
    if len(steps) > PREVIEW_LINES:
        lines.append(f"…and {len(steps) - PREVIEW_LINES} more")
    return f"run this plan ({len(steps)} steps)?\n" + "\n".join(lines)


def plan_preview(calls, cfg: dict | None, confirm, state=None,
                 minimum: int = PREVIEW_MIN) -> tuple:
    """Show a multi-step reply as ONE card before any step runs.
    Returns (steps, refusal): `steps` is the previewed plan ([] when no
    card was needed or none can be shown) and `refusal` a result string
    when the user said no (or let it lapse). A yes grants the steps for
    this app, so their own per-step cards do not repeat it."""
    if confirm is None or minimum <= 0:
        return [], None
    steps = plan_steps(calls, cfg)
    if len(steps) < minimum:
        return [], None
    confirmed = getattr(state, "confirmed", None)
    if isinstance(confirmed, set) and ALWAYS_GRANT in confirmed:
        return steps, None
    ok, last = ask(confirm, plan_prompt(steps))
    if not ok:
        why = "timed out" if last == _confirm.TIMEOUT else "declined by user"
        return steps, f"SKIPPED (plan {why})"
    if isinstance(confirmed, set):
        if last == _confirm.ALWAYS:
            confirmed.add(ALWAYS_GRANT)
        else:
            app = _focus_app(state)
            for n, _a in steps:
                confirmed.add((n, app))
    return steps, None


def checkpoint_prompt(items: list) -> str:
    """Card text for the gated steps of one reply: a single step keeps
    the 'run close: w1?' shape; several batch into one card naming each
    step (the artifact the user is approving)."""
    if len(items) <= 1:
        n, a = items[0] if items else ("step", "")
        return f"run {n}: {a or '(no arg)'}?"
    steps = " · ".join(f"{n} {a}".strip()[:60] for n, a in items)
    return f"run these {len(items)} steps: {steps}?"


_UNDO = {
    "click": "undo in the app",
    "type_text": "undo in the app",
    "key": "undo in the app",
    "fill": "revert the field",
    "scroll": "scroll back",
    "workspace": "switch back",
    "memory": "memory remove",
    "agent_spawn": "task_cancel",
}


def undo_ref(name: str, arg: str, cfg: dict | None) -> str | None:
    """T1 stream entries carry how to take the step back; other tiers
    publish none."""
    if tier_of(name, arg, cfg) != "T1":
        return None
    return _UNDO.get(name)


# -- call-shape refinements ----------------------------------------------

# `memory` arg: 'target|op|old|new' — add is reversible (remove undoes
# it); replace/remove destroy a curated fact, anything else stays T2.
def _refine(name: str, arg: str, tier: str) -> str:
    if name == "memory":
        op = arg.split("|", 2)[1].strip().lower() if "|" in arg else ""
        return "T1" if op == "add" else "T2"
    if name == "mcp_call":
        return _mcp_tier(arg)
    if name == "skill_manage":
        return "T0" if arg.split("|", 1)[0].strip().lower() == "list" \
            else "T2"
    return tier


# mcp_call varies by call: OAuth/credential/purchase-shaped server or
# tool names hand off (T3 — the agent does everything up to the
# boundary, then waits); read-verb tools observe (T0); everything else
# stays T2. Hints match the server+tool names only — a "payment history"
# lookup in the args must not pause the run.
_MCP_T3 = ("oauth", "login", "signin", "sign_in", "credential",
           "password", "passwd", "secret", "token", "payment",
           "purchase", "checkout", "billing")
_MCP_READ = ("list", "get", "read", "search", "fetch", "query",
             "describe", "find", "status", "show", "tabs", "poll",
             "snapshot", "inspect")
# a mutating verb ANYWHERE in the tool name keeps the call at T2 —
# 'find_and_replace' must not read as 'find'
_MCP_WRITE = ("delete", "remove", "purge", "create", "update", "write",
              "send", "post", "put", "set", "move", "rename", "execute",
              "run", "submit", "replace", "close", "modify", "drop",
              "insert", "add", "new", "edit", "open", "click", "fill",
              "navigate", "unlock", "charge", "buy", "pay", "import",
              "export", "save", "delete_all", "destroy", "approve")


def _mcp_tier(arg: str) -> str:
    parts = arg.split(None, 2)
    if len(parts) < 2:
        return "T2"
    probe = f"{parts[0]} {parts[1]}".lower()
    if any(h in probe for h in _MCP_T3):
        return "T3"
    tool = parts[1].lower().split("/")[-1]  # strata '<category>/<action>'
    tokens = [t for t in re.split(r"[_.\-/\s]+", tool) if t]
    if any(t in _MCP_WRITE for t in tokens):
        return "T2"
    if tokens and tokens[0] in _MCP_READ:
        if len(parts) < 3:
            return "T0"  # read-named tool invoked with no args
        try:
            payload = json.loads(parts[2])
        except ValueError:
            payload = None
        if isinstance(payload, dict) and not payload:
            return "T0"  # read-named tool, empty payload
        # fail closed: T0 needs a positively read `action`; args whose
        # verb lives in another key ({"sql"}, {"operation"}) or a
        # non-object tail stay T2
        if isinstance(payload, dict):
            action = str(payload.get("action", "")).lower()
            if action and re.split(r"[_.\s]", action, maxsplit=1)[0] \
                    in _MCP_READ:
                return "T0"
    return "T2"


def _focus_app(state) -> str:
    """The (tool, app) confirm-once scope: the app focused when the turn
    started, "" when no usable state was handed down."""
    focus = getattr(state, "focus", None)
    return focus.get("app", "") if isinstance(focus, dict) else ""


def ask(confirm, prompt: str, kind: str = "confirm",
        detail: str = "") -> tuple:
    """Call the confirm callable. Rich ones (wisp/confirm.make) take
    `kind` and offer the "always" session grant; plain doubles take just
    the prompt. `detail` is body the card renders under the ask — the
    thing being approved (a dictation preview); plain doubles ignore
    it. Returns (ok, confirm.last)."""
    if getattr(confirm, "rich", False):
        kw = {"kind": kind, "always": kind == "confirm"}
        if detail:
            kw["detail"] = detail
        ok = confirm(prompt, **kw)
    else:
        ok = confirm(prompt)
    return bool(ok), str(getattr(confirm, "last", "") or "")


def _handoff(name: str, arg: str, confirm) -> str:
    """T3 — the run pauses with a "needs you" card; the user does the
    step (OAuth, credentials, a purchase) and answers. The tool itself
    never runs: a yes reads HANDED_OFF, anything else skips."""
    if confirm is None:
        return f"SKIPPED ({name} needs a human — no handoff channel)"
    prompt = f"needs you: {name} {arg}".strip()[:80]
    ok, last = ask(confirm, prompt, kind="handoff")
    if ok:
        return f"HANDED_OFF ({name} done by the user)"
    if last == _confirm.TIMEOUT:
        return f"SKIPPED ({name} handoff timed out)"
    return f"SKIPPED ({name} handoff declined by user)"
