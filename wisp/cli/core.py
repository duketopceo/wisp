"""Daemon control: daemon, status, stop, interrupt, trigger, watch, choice,
tui, completion."""
import contextlib
import io
import json
import sys

from . import registry
from .registry import CliError, GROUPS, command

GROUPS["daemon"] = "Run and install the wisp daemon"


def _host_call(ctx, fn):
    """Run a host function that prints; keep stdout clean under --json."""
    if ctx.json or ctx.flags.quiet:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = fn()
        return rc, buf.getvalue()
    return fn(), None


@command("daemon run", "Run the daemon in the foreground (systemd unit)",
         ["wispd daemon run", "systemctl --user start wispd"], stream=True)
def daemon_run(ctx, a):
    return ctx.host.run_daemon(ctx.cfg)


def _install_args(p):
    p.add_argument("--cua", action="store_true",
                   help="also install the pinned cua-driver "
                        "(scripts/cua/install.sh)")
    p.add_argument("--units", action="store_true",
                   help="only install the systemd unit templates "
                        "(scripts/units), backing up changed ones")
    p.add_argument("--dry-run", action="store_true",
                   help="with --cua or --units: print the plan, "
                        "change nothing")


@command("daemon install",
         "Install runtime files, the systemd unit and the hotkey bind",
         ["wispd daemon install", "wispd install --units --dry-run"],
         {"installed": "bool", "cua": "any", "units": "any"},
         args=_install_args)
def daemon_install(ctx, a):
    if a.dry_run and not (a.cua or a.units):
        raise CliError("E_USAGE", "--dry-run needs --cua or --units.",
                       "wispd install --units --dry-run")
    if a.cua:
        return _install_cua(ctx, a)
    if a.units:
        return _install_units(ctx, a)

    def go():
        ctx.host.install_files()
        ctx.host.install_bind(ctx.cfg)
        return 0
    rc, text = _host_call(ctx, go)
    return ctx.emit({"installed": rc == 0, "cua": None})


def _install_units(ctx, a):
    """Only the systemd units: back up changed ones, daemon-reload,
    never enable/start/restart. --dry-run writes nothing."""
    from .. import config as _cfgmod, svc
    acts = svc.install_units(_cfgmod.HOME, dry_run=a.dry_run)
    text = svc.describe(acts, a.dry_run)
    if not a.dry_run:
        text += ("\nunits installed, not restarted; apply with "
                 "systemctl --user restart <unit>")
    return ctx.emit({"installed": not a.dry_run, "cua": None,
                     "units": acts}, text)


def _install_cua(ctx, a):
    """Run scripts/cua/install.sh. The wisp files are not reinstalled:
    `--cua` is the driver only (use plain `wispd install` for the rest)."""
    import pathlib
    import subprocess
    script = pathlib.Path(__file__).resolve().parents[2] / "scripts" \
        / "cua" / "install.sh"
    if not script.exists():
        raise CliError("E_FAILED", "scripts/cua/install.sh is not next to "
                       "this wispd.", "run from the source checkout")
    cmd = ["bash", str(script)] + (["--dry-run"] if a.dry_run else [])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise CliError("E_FAILED", f"The cua installer did not run ({e}).",
                       "wispd install --cua --dry-run")
    out = (r.stdout + r.stderr).rstrip()
    data = {"installed": r.returncode == 0 and not a.dry_run,
            "cua": {"exit": r.returncode, "dry_run": a.dry_run,
                    "output": out}}
    if r.returncode:
        if not ctx.json and not ctx.flags.quiet:
            print(out)
        raise CliError("E_FAILED", f"The cua installer exited "
                       f"{r.returncode}.", "wispd install --cua --dry-run",
                       data=data)
    text = out
    if not a.dry_run:
        from .. import probes_cua
        st = probes_cua.CuaProbe(ctx.cfg).check()
        data["cua"]["state"] = st["state"]
        text += f"\ncua state: {st['state']}"
    return ctx.emit(data, text)


@command("daemon harness", "Rebuild the agent harness file",
         ["wispd daemon harness"], {"exit": "int"})
def daemon_harness(ctx, a):
    rc, _ = _host_call(ctx, ctx.host.rebuild_harness)
    if rc:
        raise CliError("E_FAILED", f"The harness builder exited {rc}.",
                       "wispd doctor", data={"exit": rc})
    return ctx.emit({"exit": rc})


@command("status", "Show the daemon state (JSON)",
         ["wispd status", "wispd status --json"], {"state": "dict"})
def status(ctx, a):
    reply = ctx.expect_ok(ctx.send({"cmd": "status"}))
    return ctx.emit({"state": reply.get("state", {})},
                    json.dumps(reply, indent=2))


@command("stop", "Ask the daemon to shut down",
         ["wispd stop"], {"sent": "str"})
def stop(ctx, a):
    ctx.expect_ok(ctx.send({"cmd": "stop"}))
    return ctx.emit({"sent": "stop"})


@command("interrupt", "Cancel the turn in flight; the daemon keeps running",
         ["wispd interrupt"], {"sent": "str"})
def interrupt(ctx, a):
    ctx.expect_ok(ctx.send({"cmd": "interrupt"}))
    return ctx.emit({"sent": "interrupt"})


def _trigger_args(p):
    p.add_argument("phase", nargs="?", default="",
                   choices=["", "start", "stop"],
                   help="start or stop for hold-to-talk; empty toggles")


@command("trigger", "Push-to-talk: tell the daemon to start or stop listening",
         ["wispd trigger start", "wispd trigger stop"], {"phase": "str"},
         args=_trigger_args)
def trigger(ctx, a):
    rc = ctx.host.cmd_trigger(ctx.cfg, a.phase)
    return rc if rc else ctx.emit({"phase": a.phase})


def _watch_args(p):
    p.add_argument("topic", nargs="*",
                   help="state topics to follow (default: all)")


@command("watch", "Follow the daemon push stream as NDJSON",
         ["wispd watch", "wispd watch state tasks"], stream=True,
         args=_watch_args)
def watch(ctx, a):
    from .. import ipc
    try:
        for ev in ipc.watch(a.topic or None):
            print(json.dumps(ev), flush=True)
    except KeyboardInterrupt:
        pass
    return 0


def _choice_args(p):
    p.add_argument("pick", nargs="?", default="",
                   help="the option to pick (omit when using --index)")
    p.add_argument("--prompt-id", metavar="ID",
                   help="answer this prompt only")
    p.add_argument("--index", type=int, metavar="N",
                   help="1-based option number")


@command("choice", "Answer a pending prompt from the keyboard or a script",
         ["wispd choice app:kitty",
          "wispd choice --prompt-id p1 --index 2"],
         {"pick": "str"}, args=_choice_args)
def choice(ctx, a):
    msg = {"cmd": "choice", "pick": a.pick}
    if a.prompt_id:
        msg["prompt_id"] = a.prompt_id
    if a.index is not None:
        msg["index"] = a.index
    ctx.expect_ok(ctx.send(msg))
    return ctx.emit({"pick": a.pick})


@command("tui", "Open the terminal UI",
         ["wispd tui"], stream=True)
def tui(ctx, a):
    from .. import tui as _tui
    return _tui.main()


def _completion_args(p):
    p.add_argument("shell", choices=["bash", "zsh", "fish"])


@command("completion", "Print a shell completion script",
         ["wispd completion bash > ~/.local/share/bash-completion/"
          "completions/wispd",
          "wispd completion fish | source"],
         {"shell": "str", "script": "str"}, args=_completion_args)
def completion(ctx, a):
    from . import completion as comp
    script = comp.generate(a.shell)
    return ctx.emit({"shell": a.shell, "script": script},
                    script.rstrip("\n"))
