"""ACP runtime for the `opencode` agent runtime (U9, KTD1/3/5/13/14).

A `Manager` owns one `HelperProcess` per named helper (or per unnamed
task): a long-lived `ori opencode acp` child launched from the pinned
install under the private OpenCode home, inside the exit shim and the
systemd scope, with a process record in the registry. Each task is a
`SessionRun`: its own ACP session (own MCP token, model picked from
`[agents] acp_models`), a prompt queue that runs one prompt at a time
and never drops one, and a worker thread. Updates become readable lines
in `tasks/<id>.log`; permission requests go through `agent_policy` and,
when risky, the daemon ask queue; the stop reason, not the agent's
words, decides the status.

The manager is a daemon-wide singleton (`set_manager`). `agents.spawn`,
`run_named`, `cancel` and `_reap_expired` route to it for opencode;
codex/claude/devin never touch it.
"""
import collections
import os
import pathlib
import re
import signal
import sys
import threading
import time
from datetime import datetime, timezone

from . import (acp, agent_ask, agent_mcp, agent_ochome, agent_policy, agents,
               config)

DEFAULT_MODELS = ("openrouter/particle-ai/particle-1,"
                  "openrouter/deepseek/deepseek-v4-flash,"
                  "openrouter/deepseek/deepseek-v4.1-flash,"
                  "openrouter/google/gemini-3.5-flash-lite")
PROGRESS_GAP_S = 2.0        # task_progress events: at most one per 2 s
LINE_MAX = 200
ANSWER_MAX = 4000
SWEEP_S = 5.0
RESUME_PROMPT = "Continue where you left off."

_MANAGER = None


def manager():
    return _MANAGER


def set_manager(mgr) -> None:
    global _MANAGER
    _MANAGER = mgr


class _Skip(Exception):
    """The runtime can't start: spawn answers `SKIP (<reason>)`."""


class _Fail(Exception):
    """A session ends `failed` with this reason."""


def _opt(cfg, key, default) -> str:
    return str((cfg.get("agents") or {}).get(key, default)).strip()


def _secs(cfg, key, default) -> float:
    try:
        return max(0.0, float(_opt(cfg, key, default)))
    except ValueError:
        return float(default)


def configured_models(cfg) -> list:
    return [m.strip() for m in _opt(cfg, "acp_models", DEFAULT_MODELS)
            .split(",") if m.strip()]


def _one_line(text, n=LINE_MAX) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:n]


def _model_option(options):
    for o in options or []:
        if isinstance(o, dict) and (o.get("category") == "model"
                                    or o.get("id") == "model"):
            return o
    return None


def _offered(opt) -> list:
    out = []
    for o in (opt or {}).get("options") or []:
        if isinstance(o, dict) and "value" in o:
            out.append(o["value"])
        elif isinstance(o, dict):           # a group of options
            out += [g["value"] for g in o.get("options") or []
                    if isinstance(g, dict) and "value" in g]
    return out


def waiting(rec: dict) -> bool:
    """True while a question or risky-action ask from this task is
    pending (the `waiting` marker the Agents tab shows)."""
    names = {rec.get("name"), rec.get("agent")} - {None, ""}
    if agent_mcp.is_asking(names):
        return True
    mgr = _MANAGER
    return bool(mgr and mgr.asking(names))


class HelperProcess:
    def __init__(self, mgr, key, tf, ld, ephemeral):
        self.mgr, self.id, self.tf, self.ld = mgr, key, tf, ld
        self.ephemeral = ephemeral
        self.conn = None
        self.rec: dict = {}
        self.active = 0                 # runs holding this process
        self.idle_since = mgr.clock()
        self.closing = False
        self._shut = False
        self.sessions: dict = {}        # session id -> SessionRun

    def usable(self) -> bool:
        return (self.conn is not None and self.conn.dead is None
                and not self.closing)

    def start(self, cfg, cwd) -> None:
        st = agents._pinned_state()
        if st.get("state") not in ("installed", "ready"):
            fix = st.get("fix") or "wispd install --agents"
            if st.get("state") == "opencode_v1":
                raise _Skip("OpenCode 1.x is installed; Wisp only drives "
                            f"2.x. Fix: {fix}")
            raise _Skip(f"agent runtime is {st.get('state')}. Fix: {fix}")
        agent_ochome.write_config(cfg, self.mgr.home)
        argv, env = agent_ochome.launch(cfg, os.environ, self.mgr.home,
                                        self.mgr.runtime_root)
        env["WISP_TASK_ID"] = self.id
        self.ld.mkdir(parents=True, exist_ok=True)
        exit_f = agents._exit_file(self.ld, self.id)
        exit_f.unlink(missing_ok=True)
        cmd = agents._wrap_exit_shim(argv, exit_f)
        if agents._systemd_scope_enabled(cfg):
            cmd = agents.wrap_systemd_scope(cmd, self.id)
        try:
            # its own session, so the registry can signal the whole group
            self.conn = acp.AcpConnection(
                cmd, env=env, cwd=str(cwd), on_update=self._on_update,
                on_permission=self._on_permission, start_new_session=True)
        except OSError as e:
            raise _Skip(f"agent spawn failed: {e}") from None
        self.rec = agents.record_process(
            self.id, self.conn.pid, agents._scope_unit(self.id),
            self.tf)
        try:
            self.conn.initialize()
        except acp.AcpVersionError as e:
            self.shutdown(kill=True)
            raise _Skip(f"agent runtime refused: {e}") from None
        except (acp.AcpError, TimeoutError) as e:
            self.shutdown(kill=True)
            raise _Skip(f"agent failed to start: {e}") from None

    # reader-thread callbacks -------------------------------------------

    def _on_update(self, sid, upd):
        run = self.sessions.get(sid)
        if run is not None:
            run.on_update(upd)

    def _on_permission(self, sid, tool_call, options, reply):
        run = self.sessions.get(sid)
        if run is None:
            reply()
        else:
            run.on_permission(tool_call, options, reply)

    # teardown ------------------------------------------------------------

    def shutdown(self, kill=False) -> None:
        """Stop the process and everything in its scope, close its
        record. Idempotent."""
        if self._shut:
            return
        self._shut = True
        self.closing = True
        sig = signal.SIGKILL if kill else signal.SIGTERM
        if self.conn is not None:
            if agents._systemd_scope_enabled(self.mgr.cfg):
                agents._kill_scope(agents._scope_unit(self.id), sig)
            agents._signal(self.rec, sig)
            self.conn.close()
        agents._log_line({"id": self.id, "name": self.id, "status": "exited",
                          "ts": datetime.now(timezone.utc).isoformat()},
                         self.tf)


class SessionRun:
    def __init__(self, mgr, proc, name, task, prompt, cwd, out_dir, agent,
                 tf, ld, cfg, resume_sid=""):
        self.mgr, self.proc, self.id, self.task = mgr, proc, name, task
        self.agent, self.cwd, self.out_dir = agent, str(cwd), str(out_dir)
        self.tf, self.ld, self.cfg = tf, ld, cfg
        self.resume_sid = resume_sid
        # a helper's whole folder (notes/, tmp/, output/) is its own;
        # an unnamed task works inside its out dir
        self.policy = agent_policy.SessionPolicy.from_cfg(
            cfg, self.cwd, self.cwd if agent else self.out_dir)
        self.lock = threading.Lock()
        self.queue = collections.deque([prompt])
        self.closed = self.finished = False
        self.cancelling = self.timed_out = False
        self.ended = threading.Event()
        self.sid = self.token = self.model = ""
        self.loading = False
        self.stop_reason = None
        self.outcome = ("done", "")
        self.answer = ""
        self.since_tool: list = []
        self.buf = ""
        self.titles: dict = {}
        self.last_line = ""
        self.last_emit = None
        self.started = mgr.clock()
        self.log = ld / f"{name}.log"
        ld.mkdir(parents=True, exist_ok=True)

    # worker --------------------------------------------------------------

    def run(self) -> None:
        try:
            self._open()
            while True:
                with self.lock:
                    if self.cancelling or not self.queue:
                        self.closed = True
                        self.queue.clear()
                        break
                    text = self.queue.popleft()
                if not self._turn(text):
                    break
            self._settle()
        except _Fail as e:
            self.finish("failed", str(e))
        except Exception as e:  # noqa: BLE001 — never leave it "running"
            self.finish("failed", f"{type(e).__name__}: {e}")

    def _settle(self) -> None:
        if self.cancelling:
            self.finish("timed_out" if self.timed_out else "cancelled")
        else:
            self.finish(*self.outcome)

    def _open(self) -> None:
        conn = self.proc.conn
        self.token = agent_mcp.mint(self.id)
        mcp = [{"name": "wisp", "command": self.mgr.wispd,
                "args": ["agent-mcp"],
                "env": [{"name": "WISP_MCP_TOKEN", "value": self.token}]}]
        try:
            if self.resume_sid:
                self.sid, self.loading = self.resume_sid, True
                self.proc.sessions[self.sid] = self
                res = conn.load_session(self.sid, self.cwd, mcp)
                self.loading = False
            else:
                res = conn.new_session(self.cwd, mcp)
                self.sid = res["sessionId"]
                self.proc.sessions[self.sid] = self
                agents._log_line({"id": self.id, "name": self.id,
                                  "session_id": self.sid}, self.tf)
            self._choose_model(conn, res.get("configOptions"))
        except (acp.AcpError, TimeoutError, KeyError) as e:
            raise _Fail(self._dead_reason(e)) from None

    def _choose_model(self, conn, options) -> None:
        opt = _model_option(options)
        offered = _offered(opt)
        want = next((m for m in configured_models(self.cfg)
                     if m in offered), None)
        if want is None:
            raise _Fail("none of the configured cheap models is available")
        out = conn.set_config_option(self.sid, opt["id"], want)
        now = _model_option(out.get("configOptions"))
        if not now or now.get("currentValue") != want:
            raise _Fail(f"model {want} was not applied")
        self.model = want
        agents._log_line({"id": self.id, "name": self.id, "model": want},
                         self.tf)

    def _dead_reason(self, err) -> str:
        if isinstance(err, acp.AcpClosed):
            return f"process exited: {self.last_line or err}"
        return str(err)

    def _turn(self, text) -> bool:
        """Run one prompt. False when the session is over."""
        conn = self.proc.conn
        self.since_tool, self.buf = [], ""
        try:
            handle = conn.prompt(self.sid, text)
            if self.cancelling:
                conn.cancel(self.sid)
            stop = handle.wait(None)
        except acp.AcpClosed as e:
            if self.cancelling:
                return False
            raise _Fail(self._dead_reason(e)) from None
        except acp.AcpError as e:
            raise _Fail(str(e)) from None
        self._flush_buf()
        self.answer = "".join(self.since_tool).strip()
        self.stop_reason = stop
        if stop == "cancelled":
            self.cancelling = True
            return False
        if stop == "end_turn":
            self.outcome = ("done", "")
        else:
            self.outcome = ("failed", f"agent stopped: {stop}")
        return True

    # queue / cancel ------------------------------------------------------

    def enqueue(self, text) -> bool:
        with self.lock:
            # a cancelling run never reads its queue again: refuse, so the
            # caller falls back to a new session instead of dropping it
            if self.closed or self.cancelling:
                return False
            self.queue.append(text)
            return True

    def request_cancel(self) -> None:
        with self.lock:
            self.cancelling = True
            self.queue.clear()
        if self.sid and self.proc.usable():
            self.proc.conn.cancel(self.sid)
        threading.Thread(target=self._grace, daemon=True,
                         name="acp-cancel").start()

    def _grace(self) -> None:
        if not self.ended.wait(_secs(self.cfg, "cancel_grace_s", 10)):
            self.proc.shutdown(kill=True)       # then its sessions end

    # updates (reader thread) ----------------------------------------------

    def _append(self, text) -> None:
        text = _one_line(text)
        if not text:
            return
        self.last_line = text
        try:
            with self.log.open("a") as f:
                f.write(text + "\n")
        except OSError:
            pass

    def _line(self, text) -> None:
        self._append(text)
        now = self.mgr.clock()
        if self.last_emit is None or now - self.last_emit >= PROGRESS_GAP_S:
            self.last_emit = now
            self.mgr.emit("task_progress", name=self.id,
                          line=self.last_line,
                          seconds=int(now - self.started))

    def _scan(self, text) -> None:
        *lines, self.buf = (self.buf + text).split("\n")
        for line in lines:
            if line.strip().startswith("PROGRESS:"):
                self._line(line.strip())

    def _flush_buf(self) -> None:
        if self.buf.strip().startswith("PROGRESS:"):
            self._line(self.buf.strip())
        self.buf = ""

    def on_update(self, upd) -> None:
        if self.loading:            # session/load replays history
            return
        kind = upd.get("sessionUpdate")
        if kind == "agent_message_chunk":
            text = (upd.get("content") or {}).get("text")
            if isinstance(text, str):
                self.since_tool.append(text)
                self._scan(text)
        elif kind == "tool_call":
            self.since_tool = []    # the answer is what comes after
            title = _one_line(upd.get("title") or upd.get("kind") or "tool")
            what = upd.get("kind") or "tool"
            self.titles[upd.get("toolCallId")] = (what, title)
            self._line(f"{what}: {title} [{upd.get('status') or 'pending'}]")
        elif kind == "tool_call_update":
            status = upd.get("status")
            if status in ("completed", "failed"):
                what, title = self.titles.get(upd.get("toolCallId"),
                                              ("tool", "call"))
                self._line(f"{what}: {title} [{status}]")
        elif kind == "plan":
            steps = [e.get("content") for e in upd.get("entries") or []
                     if isinstance(e, dict) and e.get("content")]
            if steps:
                self._line("plan: " + "; ".join(steps))

    # permissions (reader thread: never block) --------------------------------

    def on_permission(self, tool_call, options, reply) -> None:
        def pick(kind):
            return next((o.get("optionId") for o in options
                         if isinstance(o, dict) and o.get("kind") == kind),
                        None)
        allow, reject = pick("allow_once"), pick("reject_once")
        verdict = self.policy.classify(tool_call)
        title = _one_line(tool_call.get("title") or "an action", 80)
        if verdict == "refuse":
            self._append(f"refused: {title}")
            agents.record_refusal(self.id, title, self.tf)
            reply(reject)
        elif verdict == "allow" and allow:
            self._allowed(tool_call)
            reply(allow)
        elif verdict == "allow" or self.mgr.ask is None:
            reply(reject)
        else:
            self._ask(tool_call, title, allow, reject, reply)

    def _allowed(self, tool_call, asked: bool = False) -> None:
        # auto-allowed calls only taint the session when they write; a
        # call the user approved may have written anything (policy-unknown)
        kind = tool_call.get("kind")
        if kind in ("edit", "delete", "move") or (
                asked and kind not in ("read", "search", "think", "fetch")):
            self.policy.note_edit(tool_call)

    def _ask(self, tool_call, title, allow, reject, reply) -> None:
        self.mgr.ask_begin(self.id)

        def on_answer(pick):
            self.mgr.ask_end(self.id)
            if pick == agent_ask.ALLOW and allow:
                self._allowed(tool_call, asked=True)
                reply(allow)
            else:
                reply(reject)
        try:
            self.mgr.ask.submit(
                self.agent or self.id, "permission", title, None,
                self.mgr.ask_clock() + _secs(self.cfg, "ask_timeout_s", 120),
                on_answer)
        except Exception:  # noqa: BLE001 — fail closed
            on_answer(None)

    # end -------------------------------------------------------------------

    def finish(self, status, reason="", announce=True) -> None:
        with self.lock:
            if self.finished:
                return
            self.finished = self.closed = True
            self.queue.clear()
        if reason:
            self._append(reason)
        now = datetime.now(timezone.utc)
        rec = agents._find(self.id, self.tf) or {}
        close = {"id": self.id, "name": self.id, "status": status,
                 "stop_reason": self.stop_reason, "ts": now.isoformat(),
                 "answer": self.answer[:ANSWER_MAX]}
        if reason:
            close["error"] = reason
        delivered = False
        if status == "done":
            info = agents.verify_deliverables(
                rec, finished_ts=now, log_dir=self.ld, final_status="done")
            delivered = info["delivered"]
            close.update(delivered=delivered,
                         deliverables=info["deliverables"],
                         open_actions=info["open_actions"])
        if rec.get("routine_id") and not rec.get("routine_recorded") \
                and status != "interrupted":
            rout = agents._record_routine_for_task(rec, status, delivered)
            if rout is not None:
                close.update(routine_id=rec["routine_id"],
                             routine_recorded=True, routine_outcome=rout,
                             unread=rout["unread"])
        agents._log_line(close, self.tf)
        agent_mcp.revoke(self.token)
        self.proc.sessions.pop(self.sid, None)
        self.ended.set()
        self.mgr.session_done(self, announce and status != "interrupted")


class Manager:
    def __init__(self, cfg, ask=None, bus=None, tasks_file=None,
                 log_dir=None, home=None, runtime_root=None,
                 on_finished=None, wispd_path=None, clock=time.monotonic,
                 ask_clock=time.monotonic):
        self.cfg, self.ask, self.bus = cfg, ask, bus
        self.tf = tasks_file or config.TASKS_FILE
        self.ld = log_dir or config.TASK_LOGS
        self.home, self.runtime_root = home, runtime_root
        self.on_finished = on_finished
        self.wispd = str(wispd_path or pathlib.Path(sys.argv[0]).resolve())
        self.clock, self.ask_clock = clock, ask_clock
        self._lock = threading.RLock()
        self._start_lock = threading.Lock()
        self._procs: dict = {}
        self._runs: dict = {}
        self._asks = collections.Counter()
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> None:
        """Daemon start: anything a previous daemon left running is
        killed and its sessions marked interrupted (R12), then the idle
        sweep runs."""
        try:
            agents.sweep_orphans(self.tf)
        except Exception:  # noqa: BLE001
            pass
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="acp-idle")
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(SWEEP_S):
            try:
                self.sweep()
            except Exception:  # noqa: BLE001
                pass

    def stop(self) -> None:
        """Daemon stop: running sessions end `interrupted` (never
        replayed), then every process and its scope is stopped."""
        self._stop.set()
        with self._lock:
            runs, procs = list(self._runs.values()), list(self._procs.values())
        for run in runs:
            run.finish("interrupted")
        for proc in procs:
            proc.shutdown()
        with self._lock:
            self._procs.clear()
        if self._thread is not None:
            self._thread.join(2)

    # asks --------------------------------------------------------------

    def ask_begin(self, name) -> None:
        with self._lock:
            self._asks[name] += 1

    def ask_end(self, name) -> None:
        with self._lock:
            self._asks[name] -= 1
            if self._asks[name] <= 0:
                del self._asks[name]

    def asking(self, names) -> bool:
        with self._lock:
            return any(self._asks.get(n) for n in names)

    def emit(self, event, **data) -> None:
        try:
            if self.bus is not None:
                self.bus.emit_event(event, **data)
        except Exception:  # noqa: BLE001
            pass

    # processes ----------------------------------------------------------

    def _acquire(self, key, cfg, tf, ld, cwd, ephemeral) -> HelperProcess:
        with self._start_lock:
            with self._lock:
                proc = self._procs.get(key)
                if proc is not None and proc.usable():
                    proc.active += 1
                    return proc
                self._procs.pop(key, None)
            if proc is not None:
                proc.shutdown(kill=True)    # dead or closing: fresh start
            proc = HelperProcess(self, key, tf, ld, ephemeral)
            proc.start(cfg, cwd)
            with self._lock:
                proc.active = 1
                self._procs[key] = proc
            return proc

    def _retire(self, proc) -> None:
        with self._lock:
            if self._procs.get(proc.id) is proc:
                del self._procs[proc.id]
        proc.shutdown()

    def sweep(self) -> None:
        """Idle reaping: a helper process with no session idles out after
        `[agents] acp_idle_s`; a dead one is closed."""
        idle = _secs(self.cfg, "acp_idle_s", 900)
        now = self.clock()
        with self._lock:
            gone = [p for p in self._procs.values()
                    if p.active == 0 and (not p.usable()
                                          or now - p.idle_since >= idle)]
            for p in gone:
                p.closing = True
        for p in gone:
            self._retire(p)

    def session_done(self, run, announce) -> None:
        proc = run.proc
        with self._lock:
            self._runs.pop(run.id, None)
            proc.active = max(0, proc.active - 1)
            proc.idle_since = self.clock()
            retire = proc.active == 0 and (proc.ephemeral
                                           or not proc.usable())
            if retire:
                proc.closing = True
        try:
            if announce:
                self._announce(run.id)
        finally:
            if retire:
                self._retire(proc)

    def _announce(self, task_id) -> None:
        rec = agents._find(task_id, self.tf)
        if rec is None:
            return
        cur = agents.tasks(self.tf, self.ld, recs=[rec])
        entry = agents.finished_entry(rec["name"], cur[rec["name"]], rec,
                                      self.ld)
        try:
            if self.bus is not None:
                self.bus.publish(None, tasks=agents.tasks(self.tf, self.ld))
        except Exception:  # noqa: BLE001
            pass
        agents.emit_finished(self.bus, entry, self.on_finished)

    # tasks ----------------------------------------------------------------

    def _launch(self, run) -> None:
        with self._lock:
            self._runs[run.id] = run
        threading.Thread(target=run.run, daemon=True,
                         name=f"acp-{run.id}").start()

    def start_task(self, name, task, prompt, cwd, out_dir, delivers,
                   spawned_by, depth, routine_id, agent, cfg, tf, ld) -> str:
        slug = agents._slug(agent) if agent else ""
        try:
            proc = self._acquire(f"acp-{slug or name}", cfg, tf, ld, cwd,
                                 ephemeral=not agent)
        except _Skip as e:
            return f"SKIP ({e})"
        extra = {"out_dir": str(out_dir), "delivers": list(delivers or []),
                 "spawned_by": spawned_by, "depth": int(depth)}
        if routine_id:
            extra["routine_id"] = routine_id
        if slug:
            extra["agent"] = slug
        agents.record_session(name, task, proc.id, cwd=str(cwd),
                              tasks_file=tf, **extra)
        self._launch(SessionRun(self, proc, name, task, prompt, cwd,
                                out_dir, slug, tf, ld, cfg))
        return f"SPAWNED {name} (acp {proc.id})"

    def tell(self, slug, text) -> bool:
        """Queue a follow-up into the helper's live session."""
        with self._lock:
            runs = [r for r in self._runs.values() if r.agent == slug]
        return any(r.enqueue(text) for r in runs)

    def cancel(self, task_id):
        with self._lock:
            run = self._runs.get(task_id)
        if run is None:
            return None
        run.request_cancel()
        return f"CANCELLED {task_id}"

    def expire(self, task_id) -> bool:
        """A session past `[agent] task_timeout_s`: cancel it, record
        `timed_out` (never a signal to the process)."""
        with self._lock:
            run = self._runs.get(task_id)
        if run is None or run.cancelling:
            return run is not None
        run.timed_out = True
        run.request_cancel()
        return True

    def resume(self, rec) -> str:
        """"continue" on an interrupted session: a fresh process and
        `session/load` with the stored id."""
        name, sid = rec["name"], rec.get("session_id")
        shown = rec.get("agent") or name
        cant = (f"ACTED (0 steps): {shown} can't be picked back up, so it "
                "stays interrupted.")
        if not sid:
            return cant
        slug = rec.get("agent") or ""
        cwd = rec.get("cwd") or rec.get("out_dir") or str(config.DATA_DIR)
        try:
            proc = self._acquire(f"acp-{slug or name}", self.cfg, self.tf,
                                 self.ld, cwd, ephemeral=not slug)
        except _Skip as e:
            return f"SKIP ({e})"
        if not proc.conn.agent_capabilities.get("loadSession"):
            self.session_done(_Stub(proc, name), False)
            return cant
        now = datetime.now(timezone.utc).isoformat()
        agents._log_line({"id": name, "name": name, "status": "running",
                          "resumed": now, "error": None}, self.tf)
        self._launch(SessionRun(
            self, proc, name, rec.get("task", ""), RESUME_PROMPT, cwd,
            rec.get("out_dir") or cwd, slug, self.tf, self.ld, self.cfg,
            resume_sid=sid))
        return f"ACTED (0 steps): {shown} is picking that back up."


class _Stub:
    """Releases a process hold taken for a run that never started."""

    def __init__(self, proc, name):
        self.proc, self.id = proc, name
