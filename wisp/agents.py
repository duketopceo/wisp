"""Agent manager: named, persistent ori-opencode tasks.

Each codex/claude/devin spawn runs one-shot, detached; opencode runs as an
ACP session (acp_runtime). One-shot runs log output to
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
import time
from datetime import datetime, timezone

from . import config, private, util

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


def record_process(proc_id: str, pid: int, scope: str = "",
                   tasks_file=config.TASKS_FILE) -> dict:
    """Log the one long-lived ACP process record (KTD3). It holds many
    session records and no concurrency slot of its own."""
    rec = {"id": proc_id, "name": proc_id, "kind": "acp_process",
           "pid": pid, "pstart": _pstart(pid),
           "scope": scope or _scope_unit(proc_id),
           "status": "running", "ts": datetime.now(timezone.utc).isoformat()}
    _log_line(rec, tasks_file)
    return rec


def record_session(name: str, task: str, acp_process: str,
                   session_id: str = "", model: str = "", cwd: str = "",
                   tasks_file=config.TASKS_FILE, **extra) -> dict:
    """Log a session record: today's task shape minus a pid of its own
    (liveness is its process record's), plus the ACP fields."""
    rec = {"id": name, "name": name, "task": task, "kind": "session",
           "acp_process": acp_process, "session_id": session_id,
           "model": model, "cwd": cwd, "stop_reason": None,
           "status": "running", "refused_count": 0,
           "ts": datetime.now(timezone.utc).isoformat(), **extra}
    _log_line(rec, tasks_file)
    return rec


def _proc_running(proc: dict | None) -> bool:
    return bool(proc and proc.get("kind") == "acp_process"
                and proc.get("status") == "running"
                and _alive(proc.get("pid", -1), proc.get("pstart", "")))


def _proc_stat(pid: int) -> tuple[str, str] | None:
    """(state letter, start-time token) for a pid, or None if unreadable.

    Linux reads /proc/<pid>/stat (state + field 22). Hosts without /proc
    (non-procfs hosts) fall back to `ps -o stat=,lstart=`; the start token is only
    ever compared with one taken the same way on the same host."""
    try:
        stat = pathlib.Path(f"/proc/{pid}/stat").read_text()
        tail = stat.rsplit(")", 1)[-1].split()
        return tail[0], tail[19]
    except (OSError, IndexError):
        pass
    if pathlib.Path("/proc/self").exists():
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

    # Walk pid -> ppid ancestry when registered tasks exist (or custom ppid
    # override is supplied); with an empty registry only `pid` itself can
    # carry a spoofed marker, avoiding a full /proc ancestry walk per poll.
    chain: list[int] = []
    seen: set[int] = set()
    cur = pid
    max_hops = 32 if (recs or "ppid" in peer) else 1
    while cur > 1 and cur not in seen and len(chain) < max_hops:
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
        if rec is not None and rec.get("kind") == "session":
            # a session id rides its process: valid while that runs
            if _proc_running(by_id.get(rec.get("acp_process"))):
                return {"marked": True, "verified": True, "spoofed": False,
                        "task_id": rec["id"], "reason": "env_verified"}
        elif rec is not None and rec.get("status") == "running":
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
    targets = [rec]
    if rec.get("kind") == "acp_process":
        # a peer in the process scope is attributed to the visible
        # sessions it is running; none running -> the process record
        sess = [r for r in _latest(tasks_file)
                if r.get("kind") == "session" and r.get("status") == "running"
                and r.get("acp_process") == rec["id"]]
        targets = sess or [rec]
    count = 0
    for t in targets:
        count = int(t.get("refused_count") or 0) + 1
        cmds = list(t.get("refused_cmds") or [])
        if cmd:
            cmds.append(str(cmd))
        _log_line({
            "id": t["id"],
            "name": t["name"],
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
    if rec.get("kind") == "session":
        return status  # written by the runtime; _tick fails dead-process ones
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
    recs = _latest(tasks_file)
    by_id = {r["id"]: r for r in recs if r.get("id")}
    return [r for r in recs
            if (r.get("status") == "running"
                and _proc_running(by_id.get(r.get("acp_process")))
                if r.get("kind") == "session"
                else r.get("kind") != "acp_process"
                and _alive(r.get("pid", -1), r.get("pstart", "")))]


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


def _reap_expired(cfg: dict, tasks_file=config.TASKS_FILE,
                  recs: list | None = None) -> list:
    """SIGTERM running tasks past [agent] task_timeout_s — the runaway
    guardrail. Returns names of reaped tasks. An ACP session is
    cancelled through its manager and recorded `timed_out`; an ACP
    process record is never signalled from here (KTD14)."""
    timeout = int(cfg.get("agent", {}).get("task_timeout_s", "1800"))
    if timeout <= 0:
        return []
    now = datetime.now(timezone.utc)
    reaped = []
    for rec in (recs if recs is not None else _latest(tasks_file)):
        kind = rec.get("kind")
        if kind == "acp_process" or rec.get("status") != "running":
            continue
        acp = kind == "session"
        if not acp and not _alive(rec.get("pid", -1), rec.get("pstart", "")):
            continue
        # a bad timestamp reads as 0 s, so the record is left alone
        if _elapsed(rec) <= timeout:
            continue
        if acp:
            from . import acp_runtime
            mgr = acp_runtime.manager()
            if mgr is not None and mgr.expire(rec["id"]):
                reaped.append(rec["name"])
            continue
        _signal(rec, signal.SIGTERM)
        _log_line({"id": rec["id"], "name": rec["name"],
                   "status": "timed_out", "ts": now.isoformat()},
                  tasks_file)
        reaped.append(rec["name"])
    return reaped


_SHIM_CODE = (
    "import pathlib,signal,subprocess,sys;"
    "ef=pathlib.Path(sys.argv[1]);"
    "p=subprocess.Popen(sys.argv[2:]);"
    "signal.signal(signal.SIGTERM,lambda s,f:p.terminate());"
    "rc=p.wait();"
    "tmp=ef.with_suffix('.tmp');"
    "tmp.write_text(f'{rc}\\n');"
    "tmp.replace(ef);"
    "sys.exit(rc if rc>=0 else 128-rc)"
)
_EXEC_EXTS = frozenset({
    ".desktop", ".sh", ".bash", ".zsh", ".appimage", ".exe", ".bat", ".cmd",
})


def _exit_file(log_dir: pathlib.Path, task_id: str) -> pathlib.Path:
    return log_dir / f"{task_id}.exit"


def _wrap_exit_shim(cmd: list[str], exit_file: pathlib.Path) -> list[str]:
    """Wrap `cmd` so the child's exit code is persisted to `exit_file`
    regardless of whether the daemon holds the Popen handle."""
    return [sys.executable, "-c", _SHIM_CODE, str(exit_file), *cmd]


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


# Wisp-held credentials a spawned agent must not inherit (R11). The
# names Wisp's own config points at (every `key_env`) and the built-in
# defaults are dropped, as is any name in the .env file Wisp reads keys
# from. A runtime's own login (ANTHROPIC_API_KEY, CURSOR_API_KEY, ...)
# is not Wisp-held and passes through. `[agents] env_pass` (comma list)
# re-allows a name on purpose.
_WISP_KEY_NAMES = ("OPENROUTER_API_KEY", "GROQ_API_KEY")


def _key_env_names(cfg: dict) -> set[str]:
    names = set(_WISP_KEY_NAMES)
    for section in (cfg or {}).values():
        if not isinstance(section, dict):
            continue
        spec = section.get("key_env")
        if not isinstance(spec, str):
            continue
        for cand in (c.strip() for c in spec.split(",")):
            if cand and not cand.startswith("omaseal://"):
                names.add(cand)
    try:
        if config.ENV_FILE.exists():
            for line in config.ENV_FILE.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    names.add(line.split("=", 1)[0].strip()
                              .removeprefix("export ").strip())
    except OSError:
        pass
    return names


def scrub_env(env: dict, cfg: dict) -> dict:
    """Copy of `env` without Wisp-held credentials (see above)."""
    allow = {c.strip() for c in
             str((cfg or {}).get("agents", {}).get("env_pass", "")).split(",")
             if c.strip()}
    drop = _key_env_names(cfg) - allow
    return {k: v for k, v in env.items() if k not in drop}


def spawn(task: str, cfg: dict, tasks_file=config.TASKS_FILE,
          log_dir=config.TASK_LOGS, cwd: str | None = None, *,
          delivers: list[str] | None = None,
          spawned_by: str = "user",
          depth: int = 0,
          routine_id: str | None = None,
          name_hint: str | None = None,
          agent: str | None = None) -> str:
    """Spawn one run. `agent` names a persistent helper (B10): the run
    starts in that helper's folder, its outputs go to the folder's
    output/, and its identity, notes and waiting messages ride in the
    prompt."""
    task = task.strip()
    if not task:
        return "SKIP (empty agent task)"
    _reap()
    _reap_expired(cfg, tasks_file)
    cap = int(cfg.get("agent", {}).get("max_concurrent", "3"))
    if len(_running(tasks_file)) >= cap:
        return (f"SKIP (agent limit: {cap} already running — "
                "cancel one or raise [agent] max_concurrent)")
    name = _slug(name_hint or agent or task)
    base, i = name, 2
    existing = {r.get("name") for r in _records(tasks_file)}
    while name in existing:
        name = f"{base}-{i}"
        i += 1
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / f"{name}.log"
    out_dir = log_dir / name / "out"
    prompt = task
    if agent:
        from . import agent_home
        agent_home.create(agent)
        home = agent_home.home(agent)
        out_dir = home / "output"
        cwd = cwd or str(home)
        prompt = agent_home.prompt(agent, task)
    out_dir.mkdir(parents=True, exist_ok=True)
    if resolve_runtime(cfg) == "opencode":
        return _spawn_acp(name, task, prompt, cwd or str(out_dir), out_dir,
                          cfg, tasks_file, log_dir, delivers, spawned_by,
                          depth, routine_id, agent)
    exit_f = _exit_file(log_dir, name)
    exit_f.unlink(missing_ok=True)
    # [agents] model — distinct from [agent] model (that's the Jev
    # router); empty unless the user sets an agent-model override
    model = cfg.get("agents", {}).get("model", "")
    cmd = _runtime_cmd(cfg, model)
    if cmd is None:
        rt = cfg.get("brain", {}).get("agent_runtime", "auto")
        if rt == "auto":
            return ("SKIP (agent runtime 'auto' not on PATH — tried "
                    + "/".join(_AUTO_ORDER) + "; detected: none)")
        return (f"SKIP (agent runtime {rt!r} not on PATH — detected: "
                + (", ".join(detect_runtimes()) or "none") + ")")
    scope = _scope_unit(name)
    shimmed_cmd = _wrap_exit_shim(cmd, exit_f)
    exec_cmd = (wrap_systemd_scope(shimmed_cmd, name)
                if _systemd_scope_enabled(cfg) else shimmed_cmd)
    env = scrub_env(dict(os.environ), cfg)
    env["WISP_TASK_ID"] = name
    env["WISP_OUT_DIR"] = str(out_dir)
    spawn_ts = datetime.now(timezone.utc).isoformat()
    try:
        with log.open("ab") as lf:
            with private.text_stdin(prompt) as fin:
                proc = subprocess.Popen(
                    exec_cmd, stdout=lf, stderr=subprocess.STDOUT,
                    stdin=fin,
                    cwd=cwd or str(out_dir),
                    env=env,
                    start_new_session=True)
    except OSError as e:
        return f"SKIP (agent spawn failed: {e})"
    _EXIT_CODES.pop(proc.pid, None)  # drop a stale code from a prior pid owner
    _PROCS.append(proc)  # keep the handle so _reap can collect zombies
    rec = {
        "id": name, "name": name, "task": task, "pid": proc.pid,
        "pstart": _pstart(proc.pid),
        "scope": scope,
        "cmd": " ".join(cmd), "status": "running",
        "exit_code": None,
        "delivers": list(delivers or []),
        "spawned_by": spawned_by,
        "depth": int(depth),
        "out_dir": str(out_dir),
        "shimmed": True,
        "refused_count": 0,
        "ts": spawn_ts,
    }
    if routine_id:
        rec["routine_id"] = routine_id
    if agent:
        rec["agent"] = _slug(agent)
    _log_line(rec, tasks_file)
    return f"SPAWNED {name} (pid {proc.pid})"


def _spawn_acp(name, task, prompt, cwd, out_dir, cfg, tasks_file, log_dir,
               delivers, spawned_by, depth, routine_id, agent) -> str:
    """The opencode runtime: a session on the ACP manager (U9)."""
    from . import acp_runtime
    mgr = acp_runtime.manager()
    if mgr is None:
        return ("SKIP (agent runtime 'opencode' needs the running daemon: "
                "start wispd)")
    return mgr.start_task(name, task, prompt, cwd, out_dir, delivers,
                          spawned_by, depth, routine_id, agent, cfg,
                          tasks_file, log_dir)


def interrupted(tasks_file=config.TASKS_FILE) -> list:
    """Session records a restart left `interrupted`, oldest first."""
    return [r for r in _latest(tasks_file)
            if r.get("kind") == "session"
            and r.get("status") == "interrupted"]


def run_named(detail: str, cfg: dict, tasks_file=config.TASKS_FILE,
              **spawn_kw) -> str:
    """Handle a named-agent route (`agent_home.encode` payload): create a
    helper, tell one something, or say what is running. The result starts
    with ACTED so it is spoken."""
    from . import agent_home
    d = agent_home.decode(detail) or {}
    kind = d.get("kind")
    if kind == "create":
        name = d.get("name", "")
        made = agent_home.create(name, d.get("role", ""))
        shown = name
        if d.get("task"):
            out = spawn(d["task"], cfg, tasks_file, agent=name, **spawn_kw)
            if not out.startswith("SPAWNED"):
                return out
            return f"ACTED (0 steps): {shown} is on it."
        return (f"ACTED (0 steps): {shown} is ready. Say tell {shown} what "
                "to do." if made else
                f"ACTED (0 steps): {shown} already exists. Say tell {shown} "
                "what to do.")
    if kind == "tell":
        name, msg = d.get("name", ""), d.get("message", "")
        slug = _slug(name)
        from . import acp_runtime
        mgr = acp_runtime.manager()
        if mgr is not None and mgr.tell(slug, msg.strip()):
            return (f"ACTED (0 steps): {name} is on it. It does that after "
                    "its current step.")
        busy = [r for r in _running(tasks_file) if r.get("agent") == slug]
        if busy:
            agent_home.leave_message(name, msg)
            return (f"ACTED (0 steps): {name} is still working. I left it "
                    "your message for its next run.")
        out = spawn(msg, cfg, tasks_file, agent=name, **spawn_kw)
        return (f"ACTED (0 steps): {name} is on it."
                if out.startswith("SPAWNED") else out)
    if kind == "continue":
        want = _slug(d.get("name") or "")
        pend = [r for r in interrupted(tasks_file)
                if not d.get("name") or want in (r.get("agent"), r["id"])]
        if not pend:
            return "ACTED (0 steps): nothing is waiting to continue."
        from . import acp_runtime
        mgr = acp_runtime.manager()
        if mgr is None:
            return "SKIP (agent runtime needs the running daemon)"
        if len(_running(tasks_file)) >= int(
                cfg.get("agent", {}).get("max_concurrent", "3")):
            return "SKIP (agent limit reached)"
        return mgr.resume(pend[-1])
    if kind == "status":
        running = _running(tasks_file)
        if not running:
            return "ACTED (0 steps): nothing is running."
        parts = [f"{r.get('agent') or r.get('name')}: "
                 f"{str(r.get('task') or '')[:60]}" for r in running]
        return f"ACTED (0 steps): {len(running)} running. " + "; ".join(parts)
    return "SKIP (unknown agent request)"


# Daemon-spawned children — held so exited ones can be reaped (Popen
# objects keep the zombie until wait/poll is called on them).
_PROCS: list = []
_EXIT_CODES: dict[int, int] = {}


def _reap() -> None:
    """Collect exited agent children — otherwise they sit as zombies
    under the daemon until restart. Retains each child's returncode in
    `_EXIT_CODES` so `_tick` can record `done` (0) vs `failed`."""
    still: list = []
    for p in _PROCS:
        rc = p.poll()
        if rc is None:
            still.append(p)
        else:
            try:
                _EXIT_CODES[int(p.pid)] = int(rc)
            except (TypeError, ValueError):
                pass
    _PROCS[:] = still


# [brain] agent_runtime → argv. The prompt is private (a task can quote the
# screen or a dictated message) and argv is readable by other local
# accounts while the agent runs, so it is never in argv: each runtime reads
# it from stdin (spawn hands it an unlinked 0600 temp file).
_RUNTIMES = {
    "opencode": ["ori", "opencode", "run"],
    "codex": ["codex", "exec", "-"],
    "claude": ["claude", "-p"],
    "devin": ["devin", "--print", "--prompt-file", "-"],
}
_RUNTIME_BINS = {"opencode": "ori", "codex": "codex",
                 "claude": "claude", "devin": "devin"}
# `agent_runtime = "auto"` probes PATH in this order — opencode first.
_AUTO_ORDER = ["opencode", "codex", "claude", "devin"]


_RUNTIME_ROOT = None     # pinned install root; None = the Wisp data dir


def _pinned_state() -> dict:
    """The pinned ori + OpenCode install's probe state (no sign-in check)."""
    from . import probes_agents
    return probes_agents.AgentsProbe(_RUNTIME_ROOT).check(auth=False)


def _pinned_ready() -> bool:
    return _pinned_state().get("state") in ("installed", "ready")


def detect_runtimes() -> dict:
    """runtime → resolved binary path for everything available: the
    pinned install for opencode (never a `which ori`), PATH for the rest."""
    out = {}
    for rt, b in _RUNTIME_BINS.items():
        if rt == "opencode":
            if _pinned_ready():
                from . import agent_pins
                out[rt] = str(agent_pins.runtime_paths(_RUNTIME_ROOT)["ori"])
        elif shutil.which(b):
            out[rt] = shutil.which(b)
    return out


def resolve_runtime(cfg: dict) -> str:
    """Configured runtime, or the first detected one when 'auto'."""
    rt = cfg.get("brain", {}).get("agent_runtime", "auto")
    if rt != "auto":
        return rt
    for cand in _AUTO_ORDER:
        if (_pinned_ready() if cand == "opencode"
                else shutil.which(_RUNTIME_BINS[cand])):
            return cand
    return ""


def _runtime_cmd(cfg: dict, model: str) -> list | None:
    """argv for the configured agent runtime (the prompt goes to stdin,
    not argv), or None when its binary isn't on PATH (U6: probe →
    explicit error, not a silent failure)."""
    rt = resolve_runtime(cfg)
    if not rt:
        return None
    template = _RUNTIMES.get(rt, _RUNTIMES["opencode"])
    if not shutil.which(_RUNTIME_BINS.get(rt, "ori")):
        return None
    cmd = list(template)
    if model and rt == "opencode":
        cmd[3:3] = ["--model", model]  # after 'run'
    elif model and rt == "codex":
        cmd[2:2] = ["-m", model]       # before the "-" stdin prompt
    elif model and rt == "claude":
        cmd += ["--model", model]
    return cmd


def cancel(name: str, tasks_file=config.TASKS_FILE) -> str:
    _reap()
    rec = _find(name, tasks_file)
    if not rec:
        return f"SKIP (no task {name!r})"
    if rec.get("kind") == "session":
        from . import acp_runtime
        mgr = acp_runtime.manager()
        out = mgr.cancel(rec["id"]) if mgr is not None else None
        return out or f"SKIP ({name} not running)"
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


def _resolve_exit_code(rec: dict, log_dir: pathlib.Path,
                       pid_reused: bool = False) -> int | None:
    """Resolve a finished task's integer exit code from disk shim, `_EXIT_CODES`,
    or record field. Returns None when no exit-code evidence exists (legacy
    manual records or a recycled PID)."""
    tid = rec.get("id") or rec.get("name") or ""
    pid = rec.get("pid", -1)
    # Consume the cached code up front so no path (incl. the .exit file
    # one) leaves a stale entry for a later task that reuses the pid. A
    # recycled pid's entry is not ours to take.
    cached = None
    if not pid_reused and isinstance(pid, int):
        cached = _EXIT_CODES.pop(pid, None)
    if tid:
        ef = _exit_file(log_dir, tid)
        if ef.is_file():
            try:
                return int(ef.read_text().strip().splitlines()[-1])
            except (OSError, ValueError, IndexError):
                pass
    if cached is not None:
        return cached
    if rec.get("exit_code") is not None:
        try:
            return int(rec["exit_code"])
        except (TypeError, ValueError):
            pass
    if rec.get("shimmed") and not pid_reused:
        # Shimmed child died without writing .exit -> uncatchable signal
        return -int(signal.SIGKILL)
    return None


def verify_deliverables(rec: dict, finished_ts: datetime | None = None,
                        log_dir=config.TASK_LOGS,
                        final_status: str = "done") -> dict:
    """Verify declared `delivers` files on disk at reap time (U2, R1, KTD3).

    Each item must exist as a regular file, be non-empty, and have an `mtime`
    inside the task's run window. Paths outside `out_dir`, symlinks escaping
    `out_dir`, and executable/`.desktop` files are recorded with `flagged=True`
    and `openable=False` (never offered as a notification open action).
    """
    tid = rec.get("id") or rec.get("name") or "task"
    out_dir = pathlib.Path(rec.get("out_dir") or (log_dir / tid / "out"))
    task_dir = out_dir.parent
    out_lex = pathlib.Path(os.path.normpath(str(out_dir.absolute())))
    try:
        out_real = out_dir.resolve()
    except OSError:
        out_real = out_lex

    started_str = rec.get("started") or rec.get("ts") or ""
    started_epoch = 0.0
    if started_str:
        try:
            started_epoch = datetime.fromisoformat(started_str).timestamp()
        except ValueError:
            started_epoch = 0.0
    fin_epoch = (finished_ts.timestamp()
                 if finished_ts is not None
                 else datetime.now(timezone.utc).timestamp())

    declared_list = list(rec.get("delivers") or [])
    deliverables: list[dict] = []

    for decl in declared_list:
        decl_str = str(decl).strip()
        if not decl_str:
            continue
        p = pathlib.Path(decl_str)
        if p.is_absolute():
            cand = p
        elif p.parts and p.parts[0] == "out":
            cand = task_dir / p
        else:
            cand = out_dir / p

        cand_lex = pathlib.Path(os.path.normpath(str(cand.absolute())))
        lexical_inside = (cand_lex == out_lex or out_lex in cand_lex.parents
                          or cand_lex == out_real
                          or out_real in cand_lex.parents)
        try:
            cand_real = cand.resolve()
        except OSError:
            cand_real = cand_lex
        resolved_inside = (cand_real == out_real
                           or out_real in cand_real.parents)

        exists_reg = False
        size = 0
        mtime = 0.0
        is_exec = False
        try:
            if cand.exists() and cand_real.is_file():
                st = cand_real.stat()
                exists_reg = True
                size = int(st.st_size)
                mtime = float(st.st_mtime)
                ext = cand_real.suffix.lower()
                is_exec = bool(st.st_mode & 0o111) or ext in _EXEC_EXTS
        except OSError:
            exists_reg = False

        if not lexical_inside:
            flagged, flag_reason = True, "outside_out_dir"
        elif not resolved_inside:
            flagged, flag_reason = True, "symlink_escape"
        elif is_exec:
            flagged, flag_reason = True, "executable"
        else:
            flagged, flag_reason = False, ""

        if not exists_reg:
            item_status, reason = "missing", "not_found"
        elif size <= 0:
            item_status, reason = "missing", "empty"
        elif started_epoch > 0 and mtime < started_epoch:
            item_status, reason = "missing", "stale_mtime"
        elif fin_epoch > 0 and mtime > fin_epoch + 10.0:
            item_status, reason = "missing", "future_mtime"
        else:
            item_status, reason = "delivered", ""

        openable = (item_status == "delivered" and not flagged
                    and lexical_inside and resolved_inside and not is_exec)
        deliverables.append({
            "declared": decl_str,
            "name": p.name or decl_str,
            "path": str(cand_real if exists_reg else cand),
            "status": item_status,
            "flagged": flagged,
            "flag_reason": flag_reason,
            "openable": openable,
            "reason": reason,
        })

    if deliverables:
        delivered = (final_status == "done"
                     and all(d["status"] == "delivered" for d in deliverables))
    else:
        delivered = (final_status == "done")

    return {
        "delivered": delivered,
        "deliverables": deliverables,
        "open_actions": [d["path"] for d in deliverables if d["openable"]],
        "out_dir": str(out_dir),
    }


def build_done_notification(t: dict) -> dict:
    """Build the honest completion notification + safe open actions for `t`."""
    name = t.get("name", "task")
    status = t.get("status", "exited")
    deliverables = list(t.get("deliverables") or [])
    missing = [d.get("name") or d.get("declared", "?")
               for d in deliverables if d.get("status") != "delivered"]
    present = [d.get("name") or d.get("declared", "?")
               for d in deliverables if d.get("status") == "delivered"]
    open_actions = [d["path"] for d in deliverables if d.get("openable")]
    refused = int(t.get("refused_count") or 0)

    if missing:
        msg = f"wisp agent '{name}' claims {', '.join(missing)} — not on disk"
    elif status == "done" and present:
        msg = f"wisp agent '{name}' done — delivered {', '.join(present)}"
    else:
        answer = " ".join(str(t.get("answer") or "").split())[:300]
        tail = answer if status == "done" and answer \
            else (t.get("tail") or "")[:80]
        msg = f"wisp agent '{name}' {status}" + (f" — {tail}" if tail else "")

    if refused > 0:
        word = "command" if refused == 1 else "commands"
        msg += f" — {refused} {word} refused (mutation blocked)"

    delivered = bool(t.get("delivered",
                           status == "done" and not missing))
    return {
        "message": msg,
        "open_actions": open_actions,
        "delivered": delivered,
    }


def notify_done(t: dict, notify_fn=None) -> dict:
    """Format and send the completion notification for a reaped task."""
    info = build_done_notification(t)
    # U3: routine runs are quiet on success and only notify on the 3-failure
    # auto-pause transition (`notify_user_once=True`).
    rout = t.get("routine_outcome")
    if isinstance(rout, dict):
        if rout.get("ok"):
            info["notified"] = False
            return info
        if not rout.get("notify_user_once"):
            info["notified"] = False
            return info
        rid = rout.get("id") or t.get("routine_id") or t.get("name", "routine")
        info["message"] = (
            f"wisp routine '{rid}' paused after "
            f"{rout.get('consecutive_failures', 3)} consecutive failures"
        )
    if notify_fn is None:
        from .tools import system as _sys
        notify_fn = _sys.notify_tool
    notify_fn(info["message"])
    info["notified"] = True
    return info


def output(name: str, tasks_file=config.TASKS_FILE,
           log_dir=config.TASK_LOGS, max_bytes: int = 65536) -> dict:
    """IPC/CLI read: log output and exit status for task `name` (U2)."""
    _reap()
    rec = _find(name, tasks_file)
    if not rec:
        return {"ok": False, "error": f"no task {name!r}", "name": name,
                "status": "", "exit_code": None, "output": ""}
    log = log_dir / f"{rec['id']}.log"
    text = ""
    try:
        with log.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            text = f.read().decode(errors="replace")
    except OSError:
        text = ""
    return {
        "ok": True,
        "name": rec["name"],
        "status": _state_of(rec),
        "exit_code": rec.get("exit_code"),
        "output": text,
    }


def artifacts(name: str, tasks_file=config.TASKS_FILE,
              log_dir=config.TASK_LOGS) -> dict:
    """IPC/CLI read: workspace files + deliverable status for `name` (U2)."""
    _reap()
    rec = _find(name, tasks_file)
    if not rec:
        return {"ok": False, "error": f"no task {name!r}", "name": name,
                "out_dir": "", "delivered": False, "deliverables": [],
                "artifacts": []}
    tid = rec.get("id") or rec["name"]
    out_dir = pathlib.Path(rec.get("out_dir") or (log_dir / tid / "out"))
    try:
        out_real = out_dir.resolve()
    except OSError:
        out_real = out_dir.absolute()
    st_now = _state_of(rec)
    dinfo = verify_deliverables(
        rec, log_dir=log_dir,
        final_status="done" if st_now == "done" else st_now)
    deliverables = rec.get("deliverables")
    if deliverables is None:
        deliverables = dinfo["deliverables"]
    delivered = rec.get("delivered")
    if delivered is None:
        delivered = dinfo["delivered"]

    files: list[dict] = []
    if out_dir.is_dir():
        for p in sorted(out_dir.rglob("*")):
            try:
                real = p.resolve()
                inside = (real == out_real or out_real in real.parents)
                if not real.is_file():
                    continue
                st = real.stat()
                is_exec = (bool(st.st_mode & 0o111)
                           or real.suffix.lower() in _EXEC_EXTS)
                files.append({
                    "name": str(p.relative_to(out_dir)),
                    "path": str(real),
                    "size": int(st.st_size),
                    "openable": bool(inside and not p.is_symlink()
                                     and not is_exec and st.st_size > 0),
                })
            except OSError:
                continue
    return {
        "ok": True,
        "name": rec["name"],
        "out_dir": str(out_dir),
        "delivered": bool(delivered),
        "deliverables": list(deliverables),
        "artifacts": files,
    }


def _elapsed(rec: dict) -> int:
    try:
        begin = datetime.fromisoformat(rec.get("resumed")
                                       or rec.get("started", ""))
    except (ValueError, TypeError):
        return 0
    return max(0, int((datetime.now(timezone.utc) - begin).total_seconds()))


def tasks(tasks_file=config.TASKS_FILE,
          log_dir=config.TASK_LOGS, recs: list | None = None) -> dict:
    """name -> {status, task, ts, tail, ...} for state.json publication —
    `tail` is the log's last non-empty line so the panel/orb shows live
    progress on long-running agents. Only running tasks get a tail read
    — finished logs never change."""
    _reap()
    if recs is None:
        recs = _latest(tasks_file)
    out = {}
    for rec in recs:
        if rec.get("kind") == "acp_process":
            continue
        status = _state_of(rec)
        entry = {
            "status": status,
            "task": rec.get("task", ""),
            "ts": rec.get("ts", ""),
            "tail": _tail(log_dir / f"{rec['id']}.log")
            if status == "running" else "",
        }
        if "exit_code" in rec:
            entry["exit_code"] = rec.get("exit_code")
        if "delivered" in rec:
            entry["delivered"] = rec.get("delivered")
        if "deliverables" in rec:
            entry["deliverables"] = rec.get("deliverables")
        if "out_dir" in rec:
            entry["out_dir"] = rec.get("out_dir")
        if rec.get("refused_count"):
            entry["refused_count"] = rec.get("refused_count")
        if rec.get("routine_id"):
            entry["routine_id"] = rec.get("routine_id")
        if "unread" in rec:
            entry["unread"] = bool(rec.get("unread"))
        if rec.get("kind") == "session" and status == "running":
            # the ACP session's live step and elapsed time (KTD13)
            entry["line"] = entry["tail"]
            entry["seconds"] = _elapsed(rec)
            from . import acp_runtime
            if acp_runtime.waiting(rec):
                entry["waiting"] = True
        out[rec["name"]] = entry
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


def _record_routine_for_task(rec: dict, final_status: str, delivered: bool,
                             routines_store=None) -> dict | None:
    """Record a finished task's outcome in `RoutineStore` when `routine_id`
    is present on `rec` (U3)."""
    rid = rec.get("routine_id")
    if not rid:
        return None
    from . import routines
    ok = (final_status == "done") and bool(delivered)
    # a run that failed while the network is gone is a missed run, not a
    # failing routine
    offline = not ok and not routines.online(None)
    outcome = routines.record_routine_outcome(rid, ok=ok, store=routines_store,
                                              offline=offline)
    return {
        "id": outcome.get("id", rid),
        "ok": bool(outcome.get("ok")),
        "unread": bool(outcome.get("unread")),
        "paused": bool(outcome.get("paused")),
        "auto_paused": bool(outcome.get("auto_paused")),
        "notify_user_once": bool(outcome.get("notify_user_once")),
        "consecutive_failures": int(outcome.get("consecutive_failures", 0)),
        "speak": False,
    }


def _tick(cfg: dict, tasks_file, log_dir, kill_grace_s: float,
          recs: list | None = None, routines_store=None) -> dict:
    """One reaper pass; returns the fresh `tasks()` snapshot."""
    _reap()
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    if recs is None:
        recs = _latest(tasks_file)
    by_id = {r["id"]: r for r in recs if r.get("id")}
    for rec in recs:
        pid, pstart = rec.get("pid", -1), rec.get("pstart", "")
        alive = _alive(pid, pstart)
        status = rec.get("status")
        if rec.get("kind") == "session":
            # status is the runtime's; only a dead process fails it
            if status == "running" \
                    and not _proc_running(by_id.get(rec.get("acp_process"))):
                _log_line({"id": rec["id"], "name": rec["name"],
                           "status": "failed", "error": "process exited",
                           "ts": stamp}, tasks_file)
            continue
        if rec.get("kind") == "acp_process":
            if status == "running" and not alive:
                _log_line({"id": rec["id"], "name": rec["name"],
                           "status": "exited", "ts": stamp}, tasks_file)
            continue
        if status == "running" and not alive:
            # process gone, or its pid now belongs to someone else
            st = _proc_stat(pid) if pid > 0 else None
            pid_reused = bool(st and st[0] != "Z"
                              and pstart and st[1] != pstart)
            ec = _resolve_exit_code(rec, log_dir, pid_reused=pid_reused)
            if ec is not None:
                final_status = "done" if ec == 0 else "failed"
            else:
                final_status = "exited"
            dinfo = verify_deliverables(
                rec, finished_ts=now, log_dir=log_dir,
                final_status=final_status)
            close_rec = {
                "id": rec["id"],
                "name": rec["name"],
                "status": final_status,
                "ts": stamp,
            }
            if ec is not None:
                close_rec["exit_code"] = ec
                close_rec["delivered"] = dinfo["delivered"]
            if rec.get("delivers") or dinfo["deliverables"]:
                close_rec["delivered"] = dinfo["delivered"]
                close_rec["deliverables"] = dinfo["deliverables"]
                close_rec["open_actions"] = dinfo["open_actions"]
            if rec.get("routine_id") and not rec.get("routine_recorded"):
                rout = _record_routine_for_task(
                    rec, final_status, dinfo["delivered"],
                    routines_store=routines_store)
                if rout is not None:
                    close_rec["routine_id"] = rec["routine_id"]
                    close_rec["routine_recorded"] = True
                    close_rec["routine_outcome"] = rout
                    close_rec["unread"] = rout["unread"]
            _log_line(close_rec, tasks_file)
        elif (status in ("cancelled", "timed_out") and not alive
              and rec.get("routine_id") and not rec.get("routine_recorded")):
            # closed by cancel/_reap_expired: the run never reached the
            # `running and not alive` branch, so record its (failed)
            # outcome here or a hung routine never auto-pauses (R3).
            rout = _record_routine_for_task(
                rec, status, False, routines_store=routines_store)
            if rout is not None:
                _log_line({
                    "id": rec["id"], "name": rec["name"],
                    "routine_id": rec["routine_id"],
                    "routine_recorded": True,
                    "routine_outcome": rout,
                    "unread": rout["unread"],
                    "ts": stamp,
                }, tasks_file)
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
              kill_grace_s: float = KILL_GRACE_S,
              routines_store=None) -> list:
    """One reaper pass. Returns the tasks that went running -> not
    running during it (`finished()` shape)."""
    return _tick_events(cfg, tasks_file, log_dir, kill_grace_s,
                        routines_store=routines_store)[1]


def _tick_events(cfg, tasks_file, log_dir, kill_grace_s,
                 routines_store=None) -> tuple:
    """(tasks snapshot, finished list). A task is `finished` when its
    registry status was `running` before the pass and is not after —
    judged on the raw record, since `tasks()` already reads a dead
    unclosed task as exited."""
    recs = _latest(tasks_file)
    by_id = {r["id"]: r for r in recs if r.get("id")}
    # an ACP session's own runtime reports its end (finished_entry); the
    # reaper only owns one whose process died under it
    was_running = {r["name"] for r in recs
                   if r.get("status") == "running"
                   and (r.get("kind") != "session"
                        or not _proc_running(by_id.get(r.get("acp_process"))))}
    cur = _tick(cfg, tasks_file, log_dir, kill_grace_s, recs=recs,
                routines_store=routines_store)
    # a just-finished task's tail is its final output — read it for the
    # event even though tasks() only tails running tasks
    done = []
    for n in cur:
        if n in was_running and cur[n]["status"] != "running":
            done.append(finished_entry(n, cur[n], _find(n, tasks_file),
                                       log_dir))
    return cur, done


_FINISH_KEYS = ("exit_code", "delivered", "deliverables", "open_actions",
                "out_dir", "refused_count", "routine_id", "routine_outcome",
                "unread", "answer", "stop_reason")
_EVENT_KEYS = ("exit_code", "delivered", "deliverables", "open_actions",
               "refused_count", "routine_id")


def finished_entry(name: str, cur: dict, rec: dict | None,
                   log_dir=config.TASK_LOGS) -> dict:
    """The `finished()`-shaped entry for a task that just ended."""
    entry = {"name": name, **cur}
    if rec is not None:
        if not entry["tail"]:
            entry["tail"] = _tail(log_dir / f"{rec['id']}.log")
        for k in _FINISH_KEYS:
            if k in rec and k not in entry:
                entry[k] = rec[k]
    return entry


def emit_finished(bus, t: dict, on_finished=None) -> None:
    """One `task_finished` event and the on_finished callback."""
    ev_kw = {"name": t["name"], "status": t["status"], "tail": t["tail"]}
    for k in _EVENT_KEYS:
        if k in t:
            ev_kw[k] = t[k]
    bus.emit_event("task_finished", **ev_kw)
    if on_finished:
        on_finished(t)


def _kill_scope(scope: str, sig: int) -> None:
    """Best-effort signal to a systemd scope (reaches descendants that
    left the process group); no systemd -> a no-op."""
    if not scope or not shutil.which("systemctl"):
        return
    try:
        subprocess.run(["systemctl", "--user", "kill",
                        f"--signal={signal.Signals(sig).name}", scope],
                       capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def sweep_orphans(tasks_file=config.TASKS_FILE,
                  kill_grace_s: float = KILL_GRACE_S) -> list:
    """Daemon start: every ACP process record still `running` belongs to
    a previous daemon. A live one (pstart matching) is SIGTERMed via its
    scope, then SIGKILLed after the grace; a record whose pid now belongs
    to someone else is never signalled. Either way the record closes and
    its running sessions become `interrupted` (never replayed, R12)."""
    recs = _latest(tasks_file)
    procs = [r for r in recs if r.get("kind") == "acp_process"
             and r.get("status") == "running"]
    live = [r for r in procs if r.get("pstart")
            and _alive(r.get("pid", -1), r["pstart"])]
    for r in live:
        _kill_scope(r.get("scope", ""), signal.SIGTERM)
        _signal(r, signal.SIGTERM)
    deadline = time.monotonic() + kill_grace_s
    while live and time.monotonic() < deadline:
        live = [r for r in live if _alive(r["pid"], r["pstart"])]
        if live:
            time.sleep(0.05)
    for r in live:
        _kill_scope(r.get("scope", ""), signal.SIGKILL)
        _signal(r, signal.SIGKILL)
    stamp = datetime.now(timezone.utc).isoformat()
    ids = {r["id"] for r in procs}
    swept = []
    for r in recs:
        if r.get("kind") == "session" and r.get("status") == "running" \
                and r.get("acp_process") in ids:
            _log_line({"id": r["id"], "name": r["name"],
                       "status": "interrupted", "ts": stamp}, tasks_file)
            swept.append(r["name"])
    for r in procs:
        _log_line({"id": r["id"], "name": r["name"], "status": "exited",
                   "ts": stamp}, tasks_file)
    return swept


def reconcile_routines(cfg: dict, tasks_file=config.TASKS_FILE,
                       log_dir=config.TASK_LOGS, routines_store=None,
                       on_finished=None) -> list:
    """Reconcile any daemon-down fallback routine runs on daemon start (U3).

    Runs one reaper pass (closing dead `running` tasks and recording their
    routine outcomes) and also reconciles any already-closed routine task
    whose outcome was not yet written to `RoutineStore`."""
    _, done = _tick_events(cfg, tasks_file, log_dir, KILL_GRACE_S,
                           routines_store=routines_store)
    seen = {t["name"] for t in done}
    for rec in _latest(tasks_file):
        if (rec.get("routine_id") and not rec.get("routine_recorded")
                and _state_of(rec) != "running"
                and rec.get("name") not in seen):
            st_now = _state_of(rec)
            delivered = bool(rec.get("delivered", st_now == "done"))
            rout = _record_routine_for_task(
                rec, st_now, delivered, routines_store=routines_store)
            if rout is not None:
                _log_line({
                    "id": rec["id"],
                    "name": rec["name"],
                    "routine_id": rec["routine_id"],
                    "routine_recorded": True,
                    "routine_outcome": rout,
                    "unread": rout["unread"],
                }, tasks_file)
                entry = {
                    "name": rec["name"],
                    "status": st_now,
                    "tail": _tail(log_dir / f"{rec['id']}.log"),
                    "routine_id": rec["routine_id"],
                    "routine_outcome": rout,
                    "unread": rout["unread"],
                }
                done.append(entry)
    if on_finished:
        for t in done:
            on_finished(t)
    return done


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
        from . import acp_runtime
        try:
            # a running manager already swept at its own start; sweeping
            # again would kill the processes it has launched since
            if acp_runtime.manager() is None:
                sweep_orphans(tasks_file, kill_grace_s)
        except Exception:
            pass
        while not stop.is_set():
            try:
                cur, done = _tick_events(cfg, tasks_file, log_dir,
                                         kill_grace_s)
                bus.publish(None, tasks=cur)
                for t in done:
                    emit_finished(bus, t, on_finished)
            except Exception:
                pass  # a bad record must never kill the reaper
            stop.wait(interval_s)
    th = threading.Thread(target=run, name="agent-reaper", daemon=True)
    th.start()
    return th
