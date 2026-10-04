"""Agents and memory: task, memory, suggest, label, context."""
import base64
import binascii

from .. import config
from .registry import CliError, GROUPS, command, from_wisp_code
from . import strings

GROUPS["task"] = "Background agents: list, status, cancel, run"
GROUPS["memory"] = "Edit the MEMORY and USER notes"
GROUPS["suggest"] = "Suggestions mined from your activity"
GROUPS["label"] = "Label the last turn to measure routing accuracy"


@command("task list", "List background agents with their last log line",
         ["wispd task list"], {"tasks": "list"})
def task_list(ctx, a):
    from .. import agents
    ts = agents.tasks()
    rows = [{"name": n, "status": t["status"], "task": t.get("task", ""),
             "ts": t.get("ts", ""), "tail": t.get("tail") or ""}
            for n, t in sorted(ts.items(),
                               key=lambda kv: kv[1].get("ts", ""))]
    if not rows:
        return ctx.emit({"tasks": []}, strings.NO_TASKS)
    lines = []
    for r in rows:
        lines.append(f"{r['status']:<10} {r['name']:<24} {r['task'][:50]}"
                     + (f"\n{'':<36}↳ {r['tail'][:90]}"
                        if r["tail"] else ""))
    return ctx.emit({"tasks": rows}, "\n".join(lines))


def _name_arg(p):
    p.add_argument("name", nargs="?", default="", help="task name")


def _result(ctx, msg):
    r = ctx.expect_ok(ctx.send(msg))
    res = r.get("result") or ""
    return ctx.emit({"result": res}, res)


@command("task status", "Show one agent's status and last log line",
         ["wispd task status fix-bug"], {"result": "str"}, args=_name_arg)
def task_status(ctx, a):
    return _result(ctx, {"cmd": "task_status", "name": a.name})


@command("task cancel", "Cancel a running agent",
         ["wispd task cancel fix-bug"], {"result": "str"}, args=_name_arg)
def task_cancel(ctx, a):
    return _result(ctx, {"cmd": "task_cancel", "name": a.name})


def _text_arg(dest, help_):
    def add(p):
        p.add_argument(dest, nargs="*", help=help_)
    return add


@command("task run", "Spawn a background agent for a task",
         ["wispd task run fix the flaky login test"], {"result": "str"},
         args=_text_arg("task", "what the agent should do"))
def task_run(ctx, a):
    return _result(ctx, {"cmd": "agent", "task": " ".join(a.task)})


@command("memory edit", "Edit MEMORY or USER notes: target|op|old|new",
         ["wispd memory edit 'memory|add||prefers dark mode'"],
         {"result": "str"},
         args=_text_arg("arg", "target|op|old|new"))
def memory_edit(ctx, a):
    return _result(ctx, {"cmd": "memory", "arg": " ".join(a.arg)})


def _mem_write_args(p):
    p.add_argument("target", help="memory or user")
    p.add_argument("body_b64", metavar="BASE64",
                   help="whole document, base64 encoded")


@command("memory write", "Replace a whole notes document (base64 body)",
         ["wispd memory write user \"$(base64 -w0 USER.md)\""],
         {"result": "str"}, args=_mem_write_args)
def memory_write(ctx, a):
    try:
        body = base64.b64decode(a.body_b64).decode()
    except (ValueError, binascii.Error) as e:
        raise CliError("E_USAGE", f"The body is not valid base64 ({e}).",
                       "wispd memory write --help")
    return _result(ctx, {"cmd": "memory", "target": a.target, "body": body})


@command("suggest list", "Show pending suggestions",
         ["wispd suggest list"], {"suggestions": "list"})
def suggest_list(ctx, a):
    r = ctx.expect_ok(ctx.send({"cmd": "suggestions"}))
    sugg = r.get("suggestions", [])
    text = "\n".join(f"[{s.get('status', '?')}] {s.get('title', '')} "
                     f"— {s.get('evidence', '')}" for s in sugg)
    return ctx.emit({"suggestions": sugg}, text if sugg else None)


@command("label report", "Per-route accuracy report from your labels",
         ["wispd label report"], {"text": "str"})
def label_report(ctx, a):
    from .. import learn
    text = learn.soak_stats()
    return ctx.emit({"text": text}, text)


def _label_args(p):
    p.add_argument("label", help="correct or incorrect: was the last route "
                   "right?")
    p.add_argument("note", nargs="*", help="optional note")


@command("label set", "Label the last turn correct or incorrect",
         ["wispd label set correct", "wispd label set incorrect it opened "
          "the wrong app"], {"result": "str"}, args=_label_args)
def label_set(ctx, a):
    note = " ".join(a.note)
    try:
        r = ctx.send({"cmd": "label", "label": a.label, "note": note})
    except CliError as e:
        if e.code != "E_DAEMON_DOWN":
            raise
        from .. import learn
        out = learn.label_last(a.label, note)
        if out.startswith(("SKIP", "ERROR", "nothing")):
            if ctx.json:
                raise CliError("E_FAILED", "Nothing was labelled.",
                               "wispd status", data={"result": out})
            print(out)
            raise CliError("E_FAILED", "Nothing was labelled.",
                           "wispd status")
        return ctx.emit({"result": out}, out)
    ctx.expect_ok(r)
    res = r.get("result") or ""
    return ctx.emit({"result": res}, res)


@command("context", "Print what the daemon sees right now",
         ["wispd context"], {"result": "str"})
def context(ctx, a):
    return _result(ctx, {"cmd": "context"})
