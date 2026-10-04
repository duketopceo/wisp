"""Short temp dirs for tests that bind AF_UNIX sockets.

sun_path is ~104 bytes on macOS (108 on Linux) and macOS's $TMPDIR is
already ~50 (`/var/folders/xx/<28 chars>/T/`), so a socket nested a few
directories under a default tempdir fails with "AF_UNIX path too long".
Anchor on /tmp when it exists. Sockets created under these dirs must
still keep their own suffix short (the longest here is
`~/.cache/cua-driver/cua-driver.sock`, 35 chars).
"""
import os
import tempfile

_BASE = "/tmp" if os.name == "posix" and os.path.isdir("/tmp") else None


def mkdtemp(prefix: str = "w-") -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=_BASE)


def TemporaryDirectory(prefix: str = "w-") -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory(prefix=prefix, dir=_BASE)
