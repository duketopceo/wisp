"""Deploy record and git-ref export for `wispd install`.

`install_files` writes `~/.local/opt/wisp/deploy.json` (source repo, ref,
commit, time); `wispd status` reads it back. `export_ref` unpacks a ref of
a source repo into a temp dir with `git archive`, so the repo's working
tree and index are never touched.
"""
import io
import json
import pathlib
import subprocess
import tarfile
import time

from . import config


def record_path() -> pathlib.Path:
    return config.HOME / ".local" / "opt" / "wisp" / "deploy.json"


def read() -> dict | None:
    """The recorded deploy, or None when absent or unreadable."""
    try:
        rec = json.loads(record_path().read_text())
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) else None


def summary() -> dict:
    return read() or {"commit": "unknown"}


def write(repo, ref, commit) -> None:
    rec = {"repo": str(repo) if repo else None, "ref": ref,
           "commit": commit or "unknown",
           "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    p = record_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, indent=1) + "\n")


def _git(repo, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, timeout=60)


def head_commit(repo) -> str | None:
    """HEAD of a checkout, or None when `repo` is not a git checkout."""
    try:
        r = _git(repo, "rev-parse", "--verify", "HEAD")
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.decode().strip() if r.returncode == 0 else None


def export_ref(repo, ref, dest) -> str:
    """Unpack `ref` of `repo` into `dest`; return its full commit hash.
    Raises ValueError with a user-facing message on any failure."""
    try:
        r = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ValueError(f"git did not run ({e})")
    if r.returncode:
        raise ValueError(f"{ref!r} is not a commit in {repo}")
    commit = r.stdout.decode().strip()
    try:
        a = _git(repo, "archive", "--format=tar", commit)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ValueError(f"git archive did not run ({e})")
    if a.returncode:
        raise ValueError(f"git archive failed for {ref!r}: "
                         f"{a.stderr.decode().strip()}")
    with tarfile.open(fileobj=io.BytesIO(a.stdout)) as tf:
        tf.extractall(dest, filter="data")
    return commit
