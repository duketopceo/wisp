"""ACP permission policy (plan U6, KTD6): one deterministic answer per
tool call an agent asks permission for.

  classify(tool_call, cwd, out_dir, autonomy, edited) -> allow|ask|refuse

Refuse is checked first and wins in every mode: SHELL_DENYLIST,
credential paths, the secret-tool/omaseal binaries, login flows and
Wisp's state dir outside out_dir. Then `always_ask` asks for everything,
`guided` asks for edits too. Allow is the narrow set in KTD6: reads
inside cwd, edits inside cwd/out_dir, and a fixed list of simple
build/test/read commands. Everything the matcher can't parse, and
anything unknown, is ask — never allow. Once the session has edited a
file that build or test commands execute, those commands become ask
(SessionPolicy.note_edit).

Callers select only allow_once/reject_once options from the result.
"""
import os
import re
import shlex

from . import config, policy, tools

# files build/test commands execute: editing one demotes the allow-listed
# build commands to ask for the rest of the session
_BUILD_NAMES = {"conftest.py", "package.json", "makefile", "pyproject.toml",
                "setup.py", "setup.cfg", "tox.ini", "noxfile.py",
                "opencode.json"}
_BUILD_PARTS = (".git/hooks/", ".opencode/")
# edited at all -> ask (agent config that loads on the next launch)
_CONFIG_NAMES = {"opencode.json"}

_CRED = re.compile(
    r"auth\.json|(^|[/\s'\"=])\.env\b|\.ori(/|$|\s|'|\")"
    r"|\.local/share/keyrings", re.I)
_BINARIES = {"secret-tool", "omaseal"}
_LOGIN = {"login", "signin", "logout"}
_UNPARSEABLE = ("|", ";", "&", "`", "$(", ">", "<", "\n", "${")

# commands that only read; paths stay inside cwd/out_dir
_READ_CMDS = {"ls", "cat", "head", "tail", "wc", "grep", "rg", "pwd",
              "tree", "stat", "file", "diff", "which", "echo"}
_GIT_READ = {"status", "diff", "log", "show", "blame", "branch"}
# build/test commands: (argv0, optional required subcommand set)
_BUILD_CMDS = {
    "pytest": None, "ruff": {"check"}, "mypy": None, "flake8": None,
    "tsc": None, "eslint": None, "pyflakes": None,
    "make": {"test", "build", "check", "lint", "all"},
    "npm": {"test", "t"}, "pnpm": {"test"}, "yarn": {"test"},
    "cargo": {"build", "test", "check", "clippy"},
    "go": {"build", "test", "vet"},
}
_PY = {"python", "python3"}
_PY_MODS = {"pytest", "unittest", "py_compile", "compileall"}
_NPM_RUN = {"test", "build", "lint", "check"}


def _under(path: str, root: str | None) -> bool:
    if not root:
        return False
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


def _norm(p: str, cwd: str) -> str:
    return os.path.realpath(os.path.join(cwd, os.path.expanduser(p)))


def _paths(tc: dict, raw: dict) -> list[str]:
    out = [str(loc["path"]) for loc in tc.get("locations") or []
           if isinstance(loc, dict) and isinstance(loc.get("path"), str)]
    for k in ("filePath", "path", "file_path", "filepath"):
        if isinstance(raw.get(k), str):
            out.append(raw[k])
    return out


def _is_build_file(path: str) -> bool:
    low = path.replace(os.sep, "/").lower()
    base = low.rsplit("/", 1)[-1]
    return (base in _BUILD_NAMES or base.endswith(".sh")
            or any(p in low + "/" if p.endswith("/") else p in low
                   for p in _BUILD_PARTS))


def _is_config(path: str) -> bool:
    low = path.replace(os.sep, "/").lower()
    return (low.rsplit("/", 1)[-1] in _CONFIG_NAMES
            or "/.opencode/" in low or "/.git/" in low)


def _is_build_cmd(argv: list[str]) -> bool:
    if not argv:
        return False
    a0, rest = os.path.basename(argv[0]), argv[1:]
    if a0 in _PY:
        return len(rest) >= 2 and rest[0] == "-m" and rest[1] in _PY_MODS
    if a0 not in _BUILD_CMDS:
        return False
    subs = _BUILD_CMDS[a0]
    if subs is None:
        return True
    sub = rest[0] if rest else ""
    if a0 in ("npm", "pnpm", "yarn") and sub == "run":
        return len(rest) > 1 and rest[1] in _NPM_RUN
    return sub in subs or (a0 == "make" and not rest)


def _refused(text: str, argv: list[str], paths: list[str], cwd: str,
             out_dir: str | None) -> bool:
    if tools.denied(text) or _CRED.search(text):
        return True
    if any(os.path.basename(a) in _BINARIES for a in argv):
        return True
    if any(a in _LOGIN for a in argv):
        return True
    for p in paths:
        if _CRED.search(p):
            return True
        n = _norm(p, cwd)
        for d in (config.DATA_DIR, config.CFG_DIR, config.RUN_DIR):
            if _under(n, str(d)) and not _under(n, out_dir):
                return True
    return False


def _command(raw: dict) -> str | None:
    c = raw.get("command")
    if isinstance(c, list) and all(isinstance(x, str) for x in c):
        return shlex.join(c)
    return c if isinstance(c, str) else None


def _shell_class(cmd: str, cwd: str, out_dir: str | None,
                 build_dirty: bool) -> str:
    if any(t in cmd for t in _UNPARSEABLE):
        return "ask"
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return "ask"
    if not argv or argv[0] == "sudo":
        return "ask"
    for a in argv[1:]:
        if not a.startswith("-") and ("/" in a or a.startswith("~")
                                      or ".." in a):
            n = _norm(a, cwd)
            if not (_under(n, cwd) or _under(n, out_dir)):
                return "ask"
    a0 = os.path.basename(argv[0])
    if a0 in _READ_CMDS:
        return "allow"
    if a0 == "git" and len(argv) > 1 and argv[1] in _GIT_READ \
            and "-D" not in argv and "-d" not in argv:
        return "allow"
    if a0 == "find" and not {"-exec", "-delete", "-execdir"} & set(argv):
        return "allow"
    if _is_build_cmd(argv):
        return "ask" if build_dirty else "allow"
    return "ask"


def classify(tool_call, cwd: str, out_dir: str | None,
             autonomy: str = "autonomous", edited=()) -> str:
    """allow | ask | refuse for one ACP tool_call. Fails closed to ask."""
    try:
        return _classify(tool_call, cwd, out_dir, autonomy, edited)
    except Exception:
        return "ask"


def _classify(tc, cwd, out_dir, autonomy, edited) -> str:
    if not isinstance(tc, dict):
        return "ask"
    mode = policy.mode_of({"agent": {"autonomy": autonomy}})
    cwd = os.path.realpath(cwd)
    out_dir = os.path.realpath(out_dir) if out_dir else None
    raw = tc.get("rawInput")
    malformed = raw is not None and not isinstance(raw, dict)
    raw = raw if isinstance(raw, dict) else {}
    kind = tc.get("kind")
    cmd = _command(raw)
    title = tc.get("title") if isinstance(tc.get("title"), str) else ""
    paths = _paths(tc, raw)
    text = " ".join([cmd or title] + paths)
    try:
        argv = shlex.split(cmd) if cmd else []
    except ValueError:
        argv = (cmd or "").split()
    if _refused(text, argv, paths, cwd, out_dir):
        return "refuse"
    if mode == "always_ask" or malformed:
        return "ask"
    dirty = any(_is_build_file(p) for p in edited)

    if kind in ("read", "search"):
        return _path_class(paths, cwd, out_dir)
    if kind in ("edit", "delete", "move"):
        r = _path_class(paths, cwd, out_dir)
        if r == "allow" and mode == "guided":
            return "ask"
        if r == "allow" and any(_is_config(p) for p in paths):
            return "ask"
        return r
    if kind == "execute":
        return _shell_class(cmd, cwd, out_dir, dirty) if cmd else "ask"
    if kind == "think":
        return "allow"
    return "ask"


def _path_class(paths, cwd, out_dir) -> str:
    if not paths:
        return "ask"
    for p in paths:
        n = _norm(p, cwd)
        if not (_under(n, cwd) or _under(n, out_dir)):
            return "ask"
        rel = os.path.relpath(n, cwd if _under(n, cwd) else out_dir)
        if any(part.startswith(".") and part not in (".", "..")
               for part in rel.split(os.sep)):
            return "ask"
    return "allow"


class SessionPolicy:
    """Per-session policy state: cwd, out_dir, autonomy and the paths the
    session has edited (the KTD6 edited-build-files rule)."""

    def __init__(self, cwd: str, out_dir: str | None = None,
                 autonomy: str = "autonomous"):
        self.cwd = cwd
        self.out_dir = out_dir
        self.autonomy = autonomy
        self.edited: set[str] = set()

    @classmethod
    def from_cfg(cls, cfg: dict | None, cwd: str,
                 out_dir: str | None = None) -> "SessionPolicy":
        return cls(cwd, out_dir, policy.mode_of(cfg))

    def classify(self, tool_call) -> str:
        return classify(tool_call, self.cwd, self.out_dir, self.autonomy,
                        self.edited)

    def note_edit(self, tool_call) -> None:
        """Record the paths of an allowed/approved edit-class call."""
        if not isinstance(tool_call, dict):
            return
        raw = tool_call.get("rawInput")
        raw = raw if isinstance(raw, dict) else {}
        for p in _paths(tool_call, raw):
            self.edited.add(_norm(p, os.path.realpath(self.cwd)))
