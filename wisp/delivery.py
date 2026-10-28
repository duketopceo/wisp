"""Input delivery modes (U5, KTD5): which channel an input call
actually used, recorded honestly on every guarded call, act-loop step
and cua.target aim.

  background — the op never moves the user's cursor: DOM/CDP dispatch,
               wtype/ydotool typing, ydotool wheel scrolls, Hyprland
               window ops over the socket, and cua-driver clicks
               (`zwlr_virtual_pointer` — a separate agent cursor, no
               focus steal).
  pointer    — the op drives the REAL cursor: every hyprcursor/ydotool/
               wlrctl click or move, every hyprctl cursor eval, and cua
               `move_cursor(scope:"desktop")` — verified live to move
               the real OS pointer (docs/research/cua-tool-catalog.md);
               only the no-scope overlay call does not.
  guide      — nothing was injected; the ghost cursor shows the point
               and the user clicks (guide mode, no backend, or the
               background policy refusing to take the real cursor).

`[cua] delivery` picks the policy:

  auto       (default) every op takes its natural path — background
             where a path exists, real-pointer as the escalation.
  background never touch the real cursor: an op that can only run as
             pointer delivery degrades to guide instead of injecting.
  pointer    prefer the real pointer: for clicks the auto backend order
             skips the background-only cua backend.

DOM-mode ops always stay background whatever the policy — no
real-pointer path into a page exists.

The current call's stamp lives in a thread-local set by the tool
function (`note`/`last`/`clear`): `Guard.run` reads it for the audit
record, the act loop for the step and stream entry.
"""
import threading

MODES = ("auto", "background", "pointer")

# tools whose every path is background delivery (no cursor involvement):
# virtual-keyboard typers, wheel scrolls, DOM ops, window/socket ops
_BACKGROUND_TOOLS = frozenset({
    "type_text", "key", "fill", "scroll",
    "focus", "tab", "workspace", "launch", "close",
})
_POINTER_TOOLS = frozenset({"click", "move"})

_LOCAL = threading.local()


def mode(cfg: dict | None) -> str:
    """`[cua] delivery` — auto | background | pointer (default auto)."""
    v = str(((cfg or {}).get("cua") or {}).get("delivery") or "")
    v = v.strip().lower()
    return v if v in MODES else "auto"


def note(d: str) -> None:
    """Stamp the delivery the running op actually used."""
    _LOCAL.mode = d


def last() -> str:
    """The stamp the running op left, "" when it set none."""
    return getattr(_LOCAL, "mode", "") or ""


def clear() -> None:
    """Reset the stamp before a dispatch (Guard.run owns this)."""
    _LOCAL.mode = ""


def backend_delivery(backend: str | None, op: str) -> str:
    """The delivery a dispatched backend actually used — the truth
    table, not the promise. `op` is "click" | "move"."""
    if backend in (None, "", "guide"):
        return "guide"
    if backend == "cua" and op == "click":
        # zwlr_virtual_pointer: the click lands at the agent cursor —
        # the user's real pointer never moves (left button only).
        return "background"
    return "pointer"


def resolve_backend(cfg: dict | None, op: str) -> str | None:
    """Backend name the pointer registry should dispatch `op`
    ("click"|"move") on under `[cua] delivery`, or None — no backend,
    or the background policy refuses to take the real cursor (the call
    guides instead of injecting)."""
    from . import platform
    b = platform.pointer_backend(cfg)
    if b is None:
        return None
    m = mode(cfg)
    from . import pointer
    pin = str(((cfg or {}).get("pointer") or {}).get("backend") or "")
    # "auto"/""/unknown pins resolve the auto order — only an explicit
    # backend pin beats the delivery=pointer escalation below
    auto_pin = pin.strip().lower() not in pointer.NAMES + ("none",)
    if m == "pointer" and op == "click" and b == "cua" and auto_pin:
        # force the escalation: prefer a real-pointer backend; when
        # none exists cua stays (marked background in the audit). An
        # explicit pointer.backend pin is more specific — it wins.
        b = platform.pointer_backend(cfg, exclude=("cua",)) or b
    if m == "background" and backend_delivery(b, op) == "pointer":
        return None
    return b


def planned(name: str, cfg: dict | None) -> str:
    """The delivery `name` would use if dispatched now — for audit
    lines on refused/dry-run calls that never reach a backend, the aim
    event, and stream entries on gated steps. "" for tools that inject
    no input."""
    if name in _BACKGROUND_TOOLS:
        return "background"
    if name not in _POINTER_TOOLS:
        return ""
    if (cfg or {}).get("screen", {}).get("dom_page"):
        return "background"
    if (cfg or {}).get("pointer", {}).get("mode") != "drive":
        return "guide"
    return backend_delivery(resolve_backend(cfg, name), name)
