"""Agent manager: named, persistent ori-opencode tasks.

Each spawn runs `ori opencode run <task>` detached, logs output to
tasks/<id>.log, and records a line in tasks.jsonl. Status = liveness +
log tail; cancel kills the process group. Registry reload on daemon
start reconciles dead pids.
"""
import json
import os
import pathlib
import shutil
import signal
import subprocess
from datetime import datetime, timezone

from . import config, util


def _slug(text: str) -> str:
    return util.slug(text, max_len=32, default="task")


def _log_line(rec: dict, tasks_file=config.TASKS_FILE) -> None:
    tasks_file.parent.mkdir(parents=True, exist_ok=True)
    with tasks_file.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def _records(tasks_file=config.TASKS_FILE) -> list:
    try:
        return [json.loads(l) for l in tasks_file.read_text().splitlines()
                if l.strip()]
    except OSError:
        return []


def _alive(pid: int) -> bool:
    """True only for a live process — a zombie (unreaped child) counts
    as dead so status doesn't report 'running' forever."""
    if pid <= 0:  # kill(-1,0) probes our own process group — never ok
        return False
    try:
        stat = pathlib.Path(f"/proc/{pid}/stat").read_text()
        if stat.rsplit(")", 1)[-1].split()[0] == "Z":
            return False
    except OSError:
        pass
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OverflowError):
        return False


def status(name: str, tasks_file=config.TASKS_FILE,
           log_dir=config.TASK_LOGS) -> str:
    _reap()
    rec = _find(name, tasks_file)
    if not rec:
        return f"SKIP (no task {name!r})"
    running = _alive(rec.get("pid", -1))
    log = log_dir / f"{rec['id']}.log"
    tail = ""
    if log.exists():
        lines = [l for l in log.read_text(errors="replace").splitlines()
                 if l.strip()]
        tail = lines[-1][:160] if lines else ""
    state = "running" if running else rec.get("status", "exited")
    return f"TASK {rec['name']} [{state}] {tail}".strip()


def _find(name: str, tasks_file=config.TASKS_FILE) -> dict | None:
    name = name.strip().lower()
    for rec in reversed(_records(tasks_file)):
        if rec.get("name", "").lower() == name \
                or rec.get("id", "").lower() == name:
            return rec
    return None


def _running(tasks_file=config.TASKS_FILE) -> list:
    return [r for r in _records(tasks_file) if _alive(r.get("pid", -1))]


def _reap_expired(cfg: dict, tasks_file=config.TASKS_FILE) -> list:
    """Kill running tasks past [agent] task_timeout_s — the runaway
    guardrail. Returns names of reaped tasks."""
    timeout = int(cfg.get("agent", {}).get("task_timeout_s", "1800"))
    if timeout <= 0:
        return []
    now = datetime.now(timezone.utc)
    reaped = []
    for rec in _running(tasks_file):
        try:
            age = (now - datetime.fromisoformat(
                rec.get("ts", ""))).total_seconds()
        except (ValueError, TypeError):
            continue
        if age <= timeout:
            continue
        pid = rec.get("pid", -1)
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        _log_line({"id": rec["id"], "name": rec["name"],
                   "status": "timed_out",
                   "ts": now.isoformat()}, tasks_file)
        reaped.append(rec["name"])
    return reaped


def spawn(task: str, cfg: dict, tasks_file=config.TASKS_FILE,
          log_dir=config.TASK_LOGS, cwd: str | None = None) -> str:
    task = task.strip()
    if not task:
        return "SKIP (empty agent task)"
    _reap()
    _reap_expired(cfg, tasks_file)
    cap = int(cfg.get("agent", {}).get("max_concurrent", "3"))
    if len(_running(tasks_file)) >= cap:
        return (f"SKIP (agent limit: {cap} already running — "
                "cancel one or raise [agent] max_concurrent)")
    name = _slug(task)
    base, i = name, 2
    existing = {r.get("name") for r in _records(tasks_file)}
    while name in existing:
        name = f"{base}-{i}"
        i += 1
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / f"{name}.log"
    model = cfg.get("agents", {}).get("model", "")
    cmd = _runtime_cmd(cfg, task, model)
    if cmd is None:
        rt = cfg.get("brain", {}).get("agent_runtime", "auto")
        if rt == "auto":
            return ("SKIP (agent runtime 'auto' not on PATH — tried "
                    + "/".join(_AUTO_ORDER) + "; detected: none)")
        return (f"SKIP (agent runtime {rt!r} not on PATH — detected: "
                + (", ".join(detect_runtimes()) or "none") + ")")
    try:
        with log.open("ab") as lf:
            proc = subprocess.Popen(
                cmd, stdout=lf, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                cwd=cwd or str(config.HOME),
                start_new_session=True)
    except OSError as e:
        return f"SKIP (agent spawn failed: {e})"
    _PROCS.append(proc)  # keep the handle so _reap can collect zombies
    _log_line({
        "id": name, "name": name, "task": task, "pid": proc.pid,
        "cmd": " ".join(cmd), "status": "running",
        "ts": datetime.now(timezone.utc).isoformat(),
    }, tasks_file)
    return f"SPAWNED {name} (pid {proc.pid})"


# Daemon-spawned children — held so exited ones can be reaped (Popen
# objects keep the zombie until wait/poll is called on them).
_PROCS: list = []


def _reap() -> None:
    """Collect exited agent children — otherwise they sit as zombies
    under the daemon until restart."""
    for p in _PROCS:
        p.poll()


_RUNTIMES = {  # [brain] agent_runtime → argv template, {task}/{model}
    "opencode": ["ori", "opencode", "run", "{task}"],
    "codex": ["codex", "exec", "{task}"],
    "claude": ["claude", "-p", "{task}"],
    "devin": ["devin", "run", "{task}"],
}
_RUNTIME_BINS = {"opencode": "ori", "codex": "codex",
                 "claude": "claude", "devin": "devin"}
# `agent_runtime = "auto"` probes PATH in this order — opencode first.
_AUTO_ORDER = ["opencode", "codex", "claude", "devin"]


def detect_runtimes() -> dict:
    """runtime → resolved binary path for everything on PATH."""
    return {rt: shutil.which(b)
            for rt, b in _RUNTIME_BINS.items() if shutil.which(b)}


def resolve_runtime(cfg: dict) -> str:
    """Configured runtime, or the first detected one when 'auto'."""
    rt = cfg.get("brain", {}).get("agent_runtime", "auto")
    if rt != "auto":
        return rt
    for cand in _AUTO_ORDER:
        if shutil.which(_RUNTIME_BINS[cand]):
            return cand
    return ""


def _runtime_cmd(cfg: dict, task: str, model: str) -> list | None:
    """argv for the configured agent runtime, or None when its binary
    isn't on PATH (U6: probe → explicit error, not a silent failure)."""
    rt = resolve_runtime(cfg)
    if not rt:
        return None
    template = _RUNTIMES.get(rt, _RUNTIMES["opencode"])
    if not shutil.which(_RUNTIME_BINS.get(rt, "ori")):
        return None
    cmd = [a.format(task=task, model=model) for a in template]
    if model and rt == "opencode":
        cmd[2:2] = ["--model", model]  # before 'run'
    elif model and rt == "codex":
        cmd += ["-m", model]
    elif model and rt == "claude":
        cmd += ["--model", model]
    return cmd


def cancel(name: str, tasks_file=config.TASKS_FILE) -> str:
    _reap()
    rec = _find(name, tasks_file)
    if not rec:
        return f"SKIP (no task {name!r})"
    pid = rec.get("pid", -1)
    if not _alive(pid):
        return f"SKIP ({name} not running)"
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    _log_line({"id": rec["id"], "name": rec["name"], "status": "cancelled",
               "ts": datetime.now(timezone.utc).isoformat()}, tasks_file)
    return f"CANCELLED {name}"


def reap(cfg: dict) -> None:
    """Public watchdog for daemon call sites: zombies + timeouts."""
    _reap()
    _reap_expired(cfg)


def tasks(tasks_file=config.TASKS_FILE) -> dict:
    """name -> {status, tail-free summary} for state.json publication."""
    _reap()
    out = {}
    for rec in _records(tasks_file):
        running = _alive(rec.get("pid", -1))
        out[rec["name"]] = {
            "status": "running" if running else rec.get("status", "exited"),
            "task": rec.get("task", ""),
            "ts": rec.get("ts", ""),
        }
    return out
