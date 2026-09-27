"""System tools: notifications, screenshot, typing, guarded shell, file search."""
import pathlib
import shutil
import subprocess

from .. import config
from ..pipeline import hypr_env, notify


def notify_tool(msg: str) -> str:
    notify(msg or "Dim")
    return "NOTIFIED"


def screenshot(_: str = "") -> str:
    out = config.DATA_DIR / "shots"
    out.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    f = out / f"shot-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
    if not shutil.which("grim"):
        return "SKIP (grim not installed)"
    r = subprocess.run(["grim", str(f)], capture_output=True, env=hypr_env())
    if r.returncode == 0 and f.exists():
        return f"SHOT {f}"
    return "SKIP (grim failed)"


def type_text(text: str) -> str:
    if not text:
        return "SKIP (nothing to type)"
    if not shutil.which("wtype"):
        return "SKIP (wtype not installed)"
    r = subprocess.run(["wtype", "--", text], capture_output=True,
                       env=hypr_env())
    return "TYPED" if r.returncode == 0 else "SKIP (wtype failed)"


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
