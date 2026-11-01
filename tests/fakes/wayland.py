"""Fake Wayland compositor socket for the virtual-pointer client.

Speaks just enough of the wire protocol: wl_display.get_registry/sync,
wl_registry.bind, zwlr_virtual_pointer_manager_v1.create_virtual_pointer
and the virtual pointer's own requests. Every request is recorded as
``(object_name, request_name, args)`` in ``self.requests``.

``globals_`` lets a test hide an interface (a compositor without the
virtual-pointer manager); ``error_on`` makes the first matching request
answer with a wl_display.error.
"""
import os
import socket
import struct
import threading

from . import sockutil

GLOBALS = (("wl_seat", 7), ("zwlr_virtual_pointer_manager_v1", 2))

_VP = ("motion", "motion_absolute", "button", "axis", "frame",
       "axis_source", "axis_stop", "axis_discrete", "destroy")
_VP_FMT = {"motion": "=Iii", "motion_absolute": "=IIIII",
           "button": "=III", "axis": "=IIi", "frame": "=",
           "axis_source": "=I", "axis_stop": "=II",
           "axis_discrete": "=IIii", "destroy": "="}


def _str(s):
    b = s.encode() + b"\0"
    return struct.pack("=I", len(b)) + b + b"\0" * (-len(b) % 4)


def _msg(obj, op, args=b""):
    return struct.pack("=II", obj, ((8 + len(args)) << 16) | op) + args


class FakeWayland:
    def __init__(self, path, globals_=GLOBALS, error_on=None):
        self.path = str(path)
        self.globals_ = tuple(globals_)
        self.error_on = error_on
        self.requests = []
        self.connections = 0
        self._objs = {1: "wl_display"}
        self._srv = sockutil.bind_stream(self.path)
        self._srv.listen(4)
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._accept, daemon=True)

    def start(self):
        self._t.start()
        return self

    def stop(self):
        self._stop.set()
        c = socket.socket(socket.AF_UNIX)
        try:
            c.settimeout(1)
            c.connect(self.path)
        except OSError:
            pass
        finally:
            c.close()
        self._srv.close()
        self._t.join(2)
        if os.path.exists(self.path):
            os.unlink(self.path)

    def names(self):
        return [(o, r) for o, r, _a in self.requests]

    # -- server --------------------------------------------------------
    def _accept(self):
        while not self._stop.is_set():
            try:
                c, _ = self._srv.accept()
            except OSError:
                return
            if self._stop.is_set():
                c.close()
                return
            self.connections += 1
            threading.Thread(target=self._serve, args=(c,),
                             daemon=True).start()

    def _serve(self, c):
        objs = {1: "wl_display"}
        buf = b""
        try:
            while True:
                while len(buf) < 8:
                    d = c.recv(65536)
                    if not d:
                        return
                    buf += d
                obj, word = struct.unpack("=II", buf[:8])
                size, op = word >> 16, word & 0xFFFF
                while len(buf) < size:
                    d = c.recv(65536)
                    if not d:
                        return
                    buf += d
                body, buf = buf[8:size], buf[size:]
                if not self._handle(c, objs, obj, op, body):
                    return
        except OSError:
            return
        finally:
            c.close()

    def _handle(self, c, objs, obj, op, body):
        name = objs.get(obj, f"obj{obj}")
        if name == "wl_display" and op == 1:             # get_registry
            (rid,) = struct.unpack("=I", body)
            objs[rid] = "wl_registry"
            self.requests.append((name, "get_registry", (rid,)))
            for i, (iface, ver) in enumerate(self.globals_, start=1):
                c.sendall(_msg(rid, 0, struct.pack("=I", i)
                               + _str(iface) + struct.pack("=I", ver)))
        elif name == "wl_display" and op == 0:           # sync
            (cb,) = struct.unpack("=I", body)
            self.requests.append((name, "sync", (cb,)))
            c.sendall(_msg(cb, 0, struct.pack("=I", 0)))
        elif name == "wl_registry" and op == 0:          # bind
            gname, ln = struct.unpack_from("=II", body)
            iface = body[8:8 + ln - 1].decode()
            off = 8 + ((ln + 3) & ~3)
            ver, nid = struct.unpack_from("=II", body, off)
            objs[nid] = iface
            self.requests.append((name, "bind", (iface, ver, nid)))
        elif name == "zwlr_virtual_pointer_manager_v1" and op == 0:
            seat, nid = struct.unpack("=II", body)
            objs[nid] = "zwlr_virtual_pointer_v1"
            self.requests.append((name, "create_virtual_pointer",
                                  (objs.get(seat), nid)))
        elif name == "zwlr_virtual_pointer_v1":
            rname = _VP[op]
            args = struct.unpack(_VP_FMT[rname], body)
            self.requests.append((name, rname, args))
        else:
            self.requests.append((name, f"op{op}", ()))
        if self.error_on and self.requests[-1][:2] == self.error_on:
            msg = "fake protocol error"
            c.sendall(_msg(1, 0, struct.pack("=II", obj, 1)
                           + _str(msg)))
            return False
        return True
