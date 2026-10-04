"""Launcher entry, desktop actions and icon-theme install (plan W27).

`assets/desktop/wisp.desktop` is a template: `@WISPD@` and `@SHELL_EXEC@`
are filled in with the installed paths, quoted per the Desktop Entry
spec. `install` is idempotent, backs up a file the user edited, never
writes in dry-run, and refreshes the desktop/icon caches only when the
tools exist. Stdlib only.
"""
import hashlib
import pathlib
import shutil
import subprocess

_MARK = "# wispd-managed sha256="
_RESERVED = set(' \t\n"\'\\><~|&;$*?#()`')


def exec_arg(s: str) -> str:
    """One Exec argument, quoted per the Desktop Entry spec (the quote
    escape and the string-level backslash doubling both applied)."""
    s = s.replace("%", "%%")
    if not any(c in _RESERVED for c in s):
        return s
    out = []
    for c in s:
        if c in '"`$\\':
            out.append("\\\\" + c)  # \c, then \ doubled for the string layer
        else:
            out.append(c)
    return '"' + "".join(out) + '"'


def template(src: pathlib.Path) -> str:
    return (src / "assets" / "desktop" / "wisp.desktop").read_text()


def stamp(body: str) -> str:
    return _MARK + hashlib.sha256(body.encode()).hexdigest() + "\n" + body


def _managed_pristine(text: str) -> bool:
    """True when `text` is an untouched file this installer wrote."""
    head, _, body = text.partition("\n")
    return (head.startswith(_MARK)
            and head[len(_MARK):] == hashlib.sha256(body.encode()).hexdigest())


def render(opt: pathlib.Path, src: pathlib.Path = None) -> str:
    src = src or pathlib.Path(__file__).resolve().parent.parent
    body = (template(src)
            .replace("@WISPD@", exec_arg(str(opt / "wispd")))
            .replace("@SHELL_EXEC@",
                     "quickshell -n -p " + exec_arg(str(opt / "shells" / "debug"))))
    return stamp(body)


def _backup_name(p: pathlib.Path) -> pathlib.Path:
    b = p.with_name(p.name + ".bak")
    n = 0
    while b.exists():
        n += 1
        b = p.with_name(f"{p.name}.bak.{n}")
    return b


def install(src: pathlib.Path, home: pathlib.Path, opt: pathlib.Path,
            dry_run: bool = False, runner=None) -> dict:
    """Install the desktop file and hicolor icons under `home`.

    `runner` provides `which(name)` and `run(cmd, **kw)` (default: shutil,
    subprocess). Returns {"written", "backups", "dry_run", "skipped"}."""
    which = runner.which if runner else shutil.which
    run = runner.run if runner else subprocess.run
    written, backups = [], []
    apps = home / ".local" / "share" / "applications"
    icons_dst = home / ".local" / "share" / "icons" / "hicolor"
    entry = apps / "wisp.desktop"
    text = render(opt, src)
    cur = entry.read_text() if entry.is_file() else None
    if cur != text:
        if cur is not None and not _managed_pristine(cur):
            b = _backup_name(entry)
            backups.append(str(b))
            if not dry_run:
                b.write_text(cur)
        written.append(str(entry))
        if not dry_run:
            apps.mkdir(parents=True, exist_ok=True)
            entry.write_text(text)
    icons_src = src / "assets" / "icons" / "hicolor"
    changed_icons = False
    if icons_src.is_dir():
        for f in sorted(icons_src.rglob("*")):
            if not f.is_file():
                continue
            dst = icons_dst / f.relative_to(icons_src)
            if dst.is_file() and dst.read_bytes() == f.read_bytes():
                continue
            written.append(str(dst))
            changed_icons = True
            if not dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, dst)
    skipped = []
    if not dry_run:
        for tool, cmd, needed in (
                ("update-desktop-database", [str(apps)], str(entry) in written),
                ("gtk-update-icon-cache", ["-q", "-t", "-f", str(icons_dst)],
                 changed_icons)):
            if not needed:
                continue
            exe = which(tool)
            if not exe:
                skipped.append(tool)
                continue
            try:
                run([exe] + cmd, capture_output=True, timeout=30)
            except (OSError, subprocess.SubprocessError):
                skipped.append(tool)
    return {"written": written, "backups": backups, "dry_run": dry_run,
            "skipped": skipped}


def sni_host_present(run=subprocess.run, which=shutil.which) -> bool:
    """Read-only: is a StatusNotifier host/watcher on the session bus?"""
    if not which("busctl"):
        return False
    try:
        r = run(["busctl", "--user", "list", "--no-pager"],
                capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return "org.kde.StatusNotifierWatcher" in (r.stdout or "")
