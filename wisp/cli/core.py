"""Daemon control: daemon, status, stop, interrupt, trigger, watch, choice,
tui, completion."""
import contextlib
import io
import json
import pathlib
import sys
import tempfile

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
    p.add_argument("--agents", action="store_true",
                   help="only install the pinned ori and OpenCode 2.x "
                        "background-agent runtime (user scope, checksummed, "
                        "no sudo)")
    p.add_argument("--units", action="store_true",
                   help="only install the systemd unit templates "
                        "(scripts/units), backing up changed ones")
    p.add_argument("--echo-cancel", action="store_true",
                   help="only write the PipeWire echo-cancel drop-in the "
                        "optional wake word needs over speakers (asks "
                        "first; --yes answers it)")
    p.add_argument("--dry-run", action="store_true",
                   help="print the plan, change nothing (also with --cua, "
                        "--agents, --units or --echo-cancel)")
    p.add_argument("--from-plugin", action="store_true",
                   help="the Omarchy plugin was added from the marketplace: "
                        "install the daemon only, leave the plugin "
                        "directory to `omarchy plugin update`, print every "
                        "file and the bind line first and ask")
    p.add_argument("--yes", "-y", action="store_true",
                   help="answer the question yes (--from-plugin, --echo-cancel) "
                        "(needed without a terminal)")
    p.add_argument("--ref", metavar="GIT_REF",
                   help="install this git ref (branch, tag or commit) "
                        "of the source repo instead of the working tree")
    p.add_argument("--repo", metavar="PATH",
                   help="source repo for --ref (default: the repo of "
                        "the last install)")


@command("daemon install",
         "Install runtime files, the systemd unit and the hotkey bind",
         ["wispd daemon install", "wispd install --dry-run",
          "wispd install --units --dry-run",
          "wispd install --ref origin/master --dry-run"],
         {"installed": "bool", "cua": "any", "units": "any",
          "agents": "any"},
         args=_install_args)
def daemon_install(ctx, a):
    if a.cua:
        return _install_cua(ctx, a)
    if a.agents:
        return _install_agents(ctx, a)
    if a.units:
        return _install_units(ctx, a)
    if a.echo_cancel:
        return _install_echo_cancel(ctx, a)

    if a.repo and not a.ref:
        raise CliError("E_USAGE", "--repo only applies with --ref.",
                       "wispd install --ref <git-ref> --repo <path>")
    if a.ref:
        with tempfile.TemporaryDirectory() as tmp:
            repo, commit = _export_ref(a, tmp)
            return _install(ctx, a, pathlib.Path(tmp), repo, commit)
    return _install(ctx, a, None, None, None)


def _export_ref(a, tmp):
    """Unpack --ref of the source repo into `tmp`; (repo, commit)."""
    from .. import deploy
    repo = a.repo or (deploy.read() or {}).get("repo")
    if repo:
        repo = str(pathlib.Path(repo).expanduser().resolve())
    if not repo:
        raise CliError("E_USAGE", "No source repo is recorded for --ref.",
                       "wispd install --ref <git-ref> --repo <path>")
    try:
        return repo, deploy.export_ref(repo, a.ref, tmp)
    except ValueError as e:
        raise CliError("E_FAILED", str(e),
                       "wispd install --ref <git-ref> --repo <path>")


def _install(ctx, a, src, repo, commit):
    deploy = ({"repo": repo, "ref": a.ref, "commit": commit}
              if src else None)
    plugin = not a.from_plugin

    def preflight_rows():
        from .. import config as _cfgmod, preflight
        return preflight.run(_cfgmod.HOME, _cfgmod.HOME / ".local" / "opt"
                             / "wisp")

    def plan():
        from .. import preflight
        print("preflight:")
        print(preflight.format_rows(preflight_rows()))
        ctx.host.install_files(dry_run=True, cfg=ctx.cfg, src=src,
                               deploy=deploy, plugin=plugin)
        ctx.host.install_bind(ctx.cfg, dry_run=True)

    def go():
        if a.dry_run:
            plan()
            return 0
        from .. import preflight
        rows = preflight_rows()
        if preflight.blockers(rows):
            raise CliError("E_FAILED", preflight.refusal(rows),
                           "wispd doctor")
        ctx.host.install_files(dry_run=False, cfg=ctx.cfg, src=src,
                               deploy=deploy, plugin=plugin)
        ctx.host.install_bind(ctx.cfg)
        return 0

    if a.from_plugin and not a.dry_run:
        # a marketplace install never edits the user's config unasked
        _host_call(ctx, lambda: (plan(), 0)[1])
        if not (a.yes or _tty_yes("Install this? [y/N] ")):
            return ctx.emit({"installed": False, "cua": None},
                            "not installed; nothing was changed")
    rc, text = _host_call(ctx, go)
    return ctx.emit({"installed": rc == 0 and not a.dry_run, "cua": None})


def _tty_yes(prompt: str) -> bool:
    import sys
    if not (sys.stdin and sys.stdin.isatty()):
        raise CliError("E_USAGE", "Installing from the plugin needs a "
                       "terminal to ask you, or --yes.",
                       "wispd install --from-plugin --dry-run")
    sys.stderr.write(prompt)
    sys.stderr.flush()
    return sys.stdin.readline().strip().lower() in ("y", "yes")


def _install_echo_cancel(ctx, a):
    """The PipeWire drop-in for the wake word: plan first, write only on a
    yes, never restart PipeWire."""
    from .. import config as _cfgmod, echo_cancel
    text = echo_cancel.plan(_cfgmod.HOME)
    if a.dry_run:
        return ctx.emit({"installed": False, "cua": None}, text)
    if not (a.yes or _tty_yes(text + "\nWrite it? [y/N] ")):
        return ctx.emit({"installed": False, "cua": None},
                        "not written; nothing was changed")
    f = echo_cancel.write(_cfgmod.HOME)
    return ctx.emit({"installed": True, "cua": None},
                    f"wrote {f}\nrestart PipeWire to apply it: systemctl "
                    "--user restart pipewire pipewire-pulse wireplumber")


def _install_units(ctx, a):
    """Only the systemd units: back up changed ones, daemon-reload,
    never enable/start/restart. --dry-run writes nothing."""
    from .. import config as _cfgmod, svc
    acts = svc.install_units(_cfgmod.HOME, dry_run=a.dry_run,
                             local=_cfgmod.local_enabled(ctx.cfg))
    text = svc.describe(acts, a.dry_run)
    if not a.dry_run:
        text += ("\nunits installed, not restarted; apply with "
                 "systemctl --user restart <unit>")
    return ctx.emit({"installed": not a.dry_run, "cua": None,
                     "units": acts}, text)


def _install_agents(ctx, a):
    """The pinned ori and OpenCode (agent_install, KTD8). Signing ori in
    is the onboarding agents step's job, not this flag's."""
    from .. import agent_install, agent_pins
    tools = ("ori", "opencode")
    if a.dry_run:
        arch = agent_pins.machine_arch()
        plan = {t: (agent_pins.pin(t, arch) or {}) for t in tools}
        lines = [f"{t} {p['version']} from {p['url']}" if p
                 else f"{t}: no build for {arch}" for t, p in plan.items()]
        return ctx.emit({"installed": False, "agents": {
            t: {"version": p.get("version"), "url": p.get("url")}
            for t, p in plan.items()}},
            "would install (sha256-verified, user scope):\n"
            + "\n".join(lines))
    done = {}
    for t in tools:
        r = agent_install.install(t)
        done[t] = {"status": r.status, "reason": r.reason}
        if r.status == "failed":
            raise CliError("E_FAILED", f"Could not install {t}: "
                           f"{r.reason}", "wispd install --agents --dry-run",
                           data={"installed": False, "agents": done})
    return ctx.emit({"installed": True, "agents": done},
                    "\n".join(f"{t}: {v['status']}"
                              for t, v in done.items())
                    + "\nsign ori in with: wispd onboard --step agents")


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


def _update_args(p):
    p.add_argument("--dry-run", action="store_true",
                   help="print version, digest and the files that would "
                        "change; write nothing")
    p.add_argument("--force", action="store_true",
                   help="install a release that is older than, the same "
                        "as, or cannot be compared with what is installed")
    p.add_argument("--sha256", metavar="HEX",
                   help="expected SHA-256 of the download, for a release "
                        "that publishes none")
    p.add_argument("--restart", action="store_true",
                   help="after a verified install, offer to restart wispd "
                        "and check that it answers (with --rollback: after "
                        "restoring)")
    p.add_argument("--rollback", action="store_true",
                   help="restore the files saved before the last update "
                        "(also the way back from an unfinished update)")


@command("daemon update",
         "Fetch the latest release, verify it, and install on your yes",
         ["wispd update --dry-run", "wispd update",
          "wispd update --restart", "wispd update --rollback",
          "wispd update --force"],
         {"version": "str", "installed_version": "str", "sha256": "str",
          "changes": "dict", "dry_run": "bool", "applied": "bool",
          "ordering": "str", "forced": "bool"},
         args=_update_args)
def daemon_update(ctx, a):
    from .. import update
    say = (lambda t: None) if ctx.json or ctx.flags.quiet \
        else (lambda t: print(t))
    try:
        if a.rollback:
            res = update.rollback(confirm=update.tty_confirm,
                                  emit_text=say, restart=a.restart)
            return ctx.emit(res)
        res = update.run_update(dry_run=a.dry_run, sha256=a.sha256,
                                force=a.force, restart=a.restart,
                                confirm=update.tty_confirm, emit_text=say)
    except update.UpdateError as e:
        raise CliError("E_FAILED", str(e), "wispd update --dry-run")
    except OSError as e:
        raise CliError("E_FAILED", f"The release could not be fetched "
                       f"({e}).", "wispd update --dry-run")
    return ctx.emit(res)


@command("daemon harness", "Rebuild the agent harness file",
         ["wispd daemon harness"], {"exit": "int"})
def daemon_harness(ctx, a):
    rc, _ = _host_call(ctx, ctx.host.rebuild_harness)
    if rc:
        raise CliError("E_FAILED", f"The harness builder exited {rc}.",
                       "wispd doctor", data={"exit": rc})
    return ctx.emit({"exit": rc})


@command("status", "Show the daemon state (JSON)",
         ["wispd status", "wispd status --json"],
         {"state": "dict", "deploy": "dict"})
def status(ctx, a):
    from .. import deploy
    reply = ctx.expect_ok(ctx.send({"cmd": "status"}))
    dep = deploy.summary()
    text = json.dumps(reply, indent=2)
    if dep["commit"] != "unknown":
        text += f"\ndeployed: {dep['commit'][:12]} ({dep.get('time')})"
    return ctx.emit({"state": reply.get("state", {}), "deploy": dep}, text)


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
         {"pick": "str", "result": "str"}, args=_choice_args)
def choice(ctx, a):
    msg = {"cmd": "choice", "pick": a.pick}
    if a.prompt_id:
        msg["prompt_id"] = a.prompt_id
    if a.index is not None:
        msg["index"] = a.index
    reply = ctx.expect_ok(ctx.send(msg))
    # the daemon's own words for picks it resolves locally (suggestion:
    # cards) — "" for a plain broker offer, which has nothing to say
    return ctx.emit({"pick": a.pick, "result": reply.get("result") or ""})


def _ask_args(p):
    p.add_argument("text", help="the question to ask, as one argument")


@command("ask", "Ask one typed question (starts a normal turn)",
         ['wispd ask "what is the front wheel for?"'],
         {"asked": "bool"}, args=_ask_args)
def ask(ctx, a):
    reply = ctx.expect_ok(ctx.send({"cmd": "ask", "text": a.text}))
    return ctx.emit({"asked": bool(reply.get("asked"))})


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
