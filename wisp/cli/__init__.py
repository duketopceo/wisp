"""wispd command line: `wispd <group> <verb>`, registry-driven.

`wispd` (the script) stays the daemon entry and passes itself in as
`host`, so handlers can reach run_daemon, install_files and friends
without importing the script by path.
"""
import sys

from . import registry, strings, output  # noqa: F401
from .registry import CliError, Flags, extract_globals  # noqa: F401

_LOADED = False


def load_groups():
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    from . import (agents, batchcmd, core, cua, diagnose,  # noqa: F401
                   learning, settings)
    registry.SECTIONS[:] = [
        ("Daemon", ["daemon", "status", "stop", "interrupt", "trigger",
                    "watch", "choice", "tui"]),
        ("Diagnose", ["doctor", "health", "latency", "spend", "binds",
                      "onboard", "trace"]),
        ("Pointer and notifications", ["cua", "notify"]),
        ("Agents and memory", ["task", "memory", "suggest", "label",
                               "context"]),
        ("Learning", ["train", "review", "learn", "skills", "recipes",
                      "eval", "batch"]),
        ("Settings", ["config", "theme", "connect", "sync", "inventory",
                      "completion"]),
    ]


def _verbs(group):
    return {p.split(" ", 1)[1] for p in registry.commands()
            if p.startswith(group + " ")}


def _grp(group, default, bare=None):
    """Legacy `wispd <group> [args]`: a known verb passes through, bare
    runs `bare`, anything else is the old implicit verb `default`."""
    def fn(rest):
        if not rest:
            return [group, bare or default]
        if rest[0] in _verbs(group) or rest[0] in ("-h", "--help"):
            return [group] + rest
        return [group, default] + rest
    return fn


def _to(*tokens):
    return lambda rest: list(tokens) + rest


def _theme(rest):
    if not rest:
        return ["theme", "show"]
    if rest[0] in _verbs("theme") or rest[0] in ("-h", "--help"):
        return ["theme"] + rest
    if rest[0] == "--check":
        return ["theme", "check"] + rest[1:]
    if rest[0] == "--css":
        return ["theme", "css"] + rest[1:]
    return ["theme", "set"] + rest


def _connect(rest):
    if not rest or rest[0] == "--list":
        return ["connect", "list"] + rest[1:]
    if rest[0] in _verbs("connect") or rest[0] in ("-h", "--help"):
        return ["connect"] + rest
    return ["connect", "add"] + rest


# Pre-W19 command names, kept for one release. Value: rest-of-argv ->
# canonical argv. Names that are also canonical (status, doctor, ...)
# need no entry.
ALIASES = {
    "daemon": _grp("daemon", "run"),
    "install": _to("daemon", "install"),
    "harness": _to("daemon", "harness"),
    "subscribe": _to("watch"),
    "label": _grp("label", "set", "report"),
    "tasks": _to("task", "list"),
    "task_status": _to("task", "status"),
    "task_cancel": _to("task", "cancel"),
    "agent": _to("task", "run"),
    "memory": _grp("memory", "edit"),
    "memory-write": _to("memory", "write"),
    "suggestions": _to("suggest", "list"),
    "fails": _to("learn", "fails"),
    "learn": _grp("learn", "weekly"),
    "tele": _to("trace", "digest"),
    "trace": _grp("trace", "show"),
    "train": _grp("train", "stats"),
    "review": _grp("review", "list"),
    "skills": _grp("skills", "list"),
    "recipes": _grp("recipes", "draft"),
    "config": _grp("config", "show"),
    "theme": _theme,
    "connect": _connect,
    "models": _to("health"),
}
# Aliases whose old output shape differs from the new command's.
LEGACY_RENDER = frozenset({"models", "connect"})


def main(argv=None, host=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    rest, flags = extract_globals(argv)
    if not rest:
        rest = ["status"]
    first = rest[0]
    legacy = first in LEGACY_RENDER
    if first in ALIASES:
        rest = ALIASES[first](rest[1:])
    return registry.run(rest, flags, host, legacy)


from . import completion  # noqa: E402,F401
