"""Newline-delimited JSON IPC: daemon server + client.

The daemon accepts one JSON object per connection and replies with one
JSON object. Commands: listen, status, choice, stop, task_status,
task_cancel. Widgets and the trigger shim are plain clients.

Transport per OS (mirrors rs/dimd/src/ipc.rs):
  linux/macos → AF_UNIX socket at SOCK_FILE
  windows     → 127.0.0.1 TCP; the ephemeral port is written to
                SOCK_FILE (a plain file) for client discovery. Same
                protocol — fixture replay is identical.
"""
import json
import socket
import threading

from . import config
from . import platform as _plat

_TIMEOUT = 10
_TCP = _plat.current() == "windows"


class Daemon:
    """IPC server. `handler(cmd_dict) -> dict` supplies the responses."""

    def __init__(self, handler, sock_file=config.SOCK_FILE):
        self._handler = handler
        self._sock_file = sock_file
        self._server = None
        self._thread = None
        self._running = False

    def start(self) -> None:
        self._sock_file.parent.mkdir(parents=True, exist_ok=True)
        if self._sock_file.exists():
            self._sock_file.unlink()
        if _TCP:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.bind(("127.0.0.1", 0))
            srv.listen(8)
            srv.settimeout(0.5)
            self._sock_file.write_text(str(srv.getsockname()[1]))
        else:
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(str(self._sock_file))
            srv.listen(8)
            srv.settimeout(0.5)
        self._server = srv
        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._server:
            try:
                self._server.close()
            except OSError:
                pass
        try:
            self._sock_file.unlink(missing_ok=True)
        except OSError:
            pass

    def _accept_loop(self) -> None:
        while self._running:
            try:
                conn, _ = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(_TIMEOUT)
            data = b""
            while not data.endswith(b"\n"):
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
            try:
                cmd = json.loads(data.decode().strip() or "{}")
            except json.JSONDecodeError:
                resp = {"ok": False, "error": "malformed json"}
            else:
                try:
                    resp = self._handler(cmd)
                except Exception as e:
                    resp = {"ok": False, "error": str(e)}
            conn.sendall(json.dumps(resp).encode() + b"\n")
        except (OSError, socket.timeout):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass


def send(cmd: dict, sock_file=config.SOCK_FILE, timeout: float = _TIMEOUT) -> dict:
    """Send one command to the daemon; returns its reply dict.

    Raises ConnectionError when the socket is absent/refused."""
    if _TCP:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            port = int(sock_file.read_text().strip())
            s.connect(("127.0.0.1", port))
        except Exception:
            s.close()
            raise ConnectionError("no daemon (port file absent)")
    else:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
    try:
        if not _TCP:
            s.connect(str(sock_file))
        s.sendall(json.dumps(cmd).encode() + b"\n")
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    finally:
        s.close()
    if not data:
        raise ConnectionError("daemon closed connection without a reply")
    return json.loads(data.decode())


def alive(sock_file=config.SOCK_FILE) -> bool:
    try:
        send({"cmd": "status"}, sock_file=sock_file, timeout=2)
        return True
    except (OSError, ConnectionError):
        return False
