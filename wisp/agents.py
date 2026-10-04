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
import sys
import threading
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


def _proc_stat(pid: int) -> tuple[str, str] | None:
    """(state letter, start-time token) for a pid, or None if unreadable.

    Linux reads /proc/<pid>/stat (state + field 22). Hosts without /proc
    (macOS) fall back to `ps -o stat=,lstart=`; the start token is only
    ever compared with one taken the same way on the same host."""
    try:
        stat = pathlib.Path(f"/proc/{pid}/stat").read_text()
        tail = stat.rsplit(")", 1)[-1].split()
        return tail[0], tail[19]
    except (OSError, IndexError):
        pass
    if sys.platform == "win32" or pathlib.Path("/proc/self").exists():
        return None
    try:
        out = subprocess.run(["ps", "-o", "stat=,lstart=", "-p", str(pid)],
                             capture_output=True, text=True,
                             timeout=2).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None
    if len(out) < 2:
        return None
    return out[0][0], "-".join(out[1:])


def _pstart(pid: int) -> str:
    """Process start-time — pins identity against PID reuse: a recycled
    pid fails this check before we signal anything."""
    st = _proc_stat(pid)
    return st[1] if st else ""


def _alive(pid: int, pstart: str = "") -> bool:
    """True only for a live process — a zombie (unreaped child) counts
    as dead so status doesn't report 'running' forever. When the task
    record carries pstart, a mismatched start-time means the pid was
    reused by an unrelated process — treat as dead."""
    if pid <= 0:  # kill(-1,0) probes our own process group — never ok
        return False
    st = _proc_stat(pid)
    if st:
        if st[0] == "Z":
            return False
        if pstart and st[1] != pstart:
            return False
    try:
        if sys.platform == "win32":
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            SYNCHRONIZE = 0x00100000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(handle)
            STILL_ACTIVE = 259
            return exit_code.value == STILL_ACTIVE
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError, PermissionError, OverflowError):
        return False


def status(name: str, tasks_file=config.TASKS_FILE,
           log_dir=config.TASK_LOGS) -> str:
    _reap()
    rec = _find(name, tasks_file)
    if not rec:
        return f"SKIP (no task {name!r})"
    tail = _tail(log_dir / f"{rec['id']}.log")
    state = _state_of(rec)
    return f"TASK {rec['name']} [{state}] {tail}".strip()


def _latest(tasks_file=config.TASKS_FILE) -> list:
    """One merged record per task, in spawn order: later records
    overlay earlier ones (so the newest `status` wins) and `started`
    keeps the spawn timestamp."""
    merged: dict = {}
    for rec in _records(tasks_file):
        key = rec.get("id") or rec.get("name")
        if not key:
            continue
        cur = merged.setdefault(key, {"started": rec.get("ts", "")})
        cur.update(rec)
    return list(merged.values())


def _state_of(rec: dict) -> str:
    """Honest status: `running` only while the recorded status says so
    AND the process (same start-time) is alive; a dead task whose
    record never got closed reads `exited`."""
    status = rec.get("status", "exited")
    if status == "running":
        return "running" if _alive(rec.get("pid", -1),
                                   rec.get("pstart", "")) else "exited"
    return status


def _tail(log: pathlib.Path) -> str:
    """Last non-empty log line (reads only the file's last 4 KiB)."""
    try:
        with log.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 4096))
            data = f.read().decode(errors="replace")
    except OSError:
        return ""
    lines = [l for l in data.splitlines() if l.strip()]
    return lines[-1][:160] if lines else ""


def _find(name: str, tasks_file=config.TASKS_FILE) -> dict | None:
    name = name.strip().lower()
    for rec in reversed(_latest(tasks_file)):
        if rec.get("name", "").lower() == name \
                or rec.get("id", "").lower() == name:
            return rec
    return None


def _running(tasks_file=config.TASKS_FILE) -> list:
    """Tasks whose process is still alive (also one that is closing
    down after SIGTERM — it still holds a concurrency slot)."""
    return [r for r in _latest(tasks_file)
            if _alive(r.get("pid", -1), r.get("pstart", ""))]


def _signal(rec: dict, sig: int) -> None:
    """Signal a task's process group — only after the pid's start-time
    still matches the record, so a recycled pid is never touched."""
    pid = rec.get("pid", -1)
    if not _alive(pid, rec.get("pstart", "")):
        return
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass


def _reap_expired(cfg: dict, tasks_file=config.TASKS_FILE) -> list:
    """SIGTERM running tasks past [agent] task_timeout_s — the runaway
    guardrail. Returns names of reaped tasks."""
    timeout = int(cfg.get("agent", {}).get("task_timeout_s", "1800"))
    if timeout <= 0:
        return []
    now = datetime.now(timezone.utc)
    reaped = []
    for rec in _latest(tasks_file):
        if rec.get("status") != "running" \
                or not _alive(rec.get("pid", -1), rec.get("pstart", "")):
            continue
        try:
            age = (now - datetime.fromisoformat(
                rec.get("started", ""))).total_seconds()
        except (ValueError, TypeError):
            continue
        if age <= timeout:
            continue
        _signal(rec, signal.SIGTERM)
        _log_line({"id": rec["id"], "name": rec["name"],
                   "status": "timed_out", "ts": now.isoformat()},
                  tasks_file)
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
    # [agents] model — distinct from [agent] model (that's the Jev
    # router); empty unless the user sets an agent-model override
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
        "pstart": _pstart(proc.pid),
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
        cmd[3:3] = ["--model", model]  # after 'run'
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
    if not _alive(rec.get("pid", -1), rec.get("pstart", "")):
        return f"SKIP ({name} not running)"
    _signal(rec, signal.SIGTERM)
    _log_line({"id": rec["id"], "name": rec["name"], "status": "cancelled",
               "ts": datetime.now(timezone.utc).isoformat()}, tasks_file)
    return f"CANCELLED {name}"


def reap(cfg: dict) -> None:
    """Public watchdog for daemon call sites: zombies + timeouts."""
    _reap()
    _reap_expired(cfg)


def tasks(tasks_file=config.TASKS_FILE,
          log_dir=config.TASK_LOGS) -> dict:
    """name -> {status, task, ts, tail} for state.json publication —
    `tail` is the log's last non-empty line so the panel/orb shows live
    progress on long-running agents."""
    _reap()
    out = {}
    for rec in _latest(tasks_file):
        out[rec["name"]] = {
            "status": _state_of(rec),
            "task": rec.get("task", ""),
            "ts": rec.get("ts", ""),
            "tail": _tail(log_dir / f"{rec['id']}.log"),
        }
    return out


def finished(prev: dict, cur: dict) -> list:
    """Tasks that transitioned running → done between polls — the
    daemon diffs tasks() snapshots and notifies on each."""
    out = []
    for name, st in cur.items():
        if prev.get(name, {}).get("status") == "running" \
                and st.get("status") != "running":
            out.append({"name": name, **st})
    return out


KILL_GRACE_S = 10.0


def _tick(cfg: dict, tasks_file, log_dir, kill_grace_s: float) -> dict:
    """One reaper pass; returns the fresh `tasks()` snapshot."""
    _reap()
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    for rec in _latest(tasks_file):
        pid, pstart = rec.get("pid", -1), rec.get("pstart", "")
        alive = _alive(pid, pstart)
        status = rec.get("status")
        if status == "running" and not alive:
            # process gone, or its pid now belongs to someone else
            _log_line({"id": rec["id"], "name": rec["name"],
                       "status": "exited", "ts": stamp}, tasks_file)
        elif status in ("cancelled", "timed_out") and alive:
            # SIGTERM was sent when the record was closed; an ignorer
            # gets SIGKILL once the grace period is over
            try:
                since = (now - datetime.fromisoformat(
                    rec.get("ts", ""))).total_seconds()
            except (ValueError, TypeError):
                since = kill_grace_s
            if since >= kill_grace_s:
                _signal(rec, signal.SIGKILL)
    _reap_expired(cfg, tasks_file)
    return tasks(tasks_file, log_dir)


def reap_tick(cfg: dict, tasks_file=config.TASKS_FILE,
              log_dir=config.TASK_LOGS,
              kill_grace_s: float = KILL_GRACE_S) -> list:
    """One reaper pass. Returns the tasks that went running -> not
    running during it (`finished()` shape)."""
    return _tick_events(cfg, tasks_file, log_dir, kill_grace_s)[1]


def _tick_events(cfg, tasks_file, log_dir, kill_grace_s) -> tuple:
    """(tasks snapshot, finished list). A task is `finished` when its
    registry status was `running` before the pass and is not after —
    judged on the raw record, since `tasks()` already reads a dead
    unclosed task as exited."""
    was_running = {r["name"] for r in _latest(tasks_file)
                   if r.get("status") == "running"}
    cur = _tick(cfg, tasks_file, log_dir, kill_grace_s)
    done = [{"name": n, **cur[n]} for n in cur
            if n in was_running and cur[n]["status"] != "running"]
    return cur, done


def start_reaper(cfg: dict, bus, stop: threading.Event,
                 interval_s: float = 5.0, tasks_file=config.TASKS_FILE,
                 log_dir=config.TASK_LOGS, on_finished=None,
                 kill_grace_s: float = KILL_GRACE_S) -> threading.Thread:
    """Daemon thread: reap every `interval_s`, publish `tasks` to the
    bus (so progress tails and status changes are pushed, not polled)
    and emit a `task_finished` event per running -> done transition,
    whoever caused it (exit, timeout, `task_cancel`). Idle cost is one
    small file read per tick; it stops when `stop` is set."""
    def run() -> None:
        while not stop.is_set():
            try:
                cur, done = _tick_events(cfg, tasks_file, log_dir,
                                         kill_grace_s)
                bus.publish(None, tasks=cur)
                for t in done:
                    bus.emit_event("task_finished", name=t["name"],
                                   status=t["status"], tail=t["tail"])
                    if on_finished:
                        on_finished(t)
            except Exception:
                pass  # a bad record must never kill the reaper
            stop.wait(interval_s)
    th = threading.Thread(target=run, name="agent-reaper", daemon=True)
    th.start()
    return th
