"""Minimal Chrome DevTools Protocol client — stdlib only, no deps.

Clicklab DOM mode needs exactly one primitive: Runtime.evaluate on a
page target inside a remote/sandboxed chromium (e.g. a CubeVM guest).
This module speaks just enough CDP over a raw websocket to do that —
Target.createTarget/attachToTarget(flatten) + Runtime.evaluate — plus
navigate/reload for page resets.

ws framing: client frames are masked per RFC6455; server frames arrive
unmasked. Messages can arrive fragmented; we reassemble on opcode 0
continuation until FIN.
"""
import base64
import json
import os
import socket
import struct
import urllib.request

TIMEOUT = 30


class CdpError(Exception):
    pass


def _ws_open(url: str, timeout: float = TIMEOUT) -> socket.socket:
    """ws://host:port/path handshake → connected socket."""
    rest = url.split("://", 1)[1]
    authority, _, path = rest.partition("/")
    host, _, port = authority.partition(":")
    port = int(port or 80)
    sock = socket.create_connection((host, port), timeout=timeout)
    key = base64.b64encode(os.urandom(16)).decode()
    req = (f"GET /{path} HTTP/1.1\r\nHost: {authority}\r\n"
           "Upgrade: websocket\r\nConnection: Upgrade\r\n"
           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
    sock.sendall(req.encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise CdpError("ws handshake: closed")
        buf += chunk
    status = buf.split(b"\r\n", 1)[0]
    if b"101" not in status:
        raise CdpError(f"ws handshake failed: {status!r}")
    return sock


def _ws_send(sock: socket.socket, payload: str) -> None:
    data = payload.encode()
    mask = os.urandom(4)
    header = bytearray([0x81])                     # FIN + text
    ln = len(data)
    if ln < 126:
        header.append(0x80 | ln)
    elif ln < 65536:
        header += bytes([0x80 | 126]) + struct.pack(">H", ln)
    else:
        header += bytes([0x80 | 127]) + struct.pack(">Q", ln)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    sock.sendall(bytes(header) + mask + masked)


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        c = sock.recv(n - len(buf))
        if not c:
            raise CdpError("ws closed mid-frame")
        buf += c
    return buf


def _ws_recv(sock: socket.socket) -> bytes:
    """One complete message (reassembly across continuation frames)."""
    out = b""
    while True:
        b1, b2 = _recv_exact(sock, 2)
        fin, op = b1 & 0x80, b1 & 0x0F
        ln = b2 & 0x7F
        if ln == 126:
            ln = struct.unpack(">H", _recv_exact(sock, 2))[0]
        elif ln == 127:
            ln = struct.unpack(">Q", _recv_exact(sock, 8))[0]
        if b2 & 0x80:
            mask = _recv_exact(sock, 4)
            data = bytes(b ^ mask[i % 4]
                         for i, b in enumerate(_recv_exact(sock, ln)))
        else:
            data = _recv_exact(sock, ln)
        if op == 9:                                # ping → pong
            hdr = bytearray([0x8A])
            m2 = os.urandom(4)
            hdr.append(0x80 | len(data))
            sock.sendall(bytes(hdr) + m2 +
                         bytes(b ^ m2[i % 4] for i, b in enumerate(data)))
            continue
        if op in (0, 1, 2):
            out += data
            if fin:
                return out
        if op == 8:
            raise CdpError("ws close frame")


class Page:
    """One attached page target; calls go through flat sessions."""

    def __init__(self, ws_url: str):
        self.sock = _ws_open(ws_url)
        self._id = 0
        self.session = None

    # holds a live socket — deepcopy shares the page instead
    def __deepcopy__(self, memo):
        return self

    __copy__ = __deepcopy__

    def _rpc(self, method: str, params: dict | None = None,
             session: bool = True) -> dict:
        self._id += 1
        rid = self._id
        msg = {"id": rid, "method": method, "params": params or {}}
        if session and self.session:
            msg["sessionId"] = self.session
        _ws_send(self.sock, json.dumps(msg))
        while True:
            r = json.loads(_ws_recv(self.sock))
            if r.get("id") != rid:
                continue                          # async events
            if "error" in r:
                raise CdpError(f"{method}: {r['error']}")
            return r.get("result", {})

    def open(self, url: str) -> "Page":
        t = self._rpc("Target.createTarget", {"url": "about:blank"},
                      session=False)
        self.target_id = t["targetId"]
        a = self._rpc("Target.attachToTarget",
                      {"targetId": self.target_id, "flatten": True},
                      session=False)
        self.session = a["sessionId"]
        self._rpc("Page.enable")
        self._rpc("Runtime.enable")
        self._rpc("Page.navigate", {"url": url})
        return self

    def evaluate(self, code: str, timeout: float = TIMEOUT) -> str:
        r = self._eval_raw(code)
        # bare `return` is illegal at top level — retry wrapped in an
        # IIFE like the neo evaluate endpoint does
        if "Illegal return" in json.dumps(
                r.get("exceptionDetails", {})):
            r = self._eval_raw(f"(function(){{{code}\n}})()")
        res = r.get("result", {})
        if r.get("exceptionDetails"):
            return "EVAL_ERR " + json.dumps(
                r["exceptionDetails"].get("text", ""))[:200]
        return json.dumps(res.get("value"))[:8000] \
            if res.get("type") != "string" else res.get("value", "")

    def _eval_raw(self, code: str) -> dict:
        return self._rpc("Runtime.evaluate",
                         {"expression": code, "returnByValue": True,
                          "awaitPromise": True})

    def close(self):
        try:
            tid = getattr(self, "target_id", None)
            if tid:
                self._rpc("Target.closeTarget", {"targetId": tid},
                          session=False)
            self.sock.close()
        except Exception:
            pass


def targets(host: str, port: int = 9222) -> list:
    r = urllib.request.urlopen(f"http://{host}:{port}/json/version",
                               timeout=5)
    return json.loads(r.read())


def open_page(host: str, url: str, port: int = 9222) -> Page:
    """Connect to the browser-level ws, spawn+attach a page, navigate."""
    ver = targets(host, port)
    ws = ver["webSocketDebuggerUrl"]
    return Page(ws).open(url)
