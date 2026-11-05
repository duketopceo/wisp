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


def text_stdin(text: str):
    """`text` as an unlinked temp file (0600), rewound, to hand a child
    as its stdin. Private text goes to a child this way because its argv
    is readable by other local accounts while it runs. A file, not a
    pipe, so a child that never reads cannot block the caller. The caller
    closes it after the child starts."""
    import tempfile
    f = tempfile.TemporaryFile()
    f.write(text.encode("utf-8"))
    f.seek(0)
    return f


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


def apply(roots=None) -> int:
    """The one setup every recording path runs before it captures audio:
    umask 077 so new files are born private, the data and config folders
    created 0700 when missing, and everything an older version wrote
    tightened. The daemon and the no-daemon trigger fallback both call
    it, so neither can record into a traversable folder or create a
    world-readable `utterance.wav`. Returns how many entries `harden`
    changed."""
    os.umask(0o077)
    for root in (roots if roots is not None
                 else [config.DATA_DIR, config.CFG_DIR]):
        if root:
            pathlib.Path(root).mkdir(parents=True, exist_ok=True,
                                     mode=DIR_MODE)
    return harden(roots)
