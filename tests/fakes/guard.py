"""LeakGuard: assert no fake leaks outside temp dirs / loopback.

The turn child already has ``NetworkGuard`` (outbound connects). This
guards the PARENT side where the fakes live: ``socket.bind`` is limited
to loopback TCP/UDP and AF_UNIX paths inside ``root``; anything else is
recorded in ``violations`` and raised. ``check_paths`` verifies a list
of files/dirs a fake created all resolve inside ``root``.
"""
import ipaddress
import os
import socket


class LeakViolation(OSError):
    pass


class LeakGuard:
    def __init__(self, root):
        self.root = os.path.realpath(str(root))
        self.violations: list = []
        self._orig = None

    def _inside(self, path) -> bool:
        p = os.path.realpath(os.fsdecode(path))
        return p == self.root or p.startswith(self.root + os.sep)

    def check_paths(self, paths) -> list:
        bad = [str(p) for p in paths if not self._inside(p)]
        self.violations.extend(f"path {b}" for b in bad)
        return bad

    def _fail(self, what: str):
        self.violations.append(what)
        raise LeakViolation(f"replay fake leaked: {what}")

    def install(self) -> None:
        guard, orig = self, socket.socket.bind
        self._orig = orig

        def bind(sock, address):
            if sock.family == socket.AF_UNIX:
                if isinstance(address, (bytes, bytearray)) and \
                        address[:1] == b"\0":
                    guard._fail(f"abstract unix socket {address!r}")
                if not guard._inside(address):
                    guard._fail(f"unix bind {os.fsdecode(address)}")
            elif sock.family in (socket.AF_INET, socket.AF_INET6):
                host = address[0]
                try:
                    ok = host not in ("", None) and \
                        ipaddress.ip_address(host).is_loopback
                except ValueError:
                    ok = host == "localhost"
                if not ok:
                    guard._fail(f"bind {host!r}")
            return orig(sock, address)

        socket.socket.bind = bind

    def uninstall(self) -> None:
        if self._orig is not None:
            socket.socket.bind = self._orig
            self._orig = None

    def __enter__(self):
        self.install()
        return self

    def __exit__(self, *exc):
        self.uninstall()
