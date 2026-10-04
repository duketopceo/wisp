"""Command registry and argparse tree for `wispd <group> <verb>`.

Each command is declared once (`@command(...)`): a path such as
"cua status", a one-line summary, examples, a JSON data schema and an
argument builder. The registry builds the argparse tree, the help text,
the shell completions and the alias checks from that single table.

Exit codes: 0 ok, 1 failure, 2 usage, 3 daemon not running, 4 unhealthy
dependency. Errors print `E_CODE: sentence` plus a `Try:` line on stderr
(or an error envelope on stdout under --json).
"""
import argparse
import dataclasses
import json
import os
import socket
import sys

from . import output, strings

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_DOWN, EXIT_UNHEALTHY = 0, 1, 2, 3, 4

GROUPS = {}      # group name -> one-line summary (set by command modules)
_COMMANDS = {}   # "cua status" -> Command


class CliError(Exception):
    def __init__(self, code: str, message: str | None = None,
                 hint: str | None = None, data=None):
        base_msg, base_hint = strings.ERRORS.get(
            code, strings.ERRORS["E_FAILED"])
        self.code = code
        self.message = message or base_msg
        self.hint = hint or base_hint
        self.data = data
        if code == "E_USAGE":
            self.exit = EXIT_USAGE
        elif code == "E_DAEMON_DOWN":
            self.exit = EXIT_DOWN
        elif code in strings.DEPENDENCY_CODES:
            self.exit = EXIT_UNHEALTHY
        else:
            self.exit = EXIT_FAIL
        super().__init__(f"{code}: {self.message}")


def from_wisp_code(code: str, message: str | None = None) -> CliError:
    """Map a typed wisp error code (errors_codes.CODES) or an IPC error
    string to a CliError."""
    key = "E_" + str(code or "failed").upper()
    if key not in strings.ERRORS:
        return CliError("E_FAILED", message or f"The daemon said: {code}.")
    return CliError(key, message)


@dataclasses.dataclass
class Flags:
    json: bool = False
    quiet: bool = False
    no_color: bool = False


def extract_globals(argv):
    """Pull --json/--quiet/--no-color out of argv wherever they appear
    (before the verb or after it). Tokens after `--` are left alone."""
    flags, rest = Flags(), []
    for i, a in enumerate(argv):
        if a == "--":
            rest.extend(argv[i:])
            break
        if a == "--json":
            flags.json = True
        elif a in ("--quiet", "-q"):
            flags.quiet = True
        elif a == "--no-color":
            flags.no_color = True
        else:
            rest.append(a)
    return rest, flags


@dataclasses.dataclass
class Command:
    path: str
    summary: str
    examples: list
    handler: object
    schema: dict
    args: object = None        # callable(parser) adding arguments
    stream: bool = False       # NDJSON / interactive: no JSON envelope

    def __post_init__(self):
        if not self.summary or "\n" in self.summary:
            raise ValueError(f"{self.path}: one-line summary required")
        if not self.examples:
            raise ValueError(f"{self.path}: at least one example required")


def command(path, summary, examples, schema=None, args=None,
            stream=False):
    def deco(fn):
        _COMMANDS[path] = Command(path, summary, list(examples), fn,
                                  schema or {}, args, stream)
        return fn
    return deco


def commands() -> dict:
    from . import load_groups
    load_groups()
    return dict(_COMMANDS)


# -- parser ---------------------------------------------------------------

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        import re
        m = re.search(r"invalid choice: '([^']*)'", message)
        if m:
            message = f"unknown {'verb' if ' ' in self.prog else 'command'}" \
                      f" '{m.group(1)}'"
        msg = message[0].upper() + message[1:]
        if not msg.endswith("."):
            msg += "."
        prog = self.prog
        hint = prog + " --help"
        raise CliError("E_USAGE", msg, hint)

    def exit(self, status=0, message=None):
        if status:
            raise CliError("E_USAGE", (message or "").strip() or None)
        raise SystemExit(0)


def _fmt(prog):
    return argparse.RawDescriptionHelpFormatter(prog, max_help_position=28,
                                                width=None)


def _globals_help(p):
    g = p.add_argument_group("global options")
    g.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                   help="machine-readable output (one JSON object)")
    g.add_argument("--quiet", "-q", action="store_true",
                   default=argparse.SUPPRESS,
                   help="print nothing on success")
    g.add_argument("--no-color", action="store_true",
                   default=argparse.SUPPRESS,
                   help="plain output (also NO_COLOR, or not a tty)")


def _epilog(c: Command) -> str:
    return "Examples:\n" + "\n".join(f"  {e}" for e in c.examples)


def _leaf(sub, name, cmd: Command):
    p = sub.add_parser(name, help=cmd.summary, description=cmd.summary,
                       epilog=_epilog(cmd), formatter_class=_fmt,
                       prog=f"wispd {cmd.path}")
    if cmd.args:
        cmd.args(p)
    _globals_help(p)
    p.set_defaults(_cmd=cmd.path)
    return p


def build_parser():
    cmds = commands()
    top = _Parser(prog="wispd", add_help=True, formatter_class=_fmt,
                  description="Wisp voice assistant control.")
    top.format_help = lambda: top_help(cmds)
    sub = top.add_subparsers(dest="_group", metavar="<command>",
                             parser_class=_Parser)
    nodes = {}
    for path, cmd in sorted(cmds.items()):
        parts = path.split(" ")
        if len(parts) == 1:
            nodes[path] = _leaf(sub, parts[0], cmd)
            continue
        group = parts[0]
        gp = nodes.get(group)
        if gp is None:
            gp = sub.add_parser(
                group, help=GROUPS.get(group, group),
                description=GROUPS.get(group, group), formatter_class=_fmt,
                prog=f"wispd {group}")
            _globals_help(gp)
            nodes[group] = gp
        if not hasattr(gp, "_verbs"):
            gp._verbs = gp.add_subparsers(dest="_verb", metavar="<verb>",
                                          parser_class=_Parser)
            # a group that is also a command (`health`) runs bare
            gp._verbs.required = group not in cmds
        _leaf(gp._verbs, parts[1], cmd)
    return top


# Top-level help sections: (title, names). A name is a group or a
# single command; its summary comes from the registry.
SECTIONS = []


def top_help(cmds) -> str:
    def summary(name):
        if name in GROUPS:
            return GROUPS[name]
        return cmds[name].summary

    lines = ["usage: wispd [--json] [--quiet] [--no-color] <command> "
             "[<verb>] [args]", "",
             "Wisp voice assistant control. `wispd <command> --help` shows "
             "verbs and examples.", ""]
    for title, names in SECTIONS:
        lines.append(title + ":")
        for n in names:
            lines.append(f"  {n:<13}{summary(n)}")
        lines.append("")
    lines += ["Global options:",
              "  --json       machine-readable output (one JSON object)",
              "  --quiet      print nothing on success",
              "  --no-color   plain output (also NO_COLOR, or not a tty)",
              "",
              "Exit codes: 0 ok, 1 failure, 2 usage, 3 daemon not "
              "running, 4 unhealthy dependency.",
              "Old command names (tasks, task_status, models, ...) still "
              "work for one release."]
    return "\n".join(lines) + "\n"


def parse(argv):
    """argv (globals already removed) -> (Command, Namespace)."""
    ns = build_parser().parse_args(argv)
    path = getattr(ns, "_cmd", None)
    if path is None:
        group = getattr(ns, "_group", None)
        if group is None:
            raise CliError("E_USAGE", "A command is required.", "wispd --help")
        raise CliError("E_USAGE", f"A verb is required for {group}.",
                       f"wispd {group} --help")
    return _COMMANDS[path], ns


# -- context --------------------------------------------------------------

class Ctx:
    """What a handler sees: parsed flags, output helpers, the daemon."""

    def __init__(self, flags: Flags, host=None, legacy: bool = False,
                 command: str = ""):
        self.flags = flags
        self._host = host
        self.legacy = legacy
        self.command = command
        self._cfg = None

    @property
    def host(self):
        """The wispd script module (daemon, install, trigger)."""
        if self._host is None:
            import importlib.machinery
            import importlib.util
            import pathlib
            path = str(pathlib.Path(__file__).resolve().parents[2]
                       / "wispd")
            loader = importlib.machinery.SourceFileLoader("wispd_host",
                                                          path)
            spec = importlib.util.spec_from_loader("wispd_host", loader)
            mod = importlib.util.module_from_spec(spec)
            loader.exec_module(mod)
            self._host = mod
        return self._host

    @property
    def cfg(self) -> dict:
        if self._cfg is None:
            from .. import config
            self._cfg = config.load_config()
        return self._cfg

    def reload_cfg(self):
        self._cfg = None

    @property
    def json(self) -> bool:
        return self.flags.json

    @property
    def color(self) -> bool:
        return output.use_color(self.flags.no_color)

    def emit(self, data, text: str | None = None) -> int:
        """Success output: the JSON envelope, or `text` (unless --quiet)."""
        if self.flags.json:
            print(json.dumps({"ok": True, "command": self.command,
                              "data": data}, ensure_ascii=False))
        elif text is not None and not self.flags.quiet:
            print(text)
        return EXIT_OK

    def table(self, headers, rows, tones=None, header=True) -> str:
        return output.table(headers, rows, tones, self.color, self.cfg,
                            header)

    def send(self, msg: dict, timeout=None) -> dict:
        """One IPC command. Daemon absent -> E_DAEMON_DOWN (exit 3)."""
        from .. import ipc
        try:
            reply = ipc.send(msg) if timeout is None \
                else ipc.send(msg, timeout=timeout)
        except (socket.timeout, TimeoutError):
            raise CliError("E_TIMEOUT")
        except (ConnectionError, OSError):
            raise CliError("E_DAEMON_DOWN")
        return reply

    def expect_ok(self, reply: dict) -> dict:
        if isinstance(reply, dict) and reply.get("ok") is False:
            raise from_wisp_code(reply.get("error"))
        return reply


# -- execution ------------------------------------------------------------

def render_error(err: CliError, flags: Flags, command: str, out, errf):
    if flags.json:
        body = {"ok": False, "command": command,
                "error": {"code": err.code, "message": err.message,
                          "try": err.hint}}
        if err.data is not None:
            body["data"] = err.data
        print(json.dumps(body, ensure_ascii=False), file=out)
    else:
        print(f"{err.code}: {err.message}\nTry: {err.hint}", file=errf)


def run(argv, flags: Flags, host=None, legacy: bool = False) -> int:
    cmd = None
    try:
        cmd, ns = parse(argv)
        ctx = Ctx(flags, host, legacy, cmd.path)
        rc = cmd.handler(ctx, ns)
        return EXIT_OK if rc is None else rc
    except CliError as e:
        render_error(e, flags, cmd.path if cmd else "", sys.stdout,
                     sys.stderr)
        return e.exit
    except SystemExit as e:  # argparse --help
        return e.code if isinstance(e.code, int) else EXIT_OK
    except BrokenPipeError:
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass
        return EXIT_OK
    except KeyboardInterrupt:
        return 130
