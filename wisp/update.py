"""`wispd update`: fetch the latest tagged release, verify it, show what
would change, and install only on an explicit yes.

Never automatic: nothing in the daemon calls this. A download is checked
against the SHA-256 the release publishes (the asset digest GitHub
records, or a `SHA256SUMS` asset, or `--sha256`); a mismatch or a missing
digest aborts before anything is unpacked into the install. `--dry-run`
downloads into a temp dir, prints version, digest and the files that
would change, and deletes it again: nothing persistent is written.

It also never goes backwards. The release is compared with what is
installed (version numbers when the install is a release, otherwise the
installed commit against the release tag through GitHub's compare API);
a release that is older, the same, diverged from the install, or cannot be
compared is refused before anything is downloaded, unless `--force`.

An applied update is a transaction over the Wisp-managed files in the opt
dir (never config, keys, memories or other user data): they are copied to
`~/.local/state/wisp/update/<id>/` with a manifest before anything is
replaced, checked against the verified tree afterwards, and `--rollback`
restores them. That is a managed-file backup, not a filesystem snapshot:
the shell plugin, units, desktop entry, binds and any external state are
not rolled back.
"""
import hashlib
import json
import os
import pathlib
import shutil
import platform as _plat
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request

from . import config, deploy, preflight

REPO = "duketopceo/wisp"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
MAX_BYTES = 400 * 1024 * 1024
TRACKED_DIRS = ("wisp", "shells", "shell-plugin")
TRACKED_FILES = ("wispd",)
SHOW = 20


class UpdateError(Exception):
    """A user-facing reason the update stopped."""


def asset_name() -> str:
    m = _plat.machine().lower()
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64",
            "arm64": "aarch64"}.get(m)
    if not arch:
        raise UpdateError(f"No release is built for {m or 'this machine'}.")
    return f"wisp-linux-{arch}.tar.gz"


def _get(url: str, limit: int = MAX_BYTES, to=None) -> bytes | None:
    req = urllib.request.Request(
        url, headers={"User-Agent": "wispd-update",
                      "Accept": "application/vnd.github+json"})
    h = hashlib.sha256()
    buf = [] if to is None else None
    n = 0
    with urllib.request.urlopen(req, timeout=60) as r:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            n += len(chunk)
            if n > limit:
                raise UpdateError("The download is larger than the limit.")
            h.update(chunk)
            if to is None:
                buf.append(chunk)
            else:
                to.write(chunk)
    _get.last_sha = h.hexdigest()
    return b"".join(buf) if buf is not None else None


def fetch_json(url: str):
    return json.loads(_get(url, 4 * 1024 * 1024))


def fetch_file(url: str, dest) -> str:
    """Download `url` to `dest`; the SHA-256 of what was written."""
    if not url.startswith(DOWNLOAD_PREFIX):
        raise UpdateError("The release points outside its own repository.")
    with open(dest, "wb") as f:
        _get(url, to=f)
    return _get.last_sha


def fetch_text(url: str) -> str:
    if not url.startswith(DOWNLOAD_PREFIX):
        raise UpdateError("The release points outside its own repository.")
    return _get(url, 1024 * 1024).decode("utf-8", "replace")


def installed_version() -> str:
    d = deploy.read() or {}
    ref, commit = d.get("ref"), d.get("commit") or "unknown"
    if ref and re.match(r"^v?\d", str(ref)):
        return str(ref)
    return commit[:12] if commit != "unknown" else "unknown"


def installed_record() -> dict:
    return deploy.read() or {}


_VER = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(-[0-9A-Za-z.\-]+)?(\+.*)?$")


def parse_version(s) -> tuple | None:
    """(major, minor, patch, release-flag) of "v1.2.3"; a pre-release
    ("1.2.3-rc1") sorts below its release. None when `s` is no version."""
    m = _VER.match(str(s or "").strip())
    if not m:
        return None
    nums = tuple(int(g or 0) for g in m.groups()[:3])
    return nums + (0 if m.group(4) else 1,)


def ordering(tag: str, *, fetch_json=fetch_json, installed=None) -> str:
    """How the release `tag` stands against the install: "newer" (safe to
    install), "same", "older", "diverged" (the install has commits the
    release lacks and the release has others) or "unknown" (cannot tell)."""
    rec = installed if installed is not None else installed_record()
    have, want = parse_version(rec.get("ref")), parse_version(tag)
    if have and want:
        return "newer" if want > have else ("same" if want == have
                                            else "older")
    commit = str(rec.get("commit") or "")
    if not re.fullmatch(r"[0-9a-f]{7,40}", commit) or not want:
        return "unknown"
    try:
        cmp = fetch_json(f"https://api.github.com/repos/{REPO}/compare/"
                         f"{urllib.parse.quote(tag)}...{commit}")
        status = str(cmp.get("status") or "")
    except (OSError, ValueError, UpdateError, AttributeError):
        return "unknown"
    # compare is base...head: the install is the head
    return {"identical": "same", "ahead": "older", "behind": "newer",
            "diverged": "diverged"}.get(status, "unknown")


def refusal(tag: str, order: str, have: str) -> str:
    why = {"same": f"{tag} is already what is installed ({have}).",
           "older": f"{tag} is older than what is installed ({have}); "
                    "installing it would downgrade.",
           "diverged": f"{tag} and what is installed ({have}) have "
                       "diverged; installing it would drop local commits.",
           }.get(order, f"Cannot tell whether {tag} is newer than what is "
                        f"installed ({have}).")
    return why + " Nothing was installed. Pass --force to install it anyway."


def opt_dir() -> pathlib.Path:
    return config.HOME / ".local" / "opt" / "wisp"


def _digest_for(asset: dict, release: dict, name: str, fetch_text,
                override: str | None) -> tuple[str, str]:
    """(sha256 hex, where it came from)."""
    if override:
        d = override.strip().lower().removeprefix("sha256:")
        if not re.fullmatch(r"[0-9a-f]{64}", d):
            raise UpdateError("--sha256 must be 64 hex characters.")
        return d, "--sha256"
    dg = str(asset.get("digest") or "")
    if dg.lower().startswith("sha256:"):
        return dg[7:].lower(), "release asset digest"
    for a in release.get("assets", []):
        if a.get("name") in ("SHA256SUMS", "SHA256SUMS.txt"):
            for line in fetch_text(a["browser_download_url"]).splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[1].lstrip("*") == name:
                    return parts[0].lower(), a["name"]
    raise UpdateError(
        "This release publishes no SHA-256 for the download, so it cannot "
        "be verified. If you got the digest from a source you trust, pass "
        "--sha256 <hex>.")


def _hashes(base: pathlib.Path) -> dict:
    """{relative path: sha256} for the tracked files under `base`."""
    out = {}
    for d in TRACKED_DIRS:
        top = base / d
        for p in sorted(top.rglob("*")) if top.is_dir() else []:
            if p.is_file() and "__pycache__" not in p.parts \
                    and not p.is_symlink():
                out[str(p.relative_to(base))] = _sha(p)
    for f in TRACKED_FILES:
        p = base / f
        if p.is_file():
            out[f] = _sha(p)
    return out


def diff(new_root: pathlib.Path, installed: pathlib.Path) -> dict:
    new, old = _hashes(new_root), _hashes(installed)
    # shell-plugin is installed elsewhere on some setups: compare only
    # directories the install actually has
    tracked = {d for d in TRACKED_DIRS if (installed / d).is_dir()} \
        or set(TRACKED_DIRS)
    new = {k: v for k, v in new.items()
           if k in TRACKED_FILES or k.split("/")[0] in tracked}
    return {"added": sorted(k for k in new if k not in old),
            "changed": sorted(k for k in new if k in old and new[k] != old[k]),
            "removed": sorted(k for k in old if k not in new)}


def describe(res: dict) -> str:
    ch = res["changes"]
    lines = [f"latest release: {res['version']} ({res['asset']})",
             f"installed:      {res['installed_version']}",
             f"sha256:         {res['sha256']}  (verified, {res['digest_source']})",
             f"files:          {len(ch['added'])} added, "
             f"{len(ch['changed'])} changed, {len(ch['removed'])} removed"]
    for label, key, mark in (("added", "added", "+"),
                             ("changed", "changed", "~"),
                             ("removed", "removed", "-")):
        names = ch[key]
        for n in names[:SHOW]:
            lines.append(f"  {mark} {n}")
        if len(names) > SHOW:
            lines.append(f"  {mark} ... and {len(names) - SHOW} more {label}")
    if res.get("ordering", "newer") != "newer":
        lines.append("note: this release is not newer than what is "
                     f"installed ({res['ordering']}); `wispd update` "
                     "refuses it without --force.")
    return "\n".join(lines)


def _extract(tarball, dest: pathlib.Path) -> pathlib.Path:
    try:
        with tarfile.open(tarball) as tf:
            tf.extractall(dest, filter="data")
    except (tarfile.TarError, OSError) as e:
        raise UpdateError(f"The download is not a valid archive ({e}).")
    tops = [p for p in dest.iterdir() if p.is_dir()]
    if len(tops) != 1 or not (tops[0] / "wispd").is_file():
        raise UpdateError("The archive does not look like a Wisp release.")
    return tops[0]


def check(*, sha256: str | None = None, fetch_json=fetch_json,
          fetch_file=fetch_file, fetch_text=fetch_text, installed=None,
          workdir=None, refuse_older: bool = False) -> dict:
    """Download, verify and diff the latest release into `workdir`.
    Raises UpdateError before anything outside `workdir` is touched; with
    `refuse_older` a release that is not newer than the install is refused
    before the download."""
    release = fetch_json(API)
    tag = str(release.get("tag_name") or "")
    if not tag:
        raise UpdateError("The latest release has no tag.")
    order = ordering(tag, fetch_json=fetch_json)
    if refuse_older and order != "newer":
        raise UpdateError(refusal(tag, order, installed_version()))
    name = asset_name()
    asset = next((a for a in release.get("assets", [])
                  if a.get("name") == name), None)
    if not asset:
        raise UpdateError(f"Release {tag} has no {name}.")
    want, source = _digest_for(asset, release, name, fetch_text, sha256)
    tarball = pathlib.Path(workdir) / name
    got = fetch_file(asset["browser_download_url"], tarball)
    if got != want:
        tarball.unlink(missing_ok=True)
        raise UpdateError(
            f"Digest mismatch for {name}: the release says {want}, the "
            f"download is {got}. Nothing was installed.")
    root = _extract(tarball, pathlib.Path(workdir) / "tree")
    return {"version": tag, "asset": name, "sha256": got,
            "digest_source": source, "installed_version": installed_version(),
            "ordering": order,
            "changes": diff(root, installed or opt_dir()), "root": root}


def install(root: pathlib.Path, run=subprocess.run) -> int:
    """`wispd install` from the verified tree (the documented release
    install); it does not restart the daemon."""
    r = run([sys.executable, str(root / "wispd"), "install"], cwd=str(root))
    return r.returncode


# -- the transaction -----------------------------------------------------

OPT_DIRS = ("wisp", "shells")
OPT_FILES = ("wispd", "CHANGELOG.md", "build_harness.py", "deploy.json")
SCOPE_NOTE = ("Rollback covers the files under ~/.local/opt/wisp only: the "
              "shell plugin, systemd units, desktop entry and hotkey bind "
              "are not rolled back.")


def state_dir() -> pathlib.Path:
    return config.HOME / ".local" / "state" / "wisp" / "update"


def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _managed(base: pathlib.Path, *, staged: bool = False) -> dict:
    """{relative path: sha256} of the managed regular files under `base`.
    `staged` reads a release tree, where build_harness.py lives in
    scripts/ and there is no deploy.json. Symlinks and bytecode caches are
    never managed."""
    out = {}
    for d in OPT_DIRS:
        top = base / d
        for p in sorted(top.rglob("*")) if top.is_dir() \
                and not top.is_symlink() else []:
            if "__pycache__" in p.parts or p.is_symlink() \
                    or not p.is_file():
                continue
            out[str(p.relative_to(base))] = _sha(p)
    for f in OPT_FILES:
        if staged and f == "deploy.json":
            continue
        p = base / ("scripts/build_harness.py" if staged
                    and f == "build_harness.py" else f)
        if p.is_file() and not p.is_symlink():
            out[f] = _sha(p)
    return out


def _safe(opt: pathlib.Path, rel: str) -> pathlib.Path | None:
    """`opt/rel` when it is a relative path that stays inside `opt` with no
    symlink along the way; otherwise None."""
    r = pathlib.PurePosixPath(rel)
    if r.is_absolute() or ".." in r.parts or not r.parts:
        return None
    cur = opt
    for part in r.parts:
        cur = cur / part
        if cur.is_symlink():
            return None
    if cur.exists() and not cur.is_file():
        return None
    return cur


def _mkdir(p: pathlib.Path) -> None:
    p.mkdir(parents=True, exist_ok=True)
    os.chmod(p, 0o700)


def _write_private(p: pathlib.Path, data: bytes) -> None:
    _mkdir(p.parent)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, p)


def _save(man: dict, phase: str | None = None) -> None:
    if phase:
        man["phase"] = phase
    _write_private(pathlib.Path(man["dir"]) / "manifest.json",
                   (json.dumps(man, indent=1) + "\n").encode())


def protect(opt: pathlib.Path, root: pathlib.Path, frm: str, to: str,
            service_active: bool, state: pathlib.Path | None = None) -> dict:
    """Copy the managed files now in `opt` to the state dir and write the
    manifest (phase `staged`). Reads only managed paths."""
    state = state or state_dir()
    for part in (state.parent, state):
        _mkdir(part)
    uid = time.strftime("%Y%m%dT%H%M%S") + f"-{os.getpid()}"
    d = state / uid
    _mkdir(d)
    before = {}
    for rel in _managed(opt):
        src = _safe(opt, rel)
        if src is None or not src.is_file():
            continue
        data = src.read_bytes()
        before[rel] = hashlib.sha256(data).hexdigest()
        _write_private(d / "files" / rel, data)
    owned = _managed(root, staged=True)
    man = {"id": uid, "dir": str(d), "opt": str(opt), "from": frm,
           "to": to, "service_active": bool(service_active),
           "before": before, "owned": owned, "phase": "staged"}
    _save(man)
    return man


def _manifests(state: pathlib.Path) -> list:
    out = []
    for d in sorted(state.iterdir()) if state.is_dir() else []:
        try:
            m = json.loads((d / "manifest.json").read_text())
        except (OSError, ValueError):
            continue
        if isinstance(m, dict) and m.get("id") == d.name:
            m["dir"] = str(d)
            out.append(m)
    return out


# Phases where the managed files may be half way between two versions.
# `restored-partial` is settled: a rollback that only left files the user
# changed, which stay kept on every later run.
UNSETTLED = ("applying", "verify-failed", "restore-incomplete")


def unfinished(state: pathlib.Path | None = None) -> dict | None:
    """The newest manifest that is not in a settled phase."""
    ms = _manifests(state or state_dir())
    last = ms[-1] if ms else None
    return last if last and last["phase"] in UNSETTLED else None


def verify(man: dict, opt: pathlib.Path, tag: str) -> list:
    """Reasons the install does not match the verified tree; [] when it
    does. deploy.json is hashed after its tag write."""
    now = _managed(opt)
    bad = [f"{rel} differs from the release"
           for rel, h in man["owned"].items() if now.get(rel) != h]
    rec = deploy.read() or {}
    if rec.get("ref") != tag:
        bad.append(f"the recorded version is {rec.get('ref')!r}, "
                   f"not {tag}")
    return bad


def plan_rollback(man: dict, opt: pathlib.Path) -> dict:
    """{restore, remove, keep}: what a rollback would do. Outside an
    interrupted apply a file changed since the update is the user's and is
    kept; inside one, anything that is not the old content is leftover, and a
    path the update would have created is removed whatever it holds."""
    interrupted = man["phase"] in UNSETTLED
    kept = set(man.get("kept", []))
    restore, remove, keep = [], [], []
    for rel, was in sorted(man["before"].items()):
        p = _safe(opt, rel)
        if rel in kept:
            keep.append((rel, "kept by an earlier rollback"))
            continue
        if p is None:
            keep.append((rel, "not a plain file inside the install"))
            continue
        cur = _sha(p) if p.is_file() else None
        if cur == was:
            continue
        if interrupted or cur is None or cur == man["owned"].get(rel):
            restore.append(rel)
        else:
            keep.append((rel, "changed since the update"))
    for rel, mine in sorted(man["owned"].items()):
        if rel in man["before"]:
            continue
        p = _safe(opt, rel)
        if rel in kept:
            keep.append((rel, "kept by an earlier rollback"))
        elif p is None:
            keep.append((rel, "not a plain file inside the install"))
        elif p.is_file():
            if interrupted or _sha(p) == mine:
                remove.append(rel)
            else:
                keep.append((rel, "changed since the update"))
    return {"restore": restore, "remove": remove, "keep": keep}


def ipc_ok(opt: pathlib.Path, run=subprocess.run) -> bool:
    """Does the installed daemon answer? A fresh process, so no module of
    the replaced package is used."""
    try:
        r = run([sys.executable, str(opt / "wispd"), "status", "--quiet"],
                capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def _systemctl(verb: str, timeout: int, run) -> bool:
    try:
        return run(["systemctl", "--user", verb, "wispd"],
                   timeout=timeout).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def service_active(run=subprocess.run) -> bool:
    return _systemctl("is-active", 10, run)


def restart_service(run=subprocess.run) -> bool:
    return _systemctl("restart", 30, run)


def outside_changes(root: pathlib.Path, home=None) -> list:
    """Things this release changes that rollback does not cover."""
    home = home or config.HOME
    out = []
    plug = home / ".config" / "omarchy" / "plugins" \
        / "io.github.duketopceo.wisp"
    new = root / "shell-plugin"
    if new.is_dir() and plug.is_dir():
        mine = {str(p.relative_to(new)): _sha(p) for p in new.rglob("*")
                if p.is_file() and not p.is_symlink()}
        have = {str(p.relative_to(plug)): _sha(p) for p in plug.rglob("*")
                if p.is_file() and not p.is_symlink()}
        if mine != have:
            out.append("shell plugin")
    try:
        udir = home / ".config" / "systemd" / "user"
        for u in sorted((root / "scripts" / "units").glob("*.service")):
            f = udir / u.name
            if f.is_file() and f.read_text() != u.read_text():
                out.append(f"unit {u.name}")
    except OSError:
        pass
    return out


def _remember_kept(man: dict, plan: dict) -> None:
    """Files a rollback left alone stay left alone on every later run."""
    man["kept"] = sorted(set(man.get("kept", []))
                         | {rel for rel, _ in plan["keep"]})


def rollback(*, confirm=None, emit_text=print, restart: bool = False,
             state: pathlib.Path | None = None, opt: pathlib.Path | None = None,
             run=subprocess.run) -> dict:
    """Restore the newest update's managed files, on a yes. Idempotent: a
    restored update is reported and left alone."""
    state = state or state_dir()
    ms = _manifests(state)
    if not ms:
        raise UpdateError("There is no update to roll back.")
    man = ms[-1]
    opt = opt or pathlib.Path(man["opt"])
    res = {"rolled_back": False, "id": man["id"], "restored": [],
           "removed": [], "kept": [], "ipc_ok": None}
    if man["phase"] == "restored":
        emit_text(f"update {man['id']} was already rolled back.")
        return res
    plan = plan_rollback(man, opt)
    emit_text(f"rollback of the update {man['from']} -> {man['to']} "
              f"({man['phase']}):")
    for rel in plan["restore"]:
        emit_text(f"  restore {rel}")
    for rel in plan["remove"]:
        emit_text(f"  remove  {rel} (added by the update)")
    for rel, why in plan["keep"]:
        emit_text(f"  keep    {rel} ({why})")
    emit_text(SCOPE_NOTE)
    if not plan["restore"] and not plan["remove"]:
        emit_text("nothing to restore.")
        _remember_kept(man, plan)
        _save(man, "restored-partial" if plan["keep"] else "restored")
        res["kept"] = [k for k, _ in plan["keep"]]
        return res
    if confirm is None or not confirm(
            "Restore these files? Files listed as keep are not touched. "
            "[y/N] "):
        emit_text("not rolled back.")
        return res
    failed = []
    for rel in plan["restore"]:
        dst, src = _safe(opt, rel), pathlib.Path(man["dir"]) / "files" / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(f".{dst.name}.{os.getpid()}.tmp")
            shutil.copyfile(src, tmp)
            os.chmod(tmp, src.stat().st_mode & 0o755 | 0o600)
            os.replace(tmp, dst)
            res["restored"].append(rel)
        except OSError as e:
            failed.append((rel, str(e)))
    for rel in plan["remove"]:
        try:
            _safe(opt, rel).unlink()
            res["removed"].append(rel)
        except OSError as e:
            failed.append((rel, str(e)))
    res["kept"] = [k for k, _ in plan["keep"]] + [k for k, _ in failed]
    complete = not plan["keep"] and not failed
    _remember_kept(man, plan)
    _save(man, "restore-incomplete" if failed else
          "restored" if complete else "restored-partial")
    res["rolled_back"] = complete
    emit_text(f"restored {len(res['restored'])} file(s), removed "
              f"{len(res['removed'])}." if complete else
              "the restore is incomplete: "
              + ", ".join(res["kept"]) + " still need your attention. "
              "External state and your own data were not rolled back.")
    if man["service_active"] and restart:
        if confirm("Restart wispd on the restored files? [y/N] "):
            if restart_service(run):
                res["ipc_ok"] = ipc_ok(opt, run)
            emit_text("daemon answers after restart." if res["ipc_ok"]
                      else "the daemon did not answer after the restart; "
                      "see: journalctl --user -u wispd")
    elif man["service_active"]:
        emit_text("the daemon was running; restart it to use the restored "
                  "files: systemctl --user restart wispd")
    return res


def run_update(*, dry_run: bool, sha256: str | None = None, confirm=None,
               emit_text=print, force: bool = False, restart: bool = False,
               **seams) -> dict:
    """The whole flow; returns the result dict (`applied` says whether the
    install ran). `confirm(prompt) -> bool` must be an explicit user yes."""
    install_fn = seams.pop("install_fn", install)
    state = seams.pop("state", None)
    probe = seams.pop("preflight_fn", None) or (lambda: preflight.run(
        config.HOME, opt_dir()))
    active_fn = seams.pop("service_active", service_active)
    run = seams.pop("run", subprocess.run)
    rows = probe()
    if preflight.blockers(rows):
        raise UpdateError(preflight.refusal(rows))
    pending = unfinished(state)
    if pending and not dry_run:
        raise UpdateError(
            f"The update {pending['from']} -> {pending['to']} did not "
            "finish. Run `wispd update --rollback` to restore the previous "
            "files, then update again.")
    with tempfile.TemporaryDirectory(prefix="wispd-update-") as td:
        res = check(sha256=sha256, workdir=td,
                    refuse_older=not dry_run and not force, **seams)
        root = res.pop("root")
        res["dry_run"], res["applied"] = dry_run, False
        res["forced"] = bool(force and res["ordering"] != "newer")
        res["outside"] = outside_changes(root)
        n = sum(len(v) for v in res["changes"].values())
        emit_text(describe(res))
        problems = preflight.format_rows(rows, only_problems=True)
        if problems:
            emit_text("preflight:\n" + problems)
        if dry_run:
            emit_text("dry run: nothing was written.")
            return res
        if n == 0 and res["installed_version"] == res["version"]:
            emit_text("already up to date.")
            return res
        if confirm is None or not confirm(
                f"Install {res['version']}? This replaces the files above "
                "after saving a backup of them, and does not restart the "
                "daemon. [y/N] "):
            emit_text("not installed.")
            return res
        opt = opt_dir()
        man = protect(opt, root, res["installed_version"], res["version"],
                      active_fn(), state)
        res["backup"] = man["dir"]
        _save(man, "applying")
        rc = install_fn(root)
        if rc:
            raise UpdateError(
                f"The installer exited {rc}; the update is unfinished. "
                "Run `wispd update --rollback` to restore the previous "
                "files. " + SCOPE_NOTE)
        deploy.write(None, res["version"], None)
        man["owned"]["deploy.json"] = _sha(deploy.record_path())
        _save(man, "applied")
        bad = verify(man, opt, res["version"])
        if bad:
            _save(man, "verify-failed")   # rollback restores every file
            raise UpdateError(
                "The installed files do not match the verified release ("
                + "; ".join(bad[:5]) + "). The update is not verified. "
                "Run `wispd update --rollback` to restore the previous "
                "files. " + SCOPE_NOTE)
        _save(man, "verified")
        res["applied"], res["verified"] = True, True
        emit_text(f"installed {res['version']} and verified every file "
                  f"against the release. Backup: {man['dir']}")
        if res["outside"]:
            emit_text("note: this release also changed "
                      + ", ".join(res["outside"]) + "; " + SCOPE_NOTE)
        if restart:
            if man["service_active"] and confirm(
                    "Restart wispd now on the new version? [y/N] "):
                if not restart_service(run) or not ipc_ok(opt, run):
                    res["ipc_ok"] = False
                    raise UpdateError(
                        "The daemon did not answer after the restart. Run "
                        "`wispd update --rollback --restart` to restore the "
                        "previous files. " + SCOPE_NOTE)
                res["ipc_ok"] = True
                emit_text("daemon restarted and answering.")
            elif not man["service_active"]:
                emit_text("wispd was not running; nothing to restart.")
        else:
            emit_text("The daemon was not restarted. To use the new version: "
                      "systemctl --user restart wispd")
        return res


def tty_confirm(prompt: str) -> bool:
    if not (sys.stdin and sys.stdin.isatty()):
        raise UpdateError("Installing needs a terminal to ask you; "
                          "use --dry-run to preview.")
    sys.stderr.write(prompt)
    sys.stderr.flush()
    return sys.stdin.readline().strip().lower() in ("y", "yes")
