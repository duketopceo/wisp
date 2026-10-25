"""Agent manager: named, persistent ori-opencode tasks.

Each spawn runs `ori opencode run <task>` detached, logs output to
tasks/<id>.log, and records a line in tasks.jsonl. Status = liveness +
log tail; cancel kills the process group. Registry reload on daemon
start reconciles dead pids.
"""
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import threading
from datetime import datetime, timezone

from . import config, util

SCOPE_PREFIX = "wisp-task-"
_SCOPE_RE = re.compile(r"\bwisp-task-([A-Za-z0-9_.-]+?)\.scope\b")


def _scope_unit(task_id: str) -> str:
    return f"{SCOPE_PREFIX}{task_id}.scope"


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


def _proc_ppid(pid: int) -> int:
    """Parent PID of `pid`, or 0 when unreadable."""
    if pid <= 1:
        return 0
    try:
        stat = pathlib.Path(f"/proc/{pid}/stat").read_text()
        tail = stat.rsplit(")", 1)[-1].split()
        return int(tail[1])
    except (OSError, IndexError, ValueError):
        pass
    if sys.platform == "win32" or pathlib.Path("/proc/self").exists():
        return 0
    try:
        out = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)],
                             capture_output=True, text=True,
                             timeout=2).stdout.strip()
        return int(out) if out else 0
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0


def _proc_cgroup(pid: int) -> str:
    """Raw `/proc/<pid>/cgroup` content on Linux, or '' when unavailable."""
    if pid <= 0:
        return ""
    try:
        return pathlib.Path(f"/proc/{pid}/cgroup").read_text(errors="replace")
    except OSError:
        return ""


def _proc_environ(pid: int) -> dict[str, str]:
    """Environment dict for `pid` (live `os.environ` for self, `/proc/<pid>/environ`
    for other same-uid processes on Linux)."""
    if pid <= 0:
        return {}
    if pid == os.getpid():
        return dict(os.environ)
    try:
        raw = pathlib.Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return {}
    env: dict[str, str] = {}
    for item in raw.split(b"\x00"):
        if not item or b"=" not in item:
            continue
        k, v = item.split(b"=", 1)
        env[k.decode(errors="replace")] = v.decode(errors="replace")
    return env


def classify_peer(peer: dict | None, tasks_file=config.TASKS_FILE) -> dict:
    """Classify a connecting IPC peer (`{pid, uid}`) against the task registry.

    Returns `{marked, verified, spoofed, task_id, reason}`:
      - cgroup scope (`wisp-task-<id>.scope`) verified against `tasks_file`
        catches spawned agents and any reparented (`double-fork`, `env -i`,
        `systemd-run`) descendants;
      - ppid ancestry walk against registered task PIDs + `WISP_TASK_ID`
        env marker is the non-systemd fallback;
      - a process carrying `WISP_TASK_ID` (or a `wisp-task-*.scope` cgroup)
        that is NOT in the task registry is flagged `spoofed=True` and
        refused (marker is verified against registry, never env alone).
    """
    unmarked = {"marked": False, "verified": False, "spoofed": False,
                "task_id": None, "reason": ""}
    if not isinstance(peer, dict) or peer.get("pid") is None:
        return unmarked
    try:
        pid = int(peer["pid"])
    except (TypeError, ValueError):
        return unmarked
    if pid <= 0:
        return unmarked

    recs = _latest(tasks_file)
    by_id = {r["id"]: r for r in recs if r.get("id")}
    by_scope = {r["scope"]: r for r in recs if r.get("scope") and r.get("id")}
    by_pid = {
        int(r["pid"]): r for r in recs
        if isinstance(r.get("pid"), int) and r.get("pid") > 0
        and r.get("status") == "running" and r.get("id")
    }

    # Walk pid -> ppid ancestry (bounded to 32 hops, cycle-safe).
    chain: list[int] = []
    seen: set[int] = set()
    cur = pid
    while cur > 1 and cur not in seen and len(chain) < 32:
        seen.add(cur)
        chain.append(cur)
        if cur == pid and isinstance(peer.get("ppid"), int):
            cur = int(peer["ppid"])
        else:
            cur = _proc_ppid(cur)

    # 1. Cgroup scope check (survives double-fork / setsid / env -i).
    for p in chain:
        cg = (str(peer["cgroup"])
              if p == pid and peer.get("cgroup") is not None
              else _proc_cgroup(p))
        if not cg:
            continue
        for scope_name, rec in by_scope.items():
            if scope_name in cg:
                return {"marked": True, "verified": True, "spoofed": False,
                        "task_id": rec["id"], "reason": "cgroup_scope"}
        m = _SCOPE_RE.search(cg)
        if m:
            tid = m.group(1)
            rec = by_id.get(tid)
            if rec is not None:
                return {"marked": True, "verified": True, "spoofed": False,
                        "task_id": rec["id"], "reason": "cgroup_scope"}
            return {"marked": True, "verified": False, "spoofed": True,
                    "task_id": None, "reason": "unregistered_scope"}

    # 2. Direct PID or ancestor PID match against running task records.
    for p in chain:
        rec = by_pid.get(p)
        if rec is not None:
            rec_pstart = rec.get("pstart", "")
            actual_pstart = _pstart(p)
            if not rec_pstart or not actual_pstart or rec_pstart == actual_pstart:
                return {
                    "marked": True, "verified": True, "spoofed": False,
                    "task_id": rec["id"],
                    "reason": "task_pid" if p == pid else "task_ancestry",
                }

    # 3. Environment marker `WISP_TASK_ID` along ancestry, verified against
    # the registry (never trusted from env alone).
    for p in chain:
        env = (peer["env"]
               if p == pid and isinstance(peer.get("env"), dict)
               else _proc_environ(p))
        tid = str((env or {}).get("WISP_TASK_ID") or "").strip()
        if not tid:
            continue
        rec = by_id.get(tid)
        if rec is not None and rec.get("status") == "running":
            rpid = int(rec.get("pid") or -1)
            rpstart = rec.get("pstart", "")
            if rpid in seen or (rpid > 0 and _alive(rpid, rpstart)):
                return {"marked": True, "verified": True, "spoofed": False,
                        "task_id": rec["id"], "reason": "env_verified"}
        return {"marked": True, "verified": False, "spoofed": True,
                "task_id": None, "reason": "unregistered_task_id"}

    return unmarked


def is_marked_peer(peer: dict | None, tasks_file=config.TASKS_FILE) -> bool:
    return bool(classify_peer(peer, tasks_file=tasks_file).get("marked"))


def record_refusal(task_id: str, cmd: str,
                   tasks_file=config.TASKS_FILE) -> int:
    """Increment `refused_count` for `task_id` in `tasks.jsonl` and return
    the updated count. Preserves existing status/ts fields on merge."""
    rec = _find(task_id, tasks_file)
    if not rec:
        return 0
    count = int(rec.get("refused_count") or 0) + 1
    cmds = list(rec.get("refused_cmds") or [])
    if cmd:
        cmds.append(str(cmd))
    _log_line({
        "id": rec["id"],
        "name": rec["name"],
        "refused_count": count,
        "refused_cmds": cmds,
    }, tasks_file)
    return count


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
        if os.name == "nt":
            # no process groups — signal the task process itself
            os.kill(pid, sig)
        else:
            os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass


def _reap_expired(cfg: dict, tasks_file=config.TASKS_FILE,
                  recs: list | None = None) -> list:
    """SIGTERM running tasks past [agent] task_timeout_s — the runaway
    guardrail. Returns names of reaped tasks."""
    timeout = int(cfg.get("agent", {}).get("task_timeout_s", "1800"))
    if timeout <= 0:
        return []
    now = datetime.now(timezone.utc)
    reaped = []
    for rec in (recs if recs is not None else _latest(tasks_file)):
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


def _systemd_scope_enabled(cfg: dict) -> bool:
    """Whether `spawn` wraps the child in `systemd-run --user --scope`."""
    opt = str((cfg.get("agents") or {}).get("systemd_scope", "")).strip().lower()
    if opt == "false":
        return False
    srun = str(shutil.which("systemd-run") or "")
    if not srun.endswith("systemd-run"):
        return False
    if opt == "true" or os.environ.get("WISP_USE_SYSTEMD_SCOPE") == "1":
        return True
    if "unittest" in sys.modules:
        return False
    xdg_rt = os.environ.get("XDG_RUNTIME_DIR", "")
    return bool(sys.platform.startswith("linux") and xdg_rt
                and (pathlib.Path(xdg_rt) / "systemd" / "private").exists())


def wrap_systemd_scope(cmd: list[str], task_id: str) -> list[str]:
    """Wrap `cmd` in a transient user scope `wisp-task-<task_id>.scope`."""
    unit = _scope_unit(task_id)
    return ["systemd-run", "--user", "--scope", "--quiet", "--collect",
            f"--unit={unit}", "--", *cmd]


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
    scope = _scope_unit(name)
    exec_cmd = wrap_systemd_scope(cmd, name) if _systemd_scope_enabled(cfg) else cmd
    env = dict(os.environ)
    env["WISP_TASK_ID"] = name
    try:
        with log.open("ab") as lf:
            proc = subprocess.Popen(
                exec_cmd, stdout=lf, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                cwd=cwd or str(config.HOME),
                env=env,
                start_new_session=True)
    except OSError as e:
        return f"SKIP (agent spawn failed: {e})"
    _PROCS.append(proc)  # keep the handle so _reap can collect zombies
    _log_line({
        "id": name, "name": name, "task": task, "pid": proc.pid,
        "pstart": _pstart(proc.pid),
        "scope": scope,
        "cmd": " ".join(cmd), "status": "running",
        "refused_count": 0,
        "ts": datetime.now(timezone.utc).isoformat(),
    }, tasks_file)
    return f"SPAWNED {name} (pid {proc.pid})"


# Daemon-spawned children — held so exited ones can be reaped (Popen
# objects keep the zombie until wait/poll is called on them).
_PROCS: list = []


def _reap() -> None:
    """Collect exited agent children — otherwise they sit as zombies
    under the daemon until restart."""
    _PROCS[:] = [p for p in _PROCS if p.poll() is None]


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
          log_dir=config.TASK_LOGS, recs: list | None = None) -> dict:
    """name -> {status, task, ts, tail} for state.json publication —
    `tail` is the log's last non-empty line so the panel/orb shows live
    progress on long-running agents. Only running tasks get a tail read
    — finished logs never change."""
    _reap()
    if recs is None:
        recs = _latest(tasks_file)
    out = {}
    for rec in recs:
        status = _state_of(rec)
        out[rec["name"]] = {
            "status": status,
            "task": rec.get("task", ""),
            "ts": rec.get("ts", ""),
            "tail": _tail(log_dir / f"{rec['id']}.log")
            if status == "running" else "",
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


def _tick(cfg: dict, tasks_file, log_dir, kill_grace_s: float,
          recs: list | None = None) -> dict:
    """One reaper pass; returns the fresh `tasks()` snapshot."""
    _reap()
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    if recs is None:
        recs = _latest(tasks_file)
    for rec in recs:
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
    _reap_expired(cfg, tasks_file, recs=recs)
    # this pass appended status records — the snapshot must re-merge
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
    recs = _latest(tasks_file)
    was_running = {r["name"] for r in recs
                   if r.get("status") == "running"}
    cur = _tick(cfg, tasks_file, log_dir, kill_grace_s, recs=recs)
    # a just-finished task's tail is its final output — read it for the
    # event even though tasks() only tails running tasks
    done = []
    for n in cur:
        if n in was_running and cur[n]["status"] != "running":
            entry = {"name": n, **cur[n]}
            if not entry["tail"]:
                rec = _find(n, tasks_file)
                if rec is not None:
                    entry["tail"] = _tail(log_dir / f"{rec['id']}.log")
            done.append(entry)
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
