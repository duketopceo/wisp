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
"""
import hashlib
import json
import os
import pathlib
import platform as _plat
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request

from . import config, deploy

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
                out[str(p.relative_to(base))] = hashlib.sha256(
                    p.read_bytes()).hexdigest()
    for f in TRACKED_FILES:
        p = base / f
        if p.is_file():
            out[f] = hashlib.sha256(p.read_bytes()).hexdigest()
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
    lines.append("scope:          file diff covers the core install only; "
                 "the installer can also change the plugin, desktop files, "
                 "user units and hotkey binding.")
    lines.append("recovery:       no automatic rollback or post-install "
                 "health check is provided.")
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


def run_update(*, dry_run: bool, sha256: str | None = None, confirm=None,
               emit_text=print, force: bool = False, **seams) -> dict:
    """The whole flow; returns the result dict (`applied` says whether the
    install ran). `confirm(prompt) -> bool` must be an explicit user yes."""
    install_fn = seams.pop("install_fn", install)
    with tempfile.TemporaryDirectory(prefix="wispd-update-") as td:
        res = check(sha256=sha256, workdir=td,
                    refuse_older=not dry_run and not force, **seams)
        root = res.pop("root")
        res["dry_run"], res["applied"] = dry_run, False
        res["forced"] = bool(force and res["ordering"] != "newer")
        n = sum(len(v) for v in res["changes"].values())
        emit_text(describe(res))
        if dry_run:
            emit_text("dry run: nothing was written.")
            return res
        if n == 0 and res["installed_version"] == res["version"]:
            emit_text("already up to date.")
            return res
        if confirm is None or not confirm(
                f"Install {res['version']}? This replaces the files above "
                "and does not restart the daemon. [y/N] "):
            emit_text("not installed.")
            return res
        rc = install_fn(root)
        if rc:
            raise UpdateError(f"The installer exited {rc}; the previous "
                              "install is as it was left by that run.")
        res["applied"] = True
        emit_text(f"installed {res['version']}. Restart the daemon to use "
                  "it: systemctl --user restart wispd")
        return res


def tty_confirm(prompt: str) -> bool:
    if not (sys.stdin and sys.stdin.isatty()):
        raise UpdateError("Installing needs a terminal to ask you; "
                          "use --dry-run to preview.")
    sys.stderr.write(prompt)
    sys.stderr.flush()
    return sys.stdin.readline().strip().lower() in ("y", "yes")
