"""Learning and telemetry: learn, skills, trace."""
import io

from .registry import GROUPS, CliError, command

GROUPS["learn"] = "Failure log"
GROUPS["skills"] = "Installed skills"
GROUPS["trace"] = "Turn trace and daily digest"
GROUPS["dev"] = "Developer views of recent turns"

_TEXT = {"text": "str"}
LATENCY_WINDOW_H = 168   # `wispd eval` shows the last week of turns


def _text(ctx, s):
    return ctx.emit({"text": s}, s)


@command("learn fails", "Show logged failures",
         ["wispd learn fails"], _TEXT)
def learn_fails(ctx, a):
    from .. import learn
    return _text(ctx, learn.fails())


def _eval_args(p):
    p.add_argument("--misses", action="store_true",
                   help="group the turns that were not right first time")
    p.add_argument("--unlabelled", action="store_true",
                   help="list recent turns that still need a label")
    p.add_argument("--limit", type=int, default=10, metavar="N",
                   help="groups or turns to list (default 10)")


@command("eval", "End-to-end eval: first-time-correct rate per turn kind",
         ["wispd eval", "wispd eval --json", "wispd eval --misses",
          "wispd eval --unlabelled --limit 20"],
         {"kinds": "dict", "total": "dict", "gate": "dict",
          "langs": "dict", "latency": "list"},
         args=_eval_args)
def eval_cmd(ctx, a):
    from .. import config, learn
    if a.misses:
        rows = learn.eval_misses(top=a.limit)
        return ctx.emit({"misses": rows}, learn.misses_text(rows))
    if a.unlabelled:
        rows = learn.eval_unlabelled(limit=a.limit)
        return ctx.emit({"unlabelled": rows}, learn.unlabelled_text(rows))
    from .. import telemetry
    rep = learn.eval_report(config.load_config())
    lat = telemetry.latency_report(LATENCY_WINDOW_H)
    text = learn.eval_text(rep)
    if lat["turns"]:
        text += "\n\n" + telemetry.latency_text(LATENCY_WINDOW_H)
    return ctx.emit({**rep, "latency": lat["rows"]}, text)


@command("skills list", "List installed skills",
         ["wispd skills list"], {"skills": "list"})
def skills_list(ctx, a):
    from .. import skills
    idx = skills.index()
    return ctx.emit(
        {"skills": [{"name": s["name"], "description": s["description"]}
                    for s in idx]},
        "\n".join(f"{s['name']}: {s['description']}" for s in idx) or None)


def _import_args(p):
    p.add_argument("dir", help="directory of skills to import")
    p.add_argument("--list", action="store_true",
                   help="preview only; install nothing")


@command("skills import", "Import skills from a directory",
         ["wispd skills import --list ~/skills", "wispd skills import "
          "~/skills"], _TEXT, args=_import_args)
def skills_import(ctx, a):
    from .. import skills
    return _text(ctx, skills.import_dir(a.dir, preview=a.list))


def _show_args(p):
    p.add_argument("--tail", type=int, default=50, metavar="N",
                   help="events to show (default 50)")
    p.add_argument("--turn", default="", metavar="ID",
                   help="only this turn")
    p.add_argument("--kind", default="", metavar="KIND",
                   help="only this event kind")
    p.add_argument("--latency", action="store_true",
                   help="p50/p90 per budget path instead of events")
    p.add_argument("--since", default="24h", metavar="AGE",
                   help="window for --latency (24h, 90m, 2d)")


@command("trace show", "Print the turn trace, or a latency summary",
         ["wispd trace show --tail 20", "wispd trace show --latency "
          "--since 6h"], _TEXT, args=_show_args)
def trace_show(ctx, a):
    from .. import trace
    argv = ["--tail", str(a.tail)]
    if a.turn:
        argv += ["--turn", a.turn]
    if a.kind:
        argv += ["--kind", a.kind]
    if a.latency:
        argv += ["--latency", "--since", a.since]
    return _capture(ctx, lambda: trace.main(argv))


def _hours_args(p):
    p.add_argument("hours", nargs="?", type=int, default=24,
                   help="window in hours (default 24)")


@command("trace digest", "Local digest over decisions and trace",
         ["wispd trace digest 48"], _TEXT, args=_hours_args)
def trace_digest(ctx, a):
    from .. import telemetry
    return _text(ctx, telemetry.text(a.hours))


def _capture(ctx, fn):
    """Run a function that prints; wrap its output under --json."""
    if ctx.json or ctx.flags.quiet:
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = fn()
        if rc:
            return rc
        return ctx.emit({"text": buf.getvalue().rstrip("\n")})
    return fn()


def _dev_args(p):
    p.add_argument("-n", "--limit", type=int, default=None, metavar="N",
                   dest="n", help="turns to return (default 20, max 50)")


def _dev_text(d):
    rs = d.get("rated_share")
    g = d.get("gate") or {}
    lines = [f"gate: {g.get('correct', 0)}/{g.get('labelled', 0)} right "
             f"first time ({g.get('status', 'unset')}), "
             f"rated {'-' if rs is None else format(rs, '.0%')} of "
             f"{d.get('finished', 0)} finished"]
    for t in d.get("turns", []):
        ms = t.get("total_ms")
        lines.append(f"  {t['id'] or '-':<10}{t['label']:<10}"
                     f"{'-' if ms is None else ms:>6} ms  "
                     f"{t['route'] or '-':<8}{t['transcript'][:50]}")
    return "\n".join(lines)


@command("dev turns", "Last turns with stages, labels, gate and misses",
         ["wispd dev turns", "wispd dev turns --json -n 5"],
         {"turns": "list", "gate": "dict", "rated": "int",
          "finished": "int", "rated_share": "float", "misses": "list",
          "truncated": "bool"}, args=_dev_args)
def dev_turns(ctx, a):
    msg = {"cmd": "devlog", **({"n": a.n} if a.n is not None else {})}
    try:
        r = ctx.send(msg)
    except CliError as e:
        if e.code != "E_DAEMON_DOWN":
            raise
        # read-only: answer from the files when no daemon is running
        from .. import config, devlog
        r = {"ok": True, **devlog.build(config.load_config(), n=a.n)}
    ctx.expect_ok(r)
    data = {k: v for k, v in r.items() if k != "ok"}
    return ctx.emit(data, _dev_text(data))


_DEV_SESSION = {"on": "bool", "runs_done": "int", "runs_left": "int",
                "max_runs": "int", "started_at": "str"}


def _dev_session_text(s):
    if not s.get("on"):
        return "dev mode: off"
    return (f"dev mode: on, {s.get('runs_done', 0)} of "
            f"{s.get('max_runs', 5)} runs done "
            f"({s.get('runs_left', 0)} left), started {s.get('started_at')}")


def _dev_switch(ctx, op):
    r = ctx.expect_ok(ctx.send({"cmd": "dev", "op": op}))
    s = r.get("dev") or {}
    return ctx.emit(s, _dev_session_text(s))


@command("dev on", "Turn dev mode on (tracing on; off after five runs)",
         ["wispd dev on"], _DEV_SESSION)
def dev_on(ctx, a):
    return _dev_switch(ctx, "on")


@command("dev off", "Turn dev mode off; your own settings return",
         ["wispd dev off"], _DEV_SESSION)
def dev_off(ctx, a):
    return _dev_switch(ctx, "off")


@command("dev status", "Show whether dev mode is on and how many runs are left",
         ["wispd dev status", "wispd dev status --json"], _DEV_SESSION)
def dev_status(ctx, a):
    try:
        return _dev_switch(ctx, "status")
    except CliError as e:
        if e.code != "E_DAEMON_DOWN":
            raise
        from .. import devsession
        s = devsession.status()      # read-only: the session file answers
        return ctx.emit(s, _dev_session_text(s))


def _dev_run_args(p):
    p.add_argument("file", metavar="FILE",
                   help="task list: one task per line, # for comments")


@command("dev run", "Run a task list on the live desktop (dev mode must be on)",
         ["wispd dev run docs/dev-tasks/starter.txt"],
         {"run_id": "str", "tasks": "int"}, args=_dev_run_args)
def dev_run(ctx, a):
    import os
    r = ctx.expect_ok(ctx.send({"cmd": "dev_run",
                                "path": os.path.abspath(a.file)}))
    return ctx.emit({"run_id": r.get("run_id"), "tasks": r.get("tasks")},
                    f"run {r.get('run_id')} started: {r.get('tasks')} tasks")


@command("dev stop", "Stop the running task list after the current task",
         ["wispd dev stop"], {"stopping": "bool"})
def dev_stop(ctx, a):
    r = ctx.expect_ok(ctx.send({"cmd": "dev_stop"}))
    return ctx.emit({"stopping": bool(r.get("stopping"))},
                    "stopping after the current task")
