"""Private by default: what Wisp records about you is for you alone.

Transcripts, replies, traces and decisions live under `~/.local/share/wisp`
and the settings under `~/.config/wisp`. Both folders are 0700 and the
files in them 0600, so another local account cannot read them even when the
home folder is traversable. New files are created that way (the daemon runs
with umask 077 and the unit sets `UMask=0077`), and `harden()` fixes
anything an older version wrote.
"""
import os
import pathlib

from . import config

DIR_MODE = 0o700
FILE_MODE = 0o600


def open_append(path, mode: int = FILE_MODE):
    """Open `path` for appending text, creating it 0600 and its parent
    folder 0700 (an existing folder keeps its mode)."""
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
    fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, mode)
    return os.fdopen(fd, "a")


def open_write(path, mode: int = FILE_MODE):
    """Open `path` for writing text (truncating), created 0600."""
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    return os.fdopen(fd, "w")


def _fix(path: pathlib.Path, mode: int) -> bool:
    try:
        if path.is_symlink():
            return False
        cur = path.stat().st_mode & 0o777
        if cur & ~mode & 0o777:
            path.chmod(cur & mode)
            return True
    except OSError:
        pass
    return False


def harden(roots=None) -> int:
    """Tighten the data and config folders and everything in them.
    Returns how many entries were changed."""
    roots = roots if roots is not None else [
        config.DATA_DIR, config.CFG_DIR]
    n = 0
    for root in roots:
        if not root:
            continue
        root = pathlib.Path(root)
        if not root.is_dir() or root.is_symlink():
            continue
        n += _fix(root, DIR_MODE)
        for dirpath, dirs, files in os.walk(root, followlinks=False):
            for d in dirs:
                n += _fix(pathlib.Path(dirpath) / d, DIR_MODE)
            for f in files:
                n += _fix(pathlib.Path(dirpath) / f, FILE_MODE)
    return n
