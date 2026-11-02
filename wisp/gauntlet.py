"""Gauntlet mode for dev runs (KTD5-KTD8, KTD12).

A gauntlet run is a dev run (wisp.devrun) with three extra allowances,
granted only on the run's own config copy and only when the driver
(scripts/gauntlet.py) asks for them over IPC:

  - `type_text` and `key`, but only while the focused window is one of
    the sandbox windows the driver spawned. Identity is the Hyprland
    window address, never a class or a workspace, and it is read again
    from the compositor immediately before each keystroke, so focus
    moving off the sandbox between the policy check and the key stops
    the task without typing;
  - `skill_manage` create and edit (delete, write_file and remove_file
    stay refused), so a learn turn can save an app skill;
  - trajectories, so a second try can lean on the first.

  - `shell`, but only through the sandbox's restricted read-only shell
    (scripts/gauntlet/rsh) in the sandbox workspace, and only when the
    driver registered that workspace; `allow_shell` itself stays false;
  - clicks without a confirmation, but only while the focused window is
    a registered sandbox window and the surface is not sensitive. The
    live hit test is skipped too (the sandbox apps expose no controls),
    so `click_guard` replaces it: a click at model coordinates runs only
    when every visible window under the point is a registered sandbox
    window (at least one), and no clickable layer surface covers it.
    Fails closed; the menu cases register no window and are refused.

Everything else in the dev run stays: the deny list, `wait_for_choice =
None` (every other confirm gate answers no) and the shell switch.

Also here: arm profiles (flat TOML files of section.key overrides, one
per configuration under test) and the persistent cumulative spend file
that caps a whole gauntlet across invocations (R13).
"""
import json
import os
import pathlib
import re
import subprocess
import sys

from . import cua_safety

PROFILE_DIR = (pathlib.Path(__file__).resolve().parent.parent
               / "docs" / "dev-tasks" / "profiles")
# sections a profile may not carry: the run owns them
_RESERVED_SECTIONS = ("dev", "traj")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
TYPING_TOOLS = ("type_text", "key")
SKILL_OPS = ("create", "edit")
# gauntlet allowances on top of devrun.ALLOW_TOOLS
EXTRA_TOOLS = frozenset(TYPING_TOOLS + ("skill_manage",))
DEFAULT_CAP_USD = 10.0
# a run with no `agents.act_max_usd` still reserves this much per task
DEFAULT_TASK_STOP_USD = 0.25


def is_gauntlet(cfg) -> bool:
    return str(((cfg or {}).get("dev") or {}).get("gauntlet", "")
               ).lower() == "true"


# -- arm profiles ---------------------------------------------------------

def parse_flat(text: str) -> dict:
    """The flat `[section]` / `key = "value"` subset config.toml uses
    (a dotted table name like `[brain.openrouter]` is one section)."""
    out: dict = {}
    section = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("["):
            section = line.strip("[]").strip()
            out.setdefault(section, {})
        elif "=" in line and section:
            k, v = (p.strip() for p in line.split("=", 1))
            out[section][k] = v.strip('"')
    return out


def load_profile(ref: str) -> tuple:
    """(label, {section: {key: value}}) for a profile name (a file under
    docs/dev-tasks/profiles/) or a path to a profile file. Raises
    ValueError on an unknown or malformed profile."""
    ref = str(ref or "").strip()
    if _NAME.fullmatch(ref):
        path = PROFILE_DIR / f"{ref}.toml"
    else:
        path = pathlib.Path(ref)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise ValueError(f"no profile {ref!r}") from None
    prof = parse_flat(text)
    if not prof:
        raise ValueError(f"profile {ref!r} sets nothing")
    bad = [s for s in prof if s in _RESERVED_SECTIONS]
    if bad:
        raise ValueError(f"profile {ref!r} cannot set [{bad[0]}]")
    return path.stem, prof


def apply_profile(cfg: dict, profile: dict) -> None:
    """Overlay a profile on `cfg` in place (the caller owns the copy)."""
    for sec, kv in (profile or {}).items():
        cfg.setdefault(sec, {}).update(kv)


def task_stop_usd(cfg: dict) -> float:
    """What one task may spend: the arm's `agents.act_max_usd`, or the
    default reservation when it sets none."""
    try:
        v = float(str(((cfg or {}).get("agents") or {}).get(
            "act_max_usd", "")).strip())
    except ValueError:
        v = 0.0
    return v if v > 0 else DEFAULT_TASK_STOP_USD


# -- spend ----------------------------------------------------------------

class Spend:
    """The gauntlet's cumulative spend file: one JSON line per charge,
    appended under an O_APPEND write so overlapping invocations (the
    click probe, a rerun) all count. The total is the sum of the file."""

    def __init__(self, path, cap_usd: float = DEFAULT_CAP_USD):
        self.path = pathlib.Path(path)
        self.cap = float(cap_usd)

    def total(self) -> float:
        t = 0.0
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return 0.0
        for line in lines:
            try:
                row = json.loads(line)
                t += max(0.0, float(row.get("usd") or 0.0))
            except (ValueError, TypeError, AttributeError):
                continue
        return t

    def remaining(self) -> float:
        return max(0.0, self.cap - self.total())

    def add(self, usd, kind: str, **meta) -> None:
        """Record a charge (`kind`: task, judge, probe, learn...)."""
        try:
            usd = max(0.0, float(usd))
        except (TypeError, ValueError):
            usd = 0.0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {"usd": round(usd, 6), "kind": kind, **meta}
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT,
                     0o600)
        try:
            os.write(fd, (json.dumps(row, separators=(",", ":"))
                          + "\n").encode())
        finally:
            os.close(fd)

    def can_afford(self, stops) -> bool:
        """True when the cap still covers every per-task stop in `stops`
        (all the arms of the next case), so a nearly spent cap stops
        every arm at the same case."""
        return self.remaining() + 1e-9 >= sum(float(s) for s in stops)


def spend_for(cfg: dict):
    """The Spend a gauntlet run config names, or None."""
    d = (cfg or {}).get("dev") or {}
    p = str(d.get("spend_file") or "").strip()
    if not (is_gauntlet(cfg) and p):
        return None
    try:
        cap = float(str(d.get("spend_cap_usd", "")).strip())
    except ValueError:
        cap = DEFAULT_CAP_USD
    return Spend(p, cap)


# -- the sandbox typing check ---------------------------------------------

def _norm_addr(a) -> str:
    a = str(a or "").strip().lower()
    if a and not a.startswith("0x"):
        a = "0x" + a
    return a


def sandbox_windows(cfg: dict) -> frozenset:
    raw = str(((cfg or {}).get("dev") or {}).get("sandbox_windows") or "")
    return frozenset(_norm_addr(a) for a in raw.split(",") if a.strip())


def focused_address() -> str:
    """The focused window's Hyprland address, read now."""
    from . import hypr
    w = hypr.query("activewindow")
    return _norm_addr(w.get("address")) if isinstance(w, dict) else ""


def sandbox_refusal(cfg: dict) -> str | None:
    """None when the focused window is a registered sandbox window, else
    the refusal text. Fails closed: no registered window, an unreadable
    compositor or an empty focus all refuse."""
    allowed = sandbox_windows(cfg)
    if not allowed:
        return "REFUSED (gauntlet: no sandbox window is registered)"
    try:
        addr = focused_address()
    except Exception:
        return "REFUSED (gauntlet: cannot read the focused window)"
    if not addr or addr not in allowed:
        return ("REFUSED (gauntlet sandbox: the focused window is not "
                "a sandbox window)")
    return None


def _skill_op(arg: str) -> str:
    return str(arg or "").split("|", 1)[0].strip().lower()


_CHORD_REFUSAL = ("REFUSED (gauntlet: super and alt chords reach the "
                  "compositor, not the window)")


def _global_chord(arg: str) -> bool:
    """A chord with super/meta/cmd/alt is handled by the compositor's own
    binds (close, launch, move), not by the focused sandbox window."""
    parts = str(arg or "").lower().replace(" ", "").split("+")
    return len(parts) > 1 and any(
        m in ("super", "meta", "cmd", "alt", "mod4", "win")
        for m in parts[:-1])


RSH = pathlib.Path(__file__).resolve().parent.parent \
    / "scripts" / "gauntlet" / "rsh"
RSH_SAFE_ENV = ("PATH", "LANG", "LC_ALL", "TERM")
CLICK_TOOLS = ("click",)


def sandbox_root(cfg: dict) -> str:
    return str(((cfg or {}).get("dev") or {}).get("sandbox_root") or ""
               ).strip()


def shell_sandboxed(name: str, cfg: dict) -> bool:
    """True for the `shell` tool in a gauntlet run that registered a
    sandbox workspace: that call runs through rsh (`rsh_run`)."""
    return name == "shell" and is_gauntlet(cfg) and bool(sandbox_root(cfg))


def rsh_run(cmd: str, cfg: dict) -> str:
    """Run one shell line through the sandbox's rsh (read-only
    allowlist, no shell syntax, paths inside the workspace, scrubbed
    environment) and return the `shell` tool's result text. Fails
    closed: no gauntlet run or no sandbox root refuses."""
    root = sandbox_root(cfg)
    if not (is_gauntlet(cfg) and root and RSH.is_file()):
        return "REFUSED (gauntlet: shell runs only through the sandbox rsh)"
    if not str(cmd or "").strip():
        return "SKIP (empty command)"
    env = {k: os.environ[k] for k in RSH_SAFE_ENV if k in os.environ}
    env["GAUNTLET_ROOT"] = root
    log = str(((cfg or {}).get("dev") or {}).get("sandbox_log") or "").strip()
    if log:
        env["GAUNTLET_LOG"] = log
    try:
        r = subprocess.run([sys.executable, str(RSH), "-c", str(cmd)],
                           cwd=root, env=env, capture_output=True,
                           text=True, timeout=30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"SKIP (sandbox shell failed: {type(e).__name__})"
    out = (r.stdout or r.stderr).strip()[:200]
    return f"SHELL rc={r.returncode} {out}"


def preempt(name: str, arg: str, cfg: dict) -> str | None:
    """The gauntlet's hard preempts (policy.preempted): typing needs a
    sandbox window in focus; skill_manage is create and edit only."""
    if not is_gauntlet(cfg):
        return None
    if name == "key" and _global_chord(arg):
        return _CHORD_REFUSAL
    if name in TYPING_TOOLS:
        return sandbox_refusal(cfg)
    if name == "skill_manage" and _skill_op(arg) not in SKILL_OPS + ("list",):
        return "REFUSED (gauntlet allows skill create and edit only)"
    if name == "shell" and not sandbox_root(cfg):
        return "REFUSED (gauntlet: no sandbox workspace for the shell)"
    return None


def pre_approved(name: str, arg: str, cfg: dict, state=None) -> bool:
    """True when the unattended gate need not ask: a typing step into a
    sandbox window on a surface that is not sensitive (the sandbox
    check already ran in `preempt`), or a skill create or edit."""
    if not is_gauntlet(cfg):
        return False
    if name == "skill_manage":
        return _skill_op(arg) in SKILL_OPS
    if name in TYPING_TOOLS:
        return not cua_safety.sensitive_surface(cfg, state=state)
    if shell_sandboxed(name, cfg):
        return True         # rsh is read-only and confined to the sandbox
    if name in CLICK_TOOLS:
        # identity by window address, read now; a sensitive surface (a
        # matched token) still stops. An unreadable title ("unknown",
        # a popup menu) does not: the sandbox identity is already known.
        if sandbox_refusal(cfg) is not None:
            return False
        return cua_safety.sensitive_surface(cfg, state=state) in ("", "unknown")
    return False


# Full-screen overlays that take no input over the click point: the
# wallpaper, the notification layer, and Wisp's own `wisp-points`
# overlay (Companion.qml), whose input mask covers only its pill and
# bubble. Counting them refused every gauntlet click (live run
# gauntlet-20261102-051957: 98 refusals).
_PASSIVE_LAYERS = frozenset(("omarchy-background", "omarchy-notifications",
                             "wisp-points"))


def _in_rect(x, y, at, size) -> bool:
    try:
        return (at[0] <= x < at[0] + size[0]
                and at[1] <= y < at[1] + size[1])
    except (TypeError, IndexError):
        return False


def _visible_ws(mons) -> set:
    ids = set()
    for m in mons:
        for k in ("activeWorkspace", "specialWorkspace"):
            w = m.get(k)
            if isinstance(w, dict) and w.get("id") not in (None, 0):
                ids.add(w["id"])
    return ids


def click_refusal(cfg: dict, x, y) -> str | None:
    """None when a click at global logical (x, y) lands on a registered
    sandbox window, else the refusal text. Reads the compositor now
    (hyprctl clients/monitors/layers; `at`/`size` are the same logical
    coordinates `click` converts to). Fails closed: no registered window,
    an unreadable compositor, no window under the point, any visible
    non-sandbox window under it, or a clickable layer surface (the bar,
    the menu or launcher) over it all refuse."""
    allowed = sandbox_windows(cfg)
    if not allowed:
        return "REFUSED (gauntlet: no sandbox window is registered)"
    from . import hypr
    try:
        x, y = int(x), int(y)
        clients = hypr.query("clients")
        mons = hypr.query("monitors")
        layers = hypr.query("layers")
        if not (isinstance(clients, list) and isinstance(mons, list)
                and isinstance(layers, dict)):
            raise ValueError("shape")
    except Exception:
        return "REFUSED (gauntlet: cannot read the compositor for the click)"
    vis = _visible_ws(mons)
    under = []
    for c in clients:
        if not isinstance(c, dict) or not c.get("mapped") \
                or c.get("hidden"):
            continue
        ws = (c.get("workspace") or {}).get("id")
        if ws not in vis:
            continue
        if _in_rect(x, y, c.get("at"), c.get("size")):
            under.append(_norm_addr(c.get("address")))
    if not under:
        return ("REFUSED (gauntlet: no sandbox window under the click "
                "point)")
    if any(a not in allowed for a in under):
        return ("REFUSED (gauntlet: a window that is not a sandbox "
                "window is under the click point)")
    offs = [(0, 0)] + [(m.get("x", 0), m.get("y", 0)) for m in mons
                       if isinstance(m, dict)]
    for per_mon in layers.values():
        levels = per_mon.get("levels") if isinstance(per_mon, dict) else None
        for lvl, items in (levels or {}).items():
            if str(lvl) in ("0", "1"):      # background/bottom: below windows
                continue
            for l in items or []:
                if not isinstance(l, dict) \
                        or l.get("namespace") in _PASSIVE_LAYERS:
                    continue
                for ox, oy in offs:
                    try:
                        at = (l["x"] + ox, l["y"] + oy)
                        size = (l["w"], l["h"])
                    except (KeyError, TypeError):
                        return ("REFUSED (gauntlet: unreadable layer "
                                "surface over the click point)")
                    if _in_rect(x, y, at, size):
                        ns = str(l.get("namespace") or "?")[:40]
                        return ("REFUSED (gauntlet: a layer surface "
                                f"({ns}) is over the click point)")
    return None


def click_guard(cfg: dict, x, y) -> str | None:
    """The check right before a click is sent (see `click_refusal`). A
    refusal is traced as a gate stop, like `keystroke_guard`, so the
    runner ends the task as stopped. None outside a gauntlet run."""
    if not is_gauntlet(cfg):
        return None
    out = click_refusal(cfg, x, y)
    if out and (cfg.get("dev") or {}).get("run_id"):
        from . import trace
        trace.emit(trace.current(), "gate_stop", "policy",
                   {"tool": "click", "result": out[:200]})
    return out


def keystroke_guard(cfg: dict, arg: str = "") -> str | None:
    """The check right before a keystroke is sent: the same sandbox
    identity test as the policy gate, run again because focus can move
    in between. A refusal is traced as a gate stop, so the runner ends
    the task as stopped."""
    if not is_gauntlet(cfg):
        return None
    out = (_CHORD_REFUSAL if _global_chord(arg) else None) \
        or sandbox_refusal(cfg)
    if out and (cfg.get("dev") or {}).get("run_id"):
        from . import trace
        trace.emit(trace.current(), "gate_stop", "policy",
                   {"tool": "keystroke", "result": out[:200]})
    return out
