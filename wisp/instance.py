"""One wispd at a time (B29).

The daemon takes an exclusive lock on `wispd.lock`, next to its socket,
before it touches the socket, the state file or any speaker. A second
start finds the lock held, says which pid holds it and exits with
EXIT_RUNNING, without unlinking or rebinding the first daemon's socket
(a second daemon that stole it would answer every key press twice).

The lock is an flock, so the kernel drops it when the holder dies: there
is no stale lock to clean up after a crash or a reboot.
"""
import fcntl
import os

from . import config

EXIT_RUNNING = 78            # systemd: RestartPreventExitStatus in the unit
_HELD = None                 # the open lock file; closing it releases


class AlreadyRunning(Exception):
    def __init__(self, pid: int | None):
        self.pid = pid
        super().__init__(
            f"wispd is already running (pid {pid})" if pid
            else "wispd is already running")


def lock_path():
    return config.RUN_DIR / "wispd.lock"


def holder(path=None) -> int | None:
    """The pid recorded by the daemon that holds the lock, if any."""
    try:
        with open(path or lock_path()) as f:
            return int(f.read().strip() or 0) or None
    except (OSError, ValueError):
        return None


def acquire(path=None) -> None:
    """Take the lock for this process or raise AlreadyRunning."""
    global _HELD
    p = path or lock_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        pid = holder(p)
        os.close(fd)
        raise AlreadyRunning(pid) from None
    os.ftruncate(fd, 0)
    os.write(fd, f"{os.getpid()}\n".encode())
    _HELD = fd


def release() -> None:
    global _HELD
    if _HELD is not None:
        try:
            os.close(_HELD)
        except OSError:
            pass
        _HELD = None
