"""System tools: notifications, screenshot, typing, guarded shell, file search."""
import pathlib
import shutil
import subprocess

from .. import config
from ..pipeline import hypr_env, notify


def notify_tool(msg: str) -> str:
    notify(msg or "Wisp")
    return "NOTIFIED"


def screenshot(_: str = "") -> str:
    out = config.DATA_DIR / "shots"
    out.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    f = out / f"shot-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
    from .. import platform
    cmd = platform.screenshot_cmd(f)
    if not cmd:
        return (f"SKIP (no screenshot tool — "
                f"{platform.missing_deps_hint()})")
    r = subprocess.run(cmd, capture_output=True, env=hypr_env())
    if r.returncode == 0 and f.exists():
        return f"SHOT {f}"
    return "SKIP (screenshot failed)"


def type_text(text: str) -> str:
    if not text:
        return "SKIP (nothing to type)"
    from .. import platform
    cmd = platform.type_text_cmd(text)
    if not cmd:
        return (f"SKIP (no typer — {platform.missing_deps_hint()})")
    r = subprocess.run(cmd, capture_output=True, env=hypr_env())
    return "TYPED" if r.returncode == 0 else "SKIP (typer failed)"


def shell(cmd: str) -> str:
    """Guarded shell — denylist is enforced in tools.run upstream; this
    executes via the user's shell and captures a bounded result."""
    if not cmd:
        return "SKIP (empty command)"
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                       timeout=60, env=hypr_env())
    out = (r.stdout or r.stderr).strip()[:200]
    return f"SHELL rc={r.returncode} {out}"


def search_files(pattern: str) -> str:
    """Name-based file search under ~, bounded to 10 hits."""
    if not pattern:
        return "SKIP (empty pattern)"
    hits = []
    try:
        for p in pathlib.Path(config.HOME).glob(f"**/*{pattern}*"):
            if len(hits) >= 10:
                break
            if ".git" in p.parts or p.is_dir() and p.name.startswith("."):
                continue
            hits.append(str(p))
    except OSError:
        pass
    if not hits:
        return f"SKIP (no files matching {pattern!r})"
    return "FOUND " + ", ".join(hits)


_XY = None  # compiled lazily


def _parse_xy(arg: str):
    """'x,y' (screenshot pixels) or 'x,y@logical' → logical (x, y)."""
    global _XY
    import re
    if _XY is None:
        _XY = re.compile(r"^\s*(-?\d+)\s*,\s*(-?\d+)\s*(@logical)?\s*$")
    m = _XY.match(arg or "")
    if not m:
        return None
    x, y = int(m.group(1)), int(m.group(2))
    if m.group(3):
        return x, y
    from .. import points
    pts = points.to_logical([{"x": x, "y": y}], points.monitors())
    return pts[0]["x"], pts[0]["y"]


def _pointer(arg: str, cfg: dict | None, do_click: bool) -> str:
    """click/move shared core. Returns 'GUIDE(x,y) label' when the
    pointer is user-driven (mode=guide or no backend) — the act loop
    publishes the ghost cursor and treats it as a handoff, not a
    failure."""
    xy = _parse_xy(arg)
    if xy is None:
        return "FAIL (arg must be 'x,y' or 'x,y@logical')"
    x, y = xy
    from .. import platform
    backend = platform.pointer_backend(cfg)
    mode = (cfg or {}).get("pointer", {}).get("mode", "guide")
    if mode == "drive" and backend:
        verb = "click" if do_click else "move"
        cmds = platform.pointer_cmds(x, y, backend, click=do_click)
        for c in cmds:
            r = subprocess.run(c, capture_output=True, env=hypr_env(),
                               timeout=10)
            if r.returncode != 0:
                return f"SKIP ({verb} failed via {backend})"
        return f"{'CLICKED' if do_click else 'MOVED'}({x},{y})"
    # guide mode — ghost cursor carries the intent, the user clicks
    verb = "GUIDE" if do_click else "MOVE-GUIDE"
    reason = "" if mode == "guide" else " (no pointer backend)"
    return f"{verb}({x},{y}){reason}"


def click(arg: str, cfg: dict | None = None) -> str:
    return _pointer(arg, cfg, True)


def move(arg: str, cfg: dict | None = None) -> str:
    return _pointer(arg, cfg, False)


_CODEGRAPH_TOOLS = frozenset({
    "search_graph", "trace_path", "get_code_snippet", "query_graph",
    "get_architecture", "search_code", "detect_changes", "list_projects",
})

_CBM_BIN = "codebase-memory-mcp"


def codegraph(arg: str) -> str:
    """Read-only query against a repo's CBM code-graph index.
    arg: '<cbm-tool> <json-args>' — e.g.
    'search_graph {"project":"wisp","query":"State"}'."""
    parts = (arg or "").split(None, 1)
    if len(parts) < 2 or parts[0] not in _CODEGRAPH_TOOLS:
        return ("FAIL (usage: codegraph '<tool> <json-args>' — tools: "
                + ", ".join(sorted(_CODEGRAPH_TOOLS)) + ")")
    if shutil.which(_CBM_BIN) is None:
        return ("SKIP (codebase-memory-mcp not installed — "
                "no code-graph index available)")
    import json as _json
    try:
        _json.loads(parts[1])
    except _json.JSONDecodeError:
        return "FAIL (args must be a JSON object, e.g. {\"project\":..})"
    try:
        r = subprocess.run(
            [_CBM_BIN, "cli", "--quiet", "--json", parts[0], parts[1]],
            capture_output=True, text=True, timeout=30)
    except subprocess.SubprocessError as e:
        return f"SKIP (codegraph failed: {e})"
    out = (r.stdout or r.stderr).strip()
    return ("GRAPH " + out[:1500]) if out else f"SKIP (rc={r.returncode})"
